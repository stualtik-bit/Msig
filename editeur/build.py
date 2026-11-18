"""Assemble l'editeur (fichier HTML unique) a partir des sources.

  msig_editeur.html         : base des modules integree (usage personnel, fonctionne hors ligne)
  msig_editeur_public.html  : sans la base des modules, qui appartient au fabricant ; elle est lue
                              sur le DSP de l'utilisateur par la passerelle (version distribuee)
"""
import json, os
d = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(d, "editeur.src.html"), encoding="utf-8").read()
js = open(os.path.join(d, "sigfile.js"), encoding="utf-8").read()
rnd = open(os.path.join(d, "random.js"), encoding="utf-8").read()
base = src.replace("/*SIGFILE*/", js).replace("/*RANDOM*/", rnd)
builds = {"msig_editeur_public.html": "null"}
mp = os.path.join(d, "modules_dsp.json")
if os.path.exists(mp):
    builds["msig_editeur.html"] = json.dumps(json.load(open(mp)), separators=(",", ":"))
for name, defs in builds.items():
    out = base.replace("/*DEFS*/", defs)
    open(os.path.join(d, name), "w", encoding="utf-8").write(out)
    print(name, len(out), "octets")
