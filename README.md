# MSIG

MSIG is an editor for modular DSP rack units of the DSP7000 family: it reads,
edits and sends algorithms ("sigfiles") and patches over RS-232 (SysEx).
It runs as a native app on macOS and as a browser-based editor on Linux.

- Graphical patch editor: modules, cables between pins, parameters, undo/redo.
- Get the algorithm loaded in the unit, send an edited one back, grab the unit's screen.
- The module list (names, parameters, outputs) is read from your own unit once,
  or imported from a database file, and kept on your computer.
- Random patch generator with several characters and shapes.

Tested on a DSP7000 (author) and an H8000 (user report). Other units of the family
have not been tested.

## Disclaimer

MSIG is an independent project by Moteka. It is not associated with, endorsed by or
supported by Eventide Inc., which is not responsible for any issue that may occur when
using MSIG with its products. MSIG contains none of the manufacturer's software or data:
the module list is read from your own unit. Provided as is, without warranty. Back up
your unit's programs before sending anything to it.

## Hardware

- A USB to RS-232 adapter (FTDI, Prolific or CH340) and a straight-through DB9 cable
  (not null-modem).
- On the unit: RS-232 at 115200 baud, 2 stop bits, SysEx on, MIDI device ID 1.
  The speed and stop bits chosen in MSIG (next to the serial port menu) must match the
  unit's settings. A mismatch in stop bits makes long replies (Get algorithm, Screen)
  arrive garbled while short messages still pass.

## Running from source

Python 3 (developed with 3.13).

macOS (native window):

    python3 -m venv ~/.venvs/msig
    ~/.venvs/msig/bin/pip install pyserial pyobjc-framework-WebKit
    python3 editeur/build.py
    ~/.venvs/msig/bin/python msig_app.py                       # auto-picks /dev/cu.usbserial*
    ~/.venvs/msig/bin/python msig_app.py --port /dev/cu.xxx    # or a given port

Linux, or any system with a browser (local gateway on http://127.0.0.1:8000):

    python3 -m venv ~/.venvs/msig
    ~/.venvs/msig/bin/pip install pyserial
    python3 editeur/build.py
    ~/.venvs/msig/bin/python msig_serveur.py

Command line tool (get/send an algorithm, screen dump, module database, monitor):

    python3 msig_mac.py --port /dev/cu.xxx get-algo -o algo.sig
    python3 msig_mac.py --port /dev/cu.xxx send-algo algo.sig
    python3 msig_mac.py --help

Data and logs: `~/Library/Application Support/MSIG` and `~/Library/Logs/MSIG.log` on macOS,
`~/.local/share/msig` and `~/.local/state/msig` on Linux.

## Building

- macOS app and DMG: `bash app/build_app.sh` (see the header of the script for
  `PYTHON`, `TARGET_ARCH=universal2`, and the optional signing variables
  `SIGN_IDENTITY`, `NOTARY_PROFILE`, `TEAM_ID`).
- Linux x86_64 archive: `bash app/build_linux.sh` (on Linux; uses `uv` or `PYTHON`).

Both put their output in `dist/`.

## Tests

    python3 -m venv .venv && .venv/bin/pip install pytest pyserial
    .venv/bin/python -m pytest tests/

The tests never open a real serial port: they use a simulated unit on a pseudo-terminal,
pyserial's `loop://` port and in-memory links. `tests/sigfile_args.test.js` runs with
Node.js when it is installed.

## Serial protocol (summary)

The serial link carries raw MIDI SysEx bytes, with no extra framing:

    F0 1C 70 <id> <cmd> [data] F7

`1C` is the manufacturer ID, `70` the model byte used for every unit of the family,
`<id>` the device ID (1 by default). Main commands:

| cmd  | direction | meaning |
|------|-----------|---------|
| `0B` | to unit   | get the current algorithm |
| `0A` | both      | algorithm as text (reply to `0B`, or sent to load it) |
| `08` | both      | same, errors shown on the unit |
| `0D` | from unit | error message (text) |
| `0E` | to unit   | get the module database |
| `0C` | from unit | module database (text, one or more frames) |
| `18` | to unit   | get the screen |
| `17` | from unit | screen: 3 big-endian 32-bit integers (width, height, size) then a 1 bit per pixel image, all sent as nibbles |

Algorithms are plain text, one module per line (`TYPE name arg1 arg2 ...`), CRLF line
endings. The module database is a text file of records between braces (`TYPE:`, `NAME:`,
`MINIMUM:`, `MAXIMUM:`, `DEFAULT:`, `CONNECT_TAG:` ...); `msig_dbase.py` converts it to
the JSON used by the editor. Some fields set how many arguments follow (number of
outputs, inputs, sections), which the editor expands.

## Layout

- `msig_mac.py`: SysEx framing, serial link, command line tool.
- `msig_serveur.py`: local HTTP gateway between the editor and the unit.
- `msig_app.py`: macOS window (PyObjC, WKWebView) around the gateway.
- `msig_dbase.py`: module database text to JSON.
- `editeur/`: the editor (`editeur.src.html`, `sigfile.js`, `random.js`), assembled into
  one HTML file by `editeur/build.py`.
- `app/`: build scripts, icon, end-user READMEs.

Code comments are in English.

## License

MIT, see [LICENSE](LICENSE).
