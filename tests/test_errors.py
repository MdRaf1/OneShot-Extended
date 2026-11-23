import pytest

from src.errors import FatalError


def test_fatal_error_is_exception_with_message():
    with pytest.raises(FatalError, match="boom"):
        raise FatalError("boom")
