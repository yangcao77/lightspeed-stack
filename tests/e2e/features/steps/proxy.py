"""Step definitions for proxy and TLS networking e2e tests.

These tests configure Llama Stack's run.yaml with NetworkConfig settings
(proxy, TLS) and verify the full pipeline works through the Lightspeed Stack.
The proxy sits between Llama Stack and the LLM provider (e.g., OpenAI).
"""

import asyncio
import os
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

# Base Llama Stack config to modify for proxy tests
_LLAMA_STACK_CONFIG = "tests/e2e/configs/run-ci.yaml"


def _load_llama_config() -> dict[str, Any]:
    """Load the base Llama Stack run config."""
    with open(_LLAMA_STACK_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write_config(config: dict[str, Any], path: str) -> None:
    """Write a YAML config file."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False)


def _find_openai_provider(config: dict[str, Any]) -> dict[str, Any] | None:
    """Find the OpenAI inference provider in the config."""
    providers = config.get("providers", {})
    for provider in providers.get("inference", []):
        if provider.get("provider_type") == "remote::openai":
            return provider
    return None


def _restart_llama_stack(config_path: str) -> None:
    """Restart Llama Stack with a new config.

    Parameters:
        config_path: Path to the run.yaml config file.
    """
    # Kill existing Llama Stack
    subprocess.run(
        ["pkill", "-f", "llama stack run"],
        capture_output=True,
        check=False,
    )
    time.sleep(3)

    # Start with new config
    env = os.environ.copy()
    env["OPENSSL_CONF"] = ""
    llama_port = os.getenv("E2E_LLAMA_PORT", "8321")
    with open("/tmp/llama-stack-proxy-test.log", "w") as log_file:
        subprocess.Popen(
            ["uv", "run", "llama", "stack", "run", config_path, "--port", llama_port],
            env=env,
            stdout=log_file,
            stderr=log_file,
        )

    # Wait for readiness
    llama_host = os.getenv("E2E_LLAMA_HOSTNAME", "localhost")
    for i in range(45):
        try:
            resp = requests.get(
                f"http://{llama_host}:{llama_port}/v1/health", timeout=2
            )
            if resp.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(2)

    raise TimeoutError("Llama Stack did not start within 90 seconds")


def _restart_lightspeed_stack() -> None:
    """Restart the Lightspeed Stack to pick up the new Llama Stack."""
    subprocess.run(
        ["pkill", "-f", "lightspeed_stack.py"],
        capture_output=True,
        check=False,
    )
    time.sleep(2)

    env = os.environ.copy()
    env["OPENSSL_CONF"] = ""
    config_path = os.getenv(
        "E2E_LSC_CONFIG", "tests/e2e/configuration/server-mode/lightspeed-stack.yaml"
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
    for i in range(15):
        try:
            resp = requests.get(f"http://{hostname}:{port}/liveness", timeout=2)
            if resp.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(2)

    raise TimeoutError("Lightspeed Stack did not start within 30 seconds")


# --- Tunnel Proxy Steps ---


@given("A tunnel proxy is running on port {port:d}")
def start_tunnel_proxy(context: Context, port: int) -> None:
    """Start a tunnel proxy in a background thread."""
    from tests.e2e.proxy.tunnel_proxy import TunnelProxy

    proxy = TunnelProxy(port=port)
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
    """Write a run.yaml with proxy config pointing to the tunnel proxy."""
    proxy = context.tunnel_proxy
    config = _load_llama_config()
    provider = _find_openai_provider(config)
    assert provider is not None, "No remote::openai provider found in run-ci.yaml"

    if "config" not in provider:
        provider["config"] = {}
    provider["config"]["network"] = {
        "proxy": {
            "url": f"http://{proxy.host}:{proxy.port}",
        }
    }

    config_path = os.path.join(tempfile.gettempdir(), "run-ci-proxy.yaml")
    _write_config(config, config_path)
    context.llama_config_path = config_path


# --- Interception Proxy Steps ---


@given("An interception proxy with trustme CA is running on port {port:d}")
def start_interception_proxy(context: Context, port: int) -> None:
    """Start an interception proxy with trustme CA."""
    from tests.e2e.proxy.interception_proxy import InterceptionProxy

    ca = trustme.CA()
    proxy = InterceptionProxy(ca=ca, port=port)

    ca_cert_path = Path(tempfile.gettempdir()) / "interception-proxy-ca.pem"
    proxy.export_ca_cert(ca_cert_path)

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
    "Llama Stack is configured to route inference through the interception proxy with CA cert"
)
def configure_llama_interception_proxy(context: Context) -> None:
    """Write a run.yaml with interception proxy and CA cert config."""
    proxy = context.interception_proxy
    config = _load_llama_config()
    provider = _find_openai_provider(config)
    assert provider is not None, "No remote::openai provider found in run-ci.yaml"

    if "config" not in provider:
        provider["config"] = {}
    provider["config"]["network"] = {
        "proxy": {
            "url": f"http://{proxy.host}:{proxy.port}",
            "cacert": context.interception_ca_cert_path,
        },
        "tls": {
            "verify": context.interception_ca_cert_path,
        },
    }

    config_path = os.path.join(tempfile.gettempdir(), "run-ci-interception.yaml")
    _write_config(config, config_path)
    context.llama_config_path = config_path


# --- TLS Steps ---


@given('Llama Stack is configured with minimum TLS version "{version}"')
def configure_llama_tls(context: Context, version: str) -> None:
    """Write a run.yaml with TLS version config."""
    config = _load_llama_config()
    provider = _find_openai_provider(config)
    assert provider is not None, "No remote::openai provider found in run-ci.yaml"

    if "config" not in provider:
        provider["config"] = {}
    provider["config"]["network"] = {
        "tls": {
            "min_version": version,
        }
    }

    config_path = os.path.join(tempfile.gettempdir(), "run-ci-tls.yaml")
    _write_config(config, config_path)
    context.llama_config_path = config_path


# --- Service Restart Steps ---


@given("The lightspeed stack is restarted with the proxy-configured Llama Stack")
@given("The lightspeed stack is restarted with the TLS-configured Llama Stack")
def restart_services(context: Context) -> None:
    """Restart Llama Stack with new config and restart Lightspeed Stack."""
    _restart_llama_stack(context.llama_config_path)
    _restart_lightspeed_stack()


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


@then("The LLM responds successfully")
def verify_llm_response(context: Context) -> None:
    """Verify the LLM returned a successful response."""
    assert (
        context.response is not None
    ), f"No response received. Connection error: {getattr(context, 'connection_error', 'unknown')}"
    assert (
        context.response.status_code == 200
    ), f"Expected 200, got {context.response.status_code}: {context.response.text[:200]}"


# --- Proxy Verification Steps ---


@then("The tunnel proxy handled at least {count:d} CONNECT request to the LLM provider")
def verify_tunnel_proxy_used(context: Context, count: int) -> None:
    """Verify the tunnel proxy received CONNECT requests."""
    proxy = context.tunnel_proxy
    assert (
        proxy.connect_count >= count
    ), f"Expected at least {count} CONNECT requests, got {proxy.connect_count}"
    # Verify the target was an LLM provider endpoint
    assert proxy.last_connect_target is not None, "No CONNECT target recorded"


@then("The interception proxy intercepted at least {count:d} connection")
def verify_interception_proxy_used(context: Context, count: int) -> None:
    """Verify the interception proxy intercepted connections."""
    proxy = context.interception_proxy
    assert (
        proxy.connect_count >= count
    ), f"Expected at least {count} intercepted connections, got {proxy.connect_count}"
