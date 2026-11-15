// English ⇄ ಕನ್ನಡ for the workspace.
//
// How it works: components keep their English text. Any region marked with a
// `data-i18n` attribute is watched; each piece of text inside it is looked up in
// i18n/kn.js and shown in Kannada while the language is "kn". Only what is
// DISPLAYED changes — React state, input values, prompts and everything sent to
// the server stay exactly as they are. Text with no dictionary entry stays English.
//
// To translate another screen: put data-i18n on its root element and add its
// strings to i18n/kn.js. To exclude a region inside one: data-noi18n.
//
// The choice lives in localStorage "prefectos_lang" — the same key the public
// website and the generated reports use, so all three follow one switch.
import { KN, RULES } from "./kn.js";

const LK = "prefectos_lang";
const ATTRS = ["placeholder", "title", "aria-label"];
const SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, CODE: 1, PRE: 1 };
const seenText = new WeakMap();
const seenAttr = new WeakMap();
const miss = new Set(); // strings known to have no translation (bounded below)
const listeners = new Set();
let lang = "en";
let started = false;

const norm = (s) => s.replace(/\s+/g, " ").trim();

function toKn(en) {
  if (en.length > 400) return null; // long free text is never a UI label
  const k = norm(en);
  if (!k || miss.has(k)) return null;
  if (Object.prototype.hasOwnProperty.call(KN, k)) return KN[k];
  for (const [re, build] of RULES) {
    const m = k.match(re);
    if (m) {
      const out = build(m, toKn);
      if (out != null) return out;
    }
  }
  if (miss.size < 5000) miss.add(k);
  return null;
}

function inScope(el) {
  return !!el && !!el.closest && !!el.closest("[data-i18n]") && !el.closest("[data-noi18n]");
}

function doText(n) {
  const cur = n.nodeValue;
  const rec = seenText.get(n);
  if (rec && rec.out === cur) {
    // still showing what we wrote
    if (lang === "en") {
      seenText.delete(n);
      n.nodeValue = rec.en;
    }
    return;
  }
  if (lang !== "kn") return;
  const p = n.parentElement;
  if (!p || SKIP[p.nodeName] || !inScope(p)) return;
  const t = toKn(cur);
  if (t == null) return;
  const out = cur.match(/^\s*/)[0] + t + cur.match(/\s*$/)[0];
  seenText.set(n, { en: cur, out });
  n.nodeValue = out;
}

function doAttrs(el) {
  let rec = seenAttr.get(el);
  for (const a of ATTRS) {
    if (!el.hasAttribute(a)) continue;
    const cur = el.getAttribute(a);
    const r = rec && rec[a];
    if (r && r.out === cur) {
      if (lang === "en") {
        delete rec[a];
        el.setAttribute(a, r.en);
      }
      continue;
    }
    if (lang !== "kn" || !inScope(el)) continue;
    const t = toKn(cur);
    if (t == null) continue;
    if (!rec) {
      rec = {};
      seenAttr.set(el, rec);
    }
    rec[a] = { en: cur, out: t };
    el.setAttribute(a, t);
  }
}

function sweep(root) {
  if (root.nodeType === 3) return doText(root);
  if (root.nodeType !== 1 || SKIP[root.nodeName]) return;
  doAttrs(root);
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    if (n.nodeType === 3) doText(n);
    else doAttrs(n);
  }
}

function loadFont() {
  if (document.getElementById("knfont")) return;
  const f = document.createElement("link");
  f.id = "knfont";
  f.rel = "stylesheet";
  f.href = "https://fonts.googleapis.com/css2?family=Noto+Sans+Kannada:wght@400;500;600;700;800&display=swap";
  document.head.appendChild(f);
}

export function getLang() {
  return lang;
}

export function setLang(next, remember = true) {
  lang = next === "kn" ? "kn" : "en";
  document.documentElement.lang = lang;
  if (remember) {
    try {
      localStorage.setItem(LK, lang);
    } catch {
      /* storage unavailable */
    }
  }
  if (lang === "kn") loadFont();
  if (document.body) sweep(document.body);
  listeners.forEach((fn) => fn(lang));
}

export function onLangChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Call once, before React renders. Reads ?lang=, then the remembered choice. */
export function initI18n() {
  if (started) return;
  started = true;
  let start = "en";
  try {
    const q = new URLSearchParams(window.location.search).get("lang");
    start = q === "kn" || q === "en" ? q : localStorage.getItem(LK) || "en";
    if (q === "kn" || q === "en") localStorage.setItem(LK, q);
  } catch {
    /* storage unavailable — English */
  }
  // Whatever React renders or updates later is translated as it lands.
  new MutationObserver((records) => {
    if (lang !== "kn") return;
    for (const m of records) {
      if (m.type === "characterData") doText(m.target);
      else if (m.type === "attributes") doAttrs(m.target);
      else m.addedNodes.forEach(sweep);
    }
  }).observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRS,
  });
  setLang(start, false);
}
