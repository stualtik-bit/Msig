#!/usr/bin/env python3
"""
msig_mac.py - communication (macOS and Linux) with a DSP7000 (and units of the same family)
over RS-232 (USB-serial adapter)
or through a MIDI interface.

Protocol reconstructed by static analysis (interoperability).

SysEx frame:  F0 1C 70 <id> <cmd> [data] F7
  1C = manufacturer ID, 70 = model (DSP4000/7000 family),
  id = "device ID" (default 1, must match the unit's SETUP/MIDI setting).

Over RS-232 the MIDI bytes are sent as is (no encapsulation).
"""
import argparse
import sys
import time

MFR_ID = 0x1C
MODEL_DSP = 0x70

# Observed command codes
CMD = {
    "SIGFILE_TEXT_ERRS_ON_UNIT": 0x08,  # send/receive text sigfile ("errors on unit screen" variant)
    "SIGFILE_TEXT": 0x0A,               # send/receive text sigfile
    "GET_SIGFILE": 0x0B,                # menu MIDI > Get / Update params
    "DBASE_TEXT": 0x0C,                 # reply to GET_DBASE (DSP7000: a single 264 KB frame)
    "ERROR_TEXT": 0x0D,                 # text error message returned by the unit
    "GET_DBASE": 0x0E,                  # menu MIDI > Get Dbase
    "SEND_USER_FILES": 0x0F,            # (not implemented)
    "GET_USER_FILES": 0x10,
    "SEND_SETUP": 0x11,                 # (not implemented)
    "GET_SETUP": 0x12,
    "BIN_CARD": 0x13,                   # binary file received -> card.bin
    "BIN_PROG": 0x15,                   # binary file received -> prog.bin / compiled algorithm upload
    "BIN_SETUP": 0x16,                  # binary file received -> setup.bin
    "SCREEN_DUMP": 0x17,                # reply to GET_SCREEN
    "GET_SCREEN": 0x18,
    "PROGNUMS_DUMP": 0x30,
    "GET_PRESET_ALT": 0x35,
    "PRESET_ALT_TEXT": 0x36,
    "BIN_DATA": 0x39,                   # binary file received -> data.bin
    "TEXT_NIBBLES": 0x40,
    "SCREEN_DUMP_ALT": 0x42,
}
CMD_NAME = {v: k for k, v in CMD.items()}
TEXT_REPLIES = {0x08, 0x0A, 0x19, 0x22, 0x2C, 0x2D, 0x2E, 0x32, 0x34, 0x36, 0x3C}
BINARY_FILE_REPLIES = {0x13: "card.bin", 0x15: "prog.bin", 0x16: "setup.bin", 0x39: "data.bin"}


# --------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------
def build_sysex(cmd, data=b"", dev_id=1):
    data = bytes(data)
    if any(b & 0x80 for b in data):
        raise ValueError("SysEx data must be 7-bit (use nibbleize)")
    return bytes([0xF0, MFR_ID, MODEL_DSP, dev_id & 0x7F, cmd & 0x7F]) + data + b"\xF7"


def _nib(b):
    return bytes([(b >> 4) & 0x0F, b & 0x0F])


def nibbleize(data, with_length=True):
    """Nibble encoding of binary data.
    [32-bit big-endian length as nibbles] + bytes as nibbles (high nibble first)
    + checksum = -(sum of bytes, length included) & 0xFF, as nibbles."""
    out = bytearray()
    csum = 0
    if with_length:
        for b in len(data).to_bytes(4, "big"):
            out += _nib(b)
            csum += b
    for b in data:
        out += _nib(b)
        csum += b
    out += _nib((-csum) & 0xFF)
    return bytes(out)


def denibbleize(nibbles):
    """(high, low) nibble pairs -> bytes."""
    n = len(nibbles) // 2
    return bytes(((nibbles[2 * i] & 0x0F) << 4) | (nibbles[2 * i + 1] & 0x0F) for i in range(n))


# --------------------------------------------------------------------------
# Decoding the incoming stream
# --------------------------------------------------------------------------
class SysexParser:
    """Accumulates a MIDI byte stream and extracts F0..F7 frames."""

    def __init__(self):
        self.buf = bytearray()
        self.inside = False

    def feed(self, chunk):
        msgs = []
        for b in chunk:
            if b == 0xF0:
                self.buf = bytearray([b])
                self.inside = True
            elif self.inside:
                if b >= 0xF8:          # real-time messages: ignored inside a SysEx
                    continue
                self.buf.append(b)
                if b == 0xF7:
                    msgs.append(bytes(self.buf))
                    self.inside = False
        return msgs


def parse_frame(frame):
    """Returns (dev_id, cmd, payload), or None if the frame is not a DSP frame."""
    if len(frame) < 6 or frame[0] != 0xF0 or frame[-1] != 0xF7:
        return None
    # model byte not checked: we send 70 (like the original software, for all units)
    # but some units of the family reply with their own value
    if frame[1] != MFR_ID:
        return None
    return frame[3], frame[4], frame[5:-1]


def describe(frame):
    p = parse_frame(frame)
    if not p:
        return "non-DSP frame: " + frame[:16].hex(" ")
    dev, cmd, payload = p
    name = CMD_NAME.get(cmd, "UNKNOWN")
    return f"id={dev} cmd=0x{cmd:02X} ({name}) {len(payload)} bytes"


def decode_screen_dump(payload):
    """Reply 0x17. Inferred: 12-byte header (three 32-bit BE integers, as nibbles),
    then the image as nibbles. Assumed to be (width, height, size) - NOT VERIFIED."""
    head = denibbleize(payload[:24])
    a, b, size = (int.from_bytes(head[i:i + 4], "big") for i in (0, 4, 8))
    img = denibbleize(payload[24:24 + 2 * size])
    return a, b, img


def looks_garbled(raw):
    """Garbled reply: the DSP7000 only sends MIDI bytes (data < 0x80 between F0 and F7).
    Many bytes >= 0x80 mean the serial settings differ between the unit and MSIG
    (mostly stop bits: H8000 set to 1 stop bit, MSIG to 2)."""
    return sum(1 for b in bytes(raw) if b >= 0x80 and b not in (0xF0, 0xF7)) >= 8


def write_pbm(path, width, height, img):
    """Writes a 1 bit/pixel PBM if the dimensions match the received size."""
    row = (width + 7) // 8
    if row * height > len(img):
        return False
    with open(path, "wb") as f:
        f.write(f"P4\n{width} {height}\n".encode())
        f.write(img[: row * height])
    return True


# --------------------------------------------------------------------------
# Transports
# --------------------------------------------------------------------------
class SerialLink:
    """Serial port, 8 bits, no parity, 2 stop bits by default (8N2), same setting in both
    directions. The stop bits must match the unit's setting: an H8000 set to 1 stop bit
    replies in 8N1 with back-to-back bytes, and its replies arrive garbled in 8N2.
    The setting is never changed while the port is open: 1.0.8 did so on every send and
    lost requests (the USB adapter was still transmitting)."""

    def __init__(self, port, baud=115200, stopbits=2, rtscts=False):
        import serial  # pyserial
        kw = {"exclusive": True} if port.startswith("/dev/") else {}  # one program at a time
        self.ser = serial.serial_for_url(
            port, baudrate=baud, bytesize=8, parity="N",
            stopbits=stopbits, rtscts=rtscts, timeout=0.1, **kw)

    def write(self, data):
        self.ser.write(data)
        self.ser.flush()

    def describe(self):
        n = self.ser.stopbits
        return f"{self.ser.baudrate} baud, 8 data bits, no parity, {n} stop bit{'s' if n > 1 else ''}"

    def read(self):
        return self.ser.read(4096)

    def close(self):
        self.ser.close()


class MidiLink:
    """Optional MIDI transport (pip install mido python-rtmidi)."""

    def __init__(self, in_name, out_name):
        import mido
        self.mido = mido
        self.out = mido.open_output(out_name)
        self.inp = mido.open_input(in_name)

    def write(self, data):
        msg = self.mido.Message.from_bytes(list(data))
        self.out.send(msg)

    def read(self):
        out = bytearray()
        for msg in self.inp.iter_pending():
            out += bytes(msg.bytes())
        if not out:
            time.sleep(0.05)
        return bytes(out)

    def close(self):
        self.inp.close()
        self.out.close()


class Device:
    def __init__(self, link, dev_id=1, verbose=False):
        self.link = link
        self.dev_id = dev_id
        self.parser = SysexParser()
        self.verbose = verbose
        self.raw = bytearray()

    def send(self, cmd, data=b""):
        frame = build_sysex(cmd, data, self.dev_id)
        if self.verbose:
            print(">>", frame[:32].hex(" "), "..." if len(frame) > 32 else "", file=sys.stderr)
        self.link.write(frame)

    def wait_for(self, cmds, timeout=10.0, idle=None):
        """Waits for a frame whose command is in `cmds`. 0x0D errors are raised."""
        end = time.time() + timeout
        while time.time() < end:
            chunk = self._read()
            for fr in self.parser.feed(chunk):
                if self.verbose:
                    print("<<", describe(fr), file=sys.stderr)
                p = parse_frame(fr)
                if not p:
                    continue
                _, cmd, payload = p
                if cmd == CMD["ERROR_TEXT"]:
                    raise RuntimeError("Device error: " + payload.decode("latin1").strip())
                if cmd in cmds:
                    return cmd, payload
        raise TimeoutError("no response (check cabling, baud rate, SysEx=on, device ID)")

    def _read(self):
        """Reads the link; all received bytes are also kept in self.raw (diagnostics)."""
        chunk = self.link.read()
        if chunk and len(self.raw) < 8_000_000:
            self.raw += chunk
        return chunk

    def receive_dump(self, cmd, first=60.0, idle=30.0, limit=1800.0, progress=None,
                     settle=2.0):
        """Receives a large reply (module database) with no fixed total duration.

        The duration depends on the unit, the size of its database and the unit's SysEx
        speed setting: from 25 s (DSP7000, 264 KB) to several minutes. So we keep waiting
        as long as bytes arrive; fails if nothing arrives for `first` seconds after the
        request, or for `idle` seconds during the transfer, or beyond `limit`.
        Manufacturer frames carrying `cmd` (one command or a set) are concatenated
        (whatever the model byte); we return `settle` seconds after the last frame kept.

        `progress(bytes, frames, seconds)` is called regularly. Returns the data (bytes)
        without the SysEx headers; a summary of the exchange (start of each frame, header
        form, unit texts, duration) is kept in self.last_reply."""
        cmds = {cmd} if isinstance(cmd, int) else set(cmd)
        start = last = got = time.time()
        total, parts, others, heads, notes, tick = 0, [], [], [], [], 0.0
        self.last_reply = {"bytes": 0, "frames": 0, "heads": heads, "others": others,
                           "notes": notes, "form": None, "seconds": 0, "pending": ""}
        while True:
            now = time.time()
            chunk = self._read()
            if chunk:
                total += len(chunk)
                last = now
            for fr in self.parser.feed(chunk):
                if self.verbose:
                    print("<<", describe(fr), file=sys.stderr)
                if len(heads) < 24:
                    heads.append(f"{fr[:32].hex(' ')}{' ...' if len(fr) > 32 else ''} ({len(fr)} bytes)")
                if len(fr) >= 6 and fr[1] == MFR_ID:
                    if fr[4] in (CMD["ERROR_TEXT"], 0x3C) and len(notes) < 8:
                        notes.append(f"0x{fr[4]:02X}: " + fr[5:-1].decode("latin1").strip()[:200])
                    if fr[4] == CMD["ERROR_TEXT"]:
                        raise RuntimeError("Device error: " + fr[5:-1].decode("latin1").strip())
                    if fr[4] in cmds:
                        parts.append(fr[5:-1])
                        got = now
                        self.last_reply["form"] = "F0 1C"
                        continue
                others.append(fr[:5].hex(" "))
            self.last_reply.update(bytes=total, frames=len(parts), seconds=round(now - start, 1),
                                   pending=bytes(self.parser.buf[:32]).hex(" ") if self.parser.inside else "")
            if progress and (now - tick >= 0.5 or not chunk):
                tick = now
                progress(total, len(parts), now - start)
            if parts and not self.parser.inside and now - max(last, got) > settle:
                return b"".join(parts)
            if total == 0 and now - start > first:
                raise TimeoutError(f"no response after {first:.0f} s (check cabling, baud rate, "
                                   "SysEx=on, device ID)")
            if total and now - last > idle:
                seen = f"; other frames: {', '.join(others[:5])}" if others else ""
                raise TimeoutError(f"transfer stopped: nothing received for {idle:.0f} s after "
                                   f"{total} bytes ({len(parts)} complete frames){seen}")
            if now - start > limit:
                raise TimeoutError(f"transfer too long (over {limit / 60:.0f} min, {total} bytes received)")

    def collect(self, duration):
        """Collects all frames for `duration` seconds."""
        frames = []
        end = time.time() + duration
        last = None
        while time.time() < end:
            chunk = self._read()
            if chunk or self.parser.inside:
                last = time.time()
            for fr in self.parser.feed(chunk):
                if self.verbose:
                    print("<<", describe(fr), file=sys.stderr)
                frames.append(fr)
            # end of transfer: nothing received for 3 s after at least one frame
            if frames and not self.parser.inside and time.time() - last > 3:
                break
        return frames


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def open_device(a):
    if a.midi_in or a.midi_out:
        link = MidiLink(a.midi_in, a.midi_out)
    else:
        if not a.port:
            sys.exit("--port required (e.g. /dev/cu.usbserial-XXXX) or --midi-in/--midi-out")
        link = SerialLink(a.port, a.baud, a.stopbits, a.rtscts)
    return Device(link, a.id, a.verbose)


def cmd_ports(a):
    from serial.tools import list_ports
    for p in list_ports.comports():
        print(p.device, "-", p.description)
    try:
        import mido
        print("MIDI in :", mido.get_input_names())
        print("MIDI out:", mido.get_output_names())
    except ImportError:
        pass


def cmd_get_algo(a):
    d = open_device(a)
    d.send(CMD["GET_SIGFILE"])
    cmd, payload = d.wait_for({0x08, 0x0A}, a.timeout)
    text = payload.decode("latin1").strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")   # Unix line endings for editing on a Mac
    with open(a.output, "w", newline="\n") as f:
        f.write(text + "\n")
    print(f"sigfile received (cmd 0x{cmd:02X}, {len(text)} characters) -> {a.output}")


def cmd_send_algo(a):
    d = open_device(a)
    text = open(a.file, "rb").read()
    text = bytes(b for b in text if b < 0x80)
    # the unit sends its sigfiles with CRLF: send back in the same format
    text = text.replace(b"\r\n", b"\n").replace(b"\r", b"\n").strip().replace(b"\n", b"\r\n")
    code = CMD["SIGFILE_TEXT_ERRS_ON_UNIT"] if a.errors_on_unit else CMD["SIGFILE_TEXT"]
    d.send(code, text)
    print(f"sigfile sent ({len(text)} bytes, cmd 0x{code:02X})")
    for fr in d.collect(a.listen):
        p = parse_frame(fr)
        if p and p[1] == CMD["ERROR_TEXT"]:
            print("ERROR:", p[2].decode("latin1").strip())
        else:
            print("reply:", describe(fr))


def cmd_get_screen(a):
    d = open_device(a)
    d.send(CMD["GET_SCREEN"])
    cmd, payload = d.wait_for({0x17, 0x42}, a.timeout)
    open(a.output + ".raw", "wb").write(payload)
    if cmd == 0x17:
        w, h, img = decode_screen_dump(payload)
        print(f"screen: header {w} x {h}, {len(img)} bytes")
        if write_pbm(a.output + ".pbm", w, h, img):
            print("image ->", a.output + ".pbm")
        else:
            print("inconsistent dimensions: only the raw frame was saved")
    else:
        print("format 0x42 not decoded; raw frame ->", a.output + ".raw")


def _dump(a, cmd_name, accept):
    d = open_device(a)
    d.send(CMD[cmd_name])
    frames = d.collect(a.timeout)
    with open(a.output, "wb") as f:
        for fr in frames:
            f.write(fr)
    print(f"{len(frames)} SysEx frames saved -> {a.output}")
    for fr in frames[:20]:
        print("  ", describe(fr))


def cmd_get_dbase(a):
    """Can take several minutes depending on the unit: --timeout is the idle timeout."""
    d = open_device(a)
    d.send(CMD["GET_DBASE"])

    def show(n, frames, t):
        print(f"\r{n / 1024:8.1f} KB received  {int(t) // 60}:{int(t) % 60:02d}", end="", file=sys.stderr)
    text = d.receive_dump(CMD["DBASE_TEXT"], first=max(a.timeout, 60), idle=max(a.timeout, 30), progress=show)
    print(file=sys.stderr)
    with open(a.output, "wb") as f:
        f.write(build_sysex(CMD["DBASE_TEXT"], text, d.dev_id) if a.output.lower().endswith(".syx") else text)
    print(f"module database: {len(text)} bytes -> {a.output}")


def cmd_get_setup(a):
    _dump(a, "GET_SETUP", None)


def cmd_get_user_files(a):
    _dump(a, "GET_USER_FILES", None)


def cmd_monitor(a):
    d = open_device(a)
    print("Listening (Ctrl-C to stop)...")
    try:
        while True:
            for fr in d.parser.feed(d.link.read()):
                print(time.strftime("%H:%M:%S"), describe(fr))
                p = parse_frame(fr)
                if p and p[1] in TEXT_REPLIES | {0x0D}:
                    print(p[2].decode("latin1"))
    except KeyboardInterrupt:
        pass


def cmd_send_raw(a):
    d = open_device(a)
    data = bytes.fromhex(a.hex)
    d.link.write(data)
    for fr in d.collect(a.listen):
        print(describe(fr))


def cmd_cc(a):
    d = open_device(a)
    d.link.write(bytes([0xB0 | ((a.channel - 1) & 0x0F), a.controller & 0x7F, a.value & 0x7F]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="MSIG: command line tool (DSP7000)")
    ap.add_argument("--port", help="serial port, e.g. /dev/cu.usbserial-A10K1234")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--stopbits", type=int, default=2, choices=(1, 2),
                    help="2 by default (8N2); must match the unit's setting")
    ap.add_argument("--rtscts", action="store_true", help="hardware flow control")
    ap.add_argument("--midi-in"), ap.add_argument("--midi-out")
    ap.add_argument("--id", type=int, default=1, help="SysEx device ID (default 1)")
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("-v", "--verbose", action="store_true")
    sp = ap.add_subparsers(dest="cmd", required=True)

    sp.add_parser("ports").set_defaults(fn=cmd_ports)
    p = sp.add_parser("get-algo"); p.add_argument("-o", "--output", default="algo.sig"); p.set_defaults(fn=cmd_get_algo)
    p = sp.add_parser("send-algo"); p.add_argument("file")
    p.add_argument("--errors-on-unit", action="store_true", help="use 0x08 instead of 0x0A")
    p.add_argument("--listen", type=float, default=5.0); p.set_defaults(fn=cmd_send_algo)
    p = sp.add_parser("get-screen"); p.add_argument("-o", "--output", default="screen"); p.set_defaults(fn=cmd_get_screen)
    for name, fn, default in (("get-dbase", cmd_get_dbase, "dbase.syx"),
                              ("get-setup", cmd_get_setup, "setup.syx"),
                              ("get-user-files", cmd_get_user_files, "userfiles.syx")):
        p = sp.add_parser(name); p.add_argument("-o", "--output", default=default); p.set_defaults(fn=fn)
    sp.add_parser("monitor").set_defaults(fn=cmd_monitor)
    p = sp.add_parser("send-raw"); p.add_argument("hex"); p.add_argument("--listen", type=float, default=3.0)
    p.set_defaults(fn=cmd_send_raw)
    p = sp.add_parser("cc"); p.add_argument("channel", type=int); p.add_argument("controller", type=int)
    p.add_argument("value", type=int); p.set_defaults(fn=cmd_cc)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
