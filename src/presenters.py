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

"""Pure GUI data-mapping functions — no I/O, no UI-framework import.
Framework-agnostic by design, so any front end's route/screen modules
can call into these rather than formatting anything themselves; used
today by the web GUI's routes (src/web/).
"""

import re

from src.events import Event
from src.session import TargetRecord

_ANSI_ESCAPE_RE = re.compile(r'\033\[[0-9;]*m')

_STATUS_LABELS = {
    'pending': 'Pending',
    'running': 'Running',
    'locked': 'Locked',
    'cracked': 'Cracked',
    'failed': 'Failed',
}


def format_network_row(network: dict) -> dict:
    """Maps one scan-result network dict (the shape WiFiScanner._iwScanner()
    returns) to GUI display fields.

    Priority order matches scanner.py's own CLI table highlighting
    exactly: stored > vulnerable (WPS 1.0) > locked > vulnerable model >
    none. "Stored" and "vulnerable model" require context a single
    network dict can't carry on its own (a loaded stored.csv / vuln-list
    file, same as scanner.py's self.STORED/self.VULN_LIST) — a caller that
    wants those two categories pre-computes them and sets the optional
    '_stored' / '_vulnerable_model' boolean keys before calling this.
    """

    essid = network.get('ESSID', '')
    bssid = network.get('BSSID', '')
    level = network.get('Level', 0)
    label = f'{essid} ({bssid}) {level}dBm'

    if network.get('_stored', False):
        highlight = 'stored'
    elif network.get('WPS version') == '1.0':
        highlight = 'vulnerable_version'
    elif network.get('WPS locked', False):
        highlight = 'locked'
    elif network.get('_vulnerable_model', False):
        highlight = 'vulnerable_model'
    else:
        highlight = 'none'

    return {'label': label, 'highlight': highlight}


def format_queue_row(record: TargetRecord) -> dict:
    """Maps one TargetRecord to GUI queue-list display fields."""

    label_name = record.essid if record.essid else record.bssid
    label = f'{label_name} ({record.bssid})'

    if record.state in ('cracked', 'failed'):
        status_text = _STATUS_LABELS[record.state]
    elif record.cooldown_until is not None:
        status_text = 'Locked (cooldown)'
    else:
        status_text = _STATUS_LABELS.get(record.state, record.state.capitalize())

    progress_percent = None
    if record.state == 'running' and record.bruteforce_mask:
        mask = record.bruteforce_mask
        if len(mask) == 4:
            progress_percent = int(int(mask) / 11000 * 100)
        else:
            progress_percent = int((10000 / 11000 + int(mask[4:]) / 11000) * 100)

    return {'label': label, 'status_text': status_text, 'progress_percent': progress_percent}


def format_log_line(event: Event) -> str:
    """Maps one Event to a single ANSI-stripped display line."""

    clean_message = _ANSI_ESCAPE_RE.sub('', event.message)
    return f'[{event.level.upper()}] {clean_message}'
