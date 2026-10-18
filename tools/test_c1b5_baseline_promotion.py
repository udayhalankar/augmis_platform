"""Offline C1-B5 guard tests; no Control Plane DB, Docker, or live API calls."""
from types import SimpleNamespace
import uuid
import pytest
from fastapi import HTTPException
import ast
from pathlib import Path
from sqlalchemy import select
from services.api.app.services.version_policy_service import (require_subscription_version_allowed,parse_version,is_version_technically_ready,VersionPolicyError)
from services.api.app.services.authorization_service import AuthorizationError
from services.api.app.schemas.subscription import SubscriptionPromoteBaselineRequest
from services.api.app.models.commerce import TenantSubscription, ApplicationOffer
from services.api.app.models.platform import Tenant, ApplicationVersion, ApplicationBuild

def _load_reviewed_route_logic():
    path = Path(__file__).resolve().parents[1] / 'services/api/app/routes/subscriptions.py'
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    route = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'promote_subscription_baseline')
    # Offline review loads only the new endpoint to avoid importing startup/auth dependencies.
    route.decorator_list=[]
    code = compile(ast.fix_missing_locations(ast.Module(body=[route], type_ignores=[])),str(path),'exec')
    ns = dict(uuid=uuid,select=select,Session=object,User=object,Depends=lambda _=None:None,
              get_db=None,get_current_user=None, SubscriptionPromoteBaselineRequest=SubscriptionPromoteBaselineRequest,
              TenantSubscription=TenantSubscription,ApplicationOffer=ApplicationOffer,Tenant=Tenant,ApplicationVersion=ApplicationVersion,
              HTTPException=HTTPException, AuthorizationError=AuthorizationError,
              require_tenant_permission=lambda **kw:None,acquire_instance_limit_lock=lambda **kw:None,
              record_audit_event=lambda *args,**kw:None,
              require_subscription_version_allowed=require_subscription_version_allowed,
              parse_version=parse_version, is_version_technically_ready=is_version_technically_ready,
              VersionPolicyError=VersionPolicyError)
    exec(code,ns)
    return SimpleNamespace(promote_subscription_baseline=ns['promote_subscription_baseline'],route_ast=route)
api=_load_reviewed_route_logic()
from services.api.app.schemas.subscription import SubscriptionPromoteBaselineRequest
from services.api.app.models.commerce import TenantSubscription, ApplicationOffer
from services.api.app.models.platform import Tenant, ApplicationVersion, ApplicationBuild

APP=uuid.uuid4(); TENANT=uuid.uuid4(); SUBID=uuid.uuid4(); OFFERID=uuid.uuid4(); OLD=uuid.uuid4(); TARGET=uuid.uuid4()

class FakeDB:
    def __init__(self):
        self.subscription=SimpleNamespace(id=SUBID,tenant_id=TENANT,offer_id=OFFERID,status="active",baseline_version_id=OLD,version_policy="same_major",pinned_version_id=None,auto_upgrade=False)
        self.offer=SimpleNamespace(id=OFFERID,application_id=APP)
        self.tenant=SimpleNamespace(id=TENANT,status="active")
        self.versions={OLD:SimpleNamespace(id=OLD,application_id=APP,version="1.0.0",publication_status="retired",status="image_ready",build_type="dockerfile"),
                       TARGET:SimpleNamespace(id=TARGET,application_id=APP,version="1.2.0",publication_status="published",status="image_ready",build_type="dockerfile")}
        self.commits=0
        self.build=SimpleNamespace(id=uuid.uuid4(), status="ready", image_ref="trusted:test")
    def scalar(self, stmt):
        ent=stmt.column_descriptions[0]["entity"]
        if ent is TenantSubscription: return self.subscription
        if ent is ApplicationBuild: return self.build
        raise AssertionError(ent)
    def get(self, ent, ident):
        if ent is ApplicationOffer and ident==OFFERID: return self.offer
        if ent is Tenant and ident==TENANT: return self.tenant
        if ent is ApplicationVersion: return self.versions.get(ident)
        return None
    def commit(self): self.commits+=1

@pytest.fixture
def setup(monkeypatch):
    db=FakeDB(); perms=[]; audits=[]; locks=[]
    monkeypatch.setitem(api.promote_subscription_baseline.__globals__,"require_tenant_permission",lambda **kw:perms.append(kw["permission_code"]))
    monkeypatch.setitem(api.promote_subscription_baseline.__globals__,"record_audit_event",lambda *args,**kwargs: audits.append(kwargs))
    monkeypatch.setitem(api.promote_subscription_baseline.__globals__,"acquire_instance_limit_lock",lambda **kwargs: locks.append(kwargs))
    return db,perms,audits,locks

def run(db, target=TARGET):
    return api.promote_subscription_baseline(SUBID, SubscriptionPromoteBaselineRequest(target_version_id=target), db=db, current_user=SimpleNamespace(id=uuid.uuid4()))

def test_success_preserves_subscription_commerce(setup):
    db,perms,audits,locks=setup
    result=run(db)
    assert result["status"]=="PROMOTED" and result["version"]=="1.2.0"
    assert db.subscription.baseline_version_id==TARGET and db.commits==1
    assert db.subscription.offer_id==OFFERID and db.subscription.version_policy=="same_major" and db.subscription.auto_upgrade is False
    assert perms==["subscription.manage","application.deploy"]
    assert len(audits)==1 and len(locks)==1

def test_idempotent_no_second_commit(setup):
    db,_,audits,_=setup; db.subscription.baseline_version_id=TARGET
    result=run(db)
    assert result["status"]=="UNCHANGED" and db.commits==0 and not audits

def test_unpublished_target_rejected(setup):
    db,_,_,_=setup; db.versions[TARGET].publication_status="draft"
    with pytest.raises(HTTPException) as exc: run(db)
    assert exc.value.status_code==409 and db.commits==0

def test_cross_application_rejected(setup):
    db,_,_,_=setup; db.versions[TARGET].application_id=uuid.uuid4()
    with pytest.raises(HTTPException) as exc: run(db)
    assert exc.value.status_code==404 and db.commits==0

def test_major_change_denied(setup):
    db,_,_,_=setup; db.versions[TARGET].version="2.0.0"
    with pytest.raises(HTTPException) as exc: run(db)
    assert exc.value.status_code==409 and db.commits==0

def test_downgrade_denied(setup):
    db,_,_,_=setup; db.versions[OLD].version="1.3.0"
    with pytest.raises(HTTPException) as exc: run(db)
    assert exc.value.status_code==409 and db.commits==0

def test_pinned_subscription_denied(setup):
    db,_,_,_=setup; db.subscription.version_policy="pinned"; db.subscription.pinned_version_id=OLD
    with pytest.raises(HTTPException) as exc: run(db)
    assert exc.value.status_code==409 and db.commits==0

def test_no_ready_build_denied(setup):
    db,_,_,_=setup; db.build=None
    with pytest.raises(HTTPException) as exc: run(db)
    assert exc.value.status_code==409 and db.commits==0

def test_missing_permission_denied(setup,monkeypatch):
    db,_,_,_=setup
    from services.api.app.services.authorization_service import AuthorizationError
    monkeypatch.setitem(api.promote_subscription_baseline.__globals__,"require_tenant_permission",lambda **_: (_ for _ in ()).throw(AuthorizationError("denied")))
    with pytest.raises(HTTPException) as exc: run(db)
    assert exc.value.status_code==403 and db.commits==0

def test_inactive_subscription_denied(setup):
    db,_,_,_=setup; db.subscription.status="cancelled"
    with pytest.raises(HTTPException) as exc: run(db)
    assert exc.value.status_code==409 and db.commits==0

def test_route_registered():
    source=(Path(__file__).resolve().parents[1] / 'services/api/app/routes/subscriptions.py').read_text()
    assert '@router.post("/subscriptions/{subscription_id}/promote-baseline")' in source
