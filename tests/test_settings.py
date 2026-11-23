import dataclasses

from src.args import parseArgs
from src.settings import Settings


def test_from_args_mirrors_every_argparse_field():
    ns = parseArgs(["-i", "wlan0", "-B", "-t", "30"])
    s = Settings.from_args(ns)
    assert s.interface == "wlan0"
    assert s.bruteforce is True
    assert s.timeout == 30


def test_from_cli_defaults_match_argparse_defaults():
    s = Settings.from_cli(["-i", "wlan0"])
    assert s.timeout == 60
    assert s.delay == 0
    assert s.vuln_list.endswith("vulnwsc.txt")


def test_settings_field_names_match_args_dest_names():
    ns = parseArgs(["-i", "wlan0"])
    assert set(vars(ns).keys()) == {f.name for f in dataclasses.fields(Settings)}


def test_settings_defaults_without_from_args():
    s = Settings(interface="wlan0")
    assert s.bssid is None
    assert s.null_pin is False
    assert s.timeout == 60
    assert s.verbose is False
