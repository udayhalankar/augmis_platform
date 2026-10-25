"""C1-B4 request-bound Ed25519 signatures from authorized gateway context."""
from __future__ import annotations
import hashlib
import os
import re
import time
import uuid
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from services.api.app.services.private_crud_runtime import CrudRuntimeError, _expected_application, signing_material, signing_private_key_bytes
from services.api.app.core.config import settings

ROUTE = re.compile(r'/api/(?:summary|records(?:/[0-9a-f-]{36})?)\Z')
ITEM = re.compile(r'/api/records/[0-9a-f-]{36}\Z')


def make_crud_request_assertion(*, context: dict, method: str,
                                relative_path: str, body: bytes,
                                raw_query: str = '') -> str | None:
    if (os.environ.get('AUGMIS_C1B_CRUD_PRIVATE_RUNTIME_ENABLED') != '1' or
            str(settings.app_env).lower() not in {'development', 'dev'}):
        return None
    if context['application'].id != _expected_application():
        return None
    path = '/' + relative_path.lstrip('/')
    if (not ROUTE.fullmatch(path) or len(body) > 1024 * 1024 or
            method not in {'GET', 'POST', 'PUT', 'DELETE'}):
        raise CrudRuntimeError('C1B4_ROUTE_NOT_ALLOWED')
    if not ((method == 'GET' and not body) or
            (method == 'POST' and path == '/api/records') or
            (method in {'PUT', 'DELETE'} and ITEM.fullmatch(path))):
        raise CrudRuntimeError('C1B4_OPERATION_NOT_ALLOWED')
    private, _ = signing_material()
    signer = load_pem_private_key(signing_private_key_bytes(private), password=None)
    now = int(time.time())
    claims = {
        'iss': 'augmis.control-plane',
        'aud': f"augmis.runtime:{context['instance'].id}",
        'sub': str(context['user'].id),
        'iat': now, 'nbf': now, 'exp': now + 20, 'jti': str(uuid.uuid4()),
        'typ': 'augmis.runtime.crud.v1',
        'tenantId': str(context['tenant'].id),
        'applicationId': str(context['application'].id),
        'instanceId': str(context['instance'].id),
        'method': method, 'path': path,
        'querySha256': hashlib.sha256(raw_query.encode('utf-8')).hexdigest(),
        'bodySha256': hashlib.sha256(body).hexdigest(),
        'scope': ['records.read' if method == 'GET' else 'records.write'],
    }
    return jwt.encode(claims, signer, algorithm='EdDSA', headers={'typ': 'JWT'})
