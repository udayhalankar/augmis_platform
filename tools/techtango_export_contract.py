"""B4 read-only AI Builder snapshot validation; no production publish capability.

Usage:
 python -m tools.techtango_export_contract --input exported_app.json --out snapshot.json
Never include application records, credentials, generated SQL or user data.
"""
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path

MAX_INPUT = 512 * 1024
SLUG = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
APP_SLUG = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")

class ExportContractError(ValueError):
    pass

def validated_snapshot(record: dict) -> dict:
    if not isinstance(record, dict):
        raise ExportContractError("Expected one AI Builder app record")
    if str(record.get('status', '')).lower() != 'published':
        raise ExportContractError("Only published Techtango apps can be reviewed")
    tenant = record.get('tenant_id')
    if isinstance(tenant, bool) or not isinstance(tenant, int) or tenant < 1:
        raise ExportContractError("Verified source tenant ID required")
    slug = record.get('app_slug', '')
    if not isinstance(slug, str) or not APP_SLUG.fullmatch(slug):
        raise ExportContractError("Invalid app slug")
    name = record.get('app_name')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
        raise ExportContractError("Invalid app name")
    schema = record.get('schema_json')
    if not isinstance(schema, dict):
        raise ExportContractError("Missing object schema_json")
    fields = schema.get('fields', [])
    if not isinstance(fields, list) or len(fields) > 128:
        raise ExportContractError("Too many application fields")
    result_fields = []
    for f in fields:
        if not isinstance(f, dict):
            raise ExportContractError("Invalid field definition")
        field = f.get('name')
        if not isinstance(field, str) or not SLUG.fullmatch(field):
            raise ExportContractError("Invalid field name")
        result_fields.append({'name':field,'type':str(f.get('type','text'))[:30],
                              'label':str(f.get('label',field))[:100]})
    # Exclude source data, SQL, application secrets and unknown schema keys.
    payload = {'format':'augmis.techtango.aiappbuilder.snapshot.v1',
               'sourceTenantId':tenant,'appSlug':slug,'appName':name.strip(),
               'fields':result_fields}
    canonical = json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    payload['sha256'] = hashlib.sha256(canonical).hexdigest()
    return payload

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args()
    if args.input.stat().st_size>MAX_INPUT:
        raise SystemExit('Input exceeds 512 KiB')
    rec=json.loads(args.input.read_text(encoding='utf-8'))
    snapshot=validated_snapshot(rec)
    if args.out.exists():
        raise SystemExit('Refusing to overwrite immutable snapshot')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(snapshot,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print('Validated metadata-only snapshot:',snapshot['sha256'])
    print('IMPORTANT: Not a hostable AAPS package; no live data exported.')

if __name__ == '__main__':main()
