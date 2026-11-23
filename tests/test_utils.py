import pytest

import src.utils as utils
from src.errors import FatalError


def test_die_raises_fatal_error_not_sys_exit():
    with pytest.raises(FatalError, match="boom"):
        utils.die("boom")
