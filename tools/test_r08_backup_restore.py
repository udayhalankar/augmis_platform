"""R08 standalone negative tests: cryptographic integrity and scope guards.
No Docker, PostgreSQL, filesystem mounts, credentials or network needed.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile

import pytest

from tools.r08_backup_restore import (
    MAGIC, R08Error, SHA256_ID, RESTORE_SCRIPT,
    open_authenticated, read_header, seal_stream, main,
)

META = {"schema": "augmis.r08.backup.v1", "created_utc": "2026-10-28T00:00:00+00:00",
        "scope": "application", "instance_id": "fixture-only", "database": "augmis_app"}
PASSWORD = "correct horse fake test passphrase 1234"


def _make(path: Path, *, content=b"PGDMP" + b"fake pg dump bytes" * 400):
    return seal_stream(BytesIO(content), path, PASSWORD, META)


def test_roundtrip_authentic_and_no_plaintext_artifact(tmp_path):
    out = tmp_path / "archive.r08"
    receipt = _make(out)
    assert receipt["plaintext_bytes"] > 1000
    assert b"fake pg dump" not in out.read_bytes()
    destination = BytesIO()
    result = open_authenticated(out, PASSWORD, destination)
    assert result["scope"] == "application"
    assert destination.getvalue().startswith(b"PGDMP")
    assert result["verified_plaintext_bytes"] == len(destination.getvalue())
    assert list(tmp_path.iterdir()) == [out]


def test_modified_ciphertext_rejected(tmp_path):
    out = tmp_path / "archive.r08"
    _make(out)
    data = bytearray(out.read_bytes()); data[-28] ^= 1
    out.write_bytes(data)
    with pytest.raises(R08Error, match="INTEGRITY"):
        open_authenticated(out, PASSWORD)


def test_modified_authenticated_header_rejected(tmp_path):
    out = tmp_path / "archive.r08"
    _make(out)
    data = bytearray(out.read_bytes()); position = data.index(b"fixture-only"); data[position] ^= 1
    out.write_bytes(data)
    with pytest.raises(R08Error, match="INTEGRITY"):
        open_authenticated(out, PASSWORD)


def test_wrong_password_rejected(tmp_path):
    out = tmp_path / "archive.r08"; _make(out)
    with pytest.raises(R08Error, match="INTEGRITY"):
        open_authenticated(out, "another long incorrect test passphrase")


def test_truncated_archive_rejected(tmp_path):
    out = tmp_path / "archive.r08"; _make(out)
    out.write_bytes(out.read_bytes()[:30])
    with pytest.raises(R08Error):
        open_authenticated(out, PASSWORD)


def test_wrong_magic_rejected(tmp_path):
    out = tmp_path / "bad.r08"; out.write_bytes(b"NOT AUGMIS")
    with pytest.raises(R08Error, match="MAGIC"):
        open_authenticated(out, PASSWORD)


def test_reject_plaintext_stream(tmp_path):
    out = tmp_path / "archive.r08"
    with pytest.raises(R08Error, match="NOT_CUSTOM_PGDUMP"):
        seal_stream(BytesIO(b"plaintext"), out, PASSWORD, META)
    assert list(tmp_path.iterdir()) == []


def test_reject_existing_output(tmp_path):
    out = tmp_path / "archive.r08"; out.write_text("important")
    with pytest.raises(R08Error, match="OUTPUT_EXISTS"):
        _make(out)
    assert out.read_text() == "important"


def test_reject_short_passphrase(tmp_path):
    with pytest.raises(R08Error, match="TOO_SHORT"):
        seal_stream(BytesIO(b"PGDMPabc"), tmp_path / "a", "short", META)


def test_restore_is_explicit(tmp_path):
    assert main(["restore-probe", "--archive", str(tmp_path / "does-not-exist")]) == 2


def test_backup_is_explicit(tmp_path):
    assert main(["backup", "--scope", "platform", "--out", str(tmp_path / "x")]) == 2


def test_no_network_or_host_mounts():
    assert "listen_addresses=''" in RESTORE_SCRIPT
    assert "--auth-host=reject" in RESTORE_SCRIPT
    assert SHA256_ID.fullmatch("sha256:" + "a" * 64)
    assert not SHA256_ID.fullmatch("postgres:15")


def test_archive_header_contains_no_secrets(tmp_path):
    out = tmp_path / "archive.r08"; _make(out)
    with out.open("rb") as f:
        _prefix, metadata, _salt, _nonce = read_header(f)
    assert metadata["database"] == "augmis_app"
    assert "password" not in metadata
    assert "secret" not in metadata
