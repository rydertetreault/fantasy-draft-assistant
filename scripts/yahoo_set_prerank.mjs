// SKELETON — upload a pre-draft ranking list to Yahoo ("Pre-Draft Ranks").
// Mirrors scripts/espn_set_draftlist.mjs: allowlist gate, write, then
// VERIFY-AFTER-WRITE by re-reading the server state.
//
// Usage: node scripts/yahoo_set_prerank.mjs <preranklist.json> --league <id> --team <id> [--game-key 461]
//        preranklist.json = non-empty array of positive integer Yahoo player ids
//
// STATUS: SCAFFOLD — REFUSES EVERYTHING TODAY.
// 1) The allowlist below is EMPTY (no Yahoo league configured), so the gate
//    refuses before any browser contact.
// 2) Yahoo has NO documented API for pre-rank upload (research doc §3,
//    ASSUMED browser-only via the league's "Pre-Draft Ranks" page). The
//    write + verify endpoints below are TODO(verify) placeholders that exit
//    with NOT-IMPLEMENTED even if an allowlist entry existed, until the real
//    mechanism is captured read-only (DevTools, user's own session, with
//    explicit user authorization).
import { chromium } from "playwright";
import { readFileSync } from "node:fs";

// EMPTY BY DESIGN: map of "leagueId:teamId" -> alias, mirroring the ESPN
// script. Populate only with user-confirmed ids recorded in yahoo_safety.py
// and the TEAM_SAFETY-style doc. RoughRydas (or any analog) never appears.
const ALLOWED = new Map([]);

const args = process.argv.slice(2);
const file = args[0];
const opt = (name, dflt) => { const i = args.indexOf(`--${name}`); return i >= 0 ? args[i + 1] : dflt; };
const league = opt("league", ""), team = opt("team", ""), gameKey = opt("game-key", "");

if (!file || !league || !team) {
  console.error("usage: yahoo_set_prerank.mjs <preranklist.json> --league <id> --team <id> [--game-key 461]");
  process.exit(2);
}
// Refuse-by-default gate: with the empty map this refuses every invocation.
if (!ALLOWED.has(`${league}:${team}`)) {
  console.error(`REFUSED: ${league}:${team} is not an allowlisted Yahoo team (allowlist is empty — no league configured)`);
  process.exit(3);
}

const ids = JSON.parse(readFileSync(file, "utf8"));
if (!Array.isArray(ids) || !ids.length || !ids.every(n => Number.isInteger(n) && n > 0)) {
  console.error("REFUSED: preranklist must be a non-empty array of positive integer player ids"); process.exit(4);
}

const b = await chromium.connectOverCDP(process.env.BROWSER_CDP_URL || "http://localhost:9222");
const page = b.contexts().flatMap(c => c.pages()).find(p => p.url().includes("fantasysports.yahoo.com"));
if (!page) { console.error("REFUSED: no logged-in fantasysports.yahoo.com tab"); process.exit(5); }

// ---------------------------------------------------------------------------
// TODO(verify): the actual pre-rank write. Yahoo's "Pre-Draft Ranks" page
// (ASSUMED at https://football.fantasysports.yahoo.com/f1/<league>/editprerank
// or similar) supports drag-drop reorder and a paste-a-list import; the
// underlying request is site-internal and undocumented. Capture it once,
// read-only, in the user's own session, then implement here following the
// ESPN pattern: page.evaluate(fetch(write)) -> page.evaluate(fetch(read)) ->
// compare count + first3 -> nonzero exit on VERIFY FAILED.
// ---------------------------------------------------------------------------
await b.close();
console.error("NOT-IMPLEMENTED: Yahoo pre-rank write endpoint is unverified (TODO(verify) — see docs/yahoo-adapter.research.md §3). No write was attempted.");
process.exit(6);

// Shape of the eventual implementation (kept for review, unreachable):
//
// const write = await page.evaluate(async ({ ids, league, team }) => {
//   // TODO(verify): endpoint, method, CSRF ("crumb") token, payload shape.
//   return { status: 0, ok: false };
// }, { ids, league, team });
// if (!write.ok) { console.error(`WRITE FAILED: HTTP ${write.status}`); process.exit(6); }
//
// const check = await page.evaluate(async ({ league, team }) => {
//   // TODO(verify): read-back source — site-internal prerank read, or the
//   // rendered editprerank page. Must return { count, first3 }.
//   return { count: 0, first3: [] };
// }, { league, team });
//
// if (check.count !== ids.length || check.first3.some((v, i) => v !== ids[i])) {
//   console.error(`VERIFY FAILED: server has ${check.count} ids, first3=${check.first3}`); process.exit(7);
// }
// console.log(`OK: ${check.count} players ranked on Yahoo for ${ALLOWED.get(`${league}:${team}`)}; first3=${check.first3}`);
