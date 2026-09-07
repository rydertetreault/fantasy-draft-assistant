import { chromium } from "playwright";
const b = await chromium.connectOverCDP("http://localhost:9222");
const p = b.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes("leagueId=1851947")&&p.url().includes("/draft"));
const setPos = async (label) => p.evaluate((label)=>{
  const sel=[...document.querySelectorAll("select.dropdown__select")].find(s=>[...s.options].some(o=>o.text==="All Pos.") && !s.name.startsWith("fake-"));
  const opt=[...sel.options].find(o=>o.text===label);
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,"value").set.call(sel,opt.value); sel.dispatchEvent(new Event("change",{bubbles:true})); return "set "+label;}, label);
const rows = () => p.evaluate(()=>[...document.querySelectorAll("div.public_fixedDataTableRow_main")].map(r=>(r.innerText||"").replace(/\s+/g," ").slice(0,32)));
await setPos("RB"); for (const w of [500,1000,2000]) { await new Promise(r=>setTimeout(r,w)); const r=await rows(); console.log(`+${w}ms rows=${r.length} jacobs=${r.some(x=>/Jacobs/.test(x))}`, r.slice(0,20).join(" | ")); }
await setPos("All Pos."); process.exit(0);
