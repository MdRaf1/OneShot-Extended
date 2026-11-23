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

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Event:
    """A structured piece of engine output (progress, state, success, …).

    Produced by the logger (see src.logger.set_event_bus) and by the
    orchestrator, consumed by anything subscribed to an EventBus — the GUI
    log pane, a future test, etc.
    """

    kind: str
    level: str
    message: str
    data: dict = field(default_factory=dict)


class EventBus:
    """A minimal publish/subscribe hub for Event objects.

    emit() never lets one bad subscriber break delivery to the others:
    any exception a subscriber raises is caught and swallowed.
    """

    def __init__(self):
        self._subscribers: list[Callable[[Event], None]] = []

    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]:
        self._subscribers.append(fn)

        def unsubscribe() -> None:
            if fn in self._subscribers:
                self._subscribers.remove(fn)

        return unsubscribe

    def emit(self, event: Event) -> None:
        for fn in list(self._subscribers):
            try:
                fn(event)
            except Exception:  # pylint: disable=broad-except
                pass
