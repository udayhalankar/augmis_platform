from __future__ import annotations
import copy
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
import pytest
import yaml
from services.api.app.services.aaps_deployment_contract import (
    assess_manifest, migration_contract, route_contract,
    fail_closed_if_unimplemented, DeploymentContractError,
)
from tools.validate_package import validate_application_package, PackageValidationError

BASE = Path(__file__).resolve().parents[1]

@pytest.fixture
def manifest():
    return {
      'apiVersion':'apps.augmis.com/v1alpha1','kind':'Application',
      'metadata':{'id':'augmis-example-test','name':'Example Test','version':'1.0.0'},
      'runtime':{'deploymentMode':'dedicated','buildType':'dockerfile','context':'.','dockerfile':'Dockerfile'},
      'services':{'web':{'type':'web','port':8080,'public':True,'health':{'path':'/health'}}},
      'addons':{'database':{'type':'postgresql','version':'15','storage':'1Gi'}},
      'authentication':{'type':'augmis_oidc','required':True},
    }

def test_workorder_manifest_blocked_before_start(manifest):
    manifest['metadata']['id']='augmis-maintenance-work-orders'
    with pytest.raises(DeploymentContractError,match='C1C_SCHEMA_DECLARATION_REQUIRED'):
        fail_closed_if_unimplemented(manifest,legacy_crud=False)

@pytest.mark.parametrize('key,expected', [('metadata','AAPS'),('runtime','AAPS_RUNTIME_UNSUPPORTED')])
def test_invalid_runtime(manifest,key,expected):
    if key=='runtime':manifest['runtime']['buildType']='oci'
    else:manifest['runtime']['deploymentMode']='x'
    with pytest.raises(DeploymentContractError,match='AAPS_RUNTIME_UNSUPPORTED'):
        assess_manifest(manifest)

def test_valid_capabilities(manifest):
    p=assess_manifest(manifest)
    assert p.requires_private_database and p.health_path=='/health'

def test_unsupported_database(manifest):
    manifest['addons']['database']['type']='mysql'
    with pytest.raises(DeploymentContractError,match='AAPS_DATABASE_UNSUPPORTED'):
        assess_manifest(manifest)

def test_database_requires_augmis_auth(manifest):
    manifest['authentication']={'type':'none','required':False}
    with pytest.raises(DeploymentContractError,match='AAPS_AUTH_REQUIRED'):
        assess_manifest(manifest)

def test_no_db_ordinary_path(manifest):
    del manifest['addons']
    fail_closed_if_unimplemented(manifest,legacy_crud=False)

def test_existing_crud_path_unchanged(manifest):
    fail_closed_if_unimplemented(manifest,legacy_crud=True)

def test_migration_contract_missing(manifest):
    with pytest.raises(DeploymentContractError,match='C1C_SCHEMA_DECLARATION_REQUIRED'):
        fail_closed_if_unimplemented(manifest,legacy_crud=False)

def test_gateway_contract_missing(manifest):
    manifest['addons']['database']['migrations']=[{'path':'db/migrations/001.sql','sha256':'a'*64}]
    with pytest.raises(DeploymentContractError,match='C1C_GATEWAY_ROUTE_CONTRACT_REQUIRED'):
        fail_closed_if_unimplemented(manifest,legacy_crud=False)

def test_adapter_still_fail_closed(manifest):
    manifest['addons']['database']['migrations']=[{'path':'db/migrations/001.sql','sha256':'a'*64}]
    manifest['gateway']={'routes':[{'path':'/api/work-orders','methods':['GET','POST']}]}
    with pytest.raises(DeploymentContractError,match='C1C_PRIVATE_DB_ADAPTER_PENDING'):
        fail_closed_if_unimplemented(manifest,legacy_crud=False)

def test_declared_routes(manifest):
    manifest['gateway']={'routes':[{'path':'/api/work-orders','methods':['GET','POST']},
                                   {'path':'/api/work-orders/{id:uuid}','methods':['GET','PUT','DELETE']} ]}
    assert len(route_contract(manifest))==2

@pytest.mark.parametrize('path',['/admin','//api/x','/api/x/../../etc','/api/x/{id}','/api/foo/?a=b','/api/x/%2e%2e'])
def test_dangerous_routes_denied(manifest,path):
    manifest['gateway']={'routes':[{'path':path,'methods':['GET']}]}
    with pytest.raises(DeploymentContractError):route_contract(manifest)

def test_duplicate_routes_denied(manifest):
    manifest['gateway']={'routes':[{'path':'/api/x','methods':['GET']},{'path':'/api/x','methods':['POST']}]}
    with pytest.raises(DeploymentContractError,match='DUPLICATE'):route_contract(manifest)

def test_duplicate_methods_denied(manifest):
    manifest['gateway']={'routes':[{'path':'/api/x','methods':['GET','GET']}]}
    with pytest.raises(DeploymentContractError,match='METHOD'):route_contract(manifest)

@pytest.mark.parametrize('path',['../../bad.sql','db/migrations/../a.sql','/etc/passwd','db/migrations/a.txt','db/migrations/\\evil.sql'])
def test_migration_path_denied(manifest,path):
    manifest['addons']['database']['migrations']=[{'path':path,'sha256':'a'*64}]
    with pytest.raises(DeploymentContractError):migration_contract(manifest)

def test_migration_requires_digest(manifest):
    manifest['addons']['database']['migrations']=[{'path':'db/migrations/001.sql','sha256':'1234'}]
    with pytest.raises(DeploymentContractError,match='DIGEST'):migration_contract(manifest)

def test_ingestion_detects_checksum_mismatch(manifest,tmp_path):
    manifest['addons']['database']['migrations']=[{'path':'db/migrations/001.sql','sha256':'f'*64}]
    (tmp_path/'db'/'migrations').mkdir(parents=True)
    (tmp_path/'db'/'migrations'/'001.sql').write_text('select 1;')
    (tmp_path/'Dockerfile').write_text('FROM scratch')
    (tmp_path/'augmis-app.yaml').write_text(yaml.safe_dump(manifest))
    z=tmp_path/'test.zip'
    with zipfile.ZipFile(z,'w') as archive:
        for path in ['Dockerfile','augmis-app.yaml','db/migrations/001.sql']:
            archive.write(tmp_path/path,path)
    with pytest.raises(PackageValidationError,match='DIGEST_MISMATCH'):
        validate_application_package(z)

def test_ingestion_accepts_matching_digest(manifest,tmp_path):
    content=b'-- only a checksum test\nSELECT 1;\n'
    manifest['addons']['database']['migrations']=[{'path':'db/migrations/001.sql','sha256':hashlib.sha256(content).hexdigest()}]
    (tmp_path/'Dockerfile').write_text('FROM scratch')
    (tmp_path/'augmis-app.yaml').write_text(yaml.safe_dump(manifest))
    z=tmp_path/'test.zip'
    with zipfile.ZipFile(z,'w') as archive:
        archive.writestr('Dockerfile','FROM scratch')
        archive.writestr('augmis-app.yaml',yaml.safe_dump(manifest))
        archive.writestr('db/migrations/001.sql',content)
    result=validate_application_package(z)
    assert result['status']=='VALID'

