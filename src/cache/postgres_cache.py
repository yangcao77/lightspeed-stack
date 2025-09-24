"""PostgreSQL cache implementation."""

from cache.cache import Cache
from models.cache_entry import CacheEntry
from models.config import PostgreSQLDatabaseConfiguration
from log import get_logger
from utils.connection_decorator import connection

logger = get_logger("cache.postgres_cache")


class PostgresCache(Cache):
    """PostgreSQL cache implementation."""

    def __init__(self, config: PostgreSQLDatabaseConfiguration) -> None:
        """Create a new instance of PostgreSQL cache."""
        self.postgres_config = config

    def connect(self) -> None:
        """Initialize connection to database."""
        logger.info("Connecting to storage")

    def connected(self) -> bool:
        """Check if connection to cache is alive."""
        return True

    def initialize_cache(self) -> None:
        """Initialize cache."""

    @connection
    def get(
        self, user_id: str, conversation_id: str, skip_user_id_check: bool = False
    ) -> list[CacheEntry]:
        """Get the value associated with the given key.

        Args:
            user_id: User identification.
            conversation_id: Conversation ID unique for given user.
            skip_user_id_check: Skip user_id suid check.

        Returns:
            Empty list.
        """
        # just check if user_id and conversation_id are UUIDs
        super().construct_key(user_id, conversation_id, skip_user_id_check)
        return []

    @connection
    def insert_or_append(
        self,
        user_id: str,
        conversation_id: str,
        cache_entry: CacheEntry,
        skip_user_id_check: bool = False,
    ) -> None:
        """Set the value associated with the given key.

        Args:
            user_id: User identification.
            conversation_id: Conversation ID unique for given user.
            cache_entry: The `CacheEntry` object to store.
            skip_user_id_check: Skip user_id suid check.

        """
        # just check if user_id and conversation_id are UUIDs
        super().construct_key(user_id, conversation_id, skip_user_id_check)

    @connection
    def delete(
        self, user_id: str, conversation_id: str, skip_user_id_check: bool = False
    ) -> bool:
        """Delete conversation history for a given user_id and conversation_id.

        Args:
            user_id: User identification.
            conversation_id: Conversation ID unique for given user.
            skip_user_id_check: Skip user_id suid check.

        Returns:
            bool: True in all cases.

        """
        # just check if user_id and conversation_id are UUIDs
        super().construct_key(user_id, conversation_id, skip_user_id_check)
        return True

    @connection
    def list(self, user_id: str, skip_user_id_check: bool = False) -> list[str]:
        """List all conversations for a given user_id.

        Args:
            user_id: User identification.
            skip_user_id_check: Skip user_id suid check.

        Returns:
            An empty list.

        """
        super()._check_user_id(user_id, skip_user_id_check)
        return []

    def ready(self) -> bool:
        """Check if the cache is ready.

        Returns:
            True in all cases.
        """
        return True
