from unittest.mock import MagicMock

from src import logger
from src.events import Event, EventBus
from src.prompts import Prompter
from src.settings import Settings
from src.wps.connection import Initialize


class FakePrompter(Prompter):
    def __init__(self, confirm_returns=True):
        self.confirm_returns = confirm_returns
        self.confirm_called = False
        self.confirm_message = None

    def confirm(self, message: str) -> bool:
        self.confirm_called = True
        self.confirm_message = message
        return self.confirm_returns

    def confirm_explicit_yes(self, message: str) -> bool:
        return False

    def select_index(self, prompt, count, cancel_tokens=frozenset()):
        return 0


def _make_initialize_with_fakes(monkeypatch, settings=None, prompter=None):
    monkeypatch.setattr(Initialize, "_initWpaSupplicant", lambda self: None)
    conn = Initialize("wlan0", settings=settings, prompter=prompter)
    conn.WPAS = MagicMock()
    # No real _wpsConnection (no real wpa_supplicant socket) — the status
    # just stays unset ('' not GOT_PSK), which is what we need to reach
    # the pin-resolution step without going further.
    monkeypatch.setattr(conn, "_wpsConnection", lambda *a, **kw: False)
    return conn


def test_pixie_reuse_confirm_uses_injected_prompter(tmp_path, monkeypatch):
    monkeypatch.setattr("src.utils.PIXIEWPS_DIR", str(tmp_path) + "/")
    bssid = "AA:BB:CC:DD:EE:FF"
    (tmp_path / "AABBCCDDEEFF.run").write_text("12345670")

    fake = FakePrompter(confirm_returns=True)
    settings = Settings(interface="wlan0", pixie_dust=True)
    conn = _make_initialize_with_fakes(monkeypatch, settings=settings, prompter=fake)

    conn.singleConnection(bssid=bssid)

    assert fake.confirm_called
    assert "12345670" in fake.confirm_message


def test_pixie_reuse_declined_falls_back_to_generator(tmp_path, monkeypatch):
    monkeypatch.setattr("src.utils.PIXIEWPS_DIR", str(tmp_path) + "/")
    # This BSSID matches the 'pin24' vendor algorithm (see Task 7's golden
    # cases), which generator.getLikely() will return deterministically —
    # distinct from both the saved pin below and the '12345670' literal
    # fallback, so a wrong branch is unambiguously detectable.
    bssid = "04:BF:6D:11:22:33"
    (tmp_path / "04BF6D112233.run").write_text("99999990")

    fake = FakePrompter(confirm_returns=False)
    settings = Settings(interface="wlan0", pixie_dust=True)
    conn = _make_initialize_with_fakes(monkeypatch, settings=settings, prompter=fake)

    used_pins = []
    monkeypatch.setattr(conn, "_wpsConnection", lambda bssid, pin, **kw: used_pins.append(pin))

    conn.singleConnection(bssid=bssid)

    assert fake.confirm_called
    assert used_pins == ["11228677"]


def test_default_prompter_is_cli_prompter_when_none_given(monkeypatch):
    conn = _make_initialize_with_fakes(monkeypatch)
    assert conn.PROMPTER is not None


def test_verbose_passthrough_uses_logger_raw_not_bare_print(monkeypatch, capsys):
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)

    settings = Settings(interface="wlan0", verbose=True)
    conn = _make_initialize_with_fakes(monkeypatch, settings=settings)
    conn.WPAS.stdout.readline.return_value = "some wpa_supplicant debug line\n"

    conn._handleWpas()  # pylint: disable=protected-access

    logger.set_event_bus(None)
    assert any(e.message == "some wpa_supplicant debug line" for e in seen)
    # and nothing leaked to real stdout via a bare print() when a bus is set
    assert "some wpa_supplicant debug line" not in capsys.readouterr().out


def test_non_verbose_does_not_emit_raw_passthrough(monkeypatch):
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)

    settings = Settings(interface="wlan0", verbose=False)
    conn = _make_initialize_with_fakes(monkeypatch, settings=settings)
    conn.WPAS.stdout.readline.return_value = "some wpa_supplicant debug line\n"

    conn._handleWpas()  # pylint: disable=protected-access

    logger.set_event_bus(None)
    assert not any(e.message == "some wpa_supplicant debug line" for e in seen)
