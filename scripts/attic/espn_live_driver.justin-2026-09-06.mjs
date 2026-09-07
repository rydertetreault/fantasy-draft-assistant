// ESPN LIVE draft-room driver — REAL ROOMS, grant-gated, dry-run by default.
// Adapted 2026-09-06 from espn_mock_driver.mjs (16/16 mock-validated) the same
// way yahoo_live_driver.mjs was adapted for the Yahoo clean sweep:
//   - page finder REQUIRES the exact real league id + team id (env), instead
//     of refusing real rooms;
//   - NO auto-generated grant: --live requires --grant-file, validated here
//     AND again inside espn_actuate.mjs (alias allowlist, league match,
//     expiry). Without --live every turn logs DRY-RUN and never clicks.
//   - chooser gets BOARD_CSV/CONFIG_YAML for the target league profile.
// Turn detection is DOM-driven (pickArea text), so variable pick timing is
// inherently handled: 400ms cycles, one LIVE click max per turn, verify by
// on-clock state leaving.
import { chromium } from "playwright";
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const die = (code, msg) => { console.error(`REFUSED: ${msg}`); process.exit(code); };

const ALLOWED_ALIASES = new Set(["synaps1", "synaps2", "allidoiswin"]);
const FORBIDDEN = new Set(["roughrydas", "rough rydahs", "roughrydahs"]);
const REAL_IDS = ["305025860", "2144943745", "1851947"];

const ALIAS = String(process.env.ALIAS || "").trim().toLowerCase();
if (FORBIDDEN.has(ALIAS)) die(2, "RoughRydas is forbidden — never drive it");
if (!ALLOWED_ALIASES.has(ALIAS)) die(2, `alias ${JSON.stringify(ALIAS)} is not allowlisted`);
const LEAGUE_ID = String(process.env.LEAGUE_ID || "").trim();
if (!REAL_IDS.includes(LEAGUE_ID)) die(2, `league ${LEAGUE_ID} is not a known real league`);
const TEAM_ID = parseInt(process.env.TEAM_ID || "0", 10);
if (!Number.isInteger(TEAM_ID) || TEAM_ID <= 0) die(2, "TEAM_ID env required (our team id)");
const TEAMS = parseInt(process.env.TEAMS || "0", 10);
if (!Number.isInteger(TEAMS) || TEAMS < 4) die(2, "TEAMS env required (league size)");
const BOARD_CSV = process.env.BOARD_CSV || "";
const CONFIG_YAML = process.env.CONFIG_YAML || "";
if (!BOARD_CSV || !CONFIG_YAML) die(2, "BOARD_CSV and CONFIG_YAML env are required");

const args = process.argv.slice(2);
const live = args.includes("--live");
const grantIdx = args.indexOf("--grant-file");
const grantFile = grantIdx !== -1 ? args[grantIdx + 1] : null;
if (live && !grantFile) die(2, "--live requires --grant-file");
if (live) {
  let g;
  try { g = JSON.parse(readFileSync(grantFile, "utf8")); } catch { die(3, "grant file unreadable"); }
  const galias = String(g.alias || "").trim().toLowerCase();
  if (galias !== ALIAS) die(3, `grant alias ${JSON.stringify(g.alias)} != ${ALIAS}`);
  if (String(g.league_id) !== LEAGUE_ID) die(3, `grant league ${g.league_id} != ${LEAGUE_ID}`);
  const now = Date.now();
  if (!(g.issued_at_ms <= now && now < g.expires_at_ms)) die(3, "grant is not currently valid");
  if (!String(g.draft_session_id || "").trim()) die(3, "grant missing draft_session_id");
}

const repo = fileURLToPath(new URL("..", import.meta.url));
const DDIR = join(repo, "data", ALIAS, "live");
mkdirSync(DDIR, { recursive: true });
const D = (f) => join(DDIR, f);
const log = (m) => { const l = `${new Date().toISOString()} ${m}`; console.log(l); appendFileSync(D("driver.log"), l + "\n"); };

const browser = await chromium.connectOverCDP(process.env.BROWSER_CDP_URL || "http://localhost:9222");
log(`live driver armed: alias=${ALIAS} league=${LEAGUE_ID} team=${TEAM_ID} teams=${TEAMS} mode=${live ? "LIVE" : "DRY-RUN"}`);

// ---- wait for OUR room ----------------------------------------------------
let page = null, leagueId = 0, teamId = 0;
while (!page) {
  for (const p of browser.contexts().flatMap((c) => c.pages())) {
    let u; try { u = new URL(p.url()); } catch { continue; }
    if (u.protocol !== "https:" || !/(^|\.)espn\.com$/i.test(u.hostname)) continue;
    if (!/^\/football\/draft$/i.test(u.pathname)) continue;
    if (!p.url().includes(LEAGUE_ID)) continue; // ONLY our exact league
    const tid = parseInt(u.searchParams.get("teamId") || "0", 10);
    if (tid !== TEAM_ID) { continue; } // ONLY our exact team's room tab
    page = p; leagueId = parseInt(u.searchParams.get("leagueId") || "0", 10); teamId = tid;
    break;
  }
  if (!page) await new Promise((r) => setTimeout(r, 700));
}
log(`room latched: league=${leagueId} teamId=${teamId}`);

// ---- raw CDP websocket tap (best-effort enrichment) -----------------------
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

// ---- state extraction (identical to mock-validated version) ---------------
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
const draftedLog = [];
let prevTop = [];
function trackDisappearance(visible) {
  const nowNames = visible.map((v) => v.toLowerCase());
  for (const name of prevTop) {
    if (!nowNames.some((n) => n.includes(name)) && !draftedLog.includes(name)) draftedLog.push(name);
  }
  prevTop = visible.slice(0, 10).map((v) => v.toLowerCase()
    .replace(/^\d+\s*/, "").replace(/\s+(qb|rb|wr|te|k|d\/st|dst)\s.*$/, "").trim()).filter((n) => n.length > 3);
}

// ---- main loop ------------------------------------------------------------
let lastPickArea = "", ourPicks = [], clickedThisTurn = false, dryLogged = false, done = false;
let nextR = 0, nextP = 0;
try {
  const saved = JSON.parse(readFileSync(D("our_picks.json"), "utf8"));
  if (saved && saved.league === leagueId && Array.isArray(saved.picks)) {
    ourPicks = saved.picks; log(`resumed roster (league ${leagueId}): ${ourPicks.join(", ")}`);
  } else log("stale roster file for a different league — starting fresh");
} catch {}
log(`chooser: contextual engine (slot-adjusted VORP), teams=${TEAMS}, board=${BOARD_CSV}`);
while (!done) {
  let s;
  try { s = await page.evaluate(STATE); } catch (e) { log(`evaluate err: ${String(e).slice(0, 80)}`); await new Promise(r => setTimeout(r, 800)); continue; }
  trackDisappearance(s.visible);
  if (s.pickArea !== lastPickArea) { log(`pickArea: ${s.pickArea} | ${s.round} ${s.clock}`); lastPickArea = s.pickArea; }
  if (/draft is complete|draft complete/i.test(s.pickArea)) { log("DRAFT COMPLETE"); break; }
  const ann = /Round (\d+), Pick (\d+)/i.exec(s.pickArea);
  if (ann) { nextR = parseInt(ann[1], 10); nextP = parseInt(ann[2], 10); }

  const onClock = /you are on the clock/i.test(s.pickArea);
  if (!onClock) { clickedThisTurn = false; dryLogged = false; await new Promise((r) => setTimeout(r, 400)); continue; }
  if (clickedThisTurn) { await new Promise((r) => setTimeout(r, 500)); continue; }

  let overall, slot;
  if (nextR > 0) {
    overall = (nextR - 1) * TEAMS + nextP;
    slot = nextR % 2 === 1 ? nextP : TEAMS - nextP + 1;
  } else {
    overall = draftedLog.length + 1;
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
      { encoding: "utf8", timeout: 10000,
        env: { ...process.env, BOARD_CSV: join(repo, BOARD_CSV), CONFIG_YAML: join(repo, CONFIG_YAML) } })
      .trim().split("\n").pop());
  } catch (e) { log(`chooser err: ${String(e).slice(0, 120)}`); await new Promise((r) => setTimeout(r, 400)); continue; }
  if (choice.error) { log(`chooser: ${choice.error}`); await new Promise((r) => setTimeout(r, 400)); continue; }

  const t0 = Date.now();
  log(`OUR TURN (overall~${overall} slot~${slot}) clock=${s.clock} -> ${choice.playerName} (${choice.pos}) why=${JSON.stringify(choice.why || {})}`);
  if (!live) {
    if (!dryLogged) { log(`DRY-RUN: would draft ${choice.playerName} — no click`); dryLogged = true; }
    await new Promise((r) => setTimeout(r, 500));
    continue;
  }
  try {
    const out = execFileSync("node", [join(repo, "scripts/espn_actuate.mjs"),
      JSON.stringify({ playerId: choice.playerId, playerName: choice.playerName, leagueId, teamId }),
      "--grant-file", grantFile, "--live"], { encoding: "utf8", timeout: 15000 });
    clickedThisTurn = true;
    log(`actuate LIVE ok (${Date.now() - t0}ms): ${out.trim().split("\n").pop()}`);
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
    } else log(`UNVERIFIED: ${choice.playerName} — one click max, holding`);
  } catch (e) {
    log(`actuate refused: ${String(e.stderr || e).slice(0, 140)} — re-choosing next cycle`);
  }
  await new Promise((r) => setTimeout(r, 400));
}
log("live driver exiting");
