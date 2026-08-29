// AUTHORIZED WRITE: upload a pre-draft ranking list to ESPN Edit Draft Strategy.
// Only for allowlisted teams. Requires a logged-in fantasy.espn.com tab on CDP :9222.
// Usage: node scripts/espn_set_draftlist.mjs <draftlist.json> [--league 305025860 --team 2 --season 2026]
import { chromium } from "playwright";
import { readFileSync } from "node:fs";

const ALLOWED = new Map([["305025860:2", "synaps1"], ["2144943745:4", "synaps2"]]);
const args = process.argv.slice(2);
const file = args[0];
const opt = (name, dflt) => { const i = args.indexOf(`--${name}`); return i >= 0 ? args[i + 1] : dflt; };
const league = opt("league", "305025860"), team = opt("team", "2"), season = opt("season", "2026");

if (!file) { console.error("usage: espn_set_draftlist.mjs <draftlist.json> [--league L --team T --season S]"); process.exit(2); }
if (!ALLOWED.has(`${league}:${team}`)) { console.error(`REFUSED: ${league}:${team} is not an allowlisted team`); process.exit(3); }

const ids = JSON.parse(readFileSync(file, "utf8"));
if (!Array.isArray(ids) || !ids.length || !ids.every(n => Number.isInteger(n) && n > 0)) {
  console.error("REFUSED: draftlist must be a non-empty array of positive integer player ids"); process.exit(4);
}

const b = await chromium.connectOverCDP(process.env.BROWSER_CDP_URL || "http://localhost:9222");
const page = b.contexts().flatMap(c => c.pages()).find(p => p.url().includes("fantasy.espn.com"));
if (!page) { console.error("REFUSED: no logged-in fantasy.espn.com tab"); process.exit(5); }

const write = await page.evaluate(async ({ ids, league, team, season }) => {
  const body = JSON.stringify({ draftStrategy: { draftList: ids.map(playerId => ({ playerId })) } });
  const r = await fetch(`https://lm-api-writes.fantasy.espn.com/apis/v3/games/ffl/seasons/${season}/segments/0/leagues/${league}/teams/${team}?platformVersion=96e7cdc122a61e6c778b4087703c10d123d0565d`, {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-Fantasy-Source": "kona", "X-Fantasy-Platform": "kona-PROD" },
    body,
  });
  return { status: r.status, ok: r.ok };
}, { ids, league, team, season });
if (!write.ok) { console.error(`WRITE FAILED: HTTP ${write.status}`); process.exit(6); }

const check = await page.evaluate(async ({ league, team, season }) => {
  const r = await fetch(`https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/${season}/segments/0/leagues/${league}?view=mTeam`, { credentials: "include", headers: { Accept: "application/json" } });
  const j = await r.json();
  const dl = ((j.teams || []).find(t => t.id === Number(team))?.draftStrategy?.draftList) || [];
  return { count: dl.length, first3: dl.slice(0, 3).map(x => x.playerId) };
}, { league, team, season });
await b.close();

if (check.count !== ids.length || check.first3.some((v, i) => v !== ids[i])) {
  console.error(`VERIFY FAILED: server has ${check.count} ids, first3=${check.first3}`); process.exit(7);
}
console.log(`OK: ${check.count} players ranked on ESPN for ${ALLOWED.get(`${league}:${team}`)}; first3=${check.first3}`);
