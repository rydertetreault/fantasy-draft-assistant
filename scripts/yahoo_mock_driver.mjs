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

// REAL room = exactly /f1/384341/draft with no "mock" anywhere. Yahoo
// namespaces the user's mocks UNDER the league path (/f1/384341/mock_waiting),
// so the guard must be surgical, not prefix-based.
const isRealRoom = (u) => /\/f1\/384341\/draft(\b|$|[/?#])/.test(u) && !/mock/i.test(u);
let page = null;
while (!page) {
  page = browser.contexts().flatMap((c) => c.pages()).find((p) =>
    /yahoo\.com/i.test(p.url()) && (/mock/i.test(p.url()) || /draft/i.test(p.url())) && !isRealRoom(p.url())) || null;
  if (!page) await new Promise((r) => setTimeout(r, 700));
}
log(`room: ${page.url().slice(0, 110)}`);
if (isRealRoom(page.url())) { log("REFUSED: real league room"); process.exit(3); }

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

try { const saved = JSON.parse((await import("node:fs")).readFileSync(D("our_picks.json"), "utf8")); if (saved.room === page.url()) { var _op = saved.picks; } } catch {}
let ourPicks = (typeof _op !== "undefined" ? _op : []), clickedThisTurn = false, lastSig = "", slot = SLOT, slotSource = "env-default", lastAnnounced = 0, lastAnnouncedAt = 0;
while (ourPicks.length < ROUNDS) {
  let s;
  try { s = await page.evaluate(STATE); } catch (e) { log(`eval err: ${String(e).slice(0, 70)}`); await new Promise((r) => setTimeout(r, 1500)); continue; }
  // self-correcting slot: Yahoo's own "your turn - Nth pick" is authoritative
  if (s.announcedPick > 0 && s.announcedPick !== lastAnnounced) {
    lastAnnounced = s.announcedPick; lastAnnouncedAt = Date.now();
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
  // lobby shows a persistent "YOUR TURN - 9TH PICK" label => banner alone is
  // NOT proof we are on the clock. Require live rows + enabled Draft buttons.
  const onTurn = s.titleTurn && s.rows.length > 0;
  if (!onTurn) { clickedThisTurn = false; await new Promise((r) => setTimeout(r, 500)); continue; }
  if (clickedThisTurn) { await new Promise((r) => setTimeout(r, 600)); continue; }
  if (!s.rows.length) { await new Promise((r) => setTimeout(r, 400)); continue; }

  // turn index from the room's own roster count "(N/15)" — restart-proof,
  // autopick-proof. Ordinal announcement (49TH PICK) is primary when present.
  const cm = /\((\d+)\/\d+\)/.exec(s.rosterText || "");
  const haveCount = cm ? parseInt(cm[1], 10) : ourPicks.length;
  const fromCount = ((k) => { const r = k + 1; return r % 2 === 1 ? (r - 1) * TEAMS + slot : r * TEAMS - slot + 1; })(haveCount);
  const annFresh = Date.now() - lastAnnouncedAt < 15000;
  const overall = (annFresh && lastAnnounced > 0 && lastAnnounced >= fromCount - TEAMS && lastAnnounced <= fromCount + TEAMS) ? lastAnnounced : fromCount;
  writeFileSync(D("visible.json"), JSON.stringify(s.rows));
  writeFileSync(D("hist.txt"), "");
  writeFileSync(D("roster.txt"), s.rosterText || "");
  let choice;
  try {
    choice = JSON.parse(execFileSync(join(repo, ".venv/bin/python"),
      [join(repo, "scripts/ctx_choose.py"), "--history", D("hist.txt"), "--visible", D("visible.json"),
       "--exclude", ourPicks.join(","), "--roster", ourPicks.join(","), "--overall", String(overall),
       "--roster-file", D("roster.txt"), "--slot", String(slot), "--teams", String(TEAMS), "--league", 999999, "--teamid", "6"],
      { encoding: "utf8", timeout: 10000, env: { ...process.env, BOARD_CSV: join(repo, "data/yahoo/board.csv"), CONFIG_YAML: join(repo, "config.yahoo.yaml") } }).trim().split("\n").pop());
  } catch (e) { log(`chooser err: ${String(e).slice(0, 100)}`); await new Promise((r) => setTimeout(r, 400)); continue; }
  if (choice.error) { log(`chooser: ${choice.error}`); await new Promise((r) => setTimeout(r, 400)); continue; }
  if (choice.wanted && choice.wanted.gain > 5) {
    const FILTER = { QB: "Quarterbacks", RB: "Running Backs", WR: "Wide Receivers", TE: "Tight Ends", K: "Kickers", DST: "Defen", DEF: "Defen" };
    const label = FILTER[choice.wanted.pos] || null;
    if (label) {
      log(`filter-click: want ${choice.wanted.pos} (${choice.wanted.player}, gain ${choice.wanted.gain}) -> "${label}"`);
      await page.evaluate((lbl) => {
        const el = Array.from(document.querySelectorAll("button, a, [role=tab], [role=button], li, span")).find((e) =>
          (e.innerText || "").trim().toLowerCase().startsWith(lbl.toLowerCase()) && (e.innerText || "").length < 30);
        if (el) el.click();
      }, label).catch(() => null);
      const before = JSON.stringify(s.rows);
      let s3 = null;
      for (let w = 0; w < 8; w++) {
        await new Promise((r) => setTimeout(r, 350));
        s3 = await page.evaluate(STATE).catch(() => null);
        if (s3 && s3.rows.length && JSON.stringify(s3.rows) !== before) break;
      }
      if (s3 && s3.rows.length) { writeFileSync(D("visible.json"), JSON.stringify(s3.rows)); }
      else { log("filter-click: rows never refreshed — keeping pre-filter list"); }
      try {
        choice = JSON.parse(execFileSync(join(repo, ".venv/bin/python"),
          [join(repo, "scripts/ctx_choose.py"), "--history", D("hist.txt"), "--visible", D("visible.json"),
           "--exclude", ourPicks.join(","), "--roster", ourPicks.join(","), "--roster-file", D("roster.txt"),
           "--overall", String(overall), "--slot", String(slot), "--teams", String(TEAMS),
           "--league", "999999", "--teamid", "6"],
          { encoding: "utf8", timeout: 10000, env: { ...process.env, BOARD_CSV: join(repo, "data/yahoo/board.csv"), CONFIG_YAML: join(repo, "config.yahoo.yaml") } }).trim().split("\n").pop());
      } catch (e) { log(`chooser err after filter: ${String(e).slice(0, 90)}`); }
    }
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
        writeFileSync(D("our_picks.json"), JSON.stringify({ room: page.url(), picks: ourPicks }));
        log(`VERIFIED pick #${ourPicks.length}: ${choice.playerName} (${choice.pos}) via ${res.how} | ${Date.now() - t0}ms`);
      }
      else log(`UNVERIFIED after ${res.how} click: ${choice.playerName} — one submission max, holding`);
    } else {
      log(`click failed: ${res.why || JSON.stringify(res)} — re-choosing next cycle`);
    }
  } catch (e) { log(`click err: ${String(e).slice(0, 120)}`); }
  await new Promise((r) => setTimeout(r, 500));
}
log(`driver done: ${ourPicks.length} picks`);
