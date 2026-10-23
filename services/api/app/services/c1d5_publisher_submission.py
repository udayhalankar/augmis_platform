"""C1-D5.4: read-only trusted release evidence assessment.

This is not a build, qualification or publication engine. Existing AAPS
package upload, Docker build and trusted C1-D2 qualification remain owners.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from sqlalchemy import select

from services.api.app.models.platform import (
    Application, ApplicationBuild, ApplicationPackage, ApplicationVersion,
)
from services.api.app.models.deployment_reliability import ApplicationBuildQualification
from services.api.app.services.c1d2_automatic_qualification import (
    QualificationGateError, require_passing_build,
)
from services.api.app.services.runtime_controls_service import (
    RuntimeControlError, pinned_image_identity,
)

_SHA = re.compile(r"[a-f0-9]{64}\Z")


class PublisherSubmissionIssue(ValueError):
    def __init__(self, code: str, problem: str, correction: str, status: str = "action_required"):
        self.code, self.problem, self.correction, self.status = code, problem, correction, status
        super().__init__(problem)

    def as_dict(self):
        return {"code": self.code, "problem": self.problem,
                "correction": self.correction, "status": self.status}


def _reject(code: str, problem: str, correction: str, status: str = "action_required"):
    raise PublisherSubmissionIssue(code, problem, correction, status)


def _digest_on_disk(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        _reject("C1D54_PACKAGE_FILE_MISSING", "Registered artifact is unavailable.",
                "Restore the package through the existing Publisher package workflow.")
    return digest.hexdigest()


def release_review(db, *, publisher_id: uuid.UUID, package_id: uuid.UUID,
                   version_id: uuid.UUID, build_id: uuid.UUID,
                   expected_artifact_sha256: str) -> dict:
    """Fail closed unless exact persisted package/build/qualified image match.

    Never grants release from browser-supplied Passed flags or D5.3 preflight.
    """
    if not _SHA.fullmatch(expected_artifact_sha256):
        _reject("C1D54_BAD_SHA256", "Artifact SHA-256 is invalid.",
                "Regenerate and validate the exact AAPS artifact.")
    package = db.get(ApplicationPackage, package_id)
    if package is None or package.publisher_id != publisher_id:
        _reject("C1D54_PACKAGE_SCOPE", "Package does not belong to this publisher.",
                "Select the correct publisher and qualified artifact.")
    if package.status != "validated" or package.sha256 != expected_artifact_sha256:
        _reject("C1D54_PACKAGE_MISMATCH", "Package is not validated against this exact draft SHA-256.",
                "Register and qualify the same generated AAPS ZIP.")
    if _digest_on_disk(Path(package.stored_path)) != expected_artifact_sha256:
        _reject("C1D54_PACKAGE_FILE_DRIFT", "Stored package bytes differ from the registered hash.",
                "Restore the validated immutable package; do not publish this artifact.")
    version = db.get(ApplicationVersion, version_id)
    if version is None or package.application_version_id != version.id:
        _reject("C1D54_VERSION_MISMATCH", "Package is not linked to this application version.",
                "Review the exact registered version and package.")
    application = db.get(Application, version.application_id)
    if application is None or application.publisher_id != publisher_id:
        _reject("C1D54_APPLICATION_SCOPE", "Version is not owned by the selected publisher.",
                "Select the correct publisher workspace.")
    if version.publication_status != "draft" or version.status != "image_ready" or version.build_type != "dockerfile":
        _reject("C1D54_VERSION_NOT_READY", "Version must be a Docker image-ready, unpublished draft.",
                "Complete its existing registered build and qualification.")
    build = db.get(ApplicationBuild, build_id)
    if (build is None or build.status != "ready" or
            build.package_id != package.id or build.application_version_id != version.id):
        _reject("C1D54_BUILD_MISMATCH", "Ready build is not bound to this exact version/package.",
                "Build the registered package through the existing build endpoint.")
    try:
        image_id = pinned_image_identity(db, build)
    except RuntimeControlError:
        _reject("C1D54_IMAGE_UNPINNED", "Registered build does not have a verifiable immutable Docker image.",
                "Restore the image or rebuild using the existing engine.")
    evidence = db.scalar(select(ApplicationBuildQualification).where(
        ApplicationBuildQualification.build_id == build.id))
    try:
        passing = require_passing_build(db, version=version)
    except QualificationGateError as error:
        pending = evidence is None or evidence.status == "pending_smoke"
        return {
            "status": "not_checked" if pending else "failed", "eligible": False,
            "code": error.code, "problem": "Trusted C1-D2 release qualification is pending." if pending
                else "Trusted C1-D2 release qualification has not passed.",
            "correction": "Run the existing trusted C1-D2 worker, then refresh the review."
                if pending else "Review the worker failure code; correct and requalify through existing procedures.",
            "qualificationStatus": evidence.status if evidence else "not_started",
            "qualificationFailureCode": evidence.failure_code if evidence else None,
            "artifactSha256": expected_artifact_sha256, "immutableImageId": image_id,
            "packageId": str(package.id), "versionId": str(version.id), "buildId": str(build.id),
        }
    if passing is None or passing.build_id != build.id or passing.image_id != image_id:
        _reject("C1D54_EVIDENCE_MISMATCH", "Qualified image evidence is not for the requested exact build.",
                "Reconcile registered build/qualification evidence before submitting.")
    return {
        "status": "passed", "eligible": True, "code": "C1D54_EXACT_RELEASE_QUALIFIED",
        "problem": "Exact registered AAPS package and immutable build passed trusted C1-D2 qualification.",
        "correction": "", "qualificationStatus": passing.status, "qualificationFailureCode": None,
        "artifactSha256": expected_artifact_sha256, "immutableImageId": image_id,
        "packageId": str(package.id), "versionId": str(version.id), "buildId": str(build.id),
    }
