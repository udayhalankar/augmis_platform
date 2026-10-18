
from __future__ import annotations

import hashlib
import json
import re
import stat
import sys
import tempfile
import zipfile

from pathlib import Path, PurePosixPath

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]

CONTRACT_FILE = (
    ROOT
    / "packages"
    / "contracts"
    / "aaps-v1.schema.json"
)

MANIFEST_NAME = "augmis-app.yaml"

MAX_FILES = 5000

MAX_UNCOMPRESSED_SIZE = 200 * 1024 * 1024

MAX_SINGLE_FILE_SIZE = 100 * 1024 * 1024


class PackageValidationError(Exception):
    pass


def calculate_sha256(file_path: Path) -> str:

    sha = hashlib.sha256()

    with file_path.open("rb") as f:

        while True:

            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            sha.update(chunk)

    return sha.hexdigest()


def load_contract() -> dict:

    if not CONTRACT_FILE.exists():

        raise PackageValidationError(
            f"Contract schema not found: {CONTRACT_FILE}"
        )

    with CONTRACT_FILE.open(
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def validate_zip_member_name(name: str):

    normalized = name.replace("\\", "/")

    if normalized.startswith("/"):

        raise PackageValidationError(
            f"Absolute path not allowed: {name}"
        )

    if re.match(
        r"^[A-Za-z]:",
        normalized
    ):

        raise PackageValidationError(
            f"Windows absolute path not allowed: {name}"
        )

    path = PurePosixPath(normalized)

    if ".." in path.parts:

        raise PackageValidationError(
            f"Path traversal detected: {name}"
        )


def is_symlink(info: zipfile.ZipInfo) -> bool:

    mode = (
        info.external_attr >> 16
    ) & 0o170000

    return mode == stat.S_IFLNK


def inspect_archive(zip_path: Path):

    with zipfile.ZipFile(
        zip_path,
        "r"
    ) as archive:

        members = archive.infolist()

        if len(members) > MAX_FILES:

            raise PackageValidationError(
                f"Package contains too many files. "
                f"Maximum is {MAX_FILES}."
            )

        total_size = 0

        for member in members:

            validate_zip_member_name(
                member.filename
            )

            if is_symlink(member):

                raise PackageValidationError(
                    f"Symbolic links are not allowed: "
                    f"{member.filename}"
                )

            if (
                member.file_size
                > MAX_SINGLE_FILE_SIZE
            ):

                raise PackageValidationError(
                    f"File too large: "
                    f"{member.filename}"
                )

            total_size += member.file_size

        if (
            total_size
            > MAX_UNCOMPRESSED_SIZE
        ):

            raise PackageValidationError(
                "Package exceeds maximum "
                "uncompressed size."
            )


def safe_extract(
    zip_path: Path,
    destination: Path
):

    destination = destination.resolve()

    with zipfile.ZipFile(
        zip_path,
        "r"
    ) as archive:

        for member in archive.infolist():

            validate_zip_member_name(
                member.filename
            )

            target = (
                destination
                / member.filename
            ).resolve()

            try:

                target.relative_to(
                    destination
                )

            except ValueError:

                raise PackageValidationError(
                    f"Illegal extraction path: "
                    f"{member.filename}"
                )

        archive.extractall(destination)


def load_manifest(
    extracted_root: Path
) -> dict:

    manifest_path = (
        extracted_root
        / MANIFEST_NAME
    )

    if not manifest_path.exists():

        raise PackageValidationError(
            f"{MANIFEST_NAME} must exist "
            f"at the root of the package."
        )

    with manifest_path.open(
        "r",
        encoding="utf-8"
    ) as f:

        manifest = yaml.safe_load(f)

    if not isinstance(
        manifest,
        dict
    ):

        raise PackageValidationError(
            "Application manifest must "
            "contain a YAML object."
        )

    return manifest


def validate_schema(
    manifest: dict,
    schema: dict
):

    validator = Draft202012Validator(
        schema
    )

    errors = sorted(
        validator.iter_errors(
            manifest
        ),
        key=lambda error: list(
            error.absolute_path
        )
    )

    if errors:

        messages = []

        for error in errors:

            location = ".".join(
                str(p)
                for p
                in error.absolute_path
            )

            if not location:

                location = "manifest"

            messages.append(
                f"{location}: "
                f"{error.message}"
            )

        raise PackageValidationError(
            "Manifest validation failed:\n"
            + "\n".join(
                f" - {message}"
                for message
                in messages
            )
        )


def resolve_package_path(
    package_root: Path,
    relative_path: str
) -> Path:

    package_root = (
        package_root.resolve()
    )

    path = (
        package_root
        / relative_path
    ).resolve()

    try:

        path.relative_to(
            package_root
        )

    except ValueError:

        raise PackageValidationError(
            f"Referenced path escapes "
            f"package root: "
            f"{relative_path}"
        )

    return path


def validate_runtime_files(
    root: Path,
    manifest: dict
):

    runtime = manifest["runtime"]

    build_type = runtime["buildType"]

    if build_type == "dockerfile":

        context = runtime["context"]

        dockerfile = runtime["dockerfile"]

        context_path = resolve_package_path(
            root,
            context
        )

        dockerfile_path = resolve_package_path(
            context_path,
            dockerfile
        )

        if not context_path.exists():

            raise PackageValidationError(
                f"Build context does not exist: "
                f"{context}"
            )

        if not dockerfile_path.exists():

            raise PackageValidationError(
                f"Dockerfile does not exist: "
                f"{dockerfile}"
            )

    elif build_type == "docker-compose":

        compose_file = runtime[
            "composeFile"
        ]

        compose_path = resolve_package_path(
            root,
            compose_file
        )

        if not compose_path.exists():

            raise PackageValidationError(
                f"Compose file does not exist: "
                f"{compose_file}"
            )


def validate_application_package(
    zip_path: Path
) -> dict:

    if not zip_path.exists():

        raise PackageValidationError(
            f"Package does not exist: "
            f"{zip_path}"
        )

    if zip_path.suffix.lower() != ".zip":

        raise PackageValidationError(
            "Application package must "
            "be a ZIP file."
        )

    inspect_archive(
        zip_path
    )

    package_hash = calculate_sha256(
        zip_path
    )

    schema = load_contract()

    with tempfile.TemporaryDirectory() as temp:

        temp_path = Path(temp)

        safe_extract(
            zip_path,
            temp_path
        )

        manifest = load_manifest(
            temp_path
        )

        validate_schema(
            manifest,
            schema
        )

        validate_runtime_files(
            temp_path,
            manifest
        )

        # Hash-declared migration artifacts are checked at ingestion, never
        # executed during upload/build. A publisher checksum is NOT approval.
        from services.api.app.services.aaps_deployment_contract import (
            migration_contract, route_contract, DeploymentContractError,
        )
        try:
            declared = migration_contract(manifest)
            route_contract(manifest)
            from services.api.app.services.aaps_declarative_schema import read_declarative_schema, SchemaContractError
            try:
                compiled_schema = read_declarative_schema(manifest)
            except SchemaContractError as exc:
                raise DeploymentContractError(exc.code, "Invalid declarative schema") from exc
            if declared and compiled_schema is not None:
                raise DeploymentContractError("C1C_SCHEMA_MODE_CONFLICT", "Use one schema declaration mode")
        except DeploymentContractError as exc:
            raise PackageValidationError(str(exc)) from exc
        for relative, expected in declared:
            file_path = resolve_package_path(temp_path, relative)
            if (not file_path.is_file() or file_path.is_symlink()
                    or file_path.stat().st_size > 256 * 1024):
                raise PackageValidationError('AAPS_MIGRATION_FILE_INVALID: ' + relative)
            if calculate_sha256(file_path) != expected:
                raise PackageValidationError('AAPS_MIGRATION_DIGEST_MISMATCH: ' + relative)

    return {

    "status": "VALID",

    "sha256": package_hash,

    "manifest": manifest,

        "application": {
            "id":
                manifest["metadata"]["id"],

            "name":
                manifest["metadata"]["name"],

            "version":
                manifest["metadata"]["version"]
        },

        "runtime": {
            "deploymentMode":
                manifest["runtime"][
                    "deploymentMode"
                ],

            "buildType":
                manifest["runtime"][
                    "buildType"
                ]
        }
    }


def main():

    if len(sys.argv) != 2:

        print(
            "Usage:\n"
            "python tools\\validate_package.py "
            "<application.zip>"
        )

        sys.exit(1)

    zip_path = Path(
        sys.argv[1]
    ).resolve()

    try:

        result = (
            validate_application_package(
                zip_path
            )
        )

        print()
        print("=" * 55)

        print(
            "AUGMIS APPLICATION "
            "PACKAGE VALIDATION"
        )

        print("=" * 55)

        print(
            f"Status       : "
            f"{result['status']}"
        )

        print(
            f"Application  : "
            f"{result['application']['name']}"
        )

        print(
            f"ApplicationID: "
            f"{result['application']['id']}"
        )

        print(
            f"Version      : "
            f"{result['application']['version']}"
        )

        print(
            f"Build Type   : "
            f"{result['runtime']['buildType']}"
        )

        print(
            f"Deployment   : "
            f"{result['runtime']['deploymentMode']}"
        )

        print(
            f"SHA256       : "
            f"{result['sha256']}"
        )

        print("=" * 55)

        print(
            "PACKAGE VALID"
        )

        print("=" * 55)

    except (
        PackageValidationError,
        zipfile.BadZipFile
    ) as error:

        print()
        print("=" * 55)

        print(
            "PACKAGE INVALID"
        )

        print("=" * 55)

        print(error)

        print("=" * 55)

        sys.exit(2)


if __name__ == "__main__":
    main()