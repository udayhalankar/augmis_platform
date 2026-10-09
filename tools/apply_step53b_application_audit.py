"""AUGMIS Phase 5, Step 53B: guarded, atomic patch to existing applications.py.

Run from AUGMIS_PLATFORM repo root:
    python tools/apply_step53b_application_audit.py --check
    python tools/apply_step53b_application_audit.py

No partial writes: the module is modified only after all anchors and syntax checks pass.
"""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import tempfile

ROUTE = Path("services/api/app/routes/applications.py")
SIGNATURE = 'action="application.package.uploaded"'


def replace_once(s: str, old: str, new: str, step: str) -> str:
    n = s.count(old)
    if n != 1:
        raise ValueError(f"{step}: expected exactly one anchor, found {n}. No files changed.")
    return s.replace(old, new, 1)


def transform_section(source: str, func: str, transform):
    signature = f"def {func}("
    start = source.find(signature)
    if start < 0:
        raise ValueError(f"Function {func} not found. No files changed.")
    end = source.find("\n@router.", start)
    if end < 0:
        end = len(source)
    original = source[start:end]
    changed = transform(original)
    return source[:start] + changed + source[end:]


def apply(source: str) -> str:
    if SIGNATURE in source:
        raise ValueError("Step 53B application audit appears already applied. No files changed.")

    source = replace_once(
        source,
        'from services.api.app.services.build_engine import (\n',
        'from services.api.app.services.audit_service import record_audit_event\n\n'
        'from services.api.app.services.build_engine import (\n',
        'Add existing shared audit writer import',
    )

    def zip_upload(s):
        s = replace_once(s,
            '    db.add(package)\n\n    db.commit()',
            '''    db.add(package)

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
    db.commit()''', 'Zip: upload committed')
        s = replace_once(s,
            '    db.add(validation_run)\n\n    db.commit()',
            '''    db.add(validation_run)

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
    db.commit()''', 'Zip: validation started')
        s = replace_once(s,
            '''        validation_run.errors = [
            str(error)
        ]

        db.commit()''',
            '''        validation_run.errors = [
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
        db.commit()''', 'Zip: validation failed')
        s = replace_once(s,
            '    if not application:\n\n        application = Application(',
            '    new_application = application is None\n'
            '    previous_application_details = (\n'
            '        (application.name, application.description)\n'
            '        if application is not None else None\n'
            '    )\n\n'
            '    if not application:\n\n        application = Application(',
            'Zip: new application flag')
        s = replace_once(s,
            '''    validation_run.errors = []

    db.commit()''',
            '''    validation_run.errors = []

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
    db.commit()''', 'Zip: final version validated')
        return s

    source = transform_section(source, "upload_application", zip_upload)

    def static_upload(s):
        s = replace_once(s,
            '''        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Static application package "
                    "validation failed",''',
            '''        # No database package record exists on this failure path.
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
                    "validation failed",''', 'Static: validation rejection audit')
        s = replace_once(s,
            '    if not application:\n\n        application = Application(',
            '    new_application = application is None\n'
            '    previous_application_details = (\n'
            '        (application.name, application.description)\n'
            '        if application is not None else None\n'
            '    )\n\n'
            '    if not application:\n\n        application = Application(',
            'Static: new application flag')
        s = replace_once(s,
            '''        db.rollback()


        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Static application package "
                    "extraction failed",''',
            '''        db.rollback()

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
                    "extraction failed",''', 'Static: extraction failure audit')
        s = replace_once(s,
            '''    db.add(
        validation_run
    )


    db.commit()''',
            '''    db.add(
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
    db.commit()''', 'Static: commit registered version/package')
        return s

    source = transform_section(source, "upload_static_application", static_upload)

    def build(s):
        s = replace_once(s,
            '''    db.add(build)

    db.commit()''',
            '''    db.add(build)
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
    db.commit()''', 'Build: started')
        s = replace_once(s,
            '''        version.status = (
            "build_failed"
        )

        db.commit()''',
            '''        version.status = (
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
        db.commit()''', 'Build: failed')
        s = replace_once(s,
            '''    version.status = (
        "image_ready"
    )

    db.commit()''',
            '''    version.status = (
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
    db.commit()''', 'Build: succeeded')
        return s

    source = transform_section(source, "build_application_package", build)

    def publish(s):
        s = replace_once(s,
            '''    version.publication_status = "published"
    application.status = "published"

    db.commit()''',
            '''    version.publication_status = "published"
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
    db.commit()''', 'Publication: published / automatic retirement')
        return s

    source = transform_section(source, "publish_application_version", publish)

    def retire(s):
        s = replace_once(s,
            '''    db.commit()

    db.refresh(version)
    db.refresh(application)''',
            '''    record_audit_event(
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
    db.refresh(application)''', 'Publication: manual retirement')
        return s

    source = transform_section(source, "retire_application_version", retire)

    ast.parse(source, filename=str(ROUTE))
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate all anchors and syntax without modifying the file")
    parser.add_argument("--source", type=Path, default=ROUTE, help="Route path (default: repository location)")
    args = parser.parse_args()

    path = args.source
    if not path.is_file():
        parser.error(f"Route file missing: {path}")
    raw = path.read_bytes()
    newline = "\r\n" if raw.count(b"\r\n") > raw.count(b"\n") // 2 else "\n"
    original = raw.decode("utf-8").replace("\r\n", "\n")
    updated = apply(original)
    if args.check:
        print("PASS: all Step 53B anchors matched; proposed application route parses; no file changed.")
        return

    # Atomic filesystem replace prevents partial modifications on failure.
    fd, temp_path = tempfile.mkstemp(prefix=".augmis_step53b_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(updated.replace("\n", newline))
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    print(f"PASS: Step 53B application audit changes applied to {path}")
    print("Inspect git diff, compile, and run application lifecycle regression tests before committing.")


if __name__ == "__main__":
    main()
