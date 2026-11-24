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

from abc import ABC, abstractmethod

from src import logger


class Prompter(ABC):
    """Injectable replacement for the engine's blocking input() calls.

    The CLI's CLIPrompter (below) reproduces today's exact terminal
    behavior. The web GUI's Orchestrator-driven queue and PBC flow don't
    need a Prompter implementation of their own at all (the queue uses
    orchestrator.AutoConfirmPrompter — unattended steps never block on a
    human — and PBC never resolves a pin), but any future attended UI
    that does would implement this interface.
    """

    @abstractmethod
    def confirm(self, message: str) -> bool:
        """Ask a yes/no question that defaults to yes on empty input."""

    @abstractmethod
    def confirm_explicit_yes(self, message: str) -> bool:
        """Ask a yes/no question that defaults to no on empty input."""

    @abstractmethod
    def select_index(
        self,
        prompt: str,
        count: int,
        cancel_tokens: frozenset = frozenset(),
    ) -> int | None:
        """Ask the user to pick one of `count` items (1-based on input).

        Returns a 0-based index, or None if the user entered one of
        `cancel_tokens`.
        """


class CLIPrompter(Prompter):
    """Reproduces today's exact input()-based CLI prompts."""

    def confirm(self, message: str) -> bool:
        answer = input(message).strip().lower()
        return answer != 'n'

    def confirm_explicit_yes(self, message: str) -> bool:
        answer = input(message).strip().lower()
        return answer == 'y'

    def select_index(
        self,
        prompt: str,
        count: int,
        cancel_tokens: frozenset = frozenset(),
    ) -> int | None:
        normalized_cancel_tokens = {token.lower() for token in cancel_tokens}
        while True:
            answer = input(prompt).strip()
            if answer.lower() in normalized_cancel_tokens:
                return None
            try:
                index = int(answer) - 1
                if index < 0 or index >= count:
                    raise IndexError
            except (ValueError, IndexError):
                logger.warning('Invalid number')
                continue
            return index
