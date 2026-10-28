"""R08: encrypted logical PostgreSQL backups and offline disposable restore probe.

Operator CLI, development acceptance only. Does not run on import. No plaintext
archive is written to disk and restore never targets a provisioned database.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"AUGMIS-R08-GCM-1\n"
CHUNK = 1024 * 1024
SHA256_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
SCOPES = {"platform", "application"}

class R08Error(Exception):
    pass


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _key(password: str, salt: bytes) -> bytes:
    if len(password) < 16:
        raise R08Error("R08_BACKUP_PASSPHRASE_TOO_SHORT")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode("utf-8"))


def _password(*, confirm: bool = False) -> str:
    value = getpass.getpass("R08 backup passphrase (never put it in command arguments): ")
    if confirm and value != getpass.getpass("Repeat R08 backup passphrase: "):
        raise R08Error("R08_BACKUP_PASSPHRASE_MISMATCH")
    return value


def _header(meta: dict, salt: bytes, nonce: bytes) -> bytes:
    content = _json({**meta, "salt": base64.b64encode(salt).decode("ascii"),
                     "nonce": base64.b64encode(nonce).decode("ascii")})
    if len(content) > 16_384:
        raise R08Error("R08_HEADER_OVERSIZE")
    return MAGIC + len(content).to_bytes(4, "big") + content


def read_header(f):
    magic = f.read(len(MAGIC))
    if magic != MAGIC:
        raise R08Error("R08_INVALID_ARCHIVE_MAGIC")
    raw_len = f.read(4)
    if len(raw_len) != 4:
        raise R08Error("R08_HEADER_TRUNCATED")
    length = int.from_bytes(raw_len, "big")
    if not 30 <= length <= 16_384:
        raise R08Error("R08_HEADER_LENGTH_INVALID")
    value = f.read(length)
    if len(value) != length:
        raise R08Error("R08_HEADER_TRUNCATED")
    try:
        metadata = json.loads(value)
        salt = base64.b64decode(metadata["salt"], validate=True)
        nonce = base64.b64decode(metadata["nonce"], validate=True)
    except (ValueError, KeyError, TypeError) as exc:
        raise R08Error("R08_HEADER_INVALID") from exc
    if len(salt) != 16 or len(nonce) != 12 or metadata.get("scope") not in SCOPES:
        raise R08Error("R08_HEADER_FIELDS_INVALID")
    return MAGIC + raw_len + value, metadata, salt, nonce


def seal_stream(source, out: Path, password: str, metadata: dict) -> dict:
    """Encrypt streaming binary pg_dump; atomic publication; never plaintext on disk."""
    if out.exists():
        raise R08Error("R08_OUTPUT_EXISTS")
    out.parent.mkdir(parents=True, exist_ok=True)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    prefix = _header(metadata, salt, nonce)
    cipher = Cipher(algorithms.AES(_key(password, salt)), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(prefix)
    tmp = out.with_name(out.name + "." + uuid.uuid4().hex + ".partial")
    total = 0
    h = hashlib.sha256()
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as dst:
            dst.write(prefix); h.update(prefix)
            start = source.read(5)
            if start != b"PGDMP":
                raise R08Error("R08_SOURCE_NOT_CUSTOM_PGDUMP")
            chunk = start
            while chunk:
                total += len(chunk)
                encrypted = cipher.update(chunk)
                dst.write(encrypted); h.update(encrypted)
                chunk = source.read(CHUNK)
            suffix = cipher.finalize() + cipher.tag
            dst.write(suffix); h.update(suffix)
            dst.flush(); os.fsync(dst.fileno())
        os.replace(tmp, out)
        return {"archive_sha256": h.hexdigest(), "plaintext_bytes": total,
                "ciphertext_bytes": out.stat().st_size, **metadata}
    finally:
        tmp.unlink(missing_ok=True)


def open_authenticated(path: Path, password: str, sink=None) -> dict:
    """Authenticate entire archive before any restore process is started."""
    with path.open("rb") as source:
        prefix, meta, salt, nonce = read_header(source)
        pos = source.tell()
        size = path.stat().st_size
        if size - pos < 5 + 16:
            raise R08Error("R08_ARCHIVE_TRUNCATED")
        source.seek(-16, os.SEEK_END)
        tag = source.read(16)
        source.seek(pos)
        dec = Cipher(algorithms.AES(_key(password, salt)), modes.GCM(nonce, tag)).decryptor()
        dec.authenticate_additional_data(prefix)
        remaining = size - pos - 16
        first = True
        valid_pg_signature = True
        plain_count = 0
        while remaining:
            payload = source.read(min(CHUNK, remaining))
            if not payload:
                raise R08Error("R08_ARCHIVE_TRUNCATED")
            remaining -= len(payload)
            plaintext = dec.update(payload)
            if first:
                valid_pg_signature = plaintext.startswith(b"PGDMP")
                first = False
            if sink is not None:
                sink.write(plaintext)
            plain_count += len(plaintext)
        try:
            dec.finalize()
        except InvalidTag as exc:
            raise R08Error("R08_INTEGRITY_OR_KEY_FAILURE") from exc
        if not valid_pg_signature:
            raise R08Error("R08_INVALID_PGDUMP_SIGNATURE")
        if sink is not None:
            sink.flush()
        return {**meta, "verified_plaintext_bytes": plain_count}


def _run(args, *, input_data=None) -> str:
    p = subprocess.run(args, input=input_data, stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, check=False)
    if p.returncode != 0:
        raise R08Error("R08_EXTERNAL_COMMAND_FAILED")
    return p.stdout.decode("utf-8", errors="replace").strip()


def _dev_db():
    from services.api.app.core.config import settings
    if str(settings.app_env).lower() not in {"dev", "development", "local", "test"}:
        raise R08Error("R08_DEVELOPMENT_SCOPE_ONLY")
    from services.api.app.db.session import SessionLocal
    return SessionLocal


def _db_resource(instance_id: uuid.UUID):
    from sqlalchemy import select
    from services.api.app.models.runtime_control import ApplicationDatabaseResource
    session = _dev_db()
    with session() as db:
        rows = list(db.scalars(select(ApplicationDatabaseResource).where(
            ApplicationDatabaseResource.instance_id == instance_id)))
        if len(rows) != 1:
            raise R08Error("R08_INSTANCE_RESOURCE_NOT_UNIQUE")
        row = rows[0]
        attrs = ("id", "instance_id", "tenant_id", "status", "engine", "engine_version",
                 "database_name", "container_name", "data_volume", "bootstrap_secret_volume",
                 "runtime_secret_volume", "network_name", "database_image_id")
        return {a: str(getattr(row, a)) for a in attrs}


def inventory():
    from sqlalchemy import select
    from services.api.app.models.runtime_control import ApplicationDatabaseResource
    session = _dev_db()
    with session() as db:
        rows = list(db.scalars(select(ApplicationDatabaseResource)))
        print("PLATFORM DB: configured (credentials not displayed)")
        print("APPLICATION DATABASE RESOURCES:", len(rows))
        for row in rows:
            print("instance:", row.instance_id, "resource:", row.id,
                  "status:", row.status, "engine:", row.engine,
                  "PG image pinned:", bool(row.database_image_id))
    print("READ ONLY; zero Docker or DB mutations")


def _assert_container(row: dict):
    name = row["container_name"]
    raw = _run(["docker", "inspect", "--type", "container", name])
    obj = json.loads(raw)[0]
    labels = obj["Config"].get("Labels") or {}
    if labels.get("augmis.managed") != "true" or labels.get("augmis.database_instance_id") != row["instance_id"]:
        raise R08Error("R08_DATABASE_OWNER_MISMATCH")
    if not obj["State"].get("Running"):
        raise R08Error("R08_DATABASE_CONTAINER_NOT_RUNNING")
    if obj.get("Image") != row["database_image_id"] or not SHA256_ID.fullmatch(row["database_image_id"]):
        raise R08Error("R08_DATABASE_IMAGE_MISMATCH")
    mounts = {m.get("Destination"): m.get("Name") for m in obj.get("Mounts", [])}
    if mounts.get("/var/lib/postgresql/data") != row["data_volume"] or mounts.get("/run/bootstrap") != row["bootstrap_secret_volume"]:
        raise R08Error("R08_DATABASE_MOUNT_MISMATCH")
    if set(obj.get("NetworkSettings", {}).get("Networks", {})) != {row["network_name"]}:
        raise R08Error("R08_DATABASE_NETWORK_MISMATCH")
    return name


def _platform_dump_command(binary: str):
    from sqlalchemy.engine import make_url
    from services.api.app.core.config import settings
    url = make_url(settings.database_url)
    if not url.host or not url.database or not url.username:
        raise R08Error("R08_PLATFORM_DATABASE_URL_INCOMPLETE")
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    if "sslmode" in url.query:
        env["PGSSLMODE"] = str(url.query["sslmode"])
    cmd = [binary, "-Fc", "--no-owner", "--no-acl", "-w", "-h", url.host,
           "-p", str(url.port or 5432), "-U", url.username, "-d", url.database]
    return cmd, env, url.database


def _backup(args):
    if not args.execute:
        raise R08Error("R08_EXPLICIT_EXECUTE_REQUIRED")
    _dev_db()
    out = Path(args.out).resolve()
    repo = Path(__file__).resolve().parents[1]
    if out.is_relative_to(repo):
        raise R08Error("R08_BACKUP_MUST_BE_OUTSIDE_REPO")
    if out.exists() or out.with_suffix(out.suffix + ".json").exists():
        raise R08Error("R08_OUTPUT_EXISTS")
    meta = {"schema": "augmis.r08.backup.v1", "created_utc": _utc(),
            "scope": args.scope, "format": "pg_dump.custom", "encryption": "AES-256-GCM+Scrypt"}
    if args.scope == "application":
        if not args.instance_id:
            raise R08Error("R08_INSTANCE_ID_REQUIRED")
        row = _db_resource(uuid.UUID(args.instance_id))
        if row["status"] != "ready" or row["engine"] != "postgresql" or row["engine_version"] != "15":
            raise R08Error("R08_APP_DATABASE_NOT_READY")
        container = _assert_container(row)
        meta.update({"instance_id": row["instance_id"], "tenant_id": row["tenant_id"],
                     "resource_id": row["id"], "database": row["database_name"],
                     "postgres_image": row["database_image_id"]})
        cmd = ["docker", "exec", "--user", "postgres", container, "pg_dump", "-Fc", "--no-owner",
               "--no-acl", "-w", "-U", "postgres", "-d", row["database_name"]]
        env = os.environ.copy()
    else:
        cmd, env, db_name = _platform_dump_command(args.pg_dump)
        meta.update({"database": db_name})
    secret = _password(confirm=True)
    started = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    try:
        with proc.stdout:
            receipt = seal_stream(proc.stdout, out, secret, meta)
        if proc.wait(timeout=120) != 0:
            raise R08Error("R08_PGDUMP_FAILED")
        open_authenticated(out, secret)  # cryptographic self-check
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 2)
        receipt_path = out.with_suffix(out.suffix + ".json")
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
        print("PASS encrypted backup and authentication")
        print("SCOPE", args.scope, "CIPHERTEXT", out, "SHA256", receipt["archive_sha256"])
        print("RECEIPT", receipt_path, "ELAPSED_SECONDS", receipt["elapsed_seconds"])
    except Exception:
        proc.kill(); proc.wait()
        out.unlink(missing_ok=True)
        raise


def _isolated_restore_role(metadata: dict) -> str | None:
    """Resolve only AUGMIS's deterministic app role for a scratch restore.

    The backup contains RLS CREATE POLICY ... TO <instance role> statements.
    pg_dump -Fc --no-owner --no-acl does not remove those policy references.
    A freshly initialized PostgreSQL cluster lacks the role; create a NOLOGIN
    placeholder *in the disposable cluster only* so policies restore intact.
    This is not runtime credential recovery or a grant restoration procedure.
    """
    scope = metadata.get("scope")
    if scope == "platform":
        return None
    if scope != "application":
        raise R08Error("R08_RESTORE_SCOPE_INVALID")
    value = metadata.get("instance_id")
    if not isinstance(value, str):
        raise R08Error("R08_RESTORE_INSTANCE_ID_INVALID")
    try:
        instance_id = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise R08Error("R08_RESTORE_INSTANCE_ID_INVALID") from exc
    if str(instance_id) != value:
        raise R08Error("R08_RESTORE_INSTANCE_ID_NOT_CANONICAL")
    # Use the canonical C1-B2 implementation; do not invent a separate role
    # naming rule that could drift from the installed application schema.
    from services.api.app.services.application_database_credentials import runtime_role
    role = runtime_role(instance_id)
    if not re.fullmatch(r"augmis_rw_[0-9a-f]{32}", role):
        raise R08Error("R08_RESTORE_RUNTIME_ROLE_INVALID")
    return role


# A no-network PostgreSQL process that exists only inside an isolated test
# container with its own scratch volume. It cannot access any AUGMIS volume.
RESTORE_SCRIPT = r'''set -eu
export PGDATA=/var/lib/postgresql/data/r08-probe
# Debian pg clients default to /var/run/postgresql, while this hardened
# no-network probe deliberately creates its local socket in /tmp.
export PGHOST=/tmp
mkdir -p "$PGDATA"
chmod 0700 "$PGDATA"
initdb -D "$PGDATA" --auth-local=trust --auth-host=reject --no-instructions >/dev/null
printf "R08_STAGE=initdb_ready\n"
pg_ctl -D "$PGDATA" -o "-c listen_addresses='' -c unix_socket_directories=/tmp" -w start >/dev/null
printf "R08_STAGE=postgres_started\n"
trap 'pg_ctl -D "$PGDATA" -m immediate stop >/dev/null 2>&1 || true' EXIT
# Tenant-scoped RLS policies explicitly reference a deterministic login role.
# A fresh isolated PostgreSQL cluster has no such role. Restore the schema
# contract with a tightly restricted NOLOGIN placeholder, never credentials.
# The host has validated this role against the authenticated archive identity.
if [ -n "${R08_PROBE_RUNTIME_ROLE:-}" ]; then
  if ! printf '%s\n' "$R08_PROBE_RUNTIME_ROLE" | grep -Eq '^augmis_rw_[0-9a-f]{32}$'; then
    exit 48
  fi
  psql -X -q -v ON_ERROR_STOP=1 -h /tmp -U postgres -d postgres \
    -c "CREATE ROLE ${R08_PROBE_RUNTIME_ROLE} WITH NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;" >/dev/null
  printf 'R08_STAGE=restore_role_ready\n'
fi
pg_restore --exit-on-error --no-owner --no-acl -h /tmp -U postgres -d postgres >/dev/null
printf "R08_STAGE=pg_restore_completed\n"
if [ -n "${R08_PROBE_RUNTIME_ROLE:-}" ]; then
  psql -X -q -t -A -v ON_ERROR_STOP=1 -h /tmp -U postgres -d postgres \
    -c "SELECT 'R08_RESTORE_ROLE_SAFE=' || CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${R08_PROBE_RUNTIME_ROLE}' AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls) THEN '1' ELSE '0' END" 
  psql -X -q -t -A -v ON_ERROR_STOP=1 -h /tmp -U postgres -d postgres \
    -c "SELECT 'R08_RESTORED_RLS_POLICIES=' || count(*) FROM pg_policies WHERE '${R08_PROBE_RUNTIME_ROLE}' = ANY(roles)"
fi
psql -X -q -t -A -h /tmp -U postgres -d postgres -c "SELECT 'R08_RESTORED_TABLES=' || count(*) FROM pg_catalog.pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"
'''


def _restore_probe(args):
    if not args.execute or not args.confirm_isolated:
        raise R08Error("R08_ISOLATED_RESTORE_CONFIRMATION_REQUIRED")
    _dev_db()
    path = Path(args.archive).resolve()
    if not path.is_file():
        raise R08Error("R08_ARCHIVE_NOT_FOUND")
    with path.open("rb") as f:
        _, meta, _, _ = read_header(f)
    img = args.postgres_image or meta.get("postgres_image")
    if not isinstance(img, str) or not SHA256_ID.fullmatch(img):
        raise R08Error("R08_PINNED_POSTGRES_IMAGE_REQUIRED")
    if meta["scope"] == "application" and args.postgres_image and args.postgres_image != meta.get("postgres_image"):
        raise R08Error("R08_APPLICATION_RESTORE_IMAGE_DRIFT")
    observed = _run(["docker", "image", "inspect", "--format", "{{.Id}}", img])
    if observed != img:
        raise R08Error("R08_PINNED_IMAGE_ID_MISMATCH")
    secret = _password()
    verified = open_authenticated(path, secret)
    restore_role = _isolated_restore_role(verified)
    rid = uuid.uuid4().hex
    volume = "augmis-r08-restore-" + rid
    labels = ["--label", "augmis.r08.temporary=true", "--label", f"augmis.r08.probe_id={rid}"]
    started = time.monotonic()
    created = False
    try:
        _run(["docker", "volume", "create", *labels, volume]); created = True
        cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--user", "postgres",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
               "--pids-limit", "128", "--memory", "1024m", "--cpus", "1",
               "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
               "--mount", f"type=volume,source={volume},target=/var/lib/postgresql/data"]
        if restore_role is not None:
            cmd.extend(["--env", "R08_PROBE_RUNTIME_ROLE=" + restore_role])
        cmd.extend(["--entrypoint", "/bin/sh", img, "-ec", RESTORE_SCRIPT])
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            with proc.stdin:
                open_authenticated(path, secret, proc.stdin)
            stdout = proc.stdout.read(1024).decode("utf-8", errors="replace")
            rc = proc.wait(timeout=300)
            if (rc != 0 or "R08_RESTORED_TABLES=" not in stdout
                    or (restore_role is not None and "R08_RESTORE_ROLE_SAFE=1" not in stdout)):
                # Never print raw PostgreSQL/Docker stderr or restored contents.
                # These fixed stage markers make Linux/Windows failures actionable.
                completed = (
                    "pg_restore_completed" if "R08_STAGE=pg_restore_completed" in stdout else
                    "restore_role_ready" if "R08_STAGE=restore_role_ready" in stdout else
                    "postgres_started" if "R08_STAGE=postgres_started" in stdout else
                    "initdb_ready" if "R08_STAGE=initdb_ready" in stdout else
                    "container_start_or_initdb"
                )
                print("R08_RESTORE_LAST_STAGE=" + completed, file=sys.stderr)
                raise R08Error("R08_ISOLATED_RESTORE_FAILED")
        except Exception:
            proc.kill(); proc.wait()
            raise
        elapsed = round(time.monotonic()-started, 2)
        print("PASS authenticated encrypted archive restored on isolated no-network PostgreSQL")
        print(stdout.strip())
        print("RTO_PROBE_SECONDS", elapsed, "BACKUP_UTC", verified["created_utc"])
        print("LIMIT: restore probe only; original DB/container/volume were not modified")
    finally:
        if created:
            # Only the freshly generated, caller-owned probe volume. Never source volume.
            check = json.loads(_run(["docker", "volume", "inspect", volume]))[0]
            labels = check.get("Labels") or {}
            if labels.get("augmis.r08.temporary") != "true" or labels.get("augmis.r08.probe_id") != rid:
                raise R08Error("R08_PROBE_VOLUME_OWNERSHIP_DRIFT")
            _run(["docker", "volume", "rm", volume])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest="action", required=True)
    sp.add_parser("inventory", help="Read-only control-plane database inventory")
    b = sp.add_parser("backup", help="Stream pg_dump directly into authenticated AES-256-GCM archive")
    b.add_argument("--scope", choices=sorted(SCOPES), required=True)
    b.add_argument("--instance-id", help="Required for application DB backup")
    b.add_argument("--pg-dump", default="pg_dump", help="pg_dump executable for platform DB")
    b.add_argument("--out", required=True)
    b.add_argument("--execute", action="store_true", help="Explicit permission to perform read-only DB dump")
    v = sp.add_parser("verify", help="Authenticate encrypted archive without Docker or database access")
    v.add_argument("--archive", required=True)
    r = sp.add_parser("restore-probe", help="Temporary no-network Docker volume restore; NEVER original instance")
    r.add_argument("--archive", required=True)
    r.add_argument("--postgres-image", help="Required pinned PostgreSQL 15 image for platform backup")
    r.add_argument("--execute", action="store_true")
    r.add_argument("--confirm-isolated", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.action == "inventory":
            inventory()
        elif args.action == "backup":
            _backup(args)
        elif args.action == "verify":
            verified = open_authenticated(Path(args.archive), _password())
            print("PASS AES-GCM authenticated backup; scope:", verified["scope"],
                  "creation:", verified["created_utc"], "plain bytes:", verified["verified_plaintext_bytes"])
        elif args.action == "restore-probe":
            _restore_probe(args)
        return 0
    except (R08Error, OSError, ValueError, subprocess.TimeoutExpired, BrokenPipeError) as exc:
        # Fixed failure category, no external stderr or connection-string details.
        code = str(exc) if isinstance(exc, R08Error) else "R08_OPERATION_FAILED"
        print("FAILED:", code, file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
