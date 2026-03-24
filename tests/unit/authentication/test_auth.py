"""Unit tests for functions defined in authentication/__init__.py"""

from authentication import get_auth_dependency, k8s, noop, noop_with_token
from configuration import configuration
from constants import AUTH_MOD_K8S, AUTH_MOD_NOOP, AUTH_MOD_NOOP_WITH_TOKEN


def test_get_auth_dependency_noop() -> None:
    """Test getting Noop authentication dependency."""
    assert configuration.authentication_configuration is not None
    configuration.authentication_configuration.module = AUTH_MOD_NOOP
    auth_dependency = get_auth_dependency()
    assert isinstance(auth_dependency, noop.NoopAuthDependency)


def test_get_auth_dependency_noop_with_token() -> None:
    """Test getting Noop with token authentication dependency."""
    assert configuration.authentication_configuration is not None
    configuration.authentication_configuration.module = AUTH_MOD_NOOP_WITH_TOKEN
    auth_dependency = get_auth_dependency()
    assert isinstance(auth_dependency, noop_with_token.NoopWithTokenAuthDependency)


def test_get_auth_dependency_k8s() -> None:
    """Test getting K8s authentication dependency."""
    assert configuration.authentication_configuration is not None
    configuration.authentication_configuration.module = AUTH_MOD_K8S
    auth_dependency = get_auth_dependency()
    assert isinstance(auth_dependency, k8s.K8SAuthDependency)
