"""Converts the DSP module database (file written by `msig_mac.py get-dbase`)
to JSON for the editor: editeur/modules_dsp.json.
Usage: python3 dbase2json.py ../dsp/dbase.syx"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from msig_dbase import convert  # noqa: E402

src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "dsp", "dbase.syx")
mods = convert(open(src, "rb").read())
out = os.path.join(HERE, "modules_dsp.json")
json.dump(mods, open(out, "w"), indent=1)
print(len(mods), "modules ->", out)
