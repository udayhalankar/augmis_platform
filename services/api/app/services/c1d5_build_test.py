"""C1-D5.3 trusted pre-submission build and disposable smoke test.

Reuse the existing AUGMIS Docker build engine and C1-D2 disposable runner.
Never register an application, write publisher/tenant records or claim a C1-D2
release qualification. The latter remains the authoritative C1-D2 worker gate.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from services.api.app.services.build_engine import BuildError, build_docker_image
from services.api.app.services.c1d2_disposable_qualification import (
    DisposableQualification, QualificationFailure, RuntimeImages,
)
from services.api.app.services.c1d5_aaps_generator import generate_aaps_zip
from services.api.app.core.runtime_host import read_profile
from services.api.app.services.runtime_host_readiness import check_runtime_host
from tools.validate_package import validate_application_package

_SHA = re.compile(r"sha256:[a-f0-9]{64}\Z")
_KEYS = ("image_identity", "database_isolation", "schema_rls", "internal_health",
         "gateway_auth", "gateway_rejection")


class DraftBuildIssue(ValueError):
    def __init__(self, code: str, problem: str, correction: str, location: str | None = None):
        self.code, self.problem, self.correction, self.location = code, problem, correction, location
        super().__init__(problem)

    def as_dict(self):
        return dict(code=self.code, problem=self.problem,
                    correction=self.correction, location=self.location)


def _check(identifier: str, status: str, code: str, problem: str,
           correction: str = "", location: str | None = None):
    return dict(id=identifier, status=status, code=code,
                problem=problem, correction=correction, location=location)


def _image_identity(image_ref: str) -> str:
    """Read immutable Docker image identity; do not create a new build engine."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_ref, "--format", "{{.Id}}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DraftBuildIssue("C1D53_IMAGE_INSPECT_UNAVAILABLE",
                              "Docker image identity could not be inspected.",
                              "Verify Docker Desktop Linux containers and Docker CLI availability.",
                              "Docker image") from exc
    value = (result.stdout or "").strip()
    if result.returncode != 0 or not _SHA.fullmatch(value):
        raise DraftBuildIssue("C1D53_IMAGE_ID_INVALID",
                              "Built Docker image has no verifiable immutable SHA-256 identity.",
                              "Inspect the generated image and Docker Desktop state.",
                              "Docker image")
    return value


def _runtime_images() -> RuntimeImages:
    try:
        profile = read_profile()
        if profile is None or not check_runtime_host().ready:
            raise DraftBuildIssue("C1D53_RUNTIME_HOST_UNREADY",
                                  "Existing AUGMIS runtime host is not ready.",
                                  "Restore existing runtime host readiness before retrying.",
                                  "runtime-host.json")
        env = profile.environment
        return RuntimeImages(
            postgres_image_id=env["AUGMIS_C1B_POSTGRES_IMAGE_ID"],
            relay_image_id=env["AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID"],
            ingress_network=env["AUGMIS_C1B_CRUD_INGRESS_NETWORK"],
        )
    except KeyError as exc:
        raise DraftBuildIssue("C1D53_RUNTIME_IMAGES_MISSING",
                              "Existing runtime host lacks required pinned image/network configuration.",
                              "Check the C1-D1 runtime-host profile; do not hard-code image tags.",
                              "runtime-host.json") from exc


def build_test_draft(source: bytes, *, filename: str, app_key: str, app_name: str,
                     version: str, routes_json: str, schema_json: str, output_dir: str,
                     expected_source_sha256: str, expected_artifact_sha256: str,
                     max_upload_bytes: int):
    """Execute a single exact-artifact preflight. No release qualification is recorded."""
    actual_source = hashlib.sha256(source).hexdigest()
    if actual_source != expected_source_sha256:
        raise DraftBuildIssue("C1D53_SOURCE_CHANGED",
                              "Selected source ZIP differs from the analyzed source.",
                              "Analyze and generate a new draft for this exact ZIP.", "Source ZIP")

    artifact, metadata = generate_aaps_zip(
        source, filename=filename, app_key=app_key, app_name=app_name,
        version=version, routes_json=routes_json, schema_json=schema_json,
        output_dir=output_dir, max_upload_bytes=max_upload_bytes,
    )
    if metadata["artifactSha256"] != expected_artifact_sha256:
        raise DraftBuildIssue("C1D53_ARTIFACT_CHANGED",
                              "Regenerated AAPS ZIP differs from the validated draft SHA-256.",
                              "Regenerate the draft using the same configuration; do not build a different artifact.",
                              "AAPS ZIP")

    qualification = _check("qualification", "not_checked", "C1D2_RELEASE_QUALIFICATION_PENDING",
                           "Trusted C1-D2 release qualification is a separate server-side publication gate.",
                           "Complete the existing authoritative C1-D2 worker flow in C1-D5.4.")
    checks = {
        "build": _check("build", "not_checked", "C1D53_BUILD_NOT_STARTED",
                        "Isolated Docker build has not run."),
        "runtime": _check("runtime", "not_checked", "C1D53_RUNTIME_NOT_STARTED",
                          "Disposable app/database/gateway testing has not run."),
        "qualification": qualification,
    }
    response = dict(stage="C1-D5.3", sourceSha256=actual_source,
                    artifactSha256=metadata["artifactSha256"],
                    buildStatus="not_checked", runtimeStatus="not_checked",
                    qualificationStatus="not_checked", imageId=None,
                    buildLog="", smokeChecks={}, checks=checks,
                    publisherSubmissionEligible=False)

    # Only this invocation's freshly generated ZIP is passed to the existing engine.
    with tempfile.TemporaryDirectory(prefix="augmis-c1d53-preflight-") as folder:
        path = Path(folder) / "draft-aaps.zip"
        path.write_bytes(artifact)
        validation = validate_application_package(path)
        if validation["sha256"] != expected_artifact_sha256:
            raise DraftBuildIssue("C1D53_PACKAGE_DIGEST_MISMATCH",
                                  "Validated package digest does not match the selected draft.",
                                  "Regenerate the AAPS ZIP; verify the installed package validator.",
                                  "AAPS ZIP")
        # Unique tag prevents one test from overwriting a running test's tag.
        image_ref = f"augmis.local/c1d53-preflight/{app_key}:{version}-{uuid.uuid4().hex[:12]}"
        try:
            built = build_docker_image(path, validation["manifest"], image_ref)
            image_id = _image_identity(image_ref)
        except BuildError as exc:
            response["buildLog"] = str(exc)
            response["buildStatus"] = "failed"
            response["checks"]["build"] = _check(
                "build", "failed", "C1D53_DOCKER_BUILD_FAILED",
                "Existing AUGMIS Docker build engine could not build the generated artifact.",
                "Inspect the actual Docker build log below and fix the indicated source/Dockerfile step.",
                "Dockerfile")
            return response
        except DraftBuildIssue as exc:
            response["buildStatus"] = "failed"
            response["checks"]["build"] = _check("build", "failed", exc.code,
                                                    exc.problem, exc.correction, exc.location)
            return response

        response["buildLog"] = built.get("log", "")
        response["imageId"] = image_id
        response["buildStatus"] = "passed"
        response["checks"]["build"] = _check(
            "build", "passed", "C1D53_IMAGE_BUILT_PINNED",
            f"Existing Docker build succeeded; immutable image ID {image_id}.",
            location="Dockerfile")
        try:
            images = _runtime_images()
            runner = DisposableQualification(manifest=validation["manifest"],
                                            image_id=image_id, images=images)
            smoke = runner.run()  # Existing isolated PostgreSQL + app + signed gateway.
            response["smokeChecks"] = smoke
            if set(smoke) != set(_KEYS) or any(type(smoke[x]) is not bool for x in _KEYS) or not all(smoke.values()):
                raise DraftBuildIssue("C1D53_SMOKE_ASSERTION_FAILED",
                                      "One or more disposable runtime or API authorization assertions failed.",
                                      "Inspect the smoke check results; repair the app or runtime configuration.",
                                      "Application runtime")
        except DraftBuildIssue as exc:
            response["runtimeStatus"] = "action_required"
            response["checks"]["runtime"] = _check(
                "runtime", "action_required", exc.code, exc.problem, exc.correction, exc.location)
            return response
        except QualificationFailure as exc:
            response["runtimeStatus"] = "failed"
            response["checks"]["runtime"] = _check(
                "runtime", "failed", exc.code,
                "The existing C1-D2 disposable qualification runner rejected the test.",
                "Check the failing C1-D2 assertion: immutable image, private DB/RLS, health, or authenticated API.",
                "Application runtime")
            return response
        except Exception:
            response["runtimeStatus"] = "failed"
            response["checks"]["runtime"] = _check(
                "runtime", "failed", "C1D53_SMOKE_UNEXPECTED",
                "The existing disposable runtime check failed unexpectedly.",
                "Inspect backend diagnostics without exposing runtime secrets.", "Application runtime")
            return response

        response["runtimeStatus"] = "passed"
        response["checks"]["runtime"] = _check(
            "runtime", "passed", "C1D53_DISPOSABLE_SMOKE_PASSED",
            "Existing C1-D2 disposable tests passed: immutable image, isolated PostgreSQL, RLS, "
            "health, authorized GET API and unauthorized/replay rejection.",
            location="Runtime / gateway / PostgreSQL")
    return response
