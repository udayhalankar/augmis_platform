"""Pass 3H-2 tests. All credentials synthetic; Docker/network calls mocked."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.api.app.services import dashboard_runtime_mounts as sec
from services.api.app.services import deployment_engine as engine

TENANT = uuid.UUID('b6e8ccbc-aefb-4a4d-8955-1434dc1213d7')
APP = uuid.UUID('11111111-1111-4111-8111-111111111111')
INSTANCE = uuid.UUID('22222222-2222-4222-8222-222222222222')
IMAGE = 'sha256:' + 'a' * 64
PASSWORD = 'synthetic-test-password-only'


def create_pilot(monkeypatch, tmp_path):
    for key in [sec.APP_ENV, sec.TENANT_ENV, sec.SIGNING_FILE_ENV,
                sec.ROOT_ENV, sec.IMAGE_ENV, sec.NETWORK_ENV,
                sec.DB_HOST_ENV, sec.DB_PORT_ENV]:
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / 'secrets'
    folder = root / str(TENANT) / str(INSTANCE)
    folder.mkdir(parents=True)
    private = Ed25519PrivateKey.generate()
    signing = tmp_path / 'signing-private.pem'
    signing.write_bytes(private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    (folder / sec.PUBLIC_KEY_FILE).write_bytes(private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    (folder / sec.PASSWORD_FILE).write_text(PASSWORD, encoding='utf-8')
    settings = {
        sec.APP_ENV: str(APP), sec.TENANT_ENV: str(TENANT),
        sec.SIGNING_FILE_ENV: str(signing), sec.ROOT_ENV: str(root),
        sec.IMAGE_ENV: IMAGE, sec.NETWORK_ENV: 'augmis-dashboard-private',
        sec.DB_HOST_ENV: 'dashboard-db', sec.DB_PORT_ENV: '5432',
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    return root, folder, private


def docker_inspect(args):
    if args[:3] == ['docker', 'network', 'inspect']:
        return 'true'
    if args[:3] == ['docker', 'image', 'inspect']:
        return '10001:10001'
    raise AssertionError(f'Unexpected docker inspection command: {args}')


def launch():
    return sec.build_dashboard_pilot_launch(
        tenant_id=TENANT, application_id=APP, instance_id=INSTANCE,
        image_id=IMAGE, inspect_docker=docker_inspect,
    )


def test_disabled_does_not_inspect_or_change_other_apps(monkeypatch):
    monkeypatch.delenv(sec.APP_ENV, raising=False)
    assert sec.build_dashboard_pilot_launch(
        tenant_id=TENANT, application_id=APP, instance_id=INSTANCE,
        image_id=IMAGE,
        inspect_docker=lambda _: pytest.fail('Should not inspect for unrelated app'),
    ) is None


def test_different_application_is_unchanged(monkeypatch, tmp_path):
    create_pilot(monkeypatch, tmp_path)
    assert sec.build_dashboard_pilot_launch(
        tenant_id=TENANT, application_id=uuid.uuid4(), instance_id=INSTANCE,
        image_id=IMAGE, inspect_docker=lambda _: pytest.fail('Should not inspect'),
    ) is None


def test_pilot_receives_only_identity_and_file_paths(monkeypatch, tmp_path):
    create_pilot(monkeypatch, tmp_path)
    spec = launch()
    assert spec.private_network == 'augmis-dashboard-private'
    assert spec.environment['AUGMIS_RUNTIME_TENANT_ID'] == str(TENANT)
    assert spec.environment['AUGMIS_RUNTIME_APPLICATION_ID'] == str(APP)
    assert spec.environment['AUGMIS_RUNTIME_INSTANCE_ID'] == str(INSTANCE)
    assert spec.environment['AUGMIS_DASHBOARD_DB_HOST'] == 'dashboard-db'
    assert len(spec.secret_mounts) == 2
    assert all('password' not in str(v).lower() or 'file' in k.lower() or k=='AUGMIS_DASHBOARD_DB_PASSWORD_FILE'
               for k, v in spec.environment.items())
    assert PASSWORD not in repr(spec)


def test_wrong_tenant_rejected(monkeypatch, tmp_path):
    create_pilot(monkeypatch, tmp_path)
    with pytest.raises(sec.PilotLaunchError, match='tenant scope mismatch'):
        sec.build_dashboard_pilot_launch(
            tenant_id=uuid.uuid4(), application_id=APP, instance_id=INSTANCE,
            image_id=IMAGE, inspect_docker=docker_inspect,
        )


def test_unapproved_image_rejected(monkeypatch, tmp_path):
    create_pilot(monkeypatch, tmp_path)
    with pytest.raises(sec.PilotLaunchError, match='not explicitly approved'):
        sec.build_dashboard_pilot_launch(
            tenant_id=TENANT, application_id=APP, instance_id=INSTANCE,
            image_id='sha256:'+'b'*64, inspect_docker=docker_inspect,
        )


def test_missing_secret_rejected(monkeypatch, tmp_path):
    _, folder, _ = create_pilot(monkeypatch, tmp_path)
    (folder / sec.PASSWORD_FILE).unlink()
    with pytest.raises(sec.PilotLaunchError, match='missing'):
        launch()


def test_wrong_public_key_rejected(monkeypatch, tmp_path):
    _, folder, _ = create_pilot(monkeypatch, tmp_path)
    (folder / sec.PUBLIC_KEY_FILE).write_bytes(Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    with pytest.raises(sec.PilotLaunchError, match='differs'):
        launch()


def test_secret_symlink_rejected(monkeypatch, tmp_path):
    _, folder, _ = create_pilot(monkeypatch, tmp_path)
    original = folder / sec.PASSWORD_FILE
    backup = tmp_path / 'elsewhere'
    original.replace(backup)
    try:
        original.symlink_to(backup)
    except (OSError, NotImplementedError):
        pytest.skip('Symlinks unavailable without developer mode on Windows')
    with pytest.raises(sec.PilotLaunchError, match='links'):
        launch()


@pytest.mark.parametrize('bad_host', ['localhost', 'host.docker.internal', '127.0.0.1',
                                     'gateway.docker.internal', 'host-gateway'])
def test_host_db_is_not_private_network_service(monkeypatch, tmp_path, bad_host):
    create_pilot(monkeypatch, tmp_path)
    monkeypatch.setenv(sec.DB_HOST_ENV, bad_host)
    with pytest.raises(sec.PilotLaunchError, match='private service'):
        launch()


def test_network_must_be_internal(monkeypatch, tmp_path):
    create_pilot(monkeypatch, tmp_path)
    with pytest.raises(sec.PilotLaunchError, match='internal'):
        sec.build_dashboard_pilot_launch(
            tenant_id=TENANT, application_id=APP, instance_id=INSTANCE,
            image_id=IMAGE, inspect_docker=lambda args: 'false' if args[1]=='network' else '10001:10001',
        )


def test_image_must_use_nonroot_identity(monkeypatch, tmp_path):
    create_pilot(monkeypatch, tmp_path)
    with pytest.raises(sec.PilotLaunchError, match='non-root'):
        sec.build_dashboard_pilot_launch(
            tenant_id=TENANT, application_id=APP, instance_id=INSTANCE,
            image_id=IMAGE, inspect_docker=lambda args: 'true' if args[1]=='network' else '0:0',
        )


def test_no_password_in_docker_args_and_mounts_read_only(monkeypatch, tmp_path):
    # B4 3H-5D replaces direct dashboard host publishing with a managed
    # loopback-only companion. Preserve original secret-mount assertions.
    create_pilot(monkeypatch, tmp_path)
    spec = launch()
    from services.api.app.services.dev_dashboard_ingress import DevRelay
    monkeypatch.setattr(engine, 'require_dev_relay', lambda *a, **kw: DevRelay(
        'augmis-dashboard-ingress', 'augmis-dashboard-private', IMAGE))
    calls = []
    def run(args, timeout=120):
        calls.append(args)
        if args[:2] == ['docker', 'run']:
            return 'container-id'
        if args[:2] == ['docker', 'port']:
            return '127.0.0.1:49152'
        return ''
    monkeypatch.setattr(engine, 'run_docker', run)
    monkeypatch.setattr(engine, 'wait_for_health', lambda url, seconds: None)
    monkeypatch.setattr(engine, '_dashboard_internal_health', lambda *a: None)
    manifest = {'services': {'dashboard': {'public': True, 'port': 8080, 'health': {'path':'/healthz'}}}}
    result = engine.start_container(
        image_ref=IMAGE, manifest=manifest,
        container_name='augmis-test-container',
        labels={'augmis.managed':'true'}, environment={'SAFE': 'yes'}, pilot_runtime=spec,
    )
    argv = [call for call in calls if call[:2] == ['docker', 'run']][0]
    assert result['host_port'] == 49152
    assert argv[argv.index('--network') + 1] == 'augmis-dashboard-private'
    assert '--read-only' in argv and '--user' in argv
    assert '--mount' in argv and sum('readonly' in x for x in argv) == 2
    assert argv.count('--env') == 8  # 7 platform nonsecret + 1 nonsecret override
    assert PASSWORD not in str(argv)
    assert 'type=bind' in str(argv)
    assert '-p' not in argv  # secure change: dashboard is never host published
    relay = [call for call in calls if call[:2] == ['docker', 'run']][1]
    assert '127.0.0.1::18080' in relay
    assert PASSWORD not in str(relay)


def test_existing_app_docker_command_unchanged(monkeypatch):
    calls=[]
    def run(args, timeout=120):
        calls.append(args)
        return 'cid' if args[1]=='run' else '127.0.0.1:49153'
    monkeypatch.setattr(engine, 'run_docker', run)
    monkeypatch.setattr(engine, 'wait_for_health', lambda *args: None)
    engine.start_container(
        image_ref=IMAGE, manifest={'services': {'web': {'public':True, 'port': 8080}}},
        container_name='ordinary-app', labels={}, environment={'SAFE':'yes'},
    )
    argv=calls[0]
    assert '--mount' not in argv and '--network' not in argv and '--read-only' not in argv
    assert 'SAFE=yes' in argv


def test_password_not_exposed_in_exception(monkeypatch, tmp_path):
    _, folder, _ = create_pilot(monkeypatch, tmp_path)
    (folder / sec.PASSWORD_FILE).write_text('abc\nmalicious\n', encoding='utf-8')
    with pytest.raises(sec.PilotLaunchError) as error:
        launch()
    assert 'malicious' not in str(error.value)
