// SKELETON — Read-only Yahoo Fantasy data fetch. Mirrors scripts/fetch_espn_data.mjs.
//
// Reads league settings + players through the user's already-authenticated
// browser session over CDP (BROWSER_CDP_URL, default http://localhost:9222).
// Never navigates, never clicks, never posts. Writes raw JSON to a
// league-specific dir.
//
// STATUS: SCAFFOLD. Every Yahoo endpoint below is marked TODO(verify) — the
// official guide is archived-only (see docs/yahoo-adapter.research.md) and no
// Yahoo league exists yet. Running this today exits with a clear refusal
// unless YAHOO_LEAGUE_KEY is explicitly provided.
//
// Usage:
//   YAHOO_LEAGUE_KEY=461.l.123456 OUT_DIR=data/yahoo/123456/raw node scripts/yahoo_fetch.mjs
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const die = (code, msg) => { console.error(`REFUSED: ${msg}`); process.exit(code); };

// Yahoo league key: {game_key}.l.{league_id} — VERIFIED format (archived guide).
const LEAGUE_KEY = String(process.env.YAHOO_LEAGUE_KEY || "").trim();
if (!LEAGUE_KEY) die(2, "YAHOO_LEAGUE_KEY env var is required (e.g. 461.l.123456) — no Yahoo league is configured yet");
if (!/^(?:[0-9]+|[a-z]+)\.l\.[0-9]+$/.test(LEAGUE_KEY)) die(2, `YAHOO_LEAGUE_KEY ${JSON.stringify(LEAGUE_KEY)} is not a valid {game_key}.l.{league_id} key`);

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const OUT = process.env.OUT_DIR ? join(repoRoot, process.env.OUT_DIR) : join(repoRoot, "data", "yahoo", "raw");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.connectOverCDP(process.env.BROWSER_CDP_URL || "http://localhost:9222").catch(() => null);
if (!browser) die(4, "no CDP browser at BROWSER_CDP_URL (default localhost:9222)");
const pages = browser.contexts().flatMap((c) => c.pages());
// TODO(verify): confirm the logged-in Yahoo Fantasy host serves same-origin
// API reads from page context (fantasysports.yahoo.com vs yahooapis.com +
// OAuth). If page-context fetch is cross-origin-blocked, this script must
// switch to an OAuth token flow (user-authorized; NOT initiated by the agent).
const page = pages.find((p) => p.url().includes("fantasysports.yahoo.com"));
if (!page) { await browser.close(); die(5, "no logged-in fantasysports.yahoo.com tab"); }

async function grab(name, url) {
  const res = await page.evaluate(async (u) => {
    const r = await fetch(u, { credentials: "include", headers: { Accept: "application/json" } });
    return { status: r.status, body: await r.text() };
  }, url);
  if (res.status !== 200) { console.error(`${name} HTTP ${res.status}`); return null; }
  writeFileSync(join(OUT, `${name}.json`), res.body);
  console.log(`${name}: ${res.body.length} bytes -> ${join(OUT, name + ".json")}`);
  try { return JSON.parse(res.body); } catch { return null; }
}

// TODO(verify): base URL + ?format=json behavior (ASSUMED; default is XML).
const base = "https://fantasysports.yahooapis.com/fantasy/v2";
// League settings (roster slots, scoring incl. PPR, draft_type, draft time).
// TODO(verify): exact settings payload shape; ESPN-equivalent of mSettings.
await grab("league_settings", `${base}/league/${LEAGUE_KEY};out=settings,teams?format=json`);
// Players: ranks + ADP only — Yahoo exposes NO projections via API (ASSUMED);
// projections come from our own board pipeline.
// TODO(verify): pagination is 25/page via ;start=N;count=25 and sort=OR.
for (let start = 0; start < 300; start += 25) {
  const out = await grab(
    `players_${String(start).padStart(3, "0")}`,
    `${base}/league/${LEAGUE_KEY}/players;start=${start};count=25;sort=OR/draft_analysis?format=json`
  );
  if (!out) break; // stop paginating on first failure; partial data is fine for a scaffold
}
// Draft results (empty predraft; fills during/after the draft).
// TODO(verify): /draftresults is community-documented only — probe before relying on it.
await grab("draft_results", `${base}/league/${LEAGUE_KEY}/draftresults?format=json`);
await browser.close();
