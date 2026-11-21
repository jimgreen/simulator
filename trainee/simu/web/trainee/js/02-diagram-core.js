// 学员端模块：接线图 SVG 清洗、潮流动画与定义基础（02-diagram-core.js）
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]
  ));
}

function sanitizeDiagramSvg(svgText) {
  const raw = String(svgText || "").trim();
  if (!raw) return "";
  const documentParser = new DOMParser();
  const parsed = documentParser.parseFromString(raw, "image/svg+xml");
  if (parsed.querySelector("parsererror")) return "";
  const svg = parsed.querySelector("svg");
  if (!svg) return "";
  svg.querySelectorAll("script, foreignObject, iframe, object, embed").forEach((node) => node.remove());
  svg.querySelectorAll("*").forEach((node) => {
    [...node.attributes].forEach((attribute) => {
      const name = attribute.name.toLowerCase();
      const value = String(attribute.value || "").trim().toLowerCase();
      if (name.startsWith("on") || value.startsWith("javascript:")) node.removeAttribute(attribute.name);
      if ((name === "href" || name.endsWith(":href")) && value.startsWith("javascript:")) node.removeAttribute(attribute.name);
    });
  });
  normalizeDiagramSvgBackground(svg);
  svg.classList.add("model-diagram-svg");
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  return svg.outerHTML;
}

const DIAGRAM_TREND_WINDOWS = Object.freeze({ hour: 60, day: 24 * 60 });

function traceWindowRealPoints(points, range = {}, options = {}) {
  const startMinute = Number(range.startMinute);
  const defaultEndMinute = Number(range.endMinute);
  const requestedEndMinute = Number(options.endMinute);
  const endMinute = Number.isFinite(requestedEndMinute) ? requestedEndMinute : defaultEndMinute;
  if (!Number.isFinite(startMinute) || !Number.isFinite(endMinute) || endMinute < startMinute) return [];
  const includeEnd = options.includeEnd !== false;
  const source = (Array.isArray(points) ? points : [])
    .filter((point) => Number.isFinite(Number(point?.minute)))
    .slice()
    .sort((left, right) => Number(left.minute) - Number(right.minute));
  return source.filter((point) => {
    const minute = Number(point.minute);
    return minute >= startMinute && (includeEnd ? minute <= endMinute : minute < endMinute);
  });
}

function traceWindowDataPointCount(points) {
  return Array.isArray(points) ? points.length : 0;
}

const DIAGRAM_DISPLAY_PREFERENCES_KEY = "trainee.svgDisplayPreferences.v1";
const DIAGRAM_DISPLAY_PREFERENCES_DEFAULTS = Object.freeze({
  measurements: true,
  labels: true,
  flowArrows: true,
});
const DIAGRAM_MAX_ZOOM = 8;
const DIAGRAM_PAN_THRESHOLD_PX = 5;
const DIAGRAM_FIT_PADDING_RATIO = 0.006;
const DIAGRAM_TOOLTIP_HIDE_DELAY_MS = 150;

function normalizeDiagramDisplayPreferences(value) {
  const source = value && typeof value === "object" ? value : {};
  return {
    measurements: typeof source.measurements === "boolean" ? source.measurements : true,
    labels: typeof source.labels === "boolean" ? source.labels : true,
    flowArrows: typeof source.flowArrows === "boolean" ? source.flowArrows : true,
  };
}

function diagramDisplayPreferenceMenuItems(preferences) {
  const value = normalizeDiagramDisplayPreferences(preferences);
  return [
    { key: "measurements", label: value.measurements ? "不显示量测" : "显示量测" },
    { key: "labels", label: value.labels ? "不显示标识" : "显示标识" },
    { key: "flowArrows", label: value.flowArrows ? "不显示流动箭头" : "显示流动箭头" },
  ];
}

function loadDiagramDisplayPreferences(storage = typeof localStorage === "undefined" ? null : localStorage) {
  try {
    const raw = storage?.getItem?.(DIAGRAM_DISPLAY_PREFERENCES_KEY);
    return normalizeDiagramDisplayPreferences(raw ? JSON.parse(raw) : null);
  } catch (_error) {
    return normalizeDiagramDisplayPreferences(null);
  }
}

function saveDiagramDisplayPreferences(preferences, storage = typeof localStorage === "undefined" ? null : localStorage) {
  const normalized = normalizeDiagramDisplayPreferences(preferences);
  try {
    storage?.setItem?.(DIAGRAM_DISPLAY_PREFERENCES_KEY, JSON.stringify(normalized));
  } catch (_error) {
    // The current page still uses the normalized in-memory preference when storage is unavailable.
  }
  return normalized;
}

let diagramDisplayPreferences = loadDiagramDisplayPreferences();

function diagramContextMenuAction(targetKind = "", insideCanvas = false) {
  return insideCanvas && !String(targetKind || "").trim() ? "open" : "ignore";
}

function diagramFloatingPosition(anchor, size, viewport, padding = 8) {
  const inset = Math.max(0, Number(padding) || 0);
  const viewportWidth = Math.max(0, Number(viewport?.width) || 0);
  const viewportHeight = Math.max(0, Number(viewport?.height) || 0);
  const width = Math.max(0, Number(size?.width) || 0);
  const height = Math.max(0, Number(size?.height) || 0);
  const anchorX = Number.isFinite(Number(anchor?.x)) ? Number(anchor.x) : inset;
  const anchorY = Number.isFinite(Number(anchor?.y)) ? Number(anchor.y) : inset;
  return {
    left: Math.max(inset, Math.min(anchorX, Math.max(inset, viewportWidth - width - inset))),
    top: Math.max(inset, Math.min(anchorY, Math.max(inset, viewportHeight - height - inset))),
  };
}

function diagramFlowArrowDirection(power, orientation = 1) {
  const value = Number(power) * (Number(orientation) < 0 ? -1 : 1);
  return value < 0 ? -1 : value > 0 ? 1 : 0;
}

function diagramFlowArrowSize(power, referencePower) {
  const reference = Math.abs(Number(referencePower));
  const magnitude = Math.abs(Number(power));
  if (!Number.isFinite(magnitude) || magnitude <= 0) return 10;
  const ratio = reference > 0 ? Math.max(0, Math.min(1, magnitude / reference)) : 1;
  return 10 + 14 * Math.sqrt(ratio);
}

function diagramFlowArrowCount(routeLength) {
  const length = Number(routeLength);
  if (!Number.isFinite(length) || length <= 0) return 2;
  return Math.max(2, Math.min(6, Math.ceil(length / 80) + 1));
}

function diagramFlowMotionAttributes(direction) {
  const reverse = Number(direction) < 0;
  return {
    keyPoints: reverse ? "1;0" : "0;1",
    rotate: reverse ? "auto-reverse" : "auto",
  };
}

const DIAGRAM_FLOW_POWER_MEASUREMENT_TYPES = Object.freeze({
  ACGENERATOR: Object.freeze(["P_GEN"]),
  DCGENERATOR: Object.freeze(["P_GEN"]),
  ACLOAD: Object.freeze(["P_LOAD"]),
  DCLOAD: Object.freeze(["P_LOAD"]),
  ACDCCONVERTER: Object.freeze(["P_AC", "P_DC"]),
  DCACCONVERTER: Object.freeze(["P_AC", "P_DC"]),
  DCDCCONVERTER: Object.freeze(["P_FROM", "P_TO"]),
  ACACCONVERTER: Object.freeze(["P_FROM", "P_TO"]),
  ACTRANSFORMER: Object.freeze(["P_FROM", "P_TO"]),
  ACBRANCH: Object.freeze(["P_FROM", "P_TO"]),
  DCBRANCH: Object.freeze(["P_FROM", "P_TO"]),
  ACZEROBRANCH: Object.freeze(["P_FROM", "P_TO"]),
  DCZEROBRANCH: Object.freeze(["P_FROM", "P_TO"]),
  ACBREAK: Object.freeze(["P_FROM", "P_TO"]),
  DCBREAK: Object.freeze(["P_FROM", "P_TO"]),
  ACSWITCH: Object.freeze(["P_FROM", "P_TO"]),
  DCSWITCH: Object.freeze(["P_FROM", "P_TO"]),
  HYDROSOURCE: Object.freeze(["FLOW"]),
  HYDROLOAD: Object.freeze(["FLOW"]),
  HYDROSTORAGE: Object.freeze(["FLOW"]),
  ACE2HYDRO: Object.freeze([]),
  DCE2HYDRO: Object.freeze([]),
  HYDRO2ACE: Object.freeze([]),
  HYDRO2DCE: Object.freeze([]),
  HYDROPIPE: Object.freeze(["FLOW"]),
  HYDROVALVE: Object.freeze(["FLOW"]),
  HYDROCOMPRESSOR: Object.freeze(["FLOW"]),
  HYDROPRESSREGULATOR: Object.freeze(["FLOW"]),
  HYDROSTOPVALVE: Object.freeze(["FLOW"]),
});

function diagramFlowPowerMeasurementTypes(devType) {
  const type = normalizeDiagramMeasurementToken(devType);
  const specific = DIAGRAM_FLOW_POWER_MEASUREMENT_TYPES[type];
  return specific ? [...specific] : diagramMetricMeasurementTypes(devType, "activePower");
}

function diagramFlowCanonicalPower(measType, value) {
  const power = Number(value);
  if (!Number.isFinite(power)) return Number.NaN;
  const type = normalizeDiagramMeasurementToken(measType);
  if (type === "P_AC" || type === "P_TO") return -power;
  return power;
}

function diagramFlowPowerRouteOrientation(device, nodes = []) {
  const type = normalizeDiagramMeasurementToken(device?.devType);
  if (["HYDRO2ACE", "HYDRO2DCE"].includes(type)) return -1;
  if (["ACE2HYDRO", "DCE2HYDRO"].includes(type)) return 1;
  if (type !== "ACDCCONVERTER" && type !== "DCACCONVERTER") return 1;
  const terminalFor = (domain) => Number((nodes || []).find((item) => {
    const nodeDomain = normalizeDiagramMeasurementToken(
      item?.domain || String(item?.key || "").split(":", 1)[0],
    );
    return nodeDomain === domain;
  })?.terminal) || 0;
  const acTerminal = terminalFor("AC");
  const dcTerminal = terminalFor("DC");
  if (acTerminal === 1 && dcTerminal === 2) return -1;
  return 1;
}

function diagramFlowInlineDeviceKind(devType, nodes = []) {
  const type = normalizeDiagramMeasurementToken(devType);
  if (type === "HYDROPIPE") return "branch";
  if ([
    "ACE2HYDRO",
    "DCE2HYDRO",
    "HYDRO2ACE",
    "HYDRO2DCE",
    "HYDROVALVE",
    "HYDROSTOPVALVE",
    "HYDROCOMPRESSOR",
    "HYDROPRESSREGULATOR",
  ].includes(type)) return "device";
  if (diagramHydrogenFlowInlineKind(type, nodes)) return "device";
  if (type.includes("BRANCH")) return "branch";
  if (
    type.includes("BREAK")
    || type.includes("SWITCH")
    || type.includes("CONVERTER")
    || type.includes("TRANSFORMER")
  ) return "device";
  return "";
}

function diagramFlowSeriesOrientation(subjectTerminal, neighborKind, neighborTerminal = 0) {
  const terminal = Number(subjectTerminal);
  if (["generator", "source", "storage"].includes(neighborKind)) return terminal === 1 ? 1 : -1;
  if (neighborKind === "load") return terminal === 2 ? 1 : -1;
  return terminal !== Number(neighborTerminal) ? 1 : -1;
}

function diagramFlowEdgeTerminalOrientation(position, terminal) {
  const terminalIndex = Number(terminal);
  if (position === "source") return terminalIndex === 2 ? 1 : -1;
  return terminalIndex === 1 ? 1 : -1;
}

function diagramFlowNodeKey(node, domain = "") {
  return `${normalizeDiagramMeasurementToken(diagramFlowDomain(domain)) || "NODE"}:${String(node || "").trim()}`;
}

function diagramFlowArrowThreshold(measType, electricThreshold, hydrogenThreshold) {
  const type = normalizeDiagramMeasurementToken(measType);
  const threshold = type === "FLOW" ? Number(hydrogenThreshold) : Number(electricThreshold);
  return Number.isFinite(threshold) ? Math.max(0, threshold) : 0;
}

function diagramFlowArrowVisibility({ power, threshold = 0, valid = true, offline = false } = {}) {
  const magnitude = Math.abs(Number(power));
  if (!valid || offline || !Number.isFinite(magnitude)) return false;
  return magnitude > Math.max(0, Number(threshold) || 0);
}

function diagramTooltipPointerMoveAction(currentHover, nextHover, tooltipHidden = false) {
  if (currentHover && !tooltipHidden && nextHover?.kind !== currentHover.kind) return "schedule-hide";
  if (!nextHover) return "hide";
  if (tooltipHidden || nextHover.key !== currentHover?.key) return "refresh";
  return "hold";
}

function diagramTooltipNeedsPosition(hover, positionedKey = "") {
  if (!hover) return false;
  const hoverKey = String(hover.key || "");
  return !hoverKey || hoverKey !== String(positionedKey || "");
}

function diagramSvgDoubleClickAction(targetKind = "", insideCanvas = false) {
  if (!insideCanvas) return "ignore";
  const kind = String(targetKind || "").trim();
  if (kind === "device") return "command";
  return kind ? "ignore" : "fit";
}

function diagramInteractionEventTarget(container, viewport, event) {
  const svg = viewport?.svg;
  const directTarget = event?.target;
  if (!container || !svg || !(directTarget instanceof Element)) return null;
  if (directTarget !== container && !container.contains(directTarget)) return null;
  if (directTarget.closest("svg") === svg) return directTarget;
  const clientX = Number(event?.clientX);
  const clientY = Number(event?.clientY);
  const pointTarget = Number.isFinite(clientX)
    && Number.isFinite(clientY)
    && typeof document !== "undefined"
    && typeof document.elementFromPoint === "function"
    ? document.elementFromPoint(clientX, clientY)
    : null;
  if (
    pointTarget instanceof Element
    && container.contains(pointTarget)
    && pointTarget.closest("svg") === svg
  ) {
    return pointTarget;
  }
  return svg;
}

function diagramViewBoxValue(value) {
  const values = String(value || "")
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  if (values.length !== 4 || values.some((item) => !Number.isFinite(item))) return null;
  const [x, y, width, height] = values;
  if (width <= 0 || height <= 0) return null;
  return { x, y, width, height };
}

function normalizeDiagramSvgBackground(svg) {
  const viewBox = diagramViewBoxValue(svg?.getAttribute("viewBox"));
  if (!viewBox) return 0;
  let normalized = 0;
  svg.querySelectorAll("rect").forEach((rect) => {
    const width = String(rect.getAttribute("width") || "").trim();
    const height = String(rect.getAttribute("height") || "").trim();
    if (width !== "100%" || height !== "100%") return;
    if (rect.closest("defs, symbol, marker, pattern, clipPath, mask")) return;
    rect.setAttribute("x", String(viewBox.x));
    rect.setAttribute("y", String(viewBox.y));
    rect.setAttribute("width", String(viewBox.width));
    rect.setAttribute("height", String(viewBox.height));
    rect.setAttribute("pointer-events", "none");
    rect.classList.add("diagram-svg-background");
    normalized += 1;
  });
  return normalized;
}

function diagramTrendWindowMinutes(period = "hour") {
  return DIAGRAM_TREND_WINDOWS[period] || DIAGRAM_TREND_WINDOWS.hour;
}

function diagramTrendPeriodRange(period = "hour", endMinute = 0) {
  const windowMinutes = diagramTrendWindowMinutes(period);
  const latestMinute = Number.isFinite(Number(endMinute)) ? Number(endMinute) : 0;
  const startMinute = Math.floor(latestMinute / windowMinutes) * windowMinutes;
  return {
    startMinute,
    endMinute: startMinute + windowMinutes,
    latestMinute,
    windowMinutes,
  };
}

function diagramTrendNavigationRange(
  points,
  period = "hour",
  endMinute = null,
  requestedOffset = 0,
  simulationDurationMinutes = Number.POSITIVE_INFINITY,
) {
  let earliestHistoryMinute = Number.POSITIVE_INFINITY;
  let latestHistoryMinute = Number.NEGATIVE_INFINITY;
  (Array.isArray(points) ? points : []).forEach((point) => {
    const minute = Number(point?.minute);
    if (!Number.isFinite(minute) || !diagramTrendPointHasFiniteValue(point)) return;
    earliestHistoryMinute = Math.min(earliestHistoryMinute, minute);
    latestHistoryMinute = Math.max(latestHistoryMinute, minute);
  });
  const hasHistory = Number.isFinite(earliestHistoryMinute) && Number.isFinite(latestHistoryMinute);
  const explicitEndMinute = endMinute === null || endMinute === undefined || endMinute === ""
    ? null
    : Number(endMinute);
  const latestMinute = Number.isFinite(explicitEndMinute)
    ? explicitEndMinute
    : (hasHistory ? latestHistoryMinute : 0);
  const currentRange = diagramTrendPeriodRange(period, latestMinute);
  const normalizedSimulationDuration = Number(simulationDurationMinutes);
  const cycleStartMinute = Number.isFinite(normalizedSimulationDuration) && normalizedSimulationDuration > 0
    ? Math.floor((latestMinute + 1e-9) / normalizedSimulationDuration) * normalizedSimulationDuration
    : Number.NEGATIVE_INFINITY;
  const earliestMinute = hasHistory
    ? Math.max(earliestHistoryMinute, cycleStartMinute)
    : latestMinute;
  const periodNavigationAllowed = !Number.isFinite(normalizedSimulationDuration)
    || normalizedSimulationDuration <= 0
    || currentRange.windowMinutes < normalizedSimulationDuration;
  const minWindowOffset = periodNavigationAllowed && hasHistory
    ? Math.min(0, Math.floor((earliestMinute - currentRange.startMinute) / currentRange.windowMinutes))
    : 0;
  const normalizedOffset = periodNavigationAllowed
    ? Math.min(0, Math.trunc(Number(requestedOffset) || 0))
    : 0;
  const windowOffset = Math.max(minWindowOffset, normalizedOffset);
  const startMinute = currentRange.startMinute + windowOffset * currentRange.windowMinutes;
  return {
    ...currentRange,
    startMinute,
    endMinute: startMinute + currentRange.windowMinutes,
    currentStartMinute: currentRange.startMinute,
    earliestMinute,
    windowOffset,
    minWindowOffset,
    periodNavigationAllowed,
  };
}

function diagramTrendPeriodLabels(period = "hour", range = {}) {
  if (period === "day") return { start: "00:00", end: "24:00" };
  const startMinute = Number(range.startMinute) || 0;
  const endMinute = Number(range.endMinute) || startMinute + DIAGRAM_TREND_WINDOWS.hour;
  const dayStart = Math.floor(startMinute / DIAGRAM_TREND_WINDOWS.day) * DIAGRAM_TREND_WINDOWS.day;
  const clockText = (minute) => {
    const offset = Math.round(Number(minute) - dayStart);
    if (offset === DIAGRAM_TREND_WINDOWS.day) return "24:00";
    const normalized = ((offset % DIAGRAM_TREND_WINDOWS.day) + DIAGRAM_TREND_WINDOWS.day) % DIAGRAM_TREND_WINDOWS.day;
    return `${String(Math.floor(normalized / 60)).padStart(2, "0")}:${String(normalized % 60).padStart(2, "0")}`;
  };
  return { start: clockText(startMinute), end: clockText(endMinute) };
}

function diagramTrendPointHasFiniteValue(point) {
  return [point?.value, point?.scada].some((value) => (
    value !== null
    && value !== undefined
    && value !== ""
    && Number.isFinite(Number(value))
  ));
}

function diagramTrendWindowPoints(points, period = "hour", endMinute = null, requestedOffset = 0, rangeOverride = null) {
  const valid = (points || []).filter((point) => (
    Number.isFinite(Number(point?.minute)) && diagramTrendPointHasFiniteValue(point)
  ));
  if (!valid.length) return [];
  const explicitEndMinute = endMinute === null || endMinute === undefined || endMinute === ""
    ? null
    : Number(endMinute);
  const latestMinute = Number.isFinite(explicitEndMinute)
    ? explicitEndMinute
    : Number(valid[valid.length - 1].minute);
  const range = rangeOverride || diagramTrendNavigationRange(valid, period, latestMinute, requestedOffset);
  const visibleLatestMinute = range.windowOffset === 0 ? range.latestMinute : range.endMinute;
  return traceWindowRealPoints(valid, range, {
    endMinute: visibleLatestMinute,
    includeEnd: visibleLatestMinute < range.endMinute,
  });
}

function diagramSampleTrendPoints(points, targetCount = 160) {
  const source = Array.isArray(points) ? points : [];
  const target = Math.max(4, Math.floor(Number(targetCount) || 160));
  if (source.length <= target) return [...source];
  const bucketCount = Math.max(1, Math.floor(target / 4));
  const bucketSize = source.length / bucketCount;
  const sampled = new Map();
  for (let bucket = 0; bucket < bucketCount; bucket += 1) {
    const start = Math.floor(bucket * bucketSize);
    const end = Math.min(source.length, Math.max(start + 1, Math.ceil((bucket + 1) * bucketSize)));
    let minIndex = start;
    let maxIndex = start;
    for (let index = start + 1; index < end; index += 1) {
      if (Number(source[index]?.value) < Number(source[minIndex]?.value)) minIndex = index;
      if (Number(source[index]?.value) > Number(source[maxIndex]?.value)) maxIndex = index;
    }
    [start, minIndex, maxIndex, end - 1].forEach((index) => sampled.set(index, source[index]));
  }
  sampled.set(0, source[0]);
  sampled.set(source.length - 1, source[source.length - 1]);
  return Array.from(sampled.entries())
    .sort((left, right) => left[0] - right[0])
    .map(([, point]) => point);
}

function diagramNiceStep(value) {
  const raw = Math.abs(Number(value));
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10;
  return nice * power;
}

function diagramTrendAxisScale(values, targetTickCount = 4) {
  const valid = (values || []).map(Number).filter(Number.isFinite);
  if (!valid.length) return { min: 0, max: 1, ticks: [0, 0.5, 1] };
  let dataMin = Math.min(...valid);
  let dataMax = Math.max(...valid);
  if (Math.abs(dataMax - dataMin) < 1e-9) {
    const padding = Math.max(1, Math.abs(dataMax) * 0.05);
    dataMin -= padding;
    dataMax += padding;
  }
  const step = diagramNiceStep((dataMax - dataMin) / Math.max(2, Number(targetTickCount) - 1));
  const min = Math.floor(dataMin / step) * step;
  const max = Math.ceil(dataMax / step) * step;
  const ticks = [];
  for (let value = min, guard = 0; value <= max + step * 1e-7 && guard < 12; value += step, guard += 1) {
    ticks.push(Number(value.toPrecision(12)));
  }
  return { min, max: max > min ? max : min + step, ticks };
}

function diagramNearestTrendPoint(points, targetMinute) {
  const source = (points || []).filter((point) => Number.isFinite(Number(point?.minute)));
  if (!source.length) return null;
  const target = Number(targetMinute);
  if (!Number.isFinite(target) || target <= Number(source[0].minute)) return source[0];
  if (target >= Number(source[source.length - 1].minute)) return source[source.length - 1];
  let low = 0;
  let high = source.length - 1;
  while (low + 1 < high) {
    const middle = Math.floor((low + high) / 2);
    if (Number(source[middle].minute) <= target) low = middle;
    else high = middle;
  }
  return target - Number(source[low].minute) <= Number(source[high].minute) - target
    ? source[low]
    : source[high];
}

function diagramTrendCursorData(points, targetMinute, unit = "") {
  const point = diagramNearestTrendPoint(points, targetMinute);
  if (!point) return null;
  return {
    minute: Number(point.minute),
    time: point.time || "--",
    value: Number(point.value),
    unit: String(unit || ""),
  };
}

function diagramZoomViewBox(current, original, focus, factor) {
  const boxes = [current, original];
  if (boxes.some((box) => !box || [box.x, box.y, box.width, box.height].some((value) => !Number.isFinite(Number(value))))) {
    return current;
  }
  const originalWidth = Number(original.width);
  const originalHeight = Number(original.height);
  const currentWidth = Number(current.width);
  const currentHeight = Number(current.height);
  if (originalWidth <= 0 || originalHeight <= 0 || currentWidth <= 0 || currentHeight <= 0) return current;
  const zoomFactor = Number(factor);
  if (!Number.isFinite(zoomFactor) || zoomFactor <= 0) return current;
  const nextWidth = Math.max(originalWidth / DIAGRAM_MAX_ZOOM, Math.min(originalWidth, currentWidth * zoomFactor));
  const scale = nextWidth / currentWidth;
  const nextHeight = Math.max(originalHeight / DIAGRAM_MAX_ZOOM, Math.min(originalHeight, currentHeight * scale));
  const focusX = Number.isFinite(Number(focus?.x)) ? Number(focus.x) : Number(current.x) + currentWidth / 2;
  const focusY = Number.isFinite(Number(focus?.y)) ? Number(focus.y) : Number(current.y) + currentHeight / 2;
  const rawX = focusX - (focusX - Number(current.x)) * (nextWidth / currentWidth);
  const rawY = focusY - (focusY - Number(current.y)) * (nextHeight / currentHeight);
  const minX = Number(original.x);
  const minY = Number(original.y);
  const maxX = minX + originalWidth - nextWidth;
  const maxY = minY + originalHeight - nextHeight;
  return {
    x: Math.max(minX, Math.min(maxX, rawX)),
    y: Math.max(minY, Math.min(maxY, rawY)),
    width: nextWidth,
    height: nextHeight,
  };
}

function diagramPanViewBox(current, original, delta) {
  const boxes = [current, original];
  if (boxes.some((box) => !box || [box.x, box.y, box.width, box.height].some((value) => !Number.isFinite(Number(value))))) {
    return current;
  }
  const originalWidth = Number(original.width);
  const originalHeight = Number(original.height);
  const currentWidth = Number(current.width);
  const currentHeight = Number(current.height);
  if (originalWidth <= 0 || originalHeight <= 0 || currentWidth <= 0 || currentHeight <= 0) return current;
  const deltaX = Number.isFinite(Number(delta?.x)) ? Number(delta.x) : 0;
  const deltaY = Number.isFinite(Number(delta?.y)) ? Number(delta.y) : 0;
  const minX = Number(original.x);
  const minY = Number(original.y);
  const maxX = minX + originalWidth - currentWidth;
  const maxY = minY + originalHeight - currentHeight;
  return {
    x: Math.max(minX, Math.min(maxX, Number(current.x) - deltaX)),
    y: Math.max(minY, Math.min(maxY, Number(current.y) - deltaY)),
    width: currentWidth,
    height: currentHeight,
  };
}

function diagramSvgRenderMapping(viewBox, viewportRect, preserveAspectRatio = "") {
  const viewValues = [viewBox?.x, viewBox?.y, viewBox?.width, viewBox?.height].map(Number);
  const rectValues = [viewportRect?.left, viewportRect?.top, viewportRect?.width, viewportRect?.height].map(Number);
  if (
    viewValues.some((value) => !Number.isFinite(value))
    || rectValues.some((value) => !Number.isFinite(value))
    || viewValues[2] <= 0
    || viewValues[3] <= 0
    || rectValues[2] <= 0
    || rectValues[3] <= 0
  ) return null;
  const [left, top, viewportWidth, viewportHeight] = rectValues;
  const tokens = String(preserveAspectRatio || "xMidYMid meet").trim().split(/\s+/).filter(Boolean);
  if (tokens.includes("none")) {
    return {
      left,
      top,
      scaleX: viewportWidth / viewValues[2],
      scaleY: viewportHeight / viewValues[3],
    };
  }
  const align = tokens.find((token) => /^x(?:Min|Mid|Max)Y(?:Min|Mid|Max)$/.test(token)) || "xMidYMid";
  const scale = (tokens.includes("slice") ? Math.max : Math.min)(
    viewportWidth / viewValues[2],
    viewportHeight / viewValues[3],
  );
  const spareX = viewportWidth - viewValues[2] * scale;
  const spareY = viewportHeight - viewValues[3] * scale;
  const alignX = align.startsWith("xMin") ? 0 : align.startsWith("xMax") ? spareX : spareX / 2;
  const alignY = align.endsWith("YMin") ? 0 : align.endsWith("YMax") ? spareY : spareY / 2;
  return { left: left + alignX, top: top + alignY, scaleX: scale, scaleY: scale };
}

function diagramMeasurementFitViewBox(svg, source) {
  const sourceValues = [source?.x, source?.y, source?.width, source?.height].map(Number);
  if (sourceValues.some((value) => !Number.isFinite(value)) || sourceValues[2] <= 0 || sourceValues[3] <= 0) {
    return source;
  }
  const [sourceX, sourceY, sourceWidth, sourceHeight] = sourceValues;
  const fallback = { x: sourceX, y: sourceY, width: sourceWidth, height: sourceHeight };
  if (
    typeof svg?.getBoundingClientRect !== "function"
    || typeof svg?.querySelectorAll !== "function"
  ) return fallback;
  const renderedViewBox = diagramViewBoxValue(svg.getAttribute?.("viewBox")) || fallback;
  const mapping = diagramSvgRenderMapping(
    renderedViewBox,
    svg.getBoundingClientRect(),
    svg.getAttribute?.("preserveAspectRatio") || "",
  );
  if (!mapping) return fallback;
  let minX = sourceX;
  let minY = sourceY;
  let maxX = sourceX + sourceWidth;
  let maxY = sourceY + sourceHeight;
  [...svg.querySelectorAll(".diagram-measurement-layer")].forEach((element) => {
    if (typeof element?.getBoundingClientRect !== "function") return;
    const rect = element.getBoundingClientRect();
    const values = [rect?.left, rect?.top, rect?.width, rect?.height].map(Number);
    if (values.some((value) => !Number.isFinite(value)) || values[2] <= 0 || values[3] <= 0) return;
    const left = renderedViewBox.x + (values[0] - mapping.left) / mapping.scaleX;
    const top = renderedViewBox.y + (values[1] - mapping.top) / mapping.scaleY;
    const right = left + values[2] / mapping.scaleX;
    const bottom = top + values[3] / mapping.scaleY;
    minX = Math.min(minX, left);
    minY = Math.min(minY, top);
    maxX = Math.max(maxX, right);
    maxY = Math.max(maxY, bottom);
  });
  const epsilon = 1e-7;
  const expandsLeft = minX < sourceX - epsilon;
  const expandsTop = minY < sourceY - epsilon;
  const expandsRight = maxX > sourceX + sourceWidth + epsilon;
  const expandsBottom = maxY > sourceY + sourceHeight + epsilon;
  if (!expandsLeft && !expandsTop && !expandsRight && !expandsBottom) return fallback;
  const padding = Math.max(
    4,
    Math.min(24, Math.max(sourceWidth, sourceHeight) * DIAGRAM_FIT_PADDING_RATIO),
  );
  const x = expandsLeft ? minX - padding : sourceX;
  const y = expandsTop ? minY - padding : sourceY;
  const right = expandsRight ? maxX + padding : sourceX + sourceWidth;
  const bottom = expandsBottom ? maxY + padding : sourceY + sourceHeight;
  return { x, y, width: right - x, height: bottom - y };
}

function fitDiagramViewport(viewport) {
  const svg = viewport?.svg;
  const source = viewport?.source || viewport?.original;
  if (!source || !svg || typeof svg.setAttribute !== "function") return false;
  const values = [source.x, source.y, source.width, source.height].map(Number);
  if (values.some((value) => !Number.isFinite(value)) || values[2] <= 0 || values[3] <= 0) return false;
  const original = diagramMeasurementFitViewBox(svg, {
    x: values[0],
    y: values[1],
    width: values[2],
    height: values[3],
  });
  viewport.source = { x: values[0], y: values[1], width: values[2], height: values[3] };
  viewport.original = { ...original };
  viewport.current = { ...original };
  svg.setAttribute("viewBox", `${original.x} ${original.y} ${original.width} ${original.height}`);
  return true;
}

const DIAGRAM_METRIC_MEASUREMENT_TYPES = Object.freeze({
  activePower: Object.freeze({
    ACGENERATOR: ["P_GEN"],
    DCGENERATOR: ["P_GEN"],
    ACLOAD: ["P_LOAD"],
    DCACCONVERTER: ["P_AC", "P_DC"],
    DCDCCONVERTER: ["P_TO", "P_FROM"],
    ACBRANCH: ["P_FROM", "P_TO"],
    DCBRANCH: ["P_FROM", "P_TO"],
    ACBREAK: ["P_FROM", "P_TO"],
    DCBREAK: ["P_FROM", "P_TO"],
    ACZEROBRANCH: ["P_FROM", "P_TO"],
    "*": ["P", "P_GEN", "P_LOAD", "P_AC", "P_DC", "P_TO", "P_FROM"],
  }),
  reactivePower: Object.freeze({
    ACGENERATOR: ["Q_GEN"],
    ACLOAD: ["Q_LOAD"],
    DCACCONVERTER: ["Q_AC"],
    ACBRANCH: ["Q_FROM", "Q_TO"],
    ACBREAK: ["Q_FROM", "Q_TO"],
    ACZEROBRANCH: ["Q_FROM", "Q_TO"],
    "*": ["Q", "Q_GEN", "Q_LOAD", "Q_AC", "Q_FROM", "Q_TO"],
  }),
  voltage: Object.freeze({
    ACGENERATOR: ["V_GEN"],
    DCGENERATOR: ["V_GEN"],
    ACLOAD: ["V_LOAD"],
    DCACCONVERTER: ["V_AC", "V_DC"],
    DCDCCONVERTER: ["V_TO", "V_FROM"],
    "*": ["V", "V_GEN", "V_LOAD", "V_AC", "V_DC", "V_TO", "V_FROM"],
  }),
  current: Object.freeze({
    ACGENERATOR: ["I_GEN"],
    DCGENERATOR: ["I_GEN"],
    ACLOAD: ["I_LOAD"],
    DCACCONVERTER: ["I_AC", "I_DC"],
    DCDCCONVERTER: ["I_TO", "I_FROM"],
    "*": ["I", "I_GEN", "I_LOAD", "I_AC", "I_DC", "I_TO", "I_FROM"],
  }),
  status: Object.freeze({ "*": ["STATUS", "RUN_STAT"] }),
  level: Object.freeze({ "*": ["SOC", "LEVEL"] }),
  frequency: Object.freeze({ "*": ["FREQUENCY", "FREQ", "F"] }),
  flow: Object.freeze({ "*": ["FLOW"] }),
  pressure: Object.freeze({ "*": ["PRESSURE"] }),
  gas_quantity: Object.freeze({ "*": ["GAS_QUANTITY"] }),
  soc: Object.freeze({ "*": ["SOC"] }),
  temperature: Object.freeze({ "*": ["TEMPERATURE"] }),
});

function diagramNumberText(value) {
  const number = Number(value);
  if (Number.isFinite(number)) return number.toFixed(2);
  const text = String(value ?? "").trim();
  return text || "--";
}

function diagramRowText(row) {
  if (!row) return "--";
  const unit = String(row.unit || "").trim();
  return `${diagramNumberText(row.value)}${unit ? ` ${unit}` : ""}`;
}

function addDiagramMeasurementAliases(map, row) {
  if (!row) return;
  const aliases = [
    row.name,
    measurementKey(row),
    `${row.dev_type || ""}.${row.dev_name || ""}.${row.meas_type || ""}`,
  ].map((item) => String(item || "").trim()).filter(Boolean);
  aliases.forEach((alias) => map.set(alias, row));
}

function normalizeDiagramMeasurementToken(value) {
  return String(value || "").trim().toUpperCase();
}

function normalizeDiagramMetricType(value) {
  const metricName = String(value || "").trim().toLowerCase();
  const compactName = metricName.replace(/[\s_-]+/g, "");
  if (compactName === "soc" || compactName === "stateofcharge") return "level";
  if (compactName === "gasquantity") return "gas_quantity";
  return metricName;
}

function diagramMetricTypeFromElement(element) {
  return String(element?.getAttribute?.("mti") || element?.getAttribute?.("mt") || "").trim();
}

function diagramMetricMeasurementTypes(devType, metricType) {
  const metricName = normalizeDiagramMetricType(metricType);
  const metricEntry = Object.entries(DIAGRAM_METRIC_MEASUREMENT_TYPES)
    .find(([key]) => key.toLowerCase() === metricName)?.[1] || {};
  const specific = metricEntry[normalizeDiagramMeasurementToken(devType)] || [];
  return [...new Set([...specific, ...(metricEntry["*"] || [])])];
}

function diagramDeviceMeasurementKey(devType, devName, measType) {
  return [
    normalizeDiagramMeasurementToken(devType),
    String(devName || "").trim(),
    normalizeDiagramMeasurementToken(measType),
  ].join("\u0000");
}

function diagramCouplingMeasurementEndpointKey(devType, devName) {
  return [normalizeDiagramMeasurementToken(devType), String(devName || "").trim()].join("\u0000");
}

function diagramIsHydrogenConversionDevice(device) {
  return ["ACE2HYDRO", "DCE2HYDRO", "HYDRO2ACE", "HYDRO2DCE"].includes(
    normalizeDiagramMeasurementToken(device?.devType ?? device?.dev_type),
  );
}

function diagramCouplingMeasurementEndpoints(snapshot = {}) {
  const result = new Map();
  (snapshot.devices || []).forEach((device) => {
    if (!diagramIsHydrogenConversionDevice(device)) return;
    const endpoints = { electric: null, hydrogen: null };
    (Array.isArray(device?.control_bindings) ? device.control_bindings : []).forEach((binding) => {
      const target = {
        devType: String(binding?.target_dev_type || "").trim(),
        devName: String(binding?.target_dev_name || "").trim(),
      };
      const targetType = normalizeDiagramMeasurementToken(target.devType);
      if (!target.devType || !target.devName) return;
      if (["ACGENERATOR", "DCGENERATOR", "ACLOAD", "DCLOAD"].includes(targetType)) endpoints.electric = target;
      if (["HYDROSOURCE", "HYDROLOAD", "HYDROSTORAGE"].includes(targetType)) endpoints.hydrogen = target;
    });
    result.set(
      diagramCouplingMeasurementEndpointKey(device.dev_type, device.dev_name),
      endpoints,
    );
  });
  return result;
}

function diagramCouplingMeasurementEndpoint(device, maps, metricType = "", measurementTypes = null) {
  if (!diagramIsHydrogenConversionDevice(device)) return device;
  const endpoints = maps?.couplingEndpoints?.get(
    diagramCouplingMeasurementEndpointKey(device?.devType, device?.devName),
  );
  if (!endpoints) return null;
  const explicitTypes = Array.isArray(measurementTypes)
    ? measurementTypes.map(normalizeDiagramMeasurementToken)
    : [];
  const hydrogenMetric = normalizeDiagramMetricType(metricType) === "flow"
    || (explicitTypes.length > 0 && explicitTypes.every((type) => type === "FLOW"));
  return (hydrogenMetric ? endpoints.hydrogen : endpoints.electric) || device;
}

function addDiagramDeviceMeasurement(map, row) {
  if (!row?.dev_type || !row?.dev_name || !row?.meas_type) return;
  map.set(diagramDeviceMeasurementKey(row.dev_type, row.dev_name, row.meas_type), row);
}

function diagramMeasurementMaps(snapshot = state.snapshot || {}) {
  const measurements = snapshot.measurements || {};
  const scada = new Map();
  const scadaByDevice = new Map();
  const deviceRuntimeByDevice = new Map();
  (snapshot.devices || []).forEach((row) => {
    const devType = String(row?.dev_type || "").trim();
    const devName = String(row?.dev_name || row?.name || "").trim();
    if (!devType || !devName) return;
    deviceRuntimeByDevice.set(diagramDeviceStateKey(devType, devName), row);
  });
  (measurements.scada || []).forEach((row) => {
    addDiagramMeasurementAliases(scada, row);
    addDiagramDeviceMeasurement(scadaByDevice, row);
  });
  return {
    scada,
    scadaByDevice,
    deviceRuntimeByDevice,
    couplingEndpoints: diagramCouplingMeasurementEndpoints(snapshot),
  };
}

function diagramMetricBindingValue(binding, maps) {
  const measurementDevice = diagramCouplingMeasurementEndpoint(binding, maps, binding?.metricType);
  if (!measurementDevice) return null;
  const candidates = diagramMetricMeasurementTypes(measurementDevice?.devType, binding?.metricType);
  for (const measType of candidates) {
    const key = diagramDeviceMeasurementKey(measurementDevice.devType, measurementDevice.devName, measType);
    if (maps.scadaByDevice?.has(key)) return maps.scadaByDevice.get(key);
  }
  return null;
}

function diagramDisplayRow(row, metricType = "") {
  if (!row) return row;
  if (
    normalizeDiagramMetricType(metricType) === "level"
    && normalizeDiagramMeasurementToken(row.meas_type) === "SOC"
    && Number.isFinite(Number(row.value))
  ) {
    return { ...row, value: Number(row.value) * 100 };
  }
  return row;
}

function diagramTrendDisplayValue(value, row, metricType = "") {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  const displayRow = diagramDisplayRow({ ...(row || {}), value: number }, metricType);
  return Number.isFinite(Number(displayRow?.value)) ? Number(displayRow.value) : null;
}

function diagramDeviceStateKey(devType, devName) {
  return `${normalizeDiagramMeasurementToken(devType)}\u0000${String(devName || "").trim()}`;
}

function diagramDeviceOperatingStateMaps(snapshot = {}) {
  const exact = new Map();
  const byName = new Map();
  (snapshot.device_states || snapshot.devices || []).forEach((item) => {
    const devType = String(item?.dev_type || "").trim();
    const devName = String(item?.dev_name || item?.name || "").trim();
    if (!devType || !devName) return;
    exact.set(diagramDeviceStateKey(devType, devName), item);
    if (!byName.has(devName)) {
      byName.set(devName, item);
      return;
    }
    const previous = byName.get(devName);
    if (previous && normalizeDiagramMeasurementToken(previous.dev_type) !== normalizeDiagramMeasurementToken(devType)) {
      byName.set(devName, null);
    }
  });
  return { exact, byName };
}

function diagramDeviceOperatingState(device, maps) {
  if (!device) return null;
  return maps.exact.get(diagramDeviceStateKey(device.devType, device.devName))
    || maps.byName.get(String(device.devName || "").trim())
    || null;
}

function diagramDeviceIsOffline(deviceState) {
  if (!deviceState) return false;
  const deadIsland = deviceState.dead_island === true
    || Number(deviceState.dead_island) === 1
    || String(deviceState.dead_island).trim().toLowerCase() === "true";
  return Number(deviceState.run_stat ?? deviceState.running ?? 1) === 0 || deadIsland;
}

function diagramSwitchState(value) {
  if (typeof value === "boolean") return value ? "closed" : "open";
  const text = String(value ?? "").trim();
  if (!text || text === "--") return "unknown";
  const number = Number(text);
  if (Number.isFinite(number)) return number > 0.5 ? "closed" : "open";
  const token = text.toLowerCase().replace(/\s+/g, "");
  if (["closed", "close", "on", "合", "合闸", "闭合", "投入", "true"].includes(token)) return "closed";
  if (["open", "off", "分", "分闸", "断开", "打开", "退出", "false"].includes(token)) return "open";
  return "unknown";
}

function diagramSwitchStateHref(href, switchState) {
  const value = String(href || "");
  if (!value || !["open", "closed"].includes(switchState)) return value;
  const stateValue = switchState === "closed" ? 1 : 0;
  return value.replace(/_state_[01](?=(?:_\d+)?(?:$|[?#]))/, `_state_${stateValue}`);
}

function diagramSwitchMeasurementRow(device, maps) {
  if (!device) return null;
  const key = diagramDeviceMeasurementKey(device.devType, device.devName, "STATUS");
  return maps.scadaByDevice?.get(key) || maps.realByDevice?.get(key) || null;
}

function diagramSwitchActualValue(device, maps) {
  if (!device) return null;
  const runtime = maps.deviceRuntimeByDevice?.get(
    diagramDeviceStateKey(device.devType, device.devName),
  );
  if (
    runtime
    && Object.prototype.hasOwnProperty.call(runtime, "closed_status")
    && runtime.closed_status !== null
    && runtime.closed_status !== ""
  ) {
    return runtime.closed_status;
  }
  return diagramSwitchMeasurementRow(device, maps)?.value ?? null;
}

function diagramDeviceDefinitionRuntimeValue(live, field) {
  if (!live || typeof live !== "object") return { present: false, value: undefined };
  const name = String(field || "").trim().toLowerCase();
  const ownValue = (source, key) => (
    source
    && Object.prototype.hasOwnProperty.call(source, key)
    && source[key] !== null
    && source[key] !== ""
      ? { present: true, value: source[key] }
      : null
  );
  if (name === "closed_status_set") {
    return ownValue(live, "closed_status_set")
      || ownValue(live.set_values, "closed_status_set")
      || { present: false, value: undefined };
  }
  if (name === "closed_status") {
    return ownValue(live, "closed_status")
      || { present: false, value: undefined };
  }
  if (name === "status") {
    return ownValue(live, "closed_status")
      || ownValue(live, "status")
      || { present: false, value: undefined };
  }
  return { present: false, value: undefined };
}

function applyDiagramDeviceDefinitionRuntimeValues(records = [], live = null) {
  const primaryRecord = records[0];
  if (!primaryRecord?.row || !live) return records;
  (primaryRecord.headers || Object.keys(primaryRecord.row)).forEach((field) => {
    const runtime = diagramDeviceDefinitionRuntimeValue(live, field);
    if (runtime.present) primaryRecord.row[field] = runtime.value;
  });
  return records;
}

function setDiagramSwitchElementState(element, switchState) {
  element.setAttribute("data-diagram-switch-state", switchState);
  element.classList.toggle("is-diagram-switch-open", switchState === "open");
  element.classList.toggle("is-diagram-switch-closed", switchState === "closed");
}

function updateDiagramSwitchVisualStates(container, maps) {
  if (!container) return;
  const elementsByDevice = new Map();
  container.querySelectorAll("[dev-id], [dev]").forEach((element) => {
    [element.getAttribute("dev-id"), element.getAttribute("dev")]
      .map((value) => String(value || "").trim())
      .filter(Boolean)
      .forEach((devId) => {
        if (!elementsByDevice.has(devId)) elementsByDevice.set(devId, []);
        elementsByDevice.get(devId).push(element);
      });
  });
  const devices = diagramDeviceIndex(container);
  container.querySelectorAll("use[dev-id], use[id][name]").forEach((element) => {
    const devId = String(element.getAttribute("dev-id") || element.getAttribute("id") || "").trim();
    const device = devices.get(devId);
    if (!devId || !device) return;
    const currentHref = element.getAttribute("href") || element.getAttribute("xlink:href") || "";
    const supportsStateSymbols = /_state_[01](?=(?:_\d+)?(?:$|[?#]))/.test(currentHref)
      || element.hasAttribute("data-open-href")
      || element.hasAttribute("data-closed-href");
    if (!supportsStateSymbols) return;
    const switchState = diagramSwitchState(diagramSwitchActualValue(device, maps));
    (elementsByDevice.get(devId) || [element]).forEach((related) => {
      setDiagramSwitchElementState(related, switchState);
    });
    if (switchState === "unknown") return;
    const explicitHref = element.getAttribute(switchState === "closed" ? "data-closed-href" : "data-open-href");
    const nextHref = explicitHref || diagramSwitchStateHref(currentHref, switchState);
    if (!nextHref || nextHref === currentHref) return;
    element.setAttribute("href", nextHref);
    if (element.hasAttribute("xlink:href")) element.setAttribute("xlink:href", nextHref);
  });
}

function addDiagramControlAliases(map, aliases, value, updated) {
  aliases.map((item) => String(item || "").trim()).filter(Boolean).forEach((alias) => {
    map.set(alias, { value, updated });
  });
}

function diagramControlMap(snapshot = state.snapshot || {}) {
  const map = new Map();
  activeCommandHistory(snapshot).forEach((entry) => {
    const normalized = entry.normalized || {};
    const payload = entry.payload || {};
    const updated = entry.issue_simu_time || entry.receive_simu_time || entry.simu_time || entry.wall_time || "";
    (normalized.run_status || payload.run_status || []).forEach((item) => {
      const devType = item.dev_type || "";
      const devName = item.dev_name || "";
      addDiagramControlAliases(map, [
        item.name,
        `${devType}.${devName}.RUN_STAT`,
        `${devType}.${devName}.STATUS`,
      ], item.run_stat ?? item.status ?? item.value, updated);
    });
    (normalized.set_values || payload.set_values || payload.setpoints || []).forEach((item) => {
      const devType = item.dev_type || "";
      const devName = item.dev_name || "";
      const setType = item.set_type || "";
      addDiagramControlAliases(map, [
        item.name,
        `${devType}.${devName}.${setType}`,
      ], item.set_value ?? item.value, updated);
    });
  });
  return map;
}

function diagramBindingValue(name, maps, channel = "scada") {
  const key = String(name || "").trim();
  if (!key) return null;
  if (channel === "control") return maps.controls.get(key) || null;
  return maps.scada.get(key) || null;
}

function setDiagramElementValue(element, row, metricType = "") {
  const displayRow = diagramDisplayRow(row, metricType);
  const missing = displayRow?.value === undefined || displayRow?.value === null;
  const text = missing
    ? "--"
    : (displayRow.unit !== undefined ? diagramRowText(displayRow) : diagramNumberText(displayRow.value));
  const tag = String(element.tagName || "").toLowerCase();
  if (["text", "tspan", "title", "desc"].includes(tag) || element instanceof HTMLElement) {
    element.textContent = text;
  } else {
    element.setAttribute("data-current-value", text);
  }
  element.classList.toggle("is-diagram-bound", Boolean(displayRow) && !missing);
  element.setAttribute("data-bound-value", text);
  const updated = displayRow?.updated_simu_time || displayRow?.updated_wall_time || displayRow?.updated;
  if (updated) element.setAttribute("data-bound-time", updated);
  else element.removeAttribute("data-bound-time");
}

const diagramDeviceIndexCache = new WeakMap();
const diagramMetricBindingCache = new WeakMap();
const diagramRealtimeBindingCache = new WeakMap();
const diagramInteractionCache = new WeakMap();
const diagramViewportCache = new WeakMap();

function compileDiagramDeviceIndex(container) {
  const devices = new Map();
  container.querySelectorAll("[dev-id][name], use[id][name]").forEach((element) => {
    const devId = element.getAttribute("dev-id") || element.getAttribute("id") || "";
    const devName = element.getAttribute("name") || "";
    if (!devId || !devName || devices.has(devId)) return;
    const layerType = element.closest("[device-type]")?.getAttribute("device-type") || "";
    devices.set(devId, {
      devId,
      devType: layerType,
      devName,
    });
  });
  return devices;
}

function diagramDeviceIndex(container) {
  let devices = diagramDeviceIndexCache.get(container);
  if (!devices) {
    devices = compileDiagramDeviceIndex(container);
    diagramDeviceIndexCache.set(container, devices);
  }
  return devices;
}

function compileDiagramMetricBindings(container) {
  const devices = diagramDeviceIndex(container);
  return [...container.querySelectorAll("[dev] [mt]")].map((element) => {
    if (element.matches("[data-meas-name], [data-scada-name], [data-real-name], [data-control-name]")) {
      return null;
    }
    const owner = element.closest("[dev]");
    const device = devices.get(owner?.getAttribute("dev") || "");
    const metricType = diagramMetricTypeFromElement(element);
    if (!device || !metricType) return null;
    return { element, ...device, metricType };
  }).filter(Boolean);
}

function diagramMetricBindings(container) {
  let bindings = diagramMetricBindingCache.get(container);
  if (!bindings) {
    bindings = compileDiagramMetricBindings(container);
    diagramMetricBindingCache.set(container, bindings);
  }
  return bindings;
}

function diagramRealtimeBindings(container) {
  let bindings = diagramRealtimeBindingCache.get(container);
  if (!bindings) {
    const named = (attribute) => [...container.querySelectorAll(`[${attribute}]`)].map((element) => ({
      element,
      name: element.getAttribute(attribute),
    }));
    bindings = {
      measurements: named("data-meas-name"),
      scada: named("data-scada-name"),
      real: named("data-real-name"),
      controls: named("data-control-name"),
      metrics: diagramMetricBindings(container),
    };
    diagramRealtimeBindingCache.set(container, bindings);
  }
  return bindings;
}

function diagramDisplaySvg(container) {
  if (!container) return null;
  if (container.matches?.("svg.model-diagram-svg")) return container;
  return container.querySelector?.("svg.model-diagram-svg") || null;
}

function removeDiagramRuntimeLabels(container) {
  container
    ?.querySelectorAll?.(".diagram-device-label-id[data-diagram-runtime-label]")
    .forEach((element) => element.remove());
}

function prepareDiagramDisplayLayers(container) {
  const svg = diagramDisplaySvg(container);
  if (!svg) return { measurements: 0, labels: 0 };
  removeDiagramRuntimeLabels(svg);
  const measurementLayers = new Set();
  svg.querySelectorAll("[dev] [mt]").forEach((element) => {
    const owner = element.closest("[dev]");
    if (owner) measurementLayers.add(owner);
  });
  svg.querySelectorAll("[data-meas-name], [data-scada-name], [data-real-name], [data-control-name]").forEach((element) => {
    measurementLayers.add(element.closest("text") || element);
  });
  measurementLayers.forEach((element) => element.classList.add("diagram-measurement-layer"));

  let labelCount = 0;
  svg.querySelectorAll('text[id^="label_"][dev-id]').forEach((nameLabel) => {
    const devId = String(nameLabel.getAttribute("dev-id") || "").trim();
    if (!devId || !nameLabel.parentNode) return;
    nameLabel.classList.add("diagram-device-label-name");
    const idLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    ["x", "text-anchor", "transform", "dominant-baseline", "font-family", "font-weight", "font-style"].forEach((attribute) => {
      const value = nameLabel.getAttribute(attribute);
      if (value !== null && value !== "") idLabel.setAttribute(attribute, value);
    });
    const fontSize = Math.max(8, Number.parseFloat(nameLabel.getAttribute("font-size")) || 14);
    const sourceY = String(nameLabel.getAttribute("y") || "").trim();
    const numericY = Number(sourceY);
    if (sourceY && Number.isFinite(numericY)) idLabel.setAttribute("y", String(numericY + fontSize * 1.15));
    else {
      if (sourceY) idLabel.setAttribute("y", sourceY);
      idLabel.setAttribute("dy", String(fontSize * 1.15));
    }
    idLabel.setAttribute("font-size", String(Math.max(8, fontSize * 0.72)));
    idLabel.setAttribute("dev-id", devId);
    idLabel.setAttribute("data-diagram-runtime-label", "device-id");
    idLabel.setAttribute("aria-label", `设备编号 ${devId}`);
    idLabel.classList.add("diagram-device-label-id");
    idLabel.textContent = devId;
    nameLabel.parentNode.insertBefore(idLabel, nameLabel.nextSibling);
    labelCount += 1;
  });
  return { measurements: measurementLayers.size, labels: labelCount };
}

function applyDiagramDisplayPreferences(container, preferences = diagramDisplayPreferences) {
  const svg = diagramDisplaySvg(container);
  if (!svg) return null;
  const value = normalizeDiagramDisplayPreferences(preferences);
  svg.classList.toggle("is-diagram-measurements-hidden", !value.measurements);
  svg.classList.toggle("is-diagram-labels-hidden", !value.labels);
  svg.classList.toggle("is-diagram-flow-arrows-hidden", !value.flowArrows);
  return value;
}

function renderDiagramContextMenu(interaction) {
  const menu = interaction?.contextMenu;
  if (!menu) return;
  menu.innerHTML = diagramDisplayPreferenceMenuItems(diagramDisplayPreferences).map((item) => `
    <button type="button" class="diagram-context-menu-item" data-diagram-display-toggle="${item.key}"${item.value ? ` data-diagram-display-value="${item.value}"` : ""}>
      ${escapeHtml(item.label)}
    </button>`).join("");
}

function closeDiagramContextMenu(interaction) {
  if (!interaction?.contextMenu) return;
  interaction.contextMenu.hidden = true;
}

function openDiagramContextMenu(interaction, event) {
  const menu = interaction?.contextMenu;
  if (!menu) return;
  renderDiagramContextMenu(interaction);
  menu.hidden = false;
  menu.style.left = "0px";
  menu.style.top = "0px";
  const rect = menu.getBoundingClientRect();
  const position = diagramFloatingPosition(
    { x: event.clientX, y: event.clientY },
    { width: rect.width, height: rect.height },
    { width: window.innerWidth, height: window.innerHeight },
    8,
  );
  menu.style.left = `${position.left}px`;
  menu.style.top = `${position.top}px`;
}

function diagramFlowRouteD(element) {
  if (!element) return "";
  if (String(element.tagName || "").toLowerCase() === "line") {
    const values = ["x1", "y1", "x2", "y2"].map((attribute) => Number(element.getAttribute(attribute)));
    if (values.some((value) => !Number.isFinite(value))) return "";
    return `M ${values[0]} ${values[1]} L ${values[2]} ${values[3]}`;
  }
  return String(element.getAttribute?.("d") || "").trim();
}

function diagramFlowRouteLength(element) {
  try {
    const length = Number(element?.getTotalLength?.());
    return Number.isFinite(length) && length > 0 ? length : 0;
  } catch (_error) {
    return 0;
  }
}

function diagramFlowArrowColor(sourceElement) {
  const computed = typeof window !== "undefined" && typeof window.getComputedStyle === "function"
    ? window.getComputedStyle(sourceElement)
    : null;
  const values = [
    sourceElement?.getAttribute?.("stroke"),
    computed?.stroke,
    sourceElement?.getAttribute?.("color"),
    computed?.color,
  ];
  return values.find((value) => {
    const normalized = String(value || "").trim().toLowerCase();
    return normalized
      && !["none", "transparent", "currentcolor", "inherit", "initial", "unset"].includes(normalized)
      && normalized !== "rgba(0, 0, 0, 0)";
  }) || "";
}

function diagramFlowSymbol(svg, useElement) {
  const href = String(useElement?.getAttribute("href") || useElement?.getAttribute("xlink:href") || "").trim();
  if (!href.startsWith("#")) return null;
  const id = href.slice(1);
  return [...(svg?.querySelectorAll("symbol") || [])].find((symbol) => symbol.getAttribute("id") === id) || null;
}

function diagramFlowPathTransforms(path, symbol) {
  const elements = [];
  let current = path?.parentElement || null;
  while (current && current !== symbol) {
    elements.unshift(current);
    current = current.parentElement;
  }
  if (path) elements.push(path);
  return elements
    .map((element) => String(element.getAttribute?.("transform") || "").trim())
    .filter(Boolean);
}

function diagramUseRouteTransform(useElement, symbol) {
  const viewBox = diagramViewBoxValue(symbol?.getAttribute("viewBox"));
  if (!viewBox) return "";
  const x = Number(useElement.getAttribute("x")) || 0;
  const y = Number(useElement.getAttribute("y")) || 0;
  const width = Number(useElement.getAttribute("width")) || viewBox.width;
  const height = Number(useElement.getAttribute("height")) || viewBox.height;
  if (width <= 0 || height <= 0) return "";
  const preserve = String(
    useElement.getAttribute("preserveAspectRatio")
    || symbol.getAttribute("preserveAspectRatio")
    || "xMidYMid meet",
  ).trim();
  if (preserve.startsWith("none")) {
    const scaleX = width / viewBox.width;
    const scaleY = height / viewBox.height;
    return `translate(${x - viewBox.x * scaleX} ${y - viewBox.y * scaleY}) scale(${scaleX} ${scaleY})`;
  }
  const parts = preserve.split(/\s+/);
  const align = parts[0] || "xMidYMid";
  const scaleMode = parts.includes("slice") ? "slice" : "meet";
  const scaleX = width / viewBox.width;
  const scaleY = height / viewBox.height;
  const scale = scaleMode === "slice" ? Math.max(scaleX, scaleY) : Math.min(scaleX, scaleY);
  const spareX = width - viewBox.width * scale;
  const spareY = height - viewBox.height * scale;
  const alignX = align.includes("xMax") ? spareX : align.includes("xMid") ? spareX / 2 : 0;
  const alignY = align.includes("YMax") ? spareY : align.includes("YMid") ? spareY / 2 : 0;
  return `translate(${x + alignX - viewBox.x * scale} ${y + alignY - viewBox.y * scale}) scale(${scale})`;
}

function diagramFlowEndpointKind(device) {
  const type = normalizeDiagramMeasurementToken(device?.devType);
  if (type.includes("CONVERTER")) return "";
  if (type.includes("GENERATOR")) return "generator";
  if (type.includes("LOAD")) return "load";
  return "";
}

function diagramHydrogenFlowRole(devType) {
  const type = normalizeDiagramMeasurementToken(devType);
  if (["ACE2HYDRO", "DCE2HYDRO", "HYDROSOURCE"].includes(type)) return "source";
  if (["HYDRO2ACE", "HYDRO2DCE", "HYDROLOAD"].includes(type)) return "load";
  if (type === "HYDROSTORAGE") return "storage";
  return "";
}

function diagramHydrogenFlowInlineKind(devType, nodes = []) {
  const type = normalizeDiagramMeasurementToken(devType);
  if (type === "HYDROPIPE") return "branch";
  if ([
    "HYDROVALVE",
    "HYDROSTOPVALVE",
    "HYDROCOMPRESSOR",
    "HYDROPRESSREGULATOR",
  ].includes(type)) return "device";
  const hydrogenTerminals = (nodes || []).filter((node) => (
    Number(node?.terminal) > 0 && diagramFlowDomain(node?.domain) === "hydro"
  ));
  if (hydrogenTerminals.length === 2) return "device";
  return "";
}

const DIAGRAM_HYDROGEN_TERMINAL_DOMAINS = Object.freeze({
  HYDROSOURCE: Object.freeze(["hydro"]),
  HYDROLOAD: Object.freeze(["hydro"]),
  HYDROSTORAGE: Object.freeze(["hydro"]),
  HYDROBUS: Object.freeze(["hydro"]),
  HYDROPIPE: Object.freeze(["hydro", "hydro"]),
  HYDROVALVE: Object.freeze(["hydro", "hydro"]),
  HYDROSTOPVALVE: Object.freeze(["hydro", "hydro"]),
  HYDROCOMPRESSOR: Object.freeze(["hydro", "hydro"]),
  HYDROPRESSREGULATOR: Object.freeze(["hydro", "hydro"]),
  ACE2HYDRO: Object.freeze(["ac", "hydro"]),
  DCE2HYDRO: Object.freeze(["dc", "hydro"]),
  HYDRO2ACE: Object.freeze(["ac", "hydro"]),
  HYDRO2DCE: Object.freeze(["dc", "hydro"]),
});

function diagramFlowTerminalDomains(devType) {
  const domains = DIAGRAM_HYDROGEN_TERMINAL_DOMAINS[normalizeDiagramMeasurementToken(devType)];
  return domains ? [...domains] : [];
}

function diagramFlowDomain(value) {
  const type = normalizeDiagramMeasurementToken(value);
  if (["HYDRO", "HYDROGEN", "H2"].includes(type)) return "hydro";
  if (type === "AC") return "ac";
  if (type === "DC") return "dc";
  return String(value || "").trim().toLowerCase();
}

function diagramHydrogenFlowEdgeTerminal(entry, otherEntry) {
  const hydrogenNodes = (entry?.nodes || []).filter((node) => (
    diagramFlowDomain(node?.domain || String(node?.key || "").split(":", 1)[0]) === "hydro"
  ));
  return hydrogenNodes.find((node) => (
    (otherEntry?.nodes || []).some((otherNode) => otherNode.key === node.key)
  )) || null;
}

function diagramHydrogenFlowEdgeCandidate(position, entry, otherEntry, topology) {
  const terminalNode = diagramHydrogenFlowEdgeTerminal(entry, otherEntry);
  if (!terminalNode) return null;
  const role = diagramHydrogenFlowRole(entry?.device?.devType);
  if (role) {
    const orientation = role === "load"
      ? (position === "target" ? 1 : -1)
      : (position === "source" ? 1 : -1);
    return {
      entry,
      orientation,
      priority: role === "storage" ? 1 : 2,
      powerBindings: [{
        device: entry.device,
        nodes: entry.nodes || [],
        orientation: 1,
        priority: role === "storage" ? 1 : 2,
        measurementTypes: ["FLOW"],
      }],
    };
  }
  if (!diagramHydrogenFlowInlineKind(entry?.device?.devType, entry?.nodes) || Number(terminalNode.terminal) <= 0) return null;
  return {
    entry,
    orientation: diagramFlowEdgeTerminalOrientation(position, terminalNode.terminal),
    priority: 3,
    powerBindings: diagramFlowPowerBindings(entry.device, entry.element, topology),
  };
}

function diagramHydrogenFlowEdgeBinding(sourceEntry, targetEntry, topology) {
  const candidates = [
    diagramHydrogenFlowEdgeCandidate("source", sourceEntry, targetEntry, topology),
    diagramHydrogenFlowEdgeCandidate("target", targetEntry, sourceEntry, topology),
  ].filter(Boolean).sort((left, right) => right.priority - left.priority);
  if (!candidates.length) return null;
  const selected = candidates[0];
  const orientation = selected.orientation;
  const uniqueBindings = new Map();
  candidates.forEach((candidate) => {
    candidate.powerBindings.forEach((binding) => {
      const adjusted = {
        ...binding,
        orientation: (Number(binding.orientation) < 0 ? -1 : 1)
          * candidate.orientation
          * orientation,
      };
      const key = `${adjusted.device?.devId || ""}|${adjusted.orientation}|${(adjusted.measurementTypes || []).join(",")}`;
      if (!uniqueBindings.has(key)) uniqueBindings.set(key, adjusted);
    });
  });
  return {
    kind: "hydrogen",
    device: selected.entry.device,
    orientation,
    powerBindings: [...uniqueBindings.values()],
  };
}

function diagramFlowPowerAnchorKind(device, nodes = []) {
  const hydrogenRole = diagramHydrogenFlowRole(device?.devType);
  if (hydrogenRole) return hydrogenRole;
  if (diagramHydrogenFlowInlineKind(device?.devType, nodes)) return "two-terminal";
  const endpointKind = diagramFlowEndpointKind(device);
  if (endpointKind) return endpointKind;
  const type = normalizeDiagramMeasurementToken(device?.devType);
  if (type.includes("BRANCH") || type.includes("CONVERTER") || type.includes("TRANSFORMER")) {
    return "two-terminal";
  }
  return "";
}

function diagramFlowDeviceNodes(element) {
  if (!element?.getAttribute) return [];
  const node1 = String(element.getAttribute("node-1") || "").trim();
  const node2 = String(element.getAttribute("node-2") || "").trim();
  const baseDomain = String(element.getAttribute("voltage-type") || "").trim();
  const fallbackType = normalizeDiagramMeasurementToken(element.parentElement?.getAttribute?.("device-type"));
  const terminalDomains = diagramFlowTerminalDomains(fallbackType);
  const fallbackDomain = fallbackType.startsWith("AC") ? "ac" : fallbackType.startsWith("DC") ? "dc" : "";
  const domain1 = diagramFlowDomain(element.getAttribute("voltage-type-1") || terminalDomains[0] || baseDomain || fallbackDomain);
  const domain2 = diagramFlowDomain(element.getAttribute("voltage-type-2") || terminalDomains[1] || baseDomain || fallbackDomain);
  const nodes = [];
  if (node1) nodes.push({ node: node1, key: diagramFlowNodeKey(node1, domain1), terminal: 1, domain: domain1 });
  if (node2) nodes.push({ node: node2, key: diagramFlowNodeKey(node2, domain2), terminal: 2, domain: domain2 });
  if (!nodes.length) {
    const node = String(element.getAttribute("node") || "").trim();
    const domain = diagramFlowDomain(terminalDomains[0] || baseDomain || fallbackDomain);
    if (node) nodes.push({ node, key: diagramFlowNodeKey(node, domain), terminal: 0, domain });
  }
  return nodes;
}

function diagramFlowTopology(svg, container) {
  const entries = [];
  const byId = new Map();
  const byNode = new Map();
  svg?.querySelectorAll?.("g[device-type] > use[dev-id]").forEach((element) => {
    const devId = diagramElementDeviceId(element);
    const device = diagramDeviceRecord(container, devId);
    const entry = { devId, device, element, nodes: diagramFlowDeviceNodes(element) };
    entries.push(entry);
    byId.set(devId, entry);
    entry.nodes.forEach(({ key }) => {
      if (!byNode.has(key)) byNode.set(key, []);
      byNode.get(key).push(entry);
    });
  });
  return { entries, byId, byNode };
}

function diagramFlowDeviceRoute(symbol) {
  const viewBox = diagramViewBoxValue(symbol?.getAttribute?.("viewBox"));
  if (!viewBox) return null;
  const y = viewBox.y + viewBox.height / 2;
  const inset = viewBox.width * 0.08;
  const x1 = viewBox.x + inset;
  const x2 = viewBox.x + viewBox.width - inset;
  const orientationGroup = [...(symbol.children || [])].find(
    (element) => String(element.tagName || "").toLowerCase() === "g",
  );
  return {
    routeD: `M ${x1} ${y} L ${x2} ${y}`,
    routeLength: viewBox.width * 0.45,
    transforms: [String(orientationGroup?.getAttribute?.("transform") || "").trim()].filter(Boolean),
  };
}

function diagramFlowPowerBindings(device, element, topology) {
  const entry = topology?.byId?.get(String(device?.devId || ""));
  const ownNodes = entry?.nodes || diagramFlowDeviceNodes(element);
  const hydrogenInline = diagramHydrogenFlowInlineKind(device?.devType, ownNodes);
  const own = {
    device,
    nodes: ownNodes,
    orientation: diagramFlowPowerRouteOrientation(device, ownNodes),
    priority: hydrogenInline ? 3 : 1,
    ...(hydrogenInline ? { measurementTypes: ["FLOW"] } : {}),
  };
  const type = normalizeDiagramMeasurementToken(device?.devType);
  if (!type.includes("BREAK") && !type.includes("SWITCH") && !hydrogenInline) return [own];
  if (!entry) return [own];
  const fallbacks = [];
  entry.nodes.filter(({ terminal }) => terminal > 0).forEach(({ key, terminal }) => {
    (topology.byNode.get(key) || []).forEach((neighbor) => {
      if (neighbor === entry) return;
      const neighborKind = diagramFlowPowerAnchorKind(neighbor.device, neighbor.nodes);
      if (!neighborKind) return;
      const hydrogenNeighbor = Boolean(
        diagramHydrogenFlowRole(neighbor.device?.devType)
        || diagramHydrogenFlowInlineKind(neighbor.device?.devType, neighbor.nodes),
      );
      if (hydrogenInline && !hydrogenNeighbor) return;
      const neighborTerminal = neighbor.nodes.find((item) => item.key === key)?.terminal || 0;
      fallbacks.push({
        device: neighbor.device,
        nodes: neighbor.nodes,
        orientation: diagramFlowSeriesOrientation(terminal, neighborKind, neighborTerminal)
          * diagramFlowPowerRouteOrientation(neighbor.device, neighbor.nodes),
        priority: 2,
        ...(hydrogenNeighbor ? { measurementTypes: ["FLOW"] } : {}),
      });
    });
  });
  const unique = new Map();
  fallbacks.forEach((binding) => {
    const key = `${binding.device?.devId || ""}|${binding.orientation}`;
    if (!unique.has(key)) unique.set(key, binding);
  });
  return [...unique.values(), own];
}

function diagramFlowEdgeBinding(sourceEntry, targetEntry, topology) {
  const hydrogenBinding = diagramHydrogenFlowEdgeBinding(sourceEntry, targetEntry, topology);
  if (hydrogenBinding) return hydrogenBinding;
  const endpoints = [
    { position: "source", entry: sourceEntry, endpointKind: diagramFlowEndpointKind(sourceEntry?.device) },
    { position: "target", entry: targetEntry, endpointKind: diagramFlowEndpointKind(targetEntry?.device) },
  ];
  const direct = endpoints.filter((item) => item.endpointKind);
  if (direct.length === 1) {
    const selected = direct[0];
    const orientation = selected.endpointKind === "generator"
      ? (selected.position === "source" ? 1 : -1)
      : (selected.position === "target" ? 1 : -1);
    return {
      kind: "endpoint",
      device: selected.entry.device,
      orientation,
      powerBindings: diagramFlowPowerBindings(selected.entry.device, selected.entry.element, topology),
    };
  }
  if (direct.length > 1) return null;
  const connectorCandidates = endpoints.map((item) => {
    const inlineKind = diagramFlowInlineDeviceKind(item.entry?.device?.devType, item.entry?.nodes);
    const type = normalizeDiagramMeasurementToken(item.entry?.device?.devType);
    const priority = inlineKind === "branch" ? 3 : type.includes("CONVERTER") ? 2 : inlineKind ? 1 : 0;
    return { ...item, priority };
  }).filter((item) => item.priority > 0);
  if (!connectorCandidates.length) return null;
  const bestPriority = Math.max(...connectorCandidates.map((item) => item.priority));
  const best = connectorCandidates.filter((item) => item.priority === bestPriority);
  if (best.length !== 1) return null;
  const selected = best[0];
  const other = selected.position === "source" ? targetEntry : sourceEntry;
  const terminal = selected.entry.nodes.find(
    (item) => item.terminal > 0 && other?.nodes?.some((otherNode) => otherNode.key === item.key),
  )?.terminal;
  if (!terminal) return null;
  return {
    kind: "connector",
    device: selected.entry.device,
    orientation: diagramFlowEdgeTerminalOrientation(selected.position, terminal),
    powerBindings: diagramFlowPowerBindings(selected.entry.device, selected.entry.element, topology),
  };
}

function diagramFlowDevicePowerSample(device, measurementMaps, measurementTypes = null) {
  const measurementDevice = diagramCouplingMeasurementEndpoint(
    device,
    measurementMaps,
    "",
    measurementTypes,
  );
  if (!measurementDevice) return null;
  const types = Array.isArray(measurementTypes) && measurementTypes.length
    ? measurementTypes
    : diagramFlowPowerMeasurementTypes(measurementDevice?.devType);
  for (const map of [measurementMaps?.scadaByDevice, measurementMaps?.realByDevice]) {
    const candidates = types.map((measType, order) => {
      const key = diagramDeviceMeasurementKey(measurementDevice?.devType, measurementDevice?.devName, measType);
      const row = map?.get(key);
      const rawPower = Number(row?.value);
      const valid = Boolean(row) && Number(row.valid ?? 1) === 1 && Number.isFinite(rawPower);
      return valid ? {
        row,
        power: diagramFlowCanonicalPower(
          row?.meas_type || row?.measurement_type || measType,
          rawPower,
        ),
        order,
      } : null;
    }).filter(Boolean);
    if (candidates.length) {
      return candidates.reduce((best, item) => (
        Math.abs(item.power) > Math.abs(best.power) ? item : best
      ));
    }
  }
  return null;
}

function diagramFlowResolvePower(record, measurementMaps) {
  const resolved = (record?.powerBindings || [{ device: record?.device, orientation: 1, priority: 1 }])
    .map((binding) => {
      const sample = diagramFlowDevicePowerSample(
        binding.device,
        measurementMaps,
        binding.measurementTypes,
      );
      return {
        binding,
        row: sample?.row || null,
        valid: Boolean(sample) && Number.isFinite(sample.power),
        power: Number(sample?.power) * (Number(binding.orientation) < 0 ? -1 : 1),
      };
    })
    .filter((item) => item.valid);
  if (!resolved.length) return { row: null, binding: null, power: Number.NaN, valid: false };
  const priority = Math.max(...resolved.map((item) => Number(item.binding.priority) || 0));
  const candidates = resolved.filter((item) => (Number(item.binding.priority) || 0) === priority);
  const selected = candidates.reduce((best, item) => (
    Math.abs(item.power) > Math.abs(best.power) ? item : best
  ));
  return { ...selected, valid: true };
}

function diagramFlowDeviceBlocksFlow(device, deviceState, measurementMaps) {
  const type = normalizeDiagramMeasurementToken(device?.devType);
  if (!["HYDROVALVE", "HYDROSTOPVALVE"].includes(type)) return false;
  const status = diagramSwitchMeasurementRow(device, measurementMaps)?.value ?? deviceState?.status;
  return diagramSwitchState(status) === "open";
}

function createDiagramFlowArrow(sourceElement, routeD, transforms = [], routeLength = 0) {
  if (!sourceElement?.parentNode || !routeD) return null;
  const createSvgElement = (tagName) => document.createElementNS("http://www.w3.org/2000/svg", tagName);
  const root = createSvgElement("g");
  root.classList.add("diagram-flow-arrow");
  root.setAttribute("data-diagram-runtime-flow", "true");
  root.setAttribute("hidden", "");
  const color = diagramFlowArrowColor(sourceElement);
  if (color) root.style.setProperty("--diagram-flow-color", color);
  let parent = root;
  transforms.filter(Boolean).forEach((transform) => {
    const group = createSvgElement("g");
    group.setAttribute("transform", transform);
    parent.appendChild(group);
    parent = group;
  });
  const guide = createSvgElement("path");
  guide.classList.add("diagram-flow-guide");
  guide.setAttribute("d", routeD);
  guide.setAttribute("fill", "none");
  parent.appendChild(guide);
  const markerCount = diagramFlowArrowCount(routeLength);
  const durationSeconds = 1.8;
  const markers = Array.from({ length: markerCount }, (_value, index) => {
    const marker = createSvgElement("g");
    marker.classList.add("diagram-flow-arrow-marker");
    marker.setAttribute("data-flow-marker-index", String(index));
    const polygon = createSvgElement("polygon");
    polygon.setAttribute("points", "-5,-3 5,0 -5,3");
    const animation = createSvgElement("animateMotion");
    animation.setAttribute("path", routeD);
    animation.setAttribute("dur", `${durationSeconds}s`);
    animation.setAttribute("begin", `${-(durationSeconds * index / markerCount).toFixed(3)}s`);
    animation.setAttribute("repeatCount", "indefinite");
    animation.setAttribute("calcMode", "linear");
    animation.setAttribute("keyTimes", "0;1");
    animation.setAttribute("keyPoints", "0;1");
    animation.setAttribute("rotate", "auto");
    marker.appendChild(polygon);
    marker.appendChild(animation);
    parent.appendChild(marker);
    return { marker, polygon, animation };
  });
  sourceElement.parentNode.insertBefore(root, sourceElement.nextSibling);
  return { root, guide, markers, direction: 0 };
}

function removeDiagramFlowArrows(container) {
  container?.querySelectorAll?.('.diagram-flow-arrow[data-diagram-runtime-flow]').forEach((element) => element.remove());
  const interaction = container ? diagramInteractionCache.get(container) : null;
  if (interaction) {
    interaction.flowArrows = [];
    interaction.flowArrowPeakReferences = new Map();
  }
}

function compileDiagramFlowArrows(container) {
  const svg = diagramDisplaySvg(container);
  const interaction = diagramInteractionState(container);
  removeDiagramFlowArrows(container);
  interaction.flowArrows = [];
  interaction.flowArrowPeakReferences = new Map();
  if (!svg) return interaction.flowArrows;
  const topology = diagramFlowTopology(svg, container);

  topology.entries.forEach(({ device, element: useElement, nodes }) => {
    const inlineKind = diagramFlowInlineDeviceKind(device?.devType, nodes);
    if (!inlineKind) return;
    const symbol = diagramFlowSymbol(svg, useElement);
    if (!symbol) return;
    const baseTransforms = [
      String(useElement.getAttribute("transform") || "").trim(),
      diagramUseRouteTransform(useElement, symbol),
    ].filter(Boolean);
    const powerBindings = diagramFlowPowerBindings(device, useElement, topology);
    if (inlineKind === "branch") {
      const routePath = symbol.querySelector(".routable-line-device-glyph path[d]");
      const routeD = diagramFlowRouteD(routePath);
      if (!routePath || !routeD) return;
      const transforms = [...baseTransforms, ...diagramFlowPathTransforms(routePath, symbol)];
      const arrow = createDiagramFlowArrow(useElement, routeD, transforms, diagramFlowRouteLength(routePath));
      if (!arrow) return;
      arrow.root.setAttribute("data-flow-source-id", String(device?.devId || ""));
      interaction.flowArrows.push({
        ...arrow,
        kind: "branch",
        device,
        pathDevices: [device],
        powerBindings,
        orientation: 1,
      });
      return;
    }
    const route = diagramFlowDeviceRoute(symbol);
    if (!route?.routeD) return;
    const arrow = createDiagramFlowArrow(
      useElement,
      route.routeD,
      [...baseTransforms, ...(route.transforms || [])],
      route.routeLength,
    );
    if (!arrow) return;
    arrow.root.setAttribute("data-flow-source-id", String(device?.devId || ""));
    interaction.flowArrows.push({
      ...arrow,
      kind: "device",
      device,
      pathDevices: [device],
      powerBindings,
      orientation: 1,
    });
  });

  svg.querySelectorAll("path[source-dev-id][target-dev-id], line[source-dev-id][target-dev-id]").forEach((edge) => {
    if (edge.closest("defs, symbol, marker, pattern, clipPath, mask") || edge.hasAttribute("data-diagram-runtime-flow")) return;
    const sourceEntry = topology.byId.get(String(edge.getAttribute("source-dev-id") || ""));
    const targetEntry = topology.byId.get(String(edge.getAttribute("target-dev-id") || ""));
    const binding = diagramFlowEdgeBinding(sourceEntry, targetEntry, topology);
    if (!binding) return;
    const routeD = diagramFlowRouteD(edge);
    if (!routeD) return;
    const transforms = [String(edge.getAttribute("transform") || "").trim()].filter(Boolean);
    const arrow = createDiagramFlowArrow(edge, routeD, transforms, diagramFlowRouteLength(edge));
    if (arrow) {
      arrow.root.setAttribute("data-flow-source-id", String(binding.device?.devId || ""));
      interaction.flowArrows.push({
        ...arrow,
        kind: binding.kind,
        device: binding.device,
        pathDevices: [sourceEntry?.device, targetEntry?.device].filter(Boolean),
        powerBindings: binding.powerBindings,
        orientation: binding.orientation,
      });
    }
  });
  return interaction.flowArrows;
}

function diagramFlowReferencePower(container, device, snapshot, interaction, power) {
  const raw = diagramDeviceData(container, device, snapshot).raw || {};
  const capacities = new Map(Object.entries(raw).map(([key, value]) => [
    String(key).trim().toLowerCase(),
    Number(value),
  ]));
  for (const key of ["flow_max", "rated_capacity", "rated_power", "p_max", "max_power", "max_charge_power", "max_discharge_power"]) {
    const value = Math.abs(Number(capacities.get(key)));
    if (Number.isFinite(value) && value > 0) return value;
  }
  const peakKey = normalizeDiagramMeasurementToken(device?.devType) || String(device?.devId || "unknown");
  const magnitude = Math.abs(Number(power));
  const previous = Number(interaction?.flowArrowPeakReferences?.get(peakKey)) || 0;
  const peak = Math.max(previous, Number.isFinite(magnitude) ? magnitude : 0);
  interaction?.flowArrowPeakReferences?.set(peakKey, peak);
  return peak > 0 ? peak : 1;
}

function updateDiagramFlowArrows(container, snapshot = state.snapshot || {}, measurementMaps = diagramMeasurementMaps(snapshot)) {
  const interaction = container ? diagramInteractionCache.get(container) : null;
  if (!interaction?.flowArrows?.length) return;
  const operatingMaps = diagramDeviceOperatingStateMaps(snapshot);
  interaction.flowArrows.forEach((record) => {
    const resolved = diagramFlowResolvePower(record, measurementMaps);
    const power = Number(resolved.power);
    const valid = Boolean(resolved.valid) && Number.isFinite(power);
    const relevantDevices = [
      record.device,
      resolved.binding?.device,
      ...(record.pathDevices || []),
    ].filter(Boolean);
    const offline = relevantDevices.some((device) => (
      diagramDeviceIsOffline(diagramDeviceOperatingState(device, operatingMaps))
      || diagramFlowDeviceBlocksFlow(
        device,
        diagramDeviceOperatingState(device, operatingMaps),
        measurementMaps,
      )
    ));
    const referenceDevice = resolved.binding?.device || record.device;
    const referencePower = diagramFlowReferencePower(container, referenceDevice, snapshot, interaction, power);
    const threshold = diagramFlowArrowThreshold(
      resolved.row?.meas_type || resolved.row?.measurement_type,
      activeRuntimeSetting("diagram_flow_electric_threshold_kw"),
      activeRuntimeSetting("diagram_flow_hydrogen_threshold_nm3_h"),
    );
    const visible = diagramFlowArrowVisibility({ power, threshold, valid, offline });
    record.root.setAttribute("data-flow-power", valid ? String(power) : "");
    record.root.setAttribute("data-flow-binding-id", String(resolved.binding?.device?.devId || ""));
    record.root.setAttribute(
      "data-flow-measurement-type",
      String(resolved.row?.meas_type || resolved.row?.measurement_type || ""),
    );
    record.root.toggleAttribute("hidden", !visible);
    if (!visible) return;
    const size = diagramFlowArrowSize(power, referencePower);
    const halfLength = size / 2;
    const halfHeight = Math.max(2, size * 0.32);
    record.markers.forEach(({ polygon }) => {
      polygon.setAttribute(
        "points",
        `${-halfLength},${-halfHeight} ${halfLength},0 ${-halfLength},${halfHeight}`,
      );
    });
    const direction = diagramFlowArrowDirection(power, record.orientation);
    if (direction !== record.direction) {
      record.direction = direction;
      const motion = diagramFlowMotionAttributes(direction);
      record.markers.forEach(({ animation }) => {
        animation.setAttribute("keyPoints", motion.keyPoints);
        animation.setAttribute("rotate", motion.rotate);
      });
    }
    record.root.setAttribute("data-flow-direction", direction < 0 ? "reverse" : "forward");
  });
}

function diagramInteractionState(container) {
  let interaction = diagramInteractionCache.get(container);
  if (!interaction) {
    interaction = {
      container,
      initialized: false,
      selectedDevId: "",
      hover: null,
      snapshot: null,
      tooltip: null,
      tooltipPositionKey: "",
      trendPeriod: "hour",
      trendPeriodOffsets: { hour: 0, day: 0 },
      trendNavigationRange: null,
      trendChart: null,
      trendCursorClientX: null,
      contextMenu: null,
      flowArrows: [],
      flowArrowPeakReferences: new Map(),
      pointer: { x: 0, y: 0 },
      hideTimer: null,
      definitionEditor: null,
      definitionSaving: false,
      definitionLeavePrompt: false,
      definitionCloseAfterSave: false,
      definitionMessage: "",
      definitionMessageWarning: false,
      deviceTooltipHostKey: "",
      deviceTooltipTabKey: "self",
      drag: null,
      suppressClick: false,
      suppressClickTimer: null,
    };
    diagramInteractionCache.set(container, interaction);
  }
  return interaction;
}

function diagramDeviceRecord(container, devId) {
  const key = String(devId || "").trim();
  if (!key) return null;
  const indexed = diagramDeviceIndex(container).get(key);
  if (indexed) return indexed;
  return {
    devId: key,
    devType: "",
    devName: key,
  };
}

const DIAGRAM_DEVICE_ELEMENT_SELECTOR = "[dev-id], use[id][name]";

function diagramElementDeviceId(element) {
  if (!element || typeof element.getAttribute !== "function") return "";
  const explicit = element.getAttribute("dev-id") || element.getAttribute("dev");
  if (explicit) return String(explicit).trim();
  if (String(element.tagName || "").toLowerCase() !== "use" || !element.getAttribute("name")) return "";
  return String(element.getAttribute("id") || "").trim();
}

function diagramMetricElementForTarget(container, target) {
  if (!(target instanceof Element) || !container.contains(target)) return null;
  const directMetric = target.closest("[mt]");
  if (directMetric && container.contains(directMetric)) return directMetric;
  const owner = target.closest("[dev]");
  const row = target.closest("text");
  if (!owner || !row || !container.contains(owner) || !owner.contains(row)) return null;
  const rowMetric = row.querySelector("[mt]");
  return rowMetric && container.contains(rowMetric) ? rowMetric : null;
}

function diagramTargetDeviceId(container, target) {
  if (!(target instanceof Element) || !container.contains(target)) return "";
  const metricElement = diagramMetricElementForTarget(container, target);
  if (metricElement) {
    const owner = metricElement.closest("[dev]");
    if (owner && container.contains(owner)) return String(owner.getAttribute("dev") || "").trim();
  }
  const deviceElement = target.closest(DIAGRAM_DEVICE_ELEMENT_SELECTOR);
  if (!deviceElement || !container.contains(deviceElement)) return "";
  return diagramElementDeviceId(deviceElement);
}

function diagramHoverTarget(container, target) {
  if (!(target instanceof Element) || !container.contains(target)) return null;
  const metricElement = diagramMetricElementForTarget(container, target);
  if (metricElement) {
    const owner = metricElement.closest("[dev]");
    const devId = String(owner?.getAttribute("dev") || "").trim();
    const metricType = String(
      metricElement.getAttribute("mti") || metricElement.getAttribute("mt") || "",
    ).trim();
    if (devId && metricType) {
      return {
        kind: "metric",
        key: `metric:${devId}:${metricType}`,
        element: metricElement,
        binding: { ...diagramDeviceRecord(container, devId), metricType },
      };
    }
  }
  const namedMetric = target.closest("[data-meas-name], [data-scada-name]");
  if (namedMetric && container.contains(namedMetric)) {
    const name = namedMetric.getAttribute("data-meas-name")
      || namedMetric.getAttribute("data-scada-name")
      || "";
    if (name) {
      return {
        kind: "metric",
        key: `named-metric:scada:${name}`,
        element: namedMetric,
        channel: "scada",
        name,
        metricType: "",
      };
    }
  }
  const devId = diagramTargetDeviceId(container, target);
  if (!devId) return null;
  return {
    kind: "device",
    key: `device:${devId}`,
    element: target.closest(DIAGRAM_DEVICE_ELEMENT_SELECTOR),
    device: diagramDeviceRecord(container, devId),
  };
}

function setDiagramSelectedDevice(container, devId = "") {
  if (!container) return;
  const interaction = diagramInteractionState(container);
  const selectedDevId = String(devId || "").trim();
  interaction.selectedDevId = selectedDevId;
  container.querySelectorAll(".is-diagram-selected").forEach((element) => {
    element.classList.remove("is-diagram-selected");
  });
  if (!selectedDevId) return;
  container.querySelectorAll(DIAGRAM_DEVICE_ELEMENT_SELECTOR).forEach((element) => {
    if (diagramElementDeviceId(element) === selectedDevId) element.classList.add("is-diagram-selected");
  });
}

function updateDiagramDeviceVisualStates(container, snapshot = {}) {
  if (!container) return;
  const maps = diagramDeviceOperatingStateMaps(snapshot);
  container.querySelectorAll("[dev-id], [dev]").forEach((element) => {
    const devId = String(element.getAttribute("dev-id") || element.getAttribute("dev") || "").trim();
    const deviceState = diagramDeviceOperatingState(diagramDeviceRecord(container, devId), maps);
    const offline = diagramDeviceIsOffline(deviceState);
    element.classList.toggle("is-diagram-offline", offline);
    if (!deviceState) {
      element.removeAttribute("data-diagram-operating-state");
    } else if (Number(deviceState.run_stat ?? 1) === 0) {
      element.setAttribute("data-diagram-operating-state", "retired");
    } else if (diagramDeviceIsOffline(deviceState)) {
      element.setAttribute("data-diagram-operating-state", "dead-island");
    } else {
      element.setAttribute("data-diagram-operating-state", "running");
    }
  });
}

function diagramTooltipValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  if (Array.isArray(value)) return value.map((item) => diagramTooltipValue(item)).join(", ");
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch (_error) {
      return String(value);
    }
  }
  return String(value);
}

function diagramMeasurementUnit(measType) {
  const type = normalizeDiagramMeasurementToken(measType);
  if (type === "SOC" || type === "LEVEL") return "%";
  if (type === "PRESSURE") return "MPa";
  if (type === "FLOW") return "Nm3/h";
  if (type === "GAS_QUANTITY") return "Nm3";
  if (type.startsWith("P")) return "kW";
  if (type.startsWith("Q")) return "kvar";
  if (type.startsWith("V")) return "V";
  if (type.startsWith("I")) return "A";
  if (type.includes("FREQ")) return "Hz";
  if (type.includes("TEMP")) return "℃";
  return "";
}

function diagramTooltipRowKey(sectionKey, label, index = 0) {
  return `${String(sectionKey || "section")}:${String(label || index)}`;
}

function diagramIntegratedDefinitionBindingMatchesEditor(binding, interaction) {
  return Boolean(diagramDeviceDefinitionRecordEditor(
    interaction?.definitionEditor,
    binding,
  ));
}

function renderDiagramIntegratedDefinitionRow(label, value, rowKey, binding, interaction) {
  const fieldEditable = Boolean(binding?.editable);
  const activeEditor = diagramDeviceDefinitionRecordEditor(
    interaction?.definitionEditor,
    binding,
  );
  const editing = Boolean(activeEditor && fieldEditable);
  const recordAttributes = binding
    ? ` data-diagram-definition-block="${escapeHtml(binding.blockName)}" data-diagram-definition-row-index="${binding.rowIndex}"`
    : "";
  if (!editing) {
    return `
      <div class="diagram-tooltip-row${fieldEditable ? " is-editable" : ""}" data-diagram-tooltip-row="${escapeHtml(rowKey)}"${recordAttributes}>
        <dt>${escapeHtml(label)}</dt>
        <dd
          data-diagram-tooltip-value="${escapeHtml(rowKey)}"
          ${fieldEditable ? 'data-diagram-definition-editable="device"' : ""}
        >${escapeHtml(diagramDefinitionDisplayValue(binding?.field, value))}</dd>
      </div>`;
  }
  const enumOptions = diagramDefinitionEnumOptions(
    { ...binding, row: activeEditor.draft },
    binding.field,
  );
  if (enumOptions.length) {
    return `
      <div class="diagram-tooltip-row is-editing-definition" data-diagram-tooltip-row="${escapeHtml(rowKey)}"${recordAttributes}>
        <dt>${escapeHtml(label)}</dt>
        <dd data-diagram-tooltip-value="${escapeHtml(rowKey)}">
          ${renderDiagramDefinitionEnumSelect(
            { ...binding, row: activeEditor.draft },
            binding.field,
            activeEditor.draft[binding.field],
            interaction,
          )}
        </dd>
      </div>`;
  }
  const descriptor = diagramDefinitionInputDescriptor(binding.field, activeEditor.draft[binding.field]);
  return `
    <div class="diagram-tooltip-row is-editing-definition" data-diagram-tooltip-row="${escapeHtml(rowKey)}"${recordAttributes}>
      <dt>${escapeHtml(label)}</dt>
      <dd data-diagram-tooltip-value="${escapeHtml(rowKey)}">
        <span class="diagram-definition-input-wrap">
          <input
            class="diagram-definition-input"
            data-diagram-tooltip-inline-input
            data-diagram-definition-input="device"
            data-diagram-definition-field="${escapeHtml(binding.field)}"
            type="${descriptor.type}"
            ${descriptor.type === "number" ? 'step="any"' : ""}
            ${descriptor.min !== "" ? `min="${descriptor.min}"` : ""}
            ${descriptor.max !== "" ? `max="${descriptor.max}"` : ""}
            value="${escapeHtml(descriptor.value)}"
            ${interaction?.definitionSaving ? "disabled" : ""}
          >
          ${descriptor.suffix ? `<small>${escapeHtml(descriptor.suffix)}</small>` : ""}
        </span>
      </dd>
    </div>`;
}

function diagramTooltipRows(rows = [], sectionKey = "", interaction = null) {
  const content = rows
    .filter((row) => row && row[0])
    .map(([label, value, key, binding], index) => {
      const rowKey = String(key || diagramTooltipRowKey(sectionKey, label, index));
      if (binding) {
        return renderDiagramIntegratedDefinitionRow(label, value, rowKey, binding, interaction);
      }
      return `
      <div class="diagram-tooltip-row" data-diagram-tooltip-row="${escapeHtml(rowKey)}">
        <dt>${escapeHtml(label)}</dt>
        <dd data-diagram-tooltip-value="${escapeHtml(rowKey)}">${escapeHtml(diagramTooltipValue(value))}</dd>
      </div>`;
    })
    .join("");
  return content ? `<dl class="diagram-tooltip-grid">${content}</dl>` : "";
}

const DIAGRAM_DEFINITION_PROTECTED_FIELDS = new Set([
  "idx", "name", "dev_name", "dev_type", "path",
  "node", "i_node", "j_node", "ac_node", "dc_node",
  "isl", "run_stat", "status", "pv0", "qv0",
]);

const DIAGRAM_DEFINITION_IDENTITY_FIELDS = new Set([
  "idx", "name", "dev_name", "dev_type",
]);
const DIAGRAM_DEFINITION_HIDDEN_FIELDS = new Set([
  "closed_status", "closed_status_set",
]);
const DIAGRAM_REALTIME_MEASUREMENT_FIELDS = new Set(["p", "q", "u", "i", "f"]);

function diagramDefinitionDisplayHeaders(record) {
  const integratedFields = record?.integratedFields instanceof Set
    ? record.integratedFields
    : new Set(record?.integratedFields || []);
  return (record?.headers || []).filter((field) => {
    const name = String(field || "").trim().toLowerCase();
    return !DIAGRAM_DEFINITION_IDENTITY_FIELDS.has(name)
      && !DIAGRAM_DEFINITION_HIDDEN_FIELDS.has(name)
      && !integratedFields.has(name)
      && !DIAGRAM_REALTIME_MEASUREMENT_FIELDS.has(name);
  });
}

function diagramDefinitionFieldBinding(records, fieldNames = []) {
  const candidates = new Set(fieldNames.map((field) => String(field || "").trim().toLowerCase()));
  for (const record of records || []) {
    const field = (record.headers || []).find((header) => (
      candidates.has(String(header || "").trim().toLowerCase())
    ));
    if (!field) continue;
    if (!(record.integratedFields instanceof Set)) record.integratedFields = new Set();
    record.integratedFields.add(String(field).trim().toLowerCase());
    return {
      blockName: record.blockName,
      rowIndex: record.rowIndex,
      field,
      editable: diagramDeviceParameterEditable(field),
    };
  }
  return null;
}

const DIAGRAM_LINKED_DEFINITION_BLOCKS = Object.freeze({
  ACGENERATOR: [
    { blockName: "ACWindGen", referenceField: "idx_acgenerator" },
    { blockName: "ACPVGen", referenceField: "idx_acgenerator" },
    { blockName: "ACStorageGen", referenceField: "idx_acgenerator" },
  ],
  DCGENERATOR: [
    { blockName: "DCWindGen", referenceField: "idx_dcgenerator" },
    { blockName: "DCPVGen", referenceField: "idx_dcgenerator" },
    { blockName: "DCStorageGen", referenceField: "idx_dcgenerator" },
  ],
});

function diagramDeviceParameterEditable(field) {
  const name = String(field || "").trim().toLowerCase();
  return Boolean(name)
    && !DIAGRAM_DEFINITION_PROTECTED_FIELDS.has(name)
    && !DIAGRAM_REALTIME_MEASUREMENT_FIELDS.has(name)
    && !name.startsWith("idx_")
    && !name.endsWith("_set");
}

function diagramDefinitionSigmaFromWeight(weight) {
  const number = Number(weight);
  return Number.isFinite(number) && number > 0 ? 1 / Math.sqrt(number) : null;
}

function diagramDefinitionWeightFromSigma(sigma) {
  const number = Number(sigma);
  return Number.isFinite(number) && number > 0 ? 1 / (number * number) : null;
}

const DIAGRAM_MEASUREMENT_STATUS_LABELS = Object.freeze({
  valid: "有效",
  invalid: "无效",
  undefined: "无定义",
  dead: "死数",
  zero: "零值",
  fixed: "固定值",
});

function diagramMeasurementStatus(value, valid = 1) {
  const status = String(value || "").trim().toLowerCase();
  if (Object.prototype.hasOwnProperty.call(DIAGRAM_MEASUREMENT_STATUS_LABELS, status)) return status;
  return Number(valid) === 1 ? "valid" : "invalid";
}

function diagramMeasurementStatusLabel(value, valid = 1) {
  return DIAGRAM_MEASUREMENT_STATUS_LABELS[diagramMeasurementStatus(value, valid)] || "无效";
}

function diagramDefinitionEditorMessageHtml(interaction, validationError = "") {
  const validation = String(validationError || "").trim();
  const message = validation || String(interaction?.definitionMessage || "").trim();
  const warning = Boolean(validation || interaction?.definitionMessageWarning);
  return `<div class="diagram-definition-message${warning ? " is-warning" : " is-success"}" data-diagram-definition-message${message ? "" : " hidden"}>${escapeHtml(message)}</div>`;
}

function diagramDefinitionRecord(blockName, block, row, rowIndex) {
  const headers = Array.isArray(block?.headers) ? [...block.headers] : Object.keys(row || {});
  const recordRow = Object.fromEntries(headers.map((header) => [header, row?.[header] ?? ""]));
  return {
    blockName,
    headers,
    row: recordRow,
    rowIndex,
    rowKey: {
      idx: recordRow.idx ?? "",
      name: recordRow.name ?? "",
    },
    editableFields: headers.filter((field) => diagramDeviceParameterEditable(field)),
  };
}

function diagramDeviceDefinitionRecords(device, snapshot = state.snapshot || {}) {
  if (!device) return [];
  const blocks = snapshot?.definitions?.model || {};
  const deviceType = normalizeDiagramMeasurementToken(device.devType);
  const primaryEntry = Object.entries(blocks).find(([blockName]) => (
    normalizeDiagramMeasurementToken(blockName) === deviceType
  ));
  if (!primaryEntry) return [];
  const [primaryBlockName, primaryBlock] = primaryEntry;
  const primaryRows = Array.isArray(primaryBlock?.rows) ? primaryBlock.rows : [];
  const deviceName = String(device.devName || "");
  const primaryIndex = primaryRows.findIndex((row, rowIndex) => {
    const rowName = String(row?.name ?? row?.dev_name ?? "");
    if (rowName) return rowName === deviceName;
    const idx = String(row?.idx ?? rowIndex + 1);
    return deviceName === `${primaryBlockName}_${idx}`
      || String(device.devId || "") === `${primaryBlockName}-${idx}`;
  });
  if (primaryIndex < 0) return [];
  const primaryRecord = diagramDefinitionRecord(
    primaryBlockName,
    primaryBlock,
    primaryRows[primaryIndex],
    primaryIndex,
  );
  const primaryIdx = String(primaryRecord.row.idx ?? "");
  if (!primaryIdx) return [primaryRecord];

  const configuredLinks = DIAGRAM_LINKED_DEFINITION_BLOCKS[deviceType] || [];
  const configuredByBlock = new Map(configuredLinks.map((item) => [item.blockName, item.referenceField]));
  const expectedReference = `idx_${String(primaryBlockName || "").toLowerCase()}`;
  const linkedRecords = [];
  Object.entries(blocks).forEach(([blockName, block]) => {
    if (blockName === primaryBlockName) return;
    const headers = Array.isArray(block?.headers) ? block.headers : [];
    const configuredReference = configuredByBlock.get(blockName);
    const referenceField = configuredReference && headers.includes(configuredReference)
      ? configuredReference
      : headers.find((field) => String(field || "").toLowerCase() === expectedReference);
    if (!referenceField) return;
    (block.rows || []).forEach((row, rowIndex) => {
      if (String(row?.[referenceField] ?? "") !== primaryIdx) return;
      linkedRecords.push(diagramDefinitionRecord(blockName, block, row, rowIndex));
    });
  });
  return [primaryRecord, ...linkedRecords];
}

function diagramMetricMeasurementRows(snapshot = state.snapshot || {}) {
  const measurements = snapshot?.measurements || {};
  return {
    definitions: snapshot?.definitions?.measurement || measurements.definitions || [],
    scada: measurements.scada || [],
  };
}

function diagramMeasurementIdentityMatches(row, identity) {
  if (!row || !identity) return false;
  if (identity.name) return String(row.name || "") === String(identity.name);
  return normalizeDiagramMeasurementToken(row.dev_type) === normalizeDiagramMeasurementToken(identity.devType)
    && String(row.dev_name || "") === String(identity.devName || "")
    && normalizeDiagramMeasurementToken(row.meas_type) === normalizeDiagramMeasurementToken(identity.measType);
}

function diagramMeasurementFiniteValue(row) {
  if (!row || row.value === null || row.value === undefined || row.value === "") return null;
  const value = Number(row.value);
  return Number.isFinite(value) ? value : null;
}

function diagramMetricMeasurementPair(hover, snapshot = state.snapshot || {}) {
  const rows = diagramMetricMeasurementRows(snapshot);
  let identity = null;
  if (hover?.name) {
    identity = { name: hover.name };
  } else if (hover?.binding) {
    const candidates = diagramMetricMeasurementTypes(
      hover.binding.devType,
      hover.binding.metricType,
    );
    const measType = candidates.find((candidate) => {
      const candidateIdentity = {
        devType: hover.binding.devType,
        devName: hover.binding.devName,
        measType: candidate,
      };
      return [...rows.scada, ...rows.definitions]
        .some((row) => diagramMeasurementIdentityMatches(row, candidateIdentity));
    }) || candidates[0] || hover.binding.metricType;
    identity = {
      devType: hover.binding.devType,
      devName: hover.binding.devName,
      measType,
    };
  }
  const scadaRow = rows.scada.find((row) => diagramMeasurementIdentityMatches(row, identity)) || null;
  const channelRow = scadaRow;
  if (identity?.name && channelRow) {
    identity = {
      name: identity.name,
      devType: channelRow.dev_type,
      devName: channelRow.dev_name,
      measType: channelRow.meas_type,
    };
  }
  const definition = rows.definitions.find((row) => (
    identity?.name
      ? String(row.name || "") === String(identity.name)
      : diagramMeasurementIdentityMatches(row, identity)
  )) || null;
  const scadaValue = diagramMeasurementFiniteValue(scadaRow);
  const weightNumber = Number(definition?.weight ?? channelRow?.weight);
  const validNumber = Number(definition?.valid ?? channelRow?.valid ?? 1);
  const weight = Number.isFinite(weightNumber) ? weightNumber : null;
  const status = diagramMeasurementStatus(
    definition?.status ?? channelRow?.status,
    validNumber,
  );
  const fixedValueNumber = Number(definition?.fixed_value ?? channelRow?.fixed_value);
  return {
    definition,
    scadaRow,
    row: scadaRow || definition,
    name: String(definition?.name || channelRow?.name || identity?.name || ""),
    devType: String(definition?.dev_type || channelRow?.dev_type || identity?.devType || ""),
    devName: String(definition?.dev_name || channelRow?.dev_name || identity?.devName || ""),
    measType: String(definition?.meas_type || channelRow?.meas_type || identity?.measType || ""),
    scadaValue,
    valid: validNumber === 0 ? 0 : 1,
    status,
    fixedValue: Number.isFinite(fixedValueNumber) ? fixedValueNumber : null,
    weight,
    errorSigma: diagramDefinitionSigmaFromWeight(weight),
  };
}

function diagramDefinitionRowMatches(row, rowKey = {}) {
  const name = String(rowKey.name ?? "");
  const idx = String(rowKey.idx ?? "");
  if (name && String(row?.name ?? "") !== name) return false;
  if (idx && String(row?.idx ?? "") !== idx) return false;
  return Boolean(name || idx);
}

function patchDiagramModelDefinitionRecord(snapshot, record) {
  const blockName = String(record?.block_name || "");
  const block = snapshot?.definitions?.model?.[blockName];
  if (!block) return false;
  const row = (block.rows || []).find((item) => diagramDefinitionRowMatches(item, record.row_key || {}));
  if (!row) return false;
  (block.headers || Object.keys(row)).forEach((field) => {
    if (Object.prototype.hasOwnProperty.call(record, field)) row[field] = record[field];
  });
  const parameterRows = snapshot?.device_parameters?.[blockName];
  if (Array.isArray(parameterRows)) {
    const parameterRow = parameterRows.find((item) => diagramDefinitionRowMatches(item, record.row_key || {}));
    if (parameterRow) Object.assign(parameterRow, row);
  }
  return true;
}

function patchDiagramRuntimeControlRecord(snapshot, runtime) {
  const devType = String(runtime?.dev_type || "").trim();
  const devName = String(runtime?.dev_name || "").trim();
  if (!snapshot || !runtime || !devType || !devName) return false;
  const matches = (item) => (
    normalizeDiagramMeasurementToken(item?.dev_type) === normalizeDiagramMeasurementToken(devType)
    && String(item?.dev_name || item?.name || "").trim() === devName
  );
  let changed = false;
  if (Array.isArray(snapshot.devices)) {
    snapshot.devices.forEach((device) => {
      if (!matches(device)) return;
      if (Object.prototype.hasOwnProperty.call(runtime, "run_stat")) device.run_stat = runtime.run_stat;
      if (Object.prototype.hasOwnProperty.call(runtime, "status")) device.status = runtime.status;
      if (Object.prototype.hasOwnProperty.call(runtime, "closed_status_set")) device.closed_status_set = runtime.closed_status_set;
      if (Object.prototype.hasOwnProperty.call(runtime, "closed_status")) device.closed_status = runtime.closed_status;
      if (runtime.set_values && typeof runtime.set_values === "object") {
        device.set_values = {
          ...(device.set_values || {}),
          ...runtime.set_values,
        };
      }
      if (device.raw && typeof device.raw === "object") {
        if (Object.prototype.hasOwnProperty.call(runtime, "run_stat")) device.raw.run_stat = runtime.run_stat;
        if (Object.prototype.hasOwnProperty.call(runtime, "status")) device.raw.status = runtime.status;
        if (Object.prototype.hasOwnProperty.call(runtime, "closed_status_set")) device.raw.closed_status_set = runtime.closed_status_set;
        if (Object.prototype.hasOwnProperty.call(runtime, "closed_status")) device.raw.closed_status = runtime.closed_status;
        if (runtime.set_values && typeof runtime.set_values === "object") {
          device.raw = {
            ...(device.raw || {}),
            ...runtime.set_values,
          };
        }
      }
      changed = true;
    });
  }
  if (Array.isArray(snapshot.device_states)) {
    snapshot.device_states.forEach((deviceState) => {
      if (!matches(deviceState)) return;
      if (Object.prototype.hasOwnProperty.call(runtime, "run_stat")) deviceState.run_stat = runtime.run_stat;
      changed = true;
    });
  }
  if (snapshot.measurements && (Object.prototype.hasOwnProperty.call(runtime, "run_stat") || Object.prototype.hasOwnProperty.call(runtime, "status"))) {
    const measurementUpdates = new Map();
    if (Object.prototype.hasOwnProperty.call(runtime, "run_stat")) {
      measurementUpdates.set(normalizeDiagramMeasurementToken("RUN_STAT"), runtime.run_stat);
    }
    if (Object.prototype.hasOwnProperty.call(runtime, "status")) {
      measurementUpdates.set(normalizeDiagramMeasurementToken("STATUS"), runtime.status);
    }
    ["definitions", "scada"].forEach((channel) => {
      const rows = snapshot.measurements[channel];
      if (!Array.isArray(rows)) return;
      rows.forEach((row) => {
        if (
          normalizeDiagramMeasurementToken(row?.dev_type) !== normalizeDiagramMeasurementToken(devType)
          || String(row?.dev_name || "").trim() !== devName
        ) {
          return;
        }
        const measType = normalizeDiagramMeasurementToken(row?.meas_type || row?.name || "");
        if (!measurementUpdates.has(measType)) return;
        row.value = measurementUpdates.get(measType);
        row.valid = 1;
        changed = true;
      });
    });
  }
  return changed;
}

function patchDiagramMeasurementDefinitionRecord(snapshot, record) {
  const name = String(record?.name || "");
  if (!name) return false;
  let changed = false;
  const definitionLists = [
    snapshot?.definitions?.measurement,
    snapshot?.measurements?.definitions,
  ];
  const visited = new Set();
  definitionLists.forEach((rows) => {
    if (!Array.isArray(rows) || visited.has(rows)) return;
    visited.add(rows);
    const row = rows.find((item) => String(item?.name || "") === name);
    if (!row) return;
    Object.assign(row, record);
    changed = true;
  });
  [snapshot?.measurements?.scada].forEach((rows) => {
    if (!Array.isArray(rows)) return;
    const row = rows.find((item) => String(item?.name || "") === name);
    if (!row) return;
    if (record.valid !== undefined) row.valid = record.valid;
    if (record.weight !== undefined) row.weight = record.weight;
    if (record.status !== undefined) row.status = record.status;
    if (record.fixed_value !== undefined) row.fixed_value = record.fixed_value;
  });
  return changed;
}

function applyDefinitionEditResult(result) {
  if (!result?.memory_updated || !state.snapshot || !result.record) return false;
  invalidateManualDefinitionChanges();
  const record = result.record;
  const patchSnapshot = (snapshot) => {
    if (!snapshot) return false;
    const changed = record.block_name
      ? patchDiagramModelDefinitionRecord(snapshot, record)
      : patchDiagramMeasurementDefinitionRecord(snapshot, record);
    const runtimeChanged = patchDiagramRuntimeControlRecord(snapshot, result.runtime_control);
    if (result.static_meta) {
      snapshot.static_meta = {
        ...(snapshot.static_meta || {}),
        ...result.static_meta,
      };
    }
    return changed || runtimeChanged;
  };
  const changed = patchSnapshot(state.snapshot);
  if (state.localDefinitionSnapshot && state.localDefinitionSnapshot !== state.snapshot) {
    patchSnapshot(state.localDefinitionSnapshot);
  }
  persistStaticSnapshotCache(state.snapshot, currentPageName());
  return changed;
}

function definitionEditResultHasWarning(result) {
  return !result?.persisted
    || result?.change_record_persisted === false
    || Boolean(result?.warning);
}

function diagramDeviceHasSwitchStatus(definitionRecords = [], raw = {}) {
  const modelDefinesStatus = definitionRecords.some((record) => (
    (record?.headers || []).some((field) => (
      ["closed_status", "closed_status_set"].includes(String(field || "").trim().toLowerCase())
    ))
  ));
  return modelDefinesStatus || Object.prototype.hasOwnProperty.call(raw || {}, "closed_status");
}

function diagramDeviceDefinitionEditorRecords(records = []) {
  return records
    .filter((record) => Array.isArray(record?.editableFields) && record.editableFields.length)
    .map((record) => ({
      blockName: record.blockName,
      rowIndex: record.rowIndex,
      rowKey: { ...record.rowKey },
      editableFields: [...record.editableFields],
      original: { ...record.row },
      draft: { ...record.row },
      dirtyFields: new Set(),
    }));
}

function diagramDeviceDefinitionRecordEditor(editor, record) {
  if (editor?.kind !== "device" || !record) return null;
  return (editor.records || []).find((item) => (
    item.blockName === record.blockName
    && Number(item.rowIndex) === Number(record.rowIndex)
  )) || null;
}

function diagramDeviceDefinitionDirtyUpdates(editor) {
  if (editor?.kind !== "device") return [];
  return (editor.records || []).map((record) => {
    const changes = Object.fromEntries(
      [...(record.dirtyFields || [])].map((field) => [field, record.draft[field]]),
    );
    return Object.keys(changes).length ? {
      blockName: record.blockName,
      rowIndex: record.rowIndex,
      rowKey: { ...record.rowKey },
      changes,
    } : null;
  }).filter(Boolean);
}

function diagramDefinitionPendingFieldLabel(field, kind = "device") {
  const name = String(field || "").trim();
  if (kind === "measurement") {
    return ({
      errorSigma: "误差 σ",
      weight: "权重",
      medianDeviation: "中值偏差",
      status: "量测状态",
      fixedValue: "固定值",
    })[name] || name;
  }
  const normalized = name.toLowerCase();
  return ({
    control_type: "控制模式",
    ac_control_type: "交流侧控制模式",
    dc_control_type: "直流侧控制模式",
    i_control_type: "I 侧控制模式",
    j_control_type: "J 侧控制模式",
    run_stat: "运行状态",
    status: "开关状态",
    closed_status_set: "开关状态",
  })[normalized] || name;
}

function diagramDefinitionPendingDeviceValue(field, value) {
  if (typeof diagramDefinitionDisplayValue === "function") {
    return String(diagramDefinitionDisplayValue(field, value));
  }
  const name = String(field || "").trim().toLowerCase();
  const token = String(value ?? "").trim().toUpperCase();
  if (name === "run_stat") return ["1", "TRUE", "ON", "投入"].includes(token) ? "投入" : "退出";
  if (name === "status") return ["1", "TRUE", "ON", "CLOSED", "闭合", "合闸"].includes(token) ? "闭合" : "断开";
  if (name === "closed_status_set") {
    return ["1", "TRUE", "ON", "CLOSED", "闭合", "合闸"].includes(token) ? "闭合" : "打开";
  }
  return diagramTooltipValue(value);
}

function diagramDefinitionPendingValuesEqual(field, before, after, kind = "device") {
  if (kind === "measurement" && field === "status") {
    return diagramMeasurementStatus(before) === diagramMeasurementStatus(after);
  }
  const left = String(before ?? "").trim();
  const right = String(after ?? "").trim();
  if (left === right) return true;
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  return left !== "" && right !== ""
    && Number.isFinite(leftNumber) && Number.isFinite(rightNumber)
    && leftNumber === rightNumber;
}

function diagramDefinitionEditorPendingChanges(editor) {
  if (editor?.kind === "device") {
    return (editor.records || []).flatMap((record) => [...(record.dirtyFields || [])]
      .filter((field) => !diagramDefinitionPendingValuesEqual(
        field,
        record.original?.[field],
        record.draft?.[field],
      ))
      .map((field) => ({
      kind: "device",
      blockName: record.blockName,
      rowIndex: record.rowIndex,
      field,
      label: `${record.blockName || "设备"} · ${diagramDefinitionPendingFieldLabel(field)}`,
      before: diagramDefinitionPendingDeviceValue(field, record.original?.[field]),
      after: diagramDefinitionPendingDeviceValue(field, record.draft?.[field]),
      })));
  }
  if (editor?.kind === "measurement") {
    return [...(editor.dirtyFields || [])]
      .filter((field) => !diagramDefinitionPendingValuesEqual(
        field,
        editor.original?.[field],
        editor.draft?.[field],
        "measurement",
      ))
      .map((field) => ({
      kind: "measurement",
      field,
      label: diagramDefinitionPendingFieldLabel(field, "measurement"),
      before: field === "status"
        ? diagramMeasurementStatusLabel(editor.original?.[field], editor.original?.valid)
        : diagramTooltipValue(editor.original?.[field]),
      after: field === "status"
        ? diagramMeasurementStatusLabel(editor.draft?.[field], editor.draft?.valid)
        : diagramTooltipValue(editor.draft?.[field]),
      }));
  }
  return [];
}

function renderDiagramDefinitionLeavePrompt(interaction) {
  if (!interaction?.definitionLeavePrompt || !interaction?.definitionEditor) return "";
  const changes = diagramDefinitionEditorPendingChanges(interaction.definitionEditor);
  if (!changes.length) return "";
  const disabled = interaction.definitionSaving ? "disabled" : "";
  return `
    <div class="diagram-definition-leave-prompt" data-diagram-definition-leave-prompt>
      <strong>以下修改尚未保存</strong>
      <ul class="diagram-definition-change-list">
        ${changes.map((change) => `
          <li>
            <span>${escapeHtml(change.label)}</span>
            <code>${escapeHtml(change.before)}</code>
            <span aria-hidden="true">→</span>
            <code>${escapeHtml(change.after)}</code>
          </li>`).join("")}
      </ul>
      <p>是否保存这些修改？</p>
      <div class="diagram-definition-leave-actions">
        <button type="button" class="primary" data-diagram-definition-leave-action="save" ${disabled}>保存并关闭</button>
        <button type="button" data-diagram-definition-leave-action="discard" ${disabled}>不保存并关闭</button>
        <button type="button" data-diagram-definition-leave-action="continue" ${disabled}>继续编辑</button>
      </div>
    </div>`;
}

