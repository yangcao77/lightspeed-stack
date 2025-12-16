"""Unit tests for functions defined in metrics/utils.py"""

from pytest_mock import MockerFixture
from metrics.utils import setup_model_metrics, update_llm_token_count_from_turn


async def test_setup_model_metrics(mocker: MockerFixture) -> None:
    """Test the setup_model_metrics function."""

    # Mock the LlamaStackAsLibraryClient
    mock_client = mocker.patch(
        "client.AsyncLlamaStackClientHolder.get_client"
    ).return_value
    # Make sure the client is an AsyncMock for async methods
    mock_client = mocker.AsyncMock()
    mocker.patch(
        "client.AsyncLlamaStackClientHolder.get_client", return_value=mock_client
    )
    mocker.patch(
        "metrics.utils.configuration.inference.default_provider",
        "default_provider",
    )
    mocker.patch(
        "metrics.utils.configuration.inference.default_model",
        "default_model",
    )

    mock_metric = mocker.patch("metrics.provider_model_configuration")
    # Mock a model that is the default
    model_default = mocker.Mock(
        provider_id="default_provider",
        identifier="default_model",
        model_type="llm",
    )
    # Mock a model that is not the default
    model_0 = mocker.Mock(
        provider_id="test_provider-0",
        identifier="test_model-0",
        model_type="llm",
    )
    # Mock a second model which is not default
    model_1 = mocker.Mock(
        provider_id="test_provider-1",
        identifier="test_model-1",
        model_type="llm",
    )
    # Mock a model that is not an LLM type, should be ignored
    not_llm_model = mocker.Mock(
        provider_id="not-llm-provider",
        identifier="not-llm-model",
        model_type="not-llm",
    )

    # Mock the list of models returned by the client
    mock_client.models.list.return_value = [
        model_0,
        model_default,
        not_llm_model,
        model_1,
    ]

    await setup_model_metrics()

    # Check that the provider_model_configuration metric was set correctly
    # The default model should have a value of 1, others should be 0
    assert mock_metric.labels.call_count == 3
    mock_metric.assert_has_calls(
        [
            mocker.call.labels("test_provider-0", "test_model-0"),
            mocker.call.labels().set(0),
            mocker.call.labels("default_provider", "default_model"),
            mocker.call.labels().set(1),
            mocker.call.labels("test_provider-1", "test_model-1"),
            mocker.call.labels().set(0),
        ],
        any_order=False,  # Order matters here
    )


def test_update_llm_token_count_from_turn(mocker: MockerFixture) -> None:
    """Test the update_llm_token_count_from_turn function.

    Verifies that update_llm_token_count_from_turn increments LLM token metrics
    for received and sent tokens using the token counts produced by the
    formatter.

    Sets up a mock formatter that returns 3 tokens for the output and 2 tokens
    for the input, then asserts that:
    - llm_token_received_total is labeled with the provider and model and incremented by 3.
    - llm_token_sent_total is labeled with the provider and model and incremented by 2.
    """
    mocker.patch("metrics.utils.Tokenizer.get_instance")
    mock_formatter_class = mocker.patch("metrics.utils.ChatFormat")
    mock_formatter = mocker.Mock()
    mock_formatter_class.return_value = mock_formatter

    mock_received_metric = mocker.patch(
        "metrics.utils.metrics.llm_token_received_total"
    )
    mock_sent_metric = mocker.patch("metrics.utils.metrics.llm_token_sent_total")

    mock_turn = mocker.Mock()
    # turn.output_message should satisfy the type RawMessage
    mock_turn.output_message = {"role": "assistant", "content": "test response"}
    # turn.input_messages should satisfy the type list[RawMessage]
    mock_turn.input_messages = [{"role": "user", "content": "test input"}]

    # Mock the encoded results with tokens
    mock_encoded_output = mocker.Mock()
    mock_encoded_output.tokens = ["token1", "token2", "token3"]  # 3 tokens
    mock_encoded_input = mocker.Mock()
    mock_encoded_input.tokens = ["token1", "token2"]  # 2 tokens
    mock_formatter.encode_dialog_prompt.side_effect = [
        mock_encoded_output,
        mock_encoded_input,
    ]

    test_model = "test_model"
    test_provider = "test_provider"
    test_system_prompt = "test system prompt"

    update_llm_token_count_from_turn(
        mock_turn, test_model, test_provider, test_system_prompt
    )

    # Verify that llm_token_received_total.labels() was called with correct metrics
    mock_received_metric.labels.assert_called_once_with(test_provider, test_model)
    mock_received_metric.labels().inc.assert_called_once_with(
        3
    )  # token count from output

    # Verify that llm_token_sent_total.labels() was called with correct metrics
    mock_sent_metric.labels.assert_called_once_with(test_provider, test_model)
    mock_sent_metric.labels().inc.assert_called_once_with(2)  # token count from input
