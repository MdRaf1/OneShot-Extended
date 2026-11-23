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

class FatalError(Exception):
    """Raised for a fatal, unrecoverable error.

    Replaces the old pattern of calling sys.exit() deep inside the engine
    (src.utils.die()), so a fatal error raised from a non-main thread (e.g.
    a GUI background thread running the orchestrator) is observable and
    reportable instead of silently killing only that thread.
    """
