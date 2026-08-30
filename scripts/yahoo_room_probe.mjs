// READ-ONLY Yahoo draft-room DOM prober. Learns the room structure live:
// clock candidates, player-row candidates, draft-button candidates, on-clock
// banners, pick history. Writes snapshots to data/yahoo/room_recon.jsonl.
// NEVER navigates, clicks, or posts. Refuses real-league rooms unless
// YAHOO_ALLOW_REAL=1 (mock lobby recon is the default use).
import { chromium } from "playwright";
import { appendFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const repo = fileURLToPath(new URL("..", import.meta.url));
mkdirSync(join(repo, "data", "yahoo"), { recursive: true });
const OUT = join(repo, "data", "yahoo", "room_recon.jsonl");
const log = (m) => console.log(`${new Date().toISOString()} ${m}`);

const browser = await chromium.connectOverCDP(process.env.BROWSER_CDP_URL || "http://localhost:9222");
log("yahoo prober armed: waiting for a Yahoo draft page");

let page = null;
const isReal = (p) => /\/f1\/384341/.test(p.url()) && process.env.YAHOO_ALLOW_REAL !== "1";
while (!page) {
  const all = browser.contexts().flatMap((c) => c.pages()).filter((p) => !isReal(p));
  page = all.find((p) => /draftclient/i.test(p.url())) || all.find((p) => {
    let u; try { u = new URL(p.url()); } catch { return false; }
    if (!/(^|\.)yahoo\.com$/i.test(u.hostname)) return false;
    return /draftclient/i.test(u.pathname) || /draft/i.test(u.pathname + u.search);
  }) || null;
  if (!page) await new Promise((r) => setTimeout(r, 1000));
}
log(`draft page: ${page.url().slice(0, 110)}`);

const PROBE = () => {
  const t = (el) => (el ? (el.innerText || "").replace(/\s+/g, " ").trim() : "");
  const all = Array.from(document.querySelectorAll("*"));
  const clockish = all.filter((e) => /^\d{1,2}:\d\d$/.test((e.innerText || "").trim()) && e.children.length === 0)
    .slice(0, 4).map((e) => ({ cls: (e.className || "").toString().slice(0, 60), text: e.innerText.trim() }));
  const btns = Array.from(document.querySelectorAll("button, [role=button]"))
    .filter((b) => /draft|queue/i.test(b.innerText || ""))
    .slice(0, 8).map((b) => ({ text: (b.innerText || "").slice(0, 25), cls: (b.className || "").toString().slice(0, 60), disabled: !!b.disabled }));
  const onclock = all.filter((e) => /on the clock|your pick|you're up|youre up/i.test(e.innerText || "") && (e.innerText || "").length < 200)
    .slice(0, 3).map((e) => ({ cls: (e.className || "").toString().slice(0, 60), text: (e.innerText || "").replace(/\s+/g, " ").slice(0, 120) }));
  // repeated-structure candidates: parents with many similar children mentioning positions
  const rowParents = all.filter((e) => e.children.length >= 8 &&
    /(QB|RB|WR|TE)\b/.test(e.innerText || "") && (e.innerText || "").length > 200 && (e.innerText || "").length < 20000)
    .slice(0, 3).map((e) => ({
      cls: (e.className || "").toString().slice(0, 70), tag: e.tagName, kids: e.children.length,
      kidSample: t(e.children[0]).slice(0, 100), kidCls: (e.children[0].className || "").toString().slice(0, 60),
    }));
  const hist = all.filter((e) => /pick|results|history/i.test((e.className || "").toString()) && e.children.length > 2)
    .slice(0, 3).map((e) => ({ cls: (e.className || "").toString().slice(0, 60), textSample: t(e).slice(0, 100) }));
  return { url: location.href.slice(0, 120), clockish, btns, onclock, rowParents, hist };
};

let last = "";
for (;;) {
  try {
    const s = await page.evaluate(PROBE);
    s.ts = Date.now();
    const key = JSON.stringify([s.clockish, s.onclock.map((o) => o.text), s.btns.length]);
    appendFileSync(OUT, JSON.stringify(s) + "\n");
    if (key !== last) { log(`clock=${JSON.stringify(s.clockish[0] || null)} onclock=${JSON.stringify(s.onclock[0] || null)} draftBtns=${s.btns.length}`); last = key; }
  } catch (e) {
    log(`probe err (page gone?): ${String(e).slice(0, 80)}`);
    await new Promise((r) => setTimeout(r, 2000));
  }
  await new Promise((r) => setTimeout(r, 1000));
}
