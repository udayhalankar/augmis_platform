"""C1-D5.1 pure source-inspection tests. No Docker or database required."""
import io
import json
import stat
import zipfile

from services.api.app.services.c1d5_source_analysis import analyze_source_zip


GOOD = {
    "frontend/package.json": json.dumps({"dependencies": {"react": "19.0.0"}, "scripts": {"build": "vite build"}}),
    "frontend/src/main.tsx": "import React from 'react';",
    "backend/requirements.txt": "fastapi==0.115.12\npsycopg[binary]==3.2.6",
    "backend/app/main.py": "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/health')\ndef health(): return {}",
    "db/schema.sql": "CREATE TABLE service_requests (id UUID PRIMARY KEY);",
}


def analyze(entries=None, filename="source.zip", *, upload_limit=20_000_000):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, body in (GOOD if entries is None else entries).items():
            z.writestr(name, body)
    buffer.seek(0)
    return analyze_source_zip(buffer, filename, upload_limit)


def check(report, ident):
    return next(x for x in report["checks"] if x["id"] == ident)


def test_valid_supported_stack():
    result = analyze()
    assert result["detectedStack"] == "react+fastapi+postgresql"
    assert result["classification"] == "supported"
    assert result["analysisPassed"] is True
    assert result["publisherSubmissionEligible"] is False
    for id in ["source_archive", "source_structure", "frontend", "backend", "database", "health", "secrets"]:
        assert check(result, id)["status"] == "passed"
    for id in ["artifacts", "build", "runtime", "qualification"]:
        assert check(result, id)["status"] == "not_checked"


def test_nested_project_root():
    result = analyze({"my-project/" + name: value for name, value in GOOD.items()})
    assert result["sourceRoot"] == "my-project"
    assert result["analysisPassed"]


def test_invalid_zip():
    result = analyze_source_zip(io.BytesIO(b"not zip"), "app.zip", 123000)
    assert check(result, "source_archive")["code"] == "SOURCE_ZIP_INVALID"
    assert result["publisherSubmissionEligible"] is False


def test_non_zip_extension():
    result = analyze(filename="app.exe")
    assert check(result, "source_archive")["code"] == "SOURCE_ZIP_REQUIRED"


def test_source_size_limit():
    result = analyze(upload_limit=10)
    assert check(result, "source_archive")["code"] == "SOURCE_UPLOAD_TOO_LARGE"


def test_empty_archive():
    result = analyze({})
    assert check(result, "source_archive")["code"] == "SOURCE_EMPTY_ARCHIVE"


def test_traversal_rejected():
    result = analyze({**GOOD, "../.env": "PASSWORD=SECRET-DO-NOT-PRINT"})
    assert check(result, "source_archive")["code"] == "SOURCE_UNSAFE_PATH"
    assert "SECRET-DO-NOT-PRINT" not in json.dumps(result)


def test_absolute_path_rejected():
    result = analyze({**GOOD, "/etc/passwd": "secret"})
    assert check(result, "source_archive")["code"] == "SOURCE_UNSAFE_PATH"


def test_windows_absolute_path_rejected():
    result = analyze({**GOOD, "C:\\evil.txt": "bad"})
    assert check(result, "source_archive")["code"] == "SOURCE_UNSAFE_PATH"


def test_duplicate_path_rejected():
    result = analyze({**GOOD, "frontend/PACKAGE.JSON": "{}"})
    assert check(result, "source_archive")["code"] == "SOURCE_DUPLICATE_PATH"


def test_symlink_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        symlink = zipfile.ZipInfo("backend/link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(symlink, "../elsewhere")
    buffer.seek(0)
    result = analyze_source_zip(buffer, "link.zip", 200000)
    assert check(result, "source_archive")["code"] == "SOURCE_SYMLINK"


def test_secrets_file_is_blocker():
    result = analyze({**GOOD, "backend/.env": "DATABASE_PASSWORD=DO-NOT-EXPOSE"})
    assert check(result, "secrets")["status"] == "failed"
    assert "DO-NOT-EXPOSE" not in json.dumps(result)
    assert result["analysisPassed"] is False


def test_env_example_allowed():
    result = analyze({**GOOD, "backend/.env.example": "DATABASE_URL="})
    assert check(result, "secrets")["status"] == "passed"


def test_react_missing_build_script():
    entries = dict(GOOD)
    entries["frontend/package.json"] = json.dumps({"dependencies": {"react": "19"}})
    result = analyze(entries)
    assert check(result, "frontend")["code"] == "REACT_BUILD_SCRIPT_MISSING"
    assert check(result, "frontend")["correction"]


def test_react_missing_source():
    entries = dict(GOOD)
    entries.pop("frontend/src/main.tsx")
    result = analyze(entries)
    assert check(result, "frontend")["code"] == "REACT_SOURCE_MISSING"


def test_malformed_package_json():
    entries = dict(GOOD)
    entries["frontend/package.json"] = "{BROKEN"
    result = analyze(entries)
    assert check(result, "frontend")["code"] == "FRONTEND_PACKAGE_INVALID"
    assert check(result, "frontend")["location"] == "frontend/package.json"


def test_backend_missing_requirements():
    entries = dict(GOOD)
    entries.pop("backend/requirements.txt")
    result = analyze(entries)
    assert check(result, "backend")["code"] == "FASTAPI_REQUIREMENT_MISSING"


def test_backend_missing_entry():
    entries = dict(GOOD)
    entries.pop("backend/app/main.py")
    result = analyze(entries)
    assert check(result, "backend")["code"] == "FASTAPI_ENTRYPOINT_MISSING"


def test_postgres_requires_schema():
    entries = dict(GOOD)
    entries.pop("db/schema.sql")
    result = analyze(entries)
    assert check(result, "database")["code"] == "POSTGRES_SCHEMA_REQUIRED"


def test_health_check_required():
    entries = dict(GOOD)
    entries["backend/app/main.py"] = "from fastapi import FastAPI\napp=FastAPI()"
    result = analyze(entries)
    assert check(result, "health")["code"] == "HEALTH_ROUTE_REQUIRED"


def test_nextjs_detected_but_not_converted():
    entries = dict(GOOD)
    entries["frontend/package.json"] = json.dumps({"dependencies": {"next": "15", "react": "19"}, "scripts": {"build": "next build"}})
    result = analyze(entries)
    assert result["classification"] == "guided_mapping"
    assert check(result, "frontend")["code"] == "NEXTJS_MAPPING_PENDING"


def test_analysis_does_not_mutate_stream_or_file():
    original = {**GOOD}
    result = analyze(original)
    assert result["sourceSha256"]
    assert result["publisherSubmissionEligible"] is False
    assert original == GOOD


def test_existing_artifacts_not_claimed_validated():
    entries = {**GOOD, "augmis-app.yaml": "fake", "Dockerfile": "FROM scratch"}
    result = analyze(entries)
    assert check(result, "artifacts")["status"] == "passed"
    assert "not validated" in check(result, "artifacts")["problem"]
    assert check(result, "build")["status"] == "not_checked"
    assert result["publisherSubmissionEligible"] is False


def test_local_env_variant_is_blocker():
    result = analyze({**GOOD, "frontend/.env.development.local": "PRIVATE=DO-NOT-EXPOSE"})
    assert check(result, "secrets")["code"] == "SOURCE_SENSITIVE_FILE"
    assert "DO-NOT-EXPOSE" not in json.dumps(result)

# C1-D5.1 acceptance correction: source examples/strings are not application routes.
def test_test_fixture_string_does_not_count_as_fastapi_or_health():
    entries = {
        "tools/test_example.py": '''SAMPLE = """from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health(): return {}"""''',
        "README.md": "This archive is an installer, not an application.",
    }
    result = analyze(entries)
    assert check(result, "backend")["code"] == "FASTAPI_NOT_DETECTED"
    assert check(result, "health")["status"] == "not_checked"
    assert check(result, "health")["code"] == "HEALTH_SOURCE_NOT_VERIFIABLE"
    assert result["analysisPassed"] is False


def test_docstring_fake_app_cannot_satisfy_backend_requirements():
    entries = dict(GOOD)
    entries["backend/app/main.py"] = '''"""\napp=FastAPI()\n@app.get('/health')\ndef health(): return {}\n"""\n'''
    result = analyze(entries)
    assert check(result, "backend")["code"] == "FASTAPI_ENTRYPOINT_MISSING"
    assert check(result, "health")["status"] == "not_checked"
    assert result["publisherSubmissionEligible"] is False


def test_comments_cannot_satisfy_backend_or_health():
    entries = dict(GOOD)
    entries["backend/app/main.py"] = "# from fastapi import FastAPI\n# app = FastAPI()\n# @app.get('/health')\n"
    result = analyze(entries)
    assert check(result, "backend")["code"] == "FASTAPI_ENTRYPOINT_MISSING"
    assert check(result, "health")["code"] == "HEALTH_SOURCE_NOT_VERIFIABLE"


def test_app_inside_python_test_module_is_not_runtime_entrypoint():
    entries = dict(GOOD)
    entries.pop("backend/app/main.py")
    entries["backend/tests/test_api.py"] = GOOD["backend/app/main.py"]
    result = analyze(entries)
    assert check(result, "backend")["code"] == "FASTAPI_ENTRYPOINT_MISSING"
    assert check(result, "health")["status"] == "not_checked"


def test_health_route_must_bind_actual_app_and_use_get():
    entries = dict(GOOD)
    entries["backend/app/main.py"] = '''from fastapi import FastAPI
app=FastAPI()
@other.get('/health')
def health(): return {}
@app.post('/health')
def post_health(): return {}
'''
    result = analyze(entries)
    assert check(result, "backend")["status"] == "passed"
    assert check(result, "health")["code"] == "HEALTH_ROUTE_REQUIRED"


def test_fastapi_import_alias_and_api_route_get_recognized():
    entries = dict(GOOD)
    entries["backend/app/main.py"] = '''from fastapi import FastAPI as WebApp
api=WebApp()
@api.api_route('/health', methods=['GET'])
def health(): return {}
'''
    result = analyze(entries)
    assert check(result, "backend")["status"] == "passed"
    assert check(result, "health")["status"] == "passed"
    assert check(result, "runtime")["status"] == "not_checked"


def test_actual_runtime_health_not_claimed_from_source():
    result = analyze()
    assert check(result, "health")["code"] == "HEALTH_ROUTE_DETECTED"
    assert "not executed" in check(result, "health")["problem"]
    assert check(result, "runtime")["status"] == "not_checked"
    assert result["publisherSubmissionEligible"] is False


def test_installer_shaped_archive_does_not_false_pass_health():
    entries = {
        "INSTALL_C1D5_1.py": "from pathlib import Path\n",
        "NEW/tools/test_c1d5_source_analysis.py": (
            'GOOD = {"backend/app/main.py": "from fastapi import FastAPI\\n'
            'app=FastAPI()\\n@app.get(\\"/health\\")"}\n'
        ),
        "NEW/services/api/app/services/c1d5_source_analysis.py": (
            "def analyze_source_zip(stream, filename, max_upload_bytes): pass\n"
        ),
    }
    result = analyze(entries)
    assert check(result, "health")["status"] == "not_checked"
    assert check(result, "backend")["status"] != "passed"
    assert result["publisherSubmissionEligible"] is False
