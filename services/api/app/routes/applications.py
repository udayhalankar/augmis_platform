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
    ApplicationValidationRun,
    ApplicationVersion,
    Publisher
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