"""Pass 3H-5D: offline tests; all Docker calls stubbed. No credentials."""
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from services.api.app.services import dev_dashboard_ingress as dev
from services.api.app.services import deployment_engine as eng
from services.api.app.services.dashboard_runtime_mounts import DashboardPilotLaunch

DASH='augmis-tenant-21augdashboard-aabbccdd'
IMAGE='sha256:'+'b'*64
RELAY='sha256:'+'a'*64
MANIFEST={'services':{'dashboard':{'public':True,'port':8080,'health':{'path':'/healthz'}}},'lifecycle':{'startupTimeoutSeconds':5}}
PILOT=DashboardPilotLaunch(environment={'AUGMIS_RUNTIME_TENANT_ID':'synthetic'},secret_mounts=((Path('/fake/db_password'),'/run/secrets/db_password'),),private_network='augmis-dashboard-private')


def stub_config(monkeypatch):
    from services.api.app.core.config import settings
    monkeypatch.setattr(settings, 'app_env', 'development')
    monkeypatch.setenv('AUGMIS_DASHBOARD_DEV_RELAY_ENABLED','1')
    monkeypatch.setenv('AUGMIS_DASHBOARD_DEV_RELAY_IMAGE_ID',RELAY)
    monkeypatch.setenv('AUGMIS_DASHBOARD_DEV_INGRESS_NETWORK','augmis-dashboard-ingress')


def validate_docker(cmd):
    if cmd[:3] == ['docker','network','inspect']:
        return 'true' if cmd[-1]=='augmis-dashboard-private' else 'false'
    if cmd[:3] == ['docker','image','inspect']:
        return '10002:10002'
    raise AssertionError(cmd)


def test_no_pilot_has_no_config_requirements(monkeypatch):
    monkeypatch.delenv('AUGMIS_DASHBOARD_DEV_RELAY_ENABLED',raising=False)
    calls=[]
    def docker(cmd,timeout=120):
        calls.append(cmd)
        if cmd[1]=='run': return 'container-id'
        if cmd[1]=='port': return '127.0.0.1:50055'
        return ''
    monkeypatch.setattr(eng,'run_docker',docker)
    monkeypatch.setattr(eng,'wait_for_health',lambda *_:None)
    result=eng.start_container(IMAGE,MANIFEST,DASH,{'augmis.managed':'true'})
    assert result['runtime_url']=='http://127.0.0.1:50055'
    assert any('-p' in c for c in calls)
    assert not any(c[:3]==['docker','network','connect'] for c in calls)


def test_pilot_requires_explicit_activation(monkeypatch):
    monkeypatch.delenv('AUGMIS_DASHBOARD_DEV_RELAY_ENABLED',raising=False)
    with pytest.raises(eng.DeploymentError,match='explicit development'):
        eng.start_container(IMAGE,MANIFEST,DASH,{},pilot_runtime=PILOT)


def test_production_fails_closed(monkeypatch):
    stub_config(monkeypatch)
    from services.api.app.core.config import settings
    monkeypatch.setattr(settings,'app_env','production')
    with pytest.raises(dev.DevIngressError,match='forbidden'):
        dev.require_dev_relay(PILOT,run_docker=validate_docker)


def test_relay_requires_immutable_image_and_nonroot(monkeypatch):
    stub_config(monkeypatch)
    monkeypatch.setenv('AUGMIS_DASHBOARD_DEV_RELAY_IMAGE_ID','some:tag')
    with pytest.raises(dev.DevIngressError,match='immutable'):
        dev.require_dev_relay(PILOT,run_docker=validate_docker)
    monkeypatch.setenv('AUGMIS_DASHBOARD_DEV_RELAY_IMAGE_ID',RELAY)
    with pytest.raises(dev.DevIngressError,match='non-root'):
        dev.require_dev_relay(PILOT,run_docker=lambda cmd: '0:0' if cmd[1]=='image' else validate_docker(cmd))


def test_reject_wrong_ingress_network(monkeypatch):
    stub_config(monkeypatch)
    monkeypatch.setenv('AUGMIS_DASHBOARD_DEV_INGRESS_NETWORK','augmis-dashboard-private')
    with pytest.raises(dev.DevIngressError,match='dedicated'):
        dev.require_dev_relay(PILOT,run_docker=validate_docker)
    monkeypatch.setenv('AUGMIS_DASHBOARD_DEV_INGRESS_NETWORK','augmis-dashboard-ingress')
    with pytest.raises(dev.DevIngressError,match='separate'):
        dev.require_dev_relay(PILOT,run_docker=lambda cmd: 'true' if cmd[1]=='network' else '10002:10002')


@pytest.mark.parametrize('value',["0.0.0.0:50055", ":::50055", "127.0.0.1:50055\n[::1]:50055", "127.0.0.1:80", "", "127.0.0.1:65536"])
def test_relay_ports_reject_unsafe(value):
    with pytest.raises(dev.DevIngressError):dev.parse_relay_port(value)


def test_approved_loopback_port():
    assert dev.parse_relay_port('127.0.0.1:50055\n')==50055


def test_managed_pilot_starts_dashboard_without_host_port(monkeypatch):
    stub_config(monkeypatch)
    commands=[]
    def docker(cmd,timeout=120):
        commands.append(cmd)
        if cmd[:2]==['docker','network'] and cmd[2]=='inspect':return 'true' if cmd[-1]=='augmis-dashboard-private' else 'false'
        if cmd[:2]==['docker','image']:return '10002:10002'
        if cmd[:2]==['docker','run']:return 'container-id'
        if cmd[:2]==['docker','port']:return '127.0.0.1:50062'
        return ''
    monkeypatch.setattr(eng,'run_docker',docker)
    monkeypatch.setattr(eng,'_dashboard_internal_health',lambda *_:None)
    monkeypatch.setattr(eng,'wait_for_health',lambda *_:None)
    result=eng.start_container(IMAGE,MANIFEST,DASH,{'augmis.managed':'true'},pilot_runtime=PILOT)
    runs=[cmd for cmd in commands if cmd[:2]==['docker','run']]
    assert len(runs)==2
    dashboard,relay=runs
    assert '-p' not in dashboard
    assert 'augmis-dashboard-private' in dashboard
    assert '127.0.0.1::18080' in relay
    assert RELAY == relay[-1]
    assert '--read-only' in dashboard and '--read-only' in relay
    assert all('db_password' not in ' '.join([str(x) for x in cmd]) for cmd in [relay])
    assert ['docker','network','connect','augmis-dashboard-private',DASH+'-ingress'] in commands
    assert result['runtime_url']=='http://127.0.0.1:50062'


def test_failed_relay_start_cleans_dashboard_and_verified_relay(monkeypatch):
    stub_config(monkeypatch)
    calls=[]
    def docker(cmd,timeout=120):
        calls.append(cmd)
        if cmd[:2]==['docker','network'] and cmd[2]=='inspect':return 'true' if cmd[-1]=='augmis-dashboard-private' else 'false'
        if cmd[:2]==['docker','image']:return '10002:10002'
        if cmd[:2]==['docker','run']:return 'container-id'
        if cmd[:3]==['docker','network','connect']:raise eng.DeploymentError('network connect failed')
        if cmd[:3]==['docker','container','inspect']:return DASH+'|true'
        return ''
    monkeypatch.setattr(eng,'run_docker',docker)
    monkeypatch.setattr(eng,'_dashboard_internal_health',lambda *_:None)
    monkeypatch.setattr(eng,'get_container_logs',lambda **kw:'')
    with pytest.raises(eng.DeploymentError,match='ingress startup failed'):
        eng.start_container(IMAGE,MANIFEST,DASH,{},pilot_runtime=PILOT)
    assert ['docker','rm','-f',DASH+'-ingress'] in calls
    assert ['docker','rm','-f',DASH] in calls


def test_stop_owned_relay_then_dashboard(monkeypatch):
    monkeypatch.setenv('AUGMIS_DASHBOARD_DEV_RELAY_ENABLED','1')
    calls=[]
    def docker(cmd,timeout=120):
        calls.append(cmd)
        if cmd[:3]==['docker','container','inspect']:return DASH+'|true'
        return ''
    monkeypatch.setattr(eng,'run_docker',docker)
    eng.stop_container(DASH)
    assert calls[-2:]==[['docker','rm','-f',DASH+'-ingress'],['docker','rm','-f',DASH]]


def test_stop_never_removes_unowned_relay(monkeypatch):
    monkeypatch.setenv('AUGMIS_DASHBOARD_DEV_RELAY_ENABLED','1')
    calls=[]
    def docker(cmd,timeout=120):
        calls.append(cmd)
        return 'different|true'
    monkeypatch.setattr(eng,'run_docker',docker)
    with pytest.raises(eng.DeploymentError,match='ownership'):
        eng.stop_container(DASH)
    assert not any(c[1]=='rm' for c in calls)


def test_stop_disabled_unchanged(monkeypatch):
    monkeypatch.delenv('AUGMIS_DASHBOARD_DEV_RELAY_ENABLED',raising=False)
    calls=[]
    monkeypatch.setattr(eng,'run_docker',lambda cmd: calls.append(cmd))
    eng.stop_container(DASH)
    assert calls==[['docker','rm','-f',DASH]]


def test_relay_name_rejects_untrusted_value():
    for name in ['xyz','augmis-a/../../', 'augmis-A', 'augmis-'+'z'*300]:
        with pytest.raises(dev.DevIngressError):dev.relay_container_name(name)
