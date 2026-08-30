// READ-ONLY Yahoo recon through the already-authenticated CDP browser.
// Mirrors fetch_espn_data.mjs discipline: never navigates, never clicks, never posts.
// Discovers the logged-in account's fantasy football teams (league_id, team_id, names).
// Usage: node scripts/tmp_yahoo_recon.mjs
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const OUT = join(repoRoot, "data", "yahoo", "raw");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.connectOverCDP("http://localhost:9222");
const pages = browser.contexts().flatMap(c => c.pages());
const page = pages.find(p => p.url().includes("yahoo.com"));
if (!page) { console.error("NO_YAHOO_PAGE"); process.exit(2); }
console.log(`using tab (untouched): ${page.url().slice(0, 90)}`);

// In-page GET of the football home page (lists all of the account's teams).
// DOM-parsed inside the page context; the visible tab is never navigated.
const res = await page.evaluate(async () => {
  const r = await fetch("https://football.fantasysports.yahoo.com/f1/", {
    credentials: "include",
    headers: { Accept: "text/html" },
  });
  const html = await r.text();
  const doc = new DOMParser().parseFromString(html, "text/html");
  const links = [...doc.querySelectorAll('a[href*="/f1/"]')].map(a => ({
    href: a.getAttribute("href"),
    text: (a.textContent || "").trim().replace(/\s+/g, " ").slice(0, 80),
  }));
  return { status: r.status, htmlLen: html.length, html, links };
});

if (res.status !== 200) { console.error(`football home HTTP ${res.status} (not logged in?)`); process.exit(3); }
writeFileSync(join(OUT, "football_home.html"), res.html);
console.log(`football home: ${res.htmlLen} bytes -> data/yahoo/raw/football_home.html`);

// Team pages look like /f1/<league_id>/<team_id>
const teams = new Map();
for (const l of res.links) {
  const m = (l.href || "").match(/^(?:https?:\/\/football\.fantasysports\.yahoo\.com)?\/f1\/(\d+)\/(\d+)(?:\/|$)/);
  if (m) {
    const key = `${m[1]}/${m[2]}`;
    if (!teams.has(key) || (l.text && !teams.get(key).name)) {
      teams.set(key, { league_id: m[1], team_id: m[2], name: l.text || teams.get(key)?.name || "" });
    }
  }
}
console.log("\n=== TEAMS ON THIS ACCOUNT ===");
for (const t of teams.values()) console.log(JSON.stringify(t));
if (teams.size === 0) console.log("(none found — page layout may differ; inspect saved HTML)");
await browser.close();
