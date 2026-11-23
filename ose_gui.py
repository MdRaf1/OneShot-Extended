#!/usr/bin/env python3
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

"""Termux:GUI entrypoint for OneShot-Extended. See README.md for setup
(Termux + the Termux:GUI plugin app, `pip install termuxgui`) and run
as root, same as ose.py:

    sudo python ose_gui.py
"""

from src.gui.app import main

if __name__ == '__main__':
    main()
