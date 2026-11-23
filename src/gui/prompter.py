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

"""GuiPrompter — defined here for interface completeness, deliberately
NOT wired into the decided GUI flows.

The Orchestrator's auto-chain uses orchestrator.AutoConfirmPrompter
(every step must stay unattended — see its own docstring), and the PBC
flow never needs pin resolution at all, so neither ever constructs a
GuiPrompter. Do NOT "fix" this by routing confirmation dialogs into the
auto-chain: popping a dialog mid-unattended-sweep (e.g. "reuse this
pixie PIN?") would block the whole queue on a human who, by the nature
of a background multi-target run, may not be looking at the screen.

This class exists so a future feature that genuinely needs an
attended, dialog-driven Prompter (e.g. a manual single-target screen)
has one ready, backed by a real termuxgui Activity(dialog=True) call
supplied as `dialog_opener` — never imported here, only injected.
"""

from src.prompts import Prompter


class GuiPrompter(Prompter):
    """A Prompter backed by an injected dialog_opener(message, choices)
    callable — the seam a real termuxgui binding fills with an
    Activity(c, dialog=True) call. choices is None for confirm()/
    confirm_explicit_yes(); a list of generated labels for select_index().
    dialog_opener returns the user's chosen label as a string, or None if
    the dialog was cancelled.
    """

    def __init__(self, dialog_opener):
        self.dialog_opener = dialog_opener

    def confirm(self, message: str) -> bool:
        answer = self.dialog_opener(message, None)
        return (answer or '').strip().lower() != 'n'

    def confirm_explicit_yes(self, message: str) -> bool:
        answer = self.dialog_opener(message, None)
        return (answer or '').strip().lower() == 'y'

    def select_index(self, prompt: str, count: int, cancel_tokens: frozenset = frozenset()) -> int | None:
        choices = [str(i + 1) for i in range(count)]
        response = self.dialog_opener(prompt, choices)
        if response is None:
            return None
        try:
            return choices.index(response)
        except ValueError:
            return None
