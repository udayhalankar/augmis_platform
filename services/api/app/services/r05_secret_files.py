"""R05 production secret-file checks. Never embed credentials in exceptions or logs.

EC2 deployment projects AWS Secrets Manager content to protected mounted files;
IAM, projection, rotation and backups are configured/verified in R14.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path


class SecretMaterialError(RuntimeError):
    """Fixed non-sensitive error identifier."""


def read_production_secret_file(path: str, *, purpose: str, max_bytes: int = 16384) -> str:
    """Read an owned, regular, nonsymlinked, private Linux secret file.

    Disallows special files, paths through symlinks and group/other-readable
    material. Does not follow symlinks, even if they exist in a parent folder.
    """
    code = "R05_SECRET_FILE_INVALID"
    if os.name != "posix":
        raise SecretMaterialError("R05_PRODUCTION_LINUX_REQUIRED")
    try:
        value = Path(path)
        if not value.is_absolute() or not path or "\x00" in path or purpose not in {
            "jwt", "database", "settings", "smtp", "webhook", "signing"
        }:
            raise ValueError("invalid secret path")
        for part in (value, *value.parents):
            if stat.S_ISLNK(part.lstat().st_mode):
                raise ValueError("symlink path")
        meta = value.stat()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_size <= 0 or
            meta.st_size > max_bytes or meta.st_mode & 0o077 or
            meta.st_uid not in {0, os.geteuid()}):
            raise ValueError("untrusted secret file")
        descriptor = os.open(str(value), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            opened = os.fstat(descriptor)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_ino != meta.st_ino or
                opened.st_dev != meta.st_dev):
                raise ValueError("secret changed during read")
            raw = os.read(descriptor, max_bytes + 1)
        finally:
            os.close(descriptor)
        if not raw or len(raw) > max_bytes:
            raise ValueError("invalid secret length")
        result = raw.decode("utf-8")
        # Standard mounted text secrets may end with a single terminal newline.
        result = result.removesuffix("\n").removesuffix("\r")
        if not result or "\x00" in result or "\n" in result or "\r" in result:
            raise ValueError("invalid secret content")
        return result
    except Exception:
        # Never propagate OS error details or input paths which might embed secrets.
        raise SecretMaterialError(code) from None


def validate_production_signing_file(path: Path) -> None:
    """Signing PEM is multiline, so validate metadata without reading as a text secret."""
    if os.name != "posix":
        raise SecretMaterialError("R05_PRODUCTION_LINUX_REQUIRED")
    try:
        if not path.is_absolute():
            raise ValueError()
        for parent in (path, *path.parents):
            if stat.S_ISLNK(parent.lstat().st_mode):
                raise ValueError()
        record = path.stat()
        if (not stat.S_ISREG(record.st_mode) or record.st_size < 64 or
            record.st_size > 16384 or record.st_mode & 0o077 or
            record.st_uid not in {0, os.geteuid()}):
            raise ValueError()
    except Exception:
        raise SecretMaterialError("R05_SIGNING_KEY_FILE_UNSAFE") from None


def read_production_signing_key(path: Path) -> bytes:
    """Read a validated PEM without following an attacker-swapped final symlink."""
    validate_production_signing_file(path)
    try:
        earlier = path.stat()
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            current = os.fstat(fd)
            if (not stat.S_ISREG(current.st_mode) or current.st_ino != earlier.st_ino or
                current.st_dev != earlier.st_dev or current.st_mode & 0o077):
                raise ValueError()
            result = os.read(fd, 16385)
        finally:
            os.close(fd)
        if not 64 <= len(result) <= 16384:
            raise ValueError()
        return result
    except Exception:
        raise SecretMaterialError("R05_SIGNING_KEY_FILE_UNSAFE") from None
