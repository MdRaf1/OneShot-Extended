import importlib
import sys

import src.wifi.scanner
import src.wps.connection
import src.wps.bruteforce
from src.prompts import Prompter

import ose


def test_all_three_engine_modules_import_without_cli_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    importlib.reload(src.wifi.scanner)
    importlib.reload(src.wps.connection)
    importlib.reload(src.wps.bruteforce)  # none of these may raise SystemExit


class FakePrompter(Prompter):
    def __init__(self, confirm_explicit_yes_returns=True):
        self.confirm_explicit_yes_returns = confirm_explicit_yes_returns
        self.confirm_explicit_yes_called = False

    def confirm(self, message: str) -> bool:
        return True

    def confirm_explicit_yes(self, message: str) -> bool:
        self.confirm_explicit_yes_called = True
        return self.confirm_explicit_yes_returns

    def select_index(self, prompt, count, cancel_tokens=frozenset()):
        return 0


def test_loop_exit_prompt_uses_explicit_yes_prompter():
    fake = FakePrompter(confirm_explicit_yes_returns=True)
    assert ose.shouldExitLoop(fake) is True
    assert fake.confirm_explicit_yes_called


def test_loop_exit_prompt_declines_to_continue_scanning():
    fake = FakePrompter(confirm_explicit_yes_returns=False)
    assert ose.shouldExitLoop(fake) is False
    assert fake.confirm_explicit_yes_called
