// 教员端前端模块：实时量测表、故障/方式配置与启动引导。

function formatMeasurementValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  if (Math.abs(number) >= 1000) return number.toFixed(2);
  if (Math.abs(number) >= 10) return number.toFixed(3);
  return number.toFixed(5);
}

function measurementPresentationValue(value, row = null) {
  if (value === null || value === undefined || value === "") return value;
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return String(row?.meas_type || "").toUpperCase() === "SOC" ? number * 100 : number;
}

function isWeatherMeasurement(row) {
  return row?.dev_type === "Environment" && row?.dev_name === "weather";
}

function isSignalMeasurement(row) {
  return Object.prototype.hasOwnProperty.call(SIGNAL_MEASUREMENT_LABELS, String(row?.meas_type || "").toUpperCase());
}

function formatMeasurementDisplayValue(value, row = null, analogFormatter = formatMeasurementValue) {
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return isSignalMeasurement(row) ? String(Math.round(number)) : analogFormatter(number);
}

function weatherMeasurementLabel(row) {
  const type = String(row?.meas_type || "").toUpperCase();
  return WEATHER_MEASUREMENT_LABELS[type]?.label || row?.name || type || "气象";
}

function signalMeasurementLabel(row) {
  const type = String(row?.meas_type || "").toUpperCase();
  return SIGNAL_MEASUREMENT_LABELS[type]?.label || row?.name || type || "遥信";
}

function weatherMeasurementOrder(row) {
  const type = String(row?.meas_type || "").toUpperCase();
  return WEATHER_MEASUREMENT_LABELS[type]?.order ?? 99;
}

function signalMeasurementOrder(row) {
  const type = String(row?.meas_type || "").toUpperCase();
  return SIGNAL_MEASUREMENT_LABELS[type]?.order ?? 99;
}

function measurementDisplayName(row) {
  if (isSignalMeasurement(row)) return `${row.dev_type || ""}.${row.dev_name || row.name || ""}.${signalMeasurementLabel(row)}`;
  return isWeatherMeasurement(row) ? `Environment.weather.${weatherMeasurementLabel(row)}` : row.name;
}

function measurementDeviceDisplay(row) {
  return isWeatherMeasurement(row) ? "气象.weather" : `${row.dev_type || "--"}.${row.dev_name || "--"}`;
}

function measurementTypeDisplay(row) {
  if (isSignalMeasurement(row)) return signalMeasurementLabel(row);
  return isWeatherMeasurement(row) ? weatherMeasurementLabel(row) : row.meas_type;
}

function compareMeasurementsForDisplay(left, right) {
  const leftWeather = isWeatherMeasurement(left);
  const rightWeather = isWeatherMeasurement(right);
  if (leftWeather !== rightWeather) return leftWeather ? -1 : 1;
  if (leftWeather && rightWeather) return weatherMeasurementOrder(left) - weatherMeasurementOrder(right);
  const leftSignal = isSignalMeasurement(left);
  const rightSignal = isSignalMeasurement(right);
  if (leftSignal !== rightSignal) return leftSignal ? -1 : 1;
  if (leftSignal && rightSignal) {
    const signalOrder = signalMeasurementOrder(left) - signalMeasurementOrder(right);
    if (signalOrder) return signalOrder;
  }
  const typeCompare = String(left.dev_type || "").localeCompare(String(right.dev_type || ""), "zh-Hans-CN");
  if (typeCompare) return typeCompare;
  const nameCompare = String(left.dev_name || "").localeCompare(String(right.dev_name || ""), "zh-Hans-CN");
  if (nameCompare) return nameCompare;
  return String(left.name || "").localeCompare(String(right.name || ""), "zh-Hans-CN");
}

function sortMeasurementsForDisplay(rows) {
  return [...(rows || [])].sort(compareMeasurementsForDisplay);
}

function measurementCompareRows(measurements = state.snapshot?.measurements || {}) {
  const definitions = state.snapshot?.definitions?.measurement || measurements.definitions || [];
  const primaryRows = definitions.length
    ? definitions
    : (measurements.scada?.length ? measurements.scada : measurements.real || []);
  const realByKey = new Map();
  const scadaByKey = new Map();
  const addRows = (rows, target) => {
    (rows || []).forEach((row) => {
      target.set(measurementKey(row), row);
    });
  };
  addRows(measurements.real, realByKey);
  addRows(measurements.scada, scadaByKey);
  return sortMeasurementsForDisplay(primaryRows.map((definition) => {
    const key = measurementKey(definition);
    const real = realByKey.get(key);
    const scada = scadaByKey.get(key);
    const realValue = real?.value;
    const scadaValue = scada?.value;
    const realNumber = Number(realValue);
    const scadaNumber = Number(scadaValue);
    const diff = Number.isFinite(realNumber) && Number.isFinite(scadaNumber)
      ? scadaNumber - realNumber
      : null;
    return {
      idx: definition.idx,
      name: definition.name,
      dev_type: definition.dev_type,
      dev_name: definition.dev_name,
      meas_type: definition.meas_type,
      weight: definition.weight ?? "--",
      valid: scada?.valid ?? real?.valid ?? definition.valid ?? 0,
      real_value: realValue,
      scada_value: scadaValue,
      diff,
    };
  }));
}

function measurementUnit(measType) {
  const type = String(measType || "").toUpperCase();
  if (WEATHER_MEASUREMENT_LABELS[type]?.unit) return WEATHER_MEASUREMENT_LABELS[type].unit;
  if (type === "SOC" || type === "LEVEL") return "%";
  if (type === "PRESSURE") return "MPa";
  if (type === "FLOW") return "Nm3/h";
  if (type === "GAS_QUANTITY") return "Nm3";
  if (type.startsWith("P")) return "kW";
  if (type.startsWith("Q")) return "kvar";
  if (type.startsWith("V")) return "V";
  if (type.startsWith("I")) return "A";
  return "";
}

function appendMeasurementTrace(snapshot) {
  const sampledClock = snapshot.measurement_clock;
  const clock = sampledClock && Number(sampledClock.step_count ?? 0) > 0
    ? sampledClock
    : snapshot.clock || {};
  if (Number(clock.step_count ?? 0) <= 0) return false;
  const result = snapshot.result || {};
  const summary = snapshot.summary || {};
  const signature = [
    snapshot.model?.id || state.activeModelId,
    clock.absolute_minute ?? clock.minute ?? "",
    clock.time || "",
    result.updated ?? "",
    result.solver_info || "",
    summary.scada_count ?? 0,
  ].join("|");
  if (signature === state.lastMeasurementTraceKey) return false;
  const rows = measurementCompareRows(snapshot.measurements || {});
  if (!rows.some((row) => (
    numberOrNull(row.real_value) !== null
    || numberOrNull(row.scada_value) !== null
  ))) {
    return false;
  }
  state.lastMeasurementTraceKey = signature;
  const point = {
    minute: Number(clock.absolute_minute ?? clock.minute ?? state.measurementTraceHistory.length) || 0,
    sim_time: clock.time || "--",
    record_time: Date.now(),
    run_id: Number(clock.run_id ?? 0) || 0,
    step_count: Number(clock.step_count ?? 0) || 0,
    measurements: {},
  };
  rows.forEach((row) => {
    const key = measurementKey(row);
    point.measurements[key] = {
      name: measurementDisplayName(row) || "",
      dev_type: row.dev_type || "",
      dev_name: row.dev_name || "",
      meas_type: measurementTypeDisplay(row) || "",
      unit: measurementUnit(row.meas_type),
      real: numberOrNull(measurementPresentationValue(row.real_value, row)),
      scada: numberOrNull(measurementPresentationValue(row.scada_value, row)),
      valid: Number(row.valid) === 1 ? 1 : 0,
    };
  });
  const history = state.measurementTraceHistory || [];
  const latestPoint = history[history.length - 1];
  if (latestPoint && compareMeasurementHistoryPoints(point, latestPoint) <= 0) {
    const pointKey = measurementHistoryPointKey(point);
    let existingIndex = -1;
    for (let index = history.length - 1; index >= 0; index -= 1) {
      const candidate = history[index];
      if (measurementHistoryPointKey(candidate) === pointKey) {
        existingIndex = index;
        break;
      }
      if (compareMeasurementHistoryPoints(candidate, point) < 0) break;
    }
    if (existingIndex < 0) return false;
    const existing = history[existingIndex];
    history[existingIndex] = {
      ...existing,
      ...point,
      measurements: {
        ...(existing.measurements || {}),
        ...(point.measurements || {}),
      },
    };
  } else {
    history.push(point);
  }
  state.measurementTraceHistory = history;
  state.measurementTraceHistory = compactTraceHistory(state.measurementTraceHistory, state.measurementTraceWindowMinutes);
  return true;
}

function resetMeasurementHistoryHydration() {
  state.measurementHistoryGeneration = (Number(state.measurementHistoryGeneration) || 0) + 1;
  state.measurementHistoryLoaded = {};
  state.measurementHistoryRequests = {};
}

function measurementHistoryDefinitions(snapshot = state.snapshot || {}) {
  const measurementDefinitions = snapshot.measurements?.definitions;
  if (Array.isArray(measurementDefinitions)) return measurementDefinitions;
  const staticDefinitions = snapshot.definitions?.measurement;
  return Array.isArray(staticDefinitions) ? staticDefinitions : [];
}

function measurementHistoryDefinitionIndex(row, definitions = measurementHistoryDefinitions()) {
  if (!row) return -1;
  const key = measurementKey(row);
  return definitions.findIndex((definition) => measurementKey(definition) === key);
}

function measurementHistoryPointKey(point) {
  return [
    Number(point?.run_id ?? 0) || 0,
    Number(point?.step_count ?? -1),
    Number(point?.minute ?? 0) || 0,
  ].join("|");
}

function compareMeasurementHistoryPoints(left, right) {
  return (
    (Number(left?.run_id) || 0) - (Number(right?.run_id) || 0)
    || (Number(left?.step_count) || 0) - (Number(right?.step_count) || 0)
    || (Number(left?.minute) || 0) - (Number(right?.minute) || 0)
  );
}

function mergeMeasurementHistoryPayload(payload, row, definitionIndex, definitions) {
  if (!payload || payload.encoding !== "measurement-history-arrays-v1") return false;
  const expectedSignature = measurementDefinitionSignature(definitions);
  if (String(payload.definition_signature || "") !== expectedSignature) {
    throw new Error("历史量测定义顺序签名不一致，历史帧已拒绝");
  }
  if (Number(payload.count) !== definitions.length) {
    throw new Error("历史量测定义长度不一致，历史帧已拒绝");
  }
  const currentRunId = Number(state.snapshot?.clock?.run_id ?? 0) || 0;
  const payloadRunId = Number(payload.run_id ?? 0) || 0;
  if (payloadRunId !== currentRunId) return false;
  const indices = Array.isArray(payload.indices) ? payload.indices.map(Number) : [];
  const selectedPosition = indices.indexOf(Number(definitionIndex));
  if (selectedPosition < 0) return false;
  const key = measurementKey(row);
  const incoming = (payload.frames || []).map((frame) => {
    const arrays = [frame.real_values, frame.scada_values, frame.valid_values];
    if (arrays.some((values) => !Array.isArray(values) || values.length !== indices.length)) {
      throw new Error("历史量测数组长度不一致，历史帧已拒绝");
    }
    const minute = Number(frame.absolute_minute);
    if (!Number.isFinite(minute)) throw new Error("历史量测仿真时刻无效，历史帧已拒绝");
    const real = numberOrNull(measurementPresentationValue(frame.real_values[selectedPosition], row));
    const scada = numberOrNull(measurementPresentationValue(frame.scada_values[selectedPosition], row));
    const validValue = frame.valid_values[selectedPosition];
    return {
      minute,
      sim_time: frame.simu_time || "--",
      record_time: frame.wall_time || "",
      run_id: Number(frame.run_id ?? payloadRunId) || payloadRunId,
      step_count: Number(frame.step_count ?? 0) || 0,
      history_seq: Number(frame.seq ?? 0) || 0,
      measurements: {
        [key]: {
          name: measurementDisplayName(row) || "",
          dev_type: row.dev_type || "",
          dev_name: row.dev_name || "",
          meas_type: measurementTypeDisplay(row) || "",
          unit: measurementUnit(row.meas_type),
          value: scada ?? real,
          real,
          scada,
          valid: validValue === null || validValue === undefined
            ? (Number(row.valid) === 1 ? 1 : 0)
            : (Number(validValue) === 1 ? 1 : 0),
        },
      },
    };
  });
  if (!incoming.length) return false;

  const merged = new Map();
  (state.measurementTraceHistory || []).forEach((point) => {
    merged.set(measurementHistoryPointKey(point), point);
  });
  incoming.forEach((point) => {
    const pointKey = measurementHistoryPointKey(point);
    const existing = merged.get(pointKey);
    if (existing) {
      existing.measurements = { ...(existing.measurements || {}), ...point.measurements };
      if (!existing.sim_time || existing.sim_time === "--") existing.sim_time = point.sim_time;
      if (!existing.record_time) existing.record_time = point.record_time;
      existing.run_id = point.run_id;
      existing.step_count = point.step_count;
      existing.history_seq = point.history_seq;
    } else {
      merged.set(pointKey, point);
    }
  });
  state.measurementTraceHistory = compactTraceHistory(
    Array.from(merged.values()).sort(compareMeasurementHistoryPoints),
    state.measurementTraceWindowMinutes,
  );
  return true;
}

async function ensureMeasurementHistoryForRow(row) {
  const definitions = measurementHistoryDefinitions();
  const definitionIndex = measurementHistoryDefinitionIndex(row, definitions);
  if (definitionIndex < 0 || !definitions.length) return false;
  const runId = Number(state.snapshot?.clock?.run_id ?? 0) || 0;
  const definitionSignature = measurementDefinitionSignature(definitions);
  const generation = Number(state.measurementHistoryGeneration) || 0;
  const requestKey = [state.activeModelId, runId, definitionSignature, definitionIndex, generation].join("|");
  if (state.measurementHistoryLoaded?.[requestKey]) return false;
  if (state.measurementHistoryRequests?.[requestKey]) {
    return state.measurementHistoryRequests[requestKey];
  }
  const request = api(`/api/measurement-history?indices=${definitionIndex}`)
    .then((payload) => {
      const currentDefinitions = measurementHistoryDefinitions();
      const currentRunId = Number(state.snapshot?.clock?.run_id ?? 0) || 0;
      if (
        (Number(state.measurementHistoryGeneration) || 0) !== generation
        ||
        currentRunId !== runId
        || measurementDefinitionSignature(currentDefinitions) !== definitionSignature
      ) {
        return false;
      }
      const changed = mergeMeasurementHistoryPayload(payload, row, definitionIndex, currentDefinitions);
      state.measurementHistoryLoaded[requestKey] = true;
      return changed;
    })
    .catch((error) => {
      console.warn("历史量测加载失败", error);
      return false;
    })
    .finally(() => {
      delete state.measurementHistoryRequests[requestKey];
    });
  state.measurementHistoryRequests[requestKey] = request;
  return request;
}

function ensureSelectedMeasurementHistory() {
  if (currentPageName() !== "measurements") return;
  const row = selectedMeasurementRow();
  if (!row) return;
  ensureMeasurementHistoryForRow(row).then((changed) => {
    if (changed && measurementKey(row) === state.selectedMeasurementKey && currentPageName() === "measurements") {
      drawMeasurementTraceChart();
    }
  });
}

function ensureSelectedMeasurementKey(rows, fallbackRows = []) {
  const availableRows = rows.length ? rows : fallbackRows;
  const availableKeys = new Set(availableRows.map((row) => measurementKey(row)));
  if (state.selectedMeasurementKey && availableKeys.has(state.selectedMeasurementKey)) {
    return state.selectedMeasurementKey;
  }
  state.selectedMeasurementKey = availableRows.length ? measurementKey(availableRows[0]) : "";
  return state.selectedMeasurementKey;
}

function selectedMeasurementRow(rows = measurementCompareRows()) {
  if (!state.selectedMeasurementKey) return null;
  return rows.find((row) => measurementKey(row) === state.selectedMeasurementKey) || null;
}

function setSelectedMeasurementKey(key) {
  state.selectedMeasurementKey = key || "";
  renderMeasurementCompareTable();
  ensureSelectedMeasurementHistory();
}

function measurementTraceWindowRange() {
  const history = state.measurementTraceHistory || [];
  const windowMinutes = Math.max(1, Number(state.measurementTraceWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  const range = alignedTraceWindowRange(
    history,
    windowMinutes,
    fallbackMinute,
    chartPeriodOffset("measurementTrace"),
    simulationModeDurationMinutes(),
  );
  setChartPeriodOffset("measurementTrace", range.windowOffset);
  return range;
}

function measurementTraceWindowPoints(key = state.selectedMeasurementKey, range = measurementTraceWindowRange()) {
  if (!key) return [];
  const points = (state.measurementTraceHistory || [])
    .map((point) => {
      const measurement = point.measurements[key];
      if (!measurement) return null;
      return {
        minute: point.minute,
        sim_time: point.sim_time,
        real: measurement.real,
        scada: measurement.scada,
        unit: measurement.unit || "",
      };
    })
    .filter(Boolean);
  return traceWindowRealPoints(points, range);
}

function resizeMeasurementTraceCanvas() {
  const canvas = $("measurementTraceChart");
  return resizeCanvasToRenderedSize(canvas, 900, 260);
}

function drawMeasurementTraceChart() {
  const canvas = $("measurementTraceChart");
  if (!canvas) return;
  resizeMeasurementTraceCanvas();
  const chartKey = "measurementTrace";
  const { ctx, width, height } = prepareCanvas2D(canvas, 900, 260);
  const plot = width < 640
    ? { left: 42, right: 14, top: 28, bottom: 32 }
    : { left: 58, right: 24, top: 28, bottom: 36 };
  const left = plot.left;
  const right = width - plot.right;
  const top = plot.top;
  const bottom = height - plot.bottom;
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };
  const range = measurementTraceWindowRange();
  syncChartPeriodNavigation("measurementTrace", range);
  const allRows = measurementCompareRows();
  const selectedRow = selectedMeasurementRow(allRows);
  const points = measurementTraceWindowPoints(state.selectedMeasurementKey, range);
  const seriesDefs = [
    { key: "real", field: "real", label: "真值", color: "#008c8c" },
    { key: "scada", field: "scada", label: "量测值", color: "#c93a3a" },
  ];
  const visibleSeries = visibleChartSeries(chartKey, seriesDefs);
  const values = points.flatMap((point) => visibleSeries.map((series) => point[series.field]))
    .filter((value) => value !== null && Number.isFinite(value));
  const palette = chartThemePalette();
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = palette.grid;
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei, Arial";
  ctx.fillStyle = palette.text;
  for (let i = 0; i <= 4; i += 1) {
    const y = top + i * ((bottom - top) / 4);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  const xTicks = runtimeTraceAxisTicks(range, width);
  xTicks.forEach((minute, tickIndex) => {
    const ratio = (minute - range.startMinute) / range.windowMinutes;
    const x = left + ratio * (right - left);
    ctx.strokeStyle = tickIndex === xTicks.length - 1 ? palette.axis : palette.gridSubtle;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.fillStyle = palette.text;
    ctx.textAlign = tickIndex === xTicks.length - 1 ? "right" : "left";
    const textOffset = tickIndex === 0 ? 0 : tickIndex === xTicks.length - 1 ? 0 : 4;
    ctx.fillText(runtimeAxisTickLabel(minute, range, tickIndex, xTicks.length - 1), x + textOffset, height - 12);
  });
  const label = selectedRow ? measurementDisplayName(selectedRow) : "请选择测点";
  $("measurementTraceSummary").textContent = `${label} · ${traceWindowDataPointCount(points)} 点`;
  if (!selectedRow || !points.length || !visibleSeries.length || !values.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = palette.text;
    ctx.textAlign = "center";
    const emptyMsg = !visibleSeries.length ? "所有曲线已隐藏" : "暂无跟踪数据";
    ctx.fillText(typeof translatePhrase === "function" ? translatePhrase(emptyMsg) : emptyMsg, width / 2, height / 2);
    ctx.textAlign = "left";
    return;
  }
  let minValue = Math.min(...values);
  let maxValue = Math.max(...values);
  if (Math.abs(maxValue - minValue) < 1e-9) {
    minValue -= 1;
    maxValue += 1;
  }
  const padding = (maxValue - minValue) * 0.12;
  minValue -= padding;
  maxValue += padding;
  const xForMinute = (minute) => left + ((minute - range.startMinute) / range.windowMinutes) * (right - left);
  const yForValue = (value) => bottom - ((value - minValue) / (maxValue - minValue)) * (bottom - top);
  const hitData = [];
  const unit = points.find((point) => point.unit)?.unit || measurementUnit(selectedRow.meas_type);
  const selectedSeries = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const drawSeries = (series, widthScale = 2.5) => {
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = series.key === selectedSeries ? widthScale + 1.2 : widthScale;
    ctx.beginPath();
    let started = false;
    let previousMinute = null;
    points.forEach((point) => {
      const value = numberOrNull(point[series.field]);
      if (value === null) return;
      const x = xForMinute(point.minute);
      const y = yForValue(value);
      pixelPoints.push({
        x,
        y,
        minute: point.minute,
        time: point.sim_time || point.time,
        sim_time: point.sim_time || point.time,
        value,
      });
      const restartPath = started && previousMinute !== null && point.minute <= previousMinute;
      if (restartPath) {
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(x, y);
      } else if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
      previousMinute = point.minute;
    });
    if (started) ctx.stroke();
    hitData.push({ ...series, unit, points: pixelPoints });
  };
  visibleSeries.forEach((series) => drawSeries(series, series.key === "scada" ? 2 : 2.5));
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    timeLabel: (point) => runtimeTracePointTimeLabel(point, range),
    valueFormatter: formatMeasurementValue,
  });
  ctx.fillStyle = palette.text;
  ctx.textAlign = "left";
  ctx.fillText(formatMeasurementValue(maxValue), 8, top + 4);
  ctx.fillText(formatMeasurementValue(minValue), 8, bottom);
  if (unit) ctx.fillText(unit, left, 18);
}

function measurementCompareDevices(rows = measurementCompareRows()) {
  const devices = new Map();
  rows.forEach((row) => {
    if (!row.dev_type || !row.dev_name) return;
    const key = deviceKey(row);
    const entry = devices.get(key) || { dev_type: row.dev_type, dev_name: row.dev_name, count: 0 };
    entry.count += 1;
    devices.set(key, entry);
  });
  return Array.from(devices.values()).sort((left, right) => {
    if (left.dev_type === "Environment" && right.dev_type !== "Environment") return -1;
    if (left.dev_type !== "Environment" && right.dev_type === "Environment") return 1;
    const typeCompare = String(left.dev_type).localeCompare(String(right.dev_type));
    return typeCompare || String(left.dev_name).localeCompare(String(right.dev_name));
  });
}

function filteredMeasurementCompareRows(rows = measurementCompareRows()) {
  const filter = state.measurementCompareFilter || { dev_type: "all", dev_name: "" };
  return rows.filter((row) => deviceFilterMatches(row, filter));
}

function measurementCompareTypeFilterLabel(row) {
  return measurementTypeDisplay(row) || row?.meas_type || "";
}

function measurementCompareFilterFields(row) {
  return [
    measurementDisplayName(row),
    measurementDeviceDisplay(row),
    measurementCompareTypeFilterLabel(row),
    row?.name,
    row?.idx,
    row?.dev_type,
    row?.dev_name,
    row?.meas_type,
  ];
}

function syncMeasurementCompareTypeFilter(rows) {
  syncTableKeywordFilter("measurementCompareKeywordFilter", state.measurementCompareKeywordFilter);
  syncTableTypeFilter(
    "measurementCompareTypeFilter",
    "measurementCompareTypeFilter",
    tableFilterTypeOptions(rows, measurementCompareTypeFilterLabel),
  );
}

function applyMeasurementCompareTableFilters(rows) {
  const keyword = state.measurementCompareKeywordFilter || "";
  const type = state.measurementCompareTypeFilter || "all";
  return (rows || []).filter((row) => {
    if (!tableFilterMatchesKeyword(measurementCompareFilterFields(row), keyword)) return false;
    if (type !== "all" && measurementCompareTypeFilterLabel(row) !== type) return false;
    return true;
  });
}

function measurementTelemetryRows(rows) {
  return (rows || []).filter((row) => !isSignalMeasurement(row));
}

function measurementSignalRows(rows) {
  return (rows || []).filter((row) => isSignalMeasurement(row));
}

function setMeasurementCompareTab(tabName) {
  state.activeMeasurementCompareTab = tabName === "signal" ? "signal" : "telemetry";
  renderMeasurementCompareTable();
  drawMeasurementTraceChart();
}

function activeMeasurementCompareRows(rows) {
  return state.activeMeasurementCompareTab === "signal"
    ? measurementSignalRows(rows)
    : measurementTelemetryRows(rows);
}

function renderMeasurementCompareTabs(telemetryRows, signalRows) {
  const activeTab = state.activeMeasurementCompareTab === "signal" ? "signal" : "telemetry";
  const tabs = [
    { key: "telemetry", label: "遥测", count: telemetryRows.length },
    { key: "signal", label: "遥信", count: signalRows.length },
  ];
  return `
    <div class="measurement-type-tabs" role="tablist" aria-label="量测类型">
      ${tabs.map((tab) => `
        <button
          type="button"
          role="tab"
          class="measurement-type-tab ${activeTab === tab.key ? "is-active" : ""}"
          data-measurement-compare-tab="${tab.key}"
          aria-selected="${activeTab === tab.key ? "true" : "false"}"
        >
          <span>${tab.label}</span>
          <strong>${tab.count}</strong>
        </button>
      `).join("")}
    </div>
  `;
}

function measurementCompareTableStructureKey(rows) {
  const filter = state.measurementCompareFilter || { dev_type: "all", dev_name: "" };
  return [
    state.activeMeasurementCompareTab || "telemetry",
    deviceTreeFilterSelection(filter).map((item) => deviceTreeFilterKey(item.dev_type, item.dev_name)).join("|"),
    state.measurementCompareKeywordFilter || "",
    state.measurementCompareTypeFilter || "all",
    rows.map((row) => measurementKey(row)).join("||"),
  ].join("::");
}

function measurementLiveCellHtml(row, field) {
  if (field === "real") return formatMeasurementDisplayValue(measurementPresentationValue(row.real_value, row), row);
  if (field === "scada") return formatMeasurementDisplayValue(measurementPresentationValue(row.scada_value, row), row);
  if (field === "weight") return escapeHtml(row.weight);
  if (field === "status") {
    const valid = Number(row.valid) === 1;
    return `<span class="status-dot ${valid ? "on" : ""}"></span>${valid ? "有效" : "无效"}`;
  }
  if (field === "diff") return formatMeasurementDisplayValue(measurementPresentationValue(row.diff, row), row);
  return "";
}

function updateMeasurementCompareTableLiveCells(rows, selectedKey) {
  const tableRows = Array.from(document.querySelectorAll("#measurementCompareTable [data-measurement-row-key]"));
  if (tableRows.length !== rows.length) return false;
  const rowsByKey = new Map(rows.map((row) => [measurementKey(row), row]));
  for (const tableRow of tableRows) {
    const key = tableRow.dataset.measurementRowKey || "";
    const row = rowsByKey.get(key);
    if (!row) return false;
    const selected = key === selectedKey;
    const isAbnormal = !Number(row.valid ?? 1) || (row.status && String(row.status) !== "normal" && String(row.status) !== "正常");
    tableRow.classList.toggle("is-selected", selected);
    tableRow.classList.toggle("is-row-abnormal", Boolean(isAbnormal));
    tableRow.setAttribute("aria-selected", selected ? "true" : "false");
    tableRow.querySelectorAll("[data-measurement-live-field]").forEach((cell) => {
      const field = cell.dataset.measurementLiveField || "";
      const nextHtml = measurementLiveCellHtml(row, field);
      if (cell.dataset.lastHtml !== nextHtml) {
        cell.dataset.lastHtml = nextHtml;
        cell.innerHTML = nextHtml;
      }
      if (field === "diff") {
        const diffActive = row.diff !== null && Math.abs(row.diff) >= 1e-6;
        cell.classList.toggle("diff-active", diffActive);
        cell.classList.toggle("diff-neutral", !diffActive);
      }
    });
  }
  return true;
}

function renderMeasurementCompareDeviceTree(rows = measurementCompareRows()) {
  const container = $("measurementCompareDeviceTree");
  if (!container) return;
  const devices = measurementCompareDevices(rows);
  const filter = state.measurementCompareFilter || { dev_type: "all", dev_name: "" };
  const groupEntries = groupedByDeviceType(devices);
  const treeResult = filterDeviceTreeGroups(groupEntries, "measurement");
  $("measurementCompareTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-measurement-tree-type="all"
      data-measurement-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("measurement", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
          data-measurement-tree-type="${escapeHtml(devType)}"
          data-measurement-tree-name=""
          ${deviceTreeTypeAttrs("measurement", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((item) => `
            <button
              type="button"
              class="tree-node tree-child ${isDeviceTreeNodeActive(filter, item.dev_type, item.dev_name) ? "is-active" : ""}"
              data-measurement-tree-type="${escapeHtml(item.dev_type)}"
              data-measurement-tree-name="${escapeHtml(item.dev_name)}"
            >
              <span>${escapeHtml(item.dev_type === "Environment" && item.dev_name === "weather" ? "气象" : item.dev_name)}</span>
              <small>${escapeHtml(item.count)}点</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
}

function setMeasurementCompareFilter(devType, devName = "", event = null, button = null) {
  state.measurementCompareFilter = updateDeviceTreeFilterSelection(
    "measurementCompareFilter",
    devType,
    devName,
    event,
    "measurement",
    button,
  );
  renderMeasurementCompareTable();
}

function exportSimulatorMeasurementsCsv() {
  const allRows = measurementCompareRows();
  const filteredRows = filteredMeasurementCompareRows(allRows);
  let tableFilteredRows = applyMeasurementCompareTableFilters(filteredRows);
  if (state.measurementCompareOnlyAbnormal) {
    tableFilteredRows = tableFilteredRows.filter(
      (row) => Number(row.valid) !== 1 || String(row.status || "normal") !== "normal",
    );
  }
  const rows = activeMeasurementCompareRows(tableFilteredRows);
  if (!rows.length) {
    showUiToast("当前筛选下无可导出的量测数据", "warn");
    return;
  }
  const csvCell = (val) => `"${String(val ?? "").replace(/"/g, '""')}"`;
  const lines = [
    ["量测名称", "设备", "量测类型", "真值", "量测值", "偏差", "有效性", "状态"].map(csvCell).join(","),
    ...rows.map((row) => [
      measurementDisplayName(row),
      row.device_display || `${row.dev_type || ""}/${row.dev_name || ""}`,
      row.meas_type || "",
      row.real_value ?? "",
      row.scada_value ?? "",
      row.diff ?? "",
      Number(row.valid) === 1 ? "有效" : "无效",
      row.status || "normal",
    ].map(csvCell).join(",")),
  ];
  const blob = new Blob([`\uFEFF${lines.join("\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `simulator-measurements-${state.activeModelId || "model"}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  showUiToast(`已导出 ${rows.length} 条量测比对记录`, "ok", 2200);
}

function renderMeasurementCompareTable() {
  const container = $("measurementCompareTable");
  if (!container) return;
  const allRows = measurementCompareRows();
  renderMeasurementCompareDeviceTree(allRows);
  const filteredRows = filteredMeasurementCompareRows(allRows);
  syncMeasurementCompareTypeFilter(filteredRows);
  let tableFilteredRows = applyMeasurementCompareTableFilters(filteredRows);
  if (state.measurementCompareOnlyAbnormal) {
    tableFilteredRows = tableFilteredRows.filter(
      (row) => Number(row.valid) !== 1 || String(row.status || "normal") !== "normal",
    );
  }
  const telemetryRows = measurementTelemetryRows(tableFilteredRows);
  const signalRows = measurementSignalRows(tableFilteredRows);
  const rows = activeMeasurementCompareRows(tableFilteredRows);
  const selectedKey = ensureSelectedMeasurementKey(rows, []);
  const validCount = rows.filter((row) => Number(row.valid) === 1).length;
  const activeLabel = state.activeMeasurementCompareTab === "signal" ? "遥信" : "遥测";
  const filterActive = Boolean(state.measurementCompareOnlyAbnormal)
    || tableFilterIsActive(state.measurementCompareKeywordFilter, state.measurementCompareTypeFilter);
  $("measurementCompareSummary").textContent = filterActive
    ? `${activeLabel} ${rows.length}/${tableFilteredRows.length} 点 · 有效 ${validCount} 点 · 过滤 ${tableFilteredRows.length}/${filteredRows.length} 点`
    : `${activeLabel} ${rows.length}/${filteredRows.length} 点 · 有效 ${validCount} 点`;
  const tabHtml = renderMeasurementCompareTabs(telemetryRows, signalRows);
  const virtualRows = virtualTableWindow("measurementCompare", rows);
  const structureKey = [
    measurementCompareTableStructureKey(rows),
    virtualRows.enabled ? "virtual" : "full",
    virtualRows.start,
    virtualRows.end,
  ].join("|");
  if (!allRows.length) {
    container.dataset.measurementStructureKey = "";
    container.innerHTML = `${tabHtml}<div class="measurement-type-tab-page is-active"><div class="empty-state">暂无实时量测数据</div></div>`;
    drawMeasurementTraceChart();
    return;
  }
  if (!filteredRows.length) {
    container.dataset.measurementStructureKey = "";
    container.innerHTML = `${tabHtml}<div class="measurement-type-tab-page is-active"><div class="empty-state">当前筛选无量测</div></div>`;
    drawMeasurementTraceChart();
    return;
  }
  if (!tableFilteredRows.length) {
    container.dataset.measurementStructureKey = "";
    container.innerHTML = `${tabHtml}<div class="measurement-type-tab-page is-active"><div class="empty-state">当前过滤无量测</div></div>`;
    drawMeasurementTraceChart();
    return;
  }
  if (!rows.length) {
    container.dataset.measurementStructureKey = "";
    container.innerHTML = `${tabHtml}<div class="measurement-type-tab-page is-active"><div class="empty-state">当前分类无量测</div></div>`;
    drawMeasurementTraceChart();
    return;
  }
  if (
    container.dataset.measurementStructureKey === structureKey
    && updateMeasurementCompareTableLiveCells(virtualRows.rows, selectedKey)
  ) {
    drawMeasurementTraceChart();
    return;
  }
  container.dataset.measurementStructureKey = structureKey;
  container.innerHTML = `
    ${tabHtml}
    <div class="measurement-type-tab-page is-active">
    <div class="virtual-table-scroll" data-virtual-table="measurementCompare">
    <table class="measurement-compare-table">
      <thead>
        <tr>
          <th>量测名称</th>
          <th>设备</th>
          <th>量测类型</th>
          <th class="numeric-cell">真值</th>
          <th class="numeric-cell">量测值</th>
          <th class="numeric-cell">偏差</th>
          <th class="numeric-cell">权重</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, 8)}
        ${virtualRows.rows.map((row) => {
          const diffClass = row.diff === null || Math.abs(row.diff) < 1e-6 ? "diff-neutral" : "diff-active";
          const key = measurementKey(row);
          return `
            <tr
              class="${key === selectedKey ? "is-selected" : ""}"
              data-measurement-row-key="${escapeHtml(key)}"
              data-measurement-select-key="${escapeHtml(key)}"
              tabindex="0"
              aria-selected="${key === selectedKey ? "true" : "false"}"
            >
              <td>${escapeHtml(measurementDisplayName(row) || "--")}</td>
              <td>${escapeHtml(measurementDeviceDisplay(row))}</td>
              <td>${escapeHtml(measurementTypeDisplay(row) || "--")}</td>
              <td class="numeric-cell" data-measurement-live-field="real">${formatMeasurementDisplayValue(measurementPresentationValue(row.real_value, row), row)}</td>
              <td class="numeric-cell" data-measurement-live-field="scada">${formatMeasurementDisplayValue(measurementPresentationValue(row.scada_value, row), row)}</td>
              <td class="numeric-cell ${diffClass}" data-measurement-live-field="diff">${formatMeasurementDisplayValue(measurementPresentationValue(row.diff, row), row)}</td>
              <td class="numeric-cell" data-measurement-live-field="weight">${escapeHtml(row.weight)}</td>
              <td data-measurement-live-field="status"><span class="status-dot ${Number(row.valid) === 1 ? "on" : ""}"></span>${Number(row.valid) === 1 ? "有效" : "无效"}</td>
            </tr>
          `;
        }).join("")}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, 8)}
      </tbody>
    </table>
    </div>
    </div>`;
  restoreVirtualTableScroll(container, "measurementCompare");
  drawMeasurementTraceChart();
}

function renderDevices(devices) {
  $("deviceTable").innerHTML = `
    <table>
      <thead><tr><th>设备</th><th>类型</th><th>投运</th><th>状态</th><th>模式</th><th>设值</th></tr></thead>
      <tbody>
        ${devices.slice(0, 12).map((dev) => `
          <tr>
            <td>${dev.dev_name}</td>
            <td>${dev.dev_type}</td>
            <td><span class="status-dot ${dev.run_stat ? "on" : ""}"></span>${dev.run_stat ? "投入" : "退出"}</td>
            <td>${dev.status ? "闭合/可用" : "断开/故障"}</td>
            <td>${dev.mode || "--"}</td>
            <td>${Object.entries(dev.set_values || {}).map(([k, v]) => `${k}=${v}`).join(" ") || "--"}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function setFaultTab(tabName) {
  state.activeFaultTab = tabName;
  document.querySelectorAll("[data-fault-tab]").forEach((button) => {
    const active = button.dataset.faultTab === tabName;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-fault-panel]").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.faultPanel === tabName);
  });
}

function deviceKey(dev) {
  return `${dev.dev_type}|${dev.dev_name}`;
}

function measurementKey(meas) {
  return `${meas.name}|${meas.dev_type}|${meas.dev_name}|${meas.meas_type}`;
}

function faultDevices() {
  return state.snapshot?.devices || [];
}

function faultMeasurements() {
  const measurements = state.snapshot?.measurements || {};
  return measurements.scada?.length
    ? measurements.scada
    : measurements.definitions?.length
      ? measurements.definitions
      : measurements.real || [];
}

function findDeviceFault(dev) {
  return state.deviceFaults.find((fault) => fault.dev_type === dev.dev_type && fault.dev_name === dev.dev_name);
}

function findMeasurementFault(meas) {
  return state.measurementFaults.find((fault) => measurementFaultMatches(fault, meas));
}

function measurementFaultMatches(fault, meas) {
    if (fault.dev_type && fault.dev_type !== meas.dev_type) return false;
    if (fault.dev_name && fault.dev_name !== meas.dev_name) return false;
    if (fault.meas_type && String(fault.meas_type).toUpperCase() !== String(meas.meas_type).toUpperCase()) return false;
    const target = fault.target || fault.name || "";
    return !target || target === meas.name || target === meas.dev_name || target === measurementKey(meas);
}

function ensureDeviceFault(dev) {
  let fault = findDeviceFault(dev);
  if (!fault) {
    fault = {
      dev_type: dev.dev_type,
      dev_name: dev.dev_name,
      start_minute: 60,
      clear_minute: 120,
      start_day: 1,
      clear_day: 2,
      run_stat: 0,
      status: 0,
    };
    state.deviceFaults.push(fault);
  }
  return fault;
}

function ensureMeasurementFault(meas) {
  let fault = findMeasurementFault(meas);
  if (!fault) {
    fault = {
      name: meas.name,
      target: meas.name,
      dev_type: meas.dev_type,
      dev_name: meas.dev_name,
      meas_type: meas.meas_type,
      fault_type: "dead",
      start_minute: 180,
      clear_minute: 240,
      start_day: 1,
      clear_day: 2,
      median: meas.value ?? 0,
      bias: 0,
    };
    state.measurementFaults.push(fault);
  }
  return fault;
}

function deviceTreeBadge(dev) {
  const raw = dev.raw || {};
  return String(dev.mode || raw.control_type || raw.ctrl_mode || (Number(dev.run_stat ?? 1) !== 0 ? "投" : "退"));
}

function groupedByDeviceType(items) {
  const groups = new Map();
  items.forEach((item) => {
    const devType = item.dev_type || "未分类";
    const list = groups.get(devType) || [];
    list.push(item);
    groups.set(devType, list);
  });
  return Array.from(groups.entries())
    .map(([devType, list]) => [
      devType,
      list.sort((left, right) => String(left.dev_name || left.name || "").localeCompare(String(right.dev_name || right.name || ""))),
    ])
    .sort(([left], [right]) => {
      if (left === "Environment" && right !== "Environment") return -1;
      if (left !== "Environment" && right === "Environment") return 1;
      return String(left).localeCompare(String(right));
    });
}

function filteredFaultDevices() {
  const filter = state.faultDeviceFilter || { dev_type: "all", dev_name: "" };
  return faultDevices()
    .map((dev, index) => ({ dev, index }))
    .filter(({ dev }) => deviceFilterMatches(dev, filter));
}

function filteredFaultMeasurements() {
  const filter = state.faultMeasurementFilter || { dev_type: "all", dev_name: "", key: "" };
  return faultMeasurements()
    .map((meas, index) => ({ meas, index }))
    .filter(({ meas }) => {
      if (!deviceFilterMatches(meas, filter)) return false;
      if (filter.key && measurementKey(meas) !== filter.key) return false;
      return true;
    });
}

function faultMeasurementDevices(measurements = faultMeasurements()) {
  const devices = new Map();
  measurements.forEach((meas) => {
    if (!meas.dev_type || !meas.dev_name) return;
    const key = deviceKey(meas);
    const entry = devices.get(key) || { dev_type: meas.dev_type, dev_name: meas.dev_name, count: 0 };
    entry.count += 1;
    devices.set(key, entry);
  });
  return Array.from(devices.values()).sort((left, right) => {
    const typeCompare = String(left.dev_type).localeCompare(String(right.dev_type));
    return typeCompare || String(left.dev_name).localeCompare(String(right.dev_name));
  });
}

function renderFaultDeviceTree() {
  const container = $("faultDeviceTree");
  if (!container) return;
  const devices = faultDevices();
  const filter = state.faultDeviceFilter || { dev_type: "all", dev_name: "" };
  const groupEntries = groupedByDeviceType(devices);
  const treeResult = filterDeviceTreeGroups(groupEntries, "faultDevice");
  $("faultDeviceTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-fault-device-tree-type="all"
      data-fault-device-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("faultDevice", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
          data-fault-device-tree-type="${escapeHtml(devType)}"
          data-fault-device-tree-name=""
          ${deviceTreeTypeAttrs("faultDevice", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => `
            <button
              type="button"
              class="tree-node tree-child ${isDeviceTreeNodeActive(filter, dev.dev_type, dev.dev_name) ? "is-active" : ""}"
              data-fault-device-tree-type="${escapeHtml(dev.dev_type)}"
              data-fault-device-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span>${escapeHtml(dev.dev_name)}</span>
              <small>${escapeHtml(deviceTreeBadge(dev))}</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
}

function renderFaultMeasurementTree() {
  const container = $("faultMeasurementTree");
  if (!container) return;
  const measurements = faultMeasurements();
  const devices = faultMeasurementDevices(measurements);
  const filter = state.faultMeasurementFilter || { dev_type: "all", dev_name: "", key: "" };
  const groupEntries = groupedByDeviceType(devices);
  const treeResult = filterDeviceTreeGroups(groupEntries, "faultMeasurement");
  $("faultMeasurementTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-fault-measurement-tree-type="all"
      data-fault-measurement-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("faultMeasurement", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
          data-fault-measurement-tree-type="${escapeHtml(devType)}"
          data-fault-measurement-tree-name=""
          ${deviceTreeTypeAttrs("faultMeasurement", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => `
            <button
              type="button"
              class="tree-node tree-child ${isDeviceTreeNodeActive(filter, dev.dev_type, dev.dev_name) ? "is-active" : ""}"
              data-fault-measurement-tree-type="${escapeHtml(dev.dev_type)}"
              data-fault-measurement-tree-name="${escapeHtml(dev.dev_name)}"
            >
              <span>${escapeHtml(dev.dev_name)}</span>
              <small>${escapeHtml(dev.count)}点</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
}

function setDeviceFaultFilter(devType, devName = "", event = null, button = null) {
  state.faultDeviceFilter = updateDeviceTreeFilterSelection(
    "faultDeviceFilter",
    devType,
    devName,
    event,
    "faultDevice",
    button,
  );
  renderFaults(true);
}

function setMeasurementFaultFilter(devType, devName = "", event = null, button = null) {
  state.faultMeasurementFilter = {
    ...updateDeviceTreeFilterSelection(
      "faultMeasurementFilter",
      devType,
      devName,
      event,
      "faultMeasurement",
      button,
    ),
    key: "",
  };
  renderFaults(true);
}

function renderFaults(force = false) {
  const activeEditor = document.activeElement?.closest?.("#deviceFaultTable, #measurementFaultTable");
  if (!force && activeEditor) return;
  renderFaultDeviceTree();
  renderDeviceFaultTable();
  renderFaultMeasurementTree();
  renderMeasurementFaultTable();
}

function faultWindowFields() {
  if (isExtendedSimulationMode()) {
    const isYearMode = state.curveMode === "year";
    const dayCount = simulationModeDayCount();
    return {
      startField: "start_day",
      clearField: "clear_day",
      startLabel: "故障启始日",
      clearLabel: "结束日",
      inputType: isYearMode ? "text" : "number",
      min: isYearMode ? "" : "1",
      max: isYearMode ? "" : String(dayCount),
      step: isYearMode ? "" : "1",
      placeholder: isYearMode ? "1月1日" : `1-${dayCount}`,
      deviceStart: 1,
      deviceClear: 2,
      measurementStart: 1,
      measurementClear: 2,
    };
  }
  return {
    startField: "start_minute",
    clearField: "clear_minute",
    startLabel: "故障启始时刻",
    clearLabel: "结束时刻",
    inputType: "time",
    min: "00:00",
    max: "23:59",
    step: 60,
    placeholder: "",
    deviceStart: 60,
    deviceClear: 120,
    measurementStart: 180,
    measurementClear: 240,
  };
}

function dayOfYearToMonthDay(day) {
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let remain = clamp(Math.round(Number(day) || 1), 1, 365);
  let month = 0;
  while (month < monthDays.length - 1 && remain > monthDays[month]) {
    remain -= monthDays[month];
    month += 1;
  }
  return `${month + 1}月${remain}日`;
}

function monthDayToDayOfYear(value, fallback = 1) {
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const text = String(value ?? "").trim();
  const numeric = Number(text);
  if (Number.isFinite(numeric) && text !== "") {
    return clamp(Math.round(numeric), 1, 365);
  }
  const match = text.match(/(\d{1,2})\D+(\d{1,2})/);
  if (!match) return clamp(Math.round(Number(fallback) || 1), 1, 365);
  const month = clamp(Math.round(Number(match[1]) || 1), 1, 12);
  const day = clamp(Math.round(Number(match[2]) || 1), 1, monthDays[month - 1]);
  const previousDays = monthDays.slice(0, month - 1).reduce((total, count) => total + count, 0);
  return previousDays + day;
}

function faultWindowInputValue(fault, field, fallback) {
  if (field === "start_minute" || field === "clear_minute") {
    return minuteToTimeInput(fault?.[field], fallback);
  }
  const value = Number(fault?.[field]);
  const day = Number.isFinite(value) ? value : fallback;
  return state.curveMode === "year"
    ? dayOfYearToMonthDay(day)
    : String(clamp(Math.round(Number(day) || 1), 1, simulationModeDayCount()));
}

function faultSimulationModeLabel() {
  return `${simulationModeLabel()} · ${isExtendedSimulationMode() ? "按日整定" : "按时分整定"}`;
}

function renderDeviceFaultTable() {
  const container = $("deviceFaultTable");
  const devices = faultDevices();
  const rows = filteredFaultDevices();
  const windowFields = faultWindowFields();
  if (!container) return;
  $("deviceFaultSummary").textContent = `${faultSimulationModeLabel()} · ${state.deviceFaults.length} 个故障 · 显示 ${rows.length}/${devices.length} 台`;
  if (!devices.length) {
    container.innerHTML = '<div class="empty-state">暂无设备数据</div>';
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前筛选无设备</div>';
    return;
  }
  container.innerHTML = `
    <table class="fault-editor-table">
      <thead>
        <tr>
          <th>设备类型</th>
          <th>设备名称</th>
          <th>运行状态</th>
          <th>故障状态</th>
          <th>${windowFields.startLabel}</th>
          <th>${windowFields.clearLabel}</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(({ dev, index }) => {
          const fault = findDeviceFault(dev);
          const disabled = fault ? "" : "disabled";
          return `
            <tr>
              <td>${escapeHtml(dev.dev_type)}</td>
              <td>${escapeHtml(dev.dev_name)}</td>
              <td><span class="status-dot ${dev.run_stat ? "on" : ""}"></span>${dev.run_stat ? "投入" : "退出"}</td>
              <td>
                <select data-device-index="${index}" data-device-field="faulted">
                  <option value="normal" ${fault ? "" : "selected"}>正常</option>
                  <option value="fault" ${fault ? "selected" : ""}>故障</option>
                </select>
              </td>
              <td><input data-device-index="${index}" data-device-field="${windowFields.startField}" type="${windowFields.inputType}" min="${windowFields.min}" max="${windowFields.max}" step="${windowFields.step}" placeholder="${windowFields.placeholder}" value="${faultWindowInputValue(fault, windowFields.startField, windowFields.deviceStart)}" ${disabled} /></td>
              <td><input data-device-index="${index}" data-device-field="${windowFields.clearField}" type="${windowFields.inputType}" min="${windowFields.min}" max="${windowFields.max}" step="${windowFields.step}" placeholder="${windowFields.placeholder}" value="${faultWindowInputValue(fault, windowFields.clearField, windowFields.deviceClear)}" ${disabled} /></td>
            </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

function renderMeasurementFaultTable() {
  const container = $("measurementFaultTable");
  const measurements = faultMeasurements();
  const rows = filteredFaultMeasurements();
  const windowFields = faultWindowFields();
  if (!container) return;
  $("measurementFaultSummary").textContent = `${faultSimulationModeLabel()} · ${state.measurementFaults.length} 个故障 · 显示 ${rows.length}/${measurements.length} 点`;
  if (!measurements.length) {
    container.innerHTML = '<div class="empty-state">暂无量测数据</div>';
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前筛选无量测</div>';
    return;
  }
  container.innerHTML = `
    <table class="fault-editor-table">
      <thead>
        <tr>
          <th>量测名称</th>
          <th>设备</th>
          <th>量测类型</th>
          <th>当前值</th>
          <th>量测状态</th>
          <th>${windowFields.startLabel}</th>
          <th>${windowFields.clearLabel}</th>
          <th>中值</th>
          <th>误差</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(({ meas, index }) => {
          const fault = findMeasurementFault(meas);
          const faultType = fault?.fault_type || "normal";
          const disabled = fault ? "" : "disabled";
          return `
            <tr>
              <td>${escapeHtml(meas.name)}</td>
              <td>${escapeHtml(meas.dev_type)}.${escapeHtml(meas.dev_name)}</td>
              <td>${escapeHtml(meas.meas_type)}</td>
              <td>${meas.value ?? "--"}</td>
              <td>
                <select data-meas-index="${index}" data-meas-field="fault_type">
                  <option value="normal" ${faultType === "normal" ? "selected" : ""}>正常</option>
                  <option value="dead" ${faultType === "dead" ? "selected" : ""}>死数</option>
                  <option value="zero" ${faultType === "zero" ? "selected" : ""}>0值</option>
                </select>
              </td>
              <td><input data-meas-index="${index}" data-meas-field="${windowFields.startField}" type="${windowFields.inputType}" min="${windowFields.min}" max="${windowFields.max}" step="${windowFields.step}" placeholder="${windowFields.placeholder}" value="${faultWindowInputValue(fault, windowFields.startField, windowFields.measurementStart)}" ${disabled} /></td>
              <td><input data-meas-index="${index}" data-meas-field="${windowFields.clearField}" type="${windowFields.inputType}" min="${windowFields.min}" max="${windowFields.max}" step="${windowFields.step}" placeholder="${windowFields.placeholder}" value="${faultWindowInputValue(fault, windowFields.clearField, windowFields.measurementClear)}" ${disabled} /></td>
              <td>${isSignalMeasurement(meas)
                ? `<select data-meas-index="${index}" data-meas-field="median" ${disabled}>
                    <option value="1" ${Number(fault?.median ?? meas.value ?? 0) === 1 ? "selected" : ""}>1 · 投入 / 闭合</option>
                    <option value="0" ${Number(fault?.median ?? meas.value ?? 0) !== 1 ? "selected" : ""}>0 · 退出 / 断开</option>
                  </select>`
                : `<input data-meas-index="${index}" data-meas-field="median" type="number" step="0.001" value="${fault?.median ?? meas.value ?? 0}" ${disabled} />`}</td>
              <td><input data-meas-index="${index}" data-meas-field="bias" type="number" step="0.001" value="${fault?.bias ?? 0}" ${disabled} /></td>
            </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

function updateDeviceFault(index, field, rawValue, shouldRender = true) {
  const dev = faultDevices()[index];
  if (!dev) return;
  if (field === "faulted" && rawValue === "normal") {
    state.deviceFaults = state.deviceFaults.filter((fault) => deviceKey(fault) !== deviceKey(dev));
    renderFaults(true);
    return;
  }
  const fault = ensureDeviceFault(dev);
  if (field === "start_minute" || field === "clear_minute") {
    fault[field] = timeInputToMinute(rawValue, fault[field]);
  } else if (field === "start_day" || field === "clear_day") {
    fault[field] = state.curveMode === "year"
      ? monthDayToDayOfYear(rawValue, fault[field] || 1)
      : clamp(Math.round(Number(rawValue) || Number(fault[field]) || 1), 1, simulationModeDayCount());
  }
  if (shouldRender) renderFaults(true);
}

function updateMeasurementFault(index, field, rawValue, shouldRender = true) {
  const meas = faultMeasurements()[index];
  if (!meas) return;
  if (field === "fault_type" && rawValue === "normal") {
    state.measurementFaults = state.measurementFaults.filter((fault) => !measurementFaultMatches(fault, meas));
    renderFaults(true);
    return;
  }
  const fault = ensureMeasurementFault(meas);
  if (field === "fault_type") {
    fault.fault_type = rawValue;
  } else if (field === "start_minute" || field === "clear_minute") {
    fault[field] = timeInputToMinute(rawValue, fault[field]);
  } else if (field === "start_day" || field === "clear_day") {
    fault[field] = state.curveMode === "year"
      ? monthDayToDayOfYear(rawValue, fault[field] || 1)
      : clamp(Math.round(Number(rawValue) || Number(fault[field]) || 1), 1, simulationModeDayCount());
  } else if (field === "median" || field === "bias") {
    fault[field] = Number(rawValue);
  }
  if (shouldRender) renderFaults(true);
}

function isModeCapableDevice(dev) {
  if (!dev?.dev_type || !dev?.dev_name) return false;
  if (dev.mode !== undefined && String(dev.mode) !== "") return true;
  const raw = dev.raw || {};
  return ["control_type", "mode", "ctrl_mode"].some((column) => raw[column] !== undefined);
}

function syncModesFromDevices(devices, currentModes = []) {
  const currentByKey = new Map();
  currentModes.forEach((item) => {
    if (item?.dev_type && item?.dev_name) {
      currentByKey.set(deviceKey(item), item);
    }
  });
  return devices.filter(isModeCapableDevice).map((dev) => {
    const existing = currentByKey.get(deviceKey(dev));
    const mode = String(existing?.mode ?? existing?.control_type ?? dev.mode ?? "PQ");
    return {
      dev_type: dev.dev_type,
      dev_name: dev.dev_name,
      mode: mode || "PQ",
    };
  });
}

function modeDeviceMap() {
  return new Map((state.snapshot?.devices || []).map((dev) => [deviceKey(dev), dev]));
}

function modeRows() {
  const devices = modeDeviceMap();
  const filter = state.modeFilter || { dev_type: "all", dev_name: "" };
  return state.modes
    .map((item, index) => ({ item, index, device: devices.get(deviceKey(item)) }))
    .filter(({ item }) => deviceFilterMatches(item, filter));
}

function modeOptionsHtml(value) {
  const current = String(value || "PQ");
  const options = MODE_OPTIONS.includes(current)
    ? MODE_OPTIONS
    : [current, ...MODE_OPTIONS.filter((mode) => mode !== current)];
  return options.map((mode) => `
    <option value="${escapeHtml(mode)}" ${mode === current ? "selected" : ""}>${escapeHtml(mode)}</option>
  `).join("");
}

function renderModeDeviceTree() {
  const container = $("modeDeviceTree");
  if (!container) return;
  const filter = state.modeFilter || { dev_type: "all", dev_name: "" };
  const groups = new Map();
  state.modes.forEach((item) => {
    const list = groups.get(item.dev_type) || [];
    list.push(item);
    groups.set(item.dev_type, list);
  });
  const groupEntries = Array.from(groups.entries()).sort(([left], [right]) => left.localeCompare(right));
  const treeResult = filterDeviceTreeGroups(groupEntries, "mode");
  $("modeTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button
      type="button"
      class="tree-node tree-root ${isDeviceTreeNodeActive(filter, "all", "") ? "is-active" : ""}"
      data-mode-tree-type="all"
      data-mode-tree-name=""
    >
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : state.modes.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("mode", devType);
      return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(filter, devType, "") ? "is-active" : isDeviceTreeParentActive(filter, devType) ? "is-parent-active" : ""}"
          data-mode-tree-type="${escapeHtml(devType)}"
          data-mode-tree-name=""
          ${deviceTreeTypeAttrs("mode", devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((item) => `
            <button
              type="button"
              class="tree-node tree-child ${isDeviceTreeNodeActive(filter, item.dev_type, item.dev_name) ? "is-active" : ""}"
              data-mode-tree-type="${escapeHtml(item.dev_type)}"
              data-mode-tree-name="${escapeHtml(item.dev_name)}"
            >
              <span>${escapeHtml(item.dev_name)}</span>
              <small>${escapeHtml(item.mode)}</small>
            </button>
          `).join(""))}
      </div>
    `;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}
  `;
  updateDeviceTreeHtml(container, treeHtml);
}

function renderModeDeviceTable() {
  const container = $("modeDeviceTable");
  if (!container) return;
  const rows = modeRows();
  $("modeTableSummary").textContent = `${rows.length}/${state.modes.length} 台设备`;
  if (!state.modes.length) {
    container.innerHTML = '<div class="empty-state">暂无可设模式设备</div>';
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">当前筛选无设备</div>';
    return;
  }
  container.innerHTML = `
    <table class="mode-editor-table">
      <thead>
        <tr>
          <th>设备类型</th>
          <th>设备名称</th>
          <th>当前状态</th>
          <th>设备状态</th>
          <th>当前模式</th>
          <th>运行模式</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(({ item, index, device }) => {
          const running = Number(device?.run_stat ?? 1) !== 0;
          const available = Number(device?.status ?? 1) !== 0;
          const currentMode = device?.mode || item.mode || "--";
          return `
            <tr>
              <td>${escapeHtml(item.dev_type)}</td>
              <td class="device-name">${escapeHtml(item.dev_name)}</td>
              <td><span class="status-dot ${running ? "on" : ""}"></span>${running ? "投入" : "退出"}</td>
              <td>${available ? "可用/闭合" : "断开/故障"}</td>
              <td>${escapeHtml(currentMode)}</td>
              <td>
                <select data-mode-device-index="${index}" data-mode-field="mode">
                  ${modeOptionsHtml(item.mode)}
                </select>
              </td>
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>`;
}

function renderModes(force = false) {
  const activeEditor = document.activeElement?.closest?.("#modeDeviceTable");
  if (!force && activeEditor) return;
  renderModeDeviceTree();
  renderModeDeviceTable();
}

function setModeFilter(devType, devName = "", event = null, button = null) {
  state.modeFilter = updateDeviceTreeFilterSelection(
    "modeFilter",
    devType,
    devName,
    event,
    "mode",
    button,
  );
  renderModes(true);
}

function updateModeValue(index, field, rawValue) {
  if (field !== "mode" || !state.modes[index]) return;
  state.modes[index].mode = rawValue;
  renderModes(true);
}

function setCurveStatus(text) {
  const status = $("curveStatus") || state.pageSections?.curves?.querySelector("#curveStatus");
  if (status) status.textContent = text;
}

async function saveCurves() {
  const config = curveModeConfig();
  const dirtyKeys = state.curveDirtyKeys instanceof Set ? Array.from(state.curveDirtyKeys) : [];
  const modeChanged = state.curveMode !== state.curvePersistedMode;
  const keysToSave = Array.from(new Set(modeChanged ? Object.keys(state.curveSeries || {}) : dirtyKeys))
    .filter((key) => curveHasLoadedSeries(key));
  if (!keysToSave.length && !modeChanged) {
    setCurveStatus("没有需要保存的曲线");
    return;
  }
  await ensureCurveSeriesLoaded(keysToSave);
  const series = {};
  keysToSave.forEach((key) => {
    if (curveHasLoadedSeries(key)) series[key] = state.curveSeries[key].map((value) => roundCurveValue(key, value));
  });
  await api("/api/curves/series", {
    method: "POST",
    body: JSON.stringify({
      mode: state.curveMode,
      point_count: config.pointCount,
      time_step_minutes: config.stepMinutes,
      series,
    }),
  });
  state.curveDirtyKeys = new Set();
  state.curveDirtyKeysByMode[state.curveMode] = new Set();
  state.curvePersistedMode = state.curveMode;
  state.curveSummary = {
    ...(state.curveSummary || {}),
    mode: state.curveMode,
    point_count: config.pointCount,
    time_step_minutes: config.stepMinutes,
  };
  setCurveStatus("已保存");
}

async function pushSettings() {
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify({
      device_faults: state.deviceFaults,
      measurement_faults: state.measurementFaults,
      modes: state.modes,
    }),
  });
  await refresh();
}

document.querySelectorAll("[data-clock]").forEach((button) => {
  button.addEventListener("click", () => handleClockAction(button.dataset.clock));
});
$("modelManagementButton").addEventListener("click", openModelManagementDialog);
$("closeModelManagementDialog").addEventListener("click", closeModelManagementDialog);
$("cancelModelManagementDialog").addEventListener("click", closeModelManagementDialog);
$("modelManagementDialog").addEventListener("click", (event) => {
  if (event.target.id === "modelManagementDialog") closeModelManagementDialog();
});
$("modelManagementList").addEventListener("click", handleModelManagementAction);
$("modelManagementList").addEventListener("keydown", handleModelManagementKeydown);
$("modelManagementList").addEventListener("contextmenu", openModelContextMenu);
$("modelManagementList").addEventListener("scroll", closeModelContextMenu);
$("modelContextMenu").addEventListener("click", handleModelContextMenuAction);
document.addEventListener("click", (event) => {
  if (event.target instanceof Element && event.target.closest("#modelContextMenu")) return;
  closeModelContextMenu();
});
$("newModelButton").addEventListener("click", openNewModelDialog);
$("selectNewModelFile").addEventListener("click", () => $("newModelFileInput").click());
$("newModelFileInput").addEventListener("change", handleNewModelFileSelected);
$("selectNewModelSvgFile").addEventListener("click", () => $("newModelSvgInput").click());
$("newModelSvgInput").addEventListener("change", handleNewModelSvgFileSelected);
$("importDefinitionsButton").addEventListener("click", () => $("importDefinitionsInput").click());
$("importDefinitionsInput").addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (file) openImportModelDialog(file);
});
$("traineeLinkButton").addEventListener("click", openTraineeLinkDialog);
$("copyTraineeLink").addEventListener("click", copyTraineeLink);
$("closeTraineeLinkDialog").addEventListener("click", closeTraineeLinkDialog);
$("cancelTraineeLinkDialog").addEventListener("click", closeTraineeLinkDialog);
$("traineeLinkDialog").addEventListener("click", (event) => {
  if (event.target.id === "traineeLinkDialog") closeTraineeLinkDialog();
});
$("closeStartSimulationDialog").addEventListener("click", closeStartSimulationDialog);
$("cancelStartSimulation").addEventListener("click", closeStartSimulationDialog);
$("startSimulationDialog").addEventListener("click", (event) => {
  if (event.target.id === "startSimulationDialog") closeStartSimulationDialog();
});
$("startSimulationForm").addEventListener("submit", (event) => {
  event.preventDefault();
  startSimulationFromDialog();
});
$("closeCurveModeSwitchDialog").addEventListener("click", closeCurveModeSwitchDialog);
$("cancelCurveModeSwitch").addEventListener("click", closeCurveModeSwitchDialog);
$("discardCurveModeSwitch").addEventListener("click", switchCurveModeWithoutSaving);
$("saveCurveModeSwitch").addEventListener("click", saveBeforeCurveModeSwitch);
$("curveModeSwitchDialog").addEventListener("click", (event) => {
  if (event.target.id === "curveModeSwitchDialog") closeCurveModeSwitchDialog();
});
$("closeTypicalCurveDialog").addEventListener("click", closeTypicalCurveDialog);
$("cancelTypicalCurve").addEventListener("click", closeTypicalCurveDialog);
$("typicalCurveDialog").addEventListener("click", (event) => {
  if (event.target.id === "typicalCurveDialog") closeTypicalCurveDialog();
});
$("typicalCurveForm").addEventListener("submit", (event) => {
  event.preventDefault();
  try {
    confirmTypicalCurveGeneration();
  } catch (error) {
    setTypicalCurveMessage(`生成失败：${apiErrorText(error)}`, true);
  }
});
$("closeNewModelDialog").addEventListener("click", closeNewModelDialog);
$("cancelNewModel").addEventListener("click", closeNewModelDialog);
$("newModelDialog").addEventListener("click", (event) => {
  if (event.target.id === "newModelDialog") closeNewModelDialog();
});
$("newModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  createNewModelFromFile();
});
$("confirmNewModel").addEventListener("click", createNewModelFromFile);
$("newModelName").addEventListener("input", () => {
  invalidateModelPreflight("newModel");
  validateNewModelForm();
});
$("newModelServiceHostPreset")?.addEventListener("change", () => {
  handleServiceHostPresetChange("newModelServiceHostPreset", "newModelServiceHost", () => {
    invalidateModelPreflight("newModel");
    validateNewModelForm();
  });
});
$("newModelServiceHost").addEventListener("input", () => {
  invalidateModelPreflight("newModel");
  validateNewModelForm();
});
$("newModelServicePort").addEventListener("input", () => {
  invalidateModelPreflight("newModel");
  validateNewModelForm();
});
$("closeUpdateModelDialog").addEventListener("click", closeUpdateModelDialog);
$("cancelUpdateModel").addEventListener("click", closeUpdateModelDialog);
$("updateModelDialog").addEventListener("click", (event) => {
  if (event.target.id === "updateModelDialog") closeUpdateModelDialog();
});
$("selectUpdateModelFile").addEventListener("click", () => openUpdateModelFilePicker("updateModelFileInput"));
$("updateModelFileInput").addEventListener("change", handleUpdateModelFileSelected);
$("selectUpdateModelSvgFile").addEventListener("click", () => openUpdateModelFilePicker("updateModelSvgInput"));
$("updateModelSvgInput").addEventListener("change", handleUpdateModelSvgFileSelected);
$("updateModelServiceHostPreset")?.addEventListener("change", () => {
  handleServiceHostPresetChange("updateModelServiceHostPreset", "updateModelServiceHost", () => {
    invalidateModelPreflight("updateModel");
    validateUpdateModelForm();
  });
});
$("updateModelServiceHost").addEventListener("input", () => {
  invalidateModelPreflight("updateModel");
  validateUpdateModelForm();
});
$("updateModelServicePort").addEventListener("input", () => {
  invalidateModelPreflight("updateModel");
  validateUpdateModelForm();
});
$("updateModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  updateModelFromFile();
});
$("closeImportModelDialog").addEventListener("click", closeImportModelDialog);
$("cancelImportModel").addEventListener("click", closeImportModelDialog);
$("importModelDialog").addEventListener("click", (event) => {
  if (event.target.id === "importModelDialog") closeImportModelDialog();
});
$("importModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  importDefinitionModel();
});
$("importModelName").addEventListener("input", () => {
  invalidateModelPreflight("importModel");
  validateImportModelName();
});
$("closeCloneModelDialog").addEventListener("click", closeCloneModelDialog);
$("cancelCloneModel").addEventListener("click", closeCloneModelDialog);
$("cloneModelDialog").addEventListener("click", (event) => {
  if (event.target.id === "cloneModelDialog") closeCloneModelDialog();
});
$("cloneModelForm").addEventListener("submit", (event) => {
  event.preventDefault();
  cloneCurrentModel();
});
$("cloneModelName").addEventListener("input", () => validateCloneModelName());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeModelContextMenu();
  if (event.key === "Escape" && !$("typicalCurveDialog").hidden) {
    closeTypicalCurveDialog();
    return;
  }
  if (event.key === "Escape" && !$("curveModeSwitchDialog").hidden) {
    closeCurveModeSwitchDialog();
    return;
  }
  if (event.key === "Escape" && !$("startSimulationDialog").hidden) {
    closeStartSimulationDialog();
    return;
  }
  if (event.key === "Escape" && !$("importModelDialog").hidden) {
    closeImportModelDialog();
    return;
  }
  if (event.key === "Escape" && !$("newModelDialog").hidden) {
    closeNewModelDialog();
    return;
  }
  if (event.key === "Escape" && !$("updateModelDialog").hidden) {
    closeUpdateModelDialog();
    return;
  }
  if (event.key === "Escape" && !$("cloneModelDialog").hidden) {
    closeCloneModelDialog();
    return;
  }
  if (event.key === "Escape" && !$("traineeLinkDialog").hidden) {
    closeTraineeLinkDialog();
    return;
  }
  if (event.key === "Escape" && !$("modelManagementDialog").hidden) {
    closeModelManagementDialog();
  }
});

$("generateDenseCurves").addEventListener("click", () => {
  openTypicalCurveDialog().catch((error) => {
    setCurveStatus(`曲线加载失败：${apiErrorText(error)}`);
  });
});
$("randomCurves").addEventListener("click", () => {
  generateCurves(Math.random() * 8 - 4);
  $("curveStatus").textContent = "本地扰动，待保存";
});
$("saveCurves").addEventListener("click", () => {
  saveCurves().catch((error) => {
    $("curveStatus").textContent = `保存失败：${apiErrorText(error)}`;
  });
});
document.addEventListener("click", (event) => {
  const retryButton = event.target instanceof Element ? event.target.closest("[data-curve-retry]") : null;
  if (!retryButton) return;
  event.preventDefault();
  retryCurveEditorLoad();
});
document.querySelectorAll("[data-curve-mode]").forEach((button) => {
  button.addEventListener("click", () => switchSimulationMode(button.dataset.curveMode));
});
$(`simulationModeSelector`).addEventListener("change", (event) => switchSimulationMode(event.target.value));
const curveTreeElement = $("curveTree");
if (curveTreeElement) {
  curveTreeElement.addEventListener("pointerdown", beginCurveTreePointerSelection);
  curveTreeElement.addEventListener("pointerover", extendCurveTreePointerSelection);
}
window.addEventListener("pointerup", finishCurveTreePointerSelection);
window.addEventListener("pointercancel", resetCurveTreePointerSelection);
$("modelSelector").addEventListener("change", (event) => setActiveModel(event.target.value));
$("modelServiceToggle").addEventListener("click", toggleActiveModelService);
$("runtimeLogTypeFilter").addEventListener("change", (event) => {
  state.runtimeLogTypeFilter = event.target.value || "all";
  state.runtimeLogPage = 1;
  renderRuntimeLogs();
});
$("clearRuntimeLogs").addEventListener("click", clearRuntimeLogs);
const runtimeLogTableNode = $("runtimeLogTable");
runtimeLogTableNode.addEventListener("click", handleRuntimeLogTableActivation);
runtimeLogTableNode.addEventListener("dblclick", handleRuntimeLogTableActivation);
runtimeLogTableNode.addEventListener("keydown", handleRuntimeLogTableActivation);
$("closeRuntimeLogDetailDialog").addEventListener("click", closeRuntimeLogDetailDialog);
$("confirmRuntimeLogDetailDialog").addEventListener("click", closeRuntimeLogDetailDialog);
$("runtimeLogDetailDialog").addEventListener("click", (event) => {
  if (event.target === $("runtimeLogDetailDialog")) closeRuntimeLogDetailDialog();
});
$("runtimeLogPager").addEventListener("click", async (event) => {
  const button = event.target instanceof Element ? event.target.closest("[data-runtime-log-page]") : null;
  if (!button) return;
  const direction = button.dataset.runtimeLogPage;
  const pageCount = runtimeLogPageCount(filteredRuntimeLogs());
  state.runtimeLogPage = direction === "prev"
    ? Math.max(1, state.runtimeLogPage - 1)
    : Math.min(pageCount, state.runtimeLogPage + 1);
  await ensureRuntimeLogPageLoaded(state.runtimeLogPage);
  renderRuntimeLogs();
});
$("saveDeviceFaults")?.addEventListener("click", async () => {
  await pushSettings();
  const summary = $("deviceFaultSummary");
  if (summary) summary.textContent = `${faultSimulationModeLabel()} · 已保存 ${state.deviceFaults.length} 个故障`;
});
$("saveMeasurementFaults")?.addEventListener("click", async () => {
  await pushSettings();
  const summary = $("measurementFaultSummary");
  if (summary) summary.textContent = `${faultSimulationModeLabel()} · 已保存 ${state.measurementFaults.length} 个故障`;
});
document.querySelectorAll("[data-fault-tab]").forEach((button) => {
  button.addEventListener("click", () => setFaultTab(button.dataset.faultTab));
});
$("pushModes")?.addEventListener("click", pushSettings);
$("saveSystemParameters").addEventListener("click", saveSystemParameters);
$("resetSystemParameters").addEventListener("click", resetSystemParameterForm);
$("saveRuntimeParameters").addEventListener("click", saveWebRuntimeSettings);
$("undoRuntimeParameters").addEventListener("click", undoWebRuntimeSettings);
$("restoreRuntimeParameterDefaults").addEventListener("click", restoreWebRuntimeDefaults);
document.querySelectorAll("[data-runtime-setting]").forEach((input) => {
  input.addEventListener("input", () => updateWebRuntimeDraft(input));
  if (input.tagName === "SELECT") {
    input.addEventListener("change", () => updateWebRuntimeDraft(input));
  }
});
$("refreshManualChanges").addEventListener("click", loadManualDefinitionChanges);
$("retryPendingManualChanges").addEventListener("click", retryPendingManualDefinitionChanges);
$("resetSelectedManualChanges").addEventListener("click", resetSelectedManualDefinitionChanges);
$("manualDefinitionChangesTable").addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.type !== "checkbox") return;
  if (target.matches("[data-manual-change-select-all]")) {
    state.manualDefinitionChangeSelection = target.checked
      ? new Set(state.manualDefinitionChanges.map((item) => String(item.id || "")).filter(Boolean))
      : new Set();
    renderManualDefinitionChanges();
    return;
  }
  const changeId = target.dataset.manualChangeId || "";
  if (changeId) toggleManualDefinitionChange(changeId, target.checked);
});
[
  "parameterClockSpeed",
  "parameterComputeInterval",
  "parameterStorageInitialSoc",
  "parameterRemoteAdjustmentResponseRatio",
].forEach((id) => {
  const element = $(id);
  if (element) element.addEventListener("input", markSystemParametersDirty);
});
function handleSimulatorTableFilterControl(target) {
  if (!(target instanceof Element)) return false;
  const control = target.closest("[data-table-filter-scope]");
  if (!(control instanceof HTMLInputElement || control instanceof HTMLSelectElement)) return false;
  const scope = control.dataset.tableFilterScope || "";
  const field = control.dataset.tableFilterField || "";
  if (scope === "measurementCompare") {
    if (field === "type") state.measurementCompareTypeFilter = control.value || "all";
    else state.measurementCompareKeywordFilter = control.value || "";
    renderMeasurementCompareTable();
    drawMeasurementTraceChart();
    return true;
  }
  if (scope === "runtimeCommand") {
    if (field === "type") state.runtimeCommandTypeFilter = control.value || "all";
    else if (field === "origin") state.runtimeCommandOriginFilter = control.value || "all";
    else state.runtimeCommandKeywordFilter = control.value || "";
    renderRuntimeDeviceTable();
    drawRuntimeTraceChart();
    return true;
  }
  return false;
}

const _simulatorSearchDebounceTimers = new WeakMap();
const _simulatorSearchComposing = new WeakSet();
document.addEventListener("compositionstart", (event) => {
  if (event.target instanceof HTMLInputElement && event.target.type === "search") {
    _simulatorSearchComposing.add(event.target);
  }
});
document.addEventListener("compositionend", (event) => {
  if (event.target instanceof HTMLInputElement && event.target.type === "search") {
    _simulatorSearchComposing.delete(event.target);
    event.target.dispatchEvent(new Event("input", { bubbles: true }));
  }
});

function _applySimulatorSearchInput(target) {
  if (handleSimulatorTableFilterControl(target)) return;
  if (target?.id === "curveTreeFilter") {
    state.curveTreeSearch = target.value || "";
    renderCurveTree();
    return;
  }
  const input = target.closest?.("[data-device-tree-filter-scope]");
  if (!input) return;
  const scope = input.dataset.deviceTreeFilterScope || "";
  state.deviceTreeSearch[scope] = input.value || "";
  refreshDeviceTreeFilterScope(scope);
}

document.addEventListener("input", (event) => {
  const target = event.target;
  if (target instanceof HTMLInputElement && target.type === "search") {
    if (_simulatorSearchComposing.has(target)) return;
    const prevTimer = _simulatorSearchDebounceTimers.get(target);
    if (prevTimer) clearTimeout(prevTimer);
    const nextTimer = setTimeout(() => {
      _simulatorSearchDebounceTimers.delete(target);
      _applySimulatorSearchInput(target);
    }, 150);
    _simulatorSearchDebounceTimers.set(target, nextTimer);
    return;
  }
  _applySimulatorSearchInput(target);
});
document.addEventListener("change", (event) => {
  if (!(event.target instanceof Element)) return;
  const target = event.target;
  const onlyActiveToggle = target.closest("#runtimeCommandOnlyActive");
  if (!(onlyActiveToggle instanceof HTMLInputElement)) return;
  state.runtimeCommandOnlyActive = onlyActiveToggle.checked;
  syncRuntimeCommandOnlyActiveControl();
  renderRuntimeDeviceTable();
  drawRuntimeTraceChart();
});
document.addEventListener("scroll", handleVirtualTableScroll, true);
document.addEventListener("click", (event) => {
  const curveTreeToggle = event.target.closest("[data-curve-tree-toggle]");
  if (curveTreeToggle) {
    event.preventDefault();
    event.stopPropagation();
    toggleCurveTreeGroup(curveTreeToggle.dataset.curveTreeToggle || "");
    return;
  }
  const chartToggle = event.target.closest("[data-chart-toggle][data-chart-series]");
  if (chartToggle) {
    event.preventDefault();
    const chartKey = chartToggle.dataset.chartToggle || "";
    const seriesKey = chartToggle.dataset.chartSeries || "";
    const drawFn = chartKey === "runtimeTrace" ? drawRuntimeTraceChart
      : chartKey === "measurementTrace" ? drawMeasurementTraceChart
        : null;
    toggleChartSeriesVisibility(chartKey, seriesKey, drawFn);
    return;
  }
  const runtimeCommandTab = event.target.closest("[data-runtime-command-tab]");
  if (runtimeCommandTab) {
    setRuntimeCommandTab(runtimeCommandTab.dataset.runtimeCommandTab || "");
    return;
  }
  const runtimeCommandDeleteButton = event.target.closest("[data-runtime-command-delete-name]");
  if (runtimeCommandDeleteButton) {
    event.preventDefault();
    event.stopPropagation();
    deleteRuntimeCommand(
      runtimeCommandDeleteButton.dataset.runtimeCommandDeleteName || "",
      runtimeCommandDeleteButton.dataset.runtimeCommandDeleteLabel || "",
    );
    return;
  }
  const measurementCompareTab = event.target.closest("[data-measurement-compare-tab]");
  if (measurementCompareTab) {
    setMeasurementCompareTab(measurementCompareTab.dataset.measurementCompareTab || "telemetry");
    return;
  }
  const runtimeCommandRow = event.target.closest("[data-runtime-command-row-key]");
  if (runtimeCommandRow) {
    selectRuntimeCommandTrace(
      runtimeCommandRow.dataset.runtimeCommandRowKey || "",
      runtimeCommandRow.dataset.runtimeCommandRowLabel || "",
    );
    return;
  }
  const modelParamTab = event.target.closest("[data-model-param-tab]");
  if (modelParamTab) {
    setModelParamTab(modelParamTab.dataset.modelParamTab || "");
    return;
  }
  const curveTreeButton = event.target.closest("[data-curve-tree-type]");
  if (curveTreeButton) {
    if (state.suppressNextCurveTreeClick) {
      state.suppressNextCurveTreeClick = false;
      event.preventDefault();
      return;
    }
    selectCurveTreeButton(curveTreeButton, event);
    event.preventDefault();
    return;
  }
  const faultDeviceTreeButton = event.target.closest("[data-fault-device-tree-type]");
  if (faultDeviceTreeButton) {
    if (faultDeviceTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        faultDeviceTreeButton.dataset.treeToggleScope,
        faultDeviceTreeButton.dataset.treeToggleGroup,
      );
    }
    setDeviceFaultFilter(
      faultDeviceTreeButton.dataset.faultDeviceTreeType,
      faultDeviceTreeButton.dataset.faultDeviceTreeName || "",
      event,
      faultDeviceTreeButton,
    );
  }
  const faultMeasurementTreeButton = event.target.closest("[data-fault-measurement-tree-type]");
  if (faultMeasurementTreeButton) {
    if (faultMeasurementTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        faultMeasurementTreeButton.dataset.treeToggleScope,
        faultMeasurementTreeButton.dataset.treeToggleGroup,
      );
    }
    setMeasurementFaultFilter(
      faultMeasurementTreeButton.dataset.faultMeasurementTreeType,
      faultMeasurementTreeButton.dataset.faultMeasurementTreeName || "",
      event,
      faultMeasurementTreeButton,
    );
  }
  const measurementSelectRow = event.target.closest("[data-measurement-select-key]");
  if (measurementSelectRow) {
    setSelectedMeasurementKey(measurementSelectRow.dataset.measurementSelectKey || "");
  }
  const measurementTreeButton = event.target.closest("[data-measurement-tree-type]");
  if (measurementTreeButton) {
    if (measurementTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        measurementTreeButton.dataset.treeToggleScope,
        measurementTreeButton.dataset.treeToggleGroup,
      );
    }
    setMeasurementCompareFilter(
      measurementTreeButton.dataset.measurementTreeType,
      measurementTreeButton.dataset.measurementTreeName || "",
      event,
      measurementTreeButton,
    );
  }
  const modelTreeButton = event.target.closest("[data-model-tree-type]");
  if (modelTreeButton) {
    if (modelTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        modelTreeButton.dataset.treeToggleScope,
        modelTreeButton.dataset.treeToggleGroup,
      );
    }
    setGridModelFilter(
      modelTreeButton.dataset.modelTreeType,
      modelTreeButton.dataset.modelTreeName || "",
      event,
      modelTreeButton,
    );
  }
  const runtimeTreeButton = event.target.closest("[data-runtime-tree-type]");
  if (runtimeTreeButton) {
    if (runtimeTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        runtimeTreeButton.dataset.treeToggleScope,
        runtimeTreeButton.dataset.treeToggleGroup,
      );
    }
    setRuntimeDeviceFilter(
      runtimeTreeButton.dataset.runtimeTreeType,
      runtimeTreeButton.dataset.runtimeTreeName || "",
      event,
      runtimeTreeButton,
    );
  }
  const modeTreeButton = event.target.closest("[data-mode-tree-type]");
  if (modeTreeButton) {
    if (modeTreeButton.dataset.treeToggleScope && !(event.ctrlKey || event.metaKey || event.shiftKey)) {
      toggleDeviceTreeGroup(
        modeTreeButton.dataset.treeToggleScope,
        modeTreeButton.dataset.treeToggleGroup,
      );
    }
    setModeFilter(modeTreeButton.dataset.modeTreeType, modeTreeButton.dataset.modeTreeName || "", event, modeTreeButton);
  }
});
document.addEventListener("dblclick", (event) => {
  const runtimeCommandRow = event.target.closest("[data-runtime-command-row-key]");
  if (!runtimeCommandRow) return;
  event.preventDefault();
  selectRuntimeCommandTrace(
    runtimeCommandRow.dataset.runtimeCommandRowKey || "",
    runtimeCommandRow.dataset.runtimeCommandRowLabel || "",
  );
});
document.addEventListener("change", (event) => {
  if (handleSimulatorTableFilterControl(event.target)) return;
  if (event.target.dataset.modeField !== undefined) {
    updateModeValue(Number(event.target.dataset.modeDeviceIndex), event.target.dataset.modeField, event.target.value);
  }
  if (event.target.dataset.modeIndex !== undefined) {
    state.modes[Number(event.target.dataset.modeIndex)].mode = event.target.value;
  }
  if (event.target.dataset.deviceField !== undefined) {
    updateDeviceFault(Number(event.target.dataset.deviceIndex), event.target.dataset.deviceField, event.target.value);
  }
  if (event.target.dataset.measField !== undefined) {
    updateMeasurementFault(Number(event.target.dataset.measIndex), event.target.dataset.measField, event.target.value);
  }
});
document.addEventListener("input", (event) => {
  if (event.target.dataset.deviceField !== undefined && event.target.tagName === "INPUT") {
    updateDeviceFault(Number(event.target.dataset.deviceIndex), event.target.dataset.deviceField, event.target.value, false);
  }
  if (event.target.dataset.measField !== undefined && event.target.tagName === "INPUT") {
    updateMeasurementFault(Number(event.target.dataset.measIndex), event.target.dataset.measField, event.target.value, false);
  }
});
// 为实用快捷键、未保存离开保护、异常速筛及日志过滤提供统一装配
(function setupUsabilityEnhancements() {
  $("measurementCompareOnlyAbnormalFilter")?.addEventListener("change", (event) => {
    state.measurementCompareOnlyAbnormal = Boolean(event.target.checked);
    renderMeasurementCompareTable();
  });
  $("exportSimulatorMeasurementsCsvButton")?.addEventListener("click", () => {
    exportSimulatorMeasurementsCsv();
  });
  let simLogSearchTimer = null;
  $("runtimeLogKeywordFilter")?.addEventListener("input", (event) => {
    const val = String(event.target.value || "");
    if (simLogSearchTimer) clearTimeout(simLogSearchTimer);
    simLogSearchTimer = setTimeout(() => {
      simLogSearchTimer = null;
      state.runtimeLogKeywordFilter = val;
      state.runtimeLogPage = 1;
      renderRuntimeLogs();
    }, 150);
  });
  $("runtimeLogOnlyAlertFilter")?.addEventListener("change", (event) => {
    state.runtimeLogOnlyAlert = Boolean(event.target.checked);
    state.runtimeLogPage = 1;
    renderRuntimeLogs();
  });

  const hasOpenOverlay = () => Boolean(
    document.querySelector("dialog[open]")
    || [
      "startSimulationDialog",
      "newModelDialog",
      "updateModelDialog",
      "cloneModelDialog",
      "importModelDialog",
      "modelManagementDialog",
      "traineeLinkDialog",
    ].some((id) => {
      const el = $(id);
      return el && !el.hidden;
    }),
  );

  document.addEventListener("keydown", (event) => {
    const tag = String(event.target?.tagName || "").toUpperCase();
    const isEditable = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || event.target?.isContentEditable;
    const isInteractiveFocus = isEditable || tag === "BUTTON" || tag === "A";
    if (event.key === "Escape") {
      const openModal = [
        ["startSimulationDialog", closeStartSimulationDialog],
        ["newModelDialog", closeNewModelDialog],
        ["updateModelDialog", closeUpdateModelDialog],
        ["cloneModelDialog", closeCloneModelDialog],
        ["importModelDialog", closeImportModelDialog],
      ].find(([id]) => {
        const el = $(id);
        return el && !el.hidden;
      });
      if (openModal && typeof openModal[1] === "function") {
        event.preventDefault();
        openModal[1]();
      }
      return;
    }
    if (isEditable || event.ctrlKey || event.metaKey || event.altKey || hasOpenOverlay()) return;
    if (event.key === "/") {
      const activeSection = document.querySelector(".page-section.is-active");
      const searchBox = activeSection?.querySelector('input[type="search"]');
      if (searchBox) {
        event.preventDefault();
        searchBox.focus();
        searchBox.select();
      }
    } else if (event.code === "Space" && !isInteractiveFocus) {
      const clockState = String(state.snapshot?.clock?.state || "");
      if (clockState === "running" || clockState === "paused") {
        event.preventDefault();
        handleClockAction(clockState === "running" ? "pause" : "start");
      }
    }
  });

  window.addEventListener("beforeunload", (event) => {
    const hasDirtyCurves = Boolean(state.curveDirtyKeys && state.curveDirtyKeys.size > 0);
    if (!hasDirtyCurves) return;
    event.preventDefault();
    event.returnValue = "";
  });
}());

document.addEventListener("visibilitychange", () => {
  if (pageIsHidden()) {
    if (state.frontendRefreshTimerId) {
      clearTimeout(state.frontendRefreshTimerId);
      state.frontendRefreshTimerId = null;
    }
    return;
  }
  scheduleNextRefresh(0);
});
generateCurves(0);
initCurveEditor();
initRuntimeMonitor();
initMeasurementMonitor();
initOverviewBottomSplitter();
initOverviewBottomColumnSplitter();
initVerticalSplitters();
initPrecisionUiChrome();
setFaultTab(state.activeFaultTab);
renderFaults(true);
initPageNavigation();
loadModels().finally(() => {
  if (activeModelServiceRunning()) refresh();
  restartRefreshScheduler();
});
