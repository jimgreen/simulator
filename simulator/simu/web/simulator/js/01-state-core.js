// 教员端前端模块：全局配置、状态仓库、虚拟表格与仿真启动交互。

const directSimulatorServiceMode = document.documentElement.dataset.simulatorUiMode === "direct";
const directSimulatorServiceApiBase = (
  new URLSearchParams(location.search).get("service")
  || window.POLAR_SIM_SERVICE_URL
  || location.origin
).replace(/\/$/, "");
const controlPlaneApiBase = (window.POLAR_SIM_API_URL || localStorage.getItem("polarSimApiUrl") || location.origin).replace(/\/$/, "");
const OVERVIEW_BOTTOM_HEIGHT_KEY = "polarOverviewBottomHeight";
const OVERVIEW_BOTTOM_DEFAULT_HEIGHT = 156;
const OVERVIEW_BOTTOM_MIN_HEIGHT = 96;
const OVERVIEW_BOTTOM_MAX_HEIGHT = 640;
const OVERVIEW_BOTTOM_COLUMN_RATIO_KEY = "polarSimulatorOverviewBottomColumnRatio";
const OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO = 50;
const OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX = 260;
const VERTICAL_SPLIT_STORAGE_KEY = "polarSimulatorVerticalSplitRatios";
const VERTICAL_SPLIT_DEFAULTS = {
  "simulator-curves": 60,
  "simulator-runtime": 52,
  "simulator-measurements": 52,
};
const VERTICAL_SPLIT_DEFAULT_RATIO = 55;
const VERTICAL_SPLIT_MIN_TOP_PX = 120;
const VERTICAL_SPLIT_MIN_BOTTOM_PX = 120;
const STATIC_CACHE_STORAGE_KEY = "polarSimulatorStaticCacheV2";
const STATIC_CACHE_MODEL_LIMIT = 4;
const CURVE_TREE_COLLAPSE_KEY = "polarSimulatorCurveTreeCollapsedGroups";
const RUNTIME_LOG_COLUMN_WIDTHS_KEY = "polarSimulatorRuntimeLogColumnWidths";
const RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS = Object.freeze([104, 104, 112, 190, 104, 640]);
const RUNTIME_LOG_COLUMN_MIN_WIDTHS = Object.freeze([82, 82, 78, 110, 78, 180]);
const HIDDEN_REFRESH_INTERVAL_MS = 10000;
const WEB_RUNTIME_FALLBACKS = {
  frontend_refresh_seconds: 1,
  frontend_request_timeout_seconds: 30,
  runtime_log_page_size: 20,
  runtime_log_cache_limit: 300,
  curve_request_timeout_seconds: 8,
  runtime_log_delta_batch_size: 200,
  runtime_log_history_batch_size: 120,
  diagram_flow_electric_threshold_kw: 0.1,
  diagram_flow_hydrogen_threshold_nm3_h: 0.1,
};
const WEB_RUNTIME_CURRENT_IDS = {
  frontend_refresh_seconds: "currentWebRuntimeFrontendRefresh",
  frontend_request_timeout_seconds: "currentWebRuntimeFrontendRequestTimeout",
  runtime_log_page_size: "currentWebRuntimeLogPageSize",
  runtime_log_cache_limit: "currentWebRuntimeLogCacheLimit",
  curve_request_timeout_seconds: "currentWebRuntimeCurveRequestTimeout",
  runtime_log_delta_batch_size: "currentWebRuntimeLogDeltaBatchSize",
  runtime_log_history_batch_size: "currentWebRuntimeLogHistoryBatchSize",
  diagram_flow_electric_threshold_kw: "currentWebRuntimeDiagramElectricFlowThreshold",
  diagram_flow_hydrogen_threshold_nm3_h: "currentWebRuntimeDiagramHydrogenFlowThreshold",
};
const state = {
  snapshot: null,
  activePage: "",
  pageSections: {},
  pageMain: null,
  models: [],
  modelsLoaded: false,
  serviceSuggestion: { host: "127.0.0.1", port: 8711 },
  modelServiceOperationActive: false,
  clockControlOperationActive: false,
  serviceCatalogLastLoadedAt: 0,
  activeModelId: localStorage.getItem("polarSimulatorModelId") || "",
  manualDefinitionChanges: [],
  manualDefinitionChangesRevision: 0,
  manualDefinitionChangesLoadedModelId: "",
  manualDefinitionChangesLoading: false,
  manualDefinitionChangesResetting: false,
  manualDefinitionChangesRetrying: false,
  manualDefinitionChangesError: "",
  manualDefinitionChangesMessage: "",
  manualDefinitionChangesMessageWarning: false,
  manualDefinitionChangeSelection: new Set(),
  refreshRequestActive: false,
  deviceFaults: [],
  measurementFaults: [],
  modes: [],
  weatherPoints: [],
  loadPoints: [],
  loadPointsByName: {},
  curveSummary: null,
  curveSummaryLoadedModelId: "",
  curveSummaryRequest: null,
  curveSummaryRequestModelId: "",
  curveSummaryAbortController: null,
  curveSeriesRequestKey: "",
  curveSeriesRequest: null,
  curveSeriesAbortController: null,
  curveEditorLoadRequest: null,
  curveEditorLoadRequestKey: "",
  curveLoadError: "",
  curveDataRevision: 0,
  lastCurveEditorRenderKey: "",
  lastCurveEditorTableKey: "",
  curveDirtyKeys: new Set(),
  curveDirtyKeysByMode: {},
  curvePersistedMode: "",
  pendingCurveModeSwitch: "",
  curveModeSwitchSaving: false,
  typicalCurveTargetKey: "",
  curveSeries: {},
  curveSeriesByMode: {},
  curveMode: localStorage.getItem("polarSimulatorCurveMode") || "year",
  curvesLoadedModelId: "",
  activeCurveKey: "wind_speed_mps",
  selectedCurveKeys: ["wind_speed_mps"],
  hiddenCurveKeys: [],
  curveEditKey: "",
  curveTreeSearch: "",
  curveTreeGroupCollapsed: readStoredCurveTreeCollapsedGroups(),
  isCurveDragging: false,
  isCurveTreePointerDown: false,
  isCurveTreeMultiSelecting: false,
  curveTreeDragStartKeys: [],
  curveTreeDragKeys: [],
  curveTreeDragStartButton: null,
  suppressNextCurveTreeClick: false,
  curveCursor: { visible: false, x: 0, y: 0, index: 0 },
  curveLegendHitBoxes: [],
  settingsLoaded: false,
  activeFaultTab: "devices",
  faultDeviceFilter: { dev_type: "all", dev_name: "" },
  faultMeasurementFilter: { dev_type: "all", dev_name: "", key: "" },
  modelDeviceFilter: { dev_type: "all", dev_name: "" },
  activeModelParamTab: "",
  runtimeDeviceFilter: { dev_type: "all", dev_name: "" },
  activeRuntimeCommandTab: "remote_control",
  selectedRuntimeCommandKey: "",
  selectedRuntimeCommandLabel: "",
  chartSeriesHidden: {},
  chartSeriesSelected: {},
  chartCursors: {},
  chartSeriesHitData: {},
  chartPlotInfo: {},
  chartPeriodOffsets: { runtimeTrace: 0, measurementTrace: 0 },
  runtimeTraceHistory: [],
  runtimeTraceWindowMinutes: 60,
  lastRuntimeTraceKey: "",
  runtimeCommandKeywordFilter: "",
  runtimeCommandTypeFilter: "all",
  runtimeCommandOriginFilter: "all",
  runtimeCommandOnlyActive: false,
  runtimeCommandDeleteSending: new Set(),
  measurementCompareFilter: { dev_type: "all", dev_name: "" },
  measurementCompareKeywordFilter: "",
  measurementCompareTypeFilter: "all",
  activeMeasurementCompareTab: "telemetry",
  selectedMeasurementKey: "",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
  lastMeasurementTraceKey: "",
  measurementHistoryLoaded: {},
  measurementHistoryRequests: {},
  measurementHistoryGeneration: 0,
  traceRunId: null,
  traceStepCount: null,
  selectedManagementModelId: "",
  updateTargetModelId: "",
  cloneSourceModelId: "",
  modeFilter: { dev_type: "all", dev_name: "" },
  collapsedDeviceTreeGroups: {},
  deviceTreeSearch: {},
  deviceTreeSelectionAnchors: {},
  runtimeLogs: [],
  runtimeLogColumnWidths: readStoredRuntimeLogColumnWidths(),
  runtimeLogTypeFilter: "all",
  runtimeLogPage: 1,
  runtimeLogPageSize: 20,
  runtimeLogSeq: 0,
  runtimeLogSelectedSeq: 0,
  runtimeLogBackendSeq: 0,
  runtimeLogRequestActive: false,
  runtimeLogHistoryRequestActive: false,
  runtimeLogTotal: 0,
  lastRuntimeLogKey: "",
  measurementDeltaSeq: 0,
  measurementDeltaRequestActive: false,
  embeddedMeasurementDeltaReceived: false,
  embeddedRuntimeLogDeltaReceived: false,
  measurementArrayWarning: "",
  systemParameters: {
    clock_speed: 1,
    compute_interval_seconds: 1,
    storage_initial_soc: 0.5,
    remote_adjustment_response_ratio: 0.7,
  },
  systemParametersDirty: false,
  systemParametersSaving: false,
  webRuntimeSettings: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeDefaults: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeConstraints: {},
  webRuntimeDraft: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeUpdatedAt: "",
  webRuntimeLoadedModelId: "",
  webRuntimeLoading: false,
  webRuntimeSaving: false,
  webRuntimeDirty: false,
  webRuntimeError: "",
  frontendRefreshTimerId: null,
  deviceRuntimeSignature: "",
  deviceRuntimeNeedsFullRefresh: false,
  deviceRuntimeWarning: "",
  frontendDiagnostics: {
    requestCount: 0,
    responseBytes: 0,
    requestDurationMs: 0,
    snapshotRequestCount: 0,
    snapshotResponseBytes: 0,
    snapshotRenderCount: 0,
  },
  overviewBottomHeight: overviewInitialBottomHeight(),
  overviewBottomSplitDrag: null,
  overviewBottomColumnRatio: overviewInitialBottomColumnRatio(),
  overviewBottomColumnSplitDrag: null,
  verticalSplitRatios: initialVerticalSplitRatios(),
  verticalSplitDrag: null,
  virtualTables: {},
  virtualTableScrollRaf: {},
};
window.__polarFrontendDiagnostics = state.frontendDiagnostics;

const $ = (id) => document.getElementById(id);
const deviceTreeRenderKeys = new WeakMap();
const MODE_OPTIONS = ["PQ", "PV", "PH", "V"];

function activeRuntimeSetting(name) {
  const value = Number(state.webRuntimeSettings?.[name]);
  if (Number.isFinite(value)) return value;
  const configuredDefault = Number(state.webRuntimeDefaults?.[name]);
  if (Number.isFinite(configuredDefault)) return configuredDefault;
  return Number(WEB_RUNTIME_FALLBACKS[name]) || 0;
}

function frontendRefreshIntervalMs() {
  return Math.max(200, activeRuntimeSetting("frontend_refresh_seconds") * 1000);
}

function frontendRequestTimeoutMs() {
  return Math.max(1000, activeRuntimeSetting("frontend_request_timeout_seconds") * 1000);
}

function curveRequestTimeoutMs() {
  return Math.max(1000, activeRuntimeSetting("curve_request_timeout_seconds") * 1000);
}

function pageIsHidden() {
  return document.visibilityState === "hidden";
}

function refreshSchedulerIntervalMs() {
  if (pageIsHidden()) return HIDDEN_REFRESH_INTERVAL_MS;
  const baseMs = frontendRefreshIntervalMs();
  const failures = Math.max(0, Number(state.refreshConsecutiveFailures || 0));
  if (failures <= 0) return baseMs;
  // 连续断连时阶梯退避（1x -> 2x -> 4x，上限 10s），降低无效重试风暴
  return Math.min(10000, baseMs * Math.pow(2, Math.min(3, failures)));
}

function scheduleNextRefresh(delayMs = refreshSchedulerIntervalMs()) {
  if (state.frontendRefreshTimerId) {
    clearTimeout(state.frontendRefreshTimerId);
    state.frontendRefreshTimerId = null;
  }
  // 标签页后台不可见时暂停前端轮询，切回前台由 visibilitychange 立即刷新。
  if (pageIsHidden()) return;
  state.frontendRefreshTimerId = setTimeout(runRefreshScheduler, Math.max(0, delayMs));
}

function restartRefreshScheduler() {
  state.refreshConsecutiveFailures = 0;
  scheduleNextRefresh();
}

async function runRefreshScheduler() {
  state.frontendRefreshTimerId = null;
  if (pageIsHidden()) return;
  const startedAtMs = Date.now();
  try {
    await refreshServiceCatalog();
    if (activeModelServiceRunning()) await refresh();
  } finally {
    if (!pageIsHidden()) {
      const elapsedMs = Date.now() - startedAtMs;
      scheduleNextRefresh(Math.max(0, refreshSchedulerIntervalMs() - elapsedMs));
    }
  }
}

function overviewInitialBottomHeight() {
  const storedHeight = Number(localStorage.getItem(OVERVIEW_BOTTOM_HEIGHT_KEY));
  if (!Number.isFinite(storedHeight) || storedHeight <= 0) return OVERVIEW_BOTTOM_DEFAULT_HEIGHT;
  return Math.max(OVERVIEW_BOTTOM_MIN_HEIGHT, Math.min(OVERVIEW_BOTTOM_MAX_HEIGHT, storedHeight));
}

function overviewInitialBottomColumnRatio() {
  const storedRatio = Number(localStorage.getItem(OVERVIEW_BOTTOM_COLUMN_RATIO_KEY));
  if (!Number.isFinite(storedRatio) || storedRatio <= 0) return OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO;
  return Math.max(10, Math.min(90, storedRatio));
}

const CURVE_MODES = {
  hour: { key: "hour", label: "时曲线", pointCount: 3600, stepMinutes: 1 / 60, durationMinutes: 60, simulationLabel: "时仿真", defaultClockSpeed: 1, tableTitle: "时曲线数据表", tableSummary: "1秒间隔 · 可编辑" },
  day: { key: "day", label: "日曲线", pointCount: 1440, stepMinutes: 1, durationMinutes: 24 * 60, simulationLabel: "日仿真", defaultClockSpeed: 60, tableTitle: "日曲线数据表", tableSummary: "1分钟间隔 · 可编辑" },
  week: { key: "week", label: "周曲线", pointCount: 10080, stepMinutes: 1, durationMinutes: 7 * 24 * 60, simulationLabel: "周仿真", defaultClockSpeed: 60, tableTitle: "周曲线数据表", tableSummary: "1分钟间隔 · 可编辑" },
  month: { key: "month", label: "月曲线", pointCount: 720, stepMinutes: 60, durationMinutes: 30 * 24 * 60, simulationLabel: "月仿真", defaultClockSpeed: 3600, tableTitle: "月曲线数据表", tableSummary: "1小时间隔 · 可编辑" },
  year: { key: "year", label: "年曲线", pointCount: 8760, stepMinutes: 60, durationMinutes: 365 * 24 * 60, simulationLabel: "年仿真", defaultClockSpeed: 3600, tableTitle: "年曲线数据表", tableSummary: "1小时间隔 · 可编辑" },
};
const CURVE_META = [
  { key: "wind_speed_mps", label: "风速", color: "#008c8c", min: 0, max: 50, digits: 2, unit: "m/s" },
  { key: "solar_irradiance_w_m2", label: "太阳辐照", color: "#b87500", min: 0, max: 1100, digits: 1, unit: "W/m2" },
  { key: "air_temp_c", label: "气温", color: "#2b6b7f", min: -50, max: 10, digits: 2, unit: "℃" },
  { key: "load_kw", label: "负荷", color: "#c93a3a", min: 0, max: 500, digits: 2, unit: "kW" },
];
const ENV_CURVE_KEYS = ["wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c"];
const LOAD_CURVE_META = { label: "负荷", color: "#c93a3a", min: 0, max: 500, digits: 2, unit: "kW" };
const LOAD_CURVE_COLORS = ["#c93a3a", "#8a4fbf", "#23854a", "#d16300", "#4369b2", "#0a8b8b"];
const LOAD_CURVE_FAMILIES = [
  { key: "electric", label: "电负荷曲线", blocks: ["ACLoad", "DCLoad"], unit: "kW", setType: "p_set", valueKey: "p_kw" },
  { key: "hydrogen", label: "氢负荷曲线", blocks: ["HydroLoad"], unit: "Nm³/h", setType: "flow_set", valueKey: "flow_set" },
  { key: "heat", label: "热负荷曲线", blocks: ["HeatLoad"], unit: "kW", setType: "heat_power", valueKey: "heat_power" },
];
const SOURCE_CURVE_FAMILIES = [
  { key: "electric", label: "电源曲线" },
  { key: "hydrogen", label: "氢源曲线" },
  { key: "heat", label: "热源曲线" },
];
const SOURCE_CURVE_COLORS = ["#126f8a", "#8a4fbf", "#23854a", "#d16300", "#4369b2", "#0a8b8b"];
const CURVE_PLOT = { left: 58, right: 24, top: 46, bottom: 34 };
const VIRTUAL_TABLE_ROW_HEIGHT = 34;
const VIRTUAL_TABLE_MIN_ROWS = 220;
const VIRTUAL_TABLE_BUFFER_ROWS = 12;
const WEATHER_MEASUREMENT_LABELS = {
  WIND_SPEED: { label: "风速", unit: "m/s", order: 0 },
  SOLAR_IRRADIANCE: { label: "太阳辐照", unit: "W/m2", order: 1 },
  AIR_TEMP: { label: "气温", unit: "℃", order: 2 },
  HUMIDITY: { label: "湿度", unit: "%", order: 3 },
  AIR_PRESSURE: { label: "气压", unit: "hPa", order: 4 },
};
const SIGNAL_MEASUREMENT_LABELS = {
  RUN_STAT: { label: "运行状态", order: 0 },
  STATUS: { label: "开关状态", order: 1 },
};
const DIAGRAM_MEASUREMENT_FIELD_LABELS = Object.freeze({
  STATUS: "closed_status",
  P_GEN: "p",
  Q_GEN: "q",
  V_GEN: "u",
  I_GEN: "i",
  P_LOAD: "p",
  Q_LOAD: "q",
  V_LOAD: "u",
  I_LOAD: "i",
});
let pendingImportDefinitionFile = null;
let importModelCreationComplete = false;
let pendingNewModelFile = null;
let pendingNewModelSvgFile = null;
let newModelCreationActive = false;
let newModelCreationComplete = false;
let pendingUpdateModelFile = null;
let pendingUpdateModelSvgFile = null;
let updateModelSaveComplete = false;

function chartHiddenSet(chartKey) {
  const hidden = state.chartSeriesHidden?.[chartKey] || [];
  return new Set(hidden);
}

function isChartSeriesHidden(chartKey, seriesKey) {
  return chartHiddenSet(chartKey).has(seriesKey);
}

function visibleChartSeries(chartKey, seriesDefs) {
  return (seriesDefs || []).filter((series) => !isChartSeriesHidden(chartKey, series.key));
}

function selectedChartSeriesKey(chartKey, fallback = "") {
  const selected = state.chartSeriesSelected?.[chartKey];
  if (selected) return selected;
  return fallback || "";
}

function setChartSeriesSelected(chartKey, seriesKey, drawFn) {
  if (!chartKey || !seriesKey) return;
  state.chartSeriesSelected = { ...(state.chartSeriesSelected || {}), [chartKey]: seriesKey };
  syncChartLegendButtons(chartKey);
  if (typeof drawFn === "function") drawFn();
}

function toggleChartSeriesVisibility(chartKey, seriesKey, drawFn) {
  if (!chartKey || !seriesKey) return;
  const hidden = chartHiddenSet(chartKey);
  if (hidden.has(seriesKey)) hidden.delete(seriesKey);
  else hidden.add(seriesKey);
  state.chartSeriesHidden = { ...(state.chartSeriesHidden || {}), [chartKey]: Array.from(hidden) };
  state.chartSeriesSelected = { ...(state.chartSeriesSelected || {}), [chartKey]: seriesKey };
  syncChartLegendButtons(chartKey);
  if (typeof drawFn === "function") drawFn();
}

function syncChartLegendButtons(chartKey) {
  document.querySelectorAll(`[data-chart-toggle="${chartKey}"]`).forEach((button) => {
    const seriesKey = button.dataset.chartSeries || "";
    button.classList.toggle("is-hidden", isChartSeriesHidden(chartKey, seriesKey));
    button.classList.toggle("is-selected", selectedChartSeriesKey(chartKey) === seriesKey);
    button.setAttribute("aria-pressed", isChartSeriesHidden(chartKey, seriesKey) ? "false" : "true");
  });
}

function debounce(fn, delayMs = 150) {
  let timerId = null;
  return function debounced(...args) {
    if (timerId !== null) clearTimeout(timerId);
    timerId = setTimeout(() => {
      timerId = null;
      fn.apply(this, args);
    }, delayMs);
  };
}

function canvasDevicePixelRatio() {
  return Math.min(2, Math.max(1, Number(window.devicePixelRatio) || 1));
}

function canvasLogicalSize(canvas, fallbackWidth = 900, fallbackHeight = 260) {
  if (!canvas) return { width: fallbackWidth, height: fallbackHeight };
  const cssW = Number(canvas.dataset.cssWidth);
  const cssH = Number(canvas.dataset.cssHeight);
  if (Number.isFinite(cssW) && cssW > 0 && Number.isFinite(cssH) && cssH > 0) {
    return { width: cssW, height: cssH };
  }
  return {
    width: canvas.width || fallbackWidth,
    height: canvas.height || fallbackHeight,
  };
}

function prepareCanvas2D(canvas, fallbackWidth = 900, fallbackHeight = 260) {
  const ctx = canvas.getContext("2d");
  const dpr = Number(canvas.dataset.dpr) || canvasDevicePixelRatio();
  const { width, height } = canvasLogicalSize(canvas, fallbackWidth, fallbackHeight);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width, height, dpr };
}

function canvasPointerPosition(canvas, event) {
  const rect = canvas.getBoundingClientRect();
  const { width, height } = canvasLogicalSize(canvas);
  return {
    x: (event.clientX - rect.left) * (width / Math.max(1, rect.width)),
    y: (event.clientY - rect.top) * (height / Math.max(1, rect.height)),
  };
}

function canvasRenderedSize(canvas, fallbackWidth = 900, fallbackHeight = 260) {
  const rect = canvas.getBoundingClientRect();
  return {
    width: Math.max(1, Math.round(rect.width || canvas.clientWidth || fallbackWidth)),
    height: Math.max(1, Math.round(rect.height || canvas.clientHeight || fallbackHeight)),
  };
}

function resizeCanvasToRenderedSize(canvas, fallbackWidth = 900, fallbackHeight = 260) {
  if (!canvas) return false;
  const { width, height } = canvasRenderedSize(canvas, fallbackWidth, fallbackHeight);
  const dpr = canvasDevicePixelRatio();
  const pixelWidth = Math.max(1, Math.round(width * dpr));
  const pixelHeight = Math.max(1, Math.round(height * dpr));
  const changed = canvas.width !== pixelWidth
    || canvas.height !== pixelHeight
    || Number(canvas.dataset.cssWidth) !== width
    || Number(canvas.dataset.cssHeight) !== height
    || Number(canvas.dataset.dpr) !== dpr;
  if (!changed) return false;
  canvas.width = pixelWidth;
  canvas.height = pixelHeight;
  canvas.dataset.cssWidth = String(width);
  canvas.dataset.cssHeight = String(height);
  canvas.dataset.dpr = String(dpr);
  return true;
}

function sampleCurvePointsForCanvas(values, canvasWidth, density = 1.5) {
  const total = Array.isArray(values) ? values.length : 0;
  const target = Math.max(16, Math.floor((Number(canvasWidth) || 900) * density));
  if (total <= target) return values.map((value, index) => ({ index, value }));
  const bucketSize = total / target;
  const sampled = new Map();
  for (let bucket = 0; bucket < target; bucket += 1) {
    const start = Math.floor(bucket * bucketSize);
    const end = Math.min(total, Math.max(start + 1, Math.ceil((bucket + 1) * bucketSize)));
    let minIndex = start;
    let maxIndex = start;
    for (let index = start; index < end; index += 1) {
      if (Number(values[index]) < Number(values[minIndex])) minIndex = index;
      if (Number(values[index]) > Number(values[maxIndex])) maxIndex = index;
    }
    [start, minIndex, maxIndex, end - 1].forEach((index) => sampled.set(index, values[index]));
  }
  sampled.set(total - 1, values[total - 1]);
  return Array.from(sampled.entries())
    .sort((left, right) => left[0] - right[0])
    .map(([index, value]) => ({ index, value }));
}

function compactTraceHistory(history) {
  return Array.isArray(history) ? history : [];
}

function virtualTableWindow(key, rows, options = {}) {
  const sourceRows = Array.isArray(rows) ? rows : [];
  const total = sourceRows.length;
  const rowHeight = Math.max(1, Number(options.rowHeight) || VIRTUAL_TABLE_ROW_HEIGHT);
  const minRows = Math.max(1, Number(options.minRows) || VIRTUAL_TABLE_MIN_ROWS);
  const bufferRows = Math.max(0, Number(options.bufferRows) || VIRTUAL_TABLE_BUFFER_ROWS);
  if (total <= minRows) {
    return {
      enabled: false,
      rows: sourceRows,
      start: 0,
      end: total,
      beforeHeight: 0,
      afterHeight: 0,
      rowHeight,
      total,
    };
  }
  const tableState = state.virtualTables?.[key] || {};
  const viewportHeight = Math.max(180, Number(tableState.viewportHeight) || 420);
  const maxScrollTop = Math.max(0, total * rowHeight - viewportHeight);
  const scrollTop = clamp(Number(tableState.scrollTop) || 0, 0, maxScrollTop);
  const visibleRows = Math.ceil(viewportHeight / rowHeight) + bufferRows * 2;
  const maxStart = Math.max(0, total - visibleRows);
  const start = clamp(Math.floor(scrollTop / rowHeight) - bufferRows, 0, maxStart);
  const end = Math.min(total, start + visibleRows);
  state.virtualTables[key] = { ...tableState, scrollTop, viewportHeight };
  return {
    enabled: true,
    rows: sourceRows.slice(start, end),
    start,
    end,
    beforeHeight: start * rowHeight,
    afterHeight: Math.max(0, total - end) * rowHeight,
    rowHeight,
    total,
    scrollTop,
    viewportHeight,
  };
}

function renderVirtualSpacerRow(height, colSpan) {
  if (!height || height <= 0) return "";
  return `<tr class="virtual-table-spacer" aria-hidden="true"><td colspan="${Number(colSpan) || 1}" style="height:${Math.round(height)}px"></td></tr>`;
}

function restoreVirtualTableScroll(container, key) {
  const selector = `[data-virtual-table="${key}"]`;
  const scroller = container?.matches?.(selector) ? container : container?.querySelector?.(selector);
  if (!scroller) return;
  const tableState = state.virtualTables?.[key] || {};
  const scrollTop = Number(tableState.scrollTop) || 0;
  if (Math.abs(scroller.scrollTop - scrollTop) > 1) scroller.scrollTop = scrollTop;
  state.virtualTables[key] = {
    ...tableState,
    scrollTop: scroller.scrollTop,
    viewportHeight: scroller.clientHeight || tableState.viewportHeight || 420,
  };
}

function scheduleVirtualTableRender(key) {
  if (!key) return;
  state.virtualTableScrollRaf = state.virtualTableScrollRaf || {};
  if (state.virtualTableScrollRaf[key]) return;
  state.virtualTableScrollRaf[key] = requestAnimationFrame(() => {
    delete state.virtualTableScrollRaf[key];
    if (key === "measurementCompare" && currentPageName() === "measurements") {
      renderMeasurementCompareTable();
    }
    if (key.startsWith("runtimeCommand") && currentPageName() === "runtime") {
      renderRuntimeDeviceTable();
    }
    if (key.startsWith("curveEditor:") && currentPageName() === "curves") {
      renderHourlyTable(true);
    }
  });
}

function handleVirtualTableScroll(event) {
  const scroller = event.target instanceof Element ? event.target.closest("[data-virtual-table]") : null;
  if (!scroller || scroller !== event.target) return;
  const key = scroller.dataset.virtualTable || "";
  const tableState = state.virtualTables?.[key] || {};
  state.virtualTables[key] = {
    ...tableState,
    scrollTop: scroller.scrollTop,
    viewportHeight: scroller.clientHeight || tableState.viewportHeight || 420,
  };
  scheduleVirtualTableRender(key);
}

function setChartCursorFromEvent(chartKey, canvas, plot, event, drawFn) {
  if (!canvas || !plot) return;
  const pos = canvasPointerPosition(canvas, event);
  const { width, height } = canvasLogicalSize(canvas);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  const visible = pos.x >= left && pos.x <= right && pos.y >= top && pos.y <= bottom;
  state.chartCursors = {
    ...(state.chartCursors || {}),
    [chartKey]: {
      visible,
      x: clamp(pos.x, left, right),
      y: clamp(pos.y, top, bottom),
    },
  };
  if (typeof drawFn === "function") drawFn();
}

function hideChartCursor(chartKey, drawFn) {
  const cursor = state.chartCursors?.[chartKey];
  if (!cursor?.visible) return;
  state.chartCursors = {
    ...(state.chartCursors || {}),
    [chartKey]: { ...cursor, visible: false },
  };
  if (typeof drawFn === "function") drawFn();
}

function chartSeriesAtPointer(chartKey, canvas, event, threshold = 10) {
  const seriesData = state.chartSeriesHitData?.[chartKey] || [];
  if (!seriesData.length) return "";
  const pos = canvasPointerPosition(canvas, event);
  let best = { key: "", distance: Number.POSITIVE_INFINITY };
  seriesData.forEach((series) => {
    (series.points || []).forEach((point) => {
      const distance = Math.hypot(point.x - pos.x, point.y - pos.y);
      if (distance < best.distance) best = { key: series.key, distance };
    });
  });
  return best.distance <= threshold ? best.key : "";
}

function selectChartSeriesAtPointer(chartKey, canvas, event, drawFn) {
  const seriesKey = chartSeriesAtPointer(chartKey, canvas, event);
  if (!seriesKey) return false;
  setChartSeriesSelected(chartKey, seriesKey, drawFn);
  return true;
}

function nearestChartPoint(points, x) {
  let best = null;
  let distance = Number.POSITIVE_INFINITY;
  (points || []).forEach((point) => {
    const nextDistance = Math.abs(point.x - x);
    if (nextDistance < distance) {
      best = point;
      distance = nextDistance;
    }
  });
  return best;
}

function chartPointAtCursorAnchor(points, anchorPoint) {
  const source = points || [];
  const anchorTime = String(anchorPoint?.time || anchorPoint?.sim_time || "").trim();
  if (anchorTime && anchorTime !== "--") {
    const matchingTime = source.filter((point) => (
      String(point?.time || point?.sim_time || "").trim() === anchorTime
    ));
    if (matchingTime.length) return matchingTime[matchingTime.length - 1];
  }
  const anchorMinute = Number(anchorPoint?.minute);
  if (Number.isFinite(anchorMinute)) {
    const matchingMinute = source.filter((point) => {
      const minute = Number(point?.minute);
      return Number.isFinite(minute) && Math.abs(minute - anchorMinute) <= 1e-9;
    });
    if (matchingMinute.length) return matchingMinute[matchingMinute.length - 1];
    return null;
  }
  return nearestChartPoint(source, Number(anchorPoint?.x));
}

function chartCursorSnapshot(seriesData, selectedKey, cursorX) {
  const source = seriesData || [];
  const anchorSeries = source.find((series) => (
    series.key === selectedKey && Array.isArray(series.points) && series.points.length
  )) || source.find((series) => Array.isArray(series.points) && series.points.length);
  if (!anchorSeries) return null;
  const anchorPoint = nearestChartPoint(anchorSeries.points, cursorX);
  if (!anchorPoint) return null;
  const samples = source.map((series) => ({
    series,
    point: chartPointAtCursorAnchor(series.points, anchorPoint),
  })).filter((item) => item.point);
  return samples.length ? { anchorPoint, samples } : null;
}

function drawChartCursor(ctx, chartKey, canvas, plot, seriesData, options = {}) {
  const cursor = state.chartCursors?.[chartKey];
  const visibleSeries = (seriesData || []).filter((series) => !isChartSeriesHidden(chartKey, series.key));
  if (!cursor?.visible || !visibleSeries.length) return;
  const { width, height } = canvasLogicalSize(canvas);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  const selectedKey = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const snapshot = chartCursorSnapshot(visibleSeries, selectedKey, clamp(cursor.x, left, right));
  if (!snapshot) return;
  const { anchorPoint: mainPoint, samples } = snapshot;
  const x = clamp(mainPoint.x, left, right);
  const y = clamp(mainPoint.y, top, bottom);
  const timeLabel = options.timeLabel ? options.timeLabel(mainPoint) : (mainPoint.time || "");

  ctx.save();
  ctx.strokeStyle = "rgba(29, 57, 66, 0.58)";
  ctx.lineWidth = options.ratio || 1;
  ctx.setLineDash([5 * (options.ratio || 1), 4 * (options.ratio || 1)]);
  ctx.beginPath();
  ctx.moveTo(x, top);
  ctx.lineTo(x, bottom);
  ctx.moveTo(left, y);
  ctx.lineTo(right, y);
  ctx.stroke();
  ctx.setLineDash([]);

  const palette = chartThemePalette();
  samples.forEach(({ series, point }) => {
    ctx.fillStyle = palette.markerFill;
    ctx.strokeStyle = series.color;
    ctx.lineWidth = 2 * (options.ratio || 1);
    ctx.beginPath();
    ctx.arc(point.x, point.y, 4.5 * (options.ratio || 1), 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  const ratio = options.ratio || 1;
  ctx.font = `${12 * ratio}px Microsoft YaHei, Arial`;
  const valueFormatter = options.valueFormatter || ((value) => formatMeasurementValue(value));
  const lines = [
    timeLabel ? `时刻: ${timeLabel}` : "",
    ...samples.slice(0, 6).map(({ series, point }) => `${series.label}: ${valueFormatter(point.value)}${series.unit ? ` ${series.unit}` : ""}`),
    samples.length > 6 ? `另有 ${samples.length - 6} 条曲线` : "",
  ].filter(Boolean);
  const tooltipWidth = Math.max(150 * ratio, ...lines.map((line) => ctx.measureText(line).width + 24 * ratio));
  const tooltipHeight = 14 * ratio + lines.length * 18 * ratio;
  let tooltipX = x + 14 * ratio;
  let tooltipY = y + 14 * ratio;
  if (tooltipX + tooltipWidth > right - 6 * ratio) tooltipX = x - tooltipWidth - 14 * ratio;
  if (tooltipY + tooltipHeight > bottom - 6 * ratio) tooltipY = y - tooltipHeight - 14 * ratio;
  tooltipX = clamp(tooltipX, left + 6 * ratio, right - tooltipWidth - 6 * ratio);
  tooltipY = clamp(tooltipY, top + 6 * ratio, bottom - tooltipHeight - 6 * ratio);
  ctx.fillStyle = palette.tooltipBg;
  ctx.strokeStyle = palette.tooltipBorder;
  ctx.beginPath();
  ctx.roundRect(tooltipX, tooltipY, tooltipWidth, tooltipHeight, 8 * ratio);
  ctx.fill();
  ctx.stroke();
  lines.forEach((line, lineIndex) => {
    ctx.fillStyle = lineIndex === 0 ? palette.tooltipTitle : palette.tooltipText;
    ctx.fillText(line, tooltipX + 10 * ratio, tooltipY + 18 * ratio + lineIndex * 18 * ratio);
  });
  ctx.restore();
}

function initTraceChartInteractions(chartKey, canvasId, drawFn) {
  const canvas = $(canvasId);
  if (!canvas) return;
  const handleMove = (event) => {
    setChartCursorFromEvent(chartKey, canvas, state.chartPlotInfo?.[chartKey], event, drawFn);
  };
  canvas.addEventListener("pointermove", handleMove);
  canvas.addEventListener("mousemove", handleMove);
  canvas.addEventListener("pointerleave", () => hideChartCursor(chartKey, drawFn));
  canvas.addEventListener("mouseleave", () => hideChartCursor(chartKey, drawFn));
  canvas.addEventListener("click", (event) => {
    if (selectChartSeriesAtPointer(chartKey, canvas, event, drawFn)) event.preventDefault();
  });
}

function isDeviceTreeGroupCollapsed(scope, groupKey) {
  return Boolean(state.collapsedDeviceTreeGroups?.[scope]?.[groupKey]);
}

function toggleDeviceTreeGroup(scope, groupKey) {
  if (!scope || !groupKey || groupKey === "all") return;
  if (!state.collapsedDeviceTreeGroups[scope]) {
    state.collapsedDeviceTreeGroups[scope] = {};
  }
  if (state.collapsedDeviceTreeGroups[scope][groupKey]) {
    delete state.collapsedDeviceTreeGroups[scope][groupKey];
  } else {
    state.collapsedDeviceTreeGroups[scope][groupKey] = true;
  }
}

function deviceTreeTypeAttrs(scope, groupKey, isCollapsed) {
  return `
          data-tree-toggle-scope="${escapeHtml(scope)}"
          data-tree-toggle-group="${escapeHtml(groupKey)}"
          aria-expanded="${isCollapsed ? "false" : "true"}"`;
}

function deviceTreeTypeLabel(label) {
  const text = label === "Environment" ? "气象环境" : label;
  return `
          <span class="tree-title">
            <i class="tree-toggle" aria-hidden="true"></i>
            <span class="tree-title-text">${escapeHtml(text)}</span>
          </span>`;
}

function deviceTreeChildren(isCollapsed, childrenHtml) {
  if (isCollapsed) return "";
  return `
        <div class="tree-children">
          ${childrenHtml}
        </div>`;
}

function deviceTreeSearchText(scope) {
  return String(state.deviceTreeSearch?.[scope] || "").trim().toLocaleLowerCase("zh-CN");
}

function deviceTreeVisibleName(item, devType = "") {
  const name = String(item?.dev_name ?? item?.name ?? "");
  if ((devType || item?.dev_type) === "Environment" && name === "weather") return "气象";
  return name;
}

function deviceTreeSearchFields(item, devType = "") {
  const raw = item?.raw || {};
  return [
    devType,
    item?.dev_type,
    item?.dev_name,
    item?.name,
    deviceTreeVisibleName(item, devType),
    item?.idx,
    raw.idx,
    item?.count,
    item?.mode,
    item ? deviceTreeBadge(item) : "",
  ].filter((value) => value !== undefined && value !== null && String(value).trim() !== "");
}

function filterDeviceTreeGroups(groupEntries, scope) {
  const query = deviceTreeSearchText(scope);
  const total = groupEntries.reduce((sum, [, items]) => sum + items.length, 0);
  if (!query) return { groupEntries, total, filteredTotal: total, query };
  const filtered = groupEntries
    .map(([devType, items]) => {
      const typeText = [devType, devType === "Environment" ? "气象环境" : ""]
        .join(" ")
        .toLocaleLowerCase("zh-CN");
      const matchedItems = typeText.includes(query)
        ? items
        : items.filter((item) => deviceTreeSearchFields(item, devType).join(" ").toLocaleLowerCase("zh-CN").includes(query));
      return [devType, matchedItems];
    })
    .filter(([, items]) => items.length);
  const filteredTotal = filtered.reduce((sum, [, items]) => sum + items.length, 0);
  return { groupEntries: filtered, total, filteredTotal, query };
}

function deviceTreeSummary(result) {
  return result.query
    ? `${result.groupEntries.length} 类 · ${result.filteredTotal}/${result.total} 台`
    : `${result.groupEntries.length} 类 · ${result.total} 台`;
}

function renderDeviceTreeFilterEmpty(query) {
  return query ? `<div class="empty-state">未匹配“${escapeHtml(query)}”</div>` : '<div class="empty-state">暂无设备</div>';
}

function updateDeviceTreeHtml(container, html, renderKey = html) {
  if (!container) return;
  const key = String(renderKey || "");
  if (deviceTreeRenderKeys.get(container) === key) return;
  const scrollTop = container.scrollTop;
  const restoreScrollTop = () => {
    const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    container.scrollTop = Math.min(scrollTop, maxScrollTop);
  };
  container.innerHTML = html;
  deviceTreeRenderKeys.set(container, key);
  restoreScrollTop();
  requestAnimationFrame(() => {
    restoreScrollTop();
  });
}

function deviceTreeItemType(item) {
  return String(item?.dev_type || item?.type || "");
}

function deviceTreeItemName(item) {
  return String(item?.dev_name || item?.name || "");
}

function deviceTreeFilterKey(devType, devName = "") {
  return `${devType || "all"}::${devName || ""}`;
}

function deviceTreeFilterItem(devType, devName = "") {
  return { dev_type: devType || "all", dev_name: devName || "" };
}

function uniqueDeviceTreeSelection(items) {
  const seen = new Set();
  const result = [];
  (items || []).forEach((item) => {
    const devType = String(item?.dev_type || "all");
    const devName = String(item?.dev_name || "");
    const key = deviceTreeFilterKey(devType, devName);
    if (seen.has(key)) return;
    seen.add(key);
    result.push(deviceTreeFilterItem(devType, devName));
  });
  return result.some((item) => item.dev_type === "all")
    ? [deviceTreeFilterItem("all", "")]
    : result;
}

function deviceTreeFilterSelection(filter = {}) {
  const selectedItems = Array.isArray(filter?.selected_items) ? filter.selected_items : [];
  const selected = uniqueDeviceTreeSelection(selectedItems);
  if (selected.length) return selected;
  return [deviceTreeFilterItem(filter?.dev_type || "all", filter?.dev_name || "")];
}

function withDeviceTreeSelection(filter = {}, selection = []) {
  const selected = uniqueDeviceTreeSelection(selection);
  const primary = selected[0] || deviceTreeFilterItem("all", "");
  return {
    ...filter,
    dev_type: primary.dev_type,
    dev_name: primary.dev_name,
    selected_items: selected.length ? selected : [deviceTreeFilterItem("all", "")],
  };
}

function isDeviceTreeNodeActive(filter, devType, devName = "") {
  const key = deviceTreeFilterKey(devType || "all", devName || "");
  return deviceTreeFilterSelection(filter).some((item) => deviceTreeFilterKey(item.dev_type, item.dev_name) === key);
}

function isDeviceTreeParentActive(filter, devType) {
  return deviceTreeFilterSelection(filter).some((item) => item.dev_type === devType);
}

function deviceFilterMatches(dev, filter) {
  const selection = deviceTreeFilterSelection(filter);
  if (selection.some((item) => item.dev_type === "all")) return true;
  const devType = deviceTreeItemType(dev);
  const devName = deviceTreeItemName(dev);
  return selection.some((item) => item.dev_type === devType && (!item.dev_name || item.dev_name === devName));
}

function deviceTreeButtonItem(button, dataPrefix) {
  const dataset = button?.dataset || {};
  const typeKey = `${dataPrefix}TreeType`;
  const nameKey = `${dataPrefix}TreeName`;
  return deviceTreeFilterItem(dataset[typeKey] || "all", dataset[nameKey] || "");
}

function selectDeviceTreeRangeItems(button, dataPrefix, anchorKey = "") {
  const container = button?.closest?.(".device-tree") || button?.parentElement;
  if (!container) return [deviceTreeButtonItem(button, dataPrefix)];
  const selector = `[data-${dataPrefix.replace(/[A-Z]/g, (char) => `-${char.toLowerCase()}`)}-tree-type]`;
  const buttons = Array.from(container.querySelectorAll(selector)).filter((item) => item instanceof HTMLElement);
  const currentKey = deviceTreeFilterKey(
    button.dataset?.[`${dataPrefix}TreeType`] || "all",
    button.dataset?.[`${dataPrefix}TreeName`] || "",
  );
  const currentIndex = buttons.findIndex((item) => deviceTreeFilterKey(
    item.dataset?.[`${dataPrefix}TreeType`] || "all",
    item.dataset?.[`${dataPrefix}TreeName`] || "",
  ) === currentKey);
  const anchorIndex = buttons.findIndex((item) => deviceTreeFilterKey(
    item.dataset?.[`${dataPrefix}TreeType`] || "all",
    item.dataset?.[`${dataPrefix}TreeName`] || "",
  ) === anchorKey);
  if (currentIndex < 0 || anchorIndex < 0) return [deviceTreeButtonItem(button, dataPrefix)];
  const [start, end] = currentIndex < anchorIndex ? [currentIndex, anchorIndex] : [anchorIndex, currentIndex];
  return buttons.slice(start, end + 1).map((item) => deviceTreeButtonItem(item, dataPrefix));
}

function updateDeviceTreeFilterSelection(filterName, devType, devName = "", event = null, dataPrefix = "", button = null) {
  const currentFilter = state[filterName] || { dev_type: "all", dev_name: "" };
  const clicked = deviceTreeFilterItem(devType || "all", devName || "");
  const clickedKey = deviceTreeFilterKey(clicked.dev_type, clicked.dev_name);
  const isMulti = Boolean(event?.ctrlKey || event?.metaKey);
  const isRange = Boolean(event?.shiftKey);
  let nextSelection = [clicked];
  const targetButton = button || event?.currentTarget;
  if (clicked.dev_type !== "all" && isRange && dataPrefix && targetButton) {
    nextSelection = selectDeviceTreeRangeItems(
      targetButton,
      dataPrefix,
      state.deviceTreeSelectionAnchors?.[filterName] || "",
    );
  } else if (clicked.dev_type !== "all" && isMulti) {
    const currentSelection = deviceTreeFilterSelection(currentFilter).filter((item) => item.dev_type !== "all");
    const exists = currentSelection.some((item) => deviceTreeFilterKey(item.dev_type, item.dev_name) === clickedKey);
    nextSelection = exists
      ? currentSelection.filter((item) => deviceTreeFilterKey(item.dev_type, item.dev_name) !== clickedKey)
      : [...currentSelection, clicked];
    if (!nextSelection.length) nextSelection = [deviceTreeFilterItem("all", "")];
  }
  state.deviceTreeSelectionAnchors = {
    ...(state.deviceTreeSelectionAnchors || {}),
    [filterName]: clickedKey,
  };
  state[filterName] = withDeviceTreeSelection(currentFilter, nextSelection);
  return state[filterName];
}

function deviceFilterLabel(filter = {}) {
  const selection = deviceTreeFilterSelection(filter);
  if (!selection.length || selection[0].dev_type === "all") return "全部设备";
  if (selection.length > 1) return `已选 ${selection.length} 项`;
  return selection[0].dev_name || selection[0].dev_type;
}

function tableFilterText(value) {
  return String(value ?? "").trim().toLocaleLowerCase("zh-CN");
}

function tableFilterMatchesKeyword(fields, keyword) {
  const query = tableFilterText(keyword);
  if (!query) return true;
  return (fields || []).some((field) => tableFilterText(field).includes(query));
}

function tableFilterTypeOptions(rows, labelFn) {
  const labels = new Map();
  (rows || []).forEach((row) => {
    const label = String(labelFn(row) || "").trim();
    if (label) labels.set(label, label);
  });
  return Array.from(labels.values()).sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function syncTableKeywordFilter(inputId, value) {
  const input = $(inputId);
  if (input && input.value !== String(value || "")) input.value = String(value || "");
}

function syncTableTypeFilter(selectId, stateKey, options) {
  const select = $(selectId);
  if (!select) return;
  if (state[stateKey] !== "all" && !(options || []).includes(state[stateKey])) {
    state[stateKey] = "all";
  }
  const html = [
    '<option value="all">全部类型</option>',
    ...(options || []).map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`),
  ].join("");
  if (select.innerHTML !== html) select.innerHTML = html;
  if (select.value !== state[stateKey]) select.value = state[stateKey];
}

function tableFilterIsActive(keyword, type) {
  return Boolean(String(keyword || "").trim()) || (type && type !== "all");
}

function refreshDeviceTreeFilterScope(scope) {
  if (scope === "model") renderGridModelDeviceTree();
  if (scope === "faultDevice") renderFaultDeviceTree();
  if (scope === "faultMeasurement") renderFaultMeasurementTree();
  if (scope === "mode") renderModeDeviceTree();
  if (scope === "runtime") renderRuntimeDeviceTree();
  if (scope === "measurement") renderMeasurementCompareDeviceTree();
}

function simulationModeLocked(clock = state.snapshot?.clock) {
  return Boolean(clock) && clock.state !== "stopped";
}

function simulationModeLabel(mode = state.curveMode) {
  return CURVE_MODES[mode]?.simulationLabel || CURVE_MODES.day.simulationLabel;
}

function simulationModeDayCount(mode = state.curveMode) {
  if (mode === "week") return 7;
  if (mode === "month") return 30;
  if (mode === "year") return 365;
  return 1;
}

function simulationModeDurationMinutes(mode = state.curveMode) {
  return CURVE_MODES[mode]?.durationMinutes || CURVE_MODES.day.durationMinutes;
}

function isExtendedSimulationMode(mode = state.curveMode) {
  return simulationModeDayCount(mode) > 1;
}

function formatClockDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value >= 3600 && value % 3600 === 0) return `${formatOverviewNumber(value / 3600)} h`;
  if (value >= 60 && value % 60 === 0) return `${formatOverviewNumber(value / 60)} min`;
  return `${formatOverviewNumber(value)} s`;
}

function formatSimulationClock(clock) {
  const timeText = clock?.time || "00:00:00";
  const mode = CURVE_MODES[state.curveMode] ? state.curveMode : "day";
  if (!isExtendedSimulationMode(mode)) return timeText;
  const absoluteMinute = Math.max(0, Number(clock?.absolute_minute ?? clock?.minute ?? 0) || 0);
  let dayOfCycle = Math.floor(absoluteMinute / 1440) % simulationModeDayCount(mode);
  if (mode !== "year") return `第${dayOfCycle + 1}天 ${timeText}`;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  while (month < monthDays.length - 1 && dayOfCycle >= monthDays[month]) {
    dayOfCycle -= monthDays[month];
    month += 1;
  }
  return `${String(month + 1).padStart(2, "0")}-${String(dayOfCycle + 1).padStart(2, "0")} ${timeText}`;
}

function clockControlButtonDisabled(action, clockState) {
  if (clockState === "running" && ["start", "step"].includes(action)) return true;
  if (clockState === "paused" && action === "pause") return true;
  if (clockState === "stopped" && ["stop", "pause", "step"].includes(action)) return true;
  return false;
}

function clockControlButtonUnavailable(action, clockState) {
  return (
    state.clockControlOperationActive
    || modelServiceDependentControlsDisabled()
    || clockControlButtonDisabled(action, clockState)
  );
}

function renderClockControlAvailability(clockState = "") {
  const resolvedClockState = (
    clockState
    || document.querySelector(".clock-readout")?.dataset.clockState
    || state.snapshot?.clock?.state
    || "stopped"
  );
  document.querySelectorAll("[data-clock]").forEach((button) => {
    const action = button.dataset.clock;
    button.disabled = clockControlButtonUnavailable(action, resolvedClockState);
    button.setAttribute("aria-disabled", button.disabled ? "true" : "false");
  });
}

function renderClock(clock) {
  if (!clock) return;
  $("simState").textContent = clock.state || "stopped";
  $("simTime").textContent = formatSimulationClock(clock);
  $("simSpeed").textContent = `x${clock.speed ?? 1}`;
  const overviewClockSpeed = $("overviewClockSpeed");
  if (overviewClockSpeed) overviewClockSpeed.textContent = `x${clock.speed ?? 1}`;
  const readout = document.querySelector(".clock-readout");
  if (readout) {
    readout.dataset.clockState = clock.state || "stopped";
    readout.classList.toggle("is-year-mode", isExtendedSimulationMode());
  }
  document.querySelectorAll("[data-clock]").forEach((button) => {
    const action = button.dataset.clock;
    const isActive =
      (action === "start" && clock.state === "running") ||
      (action === "pause" && clock.state === "paused") ||
      (action === "stop" && clock.state === "stopped");
    button.classList.toggle("is-active", isActive);
    if (["start", "pause", "stop"].includes(action)) {
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    }
  });
  renderClockControlAvailability(clock.state || "stopped");
  renderCurveModeControls();
}

function showUiToast(message, level = "info", durationMs = 3600) {
  const container = $("uiToastContainer");
  if (!container || !message) return;
  const toast = document.createElement("div");
  toast.className = `ui-toast is-${level || "info"}`;
  toast.setAttribute("role", "status");
  const textSpan = document.createElement("span");
  textSpan.className = "ui-toast-text";
  textSpan.textContent = String(message);
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "ui-toast-close";
  closeBtn.setAttribute("aria-label", "关闭提示");
  closeBtn.textContent = "×";
  let timerId = null;
  const dismiss = () => {
    if (timerId !== null) clearTimeout(timerId);
    toast.remove();
  };
  closeBtn.addEventListener("click", dismiss);
  toast.append(textSpan, closeBtn);
  container.appendChild(toast);
  while (container.children.length > 4) {
    container.firstElementChild?.remove();
  }
  if (durationMs > 0) {
    timerId = setTimeout(dismiss, durationMs);
  }
}

function confirmDangerousAction({
  title = "确认执行此操作？",
  target = "",
  message = "此操作不可撤销，请确认是否继续。",
  confirmLabel = "确认执行",
} = {}) {
  const dialog = $("dangerConfirmDialog");
  const titleNode = $("dangerConfirmTitle");
  const targetNode = $("dangerConfirmTarget");
  const messageNode = $("dangerConfirmMessage");
  const cancelBtn = $("dangerConfirmCancel");
  const okBtn = $("dangerConfirmOk");
  if (!dialog || !cancelBtn || !okBtn || typeof dialog.showModal !== "function") {
    return Promise.resolve(window.confirm(`${title}\n${target ? `${target}\n` : ""}${message}`));
  }
  if (dialog.open) return Promise.resolve(false);
  if (titleNode) titleNode.textContent = title;
  if (targetNode) {
    targetNode.textContent = target;
    targetNode.hidden = !target;
  }
  if (messageNode) messageNode.textContent = message;
  okBtn.textContent = confirmLabel;

  return new Promise((resolve) => {
    let settled = false;
    const finish = (accepted) => {
      if (settled) return;
      settled = true;
      cancelBtn.removeEventListener("click", onCancel);
      okBtn.removeEventListener("click", onConfirm);
      dialog.removeEventListener("cancel", onDialogCancel);
      if (dialog.open) dialog.close();
      resolve(accepted);
    };
    const onCancel = () => finish(false);
    const onConfirm = () => finish(true);
    const onDialogCancel = (event) => {
      event.preventDefault();
      finish(false);
    };
    cancelBtn.addEventListener("click", onCancel);
    okBtn.addEventListener("click", onConfirm);
    dialog.addEventListener("cancel", onDialogCancel);
    dialog.showModal();
    cancelBtn.focus();
  });
}

function chartThemePalette() {
  const dark = document.documentElement.dataset.theme === "dark";
  if (dark) {
    return {
      bg: "#0f172a",
      grid: "rgba(148, 163, 184, 0.16)",
      gridSubtle: "rgba(148, 163, 184, 0.1)",
      axis: "rgba(148, 163, 184, 0.34)",
      text: "#94a3b8",
      markerFill: "#0f172a",
      tooltipBg: "rgba(15, 23, 42, 0.96)",
      tooltipBorder: "rgba(148, 163, 184, 0.35)",
      tooltipTitle: "#f1f5f9",
      tooltipText: "#cbd5e1",
    };
  }
  return {
    bg: "#fcfeff",
    grid: "#d8e1e5",
    gridSubtle: "#e7eef1",
    axis: "#c9d6dc",
    text: "#63717a",
    markerFill: "#ffffff",
    tooltipBg: "rgba(255, 255, 255, 0.96)",
    tooltipBorder: "rgba(171, 190, 198, 0.9)",
    tooltipTitle: "#1f3037",
    tooltipText: "#314850",
  };
}

function redrawActiveSimulatorCharts() {
  const page = typeof currentPageName === "function" ? currentPageName() : "";
  if (page === "curves" && typeof drawCurveEditor === "function") {
    drawCurveEditor();
  } else if (page === "runtime" && typeof drawRuntimeTraceChart === "function") {
    drawRuntimeTraceChart();
  } else if (page === "measurements" && typeof drawMeasurementTraceChart === "function") {
    drawMeasurementTraceChart();
  }
}

function initPrecisionUiChrome() {
  // 动态修正 IEC104 联动导航主机名，支持局域网跨机访问。
  const scadaLink = document.querySelector(".scada104-link");
  if (scadaLink && window.location.hostname) {
    scadaLink.href = `${window.location.protocol}//${window.location.hostname}:8878/simulator104`;
  }
  const themeBtn = $("themeToggleButton");
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      if (next === "dark") document.documentElement.dataset.theme = "dark";
      else delete document.documentElement.dataset.theme;
      try {
        localStorage.setItem("polarUiTheme", next);
      } catch (_e) {}
      redrawActiveSimulatorCharts();
      showUiToast(next === "dark" ? "已切换至控制室深色模式" : "已切换至日间浅色模式", "info", 2200);
    });
  }
  // 为所有左侧设备树面板注入一键折叠/展开按钮，最大化表格与曲线可视空间。
  document.querySelectorAll(".device-tree-panel").forEach((aside) => {
    const head = aside.querySelector(".panel-head");
    if (!head || head.querySelector(".tree-collapse-btn")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tree-collapse-btn";
    btn.textContent = "收起";
    btn.title = "折叠/展开左侧设备树面板";
    btn.addEventListener("click", () => {
      const collapsed = aside.classList.toggle("is-collapsed");
      btn.textContent = collapsed ? "展开" : "收起";
      requestAnimationFrame(redrawActiveSimulatorCharts);
    });
    head.appendChild(btn);
  });
  const dismissBtn = $("powerFlowFailureDismiss");
  const badgeBtn = $("topbarAlertBadge");
  if (dismissBtn) {
    dismissBtn.addEventListener("click", () => {
      state.powerFlowAlertDismissedKey = state.powerFlowAlertKey || "__dismissed__";
      const alertNode = $("powerFlowFailureAlert");
      if (alertNode) alertNode.hidden = true;
      if (badgeBtn) badgeBtn.hidden = false;
    });
  }
  if (badgeBtn) {
    badgeBtn.addEventListener("click", () => {
      state.powerFlowAlertDismissedKey = "";
      const alertNode = $("powerFlowFailureAlert");
      if (alertNode) alertNode.hidden = false;
      badgeBtn.hidden = true;
    });
  }
}

function renderPowerFlowFailureAlert(snapshot = state.snapshot || {}) {
  const alert = $("powerFlowFailureAlert");
  const badge = $("topbarAlertBadge");
  const badgeText = $("topbarAlertBadgeText");
  if (!alert) return;
  const computeStatus = String(snapshot.compute?.status || "").toLowerCase();
  const failed = computeStatus === "failed" || computeStatus === "timeout";
  if (!failed) {
    state.powerFlowAlertKey = "";
    state.powerFlowAlertDismissedKey = "";
    alert.hidden = true;
    if (badge) badge.hidden = true;
    return;
  }
  const timedOut = computeStatus === "timeout";
  const simulationPaused = String(snapshot.clock?.state || "").toLowerCase() === "paused";
  const simuTime = snapshot.compute?.simu_time || snapshot.clock?.time || "--";
  const lastSuccessTime = snapshot.compute?.last_successful_simu_time || "";
  const error = snapshot.compute?.error || snapshot.result?.error || "潮流内核未返回可用结果";
  const alertKey = `${computeStatus}|${simuTime}|${error}`;
  state.powerFlowAlertKey = alertKey;
  const dismissed = state.powerFlowAlertDismissedKey === alertKey;
  alert.hidden = dismissed;
  if (badge) {
    badge.hidden = !dismissed;
    if (badgeText) badgeText.textContent = timedOut ? "潮流超时（未恢复）" : "潮流失败（未恢复）";
  }
  const title = $("powerFlowFailureTitle");
  const detail = $("powerFlowFailureDetail");
  if (title) {
    title.textContent = simulationPaused
      ? (timedOut ? "潮流计算超时，仿真已暂停" : "潮流计算失败，仿真已暂停")
      : (timedOut ? "潮流计算超时，本轮结果已丢弃" : "潮流计算失败，本轮结果已丢弃");
  }
  if (detail) {
    const staleFrameText = lastSuccessTime
      ? `当前画面量测为上一成功帧（${lastSuccessTime}）`
      : "当前画面没有成功潮流量测帧";
    detail.textContent = (
      `失败仿真时刻 ${simuTime}。${error}。`
      + `本轮潮流结果未采用，${staleFrameText}，请修正边界后${simulationPaused ? "再恢复运行" : "重新计算"}。`
    );
  }
}

function parameterNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function parameterText(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toFixed(digits).replace(/\.?0+$/, "");
}

function parameterPercentInputText(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? parameterText(number * 100, digits) : "";
}

function parameterPercentText(value, digits = 2) {
  const text = parameterPercentInputText(value, digits);
  return text ? `${text}%` : "--";
}

function snapshotSystemParameters(snapshot = state.snapshot || {}) {
  const params = snapshot.system_parameters || {};
  const clock = snapshot.clock || {};
  const clockStepSeconds = parameterNumber(params.clock_step_seconds ?? clock.step_seconds, 1);
  const clockSpeed = parameterNumber(params.clock_speed ?? clock.speed, 1);
  return {
    clock_speed: clockSpeed,
    compute_interval_seconds: parameterNumber(params.compute_interval_seconds, 1),
    storage_initial_soc: Math.max(0, Math.min(1, parameterNumber(params.storage_initial_soc, 0.5))),
    remote_adjustment_response_ratio: Math.max(
      0.01,
      Math.min(1, parameterNumber(params.remote_adjustment_response_ratio, 0.7)),
    ),
    clock_step_seconds: clockStepSeconds,
    clock_step_minutes: parameterNumber(params.clock_step_minutes ?? clock.step_minutes, clockStepSeconds / 60),
    effective_step_seconds: parameterNumber(
      params.effective_step_seconds ?? clock.effective_step_seconds,
      clockStepSeconds * clockSpeed,
    ),
    effective_step_minutes: parameterNumber(
      params.effective_step_minutes ?? clock.effective_step_minutes,
      (clockStepSeconds * clockSpeed) / 60,
    ),
  };
}

function renderSystemParameters(snapshot = state.snapshot) {
  const params = snapshotSystemParameters(snapshot || {});
  state.systemParameters = params;
  const currentSpeed = $("currentClockSpeed");
  const currentInterval = $("currentComputeInterval");
  const currentStorageInitialSoc = $("currentStorageInitialSoc");
  const currentRemoteAdjustmentResponseRatio = $("currentRemoteAdjustmentResponseRatio");
  if (currentSpeed) currentSpeed.textContent = `x${parameterText(params.clock_speed, 1)}`;
  if (currentInterval) currentInterval.textContent = `${parameterText(params.compute_interval_seconds, 2)} s`;
  if (currentStorageInitialSoc) currentStorageInitialSoc.textContent = parameterPercentText(params.storage_initial_soc, 2);
  if (currentRemoteAdjustmentResponseRatio) {
    currentRemoteAdjustmentResponseRatio.textContent = parameterText(params.remote_adjustment_response_ratio, 2);
  }

  const form = $("systemParameterForm");
  const isEditing = Boolean(form?.contains(document.activeElement));
  if (!state.systemParametersDirty && !isEditing) {
    const speedInput = $("parameterClockSpeed");
    const intervalInput = $("parameterComputeInterval");
    const storageInitialSocInput = $("parameterStorageInitialSoc");
    const remoteAdjustmentResponseRatioInput = $("parameterRemoteAdjustmentResponseRatio");
    if (speedInput) speedInput.value = String(params.clock_speed);
    if (intervalInput) intervalInput.value = parameterText(params.compute_interval_seconds, 2);
    if (storageInitialSocInput) storageInitialSocInput.value = parameterPercentInputText(params.storage_initial_soc, 2);
    if (remoteAdjustmentResponseRatioInput) {
      remoteAdjustmentResponseRatioInput.value = parameterText(params.remote_adjustment_response_ratio, 2);
    }
  }

  const summary = $("systemParameterSummary");
  if (summary) {
    summary.textContent = state.systemParametersSaving
      ? "保存中"
      : state.systemParametersDirty
        ? "有未保存修改"
        : `x${parameterText(params.clock_speed, 1)} · ${parameterText(params.compute_interval_seconds, 2)} s · SOC ${parameterPercentText(params.storage_initial_soc, 2)} · 遥调 ${parameterText(params.remote_adjustment_response_ratio, 2)}`;
  }

  const modelName = snapshot?.model?.name || snapshot?.model?.id || state.activeModelId || "--";
  const clock = snapshot?.clock || {};
  const modeLabel = simulationModeLabel();
  const stateText = clock.state || "--";
  const stateMap = { running: "运行中", paused: "已暂停", stopped: "已停止" };
  const values = {
    systemParameterState: state.systemParametersDirty ? "待保存" : "已同步",
    parameterModelName: modelName,
    parameterSimulationMode: modeLabel,
    parameterClockState: stateMap[stateText] || stateText,
    parameterClockTime: snapshot?.clock ? formatSimulationClock(clock) : "--",
    parameterEffectiveStep: formatClockDuration(params.effective_step_seconds),
    parameterComputePeriod: `${parameterText(params.compute_interval_seconds, 2)} s`,
    parameterStorageInitialSocState: parameterPercentText(params.storage_initial_soc, 2),
    parameterRemoteAdjustmentResponseRatioState: parameterText(params.remote_adjustment_response_ratio, 2),
  };
  Object.entries(values).forEach(([id, text]) => {
    const node = $(id);
    if (node) node.textContent = text;
  });
}

function markSystemParametersDirty() {
  state.systemParametersDirty = true;
  renderSystemParameters(state.snapshot);
}

function systemParameterPayload() {
  return {
    clock_speed: parameterNumber($("parameterClockSpeed")?.value, state.systemParameters.clock_speed || 1),
    compute_interval_seconds: parameterNumber(
      $("parameterComputeInterval")?.value,
      state.systemParameters.compute_interval_seconds || 1,
    ),
    storage_initial_soc: Math.max(
      0,
      Math.min(
        1,
        parameterNumber(
          $("parameterStorageInitialSoc")?.value,
          (state.systemParameters.storage_initial_soc ?? 0.5) * 100,
        ) / 100,
      ),
    ),
    remote_adjustment_response_ratio: Math.max(
      0.01,
      Math.min(
        1,
        parameterNumber(
          $("parameterRemoteAdjustmentResponseRatio")?.value,
          state.systemParameters.remote_adjustment_response_ratio ?? 0.7,
        ),
      ),
    ),
  };
}

async function saveSystemParameters() {
  const saveButton = $("saveSystemParameters");
  const resetButton = $("resetSystemParameters");
  state.systemParametersSaving = true;
  if (saveButton) saveButton.disabled = true;
  if (resetButton) resetButton.disabled = true;
  renderSystemParameters(state.snapshot);
  try {
    const result = await api("/api/config", {
      method: "POST",
      body: JSON.stringify(systemParameterPayload()),
    });
    if (state.snapshot && result.clock) {
      state.snapshot.clock = result.clock;
      renderClock(result.clock);
    }
    if (result.system_parameters) {
      state.systemParameters = result.system_parameters;
    }
    state.systemParametersDirty = false;
    await refresh();
  } catch (error) {
    const summary = $("systemParameterSummary");
    if (summary) summary.textContent = "保存失败";
    throw error;
  } finally {
    state.systemParametersSaving = false;
    if (saveButton) saveButton.disabled = false;
    if (resetButton) resetButton.disabled = false;
    renderSystemParameters(state.snapshot);
  }
}

function resetSystemParameterForm() {
  state.systemParametersDirty = false;
  renderSystemParameters(state.snapshot);
}

function runtimeParameterElement(id) {
  return $(id) || state.pageSections?.parameters?.querySelector?.(`#${id}`) || null;
}

function resetWebRuntimeSettingsState() {
  state.webRuntimeSettings = { ...WEB_RUNTIME_FALLBACKS };
  state.webRuntimeDefaults = { ...WEB_RUNTIME_FALLBACKS };
  state.webRuntimeConstraints = {};
  state.webRuntimeDraft = { ...WEB_RUNTIME_FALLBACKS };
  state.webRuntimeUpdatedAt = "";
  state.webRuntimeLoadedModelId = "";
  state.webRuntimeLoading = false;
  state.webRuntimeSaving = false;
  state.webRuntimeDirty = false;
  state.webRuntimeError = "";
}

function runtimeSettingDisplay(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return Number.isInteger(number) ? String(number) : String(Number(number.toFixed(3)));
}

function renderWebRuntimeSettings() {
  const root = state.pageSections?.parameters || document;
  const values = state.webRuntimeDirty ? state.webRuntimeDraft : state.webRuntimeSettings;
  root.querySelectorAll?.("[data-runtime-setting]").forEach((input) => {
    const name = input.dataset.runtimeSetting || "";
    const value = Number(values?.[name]);
    if (Number.isFinite(value) && document.activeElement !== input) input.value = String(value);
    const constraint = state.webRuntimeConstraints?.[name] || {};
    if (constraint.min !== undefined) input.min = String(constraint.min);
    if (constraint.max !== undefined) input.max = String(constraint.max);
    input.disabled = state.webRuntimeLoading || state.webRuntimeSaving;
  });
  Object.entries(WEB_RUNTIME_CURRENT_IDS).forEach(([name, id]) => {
    const node = runtimeParameterElement(id);
    if (node) node.textContent = runtimeSettingDisplay(state.webRuntimeSettings?.[name]);
  });
  const activeModel = state.models.find((model) => model.id === state.activeModelId);
  const modelName = activeModel?.name || state.snapshot?.model?.name || state.activeModelId || "--";
  const modelNode = runtimeParameterElement("runtimeParameterModelName");
  const updatedNode = runtimeParameterElement("runtimeParameterUpdatedAt");
  if (modelNode) modelNode.textContent = modelName;
  if (updatedNode) updatedNode.textContent = state.webRuntimeUpdatedAt || "尚未保存（使用默认值）";
  const summary = runtimeParameterElement("runtimeParameterSummary");
  if (summary) {
    summary.textContent = state.webRuntimeSaving
      ? "保存中"
      : state.webRuntimeLoading
        ? "加载中"
        : state.webRuntimeError
          ? `加载失败：${state.webRuntimeError}`
          : state.webRuntimeDirty
            ? "有未保存修改"
            : "已生效";
  }
  const saveButton = runtimeParameterElement("saveRuntimeParameters");
  const undoButton = runtimeParameterElement("undoRuntimeParameters");
  const defaultsButton = runtimeParameterElement("restoreRuntimeParameterDefaults");
  if (saveButton) saveButton.disabled = !state.webRuntimeDirty || state.webRuntimeLoading || state.webRuntimeSaving;
  if (undoButton) undoButton.disabled = !state.webRuntimeDirty || state.webRuntimeLoading || state.webRuntimeSaving;
  if (defaultsButton) defaultsButton.disabled = state.webRuntimeLoading || state.webRuntimeSaving;
}

function applyWebRuntimeSettings() {
  state.runtimeLogPageSize = Math.max(5, Math.round(activeRuntimeSetting("runtime_log_page_size")));
  const logLimit = Math.max(50, Math.round(activeRuntimeSetting("runtime_log_cache_limit")));
  state.runtimeLogs = state.runtimeLogs.slice(0, logLimit);
  state.runtimeTraceHistory = compactTraceHistory(state.runtimeTraceHistory, state.runtimeTraceWindowMinutes);
  state.measurementTraceHistory = compactTraceHistory(state.measurementTraceHistory, state.measurementTraceWindowMinutes);
  restartRefreshScheduler();
}

async function loadWebRuntimeSettings(force = false) {
  const modelId = state.activeModelId;
  if (!modelId || !activeModelServiceRunning()) return null;
  if (!force && state.webRuntimeLoadedModelId === modelId) {
    renderWebRuntimeSettings();
    return state.webRuntimeSettings;
  }
  state.webRuntimeLoading = true;
  state.webRuntimeError = "";
  renderWebRuntimeSettings();
  try {
    const payload = await api("/api/runtime-settings", { timeoutMs: frontendRequestTimeoutMs() });
    if (modelId !== state.activeModelId) return null;
    state.webRuntimeSettings = { ...WEB_RUNTIME_FALLBACKS, ...(payload.settings || {}) };
    state.webRuntimeDefaults = { ...WEB_RUNTIME_FALLBACKS, ...(payload.defaults || {}) };
    state.webRuntimeConstraints = payload.constraints || {};
    state.webRuntimeDraft = { ...state.webRuntimeSettings };
    state.webRuntimeUpdatedAt = payload.updatedAt || "";
    state.webRuntimeLoadedModelId = modelId;
    state.webRuntimeDirty = false;
    applyWebRuntimeSettings();
    return payload;
  } catch (error) {
    if (modelId === state.activeModelId) state.webRuntimeError = apiErrorText(error);
    return null;
  } finally {
    if (modelId === state.activeModelId) {
      state.webRuntimeLoading = false;
      renderWebRuntimeSettings();
    }
  }
}

function updateWebRuntimeDraft(input) {
  const name = input?.dataset?.runtimeSetting || "";
  if (!name) return;
  const value = Number(input.value);
  state.webRuntimeDraft = {
    ...state.webRuntimeDraft,
    [name]: Number.isFinite(value) ? value : input.value,
  };
  state.webRuntimeDirty = true;
  renderWebRuntimeSettings();
}

async function saveWebRuntimeSettings() {
  if (state.webRuntimeSaving || !state.webRuntimeDirty) return;
  state.webRuntimeSaving = true;
  state.webRuntimeError = "";
  renderWebRuntimeSettings();
  try {
    const payload = await api("/api/runtime-settings", {
      method: "POST",
      body: JSON.stringify({ settings: state.webRuntimeDraft }),
    });
    state.webRuntimeSettings = { ...WEB_RUNTIME_FALLBACKS, ...(payload.settings || {}) };
    state.webRuntimeDefaults = { ...WEB_RUNTIME_FALLBACKS, ...(payload.defaults || {}) };
    state.webRuntimeConstraints = payload.constraints || {};
    state.webRuntimeDraft = { ...state.webRuntimeSettings };
    state.webRuntimeUpdatedAt = payload.updatedAt || "";
    state.webRuntimeLoadedModelId = state.activeModelId;
    state.webRuntimeDirty = false;
    applyWebRuntimeSettings();
  } catch (error) {
    state.webRuntimeError = apiErrorText(error);
  } finally {
    state.webRuntimeSaving = false;
    renderWebRuntimeSettings();
  }
}

function undoWebRuntimeSettings() {
  state.webRuntimeDraft = { ...state.webRuntimeSettings };
  state.webRuntimeDirty = false;
  state.webRuntimeError = "";
  renderWebRuntimeSettings();
}

async function restoreWebRuntimeDefaults() {
  const confirmed = await confirmDangerousAction({
    title: "恢复默认运行参数？",
    target: "WEB 运行参数配置",
    message: "将把全部 WEB 运行参数表单重置为系统默认值（点击保存后正式写入）。",
    confirmLabel: "确认恢复",
  });
  if (!confirmed) return;
  state.webRuntimeDraft = { ...state.webRuntimeDefaults };
  state.webRuntimeDirty = true;
  state.webRuntimeError = "";
  renderWebRuntimeSettings();
  showUiToast("已填充默认运行参数，点击保存生效", "ok");
}

function setClockButtonsBusy(isBusy) {
  state.clockControlOperationActive = Boolean(isBusy);
  document.querySelectorAll("[data-clock]").forEach((button) => {
    button.classList.toggle("is-busy", isBusy);
  });
  renderClockControlAvailability();
}

async function controlClock(action, payload = {}) {
  setClockButtonsBusy(true);
  try {
    const clock = await api("/api/clock", { method: "POST", body: JSON.stringify({ ...payload, action }) });
    renderClock(clock);
    await refresh();
    return clock;
  } catch (error) {
    const simState = $("simState");
    const solverInfo = $("solverInfo");
    if (simState) simState.textContent = "error";
    if (solverInfo) solverInfo.textContent = "时钟控制失败";
    throw error;
  } finally {
    setClockButtonsBusy(false);
  }
}

function startSimulationMode() {
  return CURVE_MODES[state.curveMode] ? state.curveMode : "day";
}

function startSimulationDefaultAbsoluteSecond() {
  const clock = state.snapshot?.clock || {};
  const second = Number(
    clock.absolute_second
      ?? ((clock.absolute_minute ?? clock.minute ?? 0) * 60),
  );
  return Number.isFinite(second) ? Math.max(0, second) : 0;
}

function setStartSimulationMessage(text, kind = "") {
  const message = $("startSimulationMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function setStartSimulationBusy(isBusy) {
  const confirm = $("confirmStartSimulation");
  const cancel = $("cancelStartSimulation");
  const close = $("closeStartSimulationDialog");
  const day = $("startSimulationDay");
  const time = $("startSimulationTime");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "启动中" : "启动";
  }
  [cancel, close, day, time].forEach((element) => {
    if (element) element.disabled = isBusy;
  });
}

function populateStartSimulationDayOptions(daySelect, dayCount, selectedDay) {
  if (!daySelect) return;
  const count = Math.max(1, Number(dayCount) || 1);
  if (Number(daySelect.dataset.dayCount) !== count) {
    const fragment = document.createDocumentFragment();
    for (let d = 1; d <= count; d += 1) {
      fragment.appendChild(new Option(`第 ${d} 天`, String(d)));
    }
    daySelect.replaceChildren(fragment);
    daySelect.dataset.dayCount = String(count);
  }
  const normalized = clamp(Math.round(Number(selectedDay) || 1), 1, count);
  daySelect.value = String(normalized);
}

function updateStartSimulationFields() {
  const mode = startSimulationMode();
  const dayCount = simulationModeDayCount(mode);
  const usesDay = dayCount > 1;
  const dayField = $("startSimulationDayField");
  const dayInput = $("startSimulationDay");
  const hint = $("startSimulationHint");
  if (dayField) dayField.hidden = !usesDay;
  if (dayInput) {
    dayInput.disabled = !usesDay;
    if (usesDay) {
      populateStartSimulationDayOptions(dayInput, dayCount, dayInput.value || 1);
    }
  }
  if (hint) {
    hint.textContent = `${simulationModeLabel(mode)} · 按步长向上对齐`;
  }
}

function openStartSimulationDialog() {
  const dialog = $("startSimulationDialog");
  const dayInput = $("startSimulationDay");
  const timeInput = $("startSimulationTime");
  if (!dialog || !timeInput) return;
  const absoluteSecond = startSimulationDefaultAbsoluteSecond();
  const dayCount = simulationModeDayCount(startSimulationMode());
  const day = Math.floor(absoluteSecond / 86400) % dayCount + 1;
  if (dayInput) populateStartSimulationDayOptions(dayInput, dayCount, day);
  timeInput.value = secondToTimeInput(absoluteSecond % 86400, 0);
  updateStartSimulationFields();
  setStartSimulationBusy(false);
  setStartSimulationMessage("");
  dialog.hidden = false;
  requestAnimationFrame(() => {
    if (isExtendedSimulationMode(startSimulationMode()) && dayInput) {
      dayInput.focus();
      return;
    }
    timeInput.focus();
  });
}

function closeStartSimulationDialog() {
  const dialog = $("startSimulationDialog");
  if (dialog) dialog.hidden = true;
  setStartSimulationMessage("");
  setStartSimulationBusy(false);
}

function startSimulationSecondFromDialog() {
  const timeSecond = timeInputToSecond($("startSimulationTime")?.value, 0);
  const dayCount = simulationModeDayCount(startSimulationMode());
  if (dayCount <= 1) return timeSecond;
  const rawDay = Number($("startSimulationDay")?.value);
  const day = clamp(Math.round(Number.isFinite(rawDay) ? rawDay : 1), 1, dayCount);
  return (day - 1) * 86400 + timeSecond;
}

async function startSimulationFromDialog() {
  const second = startSimulationSecondFromDialog();
  setStartSimulationBusy(true);
  setStartSimulationMessage("正在启动仿真...");
  try {
    await controlClock("start", { second });
    closeStartSimulationDialog();
  } catch (error) {
    setStartSimulationMessage(apiErrorText(error), "error");
    setStartSimulationBusy(false);
  }
}

async function handleClockAction(action) {
  const currentState = state.snapshot?.clock?.state || $("simState")?.textContent || "stopped";
  if (action === "start" && currentState === "stopped") {
    openStartSimulationDialog();
    return;
  }
  if (action === "stop" && (currentState === "running" || currentState === "paused")) {
    const confirmed = await confirmDangerousAction({
      title: "确认停止当前仿真？",
      target: `模型：${state.activeModelId || "当前模型"}（状态：${currentState === "running" ? "运行中" : "已暂停"}）`,
      message: "停止仿真将中止当前时钟并重置本轮仿真过程状态，确认后执行。",
      confirmLabel: "确认停止",
    });
    if (!confirmed) return;
  }
  try {
    await controlClock(action);
  } catch (error) {
    showUiToast(`时钟操作失败：${apiErrorText(error)}`, "error", 3600);
  }
}

function setNewModelMessage(text, kind = "") {
  const message = $("newModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function modelPreflightDetailLines(validation) {
  const lines = [];
  const checks = Array.isArray(validation?.checks) ? validation.checks : [];
  checks.forEach((check) => {
    const details = check?.details && typeof check.details === "object" ? check.details : {};
    [
      ["missing_in_svg", "E 中缺少对应 SVG 图元"],
      ["unknown_in_model", "SVG 中无法定位到 E 的设备"],
      ["name_mismatches", "稳定索引对应名称不一致"],
      ["dangling_edges", "SVG 连线端点未绑定图元"],
      ["identity_issues", "SVG 图元身份字段不完整"],
      ["duplicate_devices", "SVG 设备稳定索引重复"],
    ].forEach(([key, label]) => {
      const values = Array.isArray(details[key]) ? details[key] : [];
      if (!values.length) return;
      const shown = values.slice(0, 6).map((value) => String(value));
      const omitted = values.length - shown.length;
      lines.push({
        checkId: String(check.id || ""),
        text: `${label}：${shown.join("、")}${omitted > 0 ? `（另有 ${omitted} 项）` : ""}`,
      });
    });
  });
  const repairs = Array.isArray(validation?.repairs) ? validation.repairs : [];
  if (repairs.length) {
    const shown = repairs.slice(0, 8).map((repair) => {
      const target = [repair?.block, repair?.device].filter(Boolean).join("/");
      return `${target || "设备"}.${repair?.field || "字段"}=${repair?.value ?? ""}`;
    });
    const omitted = repairs.length - shown.length;
    lines.push({
      checkId: "schema",
      text: `自动补值：${shown.join("、")}${omitted > 0 ? `（另有 ${omitted} 项）` : ""}`,
    });
  }
  return lines;
}

function renderModelPreflightResult(scope, validation) {
  const container = $(`${scope}Validation`);
  const summary = $(`${scope}ValidationSummary`);
  const list = $(`${scope}ValidationChecks`);
  if (!container || !summary || !list) return;
  if (!validation || typeof validation !== "object") {
    container.hidden = true;
    container.removeAttribute("data-status");
    summary.textContent = "";
    list.innerHTML = "";
    return;
  }

  const statusText = {
    passed: "通过",
    repaired: "已补齐",
    warning: "警告",
    failed: "失败",
    blocked: "未执行",
  };
  const detailsByCheck = new Map();
  modelPreflightDetailLines(validation).forEach((item) => {
    if (!detailsByCheck.has(item.checkId)) detailsByCheck.set(item.checkId, []);
    detailsByCheck.get(item.checkId).push(item.text);
  });
  const checks = Array.isArray(validation.checks) ? validation.checks : [];
  const duration = Number(validation.duration_ms);
  summary.textContent = `${validation.summary || (validation.ok ? "模型预校核通过。" : "模型预校核未通过。")}${Number.isFinite(duration) ? `（${Math.round(duration)} ms）` : ""}`;
  list.innerHTML = checks.map((check) => {
    const status = String(check?.status || "blocked");
    const detailLines = detailsByCheck.get(String(check?.id || "")) || [];
    return `
      <li class="model-preflight-check is-${escapeHtml(status)}">
        <div class="model-preflight-check-head">
          <strong>${escapeHtml(check?.label || check?.id || "校验项")}</strong>
          <span>${escapeHtml(statusText[status] || status)}</span>
        </div>
        <p>${escapeHtml(check?.message || "未返回说明。")}</p>
        ${detailLines.map((line) => `<small>${escapeHtml(line)}</small>`).join("")}
      </li>
    `;
  }).join("");
  container.dataset.status = validation.ok ? "passed" : "failed";
  container.hidden = false;
}

function invalidateModelPreflight(scope) {
  renderModelPreflightResult(scope, null);
  if (scope === "importModel") importModelCreationComplete = false;
  if (scope === "newModel") newModelCreationComplete = false;
  if (scope === "updateModel") updateModelSaveComplete = false;
}

function setNewModelBusy(isBusy) {
  const confirm = $("confirmNewModel");
  const button = $("newModelButton");
  const input = $("newModelName");
  const hostInput = $("newModelServiceHost");
  const portInput = $("newModelServicePort");
  const selectButton = $("selectNewModelFile");
  const selectSvgButton = $("selectNewModelSvgFile");
  const cancel = $("cancelNewModel");
  const disabled = isBusy || newModelCreationComplete;
  if (confirm) {
    confirm.disabled = disabled;
    confirm.textContent = newModelCreationComplete ? "已新建" : (isBusy ? "预校核中" : "新建");
  }
  if (button) button.disabled = isBusy;
  if (input) input.disabled = disabled;
  if (hostInput) hostInput.disabled = disabled;
  if (portInput) portInput.disabled = disabled;
  if (selectButton) selectButton.disabled = disabled;
  if (selectSvgButton) selectSvgButton.disabled = disabled;
  if (cancel) cancel.textContent = newModelCreationComplete ? "关闭" : "取消";
}

function uniqueNewModelName(baseName = "新模型") {
  const base = String(baseName || "新模型").trim().replace(/\s+/g, "_") || "新模型";
  if (!isModelNameTaken(base)) return base;
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${base}_${index}`;
    if (!isModelNameTaken(candidate)) return candidate;
  }
  return `${base}_${Date.now()}`;
}

function suggestedNewModelName(filename) {
  return uniqueNewModelName(
    String(filename || "新模型")
      .replace(/\.e$/i, "")
      .trim() || "新模型",
  );
}

function validateNewModelForm(showBlank = false) {
  const input = $("newModelName");
  const confirm = $("confirmNewModel");
  if (newModelCreationComplete) {
    if (confirm) confirm.disabled = true;
    return true;
  }
  const name = String(input?.value || "").trim();
  if (!name) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage(showBlank ? "请输入新模型名称。" : "", showBlank ? "error" : "");
    return false;
  }
  if (isModelNameTaken(name)) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage(`模型已存在：${name}，请输入新的模型名称。`, "error");
    return false;
  }
  const serviceAddress = validateServiceAddressInputs("newModelServiceHost", "newModelServicePort");
  updateServiceAddressPreview("newModelServiceHost", "newModelServicePort", "newModelServicePreview");
  if (!serviceAddress.ok) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage(serviceAddress.message, "error");
    return false;
  }
  if (!pendingNewModelFile) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage(showBlank ? "请选择 model.e 文件。" : "", showBlank ? "error" : "");
    return false;
  }
  if (!String(pendingNewModelFile.name || "").toLowerCase().endsWith(".e")) {
    if (confirm) confirm.disabled = true;
    setNewModelMessage("请选择 .e 格式的模型定义文件。", "error");
    return false;
  }
  if (confirm) confirm.disabled = false;
  setNewModelMessage("");
  return true;
}

function setModelManagementMessage(text, kind = "") {
  const message = $("modelManagementMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function modelClockState(model) {
  const modelId = String(model?.id || "");
  const serviceState = String(model?.service?.state || "stopped");
  if (serviceState !== "running") return "stopped";
  if (modelId && modelId === state.activeModelId && state.snapshot?.clock?.state) {
    return state.snapshot.clock.state;
  }
  return String(model?.clock_state || "stopped");
}

function modelClockStateText(clockState) {
  return {
    running: "运行中",
    paused: "暂停中",
    stopped: "已停止",
  }[clockState] || clockState || "--";
}

function modelServiceStateText(serviceState) {
  return {
    running: "服务运行",
    starting: "启动中",
    stopping: "停止中",
    failed: "服务异常",
    stopped: "服务停止",
  }[serviceState] || serviceState || "服务停止";
}

function ensureSelectedManagementModelId(models = normalizeModels(state.models)) {
  if (!models.length) {
    state.selectedManagementModelId = "";
    return "";
  }
  const selectedId = String(state.selectedManagementModelId || "");
  if (selectedId && models.some((model) => String(model.id || "") === selectedId)) {
    return selectedId;
  }
  const activeId = String(state.activeModelId || "");
  const nextId = (activeId && models.some((model) => String(model.id || "") === activeId))
    ? activeId
    : String(models[0]?.id || "");
  state.selectedManagementModelId = nextId;
  return nextId;
}

function selectedManagementModelId() {
  return ensureSelectedManagementModelId();
}

function selectedManagementModel() {
  const modelId = selectedManagementModelId();
  return normalizeModels(state.models).find((model) => String(model.id || "") === modelId) || null;
}

function updateModelContextMenuActions() {
  const models = normalizeModels(state.models);
  const selected = selectedManagementModel();
  const hasSelected = Boolean(selected);
  const clockState = selected ? modelClockState(selected) : "";
  const serviceState = String(selected?.service?.state || "stopped");
  const menu = $("modelContextMenu");
  const serviceButton = menu?.querySelector('[data-model-context-action="service-toggle"]');
  const exportButton = menu?.querySelector('[data-model-context-action="export"]');
  const cloneButton = menu?.querySelector('[data-model-context-action="clone"]');
  const updateButton = menu?.querySelector('[data-model-context-action="update"]');
  const deleteButton = menu?.querySelector('[data-model-context-action="delete"]');
  if (serviceButton) {
    const running = serviceState === "running";
    const transitioning = serviceState === "starting" || serviceState === "stopping";
    serviceButton.textContent = serviceState === "starting"
      ? "启动中"
      : (serviceState === "stopping" ? "停止中" : (running ? "停止" : "启动"));
    serviceButton.disabled = !hasSelected || state.modelServiceOperationActive || transitioning;
    serviceButton.title = !hasSelected
      ? "请选择模型"
      : (transitioning
        ? modelServiceStateText(serviceState)
        : `${running ? "停止" : "启动"} ${selected.name || selected.id || "选中模型"}的模拟服务`);
  }
  if (exportButton) exportButton.disabled = !hasSelected;
  if (cloneButton) cloneButton.disabled = !hasSelected;
  if (updateButton) {
    const canUpdate = hasSelected && (
      clockState === "stopped"
      || (serviceState === "running" && clockState === "unknown")
    );
    updateButton.disabled = !canUpdate;
    updateButton.title = !hasSelected
      ? "请选择模型"
      : (clockState === "stopped"
        ? "导入修改后的模型与图形数据"
        : (canUpdate ? "打开后核实仿真时钟状态" : "模型运行中或暂停中，不能修改"));
  }
  if (deleteButton) {
    const canDelete = hasSelected && models.length > 1 && clockState === "stopped";
    deleteButton.disabled = !canDelete;
    deleteButton.title = !hasSelected
      ? "请选择模型"
      : (models.length <= 1
        ? "至少需要保留一个模型"
        : (clockState === "stopped" ? "删除选中的模型" : "模型运行中或暂停中，不能删除"));
  }
}

function setSelectedManagementModel(modelId, render = true) {
  state.selectedManagementModelId = String(modelId || "");
  ensureSelectedManagementModelId();
  updateModelContextMenuActions();
  if (render) renderModelManagementList();
}

function renderModelManagementList() {
  const list = $("modelManagementList");
  if (!list) return;
  const models = normalizeModels(state.models);
  if (!models.length) {
    list.innerHTML = '<div class="model-management-empty">暂无模型</div>';
    state.selectedManagementModelId = "";
    updateModelContextMenuActions();
    return;
  }
  const selectedId = ensureSelectedManagementModelId(models);
  const branchHtml = models.map((model) => {
    const modelId = String(model.id || "");
    const isActive = modelId === state.activeModelId;
    const isSelected = modelId === selectedId;
    const serviceState = String(model?.service?.state || "stopped");
    const endpoint = modelServiceEndpoint(model);
    return `
      <div
        class="model-management-item ${isActive ? "is-active" : ""} ${isSelected ? "is-selected" : ""}"
        role="treeitem"
        tabindex="0"
        aria-selected="${isSelected ? "true" : "false"}"
        data-model-id="${escapeHtml(modelId)}"
      >
        <span class="model-management-node-mark" aria-hidden="true"></span>
        <div class="model-node-main">
          <strong class="model-node-name">${escapeHtml(model.name || modelId)}</strong>
          <span class="model-service-address" title="${escapeHtml(model?.service?.base_url || endpoint.accessLink)}">${escapeHtml(endpoint.accessLink)}</span>
        </div>
        <div class="model-item-badges">
          ${isActive ? '<span class="model-current-pill">当前</span>' : ""}
          <span class="model-service-state-pill" data-state="${escapeHtml(serviceState)}">${escapeHtml(modelServiceStateText(serviceState))}</span>
        </div>
      </div>
    `;
  }).join("");
  list.innerHTML = `
    <div class="model-management-tree-root" role="treeitem" aria-expanded="true">
      <span class="model-management-root-caret" aria-hidden="true">▾</span>
      <strong>模型列表</strong>
      <small>${models.length} 个</small>
    </div>
    <div class="model-management-branches" role="group">
      ${branchHtml}
    </div>
  `;
  updateModelContextMenuActions();
}

async function openModelManagementDialog() {
  const dialog = $("modelManagementDialog");
  if (!dialog) return;
  dialog.hidden = false;
  setModelManagementMessage("正在读取模型列表...");
  try {
    await loadModels();
    ensureSelectedManagementModelId();
    renderModelManagementList();
    setModelManagementMessage(`共 ${state.models.length} 个模型，右键模型节点可操作。`, "ok");
  } catch (error) {
    renderModelManagementList();
    setModelManagementMessage(apiErrorText(error), "error");
  }
}

function closeModelManagementDialog() {
  closeModelContextMenu();
  const dialog = $("modelManagementDialog");
  if (dialog) dialog.hidden = true;
  setModelManagementMessage("");
}

function populateServiceHostPreset(presetId, inputId, currentHost) {
  const select = $(presetId);
  const input = $(inputId);
  if (!select || !input) return;
  const hostValue = String(currentHost || input.value || "127.0.0.1").trim() || "127.0.0.1";
  const presets = [
    ["127.0.0.1", "127.0.0.1（本机回环）"],
    ["localhost", "localhost"],
    ["0.0.0.0", "0.0.0.0（全部网卡）"],
  ];
  const seen = new Set(presets.map(([v]) => v));
  for (const model of state.models || []) {
    const h = String(model?.service?.host || "").trim();
    if (h && !seen.has(h)) {
      seen.add(h);
      presets.push([h, h]);
    }
  }
  const options = presets.map(([v, label]) => new Option(label, v));
  options.push(new Option("自定义地址...", "__custom__"));
  select.replaceChildren(...options);
  if (seen.has(hostValue)) {
    select.value = hostValue;
    input.value = hostValue;
    input.hidden = true;
  } else {
    select.value = "__custom__";
    input.value = hostValue;
    input.hidden = false;
  }
}

function handleServiceHostPresetChange(presetId, inputId, onUpdated) {
  const select = $(presetId);
  const input = $(inputId);
  if (!select || !input) return;
  const isCustom = select.value === "__custom__";
  input.hidden = !isCustom;
  if (!isCustom) {
    input.value = select.value;
  } else {
    input.focus();
    input.select();
  }
  if (typeof onUpdated === "function") onUpdated();
}

function openNewModelDialog() {
  const dialog = $("newModelDialog");
  const input = $("newModelName");
  const filename = $("newModelFilename");
  const svgFilename = $("newModelSvgFilename");
  const fileInput = $("newModelFileInput");
  const svgInput = $("newModelSvgInput");
  const hostInput = $("newModelServiceHost");
  const portInput = $("newModelServicePort");
  if (!dialog || !input) return;
  pendingNewModelFile = null;
  pendingNewModelSvgFile = null;
  newModelCreationComplete = false;
  renderModelPreflightResult("newModel", null);
  if (fileInput) fileInput.value = "";
  if (svgInput) svgInput.value = "";
  if (filename) filename.textContent = "未选择文件";
  if (svgFilename) svgFilename.textContent = "未选择图形";
  input.value = uniqueNewModelName("新模型");
  if (hostInput) hostInput.value = state.serviceSuggestion.host || "127.0.0.1";
  populateServiceHostPreset("newModelServiceHostPreset", "newModelServiceHost", hostInput?.value);
  if (portInput) portInput.value = String(state.serviceSuggestion.port || 8711);
  updateServiceAddressPreview("newModelServiceHost", "newModelServicePort", "newModelServicePreview");
  dialog.hidden = false;
  validateNewModelForm();
  const initialHost = String(hostInput?.value || "");
  const initialPort = String(portInput?.value || "");
  api("/api/simulator-services/suggestion", {
    modelScoped: false,
    controlPlane: true,
    timeoutMs: 3000,
  }).then((result) => {
    captureServiceSuggestion(result);
    if (dialog.hidden) return;
    if (String(hostInput?.value || "") !== initialHost || String(portInput?.value || "") !== initialPort) return;
    if (hostInput) hostInput.value = state.serviceSuggestion.host || "127.0.0.1";
    populateServiceHostPreset("newModelServiceHostPreset", "newModelServiceHost", hostInput?.value);
    if (portInput) portInput.value = String(state.serviceSuggestion.port || 8711);
    updateServiceAddressPreview("newModelServiceHost", "newModelServicePort", "newModelServicePreview");
    validateNewModelForm();
  }).catch(() => {});
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

function closeNewModelDialog() {
  const dialog = $("newModelDialog");
  if (dialog) dialog.hidden = true;
  pendingNewModelFile = null;
  pendingNewModelSvgFile = null;
  newModelCreationComplete = false;
  renderModelPreflightResult("newModel", null);
  const fileInput = $("newModelFileInput");
  const svgInput = $("newModelSvgInput");
  const filename = $("newModelFilename");
  const svgFilename = $("newModelSvgFilename");
  if (fileInput) fileInput.value = "";
  if (svgInput) svgInput.value = "";
  if (filename) filename.textContent = "未选择文件";
  if (svgFilename) svgFilename.textContent = "未选择图形";
  setNewModelMessage("");
  setNewModelBusy(false);
}

function handleNewModelFileSelected(event) {
  invalidateModelPreflight("newModel");
  const file = event.target.files?.[0] || null;
  pendingNewModelFile = file;
  const filename = $("newModelFilename");
  if (filename) filename.textContent = file?.name || "未选择文件";
  const input = $("newModelName");
  if (file && input && !String(input.value || "").trim()) {
    input.value = suggestedNewModelName(file.name);
  }
  validateNewModelForm(Boolean(file));
}

function handleNewModelSvgFileSelected(event) {
  invalidateModelPreflight("newModel");
  const file = event.target.files?.[0] || null;
  pendingNewModelSvgFile = file;
  const filename = $("newModelSvgFilename");
  if (filename) filename.textContent = file?.name || "未选择图形";
  if (file && !String(file.name || "").toLowerCase().endsWith(".svg")) {
    setNewModelMessage("请选择 .svg 格式的接线图文件。", "error");
    const confirm = $("confirmNewModel");
    if (confirm) confirm.disabled = true;
    return;
  }
  validateNewModelForm(Boolean(pendingNewModelFile));
}

async function createNewModelFromFile() {
  if (newModelCreationActive) return;
  const file = pendingNewModelFile;
  const input = $("newModelName");
  const name = String(input?.value || "").trim();
  const serviceAddress = validateServiceAddressInputs("newModelServiceHost", "newModelServicePort");
  if (!file || !validateNewModelForm(true)) {
    input?.focus();
    return;
  }
  newModelCreationActive = true;
  renderModelPreflightResult("newModel", null);
  setNewModelBusy(true);
  setNewModelMessage("正在预校核必要字段、E/SVG 匹配性和潮流收敛性；通过后才正式写入...");
  try {
    const dataBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const diagramSvgBase64 = pendingNewModelSvgFile
      ? arrayBufferToBase64(await pendingNewModelSvgFile.arrayBuffer())
      : "";
    const result = await controlPlaneApi("/api/models/create", {
      method: "POST",
      body: JSON.stringify({
        name,
        service_host: serviceAddress.host,
        service_port: serviceAddress.port,
        filename: file.name,
        data_base64: dataBase64,
        diagram_filename: pendingNewModelSvgFile?.name || "",
        diagram_svg_base64: diagramSvgBase64,
      }),
    });
    captureServiceSuggestion(result);
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.active_model_id || name;
    renderModelPreflightResult("newModel", result.validation);
    newModelCreationComplete = true;
    state.selectedManagementModelId = newModelId;
    renderModelSelector();
    renderModelManagementList();
    setNewModelMessage("模型预校核通过并已正式新建。", "ok");
    setModelManagementMessage("模型预校核通过并已正式新建。", "ok");
  } catch (error) {
    renderModelPreflightResult("newModel", apiErrorPayload(error)?.validation);
    const message = apiErrorText(error);
    if (message.includes("已存在")) await loadModels();
    setNewModelMessage(
      message.includes("已存在") ? `${message}，请输入新的模型名称。` : message,
      "error",
    );
  } finally {
    newModelCreationActive = false;
    setNewModelBusy(false);
    if (!newModelCreationComplete && !$("newModelDialog").hidden) validateNewModelForm();
  }
}

function setUpdateModelMessage(text, kind = "") {
  const message = $("updateModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function setUpdateModelBusy(isBusy) {
  const confirm = $("confirmUpdateModel");
  const selectFile = $("selectUpdateModelFile");
  const selectSvg = $("selectUpdateModelSvgFile");
  const hostInput = $("updateModelServiceHost");
  const portInput = $("updateModelServicePort");
  const cancel = $("cancelUpdateModel");
  const disabled = isBusy || updateModelSaveComplete;
  if (confirm) {
    confirm.disabled = disabled;
    confirm.textContent = updateModelSaveComplete ? "已修改" : (isBusy ? "预校核中" : "确认");
  }
  if (selectFile) selectFile.disabled = disabled;
  if (selectSvg) selectSvg.disabled = disabled;
  if (hostInput) hostInput.disabled = disabled;
  if (portInput) portInput.disabled = disabled;
  if (cancel) cancel.textContent = updateModelSaveComplete ? "关闭" : "取消";
}

function formatSelectedModelFile(file) {
  if (!file) return "";
  const size = Number(file.size);
  let sizeText = "";
  if (Number.isFinite(size) && size >= 0) {
    sizeText = size < 1024
      ? `${size} B`
      : size < 1024 * 1024
        ? `${(size / 1024).toFixed(1)} KB`
        : `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  return [String(file.name || "").trim(), sizeText].filter(Boolean).join(" · ");
}

function renderPendingUpdateModelFiles() {
  const filename = $("updateModelFilename");
  const svgFilename = $("updateModelSvgFilename");
  if (filename) {
    filename.textContent = pendingUpdateModelFile
      ? formatSelectedModelFile(pendingUpdateModelFile)
      : "未选择，保持当前文件";
  }
  if (svgFilename) {
    svgFilename.textContent = pendingUpdateModelSvgFile
      ? formatSelectedModelFile(pendingUpdateModelSvgFile)
      : "未选择，保持当前图形";
  }
}

function updateModelSelectionMessage() {
  if (pendingUpdateModelFile && pendingUpdateModelSvgFile) {
    return `已选择 E 文件“${pendingUpdateModelFile.name}”和 SVG 图“${pendingUpdateModelSvgFile.name}”，确认后导入。`;
  }
  if (pendingUpdateModelFile) {
    return `已选择 E 文件“${pendingUpdateModelFile.name}”；SVG 图保持不变。`;
  }
  if (pendingUpdateModelSvgFile) {
    return `已选择 SVG 图“${pendingUpdateModelSvgFile.name}”；E 文件保持不变。`;
  }
  return "未选择新文件，仅保存访问链接。";
}

function openUpdateModelFilePicker(inputId) {
  const input = $(inputId);
  if (!(input instanceof HTMLInputElement)) return;
  // Clear the native input so selecting the same file again still emits change.
  input.value = "";
  input.click();
}

function validateUpdateModelForm(showSelection = false) {
  const confirm = $("confirmUpdateModel");
  const hostInput = $("updateModelServiceHost");
  const portInput = $("updateModelServicePort");
  if (updateModelSaveComplete) {
    if (confirm) confirm.disabled = true;
    return true;
  }
  hostInput?.removeAttribute("aria-invalid");
  portInput?.removeAttribute("aria-invalid");
  const target = state.models.find((model) => model.id === state.updateTargetModelId);
  if (!target) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("请选择要修改的模型。", "error");
    return false;
  }
  if (modelClockState(target) !== "stopped") {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("模型运行中或暂停中，不能修改。", "error");
    return false;
  }
  const serviceAddress = validateServiceAddressInputs("updateModelServiceHost", "updateModelServicePort");
  updateServiceAddressPreview("updateModelServiceHost", "updateModelServicePort", "updateModelServicePreview");
  if (!serviceAddress.ok) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage(serviceAddress.message, "error");
    return false;
  }
  if (pendingUpdateModelFile && !String(pendingUpdateModelFile.name || "").toLowerCase().endsWith(".e")) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("请选择 .e 格式的模型定义文件。", "error");
    return false;
  }
  if (pendingUpdateModelSvgFile && !String(pendingUpdateModelSvgFile.name || "").toLowerCase().endsWith(".svg")) {
    if (confirm) confirm.disabled = true;
    setUpdateModelMessage("请选择 .svg 格式的接线图文件。", "error");
    return false;
  }
  if (confirm) confirm.disabled = false;
  setUpdateModelMessage(showSelection ? updateModelSelectionMessage() : "");
  return true;
}

async function openUpdateModelDialog(modelId = selectedManagementModelId()) {
  const target = normalizeModels(state.models).find((model) => String(model.id || "") === String(modelId || ""));
  if (!target) {
    setModelManagementMessage("请选择要修改的模型。", "error");
    return;
  }
  let refreshedTarget = target;
  const serviceBase = String(target?.service?.base_url || "").replace(/\/$/, "");
  if (String(target?.service?.state || "") === "running" && serviceBase) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000);
    try {
      const response = await fetch(
        `${serviceBase}/api/snapshot?lite=1&static=0&static_meta=0&measurements=0&devices=0&device_states=0&logs=0&commands=0`,
        {
          headers: { Accept: "application/json" },
          cache: "no-store",
          signal: controller.signal,
        },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const snapshot = await response.json();
      refreshedTarget = {
        ...target,
        clock_state: String(snapshot?.clock?.state || "unknown"),
      };
      state.models = normalizeModels(state.models).map((model) => (
        String(model.id || "") === String(modelId || "") ? refreshedTarget : model
      ));
    } catch (error) {
      setModelManagementMessage(`无法核实模型仿真时钟状态：${apiErrorText(error)}`, "error");
      return;
    } finally {
      clearTimeout(timeoutId);
    }
  }
  if (modelClockState(refreshedTarget) !== "stopped") {
    setModelManagementMessage("模型运行中或暂停中，不能修改。", "error");
    return;
  }
  state.updateTargetModelId = String(refreshedTarget.id || "");
  pendingUpdateModelFile = null;
  pendingUpdateModelSvgFile = null;
  updateModelSaveComplete = false;
  renderModelPreflightResult("updateModel", null);
  const dialog = $("updateModelDialog");
  if (!dialog) return;
  const fileInput = $("updateModelFileInput");
  const svgInput = $("updateModelSvgInput");
  const hostInput = $("updateModelServiceHost");
  const portInput = $("updateModelServicePort");
  if (fileInput) fileInput.value = "";
  if (svgInput) svgInput.value = "";
  $("updateModelTargetName").textContent = refreshedTarget.name || refreshedTarget.id || "--";
  renderPendingUpdateModelFiles();
  const endpoint = modelServiceEndpoint(refreshedTarget);
  if (hostInput) hostInput.value = endpoint.host;
  populateServiceHostPreset("updateModelServiceHostPreset", "updateModelServiceHost", endpoint.host);
  if (portInput) portInput.value = String(endpoint.port || "");
  updateServiceAddressPreview("updateModelServiceHost", "updateModelServicePort", "updateModelServicePreview");
  dialog.hidden = false;
  validateUpdateModelForm();
}

function closeUpdateModelDialog() {
  const dialog = $("updateModelDialog");
  if (dialog) dialog.hidden = true;
  state.updateTargetModelId = "";
  pendingUpdateModelFile = null;
  pendingUpdateModelSvgFile = null;
  updateModelSaveComplete = false;
  renderModelPreflightResult("updateModel", null);
  const fileInput = $("updateModelFileInput");
  const svgInput = $("updateModelSvgInput");
  if (fileInput) fileInput.value = "";
  if (svgInput) svgInput.value = "";
  setUpdateModelMessage("");
  setUpdateModelBusy(false);
}

function handleUpdateModelFileSelected(event) {
  invalidateModelPreflight("updateModel");
  const file = event.currentTarget?.files?.[0] || null;
  pendingUpdateModelFile = file;
  renderPendingUpdateModelFiles();
  validateUpdateModelForm(true);
}

function handleUpdateModelSvgFileSelected(event) {
  invalidateModelPreflight("updateModel");
  const file = event.currentTarget?.files?.[0] || null;
  pendingUpdateModelSvgFile = file;
  renderPendingUpdateModelFiles();
  validateUpdateModelForm(true);
}

async function updateModelFromFile() {
  const file = pendingUpdateModelFile;
  const diagramFile = pendingUpdateModelSvgFile;
  const modelId = state.updateTargetModelId;
  const serviceAddress = validateServiceAddressInputs("updateModelServiceHost", "updateModelServicePort");
  if (!validateUpdateModelForm(true)) return;
  const updatedActiveModel = String(modelId || "") === String(state.activeModelId || "");
  let updateFailed = false;
  let invalidServiceAddress = false;
  const needsPreflight = Boolean(file || diagramFile);
  if (needsPreflight) renderModelPreflightResult("updateModel", null);
  setUpdateModelBusy(true);
  if (file || diagramFile) setUpdateModelMessage("正在预校核必要字段、E/SVG 匹配性和潮流收敛性；通过后才正式写入...");
  else setUpdateModelMessage("正在保存访问链接...");
  try {
    const dataBase64 = file ? arrayBufferToBase64(await file.arrayBuffer()) : "";
    const diagramSvgBase64 = diagramFile
      ? arrayBufferToBase64(await diagramFile.arrayBuffer())
      : "";
    const payload = {
      model_id: modelId,
      service_host: serviceAddress.host,
      service_port: serviceAddress.port,
      restart_service: Boolean(file || diagramFile),
    };
    if (file) {
      payload.filename = file.name;
      payload.data_base64 = dataBase64;
    }
    if (diagramFile) {
      payload.diagram_filename = diagramFile.name;
      payload.diagram_svg_base64 = diagramSvgBase64;
    }
    const result = await api("/api/models/update-definitions", {
      modelScoped: false,
      controlPlane: true,
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (Array.isArray(result.models)) {
      state.models = normalizeModels(result.models);
    } else if (result.model) {
      const updatedModel = normalizeModels([result.model])[0];
      if (updatedModel) {
        let replaced = false;
        state.models = state.models.map((model) => {
          if (model.id !== updatedModel.id) return model;
          replaced = true;
          return updatedModel;
        });
        if (!replaced) state.models.push(updatedModel);
      }
    }
    state.selectedManagementModelId = modelId;
    renderModelSelector();
    renderModelManagementList();
    const serviceRestarted = result.updated?.service_restart?.restarted === true;
    setModelManagementMessage(
      file || diagramFile
        ? `模型已修改${serviceRestarted ? "，模拟服务已自动重启" : ""}。`
        : `访问链接已修改${serviceRestarted ? "，模拟服务已自动重启" : ""}。`,
      "ok",
    );
    if (needsPreflight) {
      renderModelPreflightResult("updateModel", result.validation);
      updateModelSaveComplete = true;
      setUpdateModelMessage("模型预校核通过并已正式修改。", "ok");
    } else {
      closeUpdateModelDialog();
    }
    if (updatedActiveModel && (file || diagramFile)) {
      invalidateManualDefinitionChanges();
      if (currentPageName() === "manual-changes") loadManualDefinitionChanges();
      await refresh();
    }
  } catch (error) {
    updateFailed = true;
    if (needsPreflight) {
      renderModelPreflightResult("updateModel", apiErrorPayload(error)?.validation);
    }
    const message = apiErrorText(error);
    setUpdateModelMessage(`保存失败：${message}`, "error");
    if (message.includes("已分配给模型") || message.includes("不同模型不能共用同一 IP 和端口")) {
      invalidServiceAddress = true;
      const portInput = $("updateModelServicePort");
      portInput?.setAttribute("aria-invalid", "true");
    }
  } finally {
    setUpdateModelBusy(false);
    if (invalidServiceAddress) {
      const portInput = $("updateModelServicePort");
      portInput?.focus();
      portInput?.select();
    }
    if (!updateFailed && !$("updateModelDialog").hidden) {
      if (!updateModelSaveComplete) validateUpdateModelForm();
    }
  }
}

function setCloneModelMessage(text, kind = "") {
  const message = $("cloneModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function setCloneConfirmEnabled(isEnabled) {
  const confirm = $("confirmCloneModel");
  if (confirm) confirm.disabled = !isEnabled;
}

function validateCloneModelName(showBlank = false) {
  const input = $("cloneModelName");
  const name = String(input?.value || "").trim();
  if (!name) {
    setCloneConfirmEnabled(false);
    setCloneModelMessage(showBlank ? "请输入新模型名称。" : "", showBlank ? "error" : "");
    return false;
  }
  if (isModelNameTaken(name)) {
    setCloneConfirmEnabled(false);
    setCloneModelMessage(`模型已存在：${name}`, "error");
    return false;
  }
  setCloneConfirmEnabled(true);
  setCloneModelMessage("");
  return true;
}

function openCloneModelDialog(sourceModelId = "") {
  const dialog = $("cloneModelDialog");
  const input = $("cloneModelName");
  if (!dialog || !input) return;
  state.cloneSourceModelId = sourceModelId || state.activeModelId || "";
  const source = state.models.find((model) => model.id === state.cloneSourceModelId) || activeModelInfo();
  const base = String(source.name || source.id || "model").replace(/\s+/g, "_");
  input.value = uniqueCloneName(base);
  validateCloneModelName();
  dialog.hidden = false;
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

function closeCloneModelDialog() {
  const dialog = $("cloneModelDialog");
  if (dialog) dialog.hidden = true;
  state.cloneSourceModelId = "";
}

