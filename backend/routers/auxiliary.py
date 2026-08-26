"""辅助分子全局接口（跨项目统一调用，文件存于本地固定位置）。"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aux_molecules import add_aux_molecule, list_aux_molecules
from envelope import fail, ok

router = APIRouter(prefix="/aux-molecules", tags=["aux-molecules"])


class AuxPayload(BaseModel):
    label: str = Field(min_length=1)


@router.get("")
def list_aux():
    try:
        return ok("查询成功", {"molecules": list_aux_molecules()})
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"查询辅助分子失败：{e}"))


@router.post("")
def create_aux(payload: AuxPayload):
    """新增辅助分子：创建全局 opt/frac 目录与默认输入文件。"""
    try:
        entry = add_aux_molecule(payload.label)
        return ok("辅助分子已添加", entry)
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"添加辅助分子失败：{e}"))
