from unittest.mock import MagicMock

from src.prompts import Prompter
from src.session import SessionStore
from src.wps.bruteforce import Initialize
from src.wps.connection import Initialize as ConnectionInitialize


class FakePrompter(Prompter):
    def __init__(self, confirm_returns=True):
        self.confirm_returns = confirm_returns
        self.confirm_called = False

    def confirm(self, message: str) -> bool:
        self.confirm_called = True
        return self.confirm_returns

    def confirm_explicit_yes(self, message: str) -> bool:
        return False

    def select_index(self, prompt, count, cancel_tokens=frozenset()):
        return 0


def _make_bruteforce_initialize_with_fakes(monkeypatch, session=None, prompter=None):
    monkeypatch.setattr(ConnectionInitialize, "_initWpaSupplicant", lambda self: None)
    bf = Initialize("wlan0", session=session, prompter=prompter)
    bf.CONNECTION.WPAS = MagicMock()
    return bf


def test_smart_bruteforce_resumes_from_session_store(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "s.sqlite3")
    bssid = "AA:BB:CC:DD:EE:FF"
    store.upsert_target(bssid)
    store.update_bruteforce_mask(bssid, "1234567")

    fake_prompter = FakePrompter(confirm_returns=True)
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, session=store, prompter=fake_prompter)

    seen_masks = []
    monkeypatch.setattr(bf, "_secondHalfBruteforce", lambda b, fh, sh: (seen_masks.append(fh + sh), False)[1])
    monkeypatch.setattr(bf, "_firstHalfBruteforce", lambda b, mask: (_ for _ in ()).throw(
        AssertionError("should resume directly into _secondHalfBruteforce for a 7-digit mask")
    ))

    bf.smartBruteforce(bssid)

    assert fake_prompter.confirm_called
    assert seen_masks == ["1234567"]


def test_smart_bruteforce_declining_resume_starts_fresh(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "s.sqlite3")
    bssid = "AA:BB:CC:DD:EE:FF"
    store.upsert_target(bssid)
    store.update_bruteforce_mask(bssid, "1234567")

    fake_prompter = FakePrompter(confirm_returns=False)
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, session=store, prompter=fake_prompter)
    monkeypatch.setattr(bf, "_firstHalfBruteforce", lambda b, mask: False)
    monkeypatch.setattr(bf, "_secondHalfBruteforce", lambda b, fh, sh: False)

    bf.smartBruteforce(bssid)

    assert fake_prompter.confirm_called
    assert bf.BRUTEFORCE_STATUS.MASK == "0000"


def test_smart_bruteforce_with_no_saved_session_starts_fresh_without_prompting(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "s.sqlite3")
    bssid = "AA:BB:CC:DD:EE:FF"
    fake_prompter = FakePrompter(confirm_returns=True)
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, session=store, prompter=fake_prompter)
    monkeypatch.setattr(bf, "_firstHalfBruteforce", lambda b, mask: False)
    monkeypatch.setattr(bf, "_secondHalfBruteforce", lambda b, fh, sh: False)

    bf.smartBruteforce(bssid)

    assert not fake_prompter.confirm_called
    assert bf.BRUTEFORCE_STATUS.MASK == "0000"


def test_smart_bruteforce_persists_mask_on_exit(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "s.sqlite3")
    bssid = "AA:BB:CC:DD:EE:FF"
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, session=store)
    monkeypatch.setattr(bf, "_firstHalfBruteforce", lambda b, mask: False)
    monkeypatch.setattr(bf, "_secondHalfBruteforce", lambda b, fh, sh: False)

    bf.smartBruteforce(bssid)

    assert store.get_bruteforce_mask(bssid) is not None


def test_default_session_is_constructed_when_none_given(monkeypatch, tmp_path):
    monkeypatch.setattr("src.utils.SESSIONS_DIR", str(tmp_path) + "/")
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch)
    assert bf.session is not None


def test_explicit_session_is_forwarded_to_internal_connection(tmp_path, monkeypatch):
    # Regression: bruteforce.Initialize's internal connection.Initialize
    # must share the SAME session the caller explicitly provided, not
    # silently default-construct its own (which would point at the real
    # ~/.OneShot-Extended/sessions/ path even when the caller passed an
    # explicit, sandboxed SessionStore).
    store = SessionStore(tmp_path / "s.sqlite3")
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, session=store)
    assert bf.CONNECTION.session is store
