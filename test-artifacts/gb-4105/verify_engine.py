"""Engine-level verification: lineage correctness, duplicate semantics, 64KB degradation, determinism.

Run: /tmp/gb4105/venv/bin/python verify_engine.py   (cwd must allow `import src`, set PYTHONPATH=backend)
"""
import json,sys,importlib.util

sys.path.insert(0,'/workspace/backend')
from src.services import operators as O

PASS=[];FAIL=[]
def check(name,cond,info=''):
 (PASS if cond else FAIL).append(name)
 print(('PASS' if cond else 'FAIL'),name,info if not cond else '')

# 1. Regression: new execute() must be byte-identical to the pre-change implementation.
spec=importlib.util.spec_from_file_location('operators_orig','/tmp/gb4105/operators_orig.py')
orig=importlib.util.module_from_spec(spec);sys.path.insert(0,'/workspace/backend');spec.loader.exec_module(orig)
datasets=[
 {'sensors':[{'sensor_id':i,'zone':['北场','南场','试验间'][i%3],'device_type':['pump','motor','valve'][i%3]} for i in range(1,13)],
  'readings':[{'sensor_id':i%12+1,'value':round(25+(i*13%800)/10,1),'recorded_at':f'2026-11-17T{8+i//60:02d}:{i%60:02d}:00'} for i in range(240)]},
 {'sensors':[],'readings':[]},
 {'sensors':[{'sensor_id':1,'zone':'北场','device_type':'pump'},{'sensor_id':1,'zone':'复核点','device_type':'pump'}],
  'readings':[{'sensor_id':1,'value':80,'recorded_at':'2026-11-17T09:00:00'}]},
]
plans=[
 [{'op':'scan','source':'readings'},{'op':'filter','field':'value','compare':'gte','value':50},{'op':'hash_join','right':'sensors','left_key':'sensor_id','right_key':'sensor_id'},{'op':'group','keys':['zone'],'measure':'value','aggregate':'avg'}],
 [{'op':'scan','source':'readings'}],
 [{'op':'scan','source':'readings'},{'op':'filter','field':'sensor_id','compare':'eq','value':1},{'op':'hash_join','right':'sensors','left_key':'sensor_id','right_key':'sensor_id'},{'op':'group','keys':['zone','device_type'],'measure':'value','aggregate':'sum'}],
]
def strip_timing(x):
 x=json.loads(json.dumps(x,default=str))
 if isinstance(x,dict):
  x.pop('duration_ms',None)
  for op in x.get('operators',[]):op.pop('duration_ms',None)
 return x
same=True
for d in datasets:
 for p in plans:
  try:a=orig.execute(d,p)
  except Exception as e:a=('ERR',str(e))
  try:b=O.execute(d,p)
  except Exception as e:b=('ERR',str(e))
  if json.dumps(strip_timing(a),sort_keys=True,ensure_ascii=False)!=json.dumps(strip_timing(b),sort_keys=True,ensure_ascii=False):same=False
check('execute() 与改动前实现输出一致（回归，剔除耗时）',same)

# 2. Duplicates: same key+value rows each count once; join multiplicity preserved; order deterministic.
dup={'sensors':[{'sensor_id':1,'zone':'北场','device_type':'pump'},{'sensor_id':1,'zone':'北场','device_type':'pump'}],
     'readings':[{'sensor_id':1,'value':80,'recorded_at':'t1'},{'sensor_id':1,'value':80,'recorded_at':'t1'},{'sensor_id':1,'value':80,'recorded_at':'t2'}]}
plan=[{'op':'scan','source':'readings'},{'op':'hash_join','right':'sensors','left_key':'sensor_id','right_key':'sensor_id'},{'op':'group','keys':['zone'],'measure':'value','aggregate':'count'}]
result,evidence=O.execute_with_evidence(dup,plan)
check('重复键分组 count=6（3读×2传感器）',result['output']==[{'zone':'北场','count':6}],result['output'])
check('证据级别 full',evidence['level']=='full')
entries=evidence['rows'][0]['entries']
check('同键同值重复行各算一份（readings 1,1,2,2,3,3）',[e[0] for e in entries]==[1,1,2,2,3,3],entries)
check('连接倍数保留（sensors 1,2,1,2,1,2）',[e[1] for e in entries]==[1,2,1,2,1,2],entries)
check('证据字节数自报准确',evidence['bytes']==len(json.dumps(evidence,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()))
check('证据容量不超限',evidence['bytes']<=65536)
r2,e2=O.execute_with_evidence(dup,plan)
check('重跑行号与顺序不变（确定性）',e1:=evidence['checksum']==e2['checksum'] and evidence['rows']==e2['rows'])

# 3. No-join plan: entries carry reading rows only.
res3,ev3=O.execute_with_evidence(datasets[0],[{'op':'scan','source':'readings'},{'op':'filter','field':'value','compare':'gte','value':50}])
first=ev3['rows'][0]['entries'][0]
check('无连接时条目仅含 readings 行号',len(first)==1 and ev3['totals']['sensors']==0 and ev3['totals']['readings']==res3['output_rows'])

# 4. counts degradation: 2000 readings x 5 duplicate sensors = 10000 entries in one group.
big={'sensors':[{'sensor_id':1,'zone':'北场','device_type':'pump'} for _ in range(5)],
     'readings':[{'sensor_id':1,'value':80,'recorded_at':f't{i}'} for i in range(2000)]}
plan_join_group=[{'op':'scan','source':'readings'},{'op':'hash_join','right':'sensors','left_key':'sensor_id','right_key':'sensor_id'},{'op':'group','keys':['zone'],'measure':'value','aggregate':'count'}]
res4,ev4=O.execute_with_evidence(big,plan_join_group)
check('超64KB降级为 counts',ev4['level']=='counts' and ev4['degraded'])
check('counts 级来源查全：readings=10000 sensors=10000',ev4['totals']=={'readings':10000,'sensors':10000},ev4['totals'])
check('counts 级逐组计数精确',ev4['rows']==[{'row':0,'readings':10000,'sensors':10000}],ev4['rows'])
check('counts 级容量不超限',ev4['bytes']<=65536,ev4['bytes'])

# 5. summary degradation: 10000 output rows without group -> per-row counts also exceed 64KB.
res5,ev5=O.execute_with_evidence(big,[{'op':'scan','source':'readings'},{'op':'hash_join','right':'sensors','left_key':'sensor_id','right_key':'sensor_id'}])
check('再超降级为 summary',ev5['level']=='summary' and 'rows' not in ev5)
check('summary 级来源查全：totals 精确',ev5['totals']=={'readings':10000,'sensors':10000} and ev5['output_rows']==10000)
check('summary 级容量不超限',ev5['bytes']<=65536,ev5['bytes'])

# 6. checksum commits to full lineage even when degraded.
manual=[[[i//5+1,i%5+1] for i in range(10000)]]
import hashlib
expect=hashlib.sha256(json.dumps([{'row':0,'entries':manual[0]}],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
check('降级证据 checksum 仍锚定完整血缘',ev4['checksum']==expect)

# 7. Empty input: full level, zero rows.
res7,ev7=O.execute_with_evidence({'sensors':[],'readings':[]},plan_join_group)
check('空输入：full 级空证据',ev7['level']=='full' and ev7['rows']==[] and ev7['totals']=={'readings':0,'sensors':0})

print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
sys.exit(1 if FAIL else 0)
