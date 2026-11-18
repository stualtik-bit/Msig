#!/usr/bin/env python3
"""
msig_mac.py - communication (macOS et Linux) avec un DSP7000 (et appareils de la meme famille)
via RS-232 (adaptateur USB-serie)
ou via une interface MIDI.

Protocole reconstitue par analyse statique (interoperabilite).

Trame SysEx :  F0 1C 70 <id> <cmd> [donnees] F7
  1C = identifiant fabricant, 70 = modele (famille DSP4000/7000),
  id = "device ID" (defaut 1, doit correspondre a SETUP/MIDI de l'appareil).

Sur RS-232 les octets MIDI sont envoyes tels quels (aucun encapsulage).
"""
import argparse
import sys
import time

MFR_ID = 0x1C
MODEL_DSP = 0x70

# Codes de commande observes
CMD = {
    "SIGFILE_TEXT_ERRS_ON_UNIT": 0x08,  # envoi/reception sigfile texte (variante "erreurs a l'ecran")
    "SIGFILE_TEXT": 0x0A,               # envoi/reception sigfile texte
    "GET_SIGFILE": 0x0B,                # menu MIDI > Get / Update params
    "DBASE_TEXT": 0x0C,                 # reponse a GET_DBASE (DSP7000 : une trame de 264 ko)
    "ERROR_TEXT": 0x0D,                 # message d'erreur texte renvoye par l'appareil
    "GET_DBASE": 0x0E,                  # menu MIDI > Get Dbase
    "SEND_USER_FILES": 0x0F,            # (non implemente)
    "GET_USER_FILES": 0x10,
    "SEND_SETUP": 0x11,                 # (non implemente)
    "GET_SETUP": 0x12,
    "BIN_CARD": 0x13,                   # fichier binaire recu -> card.bin
    "BIN_PROG": 0x15,                   # fichier binaire recu -> prog.bin / envoi d'algorithme compile
    "BIN_SETUP": 0x16,                  # fichier binaire recu -> setup.bin
    "SCREEN_DUMP": 0x17,                # reponse a GET_SCREEN
    "GET_SCREEN": 0x18,
    "PROGNUMS_DUMP": 0x30,
    "GET_PRESET_ALT": 0x35,
    "PRESET_ALT_TEXT": 0x36,
    "BIN_DATA": 0x39,                   # fichier binaire recu -> data.bin
    "TEXT_NIBBLES": 0x40,
    "SCREEN_DUMP_ALT": 0x42,
}
CMD_NAME = {v: k for k, v in CMD.items()}
TEXT_REPLIES = {0x08, 0x0A, 0x19, 0x22, 0x2C, 0x2D, 0x2E, 0x32, 0x34, 0x36, 0x3C}
BINARY_FILE_REPLIES = {0x13: "card.bin", 0x15: "prog.bin", 0x16: "setup.bin", 0x39: "data.bin"}


# --------------------------------------------------------------------------
# Encodage
# --------------------------------------------------------------------------
def build_sysex(cmd, data=b"", dev_id=1):
    data = bytes(data)
    if any(b & 0x80 for b in data):
        raise ValueError("les donnees SysEx doivent etre sur 7 bits (utiliser nibbleize)")
    return bytes([0xF0, MFR_ID, MODEL_DSP, dev_id & 0x7F, cmd & 0x7F]) + data + b"\xF7"


def _nib(b):
    return bytes([(b >> 4) & 0x0F, b & 0x0F])


def nibbleize(data, with_length=True):
    """Encodage en nibbles des donnees binaires.
    [longueur 32 bits big-endian en nibbles] + octets en nibbles (poids fort d'abord)
    + somme de controle = -(somme des octets, longueur incluse) & 0xFF, en nibbles."""
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
    """Paires (poids fort, poids faible) -> octets."""
    n = len(nibbles) // 2
    return bytes(((nibbles[2 * i] & 0x0F) << 4) | (nibbles[2 * i + 1] & 0x0F) for i in range(n))


# --------------------------------------------------------------------------
# Decodage du flux entrant
# --------------------------------------------------------------------------
class SysexParser:
    """Accumule un flux d'octets MIDI et extrait les trames F0..F7."""

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
                if b >= 0xF8:          # messages temps reel : ignores dans un SysEx
                    continue
                self.buf.append(b)
                if b == 0xF7:
                    msgs.append(bytes(self.buf))
                    self.inside = False
        return msgs


def parse_frame(frame):
    """Retourne (dev_id, cmd, payload) ou None si la trame n'est pas une trame DSP."""
    if len(frame) < 6 or frame[0] != 0xF0 or frame[-1] != 0xF7:
        return None
    # octet de modele non verifie : on envoie 70 (comme le logiciel d'origine, pour tous les
    # appareils) mais certains appareils de la famille repondent avec leur propre valeur
    if frame[1] != MFR_ID:
        return None
    return frame[3], frame[4], frame[5:-1]


def describe(frame):
    p = parse_frame(frame)
    if not p:
        return "trame non DSP: " + frame[:16].hex(" ")
    dev, cmd, payload = p
    name = CMD_NAME.get(cmd, "INCONNU")
    return f"id={dev} cmd=0x{cmd:02X} ({name}) {len(payload)} octets"


def decode_screen_dump(payload):
    """Reponse 0x17. Inference : 12 octets d'en-tete (3 entiers 32 bits BE, en nibbles),
    puis l'image en nibbles. On suppose (largeur, hauteur, taille) - NON VERIFIE."""
    head = denibbleize(payload[:24])
    a, b, size = (int.from_bytes(head[i:i + 4], "big") for i in (0, 4, 8))
    img = denibbleize(payload[24:24 + 2 * size])
    return a, b, img


def looks_garbled(raw):
    """Reponse illisible : le DSP7000 n'envoie que des octets MIDI (donnees < 0x80 entre F0 et
    F7). Des octets >= 0x80 en nombre indiquent des reglages serie differents entre l'appareil
    et MSIG (bits de stop surtout : H8000 regle sur 1 bit de stop, MSIG sur 2)."""
    return sum(1 for b in bytes(raw) if b >= 0x80 and b not in (0xF0, 0xF7)) >= 8


def write_pbm(path, width, height, img):
    """Ecrit un PBM 1 bit/pixel si les dimensions sont coherentes avec la taille recue."""
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
    """Port serie 8 bits sans parite, 2 bits de stop par defaut (8N2), meme reglage dans les deux
    sens. Les bits de stop doivent correspondre au reglage de l'appareil : un H8000 regle sur
    1 bit de stop repond en 8N1, octets colles, et ses reponses arrivent illisibles en 8N2.
    Le reglage n'est jamais change port ouvert : la 1.0.8 le faisait a chaque envoi et
    perdait des demandes (l'adaptateur USB emettait encore)."""

    def __init__(self, port, baud=115200, stopbits=2, rtscts=False):
        import serial  # pyserial
        kw = {"exclusive": True} if port.startswith("/dev/") else {}  # un seul programme a la fois
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
    """Transport MIDI optionnel (pip install mido python-rtmidi)."""

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
        """Attend une trame dont la commande est dans `cmds`. Les erreurs 0x0D sont levees."""
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
        """Lecture du lien ; tous les octets recus sont aussi gardes dans self.raw (diagnostic)."""
        chunk = self.link.read()
        if chunk and len(self.raw) < 8_000_000:
            self.raw += chunk
        return chunk

    def receive_dump(self, cmd, first=60.0, idle=30.0, limit=1800.0, progress=None,
                     settle=2.0):
        """Recoit une reponse volumineuse (base des modules) sans duree totale fixe.

        La duree depend de l'appareil, de la taille de sa base et du reglage de vitesse
        SysEx de l'appareil : de 25 s (DSP7000, 264 ko) a plusieurs minutes. On attend donc
        tant que des octets arrivent ; echec si rien n'arrive pendant `first` secondes apres
        la demande, ou pendant `idle` secondes en cours de transfert, ou au-dela de `limit`.
        Les trames du fabricant portant `cmd` (une commande ou un ensemble) sont concatenees
        (quel que soit l'octet de modele) ; on rend la main `settle` secondes apres la
        derniere trame retenue.

        `progress(octets, trames, secondes)` est appele regulierement. Retourne les donnees
        (bytes) sans les en-tetes SysEx ; le resume de l'echange (debut de chaque trame,
        forme d'en-tete, textes de l'appareil, duree) reste dans self.last_reply."""
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
        """Recupere toutes les trames pendant `duration` secondes."""
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
            # fin de transfert : plus rien recu depuis 3 s apres au moins une trame
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
            sys.exit("--port requis (ex. /dev/cu.usbserial-XXXX) ou --midi-in/--midi-out")
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
    text = text.replace("\r\n", "\n").replace("\r", "\n")   # fin de ligne Unix pour l'edition sur Mac
    with open(a.output, "w", newline="\n") as f:
        f.write(text + "\n")
    print(f"sigfile recu (cmd 0x{cmd:02X}, {len(text)} caracteres) -> {a.output}")


def cmd_send_algo(a):
    d = open_device(a)
    text = open(a.file, "rb").read()
    text = bytes(b for b in text if b < 0x80)
    # l'appareil envoie ses sigfiles en CRLF : on renvoie dans le meme format
    text = text.replace(b"\r\n", b"\n").replace(b"\r", b"\n").strip().replace(b"\n", b"\r\n")
    code = CMD["SIGFILE_TEXT_ERRS_ON_UNIT"] if a.errors_on_unit else CMD["SIGFILE_TEXT"]
    d.send(code, text)
    print(f"sigfile envoye ({len(text)} octets, cmd 0x{code:02X})")
    for fr in d.collect(a.listen):
        p = parse_frame(fr)
        if p and p[1] == CMD["ERROR_TEXT"]:
            print("ERREUR:", p[2].decode("latin1").strip())
        else:
            print("reponse:", describe(fr))


def cmd_get_screen(a):
    d = open_device(a)
    d.send(CMD["GET_SCREEN"])
    cmd, payload = d.wait_for({0x17, 0x42}, a.timeout)
    open(a.output + ".raw", "wb").write(payload)
    if cmd == 0x17:
        w, h, img = decode_screen_dump(payload)
        print(f"ecran: en-tete {w} x {h}, {len(img)} octets")
        if write_pbm(a.output + ".pbm", w, h, img):
            print("image ->", a.output + ".pbm")
        else:
            print("dimensions incoherentes : seule la trame brute a ete sauvee")
    else:
        print("format 0x42 non decode ; trame brute ->", a.output + ".raw")


def _dump(a, cmd_name, accept):
    d = open_device(a)
    d.send(CMD[cmd_name])
    frames = d.collect(a.timeout)
    with open(a.output, "wb") as f:
        for fr in frames:
            f.write(fr)
    print(f"{len(frames)} trames SysEx enregistrees -> {a.output}")
    for fr in frames[:20]:
        print("  ", describe(fr))


def cmd_get_dbase(a):
    """Peut durer plusieurs minutes selon l'appareil : --timeout est le delai d'inactivite."""
    d = open_device(a)
    d.send(CMD["GET_DBASE"])

    def show(n, frames, t):
        print(f"\r{n / 1024:8.1f} ko recus  {int(t) // 60}:{int(t) % 60:02d}", end="", file=sys.stderr)
    text = d.receive_dump(CMD["DBASE_TEXT"], first=max(a.timeout, 60), idle=max(a.timeout, 30), progress=show)
    print(file=sys.stderr)
    with open(a.output, "wb") as f:
        f.write(build_sysex(CMD["DBASE_TEXT"], text, d.dev_id) if a.output.lower().endswith(".syx") else text)
    print(f"base des modules : {len(text)} octets -> {a.output}")


def cmd_get_setup(a):
    _dump(a, "GET_SETUP", None)


def cmd_get_user_files(a):
    _dump(a, "GET_USER_FILES", None)


def cmd_monitor(a):
    d = open_device(a)
    print("Ecoute (Ctrl-C pour arreter)...")
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
    ap = argparse.ArgumentParser(description="MSIG : outil en ligne de commande (DSP7000)")
    ap.add_argument("--port", help="port serie, ex. /dev/cu.usbserial-A10K1234")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--stopbits", type=int, default=2, choices=(1, 2),
                    help="2 par defaut (8N2) ; doit correspondre au reglage de l'appareil")
    ap.add_argument("--rtscts", action="store_true", help="controle de flux materiel")
    ap.add_argument("--midi-in"), ap.add_argument("--midi-out")
    ap.add_argument("--id", type=int, default=1, help="device ID SysEx (defaut 1)")
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("-v", "--verbose", action="store_true")
    sp = ap.add_subparsers(dest="cmd", required=True)

    sp.add_parser("ports").set_defaults(fn=cmd_ports)
    p = sp.add_parser("get-algo"); p.add_argument("-o", "--output", default="algo.sig"); p.set_defaults(fn=cmd_get_algo)
    p = sp.add_parser("send-algo"); p.add_argument("file")
    p.add_argument("--errors-on-unit", action="store_true", help="utilise 0x08 au lieu de 0x0A")
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
