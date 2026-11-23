// 学员端模块：源荷曲线树、高 DPI Canvas 绘制与虚拟表（05-curves.js）
function curveDisplayMode(snapshot = state.snapshot || {}) {
  const curves = snapshot.curves || {};
  const boundary = snapshot.curve_boundary || {};
  const rawMode = String(curves.mode || boundary.mode || "").toLowerCase();
  if (CURVE_DISPLAY_MODES[rawMode]) return rawMode;
  const pointCount = Number(curves.point_count || curves.weather?.length || boundary.point_count || 0);
  if (pointCount === CURVE_DISPLAY_MODES.hour.pointCount) return "hour";
  if (pointCount === CURVE_DISPLAY_MODES.week.pointCount) return "week";
  if (pointCount === CURVE_DISPLAY_MODES.month.pointCount) return "month";
  if (pointCount === CURVE_DISPLAY_MODES.year.pointCount) return "year";
  return "day";
}

function curveDisplayModeDayCount(mode = curveDisplayMode()) {
  if (mode === "week") return 7;
  if (mode === "month") return 30;
  if (mode === "year") return 365;
  return 1;
}

function curveDisplayModeDurationMinutes(snapshot = state.snapshot || {}) {
  const mode = curveDisplayMode(snapshot);
  return CURVE_DISPLAY_MODES[mode]?.durationMinutes || CURVE_DISPLAY_MODES.day.durationMinutes;
}

function curveDisplayModeLabel(snapshot = state.snapshot || {}) {
  return CURVE_DISPLAY_MODES[curveDisplayMode(snapshot)]?.label || CURVE_DISPLAY_MODES.day.label;
}

function formatTraineeClockDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value >= 3600 && value % 3600 === 0) return `${formatOverviewNumber(value / 3600)} h`;
  if (value >= 60 && value % 60 === 0) return `${formatOverviewNumber(value / 60)} min`;
  return `${formatOverviewNumber(value)} s`;
}

function curveDisplayConfig(snapshot = state.snapshot || {}) {
  const mode = curveDisplayMode(snapshot);
  const defaults = CURVE_DISPLAY_MODES[mode];
  const curves = snapshot.curves || {};
  const boundary = snapshot.curve_boundary || {};
  const loads = curves.loads && typeof curves.loads === "object" ? curves.loads : {};
  const maxLoadCount = Object.values(loads).reduce((maxCount, points) => (
    Math.max(maxCount, Array.isArray(points) ? points.length : 0)
  ), 0);
  const pointCount = Math.max(
    1,
    Number(curves.point_count || 0) || Math.max(Array.isArray(curves.weather) ? curves.weather.length : 0, maxLoadCount, Number(boundary.point_count) || 0, defaults.pointCount),
  );
  const rawStepMinutes = Number(curves.time_step_minutes || boundary.time_step_minutes || defaults.stepMinutes);
  const stepMinutes = Number.isFinite(rawStepMinutes) && rawStepMinutes > 0 ? rawStepMinutes : defaults.stepMinutes;
  return { ...defaults, pointCount, stepMinutes, durationMinutes: pointCount * stepMinutes };
}

function curveDisplayPointMinute(index, snapshot = state.snapshot || {}) {
  return index * curveDisplayConfig(snapshot).stepMinutes;
}

function curveDisplayLoadKey(loadName) {
  return `load:${loadName || "load"}`;
}

function curveDisplayLoadName(key) {
  return String(key || "").replace(/^load:/, "") || "load";
}

function curveDisplayLoadFamilyConfig(family) {
  return CURVE_DISPLAY_LOAD_FAMILIES.find((item) => item.key === family) || null;
}

function curveDisplayLoadFamilyForBlock(blockName) {
  const block = String(blockName || "").trim();
  return CURVE_DISPLAY_LOAD_FAMILIES.find((item) => item.blocks.includes(block))?.key || "other";
}

function curveDisplayLoads(snapshot = state.snapshot || {}) {
  const names = new Map(Object.keys(snapshot.curves?.loads || {}).map((name) => [name, {
    name,
    devType: "",
    family: "other",
    unit: "",
    valueKey: "value",
    min: null,
    max: null,
    defaultValue: 0,
  }]));
  const supportedBlocks = new Set(CURVE_DISPLAY_LOAD_FAMILIES.flatMap((item) => item.blocks));
  (snapshot.devices || []).forEach((dev) => {
    if ((
      deviceFamily(dev) === "load"
      || supportedBlocks.has(deviceModelBlock(dev))
    ) && deviceName(dev)) {
      const name = deviceName(dev);
      const devType = deviceModelBlock(dev);
      const family = curveDisplayLoadFamilyForBlock(devType);
      const config = curveDisplayLoadFamilyConfig(family);
      const setType = family === "hydrogen" ? "flow_set" : family === "heat" ? "heat_power" : "p_set";
      names.set(name, {
        name,
        devType,
        family,
        unit: config?.unit || "",
        valueKey: config?.valueKey || "value",
        min: Number(dev.raw?.[`${setType.replace(/_set$/, "")}_min`]),
        max: Number(dev.raw?.[`${setType.replace(/_set$/, "")}_max`]),
        defaultValue: Number(dev.raw?.[setType] ?? 0),
      });
    }
  });
  return Array.from(names.values()).sort((left, right) => left.name.localeCompare(right.name, "zh-Hans-CN"));
}

function curveDisplayLoadKeys(snapshot = state.snapshot || {}) {
  return curveDisplayLoads(snapshot).map((load) => curveDisplayLoadKey(load.name));
}

function curveDisplayLoadForKey(key, snapshot = state.snapshot || {}) {
  const name = curveDisplayLoadName(key);
  return curveDisplayLoads(snapshot).find((load) => load.name === name) || null;
}

function curveDisplayLoadFamilyKeys(family, snapshot = state.snapshot || {}) {
  return curveDisplayLoads(snapshot)
    .filter((load) => load.family === family)
    .map((load) => curveDisplayLoadKey(load.name));
}

function curveDisplaySourceCatalog(snapshot = state.snapshot || {}) {
  const sources = snapshot.curves?.sources;
  return Array.isArray(sources) ? sources.filter((item) => item?.key && item?.family) : [];
}

function curveDisplaySourceKeys(snapshot = state.snapshot || {}) {
  return curveDisplaySourceCatalog(snapshot).map((item) => item.key);
}

function curveDisplayAllKeys(snapshot = state.snapshot || {}) {
  return [...CURVE_DISPLAY_ENV_KEYS, ...curveDisplayLoadKeys(snapshot), ...curveDisplaySourceKeys(snapshot)];
}

function curveDisplayRawPoints(key, snapshot = state.snapshot || {}) {
  if (String(key).startsWith("load:")) {
    const loadName = curveDisplayLoadName(key);
    const points = snapshot.curves?.loads?.[loadName];
    return Array.isArray(points) ? points : [];
  }
  if (String(key).startsWith("source:")) {
    const source = curveDisplaySourceCatalog(snapshot).find((item) => item.key === key);
    return Array.isArray(source?.points) ? source.points : [];
  }
  return Array.isArray(snapshot.curves?.weather) ? snapshot.curves.weather : [];
}

function curveDisplayPointValue(point, key, snapshot = state.snapshot || {}) {
  if (!point) return null;
  if (String(key).startsWith("load:")) {
    const load = curveDisplayLoadForKey(key, snapshot);
    return Number(
      point[load?.valueKey || "value"]
      ?? point.value
      ?? point.p_kw
      ?? point.load_kw
      ?? point.flow_set
      ?? point.heat_power,
    );
  }
  if (String(key).startsWith("source:")) return Number(point.value ?? point.set_value);
  return Number(point[key]);
}

function curveDisplayMetaForKey(key, snapshot = state.snapshot || {}) {
  const meta = CURVE_DISPLAY_META.find((item) => item.key === key);
  if (meta) return meta;
  if (String(key).startsWith("source:")) {
    const source = curveDisplaySourceCatalog(snapshot).find((item) => item.key === key) || {};
    const sourceIndex = Math.max(0, curveDisplaySourceKeys(snapshot).indexOf(key));
    const values = curveDisplayRawPoints(key, snapshot)
      .map((point) => curveDisplayPointValue(point, key, snapshot))
      .filter((value) => Number.isFinite(value));
    const defaultValue = Number(source.default_value);
    const lower = Number(source.min);
    const upper = Number(source.max);
    const minimum = Number.isFinite(lower) ? lower : Math.min(0, ...(values.length ? values : [defaultValue || 0]));
    const dynamicMax = Math.max(...(values.length ? values : [defaultValue || 0, 1]));
    return {
      key,
      label: source.name || source.dev_name || key,
      color: CURVE_DISPLAY_SOURCE_COLORS[sourceIndex % CURVE_DISPLAY_SOURCE_COLORS.length],
      min: minimum,
      max: Number.isFinite(upper) ? upper : Math.max(1, dynamicMax * 1.12),
      digits: 3,
      unit: source.unit || "",
      family: source.family || "electric",
    };
  }
  const loadKeys = curveDisplayLoadKeys(snapshot);
  const load = curveDisplayLoadForKey(key, snapshot);
  const loadIndex = Math.max(0, loadKeys.indexOf(key));
  const values = curveDisplayRawPoints(key, snapshot)
    .map((point) => curveDisplayPointValue(point, key, snapshot))
    .filter((value) => Number.isFinite(value));
  const dynamicMax = values.length ? Math.max(...values) * 1.12 : CURVE_DISPLAY_LOAD_META.max;
  const lower = Number(load?.min);
  const upper = Number(load?.max);
  return {
    ...CURVE_DISPLAY_LOAD_META,
    key,
    label: curveDisplayLoadName(key),
    color: CURVE_DISPLAY_LOAD_COLORS[loadIndex % CURVE_DISPLAY_LOAD_COLORS.length],
    unit: load?.unit || CURVE_DISPLAY_LOAD_META.unit,
    family: load?.family || "other",
    min: Number.isFinite(lower) ? lower : 0,
    max: Number.isFinite(upper) && upper > (Number.isFinite(lower) ? lower : 0)
      ? upper
      : Math.max(dynamicMax, Number(load?.defaultValue) || 0, 1),
  };
}

function curveDisplayRoundValue(key, value, snapshot = state.snapshot || {}, meta = null) {
  const resolvedMeta = meta || curveDisplayMetaForKey(key, snapshot);
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Number(numeric.toFixed(resolvedMeta.digits));
}

function curveDisplayPointPairs(points, key, snapshot = state.snapshot || {}) {
  return (points || [])
    .map((point, index) => ({
      minute: Number(point.minute ?? index),
      value: curveDisplayPointValue(point, key, snapshot),
    }))
    .filter((point) => Number.isFinite(point.minute) && Number.isFinite(point.value))
    .sort((left, right) => left.minute - right.minute);
}

function curveDisplaySeries(key, snapshot = state.snapshot || {}) {
  const config = curveDisplayConfig(snapshot);
  const points = curveDisplayRawPoints(key, snapshot);
  const meta = curveDisplayMetaForKey(key, snapshot);
  const cacheKey = `${key}|${config.key}|${config.pointCount}|${config.stepMinutes}|${meta.digits}|${meta.min}`;
  let cache = state.curveDisplaySeriesCache.get(points);
  if (cache?.has(cacheKey)) return cache.get(cacheKey);
  if (!cache) {
    cache = new Map();
    state.curveDisplaySeriesCache.set(points, cache);
  }
  let values;
  if (points.length === config.pointCount) {
    values = points.map((point) => {
      const value = curveDisplayPointValue(point, key, snapshot);
      return curveDisplayRoundValue(key, Number.isFinite(value) ? value : meta.min, snapshot, meta);
    });
  } else {
    const pairs = curveDisplayPointPairs(points, key, snapshot);
    let pairIndex = 0;
    values = Array.from({ length: config.pointCount }, (_unused, index) => {
      const target = curveDisplayPointMinute(index, snapshot);
      let value = meta.min;
      if (pairs.length === 1 || target <= pairs[0]?.minute) {
        value = pairs[0]?.value ?? meta.min;
      } else if (target >= pairs[pairs.length - 1]?.minute) {
        value = pairs[pairs.length - 1]?.value ?? meta.min;
      } else if (pairs.length > 1) {
        while (pairIndex < pairs.length - 2 && target > pairs[pairIndex + 1].minute) pairIndex += 1;
        const left = pairs[pairIndex];
        const right = pairs[pairIndex + 1];
        const span = Math.max(1e-9, right.minute - left.minute);
        value = left.value + ((target - left.minute) / span) * (right.value - left.value);
      }
      return curveDisplayRoundValue(key, value, snapshot, meta);
    });
  }
  cache.set(cacheKey, values);
  return values;
}

function curveDisplaySeriesMap(keys, snapshot = state.snapshot || {}) {
  return new Map((keys || []).map((key) => [key, curveDisplaySeries(key, snapshot)]));
}

function selectedCurveDisplayKeys(snapshot = state.snapshot || {}) {
  const available = new Set(curveDisplayAllKeys(snapshot));
  const selected = Array.from(new Set(state.selectedCurveDisplayKeys || []))
    .filter((key) => available.has(key));
  state.selectedCurveDisplayKeys = selected;
  if (!selected.includes(state.activeCurveDisplayKey)) {
    state.activeCurveDisplayKey = selected[selected.length - 1] || "";
  }
  return selected;
}

function curveDisplayHiddenSet() {
  return new Set(state.hiddenCurveDisplayKeys || []);
}

function isCurveDisplaySeriesHidden(key) {
  return curveDisplayHiddenSet().has(key);
}

function visibleCurveDisplayKeys(snapshot = state.snapshot || {}) {
  return selectedCurveDisplayKeys(snapshot).filter((key) => !isCurveDisplaySeriesHidden(key));
}

function visibleCurveDisplayMetas(snapshot = state.snapshot || {}) {
  return visibleCurveDisplayKeys(snapshot).map((key) => curveDisplayMetaForKey(key, snapshot));
}

function toggleCurveDisplaySeriesVisibility(key, shouldRender = true) {
  if (!key) return;
  const hidden = curveDisplayHiddenSet();
  if (hidden.has(key)) hidden.delete(key);
  else hidden.add(key);
  state.hiddenCurveDisplayKeys = Array.from(hidden);
  state.activeCurveDisplayKey = key;
  if (shouldRender) {
    renderCurveDisplayTree(state.snapshot || {});
    drawCurveDisplay(state.snapshot || {});
  }
}

function curveDisplayFamilyKeys(family, snapshot = state.snapshot || {}) {
  if (family === "environment") return [...CURVE_DISPLAY_ENV_KEYS];
  if (family === "load") return curveDisplayLoadKeys(snapshot);
  if (String(family).startsWith("load:")) return curveDisplayLoadFamilyKeys(String(family).slice(5), snapshot);
  if (family === "source") return curveDisplaySourceKeys(snapshot);
  if (String(family).startsWith("source:")) {
    const sourceFamily = String(family).slice(7);
    return curveDisplaySourceCatalog(snapshot).filter((item) => item.family === sourceFamily).map((item) => item.key);
  }
  if (family === "electric") return curveDisplaySourceCatalog(snapshot).filter((item) => item.family === family).map((item) => item.key);
  if (family === "hydrogen") return curveDisplaySourceCatalog(snapshot).filter((item) => item.family === family).map((item) => item.key);
  if (family === "heat") return curveDisplaySourceCatalog(snapshot).filter((item) => item.family === family).map((item) => item.key);
  return [];
}

function setCurveDisplaySelection(keys, activeKey = keys?.[keys.length - 1], shouldRender = true) {
  const available = new Set(curveDisplayAllKeys(state.snapshot || {}));
  const previous = new Set(state.selectedCurveDisplayKeys || []);
  const selected = Array.from(new Set(keys || [])).filter((key) => available.has(key));
  state.selectedCurveDisplayKeys = selected;
  state.activeCurveDisplayKey = selected.includes(activeKey) ? activeKey : selected[selected.length - 1] || "";
  const hidden = curveDisplayHiddenSet();
  selected.filter((key) => !previous.has(key)).forEach((key) => hidden.delete(key));
  state.hiddenCurveDisplayKeys = Array.from(hidden);
  state.lastCurveDisplayTableKey = "";
  if (shouldRender) renderCurveDisplay(state.snapshot || {}, true);
}

function selectCurveDisplayButton(button, event = null) {
  const key = button?.dataset.curveDisplayKey || "";
  if (!key) return;
  const selected = selectedCurveDisplayKeys(state.snapshot || {});
  const selectedSet = new Set(selected);
  const multiSelect = Boolean(event?.ctrlKey || event?.metaKey || event?.shiftKey);
  const next = multiSelect
    ? selectedSet.has(key)
      ? selected.filter((selectedKey) => selectedKey !== key)
      : [...selected, key]
    : [key];
  if (!multiSelect) {
    const hidden = curveDisplayHiddenSet();
    hidden.delete(key);
    state.hiddenCurveDisplayKeys = Array.from(hidden);
  }
  const activeKey = next.includes(key) ? key : next[next.length - 1];
  setCurveDisplaySelection(next, activeKey, true);
}

function curveDisplaySelectedLabel(snapshot = state.snapshot || {}) {
  const selected = selectedCurveDisplayKeys(snapshot);
  if (!selected.length) return "未选择曲线";
  return selected.length <= 1 ? curveDisplayMetaForKey(selected[0], snapshot).label : `已选${selected.length}条`;
}

function curveDisplayTreeGroupCollapsed(groupKey) {
  return Boolean(state.curveDisplayTreeGroupCollapsed?.[groupKey]);
}

function toggleCurveDisplayTreeGroup(groupKey, shouldRender = true) {
  if (!groupKey) return;
  state.curveDisplayTreeGroupCollapsed = {
    ...(state.curveDisplayTreeGroupCollapsed || {}),
    [groupKey]: !curveDisplayTreeGroupCollapsed(groupKey),
  };
  localStorage.setItem(CURVE_DISPLAY_TREE_COLLAPSE_KEY, JSON.stringify(state.curveDisplayTreeGroupCollapsed));
  if (shouldRender) renderCurveDisplayTree(state.snapshot || {});
}

function curveDisplayTreeGroupHeader(groupKey, label, count, buttonAttrs, buttonClasses = "", forceExpanded = false) {
  const collapsed = !forceExpanded && curveDisplayTreeGroupCollapsed(groupKey);
  return `
    <button
      type="button"
      class="tree-node tree-type ${buttonClasses} ${collapsed ? "is-collapsed" : ""}"
      data-curve-display-tree-toggle="${escapeHtml(groupKey)}"
      aria-label="${collapsed ? "展开" : "折叠"}${escapeHtml(label)}"
      aria-expanded="${collapsed ? "false" : "true"}"
      ${buttonAttrs}
    >
      <span class="tree-title">
        <i class="tree-toggle" aria-hidden="true"></i>
        <span class="tree-title-text">${escapeHtml(label)}</span>
      </span>
      <strong>${count}</strong>
    </button>`;
}

function curveDisplayTreeMediumMeta(family = "") {
  return {
    environment: { label: "环境", marker: "环", order: 0 },
    electric: { label: "电", marker: "电", order: 1 },
    hydrogen: { label: "氢", marker: "氢", order: 2 },
    heat: { label: "热", marker: "热", order: 3 },
    other: { label: "其他", marker: "其", order: 4 },
  }[family] || { label: "其他", marker: "其", order: 4 };
}

function curveDisplayTreeItemMatches(item, query) {
  if (!query) return true;
  return [item.label, item.unit, item.medium?.label]
    .some((value) => String(value || "").toLocaleLowerCase("zh-CN").includes(query));
}

function curveDisplayTreeChildHtml(item, type, selectedSet) {
  return `
    <button
      type="button"
      class="tree-node tree-child ${selectedSet.has(item.key) ? "is-active" : ""} ${isCurveDisplaySeriesHidden(item.key) ? "is-hidden-series" : ""}"
      data-curve-display-tree-type="${escapeHtml(type)}"
      data-curve-display-key="${escapeHtml(item.key)}"
      data-curve-medium="${escapeHtml(item.family)}"
      aria-pressed="${selectedSet.has(item.key) ? "true" : "false"}"
      title="${escapeHtml(`${item.label} · ${item.medium.label} · ${item.unit || "无单位"}`)}"
    >
      <span class="curve-tree-item-main">
        <i class="curve-medium-marker is-${escapeHtml(item.family)}" aria-hidden="true">${escapeHtml(item.medium.marker)}</i>
        <span class="curve-tree-item-label">${escapeHtml(item.label)}</span>
      </span>
      <small>${escapeHtml(item.unit)}</small>
    </button>`;
}

function renderCurveDisplayTree(snapshot = state.snapshot || {}) {
  const container = $("curveDisplayTree");
  if (!container) return;
  const selected = selectedCurveDisplayKeys(snapshot);
  const selectedSet = new Set(selected);
  const loadKeys = curveDisplayLoadKeys(snapshot);
  const loadDevices = curveDisplayLoads(snapshot);
  const sourceKeys = curveDisplaySourceKeys(snapshot);
  const query = String(state.curveDisplayTreeSearch || "").trim().toLocaleLowerCase("zh-CN");
  const environmentItems = CURVE_DISPLAY_ENV_KEYS.map((key) => {
    const meta = curveDisplayMetaForKey(key, snapshot);
    return { key, label: meta.label, unit: meta.unit, family: "environment", medium: curveDisplayTreeMediumMeta("environment") };
  });
  const loadItems = loadDevices.map((load) => ({
    key: curveDisplayLoadKey(load.name),
    label: load.name,
    unit: load.unit || "",
    family: curveDisplayTreeMediumMeta(load.family).label === "其他" ? "other" : load.family,
    medium: curveDisplayTreeMediumMeta(load.family),
  })).sort((left, right) => left.medium.order - right.medium.order || left.label.localeCompare(right.label, "zh-CN"));
  const sourceItems = curveDisplaySourceCatalog(snapshot).map((source) => ({
    key: source.key,
    label: source.name || source.dev_name || source.key,
    unit: source.unit || "",
    family: curveDisplayTreeMediumMeta(source.family).label === "其他" ? "other" : source.family,
    medium: curveDisplayTreeMediumMeta(source.family),
  })).sort((left, right) => left.medium.order - right.medium.order || left.label.localeCompare(right.label, "zh-CN"));
  const groups = [
    { key: "environment", label: "环境曲线", type: "environment", keys: CURVE_DISPLAY_ENV_KEYS, items: environmentItems },
    { key: "load", label: "负荷曲线", type: "load", keys: loadKeys, items: loadItems },
    { key: "source", label: "供能曲线", type: "source", keys: sourceKeys, items: sourceItems },
  ].map((group) => ({
    ...group,
    visibleItems: group.label.toLocaleLowerCase("zh-CN").includes(query)
      ? group.items
      : group.items.filter((item) => curveDisplayTreeItemMatches(item, query)),
  }));
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  const visibleTotal = groups.reduce((sum, group) => sum + group.visibleItems.length, 0);
  $("curveDisplayTreeSummary").textContent = query ? `${visibleTotal}/${total} 条` : `${total} 条`;
  container.innerHTML = groups.filter((group) => !query || group.visibleItems.length).map((group) => {
    const groupSelected = group.keys.length && group.keys.every((key) => selectedSet.has(key));
    const groupPartial = !groupSelected && group.keys.some((key) => selectedSet.has(key));
    const collapsed = !query && curveDisplayTreeGroupCollapsed(group.key);
    return `
      <div class="tree-group">
        ${curveDisplayTreeGroupHeader(
          group.key,
          group.label,
          group.visibleItems.length,
          `data-curve-display-tree-type="${escapeHtml(group.type)}" data-curve-display-family="${escapeHtml(group.key)}" aria-pressed="${groupSelected ? "true" : "false"}"`,
          groupSelected ? "is-active" : groupPartial ? "is-parent-active" : "",
          Boolean(query),
        )}
        <div class="tree-children" ${collapsed ? "hidden" : ""}>
          ${group.visibleItems.map((item) => curveDisplayTreeChildHtml(item, group.type, selectedSet)).join("")}
        </div>
      </div>`;
  }).join("") || `<div class="empty-state">未匹配“${escapeHtml(state.curveDisplayTreeSearch || "")}”</div>`;
}

function renderCurveDisplayModeControls(snapshot = state.snapshot || {}) {
  const mode = curveDisplayMode(snapshot);
  document.querySelectorAll("[data-curve-display-mode]").forEach((button) => {
    const active = button.dataset.curveDisplayMode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.disabled = true;
  });
}

function formatCurveDisplayTableTime(minute, snapshot = state.snapshot || {}) {
  const mode = curveDisplayMode(snapshot);
  if (mode === "hour") {
    const totalSeconds = Math.max(0, Math.round(Number(minute) * 60));
    const minutePart = Math.floor(totalSeconds / 60);
    const secondPart = totalSeconds % 60;
    return `00:${String(minutePart).padStart(2, "0")}:${String(secondPart).padStart(2, "0")}`;
  }
  if (mode === "year") {
    const dayOfYear = Math.floor(minute / 1440);
    const hour = Math.floor((minute % 1440) / 60);
    const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let month = 0;
    let day = dayOfYear;
    while (month < monthDays.length - 1 && day >= monthDays[month]) {
      day -= monthDays[month];
      month += 1;
    }
    return `${String(month + 1).padStart(2, "0")}-${String(day + 1).padStart(2, "0")} ${String(hour).padStart(2, "0")}:00`;
  }
  if (mode === "week" || mode === "month") {
    const total = Math.max(0, Math.round(Number(minute)));
    const day = Math.floor(total / 1440) + 1;
    const minuteOfDay = total % 1440;
    const hour = Math.floor(minuteOfDay / 60);
    const minutePart = minuteOfDay % 60;
    return `第${day}天 ${String(hour).padStart(2, "0")}:${String(minutePart).padStart(2, "0")}`;
  }
  const total = Math.round(minute);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function renderCurveDisplayLabels(snapshot = state.snapshot || {}) {
  const config = curveDisplayConfig(snapshot);
  const pointCount = $("curveDisplayPointCount");
  const status = $("curveDisplayStatus");
  const activeLabel = $("curveDisplayActiveLabel");
  const tableTitle = $("curveDisplayTableTitle");
  const tableSummary = $("curveDisplayTableSummary");
  if (pointCount) pointCount.textContent = `${config.pointCount}点`;
  if (status) status.textContent = `${config.label} · 只读`;
  if (activeLabel) activeLabel.textContent = curveDisplaySelectedLabel(snapshot);
  if (tableTitle) tableTitle.textContent = config.tableTitle;
  if (tableSummary) tableSummary.textContent = config.tableSummary;
}

function resizeCurveDisplayCanvas() {
  const canvas = $("curveDisplayChart");
  if (!canvas) return false;
  const { width, height } = canvasRenderedSize(canvas, 900, 260);
  const dpr = canvasDevicePixelRatio();
  const physicalWidth = Math.max(1, Math.floor(width * dpr));
  const physicalHeight = Math.max(1, Math.floor(height * dpr));
  const changed = (
    canvas.width !== physicalWidth
    || canvas.height !== physicalHeight
    || Number(canvas.dataset.logicalWidth) !== width
    || Number(canvas.dataset.logicalHeight) !== height
    || Number(canvas.dataset.dpr) !== dpr
  );
  if (!changed) return false;
  canvas.width = physicalWidth;
  canvas.height = physicalHeight;
  canvas.dataset.logicalWidth = String(width);
  canvas.dataset.logicalHeight = String(height);
  canvas.dataset.dpr = String(dpr);
  return true;
}

function curveDisplayPlot(canvas) {
  const { width } = canvasLogicalSize(canvas, 900, 260);
  if (width < 640) return { left: 48, right: 12, top: 58, bottom: 30 };
  return CURVE_DISPLAY_PLOT;
}

function curveYAxisTicks(meta = {}, divisions = 5) {
  const min = Number(meta?.min);
  const max = Number(meta?.max);
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [];
  const segmentCount = Math.max(1, Math.floor(Number(divisions) || 5));
  const rawDigits = Number(meta?.digits);
  const digits = Math.max(0, Math.min(4, Number.isFinite(rawDigits) ? Math.floor(rawDigits) : 2));
  return Array.from({ length: segmentCount + 1 }, (_unused, index) => {
    const ratio = index / segmentCount;
    const value = Number((max - (max - min) * ratio).toFixed(digits));
    return { ratio, value, label: String(value) };
  });
}

function curveYAxisMeta(metas = [], preferredKey = "") {
  return metas.find((meta) => meta?.key === preferredKey) || metas[0] || null;
}

function drawCurveYAxis(ctx, canvas, plot, meta) {
  const ticks = curveYAxisTicks(meta, 5);
  if (!ticks.length) return;
  const { height } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const top = plot.top;
  const bottom = height - plot.bottom;
  ctx.save();
  ctx.font = "11px Microsoft YaHei, Arial";
  ctx.lineWidth = 1;
  ctx.strokeStyle = "#aebfc7";
  ctx.fillStyle = "#63717a";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.beginPath();
  ctx.moveTo(left, top);
  ctx.lineTo(left, bottom);
  ctx.stroke();
  ticks.forEach((tick) => {
    const y = top + tick.ratio * (bottom - top);
    ctx.beginPath();
    ctx.moveTo(left - 5, y);
    ctx.lineTo(left, y);
    ctx.stroke();
    ctx.fillText(tick.label, left - 8, y);
  });
  const unit = String(meta?.unit || "").trim();
  if (unit) {
    ctx.fillStyle = meta?.color || "#52656d";
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(unit, Math.max(4, left - 42), top - 10);
  }
  ctx.restore();
}

function curveDisplayValueToY(value, meta, canvas) {
  const plot = curveDisplayPlot(canvas);
  const { height } = canvasLogicalSize(canvas, 900, 260);
  const top = plot.top;
  const bottom = height - plot.bottom;
  const span = Math.max(1e-9, meta.max - meta.min);
  const ratio = (clamp(value, meta.min, meta.max) - meta.min) / span;
  return bottom - ratio * (bottom - top);
}

function drawCurveDisplayXAxis(ctx, canvas, plot, snapshot = state.snapshot || {}) {
  const { width, height } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  const mode = curveDisplayMode(snapshot);
  if (mode === "hour") {
    const minuteStep = width < 560 ? 15 : 10;
    const palette = chartThemePalette();
    for (let minute = 0; minute <= 60; minute += minuteStep) {
      const x = left + (minute / 60) * (right - left);
      ctx.strokeStyle = minute % 30 === 0 ? palette.axis : palette.gridSubtle;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = palette.text;
      const labelHour = Math.floor(minute / 60);
      const labelMinute = minute % 60;
      ctx.fillText(`${String(labelHour).padStart(2, "0")}:${String(labelMinute).padStart(2, "0")}`, x - 14, height - 12);
    }
    return;
  }
  if (mode === "week" || mode === "month") {
    const dayCount = curveDisplayModeDayCount(mode);
    const dayStep = mode === "week" ? 1 : width < 560 ? 10 : width < 900 ? 5 : 3;
    const palette = chartThemePalette();
    for (let day = 0; day <= dayCount; day += dayStep) {
      const x = left + (day / dayCount) * (right - left);
      ctx.strokeStyle = day === 0 || day === dayCount ? palette.axis : palette.gridSubtle;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = palette.text;
      const dayText = `第${Math.min(day + 1, dayCount)}天`;
      ctx.fillText(typeof translatePhrase === "function" ? translatePhrase(dayText) : dayText, x - 16, height - 12);
    }
    if (dayCount % dayStep !== 0) {
      ctx.textAlign = "right";
      const endText = `第${dayCount}天`;
      ctx.fillText(typeof translatePhrase === "function" ? translatePhrase(endText) : endText, right, height - 12);
      ctx.textAlign = "left";
    }
    return;
  }
  if (mode === "year") {
    const palette = chartThemePalette();
    const monthStarts = [["01月", 0], ["02月", 31], ["03月", 59], ["04月", 90], ["05月", 120], ["06月", 151], ["07月", 181], ["08月", 212], ["09月", 243], ["10月", 273], ["11月", 304], ["12月", 334]];
    const monthStep = width < 560 ? 3 : width < 900 ? 2 : 1;
    monthStarts.forEach(([label, day], index) => {
      if (index % monthStep !== 0) return;
      const x = left + (day / 365) * (right - left);
      ctx.strokeStyle = index % 3 === 0 ? palette.axis : palette.gridSubtle;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = palette.text;
      ctx.fillText(label, x - 12, height - 12);
    });
    ctx.fillStyle = palette.text;
    ctx.textAlign = "right";
    ctx.fillText(typeof translatePhrase === "function" ? translatePhrase("年末") : "年末", right, height - 12);
    ctx.textAlign = "left";
    return;
  }
  const palette = chartThemePalette();
  const hourStep = width < 480 ? 4 : width < 820 ? 3 : 2;
  for (let hour = 0; hour <= 24; hour += hourStep) {
    const x = left + (hour / 24) * (right - left);
    ctx.strokeStyle = hour % 6 === 0 ? palette.axis : palette.gridSubtle;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.fillStyle = palette.text;
    ctx.fillText(`${String(hour).padStart(2, "0")}:00`, x - 14, height - 12);
  }
}

function curveDisplayPointIndexFromX(x, canvas, snapshot = state.snapshot || {}) {
  const plot = curveDisplayPlot(canvas);
  const { width } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const right = width - plot.right;
  const pointCount = curveDisplayConfig(snapshot).pointCount;
  return clamp(Math.round(((x - left) / Math.max(1, right - left)) * (pointCount - 1)), 0, pointCount - 1);
}

function curveDisplayXFromPointIndex(index, canvas, snapshot = state.snapshot || {}) {
  const plot = curveDisplayPlot(canvas);
  const { width } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const right = width - plot.right;
  const pointCount = curveDisplayConfig(snapshot).pointCount;
  return left + (clamp(index, 0, pointCount - 1) / Math.max(1, pointCount - 1)) * (right - left);
}

function drawCurveDisplayCursor(ctx, canvas, plot, metas, seriesByKey, snapshot = state.snapshot || {}) {
  const cursor = state.curveDisplayCursor;
  if (!cursor.visible || !metas.length) return;
  const { width, height } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  const index = clamp(cursor.index, 0, curveDisplayConfig(snapshot).pointCount - 1);
  const x = curveDisplayXFromPointIndex(index, canvas, snapshot);
  const y = clamp(cursor.y, top, bottom);
  const tooltipMetas = metas.slice(0, 6);
  const timeLabel = formatCurveDisplayTableTime(curveDisplayPointMinute(index, snapshot), snapshot);

  ctx.save();
  ctx.strokeStyle = "rgba(29, 57, 66, 0.58)";
  ctx.lineWidth = 1;
  ctx.setLineDash([5, 4]);
  ctx.beginPath();
  ctx.moveTo(x, top);
  ctx.lineTo(x, bottom);
  ctx.moveTo(left, y);
  ctx.lineTo(right, y);
  ctx.stroke();
  ctx.setLineDash([]);

  const palette = chartThemePalette();
  tooltipMetas.forEach((meta) => {
    const values = seriesByKey.get(meta.key) || [];
    if (!values.length) return;
    const markerY = curveDisplayValueToY(values[index], meta, canvas);
    ctx.fillStyle = palette.markerFill;
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, markerY, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  ctx.font = "12px Microsoft YaHei, Arial";
  const lines = [
    `时刻: ${timeLabel}`,
    `点号: ${index + 1}`,
    ...tooltipMetas.map((meta) => `${meta.label}: ${formatNumber(seriesByKey.get(meta.key)?.[index])} ${meta.unit}`),
    metas.length > tooltipMetas.length ? `另有 ${metas.length - tooltipMetas.length} 条曲线` : "",
  ].filter(Boolean);
  const tooltipWidth = Math.max(158, ...lines.map((line) => ctx.measureText(line).width + 24));
  const tooltipHeight = 14 + lines.length * 18;
  let tooltipX = x + 14;
  let tooltipY = y + 14;
  if (tooltipX + tooltipWidth > right - 6) tooltipX = x - tooltipWidth - 14;
  if (tooltipY + tooltipHeight > bottom - 6) tooltipY = y - tooltipHeight - 14;
  tooltipX = clamp(tooltipX, left + 6, right - tooltipWidth - 6);
  tooltipY = clamp(tooltipY, top + 6, bottom - tooltipHeight - 6);
  ctx.fillStyle = palette.tooltipBg;
  ctx.strokeStyle = palette.tooltipBorder;
  ctx.beginPath();
  ctx.roundRect(tooltipX, tooltipY, tooltipWidth, tooltipHeight, 8);
  ctx.fill();
  ctx.stroke();
  lines.forEach((line, lineIndex) => {
    ctx.fillStyle = lineIndex < 2 ? palette.tooltipTitle : palette.tooltipText;
    ctx.fillText(line, tooltipX + 10, tooltipY + 18 + lineIndex * 18);
  });
  ctx.restore();
}

function drawCurveDisplay(snapshot = state.snapshot || {}, preparedSeries = null) {
  const canvas = $("curveDisplayChart");
  if (!canvas) return;
  resizeCurveDisplayCanvas();
  const { ctx, width, height } = prepareCanvas2D(canvas, 900, 260);
  if (!ctx) return;
  const palette = chartThemePalette();
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  const allMetas = selectedCurveDisplayKeys(snapshot).map((key) => curveDisplayMetaForKey(key, snapshot));
  const metas = allMetas.filter((meta) => !isCurveDisplaySeriesHidden(meta.key));
  const seriesByKey = preparedSeries || curveDisplaySeriesMap(allMetas.map((meta) => meta.key), snapshot);
  const activeKey = isCurveDisplaySeriesHidden(state.activeCurveDisplayKey) ? "" : state.activeCurveDisplayKey;
  const axisMeta = curveYAxisMeta(metas, activeKey);
  const legendColumns = width < 560 ? 2 : Math.max(1, allMetas.length);
  const legendColumnWidth = (right - left) / legendColumns;
  state.curveDisplayLegendHitBoxes = [];
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = palette.grid;
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei, Arial";
  for (let i = 0; i <= 5; i += 1) {
    const y = top + i * ((bottom - top) / 5);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  drawCurveDisplayXAxis(ctx, canvas, plot, snapshot);
  drawCurveYAxis(ctx, canvas, plot, axisMeta);
  metas.forEach((meta) => {
    const values = seriesByKey.get(meta.key) || [];
    const sampledPoints = sampleCurvePointsForCanvas(values, right - left, 1.4);
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = activeKey === meta.key ? 3.4 : 2;
    ctx.beginPath();
    sampledPoints.forEach((point, index) => {
      const x = left + (point.index / Math.max(1, values.length - 1)) * (right - left);
      const y = curveDisplayValueToY(point.value, meta, canvas);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    if (values.length) ctx.lineTo(right, curveDisplayValueToY(values[values.length - 1], meta, canvas));
    ctx.stroke();
  });
  if (!metas.length && allMetas.length) {
    ctx.fillStyle = palette.text;
    ctx.textAlign = "center";
    ctx.fillText(typeof translatePhrase === "function" ? translatePhrase("所有曲线已隐藏") : "所有曲线已隐藏", (left + right) / 2, (top + bottom) / 2);
    ctx.textAlign = "left";
  }
  if (!allMetas.length) {
    ctx.fillStyle = palette.text;
    ctx.textAlign = "center";
    ctx.fillText(typeof translatePhrase === "function" ? translatePhrase("未选择曲线") : "未选择曲线", (left + right) / 2, (top + bottom) / 2);
    ctx.textAlign = "left";
  }
  allMetas.forEach((meta, metaIndex) => {
    const legendX = left + (metaIndex % legendColumns) * legendColumnWidth;
    const legendY = 20 + Math.floor(metaIndex / legendColumns) * 16;
    const hidden = isCurveDisplaySeriesHidden(meta.key);
    const labelText = `${meta.label} (${meta.unit})${hidden ? " 隐藏" : ""}`;
    state.curveDisplayLegendHitBoxes.push({
      key: meta.key,
      x: legendX - 6,
      y: legendY - 9,
      width: Math.min(legendColumnWidth - 8, ctx.measureText(labelText).width + 42),
      height: 16,
    });
    ctx.fillStyle = hidden ? palette.axis : meta.color;
    ctx.fillRect(legendX, legendY, 18, 3);
    ctx.fillStyle = hidden ? palette.axis : activeKey === meta.key ? palette.tooltipTitle : palette.text;
    ctx.fillText(labelText, legendX + 26, legendY + 4);
  });
  drawCurveDisplayCursor(ctx, canvas, plot, metas, seriesByKey, snapshot);
}

function renderCurveDisplayTable(snapshot = state.snapshot || {}, force = false, preparedSeries = null) {
  const container = $("curveDisplayTable");
  if (!container) return;
  const config = curveDisplayConfig(snapshot);
  const metas = selectedCurveDisplayKeys(snapshot).map((key) => curveDisplayMetaForKey(key, snapshot));
  if (!metas.length) {
    state.lastCurveDisplayTableKey = "curveDisplay:empty";
    container.removeAttribute("data-virtual-table");
    container.innerHTML = '<div class="empty-state">未选择曲线</div>';
    return;
  }
  const seriesByKey = preparedSeries || curveDisplaySeriesMap(metas.map((meta) => meta.key), snapshot);
  const tableKey = `curveDisplay:${state.activeModelId}:${config.key}`;
  const signature = JSON.stringify({
    model: state.activeModelId,
    mode: config.key,
    points: config.pointCount,
    selected: metas.map((meta) => meta.key),
    staticMeta: snapshot.static_meta?.curves || null,
    source: `${snapshot.curves?.weather?.length || 0}|${Object.values(snapshot.curves?.loads || {}).map((points) => points?.length || 0).join(",")}|${curveDisplaySourceCatalog(snapshot).map((item) => item.points?.length || 0).join(",")}`,
  });
  if (!force && signature === state.lastCurveDisplayTableKey) return;
  state.lastCurveDisplayTableKey = signature;
  const rowIndexes = Array.from({ length: config.pointCount }, (_unused, index) => index);
  const virtualRows = virtualTableWindow(tableKey, rowIndexes);
  const columnCount = metas.length + 1;
  container.setAttribute("data-virtual-table", tableKey);
  container.innerHTML = `
    <table class="curve-table curve-display-table">
      <thead>
        <tr>
          <th>时刻</th>
          ${metas.map((meta) => `<th>${escapeHtml(meta.label)}<small>${escapeHtml(meta.unit)}</small></th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, columnCount)}
        ${virtualRows.rows.map((index) => `
          <tr>
            <td>${formatCurveDisplayTableTime(curveDisplayPointMinute(index, snapshot), snapshot)}</td>
            ${metas.map((meta) => `<td class="numeric-cell">${formatNumber(seriesByKey.get(meta.key)?.[index])}</td>`).join("")}
          </tr>
        `).join("")}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, columnCount)}
      </tbody>
    </table>`;
  restoreVirtualTableScroll(container, tableKey);
}

function renderCurveDisplay(snapshot = state.snapshot || {}, forceTable = false) {
  const container = $("curveDisplayTree");
  if (!container) return;
  if (!snapshot?.curves) {
    container.innerHTML = '<div class="empty-state">暂无曲线数据</div>';
    $("curveDisplayTable").removeAttribute("data-virtual-table");
    $("curveDisplayTable").innerHTML = '<div class="empty-state">暂无曲线数据</div>';
    return;
  }
  const renderKey = JSON.stringify({
    model: state.activeModelId,
    mode: curveDisplayMode(snapshot),
    points: curveDisplayConfig(snapshot).pointCount,
    selected: selectedCurveDisplayKeys(snapshot),
    hidden: [...(state.hiddenCurveDisplayKeys || [])].sort(),
    staticMeta: snapshot.static_meta?.curves || null,
  });
  if (!forceTable && renderKey === state.lastCurveDisplayRenderKey) return;
  state.lastCurveDisplayRenderKey = renderKey;
  const selectedKeys = selectedCurveDisplayKeys(snapshot);
  const seriesByKey = curveDisplaySeriesMap(selectedKeys, snapshot);
  renderCurveDisplayTree(snapshot);
  renderCurveDisplayModeControls(snapshot);
  renderCurveDisplayLabels(snapshot);
  drawCurveDisplay(snapshot, seriesByKey);
  renderCurveDisplayTable(snapshot, false, seriesByKey);
}

function pointerPositionOnCurveDisplayCanvas(event) {
  const canvas = $("curveDisplayChart");
  const rect = canvas.getBoundingClientRect();
  const { width, height } = canvasLogicalSize(canvas, 900, 260);
  return {
    x: (event.clientX - rect.left) * (width / Math.max(1, rect.width)),
    y: (event.clientY - rect.top) * (height / Math.max(1, rect.height)),
  };
}

function curveDisplayLegendKeyAtPointer(event) {
  const canvas = $("curveDisplayChart");
  if (!canvas) return "";
  const pos = pointerPositionOnCurveDisplayCanvas(event);
  const hit = (state.curveDisplayLegendHitBoxes || []).find((box) => (
    pos.x >= box.x && pos.x <= box.x + box.width && pos.y >= box.y && pos.y <= box.y + box.height
  ));
  return hit?.key || "";
}

function curveDisplayKeyAtPointer(event) {
  const canvas = $("curveDisplayChart");
  if (!canvas) return "";
  const pos = pointerPositionOnCurveDisplayCanvas(event);
  const { width, height } = canvasLogicalSize(canvas, 900, 260);
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  if (pos.x < left || pos.x > right || pos.y < top || pos.y > bottom) return "";
  const index = curveDisplayPointIndexFromX(pos.x, canvas, state.snapshot || {});
  const tolerance = width < 640 ? 18 : 14;
  let bestKey = "";
  let bestDistance = Infinity;
  visibleCurveDisplayMetas(state.snapshot || {}).forEach((meta) => {
    const values = curveDisplaySeries(meta.key, state.snapshot || {});
    if (!values.length) return;
    const distance = Math.abs(curveDisplayValueToY(values[index], meta, canvas) - pos.y);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestKey = meta.key;
    }
  });
  return bestDistance <= tolerance ? bestKey : "";
}

function setCurveDisplayCursorFromEvent(event, shouldDraw = true) {
  const canvas = $("curveDisplayChart");
  if (!canvas) return;
  const pos = pointerPositionOnCurveDisplayCanvas(event);
  const { width, height } = canvasLogicalSize(canvas, 900, 260);
  const plot = curveDisplayPlot(canvas);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  if (pos.x < left || pos.x > right || pos.y < top || pos.y > bottom) {
    state.curveDisplayCursor = { visible: false, x: pos.x, y: pos.y, index: state.curveDisplayCursor.index || 0 };
  } else {
    state.curveDisplayCursor = {
      visible: true,
      x: clamp(pos.x, left, right),
      y: clamp(pos.y, top, bottom),
      index: curveDisplayPointIndexFromX(pos.x, canvas, state.snapshot || {}),
    };
  }
  if (shouldDraw) drawCurveDisplay(state.snapshot || {});
}

function hideCurveDisplayCursor() {
  if (!state.curveDisplayCursor.visible) return;
  state.curveDisplayCursor.visible = false;
  drawCurveDisplay(state.snapshot || {});
}

