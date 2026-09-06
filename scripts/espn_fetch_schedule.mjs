// READ-ONLY ESPN schedule/settings fetch through the already-authenticated CDP browser.
// Never navigates, never clicks, never posts. Writes raw JSON for offline analysis only.
// Usage: LEAGUE_ID=1851947 SEASON_ID=2026 node scripts/espn_fetch_schedule.mjs
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const LEAGUE = parseInt(process.env.LEAGUE_ID || "", 10);
const SEASON = parseInt(process.env.SEASON_ID || "2026", 10);
if (!LEAGUE) { console.error("LEAGUE_ID required"); process.exit(1); }
const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const OUT = join(repoRoot, "data", "leagues", String(LEAGUE), "raw");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.connectOverCDP("http://localhost:9222");
const pages = browser.contexts().flatMap(c => c.pages());
const page = pages.find(p => p.url().includes("fantasy.espn.com"));
if (!page) { console.error("NO_FANTASY_PAGE"); process.exit(2); }

async function grab(name, url) {
  const res = await page.evaluate(async ({ url }) => {
    const r = await fetch(url, { credentials: "include", headers: { Accept: "application/json" } });
    return { status: r.status, body: await r.text() };
  }, { url });
  if (res.status !== 200) { console.error(`${name} HTTP ${res.status}: ${res.body.slice(0, 200)}`); return null; }
  writeFileSync(join(OUT, `${name}.json`), res.body);
  console.log(`${name}: ${res.body.length} bytes`);
  return JSON.parse(res.body);
}

const base = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/${SEASON}/segments/0/leagues/${LEAGUE}`;
await grab("settings_teams", `${base}?view=mSettings&view=mTeam`);
await grab("schedule", `${base}?view=mMatchup`);
await browser.close();
