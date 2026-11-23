import subprocess

from src import logger
from src.events import Event, EventBus
from src.wps.pixiewps import Data


def _fake_pixiewps_run_returning(stdout_text):
    def fake_run(*args, **kwargs):  # pylint: disable=unused-argument
        return subprocess.CompletedProcess(args, 0, stdout=stdout_text, stderr=None)
    return fake_run


def _filled_data():
    data = Data()
    data.PKE = 'AA' * 192
    data.PKR = 'BB' * 192
    data.E_HASH1 = 'CC' * 32
    data.E_HASH2 = 'DD' * 32
    data.AUTHKEY = 'EE' * 32
    data.E_NONCE = 'FF' * 16
    data.R_NONCE = '11' * 16
    data.BSSID = 'AABBCCDDEEFF'
    return data


def test_run_pixie_wps_output_goes_through_logger_raw(monkeypatch, capsys):
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)

    monkeypatch.setattr(subprocess, "run", _fake_pixiewps_run_returning("[+] WPS pin: '12345670'"))
    data = _filled_data()
    pin = data.runPixieWps()

    logger.set_event_bus(None)
    # the real parser keeps the quotes from the line's text verbatim
    # (pin = line.split(':')[-1].strip()) — not this test's concern, just
    # matching existing, unchanged parsing behavior.
    assert pin == "'12345670'"
    assert any("WPS pin" in e.message for e in seen)
    # and no bare print() leaked to real stdout while a bus was set
    assert "WPS pin" not in capsys.readouterr().out


def test_run_pixie_wps_output_still_prints_when_no_bus(monkeypatch, capsys):
    logger.set_event_bus(None)
    monkeypatch.setattr(subprocess, "run", _fake_pixiewps_run_returning("[+] WPS pin: '12345670'"))
    data = _filled_data()
    data.runPixieWps()
    assert "WPS pin" in capsys.readouterr().out
