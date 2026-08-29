// SKELETON — Yahoo draft-room click actuator. DEFAULT IS DRY-RUN.
// Mirrors scripts/espn_actuate.mjs (same arg conventions, grant requirement,
// one-click-max, verify-via-next-snapshot discipline).
//
// Usage:
//   node scripts/yahoo_actuate.mjs '{"playerId":123,"playerName":"...","leagueId":123456,"teamId":7}' \
//        --grant-file /tmp/yahoo_grant.json [--live]
//
// Live pick submission on Yahoo is BROWSER-ONLY (no public API draft write —
// see docs/yahoo-adapter.research.md §4). This script connects to an EXISTING
// browser over CDP (BROWSER_CDP_URL, default localhost:9222) and NEVER
// navigates. It refuses to act unless the active page is a real https
// yahoo.com draft-room URL containing the exact league id, and the grant
// file's alias/league match an allowlisted Yahoo team.
//
// STATUS: SCAFFOLD. THE ALLOWLIST IS EMPTY — no Yahoo league exists yet, so
// every invocation refuses at the grant check. Draft-room URL shape and row/
// button selectors are TODO(verify) from a MOCK draft (read-only capture)
// before --live is ever attempted. Without --live it only logs the target
// element (dry-run), exactly like the ESPN actuator.
import { chromium } from "playwright";
import { readFileSync } from "node:fs";

// ONE confirmed team (owner-confirmed 2026-08-29; mirrored in TEAM_SAFETY.md
// and yahoo_safety.py): "allidoiswin" = "All I Do Is Win", league 384341
// ("Old Backs Fresh Minds"), team 6, game_key 470. RoughRydas (or any analog)
// can never appear here.
const ALLOWED_ALIASES = new Set(["allidoiswin"]);
const CDP_URL = process.env.BROWSER_CDP_URL || "http://localhost:9222";
const die = (code, msg) => { console.error(`REFUSED: ${msg}`); process.exit(code); };

// ---- arguments ------------------------------------------------------------
const args = process.argv.slice(2);
const live = args.includes("--live");
const allowFileFixture = args.includes("--allow-file-fixture");
const grantIdx = args.indexOf("--grant-file");
if (grantIdx === -1 || !args[grantIdx + 1]) die(2, "--grant-file is required");
const jsonArg = args.find((a) => a.startsWith("{"));
if (!jsonArg) die(2, "missing JSON argument {playerId, playerName, leagueId, teamId}");

let target;
try { target = JSON.parse(jsonArg); } catch { die(2, "argument is not valid JSON"); }
const { playerId, playerName, leagueId, teamId } = target;
if (!Number.isInteger(playerId) || playerId <= 0) die(2, "playerId must be a positive integer");
if (typeof playerName !== "string" || !playerName.trim()) die(2, "playerName is required");
if (!Number.isInteger(leagueId) || !Number.isInteger(teamId)) die(2, "leagueId/teamId must be integers");

// ---- grant file (refuse-by-default gate) ----------------------------------
let grant;
try { grant = JSON.parse(readFileSync(args[grantIdx + 1], "utf8")); }
catch { die(3, "grant file unreadable or not JSON"); }
const alias = String(grant.alias || "").trim().toLowerCase();
if (alias === "roughrydas") die(3, "RoughRydas is forbidden — never act on it");
// Exact-alias gate: anything not explicitly listed above refuses.
if (!ALLOWED_ALIASES.has(alias)) die(3, `grant alias ${JSON.stringify(grant.alias)} is not allowlisted`);
if (grant.league_id !== leagueId) die(3, `grant league ${grant.league_id} != target league ${leagueId}`);
if (typeof grant.draft_session_id !== "string" || !grant.draft_session_id.trim())
  die(3, "grant must name the exact draft session (draft_session_id)");
const now = Date.now();
if (!(grant.issued_at_ms <= now && now < grant.expires_at_ms)) die(3, "grant is not currently valid");

// ---- attach to the existing browser (read page identity; NEVER navigate) --
const browser = await chromium.connectOverCDP(CDP_URL).catch(() => null);
if (!browser) die(4, `no CDP browser at ${CDP_URL}`);
try {
  const pages = browser.contexts().flatMap((c) => c.pages());
  const page = pages.find((p) => {
    let u;
    try { u = new URL(p.url()); } catch { return false; }
    // https/host check: real Yahoo over https only. --allow-file-fixture
    // relaxes ONLY this to local file:// fixtures (never the league-id or
    // grant checks; live clicking stays disabled for fixtures).
    const originOk = allowFileFixture
      ? u.protocol === "file:"
      : u.protocol === "https:" && /(^|\.)yahoo\.com$/i.test(u.hostname);
    // TODO(verify): Yahoo draft-room URL shape. ASSUMED it contains the
    // league id and a /draft path segment (e.g. .../f1/<league>/draft or a
    // draftclient URL) — capture read-only from a mock draft.
    return originOk && p.url().includes(String(leagueId)) && /draft/i.test(u.pathname);
  });
  if (!page) die(5, `no active page for league ${leagueId} with a draft-room path`);
  console.log(`page: ${page.url()}`);
  if (live && allowFileFixture) die(2, "--live cannot be combined with --allow-file-fixture");

  // ---- locate the player row and its draft button, defensively ----------
  // TODO(verify): Yahoo draft-room DOM. The selectors below are ASSUMED
  // placeholders modeled on the ESPN actuator; replace with selectors
  // captured read-only from a mock draft room before trusting even dry-run.
  const row = page
    .locator(
      `[data-player-id="${playerId}"], [data-playerid="${playerId}"], ` +
      `tr:has-text(${JSON.stringify(playerName)}), li:has-text(${JSON.stringify(playerName)})`
    )
    .first();
  if ((await row.count()) === 0) die(6, `no row found for ${playerName} (${playerId})`);
  const rowText = (await row.innerText().catch(() => "")).replace(/\s+/g, " ").trim();
  if (!rowText.toLowerCase().includes(playerName.toLowerCase()))
    die(6, `row text does not mention ${playerName}: ${rowText.slice(0, 120)}`);

  // TODO(verify): Yahoo's button label ("Draft" is ASSUMED; may be "Draft
  // Player" or an icon button) and its enabled/on-the-clock semantics.
  const button = row
    .locator('button:has-text("Draft"), button[aria-label*="Draft" i], [class*="draft" i] button')
    .first();
  if ((await button.count()) === 0) die(6, `no draft button in row for ${playerName}`);
  if (!(await button.isEnabled().catch(() => false))) die(6, "draft button is not enabled");

  const label = (await button.innerText().catch(() => "")).trim() || "<no label>";
  console.log(`target: ${playerName} (${playerId}) | row: "${rowText.slice(0, 80)}" | button: "${label}"`);

  if (!live) {
    console.log("DRY-RUN: no click performed (pass --live to actually click).");
  } else {
    // ONE click max per turn; on failure HALT for manual takeover — never
    // blind-retry (same rule as ESPN; see DRAFT_DAY.md "Rules").
    await button.click({ timeout: 5000 });
    console.log(`LIVE: clicked draft button for ${playerName} (${playerId}) as team ${teamId}.`);
    console.log("Verify the pick via a fresh snapshot before doing anything else.");
  }
} finally {
  await browser.close(); // detaches from CDP; the user's browser stays open
}
