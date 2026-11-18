"""Import simulator JSON and power_simu_web E-file definition packages."""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
import csv
import io
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping
import xml.etree.ElementTree as ET
import zipfile

MAX_INPUT = 32 * 1024 * 1024


def _number(value, default=0.0):
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("数值必须有限")
        return result
    except (TypeError, ValueError):
        return float(default)


def _bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no", "open", "退出", "分"}
    return bool(value)


def _ebook_blocks(text):
    blocks, active, headers = {}, None, []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("<") and line.endswith(">"):
            active = None if line.startswith("</") else line[1:-1].strip()
            if active:
                blocks.setdefault(active, [])
            headers = []
        elif active and line.startswith("@"):
            headers = line[1:].split()
        elif active and headers and line.startswith("#"):
            values = line[1:].split()
            if len(values) != len(headers):
                raise ValueError(f"E 文件 {active} 列数不匹配")
            blocks[active].append(dict(zip(headers, values)))
    return blocks


def _device_family(block, row):
    # Structural identity must win over names such as "wind-node".
    if block.endswith("Node") or block.endswith("RealBs"):
        return "node"
    if block in {"ACBreak", "DCBreak", "ACSwitch", "DCSwitch"}:
        return "switch"
    if block in {"ACLoad", "DCLoad"}:
        return "load"
    if block not in {"ACGenerator", "DCGenerator"}:
        return "other"
    text = f"{row.get('name', '')} {row.get('dev_type', '')}".lower()
    for family, tokens in (
        ("battery", ("storage", "储能", "battery", "蓄电")),
        ("wind", ("wind", "风", "wtg")),
        ("pv", ("pv", "光伏", "solar")),
        ("diesel", ("diesel", "柴油", "柴发")),
    ):
        if any(token in text for token in tokens):
            return family
    return "generator"


def _read_archive(data):
    if len(data) > MAX_INPUT:
        raise ValueError("文件不能超过 32 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = [e for e in archive.infolist() if not e.is_dir()]
            if len(entries) > 200 or sum(e.file_size for e in entries) > MAX_INPUT:
                raise ValueError("ZIP 解压内容超过限制（200 个文件 / 32 MB）")
            files = {}
            for entry in entries:
                name = Path(entry.filename.replace("\\", "/")).name.lower()
                if name in files:
                    raise ValueError(f"ZIP 包含重名文件: {name}")
                files[name] = archive.read(entry)
            return files
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ValueError(f"ZIP 无法解析: {exc}") from exc


def _decode(data):
    if not data or len(data) > MAX_INPUT:
        raise ValueError("文件为空或超过 32 MB")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("文件编码应为 UTF-8 或 GB18030")


def _time_minutes(value):
    text = str(value).strip()
    try:
        if ":" in text:
            parts = [float(p) for p in text.split(":")]
            if len(parts) not in (2, 3) or not 0 <= parts[1] < 60 or (len(parts) == 3 and not 0 <= parts[2] < 60):
                raise ValueError()
            number = parts[0] * 60 + parts[1] + (parts[2] / 60 if len(parts) == 3 else 0)
        else:
            number = float(text)
        if not math.isfinite(number) or not 0 <= number <= 1440:
            raise ValueError()
        return number
    except (ValueError, TypeError):
        raise ValueError(f"无效日内时间: {value}，应为 0–1440 分钟或 HH:MM:SS") from None


ALIASES = {
    "minute": ("minute", "time_minutes", "minutes", "time", "时间", "分钟"),
    "wind_speed_mps": ("wind_speed_mps", "wind_speed", "wind", "风速"),
    "solar_irradiance_w_m2": ("solar_irradiance_w_m2", "solar_irradiance", "irradiance", "solar", "ghi", "辐照度", "光照"),
    "air_temp_c": ("air_temp_c", "air_temperature_c", "temperature_c", "temperature", "temp", "temp_c", "温度", "气温"),
    "air_pressure_hpa": ("air_pressure_hpa", "pressure", "气压"),
    "humidity_pct": ("humidity_pct", "humidity", "湿度"),
    "load_kw": ("load_kw", "load", "active_load_kw", "demand_kw", "负荷"),
    "diesel_kw": ("diesel_kw", "柴发"),
    "battery_kw": ("battery_kw", "储能"),
}
WEATHER_FIELDS = set(ALIASES) - {"minute", "diesel_kw", "battery_kw"}


def _rows(rows, fields=None):
    if not isinstance(rows, list):
        raise ValueError("曲线必须为数据行数组")
    result, times = [], set()
    aliases = {alias.lower(): key for key, names in ALIASES.items() for alias in names}
    for index, item in enumerate(rows, 1):
        if not isinstance(item, Mapping):
            raise ValueError(f"第 {index} 行必须是对象")
        raw = {aliases.get(str(k).strip().lower(), str(k)): v for k, v in item.items()}
        if "minute" not in raw:
            raise ValueError(f"第 {index} 行缺少时间列")
        minute = _time_minutes(raw["minute"])
        row = {"minute": minute}
        for key in (fields if fields is not None else WEATHER_FIELDS | {"diesel_kw", "battery_kw"}):
            value = raw.get(key)
            if value is None or str(value).strip().upper() in {"", "NA", "N/A", "NULL", "--"}:
                continue
            try:
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError(f"第 {index} 行 {key} 不是有限数值: {value}") from None
            if key in {"wind_speed_mps", "solar_irradiance_w_m2", "load_kw", "diesel_kw", "air_pressure_hpa"} and number < 0:
                raise ValueError(f"第 {index} 行 {key} 不能为负")
            if key == "humidity_pct" and not 0 <= number <= 100:
                raise ValueError("湿度必须为 0–100%")
            row[key] = number
        if len(row) == 1:
            continue
        if minute in times:
            raise ValueError(f"重复时间: {minute} 分钟")
        times.add(minute)
        result.append(row)
    return sorted(result, key=lambda row: row["minute"])


def _normalize_curves(payload, *, defaults=True):
    source = payload.get("curves", payload)
    if not isinstance(source, Mapping):
        raise ValueError("curves 必须是对象")
    curves = _default_curves() if defaults else {}
    for key, fields in (("weather", WEATHER_FIELDS), ("load", {"load_kw"}), ("diesel", {"diesel_kw"}), ("battery", {"battery_kw"})):
        if key in source:
            curves[key] = _rows(source[key], fields)
    for name, rows in source.get("loads", {}).items():
        curves["load@" + str(name)] = _rows(rows, {"p_kw"})
    for entry in source.get("sources", []):
        if entry.get("set_type", "p_set") != "p_set" or entry.get("family", "electric") != "electric":
            key = "unapplied@" + str(entry.get("dev_type")) + "@" + str(entry.get("dev_name")) + "@" + str(entry.get("set_type"))
            curves[key] = _rows(entry["points"], {"value"})
            continue
        factor = {"kw": 1, "mw": 1000, "w": .001}.get(str(entry.get("unit", "kW")).lower())
        if factor is None:
            raise ValueError("源曲线功率单位应为 kW、MW 或 W")
        key = "source@" + str(entry["dev_type"]) + "@" + str(entry.get("dev_name", entry.get("name")))
        curves[key] = _rows(entry["points"], {"value"})
        for row in curves[key]:
            if "value" in row:
                row["value"] *= factor
    for key, rows in source.items():
        if key.startswith(("load@", "source@", "unapplied@")):
            curves[key] = _rows(rows, {"p_kw"} if key.startswith("load@") else {"value"})
    return curves


def interpolate(rows, field, minute):
    values = [(row["minute"], row[field]) for row in rows if field in row]
    if not values:
        return None
    times = [pair[0] for pair in values]
    index = bisect_right(times, minute)
    if index == 0:
        return values[0][1]
    if index == len(values):
        return values[-1][1]
    left, right = values[index - 1], values[index]
    return left[1] + (right[1] - left[1]) * (minute - left[0]) / (right[0] - left[0])


def merge_curve_fields(old, new):
    """Replace only supplied channels, retaining other time-series exactly."""
    fields = set().union(*(row.keys() for row in old + new)) - {"minute"}
    replaced = set().union(*(row.keys() for row in new)) - {"minute"}
    series = {field: new if field in replaced else old for field in fields}
    times = sorted({row["minute"] for rows in series.values() for row in rows})
    # Compile each channel once: O(fields * points log(points)), not quadratic.
    indexed = {field: [(r["minute"], r[field]) for r in rows if field in r] for field, rows in series.items()}
    positions = {field: [p[0] for p in values] for field, values in indexed.items()}
    result = []
    for minute in times:
        row = {"minute": minute}
        for field, values in indexed.items():
            index = bisect_right(positions[field], minute)
            if index == 0:
                row[field] = values[0][1]
            elif index == len(values):
                row[field] = values[-1][1]
            else:
                left, right = values[index - 1], values[index]
                row[field] = left[1] + (right[1] - left[1]) * (minute - left[0]) / (right[0] - left[0])
        result.append(row)
    return result


def load_boundary_bytes(data, *, source_name="boundary.csv"):
    if source_name.lower().endswith(".zip") or data[:2] == b"PK":
        files = _read_archive(data)
        candidates = [name for name in ("curves.e", "curves.json", "boundary.json", "boundary.csv", "weather.e", "weather.csv") if name in files]
        if not candidates:
            candidates = sorted(name for name in files if name.endswith((".json", ".csv", ".tsv", ".e")))
        if len(candidates) != 1 and not any(name in files for name in ("curves.e", "curves.json")):
            raise ValueError("边界 ZIP 应包含一个可识别的边界文件")
        name = candidates[0] if candidates else ""
        if not name:
            raise ValueError("ZIP 中没有边界数据")
        result = load_boundary_bytes(files[name], source_name=name)
        result["source"] = source_name + ":" + name
        return result
    text = _decode(data)
    if text.lstrip().startswith("<"):
        blocks = _ebook_blocks(text)
        payload = {}
        if "EnvironmentCurve" in blocks or "Weather" in blocks:
            payload["weather"] = blocks.get("EnvironmentCurve", blocks.get("Weather"))
        loads = {}
        for row in blocks.get("LoadCurve", []):
            loads.setdefault(row["load_name"], []).append(row)
        payload["loads"] = loads
        sources = {}
        for row in blocks.get("SourceCurve", []):
            key = (row["dev_type"], row["dev_name"], row["set_type"])
            entry = sources.setdefault(key, {**row, "points": []})
            entry["points"].append({"minute": row["minute"], "value": row["value"]})
        payload["sources"] = list(sources.values())
    elif text.lstrip().startswith(("{", "[")):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"边界 JSON 无效: {exc}") from exc
    else:
        delimiter = "\t" if "\t" in text.splitlines()[0] else ","
        payload = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
    if isinstance(payload, Mapping) and ("rows" in payload or "data" in payload):
        payload = payload.get("rows", payload.get("data"))
    if isinstance(payload, list):
        rows = _rows(payload)
        payload = {key: [{"minute": r["minute"], **{f: r[f] for f in fields if f in r}} for r in rows if any(f in r for f in fields)]
                   for key, fields in (("weather", WEATHER_FIELDS), ("diesel", {"diesel_kw"}), ("battery", {"battery_kw"}))}
    if not isinstance(payload, Mapping):
        raise ValueError("边界数据必须为曲线对象或数据行数组")
    curves = _normalize_curves(payload, defaults=False)
    if not any(curves.values()):
        raise ValueError("边界数据没有可用记录或已识别数据列")
    return {"source": source_name, "curves": curves, "rows": sum(map(len, curves.values())),
            "warnings": [f"已保留但未参与电力仿真: {key[10:]}" for key in curves if key.startswith("unapplied@")]}


def sanitize_svg(data, *, source_name="diagram.svg"):
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("SVG 文件不能超过 4 MB")
    text = _decode(data)
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        raise ValueError("SVG 不支持 DTD 或实体声明")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"SVG XML 无效: {exc}") from exc
    def local(tag):
        return tag.rsplit("}", 1)[-1]
    if local(root.tag).lower() != "svg":
        raise ValueError("根元素必须是 SVG")
    forbidden = {"script", "foreignobject", "iframe", "object", "embed", "animate", "animatetransform", "animatemotion", "set", "a"}
    def safe_style(value):
        return not re.search(r"@import|expression|javascript|\\|url\s*\(\s*['\"]?(?!#)[^)]", value, re.I)
    for parent in root.iter():
        for child in list(parent):
            if local(child.tag).lower() in forbidden or (local(child.tag).lower() == "style" and not safe_style(child.text or "")):
                parent.remove(child)
        for key, value in list(parent.attrib.items()):
            name = local(key).lower()
            if name.startswith("on") or name == "base" or (name in {"href", "src"} and not value.strip().startswith("#")) or not safe_style(value):
                del parent.attrib[key]
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    svg = ET.tostring(root, encoding="unicode")
    return {"source": source_name, "svg": svg, "bytes": len(svg.encode("utf-8"))}


def _from_ebook(files, source_name):
    blocks = _ebook_blocks(_decode(files["model.e"]))
    info = (blocks.get("Model") or [{}])[0]
    factor = {"kw": 1, "mw": 1000, "w": .001}.get(info.get("p_unit", "kW").lower())
    if factor is None:
        raise ValueError("E 模型 p_unit 应为 kW、MW 或 W")
    devices, nodes, edges = [], [], []
    for block, rows in blocks.items():
        for index, row in enumerate(rows, 1):
            if "run_stat" not in row:
                continue
            idx = str(row.get("idx", index))
            family = _device_family(block, row)
            prefix = "AC" if block.startswith("AC") else "DC" if block.startswith("DC") else re.sub(r"(Node|Source|Load|Storage)$", "", block)
            node = row.get("node", row.get("i_node", ""))
            node_id = f"{prefix}Node:{node}" if node else ""
            device_id = f"{block}:{idx}"
            device = {
                "id": device_id, "idx": idx, "name": row.get("name", device_id),
                "type": family, "block": block, "dev_type": row.get("dev_type", ""),
                "aliases": [f"{block}-{idx}", device_id], "fields": dict(row),
                "node": node_id, "run": _bool(row.get("run_stat", 1)),
                "rated_kw": _number(row.get("rated_capacity", row.get("p_max", 0))) * factor,
                "p_max_kw": _number(row.get("p_max", row.get("rated_capacity", 0))) * factor,
                "p_set_kw": _number(row.get("p_set")) * factor,
                "closed_status": _bool(row.get("closed_status", row.get("status", 1))),
            }
            devices.append(device)
            if block.endswith("Node"):
                device["node"] = device_id
                nodes.append({"id": device_id, "name": device["name"], "run": device["run"]})
            if "i_node" in row and "j_node" in row:
                edges.append({"id": device_id, "from": f"{prefix}Node:{row['i_node']}", "to": f"{prefix}Node:{row['j_node']}", "run": device["run"], "closed": device["closed_status"], "kind": block})
            elif "ac_node" in row and "dc_node" in row:
                edges.append({"id": device_id, "from": f"ACNode:{row['ac_node']}", "to": f"DCNode:{row['dc_node']}", "run": device["run"], "closed": True, "kind": block})
    if not devices:
        raise ValueError("E 模型没有可识别的设备或节点")
    indexed = {d["id"]: d for d in devices}
    for block, rows in blocks.items():
        if block in {"ACStorageGen", "DCStorageGen", "ACWindGen", "DCWindGen", "ACPVGen", "DCPVGen", "ACDieselGen", "DCDieselGen"}:
            prefix = block[:2]
            for row in rows:
                device = indexed.get(f"{prefix}Generator:{row.get('idx_' + prefix.lower() + 'generator')}")
                if device:
                    device["parameters"] = dict(row)
                    if "energy_capacity" in row:
                        device["energy_kwh"] = _number(row["energy_capacity"])
    curves = _default_curves()
    for name in ("curves.e", "curves.json", "weather.e"):
        if name in files:
            curves.update(load_boundary_bytes(files[name], source_name=name)["curves"])
            break
    return normalize_model({
        "name": info.get("name") or Path(source_name).stem,
        "devices": devices, "topology": {"nodes": nodes, "edges": edges},
        "curves": curves,
        "measurements": _ebook_blocks(_decode(files["meas.e"])).get("Measurement", []) if "meas.e" in files else [],
        "controls": _ebook_blocks(_decode(files["control.e"])) if "control.e" in files else {},
        "metadata": {"format": "power_simu_web-e-file", "blocks": list(blocks), "units": info},
    }, source_name=source_name)


def normalize_model(payload, *, source_name="model.json"):
    if not isinstance(payload.get("devices"), list):
        raise ValueError("模型必须包含 devices 数组")
    result = deepcopy(dict(payload))
    devices, ids = [], set()
    aliases = {"storage": "battery", "ess": "battery", "solar": "pv", "photovoltaic": "pv", "wind_turbine": "wind", "wtg": "wind", "diesel_generator": "diesel"}
    for index, item in enumerate(payload["devices"], 1):
        if not isinstance(item, Mapping):
            raise ValueError("设备必须是对象")
        device = deepcopy(dict(item))
        device["id"] = str(item.get("id", item.get("name", f"device-{index}")))
        if device["id"] in ids:
            raise ValueError(f"重复设备 ID: {device['id']}")
        ids.add(device["id"])
        device["name"] = str(item.get("name", device["id"]))
        family = str(item.get("type", item.get("family", "other"))).lower()
        if not item.get("block") and family in {"generator", "gen"}:
            family = "diesel"
        device["type"] = aliases.get(family, family)
        device["block"] = str(item.get("block", ""))
        device["node"] = str(item.get("node", ""))
        device["run"] = _bool(item.get("run", item.get("run_stat", True)))
        for field, fallback in (("rated_kw", "rated_capacity"), ("p_max_kw", "p_max"), ("energy_kwh", "capacity_kwh")):
            device[field] = _number(item.get(field, item.get(fallback, 0)))
        if not device["rated_kw"]:
            device["rated_kw"] = device["p_max_kw"]
        device["closed_status"] = _bool(item.get("closed_status", item.get("status", True)))
        device["aliases"] = list(item.get("aliases", []))
        parameters = device.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ValueError(f"{device['id']} 参数必须是对象")
        parameters = device["parameters"] = dict(parameters)
        for field in ("rated_wind_speed", "cut_in_wind_speed", "cut_out_wind_speed", "temperature_coefficient", "soc", "charge_discharge_efficiency", "soc_lower_limit", "soc_upper_limit"):
            if field in parameters:
                try:
                    value = float(parameters[field])
                    if not math.isfinite(value):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise ValueError(f"{device['id']} 参数 {field} 必须是有限数值") from None
                parameters[field] = value
        efficiency = float(parameters.get("charge_discharge_efficiency", 1.0))
        lower = float(parameters.get("soc_lower_limit", 0.1))
        upper = float(parameters.get("soc_upper_limit", 0.95))
        if not 0.0 < efficiency <= 1.0:
            raise ValueError(f"{device['id']} 参数 charge_discharge_efficiency 应在 (0, 1] 内")
        if not 0.0 <= lower < upper <= 1.0:
            raise ValueError(f"{device['id']} 参数 SOC 上下限无效")
        if "soc" in parameters and not 0.0 <= parameters["soc"] <= 1.0:
            raise ValueError(f"{device['id']} 参数 soc 应在 0–1 内")
        manual = item.get("manual_p_kw")
        if item.get("control_mode") == "manual" and manual is not None:
            try:
                manual = float(manual)
            except (TypeError, ValueError):
                raise ValueError(f"{device['id']} 手动功率必须是有限数值") from None
            if not math.isfinite(manual):
                raise ValueError(f"{device['id']} 手动功率必须是有限数值")
            limit = max(0.0, float(device.get("p_max_kw") or device.get("rated_kw", 0.0) or 0.0))
            if device["type"] == "battery":
                valid = -limit <= manual <= limit
            else:
                valid = 0.0 <= manual <= limit
            if device["type"] in {"wind", "pv", "diesel", "battery", "generator", "load"} and not valid:
                raise ValueError(f"{device['id']} 手动功率超出额定范围")
            device["control_mode"], device["manual_p_kw"] = "manual", manual
        else:
            device["control_mode"], device["manual_p_kw"] = "curve", None
        devices.append(device)
    topology = deepcopy(payload.get("topology") or {"nodes": [], "edges": []})
    for key in ("nodes", "edges"):
        if not isinstance(topology.get(key, []), list) or not all(isinstance(r, dict) for r in topology.get(key, [])):
            raise ValueError(f"topology.{key} 必须是对象数组")
        topology.setdefault(key, [])
    result.update(name=str(payload.get("name") or payload.get("model_name") or Path(source_name).stem),
                  source=source_name, devices=devices, topology=topology,
                  curves=_normalize_curves(payload), points=deepcopy(payload.get("points", [])))
    result["metadata"] = {**payload.get("metadata", {}), "device_count": len(devices)}
    result["metadata"].setdefault("format", "simulator-json")
    result["metadata"]["warnings"] = [f"已保留但未参与电力仿真: {key[10:]}" for key in result["curves"] if key.startswith("unapplied@")]
    if payload.get("diagram"):
        result["diagram"] = sanitize_svg(str(payload["diagram"]["svg"]).encode(), source_name=payload["diagram"].get("source", "diagram.svg"))
    return result


def load_model_bytes(data, *, source_name="model.json"):
    if source_name.lower().endswith(".zip") or data[:2] == b"PK":
        files = _read_archive(data)
        if "model.e" in files:
            result = _from_ebook(files, source_name)
        elif "model.json" in files:
            result = normalize_model(json.loads(_decode(files["model.json"])), source_name=source_name)
            for name in ("curves.e", "curves.json", "weather.e"):
                if name in files:
                    result["curves"].update(load_boundary_bytes(files[name], source_name=name)["curves"])
                    break
            result = normalize_model(result, source_name=source_name)
        else:
            raise ValueError("定义 ZIP 必须包含 model.e 或 model.json")
        if "diagram.svg" in files:
            result["diagram"] = sanitize_svg(files["diagram.svg"], source_name="diagram.svg")
        return result
    text = _decode(data)
    if text.lstrip().startswith("<"):
        return _from_ebook({"model.e": data}, source_name)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型 JSON 无效: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("模型 JSON 根节点必须是对象")
    return normalize_model(payload, source_name=source_name)


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
        if device.get("type") == "switch":
            points.append({"kind": "yx", "point_no": next_yx, "name": f"{device_id}_closed_status", "unit": "bool", "data_type": 1, "description": f"{label} 实际合位", "device_id": device_id})
            next_yx += 1
            continue
        points.append({"kind": "yc", "point_no": next_yc, "name": f"{device_id}_p_kw", "unit": "kW", "data_type": 13, "description": f"{label} 有功出力", "device_id": device_id})
        next_yc += 1
    # Append storage SOC points after the established device point sequence so
    # existing IOAs remain stable when per-device SOC is enabled.
    for device in model.get("devices", []):
        if isinstance(device, Mapping) and device.get("type") == "battery":
            device_id = str(device.get("id", device.get("name", "battery")))
            label = str(device.get("name", device_id))
            points.append({"kind": "yc", "point_no": next_yc, "name": f"{device_id}_soc_pct", "unit": "%", "data_type": 13, "description": f"{label} 荷电状态", "device_id": device_id})
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

