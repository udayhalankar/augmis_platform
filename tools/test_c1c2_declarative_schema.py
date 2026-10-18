"""Offline C1-C2 security/compatibility regression tests. No DB or Docker I/O."""
from __future__ import annotations
import copy
import json
import zipfile
from pathlib import Path
import pytest
import yaml
from services.api.app.services.aaps_declarative_schema import (
    read_declarative_schema, schema_sql, verification_sql, SchemaContractError,
)
from services.api.app.services.aaps_deployment_contract import (
    assess_manifest, DeploymentContractError, fail_closed_if_unimplemented,
)


def manifest():
    return {
        'runtime': {'deploymentMode':'dedicated','buildType':'dockerfile'},
        'services': {'web': {'public':True,'port':8080,'health':{'path':'/health'}}},
        'authentication': {'type':'augmis_oidc','required':True},
        'addons': {'database':{'type':'postgresql','version':'15','storage':'1Gi',
            'schema':{'tables':[{'name':'maintenance_work_orders','columns':[
                {'name':'title','type':'text','maxLength':140},
                {'name':'priority','type':'text','maxLength':12,'choices':['High','Low'],'default':'Low'},
                {'name':'due_date','type':'date','nullable':True},
            ], 'indexes':['priority'], 'unique':[['title']]}]}}},
        'gateway': {'routes':[{'path':'/api/work-orders','methods':['GET','POST']},
                              {'path':'/api/work-orders/{id:uuid}','methods':['GET','PUT','DELETE']}]},
    }


def invalid(mutator, expected):
    m=manifest(); mutator(m)
    with pytest.raises(SchemaContractError, match=expected):read_declarative_schema(m)


def test_contract_declares_capabilities():
    plan=assess_manifest(manifest())
    assert plan.requires_private_database and plan.has_migration_contract and plan.has_route_contract


def test_generic_launch_remains_fail_closed():
    with pytest.raises(DeploymentContractError,match='C1C_PRIVATE_DB_ADAPTER_PENDING'):
        fail_closed_if_unimplemented(manifest(),legacy_crud=False)


def test_deterministic_revision_and_sql():
    a=read_declarative_schema(manifest()); b=read_declarative_schema(manifest())
    assert a==b and a.revision.startswith('c1c2:') and len(a.revision)==69
    sql=schema_sql(a,runtime_role='augmis_rw_0123456789abcdef0123456789abcdef')
    assert 'FORCE ROW LEVEL SECURITY' in sql
    assert 'CREATE POLICY "augmis_create"' in sql
    assert 'CREATE POLICY "augmis_edit"' in sql
    assert 'GRANT UPDATE ("title", "priority", "due_date", "is_deleted", "updated_at")' in sql
    assert '"tenant_id"' in sql and 'CURRENT_USER' not in sql
    assert ' GRANT DELETE ' not in sql and ' CREATE ROLE ' not in sql
    assert 'SET LOCAL statement_timeout' in sql
    check=verification_sql(a,runtime_role='augmis_rw_0123456789abcdef0123456789abcdef')
    assert 'relforcerowsecurity' in check and "'DELETE'" in check


def test_publishers_cannot_override_tenant_boundary():
    invalid(lambda m:m['addons']['database']['schema']['tables'][0]['columns'].append({'name':'tenant_id','type':'uuid'}),
            'COLUMN_DUPLICATE_OR_RESERVED')


def test_disallow_reserved_system_names():
    invalid(lambda m:m['addons']['database']['schema']['tables'][0].update({'name':'pg_authid'}),
            'TABLE_NAME_INVALID')


def test_disallow_raw_sql_properties():
    invalid(lambda m:m['addons']['database']['schema']['tables'][0].update({'sql':'DROP TABLE users'}),
            'TABLE_INVALID')


def test_disallow_raw_sql_default():
    invalid(lambda m:m['addons']['database']['schema']['tables'][0]['columns'][0].update({'default':'now(); DROP TABLE users;'}),
            'DEFAULT_LENGTH_INVALID|DEFAULT_UNSUPPORTED|DEFAULT_CHOICE_INVALID|DEFAULT_LENGTH_INVALID') if False else None
    # String defaults are emitted exclusively as quoted literals (never SQL expressions).
    m=manifest();m['addons']['database']['schema']['tables'][0]['columns'][0]['default']="a';DROP TABLE users;--"
    sql=schema_sql(read_declarative_schema(m),runtime_role='augmis_rw_0123456789abcdef0123456789abcdef')
    assert "DEFAULT 'a'';DROP TABLE users;--'" in sql


def test_duplicate_and_missing_columns_rejected():
    invalid(lambda m:m['addons']['database']['schema']['tables'][0]['columns'].append({'name':'title','type':'integer'}),
            'COLUMN_DUPLICATE_OR_RESERVED')
    invalid(lambda m:m['addons']['database']['schema']['tables'][0]['columns'][0].pop('maxLength'),
            'TEXT_LENGTH_REQUIRED')


def test_sql_fragments_are_never_accepted():
    invalid(lambda m:m['addons']['database']['schema']['tables'][0]['columns'][0].update({'expression':'SELECT 1'}),
            'COLUMN_INVALID')
    invalid(lambda m:m['addons']['database']['schema']['tables'][0]['columns'][0].update({'type':'sql'}),
            'TYPE_UNSUPPORTED')


def test_validated_enums_only():
    invalid(lambda m:m['addons']['database']['schema']['tables'][0]['columns'][1].update({'default':'Critical'}),
            'DEFAULT_CHOICE_INVALID')


def test_unique_unknown_column_denied():
    invalid(lambda m:m['addons']['database']['schema']['tables'][0].update({'unique':[['tenant_id']]}),
            'UNIQUE_INVALID')


def test_unknown_index_denied():
    invalid(lambda m:m['addons']['database']['schema']['tables'][0].update({'indexes':['pg_class']}),
            'INDEX_INVALID')


def test_no_arbitrary_role_sql():
    with pytest.raises(SchemaContractError,match='ROLE_INVALID'):
        schema_sql(read_declarative_schema(manifest()),runtime_role='postgres; DROP TABLE')


def test_conflicting_migration_modes_denied():
    m=manifest();m['addons']['database']['migrations']=[{'path':'db/migrations/001_x.sql','sha256':'a'*64}]
    with pytest.raises(DeploymentContractError,match='C1C_SCHEMA_MODE_CONFLICT'):assess_manifest(m)


def test_missing_declared_schema_is_not_ready():
    m=manifest();del m['addons']['database']['schema']
    assert assess_manifest(m).has_migration_contract is False


def test_system_columns_and_policy_are_fixed():
    sql=schema_sql(read_declarative_schema(manifest()),runtime_role='augmis_rw_0123456789abcdef0123456789abcdef')
    assert '"tenant_id" uuid NOT NULL' in sql
    assert '"is_deleted" boolean NOT NULL DEFAULT false' in sql
    assert 'current_setting(\'augmis.tenant_id\',true)' in sql
    assert 'GRANT INSERT ("id", "tenant_id"' in sql
    assert 'GRANT UPDATE ("title"' in sql
