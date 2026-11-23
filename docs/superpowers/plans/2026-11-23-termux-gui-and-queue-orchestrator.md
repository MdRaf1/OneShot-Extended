# Termux:GUI + Multi-Target Auto-Attack Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OneShot-Extended WPS engine usable as a library (fixing
a module-import-time `argparse` hazard), add crash-safe multi-target
session persistence, add an auto-chain/multi-target queue orchestrator, and
build a native Android GUI for it on top of the Termux:GUI plugin — all
while the existing CLI (`ose.py`) keeps behaving identically throughout.

**Architecture:** Thread an explicit `Settings` object and an injectable
`Prompter` through `scanner.py`/`connection.py`/`bruteforce.py`/
`generator.py` in place of their current module-level `parseArgs()` call
and blocking `input()`s. Replace the single-file bruteforce-mask resume
mechanism with a `sqlite3`-backed `SessionStore` written incrementally
(crash-safe). Build a new `Orchestrator` on top of the existing
`connection.Initialize`/`bruteforce.Initialize`/`generator.WPSpin` classes
(composition, no duplicated attack logic) that runs a breadth-first
multi-target sweep of fast attack steps, then a sequential bruteforce pass,
with lock-cooldown requeueing. Build the GUI as a thin Termux:GUI binding
layer over a separately-testable presenter module, so as much of the new
code as possible has real unit test coverage despite no rooted device, WPS
hardware, or Termux:GUI plugin being available in the implementation
environment.

**Tech Stack:** Python 3.11+ stdlib only for the core engine (no new
runtime pip dependencies); `sqlite3` (stdlib) for persistence; `pytest`
(dev-only) for tests; `termuxgui` (pip, GUI-entrypoint-only, never imported
by `ose.py` or anything under `src/`).

**Spec:** `/root/.claude/plans/can-you-turn-this-radiant-firefly.md` (the
approved design doc — read it first; this plan argues from it and does not
repeat its Context/Goals/Non-goals/Verification sections, only the task
breakdown).

## Global Constraints

- Zero new runtime pip dependencies for the core engine (`src/`, `ose.py`).
  `termuxgui` is imported only by `ose_gui.py` and `src/gui/*`.
- The CLI (`ose.py`) must behave identically — same flags, same output,
  same exit codes — after every task. Verify with a manual smoke run
  (documented per task) in addition to the automated test suite.
- Python 3.11+ (existing requirement, unchanged).
- Keep `.pylintrc` clean (best-effort: `pylint` is not pre-installed in
  this environment; install it from `requirements-dev.txt` if running
  pylint, but do not block a task's completion on it — pytest is the
  binding gate).
- No real root, WPS-capable AP hardware, or Termux:GUI plugin is available
  in the implementation environment. Every task's tests use fakes/mocks for
  `subprocess`, `wpa_supplicant`, `pixiewps`, and `termuxgui`. Tasks that
  cannot be meaningfully unit-tested this way say so explicitly and list the
  on-device follow-up instead of claiming false coverage.
- Session/pixie state files live under `~/.OneShot-Extended/` (existing
  `SESSIONS_DIR`/`PIXIEWPS_DIR` constants in `src/utils.py`) — the new
  `SessionStore` adds a sqlite file there, it does not relocate existing
  dirs.
- Preserve the existing `~/.OSE` → `~/.OneShot-Extended` migration already
  in `setupDirectories()` — new migration code is additive, not a
  replacement.

## Review Focus

- **Empty vendor-PIN suggestion list.** `generator.getAllLikely(bssid)`
  returns `[]` for a BSSID with no matching OUI table entry (very common —
  most of the 24 algorithms are vendor-specific). The orchestrator's
  `DEFAULT_PINS` step must skip cleanly to the next step/target, not treat
  an empty list as a crash or as a false success. Covered in Task 20.
- **Malformed legacy session file during migration.** `migrate_legacy_run_files()`
  must not abort `setupDirectories()`/the whole program if an existing
  `.run` file under `SESSIONS_DIR`/`PIXIEWPS_DIR` is empty, non-UTF-8, or
  contains garbage instead of a mask/PIN — it should skip that file and
  continue, not raise. Covered in Task 14.
- **Concurrent writers to the same `SessionStore`.** The CLI and the GUI
  can both run against the same `~/.OneShot-Extended/` directory (e.g. a
  user runs `ose.py -B` in one Termux session while the GUI queue is also
  active). `SessionStore` must not corrupt its sqlite file or raise an
  uncaught `sqlite3.OperationalError` under two concurrent writers to
  different BSSID rows. Covered in Task 14.
- **Settings mutated mid-flight.** The orchestrator reuses one
  `base_settings` object across chain steps, toggling fields like
  `null_pin`/`pixie_dust` between calls into a long-lived
  `connection.Initialize`. A test must prove that toggling fields between
  steps produces the expected per-step attack behavior and does not leak
  the previous step's flags into the next one. Covered in Task 20.
- **`FatalError` raised off the main thread.** When `connection.Initialize`
  or `bruteforce.Initialize` raises `FatalError` (e.g. `die()` from a
  missing binary) from inside the orchestrator's background thread, it
  must surface as an `Event` the GUI can observe, not vanish as an
  uncaught thread exception. Covered in Task 20.

---

### Task 1: Core infrastructure — errors, events, prompts

**Files:**
- Create: `src/errors.py`
- Create: `src/events.py`
- Create: `src/prompts.py`
- Test: `tests/test_errors.py`
- Test: `tests/test_events.py`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Produces: `errors.FatalError(Exception)`.
- Produces: `events.Event` (dataclass: `kind: str`, `level: str`,
  `message: str`, `data: dict = field(default_factory=dict)`);
  `events.EventBus` with `subscribe(fn: Callable[[Event], None]) ->
  Callable[[], None]` (returns an unsubscribe callback) and
  `emit(event: Event) -> None` (calls every subscribed `fn`, catching and
  swallowing any exception a subscriber raises so one bad subscriber can't
  break emission for the others).
- Produces: `prompts.Prompter` (ABC) — `confirm(message: str) -> bool`
  (default-yes semantics), `confirm_explicit_yes(message: str) -> bool`
  (default-no semantics), `select_index(prompt: str, count: int,
  cancel_tokens: frozenset[str] = frozenset()) -> int | None` (returns a
  0-based index, or `None` if the user entered a cancel token).
  `prompts.CLIPrompter(Prompter)` implements all three via `input()`,
  reproducing today's exact retry-on-invalid-input behavior (used by
  `generator.promptPin`, `connection`'s pixie-reuse confirm, `bruteforce`'s
  resume confirm, and `ose.py`'s loop-exit confirm, which the later tasks
  wire up — this task only defines the abstraction and its CLI
  implementation).

- [ ] **Step 1: Write failing tests for `FatalError`**

```python
def test_fatal_error_is_exception_with_message():
    with pytest.raises(FatalError, match="boom"):
        raise FatalError("boom")
```

- [ ] **Step 2: Run `pytest tests/test_errors.py -v`**

Expected: FAIL — `src.errors` does not exist.

- [ ] **Step 3: Implement `src/errors.py`**

`class FatalError(Exception): pass`.

- [ ] **Step 4: Run `pytest tests/test_errors.py -v`**

Expected: PASS.

- [ ] **Step 5: Write failing tests for `EventBus`**

```python
def test_emit_calls_subscribers():
    bus = EventBus(); seen = []
    bus.subscribe(lambda e: seen.append(e))
    bus.emit(Event(kind="x", level="info", message="hi"))
    assert seen[0].message == "hi"

def test_unsubscribe_stops_delivery():
    bus = EventBus(); seen = []
    unsub = bus.subscribe(lambda e: seen.append(e))
    unsub()
    bus.emit(Event(kind="x", level="info", message="hi"))
    assert seen == []

def test_emit_survives_a_raising_subscriber():
    bus = EventBus(); seen = []
    bus.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("bad")))
    bus.subscribe(lambda e: seen.append(e))
    bus.emit(Event(kind="x", level="info", message="hi"))
    assert len(seen) == 1
```

- [ ] **Step 6: Run `pytest tests/test_events.py -v`**

Expected: FAIL — `src.events` does not exist.

- [ ] **Step 7: Implement `src/events.py`** (`Event` dataclass,
  `EventBus` with `subscribe`/`emit` as specified above; `emit` wraps each
  subscriber call in `try/except Exception: pass`)

- [ ] **Step 8: Run `pytest tests/test_events.py -v`**

Expected: PASS.

- [ ] **Step 9: Write failing tests for `CLIPrompter`** (monkeypatch
  `builtins.input`)

```python
def test_confirm_default_yes_on_enter(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert CLIPrompter().confirm("ok?") is True

def test_confirm_explicit_yes_default_no_on_enter(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert CLIPrompter().confirm_explicit_yes("exit?") is False

def test_select_index_valid_choice(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "2")
    assert CLIPrompter().select_index("pick", 3) == 1  # 1-based input, 0-based return

def test_select_index_cancel_token(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "r")
    assert CLIPrompter().select_index("pick", 3, cancel_tokens=frozenset({"r"})) is None

def test_select_index_retries_on_invalid(monkeypatch):
    responses = iter(["bogus", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    assert CLIPrompter().select_index("pick", 3) == 0
```

- [ ] **Step 10: Run `pytest tests/test_prompts.py -v`**

Expected: FAIL — `src.prompts` does not exist.

- [ ] **Step 11: Implement `src/prompts.py`** (`Prompter` ABC via
  `abc.ABC`/`abstractmethod`; `CLIPrompter` reproducing today's exact
  prompt text and retry loop — reuse the literal strings already in
  `generator.py:143`, `connection.py:121`, `bruteforce.py:166`, `ose.py:181`
  when those call sites are rewired in later tasks, so this class's text
  constants must match those exactly: `'[?] Use previously calculated PIN
  {t_pin}? [n/Y] '`-style confirm, `'[?] Restore previous session for
  {bssid}? [n/Y]'`-style confirm, `'Select the PIN: '`-style select,
  `'\n[?] Exit the script (otherwise continue to AP scan)? [N/y] '`-style
  explicit-yes confirm — keep the format strings as caller-supplied
  `message` arguments, not hardcoded here, so this class stays generic)

- [ ] **Step 12: Run `pytest tests/test_prompts.py -v`**

Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add src/errors.py src/events.py src/prompts.py tests/test_errors.py tests/test_events.py tests/test_prompts.py
git commit -m "feat: add FatalError, EventBus, and Prompter abstractions"
```

---

### Task 2: Settings object + testable argparse

**Files:**
- Create: `src/settings.py`
- Modify: `src/args.py` (`parseArgs` signature)
- Test: `tests/test_settings.py`
- Test: `tests/test_args.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `settings.Settings` — a mutable dataclass with one field per
  `args.py` flag, exact names and defaults matching `args.py`'s
  `dest`/`default` values: `interface: str`, `bssid: str | None = None`,
  `pin: str | None = None`, `null_pin: bool = False`, `pixie_dust: bool =
  False`, `bruteforce: bool = False`, `pbc: bool = False`, `kill: bool =
  False`, `restore: bool = False`, `write: bool = False`, `loop: bool =
  False`, `clear: bool = False`, `delay: float = 0`, `timeout: float = 60`,
  `pixie_force: bool = False`, `show_pixie: bool = False`, `iface_down:
  bool = False`, `mtk_wifi: bool = False`, `dont_touch_settings: bool =
  False`, `reverse_scan: bool = False`, `vuln_list: str = <same default
  expression as args.py's `--vuln-list` default>`, `verbose: bool = False`.
  Classmethods: `Settings.from_args(ns: argparse.Namespace) ->
  "Settings"` (`cls(**vars(ns))`), `Settings.from_cli(argv:
  list[str] | None = None) -> "Settings"` (calls
  `src.args.parseArgs(argv)` then `from_args`).
- Modifies: `src/args.py`'s `parseArgs()` → `parseArgs(argv: list[str] |
  None = None)`, passing `argv` through to `parser.parse_args(argv)`
  (default `None` preserves today's `sys.argv` behavior exactly).

- [ ] **Step 1: Write failing test proving `parseArgs` takes an explicit argv**

```python
def test_parse_args_accepts_explicit_argv():
    ns = parseArgs(["-i", "wlan0", "-P"])
    assert ns.interface == "wlan0"
    assert ns.pixie_dust is True
```

- [ ] **Step 2: Run `pytest tests/test_args.py -v`**

Expected: FAIL — `parseArgs()` takes no arguments.

- [ ] **Step 3: Implement the `argv` parameter in `src/args.py`**

- [ ] **Step 4: Run `pytest tests/test_args.py -v`**

Expected: PASS.

- [ ] **Step 5: Write failing tests for `Settings`**

```python
def test_from_args_mirrors_every_argparse_field():
    ns = parseArgs(["-i", "wlan0", "-B", "-t", "30"])
    s = Settings.from_args(ns)
    assert s.interface == "wlan0"
    assert s.bruteforce is True
    assert s.timeout == 30

def test_from_cli_defaults_match_argparse_defaults():
    s = Settings.from_cli(["-i", "wlan0"])
    assert s.timeout == 60
    assert s.delay == 0
    assert s.vuln_list.endswith("vulnwsc.txt")

def test_settings_field_names_match_args_dest_names():
    ns = parseArgs(["-i", "wlan0"])
    assert set(vars(ns).keys()) == {f.name for f in dataclasses.fields(Settings)}
```

The third test is the drift guard named in the approved design — it fails
loudly the next time someone adds a flag to `args.py` without updating
`Settings`.

- [ ] **Step 6: Run `pytest tests/test_settings.py -v`**

Expected: FAIL — `src.settings` does not exist.

- [ ] **Step 7: Implement `src/settings.py`**

- [ ] **Step 8: Run `pytest tests/test_settings.py -v`**

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/settings.py src/args.py tests/test_settings.py tests/test_args.py
git commit -m "feat: add Settings object and testable parseArgs(argv)"
```

---

### Task 3: FatalError wiring, setup.py extraction, logger event-bus hook

**Files:**
- Modify: `src/utils.py` (`die`)
- Create: `src/setup.py`
- Modify: `ose.py` (extraction call sites, top-level catch)
- Modify: `src/logger.py` (additive hook)
- Test: `tests/test_utils.py`
- Test: `tests/test_setup.py`
- Test: `tests/test_logger.py`

**Interfaces:**
- Consumes: `errors.FatalError` (Task 1).
- Produces: `utils.die(text: str)` now `raise FatalError(text)` instead of
  `sys.exit(...)` (signature unchanged, behavior change documented here).
- Produces: `setup.checkRequirements() -> None`, `setup.setupDirectories()
  -> None`, `setup.setupMediatekWifi(wmt_wifi_device: Path) -> None` —
  verbatim bodies moved out of `ose.py` (same logic, same `FatalError`
  raises via `utils.die`, same log lines). `ose.py`'s `setupAndroidWifi`
  stays in `ose.py` (it's CLI-loop-specific, not reused elsewhere).
- Produces: `logger.set_event_bus(bus: EventBus | None) -> None`,
  `logger.raw(message: str) -> None` (emits an `Event(kind="raw",
  level="info", message=message)` via the bus if one is set, else
  `print(message)` — this is the replacement target for the two
  logger-bypassing `print()` calls fixed in Task 9 and the pixiewps fix in
  Task 9's commit). `info`/`success`/`warning`/`error` each gain one line:
  if a bus is set, also `emit(Event(kind=<name>, level=<name>,
  message=<original text, ANSI-stripped>))` — the existing `_LOGGER.*`
  call and its ANSI-colored console output are unchanged.

- [ ] **Step 1: Write failing test — `die()` raises, doesn't exit**

```python
def test_die_raises_fatal_error_not_sys_exit():
    with pytest.raises(FatalError, match="boom"):
        utils.die("boom")
```

- [ ] **Step 2: Run `pytest tests/test_utils.py -v`**

Expected: FAIL — `die` calls `sys.exit`, pytest sees `SystemExit`, not
`FatalError`.

- [ ] **Step 3: Implement the `die()` change in `src/utils.py`**

- [ ] **Step 4: Run `pytest tests/test_utils.py -v`**

Expected: PASS.

- [ ] **Step 5: Write failing tests for the extracted `setup` functions**
  (mock `shutil.which`, `os.getuid`, `os.path.exists`/`os.makedirs` as
  today's equivalent CLI behavior requires)

```python
def test_check_requirements_dies_on_missing_binary(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda b: None)
    with pytest.raises(FatalError, match="Missing required utilities"):
        setup.checkRequirements()

def test_check_requirements_dies_when_not_root(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda b: "/usr/bin/" + b)
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    with pytest.raises(FatalError, match="Run it as root"):
        setup.checkRequirements()

def test_setup_mediatek_wifi_dies_if_not_char_device(tmp_path):
    fake = tmp_path / "wmtWifi"  # exists as a regular file, not a char device
    fake.touch()
    with pytest.raises(FatalError, match="MediaTek"):
        setup.setupMediatekWifi(fake)
```

- [ ] **Step 6: Run `pytest tests/test_setup.py -v`**

Expected: FAIL — `src.setup` does not exist.

- [ ] **Step 7: Implement `src/setup.py`** (move the three functions'
  bodies verbatim out of `ose.py`; update `ose.py` to import and call
  `src.setup.checkRequirements()` / `src.setup.setupDirectories()` /
  `src.setup.setupMediatekWifi(...)` in place of the old local defs)

- [ ] **Step 8: Run `pytest tests/test_setup.py -v`**

Expected: PASS.

- [ ] **Step 9: Wrap `ose.py`'s `main()` body in
  `try/except FatalError`**

`except FatalError as e: sys.exit(f'[!] {e} \n')` — matches `die()`'s old
exact message format so the CLI's observable behavior is unchanged.

- [ ] **Step 10: Manual smoke check** — run
  `python3 ose.py -i nonexistent0 -P` (as non-root or with a missing
  binary stubbed) and confirm the printed message and exit code are
  byte-identical to the pre-Task-3 behavior.

Expected: identical `[!] ...` message, non-zero exit, no traceback.

- [ ] **Step 11: Write failing tests for the logger hook**

```python
def test_raw_emits_event_when_bus_set():
    bus = EventBus(); seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)
    logger.raw("hello")
    assert seen[0].message == "hello" and seen[0].kind == "raw"
    logger.set_event_bus(None)

def test_raw_prints_when_no_bus(capsys):
    logger.set_event_bus(None)
    logger.raw("hello")
    assert "hello" in capsys.readouterr().out

def test_info_emits_event_when_bus_set():
    bus = EventBus(); seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)
    logger.info("[*] scanning")
    assert any(e.kind == "info" for e in seen)
    logger.set_event_bus(None)

def test_info_console_output_unchanged_when_no_bus(capsys):
    logger.set_event_bus(None)
    logger.info("[*] scanning")
    assert "scanning" in capsys.readouterr().out
```

- [ ] **Step 12: Run `pytest tests/test_logger.py -v`**

Expected: FAIL — `set_event_bus`/`raw` don't exist.

- [ ] **Step 13: Implement the additive hook in `src/logger.py`**

- [ ] **Step 14: Run `pytest tests/test_logger.py -v`**

Expected: PASS.

- [ ] **Step 15: Commit**

```bash
git add src/utils.py src/setup.py src/logger.py ose.py tests/test_utils.py tests/test_setup.py tests/test_logger.py
git commit -m "feat: FatalError wiring, setup.py extraction, logger event-bus hook"
```

---

### Task 4: Settings DI — `src/wifi/scanner.py`

**Files:**
- Modify: `src/wifi/scanner.py`
- Test: `tests/test_scanner.py`

**Interfaces:**
- Consumes: `settings.Settings` (Task 2).
- Produces: `WiFiScanner.__init__(self, interface: str, vuln_list: list[str]
  | None = None, settings: Settings | None = None)` — defaults
  `settings` to `Settings(interface=interface)` if `None` (so existing
  direct instantiations without the new kwarg don't break); every
  `args.*` read in the file becomes `self.settings.*`. The module-level
  `args = src.args.parseArgs()` (currently line 25) is deleted.

- [ ] **Step 1: Write the regression test for the core blocker**

```python
def test_importing_scanner_does_not_parse_sys_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest", "--some-unrelated-flag"])
    importlib.reload(src.wifi.scanner)  # must not raise SystemExit
```

- [ ] **Step 2: Run `pytest tests/test_scanner.py -v`**

Expected: FAIL — reload raises `SystemExit` (argparse sees an unknown
flag and `-i` missing).

- [ ] **Step 3: Delete the module-level `args = src.args.parseArgs()`
  line and thread `settings` through `WiFiScanner` as specified**

- [ ] **Step 4: Run `pytest tests/test_scanner.py -v`**

Expected: PASS.

- [ ] **Step 5: Write a behavioral test proving settings flow through**
  (e.g. `args.clear`/`args.reverse_scan`/`args.verbose` equivalents)

```python
def test_reverse_scan_setting_reverses_network_list_order(monkeypatch):
    # stub _iwScanner's subprocess call to return two canned WPS-enabled
    # networks; assert settings.reverse_scan=True reverses display order
    ...
```

- [ ] **Step 6: Run `pytest tests/test_scanner.py -v`**

Expected: PASS.

- [ ] **Step 7: Manual smoke check** — `python3 ose.py -i wlan0`
  (or a stubbed interface) still reaches the scan step with no traceback.

- [ ] **Step 8: Commit**

```bash
git add src/wifi/scanner.py tests/test_scanner.py
git commit -m "refactor: inject Settings into WiFiScanner, remove module-level parseArgs()"
```

---

### Task 5: Settings DI — `src/wps/connection.py`

**Files:**
- Modify: `src/wps/connection.py`
- Test: `tests/test_connection_settings.py`

**Interfaces:**
- Consumes: `settings.Settings` (Task 2).
- Produces: `connection.Initialize.__init__(self, interface: str,
  settings: Settings | None = None)` — same default-construction fallback
  pattern as Task 4; every `args.*` read (`args.pixie_dust`,
  `args.show_pixie`, `args.pixie_force`, `args.write`, `args.verbose`,
  `args.null_pin`, `args.timeout`) becomes `self.SETTINGS.*`. Module-level
  `args = src.args.parseArgs()` (currently line 30) is deleted.

- [ ] **Step 1: Write the regression test**

```python
def test_importing_connection_does_not_parse_sys_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    importlib.reload(src.wps.connection)
```

- [ ] **Step 2: Run `pytest tests/test_connection_settings.py -v`**

Expected: FAIL — `SystemExit` (missing required `-i`).

- [ ] **Step 3: Delete the module-level call; thread `settings` through
  `Initialize.__init__` and every method that currently reads `args`**

- [ ] **Step 4: Run `pytest tests/test_connection_settings.py -v`**

Expected: PASS.

- [ ] **Step 5: Write a behavioral test** — construct `Initialize` with a
  `Settings(interface="wlan0", timeout=5)` and a monkeypatched
  `_initWpaSupplicant` (no real subprocess), assert the lock-retry sleep
  duration in `_wpsConnection` reads `self.SETTINGS.timeout` (mock
  `time.sleep` and assert it's called with `5`).

- [ ] **Step 6: Run `pytest tests/test_connection_settings.py -v`**

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/wps/connection.py tests/test_connection_settings.py
git commit -m "refactor: inject Settings into connection.Initialize, remove module-level parseArgs()"
```

---

### Task 6: Settings DI — `src/wps/bruteforce.py` + `ose.py` wiring (completes fast-path settings refactor)

**Files:**
- Modify: `src/wps/bruteforce.py`
- Modify: `ose.py`
- Test: `tests/test_bruteforce_settings.py`
- Test: `tests/test_ose_wiring.py`

**Interfaces:**
- Consumes: `settings.Settings` (Task 2), Task 4/5's constructor patterns.
- Produces: `bruteforce.Initialize.__init__(self, interface: str,
  settings: Settings | None = None)`, forwarding `settings` into its
  internal `connection.Initialize(interface, settings)`. Module-level
  `args = src.args.parseArgs()` (currently line 26) deleted; `args.delay`,
  `args.timeout`, `args.loop` reads become `self.settings.*`.
- Modifies `ose.py`: `settings = src.settings.Settings.from_cli()`
  replaces the old `args = src.args.parseArgs()` call; the three
  constructor call sites (`src.wps.bruteforce.Initialize(args.interface)`,
  `src.wps.connection.Initialize(args.interface)`, and the scanner
  construction inside `scanForNetworks`) now pass `settings` through, and
  every remaining `args.*` reference in `ose.py` becomes `settings.*`.

- [ ] **Step 1: Write the regression test for bruteforce.py**

```python
def test_importing_bruteforce_does_not_parse_sys_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    importlib.reload(src.wps.bruteforce)
```

- [ ] **Step 2: Run `pytest tests/test_bruteforce_settings.py -v`**

Expected: FAIL — `SystemExit`.

- [ ] **Step 3: Delete the module-level call; thread `settings` through
  `Initialize.__init__`, forwarding to the internal `connection.Initialize`**

- [ ] **Step 4: Run `pytest tests/test_bruteforce_settings.py -v`**

Expected: PASS.

- [ ] **Step 5: Write the `ose.py` wiring test** — this is the plan's
  explicit core-blocker proof: with Tasks 4–6 complete, importing all
  three modules together under an arbitrary `sys.argv` must not raise.

```python
def test_all_three_engine_modules_import_without_cli_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    importlib.reload(src.wifi.scanner)
    importlib.reload(src.wps.connection)
    importlib.reload(src.wps.bruteforce)  # none of these may raise SystemExit
```

- [ ] **Step 6: Update `ose.py`'s wiring as specified**

- [ ] **Step 7: Run `pytest tests/test_ose_wiring.py -v`**

Expected: PASS.

- [ ] **Step 8: Manual smoke check** — run the CLI's full existing flag
  matrix at least once each (`-P`, `-B`, `-N`, `--pbc`, with `--kill`,
  `--write`, `--loop` toggled where applicable, against a stubbed/absent
  interface so it fails gracefully) and confirm output matches
  pre-refactor behavior exactly (same log lines, same prompts, same exit
  codes). Record the exact commands run and their output in the task's
  commit message or a scratch note — this is the task's primary
  correctness evidence, since `ose.py`'s `main()` itself has no pytest
  coverage.

- [ ] **Step 9: Commit**

```bash
git add src/wps/bruteforce.py ose.py tests/test_bruteforce_settings.py tests/test_ose_wiring.py
git commit -m "refactor: inject Settings into bruteforce.Initialize; wire Settings end-to-end in ose.py"
```

---

### Task 7: Prompter DI — `src/wps/generator.py`

**Files:**
- Modify: `src/wps/generator.py`
- Test: `tests/test_generator.py`

**Interfaces:**
- Consumes: `prompts.Prompter`/`CLIPrompter` (Task 1).
- Produces: `WPSpin.__init__(self, prompter: Prompter | None = None)`
  (defaults to `CLIPrompter()`); `promptPin`'s `input()` retry loop
  (line 143) replaced by `self.prompter.select_index('Select the PIN: ',
  len(candidates))`, with the existing 0-candidate/1-candidate/
  N-candidate branching logic unchanged around it. New method
  `getAllLikely(self, bssid: str) -> list[str]` wrapping the existing
  `_getSuggestedList(bssid)` (same return shape, public name for the
  orchestrator to use in Task 20).

- [ ] **Step 1: Write a golden-value test proving the 24 algorithms are
  byte-identical before and after this refactor** (this is the plan's
  explicit regression guard — run it once against the pre-refactor code
  to capture the table, then keep it green through this and every later
  change)

```python
GOLDEN_BSSIDS = [...]  # a handful of real OUI-prefixed MACs, one per
                        # algorithm family already present in WPSpin.ALGOS

def test_suggested_pins_unchanged_for_known_bssids():
    gen = WPSpin()
    for bssid, expected_pins in GOLDEN_CASES:
        assert gen._getSuggestedList(bssid) == expected_pins
```

- [ ] **Step 2: Run `pytest tests/test_generator.py -v`**

Expected: PASS already (no behavior change yet) — this step exists to
lock in the golden values *before* touching the file, per the plan's risk
note. If it fails here, the test itself is wrong; fix the test, not the
code.

- [ ] **Step 3: Write the failing test for `getAllLikely` and prompter DI**

```python
def test_get_all_likely_wraps_get_suggested_list():
    gen = WPSpin()
    assert gen.getAllLikely("AA:BB:CC:00:00:00") == gen._getSuggestedList("AA:BB:CC:00:00:00")

def test_prompt_pin_uses_injected_prompter():
    fake = FakePrompter(select_index_returns=0)
    gen = WPSpin(prompter=fake)
    # bssid with >1 suggested candidate
    result = gen.promptPin(MULTI_CANDIDATE_BSSID)
    assert fake.select_index_called
    assert result == gen._getSuggested(MULTI_CANDIDATE_BSSID)[0]
```

- [ ] **Step 4: Run `pytest tests/test_generator.py -v`**

Expected: FAIL — `getAllLikely` undefined, `prompter` kwarg rejected.

- [ ] **Step 5: Implement `getAllLikely` and the prompter DI as specified**

- [ ] **Step 6: Run `pytest tests/test_generator.py -v`** (full file,
  including the golden-value test from Step 1)

Expected: PASS — all tests green, golden values unchanged.

- [ ] **Step 7: Commit**

```bash
git add src/wps/generator.py tests/test_generator.py
git commit -m "refactor: inject Prompter into WPSpin, add getAllLikely(), lock golden PIN values"
```

---

### Task 8: Prompter DI — `src/wifi/scanner.py` (`promptNetwork` rewrite)

**Files:**
- Modify: `src/wifi/scanner.py`
- Test: `tests/test_scanner.py` (extend)

**Interfaces:**
- Consumes: `prompts.Prompter`/`CLIPrompter` (Task 1), Task 4's
  `WiFiScanner.__init__`.
- Produces: `WiFiScanner.__init__` gains `prompter: Prompter | None =
  None` (defaults to `CLIPrompter()`). `promptNetwork()`'s `input()` at
  line 68 is replaced by `self.prompter.select_index('Select target
  (press Enter to refresh): ', len(networks), cancel_tokens=frozenset({
  'r', 'R', '0', ''}))`; `None` result → recursive rescan (unchanged
  control flow), an in-range integer result → `(selected['BSSID'],
  selected)` tuple (unchanged return shape).

- [ ] **Step 1: Write the failing test**

```python
def test_prompt_network_returns_selected_bssid_and_info(monkeypatch):
    scanner = WiFiScanner("wlan0", prompter=FakePrompter(select_index_returns=0))
    monkeypatch.setattr(scanner, "_iwScanner", lambda: {1: {"BSSID": "AA:BB:CC:DD:EE:FF", "ESSID": "x"}})
    bssid, info = scanner.promptNetwork()
    assert bssid == "AA:BB:CC:DD:EE:FF"

def test_prompt_network_rescans_on_cancel_token(monkeypatch):
    scanner = WiFiScanner("wlan0", prompter=FakePrompter(select_index_returns=None))
    calls = []
    monkeypatch.setattr(scanner, "_iwScanner", lambda: (calls.append(1), {1: {"BSSID": "x", "ESSID": "y"}})[1] if len(calls) > 1 else {1: {"BSSID": "x", "ESSID": "y"}})
    # cap recursion via a prompter that returns a valid index on the 2nd call
    ...
```

(Implementer's judgment on the exact recursion-termination test shape is
fine as long as it proves: `None` → re-scan happens, a valid index →
returns promptly, no infinite loop in the test itself.)

- [ ] **Step 2: Run `pytest tests/test_scanner.py -v`**

Expected: FAIL — `prompter` kwarg rejected / old `input()`-based flow.

- [ ] **Step 3: Implement the rewrite as specified**

- [ ] **Step 4: Run `pytest tests/test_scanner.py -v`**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wifi/scanner.py tests/test_scanner.py
git commit -m "refactor: inject Prompter into WiFiScanner, replace promptNetwork's input()"
```

---

### Task 9: Prompter DI — `src/wps/connection.py` + the two `print()` bypasses

**Files:**
- Modify: `src/wps/connection.py`
- Modify: `src/wps/pixiewps.py`
- Test: `tests/test_connection_prompts.py`
- Test: `tests/test_pixiewps.py`

**Interfaces:**
- Consumes: `prompts.Prompter`/`CLIPrompter` (Task 1), `logger.raw`
  (Task 3), Task 5's `connection.Initialize.__init__`.
- Produces: `Initialize.__init__` gains `prompter: Prompter | None = None`
  (defaults `CLIPrompter()`); pixie-reuse `input()` at line 121 →
  `self.prompter.confirm(f'Use previously calculated PIN {t_pin}?')`;
  `WPSpin()` construction inside this file becomes
  `generator.WPSpin(prompter=self.PROMPTER)` (propagates to Task 7's DI);
  the verbose passthrough `print(line)` at line 231 → `logger.raw(line)`,
  still gated on `self.SETTINGS.verbose`.
- Produces: `pixiewps.Data.runPixieWps`'s unconditional
  `print(command_output.stdout)` (line 55) → `logger.raw(command_output.stdout)`.

- [ ] **Step 1: Write the failing tests for connection.py's prompter DI**

```python
def test_pixie_reuse_confirm_uses_injected_prompter(monkeypatch):
    fake = FakePrompter(confirm_returns=True)
    conn = make_initialize_with_fakes(prompter=fake)  # helper constructs
                                                        # Initialize with a
                                                        # monkeypatched
                                                        # _initWpaSupplicant
    # seed a saved pixie .run equivalent via a fake session/collector path
    ...
    assert fake.confirm_called

def test_verbose_passthrough_uses_logger_raw(monkeypatch, capsys):
    bus = EventBus(); seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)
    conn = make_initialize_with_fakes(settings=Settings(interface="wlan0", verbose=True))
    conn._handleWpas.__wrapped_call_with_canned_line__("some wpa_supplicant debug line")
    assert any(e.message == "some wpa_supplicant debug line" for e in seen)
    logger.set_event_bus(None)
```

(Exact test helper shape is the implementer's call; the assertions above —
injected prompter is consulted, verbose output flows through
`logger.raw`/the event bus instead of a bare `print` — are the binding
requirement.)

- [ ] **Step 2: Run `pytest tests/test_connection_prompts.py -v`**

Expected: FAIL.

- [ ] **Step 3: Implement the prompter DI and the `print`→`logger.raw`
  fix in `src/wps/connection.py`**

- [ ] **Step 4: Run `pytest tests/test_connection_prompts.py -v`**

Expected: PASS.

- [ ] **Step 5: Write the failing test for pixiewps.py**

```python
def test_run_pixie_wps_output_goes_through_logger_raw(monkeypatch, capsys):
    bus = EventBus(); seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)
    monkeypatch.setattr(subprocess, "run", fake_pixiewps_run_returning("[+] WPS pin: '12345670'"))
    data = Data(); data.BSSID = "AA:BB:CC:DD:EE:FF"  # plus the other 7 required fields, fake values
    pin = data.runPixieWps()
    assert pin == "12345670"
    assert any("WPS pin" in e.message for e in seen)
    logger.set_event_bus(None)
```

- [ ] **Step 6: Run `pytest tests/test_pixiewps.py -v`**

Expected: FAIL — output still goes through a bare `print`, not captured
by the bus.

- [ ] **Step 7: Implement the fix in `src/wps/pixiewps.py`**

- [ ] **Step 8: Run `pytest tests/test_pixiewps.py -v`**

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/wps/connection.py src/wps/pixiewps.py tests/test_connection_prompts.py tests/test_pixiewps.py
git commit -m "refactor: inject Prompter into connection.Initialize; route print() bypasses through logger.raw"
```

---

### Task 10: Prompter DI — `src/wps/bruteforce.py`

**Files:**
- Modify: `src/wps/bruteforce.py`
- Test: `tests/test_bruteforce_prompts.py`

**Interfaces:**
- Consumes: `prompts.Prompter`/`CLIPrompter` (Task 1), Task 6's
  `bruteforce.Initialize.__init__`.
- Produces: `Initialize.__init__` gains `prompter: Prompter | None = None`
  (defaults `CLIPrompter()`, forwarded into the internal
  `connection.Initialize(interface, settings, prompter)`); the
  resume-confirm `input()` at line 166 →
  `self.prompter.confirm(f'Restore previous session for {bssid}?')`.

- [ ] **Step 1: Write the failing test**

```python
def test_resume_confirm_uses_injected_prompter(tmp_path, monkeypatch):
    fake = FakePrompter(confirm_returns=False)
    bf = make_bruteforce_initialize_with_fakes(prompter=fake)
    # seed an existing session file for a BSSID, call smartBruteforce,
    # assert fake.confirm_called and that declining starts fresh (mask == '0000')
    ...
```

- [ ] **Step 2: Run `pytest tests/test_bruteforce_prompts.py -v`**

Expected: FAIL.

- [ ] **Step 3: Implement the prompter DI as specified**

- [ ] **Step 4: Run `pytest tests/test_bruteforce_prompts.py -v`**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wps/bruteforce.py tests/test_bruteforce_prompts.py
git commit -m "refactor: inject Prompter into bruteforce.Initialize"
```

---

### Task 11: `ose.py` prompter wiring (completes the input()/print() refactor)

**Files:**
- Modify: `ose.py`
- Test: `tests/test_ose_wiring.py` (extend)

**Interfaces:**
- Consumes: `prompts.CLIPrompter` (Task 1), Tasks 8–10's `prompter` kwargs.
- Produces: `ose.py` constructs one `CLIPrompter()` alongside its
  `Settings` object and passes it into every scanner/connection/bruteforce
  constructor call; the loop-exit `input()` at line 181 →
  `prompter.confirm_explicit_yes('Exit the script (otherwise continue to
  AP scan)?')`.

- [ ] **Step 1: Write the failing test** — a focused test on `ose.py`'s
  wiring helper (extract the loop-exit decision into a small testable
  function if `main()` itself is too monolithic to call directly in a
  test, e.g. `shouldExitLoop(prompter: Prompter) -> bool`):

```python
def test_loop_exit_prompt_uses_explicit_yes_prompter():
    fake = FakePrompter(confirm_explicit_yes_returns=True)
    assert shouldExitLoop(fake) is True
    assert fake.confirm_explicit_yes_called
```

- [ ] **Step 2: Run `pytest tests/test_ose_wiring.py -v`**

Expected: FAIL.

- [ ] **Step 3: Implement the wiring in `ose.py`** (introduce the small
  `shouldExitLoop` helper if needed for testability; wire `CLIPrompter()`
  through to every constructor call site)

- [ ] **Step 4: Run `pytest tests/test_ose_wiring.py -v`**

Expected: PASS.

- [ ] **Step 5: Manual smoke check** — re-run the same flag matrix as
  Task 6 Step 8 end-to-end; confirm every prompt's visible text and
  default-on-Enter behavior is byte-identical to pre-refactor.

- [ ] **Step 6: Commit**

```bash
git add ose.py tests/test_ose_wiring.py
git commit -m "refactor: wire CLIPrompter through ose.py, replace loop-exit input()"
```

---

### Task 12: `src/wifi/android.py` error-handling fix (independent)

**Files:**
- Modify: `src/wifi/android.py`
- Test: `tests/test_android.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: no signature change. All 5 `subprocess.run` calls in
  `storeAlwaysScanState`/`disableWifi`/`enableWifi` gain `check=True`; each
  call site's `except CalledProcessError` is now reachable and logs via
  `logger.warning`/`logger.error` (matching the existing style already
  used at the one call site that already has `check=True`); a missing
  binary (`FileNotFoundError`) is now also caught and logged instead of
  propagating uncaught.

- [ ] **Step 1: Write the failing tests**

```python
def test_disable_wifi_logs_on_called_process_error(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", raise_called_process_error)
    AndroidNetwork().disableWifi()
    assert "disable" in caplog.text.lower() or "wifi" in caplog.text.lower()

def test_disable_wifi_logs_on_missing_binary(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", raise_file_not_found)
    AndroidNetwork().disableWifi()  # must not raise
    assert caplog.records  # something was logged, not silently swallowed

def test_enable_wifi_logs_on_called_process_error(monkeypatch, caplog):
    ...  # mirror for enableWifi

def test_store_always_scan_state_still_logs_on_error(monkeypatch, caplog):
    ...  # regression: the one call site that already worked keeps working
```

- [ ] **Step 2: Run `pytest tests/test_android.py -v`**

Expected: FAIL — `disableWifi`/`enableWifi` currently swallow
`CalledProcessError` silently (dead except blocks) and propagate
`FileNotFoundError` uncaught.

- [ ] **Step 3: Implement `check=True` + logging on all 5 call sites**

- [ ] **Step 4: Run `pytest tests/test_android.py -v`**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wifi/android.py tests/test_android.py
git commit -m "fix: android.py subprocess calls now surface failures instead of swallowing them"
```

---

### Task 13: Session/persistence layer — `src/session.py`

**Files:**
- Create: `src/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `utils.SESSIONS_DIR`/`utils.PIXIEWPS_DIR` (existing
  constants).
- Produces: `session.TargetRecord` (dataclass: `bssid: str`, `essid: str
  | None`, `state: str` — one of `"pending"`, `"running"`, `"locked"`,
  `"cracked"`, `"failed"`; `last_chain_step: str | None`,
  `bruteforce_mask: str | None`, `pixie_pin: str | None`, `cooldown_until:
  float | None` (epoch seconds), `wps_pin: str | None`, `wpa_psk: str |
  None`, `updated_at: float`).
  `session.SessionStore(db_path: str | os.PathLike | None = None)`
  (defaults to a fixed path under `utils.SESSIONS_DIR`, e.g.
  `<SESSIONS_DIR>/sessions.sqlite3`) with methods:
  `upsert_target(bssid, essid=None) -> None`,
  `set_state(bssid, state: str) -> None`,
  `set_cooldown(bssid, seconds_from_now: float) -> None`,
  `is_cooldown_expired(bssid, now: float | None = None) -> bool` (`True`
  if no cooldown set),
  `update_bruteforce_mask(bssid, mask: str) -> None`,
  `get_bruteforce_mask(bssid) -> str | None`,
  `update_pixie_pin(bssid, pin: str) -> None`,
  `get_pixie_pin(bssid) -> str | None`,
  `clear_pixie_pin(bssid) -> None`,
  `set_last_chain_step(bssid, step: str) -> None`,
  `mark_cracked(bssid, wps_pin: str, wpa_psk: str) -> None`,
  `mark_failed(bssid) -> None`,
  `list_targets() -> list[TargetRecord]`,
  `get_target(bssid) -> TargetRecord | None`.
  Every write method commits immediately (one `sqlite3` connection per
  call, or a single connection opened with
  `isolation_level=None`/autocommit — implementer's choice, as long as
  each write is durable before the method returns, proven by Step 5
  below).
  `session.migrate_legacy_run_files(store: SessionStore, sessions_dir:
  str, pixiewps_dir: str) -> None` — scans `*.run` files under both dirs,
  upserts a `TargetRecord` (BSSID reconstructed by re-inserting `:` every
  2 hex chars from the uppercase filename stem) for each with the file's
  content as `bruteforce_mask` (from `sessions_dir`) or `pixie_pin` (from
  `pixiewps_dir`), then renames the source file to `<name>.run.migrated`.
  A file that is empty, non-UTF-8, or whose content isn't a plausible
  mask/PIN (not purely `[0-9]` for a bruteforce mask of length 4 or 7, not
  purely `[0-9]`/empty for a pixie PIN) is skipped and logged via
  `logger.warning`, not raised.

- [ ] **Step 1: Write failing tests for basic CRUD**

```python
def test_upsert_and_get_target(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF", essid="home")
    t = store.get_target("AA:BB:CC:DD:EE:FF")
    assert t.essid == "home" and t.state == "pending"

def test_set_state_and_list_targets(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    store.set_state("AA:BB:CC:DD:EE:FF", "running")
    assert store.list_targets()[0].state == "running"

def test_mark_cracked_sets_pin_and_psk(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    store.mark_cracked("AA:BB:CC:DD:EE:FF", "12345670", "secretpsk")
    t = store.get_target("AA:BB:CC:DD:EE:FF")
    assert t.state == "cracked" and t.wps_pin == "12345670" and t.wpa_psk == "secretpsk"
```

- [ ] **Step 2: Run `pytest tests/test_session.py -v`**

Expected: FAIL — `src.session` does not exist.

- [ ] **Step 3: Implement the CRUD surface of `SessionStore`**

- [ ] **Step 4: Run `pytest tests/test_session.py -v`**

Expected: PASS.

- [ ] **Step 5: Write the durability test (Review Focus: crash-safety)**

```python
def test_writes_are_durable_across_reopen(tmp_path):
    db = tmp_path / "s.sqlite3"
    store1 = SessionStore(db)
    store1.upsert_target("AA:BB:CC:DD:EE:FF")
    store1.update_bruteforce_mask("AA:BB:CC:DD:EE:FF", "1234567")
    del store1  # no explicit close/flush — simulates a hard kill right after the call returns
    store2 = SessionStore(db)
    assert store2.get_bruteforce_mask("AA:BB:CC:DD:EE:FF") == "1234567"
```

- [ ] **Step 6: Run `pytest tests/test_session.py -v`**

Expected: PASS (if it fails, the write path isn't actually committing
per-call — fix the implementation, not the test).

- [ ] **Step 7: Write the cooldown tests**

```python
def test_cooldown_not_expired_immediately_after_set(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    store.set_cooldown("AA:BB:CC:DD:EE:FF", seconds_from_now=60)
    assert store.is_cooldown_expired("AA:BB:CC:DD:EE:FF", now=1010.0) is False

def test_cooldown_expired_after_elapsed(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    store.set_cooldown("AA:BB:CC:DD:EE:FF", seconds_from_now=60)
    future = time.time() + 61
    assert store.is_cooldown_expired("AA:BB:CC:DD:EE:FF", now=future) is True

def test_no_cooldown_set_means_not_blocked(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    assert store.is_cooldown_expired("AA:BB:CC:DD:EE:FF") is True
```

- [ ] **Step 8: Run `pytest tests/test_session.py -v`**

Expected: FAIL, then implement `set_cooldown`/`is_cooldown_expired`, then
PASS.

- [ ] **Step 9: Write the concurrent-writers test (Review Focus)**

```python
def test_two_connections_write_different_bssids_without_corruption(tmp_path):
    db = tmp_path / "s.sqlite3"
    a, b = SessionStore(db), SessionStore(db)
    a.upsert_target("AA:AA:AA:AA:AA:AA")
    b.upsert_target("BB:BB:BB:BB:BB:BB")
    a.update_bruteforce_mask("AA:AA:AA:AA:AA:AA", "1111111")
    b.update_bruteforce_mask("BB:BB:BB:BB:BB:BB", "2222222")
    c = SessionStore(db)
    assert c.get_bruteforce_mask("AA:AA:AA:AA:AA:AA") == "1111111"
    assert c.get_bruteforce_mask("BB:BB:BB:BB:BB:BB") == "2222222"
```

If sqlite's default locking causes a transient `OperationalError` under
this interleaving, catch-and-retry-once inside the write methods (sqlite's
own busy-timeout, `PRAGMA busy_timeout=...`, is the simplest fix) — the
test must pass without the caller needing to know about retries.

- [ ] **Step 10: Run `pytest tests/test_session.py -v`**

Expected: FAIL, then implement the busy-timeout/retry, then PASS.

- [ ] **Step 11: Write the migration tests (Review Focus: malformed
  legacy files)**

```python
def test_migrate_converts_valid_bruteforce_mask_file(tmp_path):
    sessions_dir = tmp_path / "sessions"; sessions_dir.mkdir()
    (sessions_dir / "AABBCCDDEEFF.run").write_text("1234567")
    store = SessionStore(tmp_path / "s.sqlite3")
    migrate_legacy_run_files(store, str(sessions_dir), str(tmp_path / "pixiewps"))
    assert store.get_bruteforce_mask("AA:BB:CC:DD:EE:FF") == "1234567"
    assert (sessions_dir / "AABBCCDDEEFF.run.migrated").exists()
    assert not (sessions_dir / "AABBCCDDEEFF.run").exists()

def test_migrate_skips_malformed_file_without_raising(tmp_path, caplog):
    sessions_dir = tmp_path / "sessions"; sessions_dir.mkdir()
    (sessions_dir / "BADFILE000000.run").write_bytes(b"\xff\xfe not utf8 \x00")
    store = SessionStore(tmp_path / "s.sqlite3")
    migrate_legacy_run_files(store, str(sessions_dir), str(tmp_path / "pixiewps"))  # must not raise
    assert store.get_target("BA:DF:IL:E0:00:00") is None
    assert caplog.records

def test_migrate_is_idempotent(tmp_path):
    sessions_dir = tmp_path / "sessions"; sessions_dir.mkdir()
    (sessions_dir / "AABBCCDDEEFF.run").write_text("1234567")
    store = SessionStore(tmp_path / "s.sqlite3")
    migrate_legacy_run_files(store, str(sessions_dir), str(tmp_path / "pixiewps"))
    migrate_legacy_run_files(store, str(sessions_dir), str(tmp_path / "pixiewps"))  # no .run left; must not raise
```

- [ ] **Step 12: Run `pytest tests/test_session.py -v`**

Expected: FAIL, then implement `migrate_legacy_run_files`, then PASS.

- [ ] **Step 13: Commit**

```bash
git add src/session.py tests/test_session.py
git commit -m "feat: add sqlite-backed SessionStore with crash-safe writes and legacy .run migration"
```

---

### Task 14: Session DI — `src/wps/bruteforce.py` mask persistence

**Files:**
- Modify: `src/wps/bruteforce.py`
- Test: `tests/test_bruteforce_session.py`

**Interfaces:**
- Consumes: `session.SessionStore` (Task 13), Task 10's
  `bruteforce.Initialize.__init__`.
- Produces: `Initialize.__init__` gains `session: SessionStore | None =
  None` (defaults to constructing a `SessionStore()` with its default
  path if `None`, so existing callers keep working). `smartBruteforce`'s
  file read (the old `open(filename).readline()`) becomes
  `self.session.get_bruteforce_mask(bssid)`; the end-of-run file write
  (line 190-191) becomes `self.session.update_bruteforce_mask(bssid,
  self.BRUTEFORCE_STATUS.MASK)`. The resume-confirm prompt from Task 10
  now fires based on whether `get_bruteforce_mask` returns non-`None`
  instead of `FileNotFoundError`.

- [ ] **Step 1: Write the failing tests**

```python
def test_smart_bruteforce_resumes_from_session_store(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    store.update_bruteforce_mask("AA:BB:CC:DD:EE:FF", "1234567")
    fake_prompter = FakePrompter(confirm_returns=True)
    bf = make_bruteforce_initialize_with_fakes(session=store, prompter=fake_prompter)
    # assert the resumed mask used to seed _secondHalfBruteforce is "1234567"
    ...

def test_smart_bruteforce_persists_mask_on_exit(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    bf = make_bruteforce_initialize_with_fakes(session=store)
    # drive a short fake bruteforce run that exits via the existing
    # self-raised KeyboardInterrupt path
    ...
    assert store.get_bruteforce_mask("AA:BB:CC:DD:EE:FF") is not None
```

- [ ] **Step 2: Run `pytest tests/test_bruteforce_session.py -v`**

Expected: FAIL — still reads/writes the old `.run` text file.

- [ ] **Step 3: Implement the session DI as specified**

- [ ] **Step 4: Run `pytest tests/test_bruteforce_session.py -v`**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wps/bruteforce.py tests/test_bruteforce_session.py
git commit -m "refactor: back bruteforce resume with SessionStore instead of a plain-text .run file"
```

---

### Task 15: Session DI — `src/wps/connection.py` pixie-PIN persistence + `collector.py` cleanup

**Files:**
- Modify: `src/wps/connection.py`
- Modify: `src/wifi/collector.py`
- Modify: `src/setup.py` (wire the migration call)
- Test: `tests/test_connection_session.py`
- Test: `tests/test_collector.py`
- Test: `tests/test_setup.py` (extend)

**Interfaces:**
- Consumes: `session.SessionStore` (Task 13), Task 9's
  `connection.Initialize.__init__`.
- Produces: `Initialize.__init__` gains `session: SessionStore | None =
  None` (same default-construction pattern as Task 14). The pixie-PIN
  save-on-abort path (`collector.writePin(bssid, pin)`, currently inside
  the `KeyboardInterrupt` handler at line ~140) becomes
  `self.session.update_pixie_pin(bssid, pin)`; the pixie-reuse read
  (currently reading `PIXIEWPS_DIR/<bssid>.run`) becomes
  `self.session.get_pixie_pin(bssid)`; the delete-on-success (currently
  removing the `.run` file after `GOT_PSK`) becomes
  `self.session.clear_pixie_pin(bssid)`.
- Removes `collector.WiFiCollector.writePin` (now dead); `writeResult`
  is unmodified (unrelated — it's the success-report CSV/TXT, not resume
  state).
- `setup.setupDirectories()` additionally calls
  `session.migrate_legacy_run_files(SessionStore(), utils.SESSIONS_DIR,
  utils.PIXIEWPS_DIR)` after the existing `~/.OSE` rename logic.

- [ ] **Step 1: Write the failing tests for connection.py**

```python
def test_pixie_pin_saved_to_session_on_abort(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    conn = make_initialize_with_fakes(session=store)
    # drive an abort path that previously called collector.writePin
    ...
    assert store.get_pixie_pin("AA:BB:CC:DD:EE:FF") is not None

def test_pixie_pin_cleared_on_success(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    store.update_pixie_pin("AA:BB:CC:DD:EE:FF", "12345670")
    conn = make_initialize_with_fakes(session=store)
    # drive a success path that previously deleted the .run file
    ...
    assert store.get_pixie_pin("AA:BB:CC:DD:EE:FF") is None
```

- [ ] **Step 2: Run `pytest tests/test_connection_session.py -v`**

Expected: FAIL.

- [ ] **Step 3: Implement the session DI in `connection.py`**

- [ ] **Step 4: Run `pytest tests/test_connection_session.py -v`**

Expected: PASS.

- [ ] **Step 5: Delete `WiFiCollector.writePin` and its now-unused import
  of `src.utils.PIXIEWPS_DIR` if nothing else in the file needs it; write
  a test proving `writeResult` still works unmodified**

```python
def test_write_result_unaffected_by_write_pin_removal(tmp_path, monkeypatch):
    monkeypatch.setattr(src.utils, "REPORTS_DIR", str(tmp_path) + "/")
    WiFiCollector.writeResult("AA:BB:CC:DD:EE:FF", "home", "12345670", "secretpsk")
    assert (tmp_path / "stored.csv").exists()
    assert not hasattr(WiFiCollector, "writePin")
```

- [ ] **Step 6: Run `pytest tests/test_collector.py -v`**

Expected: PASS.

- [ ] **Step 7: Write the failing test for the migration wiring**

```python
def test_setup_directories_runs_legacy_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(src.utils, "SESSIONS_DIR", str(tmp_path / "sessions") + "/")
    monkeypatch.setattr(src.utils, "PIXIEWPS_DIR", str(tmp_path / "pixiewps") + "/")
    os.makedirs(tmp_path / "sessions")
    (tmp_path / "sessions" / "AABBCCDDEEFF.run").write_text("1234567")
    setup.setupDirectories()
    store = SessionStore()  # default path, now pointed at the monkeypatched SESSIONS_DIR
    assert store.get_bruteforce_mask("AA:BB:CC:DD:EE:FF") == "1234567"
```

- [ ] **Step 8: Run `pytest tests/test_setup.py -v`**

Expected: FAIL — migration not wired yet.

- [ ] **Step 9: Wire the migration call into `setup.setupDirectories()`**

- [ ] **Step 10: Run `pytest tests/test_setup.py -v`**

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/wps/connection.py src/wifi/collector.py src/setup.py tests/test_connection_session.py tests/test_collector.py tests/test_setup.py
git commit -m "refactor: back pixie-PIN resume with SessionStore; wire legacy migration into setupDirectories"
```

---

### Task 16: `retry_on_lock` threading through `connection.py` (orchestrator prerequisite)

**Files:**
- Modify: `src/wps/connection.py`
- Test: `tests/test_connection_retry_on_lock.py`

**Interfaces:**
- Consumes: Task 15's `connection.Initialize`.
- Produces: `Initialize.singleConnection(self, bssid=None, pin=None,
  pbc_mode=False, store_pin_on_fail=False, retry_on_lock: bool = True)` —
  threaded into both calls it makes into `_wpsConnection(...,
  retry_on_lock=retry_on_lock)` **and** into its own recursive
  pixie-verification call (`self.singleConnection(bssid, pin,
  store_pin_on_fail=True, retry_on_lock=retry_on_lock)`) — the plan's
  explicitly flagged easy-to-miss spot.

- [ ] **Step 1: Write the failing test proving the recursive call inherits
  the flag**

```python
def test_retry_on_lock_false_propagates_into_recursive_pixie_call(monkeypatch):
    conn = make_initialize_with_fakes()
    calls = []
    original = conn._wpsConnection
    monkeypatch.setattr(conn, "_wpsConnection", lambda *a, **kw: (calls.append(kw.get("retry_on_lock")), original(*a, **kw))[1])
    # drive a path where pixie data is complete, forcing the recursive
    # singleConnection(..., store_pin_on_fail=True) call
    conn.singleConnection(bssid="AA:BB:CC:DD:EE:FF", retry_on_lock=False)
    assert all(v is False for v in calls)  # every _wpsConnection call, including the recursive one, saw False
```

- [ ] **Step 2: Run `pytest tests/test_connection_retry_on_lock.py -v`**

Expected: FAIL — `retry_on_lock` kwarg doesn't exist yet, or the
recursive call doesn't forward it.

- [ ] **Step 3: Implement the parameter threading as specified**

- [ ] **Step 4: Run `pytest tests/test_connection_retry_on_lock.py -v`**

Expected: PASS.

- [ ] **Step 5: Run the full existing connection.py test files from
  Tasks 5, 9, 15, 16 together** to confirm the new parameter's default
  (`True`) preserves every prior test's behavior unchanged.

Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/wps/connection.py tests/test_connection_retry_on_lock.py
git commit -m "feat: thread retry_on_lock through singleConnection, including its recursive pixie call"
```

---

### Task 17: `_attemptPin` extraction in `src/wps/bruteforce.py` (pure refactor, isolated per plan's risk note)

**Files:**
- Modify: `src/wps/bruteforce.py`
- Test: `tests/test_bruteforce_attempt_pin.py`

**Interfaces:**
- Consumes: Task 14's `bruteforce.Initialize`.
- Produces: `Initialize._attemptPin(self, bssid: str, pin: str) -> str`
  containing the shared "try one pin via `self.CONNECTION.singleConnection`,
  interpret the result against `ConnectionStatus`" body currently
  duplicated between `_firstHalfBruteforce` and `_secondHalfBruteforce`
  (lock detection, `WPS_FAIL` retry-same-value, success check). Both
  methods are rewritten to call `self._attemptPin(bssid, pin)` in place of
  their inlined logic — **no new behavior**, this task only moves code.

- [ ] **Step 1: Write a before/after behavioral-equivalence test against
  a fake connection** (capture the exact sequence of
  `singleConnection`/`sleep`/status-check calls `_firstHalfBruteforce`
  makes today, for a scripted fake that returns lock-then-fail-then-success
  across 3 calls)

```python
def test_first_half_bruteforce_call_sequence_unchanged(monkeypatch):
    fake_conn = ScriptedFakeConnection(results=["LOCKED", "WPS_FAIL", "VALID_FIRST_HALF"])
    bf = make_bruteforce_initialize_with_fakes(connection=fake_conn)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    result = bf._firstHalfBruteforce("AA:BB:CC:DD:EE:FF", 0)
    assert fake_conn.call_log == EXPECTED_CALL_LOG  # captured from the
                                                      # pre-extraction
                                                      # implementation by
                                                      # running this test
                                                      # against it first
    assert result == EXPECTED_FIRST_HALF
```

- [ ] **Step 2: Run `pytest tests/test_bruteforce_attempt_pin.py -v`
  against the CURRENT (pre-extraction) code to capture `EXPECTED_CALL_LOG`**

Expected: the test passes against today's implementation — this run is
how `EXPECTED_CALL_LOG`/`EXPECTED_FIRST_HALF` get their values. Hardcode
the captured values into the test before proceeding.

- [ ] **Step 3: Extract `_attemptPin` and rewrite
  `_firstHalfBruteforce`/`_secondHalfBruteforce` to use it, changing no
  observable behavior**

- [ ] **Step 4: Run `pytest tests/test_bruteforce_attempt_pin.py -v`**

Expected: PASS — identical call log and result, proving the extraction
changed nothing observable.

- [ ] **Step 5: Run the full bruteforce test suite (Tasks 10, 14, 16's
  tests plus this one)**

Expected: PASS, no regressions.

- [ ] **Step 6: Commit** (isolated, as its own commit per the plan's risk
  note — do not combine with Task 18's new behavior)

```bash
git add src/wps/bruteforce.py tests/test_bruteforce_attempt_pin.py
git commit -m "refactor: extract _attemptPin from _firstHalfBruteforce/_secondHalfBruteforce (no behavior change)"
```

---

### Task 18: `bruteforceStep` — new non-blocking bruteforce entry point for the orchestrator

**Files:**
- Modify: `src/wps/bruteforce.py`
- Test: `tests/test_bruteforce_step.py`

**Interfaces:**
- Consumes: Task 17's `_attemptPin`.
- Produces: `Initialize.bruteforceStep(self, bssid: str, mask: str) ->
  tuple[str, str | None]` — attempts exactly **one** pin derived from
  `mask` (4-digit → tries that first-half value; 7-digit → tries that
  full first+second-half value) via `self._attemptPin`, returns
  `(new_state, result)` where `new_state` is one of `"advanced"`
  (try the next mask value), `"locked"`, `"first_half_found"` (mask should
  become the 7-digit form), `"cracked"` (result is the full 8-digit PIN),
  or `"exhausted"` (mask range exceeded); does **not** sleep, loop, or
  write to the session itself — the orchestrator (Task 19) owns scheduling
  and persistence, this method owns exactly one attempt's interpretation.

- [ ] **Step 1: Write the failing tests for each `new_state` outcome**

```python
def test_bruteforce_step_advances_on_plain_failure():
    bf = make_bruteforce_initialize_with_fakes(connection=FakeConnection(returns="WPS_FAIL_OTHER"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000")
    assert state == "advanced" and result is None

def test_bruteforce_step_reports_locked():
    bf = make_bruteforce_initialize_with_fakes(connection=FakeConnection(returns="LOCKED"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000")
    assert state == "locked"

def test_bruteforce_step_reports_first_half_found():
    bf = make_bruteforce_initialize_with_fakes(connection=FakeConnection(returns="VALID_FIRST_HALF"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0000")
    assert state == "first_half_found"

def test_bruteforce_step_reports_cracked_with_full_pin():
    bf = make_bruteforce_initialize_with_fakes(connection=FakeConnection(returns="GOT_PSK"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "0001234")
    assert state == "cracked" and result is not None and len(result) == 8

def test_bruteforce_step_exhausted_at_range_end():
    bf = make_bruteforce_initialize_with_fakes(connection=FakeConnection(returns="WPS_FAIL_OTHER"))
    state, result = bf.bruteforceStep("AA:BB:CC:DD:EE:FF", "9999")
    assert state == "exhausted"
```

- [ ] **Step 2: Run `pytest tests/test_bruteforce_step.py -v`**

Expected: FAIL — `bruteforceStep` doesn't exist.

- [ ] **Step 3: Implement `bruteforceStep` on top of `_attemptPin`**

- [ ] **Step 4: Run `pytest tests/test_bruteforce_step.py -v`**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wps/bruteforce.py tests/test_bruteforce_step.py
git commit -m "feat: add non-blocking bruteforceStep() for orchestrator-driven single attempts"
```

---

### Task 19: Orchestrator — auto-chain + multi-target queue

**Files:**
- Create: `src/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `settings.Settings` (Task 2), `session.SessionStore`
  (Task 13), `connection.Initialize` (Task 16's `retry_on_lock`),
  `bruteforce.Initialize.bruteforceStep` (Task 18),
  `generator.WPSpin.getAllLikely` (Task 7), `events.EventBus` (Task 1).
- Produces: `orchestrator.ChainStep` (`enum.Enum`: `NULL_PIN`,
  `PIXIE_DUST`, `DEFAULT_PINS`, `BRUTEFORCE`). `orchestrator.Target`
  (dataclass: `bssid: str`, `essid: str | None`). `orchestrator.
  AutoConfirmPrompter(Prompter)` — `confirm`/`confirm_explicit_yes`
  always return `True`, `select_index` always returns `0` (first
  candidate) — documented as "unattended steps never block on a human."
  `orchestrator.Orchestrator(interface: str, base_settings: Settings,
  session: SessionStore | None = None, event_bus: EventBus | None = None,
  connection_factory=connection.Initialize,
  bruteforce_factory=bruteforce.Initialize,
  generator_factory=generator.WPSpin)` with:
  `enqueue(bssid: str, essid: str | None = None) -> None`,
  `enqueue_many(targets: list[Target]) -> None`,
  `run(stop_flag: threading.Event | None = None) -> None` (blocking;
  caller runs it on a background thread), `stop() -> None` (sets an
  internal stop flag checked between attempts), `get_queue_snapshot() ->
  list[TargetRecord]`.

**Scheduling logic** (implement exactly as specified, it's the task's
core behavior):
1. For `step` in `[NULL_PIN, PIXIE_DUST, DEFAULT_PINS]`: for each target
   currently `pending` (or `running` with `last_chain_step < step`) whose
   cooldown has expired, attempt `step` once via one shared, long-lived
   `connection_factory(interface, base_settings)` instance, toggling
   `base_settings.null_pin`/`base_settings.pixie_dust` appropriately
   before each call (restoring both to `False` after, so one step's flags
   never leak into the next); on success call
   `session.mark_cracked(...)` and remove the target from further steps;
   on lock call `session.set_cooldown(bssid, base_settings.timeout)` and
   move to the next target (no sleep); on any other failure, record
   `last_chain_step = step` and continue to the next target. For
   `DEFAULT_PINS`, iterate `generator_factory().getAllLikely(bssid)`; an
   empty list is a no-op for that target (falls through to the next step
   untouched — Review Focus item).
2. Once no target remains `pending`/eligible for steps 1–3, for
   `BRUTEFORCE`: process remaining targets sequentially (one target fully
   exhausts its mask, or gets cracked, or hits `stop_flag`, before moving
   to the next), using `bruteforce_factory(interface, base_settings,
   session=session).bruteforceStep(bssid, mask)` in a loop seeded from
   `session.get_bruteforce_mask(bssid)` (default `"0000"`), persisting
   the advancing mask via `session.update_bruteforce_mask` after every
   step; on `"locked"`, `session.set_cooldown(...)` and move to the next
   remaining target, revisiting this one later once its cooldown expires
   and the current pass over remaining targets completes.
3. `run()` checks `stop_flag.is_set()` between every single attempt (not
   just between targets) so `stop()` is responsive mid-sweep.
4. Any `FatalError` raised by a factory call is caught inside `run()`,
   turned into `event_bus.emit(Event(kind="fatal_error", level="error",
   message=str(e), data={"bssid": bssid}))`, and that target is marked
   `session.mark_failed(bssid)` — `run()` itself does not re-raise, so a
   `FatalError` on one target never kills the whole queue (Review Focus
   item).

- [ ] **Step 1: Write the failing test for breadth-first ordering**

```python
def test_fast_steps_run_breadth_first_across_targets():
    fake_conn_factory = ScriptedConnectionFactory(
        # target A fails null_pin+pixie+default, target B fails the same —
        # the call log must show A's null_pin, B's null_pin, A's pixie,
        # B's pixie, A's default, B's default — not A-then-B depth-first
        script={"AA:AA:AA:AA:AA:AA": "always_fail", "BB:BB:BB:BB:BB:BB": "always_fail"}
    )
    orch = Orchestrator("wlan0", Settings(interface="wlan0"),
                         session=InMemorySessionStore(),
                         connection_factory=fake_conn_factory)
    orch.enqueue("AA:AA:AA:AA:AA:AA"); orch.enqueue("BB:BB:BB:BB:BB:BB")
    orch.run()
    assert fake_conn_factory.call_order == EXPECTED_BREADTH_FIRST_ORDER
```

- [ ] **Step 2: Run `pytest tests/test_orchestrator.py -v`**

Expected: FAIL — `src.orchestrator` does not exist.

- [ ] **Step 3: Implement `Orchestrator` and the breadth-first fast-step
  scheduling (steps 1 above) only — bruteforce pass comes next**

- [ ] **Step 4: Run `pytest tests/test_orchestrator.py -v`**

Expected: PASS.

- [ ] **Step 5: Write the failing test for stop-at-first-success**

```python
def test_chain_stops_at_first_success_pixie_dust():
    fake = ScriptedConnectionFactory(script={"AA:AA:AA:AA:AA:AA": "null_pin_fails_pixie_succeeds"})
    orch = Orchestrator("wlan0", Settings(interface="wlan0"), session=InMemorySessionStore(), connection_factory=fake)
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()
    assert orch.session.get_target("AA:AA:AA:AA:AA:AA").state == "cracked"
    assert fake.call_order == ["null_pin", "pixie_dust"]  # default_pins and bruteforce never attempted
```

- [ ] **Step 6: Run, implement the stop-at-first-success check, re-run**

Expected: FAIL then PASS.

- [ ] **Step 7: Write the failing test for the empty-suggestion-list case
  (Review Focus item)**

```python
def test_default_pins_step_skips_cleanly_when_no_suggestions():
    fake_gen_factory = lambda: FakeGenerator(getAllLikely_returns=[])
    fake_conn = ScriptedConnectionFactory(script={"AA:AA:AA:AA:AA:AA": "null_pin_fails_pixie_fails"})
    orch = Orchestrator("wlan0", Settings(interface="wlan0"), session=InMemorySessionStore(),
                         connection_factory=fake_conn, generator_factory=fake_gen_factory)
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()  # must not raise; target proceeds to BRUTEFORCE, not treated as cracked or as an error
    assert orch.session.get_target("AA:AA:AA:AA:AA:AA").state != "cracked"
```

- [ ] **Step 8: Run, verify/implement the empty-list skip, re-run**

Expected: PASS.

- [ ] **Step 9: Write the failing test for lock→cooldown→revisit**

```python
def test_locked_target_is_requeued_and_revisited_after_cooldown(monkeypatch):
    clock = FakeClock(start=1000.0)
    monkeypatch.setattr(time, "time", clock.now)
    fake = ScriptedConnectionFactory(script={"AA:AA:AA:AA:AA:AA": "locked_once_then_fails"})
    orch = Orchestrator("wlan0", Settings(interface="wlan0", timeout=5), session=InMemorySessionStore(), connection_factory=fake)
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.enqueue("BB:BB:BB:BB:BB:BB")  # a second target so the queue has somewhere to go meanwhile
    clock.advance(6)  # past the cooldown before run() ever checks it
    orch.run()
    assert fake.call_order.index("AA:AA:AA:AA:AA:AA:null_pin") < fake.call_order.index("BB:BB:BB:BB:BB:BB:null_pin")
    assert "AA:AA:AA:AA:AA:AA:pixie_dust" in fake.call_order  # revisited, not abandoned
```

- [ ] **Step 10: Run, implement cooldown-aware requeueing, re-run**

Expected: PASS.

- [ ] **Step 11: Write the failing test for the settings-mutation Review
  Focus item**

```python
def test_toggling_settings_between_steps_does_not_leak_into_next_step():
    seen_flags = []
    def recording_connection_factory(interface, settings):
        seen_flags.append((settings.null_pin, settings.pixie_dust))
        return FakeConnection(returns="always_fail")
    base = Settings(interface="wlan0")
    orch = Orchestrator("wlan0", base, session=InMemorySessionStore(), connection_factory=recording_connection_factory)
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()
    assert seen_flags[0] == (True, False)   # NULL_PIN step
    assert seen_flags[1] == (False, True)   # PIXIE_DUST step
    assert base.null_pin is False and base.pixie_dust is False  # restored after the sweep
```

- [ ] **Step 12: Run, fix any flag-leak, re-run**

Expected: PASS.

- [ ] **Step 13: Write the failing test for `FatalError` isolation
  (Review Focus item)**

```python
def test_fatal_error_on_one_target_does_not_kill_the_run():
    def raising_factory(interface, settings):
        raise FatalError("missing binary")
    bus = EventBus(); seen = []
    bus.subscribe(lambda e: seen.append(e))
    orch = Orchestrator("wlan0", Settings(interface="wlan0"), session=InMemorySessionStore(),
                         event_bus=bus, connection_factory=raising_factory)
    orch.enqueue("AA:AA:AA:AA:AA:AA")
    orch.run()  # must return normally, not raise
    assert any(e.kind == "fatal_error" for e in seen)
    assert orch.session.get_target("AA:AA:AA:AA:AA:AA").state == "failed"
```

- [ ] **Step 14: Run, implement the catch-and-emit, re-run**

Expected: PASS.

- [ ] **Step 15: Write the failing tests for the bruteforce pass
  (sequential, one target at a time, cracked stops it, `stop_flag`
  responsive)**

```python
def test_bruteforce_pass_runs_sequentially_after_fast_steps_exhausted():
    ...  # two targets both fail all fast steps; assert bruteforceStep calls
         # for target A run to completion/crack before target B's begin

def test_run_honors_stop_flag_mid_sweep():
    stop = threading.Event()
    fake = ScriptedConnectionFactory(script={"AA:AA:AA:AA:AA:AA": "always_fail", "BB:BB:BB:BB:BB:BB": "always_fail"},
                                      on_call=lambda *_: stop.set())  # stop fires after the very first attempt
    orch = Orchestrator("wlan0", Settings(interface="wlan0"), session=InMemorySessionStore(), connection_factory=fake)
    orch.enqueue("AA:AA:AA:AA:AA:AA"); orch.enqueue("BB:BB:BB:BB:BB:BB")
    orch.run(stop_flag=stop)
    assert len(fake.call_order) == 1  # stopped after the first attempt, not after a full sweep
```

- [ ] **Step 16: Run, implement, re-run**

Expected: PASS for both.

- [ ] **Step 17: Run the full `tests/test_orchestrator.py` file**

Expected: all tests PASS.

- [ ] **Step 18: Commit**

```bash
git add src/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add Orchestrator with breadth-first auto-chain queue and lock-cooldown requeueing"
```

---

### Task 20: GUI presenters (pure, unit-testable data mapping — no `termuxgui` import)

**Files:**
- Create: `src/gui/__init__.py`
- Create: `src/gui/presenters.py`
- Test: `tests/test_gui_presenters.py`

**Interfaces:**
- Consumes: the network dict shape returned by
  `scanner.WiFiScanner._iwScanner()` (keys: `ESSID`, `Security type`,
  `WPS`, `WPS version`, `WPS locked`, `Model`, `Model number`, `Device
  name`, `BSSID`, `Level`), `session.TargetRecord` (Task 13),
  `events.Event` (Task 1).
- Produces (all pure functions, no I/O, no `termuxgui` import — this file
  is the one piece of the GUI layer with real unit coverage):
  `presenters.format_network_row(network: dict) -> dict` (returns display
  fields: `label: str` (e.g. `"ESSID (BSSID) -45dBm"`), `highlight: str`
  one of `"stored"`, `"vulnerable_version"`, `"locked"`,
  `"vulnerable_model"`, `"none"` — same priority order as the existing
  CLI table's highlighting logic in `scanner.py`).
  `presenters.format_queue_row(record: TargetRecord) -> dict` (`label:
  str`, `status_text: str`, `progress_percent: int | None` — derived from
  `bruteforce_mask` using the same 11000-unit-keyspace formula as
  `BruteforceStatus.displayStatus` when `state == "running"` and a mask is
  present, else `None`).
  `presenters.format_log_line(event: Event) -> str` (ANSI-stripped,
  single display line, e.g. `f"[{event.level.upper()}] {event.message}"`).

- [ ] **Step 1: Write the failing tests for `format_network_row`**

```python
def test_format_network_row_highlights_locked():
    row = format_network_row({"ESSID": "x", "BSSID": "AA:BB:CC:DD:EE:FF", "Level": -50, "WPS locked": True, "WPS version": "2.0", "Model": "", "Model number": "", "Device name": ""})
    assert row["highlight"] == "locked"

def test_format_network_row_highlights_vulnerable_version_over_model():
    row = format_network_row({"ESSID": "x", "BSSID": "AA:BB:CC:DD:EE:FF", "Level": -50, "WPS locked": False, "WPS version": "1.0", "Model": "KnownVulnModel", "Model number": "", "Device name": ""})
    assert row["highlight"] == "vulnerable_version"  # priority order matches scanner.py
```

- [ ] **Step 2: Run `pytest tests/test_gui_presenters.py -v`**

Expected: FAIL.

- [ ] **Step 3: Implement `format_network_row`**

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Write the failing tests for `format_queue_row`**

```python
def test_format_queue_row_progress_percent_matches_bruteforce_formula():
    record = TargetRecord(bssid="x", essid="y", state="running", bruteforce_mask="5000", ...)
    row = format_queue_row(record)
    assert row["progress_percent"] == pytest.approx(int(5000/11000*100))

def test_format_queue_row_no_progress_when_not_running():
    record = TargetRecord(bssid="x", essid="y", state="cracked", bruteforce_mask=None, ...)
    assert format_queue_row(record)["progress_percent"] is None
```

- [ ] **Step 6: Run, implement, re-run — expect PASS**

- [ ] **Step 7: Write the failing tests for `format_log_line`**

```python
def test_format_log_line_strips_ansi_and_formats_level():
    line = format_log_line(Event(kind="warning", level="warning", message="\x1b[1;33m[-] locked\x1b[0m"))
    assert line == "[WARNING] [-] locked"
```

- [ ] **Step 8: Run, implement, re-run — expect PASS**

- [ ] **Step 9: Commit**

```bash
git add src/gui/__init__.py src/gui/presenters.py tests/test_gui_presenters.py
git commit -m "feat: add pure, unit-tested GUI presenter functions"
```

---

### Task 21: `GuiPrompter` (defined for interface completeness, not used by the decided auto-chain/PBC flows)

**Files:**
- Create: `src/gui/prompter.py`
- Test: `tests/test_gui_prompter.py`

**Interfaces:**
- Consumes: `prompts.Prompter` (Task 1).
- Produces: `gui.prompter.GuiPrompter(Prompter)` constructed with an
  injected `dialog_opener: Callable[[str, list[str] | None], str |
  None]` (a function that, given a message and an optional list of
  choice labels, returns the user's typed/selected response as a string,
  or `None` if the user cancelled — this is the seam a real `termuxgui`
  binding fills with an `Activity(c, dialog=True)` call; this task tests
  only the `GuiPrompter` logic against a fake `dialog_opener`, never a
  real `termuxgui.Connection`). Implements `confirm`/`confirm_explicit_yes`
  by mapping the opener's string response to a bool (same default-on-empty
  semantics as `CLIPrompter`), and `select_index` by mapping the chosen
  label back to its index.
- **Explicitly not wired into the `Orchestrator`** (which uses
  `AutoConfirmPrompter`, Task 19) or the PBC flow (which doesn't need pin
  resolution) — add a module docstring saying so plainly, per the
  approved plan's note that a future contributor should not "fix" this by
  routing confirmation dialogs into the unattended auto-chain.

- [ ] **Step 1: Write the failing tests**

```python
def test_confirm_maps_opener_response_to_bool(monkeypatch):
    opener = lambda msg, choices: "y"
    assert GuiPrompter(dialog_opener=opener).confirm("ok?") is True

def test_confirm_default_yes_on_none_response():
    opener = lambda msg, choices: None
    assert GuiPrompter(dialog_opener=opener).confirm("ok?") is True

def test_select_index_maps_chosen_label_back_to_index():
    opener = lambda msg, choices: choices[1]
    assert GuiPrompter(dialog_opener=opener).select_index("pick", 3) == 1

def test_select_index_none_on_cancel():
    opener = lambda msg, choices: None
    assert GuiPrompter(dialog_opener=opener).select_index("pick", 3) is None
```

- [ ] **Step 2: Run `pytest tests/test_gui_prompter.py -v`**

Expected: FAIL.

- [ ] **Step 3: Implement `GuiPrompter`**

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/gui/prompter.py tests/test_gui_prompter.py
git commit -m "feat: add GuiPrompter (unused by auto-chain/PBC by design; see module docstring)"
```

---

### Task 22: Termux:GUI binding layer + `ose_gui.py` entrypoint (integration glue — no plugin available to test against)

**Files:**
- Create: `src/gui/app.py`
- Create: `src/gui/scan_screen.py`
- Create: `src/gui/queue_screen.py`
- Create: `src/gui/log_screen.py`
- Create: `src/gui/pbc_screen.py`
- Create: `ose_gui.py`
- Create: `requirements-dev.txt`
- Modify: `README.md`
- Test: `tests/test_gui_app_import.py`

**Interfaces:**
- Consumes: `presenters.*` (Task 20), `GuiPrompter`/module docstring
  (Task 21), `orchestrator.Orchestrator` (Task 19), `connection.Initialize`
  (for the standalone PBC screen), `events.EventBus` (Task 1).
- Produces: `gui/app.py`'s `main() -> None` — builds one `TabLayout` over
  Scan/Queue/Log/PBC screens, runs the `Orchestrator` and the PBC flow
  each on their own background thread (mutually exclusive via a shared
  `threading.Lock` guarding the one radio), subscribes an `EventBus`
  listener that pushes onto a `queue.Queue` drained only by the main
  thread's `for ev in c.events()` loop (per the approved plan's threading
  rule — View objects are touched only from that thread). `ose_gui.py`:
  `from src.gui.app import main; if __name__ == '__main__': main()`.
  `requirements-dev.txt`: `pytest`. README gains an install/launch section
  (Termux + Termux:GUI plugin app, `pip install termuxgui`,
  `sudo python ose_gui.py`).

Because `termuxgui` cannot be installed/connected-to in the implementation
environment (no plugin, no Android), this task's only automated test
proves the module **structure** is sound, not its runtime behavior against
a real plugin:

- [ ] **Step 1: Write the failing structural test** (stub `termuxgui` in
  `sys.modules` so the import succeeds without the real package, then
  assert the expected public surface exists)

```python
def test_gui_app_module_imports_and_exposes_main(monkeypatch):
    stub = types.ModuleType("termuxgui")
    # populate `stub` with no-op stand-ins for every tg.* name app.py/
    # scan_screen.py/etc. reference at import time (Connection, Activity,
    # LinearLayout, Button, TextView, EditText, Checkbox, ProgressBar,
    # NestedScrollView, SwipeRefreshLayout, TabLayout, Event, ...) so the
    # modules import cleanly without a real connection ever being opened
    monkeypatch.setitem(sys.modules, "termuxgui", stub)
    import importlib
    app = importlib.import_module("src.gui.app")
    assert callable(app.main)
```

- [ ] **Step 2: Run `pytest tests/test_gui_app_import.py -v`**

Expected: FAIL — modules don't exist yet.

- [ ] **Step 3: Implement `gui/scan_screen.py`, `gui/queue_screen.py`,
  `gui/log_screen.py`, `gui/pbc_screen.py`, `gui/app.py`, `ose_gui.py` per
  the interfaces above.** Each screen module's widget-construction and
  event-dispatch code calls into `presenters.*` (Task 20) for all display
  formatting — no formatting logic duplicated here. Add a short comment
  at the top of `gui/app.py` pointing at this task's test and at the
  on-device verification list below, so a reader understands why this
  file has only an import-smoke test.

- [ ] **Step 4: Run `pytest tests/test_gui_app_import.py -v`**

Expected: PASS.

- [ ] **Step 5: Create `requirements-dev.txt` and add the README
  install/launch section**

- [ ] **Step 6: Run the full test suite one more time
  (`pytest tests/ -v`)**

Expected: every test from Tasks 1–22 passes together.

- [ ] **Step 7: Document the required on-device follow-up** (add this
  exact list to the README's new GUI section, since it cannot be executed
  here): real Termux:GUI rendering/event delivery/dialogs/notifications;
  the Scan screen against a live `iw` scan; the Queue screen driving a
  real `Orchestrator.run()` against live `wpa_supplicant`/`pixiewps`; the
  PBC screen against a real router button press; backgrounding/battery
  behavior during a long queue run; a `kill -9` mid-bruteforce crash-safety
  check against the real `SessionStore` file.

- [ ] **Step 8: Commit**

```bash
git add src/gui/app.py src/gui/scan_screen.py src/gui/queue_screen.py src/gui/log_screen.py src/gui/pbc_screen.py ose_gui.py requirements-dev.txt README.md tests/test_gui_app_import.py
git commit -m "feat: add Termux:GUI binding layer (scan/queue/log/PBC screens) and ose_gui.py entrypoint"
```

---

## Self-review (performed before handoff)

1. **Spec coverage:** every numbered item in the approved design doc's
   Phases 0–6 maps to a task above (Phase 0→Tasks 1–2, Phase 1→Task 3,
   Phase 2A→Tasks 4–6, Phase 2B→Tasks 7–11, Phase 3→Task 12, Phase
   4→Tasks 13–15, Phase 5→Tasks 16–19, Phase 6→Tasks 20–22). No gaps
   found.
2. **Step scan:** every step either names an exact test/assertion, an
   exact signature, a verification command with expected output, or
   points at another task's Interfaces block — no "TBD"/"handle edge
   cases" lines.
3. **Type consistency:** `Settings`, `Prompter`, `EventBus`/`Event`,
   `SessionStore`/`TargetRecord`, and the `connection_factory`/
   `bruteforce_factory`/`generator_factory` callable signatures are used
   identically by every later task that consumes them; checked against
   each Interfaces block while writing Tasks 4–22.
4. **Review Focus:** all five listed items have an owning task with a
   test exercising them (empty-suggestion-list → Task 19 Step 7;
   malformed-legacy-file → Task 13 Step 11; concurrent-writers → Task 13
   Step 9; settings-mutation-leak → Task 19 Step 11;
   `FatalError`-off-main-thread → Task 19 Step 13).
5. **Proportion:** task bodies use signatures, test names, and assertions
   rather than full implementation code throughout; the few inline code
   blocks are either tiny pure values (the `FatalError` class) or
   algorithms the spec pins exactly (the breadth-first/cooldown scheduling
   in Task 19, which the design doc specifies at this level of detail).
