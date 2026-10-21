# services/api/app/routes/applications.py
from __future__ import annotations

import shutil
import uuid
import zipfile

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile
)

import hashlib
import re

from fastapi.responses import HTMLResponse

from services.api.app.core.auth import (
    get_current_user
)

from services.api.app.models.iam import (
    PublisherMembership,
    User
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_publisher_permission
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.config import settings
from services.api.app.db.session import get_db

from services.api.app.models.platform import (
    Application,
    ApplicationPackage,
    ApplicationBuild,
    ApplicationValidationRun,
    ApplicationVersion,
    Publisher
)
from datetime import datetime, timezone

from services.api.app.services.audit_service import record_audit_event

from services.api.app.services.build_engine import (
    BuildError,
    build_docker_image
)

from tools.validate_package import (
    PackageValidationError,
    validate_application_package
)

from services.api.app.services.c1d5_source_analysis import analyze_source_zip
from services.api.app.services.c1d5_aaps_generator import generate_aaps_zip, GenerationIssue
from fastapi.responses import StreamingResponse

from services.api.app.services.static_package_service import (
    StaticPackageValidationError,
    calculate_sha256,
    extract_static_zip,
    inspect_static_zip,
    validate_single_static_html,
)


from services.api.app.services.c1d2_automatic_qualification import (
    enqueue_ready_build, require_passing_build, QualificationGateError,
)
from services.api.app.models.deployment_reliability import ApplicationBuildQualification

router = APIRouter(
    prefix="/api/v1",
    tags=["Applications"]
)


def save_upload(
    file: UploadFile,
    target: Path
) -> int:

    target.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    max_bytes = (
        settings.max_upload_size_mb
        * 1024
        * 1024
    )

    written = 0

    with target.open("wb") as output:

        while True:

            chunk = file.file.read(
                1024 * 1024
            )

            if not chunk:
                break

            written += len(chunk)

            if written > max_bytes:

                output.close()

                target.unlink(
                    missing_ok=True
                )

                raise HTTPException(
                    status_code=413,
                    detail="Uploaded package is too large"
                )

            output.write(chunk)

    return written

STATIC_APP_KEY = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
STATIC_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")


def validate_static_html_file(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()

    sha256 = hashlib.sha256(raw).hexdigest()

    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=422,
            detail="Static web application must be UTF-8 HTML"
        ) from error

    sample = html.lower()

    if not (
        "<!doctype" in sample
        or "<html" in sample
        or "<body" in sample
    ):
        raise HTTPException(
            status_code=422,
            detail="Uploaded file does not appear to be a standalone HTML application"
        )

    return html, sha256


@router.post("/publishers/{publisher_id}/containerization/analyze")
def analyze_containerization_source(
    publisher_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """C1-D5.1 source analysis only. Never registers or executes uploaded code."""
    publisher = db.get(Publisher, publisher_id)
    if publisher is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    try:
        require_publisher_permission(
            db=db, user=current_user, publisher_id=publisher.id,
            permission_code="application.upload",
        )
    except AuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    if not file.filename:
        raise HTTPException(status_code=400, detail="Source filename is required")
    # The upload is inspected in memory/from Starlette's spooled file.
    # It is never persisted to the published/quarantine artifact stores.
    try:
        file.file.seek(0, 2)
        compressed_size = file.file.tell()
        file.file.seek(0)
        max_bytes = settings.max_upload_size_mb * 1024 * 1024
        if compressed_size > max_bytes:
            raise HTTPException(status_code=413, detail="Source ZIP exceeds upload limit")
        return analyze_source_zip(file.file, file.filename, max_bytes)
    finally:
        file.file.close()


@router.post("/publishers/{publisher_id}/containerization/generate")
def generate_containerization_draft(
    publisher_id: uuid.UUID,
    file: UploadFile = File(...),
    app_key: str = Form(...),
    app_name: str = Form(...),
    version: str = Form(...),
    routes_json: str = Form(""),
    schema_json: str = Form(""),
    output_dir: str = Form("dist"),
    mode: str = Form("preview"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """C1-D5.2 draft generation only; no registration/build/qualification."""
    publisher = db.get(Publisher, publisher_id)
    if publisher is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    try:
        require_publisher_permission(
            db=db, user=current_user, publisher_id=publisher.id,
            permission_code="application.upload",
        )
    except AuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    if mode not in ("preview", "download"):
        raise HTTPException(status_code=400, detail={
            "code": "GEN_MODE_INVALID", "problem": "Invalid generation mode.",
            "correction": "Use preview or download.", "location": None,
        })
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    try:
        source = file.file.read(max_bytes + 1)
        if len(source) > max_bytes:
            raise HTTPException(status_code=413, detail={
                "code": "GEN_UPLOAD_TOO_LARGE", "problem": "Uploaded source ZIP is too large.",
                "correction": "Remove generated build folders and dependencies.", "location": None,
            })
        try:
            artifact, meta = generate_aaps_zip(
                source, filename=file.filename or "", app_key=app_key,
                app_name=app_name, version=version,
                routes_json=routes_json, schema_json=schema_json,
                output_dir=output_dir, max_upload_bytes=max_bytes,
            )
        except GenerationIssue as error:
            raise HTTPException(status_code=422, detail=error.as_dict()) from error
        if mode == "preview":
            return meta
        headers = {
            "Content-Disposition": f'attachment; filename="{app_key}-{version}-draft-aaps.zip"',
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        }
        return StreamingResponse(iter((artifact,)), media_type="application/zip", headers=headers)
    finally:
        file.file.close()


@router.post(
    "/publishers/{publisher_id}/applications/upload",
    status_code=201
)
def upload_application(
    publisher_id: uuid.UUID,

    file: UploadFile = File(...),

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    )
):

    publisher = db.get(
        Publisher,
        publisher_id
    )
    

    if not publisher:

        raise HTTPException(
            status_code=404,
            detail="Publisher not found"
        )
    

    if not file.filename:

        raise HTTPException(
            status_code=400,
            detail="Filename is required"
        )

    if not file.filename.lower().endswith(
        ".zip"
    ):

        raise HTTPException(
            status_code=400,
            detail="Only ZIP application packages are allowed"
        )


    try:

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=publisher.id,
            permission_code="application.upload"
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error)
        )

    
    package_id = uuid.uuid4()

    quarantine_root = (
        settings.package_storage_root
        / "quarantine"
    )

    quarantine_path = (
        quarantine_root
        / f"{package_id}.zip"
    )

    size_bytes = save_upload(
        file,
        quarantine_path
    )

    package = ApplicationPackage(
        id=package_id,
        publisher_id=publisher.id,
        original_filename=file.filename,
        stored_path=str(
            quarantine_path
        ),
        size_bytes=size_bytes,
        status="validating"
    )

    db.add(package)

    record_audit_event(
        db=db,
        action="application.package.uploaded",
        resource_type="application_package",
        resource_id=package.id,
        publisher_id=publisher.id,
        actor_user_id=current_user.id,
        metadata={
            "filename": package.original_filename,
            "sizeBytes": package.size_bytes,
            "format": "zip",
            "status": "validating",
        },
        message="Application package received for validation.",
    )
    db.commit()

    validation_run = (
        ApplicationValidationRun(
            package_id=package.id,
            status="running"
        )
    )

    db.add(validation_run)

    record_audit_event(
        db=db,
        action="application.package.validation.started",
        resource_type="application_package",
        resource_id=package.id,
        publisher_id=publisher.id,
        actor_user_id=current_user.id,
        metadata={"validationStatus": "running"},
        message="Application package validation started.",
    )
    db.commit()

    try:

        result = (
            validate_application_package(
                quarantine_path
            )
        )

    except (
        PackageValidationError,
        zipfile.BadZipFile
    ) as error:

        rejected_root = (
            settings.package_storage_root
            / "rejected"
        )

        rejected_root.mkdir(
            parents=True,
            exist_ok=True
        )

        rejected_path = (
            rejected_root
            / f"{package.id}.zip"
        )

        shutil.move(
            str(quarantine_path),
            str(rejected_path)
        )

        package.status = "rejected"

        package.stored_path = str(
            rejected_path
        )

        validation_run.status = "invalid"

        validation_run.errors = [
            str(error)
        ]

        record_audit_event(
            db=db,
            action="application.package.validation.failed",
            resource_type="application_package",
            resource_id=package.id,
            publisher_id=publisher.id,
            actor_user_id=current_user.id,
            outcome="failed",
            metadata={
                "validationStatus": "invalid",
                "errorType": type(error).__name__,
            },
            message="Application package validation failed.",
        )
        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Application package validation failed",

                "errors": [
                    str(error)
                ]
            }
        )

    manifest = result["manifest"]

    metadata = manifest["metadata"]

    runtime = manifest["runtime"]

    package.sha256 = result["sha256"]

    application = db.scalar(
        select(Application)
        .where(
            Application.publisher_id
            == publisher.id,

            Application.app_key
            == metadata["id"]
        )
    )

    new_application = application is None
    previous_application_details = (
        (application.name, application.description)
        if application is not None else None
    )

    if not application:

        application = Application(
            publisher_id=publisher.id,
            app_key=metadata["id"],
            name=metadata["name"],
            description=metadata.get(
                "description"
            ),
            status="validated"
        )

        db.add(application)

        db.flush()

    else:

        application.name = (
            metadata["name"]
        )

        application.description = (
            metadata.get(
                "description"
            )
        )

    existing_version = db.scalar(
        select(ApplicationVersion)
        .where(
            ApplicationVersion.application_id
            == application.id,

            ApplicationVersion.version
            == metadata["version"]
        )
    )

    if existing_version:

        if (
            existing_version.manifest
            == manifest
        ):

            raise HTTPException(
                status_code=409,
                detail=(
                    "This application version "
                    "already exists."
                )
            )

        raise HTTPException(
            status_code=409,
            detail=(
                "Version already exists with "
                "different application metadata. "
                "Application versions are immutable."
            )
        )

    version = ApplicationVersion(
        application_id=application.id,
        version=metadata["version"],
        deployment_mode=runtime[
            "deploymentMode"
        ],
        build_type=runtime[
            "buildType"
        ],
        manifest=manifest,
        status="validated",
        publication_status="draft"
    )

    db.add(version)

    db.flush()

    validated_path = (
        settings.package_storage_root
        / "validated"
        / publisher.slug
        / metadata["id"]
        / metadata["version"]
        / f"{result['sha256']}.zip"
    )

    validated_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    shutil.move(
        str(quarantine_path),
        str(validated_path)
    )

    package.application_version_id = (
        version.id
    )

    package.stored_path = str(
        validated_path
    )

    package.status = "validated"

    validation_run.status = "valid"

    validation_run.errors = []

    if (
        previous_application_details is not None
        and previous_application_details != (application.name, application.description)
    ):
        changed_fields = [
            field
            for field, before, after in (
                ("name", previous_application_details[0], application.name),
                ("description", previous_application_details[1], application.description),
            )
            if before != after
        ]
        record_audit_event(
            db=db,
            action="application.updated",
            resource_type="application",
            resource_id=application.id,
            publisher_id=publisher.id,
            actor_user_id=current_user.id,
            metadata={
                "appKey": application.app_key,
                "changedFields": changed_fields,
            },
            message="Publisher application metadata updated with new version.",
        )

    if new_application:
        record_audit_event(
            db=db,
            action="application.created",
            resource_type="application",
            resource_id=application.id,
            publisher_id=publisher.id,
            actor_user_id=current_user.id,
            metadata={"appKey": application.app_key},
            message="Publisher application registered.",
        )

    record_audit_event(
        db=db,
        action="application.version.created",
        resource_type="application_version",
        resource_id=version.id,
        publisher_id=publisher.id,
        actor_user_id=current_user.id,
        metadata={
            "applicationId": str(application.id),
            "version": version.version,
            "buildType": version.build_type,
            "publicationStatus": "draft",
        },
        message="Application version registered.",
    )
    record_audit_event(
        db=db,
        action="application.package.validated",
        resource_type="application_package",
        resource_id=package.id,
        publisher_id=publisher.id,
        actor_user_id=current_user.id,
        metadata={
            "applicationId": str(application.id),
            "versionId": str(version.id),
            "sha256": package.sha256,
            "format": "zip",
        },
        message="Application package validated successfully.",
    )
    db.commit()

    return {

        "status": "VALIDATED",

        "publisher": {
            "id": str(publisher.id),
            "name": publisher.name
        },

        "application": {
            "id": str(application.id),
            "appKey": application.app_key,
            "name": application.name
        },

        "version": {
            "id": str(version.id),
            "version": version.version,
            "buildType":
                version.build_type,

            "deploymentMode":
                version.deployment_mode
        },

        "package": {
            "id": str(package.id),
            "sha256": package.sha256,
            "sizeBytes":
                package.size_bytes,

            "status":
                package.status
        }
    }


@router.post(
    "/publishers/{publisher_id}/applications/upload-static",
    status_code=201,
)
def upload_static_application(
    publisher_id: uuid.UUID,

    file: UploadFile = File(...),

    app_name: str = Form(...),
    app_key: str = Form(...),
    version: str = Form("1.0.0"),
    description: str = Form(""),

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # STEP 3D-A
    # STATIC HTML + MULTI-FILE STATIC ZIP UPLOAD
    # =====================================================

    publisher = db.get(
        Publisher,
        publisher_id
    )

    if not publisher:

        raise HTTPException(
            status_code=404,
            detail="Publisher not found"
        )


    # =====================================================
    # AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=publisher.id,
            permission_code="application.upload"
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error)
        ) from error


    # =====================================================
    # NORMALIZE METADATA
    # =====================================================

    clean_name = str(
        app_name or ""
    ).strip()

    clean_key = str(
        app_key or ""
    ).strip().lower()

    clean_version = str(
        version or ""
    ).strip()

    clean_description = str(
        description or ""
    ).strip()


    if not clean_name:

        raise HTTPException(
            status_code=400,
            detail="Application name is required"
        )


    if not STATIC_APP_KEY.fullmatch(
        clean_key
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "App key must contain only lowercase "
                "letters, numbers and hyphens, and must "
                "start/end with a letter or number"
            )
        )


    if not STATIC_VERSION.fullmatch(
        clean_version
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Version must use semantic version "
                "format, for example 1.0.0"
            )
        )


    if not file.filename:

        raise HTTPException(
            status_code=400,
            detail="Filename is required"
        )


    lower_filename = (
        file.filename.lower()
    )


    is_html = (
        lower_filename.endswith(
            ".html"
        )
        or lower_filename.endswith(
            ".htm"
        )
    )

    is_zip = (
        lower_filename.endswith(
            ".zip"
        )
    )


    if not (
        is_html
        or is_zip
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Static web upload accepts "
                ".html, .htm or .zip files"
            )
        )


    # =====================================================
    # IMMUTABLE VERSION CHECK
    # =====================================================

    existing_application = db.scalar(
        select(Application)
        .where(
            Application.publisher_id
            == publisher.id,

            Application.app_key
            == clean_key,
        )
    )


    if existing_application:

        existing_version = db.scalar(
            select(ApplicationVersion)
            .where(
                ApplicationVersion.application_id
                == existing_application.id,

                ApplicationVersion.version
                == clean_version,
            )
        )


        if existing_version:

            raise HTTPException(
                status_code=409,
                detail=(
                    "This application version "
                    "already exists"
                )
            )


    # =====================================================
    # QUARANTINE
    # =====================================================

    package_id = uuid.uuid4()


    quarantine_root = (
        settings.package_storage_root
        / "quarantine"
    )


    quarantine_root.mkdir(
        parents=True,
        exist_ok=True,
    )


    quarantine_suffix = (
        ".zip"
        if is_zip
        else ".html"
    )


    quarantine_path = (
        quarantine_root
        / f"{package_id}{quarantine_suffix}"
    )


    size_bytes = save_upload(
        file,
        quarantine_path
    )


    # =====================================================
    # VALIDATE PACKAGE
    # =====================================================

    package_format = (
        "zip"
        if is_zip
        else "single_html"
    )


    extraction_info = None


    try:

        if is_zip:

            sha256 = calculate_sha256(
                quarantine_path
            )

            # Inspect before any final extraction.
            #
            # extract_static_zip() performs validation again
            # immediately before extraction.
          
            extraction_info = (
                inspect_static_zip(
                    quarantine_path
                )
            )

        else:

            html_info = (
                validate_single_static_html(
                    quarantine_path
                )
            )

            sha256 = html_info[
                "sha256"
            ]

            extraction_info = {
                "entryFile":
                    html_info[
                        "entryFile"
                    ],

                "fileCount":
                    html_info[
                        "fileCount"
                    ],

                "extractedSizeBytes":
                    html_info[
                        "extractedSizeBytes"
                    ],
            }


    except StaticPackageValidationError as error:

        rejected_root = (
            settings.package_storage_root
            / "rejected"
        )


        rejected_root.mkdir(
            parents=True,
            exist_ok=True,
        )


        rejected_path = (
            rejected_root
            / (
                f"{package_id}"
                f"{quarantine_suffix}"
            )
        )


        if quarantine_path.exists():

            shutil.move(
                str(quarantine_path),
                str(rejected_path)
            )


        # No database package record exists on this failure path.
        # The failed attempt is therefore audited independently.
        record_audit_event(
            db=db,
            action="application.package.validation.failed",
            resource_type="application_package",
            resource_id=package_id,
            publisher_id=publisher.id,
            actor_user_id=current_user.id,
            outcome="failed",
            metadata={
                "appKey": clean_key,
                "version": clean_version,
                "format": package_format,
                "errorType": type(error).__name__,
            },
            message="Static application package validation failed.",
        )
        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Static application package "
                    "validation failed",

                "errors": [
                    str(error)
                ],
            },
        ) from error


    # =====================================================
    # APPLICATION
    # =====================================================

    application = (
        existing_application
    )


    new_application = application is None
    previous_application_details = (
        (application.name, application.description)
        if application is not None else None
    )

    if not application:

        application = Application(
            publisher_id=
                publisher.id,

            app_key=
                clean_key,

            name=
                clean_name,

            description=
                clean_description
                or None,

            status=
                "validated",
        )


        db.add(
            application
        )

        db.flush()


    else:

        application.name = (
            clean_name
        )

        application.description = (
            clean_description
            or None
        )


    # =====================================================
    # MANIFEST
    # =====================================================

    manifest = {
        "metadata": {
            "id":
                clean_key,

            "name":
                clean_name,

            "description":
                clean_description,

            "version":
                clean_version,
        },

        "runtime": {
            "buildType":
                "static_web",

            "deploymentMode":
                "static",

            "entryFile":
                "index.html",

            "packageFormat":
                package_format,
        },

        "package": {
            "sha256":
                sha256,

            "fileCount":
                extraction_info[
                    "fileCount"
                ],

            "extractedSizeBytes":
                extraction_info[
                    "extractedSizeBytes"
                ],
        },
    }


    # =====================================================
    # VERSION
    # =====================================================

    version_row = ApplicationVersion(
        application_id=
            application.id,

        version=
            clean_version,

        deployment_mode=
            "static",

        build_type=
            "static_web",

        manifest=
            manifest,

        status=
            "validated",

        publication_status=
            "draft",
    )


    db.add(
        version_row
    )

    db.flush()


    # =====================================================
    # FINAL IMMUTABLE STORAGE
    # =====================================================

    version_root = (
        settings.package_storage_root
        / "validated"
        / publisher.slug
        / clean_key
        / clean_version
    )


    version_root.mkdir(
        parents=True,
        exist_ok=True,
    )


    try:

        if is_zip:

            validated_path = (
                version_root
                / sha256
            )


            extraction_info = (
                extract_static_zip(
                    quarantine_path,
                    validated_path,
                )
            )


            # The validated package is now represented by
            # the immutable extracted directory.
            #
            # The original ZIP is retained beside it for
            # traceability / future download or scanning.

            original_zip_path = (
                version_root
                / f"{sha256}.zip"
            )


            shutil.move(
                str(quarantine_path),
                str(original_zip_path)
            )


        else:

            validated_path = (
                version_root
                / f"{sha256}.html"
            )


            shutil.move(
                str(quarantine_path),
                str(validated_path)
            )


    except StaticPackageValidationError as error:

        # Remove partially-created version data.
        if is_zip:

            partial_directory = (
                version_root
                / sha256
            )

            shutil.rmtree(
                partial_directory,
                ignore_errors=True,
            )


        if quarantine_path.exists():

            rejected_root = (
                settings.package_storage_root
                / "rejected"
            )


            rejected_root.mkdir(
                parents=True,
                exist_ok=True,
            )


            rejected_path = (
                rejected_root
                / (
                    f"{package_id}"
                    f"{quarantine_suffix}"
                )
            )


            shutil.move(
                str(quarantine_path),
                str(rejected_path)
            )


        db.rollback()

        # The failed database transaction is rolled back before
        # recording the independent rejection evidence.
        record_audit_event(
            db=db,
            action="application.package.validation.failed",
            resource_type="application_package",
            resource_id=package_id,
            publisher_id=publisher.id,
            actor_user_id=current_user.id,
            outcome="failed",
            metadata={
                "appKey": clean_key,
                "version": clean_version,
                "format": package_format,
                "stage": "extraction",
                "errorType": type(error).__name__,
            },
            message="Static application package extraction failed.",
        )
        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Static application package "
                    "extraction failed",

                "errors": [
                    str(error)
                ],
            },
        ) from error


    # =====================================================
    # PACKAGE RECORD
    # =====================================================

    package = ApplicationPackage(
        id=
            package_id,

        publisher_id=
            publisher.id,

        application_version_id=
            version_row.id,

        original_filename=
            file.filename,

        stored_path=
            str(
                validated_path
            ),

        size_bytes=
            size_bytes,

        sha256=
            sha256,

        status=
            "validated",
    )


    db.add(
        package
    )

    db.flush()


    # =====================================================
    # VALIDATION RUN
    # =====================================================

    validation_run = (
        ApplicationValidationRun(
            package_id=
                package.id,

            status=
                "valid",

            errors=
                [],
        )
    )


    db.add(
        validation_run
    )

    if (
        previous_application_details is not None
        and previous_application_details != (application.name, application.description)
    ):
        changed_fields = [
            field
            for field, before, after in (
                ("name", previous_application_details[0], application.name),
                ("description", previous_application_details[1], application.description),
            )
            if before != after
        ]
        record_audit_event(
            db=db,
            action="application.updated",
            resource_type="application",
            resource_id=application.id,
            publisher_id=publisher.id,
            actor_user_id=current_user.id,
            metadata={
                "appKey": application.app_key,
                "changedFields": changed_fields,
            },
            message="Publisher application metadata updated with new version.",
        )

    if new_application:
        record_audit_event(
            db=db,
            action="application.created",
            resource_type="application",
            resource_id=application.id,
            publisher_id=publisher.id,
            actor_user_id=current_user.id,
            metadata={"appKey": application.app_key},
            message="Publisher application registered.",
        )

    record_audit_event(
        db=db,
        action="application.package.uploaded",
        resource_type="application_package",
        resource_id=package.id,
        publisher_id=publisher.id,
        actor_user_id=current_user.id,
        metadata={
            "applicationId": str(application.id),
            "versionId": str(version_row.id),
            "sizeBytes": package.size_bytes,
            "format": package_format,
        },
        message="Static application package uploaded.",
    )
    record_audit_event(
        db=db,
        action="application.version.created",
        resource_type="application_version",
        resource_id=version_row.id,
        publisher_id=publisher.id,
        actor_user_id=current_user.id,
        metadata={
            "applicationId": str(application.id),
            "version": version_row.version,
            "buildType": "static_web",
            "publicationStatus": "draft",
        },
        message="Static application version registered.",
    )
    record_audit_event(
        db=db,
        action="application.package.validated",
        resource_type="application_package",
        resource_id=package.id,
        publisher_id=publisher.id,
        actor_user_id=current_user.id,
        metadata={
            "applicationId": str(application.id),
            "versionId": str(version_row.id),
            "sha256": sha256,
            "format": package_format,
            "fileCount": extraction_info["fileCount"],
        },
        message="Static application package validated successfully.",
    )
    db.commit()


    # =====================================================
    # RESPONSE
    # =====================================================

    return {
        "status":
            "VALIDATED",

        "publisher": {
            "id":
                str(
                    publisher.id
                ),

            "name":
                publisher.name,
        },

        "application": {
            "id":
                str(
                    application.id
                ),

            "appKey":
                application.app_key,

            "name":
                application.name,
        },

        "version": {
            "id":
                str(
                    version_row.id
                ),

            "version":
                version_row.version,

            "buildType":
                version_row.build_type,

            "deploymentMode":
                version_row.deployment_mode,
        },

        "package": {
            "id":
                str(
                    package.id
                ),

            "sha256":
                package.sha256,

            "sizeBytes":
                package.size_bytes,

            "status":
                package.status,

            "format":
                package_format,

            "entryFile":
                "index.html",

            "fileCount":
                extraction_info[
                    "fileCount"
                ],

            "extractedSizeBytes":
                extraction_info[
                    "extractedSizeBytes"
                ],
        },
    }

# =========================================================
# LIST APPLICATIONS
# =========================================================

@router.get(
    "/applications"
)
def list_applications(
    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    memberships = list(
        db.scalars(
            select(PublisherMembership)
            .where(
                PublisherMembership.user_id
                == current_user.id,

                PublisherMembership.status
                == "active",
            )
        )
    )

    authorized_publisher_ids = []

    for membership in memberships:

        try:
            require_publisher_permission(
                db=db,
                user=current_user,
                publisher_id=membership.publisher_id,
                permission_code="application.manage",
            )

        except AuthorizationError:
            continue

        authorized_publisher_ids.append(
            membership.publisher_id
        )

    if not authorized_publisher_ids:
        return []

    applications = list(
        db.scalars(
            select(Application)
            .where(
                Application.publisher_id.in_(
                    authorized_publisher_ids
                )
            )
            .order_by(
                Application.created_at.desc()
            )
        )
    )

    return [
        {
            "id":
                str(app.id),

            "publisherId":
                str(app.publisher_id),

            "appKey":
                app.app_key,

            "name":
                app.name,

            "description":
                app.description,

            "status":
                app.status,
        }

        for app in applications
    ]


# =========================================================
# BUILD APPLICATION PACKAGE
# =========================================================

@router.post(
    "/application-packages/{package_id}/build",
    status_code=201
)
def build_application_package(
    package_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    )
):

    # =====================================================
    # 1. PACKAGE
    # =====================================================

    package = db.get(
        ApplicationPackage,
        package_id
    )

    if not package:

        raise HTTPException(
            status_code=404,
            detail="Application package not found"
        )

    # =====================================================
    # 2. PUBLISHER AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=package.publisher_id,
            permission_code="application.manage"
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error)
        ) from error

    # =====================================================
    # 3. PACKAGE STATUS
    # =====================================================

    if package.status != "validated":

        raise HTTPException(
            status_code=409,
            detail=(
                "Only validated application "
                "packages can be built."
            )
        )

    if not package.application_version_id:

        raise HTTPException(
            status_code=409,
            detail=(
                "Package is not linked to "
                "an application version."
            )
        )

    # =====================================================
    # 4. VERSION
    # =====================================================

    version = db.get(
        ApplicationVersion,
        package.application_version_id
    )

    if not version:

        raise HTTPException(
            status_code=404,
            detail="Application version not found"
        )

    if version.build_type == "static_web":
        raise HTTPException(
            status_code=409,
            detail=(
                "Static web applications do not require "
                "a Docker build."
            )
        )
    # =====================================================
    # VERSION BUILD STATE
    # =====================================================

    allowed_build_states = {
        "validated",
        "build_failed",
    }

    if (
        version.status
        not in allowed_build_states
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Application version cannot "
                "be built from status "
                f"{version.status}."
            )
        )

    if version.build_type == "static_web":
        raise HTTPException(
            status_code=409,
            detail=(
                "Static web applications do not require "
                "a Docker build."
            )
        )
    # =====================================================
    # 5. APPLICATION
    # =====================================================

    application = db.get(
        Application,
        version.application_id
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found"
        )

    # =====================================================
    # 6. PUBLISHER
    # =====================================================

    publisher = db.get(
        Publisher,
        application.publisher_id
    )

    if not publisher:

        raise HTTPException(
            status_code=404,
            detail="Publisher not found"
        )

    # =====================================================
    # 7. IMAGE REFERENCE
    # =====================================================

    image_ref = (
        f"augmis.local/"
        f"{publisher.slug}/"
        f"{application.app_key}:"
        f"{version.version}"
    )

    # =====================================================
    # 8. CREATE BUILD RECORD
    # =====================================================

    build = ApplicationBuild(
        application_version_id=version.id,
        package_id=package.id,
        status="building",
        image_ref=image_ref,
        started_at=datetime.now(
            timezone.utc
        )
    )

    db.add(build)
    db.flush()  # Assign build.id before using it as audit resource ID.

    record_audit_event(
        db=db,
        action="application.build.started",
        resource_type="application_build",
        resource_id=build.id,
        publisher_id=publisher.id,
        actor_user_id=current_user.id,
        metadata={
            "applicationId": str(application.id),
            "versionId": str(version.id),
            "packageId": str(package.id),
            "version": version.version,
        },
        message="Application image build started.",
    )
    db.commit()

    db.refresh(build)

    # =====================================================
    # 9. BUILD DOCKER IMAGE
    # =====================================================

    try:

        result = build_docker_image(
            package_path=Path(
                package.stored_path
            ),
            manifest=version.manifest,
            image_ref=image_ref
        )

    except BuildError as error:

        build.status = "failed"

        build.build_log = str(
            error
        )

        build.finished_at = (
            datetime.now(
                timezone.utc
            )
        )

        version.status = (
            "build_failed"
        )

        record_audit_event(
            db=db,
            action="application.build.failed",
            resource_type="application_build",
            resource_id=build.id,
            publisher_id=publisher.id,
            actor_user_id=current_user.id,
            outcome="failed",
            metadata={
                "applicationId": str(application.id),
                "versionId": str(version.id),
                "packageId": str(package.id),
                "errorType": type(error).__name__,
            },
            message="Application image build failed.",
        )
        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Application build failed",

                "buildId":
                    str(build.id),

                "error":
                    str(error),
            }
        ) from error

    # =====================================================
    # 10. BUILD SUCCESS
    # =====================================================

    build.status = "ready"

    build.image_ref = result[
        "image_ref"
    ]

    build.build_log = result[
        "log"
    ]

    build.finished_at = (
        datetime.now(
            timezone.utc
        )
    )

    version.status = (
        "image_ready"
    )

    record_audit_event(
        db=db,
        action="application.build.succeeded",
        resource_type="application_build",
        resource_id=build.id,
        publisher_id=publisher.id,
        actor_user_id=current_user.id,
        metadata={
            "applicationId": str(application.id),
            "versionId": str(version.id),
            "packageId": str(package.id),
            "imageRef": build.image_ref,
            "versionStatus": version.status,
        },
        message="Application image build succeeded.",
    )
    db.commit()

    db.refresh(build)

    db.refresh(version)

    # C1-D2: automatically enqueue the exact ready image after a successful
    # build. A separate trusted worker owns the Docker smoke test.
    try:
        enqueue_ready_build(db, build=build, version=version)
        db.commit()
    except QualificationGateError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            'code': error.code,
            'message': 'Build ready but qualification could not be enqueued',
            'buildId': str(build.id),
        }) from error

    # =====================================================
    # 11. RESPONSE
    # =====================================================

    return {
        "status":
            "IMAGE_READY",

        "build": {
            "id":
                str(build.id),

            "status":
                build.status,

            "imageRef":
                build.image_ref,
        },

        "application": {
            "id":
                str(application.id),

            "name":
                application.name,

            "appKey":
                application.app_key,
        },

        "version":
            version.version,
    }

@router.get(
    "/builds/{build_id}"
)
def get_build(
    build_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    build = db.get(
        ApplicationBuild,
        build_id
    )

    if not build:

        raise HTTPException(
            status_code=404,
            detail="Build not found"
        )

    version = db.get(
        ApplicationVersion,
        build.application_version_id
    )

    if not version:

        raise HTTPException(
            status_code=409,
            detail=(
                "Build references a missing "
                "application version."
            )
        )

    application = db.get(
        Application,
        version.application_id
    )

    if not application:

        raise HTTPException(
            status_code=409,
            detail=(
                "Application version references "
                "a missing application."
            )
        )

    try:

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=application.publisher_id,
            permission_code="application.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    qualification_row = db.scalar(select(ApplicationBuildQualification).where(
        ApplicationBuildQualification.build_id == build.id))
    return {

        "id":
            str(build.id),

        "applicationVersionId":
            str(
                build.application_version_id
            ),

        "packageId":
            str(build.package_id),

        "status":
            build.status,

        "imageRef":
            build.image_ref,

        "startedAt":
            build.started_at,

        "finishedAt":
            build.finished_at,
        "qualificationStatus": qualification_row.status if qualification_row else None,
        "qualificationFailureCode": qualification_row.failure_code if qualification_row else None,
    }

@router.get(
    "/applications/{application_id}/versions"
)
def list_application_versions(
    application_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. APPLICATION
    # =====================================================

    application = db.get(
        Application,
        application_id,
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    # =====================================================
    # 2. PUBLISHER AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=application.publisher_id,
            permission_code="application.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. VERSIONS
    # =====================================================

    versions = list(
        db.scalars(
            select(ApplicationVersion)
            .where(
                ApplicationVersion.application_id
                == application.id
            )
            .order_by(
                ApplicationVersion.created_at.desc()
            )
        )
    )

    # =====================================================
    # 4. RESPONSE
    # =====================================================

    return {
        "application": {
            "id":
                str(application.id),

            "publisherId":
                str(application.publisher_id),

            "appKey":
                application.app_key,

            "name":
                application.name,

            "status":
                application.status,
        },

        "count":
            len(versions),

        "items": [
            {
                "id":
                    str(version.id),

                "version":
                    version.version,

                "status":
                    version.status,

                "publicationStatus":
                    version.publication_status,

                "buildType":
                    version.build_type,

                "deploymentMode":
                    version.deployment_mode,

                "createdAt":
                    version.created_at,
            }

            for version in versions
        ],
    }

@router.get(
    "/application-versions/{version_id}/static-content",
    response_class=HTMLResponse,
)
def get_static_application_content(
    version_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):
    version_row = db.get(
        ApplicationVersion,
        version_id
    )

    if not version_row:
        raise HTTPException(
            status_code=404,
            detail="Application version not found"
        )

    
    application = db.get(
        Application,
        version_row.application_id
    )

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application not found"
        )

    try:
        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=application.publisher_id,
            permission_code="application.manage",
        )
    except AuthorizationError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    if version_row.build_type != "static_web":
        raise HTTPException(
            status_code=409,
            detail="This application version is not a static web application"
        )

    package = db.scalar(
        select(ApplicationPackage)
        .where(
            ApplicationPackage.application_version_id == version_row.id
        )
        .order_by(
            ApplicationPackage.created_at.desc()
        )
    )

    if not package:
        raise HTTPException(
            status_code=404,
            detail="Static application package not found"
        )

    source_path = Path(
        package.stored_path
    )

    if not source_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Static application file is missing from package storage"
        )

    try:
        html = source_path.read_text(
            encoding="utf-8"
        )
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=422,
            detail="Stored static application is not valid UTF-8 HTML"
        ) from error

    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/application-versions/{version_id}"
)
def get_application_version(
    version_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. VERSION
    # =====================================================

    version = db.get(
        ApplicationVersion,
        version_id,
    )

    if not version:

        raise HTTPException(
            status_code=404,
            detail="Application version not found",
        )
    
    # =====================================================
    # 2. APPLICATION
    # =====================================================

    application = db.get(
        Application,
        version.application_id,
    )

    if not application:

        raise HTTPException(
            status_code=409,
            detail=(
                "Application version references "
                "a missing application."
            ),
        )

    # =====================================================
    # 3. PUBLISHER AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=application.publisher_id,
            permission_code="application.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 4. LATEST BUILD
    # =====================================================

    latest_build = db.scalar(
        select(ApplicationBuild)
        .where(
            ApplicationBuild.application_version_id
            == version.id
        )
        .order_by(
            ApplicationBuild.created_at.desc()
        )
    )

    # =====================================================
    # 4B. LATEST LINKED PACKAGE
    # =====================================================

    latest_package = db.scalar(
        select(ApplicationPackage)
        .where(
            ApplicationPackage.application_version_id
            == version.id
        )
        .order_by(
            ApplicationPackage.created_at.desc()
        )
    )

    # =====================================================
    # 5. RESPONSE
    # =====================================================

    return {
        "id":
            str(version.id),

        "application": {
            "id":
                str(application.id),

            "publisherId":
                str(application.publisher_id),

            "appKey":
                application.app_key,

            "name":
                application.name,
        },

        "version":
            version.version,

        "status":
            version.status,

        "publicationStatus":
            version.publication_status,

        "buildType":
            version.build_type,

        "deploymentMode":
            version.deployment_mode,

        "manifest":
            version.manifest,

        "package": (
            {
                "id":
                    str(latest_package.id),

                "status":
                    latest_package.status,

                "filename":
                    latest_package.original_filename,

                "sha256":
                    latest_package.sha256,

                "sizeBytes":
                    latest_package.size_bytes,
            }

            if latest_package

            else None
        ),

        "latestBuild": (
            {
                "id":
                    str(latest_build.id),

                "status":
                    latest_build.status,

                "imageRef":
                    latest_build.image_ref,

                "startedAt":
                    latest_build.started_at,

                "finishedAt":
                    latest_build.finished_at,
            }

            if latest_build

            else None
        ),

        "createdAt":
            version.created_at,
    }

@router.post(
    "/application-versions/{version_id}/publish"
)
def publish_application_version(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    version = db.get(
        ApplicationVersion,
        version_id
    )

    if not version:
        raise HTTPException(
            status_code=404,
            detail="Application version not found"
        )

    application = db.get(
        Application,
        version.application_id
    )

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application not found"
        )

    try:
        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=application.publisher_id,
            permission_code="application.manage",
        )
    except AuthorizationError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    build_type = str(
        version.build_type or ""
    ).lower()

    technical_status = str(
        version.status or ""
    ).lower()

    publication_status = str(
        version.publication_status or "draft"
    ).lower()

    if publication_status == "published":
        return {
            "status": "PUBLISHED",
            "versionId": str(version.id),
            "applicationId": str(application.id),
            "version": version.version,
            "buildType": version.build_type,
            "technicalStatus": version.status,
            "publicationStatus": version.publication_status,
            "applicationStatus": application.status,
        }

    # Preserve the previous lifecycle rule:
    # once retired, a version cannot be republished.
    if publication_status == "retired":
        raise HTTPException(
            status_code=409,
            detail=(
                "A retired application version "
                "cannot be published again."
            ),
        )

    required_state = (
        "validated"
        if build_type == "static_web"
        else "image_ready"
    )

    if technical_status != required_state:
        raise HTTPException(
            status_code=409,
            detail=(
                "Application version cannot be published "
                f"from technical status '{version.status}'. "
                f"Required technical status: {required_state}."
            ),
        )

    # C1-D2: fail closed on new, not-yet-published Docker versions.
    # Already-published versions returned earlier, protecting existing tenants.
    try:
        require_passing_build(db, version=version)
    except QualificationGateError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            'code': error.code,
            'message': 'A passing immutable-build qualification is required before publication',
        }) from error

    other_published_versions = list(
        db.scalars(
            select(
                ApplicationVersion
            )
            .where(
                ApplicationVersion.application_id
                == application.id,

                ApplicationVersion.id
                != version.id,

                ApplicationVersion.publication_status
                == "published",
            )
        )
    )

    for other_version in other_published_versions:
        other_version.publication_status = "retired"

    # Flush retirement first so the partial unique index
    # cannot see two published versions during this transition.
    if other_published_versions:
        db.flush()

    version.publication_status = "published"
    application.status = "published"

    for superseded_version in other_published_versions:
        record_audit_event(
            db=db,
            action="application.version.retired",
            resource_type="application_version",
            resource_id=superseded_version.id,
            publisher_id=application.publisher_id,
            actor_user_id=current_user.id,
            metadata={
                "applicationId": str(application.id),
                "version": superseded_version.version,
                "reason": "superseded",
                "replacementVersionId": str(version.id),
            },
            message="Previously published version superseded.",
        )

    record_audit_event(
        db=db,
        action="application.version.published",
        resource_type="application_version",
        resource_id=version.id,
        publisher_id=application.publisher_id,
        actor_user_id=current_user.id,
        metadata={
            "applicationId": str(application.id),
            "version": version.version,
            "buildType": version.build_type,
            "previousPublicationStatus": publication_status,
            "publicationStatus": "published",
        },
        message="Application version published.",
    )
    db.commit()

    db.refresh(version)
    db.refresh(application)

    return {
        "status": "PUBLISHED",
        "versionId": str(version.id),
        "applicationId": str(application.id),
        "version": version.version,
        "buildType": version.build_type,
        "technicalStatus": version.status,
        "publicationStatus": version.publication_status,
        "applicationStatus": application.status,
    }


@router.post(
    "/application-versions/{version_id}/retire"
)
def retire_application_version(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    version = db.get(
        ApplicationVersion,
        version_id
    )

    if not version:
        raise HTTPException(
            status_code=404,
            detail="Application version not found"
        )

    application = db.get(
        Application,
        version.application_id
    )

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application not found"
        )

    try:
        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=application.publisher_id,
            permission_code="application.manage",
        )
    except AuthorizationError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    publication_status = str(
        version.publication_status or "draft"
    ).lower()

    if publication_status == "retired":
        return {
            "status": "RETIRED",
            "versionId": str(version.id),
            "applicationId": str(application.id),
            "version": version.version,
            "technicalStatus": version.status,
            "publicationStatus": version.publication_status,
            "applicationStatus": application.status,
        }

    if publication_status != "published":
        raise HTTPException(
            status_code=409,
            detail=(
                "Only a published application "
                "version can be retired."
            )
        )

    version.publication_status = "retired"

    remaining_published = db.scalar(
        select(
            ApplicationVersion
        )
        .where(
            ApplicationVersion.application_id
                == application.id,

            ApplicationVersion.id
                != version.id,

            ApplicationVersion.publication_status
                == "published",
        )
    )

    if remaining_published:
        application.status = "published"
    else:
        application.status = "retired"

    record_audit_event(
        db=db,
        action="application.version.retired",
        resource_type="application_version",
        resource_id=version.id,
        publisher_id=application.publisher_id,
        actor_user_id=current_user.id,
        metadata={
            "applicationId": str(application.id),
            "version": version.version,
            "reason": "manual",
            "previousPublicationStatus": publication_status,
            "publicationStatus": "retired",
        },
        message="Application version retired.",
    )
    db.commit()

    db.refresh(version)
    db.refresh(application)

    return {
        "status": "RETIRED",
        "versionId": str(version.id),
        "applicationId": str(application.id),
        "version": version.version,
        "technicalStatus": version.status,
        "publicationStatus": version.publication_status,
        "applicationStatus": application.status,
    }

