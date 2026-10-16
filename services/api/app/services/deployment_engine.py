from __future__ import annotations

import subprocess
import os
import time
import urllib.error
import urllib.request

from services.api.app.services.dashboard_runtime_mounts import DashboardPilotLaunch
from services.api.app.services.dev_dashboard_ingress import (
    require_dev_relay, relay_container_name, parse_relay_port,
    verify_companion_relay, DevIngressError,
)


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


def _dashboard_internal_health(container_name: str, timeout_seconds: int) -> None:
    """Check HTTP readiness INSIDE the private-network dashboard container.

    Direct host publishing is intentionally forbidden for the dashboard pilot.
    Python is present in the pinned image; no shell or Docker SDK is required.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            result = run_docker([
                "docker", "exec", container_name, "python", "-c",
                "import urllib.request; "
                "r=urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2); "
                "assert r.status == 200",
            ], timeout=8)
            return
        except DeploymentError:
            time.sleep(2)
    raise DeploymentError("Dashboard internal health did not become ready")


def _start_dashboard_dev_relay(*, container_name: str, labels: dict[str, str],
                               config, startup_timeout: int) -> tuple[str, int, str]:
    """Only DEV: create a credential-free, loopback-only companion relay."""
    relay_name = relay_container_name(container_name)
    command = [
        "docker", "run", "-d", "--name", relay_name,
        "--network", config.ingress_network,
        "--read-only", "--user", "10002:10002",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--memory", "128m", "--memory-swap", "128m", "--cpus", "0.25",
        "--pids-limit", "64", "--tmpfs", "/tmp:rw,nosuid,nodev,size=8m",
        "--env", f"AUGMIS_RELAY_UPSTREAM={container_name}",
        "--label", "augmis.managed=true",
        "--label", f"augmis.ingress_for={container_name}",
        "-p", "127.0.0.1::18080", config.relay_image_id,
    ]
    # Correlation labels originate from the trusted AUGMIS deployment context.
    for key in ("augmis.tenant_id", "augmis.application_id", "augmis.instance_id"):
        if key in labels:
            command[-1:-1] = ["--label", f"{key}={labels[key]}"]
    relay_id = run_docker(command)
    # No credentials or keys are present in the relay. It is the ONLY container
    # on both ingress and private networks; dashboard/DB remain private-only.
    run_docker(["docker", "network", "connect", config.private_network, relay_name])
    port_result = run_docker(["docker", "port", relay_name, "18080/tcp"])
    port = parse_relay_port(port_result)
    relay_url = f"http://127.0.0.1:{port}"
    wait_for_health(relay_url + "/healthz", startup_timeout)
    return relay_id, port, relay_url


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

    if pilot_runtime is not None and container_port != 8080:
        raise DeploymentError("Dashboard pilot service port must be 8080")

    # The dashboard pilot is development-only and MUST use a managed ingress
    # relay. Refuse the old direct -p publishing path even if config is missing.
    try:
        dev_relay = require_dev_relay(pilot_runtime, run_docker=run_docker) if pilot_runtime is not None else None
    except DevIngressError as exc:
        raise DeploymentError(str(exc)) from exc

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

    if pilot_runtime is None:
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


    # The existing path above returns. This branch is reached for the
    # explicitly allowlisted development dashboard only.
    # No -p at all for the dashboard on the internal DB network.
    command.extend([image_ref])
    container_id = run_docker(command)
    relay_name = relay_container_name(container_name)
    try:
        startup_timeout = int(manifest.get("lifecycle", {}).get("startupTimeoutSeconds", 120))
        if not 1 <= startup_timeout <= 300:
            raise DeploymentError("Invalid dashboard pilot startup timeout")
        _dashboard_internal_health(container_name, startup_timeout)
        _, host_port, base_url = _start_dashboard_dev_relay(
            container_name=container_name, labels=labels, config=dev_relay,
            startup_timeout=startup_timeout,
        )
    except Exception as error:
        # The relay may have been created before network/port/health failed.
        # Refuse to remove a non-managed container with a conflicting name.
        try:
            if verify_companion_relay(relay_name, container_name, run_docker):
                run_docker(["docker", "rm", "-f", relay_name])
        except DeploymentError:
            pass
        snapshot = None
        try:
            snapshot = get_container_logs(container_name=container_name, tail=200)
        except DeploymentError:
            pass
        try:
            run_docker(["docker", "rm", "-f", container_name])
        except DeploymentError:
            pass
        # Keep errors safe for API responses. Logs may contain sensitive data
        # and remain available only through existing admin log mechanisms.
        raise DeploymentError("Dashboard private ingress startup failed", log_snapshot=snapshot) from error
    return {
        "container_id": container_id,
        "container_name": container_name,
        "host_port": host_port,
        "runtime_url": base_url,
        "health_url": base_url + "/healthz",
        "service_name": service_name,
    }


def stop_container(
    container_name: str
):
    # If a DEV dashboard relay exists, verify its ownership label before
    # removing it. Never remove an unrelated container on a name collision.
    # Ordinary apps retain the original stop behavior when the pilot is off.
    if (os.environ.get("AUGMIS_DASHBOARD_DEV_RELAY_ENABLED") == "1"
            and container_name.startswith("augmis-")):
        try:
            relay_name = relay_container_name(container_name)
            if verify_companion_relay(relay_name, container_name, run_docker):
                run_docker(["docker", "rm", "-f", relay_name])
        except DevIngressError as exc:
            raise DeploymentError(str(exc)) from exc

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