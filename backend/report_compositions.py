"""R2-B：组合（Composition）存储、校验与自包含 HTML 导出。

只做"项目内、只读证据 → 手工组合"的最小闭环：

- 存储在 `data/reports/compositions/<项目>/<composition_id>.json`，与完整报告
  `report_store` 的索引/单份清理**完全隔离**（不同命名空间，不碰旧报告）；
- 保存时由后端按合法 ID 重新解析 Evidence，前端不能伪造科学 payload / 渲染器 / 路径；
- 证据版本冻结：版本不一致返回 `evidence_stale`，必须显式 `refresh_evidence` 才接受；
- 预览与导出都用**存下来的同一份** Evidence（导出不重新解析）；
- 文本元素走既有安全 Markdown（R1 已加固），不接受 HTML/脚本。

尚未覆盖（明确留给 R2-C/D）：前端编辑器、拖拽/画布、3Dmol 交互视图、NEB/自由能/
PDOS/Bader/功函数的组合渲染与导出。
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR
from dates import now_iso
from report_blocks import (
    BLOCK_TYPES,
    MAX_BLOCKS,
    SCHEMA_VERSION,
    block_id,
    check_text,
    check_title,
    is_text_block,
    new_text_block_id,
    normalize_options,
    resolve_evidence,
    UnsupportedEvidence,
)
from report_charts import energy_force_chart
from report_export import markdown_to_html

COMPOSITIONS_DIR = DATA_DIR / "reports" / "compositions"
MAX_COMPOSITIONS_PER_PROJECT = 50
_LOCK = threading.RLock()
_ID_RE = re.compile(r"^cmp_[0-9a-f]{12}$")


class EvidenceStale(Exception):
    """保存时证据版本与提交时不一致：需要显式刷新。"""

    def __init__(self, changes: List[Dict[str, Any]]):
        super().__init__("证据版本已变化")
        self.changes = changes


def _safe_name(value: str) -> str:
    keep = [c if (c.isalnum() or c in "-_@.") else "_" for c in str(value)]
    return "".join(keep) or "project"


def _project_dir(project_name: str) -> Path:
    return COMPOSITIONS_DIR / _safe_name(project_name)


def _path(project_name: str, composition_id: str) -> Path:
    return _project_dir(project_name) / f"{composition_id}.json"


def _read(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------ 组合构建


def _claimed_version(raw: Dict[str, Any], evidence_id_value: str) -> str:
    refs = raw.get("source_refs")
    if not isinstance(refs, list):
        return ""
    for ref in refs:
        if isinstance(ref, dict) and str(ref.get("evidence_id")) == evidence_id_value:
            return str(ref.get("version") or "")
    return ""


def build_composition(
    project: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    composition_id: str = "",
    revision: int = 1,
    created_at: str = "",
    merged: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """按提交的顺序重建组合；证据一律由后端解析，客户端只提供 ID 与展示选项。"""
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是对象")
    title = check_title(payload.get("title"))
    raw_blocks = payload.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError("组合至少需要一个元素")
    if len(raw_blocks) > MAX_BLOCKS:
        raise ValueError(f"元素过多（最多 {MAX_BLOCKS} 个）")

    project_id = str(project.get("project_id") or project.get("name") or "")
    project_name = str(project.get("name") or "")
    refresh_evidence = bool(payload.get("refresh_evidence"))
    moment = now or datetime.now().astimezone()

    blocks: List[Dict[str, Any]] = []
    evidence_map: Dict[str, Dict[str, Any]] = {}
    seen_ids: set[str] = set()
    stale: List[Dict[str, Any]] = []

    for raw in raw_blocks:
        if not isinstance(raw, dict):
            raise ValueError("blocks 里的元素必须是对象")
        block_type = str(raw.get("type") or "")
        spec = BLOCK_TYPES.get(block_type)
        if spec is None:
            raise ValueError(f"未知元素类型：{block_type}")
        options = normalize_options(raw.get("options"))
        block_title = str(raw.get("title") or "").strip()
        if len(block_title) > 200:
            raise ValueError("元素标题过长")

        if is_text_block(block_type):
            text = check_text(raw.get("text"))
            if not text.strip():
                raise ValueError("文本元素不能为空")
            bid = str(raw.get("block_id") or "") or new_text_block_id()
            if not bid.startswith("blk_txt_"):
                raise ValueError("文本元素的 block_id 非法")
            if bid in seen_ids:
                raise ValueError(f"重复的元素 ID：{bid}")
            seen_ids.add(bid)
            blocks.append(
                {
                    "block_id": bid,
                    "type": block_type,
                    "type_label": spec["label"],
                    "title": block_title or "分析文本",
                    "project_id": project_id,
                    "task_id": "",
                    "group_id": "",
                    "variant": "",
                    "renderer": "text",
                    "options": options,
                    "text": text,
                    "source_refs": [],
                    "data_status": "available",
                    "validation_status": "NOT_TESTED",
                }
            )
            continue

        task_id = str(raw.get("task_id") or "")
        group_id = str(raw.get("group_id") or "")
        variant = str(raw.get("variant") or "")
        expected_id = block_id(
            project_id, block_type, task_id=task_id, group_id=group_id, variant=variant
        )
        declared = str(raw.get("block_id") or "")
        if declared and declared != expected_id:
            raise ValueError("block_id 与元素类型/任务不匹配（不允许借用其他任务的稳定 ID）")
        if expected_id in seen_ids:
            raise ValueError(f"重复的元素 ID：{expected_id}（同一元素只能添加一次）")
        seen_ids.add(expected_id)

        try:
            evidence = resolve_evidence(
                project,
                block_type,
                task_id=task_id,
                group_id=group_id,
                merged=merged,
                now=moment,
            )
        except UnsupportedEvidence as exc:
            raise ValueError(str(exc)) from exc

        claimed = _claimed_version(raw, str(evidence["evidence_id"]))
        if claimed and claimed != evidence["version"]:
            stale.append(
                {
                    "block_id": expected_id,
                    "evidence_id": evidence["evidence_id"],
                    "claimed": claimed,
                    "current": evidence["version"],
                }
            )
        evidence_map[str(evidence["evidence_id"])] = evidence
        blocks.append(
            {
                "block_id": expected_id,
                "type": block_type,
                "type_label": spec["label"],
                "title": block_title or str(evidence.get("title") or spec["label"]),
                "project_id": project_id,
                "task_id": task_id,
                "group_id": group_id,
                "variant": variant,
                "renderer": spec["renderer"],
                "options": options,
                "text": "",
                "source_refs": [
                    {"evidence_id": evidence["evidence_id"], "version": evidence["version"]}
                ],
                "data_status": evidence["availability"],
                "validation_status": (evidence.get("validation") or {}).get("status") or "UNKNOWN",
            }
        )

    if stale and not refresh_evidence:
        raise EvidenceStale(stale)

    block_ids = [item["block_id"] for item in blocks]
    hidden = _id_list(payload.get("hidden_block_ids"), "hidden_block_ids", block_ids)
    deleted = _id_list(payload.get("deleted_block_ids"), "deleted_block_ids", block_ids)
    groups = _groups(payload.get("groups"), block_ids, set(deleted))

    doc = {
        "schema_version": SCHEMA_VERSION,
        "composition_id": composition_id or ("cmp_" + uuid.uuid4().hex[:12]),
        "project_id": project_id,
        "project_name": project_name,
        "title": title,
        "revision": int(revision),
        "created_at": created_at or now_iso(),
        "updated_at": now_iso(),
        "blocks": blocks,
        "evidence": evidence_map,
        "groups": groups,
        "hidden_block_ids": hidden,
        "deleted_block_ids": deleted,
    }
    return doc


def _id_list(value: Any, name: str, block_ids: List[str]) -> List[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} 必须是数组")
    allowed = set(block_ids)
    result: List[str] = []
    for item in value:
        text = str(item or "")
        if text not in allowed:
            raise ValueError(f"{name} 里有不存在的元素：{text}")
        if text not in result:
            result.append(text)
    return result


def _groups(value: Any, block_ids: List[str], deleted: set) -> List[Dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ValueError("groups 必须是数组")
    allowed = {item for item in block_ids}
    groups: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError("groups 里的分组必须是对象")
        group_id = str(raw.get("group_id") or f"g{index + 1}")
        if group_id in seen:
            raise ValueError(f"重复的分组 ID：{group_id}")
        seen.add(group_id)
        members = _id_list(raw.get("block_ids"), "groups.block_ids", block_ids)
        groups.append(
            {
                "group_id": group_id,
                "title": str(raw.get("title") or "")[:200],
                "block_ids": members,
                "collapsed": bool(raw.get("collapsed")),
            }
        )
    return groups


# ------------------------------------------------------------------ 持久化


def save(
    project: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    composition_id: str = "",
    expected_revision: Optional[int] = None,
    merged: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """新建（无 composition_id）或整体替换（带 expected_revision 的乐观锁）。"""
    project_name = str(project.get("name") or "")
    with _LOCK:
        if composition_id:
            if not _ID_RE.match(composition_id):
                raise ValueError("composition_id 非法")
            existing = _read(_path(project_name, composition_id))
            if existing is None:
                raise LookupError(f"组合不存在：{composition_id}")
            if int(existing.get("deleted_revision") or 0):
                raise ValueError("组合已删除，不能直接覆盖")
            revision = int(existing.get("revision") or 1)
            if expected_revision is not None and int(expected_revision) != revision:
                raise RevisionConflict(revision)
            doc = build_composition(
                project,
                payload,
                composition_id=composition_id,
                revision=revision + 1,
                created_at=str(existing.get("created_at") or ""),
                merged=merged,
            )
        else:
            if len(list_for(project)) >= MAX_COMPOSITIONS_PER_PROJECT:
                raise ValueError(f"每个项目最多 {MAX_COMPOSITIONS_PER_PROJECT} 份组合")
            doc = build_composition(project, payload, merged=merged)
            if _read(_path(project_name, doc["composition_id"])) is not None:  # pragma: no cover
                raise ValueError("组合 ID 冲突，请重试")
        _write(_path(project_name, doc["composition_id"]), doc)
        return doc


class RevisionConflict(Exception):
    """乐观锁：提交的 revision 与服务器当前不一致。"""

    def __init__(self, current: int):
        super().__init__(f"组合已被修改（当前 revision={current}）")
        self.current = current


def load(project: Dict[str, Any], composition_id: str) -> Dict[str, Any]:
    if not _ID_RE.match(str(composition_id or "")):
        raise LookupError(f"组合不存在：{composition_id}")
    doc = _read(_path(str(project.get("name") or ""), composition_id))
    if doc is None or str(doc.get("project_name")) != str(project.get("name")):
        raise LookupError(f"组合不存在：{composition_id}")
    return doc


def list_for(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    directory = _project_dir(str(project.get("name") or ""))
    if not directory.is_dir():
        return []
    items: List[Dict[str, Any]] = []
    for path in directory.glob("cmp_*.json"):
        doc = _read(path)
        if doc is None or int(doc.get("deleted_revision") or 0):
            continue
        items.append(
            {
                "composition_id": doc.get("composition_id"),
                "title": doc.get("title"),
                "revision": doc.get("revision"),
                "block_count": len(doc.get("blocks") or []),
                "updated_at": doc.get("updated_at"),
                "created_at": doc.get("created_at"),
            }
        )
    items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return items


def delete(project: Dict[str, Any], composition_id: str) -> bool:
    """软删除：保留文件与证据，便于后续恢复/追溯。"""
    with _LOCK:
        doc = load(project, composition_id)
        doc["deleted_revision"] = int(doc.get("revision") or 1)
        doc["deleted_at"] = now_iso()
        _write(_path(str(project.get("name") or ""), composition_id), doc)
        return True


# ------------------------------------------------------------------ 导出


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")


def _strip_images(text: str) -> str:
    """组合里的分析文本不允许自动加载外部图片（导出必须自包含）。"""
    return _IMAGE_RE.sub(lambda match: match.group(1), text)


def _table(headers: List[str], rows: List[List[Any]]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table class='rb-table'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _kv_table(payload: Dict[str, Any]) -> str:
    rows = [[key, value] for key, value in payload.items() if not isinstance(value, (dict, list))]
    return _table(["参数", "值"], rows)


def _block_body(block: Dict[str, Any], evidence: Dict[str, Any]) -> str:
    renderer = str(block.get("renderer") or "")
    if renderer == "text":
        return markdown_to_html(_strip_images(str(block.get("text") or "")))
    if evidence is None:
        return "<p class='rb-note'>缺少证据</p>"
    payload = evidence.get("payload") or {}
    if renderer == "metric":
        rows = [
            ["最终能量", payload.get("final_energy_ev"), "eV"],
            ["最大力", payload.get("force_max_ev_per_a"), "eV/Å"],
            ["离子步", payload.get("ionic_steps"), "步"],
            ["力已收敛", payload.get("converged"), ""],
        ]
        return _table(["指标", "数值", "单位"], [[r[0], r[1], r[2]] for r in rows])
    if renderer == "curve":
        series = payload.get("series") or []
        if not series:
            return "<p class='rb-note'>没有离子步曲线数据</p>"
        svg = energy_force_chart(
            series,
            title=str(block.get("title") or "能量 / 最大力"),
            force_threshold=float(payload.get("force_threshold_ev_per_a") or 0.02),
        )
        return svg
    if renderer == "param_table":
        incar = payload.get("incar") or {}
        if not incar:
            return "<p class='rb-note'>没有 INCAR 快照</p>"
        rows = [[k, v] for k, v in incar.items()]
        return _table(["INCAR 参数", "值"], rows)
    if renderer == "comparison_table":
        rows = payload.get("rows") or []
        return _table(
            ["任务", "状态", "总能 (eV)", "最大力 (eV/Å)", "收敛"],
            [
                [
                    row.get("task_name"),
                    row.get("status"),
                    row.get("final_energy_ev"),
                    row.get("force_max_ev_per_a"),
                    row.get("force_converged"),
                ]
                for row in rows
            ],
        )
    if renderer == "method_table":
        rows = payload.get("rows") or []
        return _table(
            ["任务", "ENCUT", "状态", "输出目录"],
            [
                [row.get("task_name"), row.get("encut"), row.get("status"), row.get("latest_output_dir")]
                for row in rows
            ],
        )
    if renderer == "facts":
        return _kv_table(payload)
    if renderer == "structure":
        has_cif = bool(payload.get("poscar_cif") or payload.get("contcar_cif"))
        return (
            "<p class='rb-note'>结构数据已固定（CIF 可用），交互 3D 视图在 R2-C 接入；"
            f"当前 {'有' if has_cif else '没有'}本地结构文件。</p>"
        )
    return "<p class='rb-note'>该元素类型的组合渲染尚未接入（R2-D）</p>"


_CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
margin:0;padding:32px;color:#1f2329;background:#fff;line-height:1.65}
.rb-head{border-bottom:2px solid #5B8DEF;padding-bottom:12px;margin-bottom:24px}
.rb-head h1{margin:0 0 6px;font-size:24px}
.rb-meta{color:#6b7280;font-size:13px}
.rb-block{margin:0 0 28px;page-break-inside:avoid}
.rb-block h2{font-size:17px;margin:0 0 10px;color:#111827}
.rb-table{border-collapse:collapse;width:100%;font-size:13px}
.rb-table th,.rb-table td{border:1px solid #e5e7eb;padding:6px 10px;text-align:left;vertical-align:top}
.rb-table th{background:#f5f7fa;font-weight:600}
.rb-note{color:#6b7280;font-size:13px;background:#f9fafb;border-left:3px solid #d1d5db;padding:8px 12px}
.rb-evidence{font-family:ui-monospace,Consolas,monospace;font-size:12px}
@media print{body{padding:12mm}.rb-block{page-break-inside:avoid}}
"""


def render_html(doc: Dict[str, Any], *, auto_print: bool = False) -> str:
    """自包含 HTML：只用**冻结在组合里**的 Evidence，不重新解析、不加载外部资源。"""
    evidence_map = doc.get("evidence") or {}
    hidden = set(doc.get("hidden_block_ids") or [])
    deleted = set(doc.get("deleted_block_ids") or [])
    parts: List[str] = []
    for block in doc.get("blocks") or []:
        block_number = str(block.get("block_id"))
        if block_number in hidden or block_number in deleted:
            continue
        refs = block.get("source_refs") or []
        evidence = evidence_map.get(str((refs[0] or {}).get("evidence_id"))) if refs else None
        parts.append(
            "<section class='rb-block' id='{bid}'>"
            "<h2>{title}</h2>{body}<p class='rb-note'>{status}</p></section>".format(
                bid=_esc(block_number),
                title=_esc(block.get("title")),
                body=_block_body(block, evidence or {}),
                status=_esc(
                    f"数据 {block.get('data_status')} · 校验 {block.get('validation_status')}"
                ),
            )
        )

    versions = "".join(
        f"<tr><td>{_esc(item.get('evidence_id'))}</td><td>{_esc(item.get('kind'))}</td>"
        f"<td>{_esc(item.get('version'))}</td></tr>"
        for item in evidence_map.values()
    )
    project = _esc(doc.get("project_name"))
    title = _esc(doc.get("title"))
    meta = _esc(
        f"项目 {project} · 组合 {doc.get('composition_id')} · revision {doc.get('revision')} · "
        f"生成 {doc.get('updated_at')}"
    )
    script = (
        "<script>window.addEventListener('load',function(){window.print()})</script>"
        if auto_print
        else ""
    )
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>{title} · {project}</title><style>{_CSS}</style></head><body>"
        f"<header class='rb-head'><h1>{title}</h1><p class='rb-meta'>{meta}</p></header>"
        f"{''.join(parts)}"
        "<section class='rb-block'><h2>证据版本</h2>"
        "<table class='rb-table rb-evidence'><thead><tr><th>Evidence</th><th>类型</th>"
        f"<th>版本</th></tr></thead><tbody>{versions}</tbody></table></section>"
        f"{script}</body></html>"
    )
