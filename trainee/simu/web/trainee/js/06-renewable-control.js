// 学员端模块：新能源实时控制、策略预设、降额配置与决策日志（06-renewable-control.js）
function estimateLoadFromDevices(devices) {
  return (devices || []).reduce((total, dev) => {
    const isLoad = deviceFamily(dev) === "load"
      || ["ACLoad", "DCLoad"].includes(deviceModelBlock(dev));
    if (!isLoad || !isDeviceOnline(dev)) return total;
    const raw = dev.raw || {};
    const values = dev.set_values || {};
    return total + toNumber(values.p_set ?? raw.pv0 ?? raw.p_set ?? 0, 0);
  }, 0);
}

function isDeviceOnline(dev) {
  if (!dev) return false;
  return Number(dev.run_stat ?? 1) === 1 && Number(dev.status ?? 1) !== 0;
}

function parameterRows(snapshot, blockName) {
  const params = snapshot.device_parameters || {};
  const rows = params[blockName] || params[blockName.toLowerCase()] || params[blockName.toUpperCase()] || [];
  return Array.isArray(rows) ? rows : [];
}

function parameterName(row) {
  return String(row?.name || row?.dev_name || "");
}

function parameterNumber(value, defaultValue = null) {
  if (value === null || value === undefined || String(value).trim() === "") return defaultValue;
  const direct = Number(value);
  if (Number.isFinite(direct)) return direct;
  const match = String(value).replace(/,/g, "").match(/[-+]?\d*\.?\d+(?:e[-+]?\d+)?/i);
  if (!match) return defaultValue;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : defaultValue;
}

function liveStorageSocRatio(value, defaultValue) {
  const number = parameterNumber(value, null);
  if (number === null) return defaultValue;
  return typeof value === "string" && value.includes("%") ? number / 100 : number;
}

function indexedDevice(snapshot, devType, index) {
  const target = String(index ?? "").trim();
  if (!target) return null;
  return (snapshot.devices || []).find((dev) => (
    deviceModelBlock(dev) === devType && String(deviceIndex(dev)).trim() === target
  )) || null;
}

function measurementValuesByDevice(snapshot, measurementTypes) {
  const values = new Map();
  const measurements = snapshot.measurements || {};
  (measurementTypes || []).map((type) => String(type || "").toUpperCase()).forEach((measurementType) => {
    (measurements.scada || []).forEach((row) => {
      if (String(row.meas_type || "").toUpperCase() !== measurementType || Number(row.valid ?? 1) !== 1) return;
      const value = optionalNumber(row.value);
      if (!Number.isFinite(value)) return;
      const key = `${row.dev_type || ""}|${row.dev_name || ""}`;
      if (!values.has(key)) values.set(key, value);
    });
  });
  return values;
}

function storageSocRatiosByDevice(snapshot) {
  const measured = measurementValuesByDevice(snapshot, ["SOC"]);
  const ratios = new Map();
  let linkedStorageCount = 0;
  parameterRows(snapshot, "ACStorageGen").forEach((param, index) => {
    linkedStorageCount += 1;
    const dev = indexedDevice(snapshot, "ACGenerator", param.idx_acgenerator);
    const name = deviceName(dev) || `ACGenerator_${param.idx_acgenerator ?? index + 1}`;
    const key = `ACGenerator|${name}`;
    const soc = liveStorageSocRatio(
      measured.get(key) ?? dev?.soc_curr ?? dev?.raw?.soc_curr,
      null,
    );
    if (Number.isFinite(soc)) ratios.set(key, soc);
  });
  parameterRows(snapshot, "DCStorageGen").forEach((param, index) => {
    linkedStorageCount += 1;
    const dev = indexedDevice(snapshot, "DCGenerator", param.idx_dcgenerator);
    const name = deviceName(dev) || `DCGenerator_${param.idx_dcgenerator ?? index + 1}`;
    const key = `DCGenerator|${name}`;
    const soc = liveStorageSocRatio(
      measured.get(key) ?? dev?.soc_curr ?? dev?.raw?.soc_curr,
      null,
    );
    if (Number.isFinite(soc)) ratios.set(key, soc);
  });
  if (linkedStorageCount) {
    return ratios;
  }
  return ratios;
}

function averageStorageSocRatio(snapshot) {
  const values = [...storageSocRatiosByDevice(snapshot).values()]
    .filter((value) => Number.isFinite(value));
  return values.length
    ? values.reduce((sum, value) => sum + value, 0) / values.length
    : null;
}
function renewableClockKey(snapshot) {
  const clock = snapshot.clock || {};
  return `${clock.absolute_minute ?? clock.minute ?? ""}|${clock.time || ""}`;
}

function renewableControlApiPath(preview = false) {
  const params = new URLSearchParams();
  if (preview) params.set("refresh", "1");
  params.set("compact", "1");
  params.set("trend", "0");
  params.set("performance", "0");
  const latestLogSeq = (state.renewableControl.logs || []).reduce(
    (latest, item) => Math.max(latest, Number(item?.seq) || 0),
    0,
  );
  if (latestLogSeq > 0) params.set("after_log_seq", String(latestLogSeq));
  const planRevision = Number(state.renewableControl.planRevision);
  const settingsRevision = Number(state.renewableControl.settingsRevision);
  const controllerInstanceId = String(state.renewableControl.controllerInstanceId || "");
  if (Number.isFinite(planRevision) && planRevision >= 0 && controllerInstanceId) {
    params.set("after_plan_revision", String(planRevision));
    params.set("after_controller_instance_id", controllerInstanceId);
  }
  if (Number.isFinite(settingsRevision) && settingsRevision >= 0 && controllerInstanceId) {
    params.set("after_settings_revision", String(settingsRevision));
  }
  return `/api/trainee/renewable-control?${params.toString()}`;
}

function renewableTrendHistoryApiPath(fields = [], cursor = "") {
  const path = "/api/trainee/renewable-control/trend";
  const params = new URLSearchParams();
  const requestedFields = Array.from(new Set(
    (Array.isArray(fields) ? fields : [])
      .map((field) => String(field || "").trim())
      .filter(Boolean),
  ));
  params.set("fields", requestedFields.join(","));
  params.set("trend_encoding", "arrays-v1");
  if (cursor) params.set("after_trend_sample_key", cursor);
  const controllerInstanceId = String(state.renewableControl.controllerInstanceId || "");
  if (controllerInstanceId) {
    params.set("after_controller_instance_id", controllerInstanceId);
  }
  return `${path}?${params.toString()}`;
}

function storageDeratingRatio(value) {
  const number = toNumber(value, Number.NaN);
  if (!Number.isFinite(number)) return null;
  return clamp(number > 1 ? number / 100 : number, 0, 1);
}

function normalizeStorageDeratingCurve(points, fallback, direction) {
  const source = Array.isArray(points) && points.length >= 2 ? points : fallback;
  const parsed = source
    .map((point) => ({
      soc: storageDeratingRatio(point?.soc ?? point?.socRatio),
      powerRatio: storageDeratingRatio(point?.powerRatio ?? point?.power_ratio ?? point?.ratio),
    }))
    .filter((point) => Number.isFinite(point.soc) && Number.isFinite(point.powerRatio))
    .sort((left, right) => left.soc - right.soc);
  if (parsed.length < 2) return fallback.map((point) => ({ ...point }));
  const unique = [];
  parsed.forEach((point) => {
    const previous = unique[unique.length - 1];
    if (previous && Math.abs(previous.soc - point.soc) < 1e-9) previous.powerRatio = point.powerRatio;
    else unique.push({ ...point });
  });
  if (unique.length < 2) return fallback.map((point) => ({ ...point }));
  let previousRatio = direction === "discharge" ? 0 : 1;
  return unique.map((point) => {
    const powerRatio = direction === "discharge"
      ? Math.max(previousRatio, point.powerRatio)
      : Math.min(previousRatio, point.powerRatio);
    previousRatio = powerRatio;
    return { soc: point.soc, powerRatio };
  });
}

function resetRenewableTrendHistoryHydration({ clearHistory = false } = {}) {
  state.renewableTrendHistoryGeneration = (
    Number(state.renewableTrendHistoryGeneration) || 0
  ) + 1;
  state.renewableTrendHistoryRequests = {};
  state.renewableTrendFieldCursors = {};
  renewableTrendDeltaItems.fields = [];
  if (clearHistory) {
    state.renewableTrendHistory = [];
    if (state.chartPeriodOffsets) state.chartPeriodOffsets.renewableTrend = 0;
  }
}

function resetRenewableControlView(modelId = state.activeModelId) {
  closeRenewableControlLogDetailDialog();
  const control = state.renewableControl;
  Object.assign(control, {
    modelId: modelId || "",
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
    lastStatus: "正在读取学员台后台控制状态。",
    logs: [],
    metricTab: "ac",
    parameterTab: "runtime",
    strategyTab: "ac-wind",
    logPage: 1,
    selectedLogSeq: 0,
    lastControlLogRenderKey: "",
  });
  resetRenewableTrendHistoryHydration({ clearHistory: true });
}

function renewableDataSourceLabel(source = "") {
  return ({
    "trainee-live": "学员台实时数据",
    "trainee-cache": "学员台缓存数据",
  })[String(source || "")] || "等待实时数据";
}

function renewablePrerequisiteStatus(control = {}) {
  if (control.controlFrozen) {
    return "模拟台暂停，学员台保持冻结；恢复后将继续原运行状态。";
  }
  if (control.prerequisiteStatus) return control.prerequisiteStatus;
  return control.receiveActive
    ? "学员台正在等待第一份实时数据。"
    : "请先启动接收，再启动新能源实时控制。";
}

function renewableTrendLifecycleChanged(previous = {}, current = {}) {
  if (Number(previous.runId ?? 0) !== Number(current.runId ?? 0)) return true;
  const previousStep = Number(previous.stepCount);
  const currentStep = Number(current.stepCount);
  if (Number.isFinite(previousStep) && Number.isFinite(currentStep) && currentStep < previousStep) return true;
  const previousMinute = Number(previous.minute);
  const currentMinute = Number(current.minute);
  return Number.isFinite(previousMinute) && Number.isFinite(currentMinute) && currentMinute < previousMinute;
}

function latestRenewableTrendSegment(points = []) {
  const source = Array.isArray(points) ? points : [];
  let segmentStart = 0;
  for (let index = 1; index < source.length; index += 1) {
    if (renewableTrendLifecycleChanged(source[index - 1], source[index])) segmentStart = index;
  }
  return source.slice(segmentStart);
}

function renewableTrendDeltaItems(payload = {}) {
  const legacyTrend = Array.isArray(payload?.trend) ? payload.trend : [];
  if (payload?.trendEncoding !== "arrays-v1") return legacyTrend;

  const providedFields = Array.isArray(payload.trendFields)
    ? payload.trendFields.filter((field) => typeof field === "string" && field)
    : [];
  if (providedFields.length) renewableTrendDeltaItems.fields = providedFields;
  const fields = Array.isArray(renewableTrendDeltaItems.fields)
    ? renewableTrendDeltaItems.fields
    : [];
  if (!fields.length || !Array.isArray(payload.trendRows)) return legacyTrend;

  const missingByRow = new Map();
  (Array.isArray(payload.trendMissing) ? payload.trendMissing : []).forEach((entry) => {
    if (!Array.isArray(entry) || !Number.isInteger(Number(entry[0]))) return;
    missingByRow.set(
      Number(entry[0]),
      new Set(
        (Array.isArray(entry[1]) ? entry[1] : [])
          .map((index) => Number(index))
          .filter((index) => Number.isInteger(index) && index >= 0),
      ),
    );
  });
  return payload.trendRows.map((row, rowIndex) => {
    if (!Array.isArray(row)) return null;
    const missing = missingByRow.get(rowIndex) || new Set();
    const point = {};
    fields.forEach((field, fieldIndex) => {
      if (fieldIndex < row.length && !missing.has(fieldIndex)) point[field] = row[fieldIndex];
    });
    return point;
  }).filter((point) => point !== null);
}
renewableTrendDeltaItems.fields = [];

function mergeRenewableTrendFieldDelta(current = [], incoming = []) {
  const merged = new Map();
  (Array.isArray(current) ? current : []).forEach((point) => {
    const sampleKey = String(point?.sampleKey || "");
    if (sampleKey) merged.set(sampleKey, { ...point });
  });
  (Array.isArray(incoming) ? incoming : []).forEach((point) => {
    const sampleKey = String(point?.sampleKey || "");
    if (!sampleKey) return;
    merged.set(sampleKey, { ...(merged.get(sampleKey) || {}), ...point });
  });
  return Array.from(merged.values()).sort((left, right) => (
    (Number(left?.runId) || 0) - (Number(right?.runId) || 0)
    || (Number(left?.stepCount) || 0) - (Number(right?.stepCount) || 0)
    || (Number(left?.minute) || 0) - (Number(right?.minute) || 0)
    || String(left?.sampleKey || "").localeCompare(String(right?.sampleKey || ""))
  ));
}

function mergeRenewableTrendDelta(current = [], incoming = [], reset = false) {
  const merged = reset ? [] : latestRenewableTrendSegment(current).slice();
  (Array.isArray(incoming) ? incoming : []).forEach((point) => {
    if (!point || typeof point !== "object") return;
    if (merged.length && renewableTrendLifecycleChanged(merged[merged.length - 1], point)) {
      merged.length = 0;
    }
    const sampleKey = String(point.sampleKey || "");
    const existingIndex = sampleKey
      ? merged.findIndex((candidate) => String(candidate?.sampleKey || "") === sampleKey)
      : -1;
    if (existingIndex >= 0) {
      merged.splice(existingIndex, merged.length - existingIndex, point);
    } else {
      merged.push(point);
    }
  });
  const result = latestRenewableTrendSegment(merged);
  return result.length > 4320 ? result.slice(result.length - 4320) : result;
}

function mergeRenewableControlLogDelta(current = [], incoming = [], reset = false) {
  const merged = new Map();
  if (!reset) {
    (Array.isArray(current) ? current : []).forEach((item) => {
      const seq = Number(item?.seq) || 0;
      if (seq > 0) merged.set(seq, item);
    });
  }
  (Array.isArray(incoming) ? incoming : []).forEach((item) => {
    const seq = Number(item?.seq) || 0;
    if (seq > 0) merged.set(seq, item);
  });
  return Array.from(merged.values())
    .sort((left, right) => (Number(right?.seq) || 0) - (Number(left?.seq) || 0))
    .slice(0, 300);
}

function resetRenewableControlHistoryForLifecycle(control = state.renewableControl) {
  closeRenewableControlLogDetailDialog();
  control.logs = [];
  control.revision = -1;
  control.planRevision = -1;
  control.settingsRevision = -1;
  control.lastPlan = null;
  control.logPage = 1;
  control.selectedLogSeq = 0;
  control.lastControlLogRenderKey = "";
  control.latestTrendSampleKey = "";
  resetRenewableTrendHistoryHydration({ clearHistory: true });
}

function applyRenewableControlState(payload = {}) {
  if (!payload || typeof payload !== "object") return false;
  const control = state.renewableControl;
  const incomingControllerInstanceId = String(
    payload.controllerInstanceId || control.controllerInstanceId || "",
  );
  const controllerLifecycleChanged = Boolean(
    incomingControllerInstanceId
    && control.controllerInstanceId
    && incomingControllerInstanceId !== control.controllerInstanceId,
  );
  const incomingRevision = Number(payload.revision);
  const incomingPlanRevision = Number(payload.planRevision);
  const incomingSettingsRevision = Number(payload.settingsRevision);
  const hasLastPlan = Object.prototype.hasOwnProperty.call(payload, "lastPlan");
  const hasTrendPayload = (
    Object.prototype.hasOwnProperty.call(payload, "trend")
    || Object.prototype.hasOwnProperty.call(payload, "trendRows")
  );
  if (
    !controllerLifecycleChanged
    &&
    payload.modelId
    && control.modelId === payload.modelId
    && Number.isFinite(incomingRevision)
    && incomingRevision < Number(control.revision ?? -1)
  ) {
    return false;
  }
  if (controllerLifecycleChanged) resetRenewableControlHistoryForLifecycle(control);
  const settings = payload.settings && typeof payload.settings === "object" ? payload.settings : {};
  Object.assign(control, {
    modelId: String(payload.modelId || state.activeModelId || ""),
    controllerInstanceId: incomingControllerInstanceId,
    enabled: Boolean(payload.enabled),
    desiredEnabled: Boolean(payload.desiredEnabled),
    resumePending: Boolean(payload.resumePending),
    runState: ["running", "frozen", "resume_pending", "stopped"].includes(payload.runState)
      ? payload.runState
      : payload.enabled
        ? "running"
        : payload.desiredEnabled
          ? "resume_pending"
          : "stopped",
    controlFrozen: Boolean(payload.controlFrozen),
    simulationPaused: Boolean(payload.simulationPaused),
    receiveActive: Boolean(payload.receiveActive),
    canRun: Boolean(payload.canRun),
    prerequisiteStatus: payload.prerequisiteStatus || "",
    loopMode: payload.loopMode === "closed" ? "closed" : "open",
    sending: Boolean(payload.sending),
    intervalSeconds: Math.max(1, toNumber(
      settings.simulationIntervalSeconds ?? settings.intervalSeconds,
      control.intervalSeconds || 2,
    )),
    largeStepThresholdKw: Math.max(0, toNumber(settings.largeStepThresholdKw, control.largeStepThresholdKw || 10)),
    stepCoefficient: Math.max(0, toNumber(
      settings.renewableStepRatio ?? settings.stepCoefficient,
      control.stepCoefficient || 0.03,
    )),
    storageStepRatio: Math.max(0, toNumber(
      settings.storageStepRatio,
      control.storageStepRatio || 0.03,
    )),
    storageSocCorrectionStepScale: Math.min(1, Math.max(0.1, toNumber(
      settings.storageSocCorrectionStepScale,
      control.storageSocCorrectionStepScale || 0.2,
    ))),
    gridFormingStorageProtectionRatio: Math.max(0, toNumber(
      settings.gridFormingStorageProtectionRatio
        ?? (Number.isFinite(Number(settings.storageSwitchDeadbandKw))
          ? Number(settings.storageSwitchDeadbandKw) / 100
          : undefined),
      control.gridFormingStorageProtectionRatio || 0.05,
    )),
    dieselPowerProtectionRatio: Math.max(0, toNumber(
      settings.dieselPowerProtectionRatio ?? settings.dieselDeadbandRatio,
      control.dieselPowerProtectionRatio || 0.03,
    )),
    socDeadband: Math.max(0, toNumber(settings.socDeadband, control.socDeadband || 0.05)),
    hydrogenClosedLoopEnabled: Boolean(
      settings.hydrogenClosedLoopEnabled
        ?? control.hydrogenClosedLoopEnabled
        ?? true,
    ),
    hydrogenPressureDeadbandRatio: Math.min(0.5, Math.max(0, toNumber(
      settings.hydrogenPressureDeadbandRatio,
      control.hydrogenPressureDeadbandRatio || 0.05,
    ))),
    electrolyzerPowerMinRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerPowerMinRatio, control.electrolyzerPowerMinRatio ?? 0.20))),
    electrolyzerPowerMaxRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerPowerMaxRatio, control.electrolyzerPowerMaxRatio ?? 0.90))),
    electrolyzerPowerDeadbandRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerPowerDeadbandRatio, control.electrolyzerPowerDeadbandRatio ?? 0.10))),
    electrolyzerPowerStepRatio: Math.min(1, Math.max(0.00001, toNumber(settings.electrolyzerPowerStepRatio, control.electrolyzerPowerStepRatio ?? 0.10))),
    electrolyzerDieselPowerLimitRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerDieselPowerLimitRatio, control.electrolyzerDieselPowerLimitRatio ?? 0.35))),
    electrolyzerDieselPowerDeadbandRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerDieselPowerDeadbandRatio, control.electrolyzerDieselPowerDeadbandRatio ?? 0.05))),
    electrolyzerDieselPowerStopMaximumRatio: Math.min(1, Math.max(0, toNumber(settings.electrolyzerDieselPowerStopMaximumRatio, control.electrolyzerDieselPowerStopMaximumRatio ?? 0.50))),
    electrolyzerStorageSocStartMinimum: Math.min(1, Math.max(0, toNumber(
      settings.electrolyzerStorageSocStartMinimum ?? settings.electrolyzerStorageSocUpperLimit,
      control.electrolyzerStorageSocStartMinimum ?? 0.7,
    ))),
    electrolyzerStorageSocStopMaximum: Math.min(1, Math.max(0, toNumber(
      settings.electrolyzerStorageSocStopMaximum ?? settings.electrolyzerStorageSocLowerLimit,
      control.electrolyzerStorageSocStopMaximum ?? 0.3,
    ))),
    electrolyzerHydrogenStorageSocStopMinimum: Math.min(1, Math.max(0, toNumber(
      settings.electrolyzerHydrogenStorageSocStopMinimum ?? settings.electrolyzerHydrogenStorageSocUpperLimit,
      control.electrolyzerHydrogenStorageSocStopMinimum ?? 0.9,
    ))),
    fuelCellPowerMinRatio: Math.min(1, Math.max(0, toNumber(settings.fuelCellPowerMinRatio, control.fuelCellPowerMinRatio ?? 0.20))),
    fuelCellPowerMaxRatio: Math.min(1, Math.max(0, toNumber(settings.fuelCellPowerMaxRatio, control.fuelCellPowerMaxRatio ?? 0.90))),
    fuelCellPowerDeadbandRatio: Math.min(1, Math.max(0, toNumber(settings.fuelCellPowerDeadbandRatio, control.fuelCellPowerDeadbandRatio ?? 0.10))),
    fuelCellPowerStepRatio: Math.min(1, Math.max(0.00001, toNumber(settings.fuelCellPowerStepRatio, control.fuelCellPowerStepRatio ?? 0.10))),
    fuelCellDieselPowerLimitRatio: Math.min(1, Math.max(0, toNumber(settings.fuelCellDieselPowerLimitRatio, control.fuelCellDieselPowerLimitRatio ?? 0.50))),
    fuelCellDieselPowerStopMinimumRatio: Math.min(1, Math.max(0, toNumber(settings.fuelCellDieselPowerStopMinimumRatio, control.fuelCellDieselPowerStopMinimumRatio ?? 0.30))),
    fuelCellStorageSocLimit: Math.min(1, Math.max(0, toNumber(settings.fuelCellStorageSocLimit, control.fuelCellStorageSocLimit ?? 0.3))),
    fuelCellHydrogenStorageSocUpperLimit: Math.min(1, Math.max(0, toNumber(settings.fuelCellHydrogenStorageSocUpperLimit, control.fuelCellHydrogenStorageSocUpperLimit ?? 0.3))),
    fuelCellHydrogenStorageSocLowerLimit: Math.min(1, Math.max(0, toNumber(settings.fuelCellHydrogenStorageSocLowerLimit, control.fuelCellHydrogenStorageSocLowerLimit ?? 0.2))),
    optimizationRenewableCurtailmentWeight: Math.max(0, toNumber(settings.optimizationRenewableCurtailmentWeight, control.optimizationRenewableCurtailmentWeight || 1)),
    optimizationDieselOutputWeight: Math.max(0, toNumber(settings.optimizationDieselOutputWeight, control.optimizationDieselOutputWeight || 1)),
    optimizationCurtailmentSquareWeight: Math.max(0, toNumber(settings.optimizationCurtailmentSquareWeight, control.optimizationCurtailmentSquareWeight || 0.000001)),
    optimizationSourceStorageAdjustmentSquareWeight: Math.max(0, toNumber(settings.optimizationSourceStorageAdjustmentSquareWeight, control.optimizationSourceStorageAdjustmentSquareWeight || 0.000001)),
    optimizationBalanceDeltaSquareWeight: Math.max(0, toNumber(settings.optimizationBalanceDeltaSquareWeight, control.optimizationBalanceDeltaSquareWeight || 10000)),
    optimizationBalanceDeltaWarningKw: Math.max(0, toNumber(settings.optimizationBalanceDeltaWarningKw, control.optimizationBalanceDeltaWarningKw || 1)),
    optimizationBalanceToleranceKw: Math.max(0, toNumber(settings.optimizationBalanceToleranceKw, control.optimizationBalanceToleranceKw || 0.1)),
    optimizationBoundToleranceKw: Math.max(0, toNumber(settings.optimizationBoundToleranceKw, control.optimizationBoundToleranceKw || 0.1)),
    optimizationFtol: Math.max(0, toNumber(settings.optimizationFtol, control.optimizationFtol || 0.001)),
    optimizationMaxIterations: Math.max(1, Math.round(toNumber(settings.optimizationMaxIterations, control.optimizationMaxIterations || 100))),
    commandValidMinutes: Math.max(0.1, toNumber(settings.commandValidMinutes, control.commandValidMinutes || 120)),
    storageChargeDeratingCurve: normalizeStorageDeratingCurve(
      settings.storageChargeDeratingCurve,
      control.storageChargeDeratingCurve || DEFAULT_STORAGE_CHARGE_DERATING_CURVE,
      "charge",
    ),
    storageDischargeDeratingCurve: normalizeStorageDeratingCurve(
      settings.storageDischargeDeratingCurve,
      control.storageDischargeDeratingCurve || DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE,
      "discharge",
    ),
    planRevision: Number.isFinite(incomingPlanRevision)
      ? incomingPlanRevision
      : control.planRevision,
    settingsRevision: Number.isFinite(incomingSettingsRevision)
      ? incomingSettingsRevision
      : control.settingsRevision,
    lastCalculatedAt: payload.lastCalculatedAt || "",
    lastSentAt: payload.lastSentAt || "",
    latestTrendSampleKey: String(
      payload.latestTrendSampleKey ?? control.latestTrendSampleKey ?? "",
    ),
    lastStatus: payload.status || "学员台后台控制状态已同步。",
    revision: Number.isFinite(incomingRevision) ? incomingRevision : control.revision,
    logs: mergeRenewableControlLogDelta(
      control.logs,
      payload.logs,
      payload.logsReset !== false,
    ),
  });
  if (hasLastPlan) control.lastPlan = payload.lastPlan || null;
  if (control.selectedLogSeq && !renewableControlLogBySeq(control.selectedLogSeq)) {
    control.selectedLogSeq = 0;
    closeRenewableControlLogDetailDialog();
  }
  if (hasTrendPayload) {
    state.renewableTrendHistory = mergeRenewableTrendDelta(
      state.renewableTrendHistory,
      renewableTrendDeltaItems(payload),
      payload.trendReset !== false,
    );
  }
  return true;
}

function renewableTrendRequestedFields() {
  const chartKey = "renewableTrend";
  ensureRenewableTrendSeriesSelection(RENEWABLE_TREND_SERIES_DEFS);
  const metrics = state.renewableControl.lastPlan?.metrics || {};
  const availableSeries = RENEWABLE_TREND_SERIES_DEFS.filter(
    (series) => renewableTrendSeriesAvailable(series, metrics),
  );
  const selectedSeries = visibleChartSeries(chartKey, availableSeries);
  const visibleSeries = visibleChartLegendSeries(chartKey, selectedSeries);
  return Array.from(new Set(visibleSeries.map((series) => series.field).filter(Boolean)));
}

function mergeRenewableTrendHistoryPayload(
  payload,
  requestedFields,
  cursor,
  { generation, modelId, controllerInstanceId },
) {
  if (!payload || payload.trendEncoding !== "arrays-v1") return false;
  if (
    (Number(state.renewableTrendHistoryGeneration) || 0) !== generation
    || state.activeModelId !== modelId
    || String(state.renewableControl.controllerInstanceId || "") !== controllerInstanceId
    || String(payload.controllerInstanceId || "") !== controllerInstanceId
  ) {
    return false;
  }
  if (cursor && payload.trendReset !== false) {
    state.renewableTrendHistory = [];
    state.renewableTrendFieldCursors = {};
    renewableTrendDeltaItems.fields = [];
    resetChartPeriodOffsets("renewableTrend");
  }
  const incoming = renewableTrendDeltaItems(payload);
  state.renewableTrendHistory = mergeRenewableTrendFieldDelta(
    state.renewableTrendHistory,
    incoming,
  );
  const latestTrendSampleKey = String(payload.latestTrendSampleKey || "");
  const nextCursors = { ...(state.renewableTrendFieldCursors || {}) };
  requestedFields.forEach((field) => {
    nextCursors[field] = latestTrendSampleKey;
  });
  state.renewableTrendFieldCursors = nextCursors;
  state.renewableControl.latestTrendSampleKey = latestTrendSampleKey;
  return incoming.length > 0;
}

async function requestRenewableTrendHistoryFields(fields, cursor, context) {
  const requestedFields = Array.from(new Set(fields)).sort();
  const requestKey = [
    context.generation,
    context.modelId,
    context.controllerInstanceId,
    cursor,
    requestedFields.join(","),
  ].join("|");
  const existingRequest = state.renewableTrendHistoryRequests?.[requestKey];
  if (existingRequest) return existingRequest;
  const request = api(renewableTrendHistoryApiPath(requestedFields, cursor))
    .then((payload) => mergeRenewableTrendHistoryPayload(
      payload,
      requestedFields,
      cursor,
      context,
    ))
    .catch((error) => {
      console.warn("新能源趋势历史加载失败", error);
      return false;
    })
    .finally(() => {
      delete state.renewableTrendHistoryRequests[requestKey];
    });
  state.renewableTrendHistoryRequests[requestKey] = request;
  return request;
}

async function ensureRenewableTrendHistoryForVisibleSeries({ render = true } = {}) {
  if (currentPageName() !== "renewable" || !state.activeModelId) return false;
  const controllerInstanceId = String(
    state.renewableControl.controllerInstanceId || "",
  );
  const latestTrendSampleKey = String(
    state.renewableControl.latestTrendSampleKey || "",
  );
  if (!controllerInstanceId || !latestTrendSampleKey) return false;
  const requestedFields = renewableTrendRequestedFields();
  if (!requestedFields.length) return false;

  const cursors = state.renewableTrendFieldCursors || {};
  const fieldsByCursor = new Map();
  requestedFields.forEach((field) => {
    const loaded = Object.prototype.hasOwnProperty.call(cursors, field);
    const cursor = loaded ? String(cursors[field] || "") : "";
    if (loaded && cursor === latestTrendSampleKey) return;
    if (!fieldsByCursor.has(cursor)) fieldsByCursor.set(cursor, []);
    fieldsByCursor.get(cursor).push(field);
  });
  if (!fieldsByCursor.size) return false;

  const context = {
    generation: Number(state.renewableTrendHistoryGeneration) || 0,
    modelId: state.activeModelId,
    controllerInstanceId,
  };
  let changed = false;
  const groups = Array.from(fieldsByCursor.entries()).sort(([left], [right]) => (
    Number(Boolean(right)) - Number(Boolean(left))
  ));
  for (const [cursor, fields] of groups) {
    if ((Number(state.renewableTrendHistoryGeneration) || 0) !== context.generation) break;
    changed = await requestRenewableTrendHistoryFields(fields, cursor, context) || changed;
  }
  if (changed) {
    persistActiveModelContext();
    if (render && currentPageName() === "renewable") drawRenewableTrendChart();
  }
  return changed;
}

async function refreshRenewableControlState({ preview = false, render = true } = {}) {
  const control = state.renewableControl;
  if (!state.activeModelId || control.requestActive) return null;
  const requestedModelId = state.activeModelId;
  control.requestActive = true;
  try {
    const payload = await api(renewableControlApiPath(preview));
    if (requestedModelId !== state.activeModelId) return null;
    applyRenewableControlState(payload);
    if (currentPageName() === "renewable") {
      await ensureRenewableTrendHistoryForVisibleSeries({ render: false });
    }
    return payload;
  } catch (error) {
    if (requestedModelId === state.activeModelId) {
      control.lastStatus = `学员台后台控制状态获取失败：${apiErrorText(error)}`;
    }
    return null;
  } finally {
    if (requestedModelId === state.activeModelId) {
      control.requestActive = false;
      if (render && currentPageName() === "renewable") renderRenewableControl(state.snapshot || {});
    }
  }
}

async function runRenewableControlAction(action, payload = {}) {
  const control = state.renewableControl;
  if (!state.activeModelId || control.actionActive) return null;
  const requestedModelId = state.activeModelId;
  control.actionActive = true;
  renderRenewableControl(state.snapshot || {});
  try {
    const response = await api("/api/trainee/renewable-control?trend=0", {
      method: "POST",
      body: JSON.stringify({ action, ...payload }),
    });
    if (requestedModelId !== state.activeModelId) return null;
    applyRenewableControlState(response);
    if (currentPageName() === "renewable") {
      await ensureRenewableTrendHistoryForVisibleSeries({ render: false });
    }
    return response;
  } catch (error) {
    if (requestedModelId === state.activeModelId) {
      control.lastStatus = `后台控制操作失败：${apiErrorText(error)}`;
    }
    return null;
  } finally {
    if (requestedModelId === state.activeModelId) {
      control.actionActive = false;
      renderRenewableControl(state.snapshot || {});
    }
  }
}
function renewableLoopMode(control = state.renewableControl) {
  return control?.loopMode === "closed" ? "closed" : "open";
}

function renewableLoopModeLabel(mode = renewableLoopMode()) {
  return mode === "closed" ? "闭环" : "开环";
}

function noteRenewableReceiveInterruption(message) {
  if (message) state.renewableControl.lastStatus = message;
  refreshRenewableControlState({
    preview: false,
    render: currentPageName() === "renewable",
  });
}

function renderRenewablePager(kind, totalCount) {
  if (kind !== "logs") return;
  const pageSize = RENEWABLE_CONTROL_LOG_PAGE_SIZE;
  const pager = $("renewableControlLogPager");
  if (!pager) return;
  const total = Math.max(0, Number(totalCount) || 0);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.max(1, Number(state.renewableControl.logPage) || 1), pageCount);
  state.renewableControl.logPage = page;
  if (!total) {
    pager.innerHTML = "";
    return;
  }
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);
  pager.innerHTML = `
    <span>${start}-${end} / ${total} 条</span>
    <button type="button" data-renewable-pager="logs" data-renewable-page-action="prev" ${page <= 1 ? "disabled" : ""}>上一页</button>
    <strong>第 ${page} / ${pageCount} 页</strong>
    <button type="button" data-renewable-pager="logs" data-renewable-page-action="next" ${page >= pageCount ? "disabled" : ""}>下一页</button>
  `;
}

function renewableRemoteAdjustmentPointName(row = {}) {
  if (!row.dev_type || !row.dev_name) return "--";
  if (row.commandKind === "run_status") return `${row.dev_type}.${row.dev_name}.run_stat`;
  if (!row.set_type) return "--";
  return `${row.dev_type}.${row.dev_name}.${row.set_type}`;
}

function renewableRowControlPointPower(row = {}, value = null) {
  const numeric = optionalNumber(value);
  if (numeric === null) return null;
  return row.set_type === "p_dc_set" ? -numeric : numeric;
}

function renewableRowBoundaryText(row = {}) {
  if (row.commandKind === "run_status") return "退出 / 投入";
  if (row.category === "柴油发电") return `下限 ${formatNumber(row.minKw)} / 容量 ${formatNumber(row.capacityKw)}`;
  if (String(row.category || "").includes("储能")) return `充 ${formatNumber(row.chargePower)} / 放 ${formatNumber(row.dischargePower)}`;
  if (row.category === "交直流变流器") return Number.isFinite(row.transferCapacityKw)
    ? `${formatNumber(row.transferCapacityKw)} kW`
    : "--";
  if (Number.isFinite(row.availableKw)) return `${formatNumber(row.availableKw)} kW`;
  if (Number.isFinite(row.capacityKw)) return `${formatNumber(row.capacityKw)} kW`;
  return "--";
}

function renewableRowStatusLabel(row = {}) {
  if (row.connectionStatusLabel) return row.connectionStatusLabel;
  if (row.statusLabel) return row.statusLabel;
  if (row.online) return "可控";
  if (row.activelyConnected === false) return "当前断开";
  return "停用";
}

function renewableStrategyRows(plan, tabKey = state.renewableControl.strategyTab) {
  const normalizedTab = RENEWABLE_STRATEGY_TABS[tabKey] ? tabKey : "ac-wind";
  const categories = RENEWABLE_STRATEGY_TABS[normalizedTab].categories;
  return (plan?.commandRows || []).filter((row) => categories.has(row.category));
}

function renderRenewableStrategyTabs(plan) {
  const requestedTab = state.renewableControl.strategyTab;
  const activeTab = RENEWABLE_STRATEGY_TABS[requestedTab] ? requestedTab : "ac-wind";
  state.renewableControl.strategyTab = activeTab;
  document.querySelectorAll("[data-renewable-strategy-tab]").forEach((button) => {
    const tabKey = button.dataset.renewableStrategyTab || "";
    const tab = RENEWABLE_STRATEGY_TABS[tabKey];
    if (!tab) return;
    const active = tabKey === activeTab;
    const count = renewableStrategyRows(plan, tabKey).length;
    button.textContent = tab.label;
    button.title = `${tab.label}：${count} 台设备`;
    button.setAttribute("aria-label", `${tab.label}，${count} 台设备`);
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
}

function renewableControlLogs() {
  return Array.isArray(state.renewableControl.logs) ? state.renewableControl.logs : [];
}

function renewableControlLogBySeq(seq) {
  const normalizedSeq = Number(seq) || 0;
  return renewableControlLogs().find((item) => (Number(item?.seq) || 0) === normalizedSeq) || null;
}

function renewableControlLogSummaryText(item = {}) {
  const detail = runtimeLogDetailText(item.detail).trim();
  if (!detail) return "--";
  const parts = detail.split(/[；\n]+/).map((part) => part.trim()).filter(Boolean);
  const preferred = parts.find((part) => /^(新能源|控制结果|已下发|开环|自动控制|告警|指令|撤销|下发)/.test(part));
  const summary = preferred || parts[0] || detail;
  return summary.length > 140 ? `${summary.slice(0, 137)}...` : summary;
}

function renewableControlLogDetailLines(item = {}) {
  const source = Array.isArray(item.full_detail)
    ? item.full_detail
    : item.full_detail !== undefined && item.full_detail !== null
      ? [item.full_detail]
      : Array.isArray(item.detail)
        ? item.detail
        : String(item.detail || "").split(/[；\n]+/);
  const lines = source.map((line) => String(line || "")).filter((line) => line.trim());
  return lines.length ? lines : ["该条日志没有附加决策详情。"];
}

function renewableControlLogDetailLineClass(line = "") {
  const trimmed = String(line || "").trim();
  if (/^【(边界提示|数据提示|告警)】/.test(trimmed)) return "is-warning";
  if (/^【.+】/.test(trimmed)) return "is-section";
  if (/^[·•\-]/.test(trimmed)) return "is-subitem";
  return "";
}

function selectRenewableControlLogRow(seq) {
  const normalizedSeq = Number(seq) || 0;
  if (!renewableControlLogBySeq(normalizedSeq)) return false;
  state.renewableControl.selectedLogSeq = normalizedSeq;
  document.querySelectorAll("#renewableControlLogTable [data-renewable-log-seq]").forEach((row) => {
    const selected = (Number(row.dataset.renewableLogSeq) || 0) === normalizedSeq;
    row.classList.toggle("is-selected", selected);
    row.setAttribute("aria-selected", String(selected));
  });
  return true;
}

function openRenewableControlLogDetailDialog(seq) {
  const item = renewableControlLogBySeq(seq);
  const dialog = $("renewableControlLogDetailDialog");
  const meta = $("renewableControlLogDetailMeta");
  const body = $("renewableControlLogDetailBody");
  if (!item || !dialog || !meta || !body) return;
  selectRenewableControlLogRow(item.seq);
  $("renewableControlLogDetailSequence").textContent = `日志 #${Number(item.seq) || "--"}`;
  meta.innerHTML = `
    <div><dt>本机时刻</dt><dd>${escapeHtml(runtimeLogWallTimeText(item.wall_time))}</dd></div>
    <div><dt>仿真时刻</dt><dd>${escapeHtml(item.simu_time || "--")}</dd></div>
    <div><dt>类型</dt><dd>${escapeHtml(item.type || "--")}</dd></div>
    <div><dt>结果</dt><dd class="is-${escapeHtml(item.level || "info")}">${escapeHtml(item.result || "--")}</dd></div>`;
  body.innerHTML = renewableControlLogDetailLines(item)
    .map((line) => {
      const cls = renewableControlLogDetailLineClass(line);
      const text = line.trim();
      const classAttr = cls ? ` class="${cls}"` : "";
      return `<li${classAttr}><span>${escapeHtml(text)}</span></li>`;
    })
    .join("");
  if (!dialog.open) dialog.showModal();
}

function closeRenewableControlLogDetailDialog() {
  const dialog = $("renewableControlLogDetailDialog");
  if (dialog?.open) dialog.close();
}

function renderRenewableMetricTabs() {
  const allowedTabs = new Set(["ac", "dc", "system", "hydrogen"]);
  const activeTab = allowedTabs.has(state.renewableControl.metricTab)
    ? state.renewableControl.metricTab
    : "ac";
  state.renewableControl.metricTab = activeTab;
  document.querySelectorAll("[data-renewable-metric-tab]").forEach((button) => {
    const active = button.dataset.renewableMetricTab === activeTab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-renewable-metric-pane]").forEach((pane) => {
    const active = pane.dataset.renewableMetricPane === activeTab;
    pane.hidden = !active;
    pane.classList.toggle("is-active", active);
  });
}

function renderRenewableControlParameterTabs(requestedTab = "") {
  const allowedTabs = new Set(["runtime", "protection", "hydrogen", "optimization"]);
  const currentTab = state.renewableControl.parameterTab;
  const activeTab = allowedTabs.has(requestedTab)
    ? requestedTab
    : allowedTabs.has(currentTab)
      ? currentTab
      : "runtime";
  state.renewableControl.parameterTab = activeTab;
  document.querySelectorAll("[data-renewable-parameter-tab]").forEach((button) => {
    const active = button.dataset.renewableParameterTab === activeTab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-renewable-parameter-pane]").forEach((pane) => {
    const active = pane.dataset.renewableParameterPane === activeTab;
    pane.hidden = !active;
    pane.classList.toggle("is-active", active);
    if (active) pane.scrollTop = 0;
  });
}

function renderRenewableDetailTabs() {
  const requestedTab = state.renewableControl.detailTab;
  const activeTab = ["trend", "logs"].includes(requestedTab)
    ? requestedTab
    : "trend";
  state.renewableControl.detailTab = activeTab;
  document.querySelectorAll("[data-renewable-detail-tab]").forEach((button) => {
    const active = button.dataset.renewableDetailTab === activeTab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-renewable-detail-pane]").forEach((pane) => {
    const active = pane.dataset.renewableDetailPane === activeTab;
    pane.hidden = !active;
    pane.classList.toggle("is-active", active);
  });
  if (activeTab === "logs") {
    renderRenewableControlLogs();
  } else {
    requestAnimationFrame(drawRenewableTrendChart);
  }
}

function renderRenewableControlLogs() {
  const table = $("renewableControlLogTable");
  const summary = $("renewableControlLogSummary");
  if (!table || !summary) return;
  const logs = renewableControlLogs();
  summary.textContent = `${logs.length} 条`;
  renderRenewablePager("logs", logs.length);
  const page = state.renewableControl.logPage;
  const start = (page - 1) * RENEWABLE_CONTROL_LOG_PAGE_SIZE;
  const pageLogs = logs.slice(start, start + RENEWABLE_CONTROL_LOG_PAGE_SIZE);
  const selectedLogSeq = Number(state.renewableControl.selectedLogSeq) || 0;
  const renderKey = `${page}|${logs.length}|${pageLogs.map((item) => item.seq).join(",")}|${selectedLogSeq}`;
  if (renderKey === state.renewableControl.lastControlLogRenderKey) return;
  state.renewableControl.lastControlLogRenderKey = renderKey;
  if (!pageLogs.length) {
    table.innerHTML = '<div class="empty-state compact">暂无新能源控制日志</div>';
    return;
  }
  table.innerHTML = `
    <table class="runtime-log-table renewable-control-log-table">
      <thead><tr><th>本机时刻</th><th>仿真时刻</th><th>类型</th><th>结果</th><th>决策摘要</th></tr></thead>
      <tbody>
        ${pageLogs.map((item) => `
          <tr class="runtime-log-row is-${escapeHtml(item.level || "info")}${Number(item.seq) === selectedLogSeq ? " is-selected" : ""}" data-renewable-log-seq="${escapeHtml(item.seq)}" tabindex="0" aria-selected="${Number(item.seq) === selectedLogSeq}" aria-label="日志 ${escapeHtml(item.seq)}，双击查看详细决策过程">
            <td>${escapeHtml(runtimeLogWallTimeText(item.wall_time))}</td>
            <td class="mono-cell">${escapeHtml(item.simu_time || "--")}</td>
            <td>${escapeHtml(item.type || "")}</td>
            <td>${escapeHtml(item.result || "")}</td>
            <td class="runtime-log-detail" title="${escapeHtml(renewableControlLogSummaryText(item))}">${escapeHtml(renewableControlLogSummaryText(item))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function renewableTrendWindowRange() {
  const history = state.renewableTrendHistory || [];
  const windowMinutes = Math.max(1, Number(state.renewableTrendWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  const range = alignedTraceWindowRange(
    history,
    windowMinutes,
    fallbackMinute,
    chartPeriodOffset("renewableTrend"),
    curveDisplayModeDurationMinutes(),
  );
  setChartPeriodOffset("renewableTrend", range.windowOffset);
  return range;
}

function renewableTrendWindowPoints(range = renewableTrendWindowRange()) {
  return traceWindowRealPoints(state.renewableTrendHistory || [], range);
}

function renewableMetricCount(metrics = {}, keys = []) {
  for (const key of keys) {
    const raw = metrics?.[key];
    if (raw === null || raw === undefined || raw === "") continue;
    const value = Number(raw);
    if (Number.isFinite(value)) return Math.max(0, value);
  }
  return null;
}

function renewableMetricGroupCount(metrics = {}, group = "") {
  const directKeys = {
    "ac-renewable": ["onlineAcRenewableCount"],
    "dc-renewable": ["onlineDcRenewableCount"],
    "ac-wind": ["onlineAcWindCount"],
    "dc-wind": ["onlineDcWindCount"],
    "ac-pv": ["onlineAcPvCount"],
    "dc-pv": ["onlineDcPvCount"],
    "ac-grid-following-storage": ["onlineAcGridFollowingStorageCount"],
    "dc-grid-following-storage": ["onlineDcGridFollowingStorageCount"],
    "ac-grid-forming-storage": ["onlineAcGridFormingStorageCount", "onlineAcBalanceStorageCount"],
    "dc-grid-forming-storage": ["onlineDcGridFormingStorageCount", "onlineDcBalanceStorageCount"],
    "ac-diesel": ["onlineAcDieselCount"],
    "dc-diesel": ["onlineDcDieselCount"],
    "ac-load": ["onlineAcLoadCount"],
    "dc-load": ["onlineDcLoadCount"],
    "system-acdc": ["onlineAcdcConverterCount", "storageConverterCount"],
    "hydrogen-electrolyzer": ["onlineElectrolyzerCount"],
    "hydrogen-fuel-cell": ["onlineFuelCellCount"],
    "hydrogen-storage": ["onlineHydrogenStorageCount"],
  };
  if (directKeys[group]) return renewableMetricCount(metrics, directKeys[group]);
  const aggregateGroups = {
    "system-renewable": ["ac-renewable", "dc-renewable"],
    "system-wind": ["ac-wind", "dc-wind"],
    "system-pv": ["ac-pv", "dc-pv"],
    "ac-storage": ["ac-grid-following-storage", "ac-grid-forming-storage"],
    "dc-storage": ["dc-grid-following-storage", "dc-grid-forming-storage"],
    "system-storage": ["ac-storage", "dc-storage"],
    "system-grid-following-storage": ["ac-grid-following-storage", "dc-grid-following-storage"],
    "system-grid-forming-storage": ["ac-grid-forming-storage", "dc-grid-forming-storage"],
    "system-diesel": ["ac-diesel", "dc-diesel"],
    "system-load": ["ac-load", "dc-load"],
  };
  const childGroups = aggregateGroups[group];
  if (!childGroups) return null;
  const counts = childGroups
    .map((childGroup) => renewableMetricGroupCount(metrics, childGroup))
    .filter((count) => count !== null);
  return counts.length ? counts.reduce((sum, count) => sum + count, 0) : null;
}

function renewableMetricGroupConfiguredCount(metrics = {}, group = "") {
  const directKeys = {
    "ac-grid-following-storage": ["acGridFollowingStorageCount"],
    "dc-grid-following-storage": ["dcGridFollowingStorageCount"],
    "ac-grid-forming-storage": ["acGridFormingStorageCount"],
    "dc-grid-forming-storage": ["dcGridFormingStorageCount"],
    "hydrogen-electrolyzer": ["configuredElectrolyzerCount"],
    "hydrogen-fuel-cell": ["configuredFuelCellCount"],
    "hydrogen-storage": ["configuredHydrogenStorageCount"],
  };
  if (directKeys[group]) return renewableMetricCount(metrics, directKeys[group]);
  const aggregateGroups = {
    "system-grid-following-storage": ["ac-grid-following-storage", "dc-grid-following-storage"],
    "system-grid-forming-storage": ["ac-grid-forming-storage", "dc-grid-forming-storage"],
    "ac-storage": ["ac-grid-following-storage", "ac-grid-forming-storage"],
    "dc-storage": ["dc-grid-following-storage", "dc-grid-forming-storage"],
    "system-storage": ["ac-storage", "dc-storage"],
  };
  const childGroups = aggregateGroups[group];
  if (!childGroups) return null;
  const counts = childGroups
    .map((childGroup) => renewableMetricGroupConfiguredCount(metrics, childGroup))
    .filter((count) => count !== null);
  return counts.length ? counts.reduce((sum, count) => sum + count, 0) : null;
}

function renewableMetricGroupAvailable(metrics = {}, group = "") {
  const configuredCount = renewableMetricGroupConfiguredCount(metrics, group);
  if (configuredCount !== null) return configuredCount > 0;
  const count = renewableMetricGroupCount(metrics, group);
  return count === null || count > 0;
}

function renewableMetricsWithCommandRowCounts(plan = {}) {
  const metrics = { ...(plan?.metrics || {}) };
  const storageRows = (plan?.commandRows || []).filter((row) => row?.technology === "storage");
  if (!storageRows.length) return metrics;

  const count = (side, role, onlineOnly = false) => storageRows.filter((row) => (
    String(row?.connectionSide || "").toUpperCase() === side
    && row?.role === role
    && (!onlineOnly || row?.online === true)
  )).length;
  const roles = [
    ["GridFollowing", "grid_following"],
    ["GridForming", "balance"],
  ];
  for (const side of ["AC", "DC"]) {
    const sideKey = side === "AC" ? "Ac" : "Dc";
    for (const [metricRole, rowRole] of roles) {
      metrics[`${sideKey[0].toLowerCase()}${sideKey.slice(1)}${metricRole}StorageCount`] = count(
        side,
        rowRole,
      );
      metrics[`online${sideKey}${metricRole}StorageCount`] = count(
        side,
        rowRole,
        true,
      );
    }
  }
  return metrics;
}

function renderRenewableMetricAvailability(metrics = {}) {
  document.querySelectorAll("[data-renewable-metric-group]").forEach((card) => {
    const alwaysVisible = card.dataset.renewableMetricAlways === "true";
    card.hidden = !alwaysVisible
      && !renewableMetricGroupAvailable(metrics, card.dataset.renewableMetricGroup || "");
  });
}

function renderRenewableTrendSeriesTree() {
  const container = $("renewableTrendSeriesGroups");
  if (!container || container.dataset.rendered === "true") return;
  const treeHtml = RENEWABLE_TREND_SCOPE_DEFS.map((scope) => {
    const devices = [];
    RENEWABLE_TREND_SERIES_DEFS
      .filter((series) => series.scope === scope.key)
      .forEach((series) => {
        let device = devices.find((candidate) => candidate.key === series.device);
        if (!device) {
          device = { key: series.device, label: series.deviceLabel, series: [] };
          devices.push(device);
        }
        device.series.push(series);
      });
    const deviceHtml = devices.map((device) => {
      const seriesHtml = device.series.map((series) => {
        const checked = RENEWABLE_TREND_DEFAULT_VISIBLE_SERIES.has(series.key) ? " checked" : "";
        const styleClass = `is-${series.style || "power"}`;
        const searchText = [
          scope.label,
          device.label,
          series.curveLabel,
          series.label,
          series.key,
          series.metricId,
        ].filter(Boolean).join(" ");
        return `
          <label
            class="renewable-trend-series-item"
            data-renewable-series-group="${escapeHtml(series.group)}"
            data-renewable-series-metric="${escapeHtml(series.metricId)}"
            data-renewable-series-search="${escapeHtml(searchText)}"
            title="${escapeHtml(series.label)}"
          >
            <input type="checkbox" data-chart-toggle="renewableTrend" data-chart-series="${escapeHtml(series.key)}"${checked} />
            <i class="renewable-trend-series-swatch ${styleClass}" style="--renewable-series-color: ${escapeHtml(series.color)}"></i>
            <span>${escapeHtml(series.curveLabel)}</span>
          </label>
        `;
      }).join("");
      return `
        <details class="renewable-trend-series-device" data-renewable-series-device="${escapeHtml(device.key)}">
          <summary><span>${escapeHtml(device.label)}</span><small>${device.series.length}</small></summary>
          <div class="renewable-trend-series-list">${seriesHtml}</div>
        </details>
      `;
    }).join("");
    const open = scope.key === "ac" ? " open" : "";
    return `
      <details class="renewable-trend-series-group" data-renewable-series-scope="${escapeHtml(scope.key)}"${open}>
        <summary><span>${escapeHtml(scope.label)}</span><small>${devices.length}</small></summary>
        <div class="renewable-trend-series-devices">${deviceHtml}</div>
      </details>
    `;
  }).join("");
  container.innerHTML = `${treeHtml}
    <div id="renewableTrendSeriesEmpty" class="renewable-trend-series-empty" hidden>没有匹配的曲线</div>
  `;
  container.dataset.rendered = "true";
}

function ensureRenewableTrendSeriesSelection(seriesDefs = []) {
  const chartKey = "renewableTrend";
  if (Object.prototype.hasOwnProperty.call(state.chartSeriesHidden || {}, chartKey)) return;
  state.chartSeriesHidden = {
    ...(state.chartSeriesHidden || {}),
    [chartKey]: seriesDefs
      .filter((series) => !RENEWABLE_TREND_DEFAULT_VISIBLE_SERIES.has(series.key))
      .map((series) => series.key),
  };
}

function renewableTrendSeriesAvailable(series = {}, metrics = {}) {
  return renewableMetricGroupAvailable(metrics, series.group || "");
}

function renewableTrendSeriesFilterText(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .trim()
    .toLocaleLowerCase("zh-CN");
}

function renewableTrendBatchSeriesInputs(metrics = {}) {
  renderRenewableTrendSeriesTree();
  const query = renewableTrendSeriesFilterText(state.renewableTrendSeriesFilter);
  return Array.from(document.querySelectorAll(".renewable-trend-series-item"))
    .map((item) => {
      const input = item.querySelector('input[data-chart-toggle="renewableTrend"]');
      const available = renewableMetricGroupAvailable(
        metrics,
        item.dataset.renewableSeriesGroup || "",
      );
      const searchText = renewableTrendSeriesFilterText(item.dataset.renewableSeriesSearch || "");
      const keywordMatches = !query || searchText.includes(query);
      return input && available && keywordMatches ? input : null;
    })
    .filter(Boolean);
}

function setRenewableTrendBatchSeriesVisibility(visible, metrics = {}) {
  const chartKey = "renewableTrend";
  const inputs = renewableTrendBatchSeriesInputs(metrics);
  if (!inputs.length) {
    applyRenewableTrendSeriesFilters(metrics);
    return;
  }
  const hidden = chartHiddenSet(chartKey);
  const legendHidden = chartLegendHiddenSet(chartKey);
  inputs.forEach((input) => {
    const seriesKey = input.dataset.chartSeries || "";
    if (!seriesKey) return;
    if (visible) hidden.delete(seriesKey);
    else hidden.add(seriesKey);
    legendHidden.delete(seriesKey);
  });
  state.chartSeriesHidden = {
    ...(state.chartSeriesHidden || {}),
    [chartKey]: Array.from(hidden),
  };
  state.chartLegendSeriesHidden = {
    ...(state.chartLegendSeriesHidden || {}),
    [chartKey]: Array.from(legendHidden),
  };

  const selectedKey = selectedChartSeriesKey(chartKey);
  if (visible && (!selectedKey || hidden.has(selectedKey))) {
    state.chartSeriesSelected = {
      ...(state.chartSeriesSelected || {}),
      [chartKey]: inputs[0].dataset.chartSeries || "",
    };
  } else if (!visible && inputs.some((input) => input.dataset.chartSeries === selectedKey)) {
    const fallback = RENEWABLE_TREND_SERIES_DEFS.find((series) => (
      renewableTrendSeriesAvailable(series, metrics) && !hidden.has(series.key)
    ));
    state.chartSeriesSelected = {
      ...(state.chartSeriesSelected || {}),
      [chartKey]: fallback?.key || "",
    };
  }
  syncChartLegendButtons(chartKey);
  drawRenewableTrendChart();
  ensureRenewableTrendHistoryForVisibleSeries();
}

function applyRenewableTrendSeriesFilters(metrics = {}) {
  renderRenewableTrendSeriesTree();
  const filterInput = $("renewableTrendSeriesFilter");
  const selectedOnlyInput = $("renewableTrendSelectedOnly");
  const clearAllButton = $("renewableTrendClearAll");
  const selectAllButton = $("renewableTrendSelectAll");
  const query = renewableTrendSeriesFilterText(state.renewableTrendSeriesFilter);
  const selectedOnly = Boolean(state.renewableTrendSelectedOnly);
  if (filterInput && filterInput.value !== state.renewableTrendSeriesFilter) {
    filterInput.value = state.renewableTrendSeriesFilter;
  }
  if (selectedOnlyInput) selectedOnlyInput.checked = selectedOnly;

  const items = Array.from(document.querySelectorAll(".renewable-trend-series-item"));
  let visibleCount = 0;
  items.forEach((item) => {
    const input = item.querySelector('input[data-chart-toggle="renewableTrend"]');
    const available = renewableMetricGroupAvailable(
      metrics,
      item.dataset.renewableSeriesGroup || "",
    );
    const searchText = renewableTrendSeriesFilterText(item.dataset.renewableSeriesSearch || "");
    if (!input) {
      item.hidden = true;
      return;
    }
    const keywordMatches = !query || searchText.includes(query);
    const selectionMatches = !selectedOnly || input.checked;
    item.hidden = !available || !keywordMatches || !selectionMatches;
    if (!item.hidden) visibleCount += 1;
  });

  const batchInputs = renewableTrendBatchSeriesInputs(metrics);
  const batchSelectedCount = batchInputs.filter((input) => input.checked).length;
  if (clearAllButton) {
    clearAllButton.disabled = batchInputs.length === 0 || batchSelectedCount === 0;
  }
  if (selectAllButton) {
    selectAllButton.disabled = batchInputs.length === 0 || batchSelectedCount === batchInputs.length;
  }

  const filterActive = Boolean(query || selectedOnly);
  document.querySelectorAll(".renewable-trend-series-device").forEach((device) => {
    const hasVisibleSeries = Array.from(device.querySelectorAll(".renewable-trend-series-item"))
      .some((item) => !item.hidden);
    device.hidden = !hasVisibleSeries;
    if (hasVisibleSeries && filterActive) device.open = true;
  });
  document.querySelectorAll(".renewable-trend-series-group").forEach((scope) => {
    const hasVisibleDevice = Array.from(scope.querySelectorAll(".renewable-trend-series-device"))
      .some((device) => !device.hidden);
    scope.hidden = !hasVisibleDevice;
    if (hasVisibleDevice && filterActive) scope.open = true;
  });

  const empty = $("renewableTrendSeriesEmpty");
  if (empty) {
    empty.textContent = filterActive ? "没有匹配的曲线" : "暂无可用曲线";
    empty.hidden = visibleCount > 0;
  }
}

function renderRenewableTrendSeriesAvailability(metrics = {}) {
  renderRenewableTrendSeriesTree();
  const chartKey = "renewableTrend";
  const items = Array.from(document.querySelectorAll(".renewable-trend-series-item"));
  const availableInputs = [];
  items.forEach((item) => {
    const group = item.dataset.renewableSeriesGroup || "";
    const available = renewableMetricGroupAvailable(metrics, group);
    const input = item.querySelector(`input[data-chart-toggle="${chartKey}"]`);
    if (!input) return;
    input.disabled = !available;
    input.checked = !isChartSeriesHidden(chartKey, input.dataset.chartSeries || "");
    item.classList.toggle("is-hidden", !input.checked);
    item.classList.toggle(
      "is-selected",
      selectedChartSeriesKey(chartKey) === (input.dataset.chartSeries || ""),
    );
    if (available) availableInputs.push(input);
  });
  const selectedCount = availableInputs.filter((input) => input.checked).length;
  const summary = $("renewableTrendSeriesSummary");
  if (summary) summary.textContent = `${selectedCount} / ${availableInputs.length}`;
  applyRenewableTrendSeriesFilters(metrics);
}

function renewableTrendAxisScale(values = [], series = [], unit = "") {
  const numericValues = values
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  const onlySoc = unit === "%" && series.length > 0 && series.every((item) => item.style === "soc");
  if (onlySoc) return { min: 0, max: 100, tickSuffix: "%" };
  const includeZero = unit === "kW";
  if (!numericValues.length) {
    return includeZero
      ? { min: -1, max: 1, tickSuffix: "" }
      : { min: 0, max: 1, tickSuffix: unit === "%" ? "%" : "" };
  }
  let minimum = Math.min(...numericValues);
  let maximum = Math.max(...numericValues);
  if (Math.abs(maximum - minimum) < 1e-9) {
    const expansion = Math.max(Math.abs(maximum) * 0.08, includeZero ? 1 : 0.1);
    minimum -= expansion;
    maximum += expansion;
  }
  if (includeZero) {
    minimum = Math.min(0, minimum);
    maximum = Math.max(0, maximum);
  }
  const padding = Math.max((maximum - minimum) * 0.08, includeZero ? 1 : 0.01);
  minimum = !includeZero && minimum >= 0 ? Math.max(0, minimum - padding) : minimum - padding;
  maximum += padding;
  if (Math.abs(maximum - minimum) < 1e-9) maximum = minimum + 1;
  return { min: minimum, max: maximum, tickSuffix: unit === "%" ? "%" : "" };
}

function renewableTrendAxisGroups(points = [], visibleSeries = [], selectedSeriesKey = "") {
  const grouped = { left: [], right: [] };
  const byAxisKey = new Map();
  visibleSeries.forEach((series) => {
    const side = series.axis === "right" ? "right" : "left";
    const unit = String(series.unit || "数值").trim() || "数值";
    const key = `${side}|${unit}`;
    let group = byAxisKey.get(key);
    if (!group) {
      group = { key, side, unit, series: [] };
      byAxisKey.set(key, group);
      grouped[side].push(group);
    }
    group.series.push(series);
  });
  ["left", "right"].forEach((side) => {
    grouped[side].forEach((group) => {
      const values = points.flatMap((point) => group.series.map((series) => {
        const rawValue = point?.[series.field];
        return rawValue === null || rawValue === undefined || rawValue === ""
          ? Number.NaN
          : Number(rawValue);
      }))
        .filter((value) => Number.isFinite(value));
      const scale = renewableTrendAxisScale(values, group.series, group.unit);
      const selectedSeries = group.series.find((series) => series.key === selectedSeriesKey);
      Object.assign(group, scale, {
        values,
        seriesKeys: group.series.map((series) => series.key),
        active: Boolean(selectedSeries),
        color: selectedSeries?.color || group.series[0]?.color || "#63717a",
      });
    });
  });
  return grouped;
}

function renewableTrendChartLayout(leftAxisCount = 0, rightAxisCount = 0) {
  const axisSlot = 58;
  const edgePadding = 14;
  const left = leftAxisCount > 0 ? edgePadding + leftAxisCount * axisSlot : 24;
  const right = rightAxisCount > 0 ? edgePadding + rightAxisCount * axisSlot : 24;
  const minPlotWidth = 280;
  return {
    axisSlot,
    left,
    right,
    top: 30,
    bottom: 38,
    minCanvasWidth: Math.max(640, left + right + minPlotWidth),
  };
}

function renewableTrendAxisY(axis, value, top, plotHeight) {
  const span = Math.max(1e-9, axis.max - axis.min);
  const normalized = (clamp(value, axis.min, axis.max) - axis.min) / span;
  return top + plotHeight - normalized * plotHeight;
}

function drawRenewableTrendAxes(ctx, axisGroups, plotBounds, ratio) {
  const { left, right, top, plotHeight, axisSlot } = plotBounds;
  const maxAxisOffset = (side) => Math.max(0, ((axisGroups[side] || []).length - 1) * axisSlot);
  ["left", "right"].forEach((side) => {
    (axisGroups[side] || []).forEach((axis, index) => {
      const direction = side === "left" ? -1 : 1;
      const axisX = side === "left"
        ? left - maxAxisOffset(side) + index * axisSlot
        : right + maxAxisOffset(side) - index * axisSlot;
      const axisColor = axis.active ? axis.color : "#829198";
      ctx.save();
      ctx.globalAlpha = axis.active ? 1 : 0.58;
      ctx.strokeStyle = axisColor;
      ctx.fillStyle = axisColor;
      ctx.lineWidth = (axis.active ? 1.8 : 1) * ratio;
      ctx.beginPath();
      ctx.moveTo(axisX, top);
      ctx.lineTo(axisX, top + plotHeight);
      ctx.stroke();
      ctx.font = `${axis.active ? "700 " : ""}${10 * ratio}px Consolas, Microsoft YaHei, Arial`;
      ctx.textAlign = side === "left" ? "right" : "left";
      ctx.fillText(axis.unit, axisX + direction * 6 * ratio, top - 13 * ratio);
      for (let tickIndex = 0; tickIndex <= 4; tickIndex += 1) {
        const fraction = tickIndex / 4;
        const y = top + plotHeight * fraction;
        const value = axis.max - (axis.max - axis.min) * fraction;
        ctx.beginPath();
        ctx.moveTo(axisX, y);
        ctx.lineTo(axisX + direction * 5 * ratio, y);
        ctx.stroke();
        ctx.fillText(
          `${formatNumber(value)}${axis.tickSuffix}`,
          axisX + direction * 8 * ratio,
          y + 4 * ratio,
        );
      }
      ctx.restore();
    });
  });
}

function renewableTrendAxisSummary(axisGroups = { left: [], right: [] }) {
  const describe = (side) => (axisGroups[side] || []).map((axis) => axis.unit).join("、") || "无";
  const active = [...(axisGroups.left || []), ...(axisGroups.right || [])].find((axis) => axis.active);
  const activeText = active ? ` · 当前${active.side === "left" ? "左" : "右"}轴 ${active.unit}` : "";
  return `左轴 ${describe("left")} · 右轴 ${describe("right")}${activeText}`;
}

function renderRenewableTrendLegend(selectedSeries = []) {
  const legend = $("renewableTrendLegend");
  if (!legend) return;
  const seriesKeys = selectedSeries.map((series) => series.key).join("|");
  if (legend.dataset.seriesKeys !== seriesKeys) {
    const fragment = document.createDocumentFragment();
    selectedSeries.forEach((series) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "renewable-trend-inline-legend-item";
      item.dataset.chartToggle = "renewableTrend";
      item.dataset.chartSeries = series.key;
      item.dataset.chartLegendLabel = series.label;
      item.dataset.chartLegendVisibility = "true";
      item.style.setProperty("--renewable-series-color", series.color || "#23854a");
      const swatch = document.createElement("i");
      swatch.className = `renewable-trend-inline-legend-swatch${series.style ? ` is-${series.style}` : ""}`;
      swatch.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.textContent = series.label;
      item.append(swatch, label);
      fragment.appendChild(item);
    });
    legend.replaceChildren(fragment);
    legend.dataset.seriesKeys = seriesKeys;
  }
  legend.hidden = !selectedSeries.length;
  syncChartLegendButtons("renewableTrend");
}

function drawRenewableTrendChart() {
  const canvas = $("renewableTrendChart");
  if (!canvas) return;
  const chartKey = "renewableTrend";
  const range = renewableTrendWindowRange();
  syncChartPeriodNavigation("renewableTrend", range);
  const points = renewableTrendWindowPoints(range);
  ensureRenewableTrendSeriesSelection(RENEWABLE_TREND_SERIES_DEFS);
  const metrics = state.renewableControl.lastPlan?.metrics || {};
  const availableSeries = RENEWABLE_TREND_SERIES_DEFS.filter((series) => renewableTrendSeriesAvailable(series, metrics));
  const selectedSeries = visibleChartSeries(chartKey, availableSeries);
  const visibleSeries = visibleChartLegendSeries(chartKey, selectedSeries);
  const requestedSeriesKey = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const selectedSeriesKey = visibleSeries.some((series) => series.key === requestedSeriesKey)
    ? requestedSeriesKey
    : visibleSeries[0]?.key || "";
  if (selectedSeriesKey && requestedSeriesKey !== selectedSeriesKey) {
    state.chartSeriesSelected = { ...(state.chartSeriesSelected || {}), [chartKey]: selectedSeriesKey };
  }
  const axisGroups = renewableTrendAxisGroups(points, visibleSeries, selectedSeriesKey);
  const layout = renewableTrendChartLayout(axisGroups.left.length, axisGroups.right.length);
  canvas.style.minWidth = `${layout.minCanvasWidth}px`;
  const ctx = canvas.getContext("2d");
  const { width, height, ratio } = resizeCanvas(canvas);
  const palette = chartThemePalette();
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, width, height);

  const left = layout.left * ratio;
  const right = layout.right * ratio;
  const top = layout.top * ratio;
  const bottom = layout.bottom * ratio;
  const plotWidth = Math.max(1, width - left - right);
  const plotHeight = Math.max(1, height - top - bottom);
  const plot = { left, right, top, bottom };
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };

  renderRenewableTrendLegend(selectedSeries);
  renderRenewableTrendSeriesAvailability(metrics);

  for (let index = 0; index <= 4; index += 1) {
    const fraction = index / 4;
    const y = top + plotHeight * fraction;
    ctx.strokeStyle = index === 4 ? palette.axis : palette.grid;
    ctx.lineWidth = 1 * ratio;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
  }
  drawRenewableTrendAxes(ctx, axisGroups, {
    left,
    right: width - right,
    top,
    plotHeight,
    axisSlot: layout.axisSlot * ratio,
  }, ratio);

  const xTicks = measurementTraceAxisTicks(range, plotWidth / ratio);
  xTicks.forEach((minute, tickIndex) => {
    const x = left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
    ctx.strokeStyle = tickIndex === xTicks.length - 1 ? "#c9d6dc" : "#edf2f4";
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotHeight);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.font = `${11 * ratio}px Consolas, Microsoft YaHei, Arial`;
    ctx.textAlign = tickIndex === xTicks.length - 1 ? "right" : "left";
    const textOffset = tickIndex === 0 || tickIndex === xTicks.length - 1 ? 0 : 4 * ratio;
    ctx.fillText(
      measurementTraceTimeLabel(minute, range, tickIndex, xTicks.length - 1),
      x + textOffset,
      height - 11 * ratio,
    );
  });

  const summary = $("renewableTrendSummary");
  if (summary) {
    const summaryText = `${traceWindowDataPointCount(points)} 点 · ${renewableTrendAxisSummary(axisGroups)}`;
    summary.textContent = summaryText;
    summary.title = summaryText;
  }
  if (!points.length || !visibleSeries.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = "#63717a";
    ctx.font = `${13 * ratio}px Microsoft YaHei, Arial`;
    ctx.textAlign = "center";
    const emptyText = !selectedSeries.length
      ? "未选择曲线"
      : !visibleSeries.length
        ? "图例已隐藏全部曲线"
        : "暂无综合趋势数据";
    ctx.fillText(emptyText, width / 2, height / 2);
    return;
  }

  const xForMinute = (minute) => left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
  const axisBySeriesKey = new Map();
  [...axisGroups.left, ...axisGroups.right].forEach((axis) => {
    axis.seriesKeys.forEach((seriesKey) => axisBySeriesKey.set(seriesKey, axis));
  });
  const hitData = [];
  visibleSeries.forEach((series) => {
    const seriesAxis = axisBySeriesKey.get(series.key);
    if (!seriesAxis) return;
    const sampled = sampleCurvePointsForCanvas(
      points.map((point) => Number.isFinite(point[series.field]) ? point[series.field] : Number.NaN),
      plotWidth / ratio,
      1.4,
    );
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = (series.key === selectedSeriesKey ? 3.2 : 2.2) * ratio;
    const dashPattern = Array.isArray(series.dashPattern)
      ? series.dashPattern.map((value) => value * ratio)
      : series.dashed
        ? [7 * ratio, 5 * ratio]
        : [];
    ctx.setLineDash(dashPattern);
    ctx.beginPath();
    let started = false;
    let previousY = Number.NaN;
    sampled.forEach(({ index, value }) => {
      if (!Number.isFinite(value)) return;
      const point = points[index];
      if (!point) return;
      const x = xForMinute(point.minute);
      const y = renewableTrendAxisY(seriesAxis, value, top, plotHeight);
      pixelPoints.push({ x, y, minute: point.minute, time: point.time, value });
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else if (series.style === "target") {
        ctx.lineTo(x, previousY);
        if (Math.abs(y - previousY) > 1e-9) ctx.lineTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
      previousY = y;
    });
    if (started) ctx.stroke();
    ctx.setLineDash([]);
    if (pixelPoints.length === 1) {
      ctx.fillStyle = series.color;
      ctx.beginPath();
      ctx.arc(pixelPoints[0].x, pixelPoints[0].y, 3.5 * ratio, 0, Math.PI * 2);
      ctx.fill();
    }
    hitData.push({ ...series, points: pixelPoints });
  });
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    ratio,
    maxSeries: 10,
    inlineSeriesLabels: true,
    timeLabel: (point) => measurementTracePointTimeLabel(point, range),
    valueFormatter: formatNumber,
  });
}

function renewableMetricTotal(metrics = {}, keys = []) {
  const values = keys
    .map((key) => metrics?.[key])
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
}

function renewableMetricValue(metrics = {}, key = "", fallbackKeys = []) {
  const raw = metrics?.[key];
  if (raw !== null && raw !== undefined && raw !== "") {
    const value = Number(raw);
    if (Number.isFinite(value)) return value;
  }
  return renewableMetricTotal(metrics, fallbackKeys);
}

function renewableMetricPowerText(value) {
  return Number.isFinite(value) ? formatNumber(value) : "--";
}

function renewableMetricNumberText(value) {
  return Number.isFinite(value) ? formatNumber(value) : "--";
}

function renewableMetricSocText(value) {
  return Number.isFinite(value) ? formatOverviewNumber(value * 100) : "--";
}

function renewableStorageUnavailableMetricText(metrics = {}, group = "") {
  const onlineCount = renewableMetricGroupCount(metrics, group);
  if (onlineCount !== null && onlineCount > 0) return "";
  const configuredCount = renewableMetricGroupConfiguredCount(metrics, group);
  if (configuredCount === 0) return "无此类设备";
  if (configuredCount !== null && configuredCount > 0 && onlineCount === 0) return "无运行设备";
  return onlineCount === 0 ? "无设备" : "";
}

function renewableStoragePowerMetricText(value, metrics = {}, group = "") {
  return renewableStorageUnavailableMetricText(metrics, group) || renewableMetricPowerText(value);
}

function renewableStorageSocMetricText(value, metrics = {}, group = "") {
  return renewableStorageUnavailableMetricText(metrics, group) || renewableMetricSocText(value);
}

function populateRenewableControlParameters(control = state.renewableControl) {
  const periodInput = $("renewableControlPeriod");
  if (periodInput) periodInput.value = String(control.intervalSeconds || 2);
  const hydrogenClosedLoopInput = $("hydrogenClosedLoopEnabled");
  if (hydrogenClosedLoopInput && document.activeElement !== hydrogenClosedLoopInput) {
    hydrogenClosedLoopInput.checked = Boolean(control.hydrogenClosedLoopEnabled);
  }
  syncRenewableControlPeriodConstraints();
  const ratioInputs = {
    renewableStepRatio: control.stepCoefficient,
    storageStepRatio: control.storageStepRatio,
    storageSocCorrectionStepScale: control.storageSocCorrectionStepScale,
    gridFormingStorageProtectionRatio: control.gridFormingStorageProtectionRatio,
    dieselPowerProtectionRatio: control.dieselPowerProtectionRatio,
    socDeadband: control.socDeadband,
    hydrogenPressureDeadbandRatio: control.hydrogenPressureDeadbandRatio,
    electrolyzerPowerMinRatio: control.electrolyzerPowerMinRatio,
    electrolyzerPowerMaxRatio: control.electrolyzerPowerMaxRatio,
    electrolyzerPowerDeadbandRatio: control.electrolyzerPowerDeadbandRatio,
    electrolyzerPowerStepRatio: control.electrolyzerPowerStepRatio,
    electrolyzerDieselPowerLimitRatio: control.electrolyzerDieselPowerLimitRatio,
    electrolyzerDieselPowerDeadbandRatio: control.electrolyzerDieselPowerDeadbandRatio,
    electrolyzerDieselPowerStopMaximumRatio: control.electrolyzerDieselPowerStopMaximumRatio,
    electrolyzerStorageSocStartMinimum: control.electrolyzerStorageSocStartMinimum,
    electrolyzerStorageSocStopMaximum: control.electrolyzerStorageSocStopMaximum,
    electrolyzerHydrogenStorageSocStopMinimum: control.electrolyzerHydrogenStorageSocStopMinimum,
    fuelCellStorageSocLimit: control.fuelCellStorageSocLimit,
    fuelCellHydrogenStorageSocUpperLimit: control.fuelCellHydrogenStorageSocUpperLimit,
    fuelCellHydrogenStorageSocLowerLimit: control.fuelCellHydrogenStorageSocLowerLimit,
    fuelCellPowerMinRatio: control.fuelCellPowerMinRatio,
    fuelCellPowerMaxRatio: control.fuelCellPowerMaxRatio,
    fuelCellPowerDeadbandRatio: control.fuelCellPowerDeadbandRatio,
    fuelCellPowerStepRatio: control.fuelCellPowerStepRatio,
    fuelCellDieselPowerLimitRatio: control.fuelCellDieselPowerLimitRatio,
    fuelCellDieselPowerStopMinimumRatio: control.fuelCellDieselPowerStopMinimumRatio,
  };
  Object.entries(ratioInputs).forEach(([id, value]) => {
    const input = $(id);
    if (input) {
      input.value = String(Number((Number(value || 0) * 100).toFixed(6)));
    }
  });
  const commandValidInput = $("renewableCommandValidMinutes");
  if (commandValidInput) commandValidInput.value = String(control.commandValidMinutes || 120);
  const numericInputs = {
    optimizationRenewableCurtailmentWeight: control.optimizationRenewableCurtailmentWeight,
    optimizationDieselOutputWeight: control.optimizationDieselOutputWeight,
    optimizationCurtailmentSquareWeight: control.optimizationCurtailmentSquareWeight,
    optimizationSourceStorageAdjustmentSquareWeight: control.optimizationSourceStorageAdjustmentSquareWeight,
    optimizationBalanceDeltaSquareWeight: control.optimizationBalanceDeltaSquareWeight,
    optimizationBalanceDeltaWarningKw: control.optimizationBalanceDeltaWarningKw,
    optimizationBalanceToleranceKw: control.optimizationBalanceToleranceKw,
    optimizationBoundToleranceKw: control.optimizationBoundToleranceKw,
    optimizationFtol: control.optimizationFtol,
    optimizationMaxIterations: control.optimizationMaxIterations,
  };
  Object.entries(numericInputs).forEach(([id, value]) => {
    const input = $(id);
    if (input) setSelectNumericValue(input, value ?? "");
  });
  const presetSelect = $("renewableControlPreset");
  if (presetSelect) presetSelect.value = detectRenewableControlPreset();
  state.renewableParametersDirty = false;
}

const RENEWABLE_CONTROL_PRESETS = Object.freeze({
  standard: Object.freeze({
    label: "标准均衡（默认）",
    values: {
      renewableControlPeriod: 2,
      renewableStepRatio: 3,
      storageStepRatio: 3,
      storageSocCorrectionStepScale: 20,
      gridFormingStorageProtectionRatio: 5,
      dieselPowerProtectionRatio: 3,
      socDeadband: 5,
      optimizationRenewableCurtailmentWeight: 1,
      optimizationDieselOutputWeight: 1,
      optimizationMaxIterations: 100,
    },
  }),
  aggressive_renewable: Object.freeze({
    label: "新能源积极消纳",
    values: {
      renewableControlPeriod: 2,
      renewableStepRatio: 5,
      storageStepRatio: 5,
      storageSocCorrectionStepScale: 25,
      gridFormingStorageProtectionRatio: 4,
      dieselPowerProtectionRatio: 3,
      socDeadband: 4,
      optimizationRenewableCurtailmentWeight: 2,
      optimizationDieselOutputWeight: 1.5,
      optimizationMaxIterations: 100,
    },
  }),
  conservative_protection: Object.freeze({
    label: "储能/氢能保守保护",
    values: {
      renewableControlPeriod: 3,
      renewableStepRatio: 2,
      storageStepRatio: 2,
      storageSocCorrectionStepScale: 30,
      gridFormingStorageProtectionRatio: 10,
      dieselPowerProtectionRatio: 5,
      socDeadband: 8,
      optimizationRenewableCurtailmentWeight: 1,
      optimizationDieselOutputWeight: 0.8,
      optimizationMaxIterations: 100,
    },
  }),
});

function detectRenewableControlPreset() {
  for (const [presetKey, preset] of Object.entries(RENEWABLE_CONTROL_PRESETS)) {
    const allMatched = Object.entries(preset.values).every(([id, expected]) => {
      const node = $(id);
      if (!node) return true;
      return Math.abs(Number(node.value) - Number(expected)) <= 1e-6;
    });
    if (allMatched) return presetKey;
  }
  return "custom";
}

function applyRenewableControlPreset(presetKey) {
  const preset = RENEWABLE_CONTROL_PRESETS[presetKey];
  if (!preset) return;
  state.renewablePresetApplying = true;
  try {
    Object.entries(preset.values).forEach(([id, value]) => {
      const node = $(id);
      if (!node) return;
      setSelectNumericValue(node, value);
    });
    syncRenewableControlPeriodConstraints();
    state.renewableParametersDirty = true;
    setRenewableControlParametersMessage(`已填充「${preset.label}」方案，点击保存生效。`, "ok");
  } finally {
    state.renewablePresetApplying = false;
  }
}

function openRenewableControlParametersDialog() {
  const dialog = $("renewableControlParametersDialog");
  if (dialog && !dialog.open) {
    populateRenewableControlParameters();
    renderRenewableControlParameterTabs("runtime");
    setRenewableControlParametersMessage();
    dialog.showModal();
  }
}

function setRenewableControlParametersMessage(message = "", status = "") {
  const node = $("renewableControlParametersMessage");
  if (!node) return;
  node.textContent = message || "参数修改后点击保存生效。";
  if (status) node.dataset.state = status;
  else delete node.dataset.state;
}

function closeRenewableControlParametersDialog() {
  const dialog = $("renewableControlParametersDialog");
  if (dialog?.open) {
    state.renewableParametersDirty = false;
    dialog.close();
  }
}

function renewableForegroundActionPending(control = state.renewableControl) {
  return Boolean(control?.actionActive);
}

function renderRenewableControl(snapshot = state.snapshot || {}) {
  state.frontendDiagnostics.renewableRenderCount += 1;
  const control = state.renewableControl;
  const actionPending = renewableForegroundActionPending(control);
  const receiveReady = Boolean(
    state.receiveMode
    && control.receiveActive
    && control.canRun
    && !control.controlFrozen
  );
  const loopMode = renewableLoopMode(control);
  const loopModeLabel = renewableLoopModeLabel(loopMode);
  const plan = control.lastPlan;
  const button = $("renewableAutoToggle");
  if (!button) return;
  const sendOnce = $("renewableSendOnce");
  const stateNode = $("renewableControlState");
  const summary = $("renewableCommandSummary");
  const lastActionLabel = $("renewableLastActionLabel");
  const hasDecisionSnapshot = Boolean(plan);
  button.textContent = control.desiredEnabled ? "停止实时控制" : "启动实时控制";
  button.classList.toggle("is-running", control.enabled);
  button.classList.toggle("is-pending", control.resumePending);
  button.disabled = actionPending || (!receiveReady && !control.desiredEnabled);
  button.title = !receiveReady && !control.desiredEnabled ? "请先启动接收" : "";
  if (sendOnce) {
    sendOnce.disabled = actionPending || !receiveReady;
    sendOnce.title = !receiveReady ? "请先启动接收" : "";
    sendOnce.textContent = loopMode === "closed" ? "单次计算下发" : "单次计算";
  }
  document.querySelectorAll("[data-renewable-loop-mode]").forEach((modeButton) => {
    const active = modeButton.dataset.renewableLoopMode === loopMode;
    modeButton.classList.toggle("is-active", active);
    modeButton.setAttribute("aria-pressed", String(active));
    modeButton.disabled = actionPending;
  });
  const periodInput = $("renewableControlPeriod");
  const parameterDialogOpen = Boolean($("renewableControlParametersDialog")?.open);
  if (!parameterDialogOpen && periodInput && document.activeElement !== periodInput) {
    periodInput.value = String(control.intervalSeconds || 2);
    syncRenewableControlPeriodConstraints();
  }
  const ratioInputs = {
    renewableStepRatio: control.stepCoefficient,
    storageStepRatio: control.storageStepRatio,
    storageSocCorrectionStepScale: control.storageSocCorrectionStepScale,
    gridFormingStorageProtectionRatio: control.gridFormingStorageProtectionRatio,
    dieselPowerProtectionRatio: control.dieselPowerProtectionRatio,
    socDeadband: control.socDeadband,
    hydrogenPressureDeadbandRatio: control.hydrogenPressureDeadbandRatio,
    electrolyzerPowerMinRatio: control.electrolyzerPowerMinRatio,
    electrolyzerPowerMaxRatio: control.electrolyzerPowerMaxRatio,
    electrolyzerPowerDeadbandRatio: control.electrolyzerPowerDeadbandRatio,
    electrolyzerPowerStepRatio: control.electrolyzerPowerStepRatio,
    electrolyzerDieselPowerLimitRatio: control.electrolyzerDieselPowerLimitRatio,
    electrolyzerDieselPowerDeadbandRatio: control.electrolyzerDieselPowerDeadbandRatio,
    electrolyzerDieselPowerStopMaximumRatio: control.electrolyzerDieselPowerStopMaximumRatio,
    electrolyzerStorageSocStartMinimum: control.electrolyzerStorageSocStartMinimum,
    electrolyzerStorageSocStopMaximum: control.electrolyzerStorageSocStopMaximum,
    electrolyzerHydrogenStorageSocStopMinimum: control.electrolyzerHydrogenStorageSocStopMinimum,
    fuelCellStorageSocLimit: control.fuelCellStorageSocLimit,
    fuelCellHydrogenStorageSocUpperLimit: control.fuelCellHydrogenStorageSocUpperLimit,
    fuelCellHydrogenStorageSocLowerLimit: control.fuelCellHydrogenStorageSocLowerLimit,
    fuelCellPowerMinRatio: control.fuelCellPowerMinRatio,
    fuelCellPowerMaxRatio: control.fuelCellPowerMaxRatio,
    fuelCellPowerDeadbandRatio: control.fuelCellPowerDeadbandRatio,
    fuelCellPowerStepRatio: control.fuelCellPowerStepRatio,
    fuelCellDieselPowerLimitRatio: control.fuelCellDieselPowerLimitRatio,
    fuelCellDieselPowerStopMinimumRatio: control.fuelCellDieselPowerStopMinimumRatio,
  };
  Object.entries(ratioInputs).forEach(([id, value]) => {
    const input = $(id);
    if (!parameterDialogOpen && input && document.activeElement !== input) {
      input.value = String(Number((Number(value || 0) * 100).toFixed(6)));
    }
  });
  const commandValidInput = $("renewableCommandValidMinutes");
  if (!parameterDialogOpen && commandValidInput && document.activeElement !== commandValidInput) {
    commandValidInput.value = String(control.commandValidMinutes || 120);
  }
  const numericInputs = {
    optimizationRenewableCurtailmentWeight: control.optimizationRenewableCurtailmentWeight,
    optimizationDieselOutputWeight: control.optimizationDieselOutputWeight,
    optimizationCurtailmentSquareWeight: control.optimizationCurtailmentSquareWeight,
    optimizationSourceStorageAdjustmentSquareWeight: control.optimizationSourceStorageAdjustmentSquareWeight,
    optimizationBalanceDeltaSquareWeight: control.optimizationBalanceDeltaSquareWeight,
    optimizationBalanceDeltaWarningKw: control.optimizationBalanceDeltaWarningKw,
    optimizationBalanceToleranceKw: control.optimizationBalanceToleranceKw,
    optimizationBoundToleranceKw: control.optimizationBoundToleranceKw,
    optimizationFtol: control.optimizationFtol,
    optimizationMaxIterations: control.optimizationMaxIterations,
  };
  Object.entries(numericInputs).forEach(([id, value]) => {
    const input = $(id);
    if (!parameterDialogOpen && input && document.activeElement !== input) {
      input.value = String(value ?? "");
    }
  });
  [
    periodInput,
    commandValidInput,
    ...Object.keys(ratioInputs).map((id) => $(id)),
    ...Object.keys(numericInputs).map((id) => $(id)),
  ].forEach((input) => {
    if (input) input.disabled = control.actionActive;
  });
  const storagePowerDeratingButton = $("storagePowerDeratingButton");
  if (storagePowerDeratingButton) storagePowerDeratingButton.disabled = control.actionActive;
  const saveControlParametersButton = $("saveRenewableControlParameters");
  if (saveControlParametersButton) saveControlParametersButton.disabled = control.actionActive;
  const controlParametersButton = $("renewableControlParametersButton");
  if (controlParametersButton) controlParametersButton.disabled = control.actionActive;
  if (lastActionLabel) lastActionLabel.textContent = loopMode === "closed" ? "最近下发" : "最近计算";
  if (stateNode) {
    const backendRunState = control.runState || (
      control.enabled ? "running" : control.desiredEnabled ? "resume_pending" : "stopped"
    );
    stateNode.dataset.state = backendRunState;
    stateNode.textContent = backendRunState === "running"
      ? `${loopModeLabel}实时控制运行中`
      : backendRunState === "frozen"
        ? "模拟台暂停，学员台已冻结"
      : backendRunState === "resume_pending"
        ? "等待接收后恢复"
        : "已停止";
  }
  const metrics = renewableMetricsWithCommandRowCounts(plan);
  const planWeather = plan?.weather || {};
  const snapshotWeather = currentWeatherLoad(snapshot);
  const observedWindSpeed = optionalNumber(planWeather.observedWindSpeed) ?? snapshotWeather.windSpeed;
  const observedSolarIrradiance = optionalNumber(planWeather.observedSolarIrradiance) ?? snapshotWeather.solarIrradiance;
  const storagePowerText = (value, group) => renewableStoragePowerMetricText(value, metrics, group);
  const storageSocText = (value, group) => renewableStorageSocMetricText(value, metrics, group);
  const metricText = {
    renewableAcCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "acRenewableCurrentKw", ["acWindCurrentKw", "acPvCurrentKw"])),
    renewableAcTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "acRenewableTargetKw", ["acWindTargetKw", "acPvTargetKw"])),
    renewableAcMaxAvailableKw: renewableMetricPowerText(metrics.acRenewableMaxAvailableKw),
    renewableAcWindCurrentKw: renewableMetricPowerText(metrics.acWindCurrentKw),
    renewableAcWindTargetKw: renewableMetricPowerText(metrics.acWindTargetKw),
    renewableAcWindMaxAvailableKw: renewableMetricPowerText(metrics.acWindMaxAvailableKw),
    renewableAcPvCurrentKw: renewableMetricPowerText(metrics.acPvCurrentKw),
    renewableAcPvTargetKw: renewableMetricPowerText(metrics.acPvTargetKw),
    renewableAcPvMaxAvailableKw: renewableMetricPowerText(metrics.acPvMaxAvailableKw),
    renewableAcStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "acStorageCurrentKw", [
        "acGridFollowingStorageCurrentKw",
        "acGridFormingStorageCurrentKw",
      ]),
      "ac-storage",
    ),
    renewableAcStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "acStorageTargetKw", [
        "acGridFollowingStorageTargetKw",
        "acGridFormingStorageTargetKw",
      ]),
      "ac-storage",
    ),
    renewableAcStorageSoc: storageSocText(metrics.acStorageSoc, "ac-storage"),
    renewableDcCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "dcRenewableCurrentKw", ["dcWindCurrentKw", "dcPvCurrentKw"])),
    renewableDcTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "dcRenewableTargetKw", ["dcWindTargetKw", "dcPvTargetKw"])),
    renewableDcMaxAvailableKw: renewableMetricPowerText(metrics.dcRenewableMaxAvailableKw),
    renewableDcWindCurrentKw: renewableMetricPowerText(metrics.dcWindCurrentKw),
    renewableDcWindTargetKw: renewableMetricPowerText(metrics.dcWindTargetKw),
    renewableDcWindMaxAvailableKw: renewableMetricPowerText(metrics.dcWindMaxAvailableKw),
    renewableDcPvCurrentKw: renewableMetricPowerText(metrics.dcPvCurrentKw),
    renewableDcPvTargetKw: renewableMetricPowerText(metrics.dcPvTargetKw),
    renewableDcPvMaxAvailableKw: renewableMetricPowerText(metrics.dcPvMaxAvailableKw),
    renewableDcStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "dcStorageCurrentKw", [
        "dcGridFollowingStorageCurrentKw",
        "dcGridFormingStorageCurrentKw",
      ]),
      "dc-storage",
    ),
    renewableDcStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "dcStorageTargetKw", [
        "dcGridFollowingStorageTargetKw",
        "dcGridFormingStorageTargetKw",
      ]),
      "dc-storage",
    ),
    renewableDcStorageSoc: storageSocText(metrics.dcStorageSoc, "dc-storage"),
    renewableAcGridFollowingStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "acGridFollowingStorageCurrentKw", ["acGridStorageCurrentKw"]),
      "ac-grid-following-storage",
    ),
    renewableAcGridFollowingStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "acGridFollowingStorageTargetKw", ["acGridStorageTargetKw"]),
      "ac-grid-following-storage",
    ),
    renewableAcGridFollowingStorageSoc: storageSocText(
      renewableMetricValue(metrics, "acGridFollowingStorageSoc", ["acGridStorageSoc"]),
      "ac-grid-following-storage",
    ),
    renewableDcGridFollowingStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "dcGridFollowingStorageCurrentKw", ["dcGridStorageCurrentKw"]),
      "dc-grid-following-storage",
    ),
    renewableDcGridFollowingStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "dcGridFollowingStorageTargetKw", ["dcGridStorageTargetKw"]),
      "dc-grid-following-storage",
    ),
    renewableDcGridFollowingStorageSoc: storageSocText(
      renewableMetricValue(metrics, "dcGridFollowingStorageSoc", ["dcGridStorageSoc"]),
      "dc-grid-following-storage",
    ),
    renewableAcGridFormingStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "acGridFormingStorageCurrentKw", ["acBalanceStorageCurrentKw"]),
      "ac-grid-forming-storage",
    ),
    renewableAcGridFormingStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "acGridFormingStorageTargetKw", ["acBalanceStorageTargetKw"]),
      "ac-grid-forming-storage",
    ),
    renewableAcGridFormingStorageSoc: storageSocText(
      renewableMetricValue(metrics, "acGridFormingStorageSoc", ["acBalanceStorageSoc"]),
      "ac-grid-forming-storage",
    ),
    renewableDcGridFormingStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "dcGridFormingStorageCurrentKw", ["dcBalanceStorageCurrentKw"]),
      "dc-grid-forming-storage",
    ),
    renewableDcGridFormingStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "dcGridFormingStorageTargetKw", ["dcBalanceStorageTargetKw"]),
      "dc-grid-forming-storage",
    ),
    renewableDcGridFormingStorageSoc: storageSocText(
      renewableMetricValue(metrics, "dcGridFormingStorageSoc", ["dcBalanceStorageSoc"]),
      "dc-grid-forming-storage",
    ),
    renewableAcDieselCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "acDieselCurrentKw", ["dieselCurrentKw"])),
    renewableAcDieselMinKw: renewableMetricPowerText(renewableMetricValue(metrics, "acDieselMinKw", ["dieselMinKw"])),
    renewableAcDieselTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "acDieselTargetKw", ["dieselTargetKw"])),
    renewableDcDieselCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "dcDieselCurrentKw")),
    renewableDcDieselMinKw: renewableMetricPowerText(renewableMetricValue(metrics, "dcDieselMinKw")),
    renewableDcDieselTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "dcDieselTargetKw")),
    renewableAcLoadKw: renewableMetricPowerText(metrics.acLoadKw),
    renewableDcLoadKw: renewableMetricPowerText(metrics.dcLoadKw),
    renewableTotalCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalRenewableCurrentKw", ["renewableCurrentKw"])),
    renewableTotalTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalRenewableTargetKw", ["renewableTarget"])),
    renewableTotalMaxAvailableKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalRenewableMaxAvailableKw", ["renewableMaxAvailableKw"])),
    renewableTotalWindCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalWindCurrentKw", ["acWindCurrentKw", "dcWindCurrentKw"])),
    renewableTotalWindTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalWindTargetKw", ["acWindTargetKw", "dcWindTargetKw"])),
    renewableTotalWindMaxAvailableKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalWindMaxAvailableKw", ["windMaxAvailableKw"])),
    renewableTotalPvCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalPvCurrentKw", ["acPvCurrentKw", "dcPvCurrentKw"])),
    renewableTotalPvTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalPvTargetKw", ["acPvTargetKw", "dcPvTargetKw"])),
    renewableTotalPvMaxAvailableKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalPvMaxAvailableKw", ["pvMaxAvailableKw"])),
    renewableTotalStorageCurrentKw: storagePowerText(
      renewableMetricValue(metrics, "totalStorageCurrentKw", ["acStorageCurrentKw", "dcStorageCurrentKw"]),
      "system-storage",
    ),
    renewableTotalStorageTargetKw: storagePowerText(
      renewableMetricValue(metrics, "totalStorageTargetKw", ["acStorageTargetKw", "dcStorageTargetKw"]),
      "system-storage",
    ),
    renewableTotalStorageSoc: storageSocText(metrics.totalStorageSoc, "system-storage"),
    renewableTotalGridFollowingStorageCurrentKw: storagePowerText(
      metrics.totalGridFollowingStorageCurrentKw,
      "system-grid-following-storage",
    ),
    renewableTotalGridFollowingStorageTargetKw: storagePowerText(
      metrics.totalGridFollowingStorageTargetKw,
      "system-grid-following-storage",
    ),
    renewableTotalGridFollowingStorageSoc: storageSocText(
      metrics.totalGridFollowingStorageSoc,
      "system-grid-following-storage",
    ),
    renewableTotalGridFormingStorageCurrentKw: storagePowerText(
      metrics.totalGridFormingStorageCurrentKw,
      "system-grid-forming-storage",
    ),
    renewableTotalGridFormingStorageTargetKw: storagePowerText(
      metrics.totalGridFormingStorageTargetKw,
      "system-grid-forming-storage",
    ),
    renewableTotalGridFormingStorageSoc: storageSocText(
      metrics.totalGridFormingStorageSoc,
      "system-grid-forming-storage",
    ),
    renewableTotalDieselCurrentKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalDieselCurrentKw", ["dieselCurrentKw"])),
    renewableTotalDieselMinKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalDieselMinKw", ["dieselMinKw"])),
    renewableTotalDieselTargetKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalDieselTargetKw", ["dieselTargetKw"])),
    renewableTotalLoadKw: renewableMetricPowerText(renewableMetricValue(metrics, "totalLoadKw", ["loadKw"])),
    renewableAcdcCurrentKw: renewableMetricPowerText(metrics.acdcCurrentKw),
    renewableAcdcTargetKw: renewableMetricPowerText(metrics.acdcTargetKw),
    renewableElectrolyzerCurrentKw: renewableMetricPowerText(metrics.electrolyzerCurrentKw),
    renewableElectrolyzerTargetKw: renewableMetricPowerText(metrics.electrolyzerTargetKw),
    renewableElectrolyzerFlowCurrentNm3h: renewableMetricNumberText(metrics.electrolyzerFlowCurrentNm3h),
    renewableElectrolyzerFlowTargetNm3h: renewableMetricNumberText(metrics.electrolyzerFlowTargetNm3h),
    renewableFuelCellCurrentKw: renewableMetricPowerText(metrics.fuelCellCurrentKw),
    renewableFuelCellTargetKw: renewableMetricPowerText(metrics.fuelCellTargetKw),
    renewableFuelCellFlowCurrentNm3h: renewableMetricNumberText(metrics.fuelCellFlowCurrentNm3h),
    renewableFuelCellFlowTargetNm3h: renewableMetricNumberText(metrics.fuelCellFlowTargetNm3h),
    renewableHydrogenStoragePressureMpa: renewableMetricNumberText(metrics.hydrogenStoragePressureMpa),
    renewableHydrogenStoragePressureLowGuardMpa: renewableMetricNumberText(metrics.hydrogenStoragePressureLowGuardMpa),
    renewableHydrogenStoragePressureHighGuardMpa: renewableMetricNumberText(metrics.hydrogenStoragePressureHighGuardMpa),
    renewableHydrogenStorageGasQuantityNm3: renewableMetricNumberText(metrics.hydrogenStorageGasQuantityNm3),
    renewableHydrogenStorageSoc: renewableMetricSocText(metrics.hydrogenStorageSoc),
    renewableHydrogenStorageFlowNm3h: renewableMetricNumberText(metrics.hydrogenStorageFlowNm3h),
    renewableObservedWindSpeed: Number.isFinite(observedWindSpeed) ? formatNumber(observedWindSpeed) : "--",
    renewableObservedSolarIrradiance: Number.isFinite(observedSolarIrradiance) ? formatNumber(observedSolarIrradiance) : "--",
    renewableLastSent: loopMode === "closed" ? control.lastSentAt || "--" : control.lastCalculatedAt || "--",
  };
  Object.entries(metricText).forEach(([id, text]) => {
    const node = $(id);
    if (node) node.textContent = text;
  });
  renderRenewableMetricAvailability(metrics);
  const status = $("renewableControlStatus");
  if (status) {
    status.textContent = actionPending
      ? "正在提交本次新能源控制操作..."
      : !receiveReady
        ? control.resumePending
          ? control.lastStatus
          : renewablePrerequisiteStatus(control)
        : control.lastStatus;
    status.classList.toggle("is-ok", control.enabled);
    status.classList.toggle("is-warning", control.resumePending);
    status.classList.toggle("is-error", !hasDecisionSnapshot && control.enabled);
  }
  if (summary) {
    const commandCount = Number(plan?.commandCount ?? plan?.commands?.length ?? 0)
      + Number(plan?.runCommandCount ?? plan?.runCommands?.length ?? 0);
    summary.textContent = `${commandCount} 条 · ${plan?.time || "--"} · ${loopModeLabel} · ${renewableDataSourceLabel(plan?.dataQuality?.source)}`;
  }
  renderRenewableMetricTabs();
  renderRenewableDetailTabs();
  renderRenewableStrategyTabs(plan);
  const table = $("renewableCommandTable");
  if (!table) return;
  const rows = renewableStrategyRows(plan);
  if (!rows.length) {
    const tabLabel = RENEWABLE_STRATEGY_TABS[control.strategyTab]?.label || "当前分类";
    table.innerHTML = `<div class="empty-state compact">暂无${escapeHtml(tabLabel)}设备</div>`;
    return;
  }
  table.innerHTML = `
    <table class="runtime-device-table renewable-command-table">
      <thead>
        <tr>
          <th>设备名称</th>
          <th>遥调/遥控点名称</th>
          <th>接入状态</th>
          <th>当前值</th>
          <th>可用边界</th>
          <th>目标值</th>
          <th>SOC</th>
          <th>执行</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => {
          const commandable = row.online && row.commandable !== false;
          const balanceStorage = row.category.includes("平衡储能");
          const disabledReason = !row.online
            ? renewableRowStatusLabel(row)
            : row.commandable === false
              ? renewableRowStatusLabel(row)
              : balanceStorage
                ? "平衡储能仅间接调节"
                : "";
          const pointName = renewableRemoteAdjustmentPointName(row);
          const connectionText = row.connectionStatusLabel || (row.activelyConnected === false ? "当前断开" : renewableRowStatusLabel(row));
          const boundaryText = renewableRowBoundaryText(row);
          const runControl = row.commandKind === "run_status";
          const currentValue = renewableRowControlPointPower(row, row.currentKw);
          const targetValue = renewableRowControlPointPower(row, balanceStorage
            ? optionalNumber(row.projectedTargetKw)
            : optionalNumber(row.targetKw ?? row.commandKw));
          const actionDisabled = !commandable || balanceStorage;
          const previewOnly = row.dispatchEnabled === false;
          const currentText = runControl
            ? (Number(currentValue) ? "投入" : "退出")
            : Number.isFinite(currentValue) ? `${formatNumber(currentValue)} kW` : "--";
          const targetText = runControl
            ? (Number(targetValue) ? "投入" : "退出")
            : Number.isFinite(targetValue) ? `${formatNumber(targetValue)} kW` : "--";
          const executionText = previewOnly
            ? "仅预览"
            : control.loopMode === "closed"
              ? "随策略下发"
              : "开环不下发";
          return `
          <tr class="${commandable && !balanceStorage ? "" : "is-muted"}">
            <td class="renewable-topology-text" title="${escapeHtml(row.dev_name)}">${escapeHtml(row.dev_name)}</td>
            <td class="renewable-control-point" title="${escapeHtml(pointName)}">${escapeHtml(pointName)}</td>
            <td><span class="status-pill ${commandable ? "is-ok" : "is-off"}">${escapeHtml(connectionText)}</span></td>
            <td class="numeric-cell">${currentText}</td>
            <td class="numeric-cell" title="${escapeHtml(boundaryText)}">${escapeHtml(boundaryText)}</td>
            <td class="numeric-cell">${targetText}</td>
            <td class="numeric-cell">${row.soc === undefined ? "--" : formatNumber(row.soc)}</td>
            <td>${actionDisabled
              ? `<button type="button" class="renewable-row-action" disabled title="${escapeHtml(disabledReason || "不可直接下发")}">不可执行</button>`
              : `<span class="renewable-row-ready${previewOnly || control.loopMode !== "closed" ? " is-preview" : ""}">${executionText}</span>`}</td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

async function toggleRenewableAuto() {
  if (!state.renewableControl.desiredEnabled && !state.receiveMode) {
    state.renewableControl.lastStatus = "请先启动接收，再启动新能源实时控制。";
    renderRenewableControl(state.snapshot || {});
    return;
  }
  const action = state.renewableControl.desiredEnabled ? "stop" : "start";
  await runRenewableControlAction(action);
}

async function runRenewableControlOnce() {
  if (!state.receiveMode) {
    state.renewableControl.lastStatus = "请先启动接收，再执行单次计算。";
    renderRenewableControl(state.snapshot || {});
    return;
  }
  await runRenewableControlAction("run_once");
}

async function setRenewableLoopMode(mode) {
  const nextMode = mode === "closed" ? "closed" : "open";
  if (renewableLoopMode() === nextMode) {
    renderRenewableControl(state.snapshot || {});
    return;
  }
  if (nextMode === "closed") {
    const confirmed = await confirmDangerousAction({
      title: "切换为新能源闭环控制？",
      target: `当前模型：${state.activeModelId || "默认模型"}`,
      message: "启用闭环模式后，学员台将按控制周期自动向模拟台下发遥控与遥调指令。",
      confirmLabel: "确认启用闭环",
    });
    if (!confirmed) {
      renderRenewableControl(state.snapshot || {});
      return;
    }
  }
  await runRenewableControlAction("set_loop_mode", { loop_mode: nextMode });
}

async function updateRenewableSettings() {
  const periodInput = $("renewableControlPeriod");
  const intervalSeconds = toNumber(periodInput?.value, 2);
  const intervalError = renewableSimulationControlIntervalError(intervalSeconds);
  periodInput?.setCustomValidity?.(intervalError);
  if (intervalError) {
    state.renewableControl.lastStatus = intervalError;
    periodInput?.reportValidity?.();
    renderRenewableControl(state.snapshot || {});
    return null;
  }
  const commandValidMinutes = Math.max(0.1, toNumber($("renewableCommandValidMinutes")?.value, 120));
  const ratio = (id, fallbackPercent, minimumPercent = 0, maximumPercent = 100) => (
    Math.min(
      maximumPercent,
      Math.max(minimumPercent, toNumber($(id)?.value, fallbackPercent)),
    ) / 100
  );
  const powerSettings = {
    electrolyzerPowerMinRatio: ratio("electrolyzerPowerMinRatio", 20),
    electrolyzerPowerMaxRatio: ratio("electrolyzerPowerMaxRatio", 90),
    electrolyzerPowerDeadbandRatio: ratio("electrolyzerPowerDeadbandRatio", 10),
    electrolyzerPowerStepRatio: ratio("electrolyzerPowerStepRatio", 10, 0.001, 100),
    fuelCellPowerMinRatio: ratio("fuelCellPowerMinRatio", 20),
    fuelCellPowerMaxRatio: ratio("fuelCellPowerMaxRatio", 90),
    fuelCellPowerDeadbandRatio: ratio("fuelCellPowerDeadbandRatio", 10),
    fuelCellPowerStepRatio: ratio("fuelCellPowerStepRatio", 10, 0.001, 100),
    electrolyzerDieselPowerLimitRatio: ratio("electrolyzerDieselPowerLimitRatio", 35),
    electrolyzerDieselPowerStopMaximumRatio: ratio("electrolyzerDieselPowerStopMaximumRatio", 50),
    fuelCellDieselPowerLimitRatio: ratio("fuelCellDieselPowerLimitRatio", 50),
    fuelCellDieselPowerStopMinimumRatio: ratio("fuelCellDieselPowerStopMinimumRatio", 30),
  };
  const powerSettingError = [
    ["电制氢", powerSettings.electrolyzerPowerMinRatio, powerSettings.electrolyzerPowerMaxRatio, powerSettings.electrolyzerPowerDeadbandRatio],
    ["燃料电池", powerSettings.fuelCellPowerMinRatio, powerSettings.fuelCellPowerMaxRatio, powerSettings.fuelCellPowerDeadbandRatio],
  ].map(([label, minimum, maximum, deadband]) => {
    if (minimum > maximum) return `${label}功率下限不能大于上限。`;
    if (minimum + deadband > maximum) return `${label}启动功率（下限+死区）不能大于上限。`;
    return "";
  }).find(Boolean);
  if (powerSettingError) {
    state.renewableControl.lastStatus = powerSettingError;
    renderRenewableControl(state.snapshot || {});
    return null;
  }
  const dieselHysteresisError = (
    powerSettings.electrolyzerDieselPowerLimitRatio
    >= powerSettings.electrolyzerDieselPowerStopMaximumRatio
  )
    ? "电制氢启机柴发门槛必须小于停机柴发门槛。"
    : powerSettings.fuelCellDieselPowerLimitRatio
      <= powerSettings.fuelCellDieselPowerStopMinimumRatio
      ? "燃料电池启机柴发门槛必须大于停机柴发门槛。"
      : "";
  if (dieselHysteresisError) {
    state.renewableControl.lastStatus = dieselHysteresisError;
    renderRenewableControl(state.snapshot || {});
    return null;
  }
  const electrolyzerStorageSocStartMinimum = ratio("electrolyzerStorageSocStartMinimum", 70);
  const electrolyzerStorageSocStopMaximum = ratio("electrolyzerStorageSocStopMaximum", 30);
  const fuelCellHydrogenStorageSocLowerLimit = ratio("fuelCellHydrogenStorageSocLowerLimit", 20);
  const fuelCellHydrogenStorageSocUpperLimit = ratio("fuelCellHydrogenStorageSocUpperLimit", 30);
  const socSettingError = electrolyzerStorageSocStartMinimum <= electrolyzerStorageSocStopMaximum
    ? "电制氢启机SOC最小值必须大于停机SOC最大值。"
    : fuelCellHydrogenStorageSocLowerLimit > fuelCellHydrogenStorageSocUpperLimit
      ? "燃料电池停机氢SOC最大值不能大于启机氢SOC最小值。"
      : "";
  if (socSettingError) {
    state.renewableControl.lastStatus = socSettingError;
    renderRenewableControl(state.snapshot || {});
    return null;
  }
  return runRenewableControlAction("update_settings", {
    settings: {
      simulationIntervalSeconds: intervalSeconds,
      commandValidMinutes,
      largeStepThresholdKw: state.renewableControl.largeStepThresholdKw,
      renewableStepRatio: ratio("renewableStepRatio", 3),
      storageStepRatio: ratio("storageStepRatio", 3),
      storageSocCorrectionStepScale: ratio("storageSocCorrectionStepScale", 20, 10, 100),
      gridFormingStorageProtectionRatio: ratio("gridFormingStorageProtectionRatio", 5, 0, 50),
      dieselPowerProtectionRatio: ratio("dieselPowerProtectionRatio", 3, 0, 50),
      socDeadband: ratio("socDeadband", 5),
      hydrogenClosedLoopEnabled: Boolean($("hydrogenClosedLoopEnabled")?.checked),
      hydrogenPressureDeadbandRatio: ratio("hydrogenPressureDeadbandRatio", 5, 0, 50),
      electrolyzerStorageSocStartMinimum,
      electrolyzerStorageSocStopMaximum,
      electrolyzerHydrogenStorageSocStopMinimum: ratio("electrolyzerHydrogenStorageSocStopMinimum", 90),
      fuelCellStorageSocLimit: ratio("fuelCellStorageSocLimit", 30),
      fuelCellHydrogenStorageSocUpperLimit,
      fuelCellHydrogenStorageSocLowerLimit,
      ...powerSettings,
      optimizationRenewableCurtailmentWeight: Math.max(0, toNumber($("optimizationRenewableCurtailmentWeight")?.value, 1)),
      optimizationDieselOutputWeight: Math.max(0, toNumber($("optimizationDieselOutputWeight")?.value, 1)),
      optimizationCurtailmentSquareWeight: Math.max(0, toNumber($("optimizationCurtailmentSquareWeight")?.value, 0.000001)),
      optimizationSourceStorageAdjustmentSquareWeight: Math.max(0, toNumber($("optimizationSourceStorageAdjustmentSquareWeight")?.value, 0.000001)),
      optimizationBalanceDeltaSquareWeight: Math.max(0, toNumber($("optimizationBalanceDeltaSquareWeight")?.value, 10000)),
      optimizationBalanceDeltaWarningKw: Math.max(0, toNumber($("optimizationBalanceDeltaWarningKw")?.value, 1)),
      optimizationBalanceToleranceKw: Math.max(0, toNumber($("optimizationBalanceToleranceKw")?.value, 0.1)),
      optimizationBoundToleranceKw: Math.max(0, toNumber($("optimizationBoundToleranceKw")?.value, 0.1)),
      optimizationFtol: Math.max(0, toNumber($("optimizationFtol")?.value, 0.001)),
      optimizationMaxIterations: Math.max(1, Math.round(toNumber($("optimizationMaxIterations")?.value, 100))),
      storageChargeDeratingCurve: state.renewableControl.storageChargeDeratingCurve,
      storageDischargeDeratingCurve: state.renewableControl.storageDischargeDeratingCurve,
    },
  });
}

async function saveRenewableControlParameters() {
  setRenewableControlParametersMessage("正在保存控制参数...");
  const response = await updateRenewableSettings();
  if (response) {
    state.renewableParametersDirty = false;
    setRenewableControlParametersMessage(
      response.status || "控制参数已保存并生效。",
      "ok",
    );
    return;
  }
  setRenewableControlParametersMessage(
    state.renewableControl.lastStatus || "控制参数保存失败，请检查输入后重试。",
    "error",
  );
}

function storagePowerDeratingRowHtml(direction, point, index) {
  const directionLabel = direction === "charge" ? "充电" : "放电";
  return `
    <tr class="storage-power-derating-row" data-derating-direction="${direction}" data-derating-index="${index}">
      <td>
        <label class="storage-power-derating-input">
          <input type="number" min="0" max="100" step="0.1" value="${formatNumber(point.soc * 100)}" data-derating-field="soc" aria-label="${directionLabel} SOC 节点 ${index + 1}" />
          <span>%</span>
        </label>
      </td>
      <td>
        <label class="storage-power-derating-input">
          <input type="number" min="0" max="100" step="0.1" value="${formatNumber(point.powerRatio * 100)}" data-derating-field="powerRatio" aria-label="${directionLabel}功率上限节点 ${index + 1}" />
          <span>%</span>
        </label>
      </td>
    </tr>`;
}

function renderStoragePowerDeratingRows(
  chargeCurve = state.renewableControl.storageChargeDeratingCurve,
  dischargeCurve = state.renewableControl.storageDischargeDeratingCurve,
) {
  const chargeRows = $("storageChargeDeratingRows");
  const dischargeRows = $("storageDischargeDeratingRows");
  if (chargeRows) {
    chargeRows.innerHTML = normalizeStorageDeratingCurve(
      chargeCurve,
      DEFAULT_STORAGE_CHARGE_DERATING_CURVE,
      "charge",
    ).map((point, index) => storagePowerDeratingRowHtml("charge", point, index)).join("");
  }
  if (dischargeRows) {
    dischargeRows.innerHTML = normalizeStorageDeratingCurve(
      dischargeCurve,
      DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE,
      "discharge",
    ).map((point, index) => storagePowerDeratingRowHtml("discharge", point, index)).join("");
  }
}

function readStoragePowerDeratingCurve(direction) {
  return Array.from(document.querySelectorAll(`[data-derating-direction="${direction}"]`)).map((row) => ({
    soc: Math.max(0, toNumber(row.querySelector('[data-derating-field="soc"]')?.value, 0)) / 100,
    powerRatio: Math.max(0, toNumber(row.querySelector('[data-derating-field="powerRatio"]')?.value, 0)) / 100,
  }));
}

function validateStoragePowerDeratingCurve(points, direction) {
  if (!Array.isArray(points) || points.length < 2) return "每条降额曲线至少需要两个节点。";
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index];
    if (!Number.isFinite(point.soc) || point.soc < 0 || point.soc > 1) return "SOC 必须位于 0% 到 100% 之间。";
    if (!Number.isFinite(point.powerRatio) || point.powerRatio < 0 || point.powerRatio > 1) return "功率上限必须位于 0% 到 100% 之间。";
    if (index > 0 && point.soc <= points[index - 1].soc) return "SOC 节点必须严格递增，不能重复。";
    if (index > 0 && direction === "charge" && point.powerRatio > points[index - 1].powerRatio) {
      return "充电功率上限必须随 SOC 升高保持不变或下降。";
    }
    if (index > 0 && direction === "discharge" && point.powerRatio < points[index - 1].powerRatio) {
      return "放电功率上限必须随 SOC 升高保持不变或上升。";
    }
  }
  return "";
}

function validateStoragePowerDeratingCurves(chargeCurve, dischargeCurve) {
  return validateStoragePowerDeratingCurve(chargeCurve, "charge")
    || validateStoragePowerDeratingCurve(dischargeCurve, "discharge");
}

function setStoragePowerDeratingMessage(message = "", level = "") {
  const node = $("storagePowerDeratingMessage");
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("is-error", level === "error");
  node.classList.toggle("is-ok", level === "ok");
}

function openStoragePowerDeratingDialog() {
  renderStoragePowerDeratingRows();
  setStoragePowerDeratingMessage("相邻 SOC 节点之间自动进行线性插值。", "");
  const dialog = $("storagePowerDeratingDialog");
  if (dialog && !dialog.open) dialog.showModal();
}

function closeStoragePowerDeratingDialog() {
  const dialog = $("storagePowerDeratingDialog");
  if (dialog?.open) dialog.close();
}

async function resetStoragePowerDeratingCurves() {
  const confirmed = await confirmDangerousAction({
    title: "恢复默认储能降额曲线？",
    target: "充/放电 SOC 分段功率上限节点",
    message: "将覆盖当前编辑中的全部降额节点为出厂默认曲线（点击保存后生效）。",
    confirmLabel: "确认恢复",
  });
  if (!confirmed) return;
  renderStoragePowerDeratingRows(
    DEFAULT_STORAGE_CHARGE_DERATING_CURVE,
    DEFAULT_STORAGE_DISCHARGE_DERATING_CURVE,
  );
  setStoragePowerDeratingMessage("已恢复默认节点，点击保存后生效。", "ok");
  showUiToast("已恢复默认储能降额曲线节点", "ok");
}

async function saveStoragePowerDeratingCurves() {
  const chargeCurve = readStoragePowerDeratingCurve("charge");
  const dischargeCurve = readStoragePowerDeratingCurve("discharge");
  const validationMessage = validateStoragePowerDeratingCurves(chargeCurve, dischargeCurve);
  if (validationMessage) {
    setStoragePowerDeratingMessage(validationMessage, "error");
    return;
  }
  setStoragePowerDeratingMessage("正在保存降额曲线...", "");
  const response = await runRenewableControlAction("update_settings", {
    settings: {
      storageChargeDeratingCurve: chargeCurve,
      storageDischargeDeratingCurve: dischargeCurve,
    },
  });
  if (!response) {
    setStoragePowerDeratingMessage(state.renewableControl.lastStatus || "降额曲线保存失败。", "error");
    return;
  }
  closeStoragePowerDeratingDialog();
}

