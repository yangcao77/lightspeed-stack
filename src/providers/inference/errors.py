"""Exceptions raised by inference providers."""


class ModelNotAvailableError(Exception):
    """Raised when a requested model is not in the provider catalog."""

    def __init__(self, name: str, model_type: str, provider_id: str) -> None:
        """Initialize with the unavailable model identity.

        Parameters:
            name: Local catalog model name that was requested.
            model_type: Requested model type (llm, embedding, or rerank).
            provider_id: Provider that rejected the request.

        """
        super().__init__(
            f"Model {name!r} of type {model_type!r} is not available "
            f"for provider {provider_id!r}"
        )
        self.name = name
        self.model_type = model_type
        self.provider_id = provider_id
