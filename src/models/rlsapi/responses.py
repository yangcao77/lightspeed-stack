"""Models for rlsapi v1 REST API responses."""

from typing import Optional
from pydantic import Field

from models.config import ConfigurationBase
from models.responses import AbstractSuccessfulResponse


class RlsapiV1InferData(ConfigurationBase):
    """Response data for rlsapi v1 /infer endpoint.

    Attributes:
        text: The generated response text.
        request_id: Unique identifier for the request.
    """

    text: str = Field(
        ...,
        description="Generated response text",
        examples=["To list files in Linux, use the `ls` command."],
    )
    request_id: Optional[str] = Field(
        None,
        description="Unique request identifier",
        examples=["01JDKR8N7QW9ZMXVGK3PB5TQWZ"],
    )


class RlsapiV1InferResponse(AbstractSuccessfulResponse):
    """RHEL Lightspeed rlsapi v1 /infer response.

    Attributes:
        data: Response data containing text and request_id.
    """

    data: RlsapiV1InferData = Field(
        ...,
        description="Response data containing text and request_id",
    )

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "data": {
                        "text": "To list files in Linux, use the `ls` command.",
                        "request_id": "01JDKR8N7QW9ZMXVGK3PB5TQWZ",
                    }
                }
            ]
        },
    }
