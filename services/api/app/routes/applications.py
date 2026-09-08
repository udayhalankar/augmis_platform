from __future__ import annotations

import shutil
import uuid
import zipfile

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile
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


@router.post(
    "/publishers/{publisher_id}/applications/upload",
    status_code=201
)
def upload_application(
    publisher_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
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
        status="validated"
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
            "id": str(app.id),
            "publisherId":
                str(app.publisher_id),

            "appKey":
                app.app_key,

            "name":
                app.name,

            "description":
                app.description,

            "status":
                app.status
        }
        for app in applications
    ]
@router.post(
    "/application-packages/{package_id}/build",
    status_code=201
)
def build_application_package(
    package_id: uuid.UUID,
    db: Session = Depends(get_db)
):

    package = db.get(
        ApplicationPackage,
        package_id
    )

    if not package:

        raise HTTPException(
            status_code=404,
            detail="Application package not found"
        )

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

    version = db.get(
        ApplicationVersion,
        package.application_version_id
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

    publisher = db.get(
        Publisher,
        application.publisher_id
    )

    if not publisher:

        raise HTTPException(
            status_code=404,
            detail="Publisher not found"
        )

    image_ref = (
        f"augmis.local/"
        f"{publisher.slug}/"
        f"{application.app_key}:"
        f"{version.version}"
    )

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
                    str(error)
            }
        )

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

    version.status = "image_ready"

    db.commit()

    return {

        "status": "IMAGE_READY",

        "build": {
            "id": str(build.id),

            "status":
                build.status,

            "imageRef":
                build.image_ref
        },

        "application": {
            "id":
                str(application.id),

            "name":
                application.name,

            "appKey":
                application.app_key
        },

        "version":
            version.version
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