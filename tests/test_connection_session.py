from unittest.mock import MagicMock

from src.prompts import Prompter
from src.session import SessionStore
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


def _make_initialize_with_fakes(monkeypatch, settings=None, prompter=None, session=None):
    monkeypatch.setattr(Initialize, "_initWpaSupplicant", lambda self: None)
    conn = Initialize("wlan0", settings=settings, prompter=prompter, session=session)
    conn.WPAS = MagicMock()
    return conn


def test_pixie_pin_saved_to_session_on_abort(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "s.sqlite3")
    bssid = "AA:BB:CC:DD:EE:FF"
    conn = _make_initialize_with_fakes(monkeypatch, session=store)

    def raising_wps_connection(*args, **kwargs):  # pylint: disable=unused-argument
        raise KeyboardInterrupt

    monkeypatch.setattr(conn, "_wpsConnection", raising_wps_connection)

    result = conn.singleConnection(bssid=bssid, pin="12345670", store_pin_on_fail=True)

    assert result is False
    assert store.get_pixie_pin(bssid) == "12345670"


def test_pixie_pin_cleared_on_success(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "s.sqlite3")
    bssid = "AA:BB:CC:DD:EE:FF"
    store.upsert_target(bssid)
    store.update_pixie_pin(bssid, "12345670")

    settings = Settings(interface="wlan0", write=False)
    conn = _make_initialize_with_fakes(monkeypatch, settings=settings, session=store)

    def fake_wps_connection(*args, **kwargs):  # pylint: disable=unused-argument
        conn.CONNECTION_STATUS.STATUS = 'GOT_PSK'
        conn.CONNECTION_STATUS.WPA_PSK = 'secretpsk'
        conn.CONNECTION_STATUS.ESSID = 'home'

    monkeypatch.setattr(conn, "_wpsConnection", fake_wps_connection)

    result = conn.singleConnection(bssid=bssid, pin="12345670")

    assert result is True
    assert store.get_pixie_pin(bssid) is None


def test_pixie_reuse_confirm_reads_from_session_not_a_file(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "s.sqlite3")
    bssid = "04:BF:6D:11:22:33"  # resolves via generator to '11228677' if reuse declined
    store.upsert_target(bssid)
    store.update_pixie_pin(bssid, "99999990")

    fake = FakePrompter(confirm_returns=True)
    settings = Settings(interface="wlan0", pixie_dust=True)
    conn = _make_initialize_with_fakes(monkeypatch, settings=settings, prompter=fake, session=store)
    monkeypatch.setattr(conn, "_wpsConnection", lambda *a, **kw: False)

    conn.singleConnection(bssid=bssid)

    assert fake.confirm_called
    assert "99999990" in fake.confirm_message


def test_pixie_reuse_with_no_saved_pin_does_not_prompt(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "s.sqlite3")
    bssid = "04:BF:6D:11:22:33"

    fake = FakePrompter(confirm_returns=True)
    settings = Settings(interface="wlan0", pixie_dust=True)
    conn = _make_initialize_with_fakes(monkeypatch, settings=settings, prompter=fake, session=store)

    used_pins = []
    monkeypatch.setattr(conn, "_wpsConnection", lambda bssid, pin, **kw: used_pins.append(pin))

    conn.singleConnection(bssid=bssid)

    assert not fake.confirm_called
    assert used_pins == ["11228677"]  # generator.getLikely fallback for this BSSID


def test_default_session_is_constructed_when_none_given(tmp_path, monkeypatch):
    monkeypatch.setattr("src.utils.SESSIONS_DIR", str(tmp_path) + "/")
    conn = _make_initialize_with_fakes(monkeypatch)
    assert conn.session is not None
