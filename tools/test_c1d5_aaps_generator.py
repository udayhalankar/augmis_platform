"""C1-D5.2: offline generator acceptance without Docker, DB, or Publisher writes."""
import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml
from services.api.app.services.c1d5_aaps_generator import generate_aaps_zip, GenerationIssue
from services.api.app.services.c1d5_source_analysis import analyze_source_zip
from tools.validate_package import validate_application_package

APP = {"app_key": "augmis-generator-test", "app_name": "Generator Test", "version": "1.0.0"}
ROUTES = '[{"path":"/api/items","methods":["GET","POST"]}]'
SCHEMA = '{"tables":[{"name":"items","columns":[{"name":"title","type":"text","maxLength":120}]}]}'


def raw_zip(extra=None, pg=True, pkg=True, health=True, output="dist"):
    files = {
        "frontend/package.json": json.dumps({"name": "test-react", "version": "1.0.0", "scripts": {"build": "vite build"},
            "dependencies": {"react": "19.0.0", "vite": "6.0.0"}}),
        "frontend/src/App.jsx": "export default function App(){return <h1>hello</h1>}",
        "frontend/index.html": "<!doctype html><html><div id='root'></div></html>",
        "app/main.py": "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/health')\ndef health(): return {'ok': True}\n" if health else "from fastapi import FastAPI\napp=FastAPI()\n",
        "requirements.txt": "fastapi==0.115.12\nuvicorn==0.34.2\n" + ("psycopg==3.2.6\n" if pg else ""),
        "gateway/routes.json": ROUTES,
    }
    if pkg: files["db/aaps-schema.json"] = SCHEMA
    if extra: files.update(extra)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem,"w",zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items(): z.writestr(name,content)
    return mem.getvalue()


def gen(contents, **kwargs):
    return generate_aaps_zip(contents, filename="raw.zip", **APP, **kwargs)


def fails(code, contents, **kwargs):
    with pytest.raises(GenerationIssue) as e: gen(contents, **kwargs)
    assert e.value.code == code
    assert e.value.as_dict()["correction"]


def test_supported_raw_react_fastapi_postgres(tmp_path):
    blob, meta = gen(raw_zip(), output_dir="dist")
    assert meta["publisherSubmissionEligible"] is False
    assert meta["dockerfileMode"] == "generated"
    assert meta["buildStatus"] == "not_checked"
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        assert "Dockerfile" in z.namelist()
        assert "augmis_generated_entry.py" in z.namelist()
        assert "USER 10001:10001" in z.read("Dockerfile").decode()
        m = yaml.safe_load(z.read("augmis-app.yaml"))
        assert m["addons"]["database"]["schema"]["tables"][0]["name"] == "items"
        assert m["gateway"]["routes"][0]["path"] == "/api/items"
    target = tmp_path / "generated.zip"
    target.write_bytes(blob)
    assert validate_application_package(target)["status"] == "VALID"


def test_no_postgres_builds_without_database_addon(tmp_path):
    blob, meta = gen(raw_zip(pg=False, pkg=False))
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        manifest = yaml.safe_load(z.read("augmis-app.yaml"))
    assert "addons" not in manifest
    target = tmp_path / "generated.zip";target.write_bytes(blob)
    assert validate_application_package(target)["status"] == "VALID"


def test_postgres_missing_mapping_is_actionable():
    fails("GEN_SOURCE_NOT_READY", raw_zip(pkg=False))


def test_explicit_schema_can_resolve_mapping_gap():
    blob, _ = gen(raw_zip(pkg=False), schema_json=SCHEMA)
    assert blob


def test_no_api_routes_is_actionable():
    src = raw_zip(extra={"gateway/routes.json": ""})
    fails("GEN_ROUTES_JSON", src)


def test_explicit_routes_allowed_without_source_route_file():
    src = raw_zip(extra={"gateway/routes.json": ""})
    blob, _ = gen(src,routes_json=ROUTES)
    assert blob


def test_health_required():
    fails("GEN_SOURCE_NOT_READY", raw_zip(health=False))


def test_invalid_version_rejected():
    with pytest.raises(GenerationIssue) as e:
        generate_aaps_zip(raw_zip(), filename="raw.zip", app_key=APP["app_key"], app_name=APP["app_name"], version="1.0.0;DROP")
    assert e.value.code=="GEN_VERSION"


def test_invalid_app_key_rejected():
    with pytest.raises(GenerationIssue) as e:
        generate_aaps_zip(raw_zip(), filename="raw.zip", app_key="../../invalid", app_name=APP["app_name"], version="1.0.0")
    assert e.value.code=="GEN_APP_KEY"


def test_unsupported_output_dir():
    fails("GEN_OUTPUT_DIR", raw_zip(), output_dir="../../temp")


def test_invalid_route_contract():
    fails("GEN_INGEST_VALIDATION", raw_zip(), routes_json='[{"path":"/not-api","methods":["GET"]}]')


def test_invalid_schema_contract():
    fails("GEN_AAPS_CONTRACT", raw_zip(), schema_json='{"tables":[{"name":"INVALID-TABLE","columns":[{"name":"title","type":"text","maxLength":120}]}]}')


def test_zip_path_escape_rejected():
    b = io.BytesIO()
    with zipfile.ZipFile(b,"w") as z: z.writestr("../test.py", "not safe")
    fails("GEN_SOURCE_NOT_READY", b.getvalue())


def test_existing_aaps_source_preserves_dockerfile(tmp_path):
    prepared, _ = gen(raw_zip())
    preserved = zipfile.ZipFile(io.BytesIO(prepared)).read("Dockerfile")
    new_blob, report = gen(prepared)
    assert report["dockerfileMode"] == "preserved"
    with zipfile.ZipFile(io.BytesIO(new_blob)) as z:
        assert z.read("Dockerfile") == preserved
    (tmp_path / "package.zip").write_bytes(new_blob)
    assert validate_application_package(tmp_path / "package.zip")["status"] == "VALID"


def test_analyzer_accepts_existing_aaps_postgres_schema():
    prepared, _ = gen(raw_zip())
    report = analyze_source_zip(io.BytesIO(prepared), "app.zip", len(prepared)+1)
    assert report["analysisPassed"] is True
    assert next(c for c in report["checks"] if c["id"] == "database")["status"] == "passed"


def test_archive_generation_does_not_modify_source():
    b=raw_zip(); before=b[:]
    gen(b)
    assert b==before


def test_deterministic_generation_for_identical_source():
    b=raw_zip()
    a,meta_a=gen(b)
    c,meta_b=gen(b)
    assert a==c
    assert meta_a["artifactSha256"]==meta_b["artifactSha256"]
