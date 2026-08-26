"""Pydantic 输入模型（对齐参考实现 schemas.py 的 add_project 规则）。"""

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dates import is_valid_date

TaskStatus = Literal[
    "pending", "queued", "running", "completed", "zombied", "archived"
]

#: v0.3.0：任务类型固定四种，流程通过 group 元数据组织
TaskType = Literal["opt", "frac", "neb", "ele"]
EleSubtype = Literal["pdos", "bader", "diff_charge", "work_function"]


class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: TaskType
    model_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_@]*$")
    subtype: Optional[EleSubtype] = None
    status: Optional[TaskStatus] = None

    @field_validator("subtype")
    @classmethod
    def _subtype_requires_ele(cls, value, info):
        task_type = info.data.get("task_type")
        if value is not None and task_type != "ele":
            raise ValueError("subtype 仅在任务类型为 ele 时允许填写")
        return value


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_]*$")
    deadline: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    server: str = Field(min_length=1)
    tasks: List[TaskIn] = Field(min_length=1)
    # Web 端扩展字段（原 Schema additionalProperties=false 之外显式放行）
    description: Optional[str] = None
    estimated_hours: Optional[Union[int, float]] = None

    @field_validator("deadline")
    @classmethod
    def _check_deadline(cls, value: str) -> str:
        if not is_valid_date(value):
            raise ValueError(f"不是合法日期 '{value}'")
        return value


class AddProjectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["add_project"]
    project: ProjectIn
