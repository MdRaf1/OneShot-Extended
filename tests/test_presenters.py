import pytest

from src.events import Event
from src.session import TargetRecord


def _network(**overrides):
    base = {
        "ESSID": "home", "BSSID": "AA:BB:CC:DD:EE:FF", "Level": -50,
        "WPS locked": False, "WPS version": "2.0",
        "Model": "", "Model number": "", "Device name": "",
    }
    base.update(overrides)
    return base


def _record(**overrides):
    base = {
        "bssid": "AA:BB:CC:DD:EE:FF", "essid": "home", "state": "pending",
        "last_chain_step": None, "bruteforce_mask": None, "pixie_pin": None,
        "cooldown_until": None, "wps_pin": None, "wpa_psk": None, "updated_at": 0.0,
    }
    base.update(overrides)
    return TargetRecord(**base)


# ---------------------------------------------------------------------------
# format_network_row
# ---------------------------------------------------------------------------

def test_format_network_row_highlights_locked():
    from src.presenters import format_network_row
    row = format_network_row(_network(**{"WPS locked": True, "WPS version": "2.0"}))
    assert row["highlight"] == "locked"


def test_format_network_row_highlights_vulnerable_version_over_model():
    from src.presenters import format_network_row
    row = format_network_row(_network(**{
        "WPS locked": False, "WPS version": "1.0", "Model": "KnownVulnModel",
    }))
    # priority order matches scanner.py: version-1.0 beats a model match
    assert row["highlight"] == "vulnerable_version"


def test_format_network_row_highlights_stored_above_everything_else():
    from src.presenters import format_network_row
    row = format_network_row(_network(**{
        "WPS locked": True, "WPS version": "1.0", "_stored": True,
    }))
    assert row["highlight"] == "stored"


def test_format_network_row_highlights_vulnerable_model_when_flagged():
    from src.presenters import format_network_row
    row = format_network_row(_network(**{
        "WPS locked": False, "WPS version": "2.0", "_vulnerable_model": True,
    }))
    assert row["highlight"] == "vulnerable_model"


def test_format_network_row_none_when_nothing_matches():
    from src.presenters import format_network_row
    row = format_network_row(_network())
    assert row["highlight"] == "none"


def test_format_network_row_label_format():
    from src.presenters import format_network_row
    row = format_network_row(_network(ESSID="home", BSSID="AA:BB:CC:DD:EE:FF", Level=-45))
    assert row["label"] == "home (AA:BB:CC:DD:EE:FF) -45dBm"


# ---------------------------------------------------------------------------
# format_queue_row
# ---------------------------------------------------------------------------

def test_format_queue_row_progress_percent_matches_bruteforce_formula():
    from src.presenters import format_queue_row
    record = _record(state="running", bruteforce_mask="5000")
    row = format_queue_row(record)
    assert row["progress_percent"] == pytest.approx(int(5000 / 11000 * 100))


def test_format_queue_row_progress_percent_for_second_half_mask():
    from src.presenters import format_queue_row
    record = _record(state="running", bruteforce_mask="0000500")
    row = format_queue_row(record)
    expected = int((10000 / 11000 + 500 / 11000) * 100)
    assert row["progress_percent"] == pytest.approx(expected)


def test_format_queue_row_no_progress_when_not_running():
    from src.presenters import format_queue_row
    record = _record(state="cracked", bruteforce_mask=None)
    assert format_queue_row(record)["progress_percent"] is None


def test_format_queue_row_no_progress_when_running_without_mask():
    from src.presenters import format_queue_row
    record = _record(state="running", bruteforce_mask=None)
    assert format_queue_row(record)["progress_percent"] is None


def test_format_queue_row_label_uses_essid_and_bssid():
    from src.presenters import format_queue_row
    record = _record(bssid="AA:BB:CC:DD:EE:FF", essid="home")
    row = format_queue_row(record)
    assert row["label"] == "home (AA:BB:CC:DD:EE:FF)"


def test_format_queue_row_label_falls_back_to_bssid_without_essid():
    from src.presenters import format_queue_row
    record = _record(bssid="AA:BB:CC:DD:EE:FF", essid=None)
    row = format_queue_row(record)
    assert row["label"] == "AA:BB:CC:DD:EE:FF (AA:BB:CC:DD:EE:FF)"


def test_format_queue_row_status_text_for_cracked():
    from src.presenters import format_queue_row
    row = format_queue_row(_record(state="cracked"))
    assert row["status_text"] == "Cracked"


def test_format_queue_row_status_text_for_failed():
    from src.presenters import format_queue_row
    row = format_queue_row(_record(state="failed"))
    assert row["status_text"] == "Failed"


def test_format_queue_row_status_text_for_cooldown_takes_priority_over_pending():
    from src.presenters import format_queue_row
    row = format_queue_row(_record(state="pending", cooldown_until=99999999.0))
    assert "lock" in row["status_text"].lower()


def test_format_queue_row_status_text_ignores_cooldown_once_cracked():
    from src.presenters import format_queue_row
    # cooldown_until is never cleared once set — a cracked target with a
    # stale cooldown must still show as Cracked, not Locked.
    row = format_queue_row(_record(state="cracked", cooldown_until=99999999.0))
    assert row["status_text"] == "Cracked"


def test_format_queue_row_status_text_for_pending():
    from src.presenters import format_queue_row
    row = format_queue_row(_record(state="pending"))
    assert row["status_text"] == "Pending"


# ---------------------------------------------------------------------------
# format_log_line
# ---------------------------------------------------------------------------

def test_format_log_line_strips_ansi_and_formats_level():
    from src.presenters import format_log_line
    line = format_log_line(Event(kind="warning", level="warning", message="\x1b[1;33m[-] locked\x1b[0m"))
    assert line == "[WARNING] [-] locked"


def test_format_log_line_with_no_ansi_codes():
    from src.presenters import format_log_line
    line = format_log_line(Event(kind="info", level="info", message="scanning..."))
    assert line == "[INFO] scanning..."


def test_format_log_line_success_level():
    from src.presenters import format_log_line
    line = format_log_line(Event(kind="success", level="success", message="cracked!"))
    assert line == "[SUCCESS] cracked!"
