/** Smoke: every frontend module parses and the app renders under jsdom. Run: node verify_smoke.mjs */
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<!doctype html><html><body><div id="app"></div></body></html>',{url:'http://localhost/'});
globalThis.document=dom.window.document;
globalThis.sessionStorage=dom.window.sessionStorage;
globalThis.fetch=async()=>({ok:true,json:async()=>([])});
const results=[];
const load=async p=>{try{await import('/workspace/frontend/src/'+p);results.push(['PASS',p]);}catch(e){results.push(['FAIL',p+' -> '+e.message]);}};
for(const p of['constants/enums.js','utils/html.js','api/client.js','api/business.js','stores/business.js','components/common/table.js','components/common/status.js','components/common/feedback.js','components/lineage.js','hooks/forms.js','hooks/poll.js','pages/login.js','pages/datasets.js','pages/plans.js','pages/traces.js','pages/results.js','router/routes.js','types/contracts.js'])await load(p);
// results page renders a completed trace with evidence badge + output pager + lineage container
const {store}=await import('/workspace/frontend/src/stores/business.js');
store.user={email:'v@x.z',role:'viewer'};
store.traces=[{id:3,name:'t',status:'completed',created_at:'2026-11-18',error:null,evidence:{level:'full',degraded:false},result:{operators:[{op:'scan',input_rows:0,output_rows:2,duration_ms:1,detail:{},checksum:'x',preview:[]}],output:[{zone:'北场',count:2},{zone:'南场',count:1}],output_rows:2,checksum:'c',row_visits:2,duration_ms:1}}];
const {resultsPage}=await import('/workspace/frontend/src/pages/results.js');
const html=resultsPage('3');
results.push([html.includes('data-lineage="0"')&&html.includes('id="lineage"')&&html.includes('来源完整')?'PASS':'FAIL','resultsPage 渲染分组按钮/面板容器/证据徽标']);
const old={...store.traces[0],evidence:null};store.traces=[old];
results.push([resultsPage('3').includes('缺少来源')?'PASS':'FAIL','旧剖面徽标缺少来源']);
await import('/workspace/frontend/src/app.js');
results.push([document.getElementById('app').innerHTML.length>50?'PASS':'FAIL','app.js 启动渲染']);
for(const [s,m] of results)console.log(s,m);
console.log(`\n${results.filter(r=>r[0]==='PASS').length} passed, ${results.filter(r=>r[0]==='FAIL').length} failed`);
process.exit(results.some(r=>r[0]==='FAIL')?1:0);
