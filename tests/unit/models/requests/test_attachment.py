"""Unit tests for Attachment model."""

from models.requests import Attachment


class TestAttachment:
    """Test cases for the Attachment model."""

    def test_constructor(self) -> None:
        """Test the Attachment with custom values."""
        a = Attachment(
            attachment_type="configuration",
            content_type="application/yaml",
            content="kind: Pod\n metadata:\n name:    private-reg",
        )
        assert a.attachment_type == "configuration"
        assert a.content_type == "application/yaml"
        assert a.content == "kind: Pod\n metadata:\n name:    private-reg"

    def test_constructor_unknown_attachment_type(self) -> None:
        """Test the Attachment with custom values.

        Verify that an Attachment retains the provided attachment_type,
        content_type, and content when given an unrecognized content type.

        Asserts that `attachment_type` is "configuration", `content_type` is
        "unknown/type", and `content` matches the supplied multi-line YAML
        string.
        """
        # for now we allow any content type
        a = Attachment(
            attachment_type="configuration",
            content_type="unknown/type",
            content="kind: Pod\n metadata:\n name:    private-reg",
        )
        assert a.attachment_type == "configuration"
        assert a.content_type == "unknown/type"
        assert a.content == "kind: Pod\n metadata:\n name:    private-reg"
