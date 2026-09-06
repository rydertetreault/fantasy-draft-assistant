import { chromium } from "playwright";
const b = await chromium.connectOverCDP("http://localhost:9222");
const p = b.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes("leagueId=1851947")&&p.url().includes("/draft"));
const setPos = async (label) => p.evaluate((label)=>{
  const sel=[...document.querySelectorAll("select.dropdown__select")].find(s=>[...s.options].some(o=>o.text==="All Pos.") && !s.name.startsWith("fake-"));
  if(!sel) return "no select";
  const opt=[...sel.options].find(o=>o.text===label); if(!opt) return "no option "+label;
  const setter=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,"value").set;
  setter.call(sel,opt.value); sel.dispatchEvent(new Event("change",{bubbles:true}));
  return "set "+label;
}, label);
const rows = () => p.evaluate(()=>[...document.querySelectorAll("div.public_fixedDataTableRow_main")].slice(1,5).map(r=>(r.innerText||"").replace(/\s+/g," ").slice(0,40)));
console.log(await setPos(process.argv[2]||"D/ST")); await new Promise(r=>setTimeout(r,1500)); console.log(await rows());
console.log(await setPos("All Pos.")); await new Promise(r=>setTimeout(r,1500)); console.log(await rows());
process.exit(0);
