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
import src.settings
from src.errors import FatalError
from src.prompts import Prompter, CLIPrompter

def setupAndroidWifi(android_network: src.wifi.android.AndroidNetwork, enable: bool = False):
    """Configure Android-specific WiFi settings"""

    if enable:
        android_network.enableWifi()
    else:
        android_network.storeAlwaysScanState()
        android_network.disableWifi()


def scanForNetworks(interface: str, vuln_list: list[str], settings: src.settings.Settings,
                     prompter: Prompter) -> tuple[str, dict] | None:
    """Scan, and prompt user to select network"""

    scanner = src.wifi.scanner.WiFiScanner(interface, vuln_list, settings, prompter)
    return scanner.promptNetwork()

def handleConnection(settings: src.settings.Settings, prompter: Prompter):
    """Main connection logic"""

    network_info = {}
    success = False

    if settings.bruteforce:
        connection = src.wps.bruteforce.Initialize(settings.interface, settings, prompter)
    else:
        connection = src.wps.connection.Initialize(settings.interface, settings, prompter)

    if settings.pbc:
        connection.singleConnection(pbc_mode=True)
    else:
        if not settings.bssid:
            try:
                with open(settings.vuln_list, 'r', encoding='utf-8') as file:
                    vuln_list = file.read().splitlines()
            except FileNotFoundError:
                vuln_list = []

            if not settings.loop:
                logger.info('BSSID not specified (--bssid) — scanning for available networks')

            result = scanForNetworks(settings.interface, vuln_list, settings, prompter)
            if result is None:
                return

            settings.bssid, network_info = result

        if settings.bssid:
            if settings.bruteforce:
                connection.smartBruteforce(
                    settings.bssid,
                    settings.pin
                )
            else:
                success = connection.singleConnection(
                    settings.bssid,
                    settings.pin
                )

            # Save to vulnerable list
            if success and settings.pixie_dust and network_info:
                src.utils.addVulnerableAP(network_info, settings.vuln_list)

def shouldExitLoop(prompter: Prompter) -> bool:
    """Asks whether to exit the script on Ctrl-C during --loop, or keep
    continuing to the next AP scan. Extracted as its own function so it's
    directly testable without driving the whole _run() loop."""

    return prompter.confirm_explicit_yes(
        '\n[?] Exit the script (otherwise continue to AP scan)? [N/y] '
    )

def _run():
    """Main os-e code"""

    src.setup.checkRequirements()
    src.setup.setupDirectories()

    settings = src.settings.Settings.from_cli()
    prompter = CLIPrompter()
    logger.initializeLogging()

    src.utils.checkRunningProcesses(settings.interface)

    if settings.kill:
        src.utils.killInterfering()

    while True:
        try:
            android_network = src.wifi.android.AndroidNetwork()

            if settings.clear:
                src.utils.clearScreen()

            if src.utils.isAndroid() is True and not settings.dont_touch_settings and not settings.mtk_wifi:
                setupAndroidWifi(android_network)

            if settings.mtk_wifi:
                wmt_wifi_device = Path('/dev/wmtWifi')
                src.setup.setupMediatekWifi(wmt_wifi_device)

            if src.utils.ifaceCtl(settings.interface, action='up'):
                src.utils.die(f'Unable to up interface \'{settings.interface}\'')

            handleConnection(settings, prompter)

            if not settings.loop:
                break

            settings.bssid = None

        except KeyboardInterrupt:
            if settings.loop:
                if shouldExitLoop(prompter):
                    logger.info('Aborting…')
                    break
                settings.bssid = None
            else:
                logger.info('Aborting…')
                break

        finally:
            if src.utils.isAndroid() is True and not settings.dont_touch_settings and not settings.mtk_wifi:
                setupAndroidWifi(android_network, enable=True)

            if settings.iface_down:
                src.utils.ifaceCtl(settings.interface, action='down')

            if settings.mtk_wifi:
                wmt_wifi_device.write_text('0', encoding='utf-8')

            if settings.restore:
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
