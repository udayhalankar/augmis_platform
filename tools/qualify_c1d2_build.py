"""Trusted-operator local C1-D2 disposable smoke test; NOT a public API.

Usage: python tools/qualify_c1d2_build.py --application-key augmis-asset-checkout-lab --execute
Only a ready, immutable image for an existing AUGMIS build is accepted.
Never run inside a web request; qualification is a local operator operation.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from sqlalchemy import select
from services.api.app.db.session import SessionLocal
from services.api.app.models.platform import Application, ApplicationBuild, ApplicationVersion
from services.api.app.services.deployment_reliability import (
    record_pending_qualification, record_smoke_result, valid_qualification, ReliabilityError,
)
from services.api.app.services.c1d2_disposable_qualification import (
    DisposableQualification, RuntimeImages, QualificationFailure,
)
from services.api.app.services.runtime_controls_service import pinned_image_identity
from services.api.app.core.runtime_host import read_profile
from services.api.app.core.config import settings

REVISION = 'c1d2-disposable-1'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--application-key', required=True)
    parser.add_argument('--execute', action='store_true', help='Create and automatically remove disposable Docker resources')
    args = parser.parse_args()
    if str(settings.app_env).lower() not in {'dev', 'development'}:
        raise SystemExit('STOP: C1D2_DEVELOPMENT_ONLY')
    profile = read_profile()
    if profile is None:
        raise SystemExit('STOP: C1D2_DURABLE_PROFILE_REQUIRED')
    if not args.execute:
        print('DRY RUN: no Docker, database or qualification records created. Use --execute for live smoke.')
        return
    with SessionLocal() as db:
        apps = list(db.scalars(select(Application).where(Application.app_key == args.application_key)))
        if len(apps) != 1:
            raise SystemExit('STOP: C1D2_APPLICATION_NOT_FOUND')
        app = apps[0]
        versions = list(db.scalars(select(ApplicationVersion).where(
            ApplicationVersion.application_id == app.id,
            ApplicationVersion.publication_status == 'published'
        ).order_by(ApplicationVersion.created_at.desc())))
        if not versions:
            raise SystemExit('STOP: C1D2_NO_PUBLISHED_VERSION')
        version = versions[0]
        builds = list(db.scalars(select(ApplicationBuild).where(
            ApplicationBuild.application_version_id == version.id,
            ApplicationBuild.status == 'ready'
        ).order_by(ApplicationBuild.finished_at.desc())))
        if not builds:
            raise SystemExit('STOP: C1D2_NO_READY_BUILD')
        build = builds[0]
        if (version.manifest.get('metadata') or {}).get('id') != app.app_key:
            raise SystemExit('STOP: C1D2_APPLICATION_MANIFEST_MISMATCH')
        try:
            # Existing service pins immutable identity and rejects changed tags.
            image_id = pinned_image_identity(db, build)
            runner = DisposableQualification(
                manifest=version.manifest, image_id=image_id,
                images=RuntimeImages(
                    postgres_image_id=profile.environment['AUGMIS_C1B_POSTGRES_IMAGE_ID'],
                    relay_image_id=profile.environment['AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID'],
                    ingress_network=profile.environment['AUGMIS_C1B_CRUD_INGRESS_NETWORK'],
                ),
            )
            row = record_pending_qualification(db, build_id=build.id,
                version_id=version.id, image_id=image_id, manifest=version.manifest)
            if valid_qualification(row, build_id=build.id, version_id=version.id,
                                   image_id=image_id, manifest=version.manifest):
                print('PASS: previously qualified exact build; no new resources created')
                return
            if row.status != 'pending_smoke':
                raise QualificationFailure('C1D2_QUALIFICATION_NOT_PENDING')
            row.started_at = datetime.now(timezone.utc)
            db.commit()
        except (ReliabilityError, QualificationFailure, ValueError) as exc:
            db.rollback()
            raise SystemExit(f'STOP: {getattr(exc, "code", "C1D2_PRECHECK_FAILED")}') from exc

        checks = None
        failure = None
        try:
            checks = runner.run()
        except QualificationFailure as exc:
            failure = exc.code
        except Exception:
            failure = 'C1D2_UNEXPECTED_SMOKE_FAILURE'
        try:
            record_smoke_result(db, build_id=build.id, version_id=version.id,
                image_id=image_id, manifest=version.manifest, qualifier_revision=REVISION,
                checks=checks if checks is not None else {
                    'image_identity': False, 'database_isolation': False,
                    'schema_rls': False, 'internal_health': False,
                    'gateway_auth': False, 'gateway_rejection': False,
                }, failure_code=failure)
            db.commit()
        except Exception:
            db.rollback()
            raise SystemExit('STOP: C1D2_QUALIFICATION_PERSISTENCE_FAILED')
        if failure:
            raise SystemExit('FAIL: ' + failure)
        print('PASS: C1-D2 disposable PostgreSQL + signed relay qualification recorded')
        print('Build:', str(build.id), 'Version:', version.version)
        print('Database, application and relay test resources automatically removed.')
        print('NOTE: Publication/deployment gates are NOT active; stage C1-D2 remains incomplete.')


if __name__ == '__main__':
    main()
