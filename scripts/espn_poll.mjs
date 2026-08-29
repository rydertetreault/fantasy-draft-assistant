// READ-ONLY ESPN draft snapshot poller for `fantasy-draft run`.
//
// Connects to an EXISTING browser over CDP (BROWSER_CDP_URL, default
// http://localhost:9222), finds the already-open fantasy.espn.com tab, and
// every POLL_MS (default 2000) fetches the league mDraftDetail view from
// page context (credentials: include, plain GET). Each response is written
// ATOMICALLY (tmp + rename) to data/<team>/snapshots/<epoch_ms>.json and the
// directory is pruned to the newest 50 files.
//
// This script NEVER navigates, clicks, or posts. If the tab or browser goes
// away, it logs and keeps retrying — the Python loop treats missing/old
// snapshots as stale and fails closed.
//
// Usage:
//   TEAM=synaps1 LEAGUE_ID=305025860 SEASON_ID=2026 POLL_MS=2000 \
//     node scripts/espn_poll.mjs
import { chromium } from "playwright";
import { mkdirSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const die = (code, msg) => { console.error(`REFUSED: ${msg}`); process.exit(code); };

const TEAM = String(process.env.TEAM || "").trim().toLowerCase();
if (!/^[a-z0-9][a-z0-9_-]*$/.test(TEAM)) die(2, "TEAM env var must be a safe alias slug (e.g. synaps1)");
if (TEAM === "roughrydas") die(2, "RoughRydas is forbidden — never poll it");
const LEAGUE = parseInt(process.env.LEAGUE_ID || "", 10);
const SEASON = parseInt(process.env.SEASON_ID || "", 10);
if (!Number.isInteger(LEAGUE) || LEAGUE <= 0) die(2, "LEAGUE_ID env var is required");
if (!Number.isInteger(SEASON) || SEASON <= 0) die(2, "SEASON_ID env var is required");
const POLL_MS = Math.max(500, parseInt(process.env.POLL_MS || "2000", 10) || 2000);
const CDP_URL = process.env.BROWSER_CDP_URL || "http://localhost:9222";
const KEEP = 50;

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const OUT = process.env.SNAPSHOT_DIR
  ? join(repoRoot, process.env.SNAPSHOT_DIR)
  : join(repoRoot, "data", TEAM, "snapshots");
mkdirSync(OUT, { recursive: true });

const URL_ = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/${SEASON}` +
  `/segments/0/leagues/${LEAGUE}?view=mDraftDetail`;

const browser = await chromium.connectOverCDP(CDP_URL).catch(() => null);
if (!browser) die(4, `no CDP browser at ${CDP_URL}`);

function findPage() {
  return browser
    .contexts()
    .flatMap((c) => c.pages())
    .find((p) => {
      try { return new URL(p.url()).hostname.endsWith("fantasy.espn.com"); }
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
  if (!page) { console.error("no fantasy.espn.com tab — retrying"); return; }
  let res;
  try {
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
  if (parsed?.id !== LEAGUE) { console.error(`payload league ${parsed?.id} != ${LEAGUE} — skipped`); return; }
  const ts = Date.now();
  const tmp = join(OUT, `.${ts}.json.tmp`);
  const final = join(OUT, `${ts}.json`);
  writeFileSync(tmp, res.body);
  renameSync(tmp, final); // atomic on the same filesystem
  const picks = parsed?.draftDetail?.picks?.length ?? 0;
  console.log(`${new Date(ts).toISOString()} wrote ${final} (${picks} pick slots)`);
  prune();
}

console.log(`polling ${URL_} every ${POLL_MS}ms -> ${OUT} (read-only; Ctrl-C to stop)`);
process.on("SIGINT", async () => { await browser.close(); process.exit(0); });
for (;;) {
  await pollOnce();
  await new Promise((r) => setTimeout(r, POLL_MS));
}
