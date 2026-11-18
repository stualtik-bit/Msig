// sigfile.js - reading/writing sigfiles (the DSP's text format for algorithms)
// One line = one module: TYPE name arg1 arg2 ... [; comment]
// An argument of the form "module-port" is a connection to the "port" output
// of an existing module; anything else is a literal value.
// The text is rewritten token by token: whatever is not modified stays identical.

(function (root) {
  "use strict";

  function tokenize(s) {
    const toks = [];
    let i = 0;
    while (i < s.length) {
      const c = s[i];
      if (c === " " || c === "\t") { i++; continue; }
      if (c === '"') {
        const j = s.indexOf('"', i + 1);
        const end = j < 0 ? s.length : j + 1;
        toks.push(s.slice(i, end));
        i = end;
      } else {
        let j = i;
        while (j < s.length && s[j] !== " " && s[j] !== "\t") j++;
        toks.push(s.slice(i, j));
        i = j;
      }
    }
    return toks;
  }

  // Splits off the ";..." comment (outside strings).
  function splitComment(line) {
    let q = false;
    for (let i = 0; i < line.length; i++) {
      if (line[i] === '"') q = !q;
      else if (line[i] === ";" && !q) return [line.slice(0, i), line.slice(i)];
    }
    return [line, ""];
  }

  function parse(text) {
    const lines = text.replace(/\r\n?/g, "\n").split("\n");
    const mods = [];
    const extra = []; // blank lines or comment-only lines, kept as is
    lines.forEach((raw, idx) => {
      const [body, comment] = splitComment(raw);
      const toks = tokenize(body);
      if (toks.length < 2) {
        if (raw.trim()) extra.push({ after: mods.length, raw });
        return;
      }
      const m = { type: toks[0], name: toks[1], args: toks.slice(2), comment, line: idx };
      const pos = /;=\s*(-?\d+)\s*,\s*(-?\d+)/.exec(comment);
      if (pos) m.pos = { x: +pos[1], y: +pos[2] };
      mods.push(m);
    });
    return { mods, extra };
  }

  function serialize(doc, eol) {
    eol = eol || "\n";
    const out = [];
    doc.mods.forEach((m, i) => {
      doc.extra.filter(e => e.after === i).forEach(e => out.push(e.raw));
      let s = [m.type, m.name].concat(m.args).join(" ");
      if (m.comment) s += " " + m.comment.trim();
      out.push(s);
    });
    doc.extra.filter(e => e.after >= doc.mods.length).forEach(e => out.push(e.raw));
    return out.join(eol) + eol;
  }

  // "diff1-out" -> {mod:"diff1", port:"out"} if "diff1" is a module of the document.
  function asConnection(tok, names) {
    if (tok[0] === '"') return null;
    const k = tok.indexOf("-");
    if (k <= 0) return null;
    const mod = tok.slice(0, k), port = tok.slice(k + 1);
    if (!port || !names.has(mod)) return null;
    return { mod, port };
  }

  // Schema taken from the DSP database (dbase2json.py):
  //   fields : [{name, type, ed, min, max, def, desc} | {repeat:"@param"|"N", items:[...]}]
  //   outputs: [{name, type} | {repeat, items}]
  // Names containing "~n" are numbered on expansion.
  function repeatCount(spec, values) {
    if (spec[0] === "@") { const v = values[spec.slice(1)]; return /^\d+$/.test(v || "") ? +v : null; }
    return /^\d+$/.test(spec) ? +spec : null;
  }

  // Argument labels for a line; null if the number of arguments does not match.
  function fieldLabels(def, args) {
    if (!def) return null;
    const labels = [], values = {};
    let ok = true;
    (function walk(items, n) {
      for (const it of items) {
        if (!ok) return;
        if (it.repeat !== undefined) {
          const c = repeatCount(it.repeat, values);
          if (c === null) { ok = false; return; }
          for (let j = 1; j <= c; j++) walk(it.items, j);
        } else {
          const label = n ? it.name.replace(/~n/g, n) : it.name;
          if (labels.length < args.length) values[label] = args[labels.length];
          labels.push(Object.assign({}, it, { label }));
        }
      }
    })(def.fields, 0);
    return ok && labels.length === args.length ? labels : null;
  }

  function valuesOf(def, args) {
    const v = {};
    (fieldLabels(def, args) || []).forEach((l, i) => { v[l.label] = args[i]; });
    return v;
  }

  // Outputs of a module (sometimes depend on its parameters, e.g. HEADM in1..inN).
  function outputsOf(def, args) {
    if (!def) return [];
    const values = valuesOf(def, args), out = [];
    (function walk(items, n) {
      for (const it of items) {
        if (it.repeat !== undefined) {
          const c = repeatCount(it.repeat, values) || 0;
          for (let j = 1; j <= c; j++) walk(it.items, j);
        } else out.push({ name: n ? it.name.replace(/~n/g, n) : it.name, type: it.type });
      }
    })(def.outputs, 0);
    return out;
  }

  // Default arguments for a new module. `given` (label -> value) keeps existing values:
  // used to rebuild the list when a count (outputs, sections...) changes.
  function defaultArgs(def, head, given) {
    given = given || {};
    const args = [], values = {};
    const plain = s => String(s == null ? "" : s).replace(/^=/, "");
    (function walk(items, n) {
      for (const it of items) {
        if (it.repeat !== undefined) {
          const c = repeatCount(it.repeat, values);
          for (let j = 1; j <= (c === null ? 1 : c); j++) walk(it.items, j);
          continue;
        }
        const label = n ? it.name.replace(/~n/g, n) : it.name;
        let v;
        if (Object.prototype.hasOwnProperty.call(given, label)) v = given[label];
        else if (it.type === "audio_in" || it.type === "mod_in") v = head + "-null";
        else if (it.type === "obj_in") v = head + "-nullobj";
        else if (it.ed === "string") v = '"' + plain(it.def).replace(/~n/g, n) + '"';
        else {
          v = plain(it.def);
          if (!/^-?[\d.]+$/.test(v)) v = /^-?[\d.]+$/.test(plain(it.min)) ? plain(it.min) : "0";
        }
        values[label] = v;
        args.push(v);
      }
    })(def.fields, 0);
    return args;
  }

  // New argument list after argument i changes. If it is a count that sets how many
  // arguments follow (HEADM outputs, MIXER inputs...), the list is rebuilt from the
  // definition: values kept by label, default values for the new ones.
  function withArg(def, args, i, v, head) {
    const before = def && fieldLabels(def, args), out = args.slice();
    out[i] = v;
    if (!before || fieldLabels(def, out)) return out;
    const by = {};
    before.forEach((l, k) => { by[l.label] = out[k]; });
    const redone = defaultArgs(def, head, by);
    return fieldLabels(def, redone) ? redone : out;
  }

  // Graph: connections (source -> field) for each module.
  function connections(doc) {
    const names = new Set(doc.mods.map(m => m.name));
    const edges = [];
    doc.mods.forEach((m, mi) => {
      m.args.forEach((a, ai) => {
        const c = asConnection(a, names);
        if (c) edges.push({ from: c.mod, port: c.port, to: m.name, arg: ai, toIndex: mi });
      });
    });
    return edges;
  }

  const api = { tokenize, parse, serialize, asConnection, fieldLabels, outputsOf, defaultArgs, withArg, connections };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Sigfile = api;
})(this);
