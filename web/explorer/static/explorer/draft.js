/* Condor Funds v2 — where the Explore draft lives.
 *
 * One draft, two homes. Signed in, it is the account's row behind
 * `/api/draft`, exactly as it always was. Anonymous, it is this browser's
 * localStorage — the whole Explore journey is open to people without an
 * account, so their mix has to survive a reload without anything of
 * theirs reaching the server.
 *
 * Both homes hold the same JSON the API round-trips ({assets, updated_at}),
 * which is what makes the import below a straight PUT.
 *
 * Build (home.js) and Optimize (app.js) both read and write the draft
 * through here; neither has to know which home is in use.
 */
"use strict";

const CondorDraft = (() => {
  const KEY = "condor.draft.v1";
  const MAX_ASSETS = 15;                       // views.MAX_ASSETS
  const TICKER_RE = /^[A-Z0-9.\-^]{1,10}$/;    // views.TICKER_RE

  // Rendered by both Explore templates via json_script.
  const authenticated = (() => {
    const el = document.getElementById("is_authenticated");
    try { return el ? JSON.parse(el.textContent) === true : false; }
    catch { return false; }
  })();

  function csrftoken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  // ---------- the account's draft (unchanged: /api/draft) ----------
  async function apiGet() {
    const res = await fetch("/api/draft");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
    return data;
  }

  async function apiPut(assets) {
    const res = await fetch("/api/draft", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrftoken() },
      body: JSON.stringify({ assets }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
    return data;
  }

  // ---------- this browser's draft (anonymous) ----------
  // localStorage is the visitor's own file: it can be missing, full,
  // disabled (private browsing throws on access), or hand-edited.
  // Anything we cannot read back as a draft counts as no draft — the
  // page must open either way.
  function cleanAssets(raw) {
    if (!Array.isArray(raw)) return [];
    const seen = new Set();
    const out = [];
    for (const entry of raw) {
      if (!entry || typeof entry !== "object") continue;
      const symbol = String(entry.symbol || "").trim().toUpperCase();
      const weight = Number(entry.weight);
      if (!TICKER_RE.test(symbol) || seen.has(symbol)) continue;
      if (!isFinite(weight) || weight < 0) continue;
      seen.add(symbol);
      out.push({ symbol, weight });
      if (out.length === MAX_ASSETS) break;
    }
    // the server says the same thing with a 400: an all-zero mix is not
    // a mix (explorer.views._clean_draft_assets)
    return out.some((a) => a.weight > 0) ? out : [];
  }

  function readLocal() {
    let raw;
    try { raw = localStorage.getItem(KEY); } catch { return null; }
    if (!raw) return null;
    let data;
    try { data = JSON.parse(raw); } catch { return null; }
    const assets = cleanAssets(data && data.assets);
    if (!assets.length) return null;
    return { assets, updated_at: (data && data.updated_at) || null };
  }

  function writeLocal(assets) {
    const payload = { assets, updated_at: new Date().toISOString() };
    try {
      localStorage.setItem(KEY, JSON.stringify(payload));
    } catch {
      throw new Error("This browser won't let us keep your mix — private " +
                      "browsing, or storage is full. It will be gone when " +
                      "you reload.");
    }
    return payload;
  }

  function clearLocal() {
    try { localStorage.removeItem(KEY); } catch { /* nothing to clear */ }
  }

  // ---------- import on sign-in ----------
  // Someone played anonymously, then signed in: their mix is sitting in
  // this browser and their account's draft is empty. Move it over, once,
  // silently. If the account already has a draft, that one wins and the
  // browser copy is dropped — no merge, no dialog, no surprise overwrite
  // of something they built while signed in.
  //
  // Resolves to true only when the account's draft was actually populated
  // from the browser, which is the one case a page rendered against an
  // empty server draft is now showing the wrong thing.
  let importing = null;

  function importLocal() {
    if (importing) return importing;          // one-shot per page load
    importing = (async () => {
      if (!authenticated) return false;
      const local = readLocal();
      if (!local) return false;
      try {
        const server = await apiGet();
        if (server.assets && server.assets.length) {
          clearLocal();                        // the account's draft wins
          return false;
        }
        await apiPut(local.assets);
        clearLocal();
        return true;
      } catch {
        // keep the browser copy and try again next load rather than
        // losing the mix to one failed request
        return false;
      }
    })();
    return importing;
  }

  // ---------- the adapter ----------
  async function get() {
    await importLocal();
    if (authenticated) return apiGet();
    return readLocal() || { assets: [], updated_at: null };
  }

  async function put(assets) {
    if (authenticated) return apiPut(assets);
    return writeLocal(assets);
  }

  return { KEY, authenticated, ready: importLocal, get, put };
})();
