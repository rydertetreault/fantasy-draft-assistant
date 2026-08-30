// READ-ONLY recon: navigate the dedicated Yahoo tab to the league settings page
// (not a draft room) and extract draft-related settings.
import { chromium } from "playwright";
const browser = await chromium.connectOverCDP("http://localhost:9222");
const pages = browser.contexts().flatMap(c => c.pages());
const page = pages.find(p => p.url().includes("yahoo.com"));
if (!page) { console.error("NO_YAHOO_TAB"); process.exit(2); }
await page.goto("https://football.fantasysports.yahoo.com/f1/384341/settings",
  { waitUntil: "domcontentloaded", timeout: 30000 });
await page.waitForTimeout(3000);
console.log("URL:", page.url().slice(0,120));
console.log("TITLE:", await page.title());
if (/login\.yahoo|signin/i.test(page.url())) { console.error("NOT_LOGGED_IN — user must log in to Yahoo in the Chrome window"); process.exit(3); }
const text = await page.evaluate(() => document.body.innerText);
const lines = text.split("\n").map(s=>s.trim()).filter(Boolean);
const hits = [];
for (let i = 0; i < lines.length; i++) {
  if (/draft time|draft type|draft status|live standard|salary cap|pick time|scoring type|league name/i.test(lines[i]))
    hits.push(lines.slice(Math.max(0,i-1), i+2).join(" || "));
}
console.log("--- settings hits ---");
console.log([...new Set(hits)].slice(0,30).join("\n") || "(no matches)");
if (!hits.length) console.log("--- first 80 lines ---\n" + lines.slice(0,80).join("\n"));
await browser.close();
