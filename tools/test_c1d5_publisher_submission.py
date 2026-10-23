"""C1-D5.4 negative/positive evidence tests. No DB, Docker or worker invoked."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.api.app.services import c1d5_publisher_submission as target
from services.api.app.services.c1d2_automatic_qualification import QualificationGateError


class FakeDb:
    def __init__(self, rows, evidence):
        self.rows = rows
        self.evidence = evidence

    def get(self, model, ident):
        return self.rows.get((model, ident))

    def scalar(self, stmt):
        return self.evidence


def scenario(tmp_path: Path, monkeypatch, *, worker_pass: bool = True):
    publisher_id, package_id, version_id, build_id, app_id = (uuid.uuid4() for _ in range(5))
    contents = b"exact generated AAPS zip (test only)"
    archive = tmp_path / 'artifact.zip'
    archive.write_bytes(contents)
    sha = hashlib.sha256(contents).hexdigest()
    image_id = 'sha256:' + '7' * 64
    package = SimpleNamespace(id=package_id, publisher_id=publisher_id,
        application_version_id=version_id, status='validated', sha256=sha,
        stored_path=str(archive))
    version = SimpleNamespace(id=version_id, application_id=app_id,
        publication_status='draft', status='image_ready', build_type='dockerfile')
    application = SimpleNamespace(id=app_id, publisher_id=publisher_id)
    build = SimpleNamespace(id=build_id, package_id=package_id,
        application_version_id=version_id, status='ready')
    evidence = SimpleNamespace(build_id=build_id, image_id=image_id,
        status='passed', failure_code=None)
    db = FakeDb({
        (target.ApplicationPackage, package_id): package,
        (target.ApplicationVersion, version_id): version,
        (target.Application, app_id): application,
        (target.ApplicationBuild, build_id): build,
    }, evidence)
    monkeypatch.setattr(target, 'select', lambda model: SimpleNamespace(where=lambda *criteria: None))
    monkeypatch.setattr(target, 'pinned_image_identity', lambda _db, _build: image_id)
    if worker_pass:
        monkeypatch.setattr(target, 'require_passing_build', lambda _db, *, version: evidence)
    else:
        monkeypatch.setattr(target, 'require_passing_build', lambda _db, *, version:
            (_ for _ in ()).throw(QualificationGateError('C1D2_QUALIFICATION_REQUIRED')))
    options = dict(publisher_id=publisher_id, package_id=package_id,
        version_id=version_id, build_id=build_id, expected_artifact_sha256=sha)
    return db, options, package, version, build, evidence


def test_exact_trusted_qualification_passes(tmp_path, monkeypatch):
    db, options, *_ = scenario(tmp_path, monkeypatch)
    result = target.release_review(db, **options)
    assert result['eligible'] is True
    assert result['status'] == 'passed'
    assert result['artifactSha256'] == options['expected_artifact_sha256']


def test_wrong_publisher_rejected(tmp_path, monkeypatch):
    db, options, *_ = scenario(tmp_path, monkeypatch)
    with pytest.raises(target.PublisherSubmissionIssue) as caught:
        target.release_review(db, **(options | {'publisher_id': uuid.uuid4()}))
    assert caught.value.code == 'C1D54_PACKAGE_SCOPE'


def test_wrong_artifact_digest_rejected(tmp_path, monkeypatch):
    db, options, *_ = scenario(tmp_path, monkeypatch)
    with pytest.raises(target.PublisherSubmissionIssue) as caught:
        target.release_review(db, **(options | {'expected_artifact_sha256': '0'*64}))
    assert caught.value.code == 'C1D54_PACKAGE_MISMATCH'


def test_modified_stored_zip_rejected(tmp_path, monkeypatch):
    db, options, package, *_ = scenario(tmp_path, monkeypatch)
    Path(package.stored_path).write_bytes(b'tampered')
    with pytest.raises(target.PublisherSubmissionIssue) as caught:
        target.release_review(db, **options)
    assert caught.value.code == 'C1D54_PACKAGE_FILE_DRIFT'


def test_wrong_build_package_rejected(tmp_path, monkeypatch):
    db, options, package, version, build, evidence = scenario(tmp_path, monkeypatch)
    build.package_id = uuid.uuid4()
    with pytest.raises(target.PublisherSubmissionIssue) as caught:
        target.release_review(db, **options)
    assert caught.value.code == 'C1D54_BUILD_MISMATCH'


def test_pending_release_does_not_enable_submission(tmp_path, monkeypatch):
    db, options, *_ = scenario(tmp_path, monkeypatch, worker_pass=False)
    db.evidence.status = 'pending_smoke'
    result = target.release_review(db, **options)
    assert result['eligible'] is False
    assert result['status'] == 'not_checked'


def test_failed_release_does_not_enable_submission(tmp_path, monkeypatch):
    db, options, *_ = scenario(tmp_path, monkeypatch, worker_pass=False)
    db.evidence.status = 'needs_review'
    db.evidence.failure_code = 'C1D2_SMOKE_ASSERTION_FAILED'
    result = target.release_review(db, **options)
    assert result['eligible'] is False
    assert result['status'] == 'failed'
    assert result['qualificationFailureCode'] == 'C1D2_SMOKE_ASSERTION_FAILED'


def test_wrong_qualified_image_rejected(tmp_path, monkeypatch):
    db, options, *_, evidence = scenario(tmp_path, monkeypatch)
    evidence.image_id = 'sha256:' + '8'*64
    with pytest.raises(target.PublisherSubmissionIssue) as caught:
        target.release_review(db, **options)
    assert caught.value.code == 'C1D54_EVIDENCE_MISMATCH'


def test_same_version_only_draft_allowed(tmp_path, monkeypatch):
    db, options, _package, version, *_ = scenario(tmp_path, monkeypatch)
    version.publication_status = 'published'
    with pytest.raises(target.PublisherSubmissionIssue) as caught:
        target.release_review(db, **options)
    assert caught.value.code == 'C1D54_VERSION_NOT_READY'
