"""R3 local discovery, deterministic evaluation and frozen data-requirement reports."""
from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from envelope import ok, fail
from storage import load_db
import properties

router = APIRouter(prefix='/properties', tags=['scientific-properties'])


def _call(function, *args, **kwargs):
    try: return ok('查询成功',function(*args,**kwargs))
    except LookupError as exc: return JSONResponse(status_code=404,content=fail(str(exc)))
    except (ValueError,TypeError) as exc: return JSONResponse(status_code=400,content=fail(str(exc)))


@router.get('/recipes')
def recipes(): return ok('查询成功',properties.schema())


@router.get('/discover')
def discover(request: Request, project_ids: list[str] = Query(), query: str = '', task_type: str | None = None, task_id: str | None = None):
    return _call(properties.discover,load_db(),getattr(request.state,'user',None),project_ids,query,task_type,task_id)


@router.post('/evaluate')
def evaluate(request: Request, payload: dict = Body()):
    return _call(properties.evaluate,load_db(),getattr(request.state,'user',None),payload,persist=True)


@router.get('/reports/{report_id}')
def read_report(report_id: str, request: Request):
    return _call(properties.read_report,load_db(),getattr(request.state,'user',None),report_id)
