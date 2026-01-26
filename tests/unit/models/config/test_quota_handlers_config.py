"""Unit tests for QuotaHandlersConfiguration model."""

from models.config import QuotaHandlersConfiguration, QuotaSchedulerConfiguration


def test_quota_handlers_configuration() -> None:
    """Test the quota handlers configuration."""
    cfg = QuotaHandlersConfiguration(
        sqlite=None,
        postgres=None,
        limiters=[],
        scheduler=QuotaSchedulerConfiguration(
            database_reconnection_count=10,
            database_reconnection_delay=60,
            period=10,
        ),
        enable_token_history=False,
    )
    assert cfg is not None
    assert cfg.sqlite is None
    assert cfg.postgres is None
    assert cfg.limiters == []
    assert cfg.scheduler is not None
    assert not cfg.enable_token_history
