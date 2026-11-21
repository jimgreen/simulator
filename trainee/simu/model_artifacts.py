"""模型定义文件（.e / SVG / 曲线 / ZIP 归档）预检、修复、产物生成与导入导出模块。"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import html
import json
import math
import re
import shutil
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence

import simu_loop
from efile_read import EBlock
from simu_loop import EBook

try:
    from .definition_editing import (
        DefinitionRevisionConflict,
        canonical_ratio_parameter_text,
        is_ratio_parameter_field,
        is_soc_parameter_field,
        render_ebook_aligned,
    )
    from .device_roles import converter_power_setpoint_fields
    from .http_common import (
        JsonApiError,
        require_active_service_instance_locked as _require_active_service_instance_locked,
    )
    from .model_semantics import energy_coupling_control_bindings
    from .point_names import automatic_point_name
    from .service import (
        DEFAULT_WEATHER,
        DEFINITION_DEFAULTS_FILE,
        DIAGRAM_FILE_NAME,
        MEAS_HEADER,
        SIGNAL_MEASUREMENTS,
        STAT_HEADERS,
        UNKNOWN_WEATHER_VALUE,
        WEATHER_HEADER,
        WEATHER_MEASUREMENTS,
        MultiModelSimulator,
        PolarMicrogridSimulator,
        _safe_model_id as _service_model_id,
        _to_float,
    )
    from .source_curves import source_curve_catalog, source_curve_identity
except ImportError:  # pragma: no cover - legacy direct-module compatibility.
    from simu.definition_editing import (
        DefinitionRevisionConflict,
        canonical_ratio_parameter_text,
        is_ratio_parameter_field,
        is_soc_parameter_field,
        render_ebook_aligned,
    )
    from simu.device_roles import converter_power_setpoint_fields
    from simu.http_common import (
        JsonApiError,
        require_active_service_instance_locked as _require_active_service_instance_locked,
    )
    from simu.model_semantics import energy_coupling_control_bindings
    from simu.point_names import automatic_point_name
    from simu.service import (
        DEFAULT_WEATHER,
        DEFINITION_DEFAULTS_FILE,
        DIAGRAM_FILE_NAME,
        MEAS_HEADER,
        SIGNAL_MEASUREMENTS,
        STAT_HEADERS,
        UNKNOWN_WEATHER_VALUE,
        WEATHER_HEADER,
        WEATHER_MEASUREMENTS,
        MultiModelSimulator,
        PolarMicrogridSimulator,
        _safe_model_id as _service_model_id,
        _to_float,
    )
    from simu.source_curves import source_curve_catalog, source_curve_identity

CONTROL_DEFINITION_BLOCKS = {"RunStat", "CbOpenStat", "SetValue", "StorageSoc"}


def _definition_file_path(service: PolarMicrogridSimulator, file_key: str, file_name: str) -> Path:
    source_files = getattr(service, "source_files", {})
    source_path = Path(source_files.get(file_key, service.sim_dir / file_name))
    if source_path.exists():
        return source_path
    runtime_path = Path(service.files.get(file_key, service.runtime_dir / file_name))
    if runtime_path.exists():
        return runtime_path
    return source_path


def _book_from_text(text: str) -> EBook:
    book = EBook({})
    block: Optional[EBlock] = None
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("<") and line.endswith(">"):
            if line.startswith("</"):
                if block is not None:
                    book.data[block.name] = block
                block = None
            else:
                block = EBlock(line[1:-1])
            continue
        if block is None:
            raise ValueError(f"Invalid E file row before block at line {line_no}")
        if line.startswith("@"):
            block.header_list = line[1:].split()
        elif line.startswith("#"):
            block.AddRow(line[1:].split())
        else:
            raise ValueError(f"Invalid E file row at line {line_no}: {line}")
    return book


def _merge_control_definition(stat_path: Path, control_text: str, model_text: str = "") -> None:
    stat_book = EBook(stat_path) if stat_path.exists() else EBook({})
    control_book = _book_from_text(control_text)
    found = False
    for block_name in CONTROL_DEFINITION_BLOCKS:
        block = control_book.data.get(block_name)
        if block is not None:
            stat_book.data[block_name] = block
            found = True
        elif block_name != "StorageSoc":
            stat_book.data.pop(block_name, None)
    if not found:
        raise ValueError("control.e must contain at least one control block")
    if control_book.data.get("StorageSoc") is None:
        stat_book.data.pop("StorageSoc", None)
        if model_text:
            storage_rows = _storage_source_rows(_book_from_text(model_text))
            if storage_rows:
                storage_block = EBlock("StorageSoc")
                storage_block.header_list = ["dev_type", "idx", "name", "soc_curr"]
                for row in storage_rows:
                    storage_block.AddRow(
                        [
                            str(row.get("dev_type", "")),
                            str(row.get("idx", "")),
                            str(row.get("name", "")),
                            str(row.get("soc_curr", 0.5)),
                        ]
                    )
                stat_book.data["StorageSoc"] = storage_block
    simu_loop.write_ebook_aligned(stat_book, stat_path)


def _extract_efile_blocks(text: str, names: set[str]) -> str:
    parts: list[str] = []
    capturing = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("<") and stripped.endswith(">") and not stripped.startswith("</"):
            block_name = stripped[1:-1]
            capturing = block_name in names
        if capturing:
            parts.append(line)
        if stripped.startswith("</") and stripped.endswith(">"):
            capturing = False
    return "".join(parts)


def _definition_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def _definition_number(value: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return number


def _aligned_efile_text(blocks: Mapping[str, tuple[list[str], list[Mapping[str, Any]]]]) -> str:
    parts: list[str] = []
    for block_name, (headers, rows) in blocks.items():
        widths = [len(header) for header in headers]
        normalized_rows = []
        for row in rows:
            normalized = [_definition_cell(row.get(header, "")) for header in headers]
            normalized_rows.append(normalized)
            widths = [max(width, len(value)) for width, value in zip(widths, normalized)]
        parts.append(f"<{block_name}>\n")
        parts.append("@ " + "  ".join(f"{header:<{widths[idx]}}" for idx, header in enumerate(headers)).rstrip() + "\n")
        for row in normalized_rows:
            parts.append("# " + "  ".join(f"{value:<{widths[idx]}}" for idx, value in enumerate(row)).rstrip() + "\n")
        parts.append(f"</{block_name}>\n")
    return "".join(parts)


def _curve_definition_text(curves: Mapping[str, Any]) -> str:
    mode = str(curves.get("mode", "day") or "day")
    time_step_minutes = curves.get("time_step_minutes", "")
    weather = curves.get("weather", [])
    loads = curves.get("loads", {})
    sources = curves.get("sources", [])
    point_count = curves.get("point_count", len(weather) if isinstance(weather, list) else "")

    info_rows = [
        {
            "mode": mode,
            "time_step_minutes": time_step_minutes,
            "point_count": point_count,
        }
    ]
    env_rows: list[Mapping[str, Any]] = []
    if isinstance(weather, list):
        for idx, point in enumerate(weather, start=1):
            if isinstance(point, Mapping):
                env_rows.append(
                    {
                        "idx": idx,
                        "minute": point.get("minute", idx - 1),
                        "wind_speed_mps": point.get("wind_speed_mps", ""),
                        "air_temp_c": point.get("air_temp_c", ""),
                        "air_pressure_hpa": point.get("air_pressure_hpa", ""),
                        "solar_irradiance_w_m2": point.get("solar_irradiance_w_m2", ""),
                        "humidity_pct": point.get("humidity_pct", ""),
                    }
                )

    load_rows: list[Mapping[str, Any]] = []
    if isinstance(loads, Mapping):
        for load_name, points in loads.items():
            if not isinstance(points, list):
                continue
            for idx, point in enumerate(points, start=1):
                if isinstance(point, Mapping):
                    load_rows.append(
                        {
                            "idx": idx,
                            "load_name": load_name,
                            "minute": point.get("minute", idx - 1),
                            "p_kw": point.get("p_kw", ""),
                        }
                    )

    source_rows: list[Mapping[str, Any]] = []
    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            points = source.get("points", [])
            if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
                continue
            for idx, point in enumerate(points, start=1):
                if not isinstance(point, Mapping):
                    continue
                source_rows.append(
                    {
                        "idx": idx,
                        "dev_type": source.get("dev_type", ""),
                        "dev_name": source.get("dev_name", source.get("name", "")),
                        "set_type": source.get("set_type", ""),
                        "family": source.get("family", ""),
                        "unit": source.get("unit", ""),
                        "minute": point.get("minute", idx - 1),
                        "value": point.get("value", point.get("set_value", "")),
                    }
                )

    return _aligned_efile_text(
        {
            "CurveInfo": (["mode", "time_step_minutes", "point_count"], info_rows),
            "EnvironmentCurve": (
                [
                    "idx",
                    "minute",
                    "wind_speed_mps",
                    "air_temp_c",
                    "air_pressure_hpa",
                    "solar_irradiance_w_m2",
                    "humidity_pct",
                ],
                env_rows,
            ),
            "LoadCurve": (["idx", "load_name", "minute", "p_kw"], load_rows),
            "SourceCurve": (
                ["idx", "dev_type", "dev_name", "set_type", "family", "unit", "minute", "value"],
                source_rows,
            ),
        }
    )


def _curves_from_definition_text(text: str) -> Mapping[str, Any]:
    book = _book_from_text(text)
    info_block = book.data.get("CurveInfo")
    info = info_block.data[0] if info_block is not None and info_block.data else {}
    payload: dict[str, Any] = {
        "mode": str(info.get("mode", "day") or "day"),
        "time_step_minutes": _definition_number(info.get("time_step_minutes", 1)),
        "point_count": _definition_number(info.get("point_count", 0)),
        "weather": [],
        "loads": {},
        "sources": [],
    }

    env_block = book.data.get("EnvironmentCurve")
    if env_block is not None:
        weather_rows = []
        for row in env_block.data:
            weather_rows.append(
                {
                    "minute": _definition_number(row.get("minute", "")),
                    "wind_speed_mps": _definition_number(row.get("wind_speed_mps", "")),
                    "air_temp_c": _definition_number(row.get("air_temp_c", "")),
                    "air_pressure_hpa": _definition_number(row.get("air_pressure_hpa", "")),
                    "solar_irradiance_w_m2": _definition_number(row.get("solar_irradiance_w_m2", "")),
                    "humidity_pct": _definition_number(row.get("humidity_pct", "")),
                }
            )
        payload["weather"] = weather_rows

    load_block = book.data.get("LoadCurve")
    loads: dict[str, list[Mapping[str, Any]]] = {}
    if load_block is not None:
        for row in load_block.data:
            load_name = str(row.get("load_name", "")).strip()
            if not load_name:
                continue
            loads.setdefault(load_name, []).append(
                {
                    "minute": _definition_number(row.get("minute", "")),
                    "p_kw": _definition_number(row.get("p_kw", "")),
                }
            )
    payload["loads"] = loads
    source_block = book.data.get("SourceCurve")
    sources: dict[tuple[str, str, str], dict[str, Any]] = {}
    if source_block is not None:
        for row in source_block.data:
            identity = (
                str(row.get("dev_type", "")).strip(),
                str(row.get("dev_name", "")).strip(),
                str(row.get("set_type", "")).strip(),
            )
            if not all(identity):
                continue
            source = sources.setdefault(
                identity,
                {
                    "dev_type": identity[0],
                    "dev_name": identity[1],
                    "name": identity[1],
                    "set_type": identity[2],
                    "family": str(row.get("family", "")).strip(),
                    "unit": str(row.get("unit", "")).strip(),
                    "points": [],
                },
            )
            source["points"].append(
                {
                    "minute": _definition_number(row.get("minute", "")),
                    "value": _definition_number(row.get("value", "")),
                }
            )
    payload["sources"] = list(sources.values())
    if not payload["point_count"]:
        payload["point_count"] = len(payload["weather"])
    return payload


def _write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _decode_uploaded_definition_text(data: bytes, description: str = "model.e") -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{description} 文件编码无法识别，请保存为 UTF-8 或 GB18030 编码")


def _read_zip_text(archive: zipfile.ZipFile, entry_name: str, required: bool = True) -> Optional[str]:
    try:
        data = archive.read(entry_name)
    except KeyError:
        if required:
            raise ValueError(f"Definition archive is missing {entry_name}") from None
        return None
    return _decode_uploaded_definition_text(data, entry_name)


def _normalize_diagram_svg_text(svg_text: Optional[str]) -> Optional[str]:
    if svg_text is None:
        return None
    text = str(svg_text).lstrip("\ufeff")
    if not text.strip():
        return None
    text = re.sub(
        r'^(\s*<\?xml\b[^>]*?\bencoding\s*=\s*)(["\'])([^"\']+)(\2)',
        lambda match: f'{match.group(1)}{match.group(2)}UTF-8{match.group(2)}',
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    lower = text.lower()
    if "<svg" not in lower:
        raise ValueError("SVG图形文件必须包含 <svg> 根图形内容")
    if "<script" in lower or "javascript:" in lower or re.search(r"\son[a-z0-9_-]+\s*=", text, re.IGNORECASE):
        raise ValueError("SVG图形文件不能包含脚本、事件属性或 javascript 链接")
    return text


def _decode_optional_svg_payload(payload: Mapping[str, Any]) -> Optional[str]:
    data_base64 = str(payload.get("diagram_svg_base64", payload.get("svg_base64", "")) or "")
    if not data_base64:
        return None
    try:
        data = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("SVG图形文件 Base64 数据无效") from exc
    return _decode_uploaded_definition_text(data, "SVG图形")


def _write_model_diagram(target_dir: Path, diagram_svg_text: Optional[str], *, remove_when_absent: bool = False) -> bool:
    path = target_dir / DIAGRAM_FILE_NAME
    normalized = _normalize_diagram_svg_text(diagram_svg_text)
    if normalized is None:
        if remove_when_absent and path.exists() and path.is_file():
            path.unlink()
        return False
    path.write_text(normalized, encoding="utf-8", newline="")
    return True


def _fallback_definition_diagram_svg(service: PolarMicrogridSimulator) -> str:
    model_id = html.escape(str(getattr(service, "model_id", "model") or "model"))
    model_name = html.escape(str(getattr(service, "model_name", model_id) or model_id))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" data-model-diagram="fallback" '
        'width="960" height="540" viewBox="0 0 960 540">'
        '<rect width="960" height="540" fill="#f8fafc"/>'
        '<rect x="220" y="190" width="520" height="160" rx="12" fill="#ffffff" stroke="#94a3b8" stroke-width="2"/>'
        '<text x="480" y="250" text-anchor="middle" font-family="Arial, sans-serif" '
        'font-size="28" fill="#0f172a">'
        f"{model_name}"
        "</text>"
        '<text x="480" y="295" text-anchor="middle" font-family="Arial, sans-serif" '
        'font-size="18" fill="#475569">'
        f"{model_id} · diagram.svg"
        "</text>"
        "</svg>"
    )


MODEL_DEVICE_BLOCKS = {
    "ACNode",
    "DCNode",
    "ACRealBs",
    "DCRealBs",
    "ACBranch",
    "DCBranch",
    "ACZeroBranch",
    "DCZeroBranch",
    "ACSwitch",
    "DCSwitch",
    "ACBreak",
    "DCBreak",
    "ACLoad",
    "DCLoad",
    "ACGenerator",
    "DCGenerator",
    "DCDCConverter",
    "DCACConverter",
    "ACACConverter",
}
SET_VALUE_COLUMN_MAP = {
    "ACGenerator": (("p_set", "p_set"), ("q_set", "q_set"), ("v_set", "v_set")),
    "DCGenerator": (("p_set", "p_set"), ("v_set", "v_set"), ("i_set", "i_set")),
    "DCDCConverter": (("p_set", "p_set"), ("i_set", "i_set"), ("v_set", "v_set")),
    "DCACConverter": (
        ("p_ac_set", "p_ac_set"),
        ("p_dc_set", "p_dc_set"),
        ("q_ac_set", "q_ac_set"),
        ("v_ac_set", "v_ac_set"),
        ("v_dc_set", "v_dc_set"),
    ),
    "ACACConverter": (
        ("p_set", "p_set"),
        ("q_set", "q_set"),
        ("v_set", "v_set"),
        ("p_from_set", "p_from_set"),
        ("q_from_set", "q_from_set"),
        ("v_from_set", "v_from_set"),
        ("p_to_set", "p_to_set"),
        ("q_to_set", "q_to_set"),
        ("v_to_set", "v_to_set"),
    ),
    "ACLoad": (
        ("p_set", "p_set"),
        ("p_set", "pv0"),
        ("q_set", "q_set"),
        ("q_set", "qv0"),
    ),
    "DCLoad": (("p_set", "p_set"), ("p_set", "pv0"), ("v_set", "v_set"), ("i_set", "i_set")),
    "HydroSource": (("flow_set", "flow_set"),),
    "HydroLoad": (("flow_set", "flow_set"),),
    "HeatSource": (("flow_set", "flow_set"),),
}
MEASUREMENT_TYPE_MAP = {
    "ACNode": ("V", "ANGLE"),
    "DCNode": ("V",),
    "ACGenerator": ("P_GEN", "Q_GEN", "V_GEN", "I_GEN"),
    "DCGenerator": ("P_GEN", "V_GEN", "I_GEN"),
    "ACLoad": ("P_LOAD", "Q_LOAD", "V_LOAD", "I_LOAD"),
    "DCLoad": ("P_LOAD", "V_LOAD", "I_LOAD"),
    "HydroSource": ("flow", "pressure"),
    "HydroLoad": ("flow", "pressure"),
    "HydroPipe": ("flow",),
    "HydroValve": ("flow",),
    "HydroCompressor": ("flow",),
    "HydroPressRegulator": ("flow",),
    "HydroStopValve": ("flow",),
    "ACBranch": ("P_FROM", "Q_FROM", "P_TO", "Q_TO", "I"),
    "ACTransformer": ("P_FROM", "Q_FROM", "P_TO", "Q_TO", "I"),
    "ACZeroBranch": ("P_FROM", "Q_FROM", "P_TO", "Q_TO", "I"),
    "ACSwitch": ("P_FROM", "Q_FROM", "P_TO", "Q_TO", "I"),
    "ACBreak": ("P_FROM", "Q_FROM", "P_TO", "Q_TO", "I"),
    "DCBranch": ("P_FROM", "P_TO", "I"),
    "DCZeroBranch": ("P_FROM", "P_TO", "I"),
    "DCSwitch": ("P_FROM", "P_TO", "I"),
    "DCBreak": ("P_FROM", "P_TO", "I"),
    "DCDCConverter": ("P_FROM", "V_FROM", "I_FROM", "P_TO", "V_TO", "I_TO"),
    "DCACConverter": ("P_DC", "V_DC", "I_DC", "P_AC", "Q_AC", "V_AC", "I_AC"),
    "ACACConverter": ("P_FROM", "Q_FROM", "V_FROM", "I_FROM", "P_TO", "Q_TO", "V_TO", "I_TO"),
    "HydroStorage": ("pressure", "flow", "gas_quantity", "soc"),
}
STORAGE_PARAMETER_SPECS = (
    ("ACStorageGen", "ACGenerator", "idx_acgenerator"),
    ("DCStorageGen", "DCGenerator", "idx_dcgenerator"),
)
CONVERTER_MODEL_BLOCKS = ("DCACConverter", "DCDCConverter", "ACACConverter")
AMBIGUOUS_CONVERTER_RUNTIME_FIELDS = frozenset({"p", "q", "u", "i"})


def _rows(book: EBook, block_name: str) -> list[dict]:
    block = book.data.get(block_name)
    return [] if block is None else list(block.data)


def _ebook_from_blocks(blocks: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]]) -> EBook:
    book = EBook({})
    for block_name, (headers, rows) in blocks.items():
        block = EBlock(block_name)
        block.header_list = list(headers)
        block.data = [{header: row.get(header, "") for header in headers} for row in rows]
        book.data[block_name] = block
    return book


def _remove_ambiguous_converter_runtime_fields(model_book: EBook) -> int:
    removed = 0
    for block_name in CONVERTER_MODEL_BLOCKS:
        block = model_book.data.get(block_name)
        if block is None:
            continue
        headers = [
            field
            for field in getattr(block, "header_list", [])
            if str(field).strip().casefold() not in AMBIGUOUS_CONVERTER_RUNTIME_FIELDS
        ]
        removed += len(getattr(block, "header_list", [])) - len(headers)
        block.header_list = headers
        block.data = [
            {field: row.get(field, "") for field in headers}
            for row in getattr(block, "data", [])
        ]
    return removed


def _row_name(row: Mapping[str, Any]) -> str:
    return str(row.get("name", row.get("dev_name", ""))).strip()


def _numeric(value: Any, default: float = 0.0) -> float:
    number = _to_float(value, None)
    if number is None:
        text = str(value or "")
        if text.endswith("%"):
            number = _to_float(text[:-1], None)
            return default if number is None else float(number) / 100.0
        return default
    return float(number)


def _storage_soc_value(value: Any, default: float = 0.5) -> float:
    text = str(value or "").strip()
    raw_value = text.replace("%", "").strip() if "%" in text else value
    number = _to_float(raw_value, None)
    if number is None:
        return default
    if "%" in text or 2.0 < abs(number) <= 100.0:
        return number / 100.0
    return number


def _first_present(row: Mapping[str, Any], columns: Sequence[str], default: Any = "") -> Any:
    for column in columns:
        if column in row and row.get(column, "") != "":
            return row.get(column)
    return default


def _model_book_has_power_model(book: EBook) -> bool:
    return any(name in MODEL_DEVICE_BLOCKS and getattr(block, "data", []) for name, block in book.data.items())


def _validate_dcac_converter_schema(model_book: EBook) -> None:
    block = model_book.data.get("DCACConverter")
    if block is None or not getattr(block, "data", []):
        return
    headers = set(getattr(block, "header_list", []))
    if "control_type" in headers:
        raise ValueError(
            "DCACConverter 已取消 control_type，请使用 ac_control_type 和 dc_control_type"
        )
    required = {"ac_control_type", "dc_control_type", "p_ac_set", "p_dc_set"}
    missing = sorted(required - headers)
    if missing:
        raise ValueError(
            f"DCACConverter 缺少必需字段: {', '.join(missing)}"
        )


_REQUIRED_POWER_MODEL_FIELDS = {
    "ACRealBs": {"node"},
    "DCRealBs": {"node"},
    "ACGenerator": {"node", "control_type", "p_set", "q_set", "v_set"},
    "DCGenerator": {"node", "control_type", "p_set", "v_set", "i_set"},
}

# Before AC generator control boundaries were serialized explicitly, the power
# flow parser interpreted an omitted ``control_type`` as PQ.  Keep that exact
# legacy meaning only for the recognizable old table layout; a current table
# with one accidentally deleted field must still fail closed.
_LEGACY_AC_GENERATOR_HEADERS = {
    "idx",
    "name",
    "node",
    "p_max",
    "p_min",
    "q_max",
    "q_min",
    "run_stat",
    "rated_capacity",
    "rated_voltage",
    "v_max",
    "v_min",
    "regable",
    "p",
    "q",
    "u",
    "f",
}
_EXPLICIT_AC_GENERATOR_CONTROL_HEADERS = {
    "dev_type",
    "alpha",
    "control_type",
    "p_set",
    "q_set",
    "v_set",
}


def _legacy_ac_generator_uses_default_pq(headers: Sequence[str]) -> bool:
    normalized = {str(field).strip() for field in headers if str(field).strip()}
    return (
        _LEGACY_AC_GENERATOR_HEADERS <= normalized
        and not (_EXPLICIT_AC_GENERATOR_CONTROL_HEADERS & normalized)
    )

_SAFE_DEFAULT_MODEL_FIELDS = {
    "ACRealBs": {"u", "f"},
    "DCRealBs": {"u", "i"},
    "ACBranch": {"p", "q", "i"},
    "ACZeroBranch": {"p", "q", "i"},
    "ACSwitch": {"p", "q", "i"},
    "ACBreak": {"p", "q", "i"},
    "DCBranch": {"p", "u", "i"},
    "DCZeroBranch": {"p", "i"},
    "DCSwitch": {"p", "i"},
    "DCBreak": {"p", "i"},
    "ACGenerator": {"p", "q", "u", "i"},
    "DCGenerator": {"p", "u", "i"},
    "ACLoad": {"p_set", "p", "q", "u", "i"},
    "DCLoad": {"p_set", "p", "u", "i"},
    "DCDCConverter": {"p_set", "i_set", "v_set"},
    "DCACConverter": {
        "p_ac_set",
        "p_dc_set",
        "q_ac_set",
        "i_dc_set",
        "v_ac_set",
        "v_dc_set",
    },
}

_SVG_REQUIRED_MODEL_BLOCKS = {
    "ACRealBs",
    "DCRealBs",
    "ACBranch",
    "DCBranch",
    "ACZeroBranch",
    "DCZeroBranch",
    "ACSwitch",
    "DCSwitch",
    "ACBreak",
    "DCBreak",
    "ACLoad",
    "DCLoad",
    "ACGenerator",
    "DCGenerator",
    "DCDCConverter",
    "DCACConverter",
    "ACACConverter",
    "AcE2Hydro",
    "DcE2Hydro",
    "Hydro2AcE",
    "Hydro2DcE",
    "HydroSource",
    "HydroLoad",
    "HydroPipe",
    "HydroValve",
    "HydroCompressor",
    "HydroPressRegulator",
    "HydroStopValve",
    "HydroStorage",
}


class ModelPreflightError(ValueError):
    """A failed, non-mutating model import validation."""

    def __init__(self, validation: Mapping[str, Any]) -> None:
        self.validation = dict(validation)
        super().__init__(str(self.validation.get("summary") or "模型预校核未通过"))


def _xml_local_name(value: Any) -> str:
    return str(value or "").rsplit("}", 1)[-1]


def _diagram_svg_inventory(svg_text: Optional[str]) -> Mapping[str, Any]:
    normalized = _normalize_diagram_svg_text(svg_text)
    if normalized is None:
        return {"svg": None, "devices": [], "edge_device_ids": []}
    try:
        root = ET.fromstring(normalized)
    except ET.ParseError as exc:
        raise ValueError(f"SVG图形 XML 解析失败: {exc}") from exc
    if _xml_local_name(root.tag).casefold() != "svg":
        raise ValueError("SVG图形文件的根元素必须是 <svg>")
    if str(root.attrib.get("data-model-diagram", "")).strip().casefold() == "fallback":
        return {"svg": None, "devices": [], "edge_device_ids": []}

    devices: list[dict[str, str]] = []
    edge_device_ids: list[str] = []
    for element in root.iter():
        attributes = {
            _xml_local_name(key): str(value or "").strip()
            for key, value in element.attrib.items()
        }
        for field in ("source-dev-id", "target-dev-id"):
            value = attributes.get(field, "")
            if value:
                edge_device_ids.append(value)
        tag = _xml_local_name(element.tag).casefold()
        # ``dev`` is a measurement-overlay reference such as ``ACGenerator-31``;
        # it is not a device type and must not be counted as another SVG device.
        explicit_type = attributes.get("dev-type", attributes.get("device-type", ""))
        device_id = attributes.get("dev-id", "")
        if tag != "use" and (tag != "g" or not device_id):
            continue
        if not device_id and tag == "use":
            candidate_id = attributes.get("id", "")
            if "-" in candidate_id and not candidate_id.startswith(("label_", "measure_")):
                device_id = candidate_id
        if not device_id:
            continue
        devices.append(
            {
                "dev_id": device_id,
                "dev_type": explicit_type,
                "idx": attributes.get("idx", ""),
                "name": attributes.get("name", ""),
                "node": attributes.get("node", ""),
            }
        )
    return {
        "svg": normalized,
        "devices": devices,
        "edge_device_ids": sorted(set(edge_device_ids)),
    }


def _resolve_svg_devices(model_book: EBook, inventory: Mapping[str, Any]) -> list[dict[str, str]]:
    block_names = {
        str(name)
        for name in model_book.data
    } | set(_SVG_REQUIRED_MODEL_BLOCKS)
    resolved: list[dict[str, str]] = []
    for source in inventory.get("devices", []):
        if not isinstance(source, Mapping):
            continue
        item = {str(key): str(value or "").strip() for key, value in source.items()}
        dev_type = item.get("dev_type", "")
        dev_id = item.get("dev_id", "")
        idx = item.get("idx", "")
        if not dev_type and dev_id:
            for block_name in sorted(block_names, key=len, reverse=True):
                prefix = f"{block_name}-"
                if dev_id.startswith(prefix):
                    dev_type = block_name
                    if not idx:
                        idx = dev_id[len(prefix):]
                    break
        item["dev_type"] = dev_type
        item["idx"] = idx
        resolved.append(item)
    return resolved


def _preflight_number_text(value: float) -> str:
    text = format(float(value), ".15g")
    return "0" if text in {"-0", "-0.0"} else text


def _bounded_zero_default(row: Mapping[str, Any], minimum_field: str, maximum_field: str) -> str:
    lower = _to_float(row.get(minimum_field), None)
    upper = _to_float(row.get(maximum_field), None)
    value = 0.0
    if lower is not None:
        value = max(value, float(lower))
    if upper is not None:
        value = min(value, float(upper))
    return _preflight_number_text(value)


def _node_base_voltage(model_book: EBook, domain: str, node_idx: Any) -> Optional[float]:
    normalized_idx = str(node_idx or "").strip()
    node_block = model_book.data.get(f"{domain}Node")
    if normalized_idx and node_block is not None:
        for node_row in getattr(node_block, "data", []):
            if str(node_row.get("idx", "")).strip() != normalized_idx:
                continue
            voltage = _to_float(node_row.get("vbase", node_row.get("voltage")), None)
            if voltage is not None and float(voltage) > 0.0:
                return float(voltage)
    return None


def _connected_node_voltage(
    model_book: EBook,
    block_name: str,
    row: Mapping[str, Any],
    field: str = "v_set",
) -> Optional[float]:
    candidates: list[tuple[str, Any]] = []
    if field == "v_ac_set":
        candidates.append(("AC", row.get("ac_node")))
    elif field == "v_dc_set":
        candidates.append(("DC", row.get("dc_node")))
    elif block_name == "DCDCConverter":
        candidates.extend(("DC", row.get(key)) for key in ("i_node", "j_node"))
    elif block_name.startswith("AC"):
        candidates.append(("AC", row.get("node", row.get("i_node"))))
    else:
        candidates.append(("DC", row.get("node", row.get("i_node"))))
    for domain, node_idx in candidates:
        voltage = _node_base_voltage(model_book, domain, node_idx)
        if voltage is not None:
            return voltage
    rated = _to_float(row.get("rated_voltage"), None)
    return float(rated) if rated is not None and float(rated) > 0.0 else None


def _safe_model_field_default(
    model_book: EBook,
    block_name: str,
    row: Mapping[str, Any],
    field: str,
) -> tuple[Optional[str], str]:
    if field in {"v_set", "v_ac_set", "v_dc_set", "u"}:
        voltage = _connected_node_voltage(model_book, block_name, row, field)
        if voltage is not None:
            return _preflight_number_text(voltage), "额定电压或连接节点基准电压"
        if field == "u":
            return "0", "运行量初值"
        return None, ""
    if field == "p_set" and block_name in {"ACLoad", "DCLoad"}:
        pbase = _to_float(row.get("pbase"), None)
        if pbase is not None:
            # ACLoad/DCLoad expose p_set as the writable alias of pbase.  Copying
            # pbase preserves the original ZIP load pbase*pv0 operating point.
            return _preflight_number_text(float(pbase)), "静态负荷模型 pbase"
        return _bounded_zero_default(row, "p_min", "p_max"), "功率上下限内的零值"
    if field in {"p_set", "p_ac_set", "p_dc_set"}:
        minimum_field = "p_min"
        maximum_field = "p_max"
        if field == "p_ac_set":
            minimum_field, maximum_field = "ac_p_min", "ac_p_max"
        elif field == "p_dc_set":
            minimum_field, maximum_field = "dc_p_min", "dc_p_max"
        return _bounded_zero_default(row, minimum_field, maximum_field), "功率上下限内的零值"
    if field in {"q_set", "q_ac_set"}:
        minimum_field, maximum_field = ("q_min", "q_max")
        if field == "q_ac_set":
            minimum_field, maximum_field = ("ac_q_min", "ac_q_max")
        return _bounded_zero_default(row, minimum_field, maximum_field), "无功上下限内的零值"
    if field in {"i_set", "i_dc_set"}:
        minimum_field, maximum_field = ("i_min", "i_max")
        if field == "i_dc_set":
            minimum_field, maximum_field = ("dc_i_min", "dc_i_max")
        return _bounded_zero_default(row, minimum_field, maximum_field), "电流上下限内的零值"
    if field == "f":
        return "50", "交流额定频率"
    if field in {"p", "q", "i"}:
        return "0", "运行量初值"
    return None, ""


def _repair_power_model_schema(
    model_book: EBook,
    svg_devices: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Fill only deterministic defaults; ambiguous topology/control stays invalid."""

    repairs: list[dict[str, str]] = []
    resolved_svg = _resolve_svg_devices(model_book, {"devices": list(svg_devices)})

    def svg_row(block_name: str, row: Mapping[str, Any]) -> Optional[Mapping[str, str]]:
        idx = str(row.get("idx", "")).strip()
        name = str(row.get("name", "")).strip()
        matches = [
            item
            for item in resolved_svg
            if item.get("dev_type") == block_name
            and (
                (idx and item.get("idx") == idx)
                or (name and item.get("name") == name)
            )
        ]
        if len(matches) != 1:
            return None
        match = matches[0]
        svg_name = str(match.get("name", "")).strip()
        return match if not svg_name or not name or svg_name == name else None

    candidate_blocks = set(_REQUIRED_POWER_MODEL_FIELDS) | set(_SAFE_DEFAULT_MODEL_FIELDS)
    for block_name in sorted(candidate_blocks):
        candidate_fields = (
            set(_REQUIRED_POWER_MODEL_FIELDS.get(block_name, set()))
            | set(_SAFE_DEFAULT_MODEL_FIELDS.get(block_name, set()))
        )
        block = model_book.data.get(block_name)
        if block is None or not getattr(block, "data", []):
            continue
        headers = list(getattr(block, "header_list", []))
        legacy_ac_generator_default = (
            block_name == "ACGenerator"
            and _legacy_ac_generator_uses_default_pq(headers)
        )
        for field in sorted(candidate_fields):
            field_was_missing = field not in headers
            repaired_any = False
            for row in block.data:
                if str(row.get(field, "")).strip():
                    continue
                replacement: Optional[str] = None
                source = ""
                if field == "node":
                    diagram_row = svg_row(block_name, row)
                    svg_node = str((diagram_row or {}).get("node", "")).strip()
                    if svg_node:
                        replacement = svg_node
                        source = "SVG设备节点"
                elif field == "control_type" and legacy_ac_generator_default:
                    replacement = "PQ"
                    source = "旧版潮流内核 ACGenerator 缺省控制模式"
                else:
                    replacement, source = _safe_model_field_default(
                        model_book,
                        block_name,
                        row,
                        field,
                    )
                if replacement is None:
                    continue
                row[field] = replacement
                repaired_any = True
                repairs.append(
                    {
                        "block": block_name,
                        "device": str(row.get("name", row.get("idx", ""))).strip(),
                        "field": field,
                        "value": replacement,
                        "source": source,
                    }
                )
            if field_was_missing and repaired_any:
                headers.append(field)
        block.header_list = headers
    return repairs


def _validate_power_model_schema(model_book: EBook) -> None:
    """Reject definitions that silently remove a bus anchor or generator control."""

    issues: list[str] = []
    for block_name in sorted(_SVG_REQUIRED_MODEL_BLOCKS):
        block = model_book.data.get(block_name)
        if block is None or not getattr(block, "data", []):
            continue
        headers = {
            str(field).strip()
            for field in getattr(block, "header_list", [])
            if str(field).strip()
        }
        missing_identity_fields = sorted({"idx", "name"} - headers)
        if missing_identity_fields:
            issues.append(
                f"{block_name} 缺少设备身份字段: {', '.join(missing_identity_fields)}"
            )
        seen_indices: set[str] = set()
        seen_names: set[str] = set()
        for position, row in enumerate(getattr(block, "data", []), start=1):
            idx = str(row.get("idx", "")).strip()
            name = str(row.get("name", "")).strip()
            if not idx:
                issues.append(f"{block_name} 第 {position} 行的稳定索引 idx 为空")
            elif idx in seen_indices:
                issues.append(f"{block_name} 的稳定索引 idx={idx} 重复")
            else:
                seen_indices.add(idx)
            if not name:
                issues.append(f"{block_name} 第 {position} 行的设备名称 name 为空")
            elif name in seen_names:
                issues.append(f"{block_name} 的设备名称 name={name} 重复")
            else:
                seen_names.add(name)
    for block_name, required_fields in _REQUIRED_POWER_MODEL_FIELDS.items():
        block = model_book.data.get(block_name)
        if block is None or not getattr(block, "data", []):
            continue
        headers = {
            str(field).strip()
            for field in getattr(block, "header_list", [])
            if str(field).strip()
        }
        missing = sorted(required_fields - headers)
        if missing:
            issues.append(f"{block_name} 缺少必需字段: {', '.join(missing)}")
        for row in getattr(block, "data", []):
            device = str(row.get("name", row.get("idx", ""))).strip() or "未命名设备"
            empty = sorted(
                field
                for field in required_fields & headers
                if not str(row.get(field, "")).strip()
            )
            if empty:
                issues.append(f"{block_name}/{device} 的必需字段为空: {', '.join(empty)}")
    if issues:
        raise ValueError(
            "model.e 关键潮流字段不完整："
            + "；".join(issues)
            + "。已拒绝更新，以免对应电网被静默判为死岛。"
        )


def _expected_svg_model_rows(model_book: EBook) -> list[tuple[str, str, str]]:
    coupled_endpoints = {
        (
            str(binding.get("target_dev_type", "")).strip(),
            str(binding.get("target_dev_name", "")).strip(),
        )
        for bindings in energy_coupling_control_bindings(model_book).values()
        for binding in bindings
    }
    expected: list[tuple[str, str, str]] = []
    for block_name in sorted(_SVG_REQUIRED_MODEL_BLOCKS):
        block = model_book.data.get(block_name)
        for row in [] if block is None else getattr(block, "data", []):
            idx = str(row.get("idx", "")).strip()
            name = str(row.get("name", "")).strip()
            if not idx or not name or (block_name, name) in coupled_endpoints:
                continue
            expected.append((block_name, idx, name))
    return expected


def _diagram_model_match_result(
    model_book: EBook,
    inventory: Mapping[str, Any],
) -> Mapping[str, Any]:
    if inventory.get("svg") is None:
        return {
            "id": "diagram",
            "label": "E/SVG 匹配性",
            "status": "warning",
            "message": "未提供 SVG 图形，已跳过 E/SVG 匹配性校验。",
            "details": {
                "missing_in_svg": [],
                "unknown_in_model": [],
                "name_mismatches": [],
                "dangling_edges": [],
                "identity_issues": [],
                "duplicate_devices": [],
            },
        }

    expected = _expected_svg_model_rows(model_book)
    by_type_idx = {(block, idx): name for block, idx, name in expected}
    all_model_rows = {
        (str(block_name), str(row.get("idx", "")).strip()): str(row.get("name", "")).strip()
        for block_name, block in model_book.data.items()
        for row in getattr(block, "data", [])
        if str(row.get("idx", "")).strip()
    }
    resolved = _resolve_svg_devices(model_book, inventory)
    matched: set[tuple[str, str]] = set()
    unknown: list[str] = []
    name_mismatches: list[str] = []
    identity_issues: list[str] = []
    svg_device_ids: set[str] = set()
    svg_identity_counts: dict[tuple[str, str], int] = {}
    for item in resolved:
        block_name = str(item.get("dev_type", "")).strip()
        idx = str(item.get("idx", "")).strip()
        name = str(item.get("name", "")).strip()
        dev_id = str(item.get("dev_id", "")).strip()
        if dev_id:
            svg_device_ids.add(dev_id)
        if block_name and idx:
            identity = (block_name, idx)
            svg_identity_counts[identity] = svg_identity_counts.get(identity, 0) + 1
        if not block_name or not idx or not name:
            missing_fields = [
                field
                for field, value in (("dev_type", block_name), ("idx", idx), ("name", name))
                if not value
            ]
            identity_issues.append(
                f"{dev_id or '--'} 缺少 {', '.join(missing_fields)}"
            )
            continue
        model_name = all_model_rows.get((block_name, idx))
        if model_name is None:
            unknown.append(dev_id or f"{block_name}/{name or idx or '--'}")
            continue
        if name and model_name and name != model_name:
            name_mismatches.append(
                f"{block_name}-{idx}: SVG={name}, E={model_name}"
            )
            continue
        if (block_name, idx) in by_type_idx:
            matched.add((block_name, idx))

    missing = [
        f"{block_name}-{idx}/{name}"
        for block_name, idx, name in expected
        if (block_name, idx) not in matched
    ]
    dangling_edges = [
        device_id
        for device_id in inventory.get("edge_device_ids", [])
        if str(device_id) not in svg_device_ids
    ]
    duplicate_devices = [
        f"{block_name}-{idx} 出现 {count} 次"
        for (block_name, idx), count in sorted(svg_identity_counts.items())
        if count > 1
    ]
    details = {
        "expected_device_count": len(expected),
        "svg_device_count": len(resolved),
        "matched_device_count": len(matched),
        "missing_in_svg": missing,
        "unknown_in_model": sorted(set(unknown)),
        "name_mismatches": sorted(set(name_mismatches)),
        "dangling_edges": sorted(set(dangling_edges)),
        "identity_issues": sorted(set(identity_issues)),
        "duplicate_devices": duplicate_devices,
    }
    mismatch_count = sum(
        len(details[key])
        for key in (
            "missing_in_svg",
            "unknown_in_model",
            "name_mismatches",
            "dangling_edges",
            "identity_issues",
            "duplicate_devices",
        )
    )
    if mismatch_count:
        summary_parts = []
        if missing:
            summary_parts.append(f"E 中有 {len(missing)} 台设备未出现在 SVG")
        if unknown:
            summary_parts.append(f"SVG 中有 {len(set(unknown))} 台设备无法在 E 中定位")
        if name_mismatches:
            summary_parts.append(f"有 {len(set(name_mismatches))} 台设备名称不一致")
        if dangling_edges:
            summary_parts.append(f"有 {len(set(dangling_edges))} 个连线端点未绑定图元")
        if identity_issues:
            summary_parts.append(f"有 {len(set(identity_issues))} 个 SVG 图元身份字段不完整")
        if duplicate_devices:
            summary_parts.append(f"有 {len(duplicate_devices)} 个 SVG 设备稳定索引重复")
        return {
            "id": "diagram",
            "label": "E/SVG 匹配性",
            "status": "failed",
            "message": "；".join(summary_parts) + "。",
            "details": details,
        }
    return {
        "id": "diagram",
        "label": "E/SVG 匹配性",
        "status": "passed",
        "message": f"E 与 SVG 的 {len(expected)} 台可视设备身份、索引和名称一致。",
        "details": details,
    }


def _repair_fixed_boundaries(model_book: EBook) -> list[dict]:
    return simu_loop.repair_fixed_boundary_setpoints(model_book)


_FIXED_BOUNDARY_CONTROL_FIELD_ALIASES = {
    "pressure_set": {"pressure_set", "p_set"},
    "supply_temperature_set": {"supply_temperature_set", "supply_temperature"},
    "return_temperature_set": {"return_temperature_set", "return_temperature"},
    "enthalpy_set": {"enthalpy_set", "h_set"},
}


def _repair_fixed_boundary_control_rows(model_book: EBook, control_book: EBook) -> list[dict]:
    """Repair invalid effective boundaries introduced by persisted SetValue rows."""
    set_block = control_book.data.get("SetValue")
    if set_block is None or not getattr(set_block, "data", []):
        return []

    effective_book = copy.deepcopy(model_book)

    run_block = control_book.data.get("RunStat")
    for run_row in [] if run_block is None else getattr(run_block, "data", []):
        dev_type = str(run_row.get("dev_type", "")).strip()
        dev_name = str(run_row.get("dev_name", "")).strip()
        block = effective_book.data.get(dev_type)
        if block is None:
            continue
        targets = [row for row in block.data if _row_name(row) == dev_name]
        if len(targets) == 1:
            targets[0]["run_stat"] = run_row.get("run_stat", "")

    applied_rows: dict[tuple[str, str, str], list[dict]] = {}
    for control_row in set_block.data:
        dev_type = str(control_row.get("dev_type", "")).strip()
        dev_name = str(control_row.get("dev_name", "")).strip()
        set_type = str(control_row.get("set_type", "")).strip()
        block = effective_book.data.get(dev_type)
        if not dev_type or not dev_name or not set_type or block is None:
            continue
        targets = [row for row in block.data if _row_name(row) == dev_name]
        if len(targets) != 1:
            continue
        targets[0][set_type] = control_row.get("set_value", "")
        applied_rows.setdefault((dev_type, dev_name, set_type), []).append(control_row)

    corrections = _repair_fixed_boundaries(effective_book)
    for item in corrections:
        dev_type = str(item["device_type"])
        dev_name = str(item["name"])
        field = str(item["field"])
        set_types = _FIXED_BOUNDARY_CONTROL_FIELD_ALIASES.get(field, {field})
        for set_type in set_types:
            for control_row in applied_rows.get((dev_type, dev_name, set_type), ()):
                control_row["set_value"] = format(item["replacement"], ".15g")
    return corrections


def _ensure_dcac_dcp_control_rows(model_book: EBook, control_book: EBook) -> None:
    _validate_dcac_converter_schema(model_book)
    _repair_fixed_boundaries(model_book)
    converter_block = model_book.data.get("DCACConverter")
    converter_rows = [] if converter_block is None else list(getattr(converter_block, "data", []))
    if not converter_rows:
        return

    set_block = control_book.data.get("SetValue")
    if set_block is None:
        set_block = EBlock("SetValue")
        set_block.header_list = list(STAT_HEADERS["SetValue"])
        set_block.data = []
        control_book.data["SetValue"] = set_block
    required_headers = set(STAT_HEADERS["SetValue"])
    missing_headers = sorted(required_headers - set(getattr(set_block, "header_list", [])))
    if missing_headers:
        raise ValueError(
            f"control.e SetValue 缺少必需字段: {', '.join(missing_headers)}"
        )

    rows = list(getattr(set_block, "data", []))
    for converter in converter_rows:
        name = _row_name(converter)
        if not name:
            raise ValueError("DCACConverter 存在缺少 name 的设备")
        matches = [
            row
            for row in rows
            if str(row.get("dev_type", "")).strip() == "DCACConverter"
            and str(row.get("dev_name", "")).strip() == name
            and str(row.get("set_type", "")).strip() == "p_dc_set"
        ]
        if len(matches) > 1:
            raise ValueError(
                f"control.e 中 DCACConverter.{name}.p_dc_set 遥调定义重复"
            )
        if matches:
            continue
        row = {
            "dev_type": "DCACConverter",
            "dev_name": name,
            "set_type": "p_dc_set",
            "set_value": converter.get("p_dc_set", 0),
        }
        set_block.data.append(row)
        rows.append(row)


def _storage_source_rows(model_book: EBook) -> list[dict]:
    storage_rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for block_name, generator_type, index_field in STORAGE_PARAMETER_SPECS:
        generators = {
            str(row.get("idx", "")): row
            for row in _rows(model_book, generator_type)
            if str(row.get("idx", ""))
        }
        for pos, row in enumerate(_rows(model_book, block_name), start=1):
            source = generators.get(str(row.get(index_field, "")))
            if source is None:
                continue
            name = _row_name(source)
            key = (generator_type, name)
            if not name or key in seen:
                continue
            storage_rows.append(
                {
                    "dev_type": generator_type,
                    "idx": source.get("idx", row.get("idx", pos)),
                    "name": name,
                    "soc_curr": _storage_soc_value(
                        _first_present(row, ("state_of_charge", "soc_curr", "soc_cur", "soc"), 0.5),
                        0.5,
                    ),
                }
            )
            seen.add(key)

    return storage_rows


def _generated_control_blocks(model_book: EBook) -> Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]]:
    _repair_fixed_boundaries(model_book)
    run_rows: list[dict[str, Any]] = []
    cb_rows: list[dict[str, Any]] = []
    set_rows: list[dict[str, Any]] = []
    set_row_keys: set[tuple[str, str, str]] = set()

    for block_name, block in model_book.data.items():
        headers = set(getattr(block, "header_list", []))
        for row in getattr(block, "data", []):
            name = _row_name(row)
            if not name:
                continue
            active_converter_power_field = ""
            if block_name == "DCACConverter":
                active_converter_power_field = next(
                    (
                        field
                        for field in converter_power_setpoint_fields(row)
                        if field in row
                    ),
                    "",
                )
            if "run_stat" in headers:
                run_rows.append(
                    {
                        "dev_type": block_name,
                        "dev_name": name,
                        "run_stat": row.get("run_stat", 1),
                    }
                )
            if "status" in headers:
                cb_rows.append(
                    {
                        "dev_type": block_name,
                        "dev_name": name,
                        "status": row.get("status", 1),
                    }
                )
            for set_type, source_column in SET_VALUE_COLUMN_MAP.get(block_name, ()):
                if (
                    block_name == "DCACConverter"
                    and set_type in {"p_ac_set", "p_set"}
                    and set_type != active_converter_power_field
                ):
                    continue
                if source_column in row:
                    source_value = row.get(source_column, 0)
                else:
                    continue
                if block_name in {"ACLoad", "DCLoad"} and source_column == "pv0":
                    source_value = _numeric(row.get("pbase"), 1.0) * _numeric(source_value, 0.0)
                elif block_name == "ACLoad" and source_column == "qv0":
                    source_value = _numeric(row.get("qbase"), 1.0) * _numeric(source_value, 0.0)
                if source_value in (None, "", "-"):
                    continue
                set_row_key = (block_name, name, set_type)
                if set_row_key in set_row_keys:
                    continue
                set_row_keys.add(set_row_key)
                set_rows.append(
                    {
                        "dev_type": block_name,
                        "dev_name": name,
                        "set_type": set_type,
                        "set_value": source_value,
                    }
                )

    blocks: dict[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]] = {
        "RunStat": (STAT_HEADERS["RunStat"], run_rows),
        "SetValue": (STAT_HEADERS["SetValue"], set_rows),
    }
    if cb_rows:
        blocks["CbOpenStat"] = (STAT_HEADERS["CbOpenStat"], cb_rows)
    storage_rows = _storage_source_rows(model_book)
    if storage_rows:
        blocks["StorageSoc"] = (STAT_HEADERS["StorageSoc"], storage_rows)
    hydrogen_state_book = EBook({})
    simu_loop.ensure_hydrogen_storage_state_rows_book(hydrogen_state_book, model_book)
    hydrogen_state = hydrogen_state_book.data.get(simu_loop.HYDROGEN_STORAGE_STATE_BLOCK)
    if hydrogen_state is not None and hydrogen_state.data:
        blocks[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK] = (
            simu_loop.HYDROGEN_STORAGE_STATE_HEADERS,
            list(hydrogen_state.data),
        )
    return blocks


def _generated_measurement_book(
    model_book: EBook,
    control_blocks: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]],
) -> EBook:
    rows: list[dict[str, Any]] = []
    name_counts: dict[str, int] = {}
    storage_rows = list(control_blocks.get("StorageSoc", ((), ()))[1])
    storage_by_key = {
        (str(row.get("dev_type", "")), str(row.get("name", ""))): row
        for row in storage_rows
    }
    storage_names = set(storage_by_key)
    measured_storage_keys: set[tuple[str, str]] = set()

    def add(
        dev_type: str,
        dev_name: str,
        meas_type: str,
        *,
        weight: float = 10000.0,
        value: Any = 0.0,
        valid: int = 1,
    ) -> None:
        if not dev_name:
            return
        base_name = automatic_point_name(dev_type, dev_name, meas_type)
        count = name_counts.get(base_name, 0)
        name_counts[base_name] = count + 1
        name = base_name if count == 0 else f"{base_name}.{count + 1}"
        rows.append(
            {
                "idx": len(rows) + 1,
                "name": name,
                "dev_type": dev_type,
                "dev_name": dev_name,
                "meas_type": meas_type,
                "weight": weight,
                "valid": valid,
                "value": value,
            }
        )

    for block_name, meas_types in MEASUREMENT_TYPE_MAP.items():
        for row in _rows(model_book, block_name):
            name = _row_name(row)
            if not name:
                continue
            for meas_type in meas_types:
                add(block_name, name, meas_type)
            storage_key = (block_name, name)
            if storage_key in storage_names:
                add(block_name, name, "SOC", value=storage_by_key[storage_key].get("soc_curr", 0.5))
                measured_storage_keys.add(storage_key)

    for storage_key, storage_row in storage_by_key.items():
        if storage_key in measured_storage_keys:
            continue
        add(
            storage_key[0],
            storage_key[1],
            "SOC",
            value=storage_row.get("soc_curr", 0.5),
        )

    for weather_key, _name_suffix, meas_type in WEATHER_MEASUREMENTS:
        value = _to_float(DEFAULT_WEATHER.get(weather_key), None)
        add(
            "Environment",
            "weather",
            meas_type,
            weight=1.0,
            value=value if value is not None else 0.0,
            valid=1 if value is not None else 0,
        )

    for block_name, value_column, meas_type, _name_suffix in SIGNAL_MEASUREMENTS:
        for row in control_blocks.get(block_name, ((), ()))[1]:
            add(
                str(row.get("dev_type", "")),
                str(row.get("dev_name", "")),
                meas_type,
                weight=1.0,
                value=row.get(value_column, 1),
            )

    return _ebook_from_blocks({"Measurement": (MEAS_HEADER, rows)})


def _generated_weather_book() -> EBook:
    row = {
        **{key: UNKNOWN_WEATHER_VALUE if value is None else value for key, value in DEFAULT_WEATHER.items()},
        "time": "00:00:00",
    }
    return _ebook_from_blocks({"Weather": (WEATHER_HEADER, [row])})


def _load_base_kw(row: Mapping[str, Any], block_name: str) -> float:
    if block_name == "ACLoad":
        pbase = _numeric(row.get("pbase"), 0.0)
        pv0 = _numeric(row.get("pv0", row.get("p_set", row.get("p", 0.0))), 0.0)
        if pbase not in (0.0, 1.0) and pv0:
            return max(0.0, pbase * pv0)
        return max(0.0, pv0 or pbase or _numeric(row.get("p_set"), 0.0))
    return max(0.0, _numeric(_first_present(row, ("p_set", "p", "p0", "p_kw"), 0.0), 0.0))


def _load_curve_sources(model_book: EBook) -> list[tuple[str, float]]:
    sources: list[tuple[str, float]] = []
    coupled_loads = {
        (
            str(binding.get("target_dev_type", "")),
            str(binding.get("target_dev_name", "")),
        )
        for bindings in energy_coupling_control_bindings(model_book).values()
        for binding in bindings
        if binding.get("set_type") == "p_set"
        and binding.get("target_dev_type") in {"ACLoad", "DCLoad"}
    }
    for block_name in ("ACLoad", "DCLoad"):
        for row in _rows(model_book, block_name):
            name = _row_name(row)
            if name and (block_name, name) not in coupled_loads:
                sources.append((name, _load_base_kw(row, block_name) or DEFAULT_WEATHER["load_kw"]))
    return sources


def _generated_curves_payload(model_book: EBook) -> dict[str, Any]:
    point_count = 1440
    load_sources = _load_curve_sources(model_book)
    weather: list[dict[str, Any]] = []
    loads: dict[str, list[dict[str, Any]]] = {name: [] for name, _base in load_sources}
    for minute in range(point_count):
        day_angle = 2.0 * math.pi * minute / point_count
        solar_shape = max(0.0, math.sin(math.pi * (minute - 360) / 720.0))
        wind_speed = max(0.0, min(50.0, 14.0 + 8.0 * math.sin(day_angle - 0.9) + 3.0 * math.sin(4.0 * day_angle)))
        air_temp = -20.0 + 7.0 * math.sin(day_angle - math.pi / 2.0)
        weather.append(
            {
                "minute": minute,
                "wind_speed_mps": round(wind_speed, 3),
                "air_temp_c": round(air_temp, 3),
                "air_pressure_hpa": round(960.0 + 4.0 * math.sin(day_angle + 0.5), 3),
                "solar_irradiance_w_m2": round(720.0 * solar_shape, 3),
                "humidity_pct": round(72.0 + 8.0 * math.sin(day_angle + 1.2), 3),
            }
        )
        load_shape = 0.88 + 0.12 * math.sin(day_angle - 1.1) + (0.16 if 1020 <= minute <= 1320 else 0.0)
        for name, base_kw in load_sources:
            loads.setdefault(name, []).append({"minute": minute, "p_kw": round(max(0.0, base_kw * load_shape), 3)})
    return {
        "mode": "day",
        "time_step_minutes": 1,
        "point_count": point_count,
        "weather": weather,
        "loads": loads,
        "sources": [
            {**item, "points": [{"minute": 0.0, "value": item["default_value"]}]}
            for item in source_curve_catalog(model_book)
        ],
    }


def _generated_model_artifacts(
    model_text: str,
    *,
    svg_devices: Sequence[Mapping[str, Any]] = (),
    allow_schema_repairs: bool = False,
    schema_repairs: Optional[list[dict[str, str]]] = None,
) -> Mapping[str, Any]:
    if not str(model_text or "").strip():
        raise ValueError("model.e 不能为空")
    model_book = _book_from_text(model_text)
    _remove_ambiguous_converter_runtime_fields(model_book)
    for block in model_book.data.values():
        for field in getattr(block, "header_list", []):
            if not is_ratio_parameter_field(field):
                continue
            allow_out_of_range = is_soc_parameter_field(field) and str(field).casefold() in {
                "state_of_charge",
                "soc",
                "soc_curr",
                "soc_cur",
            }
            for row in getattr(block, "data", []):
                if row.get(field, "") == "":
                    continue
                row[field] = canonical_ratio_parameter_text(
                    field,
                    row[field],
                    legacy_percent_points=True,
                    allow_out_of_range=allow_out_of_range,
                )
    if not _model_book_has_power_model(model_book):
        raise ValueError("model.e 中未找到可识别的电网模型设备块")
    if allow_schema_repairs:
        repairs = _repair_power_model_schema(model_book, svg_devices)
        if schema_repairs is not None:
            schema_repairs.extend(repairs)
    _validate_power_model_schema(model_book)
    _validate_dcac_converter_schema(model_book)
    _repair_fixed_boundaries(model_book)

    control_blocks = _generated_control_blocks(model_book)
    return {
        "model_book": model_book,
        "stat_book": _ebook_from_blocks(control_blocks),
        "control_book": _ebook_from_blocks(control_blocks),
        "meas_book": _generated_measurement_book(model_book, control_blocks),
        "weather_book": _generated_weather_book(),
        "curves_payload": _generated_curves_payload(model_book),
    }


def _preflight_model_import(
    model_text: str,
    *,
    diagram_svg_text: Optional[str] = None,
    source_label: str = "model.e",
) -> Mapping[str, Any]:
    """Validate and solve an uploaded model without touching its target folder."""

    started = time.perf_counter()
    schema_repairs: list[dict[str, str]] = []
    inventory: Mapping[str, Any]
    diagram_parse_error = ""
    try:
        inventory = _diagram_svg_inventory(diagram_svg_text)
    except ValueError as exc:
        inventory = {"svg": diagram_svg_text, "devices": [], "edge_device_ids": []}
        diagram_parse_error = str(exc)

    artifacts: Optional[Mapping[str, Any]] = None
    schema_error = ""
    try:
        artifacts = _generated_model_artifacts(
            model_text,
            svg_devices=inventory.get("devices", []),
            allow_schema_repairs=True,
            schema_repairs=schema_repairs,
        )
        schema_check: Mapping[str, Any] = {
            "id": "schema",
            "label": "必要字段",
            "status": "repaired" if schema_repairs else "passed",
            "message": (
                f"已自动补齐 {len(schema_repairs)} 个可确定的必要字段默认值。"
                if schema_repairs
                else "必要字段完整，无需自动补值。"
            ),
            "repairs": schema_repairs,
        }
    except (ValueError, OSError) as exc:
        schema_error = str(exc)
        schema_check = {
            "id": "schema",
            "label": "必要字段",
            "status": "failed",
            "message": schema_error,
            "repairs": schema_repairs,
        }

    if diagram_parse_error:
        diagram_check: Mapping[str, Any] = {
            "id": "diagram",
            "label": "E/SVG 匹配性",
            "status": "failed",
            "message": diagram_parse_error,
            "details": {
                "missing_in_svg": [],
                    "unknown_in_model": [],
                    "name_mismatches": [],
                    "dangling_edges": [],
                    "identity_issues": [],
                    "duplicate_devices": [],
            },
        }
    elif artifacts is None:
        diagram_check = {
            "id": "diagram",
            "label": "E/SVG 匹配性",
            "status": "blocked",
            "message": "E 文件必要字段校验失败，无法继续核对 SVG 设备身份。",
            "details": {
                "missing_in_svg": [],
                "unknown_in_model": [],
                "name_mismatches": [],
                "dangling_edges": [],
                "identity_issues": [],
                "duplicate_devices": [],
            },
        }
    else:
        diagram_check = _diagram_model_match_result(artifacts["model_book"], inventory)

    if artifacts is None:
        power_flow_check: Mapping[str, Any] = {
            "id": "power_flow",
            "label": "单次潮流",
            "status": "blocked",
            "message": "E 文件必要字段校验失败，未执行潮流计算。",
            "solver_info": "",
        }
    else:
        power_flow_started = time.perf_counter()
        try:
            _snapshot, solver_info = simu_loop.solve_hybrid_snapshot_from_book(
                copy.deepcopy(artifacts["model_book"]),
                Path(Path(str(source_label or "model.e")).name or "model.e"),
            )
            power_flow_check = {
                "id": "power_flow",
                "label": "单次潮流",
                "status": "passed",
                "message": f"潮流计算收敛：{solver_info}",
                "solver_info": solver_info,
                "duration_ms": round((time.perf_counter() - power_flow_started) * 1000.0, 3),
            }
        except Exception as exc:
            power_flow_check = {
                "id": "power_flow",
                "label": "单次潮流",
                "status": "failed",
                "message": f"潮流计算不收敛或无法建立网络：{exc}",
                "solver_info": str(exc),
                "duration_ms": round((time.perf_counter() - power_flow_started) * 1000.0, 3),
            }

    checks = [power_flow_check, schema_check, diagram_check]
    failed_checks = [
        item
        for item in checks
        if item.get("status") in {"failed", "blocked"}
    ]
    ok = not failed_checks
    signature_source = (
        str(model_text or "")
        + "\0"
        + str(inventory.get("svg") or diagram_svg_text or "")
    ).encode("utf-8", errors="replace")
    if ok:
        summary = (
            "模型预校核通过：必要字段、E/SVG 匹配性和单次潮流均满足加载条件。"
            if inventory.get("svg") is not None
            else "模型预校核通过：必要字段和单次潮流满足加载条件；未提供 SVG，匹配性校验已跳过。"
        )
    else:
        failed_labels = "、".join(str(item.get("label") or item.get("id")) for item in failed_checks)
        summary = f"模型预校核未通过：{failed_labels}。模型文件未写入。"
    validation = {
        "ok": ok,
        "status": "passed" if ok else "failed",
        "summary": summary,
        "source": str(source_label or "model.e"),
        "checks": checks,
        "repairs": schema_repairs,
        "signature": hashlib.sha256(signature_source).hexdigest(),
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }
    if not ok:
        raise ModelPreflightError(validation)
    assert artifacts is not None
    return {
        "artifacts": artifacts,
        "diagram_svg_text": inventory.get("svg"),
        "validation": validation,
    }


def _merge_generated_curves_payload(
    existing_payload: Mapping[str, Any],
    generated_payload: Mapping[str, Any],
) -> dict[str, Any]:
    merged = copy.deepcopy(dict(existing_payload))
    for key, value in generated_payload.items():
        if key not in {"loads", "sources"} and key not in merged:
            merged[key] = copy.deepcopy(value)

    existing_loads = existing_payload.get("loads", {})
    generated_loads = generated_payload.get("loads", {})
    existing_loads = existing_loads if isinstance(existing_loads, Mapping) else {}
    generated_loads = generated_loads if isinstance(generated_loads, Mapping) else {}

    try:
        target_count = int(merged.get("point_count", 0) or 0)
    except (TypeError, ValueError):
        target_count = 0
    if target_count <= 0:
        weather = merged.get("weather", [])
        target_count = len(weather) if isinstance(weather, list) else 0
    if target_count <= 0:
        for values in existing_loads.values():
            if isinstance(values, list):
                target_count = len(values)
                break

    template_points: list[Any] = []
    for values in existing_loads.values():
        if isinstance(values, list) and values:
            template_points = values
            break
    if not template_points:
        weather = merged.get("weather", [])
        if isinstance(weather, list):
            template_points = weather

    try:
        step_minutes = float(merged.get("time_step_minutes", 1) or 1)
    except (TypeError, ValueError):
        step_minutes = 1.0

    def default_curve(values: Any) -> Any:
        source = copy.deepcopy(values)
        if not isinstance(source, list) or not source or target_count <= 0 or len(source) == target_count:
            return source
        resized: list[Any] = []
        for index in range(target_count):
            source_index = min(len(source) - 1, int(index * len(source) / target_count))
            source_point = source[source_index]
            if not isinstance(source_point, Mapping):
                resized.append(copy.deepcopy(source_point))
                continue
            point = dict(source_point)
            if index < len(template_points) and isinstance(template_points[index], Mapping):
                time_fields = {
                    key: copy.deepcopy(value)
                    for key, value in template_points[index].items()
                    if key not in {"p_kw", "value", "load_kw"}
                }
                if time_fields:
                    point = {**time_fields, "p_kw": point.get("p_kw", 0.0)}
            elif "minute" in point:
                point["minute"] = round(index * step_minutes, 9)
            resized.append(point)
        return resized

    merged["loads"] = {
        str(name): (
            copy.deepcopy(existing_loads[name])
            if name in existing_loads
            else default_curve(values)
        )
        for name, values in generated_loads.items()
    }
    existing_sources = existing_payload.get("sources", [])
    generated_sources = generated_payload.get("sources", [])
    existing_by_identity = {
        source_curve_identity(item): item
        for item in existing_sources
        if isinstance(item, Mapping)
    } if isinstance(existing_sources, Sequence) and not isinstance(existing_sources, (str, bytes)) else {}
    merged["sources"] = [
        copy.deepcopy(existing_by_identity.get(source_curve_identity(item), item))
        for item in generated_sources
        if isinstance(item, Mapping)
    ] if isinstance(generated_sources, Sequence) and not isinstance(generated_sources, (str, bytes)) else []
    return merged


def _write_generated_model_artifacts(
    target_dir: Path,
    artifacts: Mapping[str, Any],
    *,
    diagram_svg_text: Optional[str] = None,
    remove_diagram_when_absent: bool = False,
    preserve_existing_curves: bool = False,
) -> list[str]:
    normalized_diagram = _normalize_diagram_svg_text(diagram_svg_text)
    target_dir.mkdir(parents=True, exist_ok=True)
    model_book = artifacts["model_book"]
    meas_book = artifacts["meas_book"]
    stat_book = artifacts["stat_book"]
    control_book = artifacts["control_book"]
    weather_book = artifacts["weather_book"]
    curves_payload = artifacts["curves_payload"]
    simu_loop.write_ebook_aligned(model_book, target_dir / "model.e")
    simu_loop.clear_model_book_cache(target_dir / "model.e")
    simu_loop.write_ebook_aligned(meas_book, target_dir / "meas.e")
    simu_loop.write_ebook_aligned(stat_book, target_dir / "stat.e")
    simu_loop.write_ebook_aligned(control_book, target_dir / "control.e")
    simu_loop.write_ebook_aligned(weather_book, target_dir / "weather.e")
    curves_path = target_dir / "curves.json"
    curves_to_write = curves_payload
    if preserve_existing_curves and curves_path.exists():
        try:
            existing_curves = json.loads(curves_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_curves = {}
        if isinstance(existing_curves, Mapping):
            curves_to_write = _merge_generated_curves_payload(existing_curves, curves_payload)
    _write_json_file(curves_path, curves_to_write)
    (target_dir / "curves.e").write_text(_curve_definition_text(curves_to_write), encoding="utf-8")
    written = ["model.e", "meas.e", "control.e", "stat.e", "weather.e", "curves.e", "curves.json"]
    if _write_model_diagram(target_dir, normalized_diagram, remove_when_absent=remove_diagram_when_absent):
        written.append(DIAGRAM_FILE_NAME)
    return written


def _recover_incomplete_model_directory(manager: Any, new_model_name: Any) -> Optional[Path]:
    """Move a non-model name collision aside without discarding its files."""
    raw_name = str(new_model_name or "").strip()
    target_id = raw_name if type(manager).__name__ == "SimulatorClusterManager" else _service_model_id(raw_name)
    if not target_id:
        return None
    models_root = Path(manager.models_root).resolve()
    target_dir = (models_root / target_id).resolve()
    try:
        target_dir.relative_to(models_root)
    except ValueError as exc:
        raise ValueError(f"模型名称无效: {new_model_name}") from exc
    if not target_dir.exists() or (target_dir / "model.e").exists():
        return None

    runtime_base = Path(
        getattr(manager, "runtime_root", getattr(manager, "runtime_dir", models_root.parent / "runtime"))
    ).resolve()
    recovery_root = runtime_base / ".incomplete-model-backups"
    recovery_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    recovery_dir = recovery_root / f"{target_id}-{timestamp}"
    target_dir.replace(recovery_dir)
    return recovery_dir


def create_model_from_efile(
    manager: MultiModelSimulator,
    new_model_name: Any,
    model_text: str,
    *,
    diagram_svg_text: Optional[str] = None,
    preflight_result: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Create one simulator source model folder from an uploaded model.e file."""
    artifacts = (
        preflight_result["artifacts"]
        if preflight_result is not None
        else _generated_model_artifacts(model_text)
    )
    with manager.lock:
        recovered_dir = _recover_incomplete_model_directory(manager, new_model_name)
        target_id = manager.validate_new_model_name(new_model_name)
        target_dir = (manager.models_root / target_id).resolve()
        try:
            written = _write_generated_model_artifacts(
                target_dir,
                artifacts,
                diagram_svg_text=diagram_svg_text,
            )
            manager._append_manifest_model(target_id, target_dir)
            model_info = manager.service_for(target_id).model_info()
        except Exception:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            raise
    meas_book = artifacts["meas_book"]
    curves_payload = artifacts["curves_payload"]
    result = {
        **model_info,
        "created": {
            "files": written,
            "measurement_count": len(meas_book.data["Measurement"].data),
            "curve_points": curves_payload["point_count"],
            "recovered_incomplete_directory": str(recovered_dir) if recovered_dir else "",
        },
    }
    if preflight_result is not None:
        result["validation"] = preflight_result["validation"]
    return result


def update_model_from_efile(
    manager: MultiModelSimulator,
    model_id: Any,
    model_text: str,
    *,
    diagram_svg_text: Optional[str] = None,
    replace_diagram: bool = False,
    preflight_result: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Replace an existing stopped model's source definitions from an uploaded model.e file."""
    target = manager.service_for(model_id)
    artifacts = (
        preflight_result["artifacts"]
        if preflight_result is not None
        else _generated_model_artifacts(model_text)
    )
    target_dir = Path(target.sim_dir).resolve()
    try:
        target_dir.relative_to(manager.models_root.resolve())
    except ValueError as exc:
        raise ValueError(f"模型目录无效，无法更新定义: {target.model_id}") from exc

    with target.definition_update_lock:
        with target.lock:
            _require_active_service_instance_locked(target)
            if target.clock.state != "stopped":
                raise ValueError(f"模型运行中或暂停中，无法更新定义: {target.model_id}")
            written = _write_generated_model_artifacts(
                target_dir,
                artifacts,
                diagram_svg_text=diagram_svg_text,
                remove_diagram_when_absent=replace_diagram,
                preserve_existing_curves=True,
            )
            target.reset_runtime_for_model_change()
            model_info = target.model_info()
    result = {
        **model_info,
        "updated": {
            "files": written,
            "measurement_count": len(artifacts["meas_book"].data["Measurement"].data),
            "curve_points": artifacts["curves_payload"]["point_count"],
        },
    }
    if preflight_result is not None:
        result["validation"] = preflight_result["validation"]
    return result


def _parse_definition_archive(data: bytes) -> Mapping[str, Any]:
    try:
        with zipfile.ZipFile(BytesIO(data), mode="r") as archive:
            model_text = _read_zip_text(archive, "model.e")
            meas_text = _read_zip_text(archive, "meas.e")
            control_text = _read_zip_text(archive, "control.e")
            curves_text = _read_zip_text(archive, "curves.e")
            diagram_text = _read_zip_text(archive, DIAGRAM_FILE_NAME)
            definition_defaults_text = _read_zip_text(
                archive,
                DEFINITION_DEFAULTS_FILE,
                required=False,
            )
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid definition archive") from exc

    definition_defaults: Optional[Mapping[str, Any]] = None
    if definition_defaults_text is not None:
        try:
            parsed_defaults = json.loads(definition_defaults_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid {DEFINITION_DEFAULTS_FILE}") from exc
        if not isinstance(parsed_defaults, Mapping):
            raise ValueError(f"Invalid {DEFINITION_DEFAULTS_FILE}")
        raw_statuses = parsed_defaults.get("measurement_statuses", {})
        if not isinstance(raw_statuses, Mapping):
            raise ValueError(f"Invalid {DEFINITION_DEFAULTS_FILE}: measurement_statuses must be an object")
        raw_median_deviations = parsed_defaults.get("measurement_median_deviations", {})
        if not isinstance(raw_median_deviations, Mapping):
            raise ValueError(
                f"Invalid {DEFINITION_DEFAULTS_FILE}: "
                "measurement_median_deviations must be an object"
            )
        median_deviations: dict[str, float] = {}
        for raw_name, raw_value in raw_median_deviations.items():
            name = str(raw_name).strip()
            value = _to_float(raw_value, None)
            if not name or value is None or not math.isfinite(value):
                raise ValueError(
                    f"Invalid {DEFINITION_DEFAULTS_FILE}: "
                    f"measurement_median_deviations[{raw_name!r}] must be finite"
                )
            if value != 0.0:
                median_deviations[name] = float(value)
        definition_defaults = {
            "version": int(_to_float(parsed_defaults.get("version"), 1) or 1),
            "measurement_statuses": {
                str(name): dict(value)
                for name, value in raw_statuses.items()
                if str(name).strip() and isinstance(value, Mapping)
            },
            "measurement_median_deviations": median_deviations,
        }

    assert model_text is not None and meas_text is not None and control_text is not None and curves_text is not None
    model_book = _book_from_text(model_text)
    removed_runtime_fields = _remove_ambiguous_converter_runtime_fields(model_book)
    diagram_inventory = _diagram_svg_inventory(diagram_text)
    schema_repairs = _repair_power_model_schema(
        model_book,
        diagram_inventory.get("devices", []),
    )
    _validate_power_model_schema(model_book)
    _validate_dcac_converter_schema(model_book)
    fixed_boundary_corrections = _repair_fixed_boundaries(model_book)
    if removed_runtime_fields or schema_repairs or fixed_boundary_corrections:
        model_text = render_ebook_aligned(model_book)
    measurement_book = _book_from_text(meas_text)
    measurement_block = measurement_book.data.get("Measurement")
    measurement_rows = (
        []
        if measurement_block is None
        else [
            [str(row.get(header, "")) for header in MEAS_HEADER]
            for row in measurement_block.data
        ]
    )
    measurement_rows, added_measurements = (
        simu_loop.reconcile_hydrogen_inline_flow_measurements(
            model_book,
            measurement_rows,
        )
    )
    if added_measurements:
        meas_text = simu_loop.render_measurement_snapshot_aligned(
            (),
            measurement_rows,
            (),
        )
    control_book = _book_from_text(control_text)
    _ensure_dcac_dcp_control_rows(model_book, control_book)
    _repair_fixed_boundary_control_rows(model_book, control_book)
    return {
        "model_text": model_text,
        "meas_text": meas_text,
        "control_text": render_ebook_aligned(control_book),
        "curves_text": curves_text,
        "diagram_text": _normalize_diagram_svg_text(diagram_text),
        "schema_repairs": schema_repairs,
        "definition_defaults": definition_defaults,
        "curves_payload": _curves_from_definition_text(curves_text),
    }


def _apply_parsed_definition_archive_locked(
    service: PolarMicrogridSimulator,
    parsed: Mapping[str, Any],
) -> Mapping[str, Any]:
    _require_active_service_instance_locked(service)
    if service.clock.state != "stopped":
        raise ValueError(f"模型运行中或暂停中，无法更新定义: {service.model_id}")
    model_text = str(parsed["model_text"])
    meas_text = str(parsed["meas_text"])
    control_text = str(parsed["control_text"])
    curves_text = str(parsed["curves_text"])
    diagram_text = parsed.get("diagram_text")
    curves_payload = parsed["curves_payload"]
    written_files: list[str] = []
    root = Path(service.sim_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "model.e").write_text(model_text, encoding="utf-8", newline="")
    simu_loop.clear_model_book_cache(root / "model.e")
    (root / "meas.e").write_text(meas_text, encoding="utf-8", newline="")
    (root / "control.e").write_text(control_text, encoding="utf-8", newline="")
    (root / "curves.e").write_text(curves_text, encoding="utf-8", newline="")
    definition_defaults = parsed.get("definition_defaults")
    definition_defaults_path = root / DEFINITION_DEFAULTS_FILE
    if isinstance(definition_defaults, Mapping):
        _write_json_file(definition_defaults_path, definition_defaults)
    else:
        definition_defaults_path.unlink(missing_ok=True)
    diagram_written = _write_model_diagram(root, diagram_text, remove_when_absent=True)
    legacy_device = root / "device.e"
    if legacy_device.exists() and legacy_device.is_file():
        legacy_device.unlink()
    _merge_control_definition(root / "stat.e", control_text, model_text)
    _write_json_file(root / "curves.json", curves_payload)
    names = ["model.e", "meas.e", "control.e", "curves.e", "stat.e", "curves.json"]
    if isinstance(definition_defaults, Mapping):
        names.append(DEFINITION_DEFAULTS_FILE)
    if diagram_written:
        names.append(DIAGRAM_FILE_NAME)
    written_files.extend(str(root / name) for name in names)

    service.reset_runtime_for_model_change()
    return {
        "written": len(written_files),
        "files": written_files,
        "curve_mode": curves_payload.get("mode"),
        "curve_points": curves_payload.get("point_count"),
        "load_count": len(curves_payload.get("loads", {})),
        "diagram": diagram_written,
    }


def _apply_parsed_definition_archive(
    service: PolarMicrogridSimulator,
    parsed: Mapping[str, Any],
) -> Mapping[str, Any]:
    with service.definition_update_lock:
        with service.lock:
            return _apply_parsed_definition_archive_locked(service, parsed)


def _preflight_parsed_definition_archive(
    parsed: Mapping[str, Any],
    *,
    source_label: str = "definitions.zip/model.e",
) -> Mapping[str, Any]:
    preflight = _preflight_model_import(
        str(parsed["model_text"]),
        diagram_svg_text=parsed.get("diagram_text"),
        source_label=source_label,
    )
    prior_repairs = list(parsed.get("schema_repairs", []))
    if not prior_repairs:
        return preflight
    validation = copy.deepcopy(preflight["validation"])
    validation["repairs"] = prior_repairs + list(validation.get("repairs", []))
    for check in validation.get("checks", []):
        if check.get("id") != "schema":
            continue
        check["status"] = "repaired"
        check["repairs"] = validation["repairs"]
        check["message"] = (
            f"已自动补齐 {len(validation['repairs'])} 个可确定的必要字段默认值。"
        )
        break
    return {**preflight, "validation": validation}


def import_definition_archive(
    service: PolarMicrogridSimulator,
    data: bytes,
    *,
    source_label: str = "definitions.zip/model.e",
) -> Mapping[str, Any]:
    parsed = _parse_definition_archive(data)
    preflight = _preflight_parsed_definition_archive(parsed, source_label=source_label)
    imported = _apply_parsed_definition_archive(service, parsed)
    return {**imported, "validation": preflight["validation"]}


def import_definition_model(
    manager: MultiModelSimulator,
    source_model_id: Optional[str],
    new_model_name: Any,
    data: bytes,
    *,
    source_label: str = "definitions.zip/model.e",
) -> Mapping[str, Any]:
    manager.validate_new_model_name(new_model_name)
    parsed = _parse_definition_archive(data)
    preflight = _preflight_parsed_definition_archive(parsed, source_label=source_label)

    model_info = manager.clone_model(source_model_id, new_model_name)
    imported_service = manager.service_for(str(model_info["id"]))
    imported = _apply_parsed_definition_archive(imported_service, parsed)
    return {
        **model_info,
        "imported": imported,
        "validation": preflight["validation"],
    }


def make_definition_archive(service: PolarMicrogridSimulator) -> tuple[str, bytes]:
    model_path = _definition_file_path(service, "model", "model.e")
    meas_path = _definition_file_path(service, "meas", "meas.e")
    stat_path = _definition_file_path(service, "stat", "stat.e")
    missing = [str(path) for path in (model_path, meas_path, stat_path) if not path.exists()]
    if missing:
        raise JsonApiError(404, f"Definition file not found: {', '.join(missing)}")

    with service.definition_update_lock:
        _require_active_service_instance_locked(service)
        snapshot = service.definition_snapshot
        manual_changes = tuple(service._manual_definition_changes.values())
        has_device_overrides = any(item.get("kind") == "device" for item in manual_changes)
        has_measurement_overrides = any(item.get("kind") == "measurement" for item in manual_changes)

        model_data = (
            render_ebook_aligned(snapshot.model_book).encode("utf-8")
            if has_device_overrides
            else model_path.read_bytes()
        )
        reconciled_measurement_rows, added_measurements = (
            simu_loop.reconcile_hydrogen_inline_flow_measurements(
                snapshot.model_book,
                snapshot.measurement_rows,
            )
        )
        try:
            _source_before, source_measurement_rows, _source_after = (
                simu_loop.parse_measurement_rows(meas_path)
            )
            _source_rows, source_added_measurements = (
                simu_loop.reconcile_hydrogen_inline_flow_measurements(
                    snapshot.model_book,
                    source_measurement_rows,
                )
            )
        except (OSError, RuntimeError, ValueError):
            source_added_measurements = added_measurements
        meas_data = (
            simu_loop.render_measurement_snapshot_aligned(
                snapshot.measurement_before,
                reconciled_measurement_rows,
                snapshot.measurement_after,
            ).encode("utf-8")
            if has_measurement_overrides or source_added_measurements
            else meas_path.read_bytes()
        )
        export_control_book = _book_from_text(render_ebook_aligned(service.control_book))
        _ensure_dcac_dcp_control_rows(snapshot.model_book, export_control_book)
        _repair_fixed_boundary_control_rows(snapshot.model_book, export_control_book)
        control_text = render_ebook_aligned(export_control_book)
        definition_defaults = {
            "version": 1,
            "measurement_statuses": service.effective_measurement_status_defaults(),
            "measurement_median_deviations": (
                service.effective_measurement_median_deviation_defaults()
            ),
        }
        diagram_path = Path(
            getattr(service, "source_files", {}).get(
                "diagram",
                service.sim_dir / DIAGRAM_FILE_NAME,
            )
        )
        diagram_data = (
            diagram_path.read_bytes()
            if diagram_path.exists() and diagram_path.is_file()
            else _fallback_definition_diagram_svg(service).encode("utf-8")
        )

    with service.curves_lock:
        curves_text = _curve_definition_text(service.curves)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_id = getattr(service, "model_id", "model") or "model"
    archive_name = f"{model_id}_definitions_{timestamp}.zip"

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("model.e", model_data)
        archive.writestr("meas.e", meas_data)
        archive.writestr("control.e", control_text.encode("utf-8"))
        archive.writestr("curves.e", curves_text.encode("utf-8"))
        archive.writestr(
            DEFINITION_DEFAULTS_FILE,
            (json.dumps(definition_defaults, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        archive.writestr(DIAGRAM_FILE_NAME, diagram_data)
    return archive_name, buffer.getvalue()
