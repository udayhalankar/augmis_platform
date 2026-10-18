"""C1-C2: bounded, declarative PostgreSQL 15 schema contract.

This module ONLY accepts structured application fields. It NEVER accepts SQL source
from uploaded packages. The instance's tenant boundary, DML grants, RLS and
system columns are controlled by AUGMIS, not by the publisher.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

_NAME = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
_TYPES = {"text", "integer", "numeric", "boolean", "date", "uuid", "timestamptz"}
_SYSTEM = {"id", "tenant_id", "is_deleted", "created_at", "updated_at"}


class SchemaContractError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SchemaPlan:
    revision: str
    tables: tuple[dict[str, Any], ...]


def _name(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value) or value.startswith("pg_"):
        raise SchemaContractError(code)
    return value


def read_declarative_schema(manifest: dict) -> SchemaPlan | None:
    database = (manifest.get("addons") or {}).get("database") or {}
    raw = database.get("schema")
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"tables"}:
        raise SchemaContractError("C1C_SCHEMA_SHAPE_INVALID")
    entries = raw["tables"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
        raise SchemaContractError("C1C_SCHEMA_TABLE_COUNT_INVALID")
    seen_tables: set[str] = set()
    sanitized = []
    for table in entries:
        if not isinstance(table, dict) or set(table) - {"name", "columns", "unique", "indexes"}:
            raise SchemaContractError("C1C_SCHEMA_TABLE_INVALID")
        table_name = _name(table.get("name"), "C1C_SCHEMA_TABLE_NAME_INVALID")
        if table_name in seen_tables or table_name in {"users", "alembic_version", "pg_roles"}:
            raise SchemaContractError("C1C_SCHEMA_TABLE_DUPLICATE_OR_RESERVED")
        seen_tables.add(table_name)
        columns = table.get("columns")
        if not isinstance(columns, list) or not 1 <= len(columns) <= 32:
            raise SchemaContractError("C1C_SCHEMA_COLUMN_COUNT_INVALID")
        result_cols = []
        seen_cols = set(_SYSTEM)
        for col in columns:
            if not isinstance(col, dict) or set(col) - {"name", "type", "maxLength", "nullable", "default", "choices"}:
                raise SchemaContractError("C1C_SCHEMA_COLUMN_INVALID")
            name = _name(col.get("name"), "C1C_SCHEMA_COLUMN_NAME_INVALID")
            if name in seen_cols:
                raise SchemaContractError("C1C_SCHEMA_COLUMN_DUPLICATE_OR_RESERVED")
            seen_cols.add(name)
            kind = col.get("type")
            if not isinstance(kind, str) or kind not in _TYPES:
                raise SchemaContractError("C1C_SCHEMA_TYPE_UNSUPPORTED")
            if "maxLength" in col and (kind != "text" or type(col["maxLength"]) is not int or
                                      not 1 <= col["maxLength"] <= 4000):
                raise SchemaContractError("C1C_SCHEMA_TEXT_LENGTH_INVALID")
            if kind == "text" and "maxLength" not in col:
                raise SchemaContractError("C1C_SCHEMA_TEXT_LENGTH_REQUIRED")
            nullable = col.get("nullable", False)
            if type(nullable) is not bool:
                raise SchemaContractError("C1C_SCHEMA_NULLABILITY_INVALID")
            default = col.get("default")
            if default is not None and (kind != "text" or not isinstance(default, str) or len(default) > 100 or
                                        any(ord(ch) < 32 for ch in default)):
                raise SchemaContractError("C1C_SCHEMA_DEFAULT_UNSUPPORTED")
            choices = col.get("choices", [])
            if (not isinstance(choices, list) or len(choices) > 16 or
                (choices and (kind != "text" or not choices)) or
                any(not isinstance(x, str) or not x or len(x) > col.get("maxLength", 0) or
                    any(ord(ch) < 32 for ch in x) for x in choices) or len(set(choices)) != len(choices)):
                raise SchemaContractError("C1C_SCHEMA_CHOICES_INVALID")
            if choices and default is not None and default not in choices:
                raise SchemaContractError("C1C_SCHEMA_DEFAULT_CHOICE_INVALID")
            if default is not None and len(default) > col.get("maxLength", 0):
                raise SchemaContractError("C1C_SCHEMA_DEFAULT_LENGTH_INVALID")
            result_cols.append({"name": name, "type": kind,
                **({"maxLength": col["maxLength"]} if kind == "text" else {}),
                "nullable": nullable,
                **({"default": default} if default is not None else {}),
                **({"choices": choices} if choices else {})})
        indexes = table.get("indexes", [])
        if (not isinstance(indexes, list) or len(indexes) > 8 or
                any(not isinstance(x, str) or x not in seen_cols - _SYSTEM for x in indexes) or
                len(set(indexes)) != len(indexes)):
            raise SchemaContractError("C1C_SCHEMA_INDEX_INVALID")
        uniques = table.get("unique", [])
        if (not isinstance(uniques, list) or len(uniques) > 8 or
                any(not isinstance(group, list) or not 1 <= len(group) <= 4 or
                    any(not isinstance(x, str) for x in group) or
                    len(set(group)) != len(group) or
                    any(x not in seen_cols - _SYSTEM for x in group)
                    for group in uniques)):
            raise SchemaContractError("C1C_SCHEMA_UNIQUE_INVALID")
        sanitized.append({"name":table_name, "columns":result_cols,
                          "indexes":indexes, "unique":uniques})
    canonical = json.dumps(sanitized, sort_keys=True, separators=(",", ":")).encode()
    return SchemaPlan(revision="c1c2:"+hashlib.sha256(canonical).hexdigest(), tables=tuple(sanitized))


def _lit(value: str) -> str:
    # Strings ONLY appear as SQL string literals, never identifiers or SQL fragments.
    return "'" + value.replace("'", "''") + "'"


def schema_sql(plan: SchemaPlan, *, runtime_role: str) -> str:
    role = _name(runtime_role, "C1C_SCHEMA_ROLE_INVALID")
    statements = ["BEGIN", "SET LOCAL statement_timeout = '20s'", "SET LOCAL lock_timeout = '3s'"]
    for table in plan.tables:
        name = table["name"]
        target = f'public."{name}"'
        defs = ['"id" uuid PRIMARY KEY', '"tenant_id" uuid NOT NULL',
                '"is_deleted" boolean NOT NULL DEFAULT false',
                '"created_at" timestamptz NOT NULL DEFAULT now()',
                '"updated_at" timestamptz NOT NULL DEFAULT now()']
        for col in table["columns"]:
            kind = col["type"]
            sql_type = f'varchar({col["maxLength"]})' if kind == 'text' else (
                'numeric(16,2)' if kind == 'numeric' else kind)
            definition = f'"{col["name"]}" {sql_type}'
            if not col["nullable"]: definition += ' NOT NULL'
            if "default" in col: definition += ' DEFAULT '+_lit(col["default"])
            if col.get("choices"):
                allowed = ', '.join(_lit(x) for x in col['choices'])
                definition += f' CHECK ("{col["name"]}" IN ({allowed}))'
            defs.append(definition)
        for group in table["unique"]:
            cols = ', '.join(['"tenant_id"']+[f'"{x}"' for x in group])
            defs.append(f'UNIQUE ({cols})')
        statements.append(f'CREATE TABLE IF NOT EXISTS {target} ('+', '.join(defs)+')')
        for index_col in table["indexes"]:
            # SHA suffix avoids PostgreSQL identifier/truncation collisions.
            ixname = 'augmis_ix_' + hashlib.sha256((name+':'+index_col).encode()).hexdigest()[:20]
            statements.append(f'CREATE INDEX IF NOT EXISTS "{ixname}" ON {target} ("tenant_id", "{index_col}", "is_deleted")')
        statements.extend([
            f'ALTER TABLE {target} ENABLE ROW LEVEL SECURITY',
            f'ALTER TABLE {target} FORCE ROW LEVEL SECURITY',
        ])
        tenant_filter = '("tenant_id" = NULLIF(current_setting(\'augmis.tenant_id\',true),\'\')::uuid AND NOT "is_deleted")'
        for op, name_suffix, clause in [
            ('SELECT','read',f'USING {tenant_filter}'),
            ('INSERT','create',f'WITH CHECK {tenant_filter}'),
            ('UPDATE','edit',f'USING {tenant_filter} WITH CHECK ("tenant_id" = NULLIF(current_setting(\'augmis.tenant_id\',true),\'\')::uuid)'),
        ]:
            policy = f'augmis_{name_suffix}'
            statements.append(f'DROP POLICY IF EXISTS "{policy}" ON {target}')
            statements.append(f'CREATE POLICY "{policy}" ON {target} FOR {op} TO "{role}" {clause}')
        writable = ', '.join([f'"{c["name"]}"' for c in table['columns']])
        statements += [
            f'REVOKE ALL ON {target} FROM PUBLIC',
            f'REVOKE ALL ON {target} FROM "{role}"',
            f'GRANT SELECT ON {target} TO "{role}"',
            f'GRANT INSERT ("id", "tenant_id", {writable}) ON {target} TO "{role}"',
            f'GRANT UPDATE ({writable}, "is_deleted", "updated_at") ON {target} TO "{role}"',
        ]
    statements.append('COMMIT')
    return ';\n'.join(statements) + ';\n'


def verification_sql(plan: SchemaPlan, *, runtime_role: str) -> str:
    role = _name(runtime_role, "C1C_SCHEMA_ROLE_INVALID")
    checks = [f"NOT (SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname={_lit(role)})",
              f"NOT has_schema_privilege({_lit(role)},'public','CREATE')"]
    for table in plan.tables:
        name = table['name']
        fq = 'public.' + name
        expected_cols = ["id", "tenant_id", "is_deleted", "created_at", "updated_at"] + [c["name"] for c in table["columns"]]
        checks.append(f"(SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name={_lit(name)}) = {len(expected_cols)}")
        for c in table["columns"]:
            typ = {'text':'character varying', 'integer':'integer', 'numeric':'numeric',
                   'boolean':'boolean', 'date':'date', 'uuid':'uuid', 'timestamptz':'timestamp with time zone'}[c['type']]
            column_rule = (f"column_name={_lit(c['name'])} AND data_type={_lit(typ)}"
                           + (f" AND character_maximum_length={c['maxLength']}" if c['type']=='text' else "")
                           + (" AND is_nullable='YES'" if c['nullable'] else " AND is_nullable='NO'"))
            checks.append(f"EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name={_lit(name)} AND {column_rule})")
        checks += [
            f"COALESCE((SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=to_regclass({_lit(fq)})),false)",
            f"(SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename={_lit(name)} AND policyname IN ('augmis_read','augmis_create','augmis_edit')) = 3",
            f"has_table_privilege({_lit(role)}, {_lit(fq)}, 'SELECT')",
            f"has_column_privilege({_lit(role)}, {_lit(fq)}, 'id', 'INSERT')",
            f"has_column_privilege({_lit(role)}, {_lit(fq)}, 'is_deleted', 'UPDATE')",
            f"NOT has_table_privilege({_lit(role)}, {_lit(fq)}, 'DELETE')",
        ]
    return "SELECT CASE WHEN " + " AND ".join(checks) + " THEN '1' ELSE '0' END;"
