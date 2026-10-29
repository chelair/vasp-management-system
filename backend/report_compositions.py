"""R2-B：组合（Composition）存储、校验与自包含 HTML 导出。

只做"项目内、只读证据 → 手工组合"的最小闭环：

- 存储在 `data/reports/compositions/<项目>/<composition_id>.json`，与完整报告
  `report_store` 的索引/单份清理**完全隔离**（不同命名空间，不碰旧报告）；
- 保存时由后端按合法 ID 重新解析 Evidence，前端不能伪造科学 payload / 渲染器 / 路径；
- 证据版本冻结：版本不一致返回 `evidence_stale`，必须显式 `refresh_evidence` 才接受；
- 预览与导出都用**存下来的同一份** Evidence（导出不重新解析）；
- 文本元素走既有安全 Markdown（R1 已加固），不接受 HTML/脚本。

前端编辑器与首批科学Adapter已接入；此模块输出同一冻结数据的预览/导出HTML，
复用原报告运行时与安全Markdown。复杂布局和AI自动编排不在本阶段范围。
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
import uuid
from copy import deepcopy
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
    result = "".join(keep) or "project"
    if result in (".", ".."):
        raise ValueError("项目名称非法")
    return result


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
    existing: Optional[Dict[str, Any]] = None,
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
    refresh_evidence = payload.get("refresh_evidence", False)
    if type(refresh_evidence) is not bool:
        raise ValueError("refresh_evidence 必须是布尔值")
    moment = now or datetime.now().astimezone()

    blocks: List[Dict[str, Any]] = []
    evidence_map: Dict[str, Dict[str, Any]] = {}
    seen_ids: set[str] = set()
    stale: List[Dict[str, Any]] = []
    aliases = {}
    saved_blocks = {b["block_id"]: b for b in (existing or {}).get("blocks", [])}
    frozen = (existing or {}).get("evidence", {}) if not refresh_evidence else {}

    def obtain(kind, tid="", gid="", raw=None, bid=""):
        # Existing display edits use server-owned snapshots, never client payloads.
        prior = saved_blocks.get(bid)
        if prior and not refresh_evidence:
            refs = prior.get("source_refs") or []
            ref = next((r for r in refs if frozen.get(r["evidence_id"], {}).get("task_id", "") == tid), None)
            if ref:
                value = deepcopy(frozen[ref["evidence_id"]])
                evidence_map[value["evidence_id"]] = value
                return value
        value = resolve_evidence(project, kind, task_id=tid, group_id=gid, merged=merged, now=moment)
        eid = value["evidence_id"]
        claimed = _claimed_version(raw or {}, eid)
        if claimed and claimed != value["version"]:
            stale.append({"block_id": bid, "evidence_id": eid, "claimed": claimed, "current": value["version"]})
        if eid in frozen:
            # A newly added view sharing an existing Evidence must keep the frozen version.
            if claimed and claimed != frozen[eid]["version"]:
                stale.append({"block_id": bid, "evidence_id": eid, "claimed": claimed, "current": frozen[eid]["version"]})
            value = deepcopy(frozen[eid])
        evidence_map[eid] = value
        return value

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
            if not re.fullmatch(r"blk_txt_[0-9a-f]{32}", bid):
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
        task_ids = raw.get("task_ids") or []
        if task_ids:
            if block_type != "project.comparison" or not isinstance(task_ids, list):
                raise ValueError("task_ids 仅用于所选模型参数对照")
            task_ids = sorted(set(str(t) for t in task_ids))
            if not 2 <= len(task_ids) <= 12:
                raise ValueError("参数对照请选择2至12个模型")
            variant = "params:" + ",".join(task_ids)
        expected_id = block_id(
            project_id, block_type, task_id=task_id, group_id=group_id, variant=variant
        )
        declared = str(raw.get("block_id") or "")
        if declared and declared != expected_id:
            raise ValueError("block_id 与元素类型/任务不匹配（不允许借用其他任务的稳定 ID）")
        if expected_id in seen_ids:
            raise ValueError(f"重复的元素 ID：{expected_id}（同一元素只能添加一次）")
        seen_ids.add(expected_id)
        client_id = raw.get("client_id")
        if client_id:
            if not isinstance(client_id, str) or not client_id.startswith("draft_") or len(client_id) > 100 or client_id in aliases:
                raise ValueError("client_id 非法或重复")
            aliases[client_id] = expected_id

        values = [obtain("task.params", tid, raw=raw, bid=expected_id) for tid in task_ids] if task_ids else [
            obtain(block_type, task_id, group_id, raw, expected_id)]
        evidence = values[0]
        blocks.append(
            {
                "block_id": expected_id,
                "type": block_type,
                "type_label": spec["label"],
                "title": block_title or (str(evidence.get("title") or "") + " · " + spec["label"]).strip(" ·"),
                "project_id": project_id,
                "task_id": task_id,
                "group_id": group_id,
                "variant": variant,
                "task_ids": task_ids,
                "renderer": spec["renderer"],
                "options": options,
                "text": "",
                "source_refs": [{"evidence_id": v["evidence_id"], "version": v["version"]} for v in values],
                "data_status": "available" if all(v["availability"] == "available" for v in values) else evidence["availability"] if len(values) == 1 else "unparsed",
                "validation_status": (evidence.get("validation") or {}).get("status") or "UNKNOWN" if len(values) == 1 else "NOT_TESTED",
            }
        )

    if stale and not refresh_evidence:
        raise EvidenceStale(stale)

    block_ids = [item["block_id"] for item in blocks]
    def remap(values):
        return [aliases.get(v, v) if isinstance(v, str) else v for v in values] if isinstance(values, list) else values
    hidden = _id_list(remap(payload.get("hidden_block_ids")), "hidden_block_ids", block_ids)
    deleted = _id_list(remap(payload.get("deleted_block_ids")), "deleted_block_ids", block_ids)
    raw_groups = payload.get("groups")
    if isinstance(raw_groups, list):
        raw_groups = [{**g, "block_ids": remap(g.get("block_ids"))} if isinstance(g, dict) else g for g in raw_groups]
    groups = _groups(raw_groups, block_ids, set(deleted))

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
    assigned: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError("groups 里的分组必须是对象")
        group_id = str(raw.get("group_id") or f"g{index + 1}")
        if group_id in seen:
            raise ValueError(f"重复的分组 ID：{group_id}")
        seen.add(group_id)
        members = _id_list(raw.get("block_ids"), "groups.block_ids", block_ids)
        if assigned.intersection(members):
            raise ValueError("每个元素只能属于一个分组")
        assigned.update(members)
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
            if existing.get("project_name") != project_name or existing.get("project_id") != str(project.get("project_id") or project_name):
                raise LookupError(f"组合不存在：{composition_id}")
            if int(existing.get("deleted_revision") or 0):
                raise ValueError("组合已删除，不能直接覆盖")
            revision = int(existing.get("revision") or 1)
            if type(expected_revision) is not int:
                raise ValueError("更新组合必须提供整数 expected_revision")
            if expected_revision != revision:
                raise RevisionConflict(revision)
            doc = build_composition(
                project,
                payload,
                composition_id=composition_id,
                revision=revision + 1,
                created_at=str(existing.get("created_at") or ""),
                merged=merged,
                existing=existing,
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
        if doc is None or int(doc.get("deleted_revision") or 0) or doc.get("project_name") != str(project.get("name")):
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


def _block_body(block: Dict[str, Any], evidence: Dict[str, Any], values=None) -> str:
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
            force_threshold=payload.get("force_threshold_ev_per_a"),
        )
        return svg
    if renderer == "param_table":
        incar = payload.get("incar") or {}
        rows = [[k, v] for k, v in incar.items()]
        rows.append(["KPOINTS", json.dumps(payload.get("kpoints") or {}, ensure_ascii=False)])
        return _table(["计算参数", "值"], rows) + "<p class='rb-note'>" + _esc(payload.get("note")) + "</p>"
    if renderer == "comparison_table":
        if block.get("task_ids"):
            params = [e.get("payload") or {} for e in (values or [])]
            keys = sorted({key for p in params for key in (p.get("incar") or {})})
            rows = [[key] + [p.get("incar", {}).get(key, "—") for p in params] for key in keys]
            rows.append(["KPOINTS"] + [json.dumps(p.get("kpoints") or {}, ensure_ascii=False) for p in params])
            rows.append(["参数来源"] + [json.dumps(p.get("parameter_sources") or {}, ensure_ascii=False) for p in params])
            return _table(["计算参数"] + [str(p.get("task_name") or p.get("task_id")) for p in params], rows)
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
            ["任务", "ENCUT", "KPOINTS", "状态", "输出目录"],
            [
                [row.get("task_name"), row.get("encut"), json.dumps(row.get("kpoints") or {}, ensure_ascii=False), row.get("status"), row.get("latest_output_dir")]
                for row in rows
            ],
        )
    if renderer == "facts":
        return _kv_table(payload)
    if renderer == "structure":
        return _widget(block, "structure-3d") + _images(payload) + "<p class='rb-note'>" + _esc(payload.get("note")) + "；PDF只包含已有结构图片，交互3D请用HTML查看。</p>"
    if renderer in ("path_panel", "neb_panel"):
        if renderer == "neb_panel":
            from report_neb import has_structures, widget_html
            if any(has_structures(item) for item in payload.get("items", [])):
                return ("<figure>" + "".join(payload.get("charts") or []) + "</figure>"
                        + widget_html(block["block_id"]))
        charts = "".join(payload.get("charts") or [])
        return (charts or "<p class='rb-note'>缺少可绘图的路径/映像数据</p>") + "<p class='rb-note'>" + _esc(payload.get("note")) + "</p>"
    if renderer in ("pdos_panel", "work_function_panel"):
        chart = "".join(payload.get("charts") or [])
        kind = "pdos-chart" if renderer == "pdos_panel" else "work-function-chart"
        return ("<figure>" + chart + "</figure>" if chart else "") + _widget(block, kind)
    if renderer == "bader_table":
        summary = payload.get("summary") or {}
        atoms = summary.get("atoms") or []
        return (_kv_table({k: summary.get(k) for k in ("n_atoms", "total_charge", "n_electrons", "net_charge_available", "net_charge_reason")})
                + (_widget(block, "structure-3d", " data-source='bader'") if payload.get("cif") else "")
                + _table(["原子", "元素", "电荷 (e)", "ZVAL", "净电荷 (e)"],
                         [[a.get(k) for k in ("index", "element", "charge", "zval", "net_charge")] for a in atoms]))
    if renderer == "image_panel":
        return _images(payload) or "<p class='rb-note'>本地没有已生成的差分电荷图片</p>"
    return "<p class='rb-note'>该元素没有可渲染数据</p>"


def _widget(block, kind, extra=""):
    return f"<div class='report-widget' data-report-widget='{kind}' data-block-id='{_esc(block['block_id'])}' data-task-id='{_esc(block['block_id'])}'{extra}></div>"


def _images(payload):
    return "".join("<figure><img alt='" + _esc(image.get("title")) + "' src='" + _esc(image["data"]) + "'><figcaption>" + _esc(image.get("title")) + "</figcaption></figure>"
                   for image in payload.get("images", []) if str(image.get("data", "")).startswith("data:image/png;base64,"))


def _interactive(doc):
    from report_interactive import runtime_js, mol_js, data_script
    data = {"structure": {}, "bader": {}, "pdos": {}, "work_function": {}, "neb": {}}
    for block in doc.get("blocks", []):
        if block["block_id"] in doc.get("hidden_block_ids", []) + doc.get("deleted_block_ids", []):
            continue
        refs = block.get("source_refs") or []
        if not refs:
            continue
        payload = doc.get("evidence", {}).get(refs[0]["evidence_id"], {}).get("payload", {})
        key = block["block_id"]  # Instance identity, never mutable task title/order.
        if block["renderer"] == "structure":
            data["structure"][key] = payload
        elif block["renderer"] == "bader_table" and payload.get("cif"):
            data["bader"][key] = {"cif": payload["cif"], "atoms": payload.get("summary", {}).get("atoms", [])}
        elif block["renderer"] == "pdos_panel" and payload.get("view"):
            data["pdos"][key] = payload["view"]
        elif block["renderer"] == "work_function_panel" and payload.get("summary"):
            data["work_function"][key] = payload["summary"]
        elif block["renderer"] == "neb_panel":
            data["neb"][key] = payload.get("items", [])
    if not any(data.values()):
        return ""
    runtime = runtime_js()
    if not runtime:
        return "<p class='rb-note'>交互运行时不可用，显示冻结的静态图表和数值。</p>"
    mol = mol_js() if data["structure"] or data["bader"] or data["neb"] else ""
    def script(value):
        return "<script>" + value.replace("</script", "<\\/script") + "</script>"
    return script("window.__VASP_REPORT_DATA__=" + data_script(data)) + script(mol) + script(runtime)


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
svg,img{max-width:100%;height:auto}figure{margin:12px 0}.report-widget{min-height:80px}
.rb-table{overflow-wrap:anywhere}.rb-group{border-bottom:1px solid #ddd;padding-top:18px}
@media print{body{padding:12mm}.rb-block{page-break-inside:avoid}.report-widget{display:none!important}.report-static-taken-over{display:block!important}}
"""


def _freshness_basis(evidence):
    from report_blocks import _freshness
    old = evidence.get("freshness") or {}
    if old.get("threshold_hours"):
        current = _freshness(evidence.get("observed_at"), datetime.now().astimezone())
        return str(current.get("basis") or "")
    return str(old.get("basis") or "")


def render_html(doc: Dict[str, Any], *, auto_print: bool = False) -> str:
    """自包含 HTML：只用**冻结在组合里**的 Evidence，不重新解析、不加载外部资源。"""
    evidence_map = doc.get("evidence") or {}
    hidden = set(doc.get("hidden_block_ids") or [])
    deleted = set(doc.get("deleted_block_ids") or [])
    parts: List[str] = []
    membership = {bid: group for group in doc.get("groups", []) for bid in group.get("block_ids", [])}
    previous_group = None
    visible_evidence_ids = set()
    for block in doc.get("blocks") or []:
        block_number = str(block.get("block_id"))
        if block_number in hidden or block_number in deleted:
            continue
        refs = block.get("source_refs") or []
        visible_evidence_ids.update(str(r.get("evidence_id")) for r in refs)
        values = [evidence_map.get(str(r.get("evidence_id")), {}) for r in refs]
        evidence = values[0] if values else None
        group = membership.get(block_number)
        if group and group.get("group_id") != previous_group:
            parts.append("<h2 class='rb-group'>" + _esc(group.get("title")) + "</h2>")
        previous_group = group.get("group_id") if group else None
        parts.append(
            "<section class='rb-block' id='{bid}'>"
            "<h2>{title}</h2>{body}<p class='rb-note'>{status}</p></section>".format(
                bid=_esc(block_number),
                title=_esc(block.get("title")),
                body=(_block_body(block, evidence or {}, values)
                      + "".join("<p class='rb-note'>" + _esc(error) + "</p>" for value in values for error in (value.get("payload", {}).get("errors") or []))
                      + "".join("<p class='rb-note'>" + _esc(block.get("options", {}).get(key)) + "</p>" for key in ("caption", "note") if block.get("options", {}).get(key))),
                status=_esc(
                    f"数据 {block.get('data_status')} · 校验 {block.get('validation_status')} · "
                    + "；".join(str(rule.get("detail") or "") for v in values for rule in (v.get("validation") or {}).get("items", [])) + " · "
                    + "；".join(_freshness_basis(v) for v in values)
                ),
            )
        )

    versions = "".join(
        f"<tr><td>{_esc(item.get('evidence_id'))}</td><td>{_esc(item.get('kind'))}</td>"
        f"<td>{_esc(item.get('version'))}</td><td>{_esc(json.dumps(item.get('provenance') or [], ensure_ascii=False))}</td></tr>"
        for eid, item in evidence_map.items() if eid in visible_evidence_ids
    )

    project = _esc(doc.get("project_name"))
    title = _esc(doc.get("title"))
    meta = _esc(
        f"项目 {doc.get('project_name')} · 组合 {doc.get('composition_id')} · revision {doc.get('revision')} · "
        f"生成 {doc.get('updated_at')}"
    )
    script = (
        "<script>window.addEventListener('load',function(){window.print()})</script>"
        if auto_print
        else ""
    )
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; worker-src blob:; font-src data:; base-uri 'none'; form-action 'none'\">"
        f"<title>{title} · {project}</title><style>{_CSS}</style></head><body>"
        f"<header class='rb-head'><h1>{title}</h1><p class='rb-meta'>{meta}</p></header>"
        f"{''.join(parts)}"
        "<section class='rb-block'><h2>证据版本</h2>"
        "<table class='rb-table rb-evidence'><thead><tr><th>Evidence</th><th>类型</th>"
        f"<th>版本</th><th>来源</th></tr></thead><tbody>{versions}</tbody></table></section>"
        f"{_interactive(doc)}{script}</body></html>"
    )

def preview(project, payload):
    """Validate draft against server snapshots without writing or changing its revision."""
    cid = str(payload.get("composition_id") or "")
    existing = load(project, cid) if cid else None
    if existing and payload.get("expected_revision") != existing["revision"]:
        raise RevisionConflict(existing["revision"])
    return build_composition(project, payload, composition_id=cid,
                             revision=existing["revision"] if existing else 1,
                             created_at=existing.get("created_at", "") if existing else "", existing=existing)


def check_updates(project, doc, *, merged=None):
    changes = []
    for eid, previous in doc.get("evidence", {}).items():
        try:
            current = resolve_evidence(project, previous["block_type"], task_id=previous.get("task_id", ""),
                                       group_id=previous.get("group_id", ""), merged=merged, force=True)
            if current["version"] != previous["version"]:
                changes.append({"evidence_id": eid, "previous": previous["version"], "current": current["version"]})
        except (ValueError, LookupError, KeyError) as exc:
            changes.append({"evidence_id": eid, "error": str(exc)})
    return changes
