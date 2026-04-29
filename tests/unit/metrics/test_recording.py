"""Unit tests for Prometheus metric recording helpers."""

from pytest_mock import MockerFixture

from metrics import recording


def test_measure_response_duration_records_timer(mocker: MockerFixture) -> None:
    """Test that response duration measurement uses the path label timer."""
    mock_timer = mocker.MagicMock()
    mock_metric = mocker.patch("metrics.recording.metrics.response_duration_seconds")
    mock_metric.labels.return_value.time.return_value = mock_timer

    with recording.measure_response_duration("/v1/infer"):
        pass

    mock_metric.labels.assert_called_once_with("/v1/infer")
    mock_metric.labels.return_value.time.assert_called_once()
    mock_timer.__enter__.assert_called_once()
    mock_timer.__exit__.assert_called_once()


def test_measure_response_duration_logs_metric_errors(mocker: MockerFixture) -> None:
    """Test that response duration metric errors are logged and request still proceeds."""
    mock_metric = mocker.patch("metrics.recording.metrics.response_duration_seconds")
    mock_metric.labels.return_value.time.side_effect = AttributeError("missing")
    mock_logger = mocker.patch("metrics.recording.logger")

    with recording.measure_response_duration("/v1/infer"):
        pass

    mock_logger.warning.assert_called_once_with(
        "Failed to start response duration metric", exc_info=True
    )


def test_record_rest_api_call_records_counter(mocker: MockerFixture) -> None:
    """Test that REST API call recording increments the labeled counter."""
    mock_metric = mocker.patch("metrics.recording.metrics.rest_api_calls_total")

    recording.record_rest_api_call("/v1/infer", 200)

    mock_metric.labels.assert_called_once_with("/v1/infer", 200)
    mock_metric.labels.return_value.inc.assert_called_once()


def test_record_rest_api_call_logs_metric_errors(mocker: MockerFixture) -> None:
    """Test that REST API call metric errors are logged and swallowed."""
    mock_metric = mocker.patch("metrics.recording.metrics.rest_api_calls_total")
    mock_metric.labels.return_value.inc.side_effect = AttributeError("missing")
    mock_logger = mocker.patch("metrics.recording.logger")

    recording.record_rest_api_call("/v1/infer", 200)

    mock_logger.warning.assert_called_once_with(
        "Failed to update REST API call metric", exc_info=True
    )


def test_record_llm_call_records_counter(mocker: MockerFixture) -> None:
    """Test that LLM call recording increments the provider/model counter."""
    mock_metric = mocker.patch("metrics.recording.metrics.llm_calls_total")

    recording.record_llm_call("provider1", "model1", "/test-endpoint")

    mock_metric.labels.assert_called_once_with("provider1", "model1", "/test-endpoint")
    mock_metric.labels.return_value.inc.assert_called_once()


def test_record_llm_call_logs_metric_errors(mocker: MockerFixture) -> None:
    """Test that LLM call metric errors are logged and swallowed."""
    mock_metric = mocker.patch("metrics.recording.metrics.llm_calls_total")
    mock_metric.labels.return_value.inc.side_effect = AttributeError("missing")
    mock_logger = mocker.patch("metrics.recording.logger")

    recording.record_llm_call("provider1", "model1", "/test-endpoint")

    mock_logger.warning.assert_called_once_with(
        "Failed to update LLM call metric", exc_info=True
    )


def test_record_llm_failure_records_counter(mocker: MockerFixture) -> None:
    """Test that LLM failure recording increments the provider/model counter."""
    mock_metric = mocker.patch("metrics.recording.metrics.llm_calls_failures_total")

    recording.record_llm_failure("provider1", "model1", "/test-endpoint")

    mock_metric.labels.assert_called_once_with("provider1", "model1", "/test-endpoint")
    mock_metric.labels.return_value.inc.assert_called_once()


def test_record_llm_failure_logs_metric_errors(mocker: MockerFixture) -> None:
    """Test that LLM failure metric errors are logged and swallowed."""
    mock_metric = mocker.patch("metrics.recording.metrics.llm_calls_failures_total")
    mock_metric.labels.return_value.inc.side_effect = TypeError("bad")
    mock_logger = mocker.patch("metrics.recording.logger")

    recording.record_llm_failure("provider1", "model1", "/test-endpoint")

    mock_logger.warning.assert_called_once_with(
        "Failed to update LLM failure metric", exc_info=True
    )


def test_record_llm_validation_error_records_counter(mocker: MockerFixture) -> None:
    """Test that validation error recording increments the counter."""
    mock_metric = mocker.patch(
        "metrics.recording.metrics.llm_calls_validation_errors_total"
    )

    recording.record_llm_validation_error("/test-endpoint")

    mock_metric.labels.assert_called_once_with("/test-endpoint")
    mock_metric.labels.return_value.inc.assert_called_once()


def test_record_llm_validation_error_logs_metric_errors(
    mocker: MockerFixture,
) -> None:
    """Test that validation error metric failures are logged and swallowed."""
    mock_metric = mocker.patch(
        "metrics.recording.metrics.llm_calls_validation_errors_total"
    )
    mock_metric.labels.return_value.inc.side_effect = ValueError("bad")
    mock_logger = mocker.patch("metrics.recording.logger")

    recording.record_llm_validation_error("/test-endpoint")

    mock_logger.warning.assert_called_once_with(
        "Failed to update LLM validation error metric", exc_info=True
    )


def test_record_llm_token_usage_records_counters(mocker: MockerFixture) -> None:
    """Test that token usage recording increments sent and received counters."""
    mock_sent = mocker.patch("metrics.recording.metrics.llm_token_sent_total")
    mock_received = mocker.patch("metrics.recording.metrics.llm_token_received_total")

    recording.record_llm_token_usage("provider1", "model1", 100, 50, "/test-endpoint")

    mock_sent.labels.assert_called_once_with("provider1", "model1", "/test-endpoint")
    mock_sent.labels.return_value.inc.assert_called_once_with(100)
    mock_received.labels.assert_called_once_with(
        "provider1", "model1", "/test-endpoint"
    )
    mock_received.labels.return_value.inc.assert_called_once_with(50)


def test_record_llm_token_usage_logs_metric_errors(mocker: MockerFixture) -> None:
    """Test that token metric failures are logged and swallowed."""
    mock_sent = mocker.patch("metrics.recording.metrics.llm_token_sent_total")
    mock_sent.labels.return_value.inc.side_effect = ValueError("bad")
    mocker.patch("metrics.recording.metrics.llm_token_received_total")
    mock_logger = mocker.patch("metrics.recording.logger")

    recording.record_llm_token_usage("provider1", "model1", 100, 50, "/test-endpoint")

    mock_logger.warning.assert_called_once_with(
        "Failed to update token metrics", exc_info=True
    )
