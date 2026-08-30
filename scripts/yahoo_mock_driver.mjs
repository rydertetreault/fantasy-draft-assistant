// Yahoo MOCK snake-draft driver. MOCK ROOMS ONLY — hard-refuses the real
// league room (/f1/384341). Self-discovering DOM: no prior selector map
// needed. Turn overalls come from slot math (SLOT/TEAMS env), not from
// Yahoo's UI. Chooser = ctx_choose.py with the half-PPR board + yahoo config.
//
// Click path handles both Yahoo styles:
//   (a) per-row "Draft" button inside the matched player row
//   (b) two-step: click row (selection, harmless) -> a "Draft"/"Draft Player"
//       button appears/enables -> ONE submission click, then verify.
import { chromium } from "playwright";
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const SLOT = parseInt(process.env.SLOT || "6", 10);
const TEAMS = parseInt(process.env.TEAMS || "10", 10);
const ROUNDS = parseInt(process.env.ROUNDS || "15", 10);
const repo = fileURLToPath(new URL("..", import.meta.url));
mkdirSync(join(repo, "data", "yahoo"), { recursive: true });
const D = (f) => join(repo, "data", "yahoo", f);
const log = (m) => { const l = `${new Date().toISOString()} ${m}`; console.log(l); appendFileSync(D("mock_driver.log"), l + "\n"); };
const ourOverall = (k) => { const r = k + 1; return r % 2 === 1 ? (r - 1) * TEAMS + SLOT : r * TEAMS - SLOT + 1; };

const { execFileSync } = await import("node:child_process");
const browser = await chromium.connectOverCDP(process.env.BROWSER_CDP_URL || "http://localhost:9222");
log(`yahoo mock driver armed: slot ${SLOT}/${TEAMS}, our overalls ${[0,1,2,3].map(ourOverall).join(",")}...`);

// REAL room guard, TWO forms (owner safety rule): the classic
// /f1/384341/draft page AND draftclient/f1/384341/<slot> — the league id
// inside the draftclient namespace IS the real room. Mocks get their own
// mock ids there (draftclient/f1/10171677/3), so this stays surgical.
const isRealRoom = (u) => (/\/f1\/384341\/draft(\b|$|[/?#])/.test(u) && !/mock/i.test(u)) || /\/draftclient\/f1\/384341(\b|[/?#])/.test(u);
const urlOf = (p) => { try { return p.url(); } catch { return ""; } };
// OWNER-CONFIRMED (mock #3): entering the room does NOT open a new browser
// tab — the existing page UNHOOKS (its target dies) and a NEW page target
// appears in place. A held Page handle silently goes stale, so room
// discovery re-scans ALL targets every cycle: prefer a live draftclient,
// else a waiting room; never the lobby, never the real room.
const findRoom = () => {
  const cand = browser.contexts().flatMap((c) => c.pages()).filter((p) => {
    const u = urlOf(p);
    return /yahoo\.com/i.test(u) && !isRealRoom(u) && !/mock_lobby/i.test(u) && (/draftclient/i.test(u) || /mock/i.test(u) || /draft/i.test(u));
  });
  return cand.find((p) => /draftclient/i.test(urlOf(p))) || cand[0] || null;
};
// draftclient URL ends in OUR SLOT (mock #2: .../10171133/7 = slot 7;
// mock #3: .../10171677/3 = slot 3) — instant-start rooms have no waiting
// room label, so the URL is the primary slot source.
const slotFromUrl = (u) => { const m = /\/draftclient\/f1\/\d+\/(\d{1,2})(\b|[/?#])/.exec(u || ""); const s = m ? parseInt(m[1], 10) : 0; return s >= 1 && s <= TEAMS ? s : 0; };
let page = null;
while (!page) { page = findRoom(); if (!page) await new Promise((r) => setTimeout(r, 500)); }
log(`room: ${urlOf(page).slice(0, 110)}`);

const STATE = () => {
  const t = (el) => (el ? (el.innerText || "").replace(/\s+/g, " ").trim() : "");
  const leaf = Array.from(document.querySelectorAll("*")).filter((e) => e.children.length === 0);
  const clock = (leaf.find((e) => /^\d{1,2}:\d\d$/.test((e.innerText || "").trim())) || {}).innerText || null;
  const turnEl = Array.from(document.querySelectorAll("*")).find((e) =>
    (e.innerText || "").length < 150 && /you'?re on the clock|your pick!|make your pick|you are on the clock|your turn/i.test(e.innerText || ""));
  // Yahoo announces our upcoming pick: "YOUR TURN - 28TH PICK" / "pick #6" —
  // parse it so the slot/overall never depend on a guessed env var.
  // ONLY the ordinal label counts ("YOUR TURN - 32ND PICK"); countdowns like
  // "12 picks until your turn" must never be parsed as a pick number.
  let announcedPick = 0;
  const ann = Array.from(document.querySelectorAll("*")).find((e) => {
    const s = (e.innerText || "");
    return s.length < 120 && /your turn/i.test(s) && !/until/i.test(s) && /(\d{1,3})(st|nd|rd|th)\s*pick/i.test(s);
  });
  if (ann) {
    const m = /(\d{1,3})(st|nd|rd|th)\s*pick/i.exec(ann.innerText || "");
    if (m) announcedPick = parseInt(m[1], 10) || 0;
  }
  // Yahoo draftclient uses atomic/hashed CSS -> derive rows FROM the strict
  // per-player "Draft" buttons: row = smallest ancestor with a position marker.
  const draftBtns = Array.from(document.querySelectorAll("button")).filter((b) => /^draft( player)?$/i.test((b.innerText || "").trim()));
  const rowOf = (b) => {
    let e = b;
    for (let i = 0; i < 6 && e.parentElement; i++) {
      e = e.parentElement;
      const s = (e.innerText || "").replace(/\s+/g, " ");
      if (/\b(QB|RB|WR|TE|K|DEF)\b/.test(s) && s.length < 300) return s;
    }
    return null;
  };
  const rows = draftBtns.filter((b) => !b.disabled).map(rowOf).filter(Boolean);
  // title is the cleanest on-clock signal: "YOUR TURN, DRAFT NOW | ..."
  const titleTurn = /your turn, draft now/i.test(document.title || "");
  const rosterEl = Array.from(document.querySelectorAll("*")).find((e) => /^YOUR TEAM/i.test((e.innerText || "").trim()) && (e.innerText || "").length < 800);
  return {
    clock, turnText: turnEl ? t(turnEl).slice(0, 100) : null, announcedPick, titleTurn,
    rosterText: rosterEl ? t(rosterEl).slice(0, 700) : "",
    rows: rows.slice(0, 40).map((r) => r.slice(0, 90)),
    draftBtnCount: draftBtns.length,
    enabledDraftBtnCount: draftBtns.filter((b) => !b.disabled).length,
  };
};

const CLICK = (name, abbrev) => {
  const rows = Array.from(document.querySelectorAll("tr, li, [class*=row i], [class*=player i]")).filter((e) => {
    const s = (e.innerText || "").toLowerCase();
    return (s.includes(name) || s.includes(abbrev)) && (e.innerText || "").length < 300;
  });
  if (!rows.length) return { ok: false, why: "no row matches " + abbrev };
  const row = rows[0];
  const inRow = Array.from(row.querySelectorAll("button")).find((b) => /^draft/i.test((b.innerText || "").trim()) && !b.disabled);
  if (inRow) { inRow.click(); return { ok: true, how: "row-button" }; }
  row.click(); // selection only — not a pick
  return { ok: false, why: "selected row, need second step", selected: true };
};
const CLICK2 = () => {
  const b = Array.from(document.querySelectorAll("button")).find((x) => /^draft( player)?$/i.test((x.innerText || "").trim()) && !x.disabled);
  if (!b) return { ok: false, why: "no enabled draft button after selection" };
  b.click(); return { ok: true, how: "two-step" };
};

try { const saved = JSON.parse((await import("node:fs")).readFileSync(D("our_picks.json"), "utf8")); if (saved.room === page.url()) { var _op = saved.picks; var _slot = saved.slot; } } catch {}
let ourPicks = (typeof _op !== "undefined" ? _op : []), clickedThisTurn = false, lastSig = "", slot = (typeof _slot === "number" && _slot >= 1 ? _slot : SLOT), slotSource = (typeof _slot === "number" && _slot >= 1 ? "persisted" : "env-default"), lastAnnounced = 0, lastHistAt = 0, lastHistLines = -1;
writeFileSync(D("hist.txt"), ""); // fresh room: scrape refills within ~12s
if (slotSource === "persisted") log(`slot restored: ${slot} (persisted from this room)`);
{ const uS = slotFromUrl(urlOf(page)); if (uS) { if (uS !== slot) log(`slot from room URL: ${uS} (was ${slot}/${slotSource})`); slot = uS; slotSource = "room URL"; } }
const normPos = (p) => String(p || "").toUpperCase().replace("D/ST", "DST");
const clockSecs = (c) => { const m = /^(\d{1,2}):(\d\d)$/.exec(c || ""); return m ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : -1; };
const runChooser = (overall) => {
  try {
    return JSON.parse(execFileSync(join(repo, ".venv/bin/python"),
      [join(repo, "scripts/ctx_choose.py"), "--history", D("hist.txt"), "--visible", D("visible.json"),
       "--exclude", ourPicks.join(","), "--roster", ourPicks.join(","), "--overall", String(overall),
       "--roster-file", D("roster.txt"), "--slot", String(slot), "--teams", String(TEAMS), "--league", "999999", "--teamid", "6"],
      { encoding: "utf8", timeout: 10000, env: { ...process.env, BOARD_CSV: join(repo, "data/yahoo/board.csv"), CONFIG_YAML: join(repo, "config.yahoo.yaml") } }).trim().split("\n").pop());
  } catch (e) { return { error: `exec: ${String(e).slice(0, 90)}` }; }
};
// List-switch with POSITION-VERIFIED refresh. Mock #7 DOM recon (live):
// Yahoo's position filter is a <select name="position-filter"> DROPDOWN
// (options by VALUE: pos=QB/RB/WR/TE/K/DEF, pos_type=All) — NOT clickable
// tabs. Every tab-click strategy in mocks #4-#7 silently did nothing.
// React selects need the native value setter + a bubbling change event.
// The search box ("Search for a player") filters by NAME and poisons the
// list for everything else — clear it before every switch, restore
// All Positions after every verified pick.
//   strat 0/1: select-dropdown by option VALUE (then by text prefix).
//   strat 2:   search box — LAST resort (mock #7: typed "broncos", list
//              went to 0 draft buttons and the turn was lost to autopick).
let usedListSwitch = false;
const POSVAL = { QB: "pos=QB", RB: "pos=RB", WR: "pos=WR", TE: "pos=TE", K: "pos=K", DST: "pos=DEF", DEF: "pos=DEF" };
const clearSearchBox = () => page.evaluate(() => {
  const inp = Array.from(document.querySelectorAll("input")).find((i) =>
    /search/i.test(i.placeholder || "") || /search/i.test(i.getAttribute("aria-label") || "") || /search/i.test(i.name || ""));
  if (!inp || !inp.value) return;
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  set.call(inp, ""); inp.dispatchEvent(new Event("input", { bubbles: true }));
}).catch(() => null);
const setPositionFilter = (val, textPrefix) => page.evaluate(([v, pref]) => {
  const sels = Array.from(document.querySelectorAll("select"));
  let sel = document.querySelector('select[name="position-filter"]') ||
    sels.find((s) => Array.from(s.options).some((o) => o.value === v || (pref && o.text.toLowerCase().startsWith(pref.toLowerCase()))));
  if (!sel) return false;
  const opt = Array.from(sel.options).find((o) => o.value === v) ||
    (pref ? Array.from(sel.options).find((o) => o.text.toLowerCase().startsWith(pref.toLowerCase())) : null);
  if (!opt) return false;
  const set = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value").set;
  set.call(sel, opt.value); sel.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}, [val, textPrefix || null]).catch(() => null);
const restoreAllPositions = async () => { await clearSearchBox(); await setPositionFilter("pos_type=All", "All Pos"); usedListSwitch = false; };
const switchListTo = async (posUp, strat, w) => {
  const tok = " " + posUp.toLowerCase().replace("dst", "def") + " ";
  await clearSearchBox(); // a poisoned search hides every list (mock #7)
  usedListSwitch = true;
  if (strat === 2) {
    if (!w || !w.player) return false;
    const text = posUp === "DST" ? (w.nickTok || w.cityTok || String(w.player).split(" ")[0]) : String(w.player).split(" ").pop();
    if (!text) return false;
    await page.evaluate((txt) => {
      const inp = Array.from(document.querySelectorAll("input")).find((i) =>
        /search/i.test(i.placeholder || "") || /search/i.test(i.getAttribute("aria-label") || "") || /search/i.test(i.name || ""));
      if (!inp) return false;
      const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      set.call(inp, txt); inp.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    }, text).catch(() => null);
  } else {
    const FILTER = { QB: "Quarterbacks", RB: "Running Backs", WR: "Wide Receivers", TE: "Tight Ends", K: "Kickers", DST: "Team Defen", DEF: "Team Defen" };
    const ok = await setPositionFilter(POSVAL[posUp] || "", strat === 1 ? (FILTER[posUp] || null) : null);
    if (!ok) { log(`list-switch: no position-filter select found for ${posUp}`); return false; }
  }
  const min = strat === 2 ? 1 : 2;
  for (let i = 0; i < 8; i++) {
    await new Promise((r) => setTimeout(r, 350));
    const s3 = await page.evaluate(STATE).catch(() => null);
    if (!s3 || !s3.rows.length) continue;
    const n = s3.rows.filter((r) => (" " + r.replace(/\s+/g, " ").toLowerCase() + " ").includes(tok)).length;
    if (n >= min) { writeFileSync(D("visible.json"), JSON.stringify(s3.rows)); log(`list-switch VERIFIED: ${n} ${posUp} row(s) via strategy ${strat}`); return true; }
  }
  log(`list-switch NOT verified for ${posUp} (strategy ${strat})`);
  return false;
};
while (ourPicks.length < ROUNDS) {
  // room hop: if our handle is stale/non-room and a live draftclient target
  // exists, jump to it NOW (instant-start rooms unhook the old page without
  // opening a tab — waiting for an eval error costs picks).
  if (!/draftclient/i.test(urlOf(page))) {
    const np = findRoom();
    if (np && np !== page && /draftclient/i.test(urlOf(np))) {
      page = np; clickedThisTurn = false;
      log(`room hop: ${urlOf(page).slice(0, 110)}`);
      const uS = slotFromUrl(urlOf(page));
      if (uS) { if (uS !== slot) log(`slot from room URL: ${uS} (was ${slot}/${slotSource})`); slot = uS; slotSource = "room URL"; }
    }
  }
  let s;
  try { s = await page.evaluate(STATE); } catch (e) {
    log(`eval err: ${String(e).slice(0, 70)}`);
    await new Promise((r) => setTimeout(r, 800)); continue; // hop check re-scans next cycle
  }
  // USER-CONFIRMED (mock #2): mid-draft, the ordinal next to the countdown
  // is the draft's CURRENT round/pick — NOT our pick. It is only meaningful
  // as OUR pick in the pre-draft waiting room ("YOUR TURN - 7TH PICK").
  // So: slot inference ONLY before our first pick and only off-turn.
  if (slotSource !== "room URL" && ourPicks.length === 0 && !s.titleTurn && s.announcedPick > 0 && s.announcedPick !== lastAnnounced) {
    lastAnnounced = s.announcedPick;
    const o = s.announcedPick;
    const r = Math.ceil(o / TEAMS);
    const inferred = r % 2 === 1 ? o - (r - 1) * TEAMS : r * TEAMS - o + 1;
    if (inferred >= 1 && inferred <= TEAMS && inferred !== slot) {
      slot = inferred; slotSource = `announced pick ${o}`;
      log(`slot corrected: ${slot} (${slotSource})`);
    }
  }
  const sig = `${s.turnText}|${s.clock}|${s.rows.length}|${s.enabledDraftBtnCount}`;
  if (sig !== lastSig) { log(`state: turn=${JSON.stringify(s.turnText)} clock=${s.clock} rows=${s.rows.length} draftBtns=${s.enabledDraftBtnCount}/${s.draftBtnCount}`); lastSig = sig; }
  // Panel tabs (Queue|Picks|Players|Board|Results|...): after a pick the
  // panel can leave "Players", unmounting ALL Draft buttons → rows=0 on our
  // turn → autopick (mock #4 lost picks 15+26 this way). On the clock with
  // zero Draft buttons: click the Players tab to remount, then re-read.
  if (s.titleTurn && s.draftBtnCount === 0) {
    log("players-tab: on clock with 0 draft buttons — clicking Players tab + list reset");
    await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll("button, [role=tab], a, li")).find((e) => (e.innerText || "").trim() === "Players");
      if (b) b.click();
    }).catch(() => null);
    // mock #7: a poisoned search box ("broncos") also yields 0 buttons and
    // the tab remount can't fix it — clear search + All Positions too.
    await restoreAllPositions();
    await new Promise((r) => setTimeout(r, 400));
    continue;
  }
  // lobby shows a persistent "YOUR TURN - 9TH PICK" label => banner alone is
  // NOT proof we are on the clock. Require live rows + enabled Draft buttons.
  const onTurn = s.titleTurn && s.rows.length > 0;
  if (!onTurn) {
    clickedThisTurn = false;
    // OWNER DIRECTIVE: feed the chooser the REAL draft history so opponent
    // need/run/survival modeling works off actual picks. Off-turn only
    // (never burn clock / touch the panel while Draft buttons are live):
    // click "Picks", diff body text before/after (queue & roster lines are
    // in both snapshots so they can't leak in), restore "Players".
    if (Date.now() - lastHistAt > 12000 && /draftclient/i.test(urlOf(page))) {
      lastHistAt = Date.now();
      try {
        // force a known panel state FIRST (mock #5: the restore click was
        // failing silently, panel stayed on Picks, diffs only caught the
        // newest entries instead of the full list)
        await page.evaluate(() => {
          const t = Array.from(document.querySelectorAll("button, [role=tab], a, li")).find((e) => (e.innerText || "").trim() === "Players");
          if (t) t.click();
        }).catch(() => null);
        await new Promise((r) => setTimeout(r, 500));
        const before = await page.evaluate(() => document.body.innerText);
        const clicked = await page.evaluate(() => {
          const t = Array.from(document.querySelectorAll("button, [role=tab], a, li")).find((e) => (e.innerText || "").trim() === "Picks");
          if (t) { t.click(); return true; } return false;
        });
        if (clicked) {
          await new Promise((r) => setTimeout(r, 700));
          const after = await page.evaluate(() => document.body.innerText);
          const beforeSet = new Set(before.split("\n").map((x) => x.trim()));
          const added = after.split("\n").map((x) => x.trim()).filter((x) => x && !beforeSet.has(x));
          if (added.length) {
            writeFileSync(D("hist.txt"), added.join("\n").toLowerCase());
            if (added.length !== lastHistLines) { log(`picks-scrape: ${added.length} lines`); lastHistLines = added.length; }
          }
          await page.evaluate(() => {
            const t = Array.from(document.querySelectorAll("button, [role=tab], a, li")).find((e) => (e.innerText || "").trim() === "Players");
            if (t) t.click();
          }).catch(() => null);
        }
      } catch {}
    }
    await new Promise((r) => setTimeout(r, 500)); continue;
  }
  if (clickedThisTurn) { await new Promise((r) => setTimeout(r, 600)); continue; }
  if (!s.rows.length) { await new Promise((r) => setTimeout(r, 400)); continue; }

  // turn index from the room's own roster count "(N/15)" — restart-proof,
  // autopick-proof, and the ONLY trusted source for our overall (banner
  // ordinals are the draft's current position, never ours — mock #2).
  const cm = /\((\d+)\/\d+\)/.exec(s.rosterText || "");
  const haveCount = cm ? parseInt(cm[1], 10) : ourPicks.length;
  const overall = ((k) => { const r = k + 1; return r % 2 === 1 ? (r - 1) * TEAMS + slot : r * TEAMS - slot + 1; })(haveCount);
  writeFileSync(D("visible.json"), JSON.stringify(s.rows));
  // hist.txt NOT blanked here — it holds the last off-turn Picks scrape
  writeFileSync(D("roster.txt"), s.rosterText || "");
  let choice = runChooser(overall);
  if (choice.error) { log(`chooser: ${choice.error}`); await new Promise((r) => setTimeout(r, 400)); continue; }
  // trust the chooser's wanted signal: it already gates on gain>5 for
  // value-chasing AND fires gate-free when NOTHING at a required position
  // is visible (endgame K/DEF — mock #5 lost both to the old >5 re-check:
  // DST gain 4.87).
  if (choice.wanted) {
    const wpos = normPos(choice.wanted.pos);
    log(`filter-click: want ${choice.wanted.pos} (${choice.wanted.player}, gain ${choice.wanted.gain})`);
    let ok = await switchListTo(wpos, 0, choice.wanted);
    if (!ok) ok = await switchListTo(wpos, 1, choice.wanted);
    if (ok) {
      const c2 = runChooser(overall);
      if (c2.error) log(`chooser err after filter: ${c2.error}`);
      else choice = c2;
    } else log(`filter-click: switch to ${wpos} failed (both tab variants)`);
  }
  // ENDGAME HARD GATE (mock #6: the filter tab silently missed, "rows
  // changed" lied, and the fallback clicked Gainwell RB / Meyers WR over a
  // wanted DST -> 15 picks, ZERO K, ZERO DEF — owner: never again). While
  // rounds left <= empty required slots, clicking a non-required position
  // is FORBIDDEN; retry every list-switch strategy and only surrender to
  // the fallback pick when the clock forces it (autopick is still worse).
  const required = Array.isArray(choice.required_now) ? choice.required_now.map(normPos) : [];
  if (required.length && !required.includes(normPos(choice.pos))) {
    const w = choice.wanted && required.includes(normPos(choice.wanted.pos)) ? choice.wanted : null;
    const targetPos = w ? normPos(w.pos) : required[0];
    log(`ENDGAME GATE: refusing ${choice.pos} (required: ${required.join("/")}) — forcing ${targetPos}`);
    let fixed = false;
    for (let att = 0; att < 12 && !fixed; att++) {
      const sNow = await page.evaluate(STATE).catch(() => null);
      const secs = clockSecs(sNow ? sNow.clock : null);
      if (secs >= 0 && secs <= 8) { log(`ENDGAME GATE EMERGENCY: ${secs}s left — taking ${choice.playerName} over autopick`); break; }
      const strat = [0, 1, 2][att % 3];
      if (strat === 2 && !w) continue;
      if (!(await switchListTo(targetPos, strat, w))) continue;
      const c3 = runChooser(overall);
      if (!c3.error && required.includes(normPos(c3.pos))) { choice = c3; fixed = true; break; }
      if (w) {
        // list verified but chooser still off-required — click wanted directly
        choice = { playerName: w.player, pos: w.pos, playerId: 0, teamTok: w.teamTok || "", cityTok: w.cityTok || "", nickTok: w.nickTok || "",
                   required_now: required, why: { endgame_direct: `gate-forced ${targetPos}` } };
        fixed = true; break;
      }
    }
    if (fixed) log(`ENDGAME GATE: recovered -> ${choice.playerName} (${choice.pos})`);
  }

  const t0 = Date.now();
  const nm = choice.playerName.toLowerCase();
  const parts = choice.playerName.split(" ");
  const ab = (parts.length > 1 ? `${parts[0][0]}. ${parts.slice(1).join(" ")}` : nm).toLowerCase();
  log(`OUR TURN (overall ${overall}) clock=${s.clock} -> ${choice.playerName} (${choice.pos}) why=${JSON.stringify(choice.why || {})}`);
  try {
    const posTok = (choice.pos || "").toLowerCase().replace("dst", "def");
    const teamTok = (choice.teamTok || "").toLowerCase();
    const cityTok = (choice.cityTok || "").toLowerCase();
    const nickTok = (choice.nickTok || "").toLowerCase();
    let res = await page.evaluate(([n, a, pt, tt, ct, nt]) => { return (function(name, abbrev, pos, team, city, nick){
      const btns = Array.from(document.querySelectorAll("button")).filter((b) => /^draft( player)?$/i.test((b.innerText || "").trim()) && !b.disabled);
      for (const b of btns) {
        let e = b;
        for (let i = 0; i < 6 && e.parentElement; i++) {
          e = e.parentElement;
          const s = " " + (e.innerText || "").replace(/\s+/g, " ").toLowerCase() + " ";
          if (/ (qb|rb|wr|te|k|def) /.test(s) && s.length < 300) {
            let hit;
            if (pos === "def") {
              hit = s.includes(" def ") && ((city && s.includes(city)) || (nick && s.includes(nick)) || (team && s.includes(" " + team + " ")));
            } else {
              // name + position + TEAM all required: same-pos abbreviation
              // collisions (B. Robinson Atl vs Was) are settled by team.
              hit = (s.includes(name) || s.includes(abbrev)) && s.includes(" " + pos + " ") && (!team || s.includes(" " + team + " "));
            }
            if (hit) { b.click(); return { ok: true, how: "row-button" }; }
            break;
          }
        }
      }
      return { ok: false, why: "no row with name+pos+team for " + abbrev + " (" + pos + "/" + team + ")" };
    })(n, a, pt, tt, ct, nt); }, [nm, ab, posTok, teamTok, cityTok, nickTok]);
    if (!res.ok && res.selected) {
      await new Promise((r) => setTimeout(r, 400));
      res = await page.evaluate(CLICK2);
    }
    if (res.ok) {
      clickedThisTurn = true;
      // verify: turn banner clears
      const beforeCount = (() => { const m = /\((\d+)\/\d+\)/.exec(s.rosterText || ""); return m ? parseInt(m[1], 10) : -1; })();
      let verified = false;
      for (let i = 0; i < 16; i++) {
        await new Promise((r) => setTimeout(r, 500));
        const s2 = await page.evaluate(STATE).catch(() => null);
        if (!s2) continue;
        const m2 = /\((\d+)\/\d+\)/.exec(s2.rosterText || "");
        const afterCount = m2 ? parseInt(m2[1], 10) : -1;
        if (beforeCount >= 0 && afterCount > beforeCount) { verified = true; break; }
        if (beforeCount < 0 && !s2.titleTurn) { verified = true; break; } // fallback if count unreadable
      }
      if (verified) {
        ourPicks.push(choice.playerName);
        writeFileSync(D("our_picks.json"), JSON.stringify({ room: page.url(), picks: ourPicks, slot }));
        log(`VERIFIED pick #${ourPicks.length}: ${choice.playerName} (${choice.pos}) via ${res.how} | ${Date.now() - t0}ms`);
        if (usedListSwitch) await restoreAllPositions();
      }
      else log(`UNVERIFIED after ${res.how} click: ${choice.playerName} — one submission max, holding`);
    } else {
      log(`click failed: ${res.why || JSON.stringify(res)} — re-choosing next cycle`);
    }
  } catch (e) { log(`click err: ${String(e).slice(0, 120)}`); }
  await new Promise((r) => setTimeout(r, 500));
}
log(`driver done: ${ourPicks.length} picks`);
