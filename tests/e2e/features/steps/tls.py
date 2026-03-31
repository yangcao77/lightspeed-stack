"""Step definitions for TLS configuration e2e tests.

These tests configure Llama Stack's run.yaml with NetworkConfig TLS settings
and verify the full pipeline works through the Lightspeed Stack.

Config switching uses the same pattern as other e2e tests: overwrite the
host-mounted run.yaml and restart Docker containers. Cleanup is handled
by a Background step that restores the backup before each scenario.
"""

import copy
from typing import Any, Optional

from behave import given  # pyright: ignore[reportAttributeAccessIssue]
from behave.runner import Context

from tests.e2e.features.steps.proxy import (
    _LLAMA_STACK_CONFIG,
    _backup_llama_config,
    _load_llama_config,
    _write_config,
)

_TLS_PROVIDER_BASE: dict[str, Any] = {
    "provider_id": "tls-openai",
    "provider_type": "remote::openai",
    "config": {
        "api_key": "test-key",
        "base_url": "https://mock-tls-inference:8443/v1",
        "allowed_models": ["mock-tls-model"],
    },
}

_TLS_MODEL_RESOURCE: dict[str, str] = {
    "model_id": "mock-tls-model",
    "provider_id": "tls-openai",
    "provider_model_id": "mock-tls-model",
}


def _ensure_tls_provider(config: dict[str, Any]) -> dict[str, Any]:
    """Find or create the tls-openai inference provider in the config.

    If the provider does not exist, it is added along with the
    mock-tls-model registered resource.

    Parameters:
        config: The Llama Stack configuration dictionary.

    Returns:
        The tls-openai provider configuration dictionary.
    """
    providers = config.setdefault("providers", {})
    inference = providers.setdefault("inference", [])

    for provider in inference:
        if provider.get("provider_id") == "tls-openai":
            return provider

    # Provider not found — add it
    provider = copy.deepcopy(_TLS_PROVIDER_BASE)
    inference.append(provider)

    # Also register the model resource
    resources = config.setdefault("registered_resources", {})
    models = resources.setdefault("models", [])
    if not any(m.get("model_id") == "mock-tls-model" for m in models):
        models.append(copy.deepcopy(_TLS_MODEL_RESOURCE))

    return provider


def _configure_tls(tls_config: dict[str, Any], base_url: Optional[str] = None) -> None:
    """Configure TLS settings for the tls-openai provider.

    Parameters:
        tls_config: The TLS configuration dictionary.
        base_url: Optional base URL override for the provider.
    """
    _backup_llama_config()
    config = _load_llama_config()
    provider = _ensure_tls_provider(config)
    provider.setdefault("config", {}).setdefault("network", {})
    if base_url is not None:
        provider["config"]["base_url"] = base_url
    provider["config"]["network"]["tls"] = tls_config
    _write_config(config, _LLAMA_STACK_CONFIG)


# --- Background Steps ---
# Restart steps ("The original Llama Stack config is restored if modified",
# "Llama Stack is restarted", "Lightspeed Stack is restarted") are defined in
# proxy.py and shared across features by behave.


# --- TLS Configuration Steps ---


@given("Llama Stack is configured with TLS verification disabled")
def configure_tls_verify_false(context: Context) -> None:
    """Configure run.yaml with TLS verify: false."""
    _configure_tls({"verify": False})


@given("Llama Stack is configured with CA certificate verification")
def configure_tls_verify_ca(context: Context) -> None:
    """Configure run.yaml with TLS verify: /certs/ca.crt."""
    _configure_tls({"verify": "/certs/ca.crt", "min_version": "TLSv1.2"})


@given("Llama Stack is configured with TLS verification enabled")
def configure_tls_verify_true(context: Context) -> None:
    """Configure run.yaml with TLS verify: true (fails with self-signed certs)."""
    _configure_tls({"verify": True})


@given("Llama Stack is configured with mutual TLS authentication")
def configure_tls_mtls(context: Context) -> None:
    """Configure run.yaml with mutual TLS (client cert and key)."""
    _configure_tls(
        {
            "verify": "/certs/ca.crt",
            "client_cert": "/certs/client.crt",
            "client_key": "/certs/client.key",
        },
        base_url="https://mock-tls-inference:8444/v1",
    )


@given('Llama Stack is configured with CA certificate path "{path}"')
def configure_tls_verify_ca_path(context: Context, path: str) -> None:
    """Configure run.yaml with TLS verify pointing to a specific CA cert path."""
    _configure_tls({"verify": path})


@given("Llama Stack is configured for mTLS without client certificate")
def configure_mtls_no_client_cert(context: Context) -> None:
    """Configure run.yaml for mTLS port without client cert (should fail)."""
    _configure_tls(
        {"verify": "/certs/ca.crt"},
        base_url="https://mock-tls-inference:8444/v1",
    )


@given("Llama Stack is configured for mTLS with wrong client certificate")
def configure_mtls_wrong_client_cert(context: Context) -> None:
    """Configure run.yaml for mTLS with invalid client cert (CA cert as client cert)."""
    _configure_tls(
        {
            "verify": "/certs/ca.crt",
            "client_cert": "/certs/ca.crt",
            "client_key": "/certs/client.key",
        },
        base_url="https://mock-tls-inference:8444/v1",
    )


@given("Llama Stack is configured for mTLS with untrusted client certificate")
def configure_mtls_untrusted_client_cert(context: Context) -> None:
    """Configure run.yaml for mTLS with client cert from untrusted CA."""
    _configure_tls(
        {
            "verify": "/certs/ca.crt",
            "client_cert": "/certs/untrusted-client.crt",
            "client_key": "/certs/untrusted-client.key",
        },
        base_url="https://mock-tls-inference:8444/v1",
    )


@given("Llama Stack is configured for mTLS with expired client certificate")
def configure_mtls_expired_client_cert(context: Context) -> None:
    """Configure run.yaml for mTLS with an expired client certificate."""
    _configure_tls(
        {
            "verify": "/certs/ca.crt",
            "client_cert": "/certs/expired-client.crt",
            "client_key": "/certs/client.key",
        },
        base_url="https://mock-tls-inference:8444/v1",
    )


@given("Llama Stack is configured with CA certificate and hostname mismatch server")
def configure_tls_hostname_mismatch(context: Context) -> None:
    """Configure run.yaml to connect to hostname-mismatch server (should fail)."""
    _configure_tls(
        {"verify": "/certs/ca.crt"},
        base_url="https://mock-tls-inference:8445/v1",
    )


@given("Llama Stack is configured with mutual TLS and hostname mismatch server")
def configure_mtls_hostname_mismatch(context: Context) -> None:
    """Configure run.yaml for mTLS against hostname-mismatch server (should fail)."""
    _configure_tls(
        {
            "verify": "/certs/ca.crt",
            "client_cert": "/certs/client.crt",
            "client_key": "/certs/client.key",
        },
        base_url="https://mock-tls-inference:8445/v1",
    )


@given(
    'Llama Stack is configured with TLS minimum version "{version}" and hostname mismatch server'
)
def configure_tls_min_version_hostname_mismatch(context: Context, version: str) -> None:
    """Configure run.yaml with TLS min version against hostname-mismatch server."""
    _configure_tls(
        {"verify": "/certs/ca.crt", "min_version": version},
        base_url="https://mock-tls-inference:8445/v1",
    )


@given(
    'Llama Stack is configured with TLS minimum version "{version}" and CA certificate path "{path}"'
)
def configure_tls_min_version_with_ca_path(
    context: Context, version: str, path: str
) -> None:
    """Configure run.yaml with TLS minimum version and a specific CA cert path."""
    _configure_tls({"verify": path, "min_version": version})
