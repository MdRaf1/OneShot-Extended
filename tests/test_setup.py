import os

import pytest

import src.setup as setup
from src.errors import FatalError


def test_check_requirements_dies_on_missing_binary(monkeypatch):
    # setup.py does `from shutil import which`, same as the original
    # ose.py it was extracted from, so the patch target is setup.which,
    # not shutil.which.
    monkeypatch.setattr(setup, "which", lambda b: None)
    with pytest.raises(FatalError, match="Missing required utilities"):
        setup.checkRequirements()


def test_check_requirements_dies_when_not_root(monkeypatch):
    monkeypatch.setattr(setup, "which", lambda b: "/usr/bin/" + b)
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    with pytest.raises(FatalError, match="Run it as root"):
        setup.checkRequirements()


def test_check_requirements_passes_when_binaries_present_and_root(monkeypatch):
    monkeypatch.setattr(setup, "which", lambda b: "/usr/bin/" + b)
    monkeypatch.setattr(os, "getuid", lambda: 0)
    setup.checkRequirements()  # must not raise


def test_setup_mediatek_wifi_dies_if_not_char_device(tmp_path):
    fake = tmp_path / "wmtWifi"  # exists as a regular file, not a char device
    fake.touch()
    with pytest.raises(FatalError, match="MediaTek"):
        setup.setupMediatekWifi(fake)


def test_setup_directories_creates_sessions_and_pixiewps_dirs(tmp_path, monkeypatch):
    sessions_dir = str(tmp_path / "sessions") + "/"
    pixiewps_dir = str(tmp_path / "pixiewps") + "/"
    monkeypatch.setattr("src.utils.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("src.utils.PIXIEWPS_DIR", pixiewps_dir)
    # No legacy ~/.OSE dir in this environment, so the rename branch is a no-op.
    setup.setupDirectories()
    assert os.path.exists(sessions_dir)
    assert os.path.exists(pixiewps_dir)
