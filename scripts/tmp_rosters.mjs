import { chromium } from "playwright";
import { writeFileSync } from "node:fs";
const b = await chromium.connectOverCDP("http://localhost:9222");
const p = b.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes("fantasy.espn.com"));
const j = await p.evaluate(async ()=>{ const r=await fetch("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leagues/1851947?view=mRoster&view=mTeam",{credentials:"include"}); return r.json(); });
writeFileSync("data/leagues/1851947/raw/rosters_postdraft.json", JSON.stringify(j));
console.log("teams", j.teams.length); process.exit(0);
