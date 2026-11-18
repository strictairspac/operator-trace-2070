"""A bounded teaching execution engine; this does not replace PostgreSQL execution."""
from collections import defaultdict
from decimal import Decimal
import time,json,hashlib,math
from src.constants.enums import OPERATORS
MAX_ROWS=10000
EVIDENCE_CAPACITY=65536
READING_FIELDS={'sensor_id','value','recorded_at'}
SENSOR_FIELDS={'sensor_id','zone','device_type'}
def validate_steps(steps):
 if not isinstance(steps,list) or not 1<=len(steps)<=6:raise ValueError('计划须包含1至6个算子')
 fields=set();grouped=False
 for i,step in enumerate(steps):
  if not isinstance(step,dict) or step.get('op') not in OPERATORS:raise ValueError('非法算子；仅允许scan/filter/hash_join/group')
  op=step['op']
  if i==0 and op!='scan':raise ValueError('第一步必须是scan')
  if op=='scan':
   if i!=0 or step!={'op':'scan','source':'readings'}:raise ValueError('scan只能在首步读取readings')
   fields=READING_FIELDS.copy()
  elif op=='filter':
   if set(step)!={'op','field','compare','value'} or not isinstance(step['field'],str) or step['field'] not in fields or step['compare'] not in ('eq','gte','lte'):raise ValueError('filter字段或比较方式无效')
   if step['compare']!='eq' and (step['field'] not in ('sensor_id','value','count','sum','avg') or not isinstance(step['value'],(int,float)) or not math.isfinite(step['value'])):raise ValueError('范围筛选只接受数值字段和有限数值')
   if not isinstance(step['value'],(str,int,float)) or isinstance(step['value'],bool) or (isinstance(step['value'],float) and not math.isfinite(step['value'])):raise ValueError('filter值只接受文本或数值')
  elif op=='hash_join':
   if grouped or not READING_FIELDS.issubset(fields) or step!={'op':'hash_join','right':'sensors','left_key':'sensor_id','right_key':'sensor_id'}:raise ValueError('hash_join仅支持分组前readings与sensors按sensor_id内连接')
   if 'zone' in fields:raise ValueError('一个计划只允许一次连接')
   fields|=SENSOR_FIELDS
  elif op=='group':
   if set(step)!={'op','keys','measure','aggregate'} or grouped:raise ValueError('仅允许一次group，参数为keys/measure/aggregate')
   keys=step['keys']
   if not isinstance(keys,list) or not 1<=len(keys)<=2 or any(not isinstance(k,str) for k in keys) or len(set(keys))!=len(keys) or any(k not in fields for k in keys):raise ValueError('分组字段无效')
   if step['measure']!='value' or step['aggregate'] not in ('count','sum','avg'):raise ValueError('group仅允许value的count/sum/avg')
   fields=set(keys)|{step['aggregate']};grouped=True
 return steps

def checksum(rows):return hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def _canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
def _run(dataset,steps):
 """Execute the plan, threading source lineage (1-based snapshot row numbers) alongside rows."""
 validate_steps(steps);rows=[];lineage=[];trace=[];total_started=time.perf_counter();reads=0
 for step in steps:
  before=len(rows);started=time.perf_counter();detail={}
  if step['op']=='scan':
   rows=[dict(r) for r in dataset['readings']];lineage=[{'readings':[i+1],'sensors':[]} for i in range(len(rows))];reads+=len(rows);detail={'source':'readings','scanned_rows':len(rows)}
  elif step['op']=='filter':
   field,cmp,value=step['field'],step['compare'],step['value']
   def match(row):
    v=row[field]
    if cmp=='eq':return v==value
    if not isinstance(v,(int,float)):raise ValueError('范围比较遇到非数值')
    return v>=value if cmp=='gte' else v<=value
   reads+=len(rows);kept=[(r,l) for r,l in zip(rows,lineage) if match(r)];rows=[r for r,_ in kept];lineage=[l for _,l in kept];detail={'predicate':step,'removed_rows':before-len(rows)}
  elif step['op']=='hash_join':
   buckets=defaultdict(list)
   for j,sensor in enumerate(dataset['sensors']):buckets[sensor['sensor_id']].append((j+1,sensor))
   joined=[];joined_lineage=[];probes=0
   for row,lin in zip(rows,lineage):
    probes+=1
    for sensor_row,sensor in buckets.get(row['sensor_id'],[]):
     joined.append({**row,**sensor});joined_lineage.append({'readings':lin['readings'],'sensors':lin['sensors']+[sensor_row]})
     if len(joined)>MAX_ROWS:raise ValueError('连接结果超过10000行，请缩小输入；未保存部分结果')
   reads+=len(rows)+len(dataset['sensors']);rows=joined;lineage=joined_lineage;detail={'build_rows':len(dataset['sensors']),'hash_buckets':len(buckets),'probe_rows':probes,'semantics':'inner join; duplicate right keys retain multiplicity'}
  elif step['op']=='group':
   grouped=defaultdict(list);keys=step['keys'];agg=step['aggregate']
   for row,lin in zip(rows,lineage):grouped[tuple(row[k] for k in keys)].append((row,lin))
   reads+=len(rows);pairs=[]
   for key,members in grouped.items():
    values=[Decimal(str(member[0]['value'])) for member in members]
    value=len(values) if agg=='count' else float(sum(values)) if agg=='sum' else float(sum(values)/len(values))
    out={**dict(zip(keys,key)),agg:round(value,6) if isinstance(value,float) else value}
    lin={'readings':[x for _,l in members for x in l['readings']],'sensors':[x for _,l in members for x in l['sensors']]}
    pairs.append((out,lin))
   pairs.sort(key=lambda p:json.dumps(p[0],sort_keys=True,ensure_ascii=False));rows=[p[0] for p in pairs];lineage=[p[1] for p in pairs];detail={'groups':len(rows),'aggregate':agg,'accumulator':'decimal from source string; rounded 6 decimals'}
  trace.append({'op':step['op'],'input_rows':before,'output_rows':len(rows),'duration_ms':round((time.perf_counter()-started)*1000,4),'detail':detail,'checksum':checksum(rows),'preview':rows[:5]})
 return rows,lineage,trace,reads,round((time.perf_counter()-total_started)*1000,4)
def _result(rows,trace,reads,duration):
 return {'operators':trace,'output':rows,'output_rows':len(rows),'checksum':checksum(rows),'row_visits':reads,'duration_ms':duration,'limits':{'max_readings':2000,'max_sensors':100,'max_join_rows':10000,'max_stages':6},'model':'Python teaching scan/filter/hash join/group engine; PostgreSQL persists business metadata only'}
def execute(dataset,steps):
 rows,_lineage,trace,reads,duration=_run(dataset,steps)
 return _result(rows,trace,reads,duration)
def build_evidence(lineage):
 """Bound per-output-row source lineage to 64KB canonical JSON; degrade full->counts->summary.
 Sources are always fully scanned: totals and per-group counts stay exact at every level."""
 rows_full=[];total_readings=total_sensors=0
 for i,lin in enumerate(lineage):
  rd,sn=lin['readings'],lin['sensors']
  entries=[[r,s] for r,s in zip(rd,sn)] if sn else [[r] for r in rd]
  total_readings+=len(rd);total_sensors+=len(sn)
  rows_full.append({'row':i,'entries':entries})
 base={'version':1,'capacity_bytes':EVIDENCE_CAPACITY,'output_rows':len(rows_full),'totals':{'readings':total_readings,'sensors':total_sensors},'checksum':checksum(rows_full)}
 candidates=[('full',rows_full),('counts',[{'row':r['row'],'readings':len(r['entries']),'sensors':sum(1 for e in r['entries'] if len(e)>1)} for r in rows_full]),('summary',None)]
 for level,rows in candidates:
  ev=dict(base);ev['level']=level;ev['degraded']=level!='full'
  if rows is not None:ev['rows']=rows
  ev['bytes']=0
  while True:
   size=len(_canonical(ev))
   if size==ev['bytes']:break
   ev['bytes']=size
  if size<=EVIDENCE_CAPACITY:return ev
 raise ValueError('追溯证据无法装入64KB容量')
def execute_with_evidence(dataset,steps):
 """Execute and also return immutable source-lineage evidence for the final output rows."""
 rows,lineage,trace,reads,duration=_run(dataset,steps)
 return _result(rows,trace,reads,duration),build_evidence(lineage)
