// READ-ONLY Yahoo recon, step 2: verify team identity + pull league settings.
// Never navigates, never clicks, never posts. Usage: node scripts/tmp_yahoo_recon2.mjs <league_id> <team_id>
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const [LEAGUE, TEAM] = process.argv.slice(2);
if (!LEAGUE || !TEAM) { console.error("usage: tmp_yahoo_recon2.mjs <league_id> <team_id>"); process.exit(1); }
const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const OUT = join(repoRoot, "data", "yahoo", "raw");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.connectOverCDP("http://localhost:9222");
const page = browser.contexts().flatMap(c => c.pages()).find(p => p.url().includes("yahoo.com"));
if (!page) { console.error("NO_YAHOO_PAGE"); process.exit(2); }

async function grab(name, url) {
  const res = await page.evaluate(async (u) => {
    const r = await fetch(u, { credentials: "include", headers: { Accept: "text/html" } });
    const html = await r.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const rows = [...doc.querySelectorAll("tr")].map(tr =>
      [...tr.querySelectorAll("td,th")].map(c => (c.textContent || "").trim().replace(/\s+/g, " ").slice(0, 60))
    ).filter(r => r.length >= 2 && r[0] && r[0].length < 40);
    return { status: r.status, title: (doc.querySelector("title")?.textContent || "").trim(),
             h1: [...doc.querySelectorAll("h1,h2")].slice(0, 6).map(h => (h.textContent || "").trim().replace(/\s+/g, " ").slice(0, 70)),
             rows: rows.slice(0, 60), html };
  }, url);
  if (res.status !== 200) { console.error(`${name} HTTP ${res.status}`); return null; }
  writeFileSync(join(OUT, `${name}.html`), res.html);
  console.log(`\n=== ${name} (title: ${res.title.slice(0, 80)}) ===`);
  res.h1.forEach(h => console.log("  heading:", h));
  return res;
}

const team = await grab("team_page", `https://football.fantasysports.yahoo.com/f1/${LEAGUE}/${TEAM}`);
const settings = await grab("league_settings", `https://football.fantasysports.yahoo.com/f1/${LEAGUE}/settings`);
if (settings) { console.log("\n--- settings rows ---"); settings.rows.forEach(r => console.log(" ", r.join(" | "))); }
await browser.close();
