"""Pure offline tests for C1-D3 direct psycopg contract detection."""
import pytest
from services.api.app.services.c1d3_source_db_contract import (
    check_direct_psycopg_contract, SourceDbContractError,
)

SCHEMA = {'tables': [{'name': 'service_requests', 'columns': [{'name':'title','type':'text','maxLength':120}]}]}
BAD = '''
import os, psycopg
from fastapi import FastAPI
app = FastAPI()
def db(): return psycopg.connect(os.environ['PGHOST'])
def create(cur):
    cur.execute("INSERT INTO service_requests (request_id,title) VALUES (%s,%s)", (1, 'x'))
'''
CONTEXT = '''
import os, psycopg
from fastapi import FastAPI
app = FastAPI()
def db():
    con = psycopg.connect(os.environ['PGHOST'])
    con.execute("SELECT set_config('augmis.tenant_id', %s, true)", (os.environ['APP_TENANT_ID'],))
    return con
def create(cur):
    cur.execute("INSERT INTO service_requests (request_id,title) VALUES (%s,%s)", (1, 'x'))
'''
GOOD = CONTEXT.replace('(request_id,title)', '(id,tenant_id,request_id,title)').replace('VALUES (%s,%s)', 'VALUES (%s,%s,%s,%s)')

def test_reject_missing_rls_context():
    with pytest.raises(SourceDbContractError) as e:
        check_direct_psycopg_contract({'app/main.py':BAD},SCHEMA)
    assert e.value.code == 'C1D3_PG_TENANT_CONTEXT_REQUIRED'

def test_reject_missing_system_columns():
    with pytest.raises(SourceDbContractError) as e:
        check_direct_psycopg_contract({'app/main.py':CONTEXT},SCHEMA)
    assert e.value.code == 'C1D3_PG_SYSTEM_COLUMNS_REQUIRED'

def test_accept_correct_direct_psycopg_shape():
    check_direct_psycopg_contract({'app/main.py':GOOD},SCHEMA)

def test_comments_and_docstrings_cannot_fake_context():
    fake = BAD.replace('def create(cur):', '''def fake():
    """SELECT set_config('augmis.tenant_id', %s, true)"""
def create(cur):''')
    with pytest.raises(SourceDbContractError) as e:
        check_direct_psycopg_contract({'app/main.py':fake},SCHEMA)
    assert e.value.code == 'C1D3_PG_TENANT_CONTEXT_REQUIRED'

def test_non_psycopg_sources_not_misclassified():
    check_direct_psycopg_contract({'app/main.py': 'from fastapi import FastAPI\napp=FastAPI()'}, SCHEMA)

def test_no_schema_does_not_block():
    check_direct_psycopg_contract({'app/main.py':BAD},None)
