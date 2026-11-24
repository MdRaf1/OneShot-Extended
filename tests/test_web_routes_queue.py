import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.session import TargetRecord
from src.web.app import create_app
from src.web.queue_runner import QueueRunner


def _make_target(bssid="AA:BB:CC:DD:EE:FF", essid="home", state="pending"):
    return TargetRecord(
        bssid=bssid, essid=essid, state=state, last_chain_step=None,
        bruteforce_mask=None, pixie_pin=None, cooldown_until=None,
        wps_pin=None, wpa_psk=None, updated_at=0.0,
    )


class FakeOrchestrator:
    def __init__(self, snapshot=None):
        self._snapshot = snapshot or []
        self.enqueue_calls = []

    def get_queue_snapshot(self):
        return self._snapshot

    def enqueue(self, bssid, essid=None):
        self.enqueue_calls.append((bssid, essid))

    def stop(self):
        pass


class FakeQueueRunner:
    def __init__(self, running=False):
        self._running = running
        self.start_calls = 0
        self.stop_calls = 0

    def is_running(self):
        return self._running

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1


def _make_app(orchestrator=None, queue_runner=None):
    return create_app(
        "wlan0",
        SimpleNamespace(),
        orchestrator or FakeOrchestrator(),
        queue_runner or FakeQueueRunner(),
        SimpleNamespace(),
        SimpleNamespace(),
        threading.Lock(),
    )


def test_get_targets_returns_running_state_and_formatted_rows():
    orchestrator = FakeOrchestrator(snapshot=[_make_target()])
    app = _make_app(orchestrator=orchestrator, queue_runner=FakeQueueRunner(running=True))
    client = TestClient(app)

    response = client.get("/api/queue/targets")

    assert response.status_code == 200
    assert response.json() == {
        "running": True,
        "targets": [{
            "bssid": "AA:BB:CC:DD:EE:FF",
            "label": "home (AA:BB:CC:DD:EE:FF)",
            "status_text": "Pending",
            "progress_percent": None,
        }],
    }


def test_post_targets_enqueues_on_orchestrator():
    orchestrator = FakeOrchestrator()
    app = _make_app(orchestrator=orchestrator)
    client = TestClient(app)

    response = client.post("/api/queue/targets", json={"bssid": "AA:BB:CC:DD:EE:FF", "essid": "home"})

    assert response.status_code == 201
    assert response.json() == {"status": "enqueued"}
    assert orchestrator.enqueue_calls == [("AA:BB:CC:DD:EE:FF", "home")]


def test_post_targets_enqueues_with_no_essid():
    orchestrator = FakeOrchestrator()
    app = _make_app(orchestrator=orchestrator)
    client = TestClient(app)

    response = client.post("/api/queue/targets", json={"bssid": "AA:BB:CC:DD:EE:FF"})

    assert response.status_code == 201
    assert orchestrator.enqueue_calls == [("AA:BB:CC:DD:EE:FF", None)]


def test_post_start_calls_queue_runner_start():
    queue_runner = FakeQueueRunner()
    app = _make_app(queue_runner=queue_runner)
    client = TestClient(app)

    response = client.post("/api/queue/start")

    assert response.status_code == 202
    assert response.json() == {"status": "started"}
    assert queue_runner.start_calls == 1


def test_post_stop_calls_queue_runner_stop():
    queue_runner = FakeQueueRunner()
    app = _make_app(queue_runner=queue_runner)
    client = TestClient(app)

    response = client.post("/api/queue/stop")

    assert response.status_code == 202
    assert response.json() == {"status": "stopped"}
    assert queue_runner.stop_calls == 1


def test_two_near_simultaneous_start_requests_only_start_one_run():
    run_started = threading.Event()
    release_run = threading.Event()
    run_count = []

    class BlockingOrchestrator(FakeOrchestrator):
        def run(self):
            run_count.append(1)
            run_started.set()
            release_run.wait(timeout=2)

    queue_runner = QueueRunner(BlockingOrchestrator(), radio_lock=threading.Lock())
    app = _make_app(queue_runner=queue_runner)
    client = TestClient(app)

    first_response = {}

    def _post_start():
        first_response["response"] = client.post("/api/queue/start")

    t1 = threading.Thread(target=_post_start)
    t1.start()
    assert run_started.wait(timeout=2)

    second_response = client.post("/api/queue/start")
    t1.join(timeout=2)

    assert first_response["response"].status_code == 202
    assert second_response.status_code == 202
    assert run_count == [1]

    release_run.set()
    client.post("/api/queue/stop")
    queue_runner._run_thread.join(timeout=2)  # pylint: disable=protected-access
