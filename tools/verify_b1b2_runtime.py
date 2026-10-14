"""B1+B2 non-destructive verification of config, policies and package guards."""
import ast
import io
import tempfile
import zipfile
from pathlib import Path
from services.api.app.services.runtime_controls_service import validate_runtime_variables, RuntimeControlError
from services.api.app.services.runtime_automation_service import _valid_subscription
from services.api.app.services.static_package_service import inspect_static_zip, StaticPackageValidationError

class SubscriptionStub:
    status = "active"
    auto_upgrade = True
    starts_at = None
    ends_at = None

def _should_reject(fn):
    try: fn()
    except (RuntimeControlError, StaticPackageValidationError): return
    raise AssertionError("Expected rejection did not occur")

def test_config():
    assert validate_runtime_variables({"APP_MODE":"development"}) == {"APP_MODE":"development"}
    _should_reject(lambda:validate_runtime_variables({"AUGMIS_SECRET":"wrong"}))
    _should_reject(lambda:validate_runtime_variables({"bad-name":"x"}))
    _should_reject(lambda:validate_runtime_variables({"SAFE":"x\x00y"}))
    _should_reject(lambda:validate_runtime_variables({"SAFE":"x"*2049}))
    s=SubscriptionStub()
    from datetime import datetime,timezone
    assert _valid_subscription(s,datetime.now(timezone.utc))
    s.auto_upgrade=False
    assert not _valid_subscription(s,datetime.now(timezone.utc))
    print("[PASS] config validation and explicit subscription opt-in")

def test_static():
    with tempfile.TemporaryDirectory() as tmp:
        good=Path(tmp)/'valid.zip'
        with zipfile.ZipFile(good,'w') as z:
            z.writestr('index.html','<html><link rel="stylesheet" href="css/app.css"></html>')
            z.writestr('css/app.css','body { color: black }')
            z.writestr('js/app.js','console.log("hi")')
            z.writestr('images/logo.png',b'\x89PNG\r\n\x1a\n' + b'0'*32)
        inspect_static_zip(good)
        bad=Path(tmp)/'traversal.zip'
        with zipfile.ZipFile(bad,'w') as z:
            z.writestr('index.html','ok')
            z.writestr('../escape.js','evil')
        _should_reject(lambda:inspect_static_zip(bad))
        noindex=Path(tmp)/'noindex.zip'
        with zipfile.ZipFile(noindex,'w') as z:z.writestr('app.js','hello')
        _should_reject(lambda:inspect_static_zip(noindex))
    print("[PASS] multi-asset static ZIP, traversal and required index.html")

def test_version_policy():
    import uuid
    from types import SimpleNamespace
    from services.api.app.models.commerce import ApplicationOffer
    from services.api.app.models.platform import ApplicationVersion
    from services.api.app.services.version_policy_service import (require_subscription_version_allowed, VersionPolicyError)
    app_id=uuid.uuid4(); offer_id=uuid.uuid4(); baseline_id=uuid.uuid4(); pinned_id=uuid.uuid4()
    baseline=SimpleNamespace(id=baseline_id, version="1.0.0")
    def version(name): return SimpleNamespace(id=uuid.uuid4(), version=name, application_id=app_id,build_type="dockerfile",status="image_ready")
    class DB:
        def get(self, klass, id):
            return SimpleNamespace(application_id=app_id) if klass is ApplicationOffer else baseline
    sub=SimpleNamespace(offer_id=offer_id,version_policy="same_major",baseline_version_id=baseline_id,pinned_version_id=None)
    good=version("1.1.0"); bad=version("2.0.0")
    require_subscription_version_allowed(DB(),sub,good)
    try: require_subscription_version_allowed(DB(),sub,bad)
    except VersionPolicyError: pass
    else: raise AssertionError("same_major permitted major upgrade")
    sub.version_policy="pinned";sub.pinned_version_id=pinned_id
    try: require_subscription_version_allowed(DB(),sub,good)
    except VersionPolicyError: pass
    else: raise AssertionError("pinned allowed another version")
    sub.version_policy="any"
    require_subscription_version_allowed(DB(),sub,bad)
    print("[PASS] same_major / pinned / any version policy decisions")

def test_image_identity():
    from types import SimpleNamespace
    from services.api.app.services import runtime_controls_service as ctrl
    fake = "sha256:" + "a"*64
    real = ctrl.run_docker
    class DB:
        def flush(self): pass
    build = SimpleNamespace(image_ref="augmis.local/lab:1.0",immutable_image_id=None)
    try:
        ctrl.run_docker = lambda *args,**kwargs: fake
        assert ctrl.pinned_image_identity(DB(),build)==fake
        assert build.immutable_image_id==fake
        ctrl.run_docker = lambda *args,**kwargs: "sha256:"+"b"*64
        _should_reject(lambda:ctrl.pinned_image_identity(DB(),build))
    finally:
        ctrl.run_docker = real
    print("[PASS] immutable image-ID pinning and moved-tag rejection")

def main():
    test_config()
    test_version_policy()
    test_image_identity()
    test_static()
    print("[PASS] B1+B2 non-destructive smoke checks")

if __name__ == '__main__': main()
