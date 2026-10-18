"""C1-D1: durable, explicitly opted-in *development* runtime-host configuration.

Loads a non-secret host profile from the service account's home directory. Existing
runtime services still consume their established environment variables; this is
an early, single-source adapter, NOT a second container/deployment engine.

This module deliberately has no Docker or application-model imports on import.
"""
from __future__ import annotations

import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from types import MappingProxyType

PROFILE_FILENAME = 'runtime-host.json'
PROFILE_OVERRIDE_ENV = 'AUGMIS_RUNTIME_PROFILE_FILE'
_ID = re.compile(r'sha256:[0-9a-f]{64}\Z')
_NETWORK = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}\Z')
_PROFILE_KEYS = frozenset({
    'schemaVersion', 'environment', 'postgresImageId', 'genericRelayImageId',
    'legacyCrudRelayImageId', 'legacyCrudApplicationId', 'enableLegacyCrud',
    'ingressNetwork', 'signingPrivateKeyFile', 'signingPublicKeyFile',
    'allowDevelopmentUnquotedVolumes',
})
_ENV_FIELDS = {
    'AUGMIS_C1C_GENERIC_RUNTIME_ENABLED': '1',
    'AUGMIS_C1C_DECLARED_SCHEMA_ENABLED': '1',
    'AUGMIS_C1B_DEV_DB_ENABLED': '1',
    'AUGMIS_C1B_DEV_SCHEMA_ENABLED': '1',
}


class RuntimeProfileError(ValueError):
    """Error code only. Never include profile contents or sensitive file paths."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def default_profile_path() -> Path:
    override = os.environ.get(PROFILE_OVERRIDE_ENV, '').strip()
    if override:
        p = Path(override)
        if not p.is_absolute():
            raise RuntimeProfileError('C1D_PROFILE_PATH_NOT_ABSOLUTE')
        return p
    return Path.home() / '.augmis' / PROFILE_FILENAME


def _required_str(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeProfileError('C1D_PROFILE_FIELD_INVALID_' + key)
    return value


def _normal_path(value: str, key: str) -> str:
    p = Path(value)
    if not p.is_absolute() or p.is_symlink() or not p.is_file():
        raise RuntimeProfileError('C1D_PROFILE_FILE_INVALID_' + key)
    return str(p)


def _parse(data: object) -> dict[str, str]:
    if not isinstance(data, dict) or set(data) - _PROFILE_KEYS:
        raise RuntimeProfileError('C1D_PROFILE_SCHEMA_INVALID')
    if type(data.get('schemaVersion')) is not int or data['schemaVersion'] != 1:
        raise RuntimeProfileError('C1D_PROFILE_VERSION_UNSUPPORTED')
    if data.get('environment') not in ('development', 'dev'):
        raise RuntimeProfileError('C1D_PROFILE_DEVELOPMENT_ONLY')
    for name in ('postgresImageId', 'genericRelayImageId'):
        if not _ID.fullmatch(_required_str(data, name)):
            raise RuntimeProfileError('C1D_PROFILE_IMAGE_INVALID_' + name)
    ingress = _required_str(data, 'ingressNetwork')
    if not _NETWORK.fullmatch(ingress) or ingress in ('bridge', 'host', 'none'):
        raise RuntimeProfileError('C1D_PROFILE_INGRESS_INVALID')
    if data.get('allowDevelopmentUnquotedVolumes') is not True:
        raise RuntimeProfileError('C1D_PROFILE_STORAGE_POLICY_REQUIRED')
    if type(data.get('enableLegacyCrud', False)) is not bool:
        raise RuntimeProfileError('C1D_PROFILE_LEGACY_MODE_INVALID')
    private = _normal_path(_required_str(data, 'signingPrivateKeyFile'), 'signingPrivateKeyFile')
    public = _normal_path(_required_str(data, 'signingPublicKeyFile'), 'signingPublicKeyFile')
    result = {
        **_ENV_FIELDS,
        'AUGMIS_C1B_DEV_UNQUOTED_VOLUME_OK': '1',
        'AUGMIS_C1B_POSTGRES_IMAGE_ID': data['postgresImageId'],
        'AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID': data['genericRelayImageId'],
        'AUGMIS_C1B_CRUD_INGRESS_NETWORK': ingress,
        'AUGMIS_C1B_CRUD_SIGNING_PRIVATE_KEY_FILE': private,
        'AUGMIS_C1B_CRUD_SIGNING_PUBLIC_KEY_FILE': public,
    }
    if data.get('enableLegacyCrud', False):
        image = _required_str(data, 'legacyCrudRelayImageId')
        if not _ID.fullmatch(image):
            raise RuntimeProfileError('C1D_PROFILE_LEGACY_IMAGE_INVALID')
        raw_id = _required_str(data, 'legacyCrudApplicationId')
        try:
            if str(uuid.UUID(raw_id)) != raw_id:
                raise ValueError('noncanonical')
        except (ValueError, AttributeError) as exc:
            raise RuntimeProfileError('C1D_PROFILE_LEGACY_ID_INVALID') from exc
        result.update({
            'AUGMIS_C1B_CRUD_PRIVATE_RUNTIME_ENABLED': '1',
            'AUGMIS_C1B_CRUD_RELAY_IMAGE_ID': image,
            'AUGMIS_C1B_CRUD_APPLICATION_ID': raw_id,
        })
    else:
        # Explicitly do NOT silently change or disable a legacy runtime configured
        # elsewhere. Require its independent compatibility controls to remain valid.
        if data.get('legacyCrudRelayImageId') or data.get('legacyCrudApplicationId'):
            raise RuntimeProfileError('C1D_PROFILE_LEGACY_DISABLED_CONFLICT')
    return result


@dataclass(frozen=True)
class LoadedProfile:
    path: Path
    environment: Mapping[str, str]


def read_profile(path: Path | None = None) -> LoadedProfile | None:
    selected = path if path is not None else default_profile_path()
    if not selected.exists():
        if os.environ.get(PROFILE_OVERRIDE_ENV, '').strip():
            raise RuntimeProfileError('C1D_PROFILE_NOT_FOUND')
        return None
    if selected.is_symlink() or not selected.is_file():
        raise RuntimeProfileError('C1D_PROFILE_PATH_INVALID')
    if os.name != 'nt' and (stat.S_IMODE(selected.stat().st_mode) & 0o022):
        raise RuntimeProfileError('C1D_PROFILE_WRITABLE_BY_OTHERS')
    try:
        if selected.stat().st_size > 8192:
            raise RuntimeProfileError('C1D_PROFILE_TOO_LARGE')
        raw = json.loads(selected.read_text(encoding='utf-8'))
    except RuntimeProfileError:
        raise
    except (OSError, ValueError, UnicodeError) as exc:
        raise RuntimeProfileError('C1D_PROFILE_READ_FAILED') from exc
    return LoadedProfile(path=selected, environment=MappingProxyType(_parse(raw)))


_LOADED: LoadedProfile | None = None


def hydrate_runtime_profile() -> LoadedProfile | None:
    """Called from core.config BEFORE route and service imports.

    Refuse differences rather than letting the last PowerShell window win.
    Existing setups without a profile remain import-compatible for migration.
    """
    global _LOADED
    profile = read_profile()
    if profile is None:
        return None
    for name, value in profile.environment.items():
        if name in os.environ and os.environ[name] != value:
            raise RuntimeProfileError('C1D_PROFILE_ENV_CONFLICT_' + name)
    for name, value in profile.environment.items():
        os.environ[name] = value
    _LOADED = profile
    return profile


def active_profile() -> LoadedProfile | None:
    return _LOADED
