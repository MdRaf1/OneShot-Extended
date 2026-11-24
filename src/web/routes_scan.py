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

"""Scan API route: lists WPS-capable networks, with the same
stored/vulnerable/locked highlighting scanner.py's own CLI table used."""

from fastapi import APIRouter, Request

from src import presenters

router = APIRouter()


@router.get("/api/scan")
def get_scan(request: Request) -> list:
    scanner = request.app.state.scanner
    networks = scanner._iwScanner()  # pylint: disable=protected-access
    if not networks:
        return []

    results = []
    for network in networks.values():
        network = dict(network)
        network['_stored'] = (network.get('BSSID'), network.get('ESSID')) in scanner.STORED
        network['_vulnerable_model'] = bool(scanner.VULN_LIST) and (
            f'{network.get("Model")} {network.get("Model number")}' in scanner.VULN_LIST
            or network.get('Device name') in scanner.VULN_LIST
        )
        row = presenters.format_network_row(network)
        results.append({
            "bssid": network.get('BSSID'),
            "essid": network.get('ESSID'),
            "label": row['label'],
            "highlight": row['highlight'],
        })

    return results
