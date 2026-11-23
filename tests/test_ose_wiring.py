import importlib
import sys

import src.wifi.scanner
import src.wps.connection
import src.wps.bruteforce


def test_all_three_engine_modules_import_without_cli_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    importlib.reload(src.wifi.scanner)
    importlib.reload(src.wps.connection)
    importlib.reload(src.wps.bruteforce)  # none of these may raise SystemExit
