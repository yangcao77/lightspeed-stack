"""Cache factory class."""

import constants
from models.config import ConversationCacheConfiguration
from cache.cache import Cache
from cache.noop_cache import NoopCache
from log import get_logger

logger = get_logger("cache.cache_factory")


# pylint: disable=R0903
class CacheFactory:
    """Cache factory class."""

    @staticmethod
    def conversation_cache(config: ConversationCacheConfiguration) -> Cache:
        """Create an instance of Cache based on loaded configuration.

        Returns:
            An instance of `Cache` (either `SQLiteCache`, `PostgresCache` or `InMemoryCache`).
        """
        logger.info("Creating cache instance of type %s", config.type)
        match config.type:
            case constants.CACHE_TYPE_NOOP:
                return NoopCache()
            case constants.CACHE_TYPE_MEMORY:
                return NoopCache()
            case constants.CACHE_TYPE_SQLITE:
                return NoopCache()
            case constants.CACHE_TYPE_POSTGRES:
                return NoopCache()
            case _:
                raise ValueError(
                    f"Invalid cache type: {config.type}. "
                    f"Use '{constants.CACHE_TYPE_POSTGRES}' '{constants.CACHE_TYPE_SQLITE}' or "
                    f"'{constants.CACHE_TYPE_MEMORY}' options."
                )
