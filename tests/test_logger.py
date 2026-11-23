import logging

import pytest

from src import logger
from src.events import Event, EventBus


@pytest.fixture(autouse=True)
def _reset_logger_singleton():
    # src.logger's _LOGGER is a module-level singleton whose StreamHandler
    # binds to sys.stdout once, lazily, the first time info()/success()/
    # warning()/error() is called (guarded by `if not logger.handlers`).
    # pytest's capsys fixture replaces sys.stdout per-test, so a handler
    # bound during an earlier test keeps writing to that test's
    # already-torn-down capture buffer instead of the current test's.
    # Reset both the module global and the underlying logging.Logger's
    # handlers before each test so info()/etc. re-bind against whatever
    # sys.stdout is current when the test calls them.
    logger._LOGGER = None  # pylint: disable=protected-access
    logging.getLogger('ose').handlers.clear()
    yield
    logger._LOGGER = None  # pylint: disable=protected-access
    logging.getLogger('ose').handlers.clear()


def test_raw_emits_event_when_bus_set():
    bus = EventBus()
    seen = []
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
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)
    logger.info("[*] scanning")
    assert any(e.kind == "info" for e in seen)
    logger.set_event_bus(None)


def test_info_console_output_unchanged_when_no_bus(capsys):
    logger.set_event_bus(None)
    logger.info("[*] scanning")
    assert "scanning" in capsys.readouterr().out


def test_success_emits_event_when_bus_set():
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)
    logger.success("done")
    assert any(e.kind == "success" for e in seen)
    logger.set_event_bus(None)


def test_warning_emits_event_when_bus_set():
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)
    logger.warning("careful")
    assert any(e.kind == "warning" for e in seen)
    logger.set_event_bus(None)


def test_error_emits_event_when_bus_set():
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    logger.set_event_bus(bus)
    logger.error("boom")
    assert any(e.kind == "error" for e in seen)
    logger.set_event_bus(None)


def test_no_event_emitted_when_bus_is_none():
    # regression: calling info() without ever setting a bus must not raise
    logger.set_event_bus(None)
    logger.info("no bus set")
