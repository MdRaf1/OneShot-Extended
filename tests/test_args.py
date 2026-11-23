import pytest

from src.args import parseArgs


def test_parse_args_accepts_explicit_argv():
    ns = parseArgs(["-i", "wlan0", "-P"])
    assert ns.interface == "wlan0"
    assert ns.pixie_dust is True


def test_parse_args_still_errors_on_missing_required_interface():
    with pytest.raises(SystemExit):
        parseArgs(["-P"])
