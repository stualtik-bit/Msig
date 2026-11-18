// random.js - generator of random but usable patches (MSIG's Random button)
// Rules: stereo input -> chain of chosen modules (100 % wet) -> limiter -> outputs; each module only reads
// modules placed before it, except for one optional, bounded feedback loop (gain <= 0.6,
// gainless blocks + HIGHCUT only). Settings drawn from safe ranges; knobs and a menu page
// to tweak the patch from the DSP. validate() checks the result before offering it.
(function (root) {
  "use strict";

  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function rng(seed) {
    const r = mulberry32(seed);
    return {
      lin: (a, b) => a + (b - a) * r(),
      log: (a, b) => Math.exp(Math.log(a) + (Math.log(b) - Math.log(a)) * r()),
      int: (a, b) => Math.floor(a + (b - a + 1) * r()),
      pick: arr => arr[Math.floor(r() * arr.length)],
      chance: p => r() < p,
      sign: () => (r() < 0.5 ? -1 : 1),
    };
  }
  const num = v => {
    if (typeof v === "string") return v;
    const x = Math.round(v * 10000) / 10000;
    return String(Object.is(x, -0) ? 0 : x);
  };
  const plain = s => String(s == null ? "" : s).replace(/^=/, "");
  const isNum = s => /^-?(\d+\.?\d*|\.\d+)$/.test(String(s));

  // Module arguments: value from p(label, n, vals) if defined, otherwise the database default.
  function buildArgs(def, head, p) {
    const args = [], vals = {};
    (function walk(items, n) {
      for (const it of items) {
        if (it.repeat !== undefined) {
          const c = it.repeat[0] === "@" ? +vals[it.repeat.slice(1)] : +it.repeat;
          for (let j = 1; j <= (c || 0); j++) walk(it.items, j);
          continue;
        }
        const label = n ? it.name.replace(/~n/g, n) : it.name;
        let v = p(label, n, vals, it);
        if (v === undefined) {
          if (it.type === "audio_in" || it.type === "mod_in") v = head + "-null";
          else if (it.type === "obj_in") v = head + "-nullobj";
          else if (it.ed === "string") v = '"' + plain(it.def).replace(/~n/g, n) + '"';
          else {
            v = plain(it.def);
            if (!isNum(v)) v = isNum(plain(it.min)) ? plain(it.min) : "0";
          }
        } else v = num(v);
        vals[label] = v;
        args.push(v);
      }
    })(def.fields, 0);
    return args;
  }

  // ---------------------------------------------------------------- catalogue
  // io: mono (1 input -> 1 output), m2s (mono -> stereo), stereo (2 -> 2).
  // params(R): values; an "x~n" key can be a function (n, vals).
  // knobs: parameters a knob can control; jitter: keys offset on the 2nd stereo instance.
  // loop: gainless block, allowed in the feedback loop.
  const K = (key, label, fmt, min, max) => ({ key, label, fmt, min, max });
  const CATALOG = [
    { type: "FILTER", io: "mono", w: 3, in: ["in"], out: "out",
      params: R => ({ freq: R.log(150, 9000), qfactor: R.log(0.7, R.chance(0.3) ? 8 : 3), type: R.pick([0, 0, 1, 2]) }),
      knobs: [K("freq", "cutoff", "%5.0f Hz", 40, 16000)], jitter: ["freq"] },
    { type: "TONE", io: "mono", w: 2, in: ["in"], out: "out", loop: true,
      params: R => ({ low_freq: R.log(60, 400), low_level: R.lin(-10, 8), high_freq: R.log(1500, 9000), high_level: R.lin(-12, 6) }),
      loopParams: R => ({ low_level: R.lin(-8, 0), high_level: R.lin(-10, 0) }),
      knobs: [K("high_level", "treble", "%5.1f dB", -18, 18), K("low_level", "bass", "%5.1f dB", -18, 18)] },
    { type: "EQ", io: "mono", w: 2, in: ["in"], out: "out",
      params: R => ({ freq: R.log(150, 6000), qfactor: R.log(0.7, 4), boost: R.sign() * R.lin(4, 12), type: 0 }),
      knobs: [K("boost", "eq boost", "%5.1f dB", -18, 18)], jitter: ["freq"] },
    { type: "MODFILTER", io: "mono", w: 3, in: ["in"], out: R => R.pick(["low", "band", "low", "high"]), lfo: ["fmod"],
      params: R => { const f = R.log(300, 3000); return { freq: f, freqmodamt: f * R.lin(0.3, 0.8), q: R.log(1, 6), qmodamt: 0 }; },
      knobs: [K("freq", "sweep freq", "%5.0f Hz", 50, 10000)], jitter: ["freq"] },
    { type: "PHASESHIFT", io: "mono", w: 2, in: ["in"], out: "out", lfo: ["mod"],
      params: R => ({ poles: R.pick([4, 6, 8, 12]), depth: R.lin(0.5, 1) }),
      knobs: [K("depth", "phase depth", "%4.2f", 0, 1)] },
    { type: "DISTORT", io: "mono", w: 2, in: ["in"], out: "out", trim: vals => -0.6 * +vals.pregain,
      params: R => ({ morphon: 0, curve1: R.lin(2, 18), curve2: 0, pregain: R.lin(3, 24), bias: R.chance(0.3) ? R.lin(-0.05, 0.05) : 0, expansion: 0 }),
      knobs: [K("curve1", "drive", "%4.1f", 0, 18)] },
    { type: "QUANTIZE", io: "mono", w: 1, in: ["in"], out: "out",
      params: R => ({ bits: R.int(3, 10) }), knobs: [K("bits", "bits", "%2.0f", 2, 24)] },
    { type: "AMPMOD", io: "mono", w: 1, in: ["in"], out: "out", lfo: ["mod"],
      params: R => { const o = R.lin(0.55, 0.75); return { modamt: o * R.lin(0.3, 0.6), offset: o }; },
      knobs: [K("modamt", "tremolo", "%4.2f", 0, 0.5)] },
    { type: "DELAY", io: "mono", w: 3, in: ["in"], out: "out", loop: true, mem: v => +v.maxdelay,
      params: R => { const m = R.int(80, 1500); return { maxdelay: m, delayamt: m * R.lin(0.3, 1) }; },
      knobs: [K("delayamt", "delay", "%4.0f ms", 1, 2000)], jitter: ["delayamt"] },
    { type: "COMB", io: "mono", w: 2, in: ["in"], out: "out", mem: v => +v.maxdelay,
      params: R => { const m = R.int(20, 660); return { maxdelay: m, delayamt: m * R.lin(0.3, 1), feedback: R.sign() * R.lin(0.2, 0.75) }; },
      knobs: [K("feedback", "comb feedbk", "%5.2f", -0.85, 0.85)], jitter: ["delayamt"] },
    { type: "ALLPASS", io: "mono", w: 1, in: ["in"], out: "out", mem: v => +v.maxdelay,
      params: R => { const m = R.int(5, 120); return { maxdelay: m, delayamt: m * R.lin(0.3, 1), g: R.sign() * R.lin(0.3, 0.7) }; },
      jitter: ["delayamt"] },
    { type: "DETUNE", io: "mono", w: 3, in: ["in"], out: "out", loop: true, mem: v => +v.maxdelay,
      params: R => { const m = R.int(30, 200); return { maxdelay: m, delay_ctl: m * R.lin(0.2, 0.8), length_ctl: m * R.lin(0.5, 1), pitch_ctl: R.sign() * R.lin(5, 70) }; },
      knobs: [K("pitch_ctl", "detune", "%4.0f c", -100, 100)], jitter: ["pitch_ctl"] },
    { type: "PITCHSHIFT", io: "mono", w: 2, in: ["in"], out: "out", loop: true,
      params: R => ({ shift: R.chance(0.6) ? R.pick([-2400, -1200, -700, -500, 500, 700, 1200, 1900, 2400]) : R.sign() * R.lin(50, 2400), modamt: 0, delayamt: R.lin(0, 120) }),
      knobs: [K("shift", "pitch", "%5.0f c", -2400, 2400)] },
    { type: "FREQSHIFT", io: "mono", w: 1, in: ["in"], out: "out", loop: true,
      params: R => ({ freq: R.sign() * (R.chance(0.5) ? R.log(0.5, 40) : R.log(40, 1500)) }),
      knobs: [K("freq", "shift", "%6.1f Hz", -1000, 1000)], jitter: ["freq"] },
    { type: "REVDLY", io: "mono", w: 1, in: ["in"], out: "out", loop: true, mem: v => +v.maxdelay,
      params: R => { const m = R.int(300, 3000); return { maxdelay: m, reverseamt: R.lin(100, m / 2), xfadetime: R.lin(5, 40), reset: 0 }; } },
    { type: "DIFFUSOR", io: "mono", w: 2, in: ["in"], out: "out",
      params: R => { const ns = R.int(4, 8); return { nsections: ns, diffusion: R.lin(0.4, 0.8), dsize: R.lin(0.3, 0.9),
        "delayamt~n": n => 6 + n * R.lin(4, 12), "g~n": () => R.sign() * R.lin(0.3, 0.6) }; } },
    { type: "DIFFCHORUS", io: "mono", w: 2, in: ["in"], out: "out",
      params: R => { const ns = R.int(4, 8); return { nsections: ns, diffusion: R.lin(0.4, 0.8), dsize: R.lin(0.3, 0.9),
        moddepth: R.lin(0.2, 2), modrate: R.lin(0.1, 1.5), modratespan: R.lin(0, 0.5), gliderate: 0,
        "delayamt~n": n => Math.min(Math.floor(2000 / ns), 8 + n * R.lin(4, 10)), "g~n": () => R.sign() * R.lin(0.3, 0.6) }; },
      knobs: [K("dsize", "size", "%4.2f", 0, 1)] },
    { type: "STEREOTAPS", io: "m2s", w: 2, out: ["left", "right"], in: ["in"], mem: () => 660,
      params: R => ({ taps: R.int(2, 4), "delayamt~n": () => R.lin(40, 640), "amp~n": () => R.lin(0.4, 0.9), "pan~n": () => R.lin(-1, 1) }) },
    { type: "EASYTAPS", io: "m2s", w: 2, out: ["left", "right"], in: ["in"], mem: v => +v.length,
      params: R => { const t = R.int(4, 32); return { taps: t, numbertaps: R.int(2, t), length: R.lin(100, 1800), randomizing: R.lin(0, 1),
        delayalpha: R.lin(0, 1), width: R.sign() * R.lin(0.5, 1), ampalpha: R.lin(0, 0.6), ampshape: R.int(0, 4), delayshape: R.int(0, 4), panshape: R.int(0, 7) }; },
      knobs: [K("length", "taps length", "%5.0f ms", 10, 2000)] },
    { type: "REVERB_A", io: "stereo", w: 3, in: ["leftin", "rightin"], out: ["left", "right"], reverb: true,
      params: R => reverbParams(R, 12, 50),
      knobs: [K("decay", "decay", "%5.1f s", 0.1, 20), K("roomsize", "room size", "%4.2f", 0, 1)] },
    { type: "REVERB_B", io: "stereo", w: 2, in: ["leftin", "rightin"], out: ["left", "right"], reverb: true,
      params: R => reverbParams(R, 8, 80),
      knobs: [K("decay", "decay", "%5.1f s", 0.1, 20), K("roomsize", "room size", "%4.2f", 0, 1)] },
    { type: "STEREOSHIFT", io: "stereo", w: 1, in: ["leftin", "rightin"], out: ["left", "right"],
      params: R => ({ shift: R.chance(0.6) ? R.sign() * R.lin(6, 25) : R.pick([-1200, 700, 1200]), modamt: 0, delayamt: R.lin(5, 40), pan: R.lin(-0.6, 0.6) }),
      knobs: [K("shift", "shift", "%5.0f c", -2400, 2400)] },
    { type: "REVERSE", io: "mono", w: 2, in: ["in"], out: "out", mem: v => +v.maxdelay, tags: ["glitch"],
      params: R => { const m = R.int(300, 2000); return { maxdelay: m, delay_ctl: m, length_ctl: m * R.lin(0.3, 1),
        pitch_ctl: R.pick([0, 0, 0, 1200, -1200, 700]), direction: R.pick([0, 1]) }; },
      knobs: [K("length_ctl", "rev length", "%5.0f ms", 10, 2000)] },
    { type: "PITCHSHIFT", id: "MODPITCH", io: "mono", w: 2, in: ["in"], out: "out", lfo: ["mod"], tags: ["pitch", "mod"],
      params: R => ({ shift: R.pick([0, 0, -1200, 700, 1200, -500]), modamt: R.sign() * R.log(20, 600), delayamt: R.lin(0, 60) }),
      knobs: [K("modamt", "warble", "%5.0f c", -2400, 2400)] },
    { type: "MODFREQSHIFT", io: "mono", w: 1, in: ["in"], out: "out", lfo: ["mod"], tags: ["mod", "glitch"],
      params: R => ({ freq: R.sign() * R.log(0.5, 200), modamt: R.sign() * R.log(5, 400) }),
      knobs: [K("modamt", "shift sweep", "%6.1f Hz", -2000, 2000)] },
    { type: "MULTIPLY", id: "RINGMOD", io: "mono", w: 2, needs: ["OSCILLATOR", "MIX"], tags: ["glitch", "dirt"],
      build: (R, ins, h) => {
        const f = R.log(25, 1800), wave = R.pick([0, 0, 1, 2]);
        const osc = h.add("OSCILLATOR", "osc", l => ({ freq: f, modamt: 0, wave, dutycycle: 0.5 })[l]);
        const mul = h.add("MULTIPLY", "ring", l => ({ in1: ins[0], in2: osc.name + "-out" })[l]);
        let out = mul.name + "-out";
        if (R.chance(0.5)) { const mx = h.add("MIX", "ringmx", l => ({ in1: ins[0], in2: out, amp1: R.lin(0.3, 0.6), amp2: 0.8 })[l]); out = mx.name + "-out"; }
        h.knob({ base: "ring", label: "ring freq", fmt: "%6.1f Hz", min: 1, max: 5000, def: f, targets: [{ m: osc, key: "freq" }] });
        return { m: mul, outs: [out] };
      } },
    { type: "SAMPHOLD", id: "DECIMATE", io: "mono", w: 2, needs: ["IMPULSE"], tags: ["glitch", "dirt"],
      build: (R, ins, h) => {
        const f = R.log(300, 6000);
        const clk = h.add("IMPULSE", "clock", l => ({ freq: f, freqmod: 0 })[l]);
        const sh = h.add("SAMPHOLD", "crush", l => ({ in: ins[0], newsamp: clk.name + "-out" })[l]);
        h.knob({ base: "crush", label: "crush rate", fmt: "%5.0f Hz", min: 50, max: 20000, def: f, targets: [{ m: clk, key: "freq" }] });
        return { m: sh, outs: [sh.name + "-out"] };
      } },
  ];
  // sound families, for the styles
  const TAGS = { FILTER: ["filter"], TONE: ["filter"], EQ: ["filter"], MODFILTER: ["mod", "filter"], PHASESHIFT: ["mod"],
    DISTORT: ["dirt"], QUANTIZE: ["dirt", "glitch"], AMPMOD: ["mod"], DELAY: ["delay"], COMB: ["dirt", "delay"],
    ALLPASS: ["diffuse"], DETUNE: ["pitch", "mod"], PITCHSHIFT: ["pitch"], FREQSHIFT: ["pitch", "glitch"],
    REVDLY: ["glitch", "delay"], DIFFUSOR: ["diffuse"], DIFFCHORUS: ["diffuse", "mod"], STEREOTAPS: ["delay"],
    EASYTAPS: ["delay", "glitch"], REVERB_A: ["reverb"], REVERB_B: ["reverb"], STEREOSHIFT: ["pitch"] };
  CATALOG.forEach(c => { c.tags = c.tags || TAGS[c.type] || []; });
  // character: weight of each family, required "signature" family, steps, loop, possible shapes
  const STYLES = {
    ambient: { w: { reverb: 3, diffuse: 3, delay: 2, pitch: 1, mod: 1, filter: 1 }, sig: "reverb", stages: [2, 4], loop: 0.15,
      shapes: { series: 3, parallel: 2, dual: 1, pingpong: 1 } },
    glitch: { w: { glitch: 4, dirt: 2, delay: 2, pitch: 1, filter: 1 }, sig: "glitch", stages: [3, 6], loop: 0.12,
      shapes: { series: 2, parallel: 2, dual: 2, pingpong: 1 } },
    shimmer: { w: { pitch: 4, reverb: 2, delay: 2, diffuse: 1 }, sig: "pitch", stages: [2, 4], loop: 0.35, loopPitch: true,
      shapes: { series: 3, parallel: 1, pingpong: 2 } },
    motion: { w: { mod: 4, filter: 3, delay: 1, diffuse: 1 }, sig: "mod", stages: [2, 5], loop: 0.1,
      shapes: { series: 2, parallel: 2, dual: 2 } },
    dirty: { w: { dirt: 4, filter: 2, delay: 1, mod: 1, glitch: 1 }, sig: "dirt", stages: [2, 5], loop: 0.12,
      shapes: { series: 3, dual: 1, parallel: 1 } },
    echo: { w: { delay: 4, filter: 2, dirt: 1, mod: 1, diffuse: 1 }, sig: "delay", stages: [2, 4], loop: 0.4,
      shapes: { series: 2, pingpong: 3, dual: 1 } },
    metal: { w: { dirt: 2, pitch: 2, glitch: 2, filter: 1, delay: 1 }, sig: "metal", stages: [2, 4], loop: 0.15,
      shapes: { resonator: 4, series: 2, parallel: 1 } },
    lofi: { w: { dirt: 3, filter: 3, glitch: 2, mod: 1, delay: 1 }, sig: "lofi", stages: [2, 5], loop: 0.1,
      shapes: { series: 3, dual: 1, parallel: 1 } },
  };
  // extra signature modules per character
  const SIGNATURE = { metal: ["COMB", "FREQSHIFT", "RINGMOD"], lofi: ["QUANTIZE", "DECIMATE", "DISTORT"] };
  // typical level loss (dB) made up by the output gain
  const LOSS = { REVERB_A: 6, REVERB_B: 6, DIFFUSOR: 2, DIFFCHORUS: 2, FILTER: 3, MODFILTER: 4, EQ: 1, RINGMOD: 4,
    AMPMOD: 3, REVERSE: 1, REVDLY: 1, STEREOTAPS: 2, EASYTAPS: 3, PHASESHIFT: 1, DECIMATE: 1, COMB: -1, DISTORT: 0 };

  function reverbParams(R, ndel, dmax) {
    const p = { decay: R.log(0.8, 8), roomsize: R.lin(0.3, 0.9), predelay: R.lin(0, 40), low_freq: R.log(80, 400), high_freq: R.log(2500, 9000),
      low_atten: R.lin(-6, 0), high_atten: R.lin(-8, -1), low_decay: R.lin(-6, 0), high_decay: R.lin(-8, -1),
      moddepth: R.lin(0, 0.8), modrate: R.lin(0, 0.5), modratespan: R.lin(0, 0.5), gliderate: 1 };
    for (let i = 1; i <= ndel; i++) p["delay" + i] = R.lin(dmax * 0.15, dmax * 0.95);
    return p;
  }
  const BY = Object.fromEntries(CATALOG.filter(c => !c.id).map(c => [c.type, c]));

  // ---------------------------------------------------------------- generation
  const NEEDED = ["HEADM", "TAIL", "KNOB", "MENUPAGE", "TEXTBLOCK", "MIX", "LFO", "GAIN"];
  function generate(DEFS, seed) {
    const missing = NEEDED.filter(t => !DEFS[t]);
    if (missing.length) throw new Error("module database incomplete: " + missing.join(", "));
    seed = seed || (1 + Math.floor(Math.random() * 9999));
    let last = [];
    for (let attempt = 0; attempt < 60; attempt++) {
      const res = tryGenerate(DEFS, seed * 100 + attempt);
      const errs = validate(res.text, DEFS);
      if (res.memory > 6000) errs.push("delay memory budget exceeded");
      if (res.count > 24) errs.push("too many modules");
      if (!errs.length) return Object.assign(res, { seed });
      last = errs;
    }
    throw new Error("could not generate a valid patch with this module database (" + last.slice(0, 3).join("; ") + ")");
  }

  function tryGenerate(DEFS, s) {
    const R = rng(s);
    const H = "adc";
    const mods = [];          // {type,name,args}
    const knobs = [];         // {name, label, fmt, min, max, def, targets:[{mod, key}]}
    const used = new Set(["adc"]);
    const chain = [];
    let memory = 0;
    const avail = CATALOG.filter(c => DEFS[c.type] && DEFS[c.type].fields && (c.needs || []).every(t => DEFS[t]));
    const styleName = R.pick(Object.keys(STYLES)), style = STYLES[styleName];
    let lossDb = 0;
    const uniq = base => { let k = 1; while (used.has(base + k)) k++; used.add(base + k); return base + k; };
    const add = (type, base, p) => {
      const name = uniq(base);
      const m = { type, name, args: buildArgs(DEFS[type], H, p), p };
      mods.push(m);
      return m;
    };
    const val = (m, key) => { const l = S().fieldLabels(DEFS[m.type], m.args); const i = l ? l.findIndex(x => x.label === key) : -1; return i < 0 ? null : m.args[i]; };
    const setArg = (m, key, v) => { const l = S().fieldLabels(DEFS[m.type], m.args); const i = l.findIndex(x => x.label === key); if (i >= 0) m.args[i] = v; };
    let sharedLfo = null;
    const lfo = () => {
      if (sharedLfo && R.chance(0.5)) return sharedLfo;
      const f = R.chance(0.2) ? R.log(4, 16) : R.log(0.05, 4);
      const m = add("LFO", "lfo", l => ({ freq: f, modamt: 0, wave: R.pick([0, 0, 1, 2, 3]), dutycycle: 0.5, polarity: 0 })[l]);
      sharedLfo = m.name + "-out";
      return sharedLfo;
    };

    // places a catalogue module; ins: input signals; returns its audio outputs
    function place(c, ins, jitter, fixed) {
      lossDb += LOSS[c.id || c.type] || 0;
      if (c.build) return c.build(R, ins, { add, knob: k => knobs.push(k) });
      const base = c.type.toLowerCase().replace(/_/g, "").slice(0, 6);
      const pv = Object.assign(c.params(R), fixed || {});
      if (jitter) (c.jitter || []).forEach(k => { if (typeof pv[k] === "number") pv[k] *= R.lin(0.88, 1.12); });
      const lfos = {};
      (c.lfo || []).forEach(f => { lfos[f] = lfo(); });
      const m = add(c.type, base, (label, n, vals, it) => {
        const ii = c.in.indexOf(label);
        if (ii >= 0) return ins[Math.min(ii, ins.length - 1)];
        if (lfos[label]) return lfos[label];
        if (c.type === "COMPRESSOR" && label === "sidechain") return ins[0];
        let v = pv[label] !== undefined ? pv[label] : pv[it.name];
        if (typeof v === "function") v = v(n, vals);
        if (v === undefined) return undefined;
        // clamp to the numeric limits of the database
        const lo = boundOf(it.min, vals), hi = boundOf(it.max, vals);
        if (typeof v === "number") { if (lo !== null) v = Math.max(lo, v); if (hi !== null) v = Math.min(hi, v); }
        return v;
      });
      m.recipe = c;
      if (c.mem) memory += c.mem(Object.fromEntries(S().fieldLabels(DEFS[c.type], m.args).map((l, i) => [l.label, m.args[i]])));
      let outs = typeof c.out === "function" ? c.out(R) : c.out;
      outs = (Array.isArray(outs) ? outs : [outs]).map(o => m.name + "-" + o);
      if (c.trim) {
        const vals = Object.fromEntries(S().fieldLabels(DEFS[c.type], m.args).map((l, i) => [l.label, m.args[i]]));
        const g = add("GAIN", "trim", l => ({ in: outs[0], gain: Math.max(-24, c.trim(vals)) })[l]);
        outs = [g.name + "-out"];
      }
      return { m, outs };
    }

    const weight = c => c.w * Math.max(0.15, ...c.tags.map(t => style.w[t] || 0));
    const pickRecipe = (filter) => {
      const list = avail.filter(filter);
      const total = list.reduce((a, c) => a + weight(c), 0);
      let x = R.lin(0, total);
      for (const c of list) { x -= weight(c); if (x <= 0) return c; }
      return list[list.length - 1];
    };
    const isSig = c => (SIGNATURE[styleName] ? SIGNATURE[styleName].includes(c.id || c.type) : c.tags.includes(style.sig));

    // ---- patch shape
    const shapeName = (() => {
      const e = Object.entries(style.shapes).filter(([k]) => k !== "resonator" || DEFS.COMB);
      let x = R.lin(0, e.reduce((a, [, w]) => a + w, 0));
      for (const [k, w] of e) { x -= w; if (x <= 0) return k; }
      return e[0][0];
    })();
    const sum = (a, b) => a === b ? a : add("MIX", "sum", l => ({ in1: a, in2: b, amp1: 0.7, amp2: 0.7 })[l]).name + "-out";
    let L = H + "-in1", Rr = H + "-in2";
    let haveReverb = false, haveLoop = false, sigDone = false;
    const label = c => c.id || c.type;
    // module choice: the first one is a "signature" module of the character
    const stagePick = filter => {
      if (!sigDone && avail.some(c => filter(c) && isSig(c))) { sigDone = true; return pickRecipe(c => filter(c) && isSig(c)); }
      const c = pickRecipe(filter);
      if (isSig(c)) sigDone = true;
      return c;
    };
    const noRev = c => !(c.reverb && haveReverb);
    function monoChain(sig, n, tag) {
      const names = [];
      for (let i = 0; i < n; i++) {
        const c = stagePick(c => c.io === "mono");
        names.push(label(c));
        const x = place(c, [sig]); sig = x.outs[0]; addKnob(c, [x.m]);
      }
      chain.push((tag ? tag + ": " : "") + names.join(" > "));
      return sig;
    }
    function feedbackLoop(src, pingpong) {
      haveLoop = true;
      const fb = R.lin(0.25, 0.55);
      // the return is only known afterwards: create the MIX, then fix in2
      const mix = { type: "MIX", name: uniq("fbmix"), args: buildArgs(DEFS.MIX, H, l => ({ in1: src, amp1: 0.7, amp2: fb })[l]) };
      mods.push(mix);
      let sig = mix.name + "-out";
      const dl = place(BY.DELAY, [sig]); sig = dl.outs[0];
      const names = ["DELAY"];
      let left = sig;
      if (R.chance(style.loopPitch ? 0.9 : 0.5)) {
        const pool = avail.filter(c => c.loop && c.type !== "DELAY" && c.type !== "REVDLY" && (!style.loopPitch || c.tags.includes("pitch")));
        if (pool.length) {
          const lc = R.pick(pool);
          const x = place(lc, [sig], false, lc.loopParams ? lc.loopParams(R) : null); sig = x.outs[0]; names.push(lc.type);
        }
      }
      if (pingpong) { const d2 = place(BY.DELAY, [sig]); sig = d2.outs[0]; names.push("DELAY"); }
      const hc = add("HIGHCUT", "hicut", l => ({ in: sig, freq: R.log(1500, 9000) })[l]);
      sig = hc.name + "-out";
      mix.args[S().fieldLabels(DEFS.MIX, mix.args).findIndex(x => x.label === "in2")] = sig;
      knobs.push({ base: "fbk", label: "feedback", fmt: "%4.2f", min: 0, max: 0.6, def: fb, targets: [{ m: mix, key: "amp2" }] });
      knobs.push({ base: "dly", label: "delay", fmt: "%4.0f ms", min: 1, max: +val(dl.m, "maxdelay"), def: +val(dl.m, "delayamt"), targets: [{ m: dl.m, key: "delayamt" }] });
      chain.push((pingpong ? "ping-pong loop: " : "feedback loop: ") + names.join(" > "));
      return pingpong ? [left, sig] : [sig, sig];
    }
    // one step of the series chain
    function stage() {
      if (!haveLoop && avail.some(c => c.type === "DELAY") && DEFS.MIX && DEFS.HIGHCUT && R.chance(style.loop)) {
        [L, Rr] = feedbackLoop(sum(L, Rr), false);
        return;
      }
      const c = stagePick(noRev);
      if (c.reverb) haveReverb = true;
      if (c.io === "stereo") {
        chain.push(label(c));
        const x = place(c, [L, Rr]); L = x.outs[0]; Rr = x.outs[1]; addKnob(c, [x.m]);
      } else if (c.io === "m2s") {
        chain.push(label(c));
        const x = place(c, [sum(L, Rr)]); L = x.outs[0]; Rr = x.outs[1]; addKnob(c, [x.m]);
      } else if (L === Rr) {
        chain.push(label(c));
        const x = place(c, [L]); L = Rr = x.outs[0]; addKnob(c, [x.m]);
      } else if (c.build || R.chance(0.45)) {
        // left and right processed by different modules
        const c2 = pickRecipe(x => x.io === "mono");
        chain.push(label(c) + " | " + label(c2));
        const a = place(c, [L]), b = place(c2, [Rr]);
        L = a.outs[0]; Rr = b.outs[0]; addKnob(c, [a.m]); addKnob(c2, [b.m]);
      } else {
        // two linked instances, parameters slightly offset on the right
        chain.push(label(c) + " (stereo)");
        const a = place(c, [L]);
        const b = place(c, [Rr], true);
        const la = S().fieldLabels(DEFS[c.type], a.m.args), lb = S().fieldLabels(DEFS[c.type], b.m.args);
        if (la && lb && la.length === lb.length) la.forEach((l, i) => {
          if (l.type === "ctl_in" && !(c.jitter || []).includes(l.label)) b.m.args[i] = a.m.args[i];
        });
        L = a.outs[0]; Rr = b.outs[0]; addKnob(c, [a.m, b.m]);
      }
    }

    const nStages = R.int(style.stages[0], style.stages[1]);
    let lossDiv = 1;
    if (shapeName === "parallel") {
      const src = sum(L, Rr), nb = R.int(2, 3);
      const br = [];
      for (let i = 0; i < nb; i++) br.push(monoChain(src, R.int(1, 2), "branch " + (i + 1)));
      if (nb === 2) { L = br[0]; Rr = br[1]; }
      else {
        L = add("MIX", "remix", l => ({ in1: br[0], in2: br[1], amp1: 0.75, amp2: 0.55 })[l]).name + "-out";
        Rr = add("MIX", "remix", l => ({ in1: br[2], in2: br[1], amp1: 0.75, amp2: 0.55 })[l]).name + "-out";
      }
      lossDiv = nb;
      for (let i = R.int(0, 1); i > 0; i--) stage();
    } else if (shapeName === "dual") {
      L = monoChain(L, R.int(1, 3), "left");
      Rr = monoChain(Rr, R.int(1, 3), "right");
      lossDiv = 2;
      for (let i = R.int(0, 1); i > 0; i--) stage();
    } else if (shapeName === "pingpong" && DEFS.MIX && DEFS.HIGHCUT && BY.DELAY) {
      if (R.chance(0.5)) stage();
      [L, Rr] = feedbackLoop(sum(L, Rr), true);
      for (let i = R.int(0, 2); i > 0; i--) stage();
    } else if (shapeName === "resonator") {
      // bank of tuned COMBs (musical intervals), remixed to stereo
      const src = sum(L, Rr), root = R.log(70, 380);
      const ratios = R.pick([[1, 1.5, 2, 3], [1, 1.25, 1.5, 2], [1, 2, 3, 4], [1, 1.335, 1.5, 2], [1, 1.2, 1.5, 1.8]]);
      const fbk = R.lin(0.55, 0.82);
      const combs = ratios.map(r => {
        const d = 1000 / (root * r);
        return add("COMB", "reso", l => ({ maxdelay: Math.ceil(d) + 1, in: src, delayamt: d, feedback: fbk })[l]);
      });
      L = add("MIX", "resmix", l => ({ in1: combs[0].name + "-out", in2: combs[2].name + "-out", amp1: 0.5, amp2: 0.5 })[l]).name + "-out";
      Rr = add("MIX", "resmix", l => ({ in1: combs[1].name + "-out", in2: combs[3].name + "-out", amp1: 0.5, amp2: 0.5 })[l]).name + "-out";
      knobs.push({ base: "reso", label: "resonance", fmt: "%4.2f", min: 0, max: 0.85, def: fbk, targets: combs.map(m => ({ m, key: "feedback" })) });
      chain.push(`resonators ${Math.round(root)} Hz x ${ratios.join("/")}`);
      memory += combs.length * 20;
      lossDb -= 4;
      for (let i = R.int(1, 2); i > 0; i--) stage();
    } else {
      for (let st = 0; st < nStages; st++) stage();
    }

    // output still mono: usually end with a stereo module
    if (L === Rr && R.chance(0.8)) {
      const c = pickRecipe(c => (c.io === "m2s" || c.io === "stereo") && noRev(c));
      chain.push(label(c));
      const x = place(c, c.io === "stereo" ? [L, L] : [L]);
      L = x.outs[0]; Rr = x.outs[1]; addKnob(c, [x.m]);
    }

    function addKnob(c, ms) {
      if (!c.knobs || knobs.length >= 4) return;
      const k = R.pick(c.knobs);
      if (knobs.some(x => x.targets.some(t => ms.includes(t.m) && t.key === k.key))) return;
      const v = +val(ms[0], k.key);
      if (!isFinite(v)) return;
      const labels = S().fieldLabels(DEFS[c.type], ms[0].args);
      const f = labels && labels.find(l => l.label === k.key);
      const vals = {}; (labels || []).forEach((l, i) => { vals[l.label] = ms[0].args[i]; });
      let lo = k.min, hi = k.max;
      ms.forEach(m => {
        const lm = S().fieldLabels(DEFS[c.type], m.args), vm = {};
        lm.forEach((l, i) => { vm[l.label] = m.args[i]; });
        const b0 = boundOf(f && f.min, vm), b1 = boundOf(f && f.max, vm);
        if (b0 !== null) lo = Math.max(lo, b0);
        if (b1 !== null) hi = Math.min(hi, b1);
      });
      if (!(hi > lo)) return;
      if (f && f.type !== "ctl_in") return;   // only control parameters accept a knob
      knobs.push({ base: k.label.replace(/[^a-z]/g, "").slice(0, 6) || "knob", label: k.label, fmt: k.fmt, min: lo, max: hi,
        def: Math.min(hi, Math.max(lo, v)), targets: ms.map(m => ({ m, key: k.key })) });
    }

    // 100 % wet (the dry/wet balance is set in the DSP7000 system); output gain that
    // makes up the chain's estimated losses, then a limiter that caps the level
    const gainDb = Math.round(Math.max(0, Math.min(18, 3 + lossDb / lossDiv)) * 10) / 10;
    const gl = add("GAIN", "level", l => ({ in: L, gain: gainDb })[l]);
    const gr = L === Rr ? gl : add("GAIN", "level", l => ({ in: Rr, gain: gainDb })[l]);
    knobs.unshift({ base: "level", label: "level", fmt: "%5.1f dB", min: -12, max: 18, def: gainDb,
      targets: gl === gr ? [{ m: gl, key: "gain" }] : [{ m: gl, key: "gain" }, { m: gr, key: "gain" }] });
    let outL = gl.name + "-out", outR = gr.name + "-out";
    if (DEFS.COMPRESSOR) {
      const lim = (sig, base) => add("COMPRESSOR", base, l => ({ in: sig, sidechain: sig, threshcntl: -1, kneecntl: 0, ratiocntl: 20, gaincntl: 0, attackcntl: 0.001, decaycntl: 0.1 })[l]);
      outL = lim(outL, "limitl").name + "-out";
      outR = lim(outR, "limitr").name + "-out";
    }

    // knobs (5 at most) and menu pages
    const ui = [];
    knobs.slice(0, 5).forEach(k => {
      const name = uniq(k.base);
      const res = (k.max - k.min) / 100 >= 1 ? 1 : Math.pow(10, Math.floor(Math.log10((k.max - k.min) / 100)));
      const label = (k.label + ": " + k.fmt).slice(0, 26);
      ui.push({ type: "KNOB", name, args: [`"${label}"`, '""', num(k.min), num(k.max), num(res), num(Math.round(k.def / res) * res)] });
      k.targets.forEach(t => setArg(t.m, t.key, name + "-out"));
    });
    const pageName = uniq("main");
    ui.push({ type: "MENUPAGE", name: pageName, args: ['"random parameters"', '"random"', String(ui.length)].concat(ui.map(u => u.name + "-obj")) });
    const title = ("Random " + String(Math.floor(s / 100)).padStart(4, "0") + " " + styleName).slice(0, 19);
    const info = uniq("info");
    const text = chainText(styleName, shapeName, chain);
    ui.push({ type: "TEXTBLOCK", name: info, args: [String(text.length)].concat(text.map(t => `"${t}"`)) });

    const lines = [`HEADM ${H} 2 2 ${outL} ${outR} "${title}" "" 2 ${pageName}-obj ${info}-obj`];
    ui.forEach(u => lines.push([u.type, u.name].concat(u.args).join(" ")));
    mods.forEach(m => lines.push([m.type, m.name].concat(m.args).join(" ")));
    lines.push("TAIL as");
    return { text: lines.join("\n") + "\n", title, chain: chain.join(" > "), style: styleName, shape: shapeName, gain: gainDb, memory, count: mods.length };
  }

  function chainText(style, shape, chain) {
    const out = ["MSIG random: " + style + ", " + shape];
    chain.forEach(c => {
      let line = "";
      c.split(" ").forEach(w => {
        if ((line + " " + w).trim().length > 38) { out.push(line.trim()); line = w; } else line += " " + w;
      });
      if (line.trim()) out.push(line.trim());
    });
    return out.slice(0, 8).map(t => t.replace(/"/g, "'"));
  }

  // numeric bound of a field (min/max), including "@param"; null if the expression is unresolved
  function boundOf(b, vals) {
    const p = plain(b);
    if (isNum(p)) return +p;
    if (/^@\w+$/.test(p) && isNum(vals[p.slice(1)])) return +vals[p.slice(1)];
    const m = /^@(\w+)\/2$/.exec(p);
    if (m && isNum(vals[m[1]])) return vals[m[1]] / 2;
    return null;
  }

  // ---------------------------------------------------------------- validation
  function validate(text, DEFS) {
    const Sg = S();
    const doc = Sg.parse(text);
    const errs = [];
    const names = new Set(doc.mods.map(m => m.name));
    const index = Object.fromEntries(doc.mods.map((m, i) => [m.name, i]));
    const outType = {};
    doc.mods.forEach(m => {
      const d = DEFS[m.type];
      if (!d) { errs.push(m.name + ": unknown type " + m.type); return; }
      if (m.type === "TAIL") return;
      const labels = Sg.fieldLabels(d, m.args);
      if (!labels) { errs.push(m.name + ": wrong number of arguments"); return; }
      Sg.outputsOf(d, m.args).forEach(o => { outType[m.name + "-" + o.name] = o.type; });
      m._labels = labels;
    });
    const edges = [];
    doc.mods.forEach((m, i) => {
      if (!m._labels) return;
      const vals = {};
      m._labels.forEach((l, j) => { vals[l.label] = m.args[j]; });
      m._labels.forEach((l, j) => {
        const a = m.args[j];
        const c = Sg.asConnection(a, names);
        const t = l.type;
        if (c) {
          const ot = outType[c.mod + "-" + c.port];
          if (!ot) { errs.push(`${m.name}.${l.label}: unknown output ${a}`); return; }
          const ok = (t === "audio_in" || t === "mod_in") ? /^(audio|mod)_out$/.test(ot)
            : t === "ctl_in" ? ot === "ctl_out" : t === "obj_in" ? ot === "obj_out" : false;
          if (!ok) errs.push(`${m.name}.${l.label}: ${ot} cannot feed ${t}`);
          if (/^(audio|mod)_in$/.test(t)) edges.push({ from: c.mod, to: m.name, i, j: index[c.mod] });
        } else {
          if (/^(audio|mod|obj)_in$/.test(t)) errs.push(`${m.name}.${l.label}: literal on ${t}`);
          if ((t === "ctl_in" || t === "spec") && l.ed !== "string" && isNum(a)) {
            const lo = boundOf(l.min, vals), hi = boundOf(l.max, vals);
            if ((lo !== null && +a < lo - 1e-9) || (hi !== null && +a > hi + 1e-9)) errs.push(`${m.name}.${l.label}=${a} outside ${l.min}..${l.max}`);
          }
        }
      });
      // silence traps
      const v = k => vals[k];
      if (m.type === "HIGHCUT" && +v("freq") < 500 && isNum(v("freq"))) errs.push(m.name + ": highcut too low");
      if (/^(GATE|GATE2|EXPANDER|SWITCH|ISWITCH|OSWITCH|DUCKER)$/.test(m.type)) errs.push(m.name + ": risky module");
      if (m.type === "MIX" && isNum(v("amp1")) && isNum(v("amp2")) && Math.abs(+v("amp1")) + Math.abs(+v("amp2")) < 0.3) errs.push(m.name + ": mix near zero");
      if (m.type === "COMB" && isNum(v("feedback")) && Math.abs(+v("feedback")) > 0.85) errs.push(m.name + ": comb feedback too high");
      if (/^REVERB/.test(m.type) && isNum(v("decay")) && +v("decay") > 20) errs.push(m.name + ": decay too long");
    });
    // loops: any edge to a module placed later (except HEADM) must end at a MIX fbmix whose return gain <= 0.6
    edges.forEach(e => {
      const to = doc.mods[e.i];
      if (to.type === "HEADM") return;
      if (e.j >= e.i) {
        const vals = {}; (to._labels || []).forEach((l, j) => { vals[l.label] = to.args[j]; });
        const fbOk = to.type === "MIX" && /^fbmix/.test(to.name);
        if (!fbOk) errs.push(`${to.name}: feedback from ${e.from} outside the controlled loop`);
      }
    });
    const loops = doc.mods.filter(m => /^fbmix/.test(m.name));
    if (loops.length > 1) errs.push("more than one feedback loop");
    loops.forEach(mx => {
      const vals = {}; (mx._labels || []).forEach((l, j) => { vals[l.label] = mx.args[j]; });
      const g = vals.amp2;
      const knob = doc.mods.find(k => g === k.name + "-out");
      const gmax = knob ? +knob.args[3] : +g;
      if (!(gmax <= 0.6)) errs.push(mx.name + ": feedback gain above 0.6");
      // blocks allowed in the loop
      const back = {}; edges.forEach(e => { (back[e.to] = back[e.to] || []).push(e.from); });
      const seen = new Set(), stack = [String(vals.in2).replace(/-\w+$/, "")];
      while (stack.length) {
        const n = stack.pop();
        if (n === mx.name || seen.has(n)) continue;
        seen.add(n);
        const mm = doc.mods[index[n]];
        if (!mm) continue;
        if (!/^(DELAY|PITCHSHIFT|FREQSHIFT|DETUNE|REVDLY|TONE|HIGHCUT)$/.test(mm.type)) errs.push(`${mx.name}: ${mm.type} not allowed in the feedback loop`);
        (back[n] || []).forEach(f => stack.push(f));
      }
    });
    // outputs: audio, fed from the input
    const head = doc.mods.find(m => m.type === "HEADM");
    if (!head || !head._labels) errs.push("HEADM missing");
    else {
      const fwd = {}; edges.forEach(e => { (fwd[e.from] = fwd[e.from] || []).push(e.to); });
      const reach = new Set(), st = ["adc"];
      while (st.length) { const n = st.pop(); (fwd[n] || []).forEach(t => { if (!reach.has(t)) { reach.add(t); st.push(t); } }); }
      [head.args[2], head.args[3]].forEach(o => {
        const c = Sg.asConnection(o, names);
        if (!c || c.mod === "adc") errs.push("output not processed: " + o);
        else if (!reach.has(c.mod)) errs.push("output not fed by the input: " + o);
        else if (!/audio_out/.test(outType[o] || "")) errs.push("output is not audio: " + o);
      });
    }
    return errs;
  }

  let Sref = null;
  const S = () => Sref || (Sref = root.Sigfile || (typeof require !== "undefined" ? require("./sigfile.js") : null));
  const api = { generate, validate, CATALOG };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MsigRandom = api;
})(this);
