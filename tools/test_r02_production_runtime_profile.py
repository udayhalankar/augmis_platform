"""R02 code-level negative tests. No Docker, database, AWS or network mutation."""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

from services.api.app.core.config import settings
from services.api.app.core import runtime_host as host
from services.api.app.services import runtime_host_readiness as readiness
from services.api.app.services import deployment_engine

IMAGE = 'sha256:' + 'a' * 64
RELAY = 'sha256:' + 'b' * 64


def production_profile(tmp_path: Path) -> dict:
    private = tmp_path / 'private.pem'
    public = tmp_path / 'public.pem'
    private.write_text('fixture-not-a-real-private-key')
    public.write_text('fixture-not-a-real-public-key')
    if os.name == 'posix':
        private.chmod(0o600)
    return {
        'schemaVersion': 2,
        'environment': 'production',
        'hostPlatform': 'aws-ec2-linux-docker',
        'deploymentMode': 'private-gateway-only',
        'postgresImageId': IMAGE,
        'genericRelayImageId': RELAY,
        'ingressNetwork': 'augmis-prod-private-ingress',
        'signingPrivateKeyFile': str(private),
        'signingPublicKeyFile': str(public),
        'allowHostPortPublishing': False,
    }


def test_production_profile_only_exposes_safe_mapping(tmp_path):
    mapped = host._parse(production_profile(tmp_path))
    assert mapped['AUGMIS_R02_PRODUCTION_PROFILE'] == '1'
    assert mapped['AUGMIS_R02_PRIVATE_INGRESS_NETWORK'] == 'augmis-prod-private-ingress'
    assert mapped['AUGMIS_C1B_POSTGRES_IMAGE_ID'] == IMAGE
    assert 'AUGMIS_C1B_DEV_UNQUOTED_VOLUME_OK' not in mapped
    assert 'AUGMIS_C1B_CRUD_PRIVATE_RUNTIME_ENABLED' not in mapped
    assert 'AUGMIS_C1C_GENERIC_RUNTIME_ENABLED' not in mapped
    assert 'AUGMIS_C1B_CRUD_INGRESS_NETWORK' not in mapped


@pytest.mark.parametrize('field,value', [
    ('schemaVersion', 1), ('environment', 'dev'),
    ('hostPlatform', 'windows-docker'), ('deploymentMode', 'legacy-host-port'),
    ('allowHostPortPublishing', True), ('allowHostPortPublishing', 0),
    ('postgresImageId', 'postgres:15'), ('genericRelayImageId', 'latest'),
    ('ingressNetwork', 'host'), ('ingressNetwork', 'bridge'),
    ('ingressNetwork', 'none'), ('ingressNetwork', 'bad/network'),
])
def test_production_profile_rejects_unsafe_fields(tmp_path, field, value):
    candidate = production_profile(tmp_path)
    candidate[field] = value
    with pytest.raises(host.RuntimeProfileError):
        host._parse(candidate)


@pytest.mark.parametrize('field,value', [
    ('allowDevelopmentUnquotedVolumes', True),
    ('enableLegacyCrud', True),
    ('dockerSocket', '/var/run/docker.sock'),
    ('privileged', True),
    ('hostNetwork', True),
])
def test_rejects_unreviewed_docker_capabilities(tmp_path, field, value):
    candidate = production_profile(tmp_path)
    candidate[field] = value
    with pytest.raises(host.RuntimeProfileError, match='R02_PROFILE_SCHEMA_INVALID'):
        host._parse(candidate)


def test_production_requires_full_contract(tmp_path):
    candidate = production_profile(tmp_path)
    candidate.pop('allowHostPortPublishing')
    with pytest.raises(host.RuntimeProfileError, match='R02_PROFILE_SCHEMA_INVALID'):
        host._parse(candidate)


@pytest.mark.skipif(os.name != 'posix', reason='Linux file ACL verification requires POSIX filesystem')
def test_production_profile_permissions_and_owner(tmp_path):
    data = production_profile(tmp_path)
    profile_path = tmp_path / 'production.json'
    profile_path.write_text(json.dumps(data))
    profile_path.chmod(0o600)
    assert host.read_profile(profile_path).mode == 'production'
    profile_path.chmod(0o644)
    with pytest.raises(host.RuntimeProfileError, match='R02_PRODUCTION_PROFILE_PERMISSIONS'):
        host.read_profile(profile_path)
    profile_path.chmod(0o600)
    Path(data['signingPrivateKeyFile']).chmod(0o644)
    with pytest.raises(host.RuntimeProfileError, match='R02_SIGNING_PRIVATE_KEY_PERMISSIONS'):
        host.read_profile(profile_path)


def test_production_and_dev_profiles_cannot_be_swapped(tmp_path, monkeypatch):
    mapping = host._parse(production_profile(tmp_path))
    loaded = host.LoadedProfile(tmp_path / 'profile.json', mapping, mode='production')
    monkeypatch.setattr(readiness, 'active_profile', lambda: loaded)
    monkeypatch.setattr(readiness.settings, 'app_env', 'development')
    assert readiness.check_runtime_host().code == 'R02_RUNTIME_PROFILE_ENV_MISMATCH'
    monkeypatch.setattr(readiness.settings, 'app_env', 'prodution')
    assert readiness.check_runtime_host().code == 'R02_RUNTIME_ENV_UNRECOGNIZED'


def test_production_never_reports_ready_without_ingress_acceptance(tmp_path, monkeypatch):
    mapping = host._parse(production_profile(tmp_path))
    loaded = host.LoadedProfile(tmp_path / 'profile.json', mapping, mode='production')
    monkeypatch.setattr(readiness, 'active_profile', lambda: loaded)
    monkeypatch.setattr(readiness.settings, 'app_env', 'production')
    for name, value in mapping.items():
        monkeypatch.setenv(name, value)
    if os.name != 'posix' or sys.platform != 'linux':
        assert readiness.check_runtime_host().code == 'R02_PRODUCTION_LINUX_REQUIRED'
        return
    monkeypatch.setitem(sys.modules, 'services.api.app.services.private_crud_runtime',
                        types.SimpleNamespace(signing_material=lambda: (Path('/tmp/pri'), Path('/tmp/pub'))))
    def docker(*args):
        if args[0] == 'info':
            return 'linux' if args[-1] == '{{.OSType}}' else '29.0.0'
        if args[0] == 'image':
            return '10002:10002' if args[-1] == RELAY and args[3] == '{{.Config.User}}' else args[-1]
        if args[0] == 'network':
            return 'true' if args[3] == '{{.Internal}}' else 'bridge'
        raise AssertionError(args)
    monkeypatch.setattr(readiness, '_docker', docker)
    assert readiness.check_runtime_host().code == 'R02_PRODUCTION_INGRESS_ACCEPTANCE_PENDING'
    assert not readiness.check_runtime_host().ready
    def bad_network(*args):
        if args[0] == 'network' and args[3] == '{{.Internal}}':
            return 'false'
        return docker(*args)
    monkeypatch.setattr(readiness, '_docker', bad_network)
    assert readiness.check_runtime_host().code == 'R02_PRIVATE_INGRESS_REQUIRED'


@pytest.mark.parametrize('mode', ['production', 'prod', 'staging', 'prodution'])
def test_all_existing_launch_modes_rejected_before_docker(monkeypatch, mode):
    monkeypatch.setattr(settings, 'app_env', mode)
    def no_docker(*args, **kwargs):
        raise AssertionError('Docker must not be called')
    monkeypatch.setattr(deployment_engine, 'run_docker', no_docker)
    common = dict(image_ref=IMAGE, manifest={'services': {'web': {'public': True, 'port': 8080}}},
                  container_name='augmis-test', labels={}, environment={})
    for extra in ({}, {'pilot_runtime': object()}, {'crud_runtime': object()}):
        with pytest.raises(deployment_engine.DeploymentError,
                           match='R02_PRODUCTION_DEPLOYMENT_MODE_NOT_APPROVED'):
            deployment_engine.start_container(**common, **extra)
