"""Unit tests for quota limiter factory class."""

import pytest
from pytest_mock import MockerFixture

from models.config import (
    QuotaLimiterConfiguration,
    PostgreSQLDatabaseConfiguration,
    SQLiteDatabaseConfiguration,
    QuotaHandlersConfiguration,
)
from quota.cluster_quota_limiter import ClusterQuotaLimiter
from quota.quota_limiter_factory import QuotaLimiterFactory
from quota.user_quota_limiter import UserQuotaLimiter


def test_quota_limiters_no_storage() -> None:
    """Test the quota limiters creating when no storage is configured."""
    configuration = QuotaHandlersConfiguration()
    configuration.sqlite = None
    configuration.postgres = None
    configuration.limiters = []
    limiters = QuotaLimiterFactory.quota_limiters(configuration)
    assert not limiters


def test_quota_limiters_no_limiters_pg_storage() -> None:
    """Test the quota limiters creating when no limiters are specified."""
    configuration = QuotaHandlersConfiguration()
    configuration.postgres = PostgreSQLDatabaseConfiguration(
        db="test",
        user="user",
        password="password",
        namespace="foo",
    )
    configuration.limiters = None
    limiters = QuotaLimiterFactory.quota_limiters(configuration)
    assert not limiters


def test_quota_limiters_no_limiters_sqlite_storage() -> None:
    """Test the quota limiters creating when no limiters are specified."""
    configuration = QuotaHandlersConfiguration()
    configuration.sqlite = SQLiteDatabaseConfiguration(
        db_path="/foo/bar",
    )
    configuration.limiters = None
    limiters = QuotaLimiterFactory.quota_limiters(configuration)
    assert not limiters


def test_quota_limiters_empty_limiters_pg_storage() -> None:
    """Test the quota limiters creating when no limiters are specified."""
    configuration = QuotaHandlersConfiguration()
    configuration.postgres = PostgreSQLDatabaseConfiguration(
        db="test",
        user="user",
        password="password",
        namespace="foo",
    )
    configuration.limiters = []
    limiters = QuotaLimiterFactory.quota_limiters(configuration)
    assert not limiters


def test_quota_limiters_empty_limiters_sqlite_storage() -> None:
    """Test the quota limiters creating when no limiters are specified."""
    configuration = QuotaHandlersConfiguration()
    configuration.sqlite = SQLiteDatabaseConfiguration(
        db_path="/foo/bar",
    )
    configuration.limiters = []
    limiters = QuotaLimiterFactory.quota_limiters(configuration)
    assert not limiters


def test_quota_limiters_user_quota_limiter_postgres_storage(
    mocker: MockerFixture,
) -> None:
    """Test the quota limiters creating when one limiter is specified."""
    configuration = QuotaHandlersConfiguration()
    configuration.postgres = PostgreSQLDatabaseConfiguration(
        db="test",
        user="user",
        password="password",
        namespace="foo",
    )
    configuration.limiters = [
        QuotaLimiterConfiguration(
            type="user_limiter",
            name="foo",
            initial_quota=100,
            quota_increase=1,
            period="5 days",
        ),
    ]
    # do not use connection to real PostgreSQL instance
    mocker.patch("psycopg2.connect")
    limiters = QuotaLimiterFactory.quota_limiters(configuration)
    assert len(limiters) == 1
    assert isinstance(limiters[0], UserQuotaLimiter)


def test_quota_limiters_user_quota_limiter_sqlite_storage() -> None:
    """Test the quota limiters creating when one limiter is specified."""
    configuration = QuotaHandlersConfiguration()
    configuration.sqlite = SQLiteDatabaseConfiguration(
        db_path=":memory:",
    )
    configuration.limiters = [
        QuotaLimiterConfiguration(
            type="user_limiter",
            name="foo",
            initial_quota=100,
            quota_increase=1,
            period="5 days",
        ),
    ]
    limiters = QuotaLimiterFactory.quota_limiters(configuration)
    assert len(limiters) == 1
    assert isinstance(limiters[0], UserQuotaLimiter)


def test_quota_limiters_cluster_quota_limiter_postgres_storage(
    mocker: MockerFixture,
) -> None:
    """Test the quota limiters creating when one limiter is specified."""
    configuration = QuotaHandlersConfiguration()
    configuration.postgres = PostgreSQLDatabaseConfiguration(
        db="test",
        user="user",
        password="password",
        namespace="foo",
    )
    configuration.limiters = [
        QuotaLimiterConfiguration(
            type="cluster_limiter",
            name="foo",
            initial_quota=100,
            quota_increase=1,
            period="5 days",
        ),
    ]
    # do not use connection to real PostgreSQL instance
    mocker.patch("psycopg2.connect")
    limiters = QuotaLimiterFactory.quota_limiters(configuration)
    assert len(limiters) == 1
    assert isinstance(limiters[0], ClusterQuotaLimiter)


def test_quota_limiters_cluster_quota_limiter_sqlite_storage() -> None:
    """Test the quota limiters creating when one limiter is specified."""
    configuration = QuotaHandlersConfiguration()
    configuration.sqlite = SQLiteDatabaseConfiguration(
        db_path=":memory:",
    )
    configuration.limiters = [
        QuotaLimiterConfiguration(
            type="cluster_limiter",
            name="foo",
            initial_quota=100,
            quota_increase=1,
            period="5 days",
        ),
    ]
    limiters = QuotaLimiterFactory.quota_limiters(configuration)
    assert len(limiters) == 1
    assert isinstance(limiters[0], ClusterQuotaLimiter)


def test_quota_limiters_two_limiters(mocker: MockerFixture) -> None:
    """Test the quota limiters creating when two limiters are specified."""
    configuration = QuotaHandlersConfiguration()
    configuration.postgres = PostgreSQLDatabaseConfiguration(
        db="test",
        user="user",
        password="password",
        namespace="foo",
    )
    configuration.limiters = [
        QuotaLimiterConfiguration(
            type="user_limiter",
            name="foo",
            initial_quota=100,
            quota_increase=1,
            period="5 days",
        ),
        QuotaLimiterConfiguration(
            type="cluster_limiter",
            name="foo",
            initial_quota=100,
            quota_increase=1,
            period="5 days",
        ),
    ]
    # do not use connection to real PostgreSQL instance
    mocker.patch("psycopg2.connect")
    limiters = QuotaLimiterFactory.quota_limiters(configuration)
    assert len(limiters) == 2
    assert isinstance(limiters[0], UserQuotaLimiter)
    assert isinstance(limiters[1], ClusterQuotaLimiter)


def test_quota_limiters_invalid_limiter_type(mocker: MockerFixture) -> None:
    """Test the quota limiters creating when invalid limiter type is specified."""
    configuration = QuotaHandlersConfiguration()
    configuration.postgres = PostgreSQLDatabaseConfiguration(
        db="test",
        user="user",
        password="password",
        namespace="foo",
    )
    configuration.limiters = [
        QuotaLimiterConfiguration(
            type="cluster_limiter",
            name="foo",
            initial_quota=100,
            quota_increase=1,
            period="5 days",
        ),
    ]
    configuration.limiters[0].type = "foo"
    # do not use connection to real PostgreSQL instance
    mocker.patch("psycopg2.connect")
    with pytest.raises(ValueError, match="Invalid limiter type: foo"):
        _ = QuotaLimiterFactory.quota_limiters(configuration)
