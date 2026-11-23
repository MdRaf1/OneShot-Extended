from unittest.mock import MagicMock

from src.prompts import Prompter
from src.session import SessionStore
from src.wps.bruteforce import Initialize
from src.wps.connection import Initialize as ConnectionInitialize


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


def _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, settings=None, prompter=None):
    monkeypatch.setattr(ConnectionInitialize, "_initWpaSupplicant", lambda self: None)
    # Always pass an explicit, tmp_path-scoped SessionStore so these tests
    # never touch the real default ~/.OneShot-Extended/sessions/ path.
    session = SessionStore(tmp_path / "s.sqlite3")
    bf = Initialize("wlan0", settings=settings, prompter=prompter, session=session)
    bf.CONNECTION.WPAS = MagicMock()
    # Don't actually attempt any real WPS traffic — smartBruteforce only
    # needs to reach the mask-resolution step for this test.
    monkeypatch.setattr(bf, "_firstHalfBruteforce", lambda bssid, mask: False)
    monkeypatch.setattr(bf, "_secondHalfBruteforce", lambda bssid, fh, sh: False)
    return bf


def test_resume_confirm_uses_injected_prompter(tmp_path, monkeypatch):
    bssid = "AA:BB:CC:DD:EE:FF"
    fake = FakePrompter(confirm_returns=False)
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, prompter=fake)
    bf.session.upsert_target(bssid)
    bf.session.update_bruteforce_mask(bssid, "1234567")

    bf.smartBruteforce(bssid)

    assert fake.confirm_called
    assert bssid in fake.confirm_message
    # declining the saved session starts fresh
    assert bf.BRUTEFORCE_STATUS.MASK == "0000"


def test_resume_confirm_accepted_restores_saved_mask(tmp_path, monkeypatch):
    bssid = "AA:BB:CC:DD:EE:FF"
    fake = FakePrompter(confirm_returns=True)
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, prompter=fake)
    bf.session.upsert_target(bssid)
    bf.session.update_bruteforce_mask(bssid, "1234567")

    bf.smartBruteforce(bssid)

    assert fake.confirm_called
    assert bf.BRUTEFORCE_STATUS.MASK == "1234567"


def test_default_prompter_is_cli_prompter_when_none_given(tmp_path, monkeypatch):
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path)
    assert bf.prompter is not None


def test_prompter_is_forwarded_to_internal_connection(tmp_path, monkeypatch):
    fake = FakePrompter()
    bf = _make_bruteforce_initialize_with_fakes(monkeypatch, tmp_path, prompter=fake)
    assert bf.CONNECTION.PROMPTER is fake
