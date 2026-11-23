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

import sys

# pylint: disable=wrong-import-position
if sys.version_info < (3, 11):
    sys.exit('Python 3.11 or higher is required to run this script.')

from pathlib import Path
from src import logger

import src.wifi.android
import src.wifi.scanner
import src.wps.connection
import src.wps.bruteforce
import src.utils
import src.setup
import src.args
from src.errors import FatalError

def setupAndroidWifi(android_network: src.wifi.android.AndroidNetwork, enable: bool = False):
    """Configure Android-specific WiFi settings"""

    if enable:
        android_network.enableWifi()
    else:
        android_network.storeAlwaysScanState()
        android_network.disableWifi()


def scanForNetworks(interface: str, vuln_list: list[str]) -> tuple[str, dict] | None:
    """Scan, and prompt user to select network"""

    scanner = src.wifi.scanner.WiFiScanner(interface, vuln_list)
    return scanner.promptNetwork()

def handleConnection(args):
    """Main connection logic"""

    network_info = {}
    success = False

    if args.bruteforce:
        connection = src.wps.bruteforce.Initialize(args.interface)
    else:
        connection = src.wps.connection.Initialize(args.interface)

    if args.pbc:
        connection.singleConnection(pbc_mode=True)
    else:
        if not args.bssid:
            try:
                with open(args.vuln_list, 'r', encoding='utf-8') as file:
                    vuln_list = file.read().splitlines()
            except FileNotFoundError:
                vuln_list = []

            if not args.loop:
                logger.info('BSSID not specified (--bssid) — scanning for available networks')

            result = scanForNetworks(args.interface, vuln_list)
            if result is None:
                return

            args.bssid, network_info = result

        if args.bssid:
            if args.bruteforce:
                connection.smartBruteforce(
                    args.bssid,
                    args.pin
                )
            else:
                success = connection.singleConnection(
                    args.bssid,
                    args.pin
                )

            # Save to vulnerable list
            if success and args.pixie_dust and network_info:
                src.utils.addVulnerableAP(network_info, args.vuln_list)

def _run():
    """Main os-e code"""

    src.setup.checkRequirements()
    src.setup.setupDirectories()

    args = src.args.parseArgs()
    logger.initializeLogging()

    src.utils.checkRunningProcesses(args.interface)

    if args.kill:
        src.utils.killInterfering()

    while True:
        try:
            android_network = src.wifi.android.AndroidNetwork()

            if args.clear:
                src.utils.clearScreen()

            if src.utils.isAndroid() is True and not args.dont_touch_settings and not args.mtk_wifi:
                setupAndroidWifi(android_network)

            if args.mtk_wifi:
                wmt_wifi_device = Path('/dev/wmtWifi')
                src.setup.setupMediatekWifi(wmt_wifi_device)

            if src.utils.ifaceCtl(args.interface, action='up'):
                src.utils.die(f'Unable to up interface \'{args.interface}\'')

            handleConnection(args)

            if not args.loop:
                break

            args.bssid = None

        except KeyboardInterrupt:
            if args.loop:
                if input('\n[?] Exit the script (otherwise continue to AP scan)? [N/y] ').lower() == 'y':
                    logger.info('Aborting…')
                    break
                args.bssid = None
            else:
                logger.info('Aborting…')
                break

        finally:
            if src.utils.isAndroid() is True and not args.dont_touch_settings and not args.mtk_wifi:
                setupAndroidWifi(android_network, enable=True)

            if args.iface_down:
                src.utils.ifaceCtl(args.interface, action='down')

            if args.mtk_wifi:
                wmt_wifi_device.write_text('0', encoding='utf-8')

            if args.restore:
                src.utils.restoreProcesses()

def main():
    """CLI entrypoint: run _run(), converting any FatalError raised deep
    inside the engine (src.utils.die()) into the same exit behavior the
    old sys.exit()-based die() produced."""

    try:
        _run()
    except FatalError as e:
        sys.exit(f'[!] {e} \n')

if __name__ == '__main__':
    main()
