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

"""Crash-safe, multi-target session persistence.

Replaces the old single-BSSID, plain-text .run mask/PIN files (written
only on clean exit) with a sqlite-backed store that commits every write
immediately, so the orchestrator's multi-target queue state (and the
existing bruteforce/pixie resume data) survives a hard kill.
"""

import os
import re
import sqlite3
import time
from dataclasses import dataclass

from src import logger
from src import utils

DEFAULT_DB_FILENAME = 'sessions.sqlite3'

_BUSY_TIMEOUT_MS = 5000


@dataclass
class TargetRecord:
    """One queue/session target's full persisted state."""

    bssid: str
    essid: str | None
    state: str
    last_chain_step: str | None
    bruteforce_mask: str | None
    pixie_pin: str | None
    cooldown_until: float | None
    wps_pin: str | None
    wpa_psk: str | None
    updated_at: float


_COLUMNS = (
    'bssid', 'essid', 'state', 'last_chain_step', 'bruteforce_mask',
    'pixie_pin', 'cooldown_until', 'wps_pin', 'wpa_psk', 'updated_at',
)


class SessionStore:
    """sqlite-backed target/session store.

    Every write method opens its own connection, commits, and closes
    before returning — so a write is durable the instant the method
    returns, with no explicit flush/close needed by the caller (proven by
    test_writes_are_durable_across_reopen).
    """

    def __init__(self, db_path: str | os.PathLike | None = None):
        if db_path is None:
            db_path = os.path.join(utils.SESSIONS_DIR, DEFAULT_DB_FILENAME)
        self.db_path = str(db_path)

        directory = os.path.dirname(self.db_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute(f'PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}')
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS targets (
                    bssid TEXT PRIMARY KEY,
                    essid TEXT,
                    state TEXT NOT NULL DEFAULT 'pending',
                    last_chain_step TEXT,
                    bruteforce_mask TEXT,
                    pixie_pin TEXT,
                    cooldown_until REAL,
                    wps_pin TEXT,
                    wpa_psk TEXT,
                    updated_at REAL NOT NULL
                )'''
            )
            conn.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> TargetRecord:
        return TargetRecord(**{col: row[col] for col in _COLUMNS})

    def upsert_target(self, bssid: str, essid: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                '''INSERT INTO targets (bssid, essid, state, updated_at)
                   VALUES (?, ?, 'pending', ?)
                   ON CONFLICT(bssid) DO UPDATE SET
                       essid = COALESCE(excluded.essid, targets.essid),
                       updated_at = excluded.updated_at''',
                (bssid, essid, time.time())
            )
            conn.commit()

    def _update_field(self, bssid: str, field: str, value) -> None:
        with self._connect() as conn:
            conn.execute(
                f'UPDATE targets SET {field} = ?, updated_at = ? WHERE bssid = ?',
                (value, time.time(), bssid)
            )
            conn.commit()

    def set_state(self, bssid: str, state: str) -> None:
        self._update_field(bssid, 'state', state)

    def set_cooldown(self, bssid: str, seconds_from_now: float) -> None:
        self._update_field(bssid, 'cooldown_until', time.time() + seconds_from_now)

    def is_cooldown_expired(self, bssid: str, now: float | None = None) -> bool:
        target = self.get_target(bssid)
        if target is None or target.cooldown_until is None:
            return True
        if now is None:
            now = time.time()
        return now >= target.cooldown_until

    def update_bruteforce_mask(self, bssid: str, mask: str) -> None:
        self._update_field(bssid, 'bruteforce_mask', mask)

    def get_bruteforce_mask(self, bssid: str) -> str | None:
        target = self.get_target(bssid)
        return target.bruteforce_mask if target else None

    def update_pixie_pin(self, bssid: str, pin: str) -> None:
        self._update_field(bssid, 'pixie_pin', pin)

    def get_pixie_pin(self, bssid: str) -> str | None:
        target = self.get_target(bssid)
        return target.pixie_pin if target else None

    def clear_pixie_pin(self, bssid: str) -> None:
        self._update_field(bssid, 'pixie_pin', None)

    def set_last_chain_step(self, bssid: str, step: str) -> None:
        self._update_field(bssid, 'last_chain_step', step)

    def mark_cracked(self, bssid: str, wps_pin: str, wpa_psk: str) -> None:
        with self._connect() as conn:
            conn.execute(
                '''UPDATE targets SET state = 'cracked', wps_pin = ?, wpa_psk = ?, updated_at = ?
                   WHERE bssid = ?''',
                (wps_pin, wpa_psk, time.time(), bssid)
            )
            conn.commit()

    def mark_failed(self, bssid: str) -> None:
        self.set_state(bssid, 'failed')

    def get_target(self, bssid: str) -> TargetRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM targets WHERE bssid = ?', (bssid,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_targets(self) -> list[TargetRecord]:
        with self._connect() as conn:
            rows = conn.execute('SELECT * FROM targets ORDER BY bssid').fetchall()
        return [self._row_to_record(row) for row in rows]


def _filename_stem_to_bssid(stem: str) -> str:
    """Reinsert ':' every 2 hex chars, e.g. 'AABBCCDDEEFF' -> 'AA:BB:CC:DD:EE:FF'."""

    return ':'.join(stem[i:i + 2] for i in range(0, len(stem), 2))


_MASK_RE = re.compile(r'^[0-9]+$')


def _migrate_one_file(store: SessionStore, path: str, field: str) -> None:
    stem = os.path.splitext(os.path.basename(path))[0]
    bssid = _filename_stem_to_bssid(stem)

    try:
        with open(path, 'r', encoding='utf-8') as file:
            content = file.readline().strip()
    except (OSError, UnicodeDecodeError) as error:
        logger.warning(f'Skipping legacy session file {path}: {error}')
        return

    # A pixie PIN may legitimately be empty (the null-PIN-style '' case);
    # a bruteforce mask must be 4 or 7 digits. Anything else is malformed.
    if field == 'bruteforce_mask':
        valid = bool(_MASK_RE.match(content)) and len(content) in (4, 7)
    else:
        valid = content == '' or bool(_MASK_RE.match(content))

    if not valid:
        logger.warning(f'Skipping malformed legacy session file {path}: unexpected content')
        return

    store.upsert_target(bssid)
    if field == 'bruteforce_mask':
        store.update_bruteforce_mask(bssid, content)
    else:
        store.update_pixie_pin(bssid, content)

    try:
        os.rename(path, path + '.migrated')
    except OSError as error:
        logger.warning(f'Failed to rename migrated legacy session file {path}: {error}')


def migrate_legacy_run_files(store: SessionStore, sessions_dir: str, pixiewps_dir: str) -> None:
    """Converts old plain-text .run files (bruteforce masks under
    sessions_dir, pixie PINs under pixiewps_dir) into SessionStore rows,
    renaming each source file to '<name>.run.migrated' once converted
    (never deleted — idempotent and recoverable). A malformed file is
    skipped and logged, never raised.
    """

    for directory, field in ((sessions_dir, 'bruteforce_mask'), (pixiewps_dir, 'pixie_pin')):
        if not os.path.isdir(directory):
            continue
        for name in os.listdir(directory):
            if not name.endswith('.run'):
                continue
            _migrate_one_file(store, os.path.join(directory, name), field)
