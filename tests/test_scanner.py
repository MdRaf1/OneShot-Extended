import importlib
import sys
from unittest.mock import MagicMock

import src.utils
import src.wifi.scanner
from src.prompts import Prompter
from src.settings import Settings
from src.wifi.scanner import WiFiScanner


class FakePrompter(Prompter):
    def __init__(self, select_index_returns=None):
        self._select_index_queue = (
            list(select_index_returns)
            if isinstance(select_index_returns, list)
            else [select_index_returns]
        )
        self.select_index_calls = 0

    def confirm(self, message: str) -> bool:
        return True

    def confirm_explicit_yes(self, message: str) -> bool:
        return False

    def select_index(self, prompt, count, cancel_tokens=frozenset()):
        self.select_index_calls += 1
        if len(self._select_index_queue) > 1:
            return self._select_index_queue.pop(0)
        return self._select_index_queue[0]


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


def test_prompt_network_returns_selected_bssid_and_info(monkeypatch):
    scanner = WiFiScanner("wlan0", prompter=FakePrompter(select_index_returns=0))
    monkeypatch.setattr(
        scanner, "_iwScanner",
        lambda: {1: {"BSSID": "AA:BB:CC:DD:EE:FF", "ESSID": "x"}},
    )
    bssid, info = scanner.promptNetwork()
    assert bssid == "AA:BB:CC:DD:EE:FF"
    assert info["ESSID"] == "x"


def test_prompt_network_selects_second_of_several_by_0_based_index(monkeypatch):
    scanner = WiFiScanner("wlan0", prompter=FakePrompter(select_index_returns=1))
    monkeypatch.setattr(
        scanner, "_iwScanner",
        lambda: {
            1: {"BSSID": "AA:AA:AA:AA:AA:AA", "ESSID": "first"},
            2: {"BSSID": "BB:BB:BB:BB:BB:BB", "ESSID": "second"},
        },
    )
    bssid, info = scanner.promptNetwork()
    assert bssid == "BB:BB:BB:BB:BB:BB"
    assert info["ESSID"] == "second"


def test_prompt_network_rescans_on_cancel_token(monkeypatch):
    # First select_index call returns None (cancel/refresh token typed);
    # the resulting recursive promptNetwork() call re-scans and this time
    # the (fresh) prompter answer selects the only network.
    scanner = WiFiScanner("wlan0", prompter=FakePrompter(select_index_returns=[None, 0]))
    scan_results = iter([
        {1: {"BSSID": "AA:AA:AA:AA:AA:AA", "ESSID": "first"}},
        {1: {"BSSID": "BB:BB:BB:BB:BB:BB", "ESSID": "second"}},
    ])
    monkeypatch.setattr(scanner, "_iwScanner", lambda: next(scan_results))
    bssid, info = scanner.promptNetwork()
    assert bssid == "BB:BB:BB:BB:BB:BB"
    assert info["ESSID"] == "second"
    assert scanner.prompter.select_index_calls == 2


def test_prompt_network_clears_screen_on_refresh_when_setting_enabled(monkeypatch):
    cleared = []
    monkeypatch.setattr(src.utils, "clearScreen", lambda: cleared.append(True))
    settings = Settings(interface="wlan0", clear=True)
    scanner = WiFiScanner("wlan0", settings=settings, prompter=FakePrompter(select_index_returns=[None, 0]))
    scan_results = iter([
        {1: {"BSSID": "AA:AA:AA:AA:AA:AA", "ESSID": "first"}},
        {1: {"BSSID": "BB:BB:BB:BB:BB:BB", "ESSID": "second"}},
    ])
    monkeypatch.setattr(scanner, "_iwScanner", lambda: next(scan_results))
    scanner.promptNetwork()
    assert cleared == [True]


def test_prompt_network_restale_loop_reprompts_against_original_networks_when_rescan_is_empty(monkeypatch):
    # Preserves a subtle pre-existing quirk: a refresh/cancel whose
    # recursive promptNetwork() finds zero networks (returns None, after
    # logging an error) makes the OUTER loop re-prompt against the
    # original (stale) network list, not return None outright.
    scanner = WiFiScanner("wlan0", prompter=FakePrompter(select_index_returns=[None, 0]))
    scan_results = iter([
        {1: {"BSSID": "AA:AA:AA:AA:AA:AA", "ESSID": "first"}},  # initial scan
        {},  # the rescan triggered by the first (None) answer finds nothing
    ])
    monkeypatch.setattr(scanner, "_iwScanner", lambda: next(scan_results))
    bssid, info = scanner.promptNetwork()
    # second select_index answer (0) is consulted against the ORIGINAL
    # (stale) single-network list from the outer frame, not the empty one.
    assert bssid == "AA:AA:AA:AA:AA:AA"
    assert info["ESSID"] == "first"
