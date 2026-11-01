"""R10 CI check tools. Never use live/development DBs or execute application packages."""
from __future__ import annotations

import argparse
import os
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-ci.lock"


class R10CheckError(RuntimeError):
    pass


def verify_lock() -> None:
    if not LOCK.is_file():
        raise R10CheckError("R10_LOCK_MISSING: generate and commit requirements-ci.lock first")
    value = LOCK.read_text(encoding="utf-8")
    if not value.strip() or not re.search(r"(?m)^cryptography==50\.0\.2(?:\s|\\)", value):
        raise R10CheckError("R10_LOCK_CRYPTO_MISMATCH")
    # All packages must be exact pins, each backed by at least one hash.
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import Version
    lines = value.splitlines()
    for line in lines:
        s = line.strip()
        if s.startswith(("--index-url", "--extra-index-url", "--trusted-host", "-r ", "-c ", "-e ")):
            raise R10CheckError("R10_LOCK_UNSAFE_DIRECTIVE")
    sections = list(re.finditer(r"(?m)^([a-zA-Z0-9][a-zA-Z0-9._-]*)==([^\s\\]+)", value))
    if not sections:
        raise R10CheckError("R10_LOCK_EMPTY")
    pinned = {}
    for i, match in enumerate(sections):
        package = canonicalize_name(match.group(1))
        version = match.group(2)
        if package in pinned:
            raise R10CheckError("R10_LOCK_DUPLICATE_PIN: " + package)
        chunk = value[match.end():sections[i + 1].start() if i + 1 < len(sections) else len(value)]
        if not re.search(r"--hash=sha256:[a-f0-9]{64}", chunk):
            raise R10CheckError("R10_LOCK_PACKAGE_MISSING_HASH: " + package)
        pinned[package] = Version(version)
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        key = canonicalize_name(requirement.name)
        if key not in pinned or pinned[key] not in requirement.specifier:
            raise R10CheckError("R10_LOCK_ROOT_REQUIREMENT_DRIFT: " + key)
    for package in ("pytest", "pip-audit", "httpx"):
        if canonicalize_name(package) not in pinned:
            raise R10CheckError("R10_LOCK_TEST_TOOL_MISSING: " + package)
    print(f"R10_LOCK_PASS: {len(pinned)} pinned distributions with hashes")


def disposable_db_preflight() -> str:
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("AUGMIS_R10_DISPOSABLE_DB") != "1":
        raise R10CheckError("R10_DB_CI_ONLY: GitHub Actions disposable PostgreSQL job required")
    if os.getenv("APP_ENV", "").lower() != "development":
        raise R10CheckError("R10_DB_ENV_DENIED")
    raw = os.getenv("DATABASE_URL", "")
    target = urlsplit(raw)
    if (target.scheme != "postgresql+psycopg"
            or target.hostname != "127.0.0.1"
            or target.port != 5432
            or target.username != "augmis_ci"
            or target.path != "/augmis_r10_ci"):
        raise R10CheckError("R10_DB_NON_DISPOSABLE_TARGET_DENIED")
    return raw


def verify_migrations() -> None:
    url = disposable_db_preflight()
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect
    from alembic.runtime.migration import MigrationContext
    cfg = Config(str(ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) != 1:
        raise R10CheckError(f"R10_MIGRATION_MULTI_HEAD: {len(heads)}")
    eng = create_engine(url)
    try:
        with eng.connect() as conn:
            current = MigrationContext.configure(conn).get_current_heads()
            tables = inspect(conn).get_table_names()
        if tuple(current) != tuple(heads):
            raise R10CheckError("R10_MIGRATION_DATABASE_NOT_AT_HEAD")
        if not tables or "alembic_version" not in tables:
            raise R10CheckError("R10_MIGRATION_NO_TABLES")
        print(f"R10_ALEMBIC_PASS: head={heads[0]}, {len(tables)} tables")
    finally:
        eng.dispose()


def _make_fixture_zip(folder: Path, output: Path) -> None:
    # CI only: repository examples are treated as input data, not executed.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            if path.is_symlink():
                raise R10CheckError("R10_PACKAGE_SYMLINK_DENIED")
            if any(part.startswith(".") for part in path.relative_to(folder).parts):
                continue
            zf.write(path, path.relative_to(folder).as_posix())


def verify_packages() -> None:
    from tools.validate_package import PackageValidationError, validate_application_package
    # Vetted static/docker example, plus functional validator regression suite in pytest.
    samples = ("hello-app", "hello-app-1.1.0", "hello-app-2.0.0", "hello-app-3.0.0")
    with tempfile.TemporaryDirectory(prefix="augmis-r10-package-") as root:
        for example in samples:
            folder = ROOT / "examples" / example
            if not (folder / "augmis-app.yaml").is_file():
                raise R10CheckError("R10_APPROVED_FIXTURE_MISSING: " + example)
            archive = Path(root) / (example + ".zip")
            _make_fixture_zip(folder, archive)
            result = validate_application_package(archive)
            if result.get("status") != "VALID":
                raise R10CheckError("R10_AAPS_POSITIVE_FAILED: " + example)
        # Negative: traversal path rejected before extraction.
        traversal = Path(root) / "traversal.zip"
        with zipfile.ZipFile(traversal, "w") as zf:
            zf.writestr("../escaped.txt", b"not permitted")
        try:
            validate_application_package(traversal)
        except (PackageValidationError, zipfile.BadZipFile):
            pass
        else:
            raise R10CheckError("R10_AAPS_TRAVERSAL_ACCEPTED")
        # Negative: no manifest.
        missing = Path(root) / "missing.zip"
        with zipfile.ZipFile(missing, "w") as zf:
            zf.writestr("README.txt", "no manifest")
        try:
            validate_application_package(missing)
        except (PackageValidationError, zipfile.BadZipFile):
            pass
        else:
            raise R10CheckError("R10_AAPS_MISSING_MANIFEST_ACCEPTED")
    print(f"R10_AAPS_PASS: {len(samples)} valid packages, 2 rejected malformed archives")


def main() -> int:
    p = argparse.ArgumentParser(description="AUGMIS R10 CI-safe validation")
    p.add_argument("command", choices=("verify-lock", "preflight-db", "verify-migrations", "verify-packages"))
    args = p.parse_args()
    try:
        if args.command == "verify-lock":
            verify_lock()
        elif args.command == "preflight-db":
            disposable_db_preflight()
            print("R10_DB_PREFLIGHT_PASS")
        elif args.command == "verify-migrations":
            verify_migrations()
        else:
            verify_packages()
    except Exception as error:
        print(f"R10_CHECK_FAILED: {type(error).__name__}: {error}")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
