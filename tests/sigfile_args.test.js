// node tests/sigfile_args.test.js : libelles des arguments quand un nombre (sorties...) change.
// Definitions minimales ecrites a la main (aucune base de modules d'un appareil).
const assert = require("assert"), path = require("path");
const S = require(path.join(__dirname, "..", "editeur", "sigfile.js"));
const HEADM = { fields: [
  { name: "ninputs", type: "spec", ed: "integer", def: "2" },
  { name: "noutputs", type: "spec", ed: "integer", def: "2" },
  { repeat: "@noutputs", items: [{ name: "out~n", type: "audio_in", ed: "signal" }] },
  { name: "obj_desription", type: "spec", ed: "string", def: "headm" },
], outputs: [] };
const MIXER = { fields: [
  { name: "ninputs", type: "spec", ed: "integer", def: "1" },
  { repeat: "@ninputs", items: [{ name: "in~n", type: "audio_in", ed: "signal" }] },
  { repeat: "@ninputs", items: [{ name: "gain~n", type: "ctl_in", ed: "control", def: "-3" }] },
], outputs: [] };
const labels = (def, args) => (S.fieldLabels(def, args) || []).map((l, k) => l.label + "=" + args[k]).join(" ");

let h = ["2", "4", "a", "b", "c", "d", '"Name"'];
assert.strictEqual(labels(HEADM, h), 'ninputs=2 noutputs=4 out1=a out2=b out3=c out4=d obj_desription="Name"');
h = S.withArg(HEADM, h, 1, "2", "adc");
assert.strictEqual(labels(HEADM, h), 'ninputs=2 noutputs=2 out1=a out2=b obj_desription="Name"');
h = S.withArg(HEADM, h, 1, "3", "adc");
assert.strictEqual(labels(HEADM, h), 'ninputs=2 noutputs=3 out1=a out2=b out3=adc-null obj_desription="Name"');

let m = S.defaultArgs(MIXER, "adc");
m = S.withArg(MIXER, m, 1, "osc", "adc");
m = S.withArg(MIXER, m, 0, "3", "adc");
assert.strictEqual(labels(MIXER, m), "ninputs=3 in1=osc in2=adc-null in3=adc-null gain1=-3 gain2=-3 gain3=-3");
// un argument ordinaire ne touche pas a la liste
assert.deepStrictEqual(S.withArg(MIXER, m, 4, "-6", "adc"), ["3", "osc", "adc-null", "adc-null", "-6", "-3", "-3"]);
// avant la 1.0.9 : simple affectation, plus aucun libelle (affiches arg1, arg2...)
const old = S.defaultArgs(MIXER, "adc"); old[0] = "3";
assert.strictEqual(S.fieldLabels(MIXER, old), null);
console.log("sigfile_args: ok");
