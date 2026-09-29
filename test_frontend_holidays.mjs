// test_frontend_holidays.mjs —— 前端 ledgerStatus 接休市行事曆（2026-09-29 批次二，規格
// taiwan-flow-live-v2/docs/holiday-calendar.md §5b）。從 index.html 抽出 holParse／holClosed／shiftHours／
// prevWeekday／isWeekend／ledgerStatus 在 node vm 沙箱跑：09-25（週五假日）／09-28（週一假日）／09-26 週六／
// 09-29 平日重演，並驗 fail-open（HOL=null）時與改動前只排週末版本逐字相同、三個門檻字面量未變。
// 用法：node test_frontend_holidays.mjs（離線、免 token；任一斷言失敗 exit 1；本 repo 無 CI，手動跑）
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";

const ROOT = import.meta.dirname;
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
function fn(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`index.html 找不到 function ${name}`);
  const open = html.indexOf("{", start);
  let depth = 0, inStr = null;
  for (let i = open; i < html.length; i++) {
    const c = html[i];
    if (inStr) { if (c === "\\") { i++; continue; } if (c === inStr) inStr = null; }
    else if (c === '"' || c === "'" || c === "`") inStr = c;
    else if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) return html.slice(start, i + 1); }
  }
  throw new Error(`${name} 大括號未配對`);
}
const NAMES = ["holParse", "holClosed", "shiftHours", "prevWeekday", "isWeekend", "ledgerStatus"];
const sb = { Date, Array, Number, String, Object, console };
vm.createContext(sb);
new vm.Script("var HOL=null; function twNow(){ throw new Error('必須注入 nowStr'); }\n" + NAMES.map(fn).join("\n")
  + "\nthis.setHol=function(j){ HOL = j==null ? null : holParse(j); return HOL; };"
  + NAMES.map(k => `this.${k}=${k};`).join("")).runInContext(sb);

// 改動前的 prevWeekday／ledgerStatus（逐字搬自改動前 index.html，只排週末），作 fail-open 對照組
const old = new vm.Script(`
function prevWeekday(d){ var t=Date.parse(d+"T00:00:00Z"),g; do{ t-=864e5; g=new Date(t).getUTCDay(); }while(g===0||g===6); return new Date(t).toISOString().slice(0,10); }
function isWeekend(d){ var g=new Date(d+"T00:00:00Z").getUTCDay(); return g===0||g===6; }
${fn("shiftHours")}
function ledgerStatus(lastDate, nowStr){
  if(!/^\\d{4}-\\d{2}-\\d{2}$/.test(String(lastDate==null?"":lastDate))) return {txt:"查詢失敗（未知）"};
  var ref=shiftHours(nowStr,-12), refDay=ref.slice(0,10), hm=ref.slice(11,16);
  if(isWeekend(refDay)){ var fri=prevWeekday(refDay); return lastDate>=fri?{txt:"休市定格"}:{txt:"資料缺漏"}; }
  if(lastDate>=refDay) return {txt:"正常"};
  var prev=prevWeekday(refDay);
  if(lastDate<prev) return {txt:"資料缺漏"};
  if(hm<"09:07") return {txt:"正常"};
  if(hm<"19:07") return {txt:"等待資料發布"};
  return {txt:"資料缺漏"};
}
this.oldStatus=ledgerStatus;`);
const osb = { Date, String }; vm.createContext(osb); old.runInContext(osb);

const CAL = { schema: 1, years: [2026], closed: ["2026-06-19", "2026-09-25", "2026-09-28", "2026-10-09", "2026-10-10"],
  names: { "2026-09-25": "中秋節", "2026-09-28": "教師節" } };
let n = 0;
const ok = (name, f) => { f(); n++; console.log("ok  ", name); };
const st = (last, now) => sb.ledgerStatus(last, now).txt;

ok("門檻字面量未變（回推 12h／09:07／19:07）", () => {
  const src = fn("ledgerStatus");
  assert.match(src, /shiftHours\(nowStr\|\|twNow\(\),-12\)/);
  assert.equal((src.match(/hm<"09:07"/g) || []).length, 1);
  assert.equal((src.match(/hm<"19:07"/g) || []).length, 1);
});
ok("解析：schema 必須是整數 1（true 不收）、years 無合法年度＝null", () => {
  assert.equal(sb.holParse({ ...CAL, schema: true }), null);
  assert.equal(sb.holParse({ ...CAL, schema: "1" }), null);
  assert.equal(sb.holParse({ ...CAL, years: ["2026"] }), null);
  assert.equal(sb.holParse(null), null);
  assert.notEqual(sb.holParse(CAL), null);
});
ok("fail-open：HOL=null 時 ledgerStatus 狀態詞與改動前逐字相同（8–12 月 × 每小時 × 帳冊落後 0–6 日）", () => {
  sb.setHol(null);
  for (let t = Date.parse("2026-08-01T00:00:00Z"); t <= Date.parse("2026-12-31T00:00:00Z"); t += 864e5) {
    for (let h = 0; h < 24; h++) {
      const now = new Date(t).toISOString().slice(0, 10) + " " + String(h).padStart(2, "0") + ":30:00";
      for (let k = 0; k <= 6; k++) {
        const last = new Date(t - k * 864e5).toISOString().slice(0, 10);
        assert.equal(st(last, now), osb.oldStatus(last, now).txt, now + " " + last);
      }
    }
  }
});
ok("休市日比照週末（帳冊停在 09-24）", () => {
  sb.setHol(CAL);
  assert.equal(st("2026-09-24", "2026-09-25 21:00:00"), "休市定格");   // refDay 09-25 假日
  assert.equal(st("2026-09-24", "2026-09-26 10:00:00"), "休市定格");   // refDay 09-25 假日（週六上午）
  assert.equal(st("2026-09-24", "2026-09-27 23:00:00"), "休市定格");   // refDay 週日，上一交易日跳過 09-25
  assert.equal(st("2026-09-24", "2026-09-28 23:00:00"), "休市定格");   // refDay 09-28 假日
  assert.equal(st("2026-09-24", "2026-09-29 10:00:00"), "休市定格");   // refDay 09-28 假日（週二上午）
  assert.equal(st("2026-09-24", "2026-09-29 20:00:00"), "正常");       // refDay 09-29 主班前
  assert.equal(st("2026-09-24", "2026-09-29 23:00:00"), "等待資料發布");
  assert.equal(st("2026-09-24", "2026-09-30 08:00:00"), "資料缺漏");   // 主班+10h 仍缺
  assert.equal(st("2026-09-23", "2026-09-28 23:00:00"), "資料缺漏");   // 真落後
  assert.match(sb.ledgerStatus("2026-09-24", "2026-09-25 21:00:00").title, /中秋節/);
});
ok("年度未涵蓋＝只排週末", () => {
  sb.setHol({ ...CAL, years: [2025] });
  assert.equal(st("2026-09-24", "2026-09-28 23:00:00"), "資料缺漏");
});
console.log(`\n${n} passed`);
