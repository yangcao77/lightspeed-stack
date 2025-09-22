"""Unit tests for CacheFactory class."""

import pytest

from constants import CACHE_TYPE_NOOP
from models.config import ConversationCacheConfiguration
from cache.cache_factory import CacheFactory
from cache.noop_cache import NoopCache


@pytest.fixture(scope="module", name="noop_cache_config_fixture")
def noop_cache_config():
    """Fixture containing initialized instance of ConversationCacheConfiguration."""
    return ConversationCacheConfiguration(type=CACHE_TYPE_NOOP)


@pytest.fixture(scope="module", name="invalid_cache_type_config_fixture")
def invalid_cache_type_config():
    """Fixture containing instance of ConversationCacheConfiguration with improper settings."""
    c = ConversationCacheConfiguration()
    c.type = "foo bar baz"
    return c


def test_conversation_cache_noop(noop_cache_config_fixture):
    """Check if NoopCache is returned by factory with proper configuration."""
    cache = CacheFactory.conversation_cache(noop_cache_config_fixture)
    assert cache is not None
    # check if the object has the right type
    assert isinstance(cache, NoopCache)


def test_conversation_cache_wrong_cache(invalid_cache_type_config_fixture):
    """Check if wrong cache configuration is detected properly."""
    with pytest.raises(ValueError, match="Invalid cache type"):
        CacheFactory.conversation_cache(invalid_cache_type_config_fixture)
