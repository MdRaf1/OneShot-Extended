import sys
import threading
import types


def _make_termuxgui_stub():
    stub = types.ModuleType("termuxgui")

    class _View:
        WRAP_CONTENT = "WRAP_CONTENT"
        MATCH_PARENT = "MATCH_PARENT"

        def __init__(self, *args, **kwargs):  # pylint: disable=unused-argument
            pass

        def __getattr__(self, name):
            return lambda *a, **kw: None

    for name in (
        "Activity", "LinearLayout", "NestedScrollView", "Button", "TextView",
    ):
        setattr(stub, name, _View)
    stub.View = _View
    return stub


def _import_queue_screen(monkeypatch):
    monkeypatch.setitem(sys.modules, "termuxgui", _make_termuxgui_stub())
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.gui"):
            del sys.modules[mod_name]
    import importlib  # pylint: disable=import-outside-toplevel
    module = importlib.import_module("src.gui.queue_screen")
    return module.QueueScreen


class _FakeOrchestratorBase:
    def get_queue_snapshot(self):
        return []

    def stop(self):
        pass


def test_start_holds_radio_lock_for_the_duration_of_the_run(monkeypatch):
    QueueScreen = _import_queue_screen(monkeypatch)  # pylint: disable=invalid-name

    lock = threading.Lock()
    lock_was_held = threading.Event()
    run_started = threading.Event()
    release_run = threading.Event()

    class FakeOrchestrator(_FakeOrchestratorBase):
        def run(self):
            run_started.set()
            if lock.locked():
                lock_was_held.set()
            release_run.wait(timeout=2)

    screen = QueueScreen(object(), object(), FakeOrchestrator(), radio_lock=lock)
    screen.on_click(screen.start_button)

    assert run_started.wait(timeout=2)
    assert lock_was_held.is_set()

    release_run.set()
    screen.on_click(screen.stop_button)
    screen._run_thread.join(timeout=2)  # pylint: disable=protected-access


def test_double_click_start_does_not_launch_a_second_run(monkeypatch):
    QueueScreen = _import_queue_screen(monkeypatch)  # pylint: disable=invalid-name

    call_count = []
    started = threading.Event()
    release = threading.Event()

    class FakeOrchestrator(_FakeOrchestratorBase):
        def run(self):
            call_count.append(1)
            started.set()
            release.wait(timeout=2)

    screen = QueueScreen(object(), object(), FakeOrchestrator(), radio_lock=threading.Lock())
    screen.on_click(screen.start_button)
    assert started.wait(timeout=2)

    screen.on_click(screen.start_button)  # second click while still running

    release.set()
    screen.on_click(screen.stop_button)
    screen._run_thread.join(timeout=2)  # pylint: disable=protected-access
    assert len(call_count) == 1


def test_start_runs_repeatedly_until_stopped(monkeypatch):
    QueueScreen = _import_queue_screen(monkeypatch)  # pylint: disable=invalid-name

    call_count = []
    reached_three = threading.Event()

    class FakeOrchestrator(_FakeOrchestratorBase):
        def run(self):
            call_count.append(1)
            if len(call_count) >= 3:
                reached_three.set()

    screen = QueueScreen(
        object(), object(), FakeOrchestrator(), radio_lock=threading.Lock(), poll_interval=0.01,
    )
    screen.on_click(screen.start_button)

    assert reached_three.wait(timeout=2)

    screen.on_click(screen.stop_button)
    screen._run_thread.join(timeout=2)  # pylint: disable=protected-access


def test_start_can_run_again_after_being_stopped(monkeypatch):
    QueueScreen = _import_queue_screen(monkeypatch)  # pylint: disable=invalid-name

    first_run_started = threading.Event()
    second_run_started = threading.Event()
    release_first = threading.Event()
    run_count = []

    class FakeOrchestrator(_FakeOrchestratorBase):
        def run(self):
            run_count.append(1)
            if len(run_count) == 1:
                first_run_started.set()
                release_first.wait(timeout=2)
            else:
                second_run_started.set()

    screen = QueueScreen(
        object(), object(), FakeOrchestrator(), radio_lock=threading.Lock(), poll_interval=0.01,
    )
    screen.on_click(screen.start_button)
    assert first_run_started.wait(timeout=2)

    screen.on_click(screen.stop_button)
    release_first.set()
    screen._run_thread.join(timeout=2)  # pylint: disable=protected-access

    screen.on_click(screen.start_button)
    assert second_run_started.wait(timeout=2)
    screen.on_click(screen.stop_button)
    screen._run_thread.join(timeout=2)  # pylint: disable=protected-access
