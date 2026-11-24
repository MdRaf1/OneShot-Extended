import threading

from src.web.queue_runner import QueueRunner


class _FakeOrchestratorBase:
    def stop(self):
        pass


def test_start_holds_radio_lock_for_the_duration_of_the_run():
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

    runner = QueueRunner(FakeOrchestrator(), radio_lock=lock)
    runner.start()

    assert run_started.wait(timeout=2)
    assert lock_was_held.is_set()

    release_run.set()
    runner.stop()
    runner._run_thread.join(timeout=2)  # pylint: disable=protected-access


def test_double_click_start_does_not_launch_a_second_run():
    call_count = []
    started = threading.Event()
    release = threading.Event()

    class FakeOrchestrator(_FakeOrchestratorBase):
        def run(self):
            call_count.append(1)
            started.set()
            release.wait(timeout=2)

    runner = QueueRunner(FakeOrchestrator(), radio_lock=threading.Lock())
    runner.start()
    assert started.wait(timeout=2)

    runner.start()  # second call while still running

    release.set()
    runner.stop()
    runner._run_thread.join(timeout=2)  # pylint: disable=protected-access
    assert len(call_count) == 1


def test_start_runs_repeatedly_until_stopped():
    call_count = []
    reached_three = threading.Event()

    class FakeOrchestrator(_FakeOrchestratorBase):
        def run(self):
            call_count.append(1)
            if len(call_count) >= 3:
                reached_three.set()

    runner = QueueRunner(FakeOrchestrator(), radio_lock=threading.Lock(), poll_interval=0.01)
    runner.start()

    assert reached_three.wait(timeout=2)

    runner.stop()
    runner._run_thread.join(timeout=2)  # pylint: disable=protected-access


def test_start_can_run_again_after_being_stopped():
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

    runner = QueueRunner(FakeOrchestrator(), radio_lock=threading.Lock(), poll_interval=0.01)
    runner.start()
    assert first_run_started.wait(timeout=2)

    runner.stop()
    release_first.set()
    runner._run_thread.join(timeout=2)  # pylint: disable=protected-access

    runner.start()
    assert second_run_started.wait(timeout=2)
    runner.stop()
    runner._run_thread.join(timeout=2)  # pylint: disable=protected-access


def test_is_running_reflects_loop_state():
    started = threading.Event()
    release = threading.Event()

    class FakeOrchestrator(_FakeOrchestratorBase):
        def run(self):
            started.set()
            release.wait(timeout=2)

    runner = QueueRunner(FakeOrchestrator(), radio_lock=threading.Lock(), poll_interval=0.01)
    assert runner.is_running() is False
    runner.start()
    assert started.wait(timeout=2)
    assert runner.is_running() is True
    release.set()
    runner.stop()
    runner._run_thread.join(timeout=2)  # pylint: disable=protected-access
    assert runner.is_running() is False
