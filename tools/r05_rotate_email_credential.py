"""R05 controlled, audited, one-row SMTP ciphertext re-encryption.

No database or key mutation on import. Read-only by default. Operators must
verify a protected, restorable DB backup before separately authorizing --apply.
Never prints plaintext, ciphertext, key material, or connection strings.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import select

_BACKUP_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{3,127}\Z")
_CONFIRM = "ROTATE_PLATFORM_EMAIL_CREDENTIAL"


class RotationDenied(RuntimeError):
    pass


def prepare_ciphertext(ciphertext: str, *, keyring: MultiFernet, active: Fernet) -> str | None:
    """Pure transform; None means ciphertext already readable by active key.

    Verifies existing keyring access and active-key-only access before storing.
    """
    if not isinstance(ciphertext, str) or not ciphertext:
        raise RotationDenied("R05_CREDENTIAL_MISSING")
    value = ciphertext.encode("ascii")
    try:
        old_plaintext = keyring.decrypt(value)
        try:
            if active.decrypt(value) == old_plaintext:
                return None
        except InvalidToken:
            pass
        rotated = keyring.rotate(value)
        if active.decrypt(rotated) != old_plaintext:
            raise RotationDenied("R05_ROTATION_VERIFICATION_FAILED")
        return rotated.decode("ascii")
    except (InvalidToken, UnicodeError, ValueError):
        raise RotationDenied("R05_CREDENTIAL_KEYRING_DENIED") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R05 platform SMTP credential re-encryption")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Read-only inspection")
    mode.add_argument("--apply", action="store_true", help="Audited transactional DB update")
    parser.add_argument("--backup-reference", default="", help="Reference to verified, restorable protected DB backup")
    parser.add_argument("--confirm", default="", help="Explicit rotation acknowledgement")
    args = parser.parse_args(argv)

    # Keep import side effects out of pure unit tests.
    from services.api.app.core.config import settings
    from services.api.app.db.session import SessionLocal
    from services.api.app.models.platform_settings import PlatformEmailSettings
    from services.api.app.services.platform_settings_service import _fernet
    from services.api.app.services.audit_service import record_audit_event

    if args.apply:
        if str(settings.app_env).strip().lower() not in ("production", "prod") or os.name != "posix":
            raise RotationDenied("R05_PRODUCTION_LINUX_REQUIRED")
        if args.confirm != _CONFIRM or not _BACKUP_REF.fullmatch(args.backup_reference):
            raise RotationDenied("R05_VERIFIED_BACKUP_AND_APPROVAL_REQUIRED")

    db = SessionLocal()
    try:
        lookup = select(PlatformEmailSettings).where(PlatformEmailSettings.id == 1)
        if args.apply:
            lookup = lookup.with_for_update()
        row = db.scalar(lookup)
        if row is None or not row.credential_ciphertext:
            print("R05_EMAIL_CREDENTIAL_ABSENT: no change")
            return 0
        keyring = _fernet()
        active = Fernet(str(settings.settings_encryption_key).encode("ascii"))
        candidate = prepare_ciphertext(row.credential_ciphertext, keyring=keyring, active=active)
        if candidate is None:
            print("R05_EMAIL_ALREADY_ACTIVE_KEY: no change")
            return 0
        if args.dry_run:
            print("R05_EMAIL_REENCRYPTION_REQUIRED: read-only check complete")
            return 0

        row.credential_ciphertext = candidate
        record_audit_event(
            db,
            action="platform.settings.credential.reencrypted",
            resource_type="platform_email_settings",
            resource_id="1",
            outcome="success",
            message="Platform email credential encrypted under the approved active key.",
            metadata={"backupReference": args.backup_reference, "operation": "R05_credential_key_rotation"},
        )
        db.flush()
        # Ensure newly-persisted candidate remains independently readable by active key.
        active.decrypt(row.credential_ciphertext.encode("ascii"))
        db.commit()
        print("R05_EMAIL_REENCRYPTED_AND_AUDITED")
        return 0
    except Exception:
        db.rollback()
        # Do not leak secret-provider, SQL or cryptographic exceptions.
        raise RotationDenied("R05_ROTATION_ABORTED_ROLLED_BACK") from None
    finally:
        db.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RotationDenied as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
