"""Unit tests for PostgreSQL connection handler."""

import pytest
from psycopg2 import OperationalError
from pydantic import SecretStr
from pytest_mock import MockerFixture

import constants
from models.config import PostgreSQLDatabaseConfiguration
from quota.connect_pg import connect_pg


def test_connect_pg_when_connection_established(mocker: MockerFixture) -> None:
    """Test the connection to PostgreSQL database."""
    # any correct PostgreSQL configuration can be used
    configuration = PostgreSQLDatabaseConfiguration(
        db="db",
        user="user",
        password=SecretStr("password"),
        namespace="foo",
        host="host",
        port=1234,
        ssl_mode=constants.POSTGRES_DEFAULT_SSL_MODE,
        gss_encmode=constants.POSTGRES_DEFAULT_GSS_ENCMODE,
        ca_cert_path=None,
    )

    # do not use connection to real PostgreSQL instance
    mocker.patch("psycopg2.connect")

    # connection should be established
    connection = connect_pg(configuration)
    assert connection is not None


def test_connect_pg_when_connection_error(mocker: MockerFixture) -> None:
    """Test the connection to PostgreSQL database."""
    # any correct PostgreSQL configuration can be used
    configuration = PostgreSQLDatabaseConfiguration(
        host="foo",
        db="db",
        user="user",
        password=SecretStr("password"),
        namespace="foo",
        port=1234,
        ssl_mode=constants.POSTGRES_DEFAULT_SSL_MODE,
        gss_encmode=constants.POSTGRES_DEFAULT_GSS_ENCMODE,
        ca_cert_path=None,
    )

    # do not use connection to real PostgreSQL instance
    mocker.patch("psycopg2.connect", side_effect=OperationalError("ERROR"))
    with pytest.raises(OperationalError, match="ERROR"):
        # connection should not be established
        _ = connect_pg(configuration)
