"""Small dedicated-instance PostgreSQL CRUD reference application.

Security boundary: serve ONLY through a trusted AUGMIS authenticated runtime gateway.
APP_TENANT_ID is provisioned by the trusted deployment operator, never a user header.
"""
import os
import hashlib
import threading
import time
import jwt
from cryptography.hazmat.primitives import serialization
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException, Query, Response, Request, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, ConfigDict

BASE = Path(__file__).parent
TENANT_ID = os.getenv("APP_TENANT_ID", "")
INSTANCE_ID = os.getenv("AUGMIS_RUNTIME_INSTANCE_ID", "")
APPLICATION_ID = os.getenv("AUGMIS_RUNTIME_APPLICATION_ID", "")
PUBLIC_KEY_FILE = os.getenv("AUGMIS_RUNTIME_ASSERTION_PUBLIC_KEY_FILE", "")
PASSWORD_FILE = os.getenv("PGPASSWORD_FILE", "/run/secrets/db_password")
PGHOST = os.getenv("PGHOST", "")
PGDATABASE = os.getenv("PGDATABASE", "")
PGUSER = os.getenv("PGUSER", "")
PUBLIC_KEY = None
_seen_tokens = {}
_seen_lock = threading.Lock()


async def require_signed_gateway(request: Request):
    """Reject direct container/relay API access, including unsigned writes.

    C1-B4 must issue the signed token from an authorized gateway context,
    binding tenant, instance, method, relative API path and request body.
    """
    authorization = request.headers.get("X-Augmis-Runtime-Assertion", "")
    if not authorization or len(authorization) > 8192 or PUBLIC_KEY is None:
        raise HTTPException(401, "Signed AUGMIS runtime request required")
    try:
        claims = jwt.decode(
            authorization, PUBLIC_KEY, algorithms=["EdDSA"],
            audience=f"augmis.runtime:{INSTANCE_ID}", issuer="augmis.control-plane",
            options={"require": ["exp", "iat", "nbf", "jti", "iss", "aud", "sub"]},
            leeway=2,
        )
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "Invalid AUGMIS runtime request") from None
    expected_scope = "records.read" if request.method == "GET" else "records.write"
    bound_path = request.url.path
    if (claims.get("typ") != "augmis.runtime.crud.v1"
            or claims.get("tenantId") != TENANT_ID
            or claims.get("applicationId") != APPLICATION_ID
            or claims.get("instanceId") != INSTANCE_ID
            or claims.get("method") != request.method
            or claims.get("path") != bound_path
            or expected_scope not in (claims.get("scope") or [])
            or claims.get("bodySha256") != hashlib.sha256(await request.body()).hexdigest()
            or claims.get("querySha256") != hashlib.sha256(request.url.query.encode("utf-8")).hexdigest()):
        raise HTTPException(403, "Runtime request scope mismatch")
    # Per-process one-time JTI check. This reference image runs one worker.
    # Production multi-worker/host deployments need a shared atomic replay store.
    with _seen_lock:
        now = time.time()
        for token_id, expires in list(_seen_tokens.items()):
            if expires < now:
                _seen_tokens.pop(token_id, None)
        jti = claims["jti"]
        if jti in _seen_tokens or len(_seen_tokens) > 10000:
            raise HTTPException(401, "Replayed AUGMIS runtime request")
        _seen_tokens[jti] = float(claims["exp"]) + 2



def db():
    # Only the restricted runtime role receives this read-only-mounted secret.
    password = Path(PASSWORD_FILE).read_text(encoding="utf-8").strip()
    connection = psycopg.connect(
        host=PGHOST, dbname=PGDATABASE, user=PGUSER, password=password,
        row_factory=dict_row, connect_timeout=5,
    )
    # Transaction-local RLS context. The tenant identity is injected by AUGMIS,
    # never accepted from a browser-controlled header or request body.
    connection.execute("SELECT set_config('augmis.tenant_id', %s, true)", (TENANT_ID,))
    return connection


def setup():
    global PUBLIC_KEY
    uuid.UUID(TENANT_ID)
    uuid.UUID(INSTANCE_ID)
    uuid.UUID(APPLICATION_ID)
    if not all((PGHOST, PGDATABASE, PGUSER, PASSWORD_FILE, PUBLIC_KEY_FILE)):
        raise RuntimeError("Required AUGMIS private runtime configuration is missing")
    pem = Path(PUBLIC_KEY_FILE).read_bytes()
    PUBLIC_KEY = serialization.load_pem_public_key(pem)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if not isinstance(PUBLIC_KEY, Ed25519PublicKey):
        raise RuntimeError("Invalid AUGMIS signing verifier")
    # No runtime DDL: migrations are applied by the trusted C1-B3 initializer.
    with db() as con:
        row = con.execute("SELECT row_security_active('public.sample_records'::regclass) AS ok").fetchone()
        if not row or not row["ok"]:
            raise RuntimeError("Restricted CRUD role must have active PostgreSQL RLS")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup()
    yield


app = FastAPI(title="AUGMIS Sample CRUD", version="1.2.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


class RecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=50)
    quantity: int = Field(ge=0, le=10000000)
    unit_price: Decimal = Field(ge=0, le=9999999999, decimal_places=2)
    notes: str = Field(default="", max_length=1000)

    @field_validator("name", "category")
    @classmethod
    def not_blank(cls, val):
        cleaned = val.strip()
        if not cleaned:
            raise ValueError("Must not be blank")
        return cleaned


def printable(row):
    row = dict(row)
    row["id"] = str(row["id"])
    row["unit_price"] = str(row["unit_price"])
    row["total"] = str(row["quantity"] * Decimal(row["unit_price"]))
    for key in ("created_at", "updated_at"):
        row[key] = row[key].isoformat()
    return row


@app.get("/health")
def health():
    try:
        with db() as con:
            r = con.execute("SELECT row_security_active('public.sample_records'::regclass) AS ok").fetchone()
            if not r or not r["ok"]:
                raise HTTPException(503, "Database RLS unavailable")
    except psycopg.Error:
        raise HTTPException(503, "Database unavailable")
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(BASE / "static" / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/records", dependencies=[Depends(require_signed_gateway)])
def list_records(q: str = Query(default="", max_length=120)):
    with db() as con:
        rows = con.execute("""SELECT * FROM sample_records WHERE tenant_id=%s AND NOT is_deleted
                  AND (%s='' OR name ILIKE ('%%' || %s || '%%')) ORDER BY created_at DESC, id DESC LIMIT 500""",
                  (TENANT_ID, q, q)).fetchall()
    return [printable(r) for r in rows]


@app.get("/api/records/{record_id}", dependencies=[Depends(require_signed_gateway)])
def get_record(record_id: uuid.UUID):
    with db() as con:
        r = con.execute("SELECT * FROM sample_records WHERE id=%s AND tenant_id=%s AND NOT is_deleted", (record_id, TENANT_ID)).fetchone()
    if not r:
        raise HTTPException(404, "Record not found")
    return printable(r)


@app.post("/api/records", status_code=201, dependencies=[Depends(require_signed_gateway)])
def create_record(data: RecordInput):
    rid = uuid.uuid4()
    with db() as con:
        r = con.execute("""INSERT INTO sample_records
            (id,tenant_id,name,category,quantity,unit_price,notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (rid, TENANT_ID, data.name, data.category, data.quantity, data.unit_price, data.notes)).fetchone()
    return printable(r)


@app.put("/api/records/{record_id}", dependencies=[Depends(require_signed_gateway)])
def update_record(record_id: uuid.UUID, data: RecordInput):
    with db() as con:
        r = con.execute("""UPDATE sample_records SET name=%s, category=%s, quantity=%s,
          unit_price=%s,notes=%s,updated_at=NOW() WHERE id=%s AND tenant_id=%s
          AND NOT is_deleted RETURNING *""",
          (data.name, data.category, data.quantity, data.unit_price, data.notes,record_id,TENANT_ID)).fetchone()
    if not r:
        raise HTTPException(404, "Record not found")
    return printable(r)


@app.delete("/api/records/{record_id}", status_code=204, dependencies=[Depends(require_signed_gateway)])
def delete_record(record_id: uuid.UUID):
    with db() as con:
        r = con.execute("""UPDATE sample_records SET is_deleted=true, updated_at=NOW()
             WHERE id=%s AND tenant_id=%s AND NOT is_deleted""", (record_id,TENANT_ID))
    if r.rowcount != 1:
        raise HTTPException(404, "Record not found")
    return Response(status_code=204)


@app.get("/api/summary", dependencies=[Depends(require_signed_gateway)])
def summary():
    with db() as con:
        stats = con.execute("""SELECT COUNT(*) AS count,
            COALESCE(SUM(quantity),0) AS quantity,
            COALESCE(SUM(quantity*unit_price),0) AS amount
            FROM sample_records WHERE tenant_id=%s AND NOT is_deleted""", (TENANT_ID,)).fetchone()
    return {"count": stats["count"], "quantity":stats["quantity"], "amount":str(stats["amount"])}
