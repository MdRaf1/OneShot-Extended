from unittest.mock import MagicMock

from src.session import SessionStore
from src.settings import Settings
from src.wps.connection import Initialize


def _make_initialize_with_fakes(monkeypatch, tmp_path, settings=None):
    monkeypatch.setattr(Initialize, "_initWpaSupplicant", lambda self: None)
    session = SessionStore(tmp_path / "s.sqlite3")
    conn = Initialize("wlan0", settings=settings, session=session)
    conn.WPAS = MagicMock()
    return conn


def test_retry_on_lock_false_propagates_into_recursive_pixie_call(tmp_path, monkeypatch):
    settings = Settings(interface="wlan0", pixie_dust=True)
    conn = _make_initialize_with_fakes(monkeypatch, tmp_path, settings=settings)

    # Fill every pixie-dust field so PIXIE_CREDS.getAll() is True, forcing
    # the recursive singleConnection(..., store_pin_on_fail=True) call.
    conn.PIXIE_CREDS.PKE = 'AA' * 192
    conn.PIXIE_CREDS.PKR = 'BB' * 192
    conn.PIXIE_CREDS.E_HASH1 = 'CC' * 32
    conn.PIXIE_CREDS.E_HASH2 = 'DD' * 32
    conn.PIXIE_CREDS.AUTHKEY = 'EE' * 32
    conn.PIXIE_CREDS.E_NONCE = 'FF' * 16
    conn.PIXIE_CREDS.R_NONCE = '11' * 16
    conn.PIXIE_CREDS.BSSID = 'AABBCCDDEEFF'

    monkeypatch.setattr(conn.PIXIE_CREDS, "runPixieWps", lambda *a, **kw: "12345670")

    calls = []

    def fake_wps_connection(*args, **kwargs):  # pylint: disable=unused-argument
        calls.append(kwargs.get("retry_on_lock"))
        if len(calls) >= 2:
            # second (recursive) attempt succeeds, ending recursion
            conn.CONNECTION_STATUS.STATUS = 'GOT_PSK'
            conn.CONNECTION_STATUS.WPA_PSK = 'secretpsk'
            conn.CONNECTION_STATUS.ESSID = 'home'

    monkeypatch.setattr(conn, "_wpsConnection", fake_wps_connection)

    conn.singleConnection(bssid="AA:BB:CC:DD:EE:FF", retry_on_lock=False)

    assert len(calls) == 2  # the original attempt + the recursive pixie-verification attempt
    assert all(v is False for v in calls)


def test_retry_on_lock_true_is_the_default(tmp_path, monkeypatch):
    conn = _make_initialize_with_fakes(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(
        conn, "_wpsConnection",
        lambda *a, **kw: calls.append(kw.get("retry_on_lock")),
    )

    conn.singleConnection(bssid="AA:BB:CC:DD:EE:FF", pin="12345670")

    assert calls == [True]


def test_retry_on_lock_false_propagates_into_plain_wps_connection_call(tmp_path, monkeypatch):
    conn = _make_initialize_with_fakes(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(
        conn, "_wpsConnection",
        lambda *a, **kw: calls.append(kw.get("retry_on_lock")),
    )

    conn.singleConnection(bssid="AA:BB:CC:DD:EE:FF", pin="12345670", retry_on_lock=False)

    assert calls == [False]


def test_retry_on_lock_propagates_into_store_pin_on_fail_call(tmp_path, monkeypatch):
    conn = _make_initialize_with_fakes(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(
        conn, "_wpsConnection",
        lambda *a, **kw: calls.append(kw.get("retry_on_lock")),
    )

    conn.singleConnection(
        bssid="AA:BB:CC:DD:EE:FF", pin="12345670", store_pin_on_fail=True, retry_on_lock=False
    )

    assert calls == [False]
