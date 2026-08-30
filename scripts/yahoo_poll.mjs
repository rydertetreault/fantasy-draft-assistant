// SKELETON — READ-ONLY Yahoo draft snapshot poller. Mirrors scripts/espn_poll.mjs.
//
// Connects to an EXISTING browser over CDP (BROWSER_CDP_URL, default
// http://localhost:9222), finds the already-open fantasysports.yahoo.com tab,
// and every POLL_MS (default 2000) fetches the league draftresults from page
// context (credentials: include, plain GET). Each response is written
// ATOMICALLY (tmp + rename) to data/<team>/snapshots/<epoch_ms>.json and the
// directory is pruned to the newest 50 files.
//
// This script NEVER navigates, clicks, or posts. If the tab or browser goes
// away, it logs and keeps retrying — downstream treats missing/old snapshots
// as stale and fails closed.
//
// STATUS: SCAFFOLD. TODO(verify): whether /draftresults updates with low
// enough latency during a live draft for a 90s clock (Yahoo's own draft room
// uses a private realtime channel). Measure in a MOCK draft before trusting.
//
// Usage:
//   TEAM=yahoo1 YAHOO_LEAGUE_KEY=461.l.123456 POLL_MS=2000 node scripts/yahoo_poll.mjs
import { chromium } from "playwright";
import { mkdirSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const die = (code, msg) => { console.error(`REFUSED: ${msg}`); process.exit(code); };

const TEAM = String(process.env.TEAM || "").trim().toLowerCase();
if (!/^[a-z0-9][a-z0-9_-]*$/.test(TEAM)) die(2, "TEAM env var must be a safe alias slug (e.g. yahoo1)");
if (TEAM === "roughrydas") die(2, "RoughRydas is forbidden — never poll it");
const LEAGUE_KEY = String(process.env.YAHOO_LEAGUE_KEY || "").trim();
if (!LEAGUE_KEY) die(2, "YAHOO_LEAGUE_KEY env var is required (e.g. 461.l.123456) — no Yahoo league is configured yet");
if (!/^(?:[0-9]+|[a-z]+)\.l\.[0-9]+$/.test(LEAGUE_KEY)) die(2, `YAHOO_LEAGUE_KEY ${JSON.stringify(LEAGUE_KEY)} is not a valid {game_key}.l.{league_id} key`);
const LEAGUE_ID = LEAGUE_KEY.split(".l.")[1];
const POLL_MS = Math.max(500, parseInt(process.env.POLL_MS || "2000", 10) || 2000);
const CDP_URL = process.env.BROWSER_CDP_URL || "http://localhost:9222";
const KEEP = 50;

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const OUT = process.env.SNAPSHOT_DIR
  ? join(repoRoot, process.env.SNAPSHOT_DIR)
  : join(repoRoot, "data", TEAM, "snapshots");
mkdirSync(OUT, { recursive: true });

// TODO(verify): endpoint + ?format=json (ASSUMED; /draftresults is
// community-documented, not in the archived official guide).
const URL_ = `https://fantasysports.yahooapis.com/fantasy/v2/league/${LEAGUE_KEY}/draftresults?format=json`;

const browser = await chromium.connectOverCDP(CDP_URL).catch(() => null);
if (!browser) die(4, `no CDP browser at ${CDP_URL}`);

function findPage() {
  return browser
    .contexts()
    .flatMap((c) => c.pages())
    .find((p) => {
      try { return new URL(p.url()).hostname.endsWith("fantasysports.yahoo.com"); }
      catch { return false; }
    });
}

function prune() {
  const files = readdirSync(OUT)
    .filter((f) => f.endsWith(".json"))
    .sort(); // epoch-ms names sort chronologically
  for (const f of files.slice(0, Math.max(0, files.length - KEEP))) {
    try { unlinkSync(join(OUT, f)); } catch { /* already gone */ }
  }
}

async function pollOnce() {
  const page = findPage();
  if (!page) { console.error("no fantasysports.yahoo.com tab — retrying"); return; }
  let res;
  try {
    // TODO(verify): page-context fetch to yahooapis.com may be cross-origin
    // blocked from fantasysports.yahoo.com; fall back to a user-authorized
    // OAuth token flow, or a site-internal read endpoint captured read-only.
    res = await page.evaluate(async (url) => {
      const r = await fetch(url, {
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      return { status: r.status, body: await r.text() };
    }, URL_);
  } catch (err) {
    console.error(`fetch failed: ${err.message || err} — retrying`);
    return;
  }
  if (res.status !== 200) { console.error(`HTTP ${res.status} — retrying`); return; }
  let parsed;
  try { parsed = JSON.parse(res.body); } catch { console.error("non-JSON body — skipped"); return; }
  // TODO(verify): payload shape. ASSUMED fantasy_content.league[0][0].league_id
  // and fantasy_content.league[1].draft_results — confirm before parsing for real.
  const bodyLeague = JSON.stringify(parsed).includes(`"league_id":"${LEAGUE_ID}"`) ||
    JSON.stringify(parsed).includes(`.l.${LEAGUE_ID}`);
  if (!bodyLeague) { console.error(`payload does not mention league ${LEAGUE_ID} — skipped`); return; }
  const ts = Date.now();
  const tmp = join(OUT, `.${ts}.json.tmp`);
  const final = join(OUT, `${ts}.json`);
  writeFileSync(tmp, res.body);
  renameSync(tmp, final); // atomic on the same filesystem
  console.log(`${new Date(ts).toISOString()} wrote ${final}`);
  prune();
}

console.log(`polling ${URL_} every ${POLL_MS}ms -> ${OUT} (read-only; Ctrl-C to stop)`);
process.on("SIGINT", async () => { await browser.close(); process.exit(0); });
for (;;) {
  await pollOnce();
  await new Promise((r) => setTimeout(r, POLL_MS));
}
