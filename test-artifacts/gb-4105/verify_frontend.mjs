/** Frontend lineage panel verification under jsdom: hotkeys across pages, cursor resume after
 *  interruption, and stable retry. Run: node verify_frontend.mjs */
import {JSDOM} from 'jsdom';

const dom=new JSDOM('<!doctype html><html><body><div id="lineage"></div></body></html>',{url:'http://localhost/'});
globalThis.document=dom.window.document;
globalThis.sessionStorage=dom.window.sessionStorage;

const PASS=[],FAIL=[];
const check=(name,cond,info='')=>{(cond?PASS:FAIL).push(name);console.log(cond?'PASS':'FAIL',name,cond?'':('-> '+String(info).slice(0,300)));};

// Mock API: 120 entries over 3 cursor pages; records every request.
const calls=[];
const pageFor=offset=>({trace_id:7,trace_name:'t',status:'completed',level:'full',degraded:false,capacity_bytes:65536,evidence_bytes:3000,row:0,output:{zone:'北场',count:120},output_rows:1,totals:{readings:120,sensors:120},checksum:'abc123',total_entries:120,entries:Array.from({length:Math.min(50,120-offset)},(_,i)=>({n:offset+i+1,reading_row:offset+i+1,sensor_row:1})),row_counts:{readings:120,sensors:120},page:{offset,limit:50,returned:Math.min(50,120-offset),next_cursor:offset+50<120?'cur-'+(offset+50):null},notice:null});
let failNext=false;
globalThis.fetch=async(url)=>{
 calls.push(url);
 if(failNext){failNext=false;return {ok:false,json:async()=>({detail:'模拟网络中断'})};}
 const u=new URL('http://x'+url);
 const cursor=u.searchParams.get('cursor');
 const offset=cursor?Number(cursor.split('-')[1]):0;
 return {ok:true,json:async()=>pageFor(offset)};
};

const L=await import('/workspace/frontend/src/components/lineage.js');
const tick=()=>new Promise(r=>setTimeout(r,0));
const key=k=>{document.body.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:k,bubbles:true}));};
const rows=()=>document.querySelectorAll('.lineage-entries tbody tr').length;

// open -> first page
await L.openLineage(7,0);
check('打开面板请求第一页（无游标）',calls.at(-1).includes('row=0&limit=50')&&!calls.at(-1).includes('cursor='));
check('第一页渲染50条',rows()===50,rows());
check('面板打开状态可查',L.lineageOpen()===true);

// ArrowRight across pages (hotkey 跨页)
key('ArrowRight');await tick();await tick();
check('热键 → 跨页取下一页（带游标 cur-50）',calls.at(-1).includes('cursor=cur-50'),calls.at(-1));
check('第二页序号从51开始',document.querySelector('.lineage-entries tbody tr td')?.textContent==='51');
key('ArrowRight');await tick();await tick();
check('第三页20条且无下一页',rows()===20&&!document.querySelector('[data-lineage-next]')?.disabled===false&&document.querySelector('[data-lineage-next]')?.disabled);
key('ArrowRight');await tick();
check('末页再按 → 不发请求',calls.filter(c=>c.includes('cursor=')).length===2,calls.length);

// ArrowLeft back across pages
key('ArrowLeft');await tick();await tick();
check('热键 ← 跨页回退到第二页',document.querySelector('.lineage-entries tbody tr td')?.textContent==='51');

// interrupt (close) then reopen -> resumes at stored cursor
key('Escape');await tick();
check('Esc 关闭面板',!L.lineageOpen()&&!document.querySelector('.lineage-panel'));
const before=calls.length;
await L.openLineage(7,0);
check('中断后重开按游标恢复到原位置（直接请求 cur-50）',calls.at(-1).includes('cursor=cur-50'),calls.at(-1));
check('恢复后仍显示第二页',document.querySelector('.lineage-entries tbody tr td')?.textContent==='51');

// retry after failure: same cursor, same data
failNext=true;
key('ArrowRight');await tick();await tick();
check('请求失败显示可重试错误',!!document.querySelector('[data-lineage-retry]'));
const callsBeforeRetry=calls.length;
document.querySelector('[data-lineage-retry]').click();await tick();await tick();
check('重试使用同一游标（行号顺序不变）',calls.at(-1)===calls[callsBeforeRetry-1]&&calls.at(-1).includes('cursor=cur-100'),calls.at(-1));
check('重试成功渲染第三页',rows()===20);

// Escape and reopen another group: isolated state
key('Escape');await tick();
await L.openLineage(7,1);
check('不同分组翻页状态隔离（从第一页开始）',calls.at(-1).includes('row=1')&&!calls.at(-1).includes('cursor='),calls.at(-1));

console.log(`\n${PASS.length} passed, ${FAIL.length} failed`);
process.exit(FAIL.length?1:0);
