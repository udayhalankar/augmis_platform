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

from services.api.app.services.build_engine import (
    BuildError,
    build_docker_image
)

from tools.validate_package import (
    PackageValidationError,
    validate_application_package
)


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

    db.commit()

    validation_run = (
        ApplicationValidationRun(
            package_id=package.id,
            status="running"
        )
    )

    db.add(validation_run)

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
    publisher = db.get(
        Publisher,
        publisher_id
    )

    if not publisher:
        raise HTTPException(
            status_code=404,
            detail="Publisher not found"
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
        ) from error

    clean_name = str(app_name or "").strip()
    clean_key = str(app_key or "").strip().lower()
    clean_version = str(version or "").strip()
    clean_description = str(description or "").strip()

    if not clean_name:
        raise HTTPException(
            status_code=400,
            detail="Application name is required"
        )

    if not STATIC_APP_KEY.fullmatch(clean_key):
        raise HTTPException(
            status_code=400,
            detail=(
                "App key must contain only lowercase letters, numbers "
                "and hyphens, and must start/end with a letter or number"
            )
        )

    if not STATIC_VERSION.fullmatch(clean_version):
        raise HTTPException(
            status_code=400,
            detail="Version must use semantic version format, for example 1.0.0"
        )

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Filename is required"
        )

    lower_filename = file.filename.lower()

    if not (
        lower_filename.endswith(".html")
        or lower_filename.endswith(".htm")
    ):
        raise HTTPException(
            status_code=400,
            detail="Static web upload currently accepts only .html or .htm files"
        )

    existing_application = db.scalar(
        select(Application)
        .where(
            Application.publisher_id == publisher.id,
            Application.app_key == clean_key,
        )
    )

    if existing_application:
        existing_version = db.scalar(
            select(ApplicationVersion)
            .where(
                ApplicationVersion.application_id == existing_application.id,
                ApplicationVersion.version == clean_version,
            )
        )

        if existing_version:
            raise HTTPException(
                status_code=409,
                detail="This application version already exists"
            )

    package_id = uuid.uuid4()

    quarantine_path = (
        settings.package_storage_root
        / "quarantine"
        / f"{package_id}.html"
    )

    size_bytes = save_upload(
        file,
        quarantine_path
    )

    try:
        _, sha256 = validate_static_html_file(
            quarantine_path
        )
    except HTTPException:
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
            / f"{package_id}.html"
        )

        shutil.move(
            str(quarantine_path),
            str(rejected_path)
        )

        raise

    application = existing_application

    if not application:
        application = Application(
            publisher_id=publisher.id,
            app_key=clean_key,
            name=clean_name,
            description=clean_description or None,
            status="validated",
        )

        db.add(application)
        db.flush()
    else:
        application.name = clean_name
        application.description = (
            clean_description or None
        )

    manifest = {
        "metadata": {
            "id": clean_key,
            "name": clean_name,
            "description": clean_description,
            "version": clean_version,
        },
        "runtime": {
            "buildType": "static_web",
            "deploymentMode": "static",
            "entryFile": "index.html",
        },
    }

    version_row = ApplicationVersion(
        application_id=application.id,
        version=clean_version,
        deployment_mode="static",
        build_type="static_web",
        manifest=manifest,
        status="validated",
        publication_status="draft",
    )

    db.add(version_row)
    db.flush()

    validated_path = (
        settings.package_storage_root
        / "validated"
        / publisher.slug
        / clean_key
        / clean_version
        / f"{sha256}.html"
    )

    validated_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    shutil.move(
        str(quarantine_path),
        str(validated_path)
    )

    package = ApplicationPackage(
        id=package_id,
        publisher_id=publisher.id,
        application_version_id=version_row.id,
        original_filename=file.filename,
        stored_path=str(validated_path),
        size_bytes=size_bytes,
        sha256=sha256,
        status="validated",
    )

    db.add(package)
    db.flush()

    validation_run = ApplicationValidationRun(
        package_id=package.id,
        status="valid",
        errors=[],
    )

    db.add(validation_run)
    db.commit()

    return {
        "status": "VALIDATED",
        "publisher": {
            "id": str(publisher.id),
            "name": publisher.name,
        },
        "application": {
            "id": str(application.id),
            "appKey": application.app_key,
            "name": application.name,
        },
        "version": {
            "id": str(version_row.id),
            "version": version_row.version,
            "buildType": version_row.build_type,
            "deploymentMode": version_row.deployment_mode,
        },
        "package": {
            "id": str(package.id),
            "sha256": package.sha256,
            "sizeBytes": package.size_bytes,
            "status": package.status,
        },
    }


# =========================================================
# LIST APPLICATIONS
# =========================================================

@router.get(
    "/applications"
)
def list_applications(
    db: Session = Depends(get_db)
):

    applications = list(
        db.scalars(
            select(Application)
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

    db.commit()

    db.refresh(build)

    db.refresh(version)

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
    db: Session = Depends(get_db)
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
            build.finished_at
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

