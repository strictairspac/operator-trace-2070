import {api} from '../api/client.js';
import {esc,json} from '../utils/html.js';
import {EVIDENCE_LEVELS} from '../constants/enums.js';
const PAGE_LIMIT=50;
let state=null;
const storageKey=(t,r)=>`lineage:${t}:${r}`;
export const lineageOpen=()=>!!state;
export async function openLineage(traceId,row){
 closeLineage();
 let saved=null;
 try{saved=JSON.parse(sessionStorage.getItem(storageKey(traceId,row))||'null');}catch(e){saved=null;}
 state={traceId,row,cursor:saved?.cursor||null,history:saved?.history||[],data:null,error:null,loading:false};
 document.addEventListener('keydown',onKey);
 await load(state.cursor);
}
export function closeLineage(){
 if(!state)return;
 state=null;document.removeEventListener('keydown',onKey);render();
}
async function load(cursor,op){
 if(!state)return;
 state.loading=true;state.error=null;state.attempted={cursor,op};render();
 try{
  const params={row:state.row,limit:PAGE_LIMIT};
  if(cursor)params.cursor=cursor;
  const data=await api(`/traces/${state.traceId}/lineage?${new URLSearchParams(params)}`);
  if(!state)return;
  if(op?.push!==undefined)state.history.push(op.push);
  if(op?.pop)state.history.pop();
  state.data=data;state.cursor=cursor;state.loading=false;
  sessionStorage.setItem(storageKey(state.traceId,state.row),JSON.stringify({cursor,history:state.history}));
 }catch(e){if(state){state.error=e.message;state.loading=false;}}
 render();
}
function nextPage(){const c=state?.data?.page?.next_cursor;if(c&&!state.loading)load(c,{push:state.cursor});}
function prevPage(){if(state&&state.history.length&&!state.loading)load(state.history[state.history.length-1],{pop:true});}
function retry(){if(state&&!state.loading&&state.attempted)load(state.attempted.cursor,state.attempted.op);}
function onKey(e){
 if(!state||e.target.closest?.('input,textarea,select'))return;
 if(e.key==='ArrowRight'){e.preventDefault();nextPage();}
 else if(e.key==='ArrowLeft'){e.preventDefault();prevPage();}
 else if(e.key==='Escape'){e.preventDefault();closeLineage();}
}
function body(){
 const d=state.data;
 if(state.loading&&!d)return '<p class="muted">正在读取来源证据…</p>';
 if(state.error)return `<div class="feedback error">${esc(state.error)}</div><button class="quiet" data-lineage-retry>重试（行号与顺序不变）</button>`;
 if(!d)return '';
 const level=EVIDENCE_LEVELS[d.level]||d.level;
 const meta=`<div class="lineage-meta"><span class="badge ${d.degraded?'degraded':''}">${esc(level)}</span>${d.evidence_bytes?`<small>证据 ${d.evidence_bytes} / ${d.capacity_bytes} 字节</small>`:''}${d.checksum?`<small>证据摘要 <code>${esc(d.checksum.slice(0,16))}…</code></small>`:''}</div><h4>输出分组 #${d.row+1}</h4><pre class="lineage-output">${json(d.output)}</pre>`;
 if(!d.entries)return `${meta}<aside class="note">${esc(d.notice||'')}</aside>${d.row_counts?`<p>该分组计入 readings <b>${d.row_counts.readings}</b> 行 · sensors <b>${d.row_counts.sensors}</b> 行（精确计数，来源已完整扫描）。</p>`:''}${d.totals?`<p>全局累计 readings <b>${d.totals.readings}</b> 行 · sensors <b>${d.totals.sensors}</b> 行。</p>`:''}`;
 const p=d.page,from=p.offset+1,to=p.offset+p.returned;
 const rows=d.entries.map(e=>`<tr><td>${e.n}</td><td>readings #${e.reading_row}</td><td>${e.sensor_row!=null?'sensors #'+e.sensor_row:'—'}</td></tr>`).join('');
 return `${meta}<p>实际计入 <b>${d.total_entries}</b> 条来源（同键同值重复行各算一份），第 ${from}–${to} 条。</p><div class="table-wrap lineage-entries"><table><thead><tr><th>序号</th><th>采样行号</th><th>传感器行号</th></tr></thead><tbody>${rows}</tbody></table></div><div class="lineage-pager"><button class="quiet" data-lineage-prev ${state.history.length?'':'disabled'}>← 上一页</button><button class="quiet" data-lineage-next ${p.next_cursor?'':'disabled'}>下一页 →</button></div>`;
}
function render(){
 const box=document.getElementById('lineage');
 if(!box)return;
 if(!state){box.innerHTML='';return;}
 box.innerHTML=`<div class="lineage-panel"><header><span class="eyebrow">SOURCE LINEAGE / TRACE #${state.traceId}</span><button class="quiet" data-lineage-close title="Esc">关闭 ×</button></header>${body()}<footer>热键 ← → 跨页翻查 · Esc 关闭；翻页位置已记录，中断后重开可恢复，重试行号与顺序不变。${state.loading?'<span class="muted"> 读取中…</span>':''}</footer></div>`;
 box.querySelector('[data-lineage-close]')?.addEventListener('click',closeLineage);
 box.querySelector('[data-lineage-next]')?.addEventListener('click',nextPage);
 box.querySelector('[data-lineage-prev]')?.addEventListener('click',prevPage);
 box.querySelector('[data-lineage-retry]')?.addEventListener('click',retry);
}
