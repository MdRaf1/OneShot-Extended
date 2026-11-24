```
▄▖    ▄▖▌   ▗   ▄▖  ▗      ▌   ▌
▌▌▛▌█▌▚ ▛▌▛▌▜▘▄▖▙▖▚▘▜▘█▌▛▌▛▌█▌▛▌
▙▌▌▌▙▖▄▌▌▌▙▌▐▖  ▙▖▞▖▐▖▙▖▌▌▙▌▙▖▙▌
```

This tool performs various WPS attacks without the requirement of monitor mode, or any python dependencies.

This is a fork of [chkndrp/OneShot-Extended](https://github.com/chkndrp/OneShot-Extended), which itself is an improved version of the original OneShot. This fork adds crash-safe session persistence, a multi-target auto-attack queue, and a local web GUI on top of the existing CLI tool.

## Features
 - PIN/Null PIN and Push button connection
 - [Pixie Dust attack](https://forums.kali.org/showthread.php?24286-WPS-Pixie-Dust-Attack-Offline-WPS-Attack)
 - [Online WPS bruteforce](https://sviehb.files.wordpress.com/2011/12/viehboeck_wps.pdf)
 - Offline WPS PIN generating algorithm
 - Wi-Fi scanner with highlighting based on iw
 - Ability to write to a file
 - Crash-safe multi-target queue with an unattended auto-chain attack and a local web GUI (see [GUI](#gui-web) below)

## Advantages over original OneShot
 - Highlighting of a vulnerable WPS version (`1.0`) in the scanner
 - Ability to kill/restore interfering processes using the same interface
 - Minor changes (e.g, `WPA3TM` indication, better `vulnwsc` detection, `RF-Kill` handling)
 - Improved Scanner reliability (retries, `up` detection, `lock` detection)
 - Improved Android support
 - Many new command arguments and features
 - Works on modern python versions (`>3.11`)

## Installing

<details>
<summary><b>On Termux (Android):</b></summary>

```shell
pkg install -y root-repo
pkg install -y git sudo python wpa-supplicant pixiewps iw openssl iproute2
cd ~
git clone https://github.com/MdRaf1/OneShot-Extended ose
cd ose
```
</details>

<details>
<summary><b>On Linux:</b></summary>

Install these packages through your distribution's package manager:
```shell
python3 wpa-supplicant iw pixiewps iproute2
```
Then clone the repo:
```shell
cd ~
git clone https://github.com/MdRaf1/OneShot-Extended ose
cd ose
```
</details>

### Updating

```shell
cd ose
git fetch
git reset --hard origin/master
```

## Quick start
#### Pixie Dust attack:
 ```shell
 sudo python ose.py -i wlan0 -P
 ```

#### Bruteforce attack:
 ```shell
 sudo python ose.py -i wlan0 -B
 ```

## GUI (Web)
OneShot-Extended also has a local web GUI: it scans for WPS networks,
lets you queue up several of them, and runs an unattended auto-chain
attack (Null PIN → Pixie Dust → vendor-likely default PINs → full
bruteforce, stopping at the first success) across the whole queue, with
a live log and a separate manual PBC screen. It needs the same root and
binaries as the CLI tool — this is an additional front end, not a
replacement for it. The server only binds to `127.0.0.1`; nothing is
reachable from the rest of the network.

#### Setup:
```shell
pip install -r requirements-web.txt
```

#### Launch:
```shell
sudo python ose_web.py
```
Then open the printed `http://127.0.0.1:8000` in your browser.

#### Known limitations / required on-device follow-up
This GUI layer was built and tested with FastAPI's `TestClient` (real
request/response behavior for every route, not just import structure),
but without a real rooted Android device available. The following still
need verifying on-device:
- Real `iw`/`wpa_supplicant`/`pixiewps` behavior behind the Scan, Queue,
  and PBC routes.
- Backgrounding/battery behavior during a long queue run.
- A `kill -9` mid-bruteforce crash-safety check against the real
  `SessionStore` file.

## Usage
```
Required arguments:
  -i, --interface INTERFACE
                        Name of the interface to use
  -b, --bssid BSSID     BSSID of the target AP

Attack Modes:
  -p, --pin PIN         Use the specified pin (arbitrary string or 4/8 digit pin)
  -N, --null-pin        Use a null pin
  -P, --pixie-dust      Run Pixie Dust attack
  -B, --bruteforce      Run online bruteforce attack
  --pbc, --push-button-connect
                        Run WPS push button connection

Optional arguments:
  -k, --kill            Automatically kill processes interfering with the wireless interface
  -r, --restore         Restore killed interfering processes on exit (--kill)
  -w, --write           Write credentials to the file on success
  -l, --loop            Run in a loop
  -c, --clear           Clear the screen on every wi-fi scan
  -d, --delay DELAY     Set a delay between pin attempts in seconds (default: 0)
  -t, --timeout TIMEOUT
                        Set the timeout for retrying after WPS lock (default: 60)

Advanced Arguments:
  -F, --pixie-force     Run Pixiewps with --force option (bruteforce full range)
  -S, --show-pixie      Print pixiewps command and related data
  -I, --iface-down      Down network interface when the work is finished
  -M, --mtk-wifi        Activate MediaTek Wi-Fi interface driver on startup and deactivate it on exit
  -D, --dont-touch-settings
                        Don't touch the Android Wi-Fi settings on startup and exit
  --reverse-scan        Reverse order of networks in the list of networks. Useful on small displays
  --vuln-list VULN_LIST
                        Use custom file with vulnerable devices list
  -v, --verbose         Verbose output
  -h, --help            Show this help message and exit
```

## Troubleshooting
`Device or resource busy (-16)`
- This happens because some other process is using the interface. 
- Turn off Wi-Fi scanners/managers or use `--kill` argument to stop them.
   - on Android, the Wi-Fi scanner is automatically disabled, and the use of `--kill` argument is not recommended

`The wireless interface disappears when Wi-Fi is disabled on Android devices with MediaTek SoC`
- Try running Oneshot-Extended with the `--mtk-wifi` flag to initialize Wi-Fi device driver.

## Credits
- [chkndrp](https://github.com/chkndrp/OneShot-Extended) for OneShot-Extended, the base this fork builds on
- [kimocoder](https://github.com/kimocoder/OneShot), [drygdryg](https://github.com/drygdryg) for the foundation of this project
- [rofl0r](https://github.com/rofl0r/oneshot) for original oneshot

## Disclaimer
- This tool is intended for educational and authorized penetration testing purposes only.
- It is not designed for, and must not be used for, illegal activities such as hacking, unauthorized access, or causing damage to systems or networks.
- By using this tool, you agree to use it responsibly and ethically, and to comply with all applicable laws and regulations.
- The developer assumes no responsibility for any misuse of this tool.
