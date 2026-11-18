import json,base64
import redis
from fastapi import HTTPException
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models.dataset import Dataset
from src.models.plan import Plan
from src.models.trace import Trace
from src.utils.serialization import record
queue=redis.Redis.from_url(REDIS_URL)
def list_items():
 with Session() as s:return [record(r) for r in s.query(Trace).order_by(Trace.id.desc()).limit(100).all()]
def detail(item_id):
 with Session() as s:
  row=s.get(Trace,item_id)
  if not row:raise HTTPException(404,'未找到执行轨迹')
  return record(row)
def create(data):
 with Session() as s:
  p=s.get(Plan,data.plan_id)
  if not p:raise HTTPException(404,'未找到算子计划')
  d=s.get(Dataset,p.dataset_id)
  row=Trace(name=data.name,plan_id=p.id,dataset_id=d.id,status='queued',snapshot={'dataset':record(d),'plan':record(p)})
  s.add(row);s.commit();s.refresh(row);result=record(row)
 try:queue.rpush('operator-traces',result['id'])
 except redis.RedisError:
  with Session() as s:r=s.get(Trace,result['id']);r.status='failed';r.error='队列不可用，请创建新任务';s.commit()
  raise HTTPException(503,'队列不可用，请稍后重试')
 return result
def _encode_cursor(offset):return base64.urlsafe_b64encode(json.dumps({'o':offset},separators=(',',':')).encode()).decode().rstrip('=')
def _decode_cursor(cursor):
 try:
  offset=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))['o']
  if not isinstance(offset,int) or isinstance(offset,bool) or offset<0:raise ValueError()
  return offset
 except Exception:raise HTTPException(400,'无效的翻页游标，请从第一页重新翻查')
def lineage(item_id,row,cursor,limit):
 """Page source row numbers for one output group from the stored evidence; never re-executes the plan."""
 with Session() as s:
  t=s.get(Trace,item_id)
  if not t:raise HTTPException(404,'未找到执行轨迹')
  if t.status!='completed' or not t.result:raise HTTPException(409,'执行尚未完成，完成后再翻查来源')
  result,evidence=t.result,t.evidence
  base={'trace_id':t.id,'trace_name':t.name,'status':t.status}
 if evidence is None:
  return {**base,'level':'missing','degraded':True,'row':row,'output':None,'entries':None,'row_counts':None,'page':None,'notice':'该剖面创建于来源追溯上线前，缺少来源证据；结果与摘要不受影响'}
 output=result.get('output') or []
 if not 0<=row<len(output):raise HTTPException(404,'输出分组不存在')
 base.update(level=evidence['level'],degraded=evidence['degraded'],capacity_bytes=evidence['capacity_bytes'],evidence_bytes=evidence.get('bytes'),row=row,output=output[row],output_rows=len(output),totals=evidence['totals'],checksum=evidence['checksum'])
 if evidence['level']=='summary':
  return {**base,'entries':None,'row_counts':None,'page':None,'notice':'追溯证据超过64KB，已降级为全局汇总；来源已完整扫描，未保留逐组行号'}
 entry=next((r for r in evidence['rows'] if r['row']==row),None)
 if entry is None:raise HTTPException(404,'输出分组缺少来源明细')
 if evidence['level']=='counts':
  return {**base,'entries':None,'row_counts':{'readings':entry['readings'],'sensors':entry['sensors']},'page':None,'notice':'追溯证据超过64KB，已降级为精确计数；来源已完整扫描'}
 entries=entry['entries'];total=len(entries);offset=_decode_cursor(cursor) if cursor else 0
 chunk=entries[offset:offset+limit]
 items=[{'n':offset+i+1,'reading_row':e[0],'sensor_row':e[1] if len(e)>1 else None} for i,e in enumerate(chunk)]
 next_cursor=_encode_cursor(offset+limit) if offset+limit<total else None
 return {**base,'total_entries':total,'entries':items,'row_counts':{'readings':total,'sensors':sum(1 for e in entries if len(e)>1)},'page':{'offset':offset,'limit':limit,'returned':len(chunk),'next_cursor':next_cursor},'notice':None}
