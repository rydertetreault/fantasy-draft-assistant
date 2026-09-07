// ESPN LIVE DRIVER — RoughRydas real room ONLY (league 1851947).
// Cloned 2026-09-06 from espn_mock_driver.mjs after it passed 16/16 (mock #2,
// room 1620892781, K+DST landed r15/16). Same loop; differences:
//   * latches ONLY the real room (leagueId in URL must equal the grant's league)
//   * --grant-file REQUIRED: alias roughrydas, league 1851947, exact
//     draft_session_id, validity window re-checked before EVERY click
//   * DRY-RUN by default (actuate locates the row, clicks nothing);
//     --live enables clicking
// Usage: TEAMS=10 node scripts/espn_live_driver.mjs --grant-file /tmp/grant.json [--live]
import { chromium } from "playwright";
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const ARGS = process.argv.slice(2);
const LIVE = ARGS.includes("--live");
const gi = ARGS.indexOf("--grant-file");
if (gi === -1 || !ARGS[gi + 1]) { console.error("REFUSED: --grant-file is required"); process.exit(2); }
const GRANT_PATH = ARGS[gi + 1];
const EXPECT = { alias: "roughrydas", league: 1851947, team: 1, session: "1851947-2026-1788739200000" };
function loadGrant() {
  let g; try { g = JSON.parse(readFileSync(GRANT_PATH, "utf8")); } catch { return { err: "grant unreadable" }; }
  if (String(g.alias || "").trim().toLowerCase() !== EXPECT.alias) return { err: `grant alias ${g.alias} != ${EXPECT.alias}` };
  if (g.league_id !== EXPECT.league) return { err: `grant league ${g.league_id} != ${EXPECT.league}` };
  if (g.draft_session_id !== EXPECT.session) return { err: `grant session ${g.draft_session_id} != ${EXPECT.session}` };
  const now = Date.now();
  if (!(g.issued_at_ms <= now && now < g.expires_at_ms)) return { err: "grant not currently valid (window)" };
  return { ok: true };
}
{ const g = loadGrant(); if (g.err) { console.error(`REFUSED: ${g.err}`); process.exit(3); } }
const TEAMS = parseInt(process.env.TEAMS || "12", 10);
const repo = fileURLToPath(new URL("..", import.meta.url));
const D = (f) => join(repo, "data", "roughrydas", "live", f);
mkdirSync(D(""), { recursive: true });
const log = (m) => { const l = `${new Date().toISOString()} ${m}`; console.log(l); appendFileSync(D("live_driver.log"), l + "\n"); };

const browser = await chromium.connectOverCDP("http://localhost:9222");
log(`LIVE DRIVER armed (${LIVE ? "LIVE — will click" : "DRY-RUN — no clicks"}): probing for the REAL room league=${EXPECT.league}`);

// ---- wait for the room ----------------------------------------------------
let page = null, leagueId = 0, teamId = 0;
while (!page) {
  for (const p of browser.contexts().flatMap((c) => c.pages())) {
    let u; try { u = new URL(p.url()); } catch { continue; }
    if (u.protocol !== "https:" || !/(^|\.)espn\.com$/i.test(u.hostname)) continue;
    if (!/^\/football\/draft$/i.test(u.pathname)) continue;
    const lid = parseInt(u.searchParams.get("leagueId") || "0", 10);
    const tid = parseInt(u.searchParams.get("teamId") || "0", 10);
    if (lid !== EXPECT.league || tid !== EXPECT.team) { continue; } // ONLY our real room
    page = p; leagueId = lid; teamId = tid;
    break;
  }
  if (!page) await new Promise((r) => setTimeout(r, 700));
}
log(`room: league=${leagueId} teamId=${teamId}`);

// ---- raw CDP websocket tap ------------------------------------------------
try {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  cdp.on("Network.webSocketFrameReceived", ({ response }) => {
    const d = response?.payloadData || "";
    appendFileSync(D("ws_frames.jsonl"), JSON.stringify({ t: Date.now(), rx: d.slice(0, 2000) }) + "\n");
  });
  cdp.on("Network.webSocketCreated", ({ url }) => log(`WS CREATED: ${url.slice(0, 90)}`));
  log("raw CDP Network tap enabled");
} catch (e) { log(`CDP tap failed (non-fatal): ${String(e).slice(0, 100)}`); }

// ---- state extraction -----------------------------------------------------
const STATE = () => {
  const t = (el) => (el ? (el.innerText || "").replace(/\s+/g, " ").trim() : "");
  const rows = Array.from(document.querySelectorAll("div.public_fixedDataTableRow_main")).filter(
    (r) => { const b = r.querySelector("button.Button--draft"); return b && !b.disabled; }
  );
  return {
    pickArea: t(document.querySelector("[class*=pickArea]")).slice(0, 160),
    round: t(document.querySelector("[class*=clock__label]")),
    clock: t(document.querySelector("[class*=clock__content]")),
    visible: rows.slice(0, 30).map((r) => t(r).slice(0, 70)),
    histText: t(document.querySelector("[class*=pick-history]")).slice(0, 5000),
  };
};

// ---- drafted tracking via disappearance -----------------------------------
const draftedLog = []; // ordered names, best-effort
let prevTop = [];
function trackDisappearance(visible) {
  const nowNames = visible.map((v) => v.toLowerCase());
  for (const name of prevTop) {
    if (!nowNames.some((n) => n.includes(name)) && !draftedLog.includes(name)) draftedLog.push(name);
  }
  // remember the *names* of the current top rows (strip row decoration)
  prevTop = visible.slice(0, 10).map((v) => v.toLowerCase()
    .replace(/^\d+\s*/, "").replace(/\s+(qb|rb|wr|te|k|d\/st|dst)\s.*$/, "").trim()).filter((n) => n.length > 3);
}

// ---- LIST-SWITCH (2026-09-06, real-room recon): ESPN's position filter is a
// <select class="dropdown__select"> with options All Pos./QB/RB/WR/TE/FLEX/D/ST/K.
// The room list is on "My Rankings" so K/D/ST (tail of our list) are never in
// the visible top-30 late -> chooser stalls (mock #3 pattern). On repeated
// chooser failure we reset to All Pos., then switch to the missing K/D/ST.
const boardPos = new Map();
try {
  for (const line of readFileSync(process.env.BOARD_CSV, "utf8").split("\n").slice(1)) {
    const c = line.split(","); if (c.length > 2) boardPos.set(c[0], c[2].replace("D/ST", "DST"));
  }
} catch {}
let curFilter = "All Pos.", chooserFails = 0;
async function setPosFilter(label) {
  if (label === curFilter) return;
  const r = await page.evaluate((label) => {
    const sel = [...document.querySelectorAll("select.dropdown__select")]
      .find((s) => [...s.options].some((o) => o.text === "All Pos.") && !s.name.startsWith("fake-"));
    if (!sel) return "no select";
    const opt = [...sel.options].find((o) => o.text === label); if (!opt) return "no option " + label;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(sel, opt.value);
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    return "set " + label;
  }, label).catch((e) => "err " + String(e).slice(0, 60));
  log(`LIST-SWITCH -> ${label}: ${r}`);
  if (r.startsWith("set")) curFilter = label;
  await new Promise((r) => setTimeout(r, 900));
}
function missingRequired() {
  const have = new Set(ourPicks.map((n) => boardPos.get(n) || (/D\/ST$/.test(n) ? "DST" : "")));
  const out = []; if (!have.has("DST")) out.push("D/ST"); if (!have.has("K")) out.push("K"); return out;
}

async function onChooserFail(roundNo) {
  chooserFails++;
  // ~3 cycles (~1.5s) of nothing: make sure the list is unfiltered.
  if (chooserFails === 4) await setPosFilter("All Pos.");
  // still nothing: late in the draft, show the required slot we still lack.
  if (chooserFails >= 8 && (chooserFails - 8) % 6 === 0) {
    const need = missingRequired();
    const roundsLeft = 16 - (roundNo || 0) + 1;
    if (need.length && roundsLeft <= need.length + 1) {
      const idx = Math.floor((chooserFails - 8) / 6) % need.length;
      await setPosFilter(need[idx]);
    } else if (chooserFails % 12 === 0) await setPosFilter("All Pos.");
  }
  await new Promise((r) => setTimeout(r, 400));
}

// ---- main loop ------------------------------------------------------------
let lastPickArea = "", ourPicks = [], clickedThisTurn = false, done = false;
let nextR = 0, nextP = 0, lastAutopickFix = 0; // our next turn, from ESPN's own announcement
try {
  const saved = JSON.parse(readFileSync(D("our_picks.json"), "utf8"));
  if (saved && saved.league === leagueId && Array.isArray(saved.picks)) {
    ourPicks = saved.picks; log(`resumed roster (league ${leagueId}): ${ourPicks.join(", ")}`);
  } else log("stale roster file for a different league — starting fresh");
} catch {}
log(`chooser: contextual engine (slot-adjusted VORP), teams=${TEAMS}`);
while (!done) {
  let s;
  try { s = await page.evaluate(STATE); } catch (e) { log(`evaluate err: ${String(e).slice(0, 80)}`); await new Promise(r => setTimeout(r, 800)); continue; }
  trackDisappearance(s.visible);
  if (s.pickArea !== lastPickArea) { log(`pickArea: ${s.pickArea} | ${s.round} ${s.clock}`); lastPickArea = s.pickArea; }
  if (/draft is complete|draft complete/i.test(s.pickArea)) { log("DRAFT COMPLETE"); break; }
  // learn our exact next slot from "You're on the clock in: N Picks Round R, Pick P"
  const ann = /Round (\d+), Pick (\d+)/i.exec(s.pickArea);
  if (ann) { nextR = parseInt(ann[1], 10); nextP = parseInt(ann[2], 10); }

  // AUTOPICK RECOVERY (mock #3, 2026-09-06): a chooser stall for a full clock
  // flips ESPN into autopick for ALL remaining rounds. Click DISABLE AUTOPICK
  // (throttled) so the driver regains control for the next turn.
  if (/disable autopick/i.test(s.pickArea) && Date.now() - lastAutopickFix > 5000) {
    lastAutopickFix = Date.now();
    if (typeof LIVE !== "undefined" && !LIVE) { log("AUTOPICK ON — DRY-RUN would click DISABLE AUTOPICK"); }
    else {
      try {
        const btn = page.locator('button:has-text("Disable Autopick"), button:has-text("DISABLE AUTOPICK")').first();
        if (await btn.count()) { await btn.click({ timeout: 2000 }); log("AUTOPICK ON — clicked DISABLE AUTOPICK"); }
        else log("AUTOPICK ON — no disable button found");
      } catch (e) { log(`AUTOPICK disable click failed: ${String(e).slice(0, 100)}`); }
    }
  }
  const onClock = /you are on the clock/i.test(s.pickArea);
  if (!onClock) { clickedThisTurn = false; await new Promise((r) => setTimeout(r, 400)); continue; }
  if (clickedThisTurn) { await new Promise((r) => setTimeout(r, 500)); continue; } // one click max: waiting on verify

  // our turn: exact overall/slot from the last announcement when we have it
  let overall, slot;
  if (nextR > 0) {
    overall = (nextR - 1) * TEAMS + nextP;
    slot = nextR % 2 === 1 ? nextP : TEAMS - nextP + 1;
  } else {
    overall = draftedLog.length + 1; // first-turn fallback (round 1: slot = pick)
    slot = ((o, n) => { const r = Math.floor((o - 1) / n), i = (o - 1) % n; return r % 2 === 0 ? i + 1 : n - i; })(overall, TEAMS);
  }
  // OWNER FORCE-PICK peek (env FORCE_NAME/FORCE_POS/FORCE_FROM): the table
  // virtualizes ~15 rows, so a deep-ranked target is never "visible" on All
  // Pos. Flip to his position for one look; if he is not rendered, flip back.
  if (process.env.FORCE_NAME && nextR >= parseInt(process.env.FORCE_FROM || "1", 10)
      && !ourPicks.includes(process.env.FORCE_NAME) && !draftedLog.includes(process.env.FORCE_NAME.toLowerCase())
      && !s.histText.toLowerCase().includes(process.env.FORCE_NAME.toLowerCase())) {
    await setPosFilter(process.env.FORCE_POS || "RB");
    const s3 = await page.evaluate(STATE).catch(() => null);
    if (s3 && s3.visible.some((v) => v.includes(process.env.FORCE_NAME))) { s = s3; log(`FORCE target ${process.env.FORCE_NAME} is visible on ${curFilter}`); }
    else { log(`FORCE target ${process.env.FORCE_NAME} not rendered on ${curFilter} — back to All Pos.`); await setPosFilter("All Pos."); const s4 = await page.evaluate(STATE).catch(() => null); if (s4) s = s4; }
  }
  writeFileSync(D("hist.txt"), draftedLog.join("\n") + "\n" + s.histText);
  writeFileSync(D("visible.json"), JSON.stringify(s.visible));
  let choice;
  try {
    choice = JSON.parse(execFileSync(join(repo, ".venv/bin/python"),
      [join(repo, "scripts/ctx_choose.py"), "--history", D("hist.txt"), "--visible", D("visible.json"),
       "--exclude", ourPicks.join(","), "--roster", ourPicks.join(","), "--overall", String(overall), "--slot", String(slot),
       "--teams", String(TEAMS), "--league", String(leagueId), "--teamid", String(teamId)],
      { encoding: "utf8", timeout: 10000 }).trim().split("\n").pop());
  } catch (e) { log(`chooser err: ${String(e.stderr || e).replace(/\s+/g, " ").slice(-200)}`); await onChooserFail(nextR); continue; }
  if (choice.error) { log(`chooser: ${choice.error}`); await onChooserFail(nextR); continue; }
  chooserFails = 0;

  const t0 = Date.now();
  log(`OUR TURN (overall~${overall} slot~${slot}) clock=${s.clock} -> ${choice.playerName} (${choice.pos}) why=${JSON.stringify(choice.why || {})}`);
  { const g = loadGrant(); if (g.err) { log(`GRANT REFUSED before click: ${g.err} — holding, human takes over`); clickedThisTurn = true; continue; } }
  if (!LIVE) {
    try {
      const out = execFileSync("node", [join(repo, "scripts/espn_actuate.mjs"),
        JSON.stringify({ playerId: choice.playerId, playerName: choice.playerName, leagueId, teamId }),
        "--grant-file", GRANT_PATH], { encoding: "utf8", timeout: 15000 });
      log(`DRY-RUN would click: ${out.trim().split("\n").pop()}`);
    } catch (e) { log(`DRY-RUN actuate refused: ${String(e.stderr || e).slice(0, 140)}`); }
    clickedThisTurn = true; continue;
  }
  try {
    const out = execFileSync("node", [join(repo, "scripts/espn_actuate.mjs"),
      JSON.stringify({ playerId: choice.playerId, playerName: choice.playerName, leagueId, teamId }),
      "--grant-file", GRANT_PATH, "--live"], { encoding: "utf8", timeout: 15000 });
    clickedThisTurn = true;
    log(`actuate LIVE ok (${Date.now() - t0}ms): ${out.trim().split("\n").pop()}`);
    // verify: pickArea leaves on-clock state
    let verified = false;
    for (let i = 0; i < 16; i++) {
      await new Promise((r) => setTimeout(r, 500));
      const s2 = await page.evaluate(STATE).catch(() => null);
      if (s2 && !/you are on the clock/i.test(s2.pickArea)) { verified = true; break; }
    }
    if (verified) {
      ourPicks.push(choice.playerName);
      writeFileSync(D("our_picks.json"), JSON.stringify({ league: leagueId, picks: ourPicks }));
      if (!draftedLog.includes(choice.playerName.toLowerCase())) draftedLog.push(choice.playerName.toLowerCase());
      log(`VERIFIED our pick #${ourPicks.length}: ${choice.playerName} (${choice.pos}) | total ${Date.now() - t0}ms`);
      chooserFails = 0; await setPosFilter("All Pos.");
    } else log(`UNVERIFIED: ${choice.playerName} — one click max, holding`);
  } catch (e) {
    // actuate refused (exit != 0) => no click happened; next cycle re-chooses
    log(`actuate refused: ${String(e.stderr || e).slice(0, 140)} — re-choosing next cycle`);
  }
  await new Promise((r) => setTimeout(r, 400));
}
log("live driver exiting");
process.exit(0);
