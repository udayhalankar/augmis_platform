from __future__ import annotations

import subprocess
import os
import time
import urllib.error
import urllib.request

from services.api.app.services.dashboard_runtime_mounts import DashboardPilotLaunch


class DeploymentError(Exception):
    def __init__(self, message: str, *, log_snapshot: str | None = None):
        super().__init__(message)
        self.log_snapshot = log_snapshot


def runtime_resource_limits() -> tuple[str, str, str]:
    """Platform-owned guardrails. Never accept limits from a publisher manifest."""
    try:
        memory_mb = int(os.environ.get("AUGMIS_RUNTIME_MEMORY_MB", "1024"))
        cpus = float(os.environ.get("AUGMIS_RUNTIME_CPUS", "1"))
        pids = int(os.environ.get("AUGMIS_RUNTIME_PIDS", "256"))
    except (TypeError, ValueError) as exc:
        raise DeploymentError("Invalid platform runtime resource configuration") from exc
    if not 128 <= memory_mb <= 32768 or not 0.25 <= cpus <= 16 or not 32 <= pids <= 4096:
        raise DeploymentError("Platform runtime resource configuration outside allowed range")
    return f"{memory_mb}m", f"{cpus:g}", str(pids)


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
                    < 300
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
    labels: dict[str, str],
    environment: dict[str, str] | None = None,
    pilot_runtime: DashboardPilotLaunch | None = None,
) -> dict:

    service_name, service = (
        find_public_service(
            manifest
        )
    )

    container_port = int(
        service["port"]
    )

    memory_limit, cpu_limit, pid_limit = runtime_resource_limits()

    command = [
        "docker", "run", "-d",
        "--name", container_name,
        "--memory", memory_limit,
        "--memory-swap", memory_limit,
        "--cpus", cpu_limit,
        "--pids-limit", pid_limit,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
    ]

    # Only this explicitly approved image may obtain read-only secret mounts.
    # The configured network must already be an internal Docker network.
    if pilot_runtime is not None:
        command.extend([
            "--network", pilot_runtime.private_network,
            "--read-only",
            "--user", "10001:10001",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m",
        ])
        for source, target in pilot_runtime.secret_mounts:
            command.extend([
                "--mount",
                f"type=bind,source={source},target={target},readonly",
            ])
        for key, value in pilot_runtime.environment.items():
            command.extend(["--env", f"{key}={value}"])

    # Non-secret variables only. Never pass credentials through this API.
    for key, value in (environment or {}).items():
        command.extend(["--env", f"{key}={value}"])

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

    except Exception as startup_error:
        # Docker removes failed candidates below. Preserve a bounded snapshot
        # on the exception so the API can persist it with the deployment.
        snapshot = None
        try:
            snapshot = get_container_logs(container_name=container_name, tail=2000)
        except DeploymentError:
            pass

        try:
            run_docker(["docker", "rm", "-f", container_name])
        except DeploymentError:
            pass

        if isinstance(startup_error, DeploymentError):
            raise DeploymentError(
                str(startup_error), log_snapshot=snapshot,
            ) from startup_error
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

def get_container_logs(
    container_name: str,
    tail: int = 200,
) -> str:

    if tail < 1:
        tail = 1

    if tail > 2000:
        tail = 2000

    try:

        result = subprocess.run(
            [
                "docker",
                "logs",
                "--tail",
                str(tail),
                "--timestamps",
                container_name,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

    except subprocess.TimeoutExpired as error:

        raise DeploymentError(
            "Docker logs command timed out."
        ) from error

    except OSError as error:

        raise DeploymentError(
            f"Could not execute Docker: {error}"
        ) from error

    if result.returncode != 0:

        raise DeploymentError(
            (
                result.stderr
                or result.stdout
                or "Could not retrieve container logs."
            ).strip()
        )

    # Docker preserves stdout/stderr separately.
    # Combine both so application errors are not lost.

    parts = []

    if result.stdout:

        parts.append(
            result.stdout.rstrip()
        )

    if result.stderr:

        parts.append(
            result.stderr.rstrip()
        )

    return "\n".join(parts)