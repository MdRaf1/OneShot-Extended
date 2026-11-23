#  OneShot-Extended (WPS penetration testing utility) is a fork of the tool with extra features
#  Copyright (C) 2026 chkndrp
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

"""One-time startup checks and directory/device setup.

Extracted verbatim out of ose.py (same logic, same FatalError raises via
src.utils.die, same log lines) so the GUI entrypoint can reuse them too,
instead of only the CLI. setupAndroidWifi() stays in ose.py — it's
CLI-loop-specific (re-run every --loop iteration), not reused elsewhere.
"""

import os

from shutil import which
from pathlib import Path

from src import logger
import src.utils
import src.session


def checkRequirements():
    """Verify requirements are met"""

    required_binaries = [
        'pixiewps',
        'wpa_supplicant',
        'iw', 'ip'
    ]
    missing = [b for b in required_binaries if not which(b)]

    if missing:
        src.utils.die(f"Missing required utilities: {', '.join(missing)}")

    if os.getuid() != 0:
        src.utils.die('Run it as root')

def setupDirectories():
    """Create required directories"""

    # We recently changed the PIXIEWPS_DIR and SESSIONS_DIR path
    # Rename older .OSE data dir to .OneShot-Extended, and maintain compatibility
    old_dir = os.path.expanduser('~/.OSE')
    new_dir = os.path.expanduser('~/.OneShot-Extended')

    if os.path.exists(old_dir):
        try:
            os.rename(old_dir, new_dir)
            logger.info('Renamed legacy data directory')
        except OSError as e:
            logger.error(f'Failed to rename data directory: {e}')

    for directory in [src.utils.SESSIONS_DIR, src.utils.PIXIEWPS_DIR]:
        if not os.path.exists(directory):
            os.makedirs(directory)

    src.session.migrate_legacy_run_files(
        src.session.SessionStore(), src.utils.SESSIONS_DIR, src.utils.PIXIEWPS_DIR
    )

def setupMediatekWifi(wmt_wifi_device: Path):
    """Initialize MediaTek WiFi dev"""

    if not wmt_wifi_device.is_char_device():
        src.utils.die('Unable to activate MediaTek Wi-Fi interface device (--mtk-wifi): '
                     '/dev/wmtWifi does not exist or it is not a character device')

    wmt_wifi_device.chmod(0o644)
    wmt_wifi_device.write_text('1', encoding='utf-8')
