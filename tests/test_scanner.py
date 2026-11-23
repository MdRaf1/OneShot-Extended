import importlib
import sys
from unittest.mock import MagicMock

import src.wifi.scanner
from src.settings import Settings
from src.wifi.scanner import WiFiScanner


def test_importing_scanner_does_not_parse_sys_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest", "--some-unrelated-flag"])
    importlib.reload(src.wifi.scanner)  # must not raise SystemExit


def _canned_iw_scan_output():
    # Two WPS-capable BSS entries, strongest signal (AA...) first, matching
    # the real `iw dev <iface> scan` output format _iwScanner()'s regexes
    # expect (nested fields indented with an embedded tab before "* ...").
    return "\n".join([
        "BSS aa:aa:aa:aa:aa:aa(on wlan0)",
        "\tSSID: first",
        "\tsignal: -40.00 dBm",
        "\tcapability: ESS Privacy (0x0011)",
        "\tWPS:\t * Version: 1.0",
        "BSS bb:bb:bb:bb:bb:bb(on wlan0)",
        "\tSSID: second",
        "\tsignal: -60.00 dBm",
        "\tcapability: ESS Privacy (0x0011)",
        "\tWPS:\t * Version: 1.0",
    ])


def test_reverse_scan_setting_reverses_printed_network_order(monkeypatch, capsys):
    settings = Settings(interface="wlan0", reverse_scan=True)
    scanner = WiFiScanner("wlan0", settings=settings)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout=_canned_iw_scan_output(), returncode=0),
    )
    scanner._iwScanner()  # pylint: disable=protected-access
    out = capsys.readouterr().out
    # strongest signal (AA...) sorts first by default; reverse_scan flips
    # the *printed* order only (the returned dict's own numbering is
    # unaffected — reverse_scan is a display-only convenience).
    assert out.index("BB:BB:BB:BB:BB:BB") < out.index("AA:AA:AA:AA:AA:AA")


def test_forward_scan_setting_keeps_printed_network_order(monkeypatch, capsys):
    settings = Settings(interface="wlan0", reverse_scan=False)
    scanner = WiFiScanner("wlan0", settings=settings)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout=_canned_iw_scan_output(), returncode=0),
    )
    scanner._iwScanner()  # pylint: disable=protected-access
    out = capsys.readouterr().out
    assert out.index("AA:AA:AA:AA:AA:AA") < out.index("BB:BB:BB:BB:BB:BB")


def test_verbose_setting_prints_raw_scan_output(monkeypatch, capsys):
    settings = Settings(interface="wlan0", verbose=True)
    scanner = WiFiScanner("wlan0", settings=settings)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout=_canned_iw_scan_output(), returncode=0),
    )
    scanner._iwScanner()  # pylint: disable=protected-access
    out = capsys.readouterr().out
    assert "BSS aa:aa:aa:aa:aa:aa(on wlan0)" in out


def test_non_verbose_setting_does_not_print_raw_scan_output(monkeypatch, capsys):
    settings = Settings(interface="wlan0", verbose=False)
    scanner = WiFiScanner("wlan0", settings=settings)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: MagicMock(stdout=_canned_iw_scan_output(), returncode=0),
    )
    scanner._iwScanner()  # pylint: disable=protected-access
    out = capsys.readouterr().out
    assert "BSS aa:aa:aa:aa:aa:aa(on wlan0)" not in out


def test_verbose_setting_flows_through_to_scanner_instance():
    settings = Settings(interface="wlan0", verbose=True)
    scanner = WiFiScanner("wlan0", settings=settings)
    assert scanner.settings.verbose is True


def test_clear_setting_flows_through_to_scanner_instance():
    settings = Settings(interface="wlan0", clear=True)
    scanner = WiFiScanner("wlan0", settings=settings)
    assert scanner.settings.clear is True


def test_default_settings_constructed_when_none_given():
    scanner = WiFiScanner("wlan0")
    assert scanner.settings.interface == "wlan0"
    assert scanner.settings.reverse_scan is False
