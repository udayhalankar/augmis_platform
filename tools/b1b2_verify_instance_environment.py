"""Read-only runtime config check. Never print variable values or full Docker env."""
import argparse
import json
import re
import subprocess
import uuid
from sqlalchemy import select


def main():
    parser=argparse.ArgumentParser(description='Verify stored/snapshotted/container non-secret config')
    parser.add_argument('--instance-id',required=True,help='UUID from Runtime Control instance selection')
    parser.add_argument('--with-docker',action='store_true',help='Inspect only selected container env')
    args=parser.parse_args()
    try: iid=uuid.UUID(args.instance_id)
    except ValueError: parser.error('Invalid --instance-id UUID')
    from services.api.app.db.session import SessionLocal
    from services.api.app.models.platform import ApplicationInstance,ApplicationDeployment
    from services.api.app.models.runtime_control import RuntimeInstanceConfig
    with SessionLocal() as db:
        try:
            inst=db.get(ApplicationInstance,iid)
            if inst is None:
                print('[FAIL] Unknown instance ID');return 2
            cfg=db.scalar(select(RuntimeInstanceConfig).where(RuntimeInstanceConfig.instance_id==iid))
            dep=db.scalar(select(ApplicationDeployment).where(
                ApplicationDeployment.instance_id==iid,
                ApplicationDeployment.status=='running',
            ).order_by(ApplicationDeployment.created_at.desc()))
            if dep is None:
                print('[REVIEW] No running deployment');return 1
            current=dict(cfg.variables_json or {}) if cfg else {}
            snapshot=dict(dep.config_snapshot_json or {})
            keys=sorted(set(current)|set(snapshot))
            print('[INSTANCE]',str(iid))
            print('[DB] Current revision:', cfg.revision if cfg else 'none',
                  'deployed revision:',dep.config_revision if dep.config_revision is not None else 'none')
            print('[DB] Configured key count:',len(current),'snapshot key count:',len(snapshot))
            match=all(current.get(k)==snapshot.get(k) for k in keys)
            if not match:
                print('[PENDING RESTART] Current settings differ from deployed snapshot. No values shown.')
                print('[DIFFERENT KEYS]', ', '.join(k for k in keys if current.get(k)!=snapshot.get(k)))
            else:
                print('[PASS] Deployed snapshot matches saved settings.')
            if not args.with_docker:
                print('[INFO] Docker not inspected; add --with-docker after starting a new container.')
                return 0
            name=str(dep.container_name or '')
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}',name):
                print('[FAIL] Invalid/missing deployment container name');return 2
            try:
                run=subprocess.run(['docker','inspect','--type','container','--format','{{json .Config.Env}}',name],
                                   capture_output=True,text=True,timeout=12,check=False)
            except (OSError,subprocess.TimeoutExpired):
                print('[FAIL] Docker unavailable or timed out');return 2
            if run.returncode:
                print('[FAIL] Container not found/inspect unavailable');return 2
            try:
                env_values=json.loads(run.stdout)
                actual=dict(item.split('=',1) for item in env_values if isinstance(item,str) and '=' in item)
            except (ValueError,TypeError):
                print('[FAIL] Docker environment inspection returned unexpected data');return 2
            mismatched=[key for key,value in snapshot.items() if actual.get(key)!=value]
            if mismatched:
                print('[FAIL] Deployed container differs from recorded snapshot for:', ', '.join(sorted(mismatched)))
                print('[SAFE] No variable values printed.')
                return 1
            print('[PASS] All',len(snapshot),'snapshotted non-secret variables reached the container.')
            print('[SAFE] No variable values printed.')
            return 0
        finally:
            db.rollback()

if __name__=='__main__':
    raise SystemExit(main())
