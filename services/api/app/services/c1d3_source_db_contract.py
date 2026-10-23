"""C1-D3 stabilization: fail-early checks for direct-psycopg FastAPI source.

Not a proof of arbitrary Python/ORM correctness. Only recognizes statically literal
SQL statements and a direct psycopg.connect pattern. Never executes uploaded code.
"""
from __future__ import annotations

import ast
import re
from typing import Mapping

_INSERT = re.compile(
    r'\bINSERT\s+INTO\s+(?:public\.)?"?([a-z][a-z0-9_]*)"?\s*\(([^)]+)\)\s*VALUES\b',
    re.IGNORECASE | re.DOTALL,
)
_CTX = re.compile(r"\b(?:SELECT\s+)?set_config\s*\(\s*['\"]augmis\.tenant_id['\"]", re.IGNORECASE)

class SourceDbContractError(ValueError):
    def __init__(self, code: str, file: str, problem: str, correction: str):
        super().__init__(problem)
        self.code, self.file, self.problem, self.correction = code, file, problem, correction


def _literal_sql(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # Unknown interpolations should never be used as SQL identifiers.
        if all(isinstance(p, ast.Constant) and isinstance(p.value, str) for p in node.values):
            return ''.join(p.value for p in node.values)
    return None


def check_direct_psycopg_contract(sources: Mapping[str, str], schema: dict | None) -> None:
    """Raise a precise source error for the demonstrated missing RLS/PK bindings.

    The supported AAPS compiler creates id and tenant_id as NOT NULL without
    defaults. The runtime connection must set transaction-local tenant RLS state.
    Sources with no direct psycopg.connect are outside this bounded audit.
    """
    if not schema or not schema.get('tables'):
        return
    trees: dict[str, ast.AST] = {}
    for filename, content in sources.items():
        try:
            trees[filename] = ast.parse(content, filename=filename)
        except SyntaxError:
            # Existing source/build checks diagnose invalid Python separately.
            return

    uses_direct_psycopg = False
    has_context = False
    has_trusted_tenant = False
    insert_statements = []
    direct_connection_file = None
    for filename, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (node.func.attr == 'connect' and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == 'psycopg'):
                    uses_direct_psycopg = True
                    direct_connection_file = filename
                if node.func.attr in {'execute', 'executemany'} and node.args:
                    sql = _literal_sql(node.args[0])
                    if sql:
                        if _CTX.search(sql):
                            has_context = True
                        if _INSERT.search(sql):
                            insert_statements.append((filename, sql))
            if isinstance(node, ast.Constant) and node.value == 'APP_TENANT_ID':
                has_trusted_tenant = True

    if not uses_direct_psycopg:
        return
    primary = direct_connection_file or next(iter(trees), 'app/main.py')
    if not has_context or not has_trusted_tenant:
        raise SourceDbContractError(
            'C1D3_PG_TENANT_CONTEXT_REQUIRED', primary,
            'Direct psycopg source has no verifiable transaction-local AUGMIS tenant RLS context.',
            "In the same database transaction, execute SELECT set_config('augmis.tenant_id', %s, true) "
            'using APP_TENANT_ID supplied by AUGMIS; never a browser-provided tenant ID.',
        )
    tables = {t['name'] for t in schema['tables'] if isinstance(t, dict) and isinstance(t.get('name'), str)}
    for filename, sql in insert_statements:
        match = _INSERT.search(sql)
        if match and match.group(1).lower() in tables:
            columns = {v.strip().strip('"').lower() for v in match.group(2).split(',')}
            missing = {'id', 'tenant_id'} - columns
            if missing:
                raise SourceDbContractError(
                    'C1D3_PG_SYSTEM_COLUMNS_REQUIRED', filename,
                    'INSERT into declared AAPS table is missing required non-default system columns: '
                    + ', '.join(sorted(missing)) + '.',
                    'Generate id as UUID and supply tenant_id from trusted APP_TENANT_ID. '
                    'Do not relax forced RLS or grant superuser privileges.',
                )
