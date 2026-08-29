// EXPERIMENTAL — ESPN draft-room click actuator. DEFAULT IS DRY-RUN.
//
// Usage:
//   node scripts/espn_actuate.mjs '{"playerId":123,"playerName":"...","leagueId":305025860,"teamId":2}' \
//        --grant-file /tmp/grant.json [--live]
//
// Safety: connects to an EXISTING browser over CDP (localhost:9222) and
// NEVER navigates. It refuses to act unless the active page URL contains
// both the exact league id and a draft-room path, and the grant file's
// alias/league match. Without --live it only logs the target element.
import { chromium } from "playwright";
import { readFileSync } from "node:fs";

const ALLOWED_ALIASES = new Set(["synaps1", "synaps2"]); // RoughRydas can never appear here
const die = (code, msg) => { console.error(`REFUSED: ${msg}`); process.exit(code); };

// ---- arguments ------------------------------------------------------------
const args = process.argv.slice(2);
const live = args.includes("--live");
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

// ---- grant file -----------------------------------------------------------
let grant;
try { grant = JSON.parse(readFileSync(args[grantIdx + 1], "utf8")); }
catch { die(3, "grant file unreadable or not JSON"); }
const alias = String(grant.alias || "").trim().toLowerCase();
if (!ALLOWED_ALIASES.has(alias)) die(3, `grant alias ${JSON.stringify(grant.alias)} is not allowlisted`);
if (grant.league_id !== leagueId) die(3, `grant league ${grant.league_id} != target league ${leagueId}`);
const now = Date.now();
if (!(grant.issued_at_ms <= now && now < grant.expires_at_ms)) die(3, "grant is not currently valid");

// ---- attach to the existing browser (read page identity; NEVER navigate) --
const browser = await chromium.connectOverCDP("http://localhost:9222").catch(() => null);
if (!browser) die(4, "no CDP browser at localhost:9222");
try {
  const pages = browser.contexts().flatMap((c) => c.pages());
  const page = pages.find((p) => {
    const url = p.url();
    return url.includes(String(leagueId)) && /\/draft/i.test(new URL(url).pathname);
  });
  if (!page) die(5, `no active page for league ${leagueId} with a draft-room path`);
  console.log(`page: ${page.url()}`);

  // ---- locate the player row and its draft button, defensively ----------
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
    await button.click({ timeout: 5000 });
    console.log(`LIVE: clicked draft button for ${playerName} (${playerId}) as team ${teamId}.`);
    console.log("Verify the pick via a fresh snapshot before doing anything else.");
  }
} finally {
  await browser.close(); // detaches from CDP; the user's browser stays open
}
