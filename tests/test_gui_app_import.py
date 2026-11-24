import os
import sys
import types


def _make_termuxgui_stub():
    """A minimal stand-in for the termuxgui package: no real Termux:GUI
    plugin or Android device is available in this environment to
    install/connect it against, so this only proves our GUI modules'
    import structure is sound — never their runtime behavior against a
    real plugin (see README's GUI section for the required on-device
    follow-up verification)."""

    stub = types.ModuleType("termuxgui")

    class _View:
        WRAP_CONTENT = "WRAP_CONTENT"
        MATCH_PARENT = "MATCH_PARENT"

        def __init__(self, *args, **kwargs):  # pylint: disable=unused-argument
            pass

        def __getattr__(self, name):
            # Any method call (settext, setwidth, setlinearlayoutparams,
            # gettext, setlist, ...) becomes a harmless no-op.
            return lambda *a, **kw: None

    class _Event:
        click = "click"
        destroy = "destroy"
        refresh = "refresh"
        itemselected = "itemselected"
        selected = "selected"
        back = "back"

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def events(self):
            return iter([])

        def toast(self, *args, **kwargs):  # pylint: disable=unused-argument
            pass

    for name in (
        "Activity", "LinearLayout", "FrameLayout", "SwipeRefreshLayout",
        "TextView", "EditText", "Button", "ImageView", "Checkbox",
        "ToggleButton", "Switch", "RadioGroup", "RadioButton", "Spinner",
        "ProgressBar", "TabLayout", "NestedScrollView", "HorizontalScrollView",
        "WebView",
    ):
        setattr(stub, name, _View)

    stub.Connection = _Connection
    stub.Event = _Event
    stub.View = _View

    return stub


def _reimport_gui_modules(monkeypatch):
    monkeypatch.setitem(sys.modules, "termuxgui", _make_termuxgui_stub())
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.gui"):
            del sys.modules[mod_name]


def test_gui_app_module_imports_and_exposes_main(monkeypatch):
    _reimport_gui_modules(monkeypatch)
    import importlib  # pylint: disable=import-outside-toplevel
    app = importlib.import_module("src.gui.app")
    assert callable(app.main)


def test_gui_screen_modules_import_cleanly(monkeypatch):
    _reimport_gui_modules(monkeypatch)
    import importlib  # pylint: disable=import-outside-toplevel
    for mod_name in (
        "src.gui.scan_screen", "src.gui.queue_screen",
        "src.gui.log_screen", "src.gui.pbc_screen",
    ):
        module = importlib.import_module(mod_name)
        assert module is not None


def test_main_exits_cleanly_on_fatal_error_instead_of_raising(monkeypatch):
    # Regression: unlike ose.py's main() (which catches FatalError and
    # exits with a clean "[!] message"), the GUI entrypoint used to let
    # any FatalError from setup (missing root, missing binary, missing
    # termux-am, ...) propagate as a raw Python traceback.
    import pytest  # pylint: disable=import-outside-toplevel

    _reimport_gui_modules(monkeypatch)
    import importlib  # pylint: disable=import-outside-toplevel
    app = importlib.import_module("src.gui.app")

    from src.errors import FatalError  # pylint: disable=import-outside-toplevel

    def _raise():
        raise FatalError("boom")

    monkeypatch.setattr(app, "_run", _raise)

    with pytest.raises(SystemExit) as excinfo:
        app.main()
    assert "boom" in str(excinfo.value)


def test_run_raises_fatal_error_when_neither_termux_am_nor_am_exist(monkeypatch):
    # termuxgui's Connection() shells out to the termux-am binary to
    # reach the Termux:GUI plugin app. Without it, tg.Connection() raised
    # an uncaught FileNotFoundError deep inside the termuxgui package;
    # this must instead surface as a clear, actionable FatalError before
    # any Connection is attempted — but only when there's truly no way
    # to reach the plugin (see test_ensure_termux_am_available_* below
    # for the case where a working `am` lets us route around a missing
    # `termux-am`).
    import pytest  # pylint: disable=import-outside-toplevel

    _reimport_gui_modules(monkeypatch)
    import importlib  # pylint: disable=import-outside-toplevel
    app = importlib.import_module("src.gui.app")

    from src.errors import FatalError  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(app.ose_setup, "checkRequirements", lambda: None)
    monkeypatch.setattr(app.ose_setup, "setupDirectories", lambda: None)
    monkeypatch.setattr(app, "which", lambda binary: None)

    with pytest.raises(FatalError, match="termux-am"):
        app._run()  # pylint: disable=protected-access


def test_ensure_termux_am_available_is_noop_when_termux_am_present(monkeypatch):
    # Regression on-device finding: a Termux package can be literally
    # named `termux-am` (0.8.0-2) yet install its binary as plain `am`,
    # not as `termux-am` — so `termux-am` being present must short-circuit
    # before any shim/PATH logic runs.
    _reimport_gui_modules(monkeypatch)
    import importlib  # pylint: disable=import-outside-toplevel
    app = importlib.import_module("src.gui.app")

    original_path = os.environ.get("PATH", "")
    app._ensure_termux_am_available(
        which_fn=lambda b: "/fake/bin/termux-am" if b == "termux-am" else None
    )
    assert os.environ.get("PATH", "") == original_path


def test_ensure_termux_am_available_raises_when_neither_present(monkeypatch):
    _reimport_gui_modules(monkeypatch)
    import importlib  # pylint: disable=import-outside-toplevel
    app = importlib.import_module("src.gui.app")

    from src.errors import FatalError  # pylint: disable=import-outside-toplevel
    import pytest  # pylint: disable=import-outside-toplevel

    with pytest.raises(FatalError, match="termux-am"):
        app._ensure_termux_am_available(which_fn=lambda b: None)


def test_ensure_termux_am_available_shims_termux_am_onto_path_when_only_am_exists(tmp_path, monkeypatch):
    # On-device finding: the `termux-am` Termux package installs its
    # binary as plain `am`. termuxgui's Connection() hardcodes the exact
    # name "termux-am" with no handling for it being entirely absent
    # (only for it timing out) — so when only `am` is on PATH, we must
    # make "termux-am" resolve to something that forwards to it, without
    # touching termuxgui's own code or Termux's real directories.
    import shutil
    import subprocess

    _reimport_gui_modules(monkeypatch)
    import importlib  # pylint: disable=import-outside-toplevel
    app = importlib.import_module("src.gui.app")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_am = fake_bin / "am"
    fake_am.write_text("#!/bin/sh\necho called-am \"$@\"\n")
    fake_am.chmod(0o755)

    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(app, "_TERMUX_SH", "/bin/sh")  # portable for this test env

    app._ensure_termux_am_available(which_fn=shutil.which)

    shim = shutil.which("termux-am")
    assert shim is not None

    result = subprocess.run([shim, "hello", "world"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "called-am hello world"
