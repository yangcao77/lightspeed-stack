"""Unit tests for functions defined in src/lightspeed_stack.py."""

from lightspeed_stack import create_argument_parser


def test_create_argument_parser() -> None:
    """Test for create_argument_parser function.

    Verify that create_argument_parser returns a parser instance.

    Asserts the factory function returns a non-None argument parser
    object and does not exercise parsing behavior.
    """
    arg_parser = create_argument_parser()
    # nothing more to test w/o actual parsing is done
    assert arg_parser is not None
