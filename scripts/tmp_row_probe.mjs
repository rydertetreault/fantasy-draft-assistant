import { chromium } from "playwright";
const b = await chromium.connectOverCDP("http://localhost:9222");
const p = b.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes("leagueId=1851947")&&p.url().includes("/draft"));
console.log(JSON.stringify(await p.evaluate(()=>{
  const rows=[...document.querySelectorAll("div.public_fixedDataTableRow_main")];
  const r=rows.find(r=>/Amon-Ra/.test(r.innerText))||rows[1];
  return {text:(r?.innerText||"").replace(/\s+/g," ").slice(0,120), btns:[...(r?.querySelectorAll("button, [role=button], a")||[])].map(b=>({t:b.innerText.trim(),cls:b.className.slice(0,60),aria:b.getAttribute("aria-label")}))};
})));
process.exit(0);
