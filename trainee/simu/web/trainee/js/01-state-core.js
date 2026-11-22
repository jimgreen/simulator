// 学员端模块：全局状态、运行参数、静态缓存与通讯核心（01-state-core.js）
const apiBase = (window.POLAR_SIM_API_URL || localStorage.getItem("polarSimApiUrl") || location.origin).replace(/\/$/, "");
const MODEL_CONTEXTS_STORAGE_KEY = "polarTraineeModelContexts";
const OVERVIEW_BOTTOM_HEIGHT_KEY = "polarTraineeOverviewBottomHeight";
const OVERVIEW_BOTTOM_DEFAULT_HEIGHT = 156;
const OVERVIEW_BOTTOM_MIN_HEIGHT = 96;
const OVERVIEW_BOTTOM_MAX_HEIGHT = 640;
const OVERVIEW_BOTTOM_COLUMN_RATIO_KEY = "polarTraineeOverviewBottomColumnRatio";
const OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO = 50;
const OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX = 260;
const VERTICAL_SPLIT_STORAGE_KEY = "polarTraineeVerticalSplitRatios";
const VERTICAL_SPLIT_DEFAULTS = {
  "trainee-curves": 60,
  "trainee-measurements": 52,
  "trainee-commands": 56,
  "trainee-renewable": 44,
};
const VERTICAL_SPLIT_DEFAULT_RATIO = 55;
const VERTICAL_SPLIT_MIN_TOP_PX = 120;
const VERTICAL_SPLIT_MIN_BOTTOM_PX = 120;
const STATIC_CACHE_STORAGE_KEY = "polarTraineeStaticCacheV2";
const STATIC_CACHE_MODEL_LIMIT = 4;
const CURVE_DISPLAY_TREE_COLLAPSE_KEY = "polarTraineeCurveTreeCollapsedGroups";
const RUNTIME_LOG_COLUMN_WIDTHS_KEY = "polarTraineeRuntimeLogColumnWidths";
const RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS = Object.freeze([104, 104, 112, 190, 104, 640]);
const RUNTIME_LOG_COLUMN_MIN_WIDTHS = Object.freeze([82, 82, 78, 110, 78, 180]);
const HIDDEN_REFRESH_INTERVAL_MS = 10000;
const MODEL_CONTEXT_PERSIST_INTERVAL_MS = 5000;
const WEB_RUNTIME_FALLBACKS = {
  frontend_refresh_seconds: 1,
  frontend_request_timeout_seconds: 30,
  runtime_log_page_size: 20,
  runtime_log_cache_limit: 300,
  backend_refresh_seconds: 1,
  backend_request_timeout_seconds: 8,
  frame_age_limit_seconds: 15,
  same_frame_limit_seconds: 30,
  receive_state_sync_seconds: 5,
  receive_max_reconnect_attempts: 3,
  measurement_delta_history_limit: 200,
  diagram_flow_electric_threshold_kw: 0.1,
  diagram_flow_hydrogen_threshold_nm3_h: 0.1,
};
const WEB_RUNTIME_CURRENT_IDS = {
  frontend_refresh_seconds: "currentWebRuntimeFrontendRefresh",
  frontend_request_timeout_seconds: "currentWebRuntimeFrontendRequestTimeout",
  runtime_log_page_size: "currentWebRuntimeLogPageSize",
  runtime_log_cache_limit: "currentWebRuntimeLogCacheLimit",
  backend_refresh_seconds: "currentBackendRuntimeRefresh",
  backend_request_timeout_seconds: "currentBackendRuntimeRequestTimeout",
  frame_age_limit_seconds: "currentBackendRuntimeFrameAgeLimit",
  same_frame_limit_seconds: "currentBackendRuntimeSameFrameLimit",
  receive_state_sync_seconds: "currentWebRuntimeReceiveStateSync",
  receive_max_reconnect_attempts: "currentBackendRuntimeReconnectAttempts",
  measurement_delta_history_limit: "currentBackendRuntimeMeasurementDeltaHistoryLimit",
  diagram_flow_electric_threshold_kw: "currentWebRuntimeDiagramElectricFlowThreshold",
  diagram_flow_hydrogen_threshold_nm3_h: "currentWebRuntimeDiagramHydrogenFlowThreshold",
};
const RUNTIME_PARAMETER_GROUPS = Object.freeze({
  backend: Object.freeze([
    "backend_refresh_seconds",
    "backend_request_timeout_seconds",
    "frame_age_limit_seconds",
    "same_frame_limit_seconds",
    "receive_max_reconnect_attempts",
    "measurement_delta_history_limit",
  ]),
  web: Object.freeze([
    "frontend_refresh_seconds",
    "frontend_request_timeout_seconds",
    "runtime_log_page_size",
    "runtime_log_cache_limit",
    "receive_state_sync_seconds",
    "diagram_flow_electric_threshold_kw",
    "diagram_flow_hydrogen_threshold_nm3_h",
  ]),
});
const DEFAULT_STORAGE_CHARGE_DERATING_CURVE = Object.freeze([
  { soc: 0.60, powerRatio: 1.00 },
  { soc: 0.70, powerRatio: 0.50 },
  { soc: 0.80, powerRatio: 0.30 },
  { soc: 0.85, powerRatio: 0.15 },
  { soc: 0.90, powerRatio: 0.00 },
]);
const DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE = Object.freeze([
  { soc: 0.10, powerRatio: 0.00 },
  { soc: 0.15, powerRatio: 0.15 },
  { soc: 0.20, powerRatio: 0.30 },
  { soc: 0.30, powerRatio: 0.50 },
  { soc: 0.40, powerRatio: 1.00 },
]);

function readStoredModelContexts() {
  let contexts = {};
  try {
    const parsed = JSON.parse(localStorage.getItem(MODEL_CONTEXTS_STORAGE_KEY) || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) contexts = parsed;
  } catch (_error) {
    contexts = {};
  }
  const legacyModelId = localStorage.getItem("polarTraineeModelId") || "";
  const legacyLink = localStorage.getItem("polarTeacherInteractionLink") || "";
  if (legacyModelId && legacyLink && !contexts[legacyModelId]) {
    contexts[legacyModelId] = {
      interactionLink: legacyLink,
      teacherApiBase: (localStorage.getItem("polarTeacherApiUrl") || "").replace(/\/$/, ""),
      teacherModelName: localStorage.getItem("polarTeacherModelName") || legacyModelId,
      teacherSnapshotPath: localStorage.getItem("polarTeacherSnapshotPath") || "",
      teacherCommandPath: localStorage.getItem("polarTeacherCommandPath") || "",
      teacherMeasurementDeltaPath: localStorage.getItem("polarTeacherMeasurementDeltaPath") || "",
      receiveMode: false,
      frozen: false,
    };
  }
  return contexts;
}

function readStoredRuntimeLogColumnWidths() {
  try {
    const stored = JSON.parse(localStorage.getItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY) || "[]");
    if (Array.isArray(stored) && stored.length === RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS.length) {
      return stored.map((value, index) => Math.max(
        RUNTIME_LOG_COLUMN_MIN_WIDTHS[index],
        Number(value) || RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS[index],
      ));
    }
  } catch (_error) {
    // Invalid local UI state falls back to the default widths.
  }
  return [...RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS];
}

function readStoredCurveDisplayTreeCollapsedGroups() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CURVE_DISPLAY_TREE_COLLAPSE_KEY) || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
  } catch (_error) {
    // Invalid local UI state falls back to the default expanded tree.
  }
  return {};
}

function initialVerticalSplitRatios() {
  const ratios = { ...VERTICAL_SPLIT_DEFAULTS };
  try {
    const stored = JSON.parse(localStorage.getItem(VERTICAL_SPLIT_STORAGE_KEY) || "{}");
    Object.entries(stored || {}).forEach(([splitId, ratio]) => {
      const numericRatio = Number(ratio);
      if (Number.isFinite(numericRatio)) ratios[splitId] = numericRatio;
    });
  } catch (error) {
    localStorage.removeItem(VERTICAL_SPLIT_STORAGE_KEY);
  }
  return ratios;
}

const state = {
  snapshot: null,
  activePage: "",
  pageSections: {},
  pageMain: null,
  models: [],
  activeModelId: localStorage.getItem("polarTraineeModelId") || "",
  modelContexts: readStoredModelContexts(),
  modelInitialized: false,
  modelInitializedAt: "",
  receiveMode: false,
  frozen: false,
  receiveEpoch: 0,
  lastReceiveAt: "",
  receiveStateRevision: "",
  snapshotSource: "",
  lastTeacherSnapshotLogKey: "",
  interactionLink: "",
  teacherApiBase: "",
  teacherModelId: "",
  teacherModelName: "",
  teacherSnapshotPath: "",
  teacherCommandPath: "",
  teacherMeasurementDeltaPath: "",
  teacherDefinitionArchivePath: "",
  localDefinitionSnapshot: null,
  localDefinitionModelId: "",
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
  receiveReconnectAttempts: 0,
  receiveTransportFailureCount: 0,
  receiveTransportInterrupted: false,
  refreshConsecutiveFailures: 0,
  renewableParametersDirty: false,
  renewablePresetApplying: false,
  refreshRequestActive: false,
  receiveRequestActive: false,
  receiveStateSyncActive: false,
  lastReceiveStateSyncAtMs: 0,
  definitionMismatchLastKey: "",
  runtimeLogs: [],
  runtimeLogColumnWidths: readStoredRuntimeLogColumnWidths(),
  runtimeLogTypeFilter: "all",
  runtimeLogPage: 1,
  runtimeLogPageSize: 20,
  runtimeLogSeq: 0,
  runtimeLogSelectedSeq: 0,
  seenCommandHistoryKeys: new Set(),
  selectedManagementModelId: "",
  modelLifecycleOperationActive: false,
  cloneSourceModelId: "",
  modelFilter: { dev_type: "all", dev_name: "" },
  activeModelParamTab: "",
  activeCurveDisplayKey: "wind_speed_mps",
  selectedCurveDisplayKeys: ["wind_speed_mps"],
  hiddenCurveDisplayKeys: [],
  curveDisplayTreeSearch: "",
  curveDisplayTreeGroupCollapsed: readStoredCurveDisplayTreeCollapsedGroups(),
  curveDisplaySeriesCache: new WeakMap(),
  curveDisplayCursor: { visible: false, x: 0, y: 0, index: 0 },
  curveDisplayLegendHitBoxes: [],
  lastCurveDisplayRenderKey: "",
  lastCurveDisplayTableKey: "",
  remoteControlDevice: null,
  remoteControlSending: false,
  remoteAdjustment: null,
  remoteAdjustmentSending: false,
  diagramDeviceCommandContext: null,
  commandCancelSending: new Set(),
  measurementFilter: { dev_type: "all", dev_name: "" },
  measurementKeywordFilter: "",
  measurementTypeFilter: "all",
  measurementDeltaSeq: 0,
  measurementDeltaRequestActive: false,
  embeddedMeasurementDeltaReceived: false,
  measurementArrayWarning: "",
  controlFilter: { dev_type: "all", dev_name: "" },
  commandKeywordFilter: "",
  commandTypeFilter: "all",
  commandOriginFilter: "all",
  commandOnlyActive: false,
  activeControlTab: "remote-control",
  selectedCommandTraceKey: "",
  selectedCommandTraceLabel: "",
  commandTraceHistory: [],
  commandTraceWindowMinutes: 60,
  chartSeriesHidden: {},
  chartSeriesSelected: {},
  chartCursors: {},
  chartSeriesHitData: {},
  chartPlotInfo: {},
  chartPeriodOffsets: { measurementTrace: 0, commandTrace: 0, renewableTrend: 0 },
  collapsedDeviceTreeGroups: {},
  deviceTreeSearch: {},
  activeMeasurementTab: "telemetry",
  selectedMeasurementKey: "",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
  lastMeasurementTraceKey: "",
  measurementHistoryLoaded: {},
  measurementHistoryRequests: {},
  measurementHistoryGeneration: 0,
  renewableTrendHistory: [],
  renewableTrendFieldCursors: {},
  renewableTrendHistoryRequests: {},
  renewableTrendHistoryGeneration: 0,
  renewableTrendWindowMinutes: 60,
  renewableTrendSeriesFilter: "",
  renewableTrendSelectedOnly: false,
  chartLegendSeriesHidden: {},
  traceRunId: null,
  traceStepCount: null,
  renewableControl: {
    modelId: "",
    controllerInstanceId: "",
    enabled: false,
    desiredEnabled: false,
    resumePending: false,
    runState: "stopped",
    controlFrozen: false,
    simulationPaused: false,
    receiveActive: false,
    canRun: false,
    prerequisiteStatus: "请先启动接收。",
    loopMode: "open",
    intervalSeconds: 2,
    largeStepThresholdKw: 10,
    stepCoefficient: 0.03,
    storageStepRatio: 0.03,
    storageSocCorrectionStepScale: 0.2,
    gridFormingStorageProtectionRatio: 0.05,
    dieselPowerProtectionRatio: 0.03,
    socDeadband: 0.05,
    hydrogenClosedLoopEnabled: true,
    hydrogenPressureDeadbandRatio: 0.05,
    electrolyzerPowerMinRatio: 0.20,
    electrolyzerPowerMaxRatio: 0.90,
    electrolyzerPowerDeadbandRatio: 0.10,
    electrolyzerPowerStepRatio: 0.10,
    electrolyzerDieselPowerLimitRatio: 0.35,
    electrolyzerDieselPowerDeadbandRatio: 0.05,
    electrolyzerDieselPowerStopMaximumRatio: 0.50,
    electrolyzerStorageSocStartMinimum: 0.7,
    electrolyzerStorageSocStopMaximum: 0.3,
    electrolyzerHydrogenStorageSocStopMinimum: 0.9,
    fuelCellPowerMinRatio: 0.20,
    fuelCellPowerMaxRatio: 0.90,
    fuelCellPowerDeadbandRatio: 0.10,
    fuelCellPowerStepRatio: 0.10,
    fuelCellDieselPowerLimitRatio: 0.50,
    fuelCellDieselPowerStopMinimumRatio: 0.30,
    fuelCellStorageSocLimit: 0.3,
    fuelCellHydrogenStorageSocUpperLimit: 0.3,
    fuelCellHydrogenStorageSocLowerLimit: 0.2,
    optimizationRenewableCurtailmentWeight: 1,
    optimizationDieselOutputWeight: 1,
    optimizationCurtailmentSquareWeight: 0.000001,
    optimizationSourceStorageAdjustmentSquareWeight: 0.000001,
    optimizationBalanceDeltaSquareWeight: 10000,
    optimizationBalanceDeltaWarningKw: 1,
    optimizationBalanceToleranceKw: 0.1,
    optimizationBoundToleranceKw: 0.1,
    optimizationFtol: 0.001,
    optimizationMaxIterations: 100,
    commandValidMinutes: 120,
    storageChargeDeratingCurve: DEFAULT_STORAGE_CHARGE_DERATING_CURVE.map((point) => ({ ...point })),
    storageDischargeDeratingCurve: DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE.map((point) => ({ ...point })),
    sending: false,
    requestActive: false,
    actionActive: false,
    revision: -1,
    planRevision: -1,
    settingsRevision: -1,
    lastPlan: null,
    lastCalculatedAt: "",
    lastSentAt: "",
    latestTrendSampleKey: "",
    lastStatus: "请选择单次计算或启动实时控制。",
    logs: [],
    metricTab: "ac",
    parameterTab: "runtime",
    strategyTab: "ac-wind",
    detailTab: "trend",
    logPage: 1,
    selectedLogSeq: 0,
    lastControlLogRenderKey: "",
  },
  overviewBottomHeight: overviewInitialBottomHeight(),
  overviewBottomSplitDrag: null,
  overviewBottomColumnRatio: overviewInitialBottomColumnRatio(),
  overviewBottomColumnSplitDrag: null,
  verticalSplitRatios: initialVerticalSplitRatios(),
  verticalSplitDrag: null,
  deviceTreeSelectionAnchors: {},
  virtualTables: {},
  virtualTableScrollRaf: {},
  webRuntimeSettings: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeDefaults: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeConstraints: {},
  webRuntimeDraft: { ...WEB_RUNTIME_FALLBACKS },
  webRuntimeUpdatedAt: "",
  webRuntimeLoadedModelId: "",
  webRuntimeLoading: false,
  webRuntimeSavingGroup: "",
  webRuntimeDirtyGroups: { backend: false, web: false },
  webRuntimeErrors: { load: "", backend: "", web: "" },
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
    renewableRenderCount: 0,
  },
};
window.__polarFrontendDiagnostics = state.frontendDiagnostics;
const pending = { run_status: new Map(), set_values: new Map() };
let modelContextPersistTimerId = null;
let lastModelContextPersistAtMs = 0;
let lastPersistedModelContextsJson = localStorage.getItem(MODEL_CONTEXTS_STORAGE_KEY) || "";
const RENEWABLE_CONTROL_LOG_PAGE_SIZE = 8;
const RENEWABLE_STRATEGY_TABS = {
  "ac-wind": { label: "交流风电", categories: new Set(["交流风电"]) },
  "dc-wind": { label: "直流风电", categories: new Set(["直流风电"]) },
  "ac-pv": { label: "交流光伏", categories: new Set(["交流光伏"]) },
  "dc-pv": { label: "直流光伏", categories: new Set(["直流光伏"]) },
  "ac-grid-storage": { label: "交流跟网储能", categories: new Set(["交流跟网储能"]) },
  "dc-grid-storage": { label: "直流跟网储能", categories: new Set(["直流跟网储能"]) },
  "ac-balance-storage": { label: "交流平衡储能", categories: new Set(["交流平衡储能"]) },
  "dc-balance-storage": { label: "直流平衡储能", categories: new Set(["直流平衡储能"]) },
  diesel: { label: "柴发", categories: new Set(["柴油发电"]) },
  converter: { label: "ACDC变流", categories: new Set(["交直流变流器"]) },
  hydrogen: { label: "氢能", categories: new Set(["氢能"]) },
};
const RENEWABLE_TREND_SCOPE_DEFS = [
  { key: "ac", label: "交流" },
  { key: "dc", label: "直流" },
  { key: "hydrogen", label: "氢能" },
  { key: "system", label: "系统" },
];
const RENEWABLE_TREND_SERIES_DEFS = [
  { key: "acRenewableCurrent", metricId: "renewableAcCurrentKw", field: "acRenewableCurrentKw", label: "交流新能源当前值", scope: "ac", device: "renewable", deviceLabel: "新能源", curveLabel: "功率", group: "ac-renewable", color: "#23854a", axis: "left", unit: "kW", style: "power" },
  { key: "acRenewableTarget", metricId: "renewableAcTargetKw", field: "acRenewableTargetKw", label: "交流新能源目标值", scope: "ac", device: "renewable", deviceLabel: "新能源", curveLabel: "目标", group: "ac-renewable", color: "#23854a", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acRenewableMaxAvailable", metricId: "renewableAcMaxAvailableKw", field: "acRenewableMaxAvailableKw", label: "交流新能源最大可发", scope: "ac", device: "renewable", deviceLabel: "新能源", curveLabel: "最大可发", group: "ac-renewable", color: "#23854a", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "acWindCurrent", metricId: "renewableAcWindCurrentKw", field: "acWindCurrentKw", label: "交流风电当前值", scope: "ac", device: "wind", deviceLabel: "风电", curveLabel: "功率", group: "ac-wind", color: "#137c72", axis: "left", unit: "kW", style: "power" },
  { key: "acWindTarget", metricId: "renewableAcWindTargetKw", field: "acWindTargetKw", label: "交流风电目标值", scope: "ac", device: "wind", deviceLabel: "风电", curveLabel: "目标", group: "ac-wind", color: "#137c72", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acWindMaxAvailable", metricId: "renewableAcWindMaxAvailableKw", field: "acWindMaxAvailableKw", label: "交流风电最大可发", scope: "ac", device: "wind", deviceLabel: "风电", curveLabel: "最大可发", group: "ac-wind", color: "#137c72", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "acPvCurrent", metricId: "renewableAcPvCurrentKw", field: "acPvCurrentKw", label: "交流光伏当前值", scope: "ac", device: "pv", deviceLabel: "光伏", curveLabel: "功率", group: "ac-pv", color: "#c17a00", axis: "left", unit: "kW", style: "power" },
  { key: "acPvTarget", metricId: "renewableAcPvTargetKw", field: "acPvTargetKw", label: "交流光伏目标值", scope: "ac", device: "pv", deviceLabel: "光伏", curveLabel: "目标", group: "ac-pv", color: "#c17a00", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acPvMaxAvailable", metricId: "renewableAcPvMaxAvailableKw", field: "acPvMaxAvailableKw", label: "交流光伏最大可发", scope: "ac", device: "pv", deviceLabel: "光伏", curveLabel: "最大可发", group: "ac-pv", color: "#c17a00", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "acStorageCurrent", metricId: "renewableAcStorageCurrentKw", field: "acStorageCurrentKw", label: "交流储能当前值", scope: "ac", device: "storage", deviceLabel: "储能", curveLabel: "功率", group: "ac-storage", color: "#426a75", axis: "left", unit: "kW", style: "power" },
  { key: "acStorageTarget", metricId: "renewableAcStorageTargetKw", field: "acStorageTargetKw", label: "交流储能目标值", scope: "ac", device: "storage", deviceLabel: "储能", curveLabel: "目标", group: "ac-storage", color: "#426a75", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acStorageSoc", metricId: "renewableAcStorageSoc", field: "acStorageSocPercent", label: "交流储能SOC", scope: "ac", device: "storage", deviceLabel: "储能", curveLabel: "SOC", group: "ac-storage", color: "#426a75", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "acGridFollowingStorageCurrent", metricId: "renewableAcGridFollowingStorageCurrentKw", field: "acGridFollowingStorageCurrentKw", label: "交流跟网储能当前值", scope: "ac", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "功率", group: "ac-grid-following-storage", color: "#315aa6", axis: "left", unit: "kW", style: "power" },
  { key: "acGridFollowingStorageTarget", metricId: "renewableAcGridFollowingStorageTargetKw", field: "acGridFollowingStorageTargetKw", label: "交流跟网储能目标值", scope: "ac", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "目标", group: "ac-grid-following-storage", color: "#315aa6", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acGridFollowingStorageSoc", metricId: "renewableAcGridFollowingStorageSoc", field: "acGridFollowingStorageSocPercent", label: "交流跟网储能SOC", scope: "ac", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "SOC", group: "ac-grid-following-storage", color: "#315aa6", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "acGridFormingStorageCurrent", metricId: "renewableAcGridFormingStorageCurrentKw", field: "acGridFormingStorageCurrentKw", label: "交流构网储能当前值", scope: "ac", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "功率", group: "ac-grid-forming-storage", color: "#7a4fb3", axis: "left", unit: "kW", style: "power" },
  { key: "acGridFormingStorageTarget", metricId: "renewableAcGridFormingStorageTargetKw", field: "acGridFormingStorageTargetKw", label: "交流构网储能目标值", scope: "ac", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "目标", group: "ac-grid-forming-storage", color: "#7a4fb3", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acGridFormingStorageSoc", metricId: "renewableAcGridFormingStorageSoc", field: "acGridFormingStorageSocPercent", label: "交流构网储能SOC", scope: "ac", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "SOC", group: "ac-grid-forming-storage", color: "#7a4fb3", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "acDieselCurrent", metricId: "renewableAcDieselCurrentKw", field: "acDieselCurrentKw", label: "交流柴发当前值", scope: "ac", device: "diesel", deviceLabel: "柴发", curveLabel: "功率", group: "ac-diesel", color: "#a76500", axis: "left", unit: "kW", style: "power" },
  { key: "acDieselMin", metricId: "renewableAcDieselMinKw", field: "acDieselMinKw", label: "交流柴发下限值", scope: "ac", device: "diesel", deviceLabel: "柴发", curveLabel: "下限", group: "ac-diesel", color: "#a76500", axis: "left", unit: "kW", style: "limit", dashPattern: [10, 4, 2, 4] },
  { key: "acDieselTarget", metricId: "renewableAcDieselTargetKw", field: "acDieselTargetKw", label: "交流柴发目标值", scope: "ac", device: "diesel", deviceLabel: "柴发", curveLabel: "目标", group: "ac-diesel", color: "#a76500", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "acLoad", metricId: "renewableAcLoadKw", field: "acLoadKw", label: "交流负荷功率", scope: "ac", device: "load", deviceLabel: "负荷", curveLabel: "功率", group: "ac-load", color: "#c93a3a", axis: "left", unit: "kW", style: "power" },
  { key: "dcRenewableCurrent", metricId: "renewableDcCurrentKw", field: "dcRenewableCurrentKw", label: "直流新能源当前值", scope: "dc", device: "renewable", deviceLabel: "新能源", curveLabel: "功率", group: "dc-renewable", color: "#118b78", axis: "left", unit: "kW", style: "power" },
  { key: "dcRenewableTarget", metricId: "renewableDcTargetKw", field: "dcRenewableTargetKw", label: "直流新能源目标值", scope: "dc", device: "renewable", deviceLabel: "新能源", curveLabel: "目标", group: "dc-renewable", color: "#118b78", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcRenewableMaxAvailable", metricId: "renewableDcMaxAvailableKw", field: "dcRenewableMaxAvailableKw", label: "直流新能源最大可发", scope: "dc", device: "renewable", deviceLabel: "新能源", curveLabel: "最大可发", group: "dc-renewable", color: "#118b78", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "dcWindCurrent", metricId: "renewableDcWindCurrentKw", field: "dcWindCurrentKw", label: "直流风电当前值", scope: "dc", device: "wind", deviceLabel: "风电", curveLabel: "功率", group: "dc-wind", color: "#087f89", axis: "left", unit: "kW", style: "power" },
  { key: "dcWindTarget", metricId: "renewableDcWindTargetKw", field: "dcWindTargetKw", label: "直流风电目标值", scope: "dc", device: "wind", deviceLabel: "风电", curveLabel: "目标", group: "dc-wind", color: "#087f89", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcWindMaxAvailable", metricId: "renewableDcWindMaxAvailableKw", field: "dcWindMaxAvailableKw", label: "直流风电最大可发", scope: "dc", device: "wind", deviceLabel: "风电", curveLabel: "最大可发", group: "dc-wind", color: "#087f89", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "dcPvCurrent", metricId: "renewableDcPvCurrentKw", field: "dcPvCurrentKw", label: "直流光伏当前值", scope: "dc", device: "pv", deviceLabel: "光伏", curveLabel: "功率", group: "dc-pv", color: "#d66f3c", axis: "left", unit: "kW", style: "power" },
  { key: "dcPvTarget", metricId: "renewableDcPvTargetKw", field: "dcPvTargetKw", label: "直流光伏目标值", scope: "dc", device: "pv", deviceLabel: "光伏", curveLabel: "目标", group: "dc-pv", color: "#d66f3c", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcPvMaxAvailable", metricId: "renewableDcPvMaxAvailableKw", field: "dcPvMaxAvailableKw", label: "直流光伏最大可发", scope: "dc", device: "pv", deviceLabel: "光伏", curveLabel: "最大可发", group: "dc-pv", color: "#d66f3c", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "dcStorageCurrent", metricId: "renewableDcStorageCurrentKw", field: "dcStorageCurrentKw", label: "直流储能当前值", scope: "dc", device: "storage", deviceLabel: "储能", curveLabel: "功率", group: "dc-storage", color: "#357987", axis: "left", unit: "kW", style: "power" },
  { key: "dcStorageTarget", metricId: "renewableDcStorageTargetKw", field: "dcStorageTargetKw", label: "直流储能目标值", scope: "dc", device: "storage", deviceLabel: "储能", curveLabel: "目标", group: "dc-storage", color: "#357987", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcStorageSoc", metricId: "renewableDcStorageSoc", field: "dcStorageSocPercent", label: "直流储能SOC", scope: "dc", device: "storage", deviceLabel: "储能", curveLabel: "SOC", group: "dc-storage", color: "#357987", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "dcGridFollowingStorageCurrent", metricId: "renewableDcGridFollowingStorageCurrentKw", field: "dcGridFollowingStorageCurrentKw", label: "直流跟网储能当前值", scope: "dc", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "功率", group: "dc-grid-following-storage", color: "#2f80c4", axis: "left", unit: "kW", style: "power" },
  { key: "dcGridFollowingStorageTarget", metricId: "renewableDcGridFollowingStorageTargetKw", field: "dcGridFollowingStorageTargetKw", label: "直流跟网储能目标值", scope: "dc", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "目标", group: "dc-grid-following-storage", color: "#2f80c4", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcGridFollowingStorageSoc", metricId: "renewableDcGridFollowingStorageSoc", field: "dcGridFollowingStorageSocPercent", label: "直流跟网储能SOC", scope: "dc", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "SOC", group: "dc-grid-following-storage", color: "#2f80c4", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "dcGridFormingStorageCurrent", metricId: "renewableDcGridFormingStorageCurrentKw", field: "dcGridFormingStorageCurrentKw", label: "直流构网储能当前值", scope: "dc", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "功率", group: "dc-grid-forming-storage", color: "#a15ca8", axis: "left", unit: "kW", style: "power" },
  { key: "dcGridFormingStorageTarget", metricId: "renewableDcGridFormingStorageTargetKw", field: "dcGridFormingStorageTargetKw", label: "直流构网储能目标值", scope: "dc", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "目标", group: "dc-grid-forming-storage", color: "#a15ca8", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcGridFormingStorageSoc", metricId: "renewableDcGridFormingStorageSoc", field: "dcGridFormingStorageSocPercent", label: "直流构网储能SOC", scope: "dc", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "SOC", group: "dc-grid-forming-storage", color: "#a15ca8", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "dcDieselCurrent", metricId: "renewableDcDieselCurrentKw", field: "dcDieselCurrentKw", label: "直流柴发当前值", scope: "dc", device: "diesel", deviceLabel: "柴发", curveLabel: "功率", group: "dc-diesel", color: "#8d6500", axis: "left", unit: "kW", style: "power" },
  { key: "dcDieselMin", metricId: "renewableDcDieselMinKw", field: "dcDieselMinKw", label: "直流柴发下限值", scope: "dc", device: "diesel", deviceLabel: "柴发", curveLabel: "下限", group: "dc-diesel", color: "#8d6500", axis: "left", unit: "kW", style: "limit", dashPattern: [10, 4, 2, 4] },
  { key: "dcDieselTarget", metricId: "renewableDcDieselTargetKw", field: "dcDieselTargetKw", label: "直流柴发目标值", scope: "dc", device: "diesel", deviceLabel: "柴发", curveLabel: "目标", group: "dc-diesel", color: "#8d6500", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "dcLoad", metricId: "renewableDcLoadKw", field: "dcLoadKw", label: "直流负荷功率", scope: "dc", device: "load", deviceLabel: "负荷", curveLabel: "功率", group: "dc-load", color: "#d66f3c", axis: "left", unit: "kW", style: "power" },
  { key: "totalRenewableCurrent", metricId: "renewableTotalCurrentKw", field: "totalRenewableCurrentKw", label: "总新能源当前值", scope: "system", device: "renewable", deviceLabel: "新能源", curveLabel: "功率", group: "system-renewable", color: "#1f7a46", axis: "left", unit: "kW", style: "power" },
  { key: "totalRenewableTarget", metricId: "renewableTotalTargetKw", field: "totalRenewableTargetKw", label: "总新能源目标值", scope: "system", device: "renewable", deviceLabel: "新能源", curveLabel: "目标", group: "system-renewable", color: "#1f7a46", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalRenewableMaxAvailable", metricId: "renewableTotalMaxAvailableKw", field: "totalRenewableMaxAvailableKw", label: "总新能源最大可发", scope: "system", device: "renewable", deviceLabel: "新能源", curveLabel: "最大可发", group: "system-renewable", color: "#1f7a46", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "totalWindCurrent", metricId: "renewableTotalWindCurrentKw", field: "totalWindCurrentKw", label: "总风电当前值", scope: "system", device: "wind", deviceLabel: "风电", curveLabel: "功率", group: "system-wind", color: "#0a7774", axis: "left", unit: "kW", style: "power" },
  { key: "totalWindTarget", metricId: "renewableTotalWindTargetKw", field: "totalWindTargetKw", label: "总风电目标值", scope: "system", device: "wind", deviceLabel: "风电", curveLabel: "目标", group: "system-wind", color: "#0a7774", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalWindMaxAvailable", metricId: "renewableTotalWindMaxAvailableKw", field: "totalWindMaxAvailableKw", label: "总风电最大可发", scope: "system", device: "wind", deviceLabel: "风电", curveLabel: "最大可发", group: "system-wind", color: "#0a7774", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "totalPvCurrent", metricId: "renewableTotalPvCurrentKw", field: "totalPvCurrentKw", label: "总光伏当前值", scope: "system", device: "pv", deviceLabel: "光伏", curveLabel: "功率", group: "system-pv", color: "#ba7200", axis: "left", unit: "kW", style: "power" },
  { key: "totalPvTarget", metricId: "renewableTotalPvTargetKw", field: "totalPvTargetKw", label: "总光伏目标值", scope: "system", device: "pv", deviceLabel: "光伏", curveLabel: "目标", group: "system-pv", color: "#ba7200", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalPvMaxAvailable", metricId: "renewableTotalPvMaxAvailableKw", field: "totalPvMaxAvailableKw", label: "总光伏最大可发", scope: "system", device: "pv", deviceLabel: "光伏", curveLabel: "最大可发", group: "system-pv", color: "#ba7200", axis: "left", unit: "kW", style: "available", dashPattern: [5, 3, 1, 3] },
  { key: "totalStorageCurrent", metricId: "renewableTotalStorageCurrentKw", field: "totalStorageCurrentKw", label: "系统储能当前值", scope: "system", device: "storage", deviceLabel: "储能", curveLabel: "功率", group: "system-storage", color: "#365f6b", axis: "left", unit: "kW", style: "power" },
  { key: "totalStorageTarget", metricId: "renewableTotalStorageTargetKw", field: "totalStorageTargetKw", label: "系统储能目标值", scope: "system", device: "storage", deviceLabel: "储能", curveLabel: "目标", group: "system-storage", color: "#365f6b", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalStorageSoc", metricId: "renewableTotalStorageSoc", field: "totalStorageSocPercent", label: "系统储能SOC", scope: "system", device: "storage", deviceLabel: "储能", curveLabel: "SOC", group: "system-storage", color: "#365f6b", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "totalGridFollowingStorageCurrent", metricId: "renewableTotalGridFollowingStorageCurrentKw", field: "totalGridFollowingStorageCurrentKw", label: "总跟网储能当前值", scope: "system", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "功率", group: "system-grid-following-storage", color: "#294f95", axis: "left", unit: "kW", style: "power" },
  { key: "totalGridFollowingStorageTarget", metricId: "renewableTotalGridFollowingStorageTargetKw", field: "totalGridFollowingStorageTargetKw", label: "总跟网储能目标值", scope: "system", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "目标", group: "system-grid-following-storage", color: "#294f95", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalGridFollowingStorageSoc", metricId: "renewableTotalGridFollowingStorageSoc", field: "totalGridFollowingStorageSocPercent", label: "总跟网储能SOC", scope: "system", device: "grid-following-storage", deviceLabel: "跟网储能", curveLabel: "SOC", group: "system-grid-following-storage", color: "#294f95", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "totalGridFormingStorageCurrent", metricId: "renewableTotalGridFormingStorageCurrentKw", field: "totalGridFormingStorageCurrentKw", label: "总构网储能当前值", scope: "system", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "功率", group: "system-grid-forming-storage", color: "#674493", axis: "left", unit: "kW", style: "power" },
  { key: "totalGridFormingStorageTarget", metricId: "renewableTotalGridFormingStorageTargetKw", field: "totalGridFormingStorageTargetKw", label: "总构网储能目标值", scope: "system", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "目标", group: "system-grid-forming-storage", color: "#674493", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalGridFormingStorageSoc", metricId: "renewableTotalGridFormingStorageSoc", field: "totalGridFormingStorageSocPercent", label: "总构网储能SOC", scope: "system", device: "grid-forming-storage", deviceLabel: "构网储能", curveLabel: "SOC", group: "system-grid-forming-storage", color: "#674493", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "dieselCurrent", metricId: "renewableTotalDieselCurrentKw", field: "totalDieselCurrentKw", label: "总柴发当前值", scope: "system", device: "diesel", deviceLabel: "柴发", curveLabel: "功率", group: "system-diesel", color: "#b87500", axis: "left", unit: "kW", style: "power" },
  { key: "dieselMin", metricId: "renewableTotalDieselMinKw", field: "totalDieselMinKw", label: "总柴发下限值", scope: "system", device: "diesel", deviceLabel: "柴发", curveLabel: "下限", group: "system-diesel", color: "#b87500", axis: "left", unit: "kW", style: "limit", dashPattern: [10, 4, 2, 4] },
  { key: "dieselTarget", metricId: "renewableTotalDieselTargetKw", field: "totalDieselTargetKw", label: "总柴发目标值", scope: "system", device: "diesel", deviceLabel: "柴发", curveLabel: "目标", group: "system-diesel", color: "#b87500", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "totalLoad", metricId: "renewableTotalLoadKw", field: "totalLoadKw", label: "总负荷功率", scope: "system", device: "load", deviceLabel: "负荷", curveLabel: "功率", group: "system-load", color: "#a93434", axis: "left", unit: "kW", style: "power" },
  { key: "acdcCurrent", metricId: "renewableAcdcCurrentKw", field: "acdcCurrentKw", label: "AC/DC变流当前值", scope: "system", device: "acdc", deviceLabel: "AC/DC变流器", curveLabel: "功率", group: "system-acdc", color: "#0a8b8b", axis: "left", unit: "kW", style: "power" },
  { key: "acdcTarget", metricId: "renewableAcdcTargetKw", field: "acdcTargetKw", label: "AC/DC变流目标值", scope: "system", device: "acdc", deviceLabel: "AC/DC变流器", curveLabel: "目标", group: "system-acdc", color: "#0a8b8b", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "observedWindSpeed", metricId: "renewableObservedWindSpeed", field: "observedWindSpeed", label: "实时风速", scope: "system", device: "environment", deviceLabel: "环境", curveLabel: "风速", group: "system-environment", color: "#3278b5", axis: "right", unit: "m/s", style: "weather" },
  { key: "observedSolarIrradiance", metricId: "renewableObservedSolarIrradiance", field: "observedSolarIrradiance", label: "实时太阳辐照度", scope: "system", device: "environment", deviceLabel: "环境", curveLabel: "太阳辐照度", group: "system-environment", color: "#d28b16", axis: "right", unit: "W/m²", style: "weather" },
  { key: "electrolyzerCurrent", metricId: "renewableElectrolyzerCurrentKw", field: "electrolyzerCurrentKw", label: "电制氢实时功率", scope: "hydrogen", device: "electrolyzer", deviceLabel: "电制氢", curveLabel: "功率", group: "hydrogen-electrolyzer", color: "#008678", axis: "left", unit: "kW", style: "power" },
  { key: "electrolyzerTarget", metricId: "renewableElectrolyzerTargetKw", field: "electrolyzerTargetKw", label: "电制氢目标功率", scope: "hydrogen", device: "electrolyzer", deviceLabel: "电制氢", curveLabel: "目标", group: "hydrogen-electrolyzer", color: "#008678", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "electrolyzerFlowCurrent", metricId: "renewableElectrolyzerFlowCurrentNm3h", field: "electrolyzerFlowCurrentNm3h", label: "实时产氢流量", scope: "hydrogen", device: "electrolyzer", deviceLabel: "电制氢", curveLabel: "产氢流量", group: "hydrogen-electrolyzer", color: "#18a899", axis: "right", unit: "Nm³/h", style: "flow" },
  { key: "electrolyzerFlowTarget", metricId: "renewableElectrolyzerFlowTargetNm3h", field: "electrolyzerFlowTargetNm3h", label: "目标产氢流量", scope: "hydrogen", device: "electrolyzer", deviceLabel: "电制氢", curveLabel: "流量目标", group: "hydrogen-electrolyzer", color: "#18a899", axis: "right", unit: "Nm³/h", style: "target", dashed: true },
  { key: "fuelCellCurrent", metricId: "renewableFuelCellCurrentKw", field: "fuelCellCurrentKw", label: "燃料电池实时功率", scope: "hydrogen", device: "fuel-cell", deviceLabel: "燃料电池", curveLabel: "功率", group: "hydrogen-fuel-cell", color: "#c06e00", axis: "left", unit: "kW", style: "power" },
  { key: "fuelCellTarget", metricId: "renewableFuelCellTargetKw", field: "fuelCellTargetKw", label: "燃料电池目标功率", scope: "hydrogen", device: "fuel-cell", deviceLabel: "燃料电池", curveLabel: "目标", group: "hydrogen-fuel-cell", color: "#c06e00", axis: "left", unit: "kW", style: "target", dashed: true },
  { key: "fuelCellFlowCurrent", metricId: "renewableFuelCellFlowCurrentNm3h", field: "fuelCellFlowCurrentNm3h", label: "实时耗氢流量", scope: "hydrogen", device: "fuel-cell", deviceLabel: "燃料电池", curveLabel: "耗氢流量", group: "hydrogen-fuel-cell", color: "#e0932f", axis: "right", unit: "Nm³/h", style: "flow" },
  { key: "fuelCellFlowTarget", metricId: "renewableFuelCellFlowTargetNm3h", field: "fuelCellFlowTargetNm3h", label: "目标耗氢流量", scope: "hydrogen", device: "fuel-cell", deviceLabel: "燃料电池", curveLabel: "流量目标", group: "hydrogen-fuel-cell", color: "#e0932f", axis: "right", unit: "Nm³/h", style: "target", dashed: true },
  { key: "hydrogenStoragePressure", metricId: "renewableHydrogenStoragePressureMpa", field: "hydrogenStoragePressureMpa", label: "储氢罐压力", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "压力", group: "hydrogen-storage", color: "#6358a9", axis: "right", unit: "MPa", style: "pressure" },
  { key: "hydrogenStoragePressureLowGuard", metricId: "renewableHydrogenStoragePressureLowGuardMpa", field: "hydrogenStoragePressureLowGuardMpa", label: "储氢罐压力下限保护值", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "压力下限", group: "hydrogen-storage", color: "#6358a9", axis: "right", unit: "MPa", style: "limit", dashPattern: [10, 4, 2, 4] },
  { key: "hydrogenStoragePressureHighGuard", metricId: "renewableHydrogenStoragePressureHighGuardMpa", field: "hydrogenStoragePressureHighGuardMpa", label: "储氢罐压力上限保护值", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "压力上限", group: "hydrogen-storage", color: "#8b55a4", axis: "right", unit: "MPa", style: "limit", dashPattern: [10, 4, 2, 4] },
  { key: "hydrogenStorageGasQuantity", metricId: "renewableHydrogenStorageGasQuantityNm3", field: "hydrogenStorageGasQuantityNm3", label: "储氢罐总储气量", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "总储气量", group: "hydrogen-storage", color: "#3b6fa1", axis: "right", unit: "Nm³", style: "quantity" },
  { key: "hydrogenStorageSoc", metricId: "renewableHydrogenStorageSoc", field: "hydrogenStorageSocPercent", label: "储氢罐SOC", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "SOC", group: "hydrogen-storage", color: "#8b55a4", axis: "right", unit: "%", style: "soc", dashPattern: [2, 4] },
  { key: "hydrogenStorageFlow", metricId: "renewableHydrogenStorageFlowNm3h", field: "hydrogenStorageFlowNm3h", label: "储氢罐净流量", scope: "hydrogen", device: "hydrogen-storage", deviceLabel: "储氢罐", curveLabel: "净流量", group: "hydrogen-storage", color: "#2d8ba4", axis: "right", unit: "Nm³/h", style: "flow" },
];
const RENEWABLE_TREND_DEFAULT_VISIBLE_SERIES = new Set([
  "acLoad",
  "dcLoad",
  "dieselCurrent",
  "acRenewableCurrent",
  "dcRenewableCurrent",
  "acGridFollowingStorageCurrent",
  "dcGridFollowingStorageCurrent",
  "acGridFormingStorageCurrent",
  "dcGridFormingStorageCurrent",
  "acdcCurrent",
  "totalRenewableMaxAvailable",
]);
const VIRTUAL_TABLE_ROW_HEIGHT = 34;
const VIRTUAL_TABLE_MIN_ROWS = 220;
const VIRTUAL_TABLE_BUFFER_ROWS = 12;
const CURVE_DISPLAY_MODES = {
  hour: { key: "hour", label: "时仿真", pointCount: 3600, stepMinutes: 1 / 60, durationMinutes: 60, tableTitle: "时曲线数据表", tableSummary: "1秒间隔 · 只读" },
  day: { key: "day", label: "日仿真", pointCount: 1440, stepMinutes: 1, durationMinutes: 24 * 60, tableTitle: "日曲线数据表", tableSummary: "1分钟间隔 · 只读" },
  week: { key: "week", label: "周仿真", pointCount: 10080, stepMinutes: 1, durationMinutes: 7 * 24 * 60, tableTitle: "周曲线数据表", tableSummary: "1分钟间隔 · 只读" },
  month: { key: "month", label: "月仿真", pointCount: 720, stepMinutes: 60, durationMinutes: 30 * 24 * 60, tableTitle: "月曲线数据表", tableSummary: "1小时间隔 · 只读" },
  year: { key: "year", label: "年仿真", pointCount: 8760, stepMinutes: 60, durationMinutes: 365 * 24 * 60, tableTitle: "年曲线数据表", tableSummary: "1小时间隔 · 只读" },
};
const CURVE_DISPLAY_ENV_KEYS = ["wind_speed_mps", "solar_irradiance_w_m2", "air_temp_c"];
const CURVE_DISPLAY_META = [
  { key: "wind_speed_mps", label: "风速", color: "#008c8c", min: 0, max: 50, digits: 2, unit: "m/s" },
  { key: "solar_irradiance_w_m2", label: "太阳辐照", color: "#b87500", min: 0, max: 1100, digits: 1, unit: "W/m2" },
  { key: "air_temp_c", label: "气温", color: "#2b6b7f", min: -60, max: 20, digits: 2, unit: "℃" },
];
const CURVE_DISPLAY_LOAD_META = { label: "负荷", color: "#c93a3a", min: 0, max: 500, digits: 2, unit: "kW" };
const CURVE_DISPLAY_LOAD_COLORS = ["#c93a3a", "#8a4fbf", "#23854a", "#d16300", "#4369b2", "#0a8b8b"];
const CURVE_DISPLAY_LOAD_FAMILIES = [
  { key: "electric", label: "电负荷曲线", blocks: ["ACLoad", "DCLoad"], unit: "kW", valueKey: "p_kw" },
  { key: "hydrogen", label: "氢负荷曲线", blocks: ["HydroLoad"], unit: "Nm³/h", valueKey: "flow_set" },
  { key: "heat", label: "热负荷曲线", blocks: ["HeatLoad"], unit: "kW", valueKey: "heat_power" },
];
const CURVE_DISPLAY_SOURCE_FAMILIES = [
  { key: "electric", label: "电源曲线" },
  { key: "hydrogen", label: "氢源曲线" },
  { key: "heat", label: "热源曲线" },
];
const CURVE_DISPLAY_SOURCE_COLORS = ["#126f8a", "#8a4fbf", "#23854a", "#d16300", "#4369b2", "#0a8b8b"];
const CURVE_DISPLAY_PLOT = { left: 58, right: 24, top: 46, bottom: 34 };
const WEATHER_MEASUREMENT_LABELS = {
  WIND_SPEED: { label: "风速", order: 0 },
  SOLAR_IRRADIANCE: { label: "太阳辐照", order: 1 },
  AIR_TEMP: { label: "气温", order: 2 },
  HUMIDITY: { label: "湿度", order: 3 },
  AIR_PRESSURE: { label: "气压", order: 4 },
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
const RECEIVE_WARNING_LIMIT = 40;

const $ = (id) => document.getElementById(id);
const deviceTreeRenderKeys = new WeakMap();

function activeRuntimeSetting(name) {
  const value = Number(state.webRuntimeSettings?.[name]);
  if (Number.isFinite(value)) return value;
  const configuredDefault = Number(state.webRuntimeDefaults?.[name]);
  if (Number.isFinite(configuredDefault)) return configuredDefault;
  return Number(WEB_RUNTIME_FALLBACKS[name]) || 0;
}

function runtimeParameterGroup(name) {
  return Object.entries(RUNTIME_PARAMETER_GROUPS)
    .find(([, names]) => names.includes(name))?.[0] || "";
}

function runtimeParameterGroupDirty(group) {
  return Boolean(state.webRuntimeDirtyGroups?.[group]);
}

function runtimeParameterGroupValues(values, group) {
  return Object.fromEntries(
    (RUNTIME_PARAMETER_GROUPS[group] || []).map((name) => [name, values?.[name]]),
  );
}

function frontendRefreshIntervalMs() {
  return Math.max(200, activeRuntimeSetting("frontend_refresh_seconds") * 1000);
}

function backendDataRefreshIntervalMs() {
  return Math.max(100, activeRuntimeSetting("backend_refresh_seconds") * 1000);
}

function renewableSimulationControlIntervalError(controlSeconds) {
  const control = Number(controlSeconds);
  if (!Number.isFinite(control) || control < 1) return "自动控制周期必须不少于 1 仿真秒。";
  return "";
}

function syncRenewableControlPeriodConstraints() {
  const input = $("renewableControlPeriod");
  if (!input) return;
  input.min = "1";
  input.step = "0.1";
  input.setCustomValidity(renewableSimulationControlIntervalError(input.value));
}

function frontendRequestTimeoutMs() {
  return Math.max(1000, activeRuntimeSetting("frontend_request_timeout_seconds") * 1000);
}

function receiveStateSyncIntervalMs() {
  return Math.max(500, activeRuntimeSetting("receive_state_sync_seconds") * 1000);
}

function receiveMaxReconnectAttempts() {
  return Math.max(1, Math.round(activeRuntimeSetting("receive_max_reconnect_attempts")));
}

function pageIsHidden() {
  return document.visibilityState === "hidden";
}

function refreshSchedulerIntervalMs() {
  if (pageIsHidden()) return HIDDEN_REFRESH_INTERVAL_MS;
  const baseMs = state.receiveMode
    ? backendDataRefreshIntervalMs()
    : frontendRefreshIntervalMs();
  const failures = Math.max(0, Number(state.refreshConsecutiveFailures) || 0);
  if (failures <= 0) return baseMs;
  const factor = Math.pow(2, Math.min(3, failures));
  return Math.min(10000, Math.round(baseMs * factor));
}

function scheduleNextRefresh(delayMs = refreshSchedulerIntervalMs()) {
  if (state.frontendRefreshTimerId) {
    clearTimeout(state.frontendRefreshTimerId);
    state.frontendRefreshTimerId = null;
  }
  // 页面处于后台不可见状态时暂停前端 UI 轮询，切回前台由 visibilitychange 立即刷新。
  if (pageIsHidden()) return;
  state.frontendRefreshTimerId = setTimeout(runRefreshScheduler, Math.max(0, delayMs));
}

function restartRefreshScheduler() {
  scheduleNextRefresh();
}

async function runRefreshScheduler() {
  state.frontendRefreshTimerId = null;
  if (pageIsHidden()) return;
  const startedAtMs = Date.now();
  try {
    await refresh();
  } finally {
    if (!pageIsHidden()) {
      const elapsedMs = Date.now() - startedAtMs;
      scheduleNextRefresh(Math.max(0, refreshSchedulerIntervalMs() - elapsedMs));
    }
  }
}

function contextKey(modelId = state.activeModelId) {
  return String(modelId || "__default__");
}

function defaultModelContext(modelId = state.activeModelId) {
  return {
    modelId: contextKey(modelId),
    modelInitialized: false,
    modelInitializedAt: "",
    receiveMode: false,
    frozen: false,
    interactionLink: "",
    teacherApiBase: "",
    teacherModelId: "",
    teacherModelName: "",
    teacherSnapshotPath: "",
    teacherCommandPath: "",
    teacherMeasurementDeltaPath: "",
    teacherDefinitionArchivePath: "",
    lastReceiveAt: "",
    receiveStateRevision: "",
    snapshotSource: "",
    lastTeacherSnapshotLogKey: "",
    receiveReconnectAttempts: 0,
    measurementDeltaSeq: 0,
    measurementArrayWarning: "",
    runtimeLogSeq: 0,
    runtimeLogs: [],
    snapshot: null,
    measurementTraceHistory: [],
    lastMeasurementTraceKey: "",
    commandTraceHistory: [],
    renewableTrendHistory: [],
    renewableTrendFieldCursors: {},
    traceRunId: null,
    traceStepCount: null,
  };
}

function storedContextInitialized(context = {}) {
  if (Object.prototype.hasOwnProperty.call(context, "modelInitialized")) {
    return Boolean(context.modelInitialized);
  }
  return Boolean(
    context.interactionLink
    && (
      context.teacherModelId
      || context.teacherModelName
      || context.teacherApiBase
      || context.teacherSnapshotPath
    )
  );
}

function activeModelContext(modelId = state.activeModelId) {
  const key = contextKey(modelId);
  const stored = state.modelContexts[key] || {};
  return {
    ...defaultModelContext(modelId),
    ...stored,
    modelInitialized: storedContextInitialized(stored),
  };
}

function serializableModelContext(context) {
  return {
    modelInitialized: Boolean(context.modelInitialized),
    modelInitializedAt: context.modelInitializedAt || "",
    receiveMode: Boolean(context.receiveMode),
    frozen: Boolean(context.frozen),
    interactionLink: context.interactionLink || "",
    teacherApiBase: context.teacherApiBase || "",
    teacherModelId: context.teacherModelId || "",
    teacherModelName: context.teacherModelName || "",
    teacherSnapshotPath: context.teacherSnapshotPath || "",
    teacherCommandPath: context.teacherCommandPath || "",
    teacherMeasurementDeltaPath: context.teacherMeasurementDeltaPath || "",
    teacherDefinitionArchivePath: context.teacherDefinitionArchivePath || "",
    lastReceiveAt: context.lastReceiveAt || "",
    receiveStateRevision: context.receiveStateRevision || "",
  };
}

function persistModelContextsToStorage() {
  const payload = {};
  Object.entries(state.modelContexts || {}).forEach(([key, context]) => {
    payload[key] = serializableModelContext(context || {});
  });
  const serialized = JSON.stringify(payload);
  if (serialized === lastPersistedModelContextsJson) return false;
  localStorage.setItem(MODEL_CONTEXTS_STORAGE_KEY, serialized);
  lastPersistedModelContextsJson = serialized;
  return true;
}

function captureActiveModelContext(overrides = {}) {
  return {
    ...activeModelContext(),
    modelInitialized: state.modelInitialized,
    modelInitializedAt: state.modelInitializedAt,
    receiveMode: state.receiveMode,
    frozen: state.frozen,
    interactionLink: state.interactionLink,
    teacherApiBase: state.teacherApiBase,
    teacherModelId: state.teacherModelId,
    teacherModelName: state.teacherModelName,
    teacherSnapshotPath: state.teacherSnapshotPath,
    teacherCommandPath: state.teacherCommandPath,
    teacherMeasurementDeltaPath: state.teacherMeasurementDeltaPath,
    teacherDefinitionArchivePath: state.teacherDefinitionArchivePath,
    lastReceiveAt: state.lastReceiveAt,
    receiveStateRevision: state.receiveStateRevision,
    snapshotSource: state.snapshotSource,
    lastTeacherSnapshotLogKey: state.lastTeacherSnapshotLogKey,
    receiveReconnectAttempts: state.receiveReconnectAttempts,
    measurementDeltaSeq: state.measurementDeltaSeq,
    measurementArrayWarning: state.measurementArrayWarning,
    runtimeLogSeq: state.runtimeLogSeq,
    runtimeLogs: state.runtimeLogs,
    snapshot: state.snapshot,
    measurementTraceHistory: state.measurementTraceHistory,
    lastMeasurementTraceKey: state.lastMeasurementTraceKey,
    commandTraceHistory: state.commandTraceHistory,
    renewableTrendHistory: state.renewableTrendHistory,
    renewableTrendFieldCursors: state.renewableTrendFieldCursors,
    traceRunId: state.traceRunId,
    traceStepCount: state.traceStepCount,
    ...overrides,
  };
}

function flushModelContextPersistence() {
  if (modelContextPersistTimerId !== null) {
    window.clearTimeout(modelContextPersistTimerId);
    modelContextPersistTimerId = null;
  }
  persistModelContextsToStorage();
  lastModelContextPersistAtMs = Date.now();
}

function persistActiveModelContext(overrides = {}, immediate = false) {
  if (!state.activeModelId) return;
  state.modelContexts[contextKey()] = captureActiveModelContext(overrides);
  if (immediate) {
    flushModelContextPersistence();
    return;
  }
  if (modelContextPersistTimerId !== null) return;
  const elapsed = Date.now() - lastModelContextPersistAtMs;
  const delay = Math.max(0, MODEL_CONTEXT_PERSIST_INTERVAL_MS - elapsed);
  modelContextPersistTimerId = window.setTimeout(flushModelContextPersistence, delay);
}

window.addEventListener("pagehide", flushModelContextPersistence);

function restoreModelContext(modelId = state.activeModelId) {
  const context = activeModelContext(modelId);
  state.modelInitialized = Boolean(context.modelInitialized);
  state.modelInitializedAt = context.modelInitializedAt || "";
  state.receiveMode = Boolean(context.receiveMode);
  state.frozen = Boolean(context.frozen);
  state.interactionLink = context.interactionLink || "";
  state.teacherApiBase = (context.teacherApiBase || "").replace(/\/$/, "");
  state.teacherModelId = context.teacherModelId || "";
  state.teacherModelName = context.teacherModelName || "";
  state.teacherSnapshotPath = context.teacherSnapshotPath || "";
  state.teacherCommandPath = context.teacherCommandPath || "";
  state.teacherMeasurementDeltaPath = context.teacherMeasurementDeltaPath || "";
  state.teacherDefinitionArchivePath = context.teacherDefinitionArchivePath || "";
  state.lastReceiveAt = context.lastReceiveAt || "";
  state.receiveStateRevision = context.receiveStateRevision || "";
  state.snapshotSource = context.snapshotSource || "";
  state.lastTeacherSnapshotLogKey = context.lastTeacherSnapshotLogKey || "";
  state.receiveReconnectAttempts = Number(context.receiveReconnectAttempts) || 0;
  state.measurementDeltaSeq = Number(context.measurementDeltaSeq) || 0;
  state.measurementArrayWarning = context.measurementArrayWarning || "";
  state.runtimeLogSeq = Number(context.runtimeLogSeq) || 0;
  state.runtimeLogs = Array.isArray(context.runtimeLogs) ? context.runtimeLogs : [];
  state.snapshot = traineeMeasurementOnlySnapshot(context.snapshot || null);
  state.measurementTraceHistory = traineeMeasurementOnlyTraceHistory(context.measurementTraceHistory);
  state.lastMeasurementTraceKey = context.lastMeasurementTraceKey || "";
  state.commandTraceHistory = Array.isArray(context.commandTraceHistory) ? context.commandTraceHistory : [];
  state.renewableTrendHistory = Array.isArray(context.renewableTrendHistory) ? context.renewableTrendHistory : [];
  state.renewableTrendHistoryGeneration = (Number(state.renewableTrendHistoryGeneration) || 0) + 1;
  state.renewableTrendHistoryRequests = {};
  state.renewableTrendFieldCursors = context.renewableTrendFieldCursors
    && typeof context.renewableTrendFieldCursors === "object"
    ? { ...context.renewableTrendFieldCursors }
    : {};
  state.traceRunId = context.traceRunId ?? null;
  state.traceStepCount = context.traceStepCount ?? null;
}

function receiveContextFromBackend(payload = {}) {
  return {
    modelInitialized: Boolean(payload.initialized ?? payload.model_initialized ?? payload.modelInitialized),
    modelInitializedAt: payload.initialized_at || payload.initializedAt || "",
    receiveMode: Boolean(payload.active ?? payload.receiveMode),
    frozen: Boolean(payload.frozen),
    interactionLink: payload.interaction_link || payload.interactionLink || "",
    teacherApiBase: (payload.teacher_api_base || payload.teacherApiBase || "").replace(/\/$/, ""),
    teacherModelId: payload.teacher_model_id || payload.teacherModelId || "",
    teacherModelName: payload.teacher_model_name || payload.teacherModelName || "",
    teacherSnapshotPath: payload.snapshot_path || payload.snapshotPath || "",
    teacherCommandPath: payload.command_path || payload.commandPath || "",
    teacherMeasurementDeltaPath: payload.measurement_delta_path || payload.measurementDeltaPath || "",
    teacherDefinitionArchivePath: payload.definition_archive_path || payload.definitionArchivePath || "",
    lastReceiveAt: payload.last_receive_at || payload.lastReceiveAt || "",
  };
}

function receiveStatePayloadFromContext(context, overrides = {}) {
  const merged = { ...context, ...overrides };
  return {
    initialized: Boolean(merged.initialized ?? merged.modelInitialized),
    initialized_at: merged.initializedAt || merged.modelInitializedAt || merged.initialized_at || "",
    active: Boolean(merged.active ?? merged.receiveMode),
    frozen: Boolean(merged.frozen),
    interaction_link: merged.interactionLink || merged.interaction_link || "",
    teacher_api_base: merged.teacherApiBase || merged.teacher_api_base || "",
    teacher_model_id: merged.teacherModelId || merged.teacher_model_id || state.activeModelId || "",
    teacher_model_name: merged.teacherModelName || merged.teacher_model_name || merged.teacherModelName || "",
    snapshot_path: merged.teacherSnapshotPath || merged.snapshot_path || "",
    command_path: merged.teacherCommandPath || merged.command_path || "",
    measurement_delta_path: merged.teacherMeasurementDeltaPath || merged.measurement_delta_path || "",
    definition_archive_path: merged.teacherDefinitionArchivePath || merged.definition_archive_path || "",
    last_receive_at: merged.lastReceiveAt || merged.last_receive_at || "",
  };
}

function mergeBackendReceiveState(modelId, payload = {}, applyIfActive = false) {
  const key = contextKey(modelId);
  const previous = activeModelContext(modelId);
  state.modelContexts[key] = {
    ...previous,
    ...receiveContextFromBackend(payload),
  };
  persistModelContextsToStorage();
  if (applyIfActive && contextKey() === key) restoreModelContext(modelId);
  return state.modelContexts[key];
}

async function saveTraineeReceiveState(modelId = state.activeModelId, overrides = {}) {
  const key = contextKey(modelId);
  const context = key === contextKey() ? captureActiveModelContext(overrides) : { ...activeModelContext(modelId), ...overrides };
  const result = await api(`/api/trainee/receive-state?model_id=${encodeURIComponent(modelId)}`, {
    method: "POST",
    modelScoped: false,
    body: JSON.stringify(receiveStatePayloadFromContext(context, overrides)),
  });
  mergeBackendReceiveState(modelId, result, key === contextKey());
  return result;
}

async function syncActiveReceiveStateFromBackend(modelId = state.activeModelId) {
  if (!modelId) return null;
  const payload = await api(`/api/trainee/receive-state?model_id=${encodeURIComponent(modelId)}`, { modelScoped: false });
  return mergeBackendReceiveState(modelId, payload, contextKey(modelId) === contextKey());
}

async function syncActiveReceiveStateBeforeRefresh(force = false) {
  if (!state.activeModelId || state.receiveStateSyncActive) return;
  if (!force && Date.now() - state.lastReceiveStateSyncAtMs < receiveStateSyncIntervalMs()) return;
  const requestedModelId = state.activeModelId;
  const switchEpoch = Number(state.modelSwitchEpoch || 0);
  state.receiveStateSyncActive = true;
  state.lastReceiveStateSyncAtMs = Date.now();
  const previousReceiveMode = state.receiveMode;
  const previousLink = state.interactionLink;
  const previousInitialized = state.modelInitialized;
  const previousInitializedAt = state.modelInitializedAt;
  try {
    await syncActiveReceiveStateFromBackend(requestedModelId);
    // 防止切换模型期间旧模型异步返回覆盖新模型上下文与缓存。
    if (
      state.activeModelId !== requestedModelId
      || Number(state.modelSwitchEpoch || 0) !== switchEpoch
    ) {
      return;
    }
    if (
      state.modelInitialized !== previousInitialized
      || state.modelInitializedAt !== previousInitializedAt
    ) {
      state.localDefinitionSnapshot = null;
      state.localDefinitionModelId = "";
      state.snapshot = null;
      state.measurementDeltaSeq = 0;
      invalidateManualDefinitionChanges();
      clearStaticSnapshotCacheForModel(requestedModelId);
    }
    if (state.receiveMode !== previousReceiveMode || state.interactionLink !== previousLink) {
      state.receiveEpoch += 1;
      state.receiveRequestActive = false;
      if (state.receiveMode) {
        state.frozen = false;
        state.lastReceiveAt = "";
        state.snapshotSource = "";
      }
    }
  } catch (_error) {
    // Keep the visible page usable if the local trainee service cannot read the shared receive state.
  } finally {
    state.receiveStateSyncActive = false;
  }
}

function mergeReceiveStatesFromBackend(items = {}) {
  Object.entries(items || {}).forEach(([modelId, payload]) => {
    mergeBackendReceiveState(modelId, payload, false);
  });
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

function chartLegendHiddenSet(chartKey) {
  const hidden = state.chartLegendSeriesHidden?.[chartKey] || [];
  return new Set(hidden);
}

function isChartLegendSeriesHidden(chartKey, seriesKey) {
  return chartLegendHiddenSet(chartKey).has(seriesKey);
}

function visibleChartLegendSeries(chartKey, seriesDefs) {
  return (seriesDefs || []).filter((series) => !isChartLegendSeriesHidden(chartKey, series.key));
}

function selectedChartSeriesKey(chartKey, fallback = "") {
  return state.chartSeriesSelected?.[chartKey] || fallback || "";
}

function setChartSeriesSelected(chartKey, seriesKey, drawFn) {
  if (!chartKey || !seriesKey) return;
  state.chartSeriesSelected = { ...(state.chartSeriesSelected || {}), [chartKey]: seriesKey };
  syncChartLegendButtons(chartKey);
  if (typeof drawFn === "function") drawFn();
}

function setChartSeriesVisibility(chartKey, seriesKey, visible, drawFn) {
  if (!chartKey || !seriesKey) return;
  const hidden = chartHiddenSet(chartKey);
  const legendHidden = chartLegendHiddenSet(chartKey);
  if (visible) hidden.delete(seriesKey);
  else hidden.add(seriesKey);
  legendHidden.delete(seriesKey);
  state.chartSeriesHidden = { ...(state.chartSeriesHidden || {}), [chartKey]: Array.from(hidden) };
  state.chartLegendSeriesHidden = {
    ...(state.chartLegendSeriesHidden || {}),
    [chartKey]: Array.from(legendHidden),
  };
  state.chartSeriesSelected = { ...(state.chartSeriesSelected || {}), [chartKey]: seriesKey };
  syncChartLegendButtons(chartKey);
  if (typeof drawFn === "function") drawFn();
}

function toggleChartSeriesVisibility(chartKey, seriesKey, drawFn) {
  setChartSeriesVisibility(chartKey, seriesKey, isChartSeriesHidden(chartKey, seriesKey), drawFn);
}

function setChartLegendSeriesVisibility(chartKey, seriesKey, visible, drawFn) {
  if (!chartKey || !seriesKey) return;
  const hidden = chartLegendHiddenSet(chartKey);
  if (visible) hidden.delete(seriesKey);
  else hidden.add(seriesKey);
  state.chartLegendSeriesHidden = {
    ...(state.chartLegendSeriesHidden || {}),
    [chartKey]: Array.from(hidden),
  };
  syncChartLegendButtons(chartKey);
  if (typeof drawFn === "function") drawFn();
}

function toggleChartLegendSeriesVisibility(chartKey, seriesKey, drawFn) {
  setChartLegendSeriesVisibility(
    chartKey,
    seriesKey,
    isChartLegendSeriesHidden(chartKey, seriesKey),
    drawFn,
  );
}

function syncChartLegendButtons(chartKey) {
  document.querySelectorAll(`[data-chart-toggle="${chartKey}"]`).forEach((control) => {
    const seriesKey = control.dataset.chartSeries || "";
    const isLegendVisibilityControl = control.dataset.chartLegendVisibility === "true";
    const hidden = isLegendVisibilityControl
      ? isChartLegendSeriesHidden(chartKey, seriesKey)
      : isChartSeriesHidden(chartKey, seriesKey);
    const selected = !isLegendVisibilityControl && selectedChartSeriesKey(chartKey) === seriesKey;
    if (control.matches('input[type="checkbox"]')) {
      control.checked = !hidden;
      const item = control.closest(".renewable-trend-series-item");
      item?.classList.toggle("is-hidden", hidden);
      item?.classList.toggle("is-selected", selected);
      return;
    }
    control.classList.toggle("is-hidden", hidden);
    control.classList.toggle("is-selected", selected);
    control.setAttribute("aria-pressed", hidden ? "false" : "true");
    const legendLabel = control.dataset.chartLegendLabel || "";
    if (legendLabel) {
      const actionLabel = hidden ? "点击显示曲线" : "点击隐藏曲线";
      control.title = `${legendLabel}：${actionLabel}`;
      control.setAttribute("aria-label", `${legendLabel}，${actionLabel}`);
    }
  });
}

function canvasPointerPosition(canvas, event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) * (canvas.width / rect.width),
    y: (event.clientY - rect.top) * (canvas.height / rect.height),
  };
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

function setSelectNumericValue(control, value) {
  if (!control) return;
  const text = String(value ?? "");
  if (control.tagName === "SELECT" && text !== "") {
    const matched = Array.from(control.options).some((opt) => opt.value === text);
    if (!matched) {
      const option = document.createElement("option");
      option.value = text;
      option.textContent = `${text}（自定义）`;
      option.dataset.customDynamicOption = "1";
      control.appendChild(option);
    }
  }
  control.value = text;
}

function canvasDevicePixelRatio() {
  return Math.min(2, Math.max(1, Number(window.devicePixelRatio) || 1));
}

function canvasRenderedSize(canvas, fallbackWidth = 900, fallbackHeight = 260) {
  const rect = canvas.getBoundingClientRect();
  return {
    width: Math.max(1, Math.floor(rect.width || canvas.clientWidth || fallbackWidth)),
    height: Math.max(1, Math.floor(rect.height || canvas.clientHeight || fallbackHeight)),
  };
}

function canvasLogicalSize(canvas, fallbackWidth = 900, fallbackHeight = 260) {
  const w = Number(canvas?.dataset?.logicalWidth);
  const h = Number(canvas?.dataset?.logicalHeight);
  if (Number.isFinite(w) && w > 0 && Number.isFinite(h) && h > 0) {
    return { width: w, height: h };
  }
  return canvasRenderedSize(canvas, fallbackWidth, fallbackHeight);
}

function prepareCanvas2D(canvas, fallbackWidth = 900, fallbackHeight = 260) {
  const { width, height } = canvasLogicalSize(canvas, fallbackWidth, fallbackHeight);
  const dpr = Number(canvas?.dataset?.dpr) || canvasDevicePixelRatio();
  const ctx = canvas.getContext("2d");
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width, height, dpr };
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
    if (key === "measurement" && currentPageName() === "measurements") {
      renderMeasurements(state.snapshot || {});
    }
    if (key.startsWith("traineeCommand:") && currentPageName() === "commands") {
      renderCombinedControlPage();
    }
    if (key.startsWith("curveDisplay:") && currentPageName() === "curves") {
      renderCurveDisplayTable(state.snapshot || {}, true);
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
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
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

function drawInlineChartCursorLabels(ctx, canvas, plot, x, samples, options = {}) {
  const ratio = options.ratio || 1;
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const valueFormatter = options.valueFormatter || formatNumber;
  const maxSeries = Math.max(1, Number(options.maxSeries) || 10);
  const labelHeight = 18 * ratio;
  const labelGap = 12 * ratio;
  const laneGap = 8 * ratio;
  ctx.font = `${11 * ratio}px Microsoft YaHei, Arial`;
  const labels = samples.slice(0, maxSeries).map(({ series, point }) => {
    const valueText = `${valueFormatter(point.value)}${series.unit ? ` ${series.unit}` : ""}`;
    const text = `${series.label}: ${valueText}`;
    return {
      series,
      point,
      text,
      width: ctx.measureText(text).width + 18 * ratio,
    };
  });
  if (!labels.length) return;

  const maxLabelWidth = Math.max(...labels.map((label) => label.width));
  const laneStride = maxLabelWidth + laneGap;
  const rightSpace = right - x - labelGap;
  const leftSpace = x - left - labelGap;
  const occupiedLanes = { left: [], right: [] };

  const findPlacement = (label, side) => {
    const availableSpace = side === "right" ? rightSpace : leftSpace;
    if (availableSpace < label.width) return null;
    const laneCount = Math.max(1, Math.floor((availableSpace + laneGap) / laneStride));
    for (let lane = 0; lane < laneCount; lane += 1) {
      const laneYs = occupiedLanes[side][lane] || [];
      if (laneYs.some((previousY) => Math.abs(previousY - label.point.y) < labelHeight + 2 * ratio)) continue;
      const labelX = side === "right"
        ? x + labelGap + lane * laneStride
        : x - labelGap - label.width - lane * laneStride;
      if (labelX < left + 2 * ratio || labelX + label.width > right - 2 * ratio) continue;
      occupiedLanes[side][lane] = [...laneYs, label.point.y];
      return { side, labelX };
    }
    return null;
  };

  const placements = labels.map((label) => {
    const rightFits = rightSpace >= label.width;
    const leftFits = leftSpace >= label.width;
    const preferredSide = rightFits && !leftFits
      ? "right"
      : leftFits && !rightFits
        ? "left"
        : rightSpace >= leftSpace
          ? "right"
          : "left";
    const secondarySide = preferredSide === "right" ? "left" : "right";
    const placement = findPlacement(label, preferredSide) || findPlacement(label, secondarySide);
    if (placement) return { ...label, ...placement };
    const fallbackSide = rightSpace >= label.width || rightSpace >= leftSpace ? "right" : "left";
    const unclampedX = fallbackSide === "right" ? x + labelGap : x - labelGap - label.width;
    return {
      ...label,
      side: fallbackSide,
      labelX: clamp(unclampedX, left + 2 * ratio, right - label.width - 2 * ratio),
    };
  });

  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  placements.forEach(({ series, point, text, side, labelX }) => {
    const connectorStartX = point.x + (side === "right" ? 6 : -6) * ratio;
    const connectorEndX = side === "right" ? labelX - 3 * ratio : labelX + ctx.measureText(text).width + 17 * ratio;
    ctx.strokeStyle = series.color;
    ctx.globalAlpha = 0.72;
    ctx.lineWidth = 1 * ratio;
    ctx.beginPath();
    ctx.moveTo(connectorStartX, point.y);
    ctx.lineTo(connectorEndX, point.y);
    ctx.stroke();
    ctx.globalAlpha = 1;

    ctx.fillStyle = series.color;
    ctx.beginPath();
    ctx.arc(labelX + 5 * ratio, point.y, 3 * ratio, 0, Math.PI * 2);
    ctx.fill();
    ctx.lineWidth = 3 * ratio;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.96)";
    ctx.strokeText(text, labelX + 12 * ratio, point.y);
    ctx.fillStyle = "#24373f";
    ctx.fillText(text, labelX + 12 * ratio, point.y);
  });

  const timeLabel = String(options.timeLabel || "").trim();
  if (timeLabel) {
    const text = `时刻: ${timeLabel}`;
    ctx.font = `${11 * ratio}px Consolas, Microsoft YaHei, Arial`;
    const textWidth = ctx.measureText(text).width;
    const preferredX = x + labelGap + textWidth <= right ? x + labelGap : x - labelGap - textWidth;
    const textX = clamp(preferredX, left + 2 * ratio, right - textWidth - 2 * ratio);
    const textY = top + 11 * ratio;
    ctx.lineWidth = 3 * ratio;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.98)";
    ctx.strokeText(text, textX, textY);
    ctx.fillStyle = "#344b54";
    ctx.fillText(text, textX, textY);
  }
}

function drawChartCursor(ctx, chartKey, canvas, plot, seriesData, options = {}) {
  const cursor = state.chartCursors?.[chartKey];
  const visibleSeries = (seriesData || []).filter((series) => !isChartSeriesHidden(chartKey, series.key));
  if (!cursor?.visible || !visibleSeries.length) return;
  const ratio = options.ratio || 1;
  const left = plot.left;
  const right = canvas.width - plot.right;
  const top = plot.top;
  const bottom = canvas.height - plot.bottom;
  const selectedKey = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const snapshot = chartCursorSnapshot(visibleSeries, selectedKey, clamp(cursor.x, left, right));
  if (!snapshot) return;
  const { anchorPoint: mainPoint, samples } = snapshot;
  const x = clamp(mainPoint.x, left, right);
  const y = clamp(mainPoint.y, top, bottom);
  const timeLabel = options.timeLabel ? options.timeLabel(mainPoint) : (mainPoint.time || "");
  const valueFormatter = options.valueFormatter || formatNumber;
  const maxSeries = Math.max(1, Number(options.maxSeries) || 6);

  ctx.save();
  ctx.strokeStyle = "rgba(29, 57, 66, 0.58)";
  ctx.lineWidth = 1 * ratio;
  ctx.setLineDash([5 * ratio, 4 * ratio]);
  ctx.beginPath();
  ctx.moveTo(x, top);
  ctx.lineTo(x, bottom);
  if (!options.inlineSeriesLabels) {
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
  }
  ctx.stroke();
  ctx.setLineDash([]);

  const palette = chartThemePalette();
  samples.forEach(({ series, point }) => {
    ctx.fillStyle = palette.markerFill;
    ctx.strokeStyle = series.color;
    ctx.lineWidth = 2 * ratio;
    ctx.beginPath();
    ctx.arc(point.x, point.y, 4.5 * ratio, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  if (options.inlineSeriesLabels) {
    drawInlineChartCursorLabels(ctx, canvas, plot, x, samples, {
      ratio,
      maxSeries,
      timeLabel,
      valueFormatter,
    });
    ctx.restore();
    return;
  }

  ctx.font = `${12 * ratio}px Microsoft YaHei, Arial`;
  const lines = [
    timeLabel ? `时刻: ${timeLabel}` : "",
    ...samples.slice(0, maxSeries).map(({ series, point }) => `${series.label}: ${valueFormatter(point.value)}${series.unit ? ` ${series.unit}` : ""}`),
    samples.length > maxSeries ? `另有 ${samples.length - maxSeries} 条曲线` : "",
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

const TRAINEE_PAGE_ROUTES = {
  "/": "overview",
  "/overview": "overview",
  "/model": "model",
  "/diagram": "diagram",
  "/curves": "curves",
  "/measurements": "measurements",
  "/commands": "commands",
  "/renewable": "renewable",
  "/manual-changes": "manual-changes",
  "/parameters": "parameters",
  "/history": "history",
};

function normalizePagePath(pathname) {
  const path = String(pathname || "/").replace(/\/+$/, "") || "/";
  return path.startsWith("/") ? path : `/${path}`;
}

function pagePath(page) {
  return page === "overview" ? "/" : `/${page}`;
}

function pageFromLocation() {
  const fallback = document.querySelector(".app-shell")?.dataset.defaultPage || "overview";
  const hashPage = (location.hash || "").replace("#", "").trim();
  if (hashPage) return hashPage;
  return TRAINEE_PAGE_ROUTES[normalizePagePath(location.pathname)] || fallback;
}

function currentPageName() {
  return state.activePage || document.querySelector("[data-page].is-active")?.dataset.page || pageFromLocation();
}

function collectPageSections() {
  const main = document.querySelector(".page-main");
  if (!main) return;
  state.pageMain = main;
  state.pageSections = {};
  Array.from(main.children).forEach((section) => {
    if (!(section instanceof HTMLElement) || !section.dataset.page) return;
    section.classList.remove("is-active");
    state.pageSections[section.dataset.page] = section;
    section.remove();
  });
}

function mountPageSection(page) {
  const main = state.pageMain || document.querySelector(".page-main");
  const section = state.pageSections?.[page];
  if (!main || !section) return;
  const current = Array.from(main.children).find((child) => child instanceof HTMLElement && child.dataset.page);
  if (current === section) {
    section.classList.add("is-active");
    return;
  }
  if (current) {
    current.classList.remove("is-active");
    current.remove();
  }
  section.classList.add("is-active");
  main.appendChild(section);
}

function showPage(page, updateHash = true) {
  const target = state.pageSections?.[page] ? page : "overview";
  state.activePage = target;
  mountPageSection(target);
  document.querySelectorAll("[data-nav-page]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.navPage === target);
  });
  const nextPath = pagePath(target);
  if (updateHash && normalizePagePath(location.pathname) !== nextPath) {
    history.pushState(null, "", nextPath);
  } else if (location.hash) {
    history.replaceState(null, "", nextPath);
  }
  requestAnimationFrame(() => {
    renderActiveTraineePage(state.snapshot || {}, true);
    if (target === "renewable") refreshRenewableControlState({ preview: false });
  });
}

function initPageNavigation() {
  collectPageSections();
  document.querySelectorAll("[data-nav-page]").forEach((button) => {
    button.addEventListener("click", () => showPage(button.dataset.navPage));
  });
  window.addEventListener("popstate", () => showPage(pageFromLocation(), false));
  window.addEventListener("hashchange", () => showPage(pageFromLocation(), true));
  showPage(pageFromLocation(), false);
}

function modelScopedPath(path) {
  if (!state.activeModelId) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}model_id=${encodeURIComponent(state.activeModelId)}`;
}

function teacherScopedPath(path) {
  if (!state.activeModelId) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}model_id=${encodeURIComponent(state.activeModelId)}`;
}

function recordFrontendRequestDiagnostics(path, response, durationMs) {
  const diagnostics = state.frontendDiagnostics;
  const responseBytes = Math.max(0, Number(response?.headers?.get?.("Content-Length")) || 0);
  diagnostics.requestCount += 1;
  diagnostics.responseBytes += responseBytes;
  diagnostics.requestDurationMs += Math.max(0, Number(durationMs) || 0);
  if (/\/api\/(?:trainee\/)?snapshot(?:\?|$)/.test(String(path || ""))) {
    diagnostics.snapshotRequestCount += 1;
    diagnostics.snapshotResponseBytes += responseBytes;
  }
}

async function api(path, options = {}) {
  const {
    modelScoped = true,
    timeoutMs = frontendRequestTimeoutMs(),
    signal: callerSignal,
    ...fetchOptions
  } = options;
  const targetPath = modelScoped ? modelScopedPath(path) : path;
  const requestStartedAtMs = performance.now();
  const controller = new AbortController();
  const boundedTimeout = Math.max(0, Number(timeoutMs) || 0);
  let timedOut = false;
  const abortFromCaller = () => controller.abort();
  const timeoutId = boundedTimeout
    ? setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, boundedTimeout)
    : null;
  if (callerSignal) {
    if (callerSignal.aborted) controller.abort();
    else callerSignal.addEventListener("abort", abortFromCaller, { once: true });
  }
  try {
    const response = await fetch(`${apiBase}${targetPath}`, {
      ...fetchOptions,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
    });
    recordFrontendRequestDiagnostics(
      targetPath,
      response,
      performance.now() - requestStartedAtMs,
    );
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  } catch (error) {
    if (timedOut) throw new Error(`请求超时（${Math.round(boundedTimeout / 1000)} 秒）`);
    throw error;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
    callerSignal?.removeEventListener?.("abort", abortFromCaller);
  }
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
  state.webRuntimeSavingGroup = "";
  state.webRuntimeDirtyGroups = { backend: false, web: false };
  state.webRuntimeErrors = { load: "", backend: "", web: "" };
}

function runtimeSettingDisplay(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return Number.isInteger(number) ? String(number) : String(Number(number.toFixed(3)));
}

function runtimeParameterGroupStatus(group) {
  if (state.webRuntimeLoading) return "加载中";
  if (state.webRuntimeSavingGroup === group) return "保存中";
  const error = state.webRuntimeErrors?.[group] || state.webRuntimeErrors?.load || "";
  if (error) return `失败：${error}`;
  return runtimeParameterGroupDirty(group) ? "有未保存修改" : "已生效";
}

function renderWebRuntimeSettings() {
  const root = state.pageSections?.parameters || document;
  root.querySelectorAll?.("[data-runtime-setting]").forEach((input) => {
    const name = input.dataset.runtimeSetting || "";
    const group = runtimeParameterGroup(name);
    const values = runtimeParameterGroupDirty(group) ? state.webRuntimeDraft : state.webRuntimeSettings;
    const value = Number(values?.[name]);
    if (Number.isFinite(value) && document.activeElement !== input) {
      setSelectNumericValue(input, value);
    }
    const constraint = state.webRuntimeConstraints?.[name] || {};
    if (input.tagName !== "SELECT") {
      if (constraint.min !== undefined) input.min = String(constraint.min);
      if (constraint.max !== undefined) input.max = String(constraint.max);
    }
    input.disabled = state.webRuntimeLoading || Boolean(state.webRuntimeSavingGroup);
  });
  Object.entries(WEB_RUNTIME_CURRENT_IDS).forEach(([name, id]) => {
    const node = runtimeParameterElement(id);
    if (node) node.textContent = runtimeSettingDisplay(state.webRuntimeSettings?.[name]);
  });
  const activeModel = state.models.find((model) => model.id === state.activeModelId);
  const modelName = activeModel?.name || state.snapshot?.model?.name || state.activeModelId || "--";
  const valuesById = {
    runtimeParameterModelName: modelName,
    runtimeParameterUpdatedAt: state.webRuntimeUpdatedAt || "尚未保存（使用默认值）",
    runtimeParameterFrontendRefreshState: `${runtimeSettingDisplay(activeRuntimeSetting("frontend_refresh_seconds"))} s`,
    runtimeParameterBackendRefreshState: `${runtimeSettingDisplay(activeRuntimeSetting("backend_refresh_seconds"))} s`,
    runtimeParameterFrontendTimeoutState: `${runtimeSettingDisplay(activeRuntimeSetting("frontend_request_timeout_seconds"))} s`,
    runtimeParameterBackendTimeoutState: `${runtimeSettingDisplay(activeRuntimeSetting("backend_request_timeout_seconds"))} s`,
    runtimeParameterReceiveState: state.receiveMode ? "正在接收" : "未启动接收",
  };
  Object.entries(valuesById).forEach(([id, text]) => {
    const node = runtimeParameterElement(id);
    if (node) node.textContent = text;
  });
  const backendStatus = runtimeParameterGroupStatus("backend");
  const webStatus = runtimeParameterGroupStatus("web");
  const backendSummary = runtimeParameterElement("backendRuntimeParameterSummary");
  const webSummary = runtimeParameterElement("runtimeParameterSummary");
  if (backendSummary) backendSummary.textContent = backendStatus;
  if (webSummary) webSummary.textContent = webStatus;
  const backendState = runtimeParameterElement("backendRuntimeParameterState");
  const webState = runtimeParameterElement("webRuntimeParameterState");
  if (backendState) backendState.textContent = backendStatus;
  if (webState) webState.textContent = webStatus;
  const stateNode = runtimeParameterElement("runtimeParameterState");
  if (stateNode) stateNode.textContent = `后台：${backendStatus} · WEB：${webStatus}`;

  const saving = Boolean(state.webRuntimeSavingGroup);
  const buttonGroups = {
    backend: {
      save: "saveBackendRuntimeParameters",
      undo: "undoBackendRuntimeParameters",
      defaults: "restoreBackendRuntimeParameterDefaults",
    },
    web: {
      save: "saveRuntimeParameters",
      undo: "undoRuntimeParameters",
      defaults: "restoreRuntimeParameterDefaults",
    },
  };
  Object.entries(buttonGroups).forEach(([group, ids]) => {
    const dirty = runtimeParameterGroupDirty(group);
    const saveButton = runtimeParameterElement(ids.save);
    const undoButton = runtimeParameterElement(ids.undo);
    const defaultsButton = runtimeParameterElement(ids.defaults);
    if (saveButton) saveButton.disabled = !dirty || state.webRuntimeLoading || saving;
    if (undoButton) undoButton.disabled = !dirty || state.webRuntimeLoading || saving;
    if (defaultsButton) defaultsButton.disabled = state.webRuntimeLoading || saving;
  });
}

function applyWebRuntimeSettings() {
  state.runtimeLogPageSize = Math.max(5, Math.round(activeRuntimeSetting("runtime_log_page_size")));
  const logLimit = Math.max(50, Math.round(activeRuntimeSetting("runtime_log_cache_limit")));
  state.runtimeLogs = state.runtimeLogs.slice(0, logLimit);
  state.measurementTraceHistory = compactTraceHistory(state.measurementTraceHistory, state.measurementTraceWindowMinutes);
  state.commandTraceHistory = compactTraceHistory(state.commandTraceHistory, state.commandTraceWindowMinutes);
  state.renewableTrendHistory = compactTraceHistory(state.renewableTrendHistory, state.renewableTrendWindowMinutes);
  restartRefreshScheduler();
}

async function loadWebRuntimeSettings(force = false) {
  const modelId = state.activeModelId;
  if (!modelId) return null;
  if (!force && state.webRuntimeLoadedModelId === modelId) {
    renderWebRuntimeSettings();
    return state.webRuntimeSettings;
  }
  state.webRuntimeLoading = true;
  state.webRuntimeErrors = { load: "", backend: "", web: "" };
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
    state.webRuntimeDirtyGroups = { backend: false, web: false };
    applyWebRuntimeSettings();
    return payload;
  } catch (error) {
    if (modelId === state.activeModelId) state.webRuntimeErrors.load = apiErrorText(error);
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
  const group = runtimeParameterGroup(name);
  if (!name || !group) return;
  const value = Number(input.value);
  state.webRuntimeDraft = {
    ...state.webRuntimeDraft,
    [name]: Number.isFinite(value) ? value : input.value,
  };
  state.webRuntimeDirtyGroups = { ...state.webRuntimeDirtyGroups, [group]: true };
  state.webRuntimeErrors = { ...state.webRuntimeErrors, [group]: "" };
  renderWebRuntimeSettings();
}

async function saveWebRuntimeSettings(group = "web") {
  if (!RUNTIME_PARAMETER_GROUPS[group] || state.webRuntimeSavingGroup || !runtimeParameterGroupDirty(group)) return;
  const pendingDraft = { ...state.webRuntimeDraft };
  state.webRuntimeSavingGroup = group;
  state.webRuntimeErrors = { ...state.webRuntimeErrors, [group]: "" };
  renderWebRuntimeSettings();
  try {
    const payload = await api("/api/runtime-settings", {
      method: "POST",
      body: JSON.stringify({ settings: runtimeParameterGroupValues(pendingDraft, group) }),
    });
    state.webRuntimeSettings = { ...WEB_RUNTIME_FALLBACKS, ...(payload.settings || {}) };
    state.webRuntimeDefaults = { ...WEB_RUNTIME_FALLBACKS, ...(payload.defaults || {}) };
    state.webRuntimeConstraints = payload.constraints || {};
    state.webRuntimeDraft = { ...state.webRuntimeSettings };
    Object.keys(RUNTIME_PARAMETER_GROUPS).forEach((otherGroup) => {
      if (otherGroup === group || !runtimeParameterGroupDirty(otherGroup)) return;
      Object.assign(
        state.webRuntimeDraft,
        runtimeParameterGroupValues(pendingDraft, otherGroup),
      );
    });
    state.webRuntimeUpdatedAt = payload.updatedAt || "";
    state.webRuntimeLoadedModelId = state.activeModelId;
    state.webRuntimeDirtyGroups = { ...state.webRuntimeDirtyGroups, [group]: false };
    applyWebRuntimeSettings();
  } catch (error) {
    state.webRuntimeErrors = { ...state.webRuntimeErrors, [group]: apiErrorText(error) };
  } finally {
    state.webRuntimeSavingGroup = "";
    renderWebRuntimeSettings();
  }
}

function undoWebRuntimeSettings(group = "web") {
  if (!RUNTIME_PARAMETER_GROUPS[group]) return;
  state.webRuntimeDraft = {
    ...state.webRuntimeDraft,
    ...runtimeParameterGroupValues(state.webRuntimeSettings, group),
  };
  state.webRuntimeDirtyGroups = { ...state.webRuntimeDirtyGroups, [group]: false };
  state.webRuntimeErrors = { ...state.webRuntimeErrors, [group]: "" };
  renderWebRuntimeSettings();
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

const UI_THEME_PRESETS = [
  { id: "minimalist-light", label: "极简明亮", scheme: "light" },
  { id: "precision-dark", label: "精密暗黑", scheme: "dark" },
  { id: "bento-grid", label: "便当盒网格", scheme: "light" },
  { id: "glassmorphism", label: "毛玻璃拟态", scheme: "dark" },
  { id: "editorial", label: "编辑杂志", scheme: "light" },
  { id: "sci-fi-cyan", label: "科幻 · 电光青", scheme: "dark" },
  { id: "sci-fi-purple", label: "科幻 · 赛博紫", scheme: "dark" },
  { id: "sci-fi-matrix", label: "科幻 · 矩阵绿", scheme: "dark" },
];

const UI_THEME_MAP = new Map(UI_THEME_PRESETS.map((item) => [item.id, item]));
const LEGACY_UI_THEME_MAP = {
  dark: "precision-dark",
  light: "minimalist-light",
  "sci-fi": "sci-fi-cyan",
  "neo-brutalism": "minimalist-light",
};

function normalizeUiTheme(raw) {
  const mapped = LEGACY_UI_THEME_MAP[raw] || raw;
  return UI_THEME_MAP.has(mapped) ? mapped : "minimalist-light";
}

function currentUiTheme() {
  return normalizeUiTheme(document.documentElement.dataset.theme);
}

function applyUiTheme(themeId, { persist = true, notify = false, redraw = true } = {}) {
  const resolved = normalizeUiTheme(themeId);
  const meta = UI_THEME_MAP.get(resolved) || UI_THEME_PRESETS[0];
  document.documentElement.dataset.theme = meta.id;
  document.documentElement.dataset.colorScheme = meta.scheme;
  const selector = $("themeSelector");
  if (selector && selector.value !== meta.id) {
    selector.value = meta.id;
  }
  if (persist) {
    try {
      localStorage.setItem("polarUiTheme", meta.id);
    } catch (_e) {}
  }
  if (redraw) {
    redrawActiveTraineeCharts();
  }
  if (notify) {
    const themeName = typeof t === "function" ? t(`theme.${meta.id}`) : meta.label;
    const msg = typeof t === "function" ? t("toast.themeChanged", { name: themeName }) : `已切换至「${meta.label}」风格`;
    showUiToast(msg, "info", 2000);
  }
  return meta;
}

function chartThemePalette() {
  const theme = currentUiTheme();
  if (theme === "sci-fi-cyan") {
    return {
      bg: "#061020",
      grid: "rgba(0, 229, 255, 0.14)",
      gridSubtle: "rgba(0, 229, 255, 0.07)",
      axis: "rgba(0, 229, 255, 0.34)",
      text: "#7da2c4",
      markerFill: "#061020",
      tooltipBg: "rgba(8, 17, 33, 0.96)",
      tooltipBorder: "rgba(0, 229, 255, 0.42)",
      tooltipTitle: "#e6f7ff",
      tooltipText: "#bae6fd",
    };
  }
  if (theme === "sci-fi-purple") {
    return {
      bg: "#120c24",
      grid: "rgba(192, 132, 252, 0.15)",
      gridSubtle: "rgba(192, 132, 252, 0.08)",
      axis: "rgba(192, 132, 252, 0.36)",
      text: "#a695c9",
      markerFill: "#120c24",
      tooltipBg: "rgba(18, 12, 36, 0.96)",
      tooltipBorder: "rgba(192, 132, 252, 0.44)",
      tooltipTitle: "#f3eeff",
      tooltipText: "#d8b4fe",
    };
  }
  if (theme === "sci-fi-matrix") {
    return {
      bg: "#081810",
      grid: "rgba(0, 230, 118, 0.14)",
      gridSubtle: "rgba(0, 230, 118, 0.07)",
      axis: "rgba(0, 230, 118, 0.34)",
      text: "#7eb396",
      markerFill: "#081810",
      tooltipBg: "rgba(8, 24, 16, 0.96)",
      tooltipBorder: "rgba(0, 230, 118, 0.42)",
      tooltipTitle: "#e2fbe9",
      tooltipText: "#a7f3d0",
    };
  }
  if (theme === "glassmorphism") {
    return {
      bg: "#0f172a",
      grid: "rgba(203, 213, 225, 0.14)",
      gridSubtle: "rgba(203, 213, 225, 0.08)",
      axis: "rgba(148, 163, 184, 0.34)",
      text: "#cbd5e1",
      markerFill: "#0f172a",
      tooltipBg: "rgba(15, 23, 42, 0.94)",
      tooltipBorder: "rgba(96, 165, 250, 0.42)",
      tooltipTitle: "#f8fafc",
      tooltipText: "#e2e8f0",
    };
  }
  if (theme === "precision-dark") {
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
  if (theme === "editorial") {
    return {
      bg: "#faf9f6",
      grid: "#e4e4e7",
      gridSubtle: "#f0eee9",
      axis: "#a1a1aa",
      text: "#52525b",
      markerFill: "#ffffff",
      tooltipBg: "rgba(255, 255, 255, 0.98)",
      tooltipBorder: "#d4d4d8",
      tooltipTitle: "#18181b",
      tooltipText: "#3f3f46",
    };
  }
  if (theme === "bento-grid") {
    return {
      bg: "#fbfbfd",
      grid: "#e5e5ea",
      gridSubtle: "#f0f0f5",
      axis: "#c7c7cc",
      text: "#6e6e73",
      markerFill: "#ffffff",
      tooltipBg: "rgba(255, 255, 255, 0.97)",
      tooltipBorder: "rgba(0, 0, 0, 0.12)",
      tooltipTitle: "#1d1d1f",
      tooltipText: "#3a3a3c",
    };
  }
  return {
    bg: "#fcfeff",
    grid: "#e2e8f0",
    gridSubtle: "#f1f5f9",
    axis: "#cbd5e1",
    text: "#64748b",
    markerFill: "#ffffff",
    tooltipBg: "rgba(255, 255, 255, 0.96)",
    tooltipBorder: "rgba(148, 163, 184, 0.6)",
    tooltipTitle: "#0f172a",
    tooltipText: "#334155",
  };
}

function redrawActiveTraineeCharts() {
  const page = typeof currentPageName === "function" ? currentPageName() : "";
  if (page === "measurements" && typeof drawMeasurementTraceChart === "function") {
    drawMeasurementTraceChart();
  } else if (page === "controls" && typeof drawCommandTraceChart === "function") {
    drawCommandTraceChart();
  } else if (page === "renewable" && typeof drawRenewableTrendChart === "function") {
    drawRenewableTrendChart();
  } else if (page === "curves" && typeof drawCurveDisplay === "function") {
    drawCurveDisplay(state.snapshot || {});
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

function initPrecisionUiChrome() {
  const themeSelector = $("themeSelector");
  let initialTheme = currentUiTheme();
  try {
    const stored = localStorage.getItem("polarUiTheme");
    if (stored) initialTheme = normalizeUiTheme(stored);
  } catch (_e) {}
  applyUiTheme(initialTheme, { persist: false, notify: false, redraw: false });
  if (themeSelector) {
    themeSelector.addEventListener("change", () => {
      applyUiTheme(themeSelector.value, { persist: true, notify: true, redraw: true });
    });
  }
  window.addEventListener("storage", (event) => {
    if (event.key === "polarUiTheme") {
      applyUiTheme(event.newValue, { persist: false, notify: false, redraw: true });
    }
  });
  if (typeof initUiI18n === "function") {
    initUiI18n();
  }
  // 为所有含左侧设备树的页面注入一键折叠/展开按钮，扩大表格与曲线主可视区。
  document.querySelectorAll(".device-tree-panel").forEach((aside) => {
    const head = aside.querySelector(".panel-head");
    if (!head || head.querySelector(".tree-collapse-btn")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tree-collapse-btn";
    btn.dataset.i18n = "tree.collapse";
    btn.textContent = typeof t === "function" ? t("tree.collapse") : "收起";
    btn.title = typeof t === "function" ? t("tree.toggleTitle") : "折叠/展开左侧设备树面板";
    btn.addEventListener("click", () => {
      const collapsed = aside.classList.toggle("is-collapsed");
      btn.dataset.i18n = collapsed ? "tree.expand" : "tree.collapse";
      btn.textContent = typeof t === "function" ? t(btn.dataset.i18n) : (collapsed ? "展开" : "收起");
      requestAnimationFrame(redrawActiveTraineeCharts);
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

async function restoreWebRuntimeDefaults(group = "web") {
  if (!RUNTIME_PARAMETER_GROUPS[group]) return;
  const label = group === "backend" ? "后台运行参数" : "WEB 运行参数";
  const confirmed = await confirmDangerousAction({
    title: `恢复默认${label}？`,
    target: label,
    message: `将把当前${label}表单重置为系统默认值（点击保存后正式生效）。`,
    confirmLabel: "确认恢复",
  });
  if (!confirmed) return;
  state.webRuntimeDraft = {
    ...state.webRuntimeDraft,
    ...runtimeParameterGroupValues(state.webRuntimeDefaults, group),
  };
  state.webRuntimeDirtyGroups = { ...state.webRuntimeDirtyGroups, [group]: true };
  state.webRuntimeErrors = { ...state.webRuntimeErrors, [group]: "" };
  renderWebRuntimeSettings();
  showUiToast(`已填充默认${label}，点击保存生效`, "ok");
}

function invalidateManualDefinitionChanges() {
  state.manualDefinitionChanges = [];
  state.manualDefinitionChangesRevision = 0;
  state.manualDefinitionChangesLoadedModelId = "";
  state.manualDefinitionChangesLoading = false;
  state.manualDefinitionChangesResetting = false;
  state.manualDefinitionChangesRetrying = false;
  state.manualDefinitionChangesError = "";
  state.manualDefinitionChangesMessage = "";
  state.manualDefinitionChangesMessageWarning = false;
  state.manualDefinitionChangeSelection = new Set();
}

function manualDefinitionChangeValue(change, key) {
  const value = String(change?.[key] ?? "");
  if (change?.field === "valid") {
    return Number(value) === 1 ? "有效（1）" : "无效（0）";
  }
  if (change?.field === "weight") {
    const sigmaKey = key === "default_value" ? "default_error_sigma" : "current_error_sigma";
    const sigma = Number(change?.[sigmaKey]);
    return Number.isFinite(sigma) && sigma > 0
      ? `${value || "--"} / σ ${Number(sigma.toPrecision(6))}`
      : (value || "--");
  }
  return value || "--";
}

function renderManualDefinitionChanges() {
  const container = $("manualDefinitionChangesTable");
  if (!container) return;
  const changes = Array.isArray(state.manualDefinitionChanges) ? state.manualDefinitionChanges : [];
  const availableIds = new Set(changes.map((item) => String(item.id || "")));
  state.manualDefinitionChangeSelection = new Set(
    [...state.manualDefinitionChangeSelection].filter((changeId) => availableIds.has(changeId)),
  );
  const selectedCount = state.manualDefinitionChangeSelection.size;
  const pendingChanges = changes.filter((item) => !item.persisted);
  const summary = $("manualDefinitionChangesSummary");
  if (summary) summary.textContent = `${changes.length} 项修改 · ${pendingChanges.length} 项未保存 · 已选 ${selectedCount} 项`;
  const message = $("manualDefinitionChangesMessage");
  if (message) {
    const text = state.manualDefinitionChangesError || state.manualDefinitionChangesMessage || "";
    message.textContent = text;
    message.hidden = !text;
    message.classList.toggle("is-error", Boolean(state.manualDefinitionChangesError));
    message.classList.toggle(
      "is-warning",
      !state.manualDefinitionChangesError
        && (state.manualDefinitionChangesMessageWarning || pendingChanges.length > 0),
    );
  }
  const resetButton = $("resetSelectedManualChanges");
  if (resetButton) {
    resetButton.disabled = !selectedCount || state.manualDefinitionChangesLoading || state.manualDefinitionChangesResetting || state.manualDefinitionChangesRetrying;
    resetButton.textContent = state.manualDefinitionChangesResetting ? "恢复中" : "恢复默认值";
  }
  const refreshButton = $("refreshManualChanges");
  if (refreshButton) {
    refreshButton.disabled = state.manualDefinitionChangesLoading || state.manualDefinitionChangesResetting || state.manualDefinitionChangesRetrying;
    refreshButton.textContent = state.manualDefinitionChangesLoading ? "刷新中" : "刷新";
  }
  const retryButton = $("retryPendingManualChanges");
  if (retryButton) {
    retryButton.disabled = !pendingChanges.length || state.manualDefinitionChangesLoading || state.manualDefinitionChangesResetting || state.manualDefinitionChangesRetrying;
    retryButton.textContent = state.manualDefinitionChangesRetrying ? "保存中" : "重试保存";
  }

  if (state.manualDefinitionChangesLoading && !changes.length) {
    container.innerHTML = '<div class="empty-state">正在加载人工修改记录...</div>';
    return;
  }
  if (state.manualDefinitionChangesError && !changes.length) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(state.manualDefinitionChangesError)}</div>`;
    return;
  }
  if (!changes.length) {
    container.innerHTML = '<div class="empty-state">当前模型没有人工修改</div>';
    return;
  }

  const allSelected = changes.every((item) => state.manualDefinitionChangeSelection.has(String(item.id || "")));
  container.innerHTML = `
    <table class="manual-definition-changes-table">
      <thead>
        <tr>
          <th class="manual-change-select-cell">
            <input type="checkbox" data-manual-change-select-all aria-label="选择全部人工修改" ${allSelected ? "checked" : ""} />
          </th>
          <th>对象</th>
          <th>修改类型</th>
          <th>参数 / 状态项</th>
          <th>默认值</th>
          <th>当前值</th>
          <th>修改时间</th>
          <th>保存状态</th>
        </tr>
      </thead>
      <tbody>
        ${changes.map((change) => {
          const changeId = String(change.id || "");
          const checked = state.manualDefinitionChangeSelection.has(changeId);
          const modifiedAt = String(change.modified_at || "").replace("T", " ") || "--";
          return `
            <tr class="${checked ? "is-selected" : ""}">
              <td class="manual-change-select-cell">
                <input type="checkbox" data-manual-change-id="${escapeHtml(changeId)}" aria-label="选择 ${escapeHtml(change.object_label || change.object_name || changeId)}" ${checked ? "checked" : ""} />
              </td>
              <td>
                <strong>${escapeHtml(change.object_label || change.object_name || "--")}</strong>
                <small>${escapeHtml(change.measurement_type || change.source_file || "")}</small>
              </td>
              <td>${escapeHtml(change.change_type || "--")}</td>
              <td><code>${escapeHtml(change.field_label || change.field || "--")}</code></td>
              <td class="manual-change-value-cell">${escapeHtml(manualDefinitionChangeValue(change, "default_value"))}</td>
              <td class="manual-change-value-cell">${escapeHtml(manualDefinitionChangeValue(change, "current_value"))}</td>
              <td>${escapeHtml(modifiedAt)}</td>
              <td>
                <span class="manual-change-persistence ${change.persisted ? "is-saved" : "is-warning"}" title="${escapeHtml(change.last_sync_error || "")}">
                  ${escapeHtml(change.persistence_status || (change.persisted ? "已保存" : "保存失败"))}
                </span>
              </td>
            </tr>`;
        }).join("")}
      </tbody>
    </table>`;
  const selectAll = container.querySelector("[data-manual-change-select-all]");
  if (selectAll) selectAll.indeterminate = selectedCount > 0 && !allSelected;
}

function toggleManualDefinitionChange(changeId, selected) {
  const normalizedId = String(changeId || "");
  if (!normalizedId) return;
  if (selected === undefined) {
    if (state.manualDefinitionChangeSelection.has(normalizedId)) state.manualDefinitionChangeSelection.delete(normalizedId);
    else state.manualDefinitionChangeSelection.add(normalizedId);
  } else if (selected) {
    state.manualDefinitionChangeSelection.add(normalizedId);
  } else {
    state.manualDefinitionChangeSelection.delete(normalizedId);
  }
  renderManualDefinitionChanges();
}

async function loadManualDefinitionChanges() {
  if (state.manualDefinitionChangesLoading || state.manualDefinitionChangesResetting || state.manualDefinitionChangesRetrying) return;
  const requestedModelId = state.activeModelId;
  state.manualDefinitionChangesLoading = true;
  state.manualDefinitionChangesError = "";
  state.manualDefinitionChangesMessage = "";
  state.manualDefinitionChangesMessageWarning = false;
  renderManualDefinitionChanges();
  try {
    const payload = await api("/api/definitions/manual-changes");
    if (requestedModelId !== state.activeModelId) return;
    state.manualDefinitionChanges = Array.isArray(payload.changes) ? payload.changes : [];
    state.manualDefinitionChangesRevision = Number(payload.revision) || 0;
    state.manualDefinitionChangesLoadedModelId = requestedModelId;
    state.manualDefinitionChangesMessage = `已加载 ${state.manualDefinitionChanges.length} 项人工修改`;
  } catch (error) {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesError = apiErrorText(error);
      state.manualDefinitionChangesLoadedModelId = "";
    }
  } finally {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesLoading = false;
      renderManualDefinitionChanges();
    }
  }
}

async function retryPendingManualDefinitionChanges() {
  if (state.manualDefinitionChangesRetrying) return;
  const changeIds = state.manualDefinitionChanges
    .filter((item) => !item.persisted)
    .map((item) => String(item.id || ""))
    .filter(Boolean);
  if (!changeIds.length) return;
  const requestedModelId = state.activeModelId;
  state.manualDefinitionChangesRetrying = true;
  state.manualDefinitionChangesError = "";
  state.manualDefinitionChangesMessage = "正在重新保存人工覆盖层";
  state.manualDefinitionChangesMessageWarning = false;
  renderManualDefinitionChanges();
  try {
    const result = await api("/api/definitions/manual-changes/retry", {
      method: "POST",
      body: JSON.stringify({
        revision: state.manualDefinitionChangesRevision,
        change_ids: changeIds,
      }),
    });
    if (requestedModelId !== state.activeModelId) return;
    state.manualDefinitionChanges = Array.isArray(result.changes) ? result.changes : [];
    state.manualDefinitionChangesRevision = Number(result.revision) || 0;
    state.manualDefinitionChangesLoadedModelId = requestedModelId;
    const resultWarning = definitionEditResultHasWarning(result);
    state.manualDefinitionChangesMessageWarning = resultWarning;
    state.manualDefinitionChangesMessage = result.warning
      || (resultWarning
        ? "重试保存未完整完成，请查看保存状态并重试"
        : `已重新保存 ${Number(result.persisted_count) || 0} 项人工修改`);
    await reloadLocalDefinitionSnapshotAfterEdit(requestedModelId);
    renderSnapshot(state.snapshot || {});
  } catch (error) {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesError = apiErrorText(error);
      state.manualDefinitionChangesLoadedModelId = "";
    }
  } finally {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesRetrying = false;
      renderManualDefinitionChanges();
    }
  }
}

async function resetSelectedManualDefinitionChanges() {
  if (state.manualDefinitionChangesResetting) return;
  const changeIds = [...state.manualDefinitionChangeSelection];
  if (!changeIds.length) return;
  const confirmed = await confirmDangerousAction({
    title: "恢复选中人工修改为默认值？",
    target: `共 ${changeIds.length} 项人工定义修改`,
    message: "将从原始 E 文件恢复所选参数的默认值，当前人工修改记录将被清除。",
    confirmLabel: "确认恢复",
  });
  if (!confirmed) return;
  const requestedModelId = state.activeModelId;
  state.manualDefinitionChangesResetting = true;
  state.manualDefinitionChangesError = "";
  state.manualDefinitionChangesMessage = "正在从原始 E 文件恢复默认值";
  state.manualDefinitionChangesMessageWarning = false;
  renderManualDefinitionChanges();
  try {
    const result = await api("/api/definitions/manual-changes/reset", {
      method: "POST",
      body: JSON.stringify({
        revision: state.manualDefinitionChangesRevision,
        change_ids: changeIds,
      }),
    });
    if (requestedModelId !== state.activeModelId) return;
    state.manualDefinitionChanges = Array.isArray(result.changes) ? result.changes : [];
    state.manualDefinitionChangesRevision = Number(result.revision) || 0;
    state.manualDefinitionChangesLoadedModelId = requestedModelId;
    state.manualDefinitionChangeSelection = new Set();
    const resultWarning = definitionEditResultHasWarning(result);
    state.manualDefinitionChangesMessageWarning = resultWarning;
    state.manualDefinitionChangesMessage = result.warning
      || (resultWarning
        ? "恢复默认值未完整完成，请查看保存状态并重试"
        : `已恢复 ${Number(result.reset_count) || changeIds.length} 项人工修改`);
    await reloadLocalDefinitionSnapshotAfterEdit(requestedModelId);
    renderSnapshot(state.snapshot || {});
  } catch (error) {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesError = apiErrorText(error);
      state.manualDefinitionChangesLoadedModelId = "";
    }
  } finally {
    if (requestedModelId === state.activeModelId) {
      state.manualDefinitionChangesResetting = false;
      renderManualDefinitionChanges();
    }
  }
}

const STATIC_SNAPSHOT_KEYS = [
  "files",
  "source_files",
  "work_files",
  "definitions",
  "curves",
  "settings",
  "device_parameters",
  "diagram",
];

const STATIC_SNAPSHOT_KEYS_BY_PAGE = {
  "overview": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "model": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "diagram": ["files", "source_files", "work_files", "definitions", "diagram"],
  "curves": ["files", "source_files", "work_files", "definitions", "curves"],
  "measurements": ["files", "source_files", "work_files", "definitions"],
  "commands": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "renewable": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "manual-changes": ["definitions", "device_parameters"],
  "parameters": [],
  "history": [],
};
const CACHEABLE_STATIC_KEYS = STATIC_SNAPSHOT_KEYS.filter((key) => key !== "curves");
let staticCacheStoreMemory = null;

function staticSnapshotKeysForPage(page = currentPageName()) {
  return STATIC_SNAPSHOT_KEYS_BY_PAGE[page] || STATIC_SNAPSHOT_KEYS;
}

function hasStaticSnapshotPayload(snapshot, requiredKeys = STATIC_SNAPSHOT_KEYS) {
  return Boolean(snapshot && requiredKeys.every((key) => snapshot[key] !== undefined));
}

function frozenSnapshotNeedsBootstrap(snapshot, page = currentPageName()) {
  return Boolean(
    state.frozen
    && !hasStaticSnapshotPayload(snapshot, staticSnapshotKeysForPage(page))
  );
}

function staticMetaSignature(meta) {
  return JSON.stringify(meta || null);
}

function staticMetaMatches(left, right) {
  return staticMetaSignature(left) === staticMetaSignature(right);
}

function staticCacheModelKey(snapshot = state.snapshot || {}) {
  const modelId = String(state.activeModelId || snapshot?.model?.id || "");
  if (!modelId) return "";
  return `local|${modelId}`;
}

function readStaticCacheStore() {
  if (staticCacheStoreMemory) return staticCacheStoreMemory;
  try {
    const raw = localStorage.getItem(STATIC_CACHE_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    staticCacheStoreMemory = parsed && typeof parsed === "object" ? parsed : {};
  } catch (_error) {
    staticCacheStoreMemory = {};
  }
  return staticCacheStoreMemory;
}

function writeStaticCacheStore(store) {
  staticCacheStoreMemory = store;
  try {
    localStorage.setItem(STATIC_CACHE_STORAGE_KEY, JSON.stringify(store));
    return true;
  } catch (_error) {
    return false;
  }
}

function clearStaticSnapshotCacheForModel(modelId = state.activeModelId) {
  const key = `local|${String(modelId || "")}`;
  if (key === "local|") return;
  const store = readStaticCacheStore();
  if (!(key in store)) return;
  delete store[key];
  writeStaticCacheStore(store);
}

function pruneStaticCacheStore(store) {
  const entries = Object.entries(store || {})
    .sort((left, right) => Number(right[1]?.updatedAt || 0) - Number(left[1]?.updatedAt || 0));
  return Object.fromEntries(entries.slice(0, STATIC_CACHE_MODEL_LIMIT));
}

function staticCacheEntryMatchesSnapshot(entry, snapshot, requiredKeys) {
  if (!entry?.fields) return false;
  return requiredKeys.every((key) => (
    entry.fields[key]
    && staticMetaMatches(entry.fields[key].meta, snapshot.static_meta?.[key])
  ));
}

function restoreStaticSnapshotCache(snapshot, page = currentPageName()) {
  if (!snapshot?.static_meta) return snapshot;
  const cacheKey = staticCacheModelKey(snapshot);
  if (!cacheKey) return snapshot;
  const requiredKeys = staticSnapshotKeysForPage(page).filter((key) => CACHEABLE_STATIC_KEYS.includes(key));
  if (!requiredKeys.length) return snapshot;
  const entry = readStaticCacheStore()[cacheKey];
  if (!entry?.fields) return snapshot;
  let restored = snapshot;
  requiredKeys.forEach((key) => {
    if (restored[key] !== undefined) return;
    const cached = entry.fields[key];
    if (!cached || !staticMetaMatches(cached.meta, restored.static_meta?.[key])) return;
    if (restored === snapshot) restored = { ...snapshot };
    restored[key] = cached.value;
  });
  return restored;
}

function persistStaticSnapshotCache(snapshot, page = currentPageName()) {
  if (!snapshot?.static_meta) return;
  const cacheKey = staticCacheModelKey(snapshot);
  if (!cacheKey) return;
  const requiredKeys = staticSnapshotKeysForPage(page).filter((key) => (
    CACHEABLE_STATIC_KEYS.includes(key)
    && snapshot[key] !== undefined
    && snapshot.static_meta?.[key] !== undefined
  ));
  if (!requiredKeys.length) return;
  const store = readStaticCacheStore();
  const entry = store[cacheKey] || { fields: {} };
  if (staticCacheEntryMatchesSnapshot(entry, snapshot, requiredKeys)) return;
  const fields = { ...(entry.fields || {}) };
  let changed = false;
  requiredKeys.forEach((key) => {
    if (fields[key] && staticMetaMatches(fields[key].meta, snapshot.static_meta[key])) return;
    fields[key] = {
      meta: snapshot.static_meta[key],
      value: snapshot[key],
    };
    changed = true;
  });
  if (!changed) return;
  store[cacheKey] = { updatedAt: Date.now(), fields };
  if (writeStaticCacheStore(pruneStaticCacheStore(store))) return;
  requiredKeys.forEach((key) => {
    if (fields[key]?.value?.svg) delete fields[key];
  });
  store[cacheKey] = { updatedAt: Date.now(), fields };
  writeStaticCacheStore(pruneStaticCacheStore(store));
}

function staticSnapshotMissingKeys(snapshot, requiredKeys = STATIC_SNAPSHOT_KEYS) {
  return (requiredKeys || []).filter((key) => snapshot?.[key] === undefined);
}

function traineeMeasurementOnlySnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return snapshot;
  const projected = { ...snapshot };
  if (snapshot.measurements && typeof snapshot.measurements === "object") {
    projected.measurements = {
      ...snapshot.measurements,
      value_channels: ["scada"],
    };
    delete projected.measurements.real;
  }
  if (snapshot.measurement_delta && typeof snapshot.measurement_delta === "object") {
    projected.measurement_delta = {
      ...snapshot.measurement_delta,
      value_channels: ["scada"],
    };
    delete projected.measurement_delta.real_values;
    if (Array.isArray(projected.measurement_delta.items)) {
      projected.measurement_delta.items = projected.measurement_delta.items.map((rawItem) => {
        if (!rawItem || typeof rawItem !== "object") return rawItem;
        const item = { ...rawItem, value: rawItem.scada_value };
        delete item.real_value;
        return item;
      });
    }
  }
  if (snapshot.measurement_history && typeof snapshot.measurement_history === "object") {
    projected.measurement_history = {
      ...snapshot.measurement_history,
      value_channels: ["scada"],
      frames: Array.isArray(snapshot.measurement_history.frames)
        ? snapshot.measurement_history.frames.map((rawFrame) => {
          if (!rawFrame || typeof rawFrame !== "object") return rawFrame;
          const frame = { ...rawFrame };
          delete frame.real_values;
          return frame;
        })
        : snapshot.measurement_history.frames,
    };
    delete projected.measurement_history.real_values;
  }
  return projected;
}

function traineeMeasurementOnlyTraceHistory(history) {
  if (!Array.isArray(history)) return [];
  return history.map((rawPoint) => {
    if (!rawPoint || typeof rawPoint !== "object") return rawPoint;
    const measurements = Object.fromEntries(
      Object.entries(rawPoint.measurements || {}).map(([key, rawMeasurement]) => {
        if (!rawMeasurement || typeof rawMeasurement !== "object") return [key, rawMeasurement];
        const measurement = {
          ...rawMeasurement,
          value: rawMeasurement.scada ?? null,
          scada: rawMeasurement.scada ?? null,
        };
        delete measurement.real;
        delete measurement.real_value;
        return [key, measurement];
      }),
    );
    return { ...rawPoint, measurements };
  });
}

function mergeSnapshot(previous, incoming) {
  const safePrevious = traineeMeasurementOnlySnapshot(previous);
  const safeIncoming = traineeMeasurementOnlySnapshot(incoming);
  if (!safePrevious || !safeIncoming) return safeIncoming;
  const merged = { ...safePrevious, ...safeIncoming };
  const previousModelId = String(safePrevious.model?.id || "");
  const incomingModelId = String(safeIncoming.model?.id || "");
  const modelChanged = Boolean(previousModelId && incomingModelId && previousModelId !== incomingModelId);
  STATIC_SNAPSHOT_KEYS.forEach((key) => {
    if (safeIncoming[key] !== undefined) return;
    const incomingMeta = safeIncoming.static_meta?.[key];
    const previousMeta = safePrevious.static_meta?.[key];
    const revisionChanged = Boolean(
      incomingMeta
      && previousMeta
      && !staticMetaMatches(incomingMeta, previousMeta)
    );
    if (modelChanged || revisionChanged) {
      delete merged[key];
      return;
    }
    if (safePrevious[key] !== undefined) merged[key] = safePrevious[key];
  });
  if (modelChanged && safeIncoming.device_states === undefined) delete merged.device_states;
  if (safeIncoming.runtime_logs === undefined) delete merged.runtime_logs;
  return merged;
}

function pageNeedsRuntimeLogs(page = currentPageName()) {
  return ["overview", "history"].includes(page);
}

function snapshotLogLimit(page = currentPageName()) {
  return page === "history" ? 300 : 20;
}

function pageNeedsMeasurementDelta(page = currentPageName()) {
  return ["overview", "diagram", "commands", "measurements", "renewable"].includes(page);
}

function pageNeedsDevices(page = currentPageName()) {
  return ["overview", "model", "diagram", "commands", "renewable"].includes(page);
}

function pageNeedsDeviceStates(page = currentPageName()) {
  return page === "diagram";
}

function pageNeedsCommands(page = currentPageName()) {
  return ["overview", "diagram", "commands", "renewable"].includes(page);
}

function pageNeedsCommandHistory(page = currentPageName()) {
  return page === "commands";
}

const DEVICE_RUNTIME_ENCODING = "device-runtime-arrays-v1";
const DEVICE_RUNTIME_SUPPLEMENT_ENCODING = "device-runtime-supplement-arrays-v1";

function deviceRuntimeIdentity(row = {}) {
  return [
    String(row.dev_type || "").trim(),
    String(row.dev_name || row.name || "").trim(),
  ];
}

function orderedDeviceRuntimeRows(rows, label) {
  if (!Array.isArray(rows)) throw new Error(`${label} is not an array`);
  const ordered = rows.filter((row) => row && typeof row === "object").slice().sort((left, right) => {
    const leftKey = deviceRuntimeIdentity(left);
    const rightKey = deviceRuntimeIdentity(right);
    if (leftKey[0] < rightKey[0]) return -1;
    if (leftKey[0] > rightKey[0]) return 1;
    if (leftKey[1] < rightKey[1]) return -1;
    if (leftKey[1] > rightKey[1]) return 1;
    return 0;
  });
  const identities = ordered.map((row) => deviceRuntimeIdentity(row));
  if (identities.some(([devType, devName]) => !devType || !devName)) {
    throw new Error(`${label} contains an empty device identity`);
  }
  const unique = new Set(identities.map(([devType, devName]) => `${devType}\u0000${devName}`));
  if (unique.size !== identities.length) throw new Error(`${label} contains duplicate device identities`);
  return ordered;
}

function deviceRuntimeOrderSignature(rows, label) {
  const encoder = new TextEncoder();
  let checksum = 0x811c9dc5;
  orderedDeviceRuntimeRows(rows, label).forEach((row) => {
    const [devType, devName] = deviceRuntimeIdentity(row);
    encoder.encode(`${devType}\u001e${devName}\u001f`).forEach((value) => {
      checksum ^= value;
      checksum = Math.imul(checksum, 0x01000193) >>> 0;
    });
  });
  return `${rows.length}:${checksum.toString(16).padStart(8, "0")}`;
}

function validatedDeviceRuntimeCount(payload, name, expected) {
  if (Number(payload?.[name]) !== expected) {
    throw new Error(`${name} mismatch: expected ${expected}, received ${payload?.[name]}`);
  }
}

function validatedDeviceRuntimeArray(payload, name, expected) {
  const values = payload?.[name];
  if (!Array.isArray(values) || values.length !== expected) {
    throw new Error(`${name} length mismatch: expected ${expected}, received ${Array.isArray(values) ? values.length : -1}`);
  }
  return values;
}

function validatedDeviceRuntimeSparseValues(payload, prefix, count) {
  const indices = payload?.[`${prefix}_indices`];
  const values = payload?.[`${prefix}_values`];
  if (!Array.isArray(indices) || !Array.isArray(values) || indices.length !== values.length) {
    throw new Error(`${prefix} sparse length mismatch`);
  }
  let previous = -1;
  return indices.map((rawIndex, position) => {
    const index = Number(rawIndex);
    if (!Number.isInteger(index) || index < 0 || index >= count || index <= previous) {
      throw new Error(`${prefix} indices must be unique, ordered, and in range`);
    }
    previous = index;
    return [index, values[position]];
  });
}

function validatedOptionalDeviceRuntimeSparseValues(payload, prefix, count) {
  const hasIndices = Object.prototype.hasOwnProperty.call(payload || {}, `${prefix}_indices`);
  const hasValues = Object.prototype.hasOwnProperty.call(payload || {}, `${prefix}_values`);
  if (!hasIndices && !hasValues) return [];
  return validatedDeviceRuntimeSparseValues(payload, prefix, count);
}

function measurementBackedRuntimeKey(row = {}, measurementType = null) {
  const [devType, devName] = deviceRuntimeIdentity(row);
  return `${devType}\u0000${devName}\u0000${String(measurementType ?? row.meas_type ?? "").trim().toUpperCase()}`;
}

function hydrateMeasurementBackedDeviceRuntime(snapshot = state.snapshot || {}) {
  const measurements = snapshot?.measurements || {};
  const definitions = Array.isArray(measurements.definitions)
    ? measurements.definitions
    : (snapshot?.definitions?.measurement || []);
  const definitionKeys = new Set(definitions.map((row) => measurementBackedRuntimeKey(row)));
  const scadaByKey = new Map(
    (measurements.scada || []).map((row) => [measurementBackedRuntimeKey(row), row]),
  );
  const hydrate = (row, measurementType, fieldName) => {
    const key = measurementBackedRuntimeKey(row, measurementType);
    if (!definitionKeys.has(key)) return;
    const measurement = scadaByKey.get(key);
    const valid = Number(measurement?.valid ?? 0) === 1 && measurement?.value !== null && measurement?.value !== undefined;
    if (valid) row[fieldName] = measurement.value;
    else if (["RUN_STAT", "STATUS"].includes(measurementType)) row[fieldName] = 0;
    else delete row[fieldName];
    if (measurementType === "STATUS" && row[fieldName] !== undefined) {
      row.closed_status = row[fieldName];
    }
  };
  (snapshot.devices || []).forEach((row) => {
    hydrate(row, "RUN_STAT", "run_stat");
    hydrate(row, "STATUS", "status");
    hydrate(row, "SOC", "soc_curr");
  });
  (snapshot.device_states || []).forEach((row) => hydrate(row, "RUN_STAT", "run_stat"));
  return snapshot;
}

function rejectDeviceRuntimeFrame(incoming, message) {
  state.deviceRuntimeSignature = "";
  state.deviceRuntimeNeedsFullRefresh = true;
  state.deviceRuntimeWarning = message;
  console.warn(`设备运行帧已拒绝，下一周期重取完整设备数据：${message}`);
  const rejected = { ...(incoming || {}) };
  delete rejected.device_runtime;
  delete rejected.device_runtime_signature;
  return rejected;
}

function applyDeviceRuntimePayload(previous, incoming) {
  if (!incoming || typeof incoming !== "object") return incoming;
  const advertisedSignature = String(incoming.device_runtime_signature || "").trim();
  const frame = incoming.device_runtime;
  if (!advertisedSignature) {
    if (incoming.devices !== undefined || incoming.device_states !== undefined) {
      state.deviceRuntimeSignature = "";
      state.deviceRuntimeNeedsFullRefresh = false;
      state.deviceRuntimeWarning = "";
    }
    return incoming;
  }
  if (!frame || typeof frame !== "object") {
    if (state.deviceRuntimeSignature && advertisedSignature === state.deviceRuntimeSignature) return incoming;
    return rejectDeviceRuntimeFrame(incoming, "设备运行签名变化但未携带运行帧");
  }
  try {
    const encoding = String(frame.encoding || "");
    if (![DEVICE_RUNTIME_ENCODING, DEVICE_RUNTIME_SUPPLEMENT_ENCODING].includes(encoding)) {
      throw new Error(`unsupported encoding ${frame.encoding || "--"}`);
    }
    if (String(frame.runtime_signature || "") !== advertisedSignature) {
      throw new Error("advertised runtime signature mismatch");
    }
    const baseDevices = Array.isArray(incoming.devices) ? incoming.devices : previous?.devices;
    if (!Array.isArray(baseDevices)) throw new Error("missing base device definitions");
    const deviceCount = baseDevices.length;
    const stateCount = Number(frame.state_count);
    validatedDeviceRuntimeCount(frame, "device_count", deviceCount);
    if (!Number.isInteger(stateCount) || stateCount < 0) throw new Error("invalid state_count");
    if (String(frame.device_signature || "") !== deviceRuntimeOrderSignature(baseDevices, "devices")) {
      throw new Error("device signature mismatch");
    }
    const modes = validatedDeviceRuntimeArray(frame, "device_modes", deviceCount);
    const setValues = validatedDeviceRuntimeArray(frame, "device_set_values", deviceCount);
    const stateDeadIslands = validatedDeviceRuntimeArray(frame, "state_dead_islands", stateCount);
    const completeFrame = encoding === DEVICE_RUNTIME_ENCODING;
    const runStats = completeFrame ? validatedDeviceRuntimeArray(frame, "device_run_stats", deviceCount) : [];
    const statuses = completeFrame ? validatedDeviceRuntimeArray(frame, "device_statuses", deviceCount) : [];
    const socPresent = completeFrame ? validatedDeviceRuntimeArray(frame, "device_soc_present", deviceCount) : [];
    const socValues = completeFrame ? validatedDeviceRuntimeArray(frame, "device_soc_values", deviceCount) : [];
    const stateRunStats = completeFrame ? validatedDeviceRuntimeArray(frame, "state_run_stats", stateCount) : [];
    const runSparse = completeFrame ? [] : validatedDeviceRuntimeSparseValues(frame, "device_run_stat", deviceCount);
    const statusSparse = completeFrame ? [] : validatedDeviceRuntimeSparseValues(frame, "device_status", deviceCount);
    const closedStatusSetSparse = validatedOptionalDeviceRuntimeSparseValues(frame, "device_closed_status_set", deviceCount);
    const socSparse = completeFrame ? [] : validatedDeviceRuntimeSparseValues(frame, "device_soc", deviceCount);
    const stateRunSparse = completeFrame ? [] : validatedDeviceRuntimeSparseValues(frame, "state_run_stat", stateCount);

    const decodedDevices = baseDevices.map((row) => ({ ...row, set_values: { ...(row?.set_values || {}) } }));
    orderedDeviceRuntimeRows(decodedDevices, "devices").forEach((row, index) => {
      if (completeFrame) {
        row.run_stat = runStats[index];
        row.status = statuses[index];
        row.closed_status = statuses[index];
      }
      row.mode = modes[index];
      row.set_values = setValues[index] && typeof setValues[index] === "object"
        ? { ...setValues[index] }
        : {};
      if (completeFrame && socPresent[index]) row.soc_curr = socValues[index];
    });
    const orderedDevices = orderedDeviceRuntimeRows(decodedDevices, "devices");
    runSparse.forEach(([index, value]) => { orderedDevices[index].run_stat = value; });
    statusSparse.forEach(([index, value]) => {
      orderedDevices[index].status = value;
      orderedDevices[index].closed_status = value;
    });
    closedStatusSetSparse.forEach(([index, value]) => { orderedDevices[index].closed_status_set = value; });
    socSparse.forEach(([index, value]) => { orderedDevices[index].soc_curr = value; });

    const baseStates = Array.isArray(incoming.device_states) ? incoming.device_states : previous?.device_states;
    let decodedStates = null;
    if (Array.isArray(baseStates)) {
      validatedDeviceRuntimeCount(frame, "state_count", baseStates.length);
      if (String(frame.state_signature || "") !== deviceRuntimeOrderSignature(baseStates, "device_states")) {
        throw new Error("device state signature mismatch");
      }
      decodedStates = baseStates.map((row) => ({ ...row }));
      orderedDeviceRuntimeRows(decodedStates, "device_states").forEach((row, index) => {
        if (completeFrame) row.run_stat = stateRunStats[index];
        row.dead_island = Boolean(stateDeadIslands[index]);
      });
      const orderedStates = orderedDeviceRuntimeRows(decodedStates, "device_states");
      stateRunSparse.forEach(([index, value]) => { orderedStates[index].run_stat = value; });
    }

    const applied = { ...incoming, devices: decodedDevices };
    if (decodedStates) applied.device_states = decodedStates;
    delete applied.device_runtime;
    state.deviceRuntimeSignature = advertisedSignature;
    state.deviceRuntimeNeedsFullRefresh = false;
    state.deviceRuntimeWarning = "";
    hydrateMeasurementBackedDeviceRuntime({ ...(previous || {}), ...applied });
    return applied;
  } catch (error) {
    return rejectDeviceRuntimeFrame(incoming, error?.message || String(error));
  }
}

function canUseCompactDeviceRuntime(page = currentPageName()) {
  if (!pageNeedsDevices(page) || state.deviceRuntimeNeedsFullRefresh) return false;
  if (!Array.isArray(state.snapshot?.devices) || !state.snapshot.devices.length) return false;
  return !pageNeedsDeviceStates(page) || Array.isArray(state.snapshot?.device_states);
}

function snapshotPollPath(page = currentPageName(), forceStaticKeys = null) {
  if (!Array.isArray(forceStaticKeys) && state.snapshot?.static_meta) {
    state.snapshot = restoreStaticSnapshotCache(state.snapshot, page);
  }
  const currentModelId = String(state.snapshot?.model?.id || "");
  const modelChanged = currentModelId && state.activeModelId && currentModelId !== state.activeModelId;
  const requiredStaticKeys = Array.isArray(forceStaticKeys)
    ? forceStaticKeys
    : (
      state.snapshot?.static_meta && !modelChanged
        ? staticSnapshotMissingKeys(state.snapshot, staticSnapshotKeysForPage(page))
        : staticSnapshotKeysForPage(page)
    );
  const params = new URLSearchParams();
  const compactDeviceRuntime = !Array.isArray(forceStaticKeys) && canUseCompactDeviceRuntime(page);
  params.set("measurements", "0");
  params.set("devices", pageNeedsDevices(page) ? "1" : "0");
  params.set("device_states", pageNeedsDeviceStates(page) ? "1" : "0");
  if (compactDeviceRuntime) {
    params.set("devices", "0");
    params.set("device_states", "0");
    params.set("device_runtime_compact", "1");
    if (state.deviceRuntimeSignature) {
      params.set("after_device_runtime_signature", state.deviceRuntimeSignature);
    }
    if (pageNeedsMeasurementDelta(page)) params.set("device_runtime_supplement", "1");
  }
  params.set("commands", pageNeedsCommands(page) ? "1" : "0");
  if (pageNeedsCommands(page) && state.snapshot?.command_signature) {
    params.set("after_command_signature", state.snapshot.command_signature);
  }
  params.set("command_history", pageNeedsCommandHistory(page) ? "1" : "0");
  if (pageNeedsMeasurementDelta(page)) {
    params.set("measurement_after_seq", String(state.measurementDeltaSeq || 0));
    params.set("measurement_compact", "1");
  }
  if (pageNeedsRuntimeLogs(page)) params.set("log_limit", String(snapshotLogLimit(page)));
  else params.set("logs", "0");
  if (requiredStaticKeys.length) params.set("static", requiredStaticKeys.join(","));
  else params.set("lite", "1");
  return `/api/snapshot?${params.toString()}`;
}

function appendUrlQuery(url, params) {
  try {
    const isAbsoluteUrl = /^https?:\/\//i.test(String(url || ""));
    const target = new URL(url, location.href);
    Object.entries(params || {}).forEach(([key, value]) => target.searchParams.set(key, String(value)));
    return isAbsoluteUrl ? target.href : `${target.pathname}${target.search}${target.hash}`;
  } catch (_error) {
    const separator = String(url || "").includes("?") ? "&" : "?";
    const query = new URLSearchParams(params || {}).toString();
    return `${url}${separator}${query}`;
  }
}

function teacherSnapshotPath() {
  if (state.teacherSnapshotPath) return state.teacherSnapshotPath;
  return "/api/snapshot";
}

function teacherReceiveAddress() {
  const configuredAddress = state.teacherApiBase || state.interactionLink;
  if (configuredAddress) {
    try {
      return normalizeConnectionUrl(configuredAddress);
    } catch (_error) {
      return configuredAddress;
    }
  }
  const base = state.teacherApiBase || "";
  const path = teacherSnapshotPath();
  if (!base) return path;
  return connectionApiUrl({ teacherApiBase: base }, path);
}

function teacherSnapshotPollAddress(page = currentPageName(), forceStaticKeys = null) {
  void forceStaticKeys;
  const params = new URLSearchParams();
  const compactDeviceRuntime = canUseCompactDeviceRuntime(page);
  params.set("measurements", "0");
  params.set("devices", pageNeedsDevices(page) ? "1" : "0");
  params.set("device_states", pageNeedsDeviceStates(page) ? "1" : "0");
  if (compactDeviceRuntime) {
    params.set("devices", "1");
    params.set("device_states", "1");
    params.set("device_runtime_compact", "1");
    if (state.deviceRuntimeSignature) {
      params.set("after_device_runtime_signature", state.deviceRuntimeSignature);
    }
    if (pageNeedsMeasurementDelta(page)) params.set("device_runtime_supplement", "1");
  }
  params.set("commands", pageNeedsCommands(page) ? "1" : "0");
  if (pageNeedsCommands(page) && state.snapshot?.command_signature) {
    params.set("after_command_signature", state.snapshot.command_signature);
  }
  params.set("command_history", "0");
  if (pageNeedsMeasurementDelta(page)) {
    params.set("measurement_after_seq", String(state.measurementDeltaSeq || 0));
    params.set("measurement_compact", "1");
  }
  params.set("logs", "0");
  params.set("static", "0");
  params.set("static_meta", "0");
  params.set("lite", "1");
  return `/api/trainee/snapshot?${params.toString()}`;
}

function traineeUiFramePath(page = currentPageName()) {
  const snapshotUrl = new URL(teacherSnapshotPollAddress(page), location.href);
  const params = new URLSearchParams(snapshotUrl.search);
  params.set("view", page);
  params.set("compact", "1");
  if (state.receiveStateRevision) {
    params.set("after_receive_state_revision", state.receiveStateRevision);
  }
  if (page === "renewable") {
    const renewableUrl = new URL(renewableControlApiPath(false), location.href);
    renewableUrl.searchParams.forEach((value, key) => params.set(key, value));
  }
  return `/api/trainee/ui-frame?${params.toString()}`;
}

function applyTraineeUiFrame(payload = {}) {
  if (!payload || payload.encoding !== "trainee-ui-frame-v1") {
    throw new Error("学员台周期帧编码无效");
  }
  const previousReceiveMode = state.receiveMode;
  const previousLink = state.interactionLink;
  const previousInitialized = state.modelInitialized;
  const previousInitializedAt = state.modelInitializedAt;
  if (payload.receive_state && typeof payload.receive_state === "object") {
    mergeBackendReceiveState(state.activeModelId, payload.receive_state, true);
    state.lastReceiveStateSyncAtMs = Date.now();
  }
  const receiveStateRevision = String(payload.receive_state_revision || "");
  if (receiveStateRevision && receiveStateRevision !== state.receiveStateRevision) {
    state.receiveStateRevision = receiveStateRevision;
    const key = contextKey();
    state.modelContexts[key] = {
      ...activeModelContext(),
      receiveStateRevision,
    };
  }
  if (
    state.modelInitialized !== previousInitialized
    || state.modelInitializedAt !== previousInitializedAt
  ) {
    state.localDefinitionSnapshot = null;
    state.localDefinitionModelId = "";
    state.snapshot = null;
    state.measurementDeltaSeq = 0;
    invalidateManualDefinitionChanges();
    clearStaticSnapshotCacheForModel(state.activeModelId);
  }
  if (state.receiveMode !== previousReceiveMode || state.interactionLink !== previousLink) {
    state.receiveEpoch += 1;
    state.receiveRequestActive = false;
    if (state.receiveMode) {
      state.frozen = false;
      state.lastReceiveAt = "";
      state.snapshotSource = "";
    }
  }
  if (payload.renewable_control && typeof payload.renewable_control === "object") {
    applyRenewableControlState(payload.renewable_control);
  }
  return payload.snapshot && typeof payload.snapshot === "object" ? payload.snapshot : null;
}

function measurementDeltaPathFromSnapshotPath(snapshotPath = "") {
  try {
    const url = new URL(snapshotPath || "/api/snapshot", location.href);
    const query = url.search || "";
    return `/api/measurements/delta${query}`;
  } catch (_error) {
    return "/api/measurements/delta";
  }
}

function teacherMeasurementDeltaAddress() {
  return appendUrlQuery("/api/trainee/measurements/delta", {
    after_seq: state.measurementDeltaSeq,
    compact: 1,
  });
}

function displayReceiveAddress(address) {
  try {
    return decodeURI(String(address || ""));
  } catch (_error) {
    return String(address || "");
  }
}

async function teacherSnapshotApi(page = currentPageName(), forceStaticKeys = null) {
  return api(teacherSnapshotPollAddress(page, forceStaticKeys));
}

function measurementNameKey(item) {
  return String(item?.name || "");
}

function measurementChannelIndex(rows = []) {
  return new Map((rows || []).map((row) => [measurementNameKey(row), row]));
}

function ensureMeasurementChannelRow(measurements, definitionsByName, channel, item, channelIndex) {
  if (item.deleted) {
    channelIndex.delete(item.name);
    return null;
  }
  let row = channelIndex.get(item.name);
  if (!row) {
    const definition = definitionsByName.get(item.name);
    if (!definition) return null;
    row = { ...definition };
    channelIndex.set(item.name, row);
  }
  return row;
}

function compactMeasurementDeltaItems(payload) {
  if (payload && payload.encoding === "measurement-rows-v1") {
    const simuTime = payload.simu_time ?? payload.time ?? "--";
    const wallTime = payload.wall_time ?? "--";
    return (payload.rows || []).map((row) => {
      const flags = Number(row?.[5]) || 0;
      return {
        name: String(row?.[0] || ""),
        scada_value: flags & 4 ? row?.[2] : null,
        valid: row?.[3],
        weight: row?.[4],
        deleted: Boolean(flags & 1),
        updated_simu_time: simuTime,
        updated_wall_time: wallTime,
        updated_absolute_minute: payload.absolute_minute,
      };
    });
  }
  return payload?.items || [];
}

function measurementDefinitionSignature(definitions = [], definitionRevision = "") {
  const rows = Array.isArray(definitions) ? definitions : [];
  const revisionKey = String(definitionRevision ?? "");
  const cache = measurementDefinitionSignature.cache
    || (measurementDefinitionSignature.cache = new WeakMap());
  const cached = cache.get(rows);
  if (
    revisionKey
    && cached?.revisionKey === revisionKey
    && cached?.length === rows.length
  ) {
    return cached.signature;
  }
  const encoder = new TextEncoder();
  let checksum = 0x811c9dc5;
  rows.forEach((definition) => {
    const token = ["name", "dev_type", "dev_name", "meas_type"]
      .map((fieldName) => String(definition?.[fieldName] ?? ""))
      .join("\x1e") + "\x1f";
    encoder.encode(token).forEach((value) => {
      checksum ^= value;
      checksum = Math.imul(checksum, 0x01000193) >>> 0;
    });
  });
  const signature = `${rows.length}:${checksum.toString(16).padStart(8, "0")}`;
  cache.set(rows, { revisionKey, length: rows.length, signature });
  return signature;
}

function reportMeasurementArrayWarning(message) {
  const changed = state.measurementArrayWarning !== message;
  state.measurementArrayWarning = message;
  console.warn(message);
  const summary = $("measurementCompareSummary") || $("measurementSummary");
  if (summary) summary.textContent = message;
  if (changed && typeof addRuntimeLog === "function") {
    addRuntimeLog("实时量测", "量测数组帧", "整帧拒绝", message, "warn");
  }
}

function applyMeasurementArrayFrame(payload, measurements, definitions) {
  const count = Number(payload.count);
  const frame = payload.frame !== false;
  const expectedValueCount = frame ? count : 0;
  const statusValues = payload.status_values;
  const fixedValues = payload.fixed_values;
  if (
    !Number.isInteger(count)
    || count < 0
    || definitions.length !== count
    || !Array.isArray(payload.scada_values)
    || payload.scada_values.length !== expectedValueCount
    || !Array.isArray(payload.valid_values)
    || payload.valid_values.length !== expectedValueCount
    || (
      statusValues !== undefined
      && statusValues !== null
      && (
        !Array.isArray(statusValues)
        || statusValues.length !== expectedValueCount
      )
    )
    || (
      fixedValues !== undefined
      && fixedValues !== null
      && (
        !Array.isArray(fixedValues)
        || fixedValues.length !== expectedValueCount
      )
    )
  ) {
    reportMeasurementArrayWarning(
      `实时量测数组长度不一致，整帧已拒绝：定义=${definitions.length}，声明=${payload.count}，`
      + `量测=${payload.scada_values?.length ?? "非数组"}，`
      + `状态=${payload.valid_values?.length ?? "非数组"}`,
    );
    return false;
  }
  const expectedSignature = measurementDefinitionSignature(
    definitions,
    payload.definition_revision ?? measurements.definition_revision ?? "",
  );
  const receivedSignature = String(payload.definition_signature || "");
  if (!receivedSignature) {
    reportMeasurementArrayWarning("实时量测定义顺序签名缺失，整帧已拒绝");
    return false;
  }
  if (receivedSignature !== expectedSignature) {
    reportMeasurementArrayWarning(
      `实时量测定义顺序不一致，整帧已拒绝：接收=${receivedSignature}，本地=${expectedSignature}`,
    );
    return false;
  }
  if (!frame) {
    state.measurementArrayWarning = "";
    return false;
  }

  const simuTime = payload.simu_time ?? payload.time ?? "--";
  const wallTime = payload.wall_time ?? "--";
  const absoluteMinute = payload.absolute_minute;
  const currentScada = Array.isArray(measurements.scada) ? measurements.scada : [];
  const scadaRows = definitions.map((definition, index) => {
    const row = currentScada[index] || {};
    Object.assign(row, definition);
    row.value = payload.scada_values[index];
    row.valid = payload.valid_values[index] ?? definition.valid ?? row.valid;
    row.weight = definition.weight ?? row.weight;
    row.status = statusValues?.[index] ?? definition.status ?? row.status;
    row.fixed_value = fixedValues?.[index] ?? definition.fixed_value ?? row.fixed_value;
    row.updated_simu_time = simuTime;
    row.updated_wall_time = wallTime;
    row.updated_absolute_minute = absoluteMinute;
    return row;
  });
  measurements.definitions = definitions;
  delete measurements.real;
  measurements.value_channels = ["scada"];
  measurements.scada = scadaRows;
  measurements.definition_signature = expectedSignature;
  measurements.definition_revision = payload.definition_revision;
  state.measurementDeltaSeq = Math.max(Number(state.measurementDeltaSeq) || 0, Number(payload.seq) || 0);
  state.measurementArrayWarning = "";
  return true;
}

function appendMeasurementTraceAfterDelta(changed) {
  if (
    changed
    && state.snapshot
    && typeof appendMeasurementTrace === "function"
  ) {
    appendMeasurementTrace(state.snapshot);
  }
  return changed;
}

function applyMeasurementDelta(payload) {
  if (!payload || !state.snapshot) return false;
  if (payload.measurement_clock && typeof payload.measurement_clock === "object") {
    state.snapshot.measurement_clock = { ...payload.measurement_clock };
  }
  const measurements = state.snapshot.measurements || {};
  state.snapshot.measurements = measurements;
  const definitions = measurements.definitions || state.snapshot.definitions?.measurement || [];
  if (payload.encoding === "measurement-arrays-v1") {
    return appendMeasurementTraceAfterDelta(
      applyMeasurementArrayFrame(payload, measurements, definitions),
    );
  }
  if (payload.reset) {
    measurements.scada = [];
    delete measurements.real;
  }
  const definitionsByName = new Map(definitions.map((row) => [measurementNameKey(row), row]));
  const channelIndexes = { scada: measurementChannelIndex(measurements.scada || []) };
  let changed = false;
  compactMeasurementDeltaItems(payload).forEach((item) => {
    if (!item?.name) return;
    const definition = definitionsByName.get(item.name);
    if (item.deleted) {
      ensureMeasurementChannelRow(measurements, definitionsByName, "scada", item, channelIndexes.scada);
      changed = true;
      return;
    }
    const scadaRow = item.scada_value !== undefined && item.scada_value !== null
      ? ensureMeasurementChannelRow(measurements, definitionsByName, "scada", item, channelIndexes.scada)
      : null;
    if (scadaRow) {
      scadaRow.value = item.scada_value;
      scadaRow.valid = definition?.valid ?? item.valid ?? scadaRow.valid;
      scadaRow.weight = definition?.weight ?? item.weight ?? scadaRow.weight;
      scadaRow.updated_simu_time = item.updated_simu_time;
      scadaRow.updated_wall_time = item.updated_wall_time;
      scadaRow.updated_absolute_minute = item.updated_absolute_minute;
      changed = true;
    }
  });
  measurements.scada = Array.from(channelIndexes.scada.values());
  measurements.value_channels = ["scada"];
  if (payload.reset) state.measurementDeltaSeq = Number(payload.seq) || 0;
  else state.measurementDeltaSeq = Math.max(Number(state.measurementDeltaSeq) || 0, Number(payload.seq) || 0);
  return appendMeasurementTraceAfterDelta(changed);
}

function applyEmbeddedMeasurementDelta(snapshot) {
  const payload = snapshot?.measurement_delta;
  state.embeddedMeasurementDeltaReceived = Boolean(payload);
  if (!payload) return false;
  delete snapshot.measurement_delta;
  state.snapshot = snapshot;
  const changed = applyMeasurementDelta(payload);
  if (changed) hydrateMeasurementBackedDeviceRuntime(state.snapshot);
  return changed;
}

async function refreshMeasurementDelta(renderNow = false) {
  if (state.measurementDeltaRequestActive || !state.snapshot) return false;
  state.measurementDeltaRequestActive = true;
  try {
    const payload = state.receiveMode
      ? await api(teacherMeasurementDeltaAddress())
      : await api(`/api/measurements/delta?after_seq=${state.measurementDeltaSeq}&compact=1`);
    const changed = applyMeasurementDelta(payload);
    if (changed) hydrateMeasurementBackedDeviceRuntime(state.snapshot);
    if (changed && renderNow && currentPageName() === "measurements") renderMeasurements(state.snapshot || {});
    return changed;
  } finally {
    state.measurementDeltaRequestActive = false;
  }
}

function teacherCommandPath() {
  if (state.teacherCommandPath) return state.teacherCommandPath;
  return state.activeModelId
    ? `/api/student/commands?model_id=${encodeURIComponent(state.activeModelId)}`
    : "/api/student/commands";
}

function teacherCommandTargetName() {
  return `模拟台 ${teacherCommandPath()}`;
}

async function teacherCommandApi(options = {}) {
  return api("/api/trainee/commands", options);
}

function hasTeacherCommandConnection() {
  return Boolean(state.modelInitialized && state.interactionLink && state.teacherCommandPath && state.teacherApiBase);
}

async function postTeacherCommand(body) {
  if (!hasTeacherCommandConnection()) {
    throw new Error("请先完成顶部“模型初始化”并启动接收后再下发指令。");
  }
  return await teacherCommandApi({ method: "POST", body: JSON.stringify(body) });
}

function commandCycleMinutes(snapshot = state.snapshot || {}) {
  const curves = snapshot.curves || {};
  const pointCount = Number(curves.point_count);
  const stepMinutes = Number(curves.time_step_minutes || CURVE_DISPLAY_MODES[curveDisplayMode(snapshot)].stepMinutes);
  const curvePeriod = pointCount * stepMinutes;
  if (Number.isFinite(curvePeriod) && curvePeriod > 0) return curvePeriod;
  return CURVE_DISPLAY_MODES[curveDisplayMode(snapshot)]?.durationMinutes || CURVE_DISPLAY_MODES.day.durationMinutes;
}

function manualCommandExpiresAtAbsoluteMinute(snapshot = state.snapshot || {}) {
  const clock = snapshot.clock || {};
  const current = Number(clock.absolute_minute ?? clock.minute ?? 0) || 0;
  const cycleMinutes = commandCycleMinutes(snapshot);
  const cycleEnd = (Math.floor(current / cycleMinutes) + 1) * cycleMinutes;
  const stepMinutes = Number(clock.step_minutes || 1) || 1;
  const speed = Number(clock.speed || 1) || 1;
  return Math.max(cycleEnd, current + Math.max(1, stepMinutes * speed));
}

function manualCommandHoldPayload() {
  return {
    manual_hold: true,
    hold_until_cancelled: true,
    priority: "manual",
  };
}

