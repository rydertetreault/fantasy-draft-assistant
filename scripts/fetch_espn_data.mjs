// Read-only ESPN data fetch through the already-authenticated CDP browser.
// Writes raw JSON to a league-specific dir. Never navigates, never clicks, never posts.
// Usage: LEAGUE_ID=2144943745 OUT_DIR=data/leagues/2144943745/raw node scripts/fetch_espn_data.mjs
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const LEAGUE = parseInt(process.env.LEAGUE_ID || "305025860", 10);
const SEASON = parseInt(process.env.SEASON_ID || "2026", 10);
const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const OUT = process.env.OUT_DIR ? join(repoRoot, process.env.OUT_DIR) : join(repoRoot, "data", "raw");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.connectOverCDP("http://localhost:9222");
const pages = browser.contexts().flatMap(c => c.pages());
const page = pages.find(p => p.url().includes("fantasy.espn.com"));
if (!page) { console.error("NO_FANTASY_PAGE"); process.exit(2); }

async function grab(name, url, filter) {
  const res = await page.evaluate(async ({ url, filter }) => {
    const headers = { Accept: "application/json" };
    if (filter) headers["X-Fantasy-Filter"] = JSON.stringify(filter);
    const r = await fetch(url, { credentials: "include", headers });
    return { status: r.status, body: await r.text() };
  }, { url, filter });
  if (res.status !== 200) { console.error(`${name} HTTP ${res.status}`); return null; }
  writeFileSync(join(OUT, `${name}.json`), res.body);
  console.log(`${name}: ${res.body.length} bytes -> ${join(OUT, name + ".json")}`);
  return JSON.parse(res.body);
}

const base = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/${SEASON}`;
await grab("league_settings", `${base}/segments/0/leagues/${LEAGUE}?view=mSettings&view=mTeam&view=mDraftDetail`);
const players = await grab("players", `${base}/segments/0/leagues/${LEAGUE}?view=kona_player_info`, {
  players: { limit: 500, sortPercOwned: { sortPriority: 1, sortAsc: false } },
});
if (players?.players?.length) console.log("count:", players.players.length);
await browser.close();
