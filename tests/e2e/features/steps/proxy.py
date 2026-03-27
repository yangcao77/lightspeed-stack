"""Step definitions for proxy and TLS networking e2e tests.

These tests configure Llama Stack's run.yaml with NetworkConfig settings
(proxy, TLS) and verify the full pipeline works through the Lightspeed Stack.
The proxy sits between Llama Stack and the LLM provider (e.g., OpenAI).

Works in both Docker (CI) and local (non-Docker) environments:
- Docker: overwrites run.yaml on host, restarts containers via docker commands
- Local: overwrites run.yaml, restarts services via process management
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import requests
import trustme
import yaml
from behave import given, then, when  # pyright: ignore[reportAttributeAccessIssue]
from behave.runner import Context

from tests.e2e.utils.utils import (
    restart_container,
)

# Base Llama Stack config — in Docker CI this is mounted into the container
_LLAMA_STACK_CONFIG = "run.yaml"
_LLAMA_STACK_CONFIG_BACKUP = "run.yaml.proxy-backup"


def _is_docker_mode() -> bool:
    """Check if services are running in Docker containers."""
    result = subprocess.run(
        ["docker", "ps", "--filter", "name=llama-stack", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return "llama-stack" in result.stdout


def _get_proxy_host(is_docker: bool) -> str:
    """Get the host address that Docker containers can use to reach the proxy.

    In Docker mode, containers reach the host via the Docker bridge gateway.
    In local mode, localhost works directly.

    Parameters:
        is_docker: Whether services are running in Docker containers.
    """
    if is_docker:
        result = subprocess.run(
            [
                "docker",
                "network",
                "inspect",
                "lightspeednet",
                "--format",
                "{{(index .IPAM.Config 0).Gateway}}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        gateway = result.stdout.strip()
        if gateway:
            return gateway
        return "172.17.0.1"
    return "127.0.0.1"


def _load_llama_config() -> dict[str, Any]:
    """Load the base Llama Stack run config."""
    with open(_LLAMA_STACK_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write_config(config: dict[str, Any], path: str) -> None:
    """Write a YAML config file."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False)


def _find_openai_provider(config: dict[str, Any]) -> dict[str, Any]:
    """Find the OpenAI inference provider in the config.

    Raises:
        AssertionError: If no remote::openai provider is found.
    """
    providers = config.get("providers", {})
    for provider in providers.get("inference", []):
        if provider.get("provider_type") == "remote::openai":
            return provider
    raise AssertionError("No remote::openai provider found in run.yaml")


def _backup_llama_config() -> None:
    """Create a backup of the current run.yaml if not already backed up."""
    if not os.path.exists(_LLAMA_STACK_CONFIG_BACKUP):
        shutil.copy(_LLAMA_STACK_CONFIG, _LLAMA_STACK_CONFIG_BACKUP)


def _restart_services(is_docker: bool = False) -> None:
    """Restart Llama Stack and Lightspeed Stack.

    Works in both Docker and local environments.

    Parameters:
        is_docker: Whether services are running in Docker containers.
    """
    if is_docker:
        restart_container("llama-stack")
        restart_container("lightspeed-stack")
    else:
        _restart_services_local()


def _restart_services_local() -> None:
    """Restart services in local (non-Docker) mode."""
    subprocess.run(
        ["pkill", "-f", "llama stack run"],
        capture_output=True,
        check=False,
    )
    time.sleep(3)

    env = os.environ.copy()
    env["OPENSSL_CONF"] = ""
    llama_port = os.getenv("E2E_LLAMA_PORT", "8321")
    with open("/tmp/llama-stack-proxy-test.log", "w") as log_file:
        subprocess.Popen(
            [
                "uv",
                "run",
                "llama",
                "stack",
                "run",
                _LLAMA_STACK_CONFIG,
                "--port",
                llama_port,
            ],
            env=env,
            stdout=log_file,
            stderr=log_file,
        )

    llama_host = os.getenv("E2E_LLAMA_HOSTNAME", "localhost")
    for _ in range(45):
        try:
            resp = requests.get(
                f"http://{llama_host}:{llama_port}/v1/health", timeout=2
            )
            if resp.status_code == 200:
                break
        except requests.ConnectionError:
            pass
        time.sleep(2)

    subprocess.run(
        ["pkill", "-f", "lightspeed_stack.py"],
        capture_output=True,
        check=False,
    )
    time.sleep(2)

    config_path = os.getenv(
        "E2E_LSC_CONFIG",
        "tests/e2e/configuration/server-mode/lightspeed-stack.yaml",
    )
    with open("/tmp/lightspeed-stack-proxy-test.log", "w") as log_file:
        subprocess.Popen(
            ["uv", "run", "src/lightspeed_stack.py", "-c", config_path],
            env=env,
            stdout=log_file,
            stderr=log_file,
        )

    hostname = os.getenv("E2E_LSC_HOSTNAME", "localhost")
    port = os.getenv("E2E_LSC_PORT", "8080")
    for _ in range(15):
        try:
            resp = requests.get(f"http://{hostname}:{port}/liveness", timeout=2)
            if resp.status_code == 200:
                break
        except requests.ConnectionError:
            pass
        time.sleep(2)


# --- Background Steps ---


@given("The original Llama Stack config is restored if modified")
def restore_if_modified(context: Context) -> None:
    """Restore original run.yaml if a previous scenario modified it.

    Called from Background so every scenario starts with a clean config,
    even if the previous scenario failed mid-way.
    """
    if os.path.exists(_LLAMA_STACK_CONFIG_BACKUP):
        print("Restoring original Llama Stack config from backup...")
        shutil.copy(_LLAMA_STACK_CONFIG_BACKUP, _LLAMA_STACK_CONFIG)
        os.remove(_LLAMA_STACK_CONFIG_BACKUP)
        try:
            _restart_services(is_docker=context.is_docker_mode)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Warning: Service restart after restore failed: {e}")


# --- Tunnel Proxy Steps ---


@given("A tunnel proxy is running on port {port:d}")
def start_tunnel_proxy(context: Context, port: int) -> None:
    """Start a tunnel proxy in a background thread."""
    from tests.e2e.proxy.tunnel_proxy import TunnelProxy

    proxy = TunnelProxy(host="0.0.0.0", port=port)
    loop = asyncio.new_event_loop()
    context.proxy_loop = loop
    context.tunnel_proxy = proxy

    def run_proxy() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(proxy.start())
        loop.run_forever()

    thread = threading.Thread(target=run_proxy, daemon=True)
    thread.start()
    time.sleep(1)


@given("Llama Stack is configured to route inference through the tunnel proxy")
def configure_llama_tunnel_proxy(context: Context) -> None:
    """Modify run.yaml with proxy config pointing to the tunnel proxy."""
    _backup_llama_config()
    proxy = context.tunnel_proxy
    proxy_host = _get_proxy_host(context.is_docker_mode)
    config = _load_llama_config()
    provider = _find_openai_provider(config)

    if "config" not in provider:
        provider["config"] = {}
    provider["config"]["network"] = {
        "proxy": {
            "url": f"http://{proxy_host}:{proxy.port}",
        }
    }

    _write_config(config, _LLAMA_STACK_CONFIG)
    context.llama_config_modified = True


@given('Llama Stack is configured to route inference through proxy "{proxy_url}"')
def configure_llama_unreachable_proxy(context: Context, proxy_url: str) -> None:
    """Modify run.yaml with a proxy URL (may be unreachable)."""
    _backup_llama_config()
    config = _load_llama_config()
    provider = _find_openai_provider(config)

    if "config" not in provider:
        provider["config"] = {}
    provider["config"]["network"] = {
        "proxy": {
            "url": proxy_url,
        }
    }

    _write_config(config, _LLAMA_STACK_CONFIG)
    context.llama_config_modified = True


# --- Interception Proxy Steps ---


@given("An interception proxy with trustme CA is running on port {port:d}")
def start_interception_proxy(context: Context, port: int) -> None:
    """Start an interception proxy with trustme CA."""
    from tests.e2e.proxy.interception_proxy import InterceptionProxy

    ca = trustme.CA()
    proxy = InterceptionProxy(ca=ca, host="0.0.0.0", port=port)

    # Write cert to a known path
    ca_cert_path = Path(tempfile.gettempdir()) / "interception-proxy-ca.pem"
    proxy.export_ca_cert(ca_cert_path)

    # In Docker mode, copy the cert into the llama-stack container
    if context.is_docker_mode:
        container_cert_path = "/tmp/interception-proxy-ca.pem"
        subprocess.run(
            ["docker", "cp", str(ca_cert_path), f"llama-stack:{container_cert_path}"],
            check=True,
        )
        context.ca_cert_path_for_config = container_cert_path
    else:
        context.ca_cert_path_for_config = str(ca_cert_path)

    loop = asyncio.new_event_loop()
    context.interception_proxy_loop = loop
    context.interception_proxy = proxy
    context.interception_ca_cert_path = str(ca_cert_path)

    def run_proxy() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(proxy.start())
        loop.run_forever()

    thread = threading.Thread(target=run_proxy, daemon=True)
    thread.start()
    time.sleep(1)


@given(
    "Llama Stack is configured to route inference through "
    "the interception proxy with CA cert"
)
def configure_llama_interception_with_ca(context: Context) -> None:
    """Modify run.yaml with interception proxy and CA cert config."""
    _backup_llama_config()
    proxy = context.interception_proxy
    proxy_host = _get_proxy_host(context.is_docker_mode)
    config = _load_llama_config()
    provider = _find_openai_provider(config)

    if "config" not in provider:
        provider["config"] = {}
    provider["config"]["network"] = {
        "proxy": {
            "url": f"http://{proxy_host}:{proxy.port}",
            "cacert": context.ca_cert_path_for_config,
        },
        "tls": {
            "verify": context.ca_cert_path_for_config,
        },
    }

    _write_config(config, _LLAMA_STACK_CONFIG)
    context.llama_config_modified = True


@given(
    "Llama Stack is configured to route inference through "
    "the interception proxy without CA cert"
)
def configure_llama_interception_no_ca(context: Context) -> None:
    """Modify run.yaml with interception proxy but NO CA cert."""
    _backup_llama_config()
    proxy = context.interception_proxy
    proxy_host = _get_proxy_host(context.is_docker_mode)
    config = _load_llama_config()
    provider = _find_openai_provider(config)

    if "config" not in provider:
        provider["config"] = {}
    provider["config"]["network"] = {
        "proxy": {
            "url": f"http://{proxy_host}:{proxy.port}",
        },
    }

    _write_config(config, _LLAMA_STACK_CONFIG)
    context.llama_config_modified = True


# --- TLS Steps ---


@given('Llama Stack is configured with minimum TLS version "{version}"')
def configure_llama_tls_version(context: Context, version: str) -> None:
    """Modify run.yaml with TLS version config."""
    _backup_llama_config()
    config = _load_llama_config()
    provider = _find_openai_provider(config)

    if "config" not in provider:
        provider["config"] = {}
    provider["config"]["network"] = {
        "tls": {
            "min_version": version,
        }
    }

    _write_config(config, _LLAMA_STACK_CONFIG)
    context.llama_config_modified = True


@given('Llama Stack is configured with ciphers "{ciphers}"')
def configure_llama_ciphers(context: Context, ciphers: str) -> None:
    """Modify run.yaml with cipher suite config."""
    _backup_llama_config()
    config = _load_llama_config()
    provider = _find_openai_provider(config)

    if "config" not in provider:
        provider["config"] = {}
    provider["config"]["network"] = {
        "tls": {
            "ciphers": ciphers.split(":"),
        }
    }

    _write_config(config, _LLAMA_STACK_CONFIG)
    context.llama_config_modified = True


# --- Service Restart Steps ---


@given("The services are restarted with the modified Llama Stack config")
def restart_services_step(context: Context) -> None:
    """Restart Llama Stack with new config and restart Lightspeed Stack."""
    _restart_services(is_docker=context.is_docker_mode)


# --- Query Steps ---


@when('I send a query "{query}" to the LLM')
def send_query(context: Context, query: str) -> None:
    """Send a query through the Lightspeed Stack."""
    hostname = context.hostname
    port = context.port
    try:
        context.response = requests.post(
            f"http://{hostname}:{port}/v1/query",
            json={"query": query},
            timeout=60,
        )
    except requests.ConnectionError as e:
        context.response = None
        context.connection_error = str(e)


# --- Verification Steps ---


@then("The LLM responds successfully")
def verify_llm_response(context: Context) -> None:
    """Verify the LLM returned a successful response."""
    assert context.response is not None, (
        "No response received. "
        f"Connection error: {getattr(context, 'connection_error', 'unknown')}"
    )
    assert context.response.status_code == 200, (
        f"Expected 200, got {context.response.status_code}: "
        f"{context.response.text[:200]}"
    )


@then("The response indicates a proxy or connection error")
def verify_error_response(context: Context) -> None:
    """Verify the response indicates a connection or proxy error."""
    if context.response is not None:
        assert (
            context.response.status_code >= 400
        ), f"Expected error status, got {context.response.status_code}"
    else:
        assert hasattr(
            context, "connection_error"
        ), "Expected a connection error or error response"


@then(
    "The tunnel proxy handled at least {count:d} " "CONNECT request to the LLM provider"
)
def verify_tunnel_proxy_used(context: Context, count: int) -> None:
    """Verify the tunnel proxy received CONNECT requests."""
    proxy = context.tunnel_proxy
    assert proxy.connect_count >= count, (
        f"Expected at least {count} CONNECT requests, " f"got {proxy.connect_count}"
    )
    assert proxy.last_connect_target is not None, "No CONNECT target recorded"


@then("The interception proxy intercepted at least {count:d} connection")
def verify_interception_proxy_used(context: Context, count: int) -> None:
    """Verify the interception proxy intercepted connections."""
    proxy = context.interception_proxy
    assert proxy.connect_count >= count, (
        f"Expected at least {count} intercepted connections, "
        f"got {proxy.connect_count}"
    )
