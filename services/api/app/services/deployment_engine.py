from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request


class DeploymentError(Exception):
    pass


def run_docker(
    command: list[str],
    timeout: int = 120
) -> str:

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout
        )

    except subprocess.TimeoutExpired as error:

        raise DeploymentError(
            "Docker command timed out."
        ) from error

    except OSError as error:

        raise DeploymentError(
            f"Could not execute Docker: {error}"
        ) from error

    if result.returncode != 0:

        raise DeploymentError(
            (result.stderr or result.stdout).strip()
        )

    return result.stdout.strip()


def find_public_service(
    manifest: dict
) -> tuple[str, dict]:

    services = manifest.get(
        "services",
        {}
    )

    for service_name, service in services.items():

        if service.get(
            "public",
            False
        ):

            return (
                service_name,
                service
            )

    raise DeploymentError(
        "Application does not define "
        "a public service."
    )


def wait_for_health(
    url: str,
    timeout_seconds: int
):

    deadline = (
        time.time()
        + timeout_seconds
    )

    last_error = None

    while time.time() < deadline:

        try:

            request = urllib.request.Request(
                url,
                method="GET"
            )

            with urllib.request.urlopen(
                request,
                timeout=3
            ) as response:

                if (
                    200
                    <= response.status
                    < 500
                ):

                    return

        except Exception as error:

            last_error = error

        time.sleep(2)

    raise DeploymentError(
        f"Application health check failed: "
        f"{last_error}"
    )


def start_container(
    image_ref: str,
    manifest: dict,
    container_name: str,
    labels: dict[str, str]
) -> dict:

    service_name, service = (
        find_public_service(
            manifest
        )
    )

    container_port = int(
        service["port"]
    )

    command = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name
    ]

    for key, value in labels.items():

        command.extend(
            [
                "--label",
                f"{key}={value}"
            ]
        )

    command.extend(
        [
            "-p",
            f"127.0.0.1::{container_port}",
            image_ref
        ]
    )

    container_id = run_docker(
        command
    )

    try:

        port_output = run_docker(
            [
                "docker",
                "port",
                container_name,
                f"{container_port}/tcp"
            ]
        )

        first_line = (
            port_output
            .splitlines()[0]
            .strip()
        )

        host_port = int(
            first_line.rsplit(
                ":",
                1
            )[1]
        )

        base_url = (
            f"http://127.0.0.1:"
            f"{host_port}"
        )

        health_config = (
            service.get(
                "health"
            )
            or {}
        )

        health_path = (
            health_config.get(
                "path",
                "/"
            )
        )

        startup_timeout = int(
            manifest
            .get(
                "lifecycle",
                {}
            )
            .get(
                "startupTimeoutSeconds",
                120
            )
        )

        health_url = (
            base_url
            + health_path
        )

        wait_for_health(
            health_url,
            startup_timeout
        )

    except Exception:

        try:

            run_docker(
                [
                    "docker",
                    "rm",
                    "-f",
                    container_name
                ]
            )

        except Exception:
            pass

        raise

    return {

        "container_id":
            container_id,

        "container_name":
            container_name,

        "host_port":
            host_port,

        "runtime_url":
            base_url,

        "health_url":
            health_url,

        "service_name":
            service_name
    }


def stop_container(
    container_name: str
):

    run_docker(
        [
            "docker",
            "rm",
            "-f",
            container_name
        ]
    )