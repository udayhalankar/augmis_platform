"""C1-C3: request-bound AUGMIS signatures for *declared* app API routes.

Requires the already authenticated, tenant-authorized, subscription-authorized,
running-instance-bound gateway context from routes/instances.py. Never accepts
an application ID, tenant ID or signing key from client headers.
"""
from __future__ import annotations
import hashlib
import re
import time
import uuid
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from services.api.app.services.aaps_deployment_contract import route_contract, DeploymentContractError
from services.api.app.services.private_crud_runtime import signing_material, signing_private_key_bytes, CrudRuntimeError

_UUID='[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


def declared_route_allowed(manifest: dict, *, method: str, path: str) -> bool:
    if not isinstance(path,str) or len(path)>256 or '?' in path or '#' in path or '%' in path or '//' in path:
        return False
    for template,methods in route_contract(manifest):
        if method not in methods:continue
        expression='^'+re.escape(template).replace(re.escape('{id:uuid}'),_UUID)+'$'
        if re.fullmatch(expression,path):return True
    return False


def make_aaps_request_assertion(*, context:dict, method:str, relative_path:str,
                                body:bytes,raw_query:str='') -> str:
    manifest=context['version'].manifest
    path='/'+relative_path.lstrip('/')
    if (not declared_route_allowed(manifest,method=method,path=path) or
            len(body)>1048576 or (method in {'GET','DELETE'} and body) or
            len(raw_query)>2048):
        raise CrudRuntimeError('C1C_ROUTE_OR_METHOD_NOT_ALLOWED')
    private,_=signing_material()
    signer=load_pem_private_key(signing_private_key_bytes(private),password=None)
    issued=int(time.time())
    claims={
        'iss':'augmis.control-plane',
        'aud':f"augmis.runtime:{context['instance'].id}",
        'sub':str(context['user'].id),
        'iat':issued,'nbf':issued,'exp':issued+20,
        'jti':str(uuid.uuid4()),
        'typ':'augmis.runtime.crud.v1',
        'tenantId':str(context['tenant'].id),
        'applicationId':str(context['application'].id),
        'instanceId':str(context['instance'].id),
        'method':method,'path':path,
        'querySha256':hashlib.sha256(raw_query.encode()).hexdigest(),
        'bodySha256':hashlib.sha256(body).hexdigest(),
        'scope':['records.read' if method=='GET' else 'records.write'],
    }
    return jwt.encode(claims,signer,algorithm='EdDSA',headers={'typ':'JWT'})
