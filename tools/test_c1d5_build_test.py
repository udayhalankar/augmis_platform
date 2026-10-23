"""C1-D5.3 unit regressions; mocks Docker and disposable containers only.

Real Docker acceptance must be run separately on the user's Windows host.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from pathlib import Path

import pytest

from services.api.app.services import c1d5_build_test as target
from services.api.app.services.build_engine import BuildError

SOURCE = b"example-raw-source-for-unit-test"
SOURCE_SHA = hashlib.sha256(SOURCE).hexdigest()
ARTIFACT = b"example-validated-generated-aaps"
ARTIFACT_SHA = hashlib.sha256(ARTIFACT).hexdigest()
IMAGE_SHA = "sha256:" + "a" * 64
SMOKE = dict.fromkeys(target._KEYS, True)


def options(**overrides):
    return dict(source=SOURCE, filename="source.zip", app_key="test-app", app_name="Test App",
                version="1.0.0", routes_json="", schema_json="", output_dir="dist",
                expected_source_sha256=SOURCE_SHA, expected_artifact_sha256=ARTIFACT_SHA,
                max_upload_bytes=1_000_000) | overrides


def setup(monkeypatch, tmp_path, *, build_failure=False, smoke=None):
    def generate(*args, **kwargs):
        return ARTIFACT, {"artifactSha256": ARTIFACT_SHA}
    monkeypatch.setattr(target, "generate_aaps_zip", generate)
    monkeypatch.setattr(target, "validate_application_package", lambda p: {
        "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest(),
        "manifest": {"runtime": {"buildType": "dockerfile"}},
    })
    def build(*args):
        if build_failure:
            raise BuildError("RUN npm run build failed: example diagnostic")
        return {"status": "ready", "log": "Docker build completed"}
    monkeypatch.setattr(target, "build_docker_image", build)
    monkeypatch.setattr(target, "_image_identity", lambda image: IMAGE_SHA)
    monkeypatch.setattr(target, "_runtime_images", lambda: SimpleNamespace())
    class StubRunner:
        def __init__(self, **kwargs):
            assert kwargs["image_id"] == IMAGE_SHA
        def run(self):
            return SMOKE.copy() if smoke is None else smoke
    monkeypatch.setattr(target, "DisposableQualification", StubRunner)


def test_source_sha_required_before_any_build(monkeypatch):
    def must_not_generate(*args, **kwargs):
        pytest.fail("Must not generate after a source SHA mismatch")
    monkeypatch.setattr(target, "generate_aaps_zip", must_not_generate)
    with pytest.raises(target.DraftBuildIssue) as caught:
        target.build_test_draft(**options(expected_source_sha256="0" * 64))
    assert caught.value.code == "C1D53_SOURCE_CHANGED"


def test_artifact_sha_prevents_build(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    with pytest.raises(target.DraftBuildIssue) as caught:
        target.build_test_draft(**options(expected_artifact_sha256="f" * 64))
    assert caught.value.code == "C1D53_ARTIFACT_CHANGED"


def test_actual_build_failure_reports_log_and_skips_smoke(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, build_failure=True)
    response = target.build_test_draft(**options())
    assert response["buildStatus"] == "failed"
    assert "npm run build" in response["buildLog"]
    assert response["runtimeStatus"] == "not_checked"
    assert response["qualificationStatus"] == "not_checked"
    assert not response["publisherSubmissionEligible"]


def test_failed_smoke_cannot_enable_release(monkeypatch, tmp_path):
    failed = SMOKE | {"internal_health": False}
    setup(monkeypatch, tmp_path, smoke=failed)
    response = target.build_test_draft(**options())
    assert response["buildStatus"] == "passed"
    assert response["runtimeStatus"] == "action_required"
    assert response["qualificationStatus"] == "not_checked"
    assert not response["publisherSubmissionEligible"]


def test_build_and_smoke_pass_but_release_gate_remains_closed(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    response = target.build_test_draft(**options())
    assert response["artifactSha256"] == ARTIFACT_SHA
    assert response["imageId"] == IMAGE_SHA
    assert response["smokeChecks"] == SMOKE
    assert response["buildStatus"] == "passed"
    assert response["runtimeStatus"] == "passed"
    assert response["qualificationStatus"] == "not_checked"
    assert response["checks"]["qualification"]["status"] == "not_checked"
    assert response["publisherSubmissionEligible"] is False


def test_draft_zip_timestamp_stability(monkeypatch):
    """Generator never uses wall-clock metadata for its generated ZIP entries."""
    import zipfile
    from tools.test_c1d5_aaps_generator import raw_zip, gen
    source = raw_zip()
    monkeypatch.setattr(zipfile.time, "localtime", lambda *_: (2026, 10, 21, 1, 2, 3, 0, 0, 0))
    zip_a, report_a = gen(source)
    monkeypatch.setattr(zipfile.time, "localtime", lambda *_: (2026, 10, 22, 7, 8, 9, 0, 0, 0))
    zip_b, report_b = gen(source)
    assert zip_a == zip_b
    assert report_a["artifactSha256"] == report_b["artifactSha256"]
