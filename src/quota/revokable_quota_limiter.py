"""Simple quota limiter where quota can be revoked."""

from datetime import datetime

from models.config import QuotaHandlersConfiguration
from log import get_logger
from utils.connection_decorator import connection
from quota.quota_exceed_error import QuotaExceedError
from quota.quota_limiter import QuotaLimiter
from quota.sql import (
    CREATE_QUOTA_TABLE_PG,
    CREATE_QUOTA_TABLE_SQLITE,
    UPDATE_AVAILABLE_QUOTA_PG,
    UPDATE_AVAILABLE_QUOTA_SQLITE,
    SELECT_QUOTA_PG,
    SELECT_QUOTA_SQLITE,
    SET_AVAILABLE_QUOTA_PG,
    SET_AVAILABLE_QUOTA_SQLITE,
    INIT_QUOTA_PG,
    INIT_QUOTA_SQLITE,
)

logger = get_logger(__name__)


class RevokableQuotaLimiter(QuotaLimiter):
    """Simple quota limiter where quota can be revoked."""

    def __init__(
        self,
        configuration: QuotaHandlersConfiguration,
        initial_quota: int,
        increase_by: int,
        subject_type: str,
    ) -> None:
        """Initialize quota limiter."""
        self.subject_type = subject_type
        self.initial_quota = initial_quota
        self.increase_by = increase_by
        self.sqlite_connection_config = configuration.sqlite
        self.postgres_connection_config = configuration.postgres

    @connection
    def available_quota(self, subject_id: str = "") -> int:
        """Retrieve available quota for given subject."""
        if self.subject_type == "c":
            subject_id = ""
        if self.sqlite_connection_config is not None:
            return self._read_available_quota(SELECT_QUOTA_SQLITE, subject_id)
        if self.postgres_connection_config is not None:
            return self._read_available_quota(SELECT_QUOTA_PG, subject_id)
        # default value is used only if quota limiter database is not setup
        return 0

    def _read_available_quota(self, query_statement: str, subject_id: str) -> int:
        """Read available quota from selected database."""
        # it is not possible to use context manager there, because SQLite does
        # not support it
        cursor = self.connection.cursor()
        cursor.execute(
            query_statement,
            (subject_id, self.subject_type),
        )
        value = cursor.fetchone()
        if value is None:
            self._init_quota(subject_id)
            return self.initial_quota
        cursor.close()
        return value[0]

    @connection
    def revoke_quota(self, subject_id: str = "") -> None:
        """Revoke quota for given subject."""
        if self.subject_type == "c":
            subject_id = ""

        if self.postgres_connection_config is not None:
            self._revoke_quota(SET_AVAILABLE_QUOTA_PG, subject_id)
            return
        if self.sqlite_connection_config is not None:
            self._revoke_quota(SET_AVAILABLE_QUOTA_SQLITE, subject_id)
            return

    def _revoke_quota(self, set_statement: str, subject_id: str) -> None:
        """Revoke quota in given database."""
        # timestamp to be used
        revoked_at = datetime.now()

        cursor = self.connection.cursor()
        cursor.execute(
            set_statement,
            (self.initial_quota, revoked_at, subject_id, self.subject_type),
        )
        self.connection.commit()
        cursor.close()

    @connection
    def increase_quota(self, subject_id: str = "") -> None:
        """Increase quota for given subject."""
        if self.subject_type == "c":
            subject_id = ""

        if self.postgres_connection_config is not None:
            self._increase_quota(UPDATE_AVAILABLE_QUOTA_PG, subject_id)
            return

        if self.sqlite_connection_config is not None:
            self._increase_quota(UPDATE_AVAILABLE_QUOTA_SQLITE, subject_id)
            return

    def _increase_quota(self, set_statement: str, subject_id: str) -> None:
        """Increase quota in given database."""
        # timestamp to be used
        updated_at = datetime.now()

        cursor = self.connection.cursor()
        cursor.execute(
            set_statement,
            (self.increase_by, updated_at, subject_id, self.subject_type),
        )
        self.connection.commit()

    def ensure_available_quota(self, subject_id: str = "") -> None:
        """Ensure that there's avaiable quota left."""
        if self.subject_type == "c":
            subject_id = ""
        available = self.available_quota(subject_id)
        logger.info("Available quota for subject %s is %d", subject_id, available)
        # check if ID still have available tokens to be consumed
        if available <= 0:
            e = QuotaExceedError(subject_id, self.subject_type, available)
            logger.exception("Quota exceed: %s", e)
            raise e

    @connection
    def consume_tokens(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        subject_id: str = "",
    ) -> None:
        """Consume tokens by given subject."""
        if self.subject_type == "c":
            subject_id = ""
        logger.info(
            "Consuming %d input and %d output tokens for subject %s",
            input_tokens,
            output_tokens,
            subject_id,
        )

        if self.sqlite_connection_config is not None:
            self._consume_tokens(
                UPDATE_AVAILABLE_QUOTA_SQLITE, input_tokens, output_tokens, subject_id
            )
            return

        if self.postgres_connection_config is not None:
            self._consume_tokens(
                UPDATE_AVAILABLE_QUOTA_PG, input_tokens, output_tokens, subject_id
            )
            return

    def _consume_tokens(
        self,
        update_statement: str,
        input_tokens: int,
        output_tokens: int,
        subject_id: str,
    ) -> None:
        """Consume tokens from selected database."""
        # timestamp to be used
        updated_at = datetime.now()

        to_be_consumed = input_tokens + output_tokens

        cursor = self.connection.cursor()
        cursor.execute(
            update_statement,
            (-to_be_consumed, updated_at, subject_id, self.subject_type),
        )
        self.connection.commit()
        cursor.close()

    def _initialize_tables(self) -> None:
        """Initialize tables used by quota limiter."""
        logger.info("Initializing tables for quota limiter")
        cursor = self.connection.cursor()
        if self.sqlite_connection_config is not None:
            cursor.execute(CREATE_QUOTA_TABLE_SQLITE)
        elif self.postgres_connection_config is not None:
            cursor.execute(CREATE_QUOTA_TABLE_PG)
        cursor.close()
        self.connection.commit()

    def _init_quota(self, subject_id: str = "") -> None:
        """Initialize quota for given ID."""
        # timestamp to be used
        revoked_at = datetime.now()

        if self.sqlite_connection_config is not None:
            cursor = self.connection.cursor()
            cursor.execute(
                INIT_QUOTA_SQLITE,
                (
                    subject_id,
                    self.subject_type,
                    self.initial_quota,
                    self.initial_quota,
                    revoked_at,
                ),
            )
            cursor.close()
            self.connection.commit()
        if self.postgres_connection_config is not None:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    INIT_QUOTA_PG,
                    (
                        subject_id,
                        self.subject_type,
                        self.initial_quota,
                        self.initial_quota,
                        revoked_at,
                    ),
                )
                self.connection.commit()
