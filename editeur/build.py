"""Builds the editor (single HTML file) from the sources.

  msig_editeur.html         : module database embedded (personal use, works offline)
  msig_editeur_public.html  : without the module database, which belongs to the manufacturer; it is
                              read from the user's DSP by the gateway (distributed version)
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
    print(name, len(out), "bytes")
