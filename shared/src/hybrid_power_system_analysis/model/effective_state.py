"""Resolve composite-device run state before building load-flow inputs."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import re
from typing import Any, Dict, Hashable, Mapping, Optional, Tuple


_TERMINAL_SUFFIX = re.compile(r"_t\d+$", re.IGNORECASE)
_COUPLING_TABLE_RE = re.compile(
    r"^(AcE|DcE|Heat|Gas|Hydro|H2|Hydrogen|Steam)2"
    r"(AcE|DcE|Heat|Gas|Hydro|H2|Hydrogen|Steam)(?:\d+)?$",
    re.IGNORECASE,
)
_KNOWN_REFERENCE_ALIASES = {
    "acunit": ("ACUnit", "ACGenerator"),
    "dcunit": ("DCUnit", "DCGenerator"),
    "h2unit": ("H2Unit", "HydroSource"),
    "hydrounit": ("HydroUnit", "HydroSource"),
    "h2source": ("H2Source", "HydroSource"),
    "h2load": ("H2Load", "HydroLoad"),
    "h2storage": ("H2Storage", "HydroStorage"),
    "hydrosource": ("HydroSource",),
    "hydroload": ("HydroLoad",),
    "hydrostorage": ("HydroStorage",),
    "heatunit": ("HeatUnit", "HeatSource", "HeatSource2"),
    "heatsource": ("HeatSource", "HeatSource2"),
    "heatsource2": ("HeatSource2", "HeatSource"),
    "heatload": ("HeatLoad", "HeatLoad2"),
    "heatload2": ("HeatLoad2", "HeatLoad"),
    "heatstorage": ("HeatStorage",),
    "gasunit": ("GasUnit", "GasSource"),
    "gassource": ("GasSource",),
    "gasload": ("GasLoad",),
    "gasstorage": ("GasStorage",),
    "steamunit": ("SteamUnit", "SteamSource"),
    "steamsource": ("SteamSource",),
    "steamload": ("SteamLoad",),
    "steamstorage": ("SteamStorage",),
}


@dataclass(frozen=True)
class _RowNode:
    table: str
    row_pos: int
    index: Hashable
    name: str
    own_online: bool
    run_stat_col: Optional[int]


def _normalized_name(value: Any) -> str:
    return "".join(char.lower() for char in str(value) if char.isalnum())


def _canonical_index(value: Any) -> Optional[Hashable]:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return text
    if math.isfinite(number) and number.is_integer():
        return int(number)
    return text


def _online(value: Any) -> bool:
    if value in (None, ""):
        return True
    try:
        return int(float(value)) == 1
    except (TypeError, ValueError):
        return str(value).strip().lower() in {"true", "on", "online", "running"}


def _column_positions(header) -> Dict[str, int]:
    return {str(name).strip().lower(): pos for pos, name in enumerate(header)}


def _reference_target(column_name: str, aliases: Mapping[str, str]) -> Optional[str]:
    name = str(column_name).strip().lower()
    if not name.startswith("idx_"):
        return None
    reference_name = _TERMINAL_SUFFIX.sub("", name[4:])
    return aliases.get(_normalized_name(reference_name))


def _table_aliases(rows: Mapping[str, Mapping[str, Any]]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for table_name in rows:
        aliases.setdefault(_normalized_name(table_name), str(table_name))
    for alias, candidates in _KNOWN_REFERENCE_ALIASES.items():
        if alias in aliases:
            continue
        for candidate in candidates:
            target_table = aliases.get(_normalized_name(candidate))
            if target_table is not None:
                aliases[alias] = target_table
                break
    return aliases


def propagate_composite_run_states(rows):
    """Return copy-on-write E rows with offline composite ancestors and energy-coupling interlocks applied.

    A relationship column uses the model convention ``idx_<child-table>_tN``
    (or ``idx_<child-table>``). The source mapping and its row objects are never
    changed. Only rows whose effective ``run_stat`` differs are copied.
    """

    if not isinstance(rows, Mapping):
        return rows, []

    aliases = _table_aliases(rows)
    relation_columns: Dict[str, Tuple[Tuple[int, str], ...]] = {}
    relevant_tables = set()
    for raw_table_name, table in rows.items():
        if not isinstance(table, Mapping):
            continue
        table_name = str(raw_table_name)
        refs = []
        for pos, column_name in enumerate(table.get("header_list", ())):
            target_table = _reference_target(column_name, aliases)
            if target_table is not None:
                refs.append((pos, target_table))
                relevant_tables.add(target_table)
        if refs:
            relation_columns[table_name] = tuple(refs)
            relevant_tables.add(table_name)
    if not relation_columns:
        return rows, []

    nodes: Dict[Tuple[str, Hashable], _RowNode] = {}

    for raw_table_name, table in rows.items():
        if not isinstance(table, Mapping):
            continue
        table_name = str(raw_table_name)
        if table_name not in relevant_tables:
            continue
        header = list(table.get("header_list", ()))
        table_rows = list(table.get("rows", ()))
        columns = _column_positions(header)
        index_col = columns.get("idx", columns.get("id"))
        if index_col is None:
            continue
        run_stat_col = columns.get("run_stat")
        name_col = columns.get("name")
        for row_pos, row in enumerate(table_rows):
            if index_col >= len(row):
                continue
            index = _canonical_index(row[index_col])
            if index is None:
                continue
            name = (
                str(row[name_col])
                if name_col is not None and name_col < len(row) and row[name_col] not in (None, "")
                else f"{table_name}[{index}]"
            )
            own_online = _online(row[run_stat_col]) if run_stat_col is not None and run_stat_col < len(row) else True
            nodes.setdefault(
                (table_name, index),
                _RowNode(
                    table=table_name,
                    row_pos=row_pos,
                    index=index,
                    name=name,
                    own_online=own_online,
                    run_stat_col=run_stat_col,
                ),
            )

    # 构建有向停运联锁图：
    # 1) 上级组合设备停运 -> 下级子设备停运（parent -> child）
    # 2) 多能耦合设备（如 AcE2Hydro/DcE2Hydro/Hydro2AcE/Hydro2DcE 等）任一端点停运 ->
    #    耦合父设备停运，并经由 (1) 联锁停运对端端点（child -> parent -> other_child），
    #    防止单侧停机或故障时对端脱离耦合约束凭空产/耗能。
    impact_edges: Dict[Tuple[str, Hashable], list[Tuple[str, Hashable]]] = {}
    for parent_key, parent in nodes.items():
        table = rows[parent.table]
        row = table.get("rows", ())[parent.row_pos]
        is_energy_coupling = _COUPLING_TABLE_RE.match(parent.table) is not None
        for column_pos, child_table in relation_columns.get(parent.table, ()):
            if column_pos >= len(row):
                continue
            child_index = _canonical_index(row[column_pos])
            if child_index is None:
                continue
            child_key = (child_table, child_index)
            if child_key in nodes:
                impact_edges.setdefault(parent_key, []).append(child_key)
                if is_energy_coupling:
                    impact_edges.setdefault(child_key, []).append(parent_key)

    blocker_by_key: Dict[Tuple[str, Hashable], Tuple[str, Hashable]] = {}
    queue: deque[Tuple[str, Hashable]] = deque()
    for key, node in nodes.items():
        if not node.own_online:
            blocker_by_key[key] = key
            queue.append(key)

    while queue:
        current_key = queue.popleft()
        blocker_key = blocker_by_key[current_key]
        for target_key in impact_edges.get(current_key, ()):
            if target_key in blocker_by_key:
                continue
            blocker_by_key[target_key] = blocker_key
            queue.append(target_key)

    changes = []
    for key, node in nodes.items():
        blocker_key = blocker_by_key.get(key)
        if not node.own_online or node.run_stat_col is None or blocker_key is None:
            continue
        blocker = nodes[blocker_key]
        changes.append((node, blocker))

    if not changes:
        return rows, []

    effective_rows = dict(rows)
    copied_table_rows: Dict[str, list] = {}
    overrides = []
    for node, blocker in changes:
        table_rows = copied_table_rows.get(node.table)
        if table_rows is None:
            source_table = rows[node.table]
            table_copy = dict(source_table)
            table_rows = list(source_table.get("rows", ()))
            table_copy["rows"] = table_rows
            effective_rows[node.table] = table_copy
            copied_table_rows[node.table] = table_rows
        row_copy = list(table_rows[node.row_pos])
        row_copy[node.run_stat_col] = 0
        table_rows[node.row_pos] = row_copy
        overrides.append(
            {
                "dev_type": node.table,
                "dev_idx": node.index,
                "dev_name": node.name,
                "source_run_stat": 1,
                "effective_run_stat": 0,
                "reason": "关联组合或耦合设备退运",
                "ancestor_type": blocker.table,
                "ancestor_idx": blocker.index,
                "ancestor_name": blocker.name,
            }
        )

    return effective_rows, overrides
