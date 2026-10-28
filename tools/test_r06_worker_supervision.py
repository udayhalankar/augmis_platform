"""R06 local safety checks (no Docker/DB/Redis required)."""
from __future__ import annotations
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

SRC = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('r06_supervised_worker', SRC/'tools/r06_supervised_worker.py')
r06 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r06)


@pytest.mark.parametrize('role', list(r06.R06_LOCK_IDS))
def test_all_roles_require_explicit_mode(role):
    with pytest.raises(SystemExit):
        r06.parser().parse_args(['--role', role])
    args = r06.parser().parse_args(['--role',role,'--once'])
    if role == 'reconciliation':
        with pytest.raises(ValueError, match='TENANT_REQUIRED'):
            r06.validate_args(args)
    else:
        r06.validate_args(args)


@pytest.mark.parametrize('flags,code', [
    (['--role','qualification','--watch','--quarantine-stale'], 'REVIEW_OPERATIONS_REQUIRE_ONCE'),
    (['--role','qualification','--once','--apply-reconciliation'], 'RECONCILIATION_OPTIONS_INVALID'),
    (['--role','auto-upgrade','--once','--quarantine-stale'], 'QUALIFICATION_OPTIONS_INVALID'),
    (['--role','qualification','--once','--plan-upgrades'], 'UPGRADE_OPTIONS_INVALID'),
    (['--role','qualification','--once','--interval','2'], 'WORKER_OPTIONS_INVALID'),
    (['--role','qualification','--once','--stale-after','60'], 'STALE_WINDOW_INVALID'),
])
def test_invalid_or_implicit_mutations_rejected(flags,code):
    with pytest.raises(ValueError,match=code):
        r06.validate_args(r06.parser().parse_args(flags))


def test_lock_ids_are_stable_unique():
    assert len(set(r06.R06_LOCK_IDS.values())) == len(r06.R06_LOCK_IDS)
    assert all(type(i) is int and i > 0 for i in r06.R06_LOCK_IDS.values())


def test_qualification_review_preserves_pending_smoke_gate():
    text = (SRC/'services/api/app/services/c1d2_automatic_qualification.py').read_text()
    assert "ApplicationBuildQualification.status == 'pending_smoke'" in text
    assert "ApplicationBuildQualification.started_at.is_not(None)" in text
    assert "row.status = 'needs_review'" in text
    assert "row.failure_code = 'R06_INTERRUPTED_QUALIFICATION_REVIEW_REQUIRED'" in text
    assert "record_audit_event(db, action='application.qualification.interrupted'" in text
    assert "row.status = 'passed'" not in text


def test_expired_upgrade_claim_emits_atomic_audit():
    text = (SRC/'services/api/app/services/runtime_automation_service.py').read_text()
    assert '"LEASE_EXPIRED_REVIEW_REQUIRED"' in text
    assert 'resource_type="runtime_upgrade_job"' in text
    assert 'job.status = "needs_reconciliation"' in text


class FakeResult:
    def __init__(self, value): self.value = value
    def scalar(self): return self.value


class FakeConnection:
    dialect = SimpleNamespace(name='postgresql')
    def __init__(self, owned=True): self.owned=owned;self.calls=[];self.invalidated=False
    def execute(self,statement,values):
        self.calls.append((str(statement),values))
        return FakeResult(self.owned if 'pg_try_advisory_lock' in str(statement) else True)
    def commit(self): self.calls.append(('commit',None))
    def invalidate(self): self.invalidated=True
    def __enter__(self):return self
    def __exit__(self,*_):pass


def test_db_lock_stays_owned_until_cycle_exits():
    conn=FakeConnection()
    with r06.exclusive_role(SimpleNamespace(connect=lambda:conn),'qualification'):
        assert sum('pg_try_advisory_lock' in x for x,y in conn.calls) == 1
        assert not any('pg_advisory_unlock' in x for x,y in conn.calls)
    assert any('pg_advisory_unlock' in x for x,y in conn.calls)


def test_duplicate_owner_is_rejected():
    conn=FakeConnection(owned=False)
    with pytest.raises(RuntimeError,match='WORKER_ALREADY_OWNED'):
        with r06.exclusive_role(SimpleNamespace(connect=lambda:conn),'auto-upgrade'):
            pass
    assert not any('pg_advisory_unlock' in x for x,y in conn.calls)


def test_no_sqlite_fallback_for_worker_lock():
    conn=FakeConnection()
    conn.dialect.name='sqlite'
    with pytest.raises(RuntimeError,match='POSTGRESQL_REQUIRED'):
        with r06.exclusive_role(SimpleNamespace(connect=lambda:conn),'qualification'):
            pass


def _load_isolated_function(source_file, function_name, namespace):
    import ast
    src = (SRC/source_file).read_text()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == function_name)
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    exec(compile(module, '<r06-isolated>', 'exec'), namespace)
    return namespace[function_name]


def _qualification_fixture():
    from sqlalchemy.orm import declarative_base, mapped_column
    from sqlalchemy import String, DateTime, Integer
    from datetime import datetime, timedelta, timezone
    from unittest.mock import MagicMock
    from sqlalchemy import select
    Base = declarative_base()
    class Qualification(Base):
        __tablename__ = 'r06_fixture_qualification'
        id = mapped_column(Integer, primary_key=True)
        status = mapped_column(String)
        started_at = mapped_column(DateTime(timezone=True))
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(build_id='build-test',status='pending_smoke',failure_code=None,
        started_at=now-timedelta(hours=5), checks_json={'image_identity':True},finished_at=None)
    db = MagicMock()
    db.scalars.return_value = [row]
    audit = Mock()
    ns = {'datetime': datetime, 'timedelta':timedelta, 'timezone': timezone,
          'ApplicationBuildQualification':Qualification, 'select':select,
          'record_audit_event':audit, 'QualificationGateError':ValueError}
    fn = _load_isolated_function('services/api/app/services/c1d2_automatic_qualification.py',
                                 'quarantine_interrupted_smokes',ns)
    return fn,db,audit,row,now


def test_interrupted_smoke_quarantine_is_audited_and_never_passes():
    fn,db,audit,row,now = _qualification_fixture()
    assert fn(db,at=now)==1
    assert row.status=='needs_review'
    assert row.failure_code=='R06_INTERRUPTED_QUALIFICATION_REVIEW_REQUIRED'
    assert row.checks_json is None and row.finished_at is None
    audit.assert_called_once()
    assert audit.call_args.kwargs['resource_id']=='build-test'
    db.commit.assert_called_once()


@pytest.mark.parametrize('age,limit',[(60,1),(3600,0),(3600,101),(3.5,25)])
def test_stale_quarantine_bad_windows_rejected_without_db_access(age,limit):
    fn,db,_,_,now = _qualification_fixture()
    with pytest.raises(ValueError):
        fn(db,older_than_seconds=age,limit=limit,at=now)
    db.scalars.assert_not_called()
    db.commit.assert_not_called()


def test_expired_upgrade_claim_quarantines_and_audits_without_retry():
    from sqlalchemy.orm import declarative_base, mapped_column
    from sqlalchemy import String, DateTime, Integer, select
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    Base=declarative_base()
    class Job(Base):
        __tablename__ = 'r06_fixture_upgrades'
        id = mapped_column(Integer, primary_key=True)
        status = mapped_column(String)
        lease_until = mapped_column(DateTime(timezone=True))
        created_at = mapped_column(DateTime(timezone=True))
    now=datetime.now(timezone.utc)
    expired=SimpleNamespace(id=123, tenant_id='tenant-fixture', status='running', last_error_code=None)
    db=MagicMock()
    db.scalars.return_value=[expired]
    db.scalar.return_value=None  # No new queued job; no execution
    audit=Mock()
    fn=_load_isolated_function('services/api/app/services/runtime_automation_service.py',
        'claim_one',{'Session':object,'utcnow':lambda: now,'RuntimeUpgradeJob':Job,
        'select':select,'record_audit_event':audit})
    assert fn(db,'r06:auto-upgrade:abc') is None
    assert expired.status=='needs_reconciliation'
    assert expired.last_error_code=='LEASE_EXPIRED_REVIEW_REQUIRED'
    assert audit.call_args.kwargs['resource_id']==123
    assert audit.call_args.kwargs['outcome']=='failed'
    db.commit.assert_called_once()
    with pytest.raises(ValueError,match='R06_WORKER_ID_INVALID'):
        fn(db, 'bad worker id')


def test_supervised_worker_checks_upgrade_claim_ownership():
    source=(SRC/'tools/r06_supervised_worker.py').read_text()
    assert 'execute_one(db, claim, expected_worker_id=worker_id)' in source
    upgrade=(SRC/'services/api/app/services/runtime_automation_service.py').read_text()
    assert 'job.claimed_by != expected_worker_id' in upgrade
    assert 'lease <= utcnow()' in upgrade
