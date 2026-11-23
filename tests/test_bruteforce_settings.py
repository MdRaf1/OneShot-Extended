import importlib
import sys

import src.wps.bruteforce


def test_importing_bruteforce_does_not_parse_sys_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    importlib.reload(src.wps.bruteforce)  # must not raise SystemExit
