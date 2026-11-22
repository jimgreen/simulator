// 教员端前端模块：源荷曲线目录、摘要加载、Canvas 绘图与编辑表。

function loadCurveFamilyConfig(family) {
  return LOAD_CURVE_FAMILIES.find((item) => item.key === family) || null;
}

function loadCurveFamilyForBlock(blockName) {
  const block = String(blockName || "").trim();
  return LOAD_CURVE_FAMILIES.find((item) => item.blocks.includes(block))?.key || "other";
}

function loadCurveFamilyKeys(family) {
  return curveLoadDevices()
    .filter((dev) => dev.family === family)
    .map((dev) => loadCurveKey(dev.dev_name));
}

function curveLoadDeviceForKey(key) {
  const devName = loadNameFromCurveKey(key);
  return curveLoadDevices().find((dev) => dev.dev_name === devName) || null;
}

function curveSourceCatalog() {
  const sources = Array.isArray(state.curveSummary?.sources) ? state.curveSummary.sources : [];
  return sources.filter((item) => item && item.key && item.family);
}

function allSourceCurveKeys() {
  return curveSourceCatalog().map((item) => item.key);
}

function allCurveKeys() {
  return [...ENV_CURVE_KEYS, ...allLoadCurveKeys(), ...allSourceCurveKeys()];
}

function semanticDeviceModelBlock(dev) {
  return String(dev?.model_block || dev?.raw?.model_block || "").trim();
}

function semanticDeviceFamily(dev) {
  return String(dev?.device_family || "").trim().toLowerCase();
}

function curveLoadDevices() {
  const summaryLoads = Array.isArray(state.curveSummary?.loads) ? state.curveSummary.loads : [];
  const summaryByName = new Map(summaryLoads.map((item) => [String(item.dev_name || item.name || ""), item]));
  const supportedBlocks = new Set(LOAD_CURVE_FAMILIES.flatMap((item) => item.blocks));
  const devices = (state.snapshot?.devices || [])
    .filter((dev) => (
      semanticDeviceFamily(dev) === "load"
      || supportedBlocks.has(semanticDeviceModelBlock(dev))
    ) && dev.dev_name)
    .map((dev) => {
      const summary = summaryByName.get(String(dev.dev_name || "")) || {};
      const modelBlock = semanticDeviceModelBlock(dev) || String(summary.dev_type || dev.dev_type || "");
      const family = String(summary.family || loadCurveFamilyForBlock(modelBlock));
      const config = loadCurveFamilyConfig(family);
      return {
        dev_type: modelBlock,
        dev_name: dev.dev_name,
        family,
        unit: summary.unit || config?.unit || "",
        set_type: summary.set_type || config?.setType || "",
        value_key: config?.valueKey || "value",
        default_value: Number(summary.default_value ?? dev.raw?.[summary.set_type || config?.setType || ""] ?? 0),
        min: Number(summary.min ?? dev.raw?.[`${String(summary.set_type || config?.setType || "").replace(/_set$/, "")}_min`]),
        max: Number(summary.max ?? dev.raw?.[`${String(summary.set_type || config?.setType || "").replace(/_set$/, "")}_max`]),
      };
    });
  const unique = new Map();
  devices.forEach((dev) => unique.set(`${dev.dev_type}|${dev.dev_name}`, dev));
  const loads = Array.from(unique.values()).sort((left, right) => left.dev_name.localeCompare(right.dev_name));
  if (!loads.length && summaryLoads.length) {
    return summaryLoads
      .map((item) => {
        const devType = String(item.dev_type || "");
        const family = String(item.family || loadCurveFamilyForBlock(devType));
        const config = loadCurveFamilyConfig(family);
        return {
          dev_type: devType,
          dev_name: item.dev_name || item.name || loadNameFromCurveKey(item.key),
          family,
          unit: item.unit || config?.unit || "",
          set_type: item.set_type || config?.setType || "",
          value_key: config?.valueKey || "value",
          default_value: Number(item.default_value ?? 0),
          min: Number(item.min),
          max: Number(item.max),
        };
      })
      .filter((dev) => dev.dev_name);
  }
  return loads.length ? loads : [{
    dev_type: "ACLoad",
    dev_name: "load_ac_1",
    family: "electric",
      unit: "kW",
      set_type: "p_set",
      value_key: "p_kw",
      default_value: 0,
      min: 0,
      max: 500,
  }];
}

function curveObservedRange(key) {
  const values = Array.isArray(state.curveSeries?.[key]) ? state.curveSeries[key] : [];
  let minimum = Infinity;
  let maximum = -Infinity;
  values.forEach((rawValue) => {
    const value = Number(rawValue);
    if (!Number.isFinite(value)) return;
    minimum = Math.min(minimum, value);
    maximum = Math.max(maximum, value);
  });
  return Number.isFinite(minimum) && Number.isFinite(maximum)
    ? { min: minimum, max: maximum }
    : null;
}

function curveMetaForKey(key) {
  const meta = CURVE_META.find((item) => item.key === key);
  if (meta) return meta;
  if (String(key).startsWith("load:")) {
    const devName = loadNameFromCurveKey(key);
    const loadDevice = curveLoadDeviceForKey(key);
    const loadIndex = Math.max(0, allLoadCurveKeys().indexOf(key));
    const color = LOAD_CURVE_COLORS[loadIndex % LOAD_CURVE_COLORS.length];
    const lower = Number(loadDevice?.min);
    const upper = Number(loadDevice?.max);
    const defaultValue = Number(loadDevice?.default_value);
    const observed = curveObservedRange(key);
    const referenceValues = [defaultValue, observed?.min, observed?.max].filter(Number.isFinite);
    const referenceMinimum = referenceValues.length ? Math.min(...referenceValues) : 0;
    const referenceMaximum = referenceValues.length ? Math.max(...referenceValues) : 0;
    const resolvedMinimum = Number.isFinite(lower) ? Math.min(lower, referenceMinimum) : Math.min(0, referenceMinimum);
    const upperIsUsable = Number.isFinite(upper) && upper > resolvedMinimum && upper >= referenceMaximum;
    const resolvedMaximum = upperIsUsable
      ? upper
      : Math.max(1, referenceMaximum * 1.2, referenceMaximum + Math.abs(referenceMinimum) * 0.2);
    return {
      ...LOAD_CURVE_META,
      key,
      label: devName,
      color,
      unit: loadDevice?.unit || LOAD_CURVE_META.unit,
      family: loadDevice?.family || "electric",
      devType: loadDevice?.dev_type || "",
      min: resolvedMinimum,
      max: resolvedMaximum,
    };
  }
  if (String(key).startsWith("source:")) {
    const source = curveSourceCatalog().find((item) => item.key === key) || {};
    const sourceIndex = Math.max(0, allSourceCurveKeys().indexOf(key));
    const defaultValue = Number(source.default_value);
    const lower = Number(source.min);
    const upper = Number(source.max);
    const observed = curveObservedRange(key);
    const referenceValues = [defaultValue, observed?.min, observed?.max].filter(Number.isFinite);
    const referenceMinimum = referenceValues.length ? Math.min(...referenceValues) : 0;
    const referenceMaximum = referenceValues.length ? Math.max(...referenceValues) : 0;
    const span = Math.max(1, referenceMaximum - referenceMinimum, Math.abs(referenceMinimum), Math.abs(referenceMaximum));
    const resolvedMinimum = Number.isFinite(lower) && lower <= referenceMinimum
      ? lower
      : Math.min(0, referenceMinimum - span * 0.2);
    const resolvedMaximum = Number.isFinite(upper) && upper > resolvedMinimum && upper >= referenceMaximum
      ? upper
      : Math.max(1, referenceMaximum + span * 0.2);
    return {
      key,
      label: source.name || source.dev_name || key,
      color: SOURCE_CURVE_COLORS[sourceIndex % SOURCE_CURVE_COLORS.length],
      min: resolvedMinimum,
      max: resolvedMaximum,
      digits: 3,
      unit: source.unit || "",
      family: source.family || "electric",
      devType: source.dev_type || "",
    };
  }
  return CURVE_META[0];
}

function activeLoadCurveKey() {
  const key = activeCurveKey();
  if (key.startsWith("load:")) return key;
  return loadCurveKey(curveLoadDevices()[0]?.dev_name);
}

function selectedCurveKeys() {
  const available = new Set(allCurveKeys());
  const selected = Array.from(new Set(state.selectedCurveKeys || []))
    .filter((key) => available.has(key));
  const activeKey = activeCurveKey();
  state.selectedCurveKeys = selected;
  if (!selected.includes(activeKey)) {
    state.activeCurveKey = selected[selected.length - 1] || "";
  }
  return selected;
}

function curveHiddenSet() {
  return new Set(state.hiddenCurveKeys || []);
}

function isCurveSeriesHidden(key) {
  return curveHiddenSet().has(key);
}

function visibleCurveKeys() {
  return selectedCurveKeys().filter((key) => !isCurveSeriesHidden(key));
}

function visibleCurveMetas() {
  return visibleCurveKeys().map(curveMetaForKey);
}

function toggleCurveSeriesVisibility(key, shouldRender = true) {
  if (!key) return;
  const hidden = curveHiddenSet();
  if (hidden.has(key)) hidden.delete(key);
  else hidden.add(key);
  state.hiddenCurveKeys = Array.from(hidden);
  state.curveEditKey = key;
  if (shouldRender) {
    renderCurveTree();
    drawCurves();
    renderHourlyTable(true);
  }
}

function resampleSeries(values, nextLength, fallbackValue) {
  if (values?.length === nextLength) return values;
  if (!values?.length) return new Array(nextLength).fill(fallbackValue);
  if (nextLength <= 1) return [values[0] ?? fallbackValue];
  const lastSource = Math.max(1, values.length - 1);
  return Array.from({ length: nextLength }, (_unused, index) => {
    const sourceIndex = Math.round((index / Math.max(1, nextLength - 1)) * lastSource);
    return values[sourceIndex] ?? fallbackValue;
  });
}

function normalizeCurveSeriesLength(key, fallbackValue) {
  const nextLength = curvePointCount();
  const changed = state.curveSeries[key]?.length !== nextLength;
  state.curveSeries[key] = resampleSeries(state.curveSeries[key], nextLength, fallbackValue);
  return changed;
}

function curveFallbackValue(key) {
  if (String(key || "").startsWith("load:")) {
    const defaultValue = Number(curveLoadDeviceForKey(key)?.default_value);
    return Number.isFinite(defaultValue) ? defaultValue : 0;
  }
  if (String(key || "").startsWith("source:")) {
    const source = curveSourceCatalog().find((item) => item.key === key);
    return Number(source?.default_value) || 0;
  }
  return curveMetaForKey(key).min;
}

function curveHasLoadedSeries(key) {
  return Array.isArray(state.curveSeries?.[key]) && state.curveSeries[key].length > 0;
}

function ensureCurveSeries(keys = selectedCurveKeys()) {
  let changed = false;
  const available = new Set(allCurveKeys());
  const targetKeys = Array.from(new Set(keys || []))
    .filter((key) => available.has(key) || ENV_CURVE_KEYS.includes(key) || /^(load|source):/.test(String(key || "")));
  targetKeys.forEach((key) => {
    changed = normalizeCurveSeriesLength(key, curveFallbackValue(key)) || changed;
  });
  return changed;
}

function markCurveDirty(key) {
  if (!key) return;
  if (!(state.curveDirtyKeys instanceof Set)) state.curveDirtyKeys = new Set(state.curveDirtyKeys || []);
  state.curveDirtyKeys.add(key);
  state.curveDirtyKeysByMode[state.curveMode] = new Set(state.curveDirtyKeys);
  state.curveDataRevision += 1;
  state.lastCurveEditorRenderKey = "";
  state.lastCurveEditorTableKey = "";
}

function markCurveKeysDirty(keys = []) {
  keys.forEach((key) => markCurveDirty(key));
}

function saveCurrentCurveModeDraft() {
  if (!state.curveMode) return;
  if (Object.keys(state.curveSeries || {}).length) {
    state.curveSeriesByMode[state.curveMode] = state.curveSeries;
  }
  state.curveDirtyKeysByMode[state.curveMode] = new Set(state.curveDirtyKeys || []);
}

function restoreCurveModeDraft(mode) {
  state.curveSeries = state.curveSeriesByMode[mode] || {};
  state.curveDirtyKeys = new Set(state.curveDirtyKeysByMode[mode] || []);
}

function curveModeHasUnsavedChanges() {
  return state.curveMode !== state.curvePersistedMode || Boolean(state.curveDirtyKeys?.size);
}

function shouldPreserveCurveDraft() {
  return Boolean(state.curvePersistedMode) && curveModeHasUnsavedChanges();
}

function curveModeSwitchLabel(mode) {
  return CURVE_MODES[mode]?.simulationLabel || CURVE_MODES[mode]?.label || mode;
}

function setCurveModeSwitchBusy(isBusy) {
  state.curveModeSwitchSaving = Boolean(isBusy);
  const saveButton = $("saveCurveModeSwitch");
  const discardButton = $("discardCurveModeSwitch");
  const cancelButton = $("cancelCurveModeSwitch");
  const closeButton = $("closeCurveModeSwitchDialog");
  if (saveButton) {
    saveButton.disabled = isBusy;
    saveButton.textContent = isBusy ? "保存中" : "保存并切换";
  }
  if (discardButton) discardButton.disabled = isBusy;
  if (cancelButton) cancelButton.disabled = isBusy;
  if (closeButton) closeButton.disabled = isBusy;
}

function openCurveModeSwitchDialog(mode) {
  const nextMode = CURVE_MODES[mode] ? mode : "";
  const dialog = $("curveModeSwitchDialog");
  if (!nextMode || !dialog) return;
  state.pendingCurveModeSwitch = nextMode;
  const hint = $("curveModeSwitchHint");
  if (hint) {
    hint.textContent = `当前${curveModeSwitchLabel(state.curveMode)}曲线存在未保存修改，是否保存后切换到${curveModeSwitchLabel(nextMode)}？`;
  }
  const message = $("curveModeSwitchMessage");
  if (message) message.textContent = "";
  setCurveModeSwitchBusy(false);
  dialog.hidden = false;
  $("saveCurveModeSwitch")?.focus();
}

function closeCurveModeSwitchDialog() {
  if (state.curveModeSwitchSaving) return;
  const dialog = $("curveModeSwitchDialog");
  if (dialog) dialog.hidden = true;
  state.pendingCurveModeSwitch = "";
  const message = $("curveModeSwitchMessage");
  if (message) message.textContent = "";
}

function applyCurveModeSwitch(mode) {
  const nextMode = CURVE_MODES[mode] ? mode : "";
  if (!nextMode || nextMode === state.curveMode) return;
  setCurveMode(nextMode, true);
  setCurveStatus("已修改，待保存");
  renderCurveModeControls();
}

async function saveBeforeCurveModeSwitch() {
  const nextMode = state.pendingCurveModeSwitch;
  if (!nextMode || state.curveModeSwitchSaving) return;
  setCurveModeSwitchBusy(true);
  try {
    await saveCurves();
    state.curveModeSwitchSaving = false;
    closeCurveModeSwitchDialog();
    applyCurveModeSwitch(nextMode);
  } catch (error) {
    const message = $("curveModeSwitchMessage");
    if (message) message.textContent = `保存失败：${apiErrorText(error)}`;
    setCurveModeSwitchBusy(false);
  }
}

function switchCurveModeWithoutSaving() {
  const nextMode = state.pendingCurveModeSwitch;
  if (!nextMode || state.curveModeSwitchSaving) return;
  closeCurveModeSwitchDialog();
  applyCurveModeSwitch(nextMode);
}

function setCurveMode(mode, shouldRender = true) {
  const nextMode = CURVE_MODES[mode] ? mode : "year";
  saveCurrentCurveModeDraft();
  state.curveMode = nextMode;
  localStorage.setItem("polarSimulatorCurveMode", nextMode);
  state.curveEditKey = "";
  if (state.curveSeriesByMode[nextMode]) {
    restoreCurveModeDraft(nextMode);
    ensureCurveSeries(selectedCurveKeys());
  } else {
    state.curveDirtyKeys = new Set();
    generateCurves(0, nextMode, false);
  }
  if (shouldRender) {
    renderCurveEditor(true);
    renderFaults(true);
    if (curveModeHasUnsavedChanges()) setCurveStatus("已修改，待保存");
  }
}

function loadCurvesFromSnapshot(curves, modelId = state.activeModelId) {
  if (!curves || typeof curves !== "object") return;
  const mode = CURVE_MODES[curves.mode] ? curves.mode : "day";
  const config = curveModeConfig(mode);
  const weather = Array.isArray(curves.weather) ? curves.weather : [];
  const loads = curves.loads && typeof curves.loads === "object" ? curves.loads : {};
  state.curveMode = mode;
  localStorage.setItem("polarSimulatorCurveMode", mode);
  state.curveSummary = curveSummaryFromCurves(curves);
  state.curveSummaryLoadedModelId = modelId || "loaded";
  state.curveSeries = {
    wind_speed_mps: resampleSeries(weather.map((point) => Number(point.wind_speed_mps) || 0), config.pointCount, 0),
    solar_irradiance_w_m2: resampleSeries(weather.map((point) => Number(point.solar_irradiance_w_m2) || 0), config.pointCount, 0),
    air_temp_c: resampleSeries(weather.map((point) => Number(point.air_temp_c) || 0), config.pointCount, -18),
  };
  curveLoadDevices().forEach((dev) => {
    const points = Array.isArray(loads[dev.dev_name]) ? loads[dev.dev_name] : [];
    state.curveSeries[loadCurveKey(dev.dev_name)] = resampleSeries(
      points.map((point) => Number(
        point[dev.value_key]
        ?? point.value
        ?? point.p_kw
        ?? point.load_kw
        ?? point.flow_set
        ?? point.heat_power,
      ) || 0),
      config.pointCount,
      curveFallbackValue(loadCurveKey(dev.dev_name)),
    );
  });
  (Array.isArray(curves.sources) ? curves.sources : []).forEach((source) => {
    if (!source?.key) return;
    const points = Array.isArray(source.points) ? source.points : [];
    state.curveSeries[source.key] = resampleSeries(
      points.map((point) => Number(point.value ?? point.set_value) || 0),
      config.pointCount,
      Number(source.default_value) || 0,
    );
  });
  ensureCurveSeries();
  state.curveSeriesByMode[mode] = state.curveSeries;
  state.curveDirtyKeys = new Set();
  state.curveDirtyKeysByMode = { [mode]: new Set() };
  state.curvePersistedMode = mode;
  syncCurvePayload(false);
  state.curvesLoadedModelId = modelId || "loaded";
  state.curveDataRevision += 1;
  state.lastCurveEditorRenderKey = "";
  state.lastCurveEditorTableKey = "";
}

function curveSummaryFromCurves(curves = {}) {
  const mode = CURVE_MODES[curves.mode] ? curves.mode : "day";
  const config = curveModeConfig(mode);
  const weather = Array.isArray(curves.weather) ? curves.weather : [];
  const loads = curves.loads && typeof curves.loads === "object" ? curves.loads : {};
  return {
    mode,
    time_step_minutes: Number(curves.time_step_minutes || config.stepMinutes),
    point_count: Number(curves.point_count || weather.length || config.pointCount),
    environment: ENV_CURVE_KEYS.map((key) => ({ key, point_count: weather.length })),
    loads: Object.keys(loads).map((name) => ({
      key: loadCurveKey(name),
      name,
      point_count: Array.isArray(loads[name]) ? loads[name].length : 0,
      ...(() => {
        const dev = (state.snapshot?.devices || []).find((item) => (
          String(item?.dev_name || "") === name
          && (semanticDeviceFamily(item) === "load" || loadCurveFamilyForBlock(semanticDeviceModelBlock(item)) !== "other")
        ));
        const devType = semanticDeviceModelBlock(dev);
        const family = loadCurveFamilyForBlock(devType);
        const config = loadCurveFamilyConfig(family);
        return devType ? {
          dev_type: devType,
          dev_name: name,
          family,
          unit: config?.unit || "",
          set_type: config?.setType || "",
        } : {};
      })(),
    })),
    sources: (Array.isArray(curves.sources) ? curves.sources : []).map((source) => ({
      ...source,
      point_count: Array.isArray(source.points) ? source.points.length : 0,
      points: undefined,
    })),
  };
}

function curveSummaryHasCatalog(summary = state.curveSummary) {
  return Boolean(summary && Array.isArray(summary.environment) && Array.isArray(summary.loads) && Array.isArray(summary.sources));
}

function applyCurveSummary(summary, modelId = state.activeModelId) {
  if (!summary || typeof summary !== "object") return;
  const mode = CURVE_MODES[summary.mode] ? summary.mode : "day";
  const initializesModel = state.curveSummaryLoadedModelId !== (modelId || "loaded");
  const preserveCurveDraft = !initializesModel && shouldPreserveCurveDraft();
  const resetsCurveDraft = initializesModel || !state.curvePersistedMode;
  state.curveSummary = summary;
  state.curveSummaryLoadedModelId = modelId || "loaded";
  state.curveLoadError = "";
  state.lastCurveEditorRenderKey = "";
  state.lastCurveEditorTableKey = "";
  if (!preserveCurveDraft) {
    state.curveMode = mode;
    state.curvePersistedMode = mode;
    localStorage.setItem("polarSimulatorCurveMode", mode);
  }
  if (resetsCurveDraft) {
    state.curveDirtyKeys = new Set();
    state.curveDirtyKeysByMode = { [mode]: new Set() };
  }
}

function isAbortRequestError(error) {
  return error?.name === "AbortError";
}

function cancelCurveRequests() {
  state.curveSummaryAbortController?.abort();
  state.curveSeriesAbortController?.abort();
  state.curveSummaryAbortController = null;
  state.curveSeriesAbortController = null;
  state.curveSummaryRequest = null;
  state.curveSummaryRequestModelId = "";
  state.curveSeriesRequest = null;
  state.curveSeriesRequestKey = "";
  state.curveEditorLoadRequest = null;
  state.curveEditorLoadRequestKey = "";
}

async function loadCurveSummary(modelId = state.activeModelId) {
  if (state.curveSummaryLoadedModelId === modelId && curveSummaryHasCatalog(state.curveSummary)) return state.curveSummary;
  if (state.curveSummaryRequest && state.curveSummaryRequestModelId === modelId) return state.curveSummaryRequest;
  state.curveSummaryAbortController?.abort();
  const controller = new AbortController();
  state.curveSummaryAbortController = controller;
  state.curveSummaryRequestModelId = modelId;
  state.curveSummaryRequest = api("/api/curves/summary", {
    signal: controller.signal,
    timeoutMs: curveRequestTimeoutMs(),
  })
    .then((summary) => {
      if (modelId === state.activeModelId) applyCurveSummary(summary, modelId);
      return summary;
    })
    .finally(() => {
      if (state.curveSummaryRequestModelId === modelId && state.curveSummaryAbortController === controller) {
        state.curveSummaryRequest = null;
        state.curveSummaryRequestModelId = "";
        state.curveSummaryAbortController = null;
      }
    });
  return state.curveSummaryRequest;
}

function applyCurveSeriesPayload(payload = {}, requestedKeys = []) {
  if (!payload || typeof payload !== "object") return;
  const payloadMode = CURVE_MODES[payload.mode] ? payload.mode : "";
  const preserveCurveDraft = shouldPreserveCurveDraft();
  if (preserveCurveDraft && payloadMode && payloadMode !== state.curveMode) return;
  if (payloadMode && !preserveCurveDraft) {
    state.curveMode = payload.mode;
    state.curvePersistedMode = payload.mode;
    localStorage.setItem("polarSimulatorCurveMode", state.curveMode);
  }
  const series = payload.series && typeof payload.series === "object" ? payload.series : {};
  Object.entries(series).forEach(([key, values]) => {
    if (!Array.isArray(values)) return;
    state.curveSeries[key] = resampleSeries(values.map((value) => Number(value) || 0), curvePointCount(), curveFallbackValue(key));
  });
  requestedKeys.forEach((key) => {
    if (!curveHasLoadedSeries(key)) normalizeCurveSeriesLength(key, curveFallbackValue(key));
  });
  state.curveSeriesByMode[state.curveMode] = state.curveSeries;
  state.curveDataRevision += 1;
  state.curveLoadError = "";
  state.lastCurveEditorRenderKey = "";
  state.lastCurveEditorTableKey = "";
}

async function ensureCurveSeriesLoaded(keys = selectedCurveKeys()) {
  const requested = Array.from(new Set(keys || [])).filter(Boolean);
  const keysToFetch = requested.filter((key) => !curveHasLoadedSeries(key));
  if (!keysToFetch.length) return true;
  const modelId = state.activeModelId;
  const requestKey = `${modelId}|${keysToFetch.slice().sort().join("|")}`;
  if (state.curveSeriesRequestKey === requestKey && state.curveSeriesRequest) return state.curveSeriesRequest;
  state.curveSeriesAbortController?.abort();
  const controller = new AbortController();
  state.curveSeriesRequestKey = requestKey;
  state.curveSeriesAbortController = controller;
  state.curveSeriesRequest = api(`/api/curves/series?keys=${encodeURIComponent(keysToFetch.join(","))}`, {
    signal: controller.signal,
    timeoutMs: curveRequestTimeoutMs(),
  })
    .then((payload) => {
      if (modelId === state.activeModelId) applyCurveSeriesPayload(payload, keysToFetch);
      return true;
    })
    .catch((error) => {
      if (!isAbortRequestError(error)) {
        state.curveLoadError = apiErrorText(error);
        const status = $("curveStatus");
        if (status) status.textContent = `曲线加载失败：${state.curveLoadError}`;
      }
      return false;
    })
    .finally(() => {
      if (state.curveSeriesRequestKey === requestKey && state.curveSeriesAbortController === controller) {
        state.curveSeriesRequest = null;
        state.curveSeriesRequestKey = "";
        state.curveSeriesAbortController = null;
      }
    });
  return state.curveSeriesRequest;
}

async function switchSimulationMode(mode) {
  if (modelServiceDependentControlsDisabled() || simulationModeLocked()) return;
  const nextMode = CURVE_MODES[mode] ? mode : "";
  if (!nextMode || nextMode === state.curveMode) return;
  if (curveModeHasUnsavedChanges()) {
    openCurveModeSwitchDialog(nextMode);
    return;
  }
  applyCurveModeSwitch(nextMode);
}

function renderCurveModeControls() {
  const modeLocked = simulationModeLocked();
  const controlsDisabled = modelServiceDependentControlsDisabled();
  document.querySelectorAll("[data-curve-mode]").forEach((button) => {
    const active = button.dataset.curveMode === state.curveMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.disabled = modeLocked || controlsDisabled;
    button.title = controlsDisabled
      ? "请先启动选中模型的模拟服务"
      : modeLocked ? "请先停止仿真，再切换仿真模式" : "";
  });
  const selector = $("simulationModeSelector");
  if (selector) {
    selector.value = state.curveMode;
    selector.disabled = modeLocked || controlsDisabled;
    selector.title = controlsDisabled
      ? "请先启动选中模型的模拟服务"
      : modeLocked ? "请先停止仿真，再切换仿真模式" : "选择时、日、周、月或年仿真";
  }
  if (state.snapshot?.clock) renderClockTextOnly(state.snapshot.clock);
}

function renderClockTextOnly(clock) {
  const time = $("simTime");
  const simSpeed = $("simSpeed");
  const readout = document.querySelector(".clock-readout");
  if (time) time.textContent = formatSimulationClock(clock);
  if (simSpeed) simSpeed.textContent = `x${clock.speed ?? 1}`;
  if (typeof syncClockTriggerSummary === "function") {
    syncClockTriggerSummary(clock.state || $("simState")?.textContent || "stopped", clock.speed ?? 1);
  }
  if (readout) readout.classList.toggle("is-year-mode", isExtendedSimulationMode());
}

function updateCurveModeLabels() {
  const config = curveModeConfig();
  const pointCount = $("curvePointCount");
  const tableTitle = $("curveTableTitle");
  const tableSummary = $("curveTableSummary");
  if (pointCount) pointCount.textContent = `${config.pointCount}点`;
  if (tableTitle) tableTitle.textContent = config.tableTitle;
  if (tableSummary) tableSummary.textContent = config.tableSummary;
}

function curveFamilyKeys(family) {
  if (family === "environment") return [...ENV_CURVE_KEYS];
  if (family === "load") return allLoadCurveKeys();
  if (String(family).startsWith("load:")) return loadCurveFamilyKeys(String(family).slice(5));
  if (family === "source") return allSourceCurveKeys();
  if (String(family).startsWith("source:")) {
    const sourceFamily = String(family).slice(7);
    return curveSourceCatalog().filter((item) => item.family === sourceFamily).map((item) => item.key);
  }
  if (SOURCE_CURVE_FAMILIES.some((item) => item.key === family)) {
    return curveSourceCatalog().filter((item) => item.family === family).map((item) => item.key);
  }
  return [];
}

function selectedCurveLabel() {
  const selected = selectedCurveKeys();
  if (!selected.length) return "未选择曲线";
  const editKey = curveEditKey(selected);
  const selectedLabel = selected.length <= 1 ? curveMetaForKey(selected[0]).label : `已选${selected.length}条`;
  return editKey && selected.length > 1 ? `${selectedLabel} · ${curveMetaForKey(editKey).label}` : selectedLabel;
}

function setSelectedCurves(keys, activeKey = keys?.[keys.length - 1], shouldRender = true) {
  const available = new Set(allCurveKeys());
  const previous = new Set(state.selectedCurveKeys || []);
  const selected = Array.from(new Set(keys || [])).filter((key) => available.has(key));
  const nextActiveKey = selected.includes(activeKey) ? activeKey : selected[selected.length - 1];
  state.selectedCurveKeys = selected;
  state.activeCurveKey = nextActiveKey || "";
  const hidden = curveHiddenSet();
  selected.filter((key) => !previous.has(key)).forEach((key) => hidden.delete(key));
  state.hiddenCurveKeys = Array.from(hidden);
  if (state.curveEditKey && !selected.includes(state.curveEditKey)) {
    state.curveEditKey = "";
  }
  const activeInput = $("activeCurve");
  if (activeInput) activeInput.value = state.activeCurveKey;
  if (shouldRender) {
    renderCurveTree();
    drawCurves();
    renderHourlyTable();
    if (selected.some((key) => !curveHasLoadedSeries(key))) {
      void ensureCurveSeriesLoaded(selected).then((loaded) => {
        if (!loaded) return;
        renderCurveTree();
        drawCurves();
        renderHourlyTable(true);
      });
    }
  }
}

function toggleCurveSelection(key, shouldRender = true) {
  const selected = selectedCurveKeys();
  const next = selected.includes(key)
    ? selected.filter((item) => item !== key)
    : [...selected, key];
  setSelectedCurves(next, next.includes(key) ? key : next[next.length - 1], shouldRender);
}

function selectCurveFamily(family, shouldRender = true) {
  const familyKeys = curveFamilyKeys(family);
  setSelectedCurves(familyKeys, familyKeys[0], shouldRender);
}

function curveTreeButtonKeys(button) {
  if (!button) return [];
  if (button.dataset.curveFamily) return curveFamilyKeys(button.dataset.curveFamily);
  return button.dataset.curveKey ? [button.dataset.curveKey] : [];
}

function selectCurveTreeButton(button, event = null, shouldRender = true) {
  const key = button?.dataset.curveKey || "";
  if (!key) return;
  const selected = selectedCurveKeys();
  const selectedSet = new Set(selected);
  const multiSelect = Boolean(event?.ctrlKey || event?.metaKey || event?.shiftKey);
  const next = multiSelect
    ? selectedSet.has(key)
      ? selected.filter((selectedKey) => selectedKey !== key)
      : [...selected, key]
    : [key];
  if (!multiSelect) {
    const hidden = curveHiddenSet();
    hidden.delete(key);
    state.hiddenCurveKeys = Array.from(hidden);
  }
  const activeKey = next.includes(key) ? key : next[next.length - 1];
  setSelectedCurves(next, activeKey, shouldRender);
}

function resetCurveTreePointerSelection() {
  state.isCurveTreePointerDown = false;
  state.isCurveTreeMultiSelecting = false;
  state.curveTreeDragStartKeys = [];
  state.curveTreeDragKeys = [];
  state.curveTreeDragStartButton = null;
}

function beginCurveTreePointerSelection(event) {
  if (event.button !== 0 || !(event.ctrlKey || event.metaKey || event.shiftKey)) return;
  const button = event.target.closest("[data-curve-tree-type]");
  if (!button || !$("curveTree")?.contains(button)) return;
  state.isCurveTreePointerDown = true;
  state.isCurveTreeMultiSelecting = false;
  state.curveTreeDragStartButton = button;
  state.curveTreeDragStartKeys = curveTreeButtonKeys(button);
  state.curveTreeDragKeys = [...state.curveTreeDragStartKeys];
}

function extendCurveTreePointerSelection(event) {
  if (!state.isCurveTreePointerDown || (event.buttons & 1) !== 1) return;
  const button = event.target.closest("[data-curve-tree-type]");
  if (!button || !$("curveTree")?.contains(button)) return;
  if (!state.isCurveTreeMultiSelecting && button === state.curveTreeDragStartButton) return;
  const keys = curveTreeButtonKeys(button);
  if (!keys.length) return;
  if (!state.isCurveTreeMultiSelecting) {
    state.isCurveTreeMultiSelecting = true;
    state.curveTreeDragKeys = [...state.curveTreeDragStartKeys];
  }
  const before = state.curveTreeDragKeys.length;
  keys.forEach((key) => {
    if (!state.curveTreeDragKeys.includes(key)) state.curveTreeDragKeys.push(key);
  });
  if (state.curveTreeDragKeys.length !== before || !selectedCurveKeys().every((key) => state.curveTreeDragKeys.includes(key))) {
    setSelectedCurves(state.curveTreeDragKeys, keys[keys.length - 1], true);
  }
}

function finishCurveTreePointerSelection() {
  if (state.isCurveTreeMultiSelecting) {
    state.suppressNextCurveTreeClick = true;
  }
  resetCurveTreePointerSelection();
}

function curveEditKey(selectedKeys = selectedCurveKeys()) {
  const editKey = state.curveEditKey || "";
  if (editKey && selectedKeys.includes(editKey) && (state.curveSeries[editKey] || []).length) {
    return editKey;
  }
  if (editKey) state.curveEditKey = "";
  return "";
}

function setCurveEditKey(key, shouldRender = true) {
  const selected = selectedCurveKeys();
  const nextKey = selected.includes(key) ? key : "";
  state.curveEditKey = nextKey;
  if (nextKey) {
    state.activeCurveKey = nextKey;
    const activeInput = $("activeCurve");
    if (activeInput) activeInput.value = nextKey;
  }
  if (shouldRender) {
    renderCurveTree();
    drawCurves();
  }
}

function cancelCurveEditSelection() {
  state.curveEditKey = "";
  state.isCurveDragging = false;
  renderCurveTree();
  drawCurves();
}

function curveTreeGroupCollapsed(groupKey) {
  return Boolean(state.curveTreeGroupCollapsed?.[groupKey]);
}

function toggleCurveTreeGroup(groupKey, shouldRender = true) {
  if (!groupKey) return;
  state.curveTreeGroupCollapsed = {
    ...(state.curveTreeGroupCollapsed || {}),
    [groupKey]: !curveTreeGroupCollapsed(groupKey),
  };
  localStorage.setItem(CURVE_TREE_COLLAPSE_KEY, JSON.stringify(state.curveTreeGroupCollapsed));
  if (shouldRender) renderCurveTree();
}

function curveTreeGroupHeader(groupKey, label, count, buttonAttrs, buttonClasses = "", forceExpanded = false) {
  const collapsed = !forceExpanded && curveTreeGroupCollapsed(groupKey);
  return `
    <button
      type="button"
      class="tree-node tree-type ${buttonClasses} ${collapsed ? "is-collapsed" : ""}"
      data-curve-tree-toggle="${escapeHtml(groupKey)}"
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

function curveTreeMediumMeta(family = "") {
  return {
    environment: { label: "环境", marker: "环", order: 0 },
    electric: { label: "电", marker: "电", order: 1 },
    hydrogen: { label: "氢", marker: "氢", order: 2 },
    heat: { label: "热", marker: "热", order: 3 },
    other: { label: "其他", marker: "其", order: 4 },
  }[family] || { label: "其他", marker: "其", order: 4 };
}

function curveTreeItemMatches(item, query) {
  if (!query) return true;
  return [item.label, item.unit, item.medium?.label]
    .some((value) => String(value || "").toLocaleLowerCase("zh-CN").includes(query));
}

function curveTreeChildHtml(item, type, selectedSet, editKey) {
  return `
    <button
      type="button"
      class="tree-node tree-child ${selectedSet.has(item.key) ? "is-active" : ""} ${editKey === item.key ? "is-edit-target" : ""} ${isCurveSeriesHidden(item.key) ? "is-hidden-series" : ""}"
      data-curve-tree-type="${escapeHtml(type)}"
      data-curve-key="${escapeHtml(item.key)}"
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

function renderCurveTree() {
  const container = $("curveTree");
  if (!container) return;
  const activeKey = activeCurveKey();
  const selectedKeys = selectedCurveKeys();
  const editKey = curveEditKey(selectedKeys);
  const selectedSet = new Set(selectedKeys);
  const loadDevices = curveLoadDevices();
  const loadKeys = allLoadCurveKeys();
  const sourceKeys = allSourceCurveKeys();
  const query = String(state.curveTreeSearch || "").trim().toLocaleLowerCase("zh-CN");
  const environmentItems = ENV_CURVE_KEYS.map((key) => {
    const meta = curveMetaForKey(key);
    return { key, label: meta.label, unit: meta.unit, family: "environment", medium: curveTreeMediumMeta("environment") };
  });
  const loadItems = loadDevices.map((dev) => ({
    key: loadCurveKey(dev.dev_name),
    label: dev.dev_name,
    unit: dev.unit || "",
    family: curveTreeMediumMeta(dev.family).label === "其他" ? "other" : dev.family,
    medium: curveTreeMediumMeta(dev.family),
  })).sort((left, right) => left.medium.order - right.medium.order || left.label.localeCompare(right.label, "zh-CN"));
  const sourceItems = curveSourceCatalog().map((source) => ({
    key: source.key,
    label: source.name || source.dev_name || source.key,
    unit: source.unit || "",
    family: curveTreeMediumMeta(source.family).label === "其他" ? "other" : source.family,
    medium: curveTreeMediumMeta(source.family),
  })).sort((left, right) => left.medium.order - right.medium.order || left.label.localeCompare(right.label, "zh-CN"));
  const groups = [
    { key: "environment", label: "环境曲线", type: "environment", keys: ENV_CURVE_KEYS, items: environmentItems },
    { key: "load", label: "负荷曲线", type: "load", keys: loadKeys, items: loadItems },
    { key: "source", label: "供能曲线", type: "source", keys: sourceKeys, items: sourceItems },
  ].map((group) => ({
    ...group,
    visibleItems: group.label.toLocaleLowerCase("zh-CN").includes(query)
      ? group.items
      : group.items.filter((item) => curveTreeItemMatches(item, query)),
  }));
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  const visibleTotal = groups.reduce((sum, group) => sum + group.visibleItems.length, 0);
  $("curveTreeSummary").textContent = query ? `${visibleTotal}/${total} 条` : `${total} 条`;
  $("activeCurve").value = activeKey;
  $("activeCurveLabel").textContent = selectedCurveLabel();
  container.innerHTML = groups.filter((group) => !query || group.visibleItems.length).map((group) => {
    const groupSelected = group.keys.length && group.keys.every((key) => selectedSet.has(key));
    const groupPartial = !groupSelected && group.keys.some((key) => selectedSet.has(key));
    const collapsed = !query && curveTreeGroupCollapsed(group.key);
    return `
      <div class="tree-group">
        ${curveTreeGroupHeader(
          group.key,
          group.label,
          group.visibleItems.length,
          `data-curve-tree-type="${escapeHtml(group.type)}" data-curve-family="${escapeHtml(group.key)}" aria-pressed="${groupSelected ? "true" : "false"}"`,
          groupSelected ? "is-active" : groupPartial ? "is-parent-active" : "",
          Boolean(query),
        )}
        <div class="tree-children" ${collapsed ? "hidden" : ""}>
          ${group.visibleItems.map((item) => curveTreeChildHtml(item, group.type, selectedSet, editKey)).join("")}
        </div>
      </div>`;
  }).join("") || `<div class="empty-state">未匹配“${escapeHtml(state.curveTreeSearch || "")}”</div>`;
}

function setActiveCurve(key, shouldRender = true) {
  const nextKey = key || "wind_speed_mps";
  setSelectedCurves([nextKey], nextKey, shouldRender);
}

function drawCurveLoading(message = "正在加载曲线...") {
  const canvas = $("curveEditorChart");
  if (!canvas) return;
  resizeCurveCanvas();
  const { ctx, width, height } = prepareCanvas2D(canvas, 900, 260);
  const palette = chartThemePalette();
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = palette.grid;
  ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
  ctx.fillStyle = palette.text;
  ctx.font = "14px Microsoft YaHei, Arial";
  ctx.textAlign = "center";
  ctx.fillText(message, width / 2, height / 2);
  ctx.textAlign = "left";
}

function renderCurveTableLoading(message = "正在加载曲线数据...") {
  const container = $("hourlyCurveTable");
  if (!container) return;
  container.removeAttribute("data-virtual-table");
  container.innerHTML = `
    <table class="curve-table">
      <tbody>
        <tr><td>${escapeHtml(message)}</td></tr>
      </tbody>
    </table>`;
}

function renderCurveTreeLoading(message = "正在加载曲线摘要...") {
  const container = $("curveTree");
  if (!container) return;
  const summary = $("curveTreeSummary");
  const activeInput = $("activeCurve");
  const activeLabel = $("activeCurveLabel");
  if (summary) summary.textContent = "加载中";
  if (activeInput) activeInput.value = "";
  if (activeLabel) activeLabel.textContent = "--";
  container.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderCurveEditorLoading(message) {
  if (curveSummaryHasCatalog(state.curveSummary)) renderCurveTree();
  else renderCurveTreeLoading(message);
  renderCurveModeControls();
  updateCurveModeLabels();
  const status = $("curveStatus");
  if (status) status.textContent = message;
  drawCurveLoading(message);
  renderCurveTableLoading(message);
}

function renderCurveEditorError(message = state.curveLoadError || "曲线加载失败") {
  const detail = String(message || "曲线加载失败");
  if (curveSummaryHasCatalog(state.curveSummary)) renderCurveTree();
  else renderCurveTreeLoading("曲线摘要加载失败");
  renderCurveModeControls();
  updateCurveModeLabels();
  const status = $("curveStatus");
  if (status) status.textContent = `曲线加载失败：${detail}`;
  drawCurveLoading("曲线加载失败，请重试");
  const container = $("hourlyCurveTable");
  if (container) {
    container.removeAttribute("data-virtual-table");
    container.innerHTML = `
      <div class="empty-state">
        <span>${escapeHtml(detail)}</span>
        <button type="button" class="primary" data-curve-retry>重试</button>
      </div>`;
  }
}

function startCurveEditorLoad(modelId = state.activeModelId) {
  const requestKey = String(modelId || "");
  if (state.curveEditorLoadRequest && state.curveEditorLoadRequestKey === requestKey) {
    return state.curveEditorLoadRequest;
  }
  state.curveLoadError = "";
  state.curveEditorLoadRequestKey = requestKey;
  let request;
  request = (async () => {
    await loadCurveSummary(modelId);
    if (modelId !== state.activeModelId || currentPageName() !== "curves") return false;
    const loaded = await ensureCurveSeriesLoaded(selectedCurveKeys());
    if (modelId !== state.activeModelId || currentPageName() !== "curves") return false;
    if (!loaded) throw new Error(state.curveLoadError || "曲线数据加载失败");
    state.lastCurveEditorRenderKey = "";
    renderCurveEditor(true);
    return true;
  })()
    .catch((error) => {
      if (isAbortRequestError(error) || modelId !== state.activeModelId || currentPageName() !== "curves") {
        return false;
      }
      state.curveLoadError = apiErrorText(error);
      renderCurveEditorError(state.curveLoadError);
      return false;
    })
    .finally(() => {
      if (state.curveEditorLoadRequest === request) {
        state.curveEditorLoadRequest = null;
        state.curveEditorLoadRequestKey = "";
      }
    });
  state.curveEditorLoadRequest = request;
  return request;
}

function retryCurveEditorLoad() {
  cancelCurveRequests();
  state.curveLoadError = "";
  state.lastCurveEditorRenderKey = "";
  renderCurveEditorLoading("正在重新加载曲线...");
  startCurveEditorLoad(state.activeModelId);
}

function curveEditorRenderKey() {
  return JSON.stringify({
    model: state.activeModelId,
    mode: state.curveMode,
    points: curvePointCount(),
    selected: selectedCurveKeys(),
    hidden: [...(state.hiddenCurveKeys || [])].sort(),
    revision: state.curveDataRevision,
  });
}

function renderCurveEditor(force = false) {
  const modelId = state.activeModelId;
  if (!state.modelsLoaded) {
    renderCurveEditorLoading("正在加载模型列表...");
    return;
  }
  const summaryMissing = state.curveSummaryLoadedModelId !== modelId || !curveSummaryHasCatalog(state.curveSummary);
  if (summaryMissing) {
    if (state.curveLoadError) {
      renderCurveEditorError(state.curveLoadError);
      return;
    }
    renderCurveEditorLoading("正在加载曲线摘要...");
    startCurveEditorLoad(modelId);
    return;
  }
  const selectedKeys = selectedCurveKeys();
  const missingKeys = selectedKeys.filter((key) => !curveHasLoadedSeries(key));
  if (missingKeys.length) {
    if (state.curveLoadError) {
      renderCurveEditorError(state.curveLoadError);
      return;
    }
    renderCurveEditorLoading(`正在加载 ${missingKeys.length} 条曲线...`);
    startCurveEditorLoad(modelId);
    return;
  }
  ensureCurveSeries(selectedKeys);
  const renderKey = curveEditorRenderKey();
  if (!force && renderKey === state.lastCurveEditorRenderKey) return;
  state.lastCurveEditorRenderKey = renderKey;
  renderCurveTree();
  renderCurveModeControls();
  updateCurveModeLabels();
  const status = $("curveStatus");
  if (status && /^正在加载|^曲线加载失败/.test(status.textContent || "")) status.textContent = "已加载";
  const activeEditor = document.activeElement?.closest?.("#hourlyCurveTable");
  if (!force && activeEditor) return;
  drawCurves();
  renderHourlyTable();
}

function generateCurves(jitter = 0, mode = state.curveMode, shouldRender = true) {
  state.curveMode = CURVE_MODES[mode] ? mode : "year";
  const config = curveModeConfig();
  const pointCount = curvePointCount();
  state.curveSeries = Object.fromEntries(ENV_CURVE_KEYS.map((key) => [key, new Array(pointCount)]));
  const windPeak = 38 + jitter;
  const solarPeak = 720;
  const tempMean = -18;
  const loadDevices = curveLoadDevices();
  loadDevices.forEach((dev) => {
    state.curveSeries[loadCurveKey(dev.dev_name)] = new Array(pointCount);
  });
  curveSourceCatalog().forEach((source) => {
    state.curveSeries[source.key] = new Array(pointCount).fill(Number(source.default_value) || 0);
  });
  for (let i = 0; i < pointCount; i += 1) {
    const minute = pointMinute(i);
    const day = (minute % (24 * 60)) / (24 * 60);
    const year = minute / config.durationMinutes;
    const season = state.curveMode === "year" ? Math.sin((year - 0.18) * Math.PI * 2) : 0;
    const gust = Math.sin(day * Math.PI * 2 * 5 + 0.8) * 4 + Math.sin(day * Math.PI * 2 * 11 + year * 9) * 2;
    const wind = clamp(windPeak * (0.58 + 0.28 * Math.sin(day * Math.PI * 2 - 0.7) + 0.10 * season) + gust, 0, 50);
    const daylight = Math.max(0, Math.sin((day - 0.25) * Math.PI * 2));
    const solarSeason = state.curveMode === "year" ? clamp(0.58 + 0.42 * season, 0.05, 1.0) : 1.0;
    const tempSeason = state.curveMode === "year" ? 9 * season : 0;
    const sunShape = daylight * solarSeason;
    const temp = tempMean + tempSeason + 6 * Math.sin((day - 0.33) * Math.PI * 2);
    const loadShape = 0.84 + 0.18 * Math.sin((day - 0.18) * Math.PI * 2) + 0.08 * Math.sin(day * Math.PI * 8);
    state.curveSeries.wind_speed_mps[i] = Number(wind.toFixed(2));
    state.curveSeries.solar_irradiance_w_m2[i] = Number((solarPeak * sunShape).toFixed(1));
    state.curveSeries.air_temp_c[i] = Number(temp.toFixed(2));
    loadDevices.forEach((dev, loadIndex) => {
      const offset = 1 + loadIndex * 0.035;
      const base = curveFallbackValue(loadCurveKey(dev.dev_name));
      const lower = Number.isFinite(Number(dev.min)) ? Number(dev.min) : 0;
      const upper = Number.isFinite(Number(dev.max)) && Number(dev.max) >= lower
        ? Number(dev.max)
        : Math.max(lower, Math.abs(base) * 1.2, 1);
      state.curveSeries[loadCurveKey(dev.dev_name)][i] = Number(
        clamp(base * loadShape * offset, lower, upper).toFixed(2),
      );
    });
  }
  const firstElectricLoad = loadDevices.find((dev) => dev.family === "electric") || loadDevices[0];
  if (firstElectricLoad) {
    state.curveSeries.load_kw = [...state.curveSeries[loadCurveKey(firstElectricLoad.dev_name)]];
  }
  state.curveSeriesByMode[state.curveMode] = state.curveSeries;
  markCurveKeysDirty(Object.keys(state.curveSeries));
  syncCurvePayload(false);
  if (shouldRender) renderCurveEditor(true);
}

function typicalCurveStatistics(values = []) {
  const numericValues = values.map(Number).filter(Number.isFinite);
  if (!numericValues.length) return { min: 0, max: 0, average: 0 };
  const sum = numericValues.reduce((total, value) => total + value, 0);
  return {
    min: Math.min(...numericValues),
    max: Math.max(...numericValues),
    average: sum / numericValues.length,
  };
}

function typicalCurveInputBounds(key, meta = curveMetaForKey(key)) {
  const observed = curveObservedRange(key);
  if (!observed) return { min: meta.min, max: meta.max };
  const observedSpan = Math.max(
    1,
    observed.max - observed.min,
    Math.abs(observed.min),
    Math.abs(observed.max),
  );
  return {
    min: Number.isFinite(Number(meta.min)) ? Number(meta.min) : observed.min - observedSpan,
    max: Math.max(meta.max, observed.max + observedSpan),
  };
}

function typicalCurveTargetKey() {
  const selected = selectedCurveKeys();
  const key = curveEditKey(selected) || activeCurveKey() || selected[0] || "";
  return allCurveKeys().includes(key) ? key : "";
}

function typicalCurveCycleCount(mode = state.curveMode) {
  return { hour: 4, day: 4, week: 7, month: 30, year: 12 }[mode] || 4;
}

function typicalCurveBaseValues(shape, pointCount) {
  const count = Math.max(2, Math.floor(Number(pointCount) || 0));
  const cycles = Math.max(1, Math.min(count - 1, typicalCurveCycleCount()));
  const values = Array.from({ length: count }, (_unused, index) => {
    if (shape === "random") return Math.random();
    const cyclePosition = (index / Math.max(1, count - 1)) * cycles;
    const phase = index === count - 1 ? 1 : cyclePosition - Math.floor(cyclePosition);
    if (shape === "step") return Math.min(3, Math.floor(phase * 4)) / 3;
    if (shape === "sawtooth") return phase;
    return (1 - Math.cos(phase * Math.PI * 2)) / 2;
  });
  let minIndex = 0;
  let maxIndex = 0;
  values.forEach((value, index) => {
    if (value < values[minIndex]) minIndex = index;
    if (value > values[maxIndex]) maxIndex = index;
  });
  if (maxIndex === minIndex) maxIndex = count - 1;
  const epsilon = Math.max(Number.EPSILON, 1 / (count * 1000));
  values.forEach((value, index) => {
    if (index === minIndex) values[index] = 0;
    else if (index === maxIndex) values[index] = 1;
    else values[index] = clamp(value, epsilon, 1 - epsilon);
  });
  return { values, minIndex, maxIndex };
}

function fitTypicalCurveNormalizedMean(values, targetAverage) {
  const target = clamp(Number(targetAverage) || 0, 0, 1);
  const meanFor = (exponent, raiseMean) => values.reduce((sum, value) => (
    sum + (raiseMean ? 1 - ((1 - value) ** exponent) : value ** exponent)
  ), 0) / values.length;
  const currentMean = values.reduce((sum, value) => sum + value, 0) / values.length;
  if (Math.abs(currentMean - target) < 1e-12) return [...values];
  const raiseMean = target > currentMean;
  let low = 1;
  let high = 2;
  while (
    high < 1048576
    && (raiseMean ? meanFor(high, true) < target : meanFor(high, false) > target)
  ) {
    high *= 2;
  }
  for (let iteration = 0; iteration < 64; iteration += 1) {
    const exponent = (low + high) / 2;
    const mean = meanFor(exponent, raiseMean);
    if (raiseMean ? mean < target : mean > target) low = exponent;
    else high = exponent;
  }
  return values.map((value) => (
    raiseMean ? 1 - ((1 - value) ** high) : value ** high
  ));
}

function adjustTypicalCurveRoundedAverage(values, targetAverage, minimum, maximum, digits, anchors) {
  const rounded = values.map((value) => Number(clamp(value, minimum, maximum).toFixed(digits)));
  rounded[anchors.minIndex] = Number(minimum.toFixed(digits));
  rounded[anchors.maxIndex] = Number(maximum.toFixed(digits));
  const targetSum = targetAverage * rounded.length;
  let difference = targetSum - rounded.reduce((sum, value) => sum + value, 0);
  const candidates = rounded.map((_value, index) => index)
    .filter((index) => index !== anchors.minIndex && index !== anchors.maxIndex);
  candidates.forEach((index, candidateIndex) => {
    if (Math.abs(difference) < (10 ** (-digits)) / 2) return;
    const remaining = Math.max(1, candidates.length - candidateIndex);
    const share = difference / remaining;
    const next = Number(clamp(rounded[index] + share, minimum, maximum).toFixed(digits));
    difference -= next - rounded[index];
    rounded[index] = next;
  });
  return rounded;
}

function generateTypicalCurveValues(key, minimum, maximum, average, shape, pointCount = curvePointCount()) {
  const meta = curveMetaForKey(key);
  const digits = Math.max(0, Math.min(6, Number(meta.digits) || 0));
  const roundedMinimum = Number(Number(minimum).toFixed(digits));
  const roundedMaximum = Number(Number(maximum).toFixed(digits));
  const roundedAverage = Number(Number(average).toFixed(digits));
  if (roundedMaximum === roundedMinimum) {
    return new Array(Math.max(2, pointCount)).fill(roundedMinimum);
  }
  const base = typicalCurveBaseValues(shape, pointCount);
  const targetNormalizedMean = (roundedAverage - roundedMinimum) / (roundedMaximum - roundedMinimum);
  const normalized = fitTypicalCurveNormalizedMean(base.values, targetNormalizedMean);
  const scaled = normalized.map((value) => roundedMinimum + (roundedMaximum - roundedMinimum) * value);
  return adjustTypicalCurveRoundedAverage(
    scaled,
    roundedAverage,
    roundedMinimum,
    roundedMaximum,
    digits,
    base,
  );
}

function setTypicalCurveMessage(text = "", isError = false) {
  const message = $("typicalCurveMessage");
  if (!message) return;
  message.textContent = text;
  message.classList.toggle("is-error", Boolean(text) && isError);
}

async function openTypicalCurveDialog() {
  const key = typicalCurveTargetKey();
  if (!key) {
    setCurveStatus("请先选择一条曲线");
    return;
  }
  await ensureCurveSeriesLoaded([key]);
  const values = state.curveSeries[key] || [];
  if (!values.length) {
    setCurveStatus("当前曲线尚未加载");
    return;
  }
  const meta = curveMetaForKey(key);
  const stats = typicalCurveStatistics(values);
  const inputBounds = typicalCurveInputBounds(key, meta);
  const digits = Math.max(0, Math.min(6, Number(meta.digits) || 0));
  const step = String(10 ** (-digits));
  const fields = [
    ["typicalCurveMax", stats.max],
    ["typicalCurveMin", stats.min],
    ["typicalCurveAverage", stats.average],
  ];
  fields.forEach(([id, value]) => {
    const input = $(id);
    if (!input) return;
    input.min = String(inputBounds.min);
    input.max = String(inputBounds.max);
    input.step = step;
    input.value = Number(value).toFixed(digits);
  });
  ["typicalCurveMaxUnit", "typicalCurveMinUnit", "typicalCurveAverageUnit"].forEach((id) => {
    const unit = $(id);
    if (unit) unit.textContent = meta.unit || "无量纲";
  });
  const hint = $("typicalCurveHint");
  if (hint) {
    hint.textContent = `${meta.label} · ${curveModeSwitchLabel(state.curveMode)} · ${curvePointCount()}点；确认后仅更新本地草稿。`;
  }
  state.typicalCurveTargetKey = key;
  setTypicalCurveMessage();
  $("typicalCurveShape").value = "sine";
  $("typicalCurveDialog").hidden = false;
  $("typicalCurveMax").focus();
  $("typicalCurveMax").select();
}

function closeTypicalCurveDialog() {
  const dialog = $("typicalCurveDialog");
  if (dialog) dialog.hidden = true;
  state.typicalCurveTargetKey = "";
  setTypicalCurveMessage();
}

function confirmTypicalCurveGeneration() {
  const key = state.typicalCurveTargetKey;
  if (!key || !allCurveKeys().includes(key)) {
    setTypicalCurveMessage("当前曲线已失效，请关闭后重新选择。", true);
    return;
  }
  const meta = curveMetaForKey(key);
  const digits = Math.max(0, Math.min(6, Number(meta.digits) || 0));
  const minimum = Number(Number($("typicalCurveMin").value).toFixed(digits));
  const maximum = Number(Number($("typicalCurveMax").value).toFixed(digits));
  const average = Number(Number($("typicalCurveAverage").value).toFixed(digits));
  const allowedMinimum = Number($("typicalCurveMin").min);
  const allowedMaximum = Number($("typicalCurveMax").max);
  const shape = $("typicalCurveShape").value;
  if (![minimum, maximum, average].every(Number.isFinite)) {
    setTypicalCurveMessage("请输入有效的最大值、最小值和平均值。", true);
    return;
  }
  if (minimum < allowedMinimum || maximum > allowedMaximum) {
    setTypicalCurveMessage(`取值范围应在 ${allowedMinimum} 至 ${allowedMaximum} ${meta.unit || ""} 之间。`, true);
    return;
  }
  if (minimum > maximum) {
    setTypicalCurveMessage("最小值不能大于最大值。", true);
    return;
  }
  if (minimum === maximum && average !== minimum) {
    setTypicalCurveMessage("最大值与最小值相同时，平均值必须与其相同。", true);
    return;
  }
  if (minimum < maximum && (average <= minimum || average >= maximum)) {
    setTypicalCurveMessage("平均值必须严格位于最小值和最大值之间。", true);
    return;
  }
  if (minimum < maximum) {
    const span = maximum - minimum;
    const pointCount = curvePointCount();
    const feasibleMinimum = minimum + span / pointCount;
    const feasibleMaximum = maximum - span / pointCount;
    if (average < feasibleMinimum || average > feasibleMaximum) {
      setTypicalCurveMessage("平均值过于接近上下限，当前点数无法同时呈现指定的最大值和最小值。", true);
      return;
    }
  }
  state.curveSeries[key] = generateTypicalCurveValues(key, minimum, maximum, average, shape);
  state.curveSeriesByMode[state.curveMode] = state.curveSeries;
  markCurveDirty(key);
  renderCurveEditor(true);
  setCurveStatus("已生成，待保存");
  closeTypicalCurveDialog();
}

function syncCurvePayload(shouldStoreSeries = true) {
  ensureCurveSeries();
  const config = curveModeConfig();
  state.weatherPoints = [];
  state.loadPoints = [];
  state.loadPointsByName = {};
  curveLoadDevices().forEach((dev) => {
    state.loadPointsByName[dev.dev_name] = [];
  });
  for (let i = 0; i < config.pointCount; i += 1) {
    const minute = Number(pointMinute(i).toFixed(4));
    const year = minute / config.durationMinutes;
    state.weatherPoints.push({
      minute,
      wind_speed_mps: roundCurveValue("wind_speed_mps", state.curveSeries.wind_speed_mps[i]),
      air_temp_c: roundCurveValue("air_temp_c", state.curveSeries.air_temp_c[i]),
      air_pressure_hpa: Number((955 + 10 * Math.sin(year * Math.PI * 2 + 0.4)).toFixed(2)),
      solar_irradiance_w_m2: roundCurveValue("solar_irradiance_w_m2", state.curveSeries.solar_irradiance_w_m2[i]),
      humidity_pct: Number((68 + 9 * Math.sin(year * Math.PI * 2 + 2.2)).toFixed(2)),
    });
    curveLoadDevices().forEach((dev, loadIndex) => {
      const key = loadCurveKey(dev.dev_name);
      const point = { minute, [dev.value_key || "value"]: roundCurveValue(key, state.curveSeries[key]?.[i] ?? 0) };
      state.loadPointsByName[dev.dev_name].push(point);
      if (loadIndex === 0) state.loadPoints.push(point);
    });
  }
  if (shouldStoreSeries) state.curveSeriesByMode[state.curveMode] = state.curveSeries;
}

function roundCurveValue(key, value) {
  const meta = curveMetaForKey(key);
  return Number(clamp(Number(value), meta.min, meta.max).toFixed(meta.digits));
}

function resizeCurveCanvas() {
  const canvas = $("curveEditorChart");
  return resizeCanvasToRenderedSize(canvas, 900, 260);
}

function curvePlot(canvas) {
  const { width } = canvasLogicalSize(canvas, 900, 260);
  if (width < 640) {
    return { left: 48, right: 12, top: 58, bottom: 30 };
  }
  return CURVE_PLOT;
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

function valueToY(value, meta, canvas) {
  const plot = curvePlot(canvas);
  const { height } = canvasLogicalSize(canvas, 900, 260);
  const top = plot.top;
  const bottom = height - plot.bottom;
  const ratio = (clamp(value, meta.min, meta.max) - meta.min) / (meta.max - meta.min);
  return bottom - ratio * (bottom - top);
}

function yToValue(y, meta, canvas) {
  const plot = curvePlot(canvas);
  const { height } = canvasLogicalSize(canvas, 900, 260);
  const top = plot.top;
  const bottom = height - plot.bottom;
  const ratio = (bottom - clamp(y, top, bottom)) / (bottom - top);
  return roundCurveValue(meta.key, meta.min + ratio * (meta.max - meta.min));
}

function drawCurveXAxis(ctx, canvas, plot) {
  const { width, height } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  if (state.curveMode === "hour") {
    const minuteStep = width < 560 ? 15 : 10;
    for (let minute = 0; minute <= 60; minute += minuteStep) {
      const x = left + (minute / 60) * (right - left);
      ctx.strokeStyle = minute % 30 === 0 ? "#c9d6dc" : "#e7eef1";
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = "#63717a";
      const labelHour = Math.floor(minute / 60);
      const labelMinute = minute % 60;
      ctx.fillText(`${String(labelHour).padStart(2, "0")}:${String(labelMinute).padStart(2, "0")}`, x - 14, height - 12);
    }
    return;
  }
  if (state.curveMode === "week" || state.curveMode === "month") {
    const dayCount = simulationModeDayCount();
    const dayStep = state.curveMode === "week" ? 1 : width < 560 ? 10 : width < 900 ? 5 : 3;
    for (let day = 0; day <= dayCount; day += dayStep) {
      const x = left + (day / dayCount) * (right - left);
      ctx.strokeStyle = day === 0 || day === dayCount ? "#c9d6dc" : "#e7eef1";
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = "#63717a";
      const labelDay = Math.min(day + 1, dayCount);
      ctx.fillText(`第${labelDay}天`, x - 16, height - 12);
    }
    if (dayCount % dayStep !== 0) {
      ctx.textAlign = "right";
      ctx.fillText(`第${dayCount}天`, right, height - 12);
      ctx.textAlign = "left";
    }
    return;
  }
  if (state.curveMode === "year") {
    const monthStarts = [
      ["01月", 0],
      ["02月", 31],
      ["03月", 59],
      ["04月", 90],
      ["05月", 120],
      ["06月", 151],
      ["07月", 181],
      ["08月", 212],
      ["09月", 243],
      ["10月", 273],
      ["11月", 304],
      ["12月", 334],
    ];
    const monthStep = width < 560 ? 3 : width < 900 ? 2 : 1;
    monthStarts.forEach(([label, day], index) => {
      if (index % monthStep !== 0) return;
      const x = left + (day / 365) * (right - left);
      ctx.strokeStyle = index % 3 === 0 ? "#c9d6dc" : "#e7eef1";
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.fillStyle = "#63717a";
      ctx.fillText(label, x - 12, height - 12);
    });
    ctx.strokeStyle = "#c9d6dc";
    ctx.beginPath();
    ctx.moveTo(right, top);
    ctx.lineTo(right, bottom);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.textAlign = "right";
    ctx.fillText("年末", right, height - 12);
    ctx.textAlign = "left";
    return;
  }
  const hourStep = width < 480 ? 4 : width < 820 ? 3 : 2;
  for (let hour = 0; hour <= 24; hour += hourStep) {
    const x = left + (hour / 24) * (right - left);
    ctx.strokeStyle = hour % 6 === 0 ? "#c9d6dc" : "#e7eef1";
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.fillStyle = "#63717a";
    ctx.fillText(`${String(hour).padStart(2, "0")}:00`, x - 14, height - 12);
  }
}

function drawCurves() {
  const canvas = $("curveEditorChart");
  if (!canvas) return;
  resizeCurveCanvas();
  const { ctx, width, height } = prepareCanvas2D(canvas, 900, 260);
  const plot = curvePlot(canvas);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  const allMetas = selectedCurveKeys().map(curveMetaForKey);
  const metas = allMetas.filter((meta) => !isCurveSeriesHidden(meta.key));
  const editKey = curveEditKey(metas.map((meta) => meta.key));
  const axisMeta = curveYAxisMeta(metas, editKey || state.activeCurveKey);
  const legendColumns = width < 560 ? 2 : Math.max(1, allMetas.length);
  const legendColumnWidth = (right - left) / legendColumns;
  const palette = chartThemePalette();
  state.curveLegendHitBoxes = [];
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = palette.grid;
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei, Arial";
  ctx.fillStyle = palette.text;
  for (let i = 0; i <= 5; i += 1) {
    const y = top + i * ((bottom - top) / 5);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  drawCurveXAxis(ctx, canvas, plot);
  drawCurveYAxis(ctx, canvas, plot, axisMeta);
  metas.forEach((meta) => {
    const values = state.curveSeries[meta.key] || [];
    const sampledPoints = sampleCurvePointsForCanvas(values, right - left, 1.4);
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = editKey && meta.key === editKey ? 3.5 : 2;
    ctx.beginPath();
    sampledPoints.forEach((point, index) => {
      const x = left + (point.index / Math.max(1, values.length - 1)) * (right - left);
      const y = valueToY(point.value, meta, canvas);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    const lastX = right;
    const lastY = valueToY(values[values.length - 1] || 0, meta, canvas);
    ctx.lineTo(lastX, lastY);
    ctx.stroke();
  });
  if (!allMetas.length) {
    ctx.fillStyle = "#63717a";
    ctx.textAlign = "center";
    ctx.fillText("未选择曲线", (left + right) / 2, (top + bottom) / 2);
    ctx.textAlign = "left";
  }
  if (!metas.length && allMetas.length) {
    ctx.fillStyle = "#63717a";
    ctx.textAlign = "center";
    ctx.fillText("所有曲线已隐藏", (left + right) / 2, (top + bottom) / 2);
    ctx.textAlign = "left";
  }
  allMetas.forEach((meta, metaIndex) => {
    const legendX = left + (metaIndex % legendColumns) * legendColumnWidth;
    const legendY = 20 + Math.floor(metaIndex / legendColumns) * 16;
    const hidden = isCurveSeriesHidden(meta.key);
    const labelText = `${meta.label} (${meta.unit})${hidden ? " 隐藏" : ""}`;
    state.curveLegendHitBoxes.push({
      key: meta.key,
      x: legendX - 6,
      y: legendY - 9,
      width: Math.min(legendColumnWidth - 8, ctx.measureText(labelText).width + 42),
      height: 16,
    });
    ctx.fillStyle = hidden ? "#9aa9af" : meta.color;
    ctx.fillRect(legendX, legendY, 18, 3);
    ctx.fillStyle = hidden ? "#9aa9af" : editKey === meta.key ? "#1f3037" : "#63717a";
    ctx.fillText(labelText, legendX + 26, legendY + 4);
  });
  drawCurveCursor(ctx, canvas, plot, metas);
}

function curveLegendKeyAtPointer(event) {
  const canvas = $("curveEditorChart");
  if (!canvas) return "";
  const pos = pointerPositionOnCanvas(event);
  const hit = (state.curveLegendHitBoxes || []).find((box) => (
    pos.x >= box.x && pos.x <= box.x + box.width && pos.y >= box.y && pos.y <= box.y + box.height
  ));
  return hit?.key || "";
}

function pointerPositionOnCanvas(event) {
  const canvas = $("curveEditorChart");
  return canvasPointerPosition(canvas, event);
}

function curvePointIndexFromX(x, canvas) {
  const plot = curvePlot(canvas);
  const { width } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const right = width - plot.right;
  const pointCount = curvePointCount();
  return clamp(Math.round(((x - left) / (right - left)) * (pointCount - 1)), 0, pointCount - 1);
}

function curveXFromPointIndex(index, canvas) {
  const plot = curvePlot(canvas);
  const { width } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const right = width - plot.right;
  return left + (clamp(index, 0, curvePointCount() - 1) / Math.max(1, curvePointCount() - 1)) * (right - left);
}

function setCurveCursorFromEvent(event, shouldDraw = true) {
  const canvas = $("curveEditorChart");
  if (!canvas) return;
  const pos = pointerPositionOnCanvas(event);
  const plot = curvePlot(canvas);
  const { width, height } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  if (pos.x < left || pos.x > right || pos.y < top || pos.y > bottom) {
    state.curveCursor = { visible: false, x: pos.x, y: pos.y, index: state.curveCursor.index || 0 };
    if (shouldDraw) drawCurves();
    return;
  }
  state.curveCursor = {
    visible: true,
    x: clamp(pos.x, left, right),
    y: clamp(pos.y, top, bottom),
    index: curvePointIndexFromX(pos.x, canvas),
  };
  if (shouldDraw) drawCurves();
}

function hideCurveCursor() {
  if (!state.curveCursor.visible) return;
  state.curveCursor.visible = false;
  drawCurves();
}

function drawCurveTooltipBox(ctx, x, y, width, height, radius = 8) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + width - radius, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
  ctx.lineTo(x + width, y + height - radius);
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  ctx.lineTo(x + radius, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

function drawCurveCursor(ctx, canvas, plot, metas) {
  const cursor = state.curveCursor;
  if (!cursor.visible || !metas.length) return;
  const { width, height } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  const index = clamp(cursor.index, 0, curvePointCount() - 1);
  const x = curveXFromPointIndex(index, canvas);
  const y = clamp(cursor.y, top, bottom);
  const tooltipMetas = metas.slice(0, 6);
  const extraCount = Math.max(0, metas.length - tooltipMetas.length);
  const timeLabel = formatCurveTableTime(pointMinute(index));
  const valueLines = tooltipMetas.map((meta) => {
    const value = roundCurveValue(meta.key, state.curveSeries[meta.key]?.[index] ?? 0);
    return { meta, text: `${meta.label}: ${value} ${meta.unit}` };
  });

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
    const values = state.curveSeries[meta.key] || [];
    if (!values.length) return;
    const markerY = valueToY(values[index], meta, canvas);
    ctx.fillStyle = palette.markerFill;
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, markerY, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  ctx.font = "12px Microsoft YaHei, Arial";
  const title = `时刻: ${timeLabel}`;
  const point = `点号: ${index + 1}`;
  const lineTexts = [title, point, ...valueLines.map((line) => line.text), extraCount ? `另有 ${extraCount} 条曲线` : ""].filter(Boolean);
  const tooltipWidth = Math.max(154, ...lineTexts.map((line) => ctx.measureText(line).width + 28));
  const lineHeight = 18;
  const tooltipHeight = 16 + lineTexts.length * lineHeight;
  let tooltipX = x + 14;
  let tooltipY = y + 14;
  if (tooltipX + tooltipWidth > right - 6) tooltipX = x - tooltipWidth - 14;
  if (tooltipY + tooltipHeight > bottom - 6) tooltipY = y - tooltipHeight - 14;
  tooltipX = clamp(tooltipX, left + 6, right - tooltipWidth - 6);
  tooltipY = clamp(tooltipY, top + 6, bottom - tooltipHeight - 6);

  ctx.shadowColor = "rgba(28, 45, 52, 0.18)";
  ctx.shadowBlur = 12;
  ctx.shadowOffsetY = 3;
  ctx.fillStyle = palette.tooltipBg;
  drawCurveTooltipBox(ctx, tooltipX, tooltipY, tooltipWidth, tooltipHeight);
  ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.strokeStyle = palette.tooltipBorder;
  ctx.stroke();

  ctx.fillStyle = "#1f3037";
  ctx.font = "700 12px Microsoft YaHei, Arial";
  ctx.fillText(title, tooltipX + 10, tooltipY + 18);
  ctx.font = "12px Microsoft YaHei, Arial";
  ctx.fillStyle = "#63717a";
  ctx.fillText(point, tooltipX + 10, tooltipY + 36);
  valueLines.forEach((line, lineIndex) => {
    const textY = tooltipY + 54 + lineIndex * lineHeight;
    ctx.fillStyle = line.meta.color;
    ctx.fillRect(tooltipX + 10, textY - 7, 10, 3);
    ctx.fillStyle = "#314850";
    ctx.fillText(line.text, tooltipX + 26, textY);
  });
  if (extraCount) {
    ctx.fillStyle = "#63717a";
    ctx.fillText(`另有 ${extraCount} 条曲线`, tooltipX + 10, tooltipY + 54 + valueLines.length * lineHeight);
  }
  ctx.restore();
}

function curveKeyAtPointer(event) {
  const canvas = $("curveEditorChart");
  if (!canvas) return "";
  const pos = pointerPositionOnCanvas(event);
  const plot = curvePlot(canvas);
  const { width, height } = canvasLogicalSize(canvas, 900, 260);
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  if (pos.x < left || pos.x > right || pos.y < top || pos.y > bottom) return "";
  const index = curvePointIndexFromX(pos.x, canvas);
  const tolerance = width < 640 ? 18 : 14;
  let bestKey = "";
  let bestDistance = Infinity;
  visibleCurveMetas().forEach((meta) => {
    const values = state.curveSeries[meta.key] || [];
    if (!values.length) return;
    const distance = Math.abs(valueToY(values[index], meta, canvas) - pos.y);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestKey = meta.key;
    }
  });
  return bestDistance <= tolerance ? bestKey : "";
}

function applyCurveDrag(event) {
  const canvas = $("curveEditorChart");
  const editKey = curveEditKey();
  const meta = curveMetaForKey(editKey);
  const values = state.curveSeries[editKey] || [];
  if (!canvas || !meta || !values.length) return;
  const pos = pointerPositionOnCanvas(event);
  const index = curvePointIndexFromX(pos.x, canvas);
  const targetValue = yToValue(pos.y, meta, canvas);
  const brush = Math.max(12, Math.round(curvePointCount() / 300));
  for (let offset = -brush; offset <= brush; offset += 1) {
    const point = index + offset;
    if (point < 0 || point >= values.length) continue;
    const weight = 1 - Math.abs(offset) / (brush + 1);
    values[point] = roundCurveValue(editKey, values[point] * (1 - weight) + targetValue * weight);
  }
  markCurveDirty(editKey);
  drawCurves();
  $("curveStatus").textContent = "已修改，待保存";
}

function formatCurveTableTime(minute) {
  if (state.curveMode === "hour") {
    const totalSeconds = Math.max(0, Math.round(Number(minute) * 60));
    const minutePart = Math.floor(totalSeconds / 60);
    const secondPart = totalSeconds % 60;
    return `00:${String(minutePart).padStart(2, "0")}:${String(secondPart).padStart(2, "0")}`;
  }
  if (state.curveMode === "year") {
    const dayOfYear = Math.floor(minute / (24 * 60));
    const hour = Math.floor((minute % (24 * 60)) / 60);
    const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let month = 0;
    let day = dayOfYear;
    while (month < monthDays.length - 1 && day >= monthDays[month]) {
      day -= monthDays[month];
      month += 1;
    }
    return `${String(month + 1).padStart(2, "0")}-${String(day + 1).padStart(2, "0")} ${String(hour).padStart(2, "0")}:00`;
  }
  if (state.curveMode === "week" || state.curveMode === "month") {
    const total = Math.max(0, Math.round(Number(minute)));
    const day = Math.floor(total / 1440) + 1;
    const minuteOfDay = total % 1440;
    const hour = Math.floor(minuteOfDay / 60);
    const minutePart = minuteOfDay % 60;
    return `第${day}天 ${String(hour).padStart(2, "0")}:${String(minutePart).padStart(2, "0")}`;
  }
  const total = Math.round(minute);
  const hour = Math.floor(total / 60);
  const minutePart = total % 60;
  return `${String(hour).padStart(2, "0")}:${String(minutePart).padStart(2, "0")}`;
}

function renderHourlyTable(force = false) {
  const container = $("hourlyCurveTable");
  if (!container) return;
  const metas = visibleCurveMetas();
  if (!metas.length) {
    state.lastCurveEditorTableKey = "curveEditor:empty";
    container.removeAttribute("data-virtual-table");
    container.innerHTML = `<div class="empty-state">${selectedCurveKeys().length ? "所有曲线已隐藏" : "未选择曲线"}</div>`;
    return;
  }
  const pointCount = curvePointCount();
  const tableKey = `curveEditor:${state.activeModelId}:${state.curveMode}`;
  const signature = JSON.stringify({
    tableKey,
    pointCount,
    selected: metas.map((meta) => meta.key),
    revision: state.curveDataRevision,
  });
  if (!force && signature === state.lastCurveEditorTableKey) return;
  state.lastCurveEditorTableKey = signature;
  const rowIndexes = Array.from({ length: pointCount }, (_unused, index) => index);
  const virtualRows = virtualTableWindow(tableKey, rowIndexes);
  const columnCount = metas.length + 1;
  container.setAttribute("data-virtual-table", tableKey);
  container.innerHTML = `
    <table class="curve-table">
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
            <td>${formatCurveTableTime(pointMinute(index))}</td>
            ${metas.map((meta) => `
              <td
                contenteditable="true"
                data-index="${index}"
                data-key="${escapeHtml(meta.key)}"
              >${roundCurveValue(meta.key, state.curveSeries[meta.key]?.[index] ?? 0)}</td>
            `).join("")}
          </tr>
        `).join("")}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, columnCount)}
      </tbody>
    </table>`;
  restoreVirtualTableScroll(container, tableKey);
}

function applyHourlyTableEdit(cell) {
  const index = Number(cell.dataset.index);
  const key = cell.dataset.key;
  const meta = curveMetaForKey(key);
  const rawValue = Number(cell.textContent);
  if (!meta || !Number.isFinite(rawValue) || !Number.isInteger(index)) {
    renderHourlyTable(true);
    return;
  }
  const value = roundCurveValue(key, rawValue);
  const values = state.curveSeries[key] || [];
  if (index >= 0 && index < values.length) values[index] = value;
  markCurveDirty(key);
  drawCurves();
  renderHourlyTable();
  $("curveStatus").textContent = "已修改，待保存";
}

function initCurveEditor() {
  const canvas = $("curveEditorChart");
  const table = $("hourlyCurveTable");
  if (!canvas || !table) return;
  let lastPointerDownAt = 0;
  const handleCurvePointerDown = (event) => {
    if (event.type === "pointerdown") {
      lastPointerDownAt = Date.now();
    } else if (Date.now() - lastPointerDownAt < 80) {
      return;
    }
    setCurveCursorFromEvent(event, false);
    if (event.button === 2) {
      event.preventDefault();
      cancelCurveEditSelection();
      return;
    }
    if (event.button !== 0) return;
    const legendKey = curveLegendKeyAtPointer(event);
    if (legendKey) {
      event.preventDefault();
      toggleCurveSeriesVisibility(legendKey, true);
      return;
    }
    const hitKey = curveKeyAtPointer(event);
    if (!hitKey) return;
    event.preventDefault();
    setCurveEditKey(hitKey);
    state.isCurveDragging = true;
    if (event.pointerId !== undefined && canvas.setPointerCapture) {
      canvas.setPointerCapture(event.pointerId);
    }
  };
  const handleCurvePointerMove = (event) => {
    setCurveCursorFromEvent(event, !state.isCurveDragging);
    if (state.isCurveDragging) {
      event.preventDefault();
      applyCurveDrag(event);
    }
  };
  canvas.addEventListener("pointerdown", handleCurvePointerDown);
  canvas.addEventListener("mousedown", handleCurvePointerDown);
  canvas.addEventListener("pointermove", handleCurvePointerMove);
  canvas.addEventListener("mousemove", handleCurvePointerMove);
  canvas.addEventListener("pointerleave", () => {
    if (!state.isCurveDragging) hideCurveCursor();
  });
  canvas.addEventListener("mouseleave", () => {
    if (!state.isCurveDragging) hideCurveCursor();
  });
  canvas.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    cancelCurveEditSelection();
  });
  canvas.addEventListener("pointercancel", cancelCurveEditSelection);
  const handleCurvePointerUp = () => {
    const wasDragging = state.isCurveDragging;
    state.isCurveDragging = false;
    if (wasDragging) renderHourlyTable();
  };
  window.addEventListener("pointerup", handleCurvePointerUp);
  window.addEventListener("mouseup", handleCurvePointerUp);
  $("activeCurve").addEventListener("change", (event) => setActiveCurve(event.target.value));
  window.addEventListener("resize", drawCurves);
  table.addEventListener("blur", (event) => {
    if (event.target.matches("[data-index][data-key]")) {
      applyHourlyTableEdit(event.target);
    }
  }, true);
  table.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches("[data-index][data-key]")) {
      event.preventDefault();
      event.target.blur();
    }
  });
}

function initRuntimeMonitor() {
  const windowSelect = $("runtimeTraceWindow");
  if (windowSelect) {
    state.runtimeTraceWindowMinutes = Number(windowSelect.value) || state.runtimeTraceWindowMinutes;
    windowSelect.addEventListener("change", (event) => {
      state.runtimeTraceWindowMinutes = Number(event.target.value) || 60;
      resetChartPeriodOffsets("runtimeTrace");
      drawRuntimeTraceChart();
    });
  }
  initChartPeriodNavigation("runtimeTrace", runtimeTraceWindowRange, drawRuntimeTraceChart);
  initTraceChartInteractions("runtimeTrace", "runtimeTraceChart", drawRuntimeTraceChart);
  window.addEventListener("resize", drawRuntimeTraceChart);
}

function initMeasurementMonitor() {
  const windowSelect = $("measurementTraceWindow");
  if (windowSelect) {
    state.measurementTraceWindowMinutes = Number(windowSelect.value) || state.measurementTraceWindowMinutes;
    windowSelect.addEventListener("change", (event) => {
      state.measurementTraceWindowMinutes = Number(event.target.value) || 60;
      resetChartPeriodOffsets("measurementTrace");
      drawMeasurementTraceChart();
    });
  }
  initChartPeriodNavigation("measurementTrace", measurementTraceWindowRange, drawMeasurementTraceChart);
  initTraceChartInteractions("measurementTrace", "measurementTraceChart", drawMeasurementTraceChart);
  let measResizeTimer = null;
  window.addEventListener("resize", () => {
    if (measResizeTimer !== null) clearTimeout(measResizeTimer);
    measResizeTimer = setTimeout(() => {
      measResizeTimer = null;
      if (currentPageName() === "measurements") drawMeasurementTraceChart();
    }, 120);
  });
}

async function refresh() {
  if (state.refreshRequestActive) return;
  if (!activeModelServiceRunning()) {
    $("simState").textContent = "stopped";
    if (typeof syncClockTriggerSummary === "function") syncClockTriggerSummary("stopped");
    const solverInfo = $("solverInfo");
    if (solverInfo) solverInfo.textContent = "模拟服务已停止";
    return;
  }
  const requestedModelId = state.activeModelId;
  const switchEpoch = Number(state.modelSwitchEpoch || 0);
  state.refreshRequestActive = true;
  try {
    const activePage = currentPageName();
    const snapshot = await refreshSnapshotPayload(activePage);
    if (state.activeModelId !== requestedModelId || Number(state.modelSwitchEpoch || 0) !== switchEpoch) {
      return;
    }
    const deltaRequests = [];
    if (pageNeedsRuntimeLogDelta(activePage) && !state.embeddedRuntimeLogDeltaReceived) {
      deltaRequests.push(refreshRuntimeLogs(false));
    }
    if (pageNeedsMeasurementDelta(activePage) && !state.embeddedMeasurementDeltaReceived) {
      deltaRequests.push(refreshMeasurementDelta(false));
    }
    await Promise.all(deltaRequests);
    if (state.activeModelId !== requestedModelId || Number(state.modelSwitchEpoch || 0) !== switchEpoch) {
      return;
    }
    state.refreshConsecutiveFailures = 0;
    renderSnapshot(snapshot);
  } catch (error) {
    if (state.activeModelId !== requestedModelId || Number(state.modelSwitchEpoch || 0) !== switchEpoch) {
      return;
    }
    state.refreshConsecutiveFailures = (Number(state.refreshConsecutiveFailures || 0)) + 1;
    const retrySec = Math.round(refreshSchedulerIntervalMs() / 1000);
    console.error("模拟台快照刷新失败", error);
    $("simState").textContent = "offline";
    if (typeof syncClockTriggerSummary === "function") syncClockTriggerSummary("offline");
    const solverInfo = $("solverInfo");
    if (solverInfo) solverInfo.textContent = `连接中断（${retrySec}s 后重试）`;
  } finally {
    if (Number(state.modelSwitchEpoch || 0) === switchEpoch) {
      state.refreshRequestActive = false;
    }
  }
}

function latestRuntimeLog(snapshot, type) {
  const logs = state.runtimeLogs.length ? state.runtimeLogs : (snapshot.runtime_logs || []);
  return [...logs].find((item) => item?.type === type) || null;
}

function logDetailText(log) {
  return Array.isArray(log?.detail) ? log.detail.join(" ") : String(log?.detail || "");
}

function matchedNumber(text, pattern) {
  const match = pattern.exec(text || "");
  return match ? Number(match[1]) : null;
}

function storageSocPercentFromText(text) {
  const directSoc = matchedNumber(text, /储能SOC\s*平均\s*([-+\d.]+)%/);
  if (Number.isFinite(directSoc)) return directSoc;
  const values = [...String(text || "").matchAll(/ESS\.[^=，,\s]+=\s*([-+\d.]+)/g)]
    .map((match) => Number(match[1]))
    .filter((value) => Number.isFinite(value));
  if (!values.length) return null;
  const average = values.reduce((total, value) => total + value, 0) / values.length;
  return average <= 1 ? average * 100 : average;
}

function powerSummaryNumber(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

const OVERVIEW_FLOW_GROUP_DEFINITIONS = [
  { key: "dcWind", category: "generation", region: "dc", color: "#2f9e62" },
  { key: "dcSolar", category: "generation", region: "dc", color: "#2f9e62" },
  { key: "dcGridFollowingStorage", category: "storage", region: "dc", color: "#2f9e62" },
  { key: "dcLoad", category: "load", region: "dc", color: "#bd5656" },
  { key: "fuelCell", category: "fuelCell", region: "hydrogen", color: "#16856a" },
  { key: "hydrogenStorage", category: "hydrogenStorage", region: "hydrogen", color: "#287ea0" },
  { key: "electrolyzer", category: "electrolyzer", region: "hydrogen", color: "#b56a22" },
  { key: "dcGridFormingStorage", category: "storage", region: "forming", color: "#2f9e62" },
  { key: "acGridFormingStorage", category: "storage", region: "forming", color: "#2f9e62" },
  { key: "acdcConverter", category: "converter", region: "bridge", color: "#0a8b8b" },
  { key: "acWind", category: "generation", region: "ac", color: "#2f9e62" },
  { key: "acSolar", category: "generation", region: "ac", color: "#2f9e62" },
  { key: "acGridFollowingStorage", category: "storage", region: "ac", color: "#2f9e62" },
  { key: "acLoad", category: "load", region: "ac", color: "#bd5656" },
  { key: "diesel", category: "generation", region: "ac", color: "#c84f4f" },
];

const OVERVIEW_FLOW_STATUS_LABELS = {
  generation: "发电",
  absorption: "吸收",
  consumption: "用电",
  discharge: "放电",
  charge: "充电",
  dcToAc: "直流送交流",
  acToDc: "交流送直流",
  idle: "待机",
  retired: "退运",
  deadIsland: "死岛",
  unmeasured: "待量测",
  storingHydrogen: "储气",
  releasingHydrogen: "供气",
};

function overviewFallbackFlowGroups(power) {
  return {
    acWind: { power: power.wind },
    dcSolar: { power: power.solar },
    dcGridFormingStorage: { power: power.storage, soc: power.soc },
    acdcConverter: { power: null },
    acLoad: { power: power.load },
    diesel: { power: power.diesel },
  };
}

function overviewFlowState(category, power) {
  if (!Number.isFinite(power)) return { status: "unmeasured", flowDirection: "idle" };
  if (Math.abs(power) <= 1e-9) return { status: "idle", flowDirection: "idle" };
  if (category === "storage") {
    return power > 0
      ? { status: "discharge", flowDirection: "toBus" }
      : { status: "charge", flowDirection: "fromBus" };
  }
  if (category === "load" || category === "electrolyzer") {
    return power > 0
      ? { status: "consumption", flowDirection: "fromBus" }
      : { status: "generation", flowDirection: "toBus" };
  }
  if (category === "converter") {
    return power > 0
      ? { status: "dcToAc", flowDirection: "toAc" }
      : { status: "acToDc", flowDirection: "toDc" };
  }
  return power > 0
    ? { status: "generation", flowDirection: "toBus" }
    : { status: "absorption", flowDirection: "fromBus" };
}

function overviewHydrogenStorageFlowState(gasFlow) {
  if (!Number.isFinite(gasFlow)) return { status: "unmeasured", flowDirection: "idle" };
  if (Math.abs(gasFlow) <= 1e-9) return { status: "idle", flowDirection: "idle" };
  return gasFlow > 0
    ? { status: "releasingHydrogen", flowDirection: "fromTank" }
    : { status: "storingHydrogen", flowDirection: "toTank" };
}

function normalizeOverviewFlowGroups(rawGroups, power) {
  const source = rawGroups && typeof rawGroups === "object" ? { ...rawGroups } : {};
  if (!source.dcLoad && !source.acLoad && source.load && typeof source.load === "object") {
    source.acLoad = source.load;
  }
  const hasStructuredGroups = Object.keys(source).length > 0;
  const fallback = overviewFallbackFlowGroups(power);
  return Object.fromEntries(OVERVIEW_FLOW_GROUP_DEFINITIONS.map((definition) => {
    const data = source[definition.key] && typeof source[definition.key] === "object"
      ? source[definition.key]
      : {};
    const fallbackData = hasStructuredGroups ? {} : (fallback[definition.key] || {});
    const groupPower = powerSummaryNumber(data.power ?? fallbackData.power);
    const gasFlow = powerSummaryNumber(data.gasFlow ?? fallbackData.gasFlow);
    const totalCountValue = Number(data.totalCount);
    const totalCount = Number.isFinite(totalCountValue)
      ? Math.max(0, Math.trunc(totalCountValue))
      : Number.isFinite(groupPower) ? 1 : 0;
    const onlineCountValue = Number(data.onlineCount);
    const onlineCount = Number.isFinite(onlineCountValue)
      ? Math.max(0, Math.trunc(onlineCountValue))
      : totalCount;
    const derived = definition.category === "hydrogenStorage"
      ? overviewHydrogenStorageFlowState(gasFlow)
      : overviewFlowState(definition.category, groupPower);
    const flowDirection = ["toBus", "fromBus", "toAc", "toDc", "toTank", "fromTank", "idle"].includes(data.flowDirection)
      ? data.flowDirection
      : derived.flowDirection;
    const status = String(data.status || derived.status);
    return [definition.key, {
      ...data,
      key: definition.key,
      category: definition.category,
      region: definition.region,
      color: definition.color,
      controlMode: String(data.controlMode ?? fallbackData.controlMode ?? "").trim().toUpperCase(),
      present: totalCount > 0,
      power: groupPower,
      targetPower: powerSummaryNumber(data.targetPower ?? fallbackData.targetPower),
      maxAvailablePower: powerSummaryNumber(data.maxAvailablePower ?? fallbackData.maxAvailablePower),
      gasFlow,
      targetGasFlow: powerSummaryNumber(data.targetGasFlow ?? fallbackData.targetGasFlow),
      gasPressure: powerSummaryNumber(data.gasPressure ?? fallbackData.gasPressure),
      gasQuantity: powerSummaryNumber(data.gasQuantity ?? fallbackData.gasQuantity),
      soc: powerSummaryNumber(data.soc ?? fallbackData.soc),
      totalCount,
      onlineCount,
      retiredCount: Math.max(0, Number(data.retiredCount) || 0),
      deadIslandCount: Math.max(0, Number(data.deadIslandCount) || 0),
      status,
      flowDirection,
    }];
  }));
}

function parsePowerFlowOverview(snapshot) {
  const summary = snapshot.power_summary && typeof snapshot.power_summary === "object"
    ? snapshot.power_summary
    : {};
  const structured = {
    source: String(summary.source || ""),
    wind: powerSummaryNumber(summary.wind),
    solar: powerSummaryNumber(summary.solar),
    diesel: powerSummaryNumber(summary.diesel),
    load: powerSummaryNumber(summary.load),
    storage: powerSummaryNumber(summary.storage),
    storageDischarge: powerSummaryNumber(summary.storageDischarge),
    storageCharge: powerSummaryNumber(summary.storageCharge),
    greenPower: powerSummaryNumber(summary.greenPower),
    soc: powerSummaryNumber(summary.soc),
    generation: powerSummaryNumber(summary.generation),
    consumption: powerSummaryNumber(summary.consumption),
    balance: powerSummaryNumber(summary.balance),
  };
  const log = latestRuntimeLog(snapshot, "潮流计算");
  const text = logDetailText(log);
  const controlText = logDetailText(latestRuntimeLog(snapshot, "控制响应"));
  const soc = storageSocPercentFromText(text);
  const power = {
    log,
    source: structured.source,
    wind: structured.wind ?? matchedNumber(text, /风力发电总功率\s*([-+\d.]+)/),
    solar: structured.solar ?? matchedNumber(text, /光伏发电总功率\s*([-+\d.]+)/),
    diesel: structured.diesel ?? matchedNumber(text, /柴油发电总功率\s*([-+\d.]+)/),
    load: structured.load ?? matchedNumber(text, /负荷用电总功率\s*([-+\d.]+)/),
    storage: structured.storage,
    storageDischarge: structured.storageDischarge ?? matchedNumber(text, /储能发电总功率\s*([-+\d.]+)/),
    storageCharge: structured.storageCharge ?? matchedNumber(text, /储能充电总功率\s*([-+\d.]+)/),
    greenPower: structured.greenPower,
    soc: structured.soc ?? (Number.isFinite(soc) ? soc : storageSocPercentFromText(controlText)),
    generation: structured.generation ?? matchedNumber(text, /电源发电总功率\s*([-+\d.]+)/),
    consumption: structured.consumption ?? matchedNumber(text, /用电及充电总功率\s*([-+\d.]+)/),
    balance: structured.balance ?? matchedNumber(text, /功率差额\s*([-+\d.]+)/),
  };
  power.flowGroups = normalizeOverviewFlowGroups(summary.flowGroups, power);
  return power;
}

function overviewCurveBoundary(snapshot) {
  const boundary = snapshot.curve_boundary || {};
  if (boundary && typeof boundary === "object" && boundary.point) {
    return {
      point: boundary.point || {},
      loadTotal: Number(boundary.load_total ?? boundary.loadTotal ?? 0),
      index: Number(boundary.index) || 0,
    };
  }
  const curves = snapshot.curves || {};
  const weather = Array.isArray(curves.weather) ? curves.weather : [];
  const rawStep = Number(curves.time_step_minutes);
  const step = Number.isFinite(rawStep) && rawStep > 0 ? rawStep : 1;
  const targetMinute = Number(snapshot.clock?.absolute_minute ?? snapshot.clock?.minute ?? 0);
  const index = weather.length ? Math.round(targetMinute / step) % weather.length : 0;
  const point = weather[index] || {};
  const loadTotal = Object.values(curves.loads || {}).reduce((total, points) => {
    if (!Array.isArray(points) || !points.length) return total;
    const loadPoint = points[index % points.length] || {};
    return total + (Number(loadPoint.p_kw ?? loadPoint.value ?? loadPoint.load_kw) || 0);
  }, 0);
  return { point, loadTotal, index };
}

function formatOverviewNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toFixed(2);
}

function hasOverviewNumber(value) {
  return value !== null && value !== undefined && String(value).trim() !== "" && Number.isFinite(Number(value));
}

function overviewPowerText(value) {
  return Number.isFinite(value) ? `${formatOverviewNumber(value)} kW` : "--";
}

function overviewPercentText(value) {
  return Number.isFinite(value) ? `${formatOverviewNumber(value)}%` : "--";
}

function overviewGasFlowText(value) {
  return Number.isFinite(value) ? `${formatOverviewNumber(value)} Nm3/h` : "--";
}

function overviewGasPressureText(value) {
  return Number.isFinite(value) ? `${formatOverviewNumber(value)} MPa` : "--";
}

function overviewGasQuantityText(value) {
  return Number.isFinite(value) ? `${formatOverviewNumber(value)} Nm3` : "--";
}

function overviewGreenGroupPower(groups, key) {
  const group = groups?.[key];
  if (!group || group.present === false) return 0;
  return Number.isFinite(group.power) ? Number(group.power) : null;
}

function overviewGreenMetrics(power = {}) {
  const groups = power.flowGroups || {};
  const dcLoadPower = overviewGreenGroupPower(groups, "dcLoad");
  const acLoadPower = overviewGreenGroupPower(groups, "acLoad");
  const electrolyzerPower = overviewGreenGroupPower(groups, "electrolyzer");
  const dieselPower = overviewGreenGroupPower(groups, "diesel");
  if ([dcLoadPower, acLoadPower, electrolyzerPower, dieselPower].some((value) => value === null)) {
    return { loadPower: null, greenPower: null, greenPowerShare: null };
  }
  const loadPower = dcLoadPower + acLoadPower + electrolyzerPower;
  const greenPower = loadPower - dieselPower;
  return {
    loadPower,
    greenPower,
    greenPowerShare: Math.abs(loadPower) > 1e-9
      ? (greenPower / loadPower) * 100.0
      : null,
  };
}

function overviewFlowPowerValue(value) {
  const number = Math.abs(Number(value));
  return Number.isFinite(number) ? number : 0;
}

