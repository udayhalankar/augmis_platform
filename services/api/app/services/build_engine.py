from __future__ import annotations

import shutil
import subprocess
import tempfile

from pathlib import Path

from tools.validate_package import (
    PackageValidationError,
    safe_extract
)


class BuildError(Exception):
    pass


def docker_available() -> bool:

    return shutil.which("docker") is not None


def build_docker_image(
    package_path: Path,
    manifest: dict,
    image_ref: str,
    timeout_seconds: int = 900
) -> dict:

    if not docker_available():

        raise BuildError(
            "Docker CLI is not available."
        )

    runtime = manifest["runtime"]

    build_type = runtime["buildType"]

    if build_type != "dockerfile":

        raise BuildError(
            "Stage 3 currently supports "
            "buildType=dockerfile only."
        )

    with tempfile.TemporaryDirectory(
        prefix="augmis-build-"
    ) as temp_dir:

        workspace = Path(
            temp_dir
        ).resolve()

        try:

            safe_extract(
                package_path,
                workspace
            )

        except PackageValidationError as error:

            raise BuildError(
                str(error)
            ) from error

        context_value = runtime[
            "context"
        ]

        dockerfile_value = runtime[
            "dockerfile"
        ]

        context_path = (
            workspace
            / context_value
        ).resolve()

        dockerfile_path = (
            context_path
            / dockerfile_value
        ).resolve()

        try:

            context_path.relative_to(
                workspace
            )

            dockerfile_path.relative_to(
                workspace
            )

        except ValueError:

            raise BuildError(
                "Build paths escape "
                "the package workspace."
            )

        if not context_path.exists():

            raise BuildError(
                f"Build context does not exist: "
                f"{context_value}"
            )

        if not dockerfile_path.exists():

            raise BuildError(
                f"Dockerfile does not exist: "
                f"{dockerfile_value}"
            )

        command = [
            "docker",
            "build",
            "--pull",
            "-f",
            str(dockerfile_path),
            "-t",
            image_ref,
            str(context_path)
        ]

        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )

        except subprocess.TimeoutExpired as error:

            raise BuildError(
                "Docker build timed out."
            ) from error

        except OSError as error:

            raise BuildError(
                f"Could not start Docker: {error}"
            ) from error

        build_log = (
            (result.stdout or "")
            + "\n"
            + (result.stderr or "")
        )

        if result.returncode != 0:

            raise BuildError(
                build_log
            )

        return {
            "status": "ready",
            "image_ref": image_ref,
            "log": build_log
        }