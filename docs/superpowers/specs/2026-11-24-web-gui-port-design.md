# OneShot-Extended: Web GUI (FastAPI) replacing Termux:GUI

## Context

OneShot-Extended's 22-task Termux:GUI implementation (branch merged to
`master`) built a full engine/UI split: `Settings`, `Prompter`, `EventBus`,
`SessionStore`, and `Orchestrator` carry zero dependency on any specific UI
technology, and a `src/gui/` package (`app.py`, `scan_screen.py`,
`queue_screen.py`, `log_screen.py`, `pbc_screen.py`, `prompter.py`,
`presenters.py`) bound that engine to Termux:GUI (`termuxgui` PyPI package
+ the Termux:GUI plugin app).

On-device testing (the one thing that couldn't be verified from the
implementation sandbox) surfaced a chain of real, confirmed problems:
`termux-am`'s providing package varies across Termux installs/mirrors
(`termux-tools`, `termux-am-socket`, or a `termux-am` package that
confusingly installs its binary as plain `am`) — each was found and fixed
in turn via `dpkg -L`/`which` diagnostics run on the user's own device.
After routing around the binary-lookup problem, `termuxgui`'s
`Connection()` still fails: the `am broadcast` to the plugin's
`GUIReceiver` runs without error, but the listening Unix sockets never see
a connection, timing out on both the primary attempt and the library's own
`am` fallback, with no diagnostic surfaced (the library discards
`am`'s stdout/stderr). Whether this is a root-vs-non-root UID mismatch, a
plugin-app-side issue, or something else, couldn't be pinned down further
without the user doing more invasive device-side debugging, and three
rounds of back-and-forth guessing a fix from documentation (not direct
observation) is where this stopped being worth continuing.

**Decision:** replace `src/gui/` entirely with a local FastAPI web app,
served over `localhost` and opened in the device's own browser. Everything
below the (now-deleted) GUI layer — the whole engine — carries over
unchanged; only the UI binding is being swapped.

## Goals

- A mobile-browser UI providing the same functional surface the
  Termux:GUI layer targeted: a Scan screen, a Queue screen (enqueue
  targets, Start/Stop the auto-chain, live per-target status/progress), a
  Log screen (live engine event feed), and a PBC screen (manual
  single-target push-button attempt, outside the queue — same rule as
  before: PBC needs a human physically pressing the router's button, so
  it's never queued/unattended).
- Real, automated behavioral tests for every route, using FastAPI's
  `TestClient` — genuinely proving request/response behavior, not just
  import structure (the ceiling Termux:GUI's own tests were stuck at).
- `sudo python ose_web.py` launches it, exactly mirroring `sudo python
  ose.py`'s existing root requirement. No privilege-separation work: a
  TCP socket bind doesn't care about the binding process's UID the way
  Termux:GUI's broadcast-based IPC apparently does — this removes the
  entire class of problem the last three rounds were chasing.
- Zero new deps for the core engine; FastAPI/uvicorn are GUI-only runtime
  deps, the same precedent `termuxgui` set (and is now replacing).

## Non-goals / anti-goals

- Not exposed beyond `127.0.0.1` — no LAN/remote access, no auth system.
  The browser runs on the same phone as the server; there's no reason a
  WPS-attack control panel should be reachable from the rest of the
  network.
- Not a rewrite of any engine behavior. `Orchestrator`, `SessionStore`,
  `connection.py`, `bruteforce.py` are untouched.
- Not a feature expansion beyond what Termux:GUI was scoped to do — no
  new attack modes, no remote/scripting API, no multi-user concerns.
- Not keeping `src/gui/` around "just in case." It's deleted outright
  (`presenters.py`'s pure formatting functions move out first, since
  they were always UI-agnostic — see Decisions). Maintaining two parallel,
  competing UI layers serves no one.
- Not another attempt to diagnose the Termux:GUI connection failure.
  That path is abandoned per the user's explicit decision.

## Constraints

- `ose_web.py` still requires root (`checkRequirements()`'s existing
  `os.getuid() != 0` check, reused as-is) — the underlying
  `wpa_supplicant`/`pixiewps`/`iw`/`ip` calls are unchanged and still need
  it.
- No Node.js/npm build pipeline. Termux compatibility and the project's
  existing "no heavy toolchain" ethos both argue against it.
- All live server→browser updates route through the existing
  `EventBus`/`Event` dataclass — reused, not reinvented.
- No new Prompter subclass. The Orchestrator already uses
  `AutoConfirmPrompter` (unattended) and PBC never needed pin resolution,
  exactly as under Termux:GUI — a future contributor should not invent a
  "WebPrompter" and wire it into either flow by mistake (this mirrors
  `GuiPrompter`'s own now-deleted module docstring warning, worth
  repeating here since the reason still applies).

## Approaches considered

1. **FastAPI + Server-Sent Events + a plain HTML/vanilla-JS page —
   chosen.** FastAPI (the technology the user named) gives clean async
   route handlers and built-in streaming-response support; SSE is a
   one-way push, which is all the live log/queue feed needs (every
   client→server action — enqueue, start, stop, pick a scan result — is a
   discrete command that maps naturally onto a normal POST endpoint); a
   plain page with a small amount of vanilla JS needs no build step, no
   npm, nothing new to install in Termux beyond the Python packages
   themselves.
2. **Flask + polling** — rejected. Flask's sync WSGI model avoids async
   entirely, but polling is chattier and less responsive for a live log
   than a push-based stream, and Flask's native streaming-response story
   is clunkier than Starlette/FastAPI's. No real advantage here, and the
   user already named FastAPI.
3. **FastAPI + WebSockets** — rejected. More "real-time"-feeling and
   bidirectional, but every client-originated action here is a discrete,
   independent command already well-served by ordinary POST endpoints; a
   single WS channel would need its own ad hoc message-routing protocol
   for no benefit over POST (for commands) + SSE (for the one genuinely
   continuous feed). Worth revisiting only if a future feature needs
   true bidirectional push, which none currently does.
4. **Keep Termux:GUI alongside the new web app as an alternate frontend**
   — rejected. Doubles the maintenance burden for a layer with an
   unresolved, possibly unfixable connection problem and no evidence a
   fix is close. Clean removal is simpler and avoids two competing UI
   layers (an explicit anti-goal above).

## Decisions made with the user

- Web framework: **FastAPI**, chosen by the user; **SSE** (not
  WebSockets) for the live feed; **plain HTML/vanilla JS** (no build
  step/framework) for the frontend — all per "Approaches" above.
- Bind host: **`127.0.0.1` only.**
- Entrypoint: `ose_web.py` replaces `ose_gui.py`, launched the same way
  (`sudo python ose_web.py`); no privilege-separation changes needed.
- `src/gui/` is deleted outright once the new layer is built and tests
  pass, except `presenters.py`, which moves to `src/presenters.py` (it
  was always pure, UI-agnostic formatting logic — "no I/O, no termuxgui
  import" per its own existing docstring — so it has no reason to live
  under a UI-specific package once that package no longer exists; its
  functions carry over unchanged into the new layer).
- New package layout: `src/web/` (app/routes), a clean break from the
  deleted `src/gui/` naming.
- New GUI-only runtime dependency file: `requirements-web.txt`
  (`fastapi`, `uvicorn`) — mirrors the already-established pattern of
  `requirements-dev.txt` (`pytest`) as an optional, non-core-engine
  dependency list; README's install story updates to match (replacing
  the whole "GUI (Termux:GUI)" section with a "GUI (Web)" section,
  including the same kind of on-device follow-up list the old section
  had — now much shorter, since there's no plugin-app handshake to
  verify).

## What's left to the builder

- The exact route list and URL scheme, the SSE endpoint's implementation
  (draining the same `EventBus`-fed `queue.Queue` pattern `src/gui/app.py`
  used, HTTP-flavored instead of GUI-event-loop-flavored), the HTML
  page's structure/tabs (CSS-only or minimal JS — builder's call) for
  Scan/Queue/Log/PBC, and the test file organization (one test module per
  route group is a reasonable default).
- Whether the single HTML page is served via a Jinja2 template or a
  plain string/static file — either is fine; no templating engine is a
  new dependency either way beyond what FastAPI already pulls in, so pick
  whichever is less code.
- The precise shape of each POST endpoint's request/response body
  (e.g. enqueue's payload, scan's trigger-and-poll vs trigger-and-SSE
  shape) — design it directly from `Orchestrator`'s and `WiFiScanner`'s
  existing method signatures, which are unchanged.
- Order of task execution and how finely to split tasks (this spec is
  the input to `superpowers:writing-plans`, not a task breakdown itself).

## Verification

**Provable from this sandbox** (no root, no WPS hardware, no real mobile
browser needed — this is a major improvement over the Termux:GUI
situation, where only import structure was ever testable):
- Every route's request/response behavior via FastAPI's `TestClient`:
  enqueue, start/stop, a faked scan trigger, PBC trigger, and the SSE
  endpoint actually receiving events pushed through a fake `EventBus`.
- The full existing engine test suite continues passing unchanged (proof
  that nothing below the UI boundary was touched).
- A smoke-test of the served HTML page (200 status, expected markup
  present) via `TestClient`, with no real browser needed.

**Still cannot be proven here — on-device follow-up, same category as
before but shorter**:
- Actually opening the page in a real mobile browser and using it
  end-to-end against live `wpa_supplicant`/`pixiewps`/`iw`.
- Real backgrounding/battery behavior while the server runs during a long
  queue run.
- A `kill -9` mid-bruteforce crash-safety check against the real
  `SessionStore` file (same check the Termux:GUI section already listed;
  unrelated to the UI layer, still outstanding).

## Critical files

- New: `src/web/` package (app + routes), `ose_web.py`,
  `requirements-web.txt`.
- Moved: `src/gui/presenters.py` → `src/presenters.py` (and its existing
  test file moves with it).
- Deleted: `src/gui/app.py`, `src/gui/scan_screen.py`,
  `src/gui/queue_screen.py`, `src/gui/log_screen.py`,
  `src/gui/pbc_screen.py`, `src/gui/prompter.py`, `ose_gui.py`, and their
  corresponding test files (`tests/test_gui_app_import.py`,
  `tests/test_gui_queue_screen.py`, `tests/test_gui_prompter.py`).
- Modified: `README.md` (GUI section rewritten), `.gitignore` if needed
  for any new build artifacts (unlikely — no build step).
- Unchanged: everything under `src/` except the above — `settings.py`,
  `prompts.py`, `events.py`, `session.py`, `orchestrator.py`,
  `wifi/`, `wps/`, `args.py`, `setup.py`, `utils.py`, `logger.py`,
  `errors.py`, and `ose.py` (the CLI).
