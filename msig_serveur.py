#!/usr/bin/env python3
"""
msig_serveur.py - local gateway between the web editor and the DSP7000.

The editor (msig_editeur.html) is served on http://127.0.0.1:8000 and talks to the
DSP through this server, which uses pyserial (the link validated with msig_mac.py).
It is also the program of the Linux version (editor in the browser); on Mac,
msig_app.py runs it inside a native window.

    python3 msig_serveur.py                        # port detected automatically
    python3 msig_serveur.py --port /dev/cu.usbserial-XXXX

The module database (203 modules on the DSP7000) is not distributed: it is read from
the DSP on first use (editor button), then kept in
~/Library/Application Support/MSIG/modules_dsp.json (Mac) or ~/.local/share/msig (Linux).
It can also come from a file (text .sbf from the old Windows software, .syx): the
"Import database file" button, or a .sbf file dropped into that folder (detected at startup).
"""
import argparse
import base64
import errno
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import msig_mac as v  # noqa: E402
from msig_dbase import convert, extract_text  # noqa: E402

VERSION = "1.0.9"
BUNDLE = getattr(sys, "_MEIPASS", None)  # resources folder inside MSIG.app (PyInstaller)


MAC = sys.platform == "darwin"


def data_dir():
    if MAC:
        d = os.path.expanduser("~/Library/Application Support/MSIG")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        d = os.path.join(base, "msig")
    os.makedirs(d, exist_ok=True)
    return d


def log_path():
    """Log of the packaged application (no terminal to show the messages)."""
    if MAC:
        return os.path.expanduser("~/Library/Logs/MSIG.log")
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "msig", "msig.log")


def open_log(suffix=""):
    log = log_path()
    os.makedirs(os.path.dirname(log), exist_ok=True)
    sys.stdout = sys.stderr = open(log, "a", buffering=1)
    print(time.strftime("--- %Y-%m-%d %H:%M:%S"), "MSIG", VERSION, sys.platform, suffix)


def find_editor():
    names = ("msig_editeur_public.html", "msig_editeur.html")
    dirs = [d for d in (BUNDLE, HERE, os.path.join(HERE, "editeur")) if d]
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    sys.exit("msig_editeur.html not found: place it next to msig_serveur.py")


# Serial ports. USB-serial adapters (FTDI, Prolific, CH340, CP210x) come first and are the
# only ones picked automatically. "usbmodem" (Mac) and "ttyACM" (Linux) ports belong to
# USB-MIDI devices and sound cards: they are listed for manual selection, but never
# connected to on their own (1.0.3 took the first one in alphabetical order and could
# send commands to another machine).
SERIAL_PATTERNS = ("/dev/cu.usbserial*", "/dev/cu.PL2303*", "/dev/cu.SLAB_USBtoUART*",
                   "/dev/cu.wchusbserial*", "/dev/ttyUSB*")
OTHER_PATTERNS = ("/dev/cu.usbmodem*", "/dev/ttyACM*")


def _glob(patterns):
    out = []
    for pat in patterns:
        out += [p for p in sorted(glob.glob(pat)) if p not in out]
    return out


def _linux_native_ports():
    """Motherboard serial ports (ttyS*) that are actually present, via pyserial."""
    if MAC:
        return []
    try:
        from serial.tools import list_ports as lp
        return sorted(p.device for p in lp.comports() if p.device.startswith("/dev/ttyS"))
    except Exception:
        return []


def list_ports():
    """Ports offered in the editor: serial adapters first, then the others."""
    first = _glob(SERIAL_PATTERNS)
    return first + [p for p in _linux_native_ports() + _glob(OTHER_PATTERNS) if p not in first]


def auto_port():
    """Port chosen at startup: a USB-serial adapter only, otherwise none."""
    return next(iter(_glob(SERIAL_PATTERNS)), None)


def explain_serial_error(port, e):
    """Clear message for the most common open errors."""
    no = getattr(e, "errno", None)
    text = str(e)
    if no == errno.EACCES or "Permission denied" in text:
        if MAC:
            return f"{port}: permission denied"
        return (f"{port}: permission denied. Add your user to the serial group "
                "(sudo usermod -aG dialout $USER, or 'uucp' on Arch), then log out and back in.")
    if no == errno.EBUSY or "busy" in text.lower() or "exclusively lock" in text:
        return f"{port}: port busy (another program, or another MSIG, is using it)"
    if no == errno.ENOENT or "No such file" in text:
        return f"{port}: adapter not found (unplugged?)"
    return f"{port}: {text}"


class Bridge:
    def __init__(self, baud, dev_id):
        self.lock = threading.Lock()
        self.baud = baud
        self.dev_id = dev_id
        self.port = None
        self.dev = None
        self.modules_path = os.path.join(data_dir(), "modules_dsp.json")
        self.settings_path = os.path.join(data_dir(), "settings.json")
        self.stopbits = 2
        try:   # last settings chosen in the editor
            with open(self.settings_path) as f:
                saved = json.load(f)
            self.baud = int(saved.get("baud") or self.baud)
            self.stopbits = 1 if int(saved.get("stopbits") or 2) == 1 else 2
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        self.job = {"running": False}   # database read in progress (separate thread)
        self.tried = {}                 # .sbf files already tried (path -> mtime)

    # ---- link
    def connect(self, port, baud=None, stopbits=None):
        self._idle()
        with self.lock:
            if self.dev:
                self.dev.link.close()
                self.dev, self.port = None, None
            self.baud = baud or self.baud
            if stopbits in (1, 2):
                self.stopbits = stopbits
            try:
                link = v.SerialLink(port, self.baud, self.stopbits, False)
            except Exception as e:
                raise RuntimeError(explain_serial_error(port, e)) from e
            self.dev = v.Device(link, self.dev_id)
            self.port = port
            print(f"serial {port}: {link.describe()}")
        try:
            with open(self.settings_path, "w") as f:
                json.dump({"baud": self.baud, "stopbits": self.stopbits}, f)
        except OSError:
            pass
        return self.status()

    def _idle(self):
        if self.job.get("running"):
            raise RuntimeError("busy: the module database is being read from the DSP")

    def _need(self):
        if not self.dev:
            raise RuntimeError("DSP not connected: choose the serial port")
        self.dev.parser = v.SysexParser()
        self.dev.link.ser.reset_input_buffer()

    def status(self):
        if not os.path.exists(self.modules_path):
            self.autodetect()
        return {"port": self.port, "baud": self.baud, "stopbits": self.stopbits, "ports": list_ports(),
                "modules": os.path.exists(self.modules_path), "version": VERSION,
                "dbase": dict(self.job), "data_dir": data_dir(),
                "dialogs": DIALOGS["save"] is not None, "platform": sys.platform}

    # ---- DSP commands
    def get_algo(self):
        self._idle()
        with self.lock:
            self._need()
            self.dev.send(v.CMD["GET_SIGFILE"])
            # no fixed total timeout: some units (reduced SysEx speed) take much longer
            # than the ~1 s of the DSP7000 (see Device.receive_dump)
            self.dev.raw = bytearray()
            try:
                payload = self.dev.receive_dump({0x08, 0x0A}, first=30, idle=15, settle=0.3)
            except TimeoutError:
                self._garbled()
                raise
            finally:
                self._log("get algorithm", "last-get.bin")
            return {"text": payload.decode("latin1").strip()}

    def send_algo(self, text):
        data = text.encode("latin1", "ignore")
        data = bytes(b for b in data if b < 0x80)
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").strip().replace(b"\n", b"\r\n")
        self._idle()
        with self.lock:
            self._need()
            self.dev.raw = bytearray()
            self.dev.send(v.CMD["SIGFILE_TEXT"], data)
            err = None
            frames = self.dev.collect(4)
            self._save_raw("last-send.bin")
            for fr in frames:
                p = v.parse_frame(fr)
                if p and p[1] == v.CMD["ERROR_TEXT"]:
                    err = p[2].decode("latin1").strip()
            print(f"send to DSP: {len(data)} bytes; reply frames: "
                  + (", ".join(f"{fr[:32].hex(' ')}{' ...' if len(fr) > 32 else ''} ({len(fr)} bytes)"
                               for fr in frames[:12]) or "none"))
            for fr in frames:
                if len(fr) > 5 and fr[1] == v.MFR_ID and fr[4] in (v.CMD["ERROR_TEXT"], 0x3C):
                    print(f"  unit text 0x{fr[4]:02X}: {fr[5:-1].decode('latin1').strip()[:200]}")
            return {"sent": len(data), "error": err}

    def screen(self):
        self._idle()
        with self.lock:
            self._need()
            self.dev.send(v.CMD["GET_SCREEN"])
            self.dev.raw = bytearray()
            try:
                payload = self.dev.receive_dump({0x17}, first=30, idle=15, settle=0.3)
            except TimeoutError:
                self._garbled()
                raise
            finally:
                self._log("screen", "last-screen.bin")
            w, h, img = v.decode_screen_dump(payload)
            return {"w": w, "h": h, "img": base64.b64encode(img).decode()}

    def _garbled(self):
        if v.looks_garbled(self.dev.raw):
            raise RuntimeError(
                f"the DSP answered, but its reply arrived garbled ({self.baud} baud, {self.stopbits} "
                "stop bits): the serial settings of the unit and of MSIG do not match. Check that "
                "the unit's stop bits match MSIG's (2 by default; an H8000 set to 1 stop bit gives "
                "exactly this) and that the speeds are the same, then click Reconnect. If it "
                "persists, send ~/Library/Logs/MSIG.log and the last-*.bin files of the MSIG folder.")

    def _save_raw(self, name):
        """Raw bytes received during the last command (file replaced each time)."""
        try:
            with open(os.path.join(data_dir(), name), "wb") as f:
                f.write(bytes(self.dev.raw))
        except OSError as e:
            print(f"{name}: {e}")

    def _log(self, what, raw_name):
        """Summary of the last reply in the log (diagnostics on other units)."""
        self._save_raw(raw_name)
        r = getattr(self.dev, "last_reply", None) or {}
        print(f"{what}: {r.get('bytes', 0)} bytes in {r.get('seconds', 0)} s, "
              f"{r.get('frames', 0)} reply frame(s), header form: {r.get('form') or 'none'}; "
              f"raw bytes saved to {raw_name}")
        for h in r.get("heads") or []:
            print("  frame:", h)
        for n in r.get("notes") or []:
            print("  unit text", n)
        if r.get("pending"):
            print("  unterminated data:", r["pending"])
        if r.get("others"):
            print("  ignored:", ", ".join(r["others"][:8]))

    # ---- module database
    def load_dbase(self):
        """Start reading the database from the DSP in a separate thread and return at once:
        the editor follows the progress through /api/dbase-progress. Duration: ~25 s for the
        264 KB of the DSP7000, several minutes for a larger database or a reduced SysEx speed
        on the unit. No fixed total timeout (see Device.receive_dump)."""
        self._idle()
        if not self.dev:
            raise RuntimeError("DSP not connected: choose the serial port")
        self.job = {"running": True, "bytes": 0, "frames": 0, "seconds": 0}
        threading.Thread(target=self._read_dbase, daemon=True).start()
        return dict(self.job)

    def _read_dbase(self):
        def progress(n, frames, t):
            self.job.update(bytes=n, frames=frames, seconds=int(t))
        try:
            with self.lock:
                self._need()
                self.dev.send(v.CMD["GET_DBASE"])
                text = self.dev.receive_dump(v.CMD["DBASE_TEXT"], progress=progress)
            print(f"module database: {len(text)} bytes received in {self.job['seconds']} s")
            n = self._store(text, "DSP")
            self.job.update(running=False, done=True, count=n)
        except Exception as e:
            print("module database:", e)
            self.job.update(running=False, error=str(e))

    def _store(self, raw, source):
        text = extract_text(raw)
        mods = convert(text)
        if not mods:
            raise RuntimeError(f"no module found in the {source} data: unknown or damaged format")
        d = data_dir()
        for name, data in (("modules_dsp.txt", text),
                           ("modules_dsp.json", json.dumps(mods, separators=(",", ":")).encode())):
            tmp = os.path.join(d, name + ".tmp")
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, os.path.join(d, name))
        return len(mods)

    def import_dbase(self, raw=None, path=None, folder=None):
        """Module database from a file: bytes sent by the editor (browser file field), a given
        path, or a file chosen in a dialog."""
        self._idle()
        if raw is None:
            if not path:
                if DIALOGS.get("open_dbase") is None:
                    raise RuntimeError("no file dialog available")
                path = DIALOGS["open_dbase"](folder)
                if path is None:
                    return {"cancelled": True}
            with open(path, "rb") as f:
                raw = f.read()
        name = os.path.basename(path) if path else "file"
        n = self._store(raw, name)
        print(f"module database imported from {path or 'editor'}: {n} modules")
        return {"count": n, "name": name}

    def autodetect(self):
        """No database: look for a .sbf file (e.g. sigdbase.sbf) in the MSIG folder."""
        d = data_dir()
        try:
            names = [n for n in os.listdir(d) if n.lower().endswith(".sbf")]
        except OSError:
            return None
        names.sort(key=lambda n: (n.lower() != "sigdbase.sbf", -os.path.getmtime(os.path.join(d, n))))
        for n in names:
            p = os.path.join(d, n)
            stamp = os.path.getmtime(p)
            if self.tried.get(p) == stamp:
                continue
            self.tried[p] = stamp
            try:
                r = self.import_dbase(path=p)
                self.job = {"running": False, "done": True, "count": r["count"], "file": n}
                return r
            except Exception as e:
                print(f"{p}: {e}")
        return None

    def modules(self):
        if not os.path.exists(self.modules_path):
            return None
        with open(self.modules_path, "rb") as f:
            return f.read()


# ---- files: native macOS dialogs (Open, Save As)
def _as_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _osascript(lines):
    """Run an AppleScript; None if the user cancels the dialog."""
    args = ["/usr/bin/osascript"]
    for line in lines:
        args += ["-e", line]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        if "-128" in r.stderr:
            return None
        raise RuntimeError(r.stderr.strip() or "file dialog failed")
    return r.stdout.strip()


def _where(folder):
    folder = os.path.expanduser(folder or "")
    if not os.path.isdir(folder):
        folder = os.path.expanduser("~/Documents")
    return " default location (POSIX file " + _as_str(folder) + ")"


def _sig_path(path):
    path = os.path.abspath(os.path.expanduser(path))
    if not path.lower().endswith((".sig", ".txt")):
        path += ".sig"
    return path


def write_patch(path, text):
    path = _sig_path(path)
    data = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="latin-1", errors="replace", newline="") as f:
        f.write(data)
    os.replace(tmp, path)
    return {"path": path, "name": os.path.basename(path)}


def _ask_save_path(name, folder):
    return _osascript(["activate",
                       "set f to choose file name with prompt " + _as_str("Save patch as") +
                       " default name " + _as_str(name) + _where(folder),
                       "POSIX path of f"])


def _ask_open_path(folder):
    return _osascript(["activate",
                       "set f to choose file with prompt " + _as_str("Open patch") + _where(folder),
                       "POSIX path of f"])


def _ask_open_dbase(folder):
    return _osascript(["activate",
                       "set f to choose file with prompt " + _as_str("Module database file (.sbf, .syx)") +
                       _where(folder or "~/Downloads"),
                       "POSIX path of f"])


# ---- Linux: zenity (GNOME, Xfce...) or kdialog (KDE) dialogs if installed;
# otherwise the editor uses the browser's (file field, download).
def _home_folder(folder):
    folder = os.path.expanduser(folder or "")
    return folder if os.path.isdir(folder) else os.path.expanduser("~")


def _run_dialog(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:  # 1 = cancelled
        return None
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else None


def _zenity_save(name, folder):
    return _run_dialog(["zenity", "--file-selection", "--save", "--confirm-overwrite",
                        "--title=Save patch as", "--file-filter=Patches (*.sig) | *.sig *.txt",
                        "--filename=" + os.path.join(_home_folder(folder), name)])


def _zenity_open(folder):
    return _run_dialog(["zenity", "--file-selection", "--title=Open patch",
                        "--file-filter=Patches (*.sig *.txt) | *.sig *.txt *.SIG *.TXT",
                        "--file-filter=All files | *",
                        "--filename=" + _home_folder(folder) + os.sep])


def _zenity_open_dbase(folder):
    return _run_dialog(["zenity", "--file-selection", "--title=Module database file",
                        "--file-filter=Module database (*.sbf *.syx *.txt) | *.sbf *.SBF *.syx *.SYX *.txt *.TXT",
                        "--file-filter=All files | *",
                        "--filename=" + _home_folder(folder or "~/Downloads") + os.sep])


def _kdialog_open_dbase(folder):
    return _run_dialog(["kdialog", "--title", "Module database file", "--getopenfilename",
                        _home_folder(folder or "~/Downloads"), "*.sbf *.SBF *.syx *.SYX *.txt *.TXT"])


def _kdialog_save(name, folder):
    return _run_dialog(["kdialog", "--title", "Save patch as", "--getsavefilename",
                        os.path.join(_home_folder(folder), name), "*.sig *.txt"])


def _kdialog_open(folder):
    return _run_dialog(["kdialog", "--title", "Open patch", "--getopenfilename",
                        _home_folder(folder), "*.sig *.txt *.SIG *.TXT"])


def _default_dialogs():
    none = {"save": None, "open": None, "open_dbase": None}
    if MAC:
        return {"save": _ask_save_path, "open": _ask_open_path, "open_dbase": _ask_open_dbase}
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return none
    if shutil.which("zenity"):
        return {"save": _zenity_save, "open": _zenity_open, "open_dbase": _zenity_open_dbase}
    if shutil.which("kdialog"):
        return {"save": _kdialog_save, "open": _kdialog_open, "open_dbase": _kdialog_open_dbase}
    return none


# File dialogs and program exit: the native window (msig_app.py) replaces these
# functions with panels attached to its window and with quitting the application.
DIALOGS = _default_dialogs()
HOOKS = {"quit": None}


def save_as(name, text, folder):
    if DIALOGS["save"] is None:
        raise RuntimeError("no file dialog available")
    p = DIALOGS["save"](name or "patch.sig", folder)
    return {"cancelled": True} if p is None else write_patch(p, text)


def open_patch(folder):
    if DIALOGS["open"] is None:
        raise RuntimeError("no file dialog available")
    p = DIALOGS["open"](folder)
    if p is None:
        return {"cancelled": True}
    with open(p, "r", encoding="latin-1") as f:
        return {"path": p, "name": os.path.basename(p), "text": f.read()}


def make_handler(bridge, editor, http_port, beat):
    allowed = {f"127.0.0.1:{http_port}", f"localhost:{http_port}"}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _trusted(self):
            # Only the editor served here may drive the DSP: refuse requests coming from
            # other sites open in the browser (Host and Origin headers).
            if self.headers.get("Host") not in allowed:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin.split("//", 1)[-1] in allowed

        def do_GET(self):
            if not self._trusted():
                return self._send(403, {"error": "origin refused"})
            beat[0] = time.time()
            if self.path in ("/", "/index.html", "/msig_editeur.html"):
                with open(editor, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._send(200, bridge.status())
            elif self.path == "/api/dbase-progress":
                self._send(200, dict(bridge.job))
            elif self.path == "/api/modules":
                m = bridge.modules()
                self._send(200, m) if m else self._send(404, {"error": "module database missing"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._trusted():
                return self._send(403, {"error": "origin refused"})
            beat[0] = time.time()
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            body = raw.decode("utf-8", "replace")
            try:
                if self.path == "/api/get-algo":
                    self._send(200, bridge.get_algo())
                elif self.path == "/api/send-algo":
                    self._send(200, bridge.send_algo(body))
                elif self.path == "/api/screen":
                    self._send(200, bridge.screen())
                elif self.path == "/api/load-dbase":
                    self._send(200, bridge.load_dbase())
                elif self.path == "/api/import-dbase":
                    # empty body: Open dialog; otherwise the content of the file chosen in the browser
                    self._send(200, bridge.import_dbase(raw) if raw else bridge.import_dbase())
                elif self.path == "/api/connect":
                    j = json.loads(body or "{}")
                    self._send(200, bridge.connect(j["port"], int(j.get("baud") or bridge.baud),
                                                   int(j.get("stopbits") or bridge.stopbits)))
                elif self.path == "/api/open":
                    j = json.loads(body or "{}")
                    self._send(200, open_patch(j.get("dir")))
                elif self.path == "/api/save-as":
                    j = json.loads(body or "{}")
                    self._send(200, save_as(j.get("name"), j["text"], j.get("dir")))
                elif self.path == "/api/save":
                    j = json.loads(body or "{}")
                    self._send(200, write_patch(j["path"], j["text"]))
                elif self.path == "/api/ping":
                    self._send(200, {"ok": True})
                elif self.path == "/api/quit":
                    self._send(200, {"ok": True})
                    threading.Thread(target=HOOKS["quit"] or self.server.shutdown, daemon=True).start()
                else:
                    self._send(404, {"error": "not found"})
            except Exception as e:  # DSP errors, timeouts, busy port
                self._send(500, {"error": str(e)})
    return H


def already_running(url):
    try:
        with urllib.request.urlopen(url + "api/status", timeout=2) as r:
            return "version" in json.loads(r.read())
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description="MSIG: web editor <-> DSP7000 gateway")
    ap.add_argument("--port", help="serial port (default: first USB-serial adapter)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--id", type=int, default=1)
    ap.add_argument("--http", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    ap.add_argument("--auto-quit", type=int, default=0, metavar="S",
                    help="stop S seconds after the editor is closed (used by MSIG.app)")
    a = ap.parse_args()
    if BUNDLE and not (sys.stdout and sys.stdout.isatty()):
        open_log("(browser)")  # launched from the applications menu: messages go to the log
    if BUNDLE and not a.auto_quit:
        a.auto_quit = 300  # no window of its own: MSIG stops when the editor is closed

    url = f"http://127.0.0.1:{a.http}/"
    bridge = Bridge(a.baud, a.id)
    beat = [time.time()]
    editor = find_editor()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.http), BaseHTTPRequestHandler)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        if already_running(url):
            print("MSIG is already running:", url)
            webbrowser.open(url)  # already running: just reopen the editor
            return
        # port used by another program: free port chosen by the system
        srv = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    http_port = srv.server_address[1]
    url = f"http://127.0.0.1:{http_port}/"
    srv.RequestHandlerClass = make_handler(bridge, editor, http_port, beat)

    port = a.port or auto_port()
    if port:
        try:
            bridge.connect(port)
            print(f"DSP on {port} at {a.baud} baud.")
        except Exception as e:
            print(f"{e} (choose the port in the editor)")
    else:
        print("no USB-serial adapter detected: plug it in, then choose the port in the editor")
    print(f"Editor: {url}  (Ctrl-C to stop)")

    if a.auto_quit:
        def watchdog():
            while True:
                time.sleep(5)
                if time.time() - beat[0] > a.auto_quit:
                    srv.shutdown()
                    return
        threading.Thread(target=watchdog, daemon=True).start()

    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if bridge.dev:
            bridge.dev.link.close()


if __name__ == "__main__":
    main()
