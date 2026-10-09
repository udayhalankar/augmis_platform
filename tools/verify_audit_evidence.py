"""Offline verification of AUGMIS audit evidence JSON or a byte-level CSV digest.

Examples:
  python -m tools.verify_audit_evidence "C:/Downloads/augmis-audit-platform-....json"
  python -m tools.verify_audit_evidence "C:/Downloads/augmis-audit-tenant-....csv" --sha256 <X-AUGMIS-Export-SHA256>

JSON recordSha256 verifies canonical events (not a cryptographic signature).
CSV requires a trusted SHA256 expected value obtained from the HTTP response
or the corresponding audit.export.created record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--sha256', help='Expected SHA256 of exact file bytes')
    args = parser.parse_args()
    raw = args.file.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    print('File SHA256:', digest)
    if args.sha256 and args.sha256.lower() != digest:
        print('[FAIL] File SHA256 differs from expected value.')
        return 1
    if args.file.suffix.lower() == '.json':
        payload = json.loads(raw.decode('utf-8'))
        assert payload.get('manifest', {}).get('schema') == 'augmis.audit.evidence.v1', 'Unexpected manifest schema'
        events = payload.get('events')
        assert isinstance(events, list), 'Missing events array'
        manifest = payload['manifest']
        assert manifest['recordCount'] == len(events), 'Record count mismatch'
        canonical = json.dumps(events, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode('utf-8')
        record_sha = hashlib.sha256(canonical).hexdigest()
        if record_sha != manifest['recordSha256']:
            print('[FAIL] Evidence records SHA256 mismatch.')
            return 1
        print('[PASS] JSON record integrity matches manifest; records:', len(events))
    elif not args.sha256:
        print('[INFO] For CSV integrity verification supply --sha256 from the audited export metadata.')
    if args.sha256:
        print('[PASS] File bytes match expected SHA256.')
    print('Note: hashes detect changes but are NOT a digital signature or independent tamper-proof archive.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
