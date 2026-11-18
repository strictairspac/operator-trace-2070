"""API-level verification: real HTTP via TestClient, SQLite for persistence, fakeredis for the queue.

Covers: schema migration on an old DB, atomic completion (result+evidence), write-failure -> failed,
cursor pagination (resume + stable retry), 64KB degradation levels, immutable evidence after source
edits, pre-feature traces marked missing, and access control.

Run: /tmp/gb4105/venv/bin/python verify_api.py
"""
import os,sys,json
os.environ['DATABASE_URL']='sqlite:////tmp/gb4105/verify.db'
os.environ['REDIS_URL']='redis://localhost:6379/15'
os.environ['JWT_SECRET']='gb4105-verify-secret'
os.environ['SEED_DEMO']='true'
sys.path.insert(0,'/workspace/backend')

import redis,fakeredis
_server=fakeredis.FakeServer()
redis.Redis.from_url=classmethod(lambda cls,url,**kw: fakeredis.FakeRedis(server=_server))

# Fresh DB file per run.
if os.path.exists('/tmp/gb4105/verify.db'):os.remove('/tmp/gb4105/verify.db')

PASS=[];FAIL=[]
def check(name,cond,info=''):
 (PASS if cond else FAIL).append(name)
 print(('PASS' if cond else 'FAIL'),name,('-> '+str(info)[:300]) if not cond else '')

# 1. Migration: build an old-schema DB (no traces.evidence), then migrate().
from sqlalchemy import inspect,text
from src.config.database import Base,engine,Session
from src.models import identity,dataset,plan  # register all tables before create_all
from src.models.trace import Trace
Base.metadata.create_all(engine)
with engine.begin() as c:c.execute(text('ALTER TABLE traces DROP COLUMN evidence'))
assert 'evidence' not in {col['name'] for col in inspect(engine).get_columns('traces')}
from src.config.migrate import migrate
migrate();migrate()  # idempotent
check('迁移为旧库补上 traces.evidence（幂等）','evidence' in {col['name'] for col in inspect(engine).get_columns('traces')})

from fastapi.testclient import TestClient
from src.main import app
from src import worker

client=TestClient(app)
client.__enter__()  # runs lifespan: migrate() (no-op now) + seed

def login(email):
 r=client.post('/auth/login',json={'email':email,'password':'Trace2026!'})
 assert r.status_code==200,r.text
 return {'Authorization':'Bearer '+r.json()['token']}
op=login('operator@operator.local');view=login('viewer@operator.local')

def run_trace(name,dataset,steps):
 r=client.post('/datasets',json={'name':name+'-ds','description':'verify','sensors':dataset['sensors'],'readings':dataset['readings']},headers=op)
 assert r.status_code==200,r.text
 ds=r.json()['id']
 r=client.post('/plans',json={'name':name+'-plan','dataset_id':ds,'steps':steps,'note':'verify'},headers=op)
 assert r.status_code==200,r.text
 plan=r.json()['id']
 r=client.post('/traces',json={'name':name,'plan_id':plan},headers=op)
 assert r.status_code==200,r.text
 tid=r.json()['id']
 worker.process(tid)
 return tid,ds

# 2. Duplicates: same key+value rows each count once, via HTTP.
dup={'sensors':[{'sensor_id':1,'zone':'北场','device_type':'pump'},{'sensor_id':1,'zone':'北场','device_type':'pump'}],
     'readings':[{'sensor_id':1,'value':80,'recorded_at':'t1'},{'sensor_id':1,'value':80,'recorded_at':'t1'},{'sensor_id':1,'value':80,'recorded_at':'t2'}]}
steps_dup=[{'op':'scan','source':'readings'},{'op':'hash_join','right':'sensors','left_key':'sensor_id','right_key':'sensor_id'},{'op':'group','keys':['zone'],'measure':'value','aggregate':'count'}]
tid,ds=run_trace('v-dup',dup,steps_dup)
with Session() as s:
 t=s.get(Trace,tid)
 check('结果与证据都落库才标 completed',t.status=='completed' and t.result is not None and t.evidence is not None)
 check('证据级别 full',t.evidence['level']=='full' and t.evidence['bytes']<=65536)
r=client.get(f'/traces/{tid}/lineage?row=0&limit=200',headers=op)
check('追溯接口 200',r.status_code==200,r.text)
data=r.json()
check('同键同值重复行各算一份',[e['reading_row'] for e in data['entries']]==[1,1,2,2,3,3],data['entries'])
check('传感器行号保留连接倍数',[e['sensor_row'] for e in data['entries']]==[1,2,1,2,1,2])
check('条目序号从1连续编号',[e['n'] for e in data['entries']]==list(range(1,7)))

# 3. Pagination: walk by cursor, union equals single shot; retry returns identical bytes; resume works.
big={'sensors':[{'sensor_id':1,'zone':'北场','device_type':'pump'}],
     'readings':[{'sensor_id':1,'value':60+i%40,'recorded_at':f't{i}'} for i in range(120)]}
tid2,ds2=run_trace('v-page',big,[{'op':'scan','source':'readings'},{'op':'hash_join','right':'sensors','left_key':'sensor_id','right_key':'sensor_id'},{'op':'group','keys':['zone'],'measure':'value','aggregate':'count'}])
one=client.get(f'/traces/{tid2}/lineage?row=0&limit=200',headers=op).json()
check('单页取全 120 条',one['total_entries']==120 and len(one['entries'])==120)
pages=[];cursor=None
while True:
 q=f'/traces/{tid2}/lineage?row=0&limit=50'+('&cursor='+cursor if cursor else '')
 resp=client.get(q,headers=op).json()
 pages.append(resp)
 cursor=resp['page']['next_cursor']
 if not cursor:break
check('游标翻页共3页（50+50+20）',[len(p['entries']) for p in pages]==[50,50,20],[len(p['entries']) for p in pages])
merged=[e for p in pages for e in p['entries']]
check('翻页不重跑计划：合并与单页完全一致',merged==one['entries'])
q2=f'/traces/{tid2}/lineage?row=0&limit=50&cursor='+pages[0]['page']['next_cursor']
again=client.get(q2,headers=op);again2=client.get(q2,headers=op)
check('重试同游标返回逐字节相同',again.content==again2.content and again.json()==pages[1])
check('中断后按游标恢复到原位置',again.json()['entries'][0]['n']==51 and again.json()['page']['offset']==50)
bad=client.get(f'/traces/{tid2}/lineage?row=0&cursor=%%%',headers=op)
check('非法游标 400',bad.status_code==400)
oor=client.get(f'/traces/{tid2}/lineage?row=99',headers=op)
check('输出分组越界 404',oor.status_code==404)

# 4. Immutability: edit source dataset after execution; evidence must still reflect that run.
before=client.get(f'/traces/{tid2}/lineage?row=0&limit=200',headers=op).content
r=client.put(f'/datasets/{ds2}',json={'name':'v-page-ds','description':'changed','sensors':[{'sensor_id':9,'zone':'南场','device_type':'valve'}],'readings':[{'sensor_id':9,'value':1,'recorded_at':'x'}]},headers=op)
check('源表可正常修改',r.status_code==200,r.text)
after=client.get(f'/traces/{tid2}/lineage?row=0&limit=200',headers=op).content
check('源表改动后证据仍按该次执行解释',before==after)

# 5. Degradation via API: counts level and summary level, sources fully counted.
huge={'sensors':[{'sensor_id':1,'zone':'北场','device_type':'pump'} for _ in range(5)],
      'readings':[{'sensor_id':1,'value':80,'recorded_at':f't{i}'} for i in range(2000)]}
tid3,_=run_trace('v-counts',huge,steps_dup)
d3=client.get(f'/traces/{tid3}/lineage?row=0',headers=op).json()
check('超64KB降级 counts 且计数精确',d3['level']=='counts' and d3['degraded'] and d3['row_counts']=={'readings':10000,'sensors':10000} and d3['entries'] is None,d3.get('row_counts'))
check('counts 级提示来源已查全','完整扫描' in (d3['notice'] or ''))
tid4,_=run_trace('v-summary',huge,[{'op':'scan','source':'readings'},{'op':'hash_join','right':'sensors','left_key':'sensor_id','right_key':'sensor_id'}])
d4=client.get(f'/traces/{tid4}/lineage?row=0',headers=op).json()
check('再超降级 summary 且 totals 精确',d4['level']=='summary' and d4['totals']=={'readings':10000,'sensors':10000} and d4['entries'] is None)

# 6. Pre-feature trace: evidence NULL -> opens as usual, marked missing.
with Session() as s:
 t=s.get(Trace,tid2);t.evidence=None;s.commit()
r=client.get(f'/traces/{tid2}',headers=op)
check('旧剖面照常打开（详情 200）',r.status_code==200 and r.json()['evidence'] is None)
d5=client.get(f'/traces/{tid2}/lineage?row=0',headers=op)
check('旧剖面标明缺少来源',d5.status_code==200 and d5.json()['level']=='missing' and '缺少来源' in d5.json()['notice'])
r=client.get(f'/traces/{tid2}/export',headers=op)
check('旧剖面导出正常',r.status_code==200)

# 7. Atomicity: failing the completing write marks the trace failed, no partial result.
import sqlalchemy.orm as orm
orig_commit=orm.Session.commit
calls={'n':0}
def flaky(self):
 calls['n']+=1
 if calls['n']==2:raise RuntimeError('simulated write failure')
 return orig_commit(self)
tid5,_=run_trace('v-atomic',dup,steps_dup[:-1])  # queued only? no: run_trace already processed it
# create a fresh queued trace and process it under the flaky commit
r=client.post('/traces',json={'name':'v-atomic-2','plan_id':[p for p in client.get('/plans',headers=op).json() if p['name']=='v-atomic-plan'][0]['id']},headers=op)
tid6=r.json()['id']
orm.Session.commit=flaky
try:worker.process(tid6)
finally:orm.Session.commit=orig_commit
with Session() as s:
 t=s.get(Trace,tid6)
 check('写入失败时标记失败',t.status=='failed' and 'simulated write failure' in (t.error or ''),t.status)
 check('失败不留部分结果/证据',t.result is None and t.evidence is None)

# 8. Not-completed trace -> 409; access control.
r=client.post('/traces',json={'name':'v-queued','plan_id':[p for p in client.get('/plans',headers=op).json() if p['name']=='v-atomic-plan'][0]['id']},headers=op)
q=client.get(f"/traces/{r.json()['id']}/lineage?row=0",headers=op)
check('未完成执行 409',q.status_code==409)
check('viewer 只读可查来源',client.get(f'/traces/{tid3}/lineage?row=0',headers=view).status_code==200)
check('未登录 401',client.get(f'/traces/{tid3}/lineage?row=0').status_code==401)
check('viewer 写接口 403',client.post('/traces',json={'name':'v-x','plan_id':1},headers=view).status_code==403)

client.__exit__(None,None,None)
print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
sys.exit(1 if FAIL else 0)
