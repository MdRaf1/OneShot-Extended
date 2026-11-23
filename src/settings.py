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

import argparse
import os
from dataclasses import dataclass

import src.args


@dataclass
class Settings:
    """Explicit, constructible replacement for the engine's old reliance
    on a module-level `args = src.args.parseArgs()` parsed at import time.

    One field per src.args.py flag (same names/defaults as the argparse
    `dest`s) so scanner.py/connection.py/bruteforce.py/generator.py can be
    constructed and used as a library — by a GUI, an orchestrator, or a
    test — without ever touching sys.argv.
    """

    interface: str
    bssid: str | None = None
    pin: str | None = None
    null_pin: bool = False
    pixie_dust: bool = False
    bruteforce: bool = False
    pbc: bool = False
    kill: bool = False
    restore: bool = False
    write: bool = False
    loop: bool = False
    clear: bool = False
    delay: float = 0
    timeout: float = 60
    pixie_force: bool = False
    show_pixie: bool = False
    iface_down: bool = False
    mtk_wifi: bool = False
    dont_touch_settings: bool = False
    reverse_scan: bool = False
    vuln_list: str = os.path.join(os.path.dirname(src.args.__file__), '../vulnwsc.txt')
    verbose: bool = False

    @classmethod
    def from_args(cls, ns: argparse.Namespace) -> "Settings":
        return cls(**vars(ns))

    @classmethod
    def from_cli(cls, argv: list[str] | None = None) -> "Settings":
        return cls.from_args(src.args.parseArgs(argv))
