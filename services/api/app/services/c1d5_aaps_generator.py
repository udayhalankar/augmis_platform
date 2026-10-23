"""C1-D5.2: deterministic draft AAPS generation; never builds or executes user code.

Input is hostile ZIP data: C1-D5.1 checks bounds/paths, then the generator
re-checks the exact archive, avoids source overwrites and validates AAPS v1.
Generated artifacts are DRAFTS and cannot unlock Publisher submission.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
from pathlib import Path
import zipfile
from pathlib import PurePosixPath
from typing import Any

import yaml
from tools.validate_package import load_contract, validate_schema, validate_zip_member_name, is_symlink, validate_application_package
from services.api.app.services.c1d5_source_analysis import analyze_source_zip

_KEY = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_REJECTED = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", ".pytest_cache"}
_OUTPUT_DIRS = {"dist", "build"}
_MAX_SOURCE_SIZE = 200 * 1024 * 1024


class GenerationIssue(Exception):
    def __init__(self, code: str, problem: str, correction: str, location: str | None = None):
        super().__init__(problem)
        self.code, self.problem, self.correction, self.location = code, problem, correction, location

    def as_dict(self):
        return {"code": self.code, "problem": self.problem, "correction": self.correction, "location": self.location}


def _fail(code, problem, correction, location=None):
    raise GenerationIssue(code, problem, correction, location)


def _source_paths(zf: zipfile.ZipFile, prefix: str) -> dict[str, zipfile.ZipInfo]:
    mapping = {}
    for info in zf.infolist():
        if info.is_dir():
            continue
        validate_zip_member_name(info.filename)
        if is_symlink(info):
            _fail("GEN_UNSAFE_LINK", "Source contains a symbolic link.", "Replace links with regular source files.", info.filename)
        path = info.filename.replace("\\", "/")
        if not path.startswith(prefix):
            _fail("GEN_ROOT_INVALID", "ZIP source root differs from analyzed root.", "Use one application source root.", path)
        relative = path[len(prefix):]
        if not relative or relative in mapping:
            _fail("GEN_DUPLICATE", "Duplicate or empty source path.", "Rename duplicate files.", relative)
        if any(part in _REJECTED for part in PurePosixPath(relative).parts):
            continue  # build artifacts and local environments are never repackaged
        mapping[relative] = info
    return mapping


def _read(zf, mapping, path, limit=256 * 1024):
    item = mapping.get(path)
    if not item:
        _fail("GEN_FILE_MISSING", f"Required file '{path}' is missing.", f"Add {path} to your source ZIP.", path)
    if item.file_size > limit:
        _fail("GEN_FILE_OVERSIZE", f"'{path}' exceeds its allowed input size.", "Reduce the source configuration file size.", path)
    with zf.open(item) as f:
        return f.read(limit + 1).decode("utf-8")


def _find_react(zf, mapping):
    possibilities = [n for n in mapping if n == "frontend/package.json" or n == "package.json"]
    for name in possibilities:
        try:
            pkg = json.loads(_read(zf, mapping, name))
        except (ValueError, UnicodeError):
            _fail("GEN_REACT_JSON", "React package.json is not valid UTF-8 JSON.", "Repair package.json.", name)
        if not isinstance(pkg, dict):
            continue
        deps = dict(pkg.get("dependencies") or {})
        deps.update(pkg.get("devDependencies") or {})
        if "react" not in deps or "next" in deps:
            continue
        if not isinstance((pkg.get("scripts") or {}).get("build"), str):
            _fail("GEN_REACT_BUILD_MISSING", "React build script is missing.", "Define scripts.build in frontend/package.json.", name)
        folder = name.rsplit("/", 1)[0] if "/" in name else ""
        if folder != "frontend":
            _fail("GEN_FRONTEND_LAYOUT", "React source is outside the supported frontend/ layout.", "Move React source and package.json into frontend/ for this first template.", name)
        if not any(n.startswith("frontend/src/") for n in mapping):
            _fail("GEN_REACT_SOURCE_MISSING", "React frontend/src is missing.", "Include frontend/src and necessary public assets.", name)
        return pkg
    _fail("GEN_REACT_NOT_FOUND", "Supported React frontend is not detected.", "Provide frontend/package.json with React and scripts.build, plus frontend/src/.")


def _backend(zf, mapping):
    # C1-D5.2 supports a fixed importable entrypoint; no dynamic factory guessing.
    for main, req, module in (("app/main.py", "requirements.txt", "app.main:app"),
                              ("backend/app/main.py", "backend/requirements.txt", "backend.app.main:app"),
                              ("backend/main.py", "backend/requirements.txt", "backend.main:app")):
        if main in mapping and req in mapping:
            src = _read(zf, mapping, main)
            from services.api.app.services.c1d5_source_analysis import _fastapi_runtime_evidence
            app, health = _fastapi_runtime_evidence(src)
            if not app:
                _fail("GEN_FASTAPI_ENTRYPOINT", "No statically verifiable app = FastAPI() declaration.", "Expose a module-level FastAPI app and an importable entrypoint.", main)
            if not health:
                _fail("GEN_HEALTH_ROUTE", "No static GET /health route found on the FastAPI app.", "Add @app.get('/health') before generating; test it during C1-D5.3.", main)
            requirements = _read(zf, mapping, req)
            if not re.search(r"(?im)^\s*fastapi\s*(?:[=<>~!\[]|$)", requirements):
                _fail("GEN_FASTAPI_REQUIREMENTS", "requirements.txt does not declare FastAPI.", "Add FastAPI to the requirements file.", req)
            return main, req, module
    _fail("GEN_BACKEND_LAYOUT", "Supported FastAPI entrypoint and requirements pair is missing.",
          "Use app/main.py + requirements.txt, backend/main.py + backend/requirements.txt, or backend/app/main.py + backend/requirements.txt.")


def _routes(value, existing, zf, mapping):
    if value and value.strip():
        try: result = json.loads(value)
        except ValueError: _fail("GEN_ROUTES_JSON", "API gateway routes JSON is malformed.", "Enter a JSON array of {path, methods} records.", "Configuration > gateway routes")
    elif existing and isinstance(existing.get("gateway"), dict):
        result = existing["gateway"].get("routes")
    elif "gateway/routes.json" in mapping:
        try: result = json.loads(_read(zf, mapping, "gateway/routes.json"))
        except ValueError: _fail("GEN_ROUTES_JSON", "gateway/routes.json is malformed.", "Provide a valid JSON array.", "gateway/routes.json")
    else:
        _fail("GEN_ROUTES_REQUIRED", "API route declaration is missing.", "Supply gateway/routes.json or enter API routes JSON with paths and permitted HTTP methods.")
    if not isinstance(result, list) or not result:
        _fail("GEN_ROUTES_INVALID", "API routes must be a non-empty JSON array.", "Define at least one application API route.")
    return result


def _database(value, existing, zf, mapping, pg_required):
    if value and value.strip():
        try: schema = json.loads(value)
        except ValueError: _fail("GEN_DB_JSON", "PostgreSQL schema JSON is invalid.", "Supply an AAPS schema object containing tables[].", "Configuration > PostgreSQL schema")
    elif existing and isinstance(existing.get("addons"), dict):
        db = existing["addons"].get("database") or {}
        schema = db.get("schema")
    elif "db/aaps-schema.json" in mapping:
        try: schema = json.loads(_read(zf, mapping, "db/aaps-schema.json"))
        except ValueError: _fail("GEN_DB_JSON", "db/aaps-schema.json is invalid.", "Supply valid JSON matching the AAPS database.schema contract.", "db/aaps-schema.json")
    else:
        schema = None
    if pg_required and not schema:
        _fail("GEN_PG_MAPPING_REQUIRED", "PostgreSQL detected but no declarative AAPS schema mapping was provided.",
              "Provide db/aaps-schema.json with tables[] or paste that JSON into PostgreSQL schema configuration. Do not submit SQL dumps or secrets.", "db/aaps-schema.json")
    if not pg_required and schema:
        pg_required = True
    return ({"database": {"type": "postgresql", "version": "15", "storage": "1Gi", "schema": schema}} if pg_required else None)


def _dockerfile(module: str, req: str, output_dir: str, has_lock: bool):
    npm_install = "npm ci --no-audit --no-fund" if has_lock else "npm install --no-audit --no-fund"
    backend_folder = module.split(".")[0]
    return ("# C1-D5.2 generated draft. Build and runtime checks are NOT performed here.\n"
            "FROM node:22-bookworm-slim AS ui-build\n"
            "WORKDIR /build/frontend\n"
            "COPY frontend/package*.json ./\n"
            f"RUN {npm_install}\n"
            "COPY frontend/ ./\n"
            "RUN npm run build\n\n"
            "FROM python:3.12-slim\n"
            "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp\n"
            "WORKDIR /opt/app\n"
            f"COPY {req} ./requirements.txt\n"
            "RUN pip install --no-cache-dir --timeout 180 --retries 10 -r requirements.txt PyJWT==2.13.0 cryptography==46.0.4 \\\n"
            "    && groupadd --gid 10001 augmisapp \\\n"
            "    && useradd --uid 10001 --gid 10001 --no-create-home augmisapp\n"
            f"COPY {backend_folder}/ ./{backend_folder}/\n"
            f"COPY --from=ui-build --chown=10001:10001 /build/frontend/{output_dir}/ ./augmis-web/\n"
            "COPY augmis_generated_entry.py ./augmis_generated_entry.py\n"
            "COPY augmis_runtime_guard.py ./augmis_runtime_guard.py\n"
            "USER 10001:10001\nEXPOSE 8080\n"
            'CMD ["uvicorn", "augmis_generated_entry:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]\n')


def _wrapper(module):
    module_path = module.split(":")[0]
    return ("# Generated AUGMIS frontend adapter; route/auth security is tested in C1-D5.3.\n"
            "from importlib import import_module\n"
            "from fastapi.staticfiles import StaticFiles\n"
            "from augmis_runtime_guard import AugmisRuntimeGuard\n"
            f"app = import_module({module_path!r}).app\n"
            "app.add_middleware(AugmisRuntimeGuard)\n"
            'app.mount("/", StaticFiles(directory="/opt/app/augmis-web", html=True), name="augmis-web")\n')



def _write_deterministic(out: zipfile.ZipFile, name: str, content: bytes | str):
    """Pin ZIP metadata: preview/download must hash to the exact same artifact."""
    member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    member.create_system = 3
    member.external_attr = 0o100644 << 16
    member.compress_type = zipfile.ZIP_DEFLATED
    out.writestr(member, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)

def generate_aaps_zip(source: bytes, *, filename: str, app_key: str, app_name: str,
                      version: str, routes_json: str = "", schema_json: str = "", output_dir: str = "dist",
                      max_upload_bytes: int = 50 * 1024 * 1024):
    """Return (validated ZIP bytes, report) without disk, Docker, DB, or publisher state mutations."""
    if not _KEY.fullmatch(app_key or ""):
        _fail("GEN_APP_KEY", "Invalid application key.", "Use 3–64 lowercase letters, digits and hyphens, beginning and ending with alphanumeric.", "Configuration > Application key")
    if not (2 <= len(app_name.strip()) <= 100):
        _fail("GEN_APP_NAME", "Application name must be 2–100 characters.", "Enter an application display name.")
    if not _VERSION.fullmatch(version or ""):
        _fail("GEN_VERSION", "Invalid semantic version.", "Enter a version such as 1.0.0.")
    if output_dir not in _OUTPUT_DIRS:
        _fail("GEN_OUTPUT_DIR", "Unsupported frontend build output directory.", "Select dist or build. Custom outputs are not supported in this template.")
    if len(routes_json) > 64 * 1024 or len(schema_json) > 256 * 1024:
        _fail("GEN_MAPPING_LIMIT", "Configuration mapping is too large.",
              "Keep gateway routes under 64 KB and schema configuration under 256 KB.")
    if len(source) > max_upload_bytes:
        _fail("GEN_UPLOAD_LIMIT", "Source ZIP exceeds upload limit.", "Remove node_modules/build artifacts and reduce ZIP size.")
    report = analyze_source_zip(io.BytesIO(source), filename, max_upload_bytes)
    blocking = [c for c in report["checks"] if c["status"] in ("failed", "action_required")]
    # A developer-supplied schema mapping can resolve the only pending source
    # schema check during configuration. It cannot bypass other failures.
    if schema_json and schema_json.strip():
        blocking = [c for c in blocking if not (c["id"] == "database" and c["code"] == "POSTGRES_SCHEMA_REQUIRED")]
    if blocking or report["classification"] != "supported":
        issue = blocking[0] if blocking else None
        _fail("GEN_SOURCE_NOT_READY", issue["problem"] if issue else "Source layout is unsupported.",
              issue["correction"] if issue else "Use a supported React + FastAPI layout.", issue["location"] if issue else None)
    try: zf = zipfile.ZipFile(io.BytesIO(source))
    except zipfile.BadZipFile: _fail("GEN_BAD_ZIP", "Invalid ZIP input.", "Upload a valid source ZIP.")
    with zf:
        prefix = report["sourceRoot"] or ""
        mapping = _source_paths(zf, prefix)
        _find_react(zf, mapping)
        _, req, module = _backend(zf, mapping)
        preexisting = None
        if "augmis-app.yaml" in mapping:
            try: preexisting = yaml.safe_load(_read(zf, mapping, "augmis-app.yaml"))
            except yaml.YAMLError:
                _fail("GEN_EXISTING_MANIFEST", "Existing augmis-app.yaml cannot be parsed.", "Correct its YAML syntax.", "augmis-app.yaml")
            if not isinstance(preexisting, dict):
                _fail("GEN_EXISTING_MANIFEST", "Existing AAPS manifest is not an object.", "Use a valid AAPS v1 manifest.", "augmis-app.yaml")
        pg_detected = "postgresql" in report["detectedStack"]
        routes = _routes(routes_json, preexisting, zf, mapping)
        addons = _database(schema_json, preexisting, zf, mapping, pg_detected)
        # Existing AAPS declarations can be retained, but cannot bypass contract checks.
        manifest: dict[str, Any] = {
            "apiVersion": "apps.augmis.com/v1alpha1", "kind": "Application",
            "metadata": {"id": app_key, "name": app_name.strip(), "version": version},
            "runtime": {"deploymentMode": "dedicated", "buildType": "dockerfile", "context": ".", "dockerfile": "Dockerfile"},
            "services": {"web": {"type": "web", "port": 8080, "public": True,
                                  "health": {"path": "/health", "intervalSeconds": 15}}},
            "authentication": {"type": "augmis_oidc", "required": True},
            "lifecycle": {"startupTimeoutSeconds": 300, "rollbackEnabled": True},
            "gateway": {"routes": routes},
        }
        if addons:
            manifest["addons"] = addons
        if preexisting:
            # Only established AAPS mappings, not arbitrary configuration, carry forward.
            for key in ("permissions", "description"):
                if key == "permissions" and isinstance(preexisting.get(key), list):
                    manifest[key] = preexisting[key]
            if isinstance(preexisting.get("metadata"), dict) and preexisting["metadata"].get("description"):
                manifest["metadata"]["description"] = preexisting["metadata"]["description"]
        try: validate_schema(manifest, load_contract())
        except Exception as err:
            _fail("GEN_AAPS_CONTRACT", "Generated AAPS manifest does not meet platform contract.",
                  str(err)[:1200], "augmis-app.yaml")
        existing_dockerfile = "Dockerfile" in mapping and preexisting is not None
        if existing_dockerfile:
            # Preserve explicitly configured build and health strategy of pre-AAPS source.
            generated_docker = None
        else:
            generated_docker = _dockerfile(module, req, output_dir, "frontend/package-lock.json" in mapping)
        if generated_docker and "augmis_runtime_guard.py" in mapping:
            _fail("GEN_RESERVED_RUNTIME_FILE", "Source conflicts with the reserved AUGMIS runtime guard.",
                  "Remove augmis_runtime_guard.py from the source archive.", "augmis_runtime_guard.py")
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as out:
            for rel in sorted(mapping):
                if rel == "augmis-app.yaml" or (generated_docker and rel in ("Dockerfile", ".dockerignore", "augmis_generated_entry.py")):
                    continue
                # original member content is read only after safety checks and bounded by analyzer limits
                with zf.open(mapping[rel]) as reader:
                    data = reader.read(_MAX_SOURCE_SIZE + 1)
                if len(data) > _MAX_SOURCE_SIZE:
                    _fail("GEN_FILE_LIMIT", "Oversized source member.", "Reduce file size.", rel)
                _write_deterministic(out, rel, data)
            _write_deterministic(out, "augmis-app.yaml", yaml.safe_dump(manifest, sort_keys=False))
            if generated_docker:
                _write_deterministic(out, "Dockerfile", generated_docker)
                _write_deterministic(out, "augmis_generated_entry.py", _wrapper(module))
                _write_deterministic(out, "augmis_runtime_guard.py",
                    Path(__file__).with_name("c1d5_runtime_guard.py").read_bytes())
                _write_deterministic(out, ".dockerignore", ".git\nnode_modules\n.venv\n__pycache__\n.next\ndist\nbuild\n*.pyc\n.env\n")
        generated = result.getvalue()
        # Reuse the actual existing AAPS ingestion contract before reporting a
        # draft as generated. This writes to a disposable local temp directory
        # only; no Docker/DB/publisher state is touched.
        try:
            with tempfile.TemporaryDirectory(prefix="augmis_c1d5_draft_") as temp:
                tempzip = Path(temp) / "draft.zip"
                tempzip.write_bytes(generated)
                validate_application_package(tempzip)
        except Exception as error:
            _fail("GEN_INGEST_VALIDATION", "Generated package did not pass the existing AUGMIS AAPS validator.",
                  f"Review the application mapping and source files. Validator: {str(error)[:1000]}", "augmis-app.yaml")
        meta = {
            "stage": "C1-D5.2", "status": "generated", "sourceSha256": hashlib.sha256(source).hexdigest(),
            "artifactSha256": hashlib.sha256(generated).hexdigest(), "artifactBytes": len(generated),
            "applicationKey": app_key, "version": version,
            "dockerfileMode": "preserved" if existing_dockerfile else "generated",
            "manifestStatus": "contract_validated", "buildStatus": "not_checked", "runtimeStatus": "not_checked",
            "qualificationStatus": "not_checked", "publisherSubmissionEligible": False,
            "message": "AAPS archive generated and manifest contract-validated. Build, runtime and qualification have NOT been run.",
        }
        return generated, meta
