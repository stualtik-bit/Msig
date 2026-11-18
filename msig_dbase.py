"""Conversion de la base de modules du DSP (reponse SysEx 0x0C a Get Dbase, texte entre
accolades) en dictionnaire pour l'editeur :
    {TYPE: {"group": ..., "fields": [...], "outputs": [...]}}
Utilise par msig_serveur.py (lecture directe sur le DSP) et editeur/dbase2json.py."""
import re

ED = {"ED_SIGNAL", "ED_CONTROL", "ED_USEROBJ", "ED_STRING", "ED_INTEGER", "ED_REAL"}


def _records(block):
    for body in re.findall(r"\{([^{}]*)\}", block):
        rec = {}
        for line in body.split("\n"):
            if ":" in line:
                k, v = line.strip().split(":", 1)
                rec[k] = v
        if rec:
            yield rec


def _clean(lst):
    """Supprime les groupes de repetition vides."""
    out = []
    for x in lst:
        if "repeat" in x:
            x["items"] = _clean(x["items"])
            if x["items"]:
                out.append(x)
        else:
            out.append(x)
    return out


def extract_text(raw):
    """Texte de la base a partir d'un fichier ou d'une reponse :
    - une ou plusieurs trames SysEx (fichier .syx), dont on concatene les donnees ;
    - le texte seul (reponse deja decodee, fichier texte .sbf enregistre par l'ancien
      logiciel Windows, .txt)."""
    raw = bytes(raw)
    if b"\xF0" in raw[:16]:
        parts, i = [], raw.find(b"\xF0")
        while i != -1:
            j = raw.find(b"\xF7", i)
            if j == -1:
                break
            parts.append(raw[i + 5:j])
            i = raw.find(b"\xF0", j)
        raw = b"".join(parts)
    return raw.replace(b"\x00", b"")


def convert(raw):
    """raw : trame(s) SysEx (F0 ... F7) ou texte seul (bytes)."""
    text = extract_text(raw).decode("latin1").replace("\r", "")
    mods = {}
    for block in re.findall(r"TYPE:OPERATOR\n.*?TYPE:OPERATOREND", text, re.S):
        # le bloc commence au milieu d'un enregistrement : on le reconstruit
        recs = list(_records("{" + block + "}"))
        head = recs[0] if recs else {}
        if "OPERATOR_NAME" not in head:
            continue
        name = head["OPERATOR_NAME"].upper()
        fields, outputs = [], []
        stack = [(fields, outputs)]
        for r in recs[1:]:
            t = r.get("TYPE")
            if t == "MULTIPLE":
                rep = r.get("ACTION_SPECIFIER", "1")
                f_items, o_items = [], []
                stack[-1][0].append({"repeat": rep, "items": f_items})
                stack[-1][1].append({"repeat": rep, "items": o_items})
                stack.append((f_items, o_items))
            elif t == "MULTIPLEEND":
                stack.pop()
            elif t in ED:
                if r.get("NAME") == "opstart_name":
                    continue
                cls = r.get("CONNECT_CLASS", "")
                kind = {"ED_SIGNAL": "mod_in" if cls == "MOD" else "audio_in", "ED_CONTROL": "ctl_in",
                        "ED_USEROBJ": "obj_in"}.get(t, "spec")
                f = {"name": r["NAME"], "type": kind, "ed": t[3:].lower()}
                for k, kk in (("DESCRIPTION", "desc"), ("MINIMUM", "min"), ("MAXIMUM", "max"), ("DEFAULT", "def")):
                    if k in r and r[k] != r["NAME"]:
                        f[kk] = r[k]
                stack[-1][0].append(f)
            elif t in ("SIGNAL", "CONTROL", "USEROBJ") and "CONNECT_TAG" in r:
                kind = {"SIGNAL": "mod_out" if r.get("CONNECT_CLASS") == "MOD" else "audio_out",
                        "CONTROL": "ctl_out", "USEROBJ": "obj_out"}[t]
                stack[-1][1].append({"name": r["CONNECT_TAG"], "type": kind})
        mods[name] = {"group": head.get("OPERATOR_CLASS", "").lower(),
                      "fields": _clean(fields), "outputs": _clean(outputs)}
    return mods
