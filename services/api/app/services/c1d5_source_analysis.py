"""C1-D5.1: inspection-only, no extraction, execution or resource mutation.

Source ZIP is untrusted input. Results report detectable readiness gaps only;
passing analysis is never evidence of a successful build or safe deployment.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import stat
import zipfile
from collections import Counter
from pathlib import PurePosixPath
from typing import BinaryIO

from tools.validate_package import (
    MAX_FILES,
    MAX_SINGLE_FILE_SIZE,
    MAX_UNCOMPRESSED_SIZE,
    validate_zip_member_name,
    is_symlink,
)

SOURCE_MAX_TEXT = 256 * 1024
_CHECKS = [
    ("source_archive", "Source archive safety"),
    ("source_structure", "Application source structure"),
    ("frontend", "React frontend and build configuration"),
    ("backend", "FastAPI backend and dependencies"),
    ("database", "PostgreSQL declaration and schema"),
    ("health", "Application health endpoint"),
    ("secrets", "Source credentials and secret files"),
    ("artifacts", "AAPS manifest and Dockerfile"),
    ("build", "Isolated Docker image build"),
    ("runtime", "Disposable startup, database and API tests"),
    ("qualification", "Immutable-build release qualification"),
]


def _empty():
    return {id: {"id": id, "label": label, "status": "not_checked",
                 "code": "NOT_RUN", "location": None,
                 "problem": "This requirement has not been checked yet.",
                 "correction": "Complete the preceding preparation stage."}
            for id, label in _CHECKS}


def _set(checks, check_id, status, code, problem, correction="", location=None):
    checks[check_id].update(status=status, code=code, problem=problem,
                            correction=correction, location=location)


def _report(checks, sha, stack="unknown", classification="unsupported", root="", files=0):
    counts = Counter(x["status"] for x in checks.values())
    return {
        "schemaVersion": "c1d5.1",
        "sourceSha256": sha,
        "sourceRoot": root or None,
        "filesInspected": files,
        "detectedStack": stack,
        "classification": classification,
        "analysisPassed": not counts["failed"] and not counts["action_required"]
                          and classification == "supported",
        "publisherSubmissionEligible": False,
        "publisherSubmissionReason": "C1-D5.1 is source analysis only. A generated artifact, successful isolated build and release qualification are required before submission.",
        "summary": {"passed": counts["passed"], "failed": counts["failed"],
                    "actionRequired": counts["action_required"],
                    "notChecked": counts["not_checked"]},
        "checks": list(checks.values()),
    }


def _sample(zf, name):
    """Read at most SOURCE_MAX_TEXT+1 bytes; never disclose contents in output."""
    try:
        with zf.open(name) as handle:
            raw = handle.read(SOURCE_MAX_TEXT + 1)
        if len(raw) > SOURCE_MAX_TEXT:
            return "", "oversize"
        return raw.decode("utf-8"), None
    except (OSError, UnicodeError, RuntimeError, zipfile.BadZipFile):
        return "", "unreadable"


# Only importable application modules can establish FastAPI/health evidence.
# Test fixtures, documentation and strings in other sources are not runtime routes.
_NON_RUNTIME_PARTS = frozenset({
    "tests", "test", "testing", "fixtures", "fixture", "examples", "example",
    "docs", "documentation", "tools", "scripts", "node_modules", ".venv", "venv",
})
_ENTRYPOINT_FILES = frozenset({"main.py", "app.py", "api.py", "server.py", "asgi.py"})
_HEALTH_PATHS = frozenset({"/health", "/healthz", "/ready"})


def _runtime_entrypoint_path(path: str) -> bool:
    parts = path.lower().split("/")
    name = parts[-1]
    if name not in _ENTRYPOINT_FILES or any(p in _NON_RUNTIME_PARTS for p in parts[:-1]):
        return False
    return True


def _fastapi_runtime_evidence(source: str) -> tuple[bool, bool]:
    """Parse only executable top-level FastAPI declarations and attached GET routes.

    This is conservative source evidence, NOT proof of running application health.
    No imports or project code are executed. Dynamic factories/routing require
    later runtime verification and are not assumed valid from text alone.
    """
    try:
        module = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        return False, False

    class_names = set()
    module_names = set()
    for node in module.body:
        if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
            class_names.update(x.asname or x.name for x in node.names if x.name == "FastAPI")
        elif isinstance(node, ast.Import):
            module_names.update(x.asname or x.name for x in node.names if x.name == "fastapi")

    def is_fastapi_constructor(expr: ast.AST) -> bool:
        if not isinstance(expr, ast.Call):
            return False
        fn = expr.func
        return (isinstance(fn, ast.Name) and fn.id in class_names) or (
            isinstance(fn, ast.Attribute) and fn.attr == "FastAPI"
            and isinstance(fn.value, ast.Name) and fn.value.id in module_names
        )

    apps = set()
    for node in module.body:
        if isinstance(node, ast.Assign) and is_fastapi_constructor(node.value):
            apps.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and is_fastapi_constructor(node.value):
            if isinstance(node.target, ast.Name):
                apps.add(node.target.id)

    if not apps:
        return False, False

    def route_on_app(decorator: ast.AST) -> bool:
        if not isinstance(decorator, ast.Call):
            return False
        call = decorator.func
        if not (isinstance(call, ast.Attribute) and isinstance(call.value, ast.Name)
                and call.value.id in apps):
            return False
        if call.attr not in ("get", "api_route") or not decorator.args:
            return False
        path_arg = decorator.args[0]
        if not (isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str)
                and path_arg.value in _HEALTH_PATHS):
            return False
        if call.attr == "api_route":
            methods = next((k.value for k in decorator.keywords if k.arg == "methods"), None)
            if not isinstance(methods, (ast.List, ast.Tuple)) or not any(
                isinstance(x, ast.Constant) and x.value == "GET" for x in methods.elts
            ):
                return False
        return True

    healthy = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(route_on_app(decorator) for decorator in node.decorator_list)
        for node in module.body
    )
    return True, healthy


def analyze_source_zip(stream: BinaryIO, filename: str, max_upload_bytes: int):
    """Return structured read-only diagnostics for untrusted source ZIP."""
    checks = _empty()
    stream.seek(0, io.SEEK_END)
    upload_size = stream.tell()
    stream.seek(0)
    if upload_size > max_upload_bytes:
        _set(checks, "source_archive", "failed", "SOURCE_UPLOAD_TOO_LARGE",
             "The uploaded ZIP exceeds the configured size limit.",
             f"Reduce the source ZIP to at most {max_upload_bytes} bytes and remove node_modules and generated build folders.")
        return _report(checks, "")
    digest = hashlib.sha256()
    while True:
        block = stream.read(1024 * 1024)
        if not block:
            break
        digest.update(block)
    sha = digest.hexdigest()
    stream.seek(0)
    if not filename.lower().endswith(".zip"):
        _set(checks, "source_archive", "failed", "SOURCE_ZIP_REQUIRED",
             "Only ZIP source archives are accepted.", "Compress the application source directory as a .zip archive.")
        return _report(checks, sha)
    try:
        archive = zipfile.ZipFile(stream)
    except (zipfile.BadZipFile, OSError):
        _set(checks, "source_archive", "failed", "SOURCE_ZIP_INVALID",
             "The file is not a readable ZIP archive.", "Create a new standard ZIP archive from the application source.")
        return _report(checks, sha)
    with archive as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        total = 0
        found = set()
        for info in zf.infolist():
            name = info.filename
            try:
                validate_zip_member_name(name)
            except Exception:
                _set(checks, "source_archive", "failed", "SOURCE_UNSAFE_PATH",
                     "ZIP contains an unsafe or traversal path.", "Remove absolute paths, parent-directory references and backslash-traversal entries.", name)
                return _report(checks, sha)
            normal = name.replace("\\", "/").rstrip("/").casefold()
            if normal in found:
                _set(checks, "source_archive", "failed", "SOURCE_DUPLICATE_PATH",
                     "ZIP has duplicate or case-conflicting entry paths.", "Rename or remove duplicate archive entries.", name)
                return _report(checks, sha)
            found.add(normal)
            if is_symlink(info):
                _set(checks, "source_archive", "failed", "SOURCE_SYMLINK",
                     "Source ZIP contains a symbolic link.", "Replace symlinks with ordinary source files.", name)
                return _report(checks, sha)
            if info.flag_bits & 1:
                _set(checks, "source_archive", "failed", "SOURCE_ENCRYPTED",
                     "Source ZIP contains an encrypted entry.", "Supply an unencrypted source ZIP.", name)
                return _report(checks, sha)
            if info.file_size > MAX_SINGLE_FILE_SIZE:
                _set(checks, "source_archive", "failed", "SOURCE_FILE_TOO_LARGE",
                     "Source ZIP contains an oversized file.", "Remove generated artifacts or oversized binaries.", name)
                return _report(checks, sha)
            total += info.file_size
        if len(zf.infolist()) > MAX_FILES or total > MAX_UNCOMPRESSED_SIZE:
            _set(checks, "source_archive", "failed", "SOURCE_ARCHIVE_LIMIT",
                 "Source ZIP exceeds the safe entry count or uncompressed-size limit.",
                 "Exclude node_modules, .next, dist, build and unnecessary binary files.")
            return _report(checks, sha)
        if not infos:
            _set(checks, "source_archive", "failed", "SOURCE_EMPTY_ARCHIVE",
                 "ZIP has no source files.", "Include frontend and backend source files.")
            return _report(checks, sha)
        _set(checks, "source_archive", "passed", "SOURCE_ZIP_OK",
             "ZIP path, entry count and declared size checks passed.", "")
        all_names = [i.filename.replace("\\", "/") for i in infos]
        # One top-level wrapping directory is supported without extraction.
        top = {n.split("/")[0] for n in all_names}
        wrapped = len(top) == 1 and all("/" in n for n in all_names)
        prefix = next(iter(top)) + "/" if wrapped else ""
        mapping = {n[len(prefix):]: i.filename for n, i in zip(all_names, infos)}
        paths = set(mapping)
        valid_names = [n for n in paths if not n.startswith("__MACOSX/")]
        _set(checks, "source_structure", "passed", "SOURCE_FILES_FOUND",
             f"Found {len(valid_names)} files in the source archive.", "")
        pkg_names = sorted(n for n in paths if n == "package.json" or n.endswith("/package.json"))
        pkg_names = [n for n in pkg_names if not any(p in ("node_modules", ".next", "dist", "build") for p in n.split("/"))]
        react_pkg = None
        next_pkg = None
        node_pkg = None
        pkg_problem = None
        for name in pkg_names[:25]:
            text, read_error = _sample(zf, mapping[name])
            if read_error:
                pkg_problem = (name, read_error)
                continue
            try:
                payload = json.loads(text)
            except (ValueError, TypeError):
                pkg_problem = (name, "invalid_json")
                continue
            if not isinstance(payload, dict):
                pkg_problem = (name, "not_object")
                continue
            dependencies = {**(payload.get("dependencies") if isinstance(payload.get("dependencies"), dict) else {}),
                            **(payload.get("devDependencies") if isinstance(payload.get("devDependencies"), dict) else {})}
            if "next" in dependencies and next_pkg is None:
                next_pkg = (name, payload)
            elif "react" in dependencies and react_pkg is None:
                react_pkg = (name, payload)
            elif node_pkg is None:
                node_pkg = (name, payload)
        # Read only bounded text and a limited number of source files.
        py_names = sorted(n for n in paths if n.endswith(".py") and not any(p.startswith(".") or p in ("node_modules", ".venv", "venv") for p in n.split("/")))[:120]
        requirements = sorted(n for n in paths if n.endswith("requirements.txt") or n.endswith("pyproject.toml"))[:15]
        py_deps = "\n".join(_sample(zf, mapping[n])[0] for n in requirements)
        fastapi_deps = bool(re.search(r"(?im)^\s*(?:fastapi\s*(?:[=<>~!\[]|$)|fastapi\s*=)", py_deps))
        fastapi_sources = []
        health_file = None
        for name in py_names:
            if not _runtime_entrypoint_path(name):
                continue
            text, error = _sample(zf, mapping[name])
            if error:
                continue
            has_app, has_health = _fastapi_runtime_evidence(text)
            if has_app:
                fastapi_sources.append(name)
                if has_health:
                    health_file = name
        is_fastapi = fastapi_deps or bool(fastapi_sources)
        pg_deps = bool(re.search(r"(?i)\b(psycopg|asyncpg|postgresql|pg8000|sqlalchemy|postgres)\b", py_deps))
        if node_pkg:
            all_deps = node_pkg[1].get("dependencies", {})
            pg_deps |= isinstance(all_deps, dict) and any(x in all_deps for x in ("pg", "postgres"))
        # Configuration references are a hint only; no values are returned.
        db_config = any("database" in n.lower() or "schema" in n.lower() for n in paths)
        schema_files = sorted(n for n in paths if n.lower().endswith(("schema.sql", "schema.json")) or
                              ("migrations/" in n.lower() and n.lower().endswith(".sql")) or
                              ("alembic/versions/" in n.lower() and n.lower().endswith(".py")))
        # An existing AAPS manifest may already carry the reviewed declarative
        # PostgreSQL schema; do not incorrectly require a second schema.json.
        # Only a real non-empty tables list counts as source-level evidence.
        if "augmis-app.yaml" in mapping:
            try:
                import yaml
                existing_aaps = yaml.safe_load(_sample(zf, mapping["augmis-app.yaml"])[0])
                aaps_database = ((existing_aaps or {}).get("addons") or {}).get("database") or {}
                aaps_schema = aaps_database.get("schema") or {}
                if (aaps_database.get("type") == "postgresql"
                    and isinstance(aaps_schema, dict)
                    and isinstance(aaps_schema.get("tables"), list)
                    and len(aaps_schema["tables"]) > 0):
                    schema_files.append("augmis-app.yaml")
            except (ValueError, AttributeError, TypeError, yaml.YAMLError):
                pass  # Full AAPS schema validation belongs to the generator.
        if "db/aaps-schema.json" in mapping:
            schema_files.append("db/aaps-schema.json")
        postgres = pg_deps or bool(schema_files)
        stack = "+".join([s for s, yes in (("react", bool(react_pkg)), ("fastapi", is_fastapi), ("postgresql", postgres)) if yes]) or "unknown"
        classification = "supported" if react_pkg and is_fastapi else ("guided_mapping" if next_pkg or node_pkg or is_fastapi or react_pkg else "unsupported")
        if pkg_problem and not (react_pkg or next_pkg or node_pkg):
            _set(checks, "frontend", "failed", "FRONTEND_PACKAGE_INVALID",
                 "A package.json file could not be read or parsed as a JSON object.",
                 "Correct the package.json syntax and ensure it is UTF-8 JSON under the size limit.", pkg_problem[0])
        elif react_pkg:
            name, pkg = react_pkg
            scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
            build = scripts.get("build") if isinstance(scripts, dict) else None
            root = name.rsplit("/", 1)[0] if "/" in name else ""
            has_src = any(n.startswith(root + "/src/") for n in paths) if root else any(n.startswith("src/") for n in paths)
            if not has_src:
                _set(checks, "frontend", "action_required", "REACT_SOURCE_MISSING",
                     "React dependency detected, but no source directory found next to package.json.",
                     "Include the React src/ directory alongside package.json.", name)
            elif not isinstance(build, str) or not build.strip():
                _set(checks, "frontend", "action_required", "REACT_BUILD_SCRIPT_MISSING",
                     "React source detected, but package.json has no build script.",
                     "Add a working scripts.build command (for example, vite build) to package.json.", name)
            else:
                _set(checks, "frontend", "passed", "REACT_SOURCE_DETECTED",
                     "React dependencies, source folder and build command detected (not executed).", "", name)
        elif next_pkg:
            _set(checks, "frontend", "action_required", "NEXTJS_MAPPING_PENDING",
                 "Next.js detected. Automatic conversion is not in the first supported template.",
                 "Use a React + FastAPI source layout for this release, or wait for the Next.js conversion template.", next_pkg[0])
        else:
            _set(checks, "frontend", "action_required", "REACT_NOT_DETECTED",
                 "A supported React frontend was not detected.",
                 "Include frontend/package.json with react dependency, build script and frontend/src/." if node_pkg else
                 "Provide a supported React frontend or use the existing Static Web upload route.",
                 node_pkg[0] if node_pkg else None)
        if not is_fastapi:
            _set(checks, "backend", "action_required", "FASTAPI_NOT_DETECTED",
                 "FastAPI backend was not detected.",
                 "Provide backend/requirements.txt with FastAPI and backend/main.py or backend/app/main.py defining FastAPI().")
        elif not fastapi_deps:
            _set(checks, "backend", "action_required", "FASTAPI_REQUIREMENT_MISSING",
                 "FastAPI application code exists, but its dependency declaration is missing.",
                 "Add FastAPI to requirements.txt or pyproject.toml, plus all runtime dependencies.",
                 fastapi_sources[0] if fastapi_sources else None)
        elif not fastapi_sources:
            _set(checks, "backend", "action_required", "FASTAPI_ENTRYPOINT_MISSING",
                 "FastAPI dependency was detected but no FastAPI() entry point was found.",
                 "Add an importable FastAPI app factory or app = FastAPI() in the backend source.",
                 requirements[0] if requirements else None)
        else:
            _set(checks, "backend", "passed", "FASTAPI_DETECTED",
                 "FastAPI dependency and app instantiation detected (not executed).", "", fastapi_sources[0])
        if postgres:
            if schema_files:
                _set(checks, "database", "passed", "POSTGRES_SCHEMA_DETECTED",
                     "PostgreSQL driver/configuration and a schema/migration artifact were detected (not applied).",
                     "", schema_files[0])
            else:
                _set(checks, "database", "action_required", "POSTGRES_SCHEMA_REQUIRED",
                     "PostgreSQL integration detected, but no portable schema or migration artifact found.",
                     "Provide a portable declarative PostgreSQL schema or reviewed migration artifact; do not include production data or credentials.")
        else:
            _set(checks, "database", "passed", "DATABASE_NOT_DECLARED",
                 "No PostgreSQL dependency detected; database provisioning is not required unless the app needs persistence.", "")
        if health_file:
            _set(checks, "health", "passed", "HEALTH_ROUTE_DETECTED",
                 "An explicit GET health route is attached to a FastAPI app in source (not executed or health-tested).",
                 "", health_file)
        elif not fastapi_sources:
            checks["health"].update(
                code="HEALTH_SOURCE_NOT_VERIFIABLE",
                problem="No verified FastAPI application entrypoint; health route evidence cannot be established from test fixtures or text matches.",
                correction="Provide an importable FastAPI app entrypoint such as backend/app/main.py with app = FastAPI() and an explicit GET /health route.",
            )
        else:
            _set(checks, "health", "action_required", "HEALTH_ROUTE_REQUIRED",
                 "No explicit GET /health route was found on a verified FastAPI app entrypoint.",
                 "Expose @app.get('/health') returning HTTP 200 on the declared FastAPI app; dynamic/router-based health routes require later runtime verification.",
                 fastapi_sources[0])
        secret_names = sorted(n for n in paths if (
            (n.rsplit("/", 1)[-1].lower().startswith(".env") and
             n.rsplit("/", 1)[-1].lower() not in (".env.example", ".env.sample", ".env.template")) or
            n.rsplit("/", 1)[-1].lower() == "id_rsa" or
            n.lower().endswith((".pem", ".p12", ".pfx", ".key"))))
        if secret_names:
            _set(checks, "secrets", "failed", "SOURCE_SENSITIVE_FILE",
                 "Source archive includes a likely secret or private-key file.",
                 "Remove embedded credentials and private keys; provide only environment variable names and a .env.example without secrets.", secret_names[0])
        else:
            _set(checks, "secrets", "passed", "SECRET_FILE_NAMES_CLEAR",
                 "No obvious secret filenames detected. This is not a malware or secret-content scan.", "")
        aaps = "augmis-app.yaml" in paths
        docker = "Dockerfile" in paths
        _set(checks, "artifacts", "passed" if aaps and docker else "not_checked",
             "AAPS_ARTIFACTS_PRESENT" if aaps and docker else "AAPS_GENERATION_PENDING",
             "Existing Dockerfile and AAPS manifest detected (not validated)." if aaps and docker else
             "AAPS manifest/Dockerfile generation belongs to C1-D5.2.",
             "The generator will create and validate artifacts in C1-D5.2." if not (aaps and docker) else "")
        for key in ("build", "runtime", "qualification"):
            checks[key]["problem"] = {
                "build": "Docker build has not been run. C1-D5.3 will invoke the existing build engine.",
                "runtime": "Isolated runtime, DB connectivity, health and CRUD tests have not been run.",
                "qualification": "C1-D2 immutable-build qualification has not been run.",
            }[key]
        return _report(checks, sha, stack, classification, prefix.rstrip("/"), len(valid_names))
