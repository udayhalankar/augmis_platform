"""Offline tests for coordinated release lifecycle. Never touches live Docker/DB."""
import sys
import types
from dataclasses import dataclass
from unittest.mock import Mock
from fastapi import HTTPException
from services.api.app.services import runtime_upgrade_executor as m

@dataclass
class Obj:
    id: str
    version: str = ''
    application_id: str = 'app'
    status: str = 'running'
    publication_status: str = 'published'
    image_ref: str = 'sha256:abc'
    version_policy: str = 'same_major'
    pinned_version_id: object = None
    baseline_version_id: str = 'old'
    tenant_id: str = 'tenant'
    active_version_id: str = 'old'
    instance_key: str = 'lab'
    name: str = 'lab'
    container_name: str = 'old-container'
    health_status: str = ''
    deployed_at: object = None
    error_message: object = None
    created_at: object = None
    container_id: str = ''
    host_port: int = 0
    runtime_url: str = ''
    build_id: str = 'build'
    manifest: object = None

class DB:
    def __init__(self):
        self.instance=Obj('inst')
        self.old=Obj('old',version='1.0.1',status='image_ready')
        self.target=Obj('new',version='1.0.2',status='image_ready')
        self.sub=Obj('sub')
        self.build=Obj('build', status='ready',image_ref='test-image')
        self.deploy=Obj('dep', status='running')
        self.calls=[]
        self.items={'old':self.old, 'new':self.target, 'build':self.build}
        self.added=[]
    def scalar(self, statement):
        i=len(self.calls);self.calls.append('scalar')
        return [self.instance,self.build,self.deploy,None][i]
    def get(self, cls, ident): return self.items.get(ident)
    def add(self,obj): self.added.append(obj)
    def commit(self): self.calls.append('commit')
    def refresh(self,obj): return None

# Need distinguish DB.scalar calls count from commit calls.
def fake_db():
    db=DB()
    def scalar(_):
        count=sum(x=='scalar' for x in db.calls);db.calls.append('scalar')
        return [db.instance,db.build,db.deploy,None][count]
    db.scalar=scalar
    return db

def setup(monkeypatch):
    db=fake_db()
    called=[]
    monkeypatch.setattr(m,'require_active_subscription',lambda **kw:db.sub)
    monkeypatch.setattr(m,'require_active_entitlement',lambda **kw:None)
    monkeypatch.setattr(m,'require_subscription_version_allowed',lambda **kw:None)
    monkeypatch.setattr(m,'start_scoped_container',lambda **kw:called.append('start') or {
        'container_id':'new-cid','container_name':'new-container', 'host_port':9999,
        'runtime_url':'http://internal'})
    monkeypatch.setattr(m,'stop_container',lambda *args:called.append('stop'))
    monkeypatch.setattr(m,'archive_before_removal',lambda *args:None)
    monkeypatch.setattr(m,'record_audit_event',lambda *args, **kwargs:None)
    fake = types.ModuleType('services.api.app.services.c1d2_automatic_qualification')
    fake.QualificationGateError=type('QualificationGateError',(ValueError,),{})
    fake.require_passing_build=lambda _db, **kw:called.append('qualification')
    monkeypatch.setitem(sys.modules,'services.api.app.services.c1d2_automatic_qualification',fake)
    return db,called,fake

def invoke(db):
    return m.perform_instance_upgrade(db=db,instance_id='inst',target_version_id='new',
        actor_user_id='operator',sync_subscription_baseline=True)

def test_success_advances_active_and_baseline_together(monkeypatch):
    db,calls,_=setup(monkeypatch)
    response=invoke(db)
    assert response['status']=='UPGRADED'
    assert db.instance.active_version_id=='new'
    assert db.sub.baseline_version_id=='new'
    assert calls==['qualification','start','stop']

def test_unqualified_build_denied_before_start(monkeypatch):
    db,calls,fake=setup(monkeypatch)
    class Gate(ValueError):
        code='QUALIFICATION_REQUIRED'
    fake.QualificationGateError=Gate
    def reject(_db, **kw): raise Gate()
    fake.require_passing_build=reject
    try:invoke(db)
    except HTTPException as e: assert e.status_code==409 and e.detail=='QUALIFICATION_REQUIRED'
    else:assert False
    assert not calls and db.sub.baseline_version_id=='old' and db.instance.active_version_id=='old'

def test_unpublished_release_denied_before_start(monkeypatch):
    db,calls,_=setup(monkeypatch)
    db.target.publication_status='draft'
    try:invoke(db)
    except HTTPException as e: assert e.status_code==409 and e.detail=='C1D3_TARGET_NOT_PUBLISHED'
    else:assert False
    assert not calls

def test_pinned_subscription_denied(monkeypatch):
    db,calls,_=setup(monkeypatch)
    db.sub.pinned_version_id='old'
    try:invoke(db)
    except HTTPException as e: assert e.detail=='C1D3_RELEASE_POLICY_NOT_SUPPORTED'
    else:assert False
    assert not calls

def test_downgrade_baseline_denied(monkeypatch):
    db,calls,_=setup(monkeypatch)
    db.sub.baseline_version_id='baseline'
    db.items['baseline']=Obj('baseline',version='1.0.3')
    try:invoke(db)
    except HTTPException as e: assert e.detail=='C1D3_BASELINE_DOWNGRADE_DENIED'
    else:assert False
    assert not calls


def test_failed_candidate_preserves_active_version_and_baseline(monkeypatch):
    db,calls,_=setup(monkeypatch)
    def failure(**kw):
        calls.append('start')
        raise m.DeploymentError('SIMULATED_HEALTH_FAILURE')
    monkeypatch.setattr(m,'start_scoped_container',failure)
    monkeypatch.setattr(m,'archive_failed_start',lambda *args:None)
    try: invoke(db)
    except HTTPException as e: assert e.status_code==422
    else: assert False
    assert db.sub.baseline_version_id=='old'
    assert db.instance.active_version_id=='old'
    assert db.instance.status=='running'
    assert calls==['qualification','start']


def test_original_upgrade_contract_has_no_forced_baseline_promotion():
    import inspect
    assert inspect.signature(m.perform_instance_upgrade).parameters['sync_subscription_baseline'].default is False
