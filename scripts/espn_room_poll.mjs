// READ-ONLY ESPN draft ROOM poller — reads what the room actually renders
// (DOM), NOT the cached lm-api-reads REST view. Postmortem fix #1:
// docs/postmortem-synaps1-2026.md — the REST feed lags entire live drafts.
//
// Every POLL_MS (default 1000) it extracts from the open draft-room tab:
//   clock text + parsed seconds, round label, pick-history text, count of
//   enabled DRAFT buttons (our-turn signal), on-the-clock banner candidates.
// Writes atomic snapshots to data/<team>/room_snapshots/<epoch_ms>.json and
// prints FROZEN alarms when the clock text stops changing while a draft is
// live (postmortem fix: blindness must be LOUD within ~10s).
//
// This script NEVER navigates, clicks, or posts.
//
// Usage:
//   TEAM=synaps2 [LEAGUE_ID=...] [POLL_MS=1000] node scripts/espn_room_poll.mjs
//   LEAGUE_ID optional (mock rooms have arbitrary ids); if set, the room URL
//   must contain it.
import { chromium } from "playwright";
import { mkdirSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const die = (code, msg) => { console.error(`REFUSED: ${msg}`); process.exit(code); };

const TEAM = String(process.env.TEAM || "").trim().toLowerCase();
if (!/^[a-z0-9][a-z0-9_-]*$/.test(TEAM)) die(2, "TEAM env var must be a safe alias slug");
if (TEAM === "roughrydas") die(2, "RoughRydas is forbidden — never poll it");
const LEAGUE_ID = String(process.env.LEAGUE_ID || "").trim();
const POLL_MS = Math.max(500, parseInt(process.env.POLL_MS || "1000", 10) || 1000);
const CDP_URL = process.env.BROWSER_CDP_URL || "http://localhost:9222";
const KEEP = 120;
const FROZEN_TICKS = 10; // ~10s of unchanging clock while live => alarm

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const OUT = join(repoRoot, "data", TEAM, "room_snapshots");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.connectOverCDP(CDP_URL).catch(() => null);
if (!browser) die(4, `no CDP browser at ${CDP_URL}`);

function findPage() {
  return browser.contexts().flatMap((c) => c.pages()).find((p) => {
    let u; try { u = new URL(p.url()); } catch { return false; }
    if (!(u.protocol === "https:" && /(^|\.)espn\.com$/i.test(u.hostname))) return false;
    if (!/\/draft/i.test(u.pathname)) return false;
    if (LEAGUE_ID && !p.url().includes(LEAGUE_ID)) return false;
    return true;
  });
}

const EXTRACT = () => {
  const txt = (el) => (el ? (el.innerText || "").replace(/\s+/g, " ").trim() : null);
  const clock = txt(document.querySelector("[class*=clock__content]"));
  const round = txt(document.querySelector("[class*=clock__label]"));
  const hist = document.querySelector("[class*=pick-history], [class*=pickHistory]");
  // enabled DRAFT buttons inside player rows = strongest our-turn signal
  const draftBtns = Array.from(document.querySelectorAll("button")).filter(
    (b) => /^\s*draft\s*$/i.test(b.innerText || "") && !b.disabled
  );
  // on-the-clock banner candidates (selector refined during mock)
  const otc = txt(document.querySelector(
    "[class*=on-the-clock], [class*=onTheClock], [class*=team-on-clock], [class*=draft-header]"
  ));
  return {
    url: location.href,
    clock_text: clock,
    round_text: round,
    pick_history_text: txt(hist)?.slice(0, 4000) ?? null,
    enabled_draft_buttons: draftBtns.length,
    draft_button_rows: draftBtns.slice(0, 3).map((b) => {
      let r = b; while (r && !/fixedDataTableRowLayout_main/.test(r.className || "")) r = r.parentElement;
      return r ? (r.innerText || "").replace(/\s+/g, " ").slice(0, 80) : null;
    }),
    on_the_clock_text: otc?.slice(0, 200) ?? null,
  };
};

function parseClock(t) {
  const m = /^(\d+):(\d\d)$/.exec(t || "");
  return m ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : null;
}

function prune() {
  const files = readdirSync(OUT).filter((f) => f.endsWith(".json")).sort();
  for (const f of files.slice(0, Math.max(0, files.length - KEEP))) {
    try { unlinkSync(join(OUT, f)); } catch {}
  }
}

let lastClock = null, unchanged = 0, alarmed = false;
console.log(`room poller: team=${TEAM} league=${LEAGUE_ID || "<any>"} poll=${POLL_MS}ms out=${OUT}`);
for (;;) {
  const t0 = Date.now();
  const page = findPage();
  if (!page) {
    console.error(`${new Date().toISOString()} NO ROOM PAGE (waiting)`);
  } else {
    try {
      const data = await page.evaluate(EXTRACT);
      data.ts_ms = Date.now();
      data.clock_seconds = parseClock(data.clock_text);
      // frozen-room watchdog: a live draft's clock text changes every second
      const liveish = data.clock_seconds !== null || data.enabled_draft_buttons > 0;
      if (data.clock_text === lastClock && liveish) unchanged += 1; else unchanged = 0;
      lastClock = data.clock_text;
      data.frozen_ticks = unchanged;
      if (unchanged >= FROZEN_TICKS && !alarmed) {
        console.error(`${new Date().toISOString()} *** FROZEN ROOM ALARM: clock "${data.clock_text}" unchanged ${unchanged} ticks ***`);
        alarmed = true;
      }
      if (unchanged === 0) alarmed = false;
      const tmp = join(OUT, `.tmp-${data.ts_ms}`);
      writeFileSync(tmp, JSON.stringify(data));
      renameSync(tmp, join(OUT, `${data.ts_ms}.json`));
      prune();
    } catch (e) {
      console.error(`${new Date().toISOString()} extract error: ${String(e).slice(0, 120)}`);
    }
  }
  await new Promise((r) => setTimeout(r, Math.max(0, POLL_MS - (Date.now() - t0))));
}
