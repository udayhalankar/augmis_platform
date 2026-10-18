"""Offline regression tests; never launch Docker resources."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.api.app.services import deployment_engine as engine
from services.api.app.core import config

APP_IMAGE = "sha256:" + "a" * 64
RELAY_IMAGE = "sha256:" + "b" * 64
SHORT_NAME = "augmis-abc-engineering-secure-augmis-crud-reference-a80a0358"
LONG_NAME = "augmis-upgrade-abc-engineering-secure-augmis-crud-reference-a80a0358-e04ddd3f"


@pytest.mark.parametrize('name', [SHORT_NAME, LONG_NAME, LONG_NAME[:-8] + '01234567'])
def test_private_relay_uses_safe_alias_without_changing_ownership(name, monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'settings', SimpleNamespace(app_env='development'))
    commands = []

    def fake_run(args, timeout=120):
        commands.append(args)
        if args[1:3] == ['network', 'inspect']:
            return 'true' if args[-1] == 'augmis-prv-test' else 'false'
        if args[1:3] == ['image', 'inspect']:
            return args[-1] if '{{.Id}}' in args else ('10002:10002' if args[-1] == RELAY_IMAGE else '10001:10001')
        if args[1:2] == ['port']:
            return '127.0.0.1:49011'
        return 'mock-docker-id'

    monkeypatch.setattr(engine, 'run_docker', fake_run)
    monkeypatch.setattr(engine, 'wait_for_health', lambda *_args, **_kwargs: None)
    launch = SimpleNamespace(
        network_name='augmis-prv-test', ingress_network='augmis-crud-ingress',
        relay_image_id=RELAY_IMAGE, secret_volume='secret-volume',
        public_key_file=Path(tmp_path) / 'public.pem',
        environment={'PGHOST': 'augmis-db'}
    )
    result = engine._start_private_crud_container(
        image_ref=APP_IMAGE,
        manifest={'services': {'web': {'public': True, 'port': 8080, 'health': {'path': '/health'}}}},
        container_name=name,
        labels={'augmis.managed': 'true', 'augmis.instance_id': 'test-instance'},
        environment={}, launch=launch
    )
    assert result['runtime_url'] == 'http://127.0.0.1:49011'
    runs = [c for c in commands if c[:3] == ['docker', 'run', '-d']]
    assert len(runs) == 2
    app, relay = runs
    assert app[app.index('--name')+1] == name
    assert relay[relay.index('--name')+1] == name + '-ingress'
    assert '-p' not in app
    assert relay[relay.index('-p')+1] == '127.0.0.1::18080'
    assert 'augmis.ingress_for=' + name in relay
    if len(name) > 63:
        expected = 'augmis-crud-' + hashlib.sha256(name.encode('ascii')).hexdigest()[:24]
        assert '--network-alias' in app
        assert app[app.index('--network-alias')+1] == expected
        assert len(expected) < 63
        assert 'AUGMIS_RELAY_UPSTREAM=' + expected in relay
    else:
        assert '--network-alias' not in app
        assert 'AUGMIS_RELAY_UPSTREAM=' + name in relay
