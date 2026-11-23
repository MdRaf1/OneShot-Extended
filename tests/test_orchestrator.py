import threading
import time
from types import SimpleNamespace

import src.wps.connection
from src.errors import FatalError
from src.events import EventBus
from src.session import SessionStore
from src.settings import Settings


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeConnection:
    """Stands in for connection.Initialize. Infers which chain step is
    active from the settings flags the orchestrator toggles (matching
    production singleConnection's own pin-resolution logic), and looks up
    scripted per-BSSID behavior from its owning factory."""

    def __init__(self, factory, settings):
        self.factory = factory
        self.settings = settings
        self.CONNECTION_STATUS = src.wps.connection.ConnectionStatus()

    def singleConnection(self, bssid=None, pin=None, pbc_mode=False,  # pylint: disable=unused-argument
                         store_pin_on_fail=False, retry_on_lock=True):
        if self.settings.null_pin:
            step_label = "null_pin"
        elif self.settings.pixie_dust:
            step_label = "pixie_dust"
        else:
            step_label = "default_pins"

        self.factory.call_order.append(f"{bssid}:{step_label}")
        if self.factory.on_call:
            self.factory.on_call(bssid, step_label)

        count = self.factory.call_counts.get(bssid, 0) + 1
        self.factory.call_counts[bssid] = count
        behavior = self.factory.script.get(bssid, "always_fail")

        self.CONNECTION_STATUS.clear()

        if behavior == "always_fail":
            return False

        if behavior == "null_pin_fails_pixie_succeeds":
            if step_label == "pixie_dust":
                self.CONNECTION_STATUS.STATUS = 'GOT_PSK'
                self.CONNECTION_STATUS.WPA_PSK = 'secretpsk'
                self.CONNECTION_STATUS.ESSID = 'home'
                return True
            return False

        if behavior == "locked_once_then_fails":
            if count == 1:
                self.CONNECTION_STATUS.IS_LOCKED = True
            return False

        return False


class ScriptedConnectionFactory:
    """Callable (interface, settings) -> FakeConnection, matching the
    orchestrator's connection_factory contract exactly (2 positional
    args)."""

    def __init__(self, script, on_call=None):
        self.script = script
        self.on_call = on_call
        self.call_order = []
        self.call_counts = {}

    def __call__(self, interface, settings):  # pylint: disable=unused-argument
        return FakeConnection(self, settings)


class RaisingConnectionFactory:
    """Always raises FatalError when constructed/called — proves the
    orchestrator isolates a FatalError to the affected target(s)."""

    def __init__(self, message="missing binary"):
        self.message = message

    def __call__(self, interface, settings):  # pylint: disable=unused-argument
        raise FatalError(self.message)


class NoOpBruteforce:
    """bruteforce.Initialize-like fake whose bruteforceStep always reports
    the mask range exhausted immediately, keeping fast-phase-only tests
    from spending time or real subprocess calls on a bruteforce phase
    they don't care about."""

    def bruteforceStep(self, bssid, mask):  # pylint: disable=unused-argument
        return ('exhausted', None)


class NoOpBruteforceFactory:
    def __call__(self, interface, settings, session=None):  # pylint: disable=unused-argument
        return NoOpBruteforce()


class FakeGenerator:
    def __init__(self, getAllLikely_returns):  # pylint: disable=invalid-name
        self._returns = getAllLikely_returns

    def getAllLikely(self, bssid):  # pylint: disable=invalid-name,unused-argument
        return self._returns


class FakeClock:
    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def advance(self, seconds):
        self._now += seconds


def _make_session(tmp_path):
    return SessionStore(tmp_path / "s.sqlite3")


# Imported lazily in each test after the implementation exists, to match
# the plan's Step 2 (run against a module that doesn't exist yet, expect
# FAIL) before Step 3 implements it.
from src.orchestrator import Orchestrator  # noqa: E402  pylint: disable=wrong-import-position


# ---------------------------------------------------------------------------
# Step 1: breadth-first ordering across the fast chain
# ---------------------------------------------------------------------------

def test_fast_steps_run_breadth_first_across_targets(tmp_path):
    fake_conn_factory = ScriptedConnectionFactory(
        script={"AA:AA:AA:AA:AA:AA": "always_fail", "BB:BB:BB:BB:BB:BB": "always_fail"}
    )
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        connection_factory=fake_conn_factory, bruteforce_factory=NoOpBruteforceFactory(),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.enqueue("BB:BB:BB:BB:BB:BB")
    orch.run()

    # Neither BSSID matches a known vendor OUI, so DEFAULT_PINS is a
    # no-op for both (no singleConnection call) — only NULL_PIN and
    # PIXIE_DUST show up, breadth-first (A, B, A, B — not A-then-B).
    assert fake_conn_factory.call_order == [
        "AA:AA:AA:AA:AA:AA:null_pin",
        "BB:BB:BB:BB:BB:BB:null_pin",
        "AA:AA:AA:AA:AA:AA:pixie_dust",
        "BB:BB:BB:BB:BB:BB:pixie_dust",
    ]


# ---------------------------------------------------------------------------
# Step 5: stop at first success
# ---------------------------------------------------------------------------

def test_chain_stops_at_first_success_pixie_dust(tmp_path):
    fake = ScriptedConnectionFactory(script={"AA:AA:AA:AA:AA:AA": "null_pin_fails_pixie_succeeds"})
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        connection_factory=fake, bruteforce_factory=NoOpBruteforceFactory(),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()

    target = orch.session.get_target("AA:AA:AA:AA:AA:AA")
    assert target.state == "cracked"
    assert target.wpa_psk == "secretpsk"
    # default_pins and bruteforce never attempted
    assert fake.call_order == ["AA:AA:AA:AA:AA:AA:null_pin", "AA:AA:AA:AA:AA:AA:pixie_dust"]


# ---------------------------------------------------------------------------
# Step 7: empty vendor-PIN suggestion list is a clean no-op
# ---------------------------------------------------------------------------

def test_default_pins_step_skips_cleanly_when_no_suggestions(tmp_path):
    fake_conn = ScriptedConnectionFactory(script={"AA:AA:AA:AA:AA:AA": "always_fail"})
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        connection_factory=fake_conn, bruteforce_factory=NoOpBruteforceFactory(),
        generator_factory=lambda: FakeGenerator(getAllLikely_returns=[]),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()  # must not raise

    target = orch.session.get_target("AA:AA:AA:AA:AA:AA")
    assert target.state != "cracked"
    # only null_pin and pixie_dust were attempted; default_pins never
    # called singleConnection at all (empty candidate list => no-op)
    assert fake_conn.call_order == [
        "AA:AA:AA:AA:AA:AA:null_pin",
        "AA:AA:AA:AA:AA:AA:pixie_dust",
    ]


# ---------------------------------------------------------------------------
# Step 9: locked target is skipped (cooldown) then revisited on a later run()
# ---------------------------------------------------------------------------

def test_locked_target_is_requeued_and_revisited_after_cooldown(tmp_path, monkeypatch):
    clock = FakeClock(start=1000.0)
    monkeypatch.setattr(time, "time", clock.now)

    fake = ScriptedConnectionFactory(
        script={"AA:AA:AA:AA:AA:AA": "locked_once_then_fails", "BB:BB:BB:BB:BB:BB": "always_fail"}
    )
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0", timeout=5), session=_make_session(tmp_path),
        connection_factory=fake, bruteforce_factory=NoOpBruteforceFactory(),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.enqueue("BB:BB:BB:BB:BB:BB")

    orch.run()  # first run: A locks on null_pin, cooldown set to 1005

    # A was attempted for null_pin (and got locked, cooldown-gated out of
    # pixie_dust this round); B proceeded through both fast steps.
    assert fake.call_order == [
        "AA:AA:AA:AA:AA:AA:null_pin",
        "BB:BB:BB:BB:BB:BB:null_pin",
        "BB:BB:BB:BB:BB:BB:pixie_dust",
    ]
    assert orch.session.get_target("AA:AA:AA:AA:AA:AA").state == "pending"

    clock.advance(10)  # past the 5s cooldown
    orch.run()  # second run: A is eligible again, revisited (not abandoned)

    assert "AA:AA:AA:AA:AA:AA:null_pin" in fake.call_order[3:]
    assert "AA:AA:AA:AA:AA:AA:pixie_dust" in fake.call_order


# ---------------------------------------------------------------------------
# Step 11: settings flags toggled per-step don't leak into the next step
# ---------------------------------------------------------------------------

def test_toggling_settings_between_steps_does_not_leak_into_next_step(tmp_path):
    # The connection is one shared, long-lived instance across the whole
    # fast-phase sweep (constructed once), so the flags must be observed
    # per singleConnection() call, not per factory construction.
    seen_flags = []

    class RecordingConnection:
        def __init__(self, settings):
            self.settings = settings
            self.CONNECTION_STATUS = src.wps.connection.ConnectionStatus()

        def singleConnection(self, **kwargs):  # pylint: disable=unused-argument
            seen_flags.append((self.settings.null_pin, self.settings.pixie_dust))
            return False

    base = Settings(interface="wlan0")
    orch = Orchestrator(
        "wlan0", base, session=_make_session(tmp_path),
        connection_factory=lambda interface, settings: RecordingConnection(settings),
        bruteforce_factory=NoOpBruteforceFactory(),
        generator_factory=lambda: FakeGenerator(getAllLikely_returns=[]),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()

    assert seen_flags[0] == (True, False)   # NULL_PIN step
    assert seen_flags[1] == (False, True)   # PIXIE_DUST step
    assert base.null_pin is False and base.pixie_dust is False  # restored after the sweep


# ---------------------------------------------------------------------------
# Step 13: a FatalError on one target doesn't kill the whole run
# ---------------------------------------------------------------------------

def test_fatal_error_on_one_target_does_not_kill_the_run(tmp_path):
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))

    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        event_bus=bus, connection_factory=RaisingConnectionFactory(),
        bruteforce_factory=NoOpBruteforceFactory(),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()  # must return normally, not raise

    assert any(e.kind == "fatal_error" for e in seen)
    assert orch.session.get_target("AA:AA:AA:AA:AA:AA").state == "failed"


def test_fatal_error_from_bruteforce_factory_marks_only_that_target_failed(tmp_path):
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))

    fake_conn = ScriptedConnectionFactory(script={"AA:AA:AA:AA:AA:AA": "always_fail"})

    def raising_bf_factory(interface, settings, session=None):  # pylint: disable=unused-argument
        raise FatalError("missing pixiewps")

    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        event_bus=bus, connection_factory=fake_conn, bruteforce_factory=raising_bf_factory,
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()  # must return normally

    assert any(e.kind == "fatal_error" for e in seen)
    assert orch.session.get_target("AA:AA:AA:AA:AA:AA").state == "failed"


# ---------------------------------------------------------------------------
# Step 15: bruteforce phase — sequential, cracked/exhausted stop it, and
# run() honors stop_flag between every single attempt
# ---------------------------------------------------------------------------

class SequentialBruteforce:
    """bruteforceStep: advances 3 times then cracks, recording which
    bssid each call belongs to in a shared log for sequencing checks."""

    def __init__(self, bssid, log):
        self.bssid = bssid
        self.log = log
        self.calls = 0
        # Mirrors the real bruteforce.Initialize's structure: the
        # orchestrator reads the cracked WPA_PSK off
        # CONNECTION.CONNECTION_STATUS after a 'cracked' result, since
        # bruteforceStep itself only returns the PIN.
        self.CONNECTION = SimpleNamespace(CONNECTION_STATUS=SimpleNamespace(WPA_PSK='secretpsk'))

    def bruteforceStep(self, bssid, mask):  # pylint: disable=unused-argument
        self.calls += 1
        self.log.append((self.bssid, self.calls))
        if self.calls >= 3:
            return ('cracked', '12345670')
        return ('advanced', None)


class SequentialBruteforceFactory:
    def __init__(self):
        self.log = []
        self._instances = {}

    def __call__(self, interface, settings, session=None):  # pylint: disable=unused-argument
        # bruteforce_factory is called once per target by the
        # orchestrator (a fresh instance per target), keyed here by call
        # order so each target's own instance tracks its own call count.
        bssid = f"target-{len(self._instances)}"
        inst = SequentialBruteforce(bssid, self.log)
        self._instances[bssid] = inst
        return inst


def test_bruteforce_pass_runs_sequentially_after_fast_steps_exhausted(tmp_path):
    fake_conn = ScriptedConnectionFactory(
        script={"AA:AA:AA:AA:AA:AA": "always_fail", "BB:BB:BB:BB:BB:BB": "always_fail"}
    )
    bf_factory = SequentialBruteforceFactory()
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        connection_factory=fake_conn, bruteforce_factory=bf_factory,
        generator_factory=lambda: FakeGenerator(getAllLikely_returns=[]),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.enqueue("BB:BB:BB:BB:BB:BB")
    orch.run()

    # target-0's 3 calls (cracking it) all happen before target-1's begin.
    bssids_in_call_order = [bssid for bssid, _n in bf_factory.log]
    assert bssids_in_call_order == ["target-0", "target-0", "target-0", "target-1", "target-1", "target-1"]


def test_run_honors_stop_flag_mid_sweep(tmp_path):
    stop = threading.Event()

    def on_call(bssid, step_label):  # pylint: disable=unused-argument
        stop.set()

    fake = ScriptedConnectionFactory(
        script={"AA:AA:AA:AA:AA:AA": "always_fail", "BB:BB:BB:BB:BB:BB": "always_fail"},
        on_call=on_call,
    )
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        connection_factory=fake, bruteforce_factory=NoOpBruteforceFactory(),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.enqueue("BB:BB:BB:BB:BB:BB")
    orch.run(stop_flag=stop)

    assert len(fake.call_order) == 1  # stopped after the first attempt


def test_stop_method_also_halts_the_run(tmp_path):
    def on_call(bssid, step_label):  # pylint: disable=unused-argument
        orch.stop()

    fake = ScriptedConnectionFactory(
        script={"AA:AA:AA:AA:AA:AA": "always_fail", "BB:BB:BB:BB:BB:BB": "always_fail"},
        on_call=on_call,
    )
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        connection_factory=fake, bruteforce_factory=NoOpBruteforceFactory(),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.enqueue("BB:BB:BB:BB:BB:BB")
    orch.run()

    assert len(fake.call_order) == 1


# ---------------------------------------------------------------------------
# enqueue/get_queue_snapshot basics
# ---------------------------------------------------------------------------

def test_enqueue_is_idempotent_for_the_same_bssid(tmp_path):
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        connection_factory=ScriptedConnectionFactory(script={}), bruteforce_factory=NoOpBruteforceFactory(),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA", essid="home")
    orch.enqueue("AA:AA:AA:AA:AA:AA", essid="home")
    assert len(orch.get_queue_snapshot()) == 1


# ---------------------------------------------------------------------------
# Final-review fix: bruteforce phase sets state='running' while in progress
# (otherwise the GUI's progress display can never render, since
# presenters.format_queue_row gates it on state == 'running')
# ---------------------------------------------------------------------------

class StateRecordingBruteforce:
    def __init__(self, session, bssid, calls_before_crack=3):
        self.session = session
        self.bssid = bssid
        self.calls_before_crack = calls_before_crack
        self.calls = 0
        self.seen_states = []
        self.CONNECTION = SimpleNamespace(CONNECTION_STATUS=SimpleNamespace(WPA_PSK='secretpsk'))

    def bruteforceStep(self, bssid, mask):  # pylint: disable=unused-argument
        self.calls += 1
        self.seen_states.append(self.session.get_target(bssid).state)
        if self.calls >= self.calls_before_crack:
            return ('cracked', '12345670')
        return ('advanced', None)


def test_bruteforce_phase_sets_state_running_while_in_progress(tmp_path):
    session = _make_session(tmp_path)
    fake_conn = ScriptedConnectionFactory(script={"AA:AA:AA:AA:AA:AA": "always_fail"})
    bf = StateRecordingBruteforce(session, "AA:AA:AA:AA:AA:AA")
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=session,
        connection_factory=fake_conn, bruteforce_factory=lambda interface, settings, session=None: bf,
        generator_factory=lambda: FakeGenerator(getAllLikely_returns=[]),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()

    assert bf.seen_states == ["running", "running", "running"]
    assert session.get_target("AA:AA:AA:AA:AA:AA").state == "cracked"


# ---------------------------------------------------------------------------
# Final-review fix: a transient WPS_FAIL during bruteforce ('retry') must
# retry the same mask value, not advance past it
# ---------------------------------------------------------------------------

class RetryThenCrackBruteforce:
    def __init__(self):
        self.calls = 0
        self.masks_seen = []
        self.CONNECTION = SimpleNamespace(CONNECTION_STATUS=SimpleNamespace(WPA_PSK='secretpsk'))

    def bruteforceStep(self, bssid, mask):  # pylint: disable=unused-argument
        self.calls += 1
        self.masks_seen.append(mask)
        if self.calls < 3:
            return ('retry', None)
        return ('cracked', '12345670')


def test_retry_state_reattempts_same_mask_without_advancing(tmp_path):
    fake_conn = ScriptedConnectionFactory(script={"AA:AA:AA:AA:AA:AA": "always_fail"})
    bf = RetryThenCrackBruteforce()
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        connection_factory=fake_conn, bruteforce_factory=lambda interface, settings, session=None: bf,
        generator_factory=lambda: FakeGenerator(getAllLikely_returns=[]),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()

    assert bf.masks_seen == ["0000", "0000", "0000"]  # never advanced past the retried value
    assert orch.session.get_target("AA:AA:AA:AA:AA:AA").state == "cracked"


# ---------------------------------------------------------------------------
# Final-review fix: stop() must not permanently latch the Orchestrator —
# a later run() call must do real work again, not return immediately
# ---------------------------------------------------------------------------

def test_stop_then_run_again_resumes_instead_of_returning_immediately(tmp_path):
    fake = ScriptedConnectionFactory(script={"AA:AA:AA:AA:AA:AA": "always_fail"})
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        connection_factory=fake, bruteforce_factory=NoOpBruteforceFactory(),
        generator_factory=lambda: FakeGenerator(getAllLikely_returns=[]),
    )
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.stop()  # simulate a prior Stop click before this run() call
    orch.run()

    assert fake.call_order == [
        "AA:AA:AA:AA:AA:AA:null_pin",
        "AA:AA:AA:AA:AA:AA:pixie_dust",
    ]


def test_run_with_empty_queue_does_nothing(tmp_path):
    orch = Orchestrator(
        "wlan0", Settings(interface="wlan0"), session=_make_session(tmp_path),
        connection_factory=ScriptedConnectionFactory(script={}), bruteforce_factory=NoOpBruteforceFactory(),
    )
    orch.run()  # must not raise
    assert orch.get_queue_snapshot() == []
