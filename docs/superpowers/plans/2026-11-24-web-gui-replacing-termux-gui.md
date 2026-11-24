# Web GUI (FastAPI) Replacing Termux:GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `src/gui/` Termux:GUI binding layer with a local FastAPI web app (`src/web/`, `ose_web.py`) that reuses the existing engine (`Settings`, `Prompter`, `EventBus`, `SessionStore`, `Orchestrator`) unchanged.

**Architecture:** A `create_app()` factory builds a FastAPI app around already-constructed engine objects stored on `app.state` (mirrors `Orchestrator`'s own dependency-injection pattern, so tests build the app around fakes without root/real hardware). Route modules are thin wrappers over existing engine methods; a `QueueRunner` class (a direct, framework-agnostic port of the old `QueueScreen`'s threading logic) owns the background run-loop; one SSE endpoint streams `EventBus` events, doubling as the signal the frontend uses to refetch queue state. `ose_web.py` is the one real wiring point, mirroring `ose.py`'s role for the CLI.

**Tech Stack:** FastAPI, uvicorn, Python stdlib `threading`/`queue`. No new deps for the core engine. No build step (plain HTML/CSS/vanilla JS).

**Spec:** `docs/superpowers/specs/2026-11-24-web-gui-port-design.md`

## Global Constraints

- Bind host is `127.0.0.1` only — never `0.0.0.0`, no auth system.
- No Node.js/npm build pipeline; the frontend is plain HTML/CSS/JS served as static files.
- No new `Prompter` subclass: the `Orchestrator` keeps using `AutoConfirmPrompter`; PBC never resolves pins.
- `ose_web.py` still requires root via `setup.checkRequirements()`'s existing `os.getuid() != 0` check, reused as-is.
- `requirements-web.txt` holds exactly `fastapi` and `uvicorn` — no other new runtime deps anywhere in this plan.
- No SSE backlog/replay buffer: a (re)connecting client re-fetches current state via a plain GET; the log feed only shows events from the moment it connects.
- `ose_web.py` never auto-launches a browser — it prints the URL and exits the wiring step; the server then blocks on `uvicorn.run(...)`.
- The interface stays hardcoded to `wlan0` (`DEFAULT_INTERFACE`) — no in-page interface picker.
- Default port: `8000`.

## Review Focus

- **SSE client disconnect must not leak a subscription.** A browser tab closing or reloading must unsubscribe its `EventBus` listener; repeated page loads must not grow the subscriber list unboundedly. Covered in Task 6.
- **Concurrent Start clicks (two tabs, near-simultaneous) must still only start one run-loop**, the same way a double-click within one tab already must (ported behavior, now also exercised across two separate HTTP requests against the one shared `QueueRunner`). Covered in Task 4.
- **`/api/scan` returning zero WPS-capable networks must return a clean empty list**, not an error — mirrors the orchestrator's own "empty vendor-PIN suggestion list" handling at a different layer. Covered in Task 5.
- **PBC while the queue is running must fail clearly, not silently.** The old GUI's PBC screen logged a warning and returned nothing visible to the user on a radio-busy condition; the HTTP API must return a non-200 response with a clear message instead of a silent no-op. Covered in Task 7.
- **A `FatalError` raised inside PBC's background thread must surface as a log-visible `Event`, not vanish as an uncaught thread exception.** The old `pbc_screen.py` never caught `FatalError` around its `connection_factory`/`singleConnection` calls at all — a pre-existing gap from Termux:GUI being carried forward here, fixed this time to match how `Orchestrator` already isolates `FatalError` per-target. Covered in Task 7.

---

## Task 1: Move `presenters.py` out of `src/gui/`

**Files:**
- Move: `src/gui/presenters.py` → `src/presenters.py`
- Move: `tests/test_gui_presenters.py` → `tests/test_presenters.py`
- Modify: `src/gui/scan_screen.py:25`, `src/gui/queue_screen.py:35`, `src/gui/log_screen.py:25` (import line only)

**Interfaces:**
- Produces: `src.presenters.format_network_row(network: dict) -> dict`, `format_queue_row(record: TargetRecord) -> dict`, `format_log_line(event: Event) -> str` — same signatures as before, new import path `from src import presenters`.

- [ ] **Step 1: Move the files**

```bash
git mv src/gui/presenters.py src/presenters.py
git mv tests/test_gui_presenters.py tests/test_presenters.py
```

- [ ] **Step 2: Update the moved test file's import** (`from src.gui import presenters` → `from src import presenters`)

- [ ] **Step 3: Update the three Termux:GUI files' import lines** to `from src import presenters` (still-live code must keep working until Task 9 deletes it)

- [ ] **Step 4: Run the full suite**

Run: `pytest tests/ -v`
Expected: all tests pass (same count as before — nothing added or removed yet), with `tests/test_presenters.py` now running from its new path.

- [ ] **Step 5: Commit**

```bash
git add src/presenters.py tests/test_presenters.py src/gui/scan_screen.py src/gui/queue_screen.py src/gui/log_screen.py
git commit -m "refactor: move presenters.py out of src/gui/ (UI-agnostic, no reason to live under it)"
```

---

## Task 2: `QueueRunner` — background run-loop controller

**Files:**
- Create: `src/web/__init__.py` (empty, just makes `src.web` a package)
- Create: `src/web/queue_runner.py`
- Test: `tests/test_web_queue_runner.py`

**Interfaces:**
- Consumes: `orchestrator.Orchestrator` (`.run()`, `.stop()` — unchanged, Task 19).
- Produces: `QueueRunner(orchestrator, radio_lock: threading.Lock = None, poll_interval: float = 5.0)` with `start() -> None`, `stop() -> None`, `is_running() -> bool`. Same threading/re-entrancy/radio-lock/repeated-run-loop behavior `src/gui/queue_screen.py`'s `QueueScreen._start`/`_run_loop` already had — this is a direct port with the GUI/termuxgui coupling removed (that class never actually touched `tg.*` in its threading logic, only `threading`/the orchestrator, so the port is mechanical). `is_running()` is new (`self._run_thread is not None and self._run_thread.is_alive()`), needed so the web API can report run/stopped state — nothing else changes.

- [ ] **Step 1: Write the failing tests** — port the 4 existing tests from `tests/test_gui_queue_screen.py` (`test_start_holds_radio_lock_for_the_duration_of_the_run`, `test_double_click_start_does_not_launch_a_second_run`, `test_start_runs_repeatedly_until_stopped`, `test_start_can_run_again_after_being_stopped`) against `QueueRunner` directly — same fake-orchestrator/`threading.Event` synchronization patterns, no `termuxgui` stub needed at all this time. Add one new test:

```python
def test_is_running_reflects_loop_state():
    started = threading.Event()
    release = threading.Event()

    class FakeOrchestrator:
        def run(self):
            started.set()
            release.wait(timeout=2)
        def stop(self):
            pass

    runner = QueueRunner(FakeOrchestrator(), radio_lock=threading.Lock(), poll_interval=0.01)
    assert runner.is_running() is False
    runner.start()
    assert started.wait(timeout=2)
    assert runner.is_running() is True
    release.set()
    runner.stop()
    runner._run_thread.join(timeout=2)
    assert runner.is_running() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_queue_runner.py -v`
Expected: FAIL — `src.web.queue_runner` doesn't exist.

- [ ] **Step 3: Implement `QueueRunner`** — copy `QueueScreen`'s `__init__`/`_start`/`_run_loop`/`on_click`'s stop-branch logic (minus every `tg.*`/view-construction line and the `on_click` dispatch itself), add `is_running()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_queue_runner.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/web/__init__.py src/web/queue_runner.py tests/test_web_queue_runner.py
git commit -m "feat: add QueueRunner, a framework-agnostic port of QueueScreen's run-loop"
```

---

## Task 3: App skeleton — `create_app()` factory + `ose_web.py` entrypoint

**Files:**
- Create: `src/web/app.py`
- Create: `ose_web.py`
- Create: `requirements-web.txt`
- Test: `tests/test_web_app.py`

**Interfaces:**
- Consumes: `Settings` (Task 2 of the original plan), `Orchestrator` (Task 19), `QueueRunner` (Task 2 above), `src.wifi.scanner.WiFiScanner`, `EventBus`, `src.wps.connection.Initialize`, `src.setup.checkRequirements`/`setupDirectories`, `src.errors.FatalError`.
- Produces: `create_app(interface: str, settings: Settings, orchestrator: Orchestrator, queue_runner: QueueRunner, scanner: WiFiScanner, event_bus: EventBus, radio_lock: threading.Lock, connection_factory=connection.Initialize) -> FastAPI`. Stores every one of those (plus `interface`) as same-named attributes on `app.state` (`app.state.settings`, `app.state.orchestrator`, `app.state.queue_runner`, `app.state.scanner`, `app.state.event_bus`, `app.state.radio_lock`, `app.state.connection_factory`, `app.state.interface`) — every later task's routes read their dependencies from `request.app.state.*` by these exact names. Registers one route for now: `GET /api/health -> {"status": "ok"}`.
- `ose_web.py`: `main()` catches `FatalError` the same way `ose.py`/the old `ose_gui.py` did (`sys.exit(f'[!] {e} \n')`); `_run()` calls `checkRequirements()`, `setupDirectories()`, constructs `Settings(interface=DEFAULT_INTERFACE)`, an `EventBus` (wired via `logger.set_event_bus`), an `Orchestrator`, a `QueueRunner`, a `WiFiScanner`, a `threading.Lock()`, calls `create_app(...)`, prints `f"Open http://{HOST}:{PORT} in your browser"`, then `uvicorn.run(app, host=HOST, port=PORT)`. Constants: `DEFAULT_INTERFACE = "wlan0"`, `HOST = "127.0.0.1"`, `PORT = 8000`.

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from src.web.app import create_app
# construct create_app(...) with fakes for every param; see existing
# tests/test_orchestrator.py's fakes for the Orchestrator/session pattern

def test_health_check_returns_ok():
    app = create_app("wlan0", fake_settings, fake_orchestrator, fake_queue_runner,
                      fake_scanner, fake_event_bus, threading.Lock())
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_app.py -v`
Expected: FAIL — `src.web.app` doesn't exist.

- [ ] **Step 3: Implement `create_app()` and `ose_web.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_web_app.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py ose_web.py requirements-web.txt tests/test_web_app.py
git commit -m "feat: add FastAPI app skeleton and ose_web.py entrypoint"
```

---

## Task 4: Queue routes

**Files:**
- Create: `src/web/routes_queue.py`
- Modify: `src/web/app.py` (register the router)
- Test: `tests/test_web_routes_queue.py`

**Interfaces:**
- Consumes: `app.state.orchestrator` (`.enqueue(bssid, essid)`, `.get_queue_snapshot() -> list[TargetRecord]`), `app.state.queue_runner` (`.start()`, `.stop()`, `.is_running()`), `src.presenters.format_queue_row`.
- Produces: `APIRouter` with:
  - `GET /api/queue/targets` → `{"running": bool, "targets": [{"bssid": str, "label": str, "status_text": str, "progress_percent": int | None}, ...]}` (each target dict is `format_queue_row(record)` plus `"bssid": record.bssid`).
  - `POST /api/queue/targets` body `EnqueueRequest{bssid: str, essid: str | None = None}` → calls `orchestrator.enqueue(bssid, essid)`, returns `201 {"status": "enqueued"}`.
  - `POST /api/queue/start` → calls `queue_runner.start()`, returns `202 {"status": "started"}`.
  - `POST /api/queue/stop` → calls `queue_runner.stop()`, returns `202 {"status": "stopped"}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_get_targets_returns_running_state_and_formatted_rows():
    # inject a fake orchestrator whose get_queue_snapshot() returns one
    # TargetRecord and whose queue_runner.is_running() returns True
    ...
    assert response.json() == {"running": True, "targets": [{"bssid": "...", "label": "...", "status_text": "...", "progress_percent": None}]}

def test_post_targets_enqueues_on_orchestrator():
    # fake orchestrator records enqueue(bssid, essid) calls
    response = client.post("/api/queue/targets", json={"bssid": "AA:BB:CC:DD:EE:FF", "essid": "home"})
    assert response.status_code == 201
    assert fake_orchestrator.enqueue_calls == [("AA:BB:CC:DD:EE:FF", "home")]

def test_post_start_calls_queue_runner_start():
    # fake queue_runner records start() was called — does NOT re-test
    # QueueRunner's own threading behavior, that's Task 2's job
    ...

def test_post_stop_calls_queue_runner_stop():
    ...

def test_two_near_simultaneous_start_requests_only_start_one_run():
    # Review Focus: concurrent Start clicks from two tabs. Use a real
    # QueueRunner (not a fake) wrapping a fake orchestrator whose run()
    # blocks on an Event, fire two POST /api/queue/start calls from two
    # threads, then assert the fake orchestrator's run() was entered
    # exactly once while the first call is still in flight.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_routes_queue.py -v`
Expected: FAIL — route module doesn't exist.

- [ ] **Step 3: Implement `routes_queue.py`, register it in `create_app()`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_routes_queue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/routes_queue.py src/web/app.py tests/test_web_routes_queue.py
git commit -m "feat: add Queue API routes (targets/enqueue/start/stop)"
```

---

## Task 5: Scan routes

**Files:**
- Create: `src/web/routes_scan.py`
- Modify: `src/web/app.py` (register the router)
- Test: `tests/test_web_routes_scan.py`

**Interfaces:**
- Consumes: `app.state.scanner` (`WiFiScanner._iwScanner() -> dict[int, dict] | bool`, `.STORED: list[tuple]`, `.VULN_LIST`), `src.presenters.format_network_row`.
- Produces: `APIRouter` with `GET /api/scan` → `[{"bssid": str, "essid": str, "label": str, "highlight": str}, ...]`. For each network dict `_iwScanner()` returns, compute `_stored`/`_vulnerable_model` exactly as `src/gui/scan_screen.py:_render()` did (`(bssid, essid) in scanner.STORED`; `f'{Model} {Model number}' in scanner.VULN_LIST or Device name in scanner.VULN_LIST`) before calling `format_network_row`. `_iwScanner()` returning `False` or `{}` → return `[]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_scan_returns_formatted_networks_with_bssid_and_essid():
    # fake scanner._iwScanner() returns one network dict
    ...

def test_scan_returns_empty_list_when_no_networks_found():
    # Review Focus: fake scanner._iwScanner() returns False
    response = client.get("/api/scan")
    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_routes_scan.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `routes_scan.py`, register it in `create_app()`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_routes_scan.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/routes_scan.py src/web/app.py tests/test_web_routes_scan.py
git commit -m "feat: add Scan API route"
```

---

## Task 6: SSE events route

**Files:**
- Create: `src/web/routes_events.py`
- Modify: `src/web/app.py` (register the router)
- Test: `tests/test_web_routes_events.py`

**Interfaces:**
- Consumes: `app.state.event_bus` (`EventBus.subscribe(fn) -> unsubscribe`, Task 1 of the original plan), `src.presenters.format_log_line`.
- Produces: `APIRouter` with `GET /api/events` → `StreamingResponse(media_type="text/event-stream")`. The generator subscribes its own `queue.Queue` to `event_bus` on entry, yields `f"data: {format_log_line(event)}\n\n"` for each event drained from that queue, and calls the `unsubscribe()` callback in a `finally` block so a disconnecting client (the generator receiving `GeneratorExit`, which Starlette raises into a `StreamingResponse` generator when the client disconnects) doesn't leak a subscription.

- [ ] **Step 1: Write the failing tests**

```python
def test_events_stream_yields_formatted_log_lines():
    # Use a real EventBus (not a fake — subscribe/emit must really run).
    # TestClient's streaming support: open the response as a context
    # manager, emit one Event on the bus from the test, iter_lines()/
    # iter_content() once, assert the formatted line appears, then close
    # the response.
    ...

def test_disconnecting_client_unsubscribes_from_event_bus():
    # Open and then close/exit the streaming response; assert the
    # EventBus's subscriber count (or a directly-observable side effect,
    # e.g. emitting afterward and asserting nothing was enqueued to the
    # now-unsubscribed queue) shows the subscription was removed.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_routes_events.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `routes_events.py`, register it in `create_app()`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_routes_events.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/routes_events.py src/web/app.py tests/test_web_routes_events.py
git commit -m "feat: add SSE /api/events route, unsubscribing on client disconnect"
```

---

## Task 7: PBC route

**Files:**
- Create: `src/web/routes_pbc.py`
- Modify: `src/web/app.py` (register the router)
- Test: `tests/test_web_routes_pbc.py`

**Interfaces:**
- Consumes: `app.state.radio_lock`, `app.state.connection_factory`, `app.state.interface`, `app.state.settings`, `app.state.event_bus`, `src.errors.FatalError`, `src.wps.connection.Initialize.singleConnection(bssid=, pbc_mode=True)`.
- Produces: `run_pbc_once(interface: str, settings: Settings, radio_lock: threading.Lock, connection_factory, bssid: str | None, event_bus: EventBus) -> None` — tries `radio_lock.acquire(blocking=False)`; on failure, emits `Event(kind='pbc_busy', level='warning', message='PBC: radio busy (queue is running)')` and returns; otherwise, in `try/finally` (release the lock in `finally`): calls `connection_factory(interface, settings).singleConnection(bssid=bssid, pbc_mode=True)`, catching `FatalError` and emitting `Event(kind='fatal_error', level='error', message=str(e))` — mirrors `Orchestrator._run_bruteforce_for_target`'s existing `except FatalError` isolation pattern exactly.
  `APIRouter` with `POST /api/pbc/start` body `PbcRequest{bssid: str | None = None}`: if `radio_lock.locked()`, return `409 {"detail": "radio busy (queue is running)"}` immediately (best-effort fast response — the spawned thread's own `acquire(blocking=False)` is the real authoritative check, so a narrow race between this check and the thread starting still ends up correctly reported via the `pbc_busy` event on the log feed); otherwise spawn `threading.Thread(target=run_pbc_once, args=(...), daemon=True).start()` and return `202 {"status": "started"}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_pbc_once_emits_busy_event_when_lock_held():
    locked_lock = threading.Lock()
    locked_lock.acquire()
    seen = []
    bus = EventBus(); bus.subscribe(lambda e: seen.append(e))
    run_pbc_once("wlan0", fake_settings, locked_lock, fake_connection_factory, None, bus)
    assert any(e.kind == "pbc_busy" for e in seen)

def test_run_pbc_once_calls_single_connection_with_bssid_and_pbc_mode():
    ...

def test_run_pbc_once_emits_fatal_error_event_instead_of_raising():
    def raising_factory(interface, settings):
        raise FatalError("missing binary")
    seen = []
    bus = EventBus(); bus.subscribe(lambda e: seen.append(e))
    run_pbc_once("wlan0", fake_settings, threading.Lock(), raising_factory, None, bus)  # must not raise
    assert any(e.kind == "fatal_error" for e in seen)

def test_post_pbc_start_returns_409_when_radio_locked():
    # app.state.radio_lock already held
    response = client.post("/api/pbc/start", json={"bssid": None})
    assert response.status_code == 409

def test_post_pbc_start_spawns_thread_when_lock_free():
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_routes_pbc.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `run_pbc_once` and the route, register it in `create_app()`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_routes_pbc.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/routes_pbc.py src/web/app.py tests/test_web_routes_pbc.py
git commit -m "feat: add PBC API route, fixing the FatalError-swallowing gap carried from Termux:GUI"
```

---

## Task 8: Frontend — static page

**Files:**
- Create: `src/web/static/index.html`, `src/web/static/app.js`, `src/web/static/style.css`
- Modify: `src/web/app.py` (mount `StaticFiles(directory=..., html=True)` at `/`, registered **after** every `/api/*` router — mounting order matters, an earlier catch-all mount would shadow the API routes)
- Test: `tests/test_web_static.py`

**Interfaces:**
- Consumes: every route from Tasks 4-7 by their exact paths/shapes above.
- Produces: one page with four tabs (Scan/Queue/Log/PBC — CSS-only or minimal-JS tab switching, builder's call). `app.js` behavior: on load and on every SSE message, `fetch('/api/queue/targets')` and re-render the Queue tab; a Scan button `fetch('/api/scan')` and render checkboxes, each row's "add" action `POST /api/queue/targets`; Start/Stop buttons `POST /api/queue/start` / `/stop`; one `new EventSource('/api/events')` whose `onmessage` both appends the line to the Log tab and triggers the queue refetch above; a PBC form `POST /api/pbc/start`, showing the server's `detail` message on a non-2xx response.

- [ ] **Step 1: Write the failing test**

```python
def test_index_page_serves_and_contains_expected_tabs():
    response = client.get("/")
    assert response.status_code == 200
    for expected in ("Scan", "Queue", "Log", "PBC"):
        assert expected in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_static.py -v`
Expected: FAIL — `/` 404s (no static mount yet).

- [ ] **Step 3: Implement the three static files and mount them**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_web_static.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/static/ src/web/app.py tests/test_web_static.py
git commit -m "feat: add the web GUI's single-page frontend"
```

---

## Task 9: Delete the Termux:GUI layer, update README, final verification

**Files:**
- Delete: `src/gui/app.py`, `src/gui/scan_screen.py`, `src/gui/queue_screen.py`, `src/gui/log_screen.py`, `src/gui/pbc_screen.py`, `src/gui/prompter.py`, `src/gui/__init__.py`, `ose_gui.py`
- Delete: `tests/test_gui_app_import.py`, `tests/test_gui_queue_screen.py`, `tests/test_gui_prompter.py`
- Modify: `README.md`

**Interfaces:** none — this task only removes dead code and prose; nothing in `src/web/` references anything under `src/gui/` after Task 1.

- [ ] **Step 1: Delete the files**

```bash
git rm -r src/gui/ ose_gui.py tests/test_gui_app_import.py tests/test_gui_queue_screen.py tests/test_gui_prompter.py
```

- [ ] **Step 2: Replace README's "GUI (Termux:GUI)" section with a "GUI (Web)" section** — install (`pip install -r requirements-web.txt`), launch (`sudo python ose_web.py`, then open the printed `http://127.0.0.1:8000` URL in your browser), and a shortened on-device follow-up list (no plugin-app handshake to verify this time): real `iw`/`wpa_supplicant`/`pixiewps` behavior behind the Scan/Queue/PBC routes, backgrounding/battery behavior during a long queue run, a `kill -9` mid-bruteforce crash-safety check against the real `SessionStore` file.

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v`
Expected: every test from this plan's Tasks 1-8 plus every pre-existing engine test (Settings/Prompter/EventBus/SessionStore/Orchestrator/wifi/wps/etc.) passes together; zero references to `src.gui`/`termuxgui` remain (`grep -rl "src.gui\|termuxgui" src/ tests/ ose_web.py` returns nothing).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "feat: remove Termux:GUI layer, replaced by the web GUI"
```
