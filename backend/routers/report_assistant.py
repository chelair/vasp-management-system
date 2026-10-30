from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from envelope import ok
from routers.ai_chat import actor, guard
import report_background as work


def private(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/reports/assistant', tags=['project-reports'], dependencies=[Depends(private)])


class WorkBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['generate', 'notes', 'comment', 'chat']
    request_id: str = Field(min_length=8, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    connection_id: str | None = Field(default=None, min_length=1, max_length=64)
    report_id: str | None = Field(default=None, min_length=1, max_length=160)
    comment_id: str | None = Field(default=None, min_length=1, max_length=64)
    keys: list[str] | None = Field(default=None, min_length=1)
    content: str = Field(default='', max_length=16000)

    @model_validator(mode='after')
    def required_values(self):
        if self.action == 'comment' and not self.comment_id:
            raise ValueError('请选择需要处理的批注')
        if self.action == 'chat' and not self.content.strip():
            raise ValueError('请输入补充要求或问题')
        return self


@router.get('/{scope}')
@guard
def get_work(scope: str, request: Request):
    user, _ = actor(request)
    return ok('查询成功', work.state(user, scope))


@router.post('/{scope}')
@guard
def start_work(scope: str, request: Request, body: WorkBody):
    user, _ = actor(request)
    return ok('已交给后台处理', work.start(user, scope, body.model_dump(exclude_none=True)))


@router.delete('/{scope}/drafts/{run_id}/{key:path}')
@guard
def discard_draft(scope: str, run_id: str, key: str, request: Request):
    user, _ = actor(request)
    work.dismiss(user, scope, run_id, key)
    return ok('草稿已移除', {})
