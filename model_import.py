"""Model package import and normalization for the standalone simulator.

The importer accepts the lightweight JSON package used by this project and
the definition ZIP exported by ``power_simu_web``.  E-file blocks are parsed
to recover device names, operating states and topology when a package does
not contain a JSON manifest.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import re
import zipfile
from typing import Any, Mapping


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace("%", ""))
    except (TypeError, ValueError):
        return float(default)


def _bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"0", "false", "off", "no", "open", "退出", "分"}:
            return False
        if token in {"1", "true", "on", "yes", "closed", "投入", "合"}:
            return True
    if value is None:
        return bool(default)
    return bool(value)


def _ebook_blocks(text: str) -> dict[str, list[dict[str, str]]]:
    blocks: dict[str, list[dict[str, str]]] = {}
    active = None
    headers: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("<") and line.endswith(">"):
            tag = line[1:-1].strip()
            if tag.startswith("/"):
                active = None
            else:
                active = tag
                blocks.setdefault(active, [])
            headers = []
            continue
        if active is None:
            continue
        if line.startswith("@"):
            headers = line[1:].strip().split()
        elif line.startswith("#") and headers:
            values = line[1:].strip().split()
            if len(values) < len(headers):
                values.extend([""] * (len(headers) - len(values)))
            blocks[active].append(dict(zip(headers, values)))
    return blocks


def _device_family(block: str, row: Mapping[str, Any]) -> str:
    text = f"{block} {row.get('name', '')} {row.get('dev_type', '')}".lower()
    if any(token in text for token in ("wind", "风", "wtg")):
        return "wind"
    if any(token in text for token in ("pv", "光伏", "solar")):
        return "pv"
    if any(token in text for token in ("diesel", "柴油", "柴发")):
        return "diesel"
    if any(token in text for token in ("storage", "储能", "battery", "蓄电")):
        return "battery"
    if block in {"ACLoad", "DCLoad"} or any(token in text for token in ("load", "负荷")):
        return "load"
    if block in {"ACSwitch", "ACBreak", "DCSwitch", "DCBreak"} or any(token in text for token in ("switch", "开关", "断路器")):
        return "switch"
    if block.endswith("Node") or block in {"ACRealBs", "DCRealBs"}:
        return "node"
    return "other"


def _default_curves() -> dict[str, list[dict[str, float]]]:
    return {
        "weather": [
            {"minute": 0, "wind_speed_mps": 7.0, "solar_irradiance_w_m2": 0.0, "air_temp_c": -24.0, "load_kw": 160.0},
            {"minute": 360, "wind_speed_mps": 8.5, "solar_irradiance_w_m2": 0.0, "air_temp_c": -20.0, "load_kw": 180.0},
            {"minute": 720, "wind_speed_mps": 6.5, "solar_irradiance_w_m2": 720.0, "air_temp_c": -16.0, "load_kw": 205.0},
            {"minute": 1080, "wind_speed_mps": 9.0, "solar_irradiance_w_m2": 120.0, "air_temp_c": -19.0, "load_kw": 190.0},
            {"minute": 1439, "wind_speed_mps": 7.0, "solar_irradiance_w_m2": 0.0, "air_temp_c": -24.0, "load_kw": 160.0},
        ],
        "load": [],
        "diesel": [],
        "battery": [],
    }


def _normalize_curves(payload: Mapping[str, Any]) -> dict[str, list[dict[str, float]]]:
    curves = _default_curves()
    source = payload.get("curves") if isinstance(payload.get("curves"), Mapping) else payload
    for key in ("weather", "load", "diesel", "battery"):
        values = source.get(key) if isinstance(source, Mapping) else None
        if isinstance(values, list):
            normalized = []
            for item in values:
                if not isinstance(item, Mapping):
                    continue
                row = {str(name): _number(value) for name, value in item.items() if name != "minute"}
                row["minute"] = _number(item.get("minute", item.get("time", 0)))
                normalized.append(row)
            if normalized:
                curves[key] = sorted(normalized, key=lambda row: row["minute"])
    # power_simu_web curves.json stores weather as a list and load curves in a
    # separate object.  Keep the weather values and map common aliases.
    if isinstance(payload.get("weather"), list) and not isinstance(source.get("weather"), list):
        curves["weather"] = []
        for item in payload["weather"]:
            if isinstance(item, Mapping):
                curves["weather"].append({
                    "minute": _number(item.get("minute", item.get("time_minutes", 0))),
                    "wind_speed_mps": _number(item.get("wind_speed_mps", item.get("wind_speed", 7))),
                    "solar_irradiance_w_m2": _number(item.get("solar_irradiance_w_m2", item.get("solar_irradiance", 0))),
                    "air_temp_c": _number(item.get("air_temp_c", item.get("temperature", -20))),
                    "load_kw": _number(item.get("load_kw", item.get("load", 160))),
                })
    return curves


def _from_ebook(files: Mapping[str, str], source_name: str) -> dict[str, Any]:
    model_text = files.get("model.e", "")
    blocks = _ebook_blocks(model_text)
    devices = []
    topology_nodes = []
    topology_edges = []
    for block, rows in blocks.items():
        for index, row in enumerate(rows, 1):
            name = str(row.get("name") or f"{block}-{row.get('idx', index)}")
            family = _device_family(block, row)
            if family == "node":
                topology_nodes.append({"id": str(row.get("idx", index)), "name": name, "run": _bool(row.get("run_stat", 1))})
                continue
            if family == "other" and block not in {"ACBranch", "DCBranch", "ACTransformer", "DCTransformer"}:
                continue
            devices.append({
                "id": f"{block}:{row.get('idx', index)}",
                "name": name,
                "type": family,
                "block": block,
                "node": row.get("node", row.get("i_node", "")),
                "run": _bool(row.get("run_stat", 1)),
                "rated_kw": _number(row.get("rated_capacity", row.get("p_max", row.get("rated_power", 0)))),
                "p_max_kw": _number(row.get("p_max", row.get("rated_capacity", 0))),
            })
    for block in ("ACBranch", "DCBranch", "ACSwitch", "ACBreak"):
        for index, row in enumerate(blocks.get(block, []), 1):
            topology_edges.append({
                "id": f"{block}:{row.get('idx', index)}",
                "from": str(row.get("i_node", row.get("node", ""))),
                "to": str(row.get("j_node", "")),
                "run": _bool(row.get("run_stat", 1)),
                "closed": _bool(row.get("closed_status", row.get("status", 1))),
                "kind": block,
            })
    curves = _default_curves()
    for name, text in files.items():
        if name.lower().endswith(".json"):
            try:
                candidate = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, Mapping):
                curves = _normalize_curves(candidate)
                break
    return {
        "name": Path(source_name).stem or "imported-model",
        "source": source_name,
        "devices": devices,
        "topology": {"nodes": topology_nodes, "edges": topology_edges},
        "curves": curves,
        "metadata": {"format": "power_simu_web-e-file", "blocks": sorted(blocks), "device_count": len(devices)},
    }


def normalize_model(payload: Mapping[str, Any], *, source_name: str = "model.json") -> dict[str, Any]:
    name = str(payload.get("name") or payload.get("model_name") or Path(source_name).stem or "imported-model").strip()
    devices = []
    family_aliases = {
        "storage": "battery", "ess": "battery", "battery_storage": "battery",
        "solar": "pv", "photovoltaic": "pv", "wind_turbine": "wind", "wtg": "wind",
        "generator": "diesel", "diesel_generator": "diesel", "gen": "diesel",
    }
    for index, item in enumerate(payload.get("devices", []), 1):
        if not isinstance(item, Mapping):
            continue
        family = str(item.get("type", item.get("family", "other"))).lower()
        family = family_aliases.get(family, family)
        devices.append({
            "id": str(item.get("id", item.get("name", f"device-{index}"))),
            "name": str(item.get("name", item.get("id", f"device-{index}"))),
            "type": family,
            "block": str(item.get("block", "")),
            "node": str(item.get("node", "")),
            "run": _bool(item.get("run", item.get("run_stat", True))),
            "rated_kw": _number(item.get("rated_kw", item.get("rated_capacity", item.get("p_max", 0)))),
            "p_max_kw": _number(item.get("p_max_kw", item.get("p_max", item.get("rated_kw", 0)))),
            "energy_kwh": _number(item.get("energy_kwh", item.get("capacity_kwh", 0))),
        })
    topology = payload.get("topology") if isinstance(payload.get("topology"), Mapping) else {}
    model = {
        "name": name,
        "source": source_name,
        "devices": devices,
        "topology": {
            "nodes": list(topology.get("nodes", [])) if isinstance(topology.get("nodes", []), list) else [],
            "edges": list(topology.get("edges", [])) if isinstance(topology.get("edges", []), list) else [],
        },
        "curves": _normalize_curves(payload),
        "points": list(payload.get("points", [])) if isinstance(payload.get("points", []), list) else [],
        "metadata": dict(payload.get("metadata", {})) if isinstance(payload.get("metadata"), Mapping) else {},
    }
    model["metadata"].update({"format": "simulator-json", "device_count": len(devices)})
    return model


def load_model_bytes(data: bytes, *, source_name: str = "model.json") -> dict[str, Any]:
    if not data:
        raise ValueError("模型文件为空")
    name = str(source_name or "model.json")
    if name.lower().endswith(".zip") or data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                json_names = [item for item in names if item.lower().endswith(".json")]
                preferred = next((item for item in json_names if Path(item).name.lower() in {"model.json", "manifest.json", "curves.json"}), None)
                if preferred:
                    payload = json.loads(archive.read(preferred).decode("utf-8-sig"))
                    if isinstance(payload, Mapping) and ("devices" in payload or Path(preferred).name.lower() != "curves.json"):
                        return normalize_model(payload, source_name=name)
                files = {}
                for item in names:
                    base = Path(item).name.lower()
                    if base in {"model.e", "meas.e", "curves.json", "curves.e"}:
                        files[base] = archive.read(item).decode("utf-8-sig", "replace")
                return _from_ebook(files, name)
        except (zipfile.BadZipFile, OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"模型 ZIP 无法解析: {exc}") from exc
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = data.decode("utf-8-sig", "replace")
        if "<Model>" in text or "<ACNode>" in text:
            return _from_ebook({"model.e": text}, name)
        raise ValueError("模型文件必须是 JSON 或 power_simu_web 定义 ZIP/E 文件")
    if not isinstance(payload, Mapping):
        raise ValueError("模型 JSON 根节点必须是对象")
    return normalize_model(payload, source_name=name)


def generate_runtime_points(model: Mapping[str, Any], base_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extend the stable system points with imported device measurements."""

    points = [dict(item) for item in base_points]
    occupied = {(str(item.get("kind")), int(item.get("point_no", item.get("pnt_no", 0)))): index for index, item in enumerate(points)}
    next_yx = max((int(item["point_no"]) for item in points if item.get("kind") == "yx"), default=0) + 1
    next_yc = max((int(item["point_no"]) for item in points if item.get("kind") == "yc"), default=0) + 1
    for device in model.get("devices", []):
        if not isinstance(device, Mapping) or device.get("type") in {"node", "other"}:
            continue
        device_id = str(device.get("id", device.get("name", "device")))
        label = str(device.get("name", device_id))
        points.append({"kind": "yx", "point_no": next_yx, "name": f"{device_id}_running", "unit": "bool", "data_type": 1, "description": f"{label} 投运状态", "device_id": device_id})
        next_yx += 1
        points.append({"kind": "yc", "point_no": next_yc, "name": f"{device_id}_p_kw", "unit": "kW", "data_type": 13, "description": f"{label} 有功出力", "device_id": device_id})
        next_yc += 1
    for item in model.get("points", []):
        if isinstance(item, Mapping) and item.get("kind") in {"yc", "yx", "yk"}:
            try:
                point = dict(item)
                key = (str(point["kind"]), int(point.get("point_no", point.get("pnt_no"))))
            except (KeyError, TypeError, ValueError):
                continue
            point["point_no"] = key[1]
            if key in occupied:
                points[occupied[key]] = point
            else:
                occupied[key] = len(points)
                points.append(point)
    return points

