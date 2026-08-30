// PROMOTED from tmp_mock_driver3 after passing 16/16 mock validation 2026-08-30.
// MOCK ROOMS ONLY — real-draft wiring goes through the runner + grant gates.
// Warm mock-draft driver v3 (untracked rehearsal helper). MOCK ROOMS ONLY.
// Fixes vs v2: (1) RAW CDP Network tap — page.on("websocket") misses sockets
// opened before attach; Network.webSocketFrameReceived does not. (2) drafted
// tracking via top-row DISAPPEARANCE as workhorse (ws parse is best-effort
// enrichment). (3) NO-STALL turn loop: chooser only ever returns visible
// candidates; 400ms cycles; one LIVE click max per turn.
import { chromium } from "playwright";
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const REAL_IDS = ["305025860", "2144943745"];
const TEAMS = parseInt(process.env.TEAMS || "12", 10);
const repo = fileURLToPath(new URL("..", import.meta.url));
const D = (f) => join(repo, "data", "mock", f);
const log = (m) => { const l = `${new Date().toISOString()} ${m}`; console.log(l); appendFileSync(D("driver3.log"), l + "\n"); };

const browser = await chromium.connectOverCDP("http://localhost:9222");
log("driver3 armed: probing for a mock draft-room page");

// ---- wait for the room ----------------------------------------------------
let page = null, leagueId = 0, teamId = 0;
while (!page) {
  for (const p of browser.contexts().flatMap((c) => c.pages())) {
    let u; try { u = new URL(p.url()); } catch { continue; }
    if (u.protocol !== "https:" || !/(^|\.)espn\.com$/i.test(u.hostname)) continue;
    if (!/^\/football\/draft$/i.test(u.pathname)) continue;
    if (REAL_IDS.some((id) => p.url().includes(id))) { continue; } // never a real room
    page = p;
    leagueId = parseInt(u.searchParams.get("leagueId") || "0", 10);
    teamId = parseInt(u.searchParams.get("teamId") || "0", 10);
    break;
  }
  if (!page) await new Promise((r) => setTimeout(r, 700));
}
log(`room: league=${leagueId} teamId=${teamId}`);
const now = Date.now();
writeFileSync("/tmp/mockgrant.json", JSON.stringify({ alias: "mock", league_id: leagueId, season: 2026,
  draft_session_id: `mock-${leagueId}`, issued_at_ms: now, expires_at_ms: now + 2 * 3600 * 1000 }));
log("mock grant written");

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

// ---- main loop ------------------------------------------------------------
let lastPickArea = "", ourPicks = [], clickedThisTurn = false, done = false;
let nextR = 0, nextP = 0; // our next turn, from ESPN's own announcement
try {
  const saved = JSON.parse(readFileSync(D("our_picks3.json"), "utf8"));
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
  writeFileSync(D("hist.txt"), draftedLog.join("\n") + "\n" + s.histText);
  writeFileSync(D("visible.json"), JSON.stringify(s.visible));
  let choice;
  try {
    choice = JSON.parse(execFileSync(join(repo, ".venv/bin/python"),
      [join(repo, "scripts/ctx_choose.py"), "--history", D("hist.txt"), "--visible", D("visible.json"),
       "--exclude", ourPicks.join(","), "--roster", ourPicks.join(","), "--overall", String(overall), "--slot", String(slot),
       "--teams", String(TEAMS), "--league", String(leagueId), "--teamid", String(teamId)],
      { encoding: "utf8", timeout: 10000 }).trim().split("\n").pop());
  } catch (e) { log(`chooser err: ${String(e).slice(0, 120)}`); await new Promise((r) => setTimeout(r, 400)); continue; }
  if (choice.error) { log(`chooser: ${choice.error}`); await new Promise((r) => setTimeout(r, 400)); continue; }

  const t0 = Date.now();
  log(`OUR TURN (overall~${overall} slot~${slot}) clock=${s.clock} -> ${choice.playerName} (${choice.pos}) why=${JSON.stringify(choice.why || {})}`);
  try {
    const out = execFileSync("node", [join(repo, "scripts/espn_actuate.mjs"),
      JSON.stringify({ playerId: choice.playerId, playerName: choice.playerName, leagueId, teamId }),
      "--grant-file", "/tmp/mockgrant.json", "--mock", "--live"], { encoding: "utf8", timeout: 15000 });
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
      writeFileSync(D("our_picks3.json"), JSON.stringify({ league: leagueId, picks: ourPicks }));
      if (!draftedLog.includes(choice.playerName.toLowerCase())) draftedLog.push(choice.playerName.toLowerCase());
      log(`VERIFIED our pick #${ourPicks.length}: ${choice.playerName} (${choice.pos}) | total ${Date.now() - t0}ms`);
    } else log(`UNVERIFIED: ${choice.playerName} — one click max, holding`);
  } catch (e) {
    // actuate refused (exit != 0) => no click happened; next cycle re-chooses
    log(`actuate refused: ${String(e.stderr || e).slice(0, 140)} — re-choosing next cycle`);
  }
  await new Promise((r) => setTimeout(r, 400));
}
log("driver3 exiting");
