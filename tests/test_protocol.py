"""Tests hors materiel : encodage/decodage et dialogue avec un DSP simule sur pseudo-terminal."""
import os, sys, threading, time, tty
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import msig_mac as v


def test_frame():
    assert v.build_sysex(0x0B) == bytes.fromhex("F0 1C 70 01 0B F7")
    assert v.parse_frame(bytes.fromhex("F0 1C 70 01 0A 41 42 F7")) == (1, 0x0A, b"AB")


def test_nibbleize_roundtrip():
    data = bytes(range(256))
    n = v.nibbleize(data)
    assert all(b < 16 for b in n)
    raw = v.denibbleize(n)
    assert int.from_bytes(raw[:4], "big") == 256 and raw[4:-1] == data
    assert (sum(raw[:-1]) + raw[-1]) & 0xFF == 0


def test_parser_split_chunks():
    p = v.SysexParser()
    f = v.build_sysex(0x0A, b"hello")
    out = p.feed(b"\x90\x40" + f[:3]) + p.feed(b"\xF8" + f[3:])
    assert out == [f]


def fake_dsp(fd, stop):
    """Repond a GET_SIGFILE par un sigfile texte et a GET_SCREEN par une image 16x2."""
    parser = v.SysexParser()
    while not stop.is_set():
        try:
            chunk = os.read(fd, 1024)
        except OSError:
            return
        for fr in parser.feed(chunk):
            _, cmd, _ = v.parse_frame(fr)
            if cmd == 0x0B:
                os.write(fd, v.build_sysex(0x0A, b"  ; test\r\nIN_A in\r\nOUT_A out in  "))
            elif cmd == 0x18:
                head = (16).to_bytes(4, "big") + (2).to_bytes(4, "big") + (4).to_bytes(4, "big")
                img = b"\xAA\x55\xFF\x00"
                payload = b"".join(v._nib(b) for b in head + img)
                os.write(fd, v.build_sysex(0x17, payload))


def test_dialog_over_pty(tmp_path):
    master, slave = os.openpty()
    tty.setraw(master); tty.setraw(slave)
    name = os.ttyname(slave)
    stop = threading.Event()
    t = threading.Thread(target=fake_dsp, args=(master, stop), daemon=True); t.start()
    out = tmp_path / "a.sig"
    v.main(["--port", name, "--timeout", "3", "get-algo", "-o", str(out)])
    assert "IN_A in" in out.read_text()
    v.main(["--port", name, "--timeout", "3", "get-screen", "-o", str(tmp_path / "s")])
    assert (tmp_path / "s.pbm").read_bytes().endswith(b"\xAA\x55\xFF\x00")
    stop.set()


class SlowLink:
    """Liaison simulee : livre des morceaux avec des pauses (appareil lent, vitesse SysEx reduite)."""

    def __init__(self, script):
        self.script = list(script)  # (pause en s, octets)
        self.t = None

    def read(self):
        if self.t is None:
            self.t = time.time()
        if self.script and time.time() - self.t >= self.script[0][0]:
            pause, data = self.script.pop(0)
            self.t = time.time()
            return data
        time.sleep(0.01)
        return b""


def test_receive_dump_slow_multi_frames():
    text = b"{\r\n" + b"x" * 5000 + b"\r\n}\r\n"
    f1, f2 = v.build_sysex(0x0C, text[:3000]), v.build_sysex(0x0C, text[3000:])
    stream = f1 + f2
    # 3 morceaux separes de pauses de 1,5 s, delai d inactivite de 2 s : le transfert doit aboutir
    link = SlowLink([(0.3, stream[:2000]), (1.5, stream[2000:4500]), (1.5, stream[4500:])])
    d = v.Device(link)
    seen = []
    out = d.receive_dump(0x0C, first=2, idle=2, progress=lambda n, f, t: seen.append(n))
    assert out == text and seen[-1] == len(stream)


def test_receive_dump_stall_and_silence():
    import pytest
    f = v.build_sysex(0x0C, b"abc" * 100)
    d = v.Device(SlowLink([(0.1, f[:100])]))
    with pytest.raises(TimeoutError, match="transfer stopped"):
        d.receive_dump(0x0C, first=1, idle=1)
    d = v.Device(SlowLink([]))
    with pytest.raises(TimeoutError, match="no response"):
        d.receive_dump(0x0C, first=0.5, idle=1)


def test_dbase_file_formats():
    import msig_dbase as db
    text = (b"{\r\n   {\r\n   TYPE:OPERATOR\r\n   NAME:opstart\r\n   OPERATOR_NAME:gain\r\n   OPERATOR_CLASS:MATH\r\n   }\r\n"
            b"   {\r\n   TYPE:ED_SIGNAL\r\n   NAME:in\r\n   }\r\n   {\r\n   TYPE:SIGNAL\r\n   NAME:out\r\n   CONNECT_TAG:out\r\n   }\r\n"
            b"   {\r\n   TYPE:OPERATOREND\r\n   NAME:opend\r\n   }\r\n}\r\n\x00")
    ref = db.convert(text)
    assert list(ref) == ["GAIN"]
    assert db.convert(v.build_sysex(0x0C, text.replace(b"\x00", b""))) == ref       # .syx, une trame
    assert db.convert(v.build_sysex(0x0C, text[:40]) + v.build_sysex(0x0C, text[40:-1])) == ref  # plusieurs
    assert db.convert(b"garbage") == {}


def test_reply_with_other_model_byte_and_slow_unit():
    # appareil qui repond avec un autre octet de modele, lentement, en deux trames
    text = b"  ; test\r\nIN_A in\r\nOUT_A out in  "
    f1 = bytes([0xF0, 0x1C, 0x5E, 0x01, 0x0A]) + text[:12] + b"\xF7"
    f2 = bytes([0xF0, 0x1C, 0x5E, 0x01, 0x0A]) + text[12:] + b"\xF7"
    assert v.parse_frame(f1) == (1, 0x0A, text[:12])
    d = v.Device(SlowLink([(0.5, f1[:8]), (1.5, f1[8:] + f2)]))
    assert d.receive_dump({0x08, 0x0A}, first=2, idle=2) == text
    assert d.last_reply["frames"] == 2 and d.last_reply["heads"][0].startswith("f0 1c 5e 01 0a")


def misframe(data, rx_stop):
    """Ce que lit un recepteur a `rx_stop` bits de stop quand l'appareil emet en 8N1, octets
    colles (simulation bit par bit). Avec 2 bits de stop, le bit de start suivant est pris pour le
    2e bit de stop et la lecture se recale au milieu d'un octet : c'est ce qu'a recu un testeur
    dont l'appareil etait regle sur 1 bit de stop (en-tetes « f0 04 05 0a », « f0 04 05 17 »)."""
    bits = [1, 1]
    for b in data:
        bits += [0] + [(b >> i) & 1 for i in range(8)] + [1]
    bits += [1] * 20
    out, i = bytearray(), 2
    while True:
        while i < len(bits) and not (bits[i - 1] == 1 and bits[i] == 0):   # front de start
            i += 1
        if i + 9 >= len(bits):
            return bytes(out)
        out.append(sum(bits[i + 1 + k] << k for k in range(8)))
        i += 9 + rx_stop


SIG_REPLY = v.build_sysex(0x0A, b"\r\nHEADM adc 2 4 diff2-out diff3-out\r\n" * 20)
_head = (240).to_bytes(4, "big") + (64).to_bytes(4, "big") + (1920).to_bytes(4, "big")
SCREEN_REPLY = v.build_sysex(0x17, b"".join(v._nib(b) for b in _head + b"\xff" * 40 + bytes(200)))


def test_misframe_model():
    assert misframe(SIG_REPLY, 1) == SIG_REPLY                      # memes reglages : intact
    assert misframe(SIG_REPLY, 2).startswith(bytes.fromhex("f0 04 05 0a"))
    assert misframe(SCREEN_REPLY, 2).startswith(bytes.fromhex("f0 04 05 17 00 00 00 08 00 00 00 04"))


def test_garbled_reply_is_detected_not_accepted():
    import pytest
    for raw, cmds in ((misframe(SIG_REPLY, 2), {0x08, 0x0A}), (misframe(SCREEN_REPLY, 2), {0x17})):
        d = v.Device(SlowLink([(0.1, raw)]))
        with pytest.raises(TimeoutError):
            d.receive_dump(cmds, first=1, idle=1, settle=0.3)
        assert v.looks_garbled(d.raw)
    # une vraie reponse DSP7000 n'est jamais prise pour une reponse illisible
    assert not v.looks_garbled(v.build_sysex(0x0A, b"  ; test\r\nIN_A in\r\n" * 50))
    head = (240).to_bytes(4, "big") + (64).to_bytes(4, "big") + (1920).to_bytes(4, "big")
    assert not v.looks_garbled(v.build_sysex(0x17, b"".join(v._nib(b) for b in head + bytes(range(256)) * 7)))


def test_reply_returns_soon_after_frame():
    text = b"\r\n  ; test\r\nIN_A in\r\n"
    unsolicited = v.build_sysex(0x01, bytes(8)) + v.build_sysex(0x3C, b"Program 1")
    d = v.Device(SlowLink([(0.2, unsolicited), (0.5, v.build_sysex(0x0A, text))]))
    t = time.time()
    assert d.receive_dump({0x08, 0x0A}, first=2, idle=2, settle=0.3) == text
    assert time.time() - t < 2.5 and d.last_reply["form"] == "F0 1C"
    assert any("Program 1" in n for n in d.last_reply["notes"]) and d.raw.startswith(unsolicited)


def test_serial_link_keeps_one_setting():
    # 1.0.9 : meme reglage a l'envoi et a la reception, jamais modifie port ouvert
    link = v.SerialLink("loop://", 115200)
    assert link.ser.stopbits == 2 and "2 stop bits" in link.describe()
    seen = []
    real_write = link.ser.write
    link.ser.write = lambda data: (seen.append(link.ser.stopbits), real_write(data))[1]
    link.write(b"\xF0\x1C\x70\x01\x0B\xF7")
    assert seen == [2] and link.ser.stopbits == 2
    assert link.read() == b"\xF0\x1C\x70\x01\x0B\xF7"
    one = v.SerialLink("loop://", 115200, 1)
    one.write(b"x")
    assert one.ser.stopbits == 1 and one.read() == b"x" and "1 stop bit," not in one.describe()


def test_bridge_remembers_speed_and_stop_bits(tmp_path, monkeypatch):
    import msig_serveur as gw
    monkeypatch.setattr(gw, "data_dir", lambda: str(tmp_path))
    b = gw.Bridge(115200, 1)
    assert (b.baud, b.stopbits) == (115200, 2)
    b.connect("loop://", 57600, 1)
    assert b.dev.link.ser.stopbits == 1 and b.status()["stopbits"] == 1
    b2 = gw.Bridge(115200, 1)
    assert (b2.baud, b2.stopbits) == (57600, 1)


def test_editor_argument_lists_follow_counts():
    import shutil, subprocess, pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    js = os.path.join(os.path.dirname(__file__), "sigfile_args.test.js")
    r = subprocess.run([node, js], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
