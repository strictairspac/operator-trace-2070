import json
from fastapi import APIRouter,Depends,Query
from fastapi.responses import Response
from src.middlewares.auth import current,writer
from src.schemas.business import TraceInput
from src.services import traces
from src.controllers.business import start_trace
router=APIRouter()
@router.get('/traces')
def listing(u=Depends(current)):return traces.list_items()
@router.post('/traces')
def create(data:TraceInput,u=Depends(writer)):return start_trace(data,u)
@router.get('/traces/{item_id}')
def detail(item_id:int,u=Depends(current)):return traces.detail(item_id)
@router.get('/traces/{item_id}/lineage')
def lineage(item_id:int,row:int=Query(0,ge=0),cursor:str|None=Query(None),limit:int=Query(50,ge=1,le=200),u=Depends(current)):return traces.lineage(item_id,row,cursor,limit)
@router.get('/traces/{item_id}/export')
def export(item_id:int,u=Depends(current)):
 return Response(json.dumps(traces.detail(item_id),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="trace-{item_id}.json"'})
