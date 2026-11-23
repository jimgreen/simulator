// 学员端模块：接线图设备与量测悬浮编辑、属性与趋势面板（03-diagram-editor.js）
function diagramMeasurementFieldName(row = {}) {
  const field = String(row?.meas_type || row?.name || "量测").trim();
  if (!field) return "量测";
  return DIAGRAM_MEASUREMENT_FIELD_LABELS[field.toUpperCase()] || field.toLowerCase();
}

function diagramDeviceData(container, device, snapshot = state.snapshot || {}) {
  if (!device) return { definition: null, live: null, raw: {}, svgIdx: "" };
  const resolvedDevice = diagramResolvedTooltipDevice(container, device);
  const type = normalizeDiagramMeasurementToken(resolvedDevice.devType);
  const name = String(resolvedDevice.devName || "");
  const definition = definedModelDevices(snapshot).find((item) => (
    normalizeDiagramMeasurementToken(item.dev_type) === type
    && String(item.dev_name || "") === name
  )) || null;
  const live = (snapshot.devices || []).find((item) => (
    normalizeDiagramMeasurementToken(item.dev_type) === type
    && String(item.dev_name || "") === name
  )) || null;
  const svgElement = [...container.querySelectorAll("[dev-id]")]
    .find((element) => String(element.getAttribute("dev-id") || "") === resolvedDevice.devId);
  return {
    device: resolvedDevice,
    definition,
    live,
    raw: { ...(definition?.raw || {}), ...(live?.raw || {}) },
    svgIdx: svgElement?.getAttribute("idx") || "",
  };
}

function diagramDeviceMeasurements(device, snapshot = state.snapshot || {}) {
  if (!device) return [];
  const type = normalizeDiagramMeasurementToken(device.devType);
  const name = String(device.devName || "");
  const matches = (row) => (
    normalizeDiagramMeasurementToken(row?.dev_type) === type
    && String(row?.dev_name || "") === name
    && Number(row?.valid ?? 1) === 1
  );
  const rows = new Map();
  (snapshot.measurements?.scada || []).filter(matches).forEach((row) => rows.set(measurementKey(row), row));
  return [...rows.values()].sort((left, right) => (
    String(left.meas_type || left.name || "").localeCompare(String(right.meas_type || right.name || ""), "zh-Hans-CN")
  ));
}

function diagramDeviceIdentityKey(device) {
  const devType = normalizeDiagramMeasurementToken(device?.devType ?? device?.dev_type);
  const devName = String(device?.devName ?? device?.dev_name ?? device?.name ?? "").trim();
  return devType && devName ? `${devType}|${devName}` : "";
}

function diagramTooltipDeviceRecord(device = {}) {
  return {
    devId: String(device?.devId ?? device?.dev_id ?? "").trim(),
    devType: String(device?.devType ?? device?.dev_type ?? "").trim(),
    devName: String(device?.devName ?? device?.dev_name ?? device?.name ?? "").trim(),
  };
}

function diagramDeviceSnapshotEntry(snapshot, devType, devName) {
  const identity = diagramDeviceIdentityKey({ devType, devName });
  if (!identity) return null;
  return (snapshot?.devices || []).find((item) => diagramDeviceIdentityKey(item) === identity)
    || definedModelDevices(snapshot).find((item) => diagramDeviceIdentityKey(item) === identity)
    || null;
}

function diagramResolvedTooltipDevice(container, device) {
  const record = diagramTooltipDeviceRecord(device);
  if (record.devId || !container) return record;
  const identity = diagramDeviceIdentityKey(record);
  const svgRecord = [...diagramDeviceIndex(container).values()]
    .find((item) => diagramDeviceIdentityKey(item) === identity);
  return svgRecord ? { ...record, devId: svgRecord.devId } : record;
}

function diagramCouplingDevicePages(device, snapshot = state.snapshot || {}) {
  const hostDevice = diagramTooltipDeviceRecord(device);
  if (!hostDevice.devType || !hostDevice.devName) return [];
  const pages = [{ key: "self", label: "设备本体", relation: null, device: hostDevice }];
  const hostEntry = diagramDeviceSnapshotEntry(snapshot, hostDevice.devType, hostDevice.devName);
  const bindings = Array.isArray(hostEntry?.control_bindings) ? hostEntry.control_bindings : [];
  const seen = new Set([diagramDeviceIdentityKey(hostDevice)]);
  bindings.forEach((binding) => {
    const targetType = String(binding?.target_dev_type || "").trim();
    const targetName = String(binding?.target_dev_name || "").trim();
    const targetEntry = diagramDeviceSnapshotEntry(snapshot, targetType, targetName);
    if (!targetEntry) return;
    const targetDevice = diagramTooltipDeviceRecord(targetEntry);
    const identity = diagramDeviceIdentityKey(targetDevice);
    if (!identity || seen.has(identity)) return;
    seen.add(identity);
    pages.push({
      key: `related:${identity}`,
      label: targetDevice.devName || targetDevice.devType,
      relation: { ...binding },
      device: targetDevice,
    });
  });
  return pages;
}

function diagramActiveDeviceTooltipPage(interaction, hover, pages = []) {
  if (!pages.length) return null;
  const hostKey = String(hover?.key || "");
  if (!interaction) return pages[0];
  if (String(interaction.deviceTooltipHostKey || "") !== hostKey) {
    interaction.deviceTooltipHostKey = hostKey;
    interaction.deviceTooltipTabKey = "self";
  }
  const active = pages.find((page) => page.key === interaction.deviceTooltipTabKey) || pages[0];
  interaction.deviceTooltipTabKey = active.key;
  return active;
}

function diagramSingleDeviceTooltipData(container, device, snapshot) {
  if (!device) return null;
  const { device: resolvedDevice, definition, live, raw, svgIdx } = diagramDeviceData(container, device, snapshot);
  const definitionRecords = diagramDeviceDefinitionRecords(resolvedDevice, snapshot);
  applyDiagramDeviceDefinitionRuntimeValues(definitionRecords, live);
  const idx = live?.raw?.idx ?? definition?.idx ?? raw.idx ?? svgIdx ?? "--";
  const identityRows = [
    ["设备类型", resolvedDevice.devType || "--", "identity:type"],
    ["设备标识", resolvedDevice.devId || "--", "identity:id"],
    ["idx", idx, "identity:idx"],
  ];
  const runStatBinding = diagramDefinitionFieldBinding(definitionRecords, ["run_stat"]);
  diagramDefinitionFieldBinding(definitionRecords, ["status"]);
  const statusBinding = diagramDefinitionFieldBinding(definitionRecords, ["closed_status_set"]);
  const hasSwitchStatus = diagramDeviceHasSwitchStatus(definitionRecords, raw);
  const runStatValue = traineeRuntimeSignalDisplayValue(live, "run_stat", live?.run_stat ?? raw.run_stat);
  const switchStatusValue = diagramDefinitionDisplayValue(
    "closed_status",
    live?.closed_status ?? raw.closed_status,
  );
  const statusRows = [
    ["运行状态", runStatValue, "status:run_stat", runStatBinding],
    ...(hasSwitchStatus
      ? [["开关状态", switchStatusValue, "status:status", statusBinding]]
      : []),
  ];
  const setRows = Object.entries(live?.set_values || {})
    .map(([key, value]) => [
      key,
      value,
      `set:${key}`,
      diagramDefinitionFieldBinding(definitionRecords, [key]),
    ]);
  const duplicateKeys = new Set([
    "idx", "name", "dev_name", "dev_type", "run_stat", "status", "closed_status",
    "closed_status_set", "mode", "control_type",
    ...Object.keys(live?.set_values || {}),
  ]);
  const rawRows = Object.entries(raw)
    .filter(([key]) => !duplicateKeys.has(key) && !definitionRecords.length)
    .map(([key, value]) => [key, value, `raw:${key}`]);
  const measurementRows = diagramDeviceMeasurements(resolvedDevice, snapshot).map((row) => {
    const metricType = normalizeDiagramMeasurementToken(row.meas_type) === "SOC" ? "level" : "";
    const value = diagramTrendDisplayValue(row.value, row, metricType);
    const unit = diagramMeasurementUnit(row.meas_type);
    return [
      diagramMeasurementFieldName(row),
      value === null ? "--" : `${diagramNumberText(value)}${unit ? ` ${unit}` : ""}`,
      `measurement:${measurementKey(row)}`,
    ];
  });
  return {
    title: resolvedDevice.devName || resolvedDevice.devId || "设备",
    dynamicSections: [
      { key: "identity", title: "", rows: identityRows },
      { key: "status", title: "运行信息", rows: statusRows },
      { key: "set", title: "当前设定值", rows: setRows },
      { key: "raw", title: "Model.e 参数（只读）", rows: rawRows },
      { key: "measurement", title: "实时量测", rows: measurementRows },
    ].filter((section) => section.rows.length),
    definitionRecords,
  };
}

function diagramDeviceTooltipData(container, hover, snapshot, interaction = null) {
  const pages = diagramCouplingDevicePages(hover?.device, snapshot);
  const activePage = diagramActiveDeviceTooltipPage(interaction, hover, pages);
  const data = diagramSingleDeviceTooltipData(container, activePage?.device, snapshot);
  if (!data || !activePage) return null;
  return {
    ...data,
    pages,
    activePageKey: activePage.key,
  };
}

function diagramTooltipSectionsHtml(sections = [], interaction = null) {
  return sections.map((section) => `
    <section class="diagram-tooltip-section" data-diagram-tooltip-section="${escapeHtml(section.key)}">
      ${section.title ? `<h4>${escapeHtml(section.title)}</h4>` : ""}
      ${diagramTooltipRows(section.rows, section.key, interaction)}
    </section>`).join("");
}

function diagramDefinitionMessageHtml(interaction) {
  const message = String(interaction?.definitionMessage || "").trim();
  if (!message) return "";
  const levelClass = interaction?.definitionMessageWarning ? " is-warning" : " is-success";
  return `<div class="diagram-definition-message${levelClass}" data-diagram-definition-message>${escapeHtml(message)}</div>`;
}

const DIAGRAM_DEFINITION_RATIO_FIELDS = new Set([
  "initial_soc",
  "soc_initial",
  "soc_init",
  "state_of_charge",
  "soc",
  "soc_curr",
  "soc_cur",
  "soc_min",
  "soc_max",
  "soc_lower_limit",
  "soc_upper_limit",
]);

const DIAGRAM_DEFINITION_FIELD_LABELS = Object.freeze({
  control_type: "控制模式",
  ac_control_type: "交流侧控制模式",
  dc_control_type: "直流侧控制模式",
  i_control_type: "I 侧控制模式",
  j_control_type: "J 侧控制模式",
  run_stat: "运行状态",
  status: "开关状态",
  e2h_coeff: "电-气效率 (Nm3/kWh)",
  h2e_coeff: "气-电效率 (kWh/Nm3)",
});

function diagramDefinitionFieldLabel(field) {
  const name = String(field || "").trim().toLowerCase();
  return DIAGRAM_DEFINITION_FIELD_LABELS[name] || String(field || "");
}

function diagramDefinitionControlModeValue(value) {
  const token = String(value || "").trim().toUpperCase();
  return ({
    P: "定电功率 (P)",
    PQ: "定有功/无功 (PQ)",
    PV: "定有功/电压 (PV)",
    Q: "定无功 (Q)",
    V: "定电压 (V)",
    I: "定电流 (I)",
    B: "定电纳 (B)",
    Z: "定阻抗 (Z)",
    SLACK: "平衡参考 (SLACK)",
    PH: "构网定压/相角 (PH)",
    FLOW: "定气流量 (FLOW)",
    PRESSURE: "定压力 (PRESSURE)",
    NONE: "无控制 (NONE)",
    PQQ: "两侧定功率 (PQQ)",
    PVQ: "I侧定压/J侧定功率 (PVQ)",
    PQV: "I侧定功率/J侧定压 (PQV)",
    PVV: "两侧定压 (PVV)",
  })[token] || diagramTooltipValue(value);
}

const DIAGRAM_CONTROL_MODE_OPTIONS_BY_BLOCK = Object.freeze({
  ACGENERATOR: ["PQ", "P", "PV", "V", "SLACK", "PH"],
  ACREALBS: ["Q", "V", "B", "Z"],
  ACACCONVERTER: ["PQQ", "PVQ", "PQV", "PVV"],
  DCGENERATOR: ["P", "V", "I", "SLACK"],
  DCDCCONVERTER: ["P", "V", "I"],
  HYDROSOURCE: ["PRESSURE", "FLOW"],
  HYDROLOAD: ["FLOW"],
  HYDROSTORAGE: ["PRESSURE", "FLOW"],
  ACE2HYDRO: ["P", "FLOW"],
  DCE2HYDRO: ["P", "FLOW"],
  HYDRO2ACE: ["P", "FLOW"],
  HYDRO2DCE: ["P", "FLOW"],
});
const DIAGRAM_AC_SIDE_CONTROL_OPTIONS = Object.freeze(["PQ", "PV", "PH", "NONE"]);
const DIAGRAM_DC_SIDE_CONTROL_OPTIONS = Object.freeze(["P", "V", "I", "NONE"]);
const DIAGRAM_DCAC_CONTROL_PAIRS = Object.freeze([
  ["PQ", "NONE"],
  ["PQ", "V"],
  ["PH", "NONE"],
  ["NONE", "P"],
]);

function diagramDefinitionEnumCanonicalValue(record, field, value) {
  const name = String(field || "").trim().toLowerCase();
  const block = normalizeDiagramMeasurementToken(record?.blockName);
  let token = String(value ?? "").trim().toUpperCase();
  if (["run_stat", "status", "closed_status", "closed_status_set"].includes(name)) {
    if (["TRUE", "ON", "CLOSED", "投入", "闭合", "合闸"].includes(token)) return "1";
    if (["FALSE", "OFF", "OPEN", "退出", "断开", "打开", "分闸"].includes(token)) return "0";
    return Number(token) === 1 ? "1" : (Number(token) === 0 ? "0" : token);
  }
  if (name === "i_control_type" || name === "j_control_type") {
    if (token === "CTRL_P") token = "P";
    if (token === "CTRL_I") token = "I";
    if (block === "ACACCONVERTER") {
      if (["CTRL_PQ", "Q"].includes(token)) token = "PQ";
      if (["CTRL_PV", "CTRL_V", "V"].includes(token)) token = "PV";
      if (token === "CTRL_PH") token = "PH";
      if (["CTRL_NONE", "UNSPEC", "UNDEFINED", "NA"].includes(token)) token = "NONE";
    } else if (block === "DCDCCONVERTER") {
      if (token === "CTRL_V") token = "V";
      if (["SLACK", "CTRL_SLACK", "CTRL_NONE"].includes(token)) token = "NONE";
    }
  }
  return token;
}

function diagramDefinitionEnumOption(value, label = "") {
  const token = String(value);
  return { value: token, label: label || diagramDefinitionControlModeValue(token) };
}

function diagramDefinitionEnumOptions(record, field) {
  const name = String(field || "").trim().toLowerCase();
  const block = normalizeDiagramMeasurementToken(record?.blockName);
  const row = record?.row || {};
  if (name === "run_stat") {
    return [diagramDefinitionEnumOption("1", "投入"), diagramDefinitionEnumOption("0", "退出")];
  }
  if (name === "status") {
    return [diagramDefinitionEnumOption("1", "闭合"), diagramDefinitionEnumOption("0", "断开")];
  }
  if (name === "closed_status_set") {
    return [diagramDefinitionEnumOption("1", "闭合"), diagramDefinitionEnumOption("0", "打开")];
  }
  let values = [];
  if (block === "DCACCONVERTER" && name === "ac_control_type") {
    values = DIAGRAM_DCAC_CONTROL_PAIRS.map((pair) => pair[0]);
  } else if (block === "DCACCONVERTER" && name === "dc_control_type") {
    values = DIAGRAM_DCAC_CONTROL_PAIRS.map((pair) => pair[1]);
  } else if (name === "ac_control_type") {
    values = DIAGRAM_AC_SIDE_CONTROL_OPTIONS;
  } else if (name === "dc_control_type") {
    values = DIAGRAM_DC_SIDE_CONTROL_OPTIONS;
  } else if (name === "i_control_type" || name === "j_control_type") {
    values = block === "ACACCONVERTER"
      ? DIAGRAM_AC_SIDE_CONTROL_OPTIONS
      : DIAGRAM_DC_SIDE_CONTROL_OPTIONS;
  } else if (name === "control_type") {
    values = DIAGRAM_CONTROL_MODE_OPTIONS_BY_BLOCK[block] || [];
  } else if (name.endsWith("_control_type") || name === "mode" || name.endsWith("_mode")) {
    values = [];
  } else {
    return [];
  }
  const current = diagramDefinitionEnumCanonicalValue(record, field, row[field]);
  const unique = [...new Set(values.map((value) => String(value)))];
  if (!unique.length && current) unique.push(current);
  return unique.map((value) => diagramDefinitionEnumOption(value));
}

function diagramDefinitionCoupledEnumValues(record, field, value) {
  const block = normalizeDiagramMeasurementToken(record?.blockName);
  const name = String(field || "").trim().toLowerCase();
  const row = record?.row || {};
  const selected = diagramDefinitionEnumCanonicalValue(record, field, value);
  const changes = { [field]: selected };
  if (block === "DCDCCONVERTER" && ["i_control_type", "j_control_type"].includes(name)) {
    const otherField = name === "i_control_type" ? "j_control_type" : "i_control_type";
    const other = diagramDefinitionEnumCanonicalValue(record, otherField, row[otherField]);
    changes[otherField] = selected === "NONE"
      ? (["P", "V", "I"].includes(other) ? other : "P")
      : "NONE";
  }
  if (block === "DCACCONVERTER" && name === "ac_control_type") {
    const dcMode = diagramDefinitionEnumCanonicalValue(record, "dc_control_type", row.dc_control_type);
    changes.dc_control_type = selected === "NONE"
      ? "P"
      : (selected === "PQ" && dcMode === "V" ? "V" : "NONE");
  }
  if (block === "DCACCONVERTER" && name === "dc_control_type") {
    const acMode = diagramDefinitionEnumCanonicalValue(record, "ac_control_type", row.ac_control_type);
    changes.ac_control_type = selected === "P"
      ? "NONE"
      : (selected === "V" ? "PQ" : (["PQ", "PH"].includes(acMode) ? acMode : "PQ"));
  }
  return changes;
}

function diagramDefinitionControlModeOptions(record, field) {
  return diagramDefinitionEnumOptions(record, field).map((option) => option.value);
}

function renderDiagramDefinitionEnumSelect(record, field, value, interaction) {
  const options = diagramDefinitionEnumOptions(record, field);
  const current = diagramDefinitionEnumCanonicalValue(record, field, value);
  const currentValid = options.some((option) => option.value === current);
  return `
    <select
      class="diagram-definition-input"
      data-diagram-tooltip-inline-input
      data-diagram-definition-input="device"
      data-diagram-definition-enum
      data-diagram-definition-control-mode
      data-diagram-definition-field="${escapeHtml(field)}"
      ${interaction?.definitionSaving ? "disabled" : ""}
    >
      ${currentValid ? "" : `<option value="" selected disabled>${escapeHtml(`无效选项 (${current || "空"})，请选择`)}</option>`}
      ${options.map((option) => `
        <option value="${escapeHtml(option.value)}" ${current === option.value ? "selected" : ""}>
          ${escapeHtml(option.label)}
        </option>`).join("")}
    </select>`;
}

function diagramDefinitionSocField(field) {
  const name = String(field || "").trim().toLowerCase();
  return DIAGRAM_DEFINITION_RATIO_FIELDS.has(name) || name.startsWith("soc_");
}

function diagramDefinitionEfficiencyField(field) {
  const name = String(field || "").trim().toLowerCase();
  return name.includes("efficiency")
    || name === "eta"
    || name.startsWith("eta_")
    || name.endsWith("_eta")
    || name.endsWith("_eff");
}

function diagramDefinitionRatioField(field) {
  return diagramDefinitionSocField(field) || diagramDefinitionEfficiencyField(field);
}

function diagramDefinitionRatioFromStored(field, value) {
  const raw = String(value ?? "").trim();
  const explicitPercent = raw.endsWith("%");
  const numericText = explicitPercent ? raw.slice(0, -1).trim() : raw;
  let number = Number(numericText);
  if (!Number.isFinite(number)) return null;
  if (explicitPercent) return number / 100;
  if (diagramDefinitionEfficiencyField(field) && number > 1 && number <= 100) number /= 100;
  if (diagramDefinitionSocField(field) && Math.abs(number) > 2 && Math.abs(number) <= 100) number /= 100;
  return number;
}

function diagramDefinitionNumberText(value) {
  if (!Number.isFinite(Number(value))) return "";
  const number = Number(Number(value).toPrecision(15));
  return Object.is(number, -0) ? "0" : String(number);
}

function diagramDefinitionDisplayValue(field, value) {
  const name = String(field || "").trim().toLowerCase();
  const canonical = diagramDefinitionEnumCanonicalValue({}, field, value);
  if (name === "run_stat") return canonical === "1" ? "投入" : (canonical === "0" ? "退出" : diagramTooltipValue(value));
  if (name === "status") return canonical === "1" ? "闭合" : (canonical === "0" ? "断开" : diagramTooltipValue(value));
  if (name === "closed_status" || name === "closed_status_set") {
    return canonical === "1" ? "闭合" : (canonical === "0" ? "打开" : diagramTooltipValue(value));
  }
  if (name === "control_type" || name === "mode" || name.endsWith("_control_type") || name.endsWith("_mode")) {
    return diagramDefinitionControlModeValue(value);
  }
  if (!diagramDefinitionRatioField(field)) return diagramTooltipValue(value);
  const ratio = diagramDefinitionRatioFromStored(field, value);
  return ratio === null ? diagramTooltipValue(value) : `${diagramDefinitionNumberText(ratio * 100)}%`;
}

function diagramDefinitionStoredValue(field, value) {
  const raw = String(value ?? "").trim();
  if (!diagramDefinitionRatioField(field)) return raw;
  const numericText = raw.endsWith("%") ? raw.slice(0, -1).trim() : raw;
  const percent = Number(numericText);
  return Number.isFinite(percent) ? diagramDefinitionNumberText(percent / 100) : raw;
}

function diagramDefinitionCanonicalStoredValue(field, value) {
  if (!diagramDefinitionRatioField(field)) return String(value ?? "").trim();
  const ratio = diagramDefinitionRatioFromStored(field, value);
  return ratio === null ? String(value ?? "").trim() : diagramDefinitionNumberText(ratio);
}

function diagramDefinitionInputDescriptor(field, value) {
  const raw = String(value ?? "").trim();
  if (diagramDefinitionRatioField(field)) {
    const ratio = diagramDefinitionRatioFromStored(field, value);
    if (ratio !== null) {
      return {
        type: "number",
        value: diagramDefinitionNumberText(ratio * 100),
        suffix: "%",
        min: "0",
        max: "100",
      };
    }
  }
  const suffix = raw.endsWith("%") ? "%" : "";
  const numericText = suffix ? raw.slice(0, -1).trim() : raw;
  const number = Number(numericText);
  return Number.isFinite(number)
    ? { type: "number", value: numericText, suffix, min: "", max: "" }
    : { type: "text", value: raw, suffix: "", min: "", max: "" };
}

function renderDiagramDeviceDefinitionEditor(record, editor, interaction) {
  const canSave = diagramDeviceDefinitionDirtyUpdates(editor).length > 0
    && !interaction?.definitionSaving;
  return `
    <div class="diagram-definition-actions diagram-definition-inline-actions" data-diagram-definition-actions="device">
      <button type="button" data-diagram-definition-cancel>取消</button>
      <button type="button" class="primary" data-diagram-definition-save="device" ${canSave ? "" : "disabled"}>
        ${interaction?.definitionSaving ? "保存中" : "保存"}
      </button>
    </div>
    ${diagramDefinitionEditorMessageHtml(interaction)}`;
}

function renderDiagramDeviceDefinitionValueRow(record, field, activeEditor, interaction) {
  const key = `definition:${record.blockName}:${record.rowIndex}:${field}`;
  const fieldEditable = diagramDeviceParameterEditable(field);
  const editable = Boolean(activeEditor && fieldEditable);
  if (!editable) {
    return `
      <div class="diagram-tooltip-row${fieldEditable ? " is-editable" : ""}" data-diagram-tooltip-row="${escapeHtml(key)}">
        <dt>${escapeHtml(diagramDefinitionFieldLabel(field))}</dt>
        <dd
          data-diagram-definition-value="${escapeHtml(key)}"
          data-diagram-tooltip-value="${escapeHtml(key)}"
          ${fieldEditable ? 'data-diagram-definition-editable="device"' : ""}
        >${escapeHtml(diagramDefinitionDisplayValue(field, record.row[field]))}</dd>
      </div>`;
  }
  const enumRecord = { ...record, row: activeEditor.draft };
  const enumOptions = diagramDefinitionEnumOptions(enumRecord, field);
  if (enumOptions.length) {
    return `
      <div class="diagram-tooltip-row is-editing-definition" data-diagram-tooltip-row="${escapeHtml(key)}">
        <dt>${escapeHtml(diagramDefinitionFieldLabel(field))}</dt>
        <dd data-diagram-definition-value="${escapeHtml(key)}">
          ${renderDiagramDefinitionEnumSelect(
            enumRecord,
            field,
            activeEditor.draft[field],
            interaction,
          )}
        </dd>
      </div>`;
  }
  const descriptor = diagramDefinitionInputDescriptor(field, activeEditor.draft[field]);
  return `
    <div class="diagram-tooltip-row is-editing-definition" data-diagram-tooltip-row="${escapeHtml(key)}">
      <dt>${escapeHtml(diagramDefinitionFieldLabel(field))}</dt>
      <dd data-diagram-definition-value="${escapeHtml(key)}">
        <span class="diagram-definition-input-wrap">
          <input
            class="diagram-definition-input"
            data-diagram-tooltip-inline-input
            data-diagram-definition-input="device"
            data-diagram-definition-field="${escapeHtml(field)}"
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

function renderDiagramDeviceDefinitionRecord(record, interaction) {
  const activeEditor = diagramDeviceDefinitionRecordEditor(
    interaction?.definitionEditor,
    record,
  );
  const displayHeaders = diagramDefinitionDisplayHeaders(record);
  if (!displayHeaders.length) return "";
  const rows = displayHeaders
    .map((field) => renderDiagramDeviceDefinitionValueRow(record, field, activeEditor, interaction))
    .join("");
  return `
    <section class="diagram-tooltip-section diagram-definition-section" data-diagram-definition-block="${escapeHtml(record.blockName)}" data-diagram-definition-row-index="${record.rowIndex}">
      <div class="diagram-definition-section-head">
        <h4>${escapeHtml(record.blockName)} 参数</h4>
      </div>
      <dl class="diagram-tooltip-grid">${rows}</dl>
    </section>`;
}

function diagramDeviceDefinitionRecordsSignature(records) {
  const payload = (records || []).map((record) => {
    const headers = diagramDefinitionDisplayHeaders(record);
    return [
      record.blockName,
      Number(record.rowIndex),
      headers.map((field) => [field, record.row?.[field] ?? ""]),
    ];
  });
  const text = JSON.stringify(payload);
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `${payload.length}:${(hash >>> 0).toString(16)}`;
}

function renderDiagramDeviceDefinitionRecords(records, interaction) {
  if (!records.length) return "";
  const content = records
    .map((record) => renderDiagramDeviceDefinitionRecord(record, interaction))
    .filter(Boolean)
    .join("");
  if (!content) return "";
  return `
    <div
      class="diagram-definition-records"
      data-diagram-definition-records
      data-diagram-definition-signature="${diagramDeviceDefinitionRecordsSignature(records)}"
    >
      ${content}
    </div>`;
}

function renderDiagramDeviceDefinitionFooter(records, interaction) {
  const editor = interaction?.definitionEditor?.kind === "device"
    ? interaction.definitionEditor
    : null;
  const activeRecord = editor
    ? records.find((record) => diagramDeviceDefinitionRecordEditor(editor, record))
    : null;
  const content = activeRecord
    ? renderDiagramDeviceDefinitionEditor(activeRecord, editor, interaction)
    : diagramDefinitionMessageHtml(interaction);
  if (!content) return "";
  return `
    <div class="diagram-definition-footer" data-diagram-definition-footer>
      ${content}
    </div>`;
}

function renderDiagramDeviceClassifiedTable(data, interaction) {
  const [identitySection, ...detailSections] = data.dynamicSections;
  const identitySections = identitySection ? [identitySection] : [];
  return `
    <div
      class="diagram-device-tab-panel"
      role="tabpanel"
      data-diagram-device-tab-panel
      data-diagram-device-active-tab="${escapeHtml(data.activePageKey || "self")}"
      data-diagram-device-dynamic-body
    >
      ${diagramTooltipSectionsHtml(identitySections, interaction)}
      ${renderDiagramDeviceDefinitionRecords(data.definitionRecords, interaction)}
      ${diagramTooltipSectionsHtml(detailSections, interaction)}
      ${renderDiagramDeviceDefinitionFooter(data.definitionRecords, interaction)}
    </div>`;
}

function renderDiagramDeviceTabs(data, interaction) {
  if (!Array.isArray(data?.pages) || data.pages.length <= 1) return "";
  const disabled = diagramDefinitionEditPinned(interaction);
  return `
    <div class="diagram-device-tabs" role="tablist" aria-label="关联设备">
      ${data.pages.map((page) => {
        const active = page.key === data.activePageKey;
        const type = page.device?.devType || "";
        return `
          <button
            type="button"
            class="diagram-device-tab"
            role="tab"
            data-diagram-device-tab="${escapeHtml(page.key)}"
            aria-selected="${active ? "true" : "false"}"
            tabindex="${active ? "0" : "-1"}"
            title="${escapeHtml(type ? `${type} · ${page.label}` : page.label)}"
            ${disabled ? "disabled" : ""}
          >
            <span>${escapeHtml(page.label)}</span>
            ${type ? `<small>${escapeHtml(type)}</small>` : ""}
          </button>`;
      }).join("")}
    </div>`;
}

function renderDiagramDeviceTooltip(container, hover, snapshot, interaction) {
  const data = diagramDeviceTooltipData(container, hover, snapshot, interaction);
  if (!data) return "";
  const leavePrompt = renderDiagramDefinitionLeavePrompt(interaction);
  if (leavePrompt) {
    return `
      <div class="diagram-tooltip-head">
        <strong data-diagram-tooltip-device-name>${escapeHtml(data.title)}</strong>
        <span>设备参数</span>
      </div>
      <div class="diagram-tooltip-body">${leavePrompt}</div>`;
  }
  return `
    <div class="diagram-tooltip-head">
      <strong data-diagram-tooltip-device-name>${escapeHtml(data.title)}</strong>
      <span>设备参数</span>
    </div>
    <div class="diagram-tooltip-body" data-diagram-device-tooltip-body>
      ${renderDiagramDeviceTabs(data, interaction)}
      ${renderDiagramDeviceClassifiedTable(data, interaction)}
    </div>`;
}

function diagramDefinitionEditPinned(interaction) {
  return Boolean(interaction?.definitionEditor || interaction?.definitionSaving);
}

function beginDiagramDeviceDefinitionEdit(container, blockName, rowIndex = 0) {
  const interaction = diagramInteractionState(container);
  const snapshot = interaction.snapshot || state.snapshot || {};
  const pages = diagramCouplingDevicePages(interaction.hover?.device, snapshot);
  const activePage = diagramActiveDeviceTooltipPage(interaction, interaction.hover, pages);
  const records = diagramDeviceDefinitionRecords(activePage?.device, snapshot);
  const record = records.find((item) => (
    item.blockName === String(blockName || "")
    && Number(item.rowIndex) === Number(rowIndex)
  ));
  if (!record || !record.editableFields.length) return false;
  const editorRecords = diagramDeviceDefinitionEditorRecords(records);
  if (!editorRecords.length) return false;
  interaction.definitionEditor = {
    kind: "device",
    blockName: record.blockName,
    rowIndex: record.rowIndex,
    revision: Number(snapshot?.static_meta?.definitions?.revision),
    records: editorRecords,
    dirtyFields: new Set(),
    validationError: "",
    devicePageKey: activePage?.key || "self",
  };
  interaction.definitionSaving = false;
  interaction.definitionLeavePrompt = false;
  interaction.definitionCloseAfterSave = false;
  interaction.definitionMessage = "";
  interaction.definitionMessageWarning = false;
  interaction.tooltip?.classList.add("is-editing-definition");
  renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  return true;
}

function cancelDiagramDefinitionEdit(container) {
  const interaction = diagramInteractionCache.get(container);
  if (!interaction?.definitionEditor && !interaction?.definitionSaving) return false;
  interaction.definitionEditor = null;
  interaction.definitionSaving = false;
  interaction.definitionLeavePrompt = false;
  interaction.definitionCloseAfterSave = false;
  interaction.definitionMessage = "";
  interaction.definitionMessageWarning = false;
  interaction.tooltip?.classList.remove("is-editing-definition");
  renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  return true;
}

function updateDiagramDefinitionSaveState(interaction) {
  const button = interaction?.tooltip?.querySelector("[data-diagram-definition-save]");
  if (!button) return;
  const editor = interaction.definitionEditor;
  const invalid = editor?.validationError;
  button.disabled = Boolean(
    interaction.definitionSaving
    || !editor?.dirtyFields?.size
    || invalid,
  );
  const message = interaction.tooltip.querySelector("[data-diagram-definition-message]");
  if (message && invalid) {
    message.textContent = invalid;
    message.classList.add("is-warning");
  }
}

function updateDiagramDeviceDefinitionDraft(interaction, input) {
  const editor = interaction?.definitionEditor;
  if (editor?.kind !== "device") return false;
  const field = String(input?.getAttribute?.("data-diagram-definition-field") || "");
  if (!diagramDeviceParameterEditable(field)) return false;
  const section = input.closest?.("[data-diagram-definition-block]");
  const blockName = String(section?.getAttribute?.("data-diagram-definition-block") || "");
  const rowIndex = Number(section?.getAttribute?.("data-diagram-definition-row-index") || 0);
  const record = (editor.records || []).find((item) => (
    item.blockName === blockName && Number(item.rowIndex) === rowIndex
  ));
  if (!record || !record.editableFields.includes(field)) return false;
  const enumRecord = { ...record, row: record.draft };
  const enumOptions = diagramDefinitionEnumOptions(enumRecord, field);
  const changes = enumOptions.length
    ? diagramDefinitionCoupledEnumValues(enumRecord, field, input.value)
    : { [field]: diagramDefinitionStoredValue(field, input.value) };
  Object.entries(changes).forEach(([changedField, value]) => {
    if (!record.editableFields.includes(changedField)) return;
    record.draft[changedField] = value;
    const changedRecord = { ...record, row: record.draft };
    const originalValue = diagramDefinitionEnumOptions(changedRecord, changedField).length
      ? diagramDefinitionEnumCanonicalValue(changedRecord, changedField, record.original[changedField])
      : diagramDefinitionCanonicalStoredValue(changedField, record.original[changedField]);
    const dirtyKey = `${record.blockName}:${record.rowIndex}:${changedField}`;
    if (value === originalValue) {
      record.dirtyFields.delete(changedField);
      editor.dirtyFields.delete(dirtyKey);
    } else {
      record.dirtyFields.add(changedField);
      editor.dirtyFields.add(dirtyKey);
    }
    interaction.tooltip?.querySelectorAll?.(`[data-diagram-definition-field="${changedField}"]`).forEach((candidate) => {
      const candidateSection = candidate.closest?.("[data-diagram-definition-block]");
      if (String(candidateSection?.getAttribute?.("data-diagram-definition-block") || "") === record.blockName
          && Number(candidateSection?.getAttribute?.("data-diagram-definition-row-index") || 0) === record.rowIndex) {
        candidate.value = value;
      }
    });
  });
  interaction.definitionMessage = "";
  interaction.definitionMessageWarning = false;
  updateDiagramDefinitionSaveState(interaction);
  return true;
}

async function saveDiagramDeviceDefinitionEdit(container) {
  const interaction = diagramInteractionCache.get(container);
  const editor = interaction?.definitionEditor;
  if (!interaction || editor?.kind !== "device" || interaction.definitionSaving) return false;
  const updates = diagramDeviceDefinitionDirtyUpdates(editor);
  if (!updates.length) return false;
  const closeAfterSave = Boolean(interaction.definitionCloseAfterSave);
  const requestedModelId = state.activeModelId;
  interaction.definitionSaving = true;
  interaction.definitionMessage = `正在更新 ${updates.length} 个参数块并保存人工覆盖层`;
  interaction.definitionMessageWarning = false;
  renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  let completed = 0;
  let revision = editor.revision;
  let resultWarning = false;
  let warningMessage = "";
  let runtimeControlUpdated = false;
  try {
    for (const update of updates) {
      const result = await api("/api/definitions/device-parameters", {
        method: "POST",
        body: JSON.stringify({
          block_name: update.blockName,
          row_key: update.rowKey,
          revision,
          changes: update.changes,
        }),
      });
      applyDefinitionEditResult(result);
      revision = Number(
        result?.revision
        ?? result?.static_meta?.definitions?.revision
        ?? revision,
      );
      completed += 1;
      const updateWarning = definitionEditResultHasWarning(result);
      resultWarning = updateWarning || resultWarning;
      interaction.definitionMessageWarning = resultWarning;
      if (result?.warning) warningMessage = result.warning;
      runtimeControlUpdated = Boolean(result?.runtime_control) || runtimeControlUpdated;
      const savedRecord = (editor.records || []).find((record) => (
        record.blockName === update.blockName && Number(record.rowIndex) === Number(update.rowIndex)
      ));
      Object.keys(update.changes).forEach((field) => {
        if (!savedRecord || updateWarning) return;
        savedRecord.original[field] = savedRecord.draft[field];
        savedRecord.dirtyFields.delete(field);
        editor.dirtyFields.delete(`${savedRecord.blockName}:${savedRecord.rowIndex}:${field}`);
      });
      editor.revision = revision;
    }
    await reloadLocalDefinitionSnapshotAfterEdit(requestedModelId);
    interaction.snapshot = state.snapshot;
    interaction.definitionSaving = false;
    interaction.definitionLeavePrompt = false;
    interaction.definitionCloseAfterSave = false;
    if (resultWarning) {
      interaction.definitionMessage = warningMessage || `${completed} 个参数块已更新，但人工覆盖层保存未完成，请重试`;
      interaction.definitionMessageWarning = true;
      renderActiveDiagramTooltip(container, state.snapshot || {}, interaction);
      return false;
    }
    interaction.definitionEditor = null;
    interaction.definitionMessage = resultWarning
      ? (warningMessage || `${completed} 个参数块已更新，但人工覆盖层需要重试`)
      : (runtimeControlUpdated
        ? `${completed} 个参数块及运行控制覆盖已保存，新能源控制将从下一轮采用新参数`
        : `${completed} 个参数块的人工覆盖已保存，新能源控制将从下一轮采用新参数`);
    interaction.definitionMessageWarning = resultWarning;
    interaction.tooltip?.classList.remove("is-editing-definition");
    if (closeAfterSave) hideDiagramTooltip(container);
    else renderActiveDiagramTooltip(container, state.snapshot || {}, interaction);
    return true;
  } catch (error) {
    interaction.snapshot = state.snapshot;
    interaction.definitionSaving = false;
    interaction.definitionCloseAfterSave = false;
    interaction.definitionMessage = completed
      ? `已保存 ${completed}/${updates.length} 个参数块；后续保存失败：${apiErrorText(error)}`
      : apiErrorText(error);
    interaction.definitionMessageWarning = true;
    renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
    return false;
  }
}

function reorderDiagramChildren(parent, desiredChildren = []) {
  if (!parent) return;
  desiredChildren.filter(Boolean).forEach((child, index) => {
    const current = parent.children[index] || null;
    if (current !== child) parent.insertBefore(child, current);
  });
}

function syncDiagramTooltipSections(body, sections = []) {
  if (!body) return false;
  const definitionAnchor = Array.from(body.children)
    .find((element) => element.hasAttribute("data-diagram-definition-records")) || null;
  const definitionFooter = Array.from(body.children)
    .find((element) => element.hasAttribute("data-diagram-definition-footer")) || null;
  const existingSections = new Map(Array.from(body.children)
    .filter((element) => element.hasAttribute("data-diagram-tooltip-section"))
    .map((element) => [element.getAttribute("data-diagram-tooltip-section") || "", element]));
  const desiredSectionKeys = new Set();
  const desiredSectionElements = [];
  sections.forEach((section) => {
    const sectionKey = String(section.key || "");
    desiredSectionKeys.add(sectionKey);
    let sectionElement = existingSections.get(sectionKey);
    if (!sectionElement) {
      sectionElement = document.createElement("section");
      sectionElement.className = "diagram-tooltip-section";
      sectionElement.setAttribute("data-diagram-tooltip-section", sectionKey);
    }
    let heading = Array.from(sectionElement.children).find((element) => element.tagName === "H4") || null;
    if (section.title) {
      if (!heading) {
        heading = document.createElement("h4");
        sectionElement.prepend(heading);
      }
      heading.textContent = section.title;
    } else if (heading) {
      heading.remove();
    }
    let list = Array.from(sectionElement.children).find((element) => element.classList.contains("diagram-tooltip-grid")) || null;
    if (!list) {
      list = document.createElement("dl");
      list.className = "diagram-tooltip-grid";
      sectionElement.appendChild(list);
    }
    const existingRows = new Map(Array.from(list.children)
      .filter((element) => element.hasAttribute("data-diagram-tooltip-row"))
      .map((element) => [element.getAttribute("data-diagram-tooltip-row") || "", element]));
    const desiredRowKeys = new Set();
    const desiredRows = [];
    section.rows.forEach(([label, value, key, binding], index) => {
      const rowKey = String(key || diagramTooltipRowKey(sectionKey, label, index));
      desiredRowKeys.add(rowKey);
      let rowElement = existingRows.get(rowKey);
      if (!rowElement) {
        rowElement = document.createElement("div");
        rowElement.className = "diagram-tooltip-row";
        rowElement.setAttribute("data-diagram-tooltip-row", rowKey);
        const term = document.createElement("dt");
        const description = document.createElement("dd");
        description.setAttribute("data-diagram-tooltip-value", rowKey);
        rowElement.append(term, description);
      }
      const term = rowElement.querySelector("dt");
      const description = rowElement.querySelector("dd");
      const inlineInput = description?.querySelector("[data-diagram-tooltip-inline-input]");
      if (term) term.textContent = label;
      if (description && !inlineInput) {
        description.textContent = binding
          ? diagramDefinitionDisplayValue(binding.field, value)
          : diagramTooltipValue(value);
      }
      if (!inlineInput) {
        rowElement.className = `diagram-tooltip-row${binding?.editable ? " is-editable" : ""}`;
        if (binding) {
          rowElement.setAttribute("data-diagram-definition-block", binding.blockName);
          rowElement.setAttribute("data-diagram-definition-row-index", String(binding.rowIndex));
        } else {
          rowElement.removeAttribute("data-diagram-definition-block");
          rowElement.removeAttribute("data-diagram-definition-row-index");
        }
        if (description) {
          if (binding?.editable) description.setAttribute("data-diagram-definition-editable", "device");
          else description.removeAttribute("data-diagram-definition-editable");
        }
      }
      desiredRows.push(rowElement);
    });
    existingRows.forEach((element, key) => {
      if (!desiredRowKeys.has(key)) element.remove();
    });
    reorderDiagramChildren(list, desiredRows);
    desiredSectionElements.push(sectionElement);
  });
  existingSections.forEach((element, key) => {
    if (!desiredSectionKeys.has(key)) element.remove();
  });
  const desiredBodyChildren = definitionAnchor
    ? [desiredSectionElements[0], definitionAnchor, ...desiredSectionElements.slice(1)]
    : [...desiredSectionElements];
  if (definitionFooter) desiredBodyChildren.push(definitionFooter);
  reorderDiagramChildren(body, desiredBodyChildren);
  return true;
}

function syncDiagramDeviceTabs(tooltip, data, interaction) {
  const body = tooltip?.querySelector("[data-diagram-device-tooltip-body]");
  const panel = body?.querySelector("[data-diagram-device-tab-panel]");
  let tabs = body?.querySelector(".diagram-device-tabs") || null;
  if (!body || !panel) return false;
  panel.setAttribute("data-diagram-device-active-tab", data.activePageKey || "self");
  if (!Array.isArray(data.pages) || data.pages.length <= 1) {
    tabs?.remove();
    return true;
  }
  if (!tabs) {
    tabs = document.createElement("div");
    tabs.className = "diagram-device-tabs";
    tabs.setAttribute("role", "tablist");
    tabs.setAttribute("aria-label", "关联设备");
    body.insertBefore(tabs, panel);
  }
  const existing = new Map(Array.from(tabs.querySelectorAll("[data-diagram-device-tab]"))
    .map((button) => [button.getAttribute("data-diagram-device-tab") || "", button]));
  const desiredKeys = new Set();
  const desiredButtons = data.pages.map((page) => {
    desiredKeys.add(page.key);
    let button = existing.get(page.key);
    if (!button) {
      button = document.createElement("button");
      button.type = "button";
      button.className = "diagram-device-tab";
      button.setAttribute("role", "tab");
      button.setAttribute("data-diagram-device-tab", page.key);
      button.append(document.createElement("span"), document.createElement("small"));
    }
    const active = page.key === data.activePageKey;
    const type = String(page.device?.devType || "");
    button.querySelector("span").textContent = page.label;
    const typeLabel = button.querySelector("small");
    typeLabel.textContent = type;
    typeLabel.hidden = !type;
    button.title = type ? `${type} · ${page.label}` : page.label;
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.tabIndex = active ? 0 : -1;
    button.disabled = diagramDefinitionEditPinned(interaction);
    return button;
  });
  existing.forEach((button, key) => {
    if (!desiredKeys.has(key)) button.remove();
  });
  reorderDiagramChildren(tabs, desiredButtons);
  return true;
}

function updateDiagramDeviceTooltip(container, hover, snapshot, interaction) {
  const tooltip = interaction?.tooltip;
  const data = diagramDeviceTooltipData(container, hover, snapshot, interaction);
  const definitions = tooltip?.querySelector("[data-diagram-definition-records]");
  if (!tooltip || !data) return false;
  syncDiagramDeviceTabs(tooltip, data, interaction);
  const dynamicBody = tooltip.querySelector("[data-diagram-device-dynamic-body]");
  if (!dynamicBody) return false;
  const title = tooltip.querySelector("[data-diagram-tooltip-device-name]");
  if (title) title.textContent = data.title;
  const dynamicUpdated = syncDiagramTooltipSections(dynamicBody, data.dynamicSections);
  if (interaction.definitionEditor?.kind === "device") return dynamicUpdated;
  if (definitions) {
    const definitionSignature = diagramDeviceDefinitionRecordsSignature(data.definitionRecords);
    const currentDefinitionSignature = definitions.getAttribute("data-diagram-definition-signature") || "";
    if (currentDefinitionSignature !== definitionSignature) {
      const definitionHtml = renderDiagramDeviceDefinitionRecords(data.definitionRecords, interaction);
      if (definitionHtml) definitions.outerHTML = definitionHtml;
      else definitions.remove();
    }
  } else if (data.definitionRecords.length) {
    const identitySection = dynamicBody.querySelector('[data-diagram-tooltip-section="identity"]');
    const definitionHtml = renderDiagramDeviceDefinitionRecords(data.definitionRecords, interaction);
    if (definitionHtml) {
      if (identitySection) identitySection.insertAdjacentHTML("afterend", definitionHtml);
      else dynamicBody.insertAdjacentHTML("afterbegin", definitionHtml);
    }
  }
  return dynamicUpdated;
}

function diagramMetricCurrentRow(container, hover, snapshot) {
  const maps = diagramMeasurementMaps(snapshot);
  if (hover?.binding) return diagramMetricBindingValue(hover.binding, maps);
  if (hover?.name) return diagramBindingValue(hover.name, maps, hover.channel || "scada");
  return null;
}

function diagramTrendHistorySeries(row, metricType = "") {
  if (!row) return [];
  const key = measurementKey(row);
  return (state.measurementTraceHistory || []).map((point) => {
    let measurement = point.measurements?.[key];
    if (!measurement) {
      measurement = Object.values(point.measurements || {}).find((item) => (
        normalizeDiagramMeasurementToken(item?.dev_type) === normalizeDiagramMeasurementToken(row.dev_type)
        && String(item?.dev_name || "") === String(row.dev_name || "")
        && normalizeDiagramMeasurementToken(item?.meas_type) === normalizeDiagramMeasurementToken(row.meas_type)
      ));
    }
    if (!measurement) return null;
    const scada = diagramTrendDisplayValue(measurement.scada ?? measurement.value, row, metricType);
    if (scada === null) return null;
    return {
      minute: Number(point.minute),
      time: point.sim_time || point.time || "--",
      scada,
    };
  }).filter((point) => point && Number.isFinite(point.minute));
}

function diagramMetricLabel(metricType, row) {
  const labels = {
    activepower: "有功功率",
    reactivepower: "无功功率",
    voltage: "电压",
    current: "电流",
    status: "状态",
    level: "SOC",
    frequency: "频率",
    flow: "流量",
    pressure: "压力",
    temperature: "温度",
  };
  return labels[normalizeDiagramMetricType(metricType)]
    || row?.meas_type
    || row?.name
    || "动态量测";
}

const DIAGRAM_TREND_SERIES = Object.freeze([
  Object.freeze({ key: "scada", label: "量测值" }),
]);

function diagramTrendFiniteValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function diagramTrendChartModel(points, period, tooltipWidth = 360, currentMinute = null, unit = "", rangeOverride = null) {
  const sourcePoints = Array.isArray(points) ? points : [];
  const targetCount = Math.max(32, Math.floor(Math.max(tooltipWidth, 320) * 0.75));
  const values = sourcePoints.flatMap((point) => DIAGRAM_TREND_SERIES.flatMap((series) => {
    const value = diagramTrendFiniteValue(point?.[series.key]);
    return value === null ? [] : [value];
  }));
  const axis = diagramTrendAxisScale(values, 4);
  const width = 336;
  const height = 148;
  const plot = { left: 52, right: 10, top: 20, bottom: 10 };
  const lastSourcePoint = sourcePoints[sourcePoints.length - 1] || null;
  const fallbackMinute = Number(lastSourcePoint?.minute);
  const defaultRange = diagramTrendPeriodRange(
    period,
    currentMinute !== null && currentMinute !== undefined && currentMinute !== "" && Number.isFinite(Number(currentMinute))
      ? Number(currentMinute)
      : (Number.isFinite(fallbackMinute) ? fallbackMinute : 0),
  );
  const range = Number.isFinite(Number(rangeOverride?.startMinute))
    && Number.isFinite(Number(rangeOverride?.endMinute))
    ? { ...defaultRange, ...rangeOverride }
    : defaultRange;
  const labels = diagramTrendPeriodLabels(period, range);
  const minuteSpan = Math.max(1, range.endMinute - range.startMinute);
  const valueSpan = Math.max(1e-9, axis.max - axis.min);
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const xForMinute = (minute) => plot.left + ((Number(minute) - range.startMinute) / minuteSpan) * plotWidth;
  const yForValue = (value) => plot.top + ((axis.max - Number(value)) / valueSpan) * plotHeight;
  const series = Object.fromEntries(DIAGRAM_TREND_SERIES.map((definition) => {
    const sourceSeries = sourcePoints.map((point) => {
      const value = diagramTrendFiniteValue(point?.[definition.key]);
      return value === null ? null : { minute: point.minute, time: point.time, value };
    }).filter(Boolean);
    const renderedPoints = diagramSampleTrendPoints(sourceSeries, targetCount).map((point) => ({
      ...point,
      x: xForMinute(point.minute),
      y: yForValue(point.value),
    }));
    const numericValues = sourceSeries.map((point) => point.value);
    return [definition.key, {
      ...definition,
      renderedPoints,
      polyline: renderedPoints.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" "),
      min: numericValues.length ? Math.min(...numericValues) : null,
      max: numericValues.length ? Math.max(...numericValues) : null,
      latest: numericValues.length ? numericValues[numericValues.length - 1] : null,
    }];
  }));
  const cursorPoints = sourcePoints.map((point) => {
    const scada = diagramTrendFiniteValue(point?.scada);
    const hasScada = scada !== null;
    if (!hasScada) return null;
    return {
      minute: Number(point.minute),
      time: point.time || "--",
      x: xForMinute(point.minute),
      scada: hasScada ? scada : null,
      scadaY: hasScada ? yForValue(scada) : null,
    };
  }).filter((point) => point && Number.isFinite(point.minute));
  return {
    empty: values.length === 0,
    period: period === "day" ? "day" : "hour",
    unit: String(unit || ""),
    width,
    height,
    plot,
    range,
    labels,
    axis,
    series,
    cursorPoints,
  };
}

function setDiagramTrendChartModel(interaction, model) {
  if (interaction) {
    interaction.trendChart = model.empty ? null : {
      width: model.width,
      height: model.height,
      plot: model.plot,
      range: model.range,
      points: model.cursorPoints,
      series: model.series,
      unit: model.unit,
    };
  }
}

function diagramTrendAxisTicksHtml(model) {
  const valueSpan = Math.max(1e-9, model.axis.max - model.axis.min);
  const plotHeight = model.height - model.plot.top - model.plot.bottom;
  return model.axis.ticks.map((value) => {
    const y = model.plot.top + ((model.axis.max - Number(value)) / valueSpan) * plotHeight;
    return `
      <g class="diagram-trend-y-tick">
        <line x1="${model.plot.left}" y1="${y.toFixed(2)}" x2="${model.width - model.plot.right}" y2="${y.toFixed(2)}" class="diagram-trend-grid-line"></line>
        <text x="${model.plot.left - 7}" y="${(y + 3.5).toFixed(2)}">${escapeHtml(diagramNumberText(value))}</text>
      </g>`;
  }).join("");
}

function diagramTrendNavigationState(range = {}) {
  const periodNavigationAllowed = range.periodNavigationAllowed !== false;
  const windowOffset = Math.min(0, Math.trunc(Number(range.windowOffset) || 0));
  const minWindowOffset = Math.min(0, Math.trunc(Number(range.minWindowOffset) || 0));
  return {
    visible: periodNavigationAllowed && (minWindowOffset < 0 || windowOffset < 0),
    previousDisabled: !periodNavigationAllowed || windowOffset <= minWindowOffset,
    currentDisabled: !periodNavigationAllowed || windowOffset === 0,
    nextDisabled: !periodNavigationAllowed || windowOffset >= 0,
  };
}

function diagramTrendNavigationHtml(range = {}) {
  const navigation = diagramTrendNavigationState(range);
  return `
    <div class="chart-period-navigation diagram-trend-period-navigation" data-diagram-trend-navigation${navigation.visible ? "" : " hidden"}>
      <button type="button" data-diagram-trend-action="previous" aria-label="上一时段" title="上一时段"${navigation.previousDisabled ? " disabled" : ""}>&#8592;</button>
      <button type="button" data-diagram-trend-action="current" aria-label="回到当前时段" title="回到当前时段"${navigation.currentDisabled ? " disabled" : ""}>&#9673;</button>
      <button type="button" data-diagram-trend-action="next" aria-label="下一时段" title="下一时段"${navigation.nextDisabled ? " disabled" : ""}>&#8594;</button>
    </div>`;
}

function diagramTrendChartHtml(points, period, tooltipWidth = 360, currentMinute = null, unit = "", interaction = null, rangeOverride = null) {
  const model = diagramTrendChartModel(points, period, tooltipWidth, currentMinute, unit, rangeOverride);
  setDiagramTrendChartModel(interaction, model);
  return `
    <div class="diagram-trend-empty" data-diagram-trend-empty${model.empty ? "" : " hidden"}>当前分页暂无历史曲线</div>
    <div class="diagram-trend-legend" data-diagram-trend-legend${model.empty ? " hidden" : ""}>
      <span><i class="is-scada"></i>量测值</span>
    </div>
    <svg class="diagram-trend-chart" data-diagram-trend-chart viewBox="0 0 ${model.width} ${model.height}" role="img" aria-label="${model.period === "day" ? "日曲线" : "小时曲线"}"${model.empty ? " hidden" : ""}>
      <text x="${model.plot.left}" y="12" class="diagram-trend-axis-unit" data-diagram-trend-unit>${escapeHtml(model.unit)}</text>
      <g data-diagram-trend-axis-ticks>${diagramTrendAxisTicksHtml(model)}</g>
      <line x1="${model.plot.left}" y1="${model.plot.top}" x2="${model.plot.left}" y2="${model.height - model.plot.bottom}" class="diagram-trend-y-axis"></line>
      <polyline class="diagram-trend-series is-scada" data-diagram-trend-series="scada" points="${model.series.scada.polyline}" fill="none" vector-effect="non-scaling-stroke"></polyline>
      <line x1="0" y1="${model.plot.top}" x2="0" y2="${model.height - model.plot.bottom}" class="diagram-trend-cursor diagram-trend-cursor-line" data-diagram-trend-cursor data-diagram-trend-cursor-line visibility="hidden"></line>
      <circle cx="0" cy="0" r="3.5" class="diagram-trend-cursor diagram-trend-cursor-point is-scada" data-diagram-trend-cursor data-diagram-trend-cursor-point="scada" visibility="hidden"></circle>
      <g class="diagram-trend-cursor diagram-trend-cursor-label" data-diagram-trend-cursor data-diagram-trend-cursor-label visibility="hidden">
        <rect width="136" height="34" rx="4" ry="4"></rect>
        <text x="7" y="13" data-diagram-trend-cursor-time>--</text>
        <text x="7" y="27" data-diagram-trend-cursor-value="scada">--</text>
      </g>
    </svg>
    <div class="diagram-trend-range" data-diagram-trend-range${model.empty ? " hidden" : ""}><span data-diagram-trend-range-start>${escapeHtml(model.labels.start)}</span><span data-diagram-trend-range-end>${escapeHtml(model.labels.end)}</span></div>
    <div class="diagram-trend-stats" data-diagram-trend-stats${model.empty ? " hidden" : ""}>
      <div><span class="diagram-trend-stat-label is-scada">量测值</span><span>最小 <strong data-diagram-trend-stat-scada-min>${model.series.scada.min === null ? "--" : diagramNumberText(model.series.scada.min)}</strong></span><span>最大 <strong data-diagram-trend-stat-scada-max>${model.series.scada.max === null ? "--" : diagramNumberText(model.series.scada.max)}</strong></span><span>最新 <strong data-diagram-trend-stat-scada-latest>${model.series.scada.latest === null ? "--" : diagramNumberText(model.series.scada.latest)}</strong></span></div>
    </div>`;
}

function syncDiagramTrendNavigation(tooltip, range = {}) {
  const container = tooltip?.querySelector?.("[data-diagram-trend-navigation]");
  if (!container) return false;
  const navigation = diagramTrendNavigationState(range);
  container.hidden = !navigation.visible;
  container.dataset.windowOffset = String(Number(range.windowOffset) || 0);
  const previous = container.querySelector('[data-diagram-trend-action="previous"]');
  const current = container.querySelector('[data-diagram-trend-action="current"]');
  const next = container.querySelector('[data-diagram-trend-action="next"]');
  if (previous) previous.disabled = navigation.previousDisabled;
  if (current) current.disabled = navigation.currentDisabled;
  if (next) next.disabled = navigation.nextDisabled;
  return true;
}

function hideDiagramTrendCursor(interaction) {
  if (interaction) interaction.trendCursorClientX = null;
  interaction?.tooltip?.querySelectorAll("[data-diagram-trend-cursor]").forEach((element) => {
    element.setAttribute("visibility", "hidden");
  });
}

function syncDiagramTrendAxisTicks(group, model) {
  if (!group || !model) return false;
  const valueSpan = Math.max(1e-9, model.axis.max - model.axis.min);
  const plotHeight = model.height - model.plot.top - model.plot.bottom;
  const existing = Array.from(group.children);
  model.axis.ticks.forEach((value, index) => {
    let tick = existing[index];
    if (!tick) {
      tick = document.createElementNS("http://www.w3.org/2000/svg", "g");
      tick.classList.add("diagram-trend-y-tick");
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.classList.add("diagram-trend-grid-line");
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      tick.append(line, text);
    }
    const y = model.plot.top + ((model.axis.max - Number(value)) / valueSpan) * plotHeight;
    const line = tick.querySelector("line");
    const text = tick.querySelector("text");
    line?.setAttribute("x1", String(model.plot.left));
    line?.setAttribute("y1", y.toFixed(2));
    line?.setAttribute("x2", String(model.width - model.plot.right));
    line?.setAttribute("y2", y.toFixed(2));
    text?.setAttribute("x", String(model.plot.left - 7));
    text?.setAttribute("y", (y + 3.5).toFixed(2));
    if (text) text.textContent = diagramNumberText(value);
    group.appendChild(tick);
  });
  existing.slice(model.axis.ticks.length).forEach((element) => element.remove());
  return true;
}

function updateDiagramTrendChart(content, points, period, tooltipWidth, currentMinute, unit, interaction, rangeOverride = null) {
  if (!content) return false;
  const model = diagramTrendChartModel(points, period, tooltipWidth, currentMinute, unit, rangeOverride);
  setDiagramTrendChartModel(interaction, model);
  const empty = content.querySelector("[data-diagram-trend-empty]");
  const legend = content.querySelector("[data-diagram-trend-legend]");
  const chart = content.querySelector("[data-diagram-trend-chart]");
  const tickGroup = content.querySelector("[data-diagram-trend-axis-ticks]");
  const seriesElements = Object.fromEntries(DIAGRAM_TREND_SERIES.map((series) => [
    series.key,
    content.querySelector(`[data-diagram-trend-series="${series.key}"]`),
  ]));
  const range = content.querySelector("[data-diagram-trend-range]");
  const stats = content.querySelector("[data-diagram-trend-stats]");
  if (!empty || !legend || !chart || !tickGroup || !range || !stats || Object.values(seriesElements).some((element) => !element)) return false;
  empty.hidden = !model.empty;
  legend.hidden = model.empty;
  chart.toggleAttribute("hidden", model.empty);
  range.hidden = model.empty;
  stats.hidden = model.empty;
  if (model.empty) {
    hideDiagramTrendCursor(interaction);
    return true;
  }
  chart.setAttribute("aria-label", model.period === "day" ? "日曲线" : "小时曲线");
  const unitElement = chart.querySelector("[data-diagram-trend-unit]");
  if (unitElement) unitElement.textContent = model.unit;
  syncDiagramTrendAxisTicks(tickGroup, model);
  DIAGRAM_TREND_SERIES.forEach((definition) => {
    seriesElements[definition.key].setAttribute("points", model.series[definition.key].polyline);
  });
  const rangeStart = range.querySelector("[data-diagram-trend-range-start]");
  const rangeEnd = range.querySelector("[data-diagram-trend-range-end]");
  if (rangeStart) rangeStart.textContent = model.labels.start;
  if (rangeEnd) rangeEnd.textContent = model.labels.end;
  DIAGRAM_TREND_SERIES.forEach((definition) => {
    ["min", "max", "latest"].forEach((field) => {
      const element = stats.querySelector(`[data-diagram-trend-stat-${definition.key}-${field}]`);
      const value = model.series[definition.key][field];
      if (element) element.textContent = value === null ? "--" : diagramNumberText(value);
    });
  });
  if (Number.isFinite(interaction?.trendCursorClientX)) {
    updateDiagramTrendCursor(interaction, chart, { clientX: interaction.trendCursorClientX });
  }
  return true;
}

function updateDiagramTrendCursor(interaction, chart, event) {
  const model = interaction?.trendChart;
  const rect = chart?.getBoundingClientRect?.();
  if (!model?.points?.length || !rect?.width || !Number.isFinite(Number(event?.clientX))) {
    hideDiagramTrendCursor(interaction);
    return;
  }
  const viewX = ((Number(event.clientX) - rect.left) / rect.width) * model.width;
  const plotWidth = model.width - model.plot.left - model.plot.right;
  if (viewX < model.plot.left || viewX > model.width - model.plot.right || plotWidth <= 0) {
    hideDiagramTrendCursor(interaction);
    return;
  }
  interaction.trendCursorClientX = Number(event.clientX);
  const targetMinute = model.range.startMinute
    + ((viewX - model.plot.left) / plotWidth) * (model.range.endMinute - model.range.startMinute);
  const point = diagramNearestTrendPoint(model.points, targetMinute);
  const line = chart.querySelector("[data-diagram-trend-cursor-line]");
  const markers = Object.fromEntries(DIAGRAM_TREND_SERIES.map((series) => [
    series.key,
    chart.querySelector(`[data-diagram-trend-cursor-point="${series.key}"]`),
  ]));
  const label = chart.querySelector("[data-diagram-trend-cursor-label]");
  const timeText = chart.querySelector("[data-diagram-trend-cursor-time]");
  const valueTexts = Object.fromEntries(DIAGRAM_TREND_SERIES.map((series) => [
    series.key,
    chart.querySelector(`[data-diagram-trend-cursor-value="${series.key}"]`),
  ]));
  if (!point || !line || !label || !timeText || Object.values(markers).some((element) => !element) || Object.values(valueTexts).some((element) => !element)) {
    hideDiagramTrendCursor(interaction);
    return;
  }
  line.setAttribute("x1", point.x.toFixed(2));
  line.setAttribute("x2", point.x.toFixed(2));
  const pointYs = DIAGRAM_TREND_SERIES.flatMap((series) => {
    const y = diagramTrendFiniteValue(point[`${series.key}Y`]);
    return y === null ? [] : [y];
  });
  const anchorY = pointYs.length ? Math.min(...pointYs) : model.plot.top;
  const labelWidth = 136;
  const labelHeight = 34;
  const labelGap = 8;
  const maxLabelX = model.width - model.plot.right - labelWidth - 2;
  const labelX = Math.max(model.plot.left + 2, Math.min(point.x + labelGap, maxLabelX));
  const preferredY = anchorY - labelHeight - labelGap;
  const fallbackY = anchorY + labelGap;
  const labelY = Math.max(
    model.plot.top + 2,
    Math.min(preferredY >= model.plot.top ? preferredY : fallbackY, model.height - model.plot.bottom - labelHeight - 2),
  );
  label.setAttribute("transform", `translate(${labelX.toFixed(2)} ${labelY.toFixed(2)})`);
  timeText.textContent = point.time || "--";
  DIAGRAM_TREND_SERIES.forEach((series) => {
    const value = diagramTrendFiniteValue(point[series.key]);
    const y = diagramTrendFiniteValue(point[`${series.key}Y`]);
    const available = value !== null && y !== null;
    markers[series.key].setAttribute("cx", point.x.toFixed(2));
    if (available) markers[series.key].setAttribute("cy", y.toFixed(2));
    markers[series.key].setAttribute("visibility", available ? "visible" : "hidden");
    const text = available ? diagramNumberText(value) : "--";
    valueTexts[series.key].textContent = `${series.label} ${model.unit && available ? `${text} ${model.unit}` : text}`;
  });
  line.setAttribute("visibility", "visible");
  label.setAttribute("visibility", "visible");
}

function diagramMetricTooltipData(container, hover, snapshot, interaction) {
  const pair = diagramMetricMeasurementPair(hover, snapshot);
  const row = pair.row || diagramMetricCurrentRow(container, hover, snapshot);
  const metricType = hover?.binding?.metricType || hover?.metricType || "";
  const scadaValue = diagramTrendDisplayValue(pair.scadaValue, pair.scadaRow || row, metricType);
  const unit = row?.unit || diagramMeasurementUnit(row?.meas_type || metricType);
  const period = interaction.trendPeriod === "day" ? "day" : "hour";
  const history = diagramTrendHistorySeries(pair.scadaRow || row, metricType);
  const endMinute = Number(snapshot?.clock?.absolute_minute ?? snapshot?.clock?.minute);
  const requestedOffset = Number(interaction?.trendPeriodOffsets?.[period]) || 0;
  const trendRange = diagramTrendNavigationRange(
    history,
    period,
    Number.isFinite(endMinute) ? endMinute : null,
    requestedOffset,
    curveDisplayModeDurationMinutes(),
  );
  if (interaction) {
    interaction.trendPeriodOffsets = {
      ...(interaction.trendPeriodOffsets || { hour: 0, day: 0 }),
      [period]: trendRange.windowOffset,
    };
    interaction.trendNavigationRange = trendRange;
  }
  const windowPoints = diagramTrendWindowPoints(
    history,
    period,
    Number.isFinite(endMinute) ? endMinute : null,
    trendRange.windowOffset,
    trendRange,
  );
  const deviceName = hover?.binding?.devName || row?.dev_name || row?.name || "动态量测";
  const metricLabel = diagramMetricLabel(metricType, row);
  const validText = pair.row || pair.definition
    ? diagramMeasurementStatusLabel(pair.status, pair.valid)
    : "缺失";
  return {
    deviceName,
    metricLabel,
    displayText: formatMeasurementDisplayValue(scadaValue, pair.row, diagramNumberText),
    scadaValue,
    scadaText: formatMeasurementDisplayValue(scadaValue, pair.row, diagramNumberText),
    valid: pair.valid,
    status: pair.status,
    statusText: validText,
    fixedValue: pair.fixedValue,
    fixedValueText: pair.fixedValue === null ? "--" : diagramNumberText(pair.fixedValue),
    unit: String(unit || ""),
    validText,
    weight: pair.weight,
    weightText: pair.weight === null ? "--" : String(pair.weight),
    errorSigma: pair.errorSigma,
    errorSigmaText: pair.errorSigma === null ? "--" : String(pair.errorSigma),
    definition: pair.definition,
    measurementName: pair.name,
    devType: pair.devType,
    devName: pair.devName,
    measType: pair.measType,
    period,
    endMinute: Number.isFinite(endMinute) ? endMinute : null,
    trendRange,
    windowPoints,
  };
}

function ensureDiagramMetricMeasurementHistory(container, hover, snapshot, interaction) {
  const pair = diagramMetricMeasurementPair(hover, snapshot);
  const row = pair.scadaRow || pair.row || diagramMetricCurrentRow(container, hover, snapshot);
  if (!row) return;
  const hoverKey = String(hover?.key || "");
  ensureMeasurementHistoryForRow(row).then((changed) => {
    const current = diagramInteractionCache.get(container);
    if (
      changed
      && current === interaction
      && String(current?.hover?.key || "") === hoverKey
      && !current?.tooltip?.hidden
    ) {
      refreshDiagramTooltip(container, current.snapshot || state.snapshot || {});
    }
  });
}

function diagramMeasurementValueWithUnit(text, unit) {
  return text === "--" || !unit ? text : `${text} ${unit}`;
}

function renderDiagramMeasurementStatusOptions(selected) {
  return Object.entries(DIAGRAM_MEASUREMENT_STATUS_LABELS).map(([value, label]) => (
    `<option value="${value}" ${value === selected ? "selected" : ""}>${label}</option>`
  )).join("");
}

function renderDiagramMeasurementSummary(data, editor = null, interaction = null) {
  const editing = Boolean(editor);
  const editableDefinition = Boolean(data.definition);
  const measurementEditableAttr = !editing && editableDefinition ? 'data-diagram-definition-editable="measurement"' : "";
  const status = diagramMeasurementStatus(editor?.draft?.status ?? data.status, data.valid);
  const statusValue = editing
    ? `<select class="diagram-definition-input" data-diagram-tooltip-inline-input data-diagram-definition-input="measurement" data-diagram-measurement-definition-field="status" data-diagram-measurement-valid ${interaction?.definitionSaving ? "disabled" : ""}>${renderDiagramMeasurementStatusOptions(status)}</select>`
    : `<span data-diagram-measurement-valid>${escapeHtml(diagramMeasurementStatusLabel(status, data.valid))}</span>`;
  const sigmaValue = editing
    ? `<input class="diagram-definition-input" data-diagram-tooltip-inline-input data-diagram-definition-input="measurement" data-diagram-measurement-definition-field="errorSigma" data-diagram-measurement-sigma type="number" min="0" step="any" value="${escapeHtml(editor.draft.errorSigma)}" ${interaction?.definitionSaving ? "disabled" : ""}>`
    : `<span data-diagram-measurement-sigma>${escapeHtml(data.errorSigmaText)}</span>`;
  const weightValue = editing
    ? `<input class="diagram-definition-input" data-diagram-tooltip-inline-input data-diagram-definition-input="measurement" data-diagram-measurement-definition-field="weight" data-diagram-measurement-weight type="number" min="0" step="any" value="${escapeHtml(editor.draft.weight)}" ${interaction?.definitionSaving ? "disabled" : ""}>`
    : `<span data-diagram-measurement-weight>${escapeHtml(data.weightText)}</span>`;
  const fixedValue = editing ? editor.draft.fixedValue : data.fixedValue;
  const isSignalMeas = ["RUN_STAT", "STATUS"].includes(
    String(data.definition?.meas_type || data.measType || data.meas_type || "").toUpperCase(),
  );
  const fixedValueText = fixedValue === null || fixedValue === undefined || fixedValue === ""
    ? "--"
    : diagramNumberText(fixedValue);
  const fixedValueControl = isSignalMeas
    ? `<select class="diagram-definition-input" data-diagram-tooltip-inline-input data-diagram-definition-input="measurement" data-diagram-measurement-definition-field="fixedValue" ${interaction?.definitionSaving ? "disabled" : ""}>
        <option value="1" ${Number(fixedValue) === 1 ? "selected" : ""}>1 · 投入 / 闭合</option>
        <option value="0" ${Number(fixedValue) !== 1 ? "selected" : ""}>0 · 退出 / 断开</option>
      </select>`
    : `<input class="diagram-definition-input" data-diagram-tooltip-inline-input data-diagram-definition-input="measurement" data-diagram-measurement-definition-field="fixedValue" type="number" step="any" value="${escapeHtml(fixedValueText)}" ${interaction?.definitionSaving ? "disabled" : ""}>`;
  const fixedValueCell = status === "fixed"
    ? `<div>
        <dt>固定值</dt>
        <dd data-diagram-measurement-fixed-value ${measurementEditableAttr}>${editing
          ? fixedValueControl
          : escapeHtml(fixedValueText)}</dd>
      </div>`
    : "";
  return `
    <dl class="diagram-measurement-summary">
      <div>
        <dt>量测值</dt>
        <dd><strong data-diagram-tooltip-current-value data-diagram-measurement-scada>${escapeHtml(data.scadaText)}</strong><span data-diagram-tooltip-current-unit>${escapeHtml(data.unit)}</span></dd>
      </div>
      <div>
        <dt>量测状态</dt>
        <dd data-diagram-tooltip-validity ${measurementEditableAttr}>${statusValue}</dd>
      </div>
      <div>
        <dt>误差 σ</dt>
        <dd ${measurementEditableAttr}>${sigmaValue}</dd>
      </div>
      <div>
        <dt>权重</dt>
        <dd ${measurementEditableAttr}>${weightValue}</dd>
      </div>
      ${fixedValueCell}
    </dl>
    ${editing ? renderDiagramMeasurementDefinitionEditor(editor, interaction) : ""}`;
}

function syncDiagramMeasurementDefinitionFields(editor, changedField = "") {
  if (!editor || editor.kind !== "measurement") return { valid: false, error: "量测定义编辑器无效" };
  const sigma = Number(editor.draft.errorSigma);
  const weight = Number(editor.draft.weight);
  if (changedField === "errorSigma" && Number.isFinite(sigma) && sigma > 0) {
    editor.draft.weight = String(diagramDefinitionWeightFromSigma(sigma));
  } else if (changedField === "weight" && Number.isFinite(weight) && weight > 0) {
    editor.draft.errorSigma = String(diagramDefinitionSigmaFromWeight(weight));
  }
  const nextSigma = Number(editor.draft.errorSigma);
  const nextWeight = Number(editor.draft.weight);
  const nextStatus = diagramMeasurementStatus(editor.draft.status, editor.original?.valid);
  editor.draft.status = nextStatus;
  const nextFixedValue = Number(editor.draft.fixedValue);
  let error = "";
  if (!Number.isFinite(nextSigma) || nextSigma <= 0) error = "误差 σ 必须大于 0";
  else if (!Number.isFinite(nextWeight) || nextWeight <= 0) error = "权重必须大于 0";
  else if (nextStatus === "fixed" && !Number.isFinite(nextFixedValue)) error = "固定值必须为有限数字";
  editor.validationError = error;
  return { valid: !error, error };
}

function renderDiagramMeasurementDefinitionEditor(editor, interaction) {
  syncDiagramMeasurementDefinitionFields(editor);
  const canSave = editor.dirtyFields?.size > 0
    && !editor.validationError
    && !interaction?.definitionSaving;
  return `
    <div class="diagram-definition-actions diagram-measurement-definition-editor" data-diagram-definition-actions="measurement">
      <button type="button" data-diagram-definition-cancel>取消</button>
      <button type="button" class="primary" data-diagram-definition-save="measurement" ${canSave ? "" : "disabled"}>
        ${interaction?.definitionSaving ? "保存中" : "保存"}
      </button>
    </div>
    ${diagramDefinitionEditorMessageHtml(interaction, editor.validationError)}`;
}

function beginDiagramMeasurementDefinitionEdit(container) {
  const interaction = diagramInteractionState(container);
  const snapshot = interaction.snapshot || state.snapshot || {};
  const data = diagramMetricTooltipData(container, interaction.hover, snapshot, interaction);
  if (!data.definition || !data.measurementName) return false;
  const originalWeight = data.weight === null ? String(data.definition.weight ?? "") : String(data.weight);
  const originalSigma = data.errorSigma === null ? "" : String(data.errorSigma);
  interaction.definitionEditor = {
    kind: "measurement",
    name: data.measurementName,
    devType: data.devType,
    devName: data.devName,
    measType: data.measType,
    revision: Number(snapshot?.static_meta?.definitions?.revision),
    original: {
      weight: originalWeight,
      errorSigma: originalSigma,
      status: data.status,
      fixedValue: data.fixedValue === null ? "" : String(data.fixedValue),
      valid: String(data.valid),
    },
    draft: {
      weight: originalWeight,
      errorSigma: originalSigma,
      status: data.status,
      fixedValue: data.fixedValue === null ? "" : String(data.fixedValue),
      valid: String(data.valid),
    },
    dirtyFields: new Set(),
    validationError: "",
  };
  interaction.definitionSaving = false;
  interaction.definitionLeavePrompt = false;
  interaction.definitionCloseAfterSave = false;
  interaction.definitionMessage = "";
  interaction.definitionMessageWarning = false;
  interaction.tooltip?.classList.add("is-editing-definition");
  renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  return true;
}

function updateDiagramMeasurementDefinitionDraft(interaction, input) {
  const editor = interaction?.definitionEditor;
  if (editor?.kind !== "measurement") return false;
  const field = String(input?.getAttribute?.("data-diagram-measurement-definition-field") || "");
  if (!["errorSigma", "weight", "status", "fixedValue"].includes(field)) return false;
  editor.draft[field] = String(input.value ?? "");
  if (field === "errorSigma" || field === "weight") {
    syncDiagramMeasurementDefinitionFields(editor, field);
    ["errorSigma", "weight"].forEach((pairedField) => {
      if (diagramDefinitionPendingValuesEqual(
        pairedField,
        editor.original[pairedField],
        editor.draft[pairedField],
        "measurement",
      )) editor.dirtyFields.delete(pairedField);
      else editor.dirtyFields.add(pairedField);
    });
    const counterpartField = field === "errorSigma" ? "weight" : "errorSigma";
    const counterpart = interaction.tooltip?.querySelector(`[data-diagram-measurement-definition-field="${counterpartField}"]`);
    if (counterpart) counterpart.value = editor.draft[counterpartField];
  } else if (field === "status") {
    syncDiagramMeasurementDefinitionFields(editor, field);
    if (String(editor.draft.status) === String(editor.original.status)) editor.dirtyFields.delete("status");
    else editor.dirtyFields.add("status");
    if (editor.draft.status !== "fixed") {
      editor.dirtyFields.delete("fixedValue");
    } else if (String(editor.draft.fixedValue) === String(editor.original.fixedValue)) {
      editor.dirtyFields.delete("fixedValue");
    } else {
      editor.dirtyFields.add("fixedValue");
    }
  } else {
    syncDiagramMeasurementDefinitionFields(editor, field);
    if (String(editor.draft.fixedValue) === String(editor.original.fixedValue)) editor.dirtyFields.delete("fixedValue");
    else editor.dirtyFields.add("fixedValue");
  }
  interaction.definitionMessage = "";
  interaction.definitionMessageWarning = false;
  const message = interaction.tooltip?.querySelector("[data-diagram-definition-message]");
  if (message) {
    message.textContent = editor.validationError || "";
    message.classList.toggle("is-warning", Boolean(editor.validationError));
    message.hidden = !editor.validationError;
  }
  updateDiagramDefinitionSaveState(interaction);
  if (field === "status") renderActiveDiagramTooltip(interaction.container, interaction.snapshot || state.snapshot || {}, interaction);
  return true;
}

async function saveDiagramMeasurementDefinitionEdit(container) {
  const interaction = diagramInteractionCache.get(container);
  const editor = interaction?.definitionEditor;
  if (!interaction || editor?.kind !== "measurement" || interaction.definitionSaving) return false;
  const validation = syncDiagramMeasurementDefinitionFields(editor);
  if (!validation.valid || !editor.dirtyFields.size) {
    interaction.definitionLeavePrompt = false;
    interaction.definitionCloseAfterSave = false;
    updateDiagramDefinitionSaveState(interaction);
    renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
    return false;
  }
  const closeAfterSave = Boolean(interaction.definitionCloseAfterSave);
  const requestedModelId = state.activeModelId;
  interaction.definitionSaving = true;
  interaction.definitionMessage = "正在更新学员台后台定义并保存人工覆盖层";
  interaction.definitionMessageWarning = false;
  renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  try {
    const result = await api("/api/definitions/measurement", {
      method: "POST",
      body: JSON.stringify({
        name: editor.name,
        dev_type: editor.devType,
        dev_name: editor.devName,
        meas_type: editor.measType,
        revision: editor.revision,
        changes: {
          weight: Number(editor.draft.weight),
          error_sigma: Number(editor.draft.errorSigma),
          status: editor.draft.status,
          ...(editor.draft.status === "fixed" ? { fixed_value: Number(editor.draft.fixedValue) } : {}),
        },
      }),
    });
    applyDefinitionEditResult(result);
    editor.revision = Number(
      result?.revision
      ?? result?.static_meta?.definitions?.revision
      ?? editor.revision,
    );
    await reloadLocalDefinitionSnapshotAfterEdit(requestedModelId);
    interaction.snapshot = state.snapshot;
    interaction.definitionSaving = false;
    interaction.definitionLeavePrompt = false;
    interaction.definitionCloseAfterSave = false;
    const resultWarning = definitionEditResultHasWarning(result);
    interaction.definitionMessageWarning = resultWarning;
    if (resultWarning) {
      interaction.definitionSaving = false;
      interaction.definitionLeavePrompt = false;
      interaction.definitionCloseAfterSave = false;
      interaction.definitionMessage = result.warning || "学员台后台定义已更新，但人工覆盖层保存未完成，请重试";
      interaction.definitionMessageWarning = true;
      renderActiveDiagramTooltip(container, state.snapshot || {}, interaction);
      return false;
    }
    interaction.definitionEditor = null;
    interaction.definitionMessage = resultWarning
      ? (result.warning || "学员台后台定义已更新，但人工覆盖层保存未完成，请重试")
      : "学员台后台定义及人工覆盖层已保存";
    interaction.definitionMessageWarning = resultWarning;
    interaction.tooltip?.classList.remove("is-editing-definition");
    if (closeAfterSave) hideDiagramTooltip(container);
    else renderActiveDiagramTooltip(container, state.snapshot || {}, interaction);
    return true;
  } catch (error) {
    interaction.definitionSaving = false;
    interaction.definitionCloseAfterSave = false;
    interaction.definitionMessage = apiErrorText(error);
    interaction.definitionMessageWarning = true;
    renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
    return false;
  }
}

function renderDiagramMetricTooltip(container, hover, snapshot, interaction) {
  const data = diagramMetricTooltipData(container, hover, snapshot, interaction);
  const leavePrompt = renderDiagramDefinitionLeavePrompt(interaction);
  if (leavePrompt) {
    return `
      <div class="diagram-tooltip-head">
        <strong data-diagram-tooltip-device-name>${escapeHtml(data.deviceName)}</strong>
        <span>${escapeHtml(data.metricLabel)}</span>
      </div>
      <div class="diagram-metric-current">${leavePrompt}</div>`;
  }
  const editor = interaction?.definitionEditor?.kind === "measurement"
    && interaction.definitionEditor.name === data.measurementName
    ? interaction.definitionEditor
    : null;
  return `
    <div class="diagram-tooltip-head">
      <strong data-diagram-tooltip-device-name>${escapeHtml(data.deviceName)}</strong>
      <span data-diagram-tooltip-metric-label>${escapeHtml(data.metricLabel)}</span>
    </div>
    <div class="diagram-metric-current" data-diagram-measurement-summary>
      ${renderDiagramMeasurementSummary(data, editor, interaction)}
    </div>
    ${!editor ? diagramDefinitionMessageHtml(interaction) : ""}
    <div class="diagram-trend-tabs" role="tablist" aria-label="量测趋势范围">
      <button type="button" data-diagram-trend-period="hour" class="${data.period === "hour" ? "is-active" : ""}" aria-selected="${data.period === "hour"}">小时曲线</button>
      <button type="button" data-diagram-trend-period="day" class="${data.period === "day" ? "is-active" : ""}" aria-selected="${data.period === "day"}">日曲线</button>
      ${diagramTrendNavigationHtml(data.trendRange)}
    </div>
    <div class="diagram-trend-content" data-diagram-trend-content>
      ${diagramTrendChartHtml(data.windowPoints, data.period, interaction.tooltip?.clientWidth || 360, data.endMinute, data.unit, interaction, data.trendRange)}
    </div>`;
}

function updateDiagramMetricDynamicValues(tooltip, data) {
  if (!tooltip || !data) return false;
  const values = [
    ["[data-diagram-tooltip-device-name]", data.deviceName],
    ["[data-diagram-tooltip-metric-label]", data.metricLabel],
    ["[data-diagram-measurement-scada]", data.scadaText],
    ["[data-diagram-tooltip-current-unit]", data.unit],
    ["[data-diagram-measurement-valid]", data.validText],
    ["[data-diagram-measurement-sigma]", data.errorSigmaText],
    ["[data-diagram-measurement-weight]", data.weightText],
    ["[data-diagram-measurement-fixed-value]", data.fixedValueText],
  ];
  let updated = true;
  values.forEach(([selector, value]) => {
    const element = tooltip.querySelector(selector);
    if (!element) {
      if (selector === "[data-diagram-measurement-fixed-value]") return;
      updated = false;
      return;
    }
    if (!["INPUT", "SELECT", "TEXTAREA"].includes(element.tagName) && !element.querySelector("input,select,textarea")) element.textContent = value;
  });
  const statusControl = tooltip.querySelector('[data-diagram-measurement-definition-field="status"]');
  const expectedStatus = diagramMeasurementStatus(
    statusControl?.value || data.status,
    data.valid,
  );
  const hasFixedValueRow = Boolean(tooltip.querySelector("[data-diagram-measurement-fixed-value]"));
  if ((expectedStatus === "fixed") !== hasFixedValueRow) updated = false;
  return updated;
}

function updateDiagramMetricTooltip(container, hover, snapshot, interaction) {
  const tooltip = interaction?.tooltip;
  if (!tooltip) return false;
  const data = diagramMetricTooltipData(container, hover, snapshot, interaction);
  const content = tooltip.querySelector("[data-diagram-trend-content]");
  if (!content || !updateDiagramMetricDynamicValues(tooltip, data)) return false;
  tooltip.querySelectorAll("[data-diagram-trend-period]").forEach((button) => {
    const selected = button.getAttribute("data-diagram-trend-period") === data.period;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-selected", String(selected));
  });
  if (!syncDiagramTrendNavigation(tooltip, data.trendRange)) return false;
  return updateDiagramTrendChart(
    content,
    data.windowPoints,
    data.period,
    interaction.tooltip?.clientWidth || 360,
    data.endMinute,
    data.unit,
    interaction,
    data.trendRange,
  );
}

function positionDiagramTooltip(interaction) {
  const tooltip = interaction?.tooltip;
  if (!tooltip || tooltip.hidden) return;
  if (!diagramTooltipNeedsPosition(interaction.hover, interaction.tooltipPositionKey)) return;
  const gap = 14;
  const padding = 10;
  const rect = tooltip.getBoundingClientRect();
  let left = interaction.pointer.x + gap;
  let top = interaction.pointer.y + gap;
  if (left + rect.width > window.innerWidth - padding) left = interaction.pointer.x - rect.width - gap;
  if (top + rect.height > window.innerHeight - padding) top = interaction.pointer.y - rect.height - gap;
  tooltip.style.left = `${Math.max(padding, Math.min(left, window.innerWidth - rect.width - padding))}px`;
  tooltip.style.top = `${Math.max(padding, Math.min(top, window.innerHeight - rect.height - padding))}px`;
  interaction.tooltipPositionKey = String(interaction.hover?.key || "");
}

function clearDiagramTooltipHide(interaction) {
  if (!interaction?.hideTimer) return;
  clearTimeout(interaction.hideTimer);
  interaction.hideTimer = null;
}

function hideDiagramTooltip(container) {
  if (!container) {
    document.querySelectorAll(".diagram-tooltip").forEach((tooltip) => {
      tooltip.hidden = true;
      tooltip.classList.remove("is-visible");
    });
    return;
  }
  const interaction = diagramInteractionCache.get(container);
  if (!interaction) return;
  clearDiagramTooltipHide(interaction);
  interaction.hover = null;
  interaction.deviceTooltipHostKey = "";
  interaction.deviceTooltipTabKey = "self";
  interaction.tooltipPositionKey = "";
  interaction.trendPeriodOffsets = { hour: 0, day: 0 };
  interaction.trendNavigationRange = null;
  hideDiagramTrendCursor(interaction);
  interaction.trendChart = null;
  if (interaction.tooltip) {
    interaction.tooltip.hidden = true;
    interaction.tooltip.classList.remove("is-visible");
  }
}

function scheduleDiagramTooltipHide(container) {
  const interaction = diagramInteractionCache.get(container);
  if (!interaction) return;
  clearDiagramTooltipHide(interaction);
  interaction.hideTimer = setTimeout(() => {
    interaction.hideTimer = null;
    if (interaction.definitionSaving || interaction.definitionLeavePrompt) return;
    if (!interaction.definitionEditor) {
      hideDiagramTooltip(container);
      return;
    }
    if (!diagramDefinitionEditorPendingChanges(interaction.definitionEditor).length) {
      interaction.definitionEditor = null;
      interaction.definitionCloseAfterSave = false;
      interaction.tooltip?.classList.remove("is-editing-definition");
      hideDiagramTooltip(container);
      return;
    }
    interaction.definitionLeavePrompt = true;
    interaction.definitionCloseAfterSave = false;
    renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
  }, DIAGRAM_TOOLTIP_HIDE_DELAY_MS);
}

function renderActiveDiagramTooltip(container, snapshot, interaction) {
  const hover = interaction?.hover;
  const tooltip = interaction?.tooltip;
  if (!hover || !tooltip) return false;
  hideDiagramTrendCursor(interaction);
  interaction.trendChart = null;
  const html = hover.kind === "metric"
    ? renderDiagramMetricTooltip(container, hover, snapshot, interaction)
    : renderDiagramDeviceTooltip(container, hover, snapshot, interaction);
  if (!html) {
    hideDiagramTooltip(container);
    return false;
  }
  tooltip.dataset.kind = hover.kind;
  tooltip.dataset.hoverKey = String(hover.key || "");
  tooltip.innerHTML = html;
  tooltip.hidden = false;
  tooltip.classList.add("is-visible");
  tooltip.classList.toggle("is-editing-definition", diagramDefinitionEditPinned(interaction));
  positionDiagramTooltip(interaction);
  if (hover.kind === "metric") {
    ensureDiagramMetricMeasurementHistory(container, hover, snapshot, interaction);
  }
  return true;
}

function refreshDiagramTooltip(container, snapshot = state.snapshot || {}) {
  const interaction = diagramInteractionCache.get(container);
  if (!interaction) return;
  interaction.snapshot = snapshot;
  if (!interaction.hover || !interaction.tooltip) return;
  const hoverKey = String(interaction.hover.key || "");
  if (interaction.tooltip.hidden || interaction.tooltip.dataset.hoverKey !== hoverKey) {
    renderActiveDiagramTooltip(container, snapshot, interaction);
    return;
  }
  const updated = interaction.hover.kind === "metric"
    ? updateDiagramMetricTooltip(container, interaction.hover, snapshot, interaction)
    : updateDiagramDeviceTooltip(container, interaction.hover, snapshot, interaction);
  if (interaction.hover.kind === "metric") {
    ensureDiagramMetricMeasurementHistory(container, interaction.hover, snapshot, interaction);
  }
  if (!updated) renderActiveDiagramTooltip(container, snapshot, interaction);
}

function resetDiagramInteractions(container) {
  if (!container) return;
  const interaction = diagramInteractionCache.get(container);
  if (interaction) {
    clearDiagramTooltipHide(interaction);
    closeDiagramContextMenu(interaction);
    if (interaction.suppressClickTimer) clearTimeout(interaction.suppressClickTimer);
    interaction.selectedDevId = "";
    interaction.hover = null;
    interaction.deviceTooltipHostKey = "";
    interaction.deviceTooltipTabKey = "self";
    interaction.snapshot = null;
    interaction.tooltipPositionKey = "";
    interaction.trendPeriodOffsets = { hour: 0, day: 0 };
    interaction.trendNavigationRange = null;
    interaction.definitionEditor = null;
    interaction.definitionSaving = false;
    interaction.definitionLeavePrompt = false;
    interaction.definitionCloseAfterSave = false;
    interaction.definitionMessage = "";
    interaction.definitionMessageWarning = false;
    hideDiagramTrendCursor(interaction);
    interaction.trendChart = null;
    interaction.drag = null;
    interaction.suppressClick = false;
    interaction.suppressClickTimer = null;
    if (interaction.tooltip) {
      interaction.tooltip.hidden = true;
      interaction.tooltip.classList.remove("is-visible");
      interaction.tooltip.classList.remove("is-editing-definition");
    }
  }
  removeDiagramRuntimeLabels(container);
  removeDiagramFlowArrows(container);
  container.classList.remove("is-diagram-panning");
  container.querySelectorAll(".is-diagram-selected").forEach((element) => element.classList.remove("is-diagram-selected"));
  if (interaction) {
    interaction.selectedElements = null;
    interaction.flowArrowStaticRefKey = "";
    interaction.flowArrowStaticRefMap = null;
  }
  diagramDeviceIndexCache.delete(container);
  diagramDeviceElementsCache.delete(container);
  diagramMetricBindingCache.delete(container);
  diagramRealtimeBindingCache.delete(container);
  diagramViewportCache.delete(container);
}

function diagramViewBox(svg) {
  const values = String(svg?.getAttribute("viewBox") || "")
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  if (values.length !== 4 || values.some((value) => !Number.isFinite(value))) return null;
  const [x, y, width, height] = values;
  if (width <= 0 || height <= 0) return null;
  return { x, y, width, height };
}

function diagramViewportState(container) {
  const svg = container?.querySelector("svg.model-diagram-svg");
  if (!svg) return null;
  const cached = diagramViewportCache.get(container);
  if (cached?.svg === svg) return cached;
  const original = diagramViewBox(svg);
  if (!original) return null;
  const viewport = {
    svg,
    source: { ...original },
    original: { ...original },
    current: { ...original },
  };
  diagramViewportCache.set(container, viewport);
  return viewport;
}

function diagramPointerSvgPoint(svg, event, inverseMatrix = null) {
  if (!svg || !event || typeof svg.createSVGPoint !== "function") return null;
  try {
    const inverse = inverseMatrix || svg.getScreenCTM?.()?.inverse?.();
    if (!inverse) return null;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(inverse);
  } catch (_error) {
    return null;
  }
}

function beginDiagramPan(container, event) {
  if (!event || event.button !== 0 || event.isPrimary === false) return false;
  const viewport = diagramViewportState(container);
  const interaction = diagramInteractionState(container);
  if (!viewport || !(event.target instanceof Element) || event.target.closest("svg") !== viewport.svg) return false;
  let inverseMatrix;
  try {
    inverseMatrix = viewport.svg.getScreenCTM?.()?.inverse?.();
  } catch (_error) {
    inverseMatrix = null;
  }
  const startPoint = diagramPointerSvgPoint(viewport.svg, event, inverseMatrix);
  if (!startPoint || !inverseMatrix) return false;
  if (interaction.suppressClickTimer) clearTimeout(interaction.suppressClickTimer);
  interaction.suppressClick = false;
  interaction.suppressClickTimer = null;
  interaction.drag = {
    pointerId: event.pointerId,
    svg: viewport.svg,
    inverseMatrix,
    startPoint: { x: startPoint.x, y: startPoint.y },
    startClient: { x: event.clientX, y: event.clientY },
    startViewBox: { ...viewport.current },
    moved: false,
  };
  try {
    container.setPointerCapture?.(event.pointerId);
  } catch (_error) {
    // Pointer capture is optional; normal pointer events still support panning inside the canvas.
  }
  return true;
}

function scheduleDiagramViewBoxApply(viewport, container) {
  if (!viewport?.svg) return;
  if (viewport._viewBoxRaf) return;
  viewport._viewBoxRaf = requestAnimationFrame(() => {
    viewport._viewBoxRaf = 0;
    const cur = viewport.current;
    if (cur && viewport.svg) {
      viewport.svg.setAttribute("viewBox", `${cur.x} ${cur.y} ${cur.width} ${cur.height}`);
    }
    if (container) updateDiagramToolbarState(container);
  });
}

function zoomDiagramByFactor(container, factor) {
  const viewport = diagramViewportState(container);
  if (!viewport?.svg || !viewport.current || !viewport.original) return false;
  const focus = {
    x: viewport.current.x + viewport.current.width / 2,
    y: viewport.current.y + viewport.current.height / 2,
  };
  const next = diagramZoomViewBox(viewport.current, viewport.original, focus, factor);
  const changed = ["x", "y", "width", "height"].some((key) => Math.abs(Number(next[key]) - Number(viewport.current[key])) > 1e-7);
  if (!changed) return false;
  viewport.current = { ...next };
  scheduleDiagramViewBoxApply(viewport, container);
  return true;
}

function resetDiagramViewport(container = $("modelDiagramCanvas")) {
  const viewport = diagramViewportState(container);
  if (!viewport) return false;
  fitDiagramViewport(viewport);
  updateDiagramToolbarState(container);
  return true;
}
if (typeof window !== "undefined") {
  window.resetDiagramViewport = resetDiagramViewport;
}

function moveDiagramPan(container, event) {
  const interaction = diagramInteractionCache.get(container);
  const drag = interaction?.drag;
  if (!drag || event.pointerId !== drag.pointerId) return false;
  const clientDistance = Math.hypot(event.clientX - drag.startClient.x, event.clientY - drag.startClient.y);
  if (!drag.moved && clientDistance < DIAGRAM_PAN_THRESHOLD_PX) return false;
  const viewport = diagramViewportState(container);
  if (!viewport || viewport.svg !== drag.svg) return false;
  const point = diagramPointerSvgPoint(viewport.svg, event, drag.inverseMatrix);
  if (!point) return false;
  if (!drag.moved) {
    drag.moved = true;
    container.classList.add("is-diagram-panning");
    hideDiagramTooltip(container);
  }
  const next = diagramPanViewBox(drag.startViewBox, viewport.original, {
    x: point.x - drag.startPoint.x,
    y: point.y - drag.startPoint.y,
  });
  viewport.current = { ...next };
  scheduleDiagramViewBoxApply(viewport, container);
  event.preventDefault();
  return true;
}

function finishDiagramPan(container, event) {
  const interaction = diagramInteractionCache.get(container);
  const drag = interaction?.drag;
  if (!drag || event.pointerId !== drag.pointerId) return false;
  const moved = Boolean(drag.moved);
  interaction.drag = null;
  container.classList.remove("is-diagram-panning");
  try {
    if (container.hasPointerCapture?.(event.pointerId)) container.releasePointerCapture?.(event.pointerId);
  } catch (_error) {
    // The pointer may already have been released by the browser.
  }
  if (moved) {
    interaction.suppressClick = true;
    interaction.suppressClickTimer = setTimeout(() => {
      interaction.suppressClick = false;
      interaction.suppressClickTimer = null;
    }, 0);
    event.preventDefault();
  }
  return moved;
}

function zoomDiagramAtPointer(container, event) {
  const viewport = diagramViewportState(container);
  if (!viewport || !event || !Number.isFinite(Number(event.deltaY)) || Number(event.deltaY) === 0) return false;
  const { svg } = viewport;
  if (!(event.target instanceof Element) || event.target.closest("svg") !== svg) return false;
  const screenMatrix = svg.getScreenCTM?.();
  if (!screenMatrix || typeof screenMatrix.inverse !== "function" || typeof svg.createSVGPoint !== "function") return false;
  let focus;
  try {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    focus = point.matrixTransform(screenMatrix.inverse());
  } catch (_error) {
    return false;
  }
  const factor = Number(event.deltaY) < 0 ? 0.88 : 1.12;
  const next = diagramZoomViewBox(viewport.current, viewport.original, focus, factor);
  const changed = ["x", "y", "width", "height"].some((key) => Math.abs(Number(next[key]) - Number(viewport.current[key])) > 1e-7);
  if (!changed) return false;
  viewport.current = { ...next };
  scheduleDiagramViewBoxApply(viewport, container);
  event.preventDefault();
  return true;
}

function initDiagramInteractions(container) {
  if (!container) return;
  const interaction = diagramInteractionState(container);
  if (interaction.initialized) return;
  interaction.initialized = true;
  const tooltip = document.createElement("div");
  tooltip.className = "diagram-tooltip";
  tooltip.hidden = true;
  tooltip.setAttribute("role", "tooltip");
  document.body.appendChild(tooltip);
  interaction.tooltip = tooltip;
  const contextMenu = document.createElement("div");
  contextMenu.className = "diagram-context-menu";
  contextMenu.hidden = true;
  contextMenu.setAttribute("role", "menu");
  contextMenu.setAttribute("aria-label", "接线图显示选项");
  document.body.appendChild(contextMenu);
  interaction.contextMenu = contextMenu;
  renderDiagramContextMenu(interaction);

  container.addEventListener("pointerdown", (event) => {
    closeDiagramContextMenu(interaction);
    beginDiagramPan(container, event);
  });
  container.addEventListener("pointermove", (event) => {
    interaction.pointer = { x: event.clientX, y: event.clientY };
    if (moveDiagramPan(container, event)) return;
    if (diagramDefinitionEditPinned(interaction)) return;
    const nextHover = diagramHoverTarget(container, event.target);
    const tooltipAction = diagramTooltipPointerMoveAction(
      interaction.hover,
      nextHover,
      Boolean(interaction.tooltip?.hidden),
    );
    if (!nextHover) {
      if (tooltipAction === "schedule-hide") scheduleDiagramTooltipHide(container);
      else hideDiagramTooltip(container);
      return;
    }
    clearDiagramTooltipHide(interaction);
    if (String(interaction.hover?.key || "") !== String(nextHover.key || "")) {
      interaction.trendPeriodOffsets = { hour: 0, day: 0 };
      interaction.trendNavigationRange = null;
    }
    interaction.hover = nextHover;
    if (tooltipAction === "refresh") {
      refreshDiagramTooltip(container, interaction.snapshot || state.snapshot || {});
    } else if (tooltipAction === "position") {
      positionDiagramTooltip(interaction);
    }
  });
  container.addEventListener("pointerup", (event) => finishDiagramPan(container, event));
  container.addEventListener("pointercancel", (event) => finishDiagramPan(container, event));
  container.addEventListener("contextmenu", (event) => {
    const viewport = diagramViewportState(container);
    const target = diagramInteractionEventTarget(container, viewport, event);
    const hover = target ? diagramHoverTarget(container, target) : null;
    const action = diagramContextMenuAction(hover?.kind || "", Boolean(target));
    if (action !== "open") {
      closeDiagramContextMenu(interaction);
      return;
    }
    event.preventDefault();
    hideDiagramTooltip(container);
    openDiagramContextMenu(interaction, event);
  });
  container.addEventListener("dblclick", (event) => {
    const viewport = diagramViewportState(container);
    const target = diagramInteractionEventTarget(container, viewport, event);
    const hover = target ? diagramHoverTarget(container, target) : null;
    const action = diagramSvgDoubleClickAction(hover?.kind || "", Boolean(target));
    if (action === "ignore") return;
    hideDiagramTooltip(container);
    if (action === "command") {
      const devId = diagramTargetDeviceId(container, target);
      openDiagramDeviceCommandForSvgDevice(container, devId);
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if (!fitDiagramViewport(viewport)) return;
    event.preventDefault();
    event.stopPropagation();
  });
  container.addEventListener("pointerleave", () => {
    if (!interaction.drag) scheduleDiagramTooltipHide(container);
  });
  container.addEventListener("click", (event) => {
    if (interaction.suppressClick) {
      if (interaction.suppressClickTimer) clearTimeout(interaction.suppressClickTimer);
      interaction.suppressClick = false;
      interaction.suppressClickTimer = null;
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const viewport = diagramViewportState(container);
    const target = diagramInteractionEventTarget(container, viewport, event);
    const devId = target ? diagramTargetDeviceId(container, target) : "";
    setDiagramSelectedDevice(container, devId);
  });
  container.addEventListener("wheel", (event) => {
    zoomDiagramAtPointer(container, event);
  }, { passive: false });
  tooltip.addEventListener("pointerenter", () => clearDiagramTooltipHide(interaction));
  tooltip.addEventListener("pointermove", (event) => {
    const chart = event.target instanceof Element ? event.target.closest(".diagram-trend-chart") : null;
    if (!chart || !tooltip.contains(chart)) {
      hideDiagramTrendCursor(interaction);
      return;
    }
    updateDiagramTrendCursor(interaction, chart, event);
  });
  tooltip.addEventListener("pointerout", (event) => {
    const chart = event.target instanceof Element ? event.target.closest(".diagram-trend-chart") : null;
    if (!chart) return;
    if (event.relatedTarget instanceof Element && chart.contains(event.relatedTarget)) return;
    hideDiagramTrendCursor(interaction);
  });
  tooltip.addEventListener("pointerleave", () => {
    hideDiagramTrendCursor(interaction);
    scheduleDiagramTooltipHide(container);
  });
  tooltip.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const leaveAction = target.closest("[data-diagram-definition-leave-action]");
    if (leaveAction) {
      clearDiagramTooltipHide(interaction);
      const action = leaveAction.getAttribute("data-diagram-definition-leave-action") || "";
      if (action === "save") {
        interaction.definitionLeavePrompt = false;
        interaction.definitionCloseAfterSave = true;
        if (interaction.definitionEditor?.kind === "measurement") {
          saveDiagramMeasurementDefinitionEdit(container);
        } else {
          saveDiagramDeviceDefinitionEdit(container);
        }
      } else if (action === "discard") {
        interaction.definitionEditor = null;
        interaction.definitionSaving = false;
        interaction.definitionLeavePrompt = false;
        interaction.definitionCloseAfterSave = false;
        interaction.definitionMessage = "";
        interaction.definitionMessageWarning = false;
        interaction.tooltip?.classList.remove("is-editing-definition");
        hideDiagramTooltip(container);
      } else if (action === "continue") {
        interaction.definitionLeavePrompt = false;
        interaction.definitionCloseAfterSave = false;
        renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
      }
      return;
    }
    const deviceTab = target.closest("[data-diagram-device-tab]");
    if (deviceTab) {
      clearDiagramTooltipHide(interaction);
      if (diagramDefinitionEditPinned(interaction)) return;
      const tabKey = deviceTab.getAttribute("data-diagram-device-tab") || "self";
      if (tabKey === interaction.deviceTooltipTabKey) return;
      interaction.deviceTooltipTabKey = tabKey;
      const updated = updateDiagramDeviceTooltip(
        container,
        interaction.hover,
        interaction.snapshot || state.snapshot || {},
        interaction,
      );
      if (!updated) renderActiveDiagramTooltip(container, interaction.snapshot || state.snapshot || {}, interaction);
      interaction.tooltip?.querySelector(`[data-diagram-device-tab="${CSS.escape(tabKey)}"]`)?.focus();
      return;
    }
    const editable = target.closest("[data-diagram-definition-editable]");
    if (editable && !interaction.definitionEditor && !interaction.definitionSaving) {
      if (editable.getAttribute("data-diagram-definition-editable") === "measurement") {
        beginDiagramMeasurementDefinitionEdit(container);
      } else {
        const section = editable.closest("[data-diagram-definition-block]");
        beginDiagramDeviceDefinitionEdit(
          container,
          section?.getAttribute("data-diagram-definition-block") || "",
          Number(section?.getAttribute("data-diagram-definition-row-index") || 0),
        );
      }
      return;
    }
    if (target.closest("[data-diagram-definition-cancel]")) {
      cancelDiagramDefinitionEdit(container);
      return;
    }
    const save = target.closest("[data-diagram-definition-save]");
    if (save) {
      if (save.getAttribute("data-diagram-definition-save") === "measurement") {
        saveDiagramMeasurementDefinitionEdit(container);
      } else {
        saveDiagramDeviceDefinitionEdit(container);
      }
      return;
    }
    const navigationButton = target.closest("[data-diagram-trend-action]");
    if (navigationButton && !navigationButton.disabled) {
      const period = interaction.trendPeriod === "day" ? "day" : "hour";
      const currentOffset = Number(interaction.trendNavigationRange?.windowOffset)
        || Number(interaction.trendPeriodOffsets?.[period])
        || 0;
      const action = navigationButton.getAttribute("data-diagram-trend-action") || "";
      const nextOffset = action === "previous"
        ? currentOffset - 1
        : action === "next" ? currentOffset + 1 : 0;
      interaction.trendPeriodOffsets = {
        ...(interaction.trendPeriodOffsets || { hour: 0, day: 0 }),
        [period]: Math.min(0, nextOffset),
      };
      refreshDiagramTooltip(container, interaction.snapshot || state.snapshot || {});
      return;
    }
    const button = target.closest("[data-diagram-trend-period]");
    if (!button) return;
    const period = button.getAttribute("data-diagram-trend-period") === "day" ? "day" : "hour";
    if (period === interaction.trendPeriod) return;
    interaction.trendPeriod = period;
    refreshDiagramTooltip(container, interaction.snapshot || state.snapshot || {});
  });
  tooltip.addEventListener("input", (event) => {
    const input = event.target instanceof Element ? event.target.closest("[data-diagram-definition-input]") : null;
    if (!input) return;
    if (input.getAttribute("data-diagram-definition-input") === "measurement") {
      updateDiagramMeasurementDefinitionDraft(interaction, input);
    } else {
      updateDiagramDeviceDefinitionDraft(interaction, input);
    }
  });
  tooltip.addEventListener("change", (event) => {
    const input = event.target instanceof Element ? event.target.closest("[data-diagram-definition-input]") : null;
    if (!input || input.getAttribute("data-diagram-definition-input") !== "measurement") return;
    updateDiagramMeasurementDefinitionDraft(interaction, input);
  });
  contextMenu.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-diagram-display-toggle]") : null;
    if (!button) return;
    const key = button.getAttribute("data-diagram-display-toggle") || "";
    if (!Object.prototype.hasOwnProperty.call(DIAGRAM_DISPLAY_PREFERENCES_DEFAULTS, key)) return;
    const nextValue = !diagramDisplayPreferences[key];
    diagramDisplayPreferences = saveDiagramDisplayPreferences({
      ...diagramDisplayPreferences,
      [key]: nextValue,
    });
    applyDiagramDisplayPreferences(container, diagramDisplayPreferences);
    updateDiagramRealtimeBindings(container, interaction.snapshot || state.snapshot || {});
    closeDiagramContextMenu(interaction);
  });
  document.addEventListener("pointerdown", (event) => {
    if (contextMenu.hidden || contextMenu.contains(event.target)) return;
    closeDiagramContextMenu(interaction);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeDiagramContextMenu(interaction);
    if (diagramDefinitionEditPinned(interaction)) cancelDiagramDefinitionEdit(container);
  });
  window.addEventListener("resize", () => closeDiagramContextMenu(interaction));
}



function diagramToolbarTranslate(text) {
  return typeof translatePhrase === "function" ? translatePhrase(text) : text;
}

function updateDiagramToolbarState(container = $("modelDiagramCanvas")) {
  const panel = container?.closest?.(".model-diagram-panel");
  const bar = panel?.querySelector?.(".diagram-floating-toolbar");
  if (!bar) return;
  const prefs = normalizeDiagramDisplayPreferences(diagramDisplayPreferences);
  const flowBtn = bar.querySelector('[data-diagram-tool="flow"]');
  if (flowBtn) {
    flowBtn.classList.toggle("is-active", prefs.flowArrows !== false);
    flowBtn.setAttribute("aria-pressed", prefs.flowArrows !== false ? "true" : "false");
  }
  const measBtn = bar.querySelector('[data-diagram-tool="meas"]');
  if (measBtn) {
    measBtn.classList.toggle("is-active", prefs.measurements !== false);
    measBtn.setAttribute("aria-pressed", prefs.measurements !== false ? "true" : "false");
  }
  const zoomBtn = bar.querySelector('[data-diagram-tool="zoom-reset"]');
  if (zoomBtn) {
    const vp = diagramViewportState(container);
    const pct = vp?.original?.width && vp?.current?.width
      ? Math.round((vp.original.width / vp.current.width) * 100)
      : 100;
    zoomBtn.textContent = `${pct}%`;
  }
}

function refreshDiagramSearchOptions(container) {
  const panel = container?.closest?.(".model-diagram-panel");
  const datalist = panel?.querySelector?.("#diagramDeviceSearchList");
  if (!datalist) return;
  const devices = diagramDeviceIndex(container);
  const seen = new Set();
  const frag = document.createDocumentFragment();
  devices.forEach((info) => {
    const nm = String(info?.devName || "").trim();
    if (!nm || seen.has(nm)) return;
    seen.add(nm);
    const opt = document.createElement("option");
    opt.value = nm;
    frag.appendChild(opt);
  });
  datalist.replaceChildren(frag);
}

function ensureDiagramFloatingToolbar(container) {
  const panel = container?.closest?.(".model-diagram-panel");
  if (!panel) return;
  let bar = panel.querySelector(".diagram-floating-toolbar");
  if (!bar) {
    bar = document.createElement("div");
    bar.className = "diagram-floating-toolbar";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", diagramToolbarTranslate("接线图工具栏"));
    bar.innerHTML = `
      <input type="search" class="diagram-tool-search" list="diagramDeviceSearchList" placeholder="${diagramToolbarTranslate("定位设备...")}" aria-label="${diagramToolbarTranslate("定位设备")}" />
      <datalist id="diagramDeviceSearchList"></datalist>
      <span class="diagram-tool-sep" aria-hidden="true"></span>
      <button type="button" class="diagram-tool-btn" data-diagram-tool="flow" title="${diagramToolbarTranslate("显示或隐藏潮流方向箭头")}">${diagramToolbarTranslate("潮流")}</button>
      <button type="button" class="diagram-tool-btn" data-diagram-tool="meas" title="${diagramToolbarTranslate("显示或隐藏量测值")}">${diagramToolbarTranslate("量测")}</button>
      <span class="diagram-tool-sep" aria-hidden="true"></span>
      <button type="button" class="diagram-tool-btn" data-diagram-tool="zoom-out" title="${diagramToolbarTranslate("缩小")} (-)">−</button>
      <button type="button" class="diagram-tool-btn diagram-tool-zoom" data-diagram-tool="zoom-reset" title="${diagramToolbarTranslate("适应画布")} (0 / F)">100%</button>
      <button type="button" class="diagram-tool-btn" data-diagram-tool="zoom-in" title="${diagramToolbarTranslate("放大")} (+)">+</button>
      <button type="button" class="diagram-tool-btn" data-diagram-tool="fit" title="${diagramToolbarTranslate("适应画布")} (F)">${diagramToolbarTranslate("适应")}</button>
    `;
    const head = panel.querySelector(".panel-head");
    if (head) head.appendChild(bar);
    else panel.prepend(bar);

    const searchInput = bar.querySelector(".diagram-tool-search");
    const runSearch = () => {
      const q = String(searchInput?.value || "").trim();
      if (!q) return;
      const ok = focusDiagramDeviceByName(container, q);
      if (!ok && typeof showUiToast === "function") {
        showUiToast(`${diagramToolbarTranslate("未找到设备")}: ${q}`, "warn", 1600);
      }
    };
    searchInput?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        runSearch();
      }
    });
    searchInput?.addEventListener("change", runSearch);

    bar.addEventListener("click", (event) => {
      const btn = event.target instanceof Element ? event.target.closest("[data-diagram-tool]") : null;
      if (!btn) return;
      const action = btn.dataset.diagramTool;
      if (action === "zoom-in") {
        zoomDiagramByFactor(container, 0.82);
      } else if (action === "zoom-out") {
        zoomDiagramByFactor(container, 1.22);
      } else if (action === "zoom-reset" || action === "fit") {
        resetDiagramViewport(container);
      } else if (action === "flow") {
        diagramDisplayPreferences = saveDiagramDisplayPreferences({
          ...diagramDisplayPreferences,
          flowArrows: diagramDisplayPreferences.flowArrows === false,
        });
        applyDiagramDisplayPreferences(container, diagramDisplayPreferences);
        updateDiagramRealtimeBindings(container, state.snapshot || {});
        updateDiagramToolbarState(container);
      } else if (action === "meas") {
        diagramDisplayPreferences = saveDiagramDisplayPreferences({
          ...diagramDisplayPreferences,
          measurements: diagramDisplayPreferences.measurements === false,
        });
        applyDiagramDisplayPreferences(container, diagramDisplayPreferences);
        updateDiagramRealtimeBindings(container, state.snapshot || {});
        updateDiagramToolbarState(container);
      }
    });

    if (!window.__polarDiagramShortcutsBound) {
      window.__polarDiagramShortcutsBound = true;
      document.addEventListener("keydown", (event) => {
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (typeof currentPageName === "function" && currentPageName() !== "diagram") return;
        const active = document.activeElement;
        if (active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.tagName === "SELECT" || active.isContentEditable)) {
          return;
        }
        const activeCanvas = $("modelDiagramCanvas");
        if (!activeCanvas || !activeCanvas.querySelector("svg")) return;
        if (event.key === "+" || event.key === "=") {
          event.preventDefault();
          zoomDiagramByFactor(activeCanvas, 0.82);
        } else if (event.key === "-" || event.key === "_") {
          event.preventDefault();
          zoomDiagramByFactor(activeCanvas, 1.22);
        } else if (event.key === "0" || event.key === "f" || event.key === "F") {
          event.preventDefault();
          resetDiagramViewport(activeCanvas);
        }
      });
    }
  }
  updateDiagramToolbarState(container);
}

function updateDiagramRealtimeBindings(container = $("modelDiagramCanvas"), snapshot = state.snapshot || {}) {
  if (!container) return;
  updateDiagramDeviceVisualStates(container, snapshot);
  const measurementMaps = diagramMeasurementMaps(snapshot);
  updateDiagramSwitchVisualStates(container, measurementMaps);
  if (diagramDisplayPreferences?.measurements !== false) {
    const maps = { ...measurementMaps, controls: diagramControlMap(snapshot) };
    const bindings = diagramRealtimeBindings(container);
    bindings.measurements.forEach(({ element, name }) => {
      setDiagramElementValue(
        element,
        diagramBindingValue(name, maps, "scada"),
      );
    });
    bindings.scada.forEach(({ element, name }) => {
      setDiagramElementValue(element, diagramBindingValue(name, maps, "scada"));
    });
    bindings.real.forEach(({ element, name }) => {
      setDiagramElementValue(element, null);
    });
    bindings.controls.forEach(({ element, name }) => {
      setDiagramElementValue(element, diagramBindingValue(name, maps, "control"));
    });
    bindings.metrics.forEach((binding) => {
      setDiagramElementValue(
        binding.element,
        diagramMetricBindingValue(binding, maps),
        binding.metricType,
      );
    });
  }
  updateDiagramFlowArrows(container, snapshot, measurementMaps);
  refreshDiagramTooltip(container, snapshot);
}

function renderModelDiagramPage(snapshot = state.snapshot || {}) {
  const activeSnapshot = snapshot || {};
  const canvas = $("modelDiagramCanvas");
  const summary = $("modelDiagramSummary");
  if (!canvas) return;
  const diagram = activeSnapshot.diagram || {};
  const modelName = activeSnapshot.model?.name || activeSnapshot.model?.id || "当前模型";
  if (!diagram.svg) {
    resetDiagramInteractions(canvas);
    canvas.dataset.diagramKey = "";
    canvas.innerHTML = '<div class="empty-state">当前模型未配置接线图</div>';
    if (summary) summary.textContent = `${modelName} · 未配置`;
    return;
  }
  const key = `${activeSnapshot.model?.id || ""}|${diagram.updated_at || ""}|${diagram.size || ""}`;
  const diagramChanged = canvas.dataset.diagramKey !== key;
  if (canvas.dataset.diagramKey !== key) {
    const sanitized = sanitizeDiagramSvg(diagram.svg);
    resetDiagramInteractions(canvas);
    canvas.dataset.diagramKey = key;
    canvas.innerHTML = sanitized
      ? `<div class="model-diagram-svg-wrap">${sanitized}</div>`
      : '<div class="empty-state">接线图 SVG 无法解析</div>';
    if (sanitized) {
      prepareDiagramDisplayLayers(canvas);
      compileDiagramFlowArrows(canvas);
    }
  }
  initDiagramInteractions(canvas);
  ensureDiagramFloatingToolbar(canvas);
  if (diagramChanged) refreshDiagramSearchOptions(canvas);
  const prefKey = JSON.stringify(diagramDisplayPreferences || {});
  const bindingKey = [
    diagramChanged ? "changed" : "same",
    prefKey,
    Number(state.measurementDeltaSeq || 0),
    String(state.deviceRuntimeSignature || ""),
    String(activeSnapshot?.clock?.step_count ?? ""),
    String(activeSnapshot?.clock?.state ?? ""),
  ].join("|");
  if (diagramChanged || canvas.dataset.lastDiagramPrefKey !== prefKey) {
    canvas.dataset.lastDiagramPrefKey = prefKey;
    applyDiagramDisplayPreferences(canvas, diagramDisplayPreferences);
    updateDiagramToolbarState(canvas);
  }
  if (summary) summary.textContent = `${modelName} · ${diagram.filename || "diagram.svg"}`;
  if (diagramChanged || canvas.dataset.lastDiagramBindingKey !== bindingKey) {
    canvas.dataset.lastDiagramBindingKey = bindingKey;
    updateDiagramRealtimeBindings(canvas, activeSnapshot);
  }
  if (diagramChanged) {
    fitDiagramViewport(diagramViewportState(canvas));
    updateDiagramToolbarState(canvas);
  }
}

window.addEventListener("storage", (event) => {
  if (event.key !== DIAGRAM_DISPLAY_PREFERENCES_KEY) return;
  try {
    diagramDisplayPreferences = normalizeDiagramDisplayPreferences(event.newValue ? JSON.parse(event.newValue) : null);
  } catch (_error) {
    diagramDisplayPreferences = normalizeDiagramDisplayPreferences(null);
  }
  const canvas = $("modelDiagramCanvas");
  applyDiagramDisplayPreferences(canvas, diagramDisplayPreferences);
  updateDiagramRealtimeBindings(canvas, state.snapshot || {});
  const interaction = canvas ? diagramInteractionCache.get(canvas) : null;
  if (interaction?.contextMenu && !interaction.contextMenu.hidden) renderDiagramContextMenu(interaction);
});

function apiErrorText(error) {
  try {
    return JSON.parse(error.message)?.error || error.message;
  } catch (_parseError) {
    return error.message || "操作失败";
  }
}

function setReceiveLinkMessage(text, kind = "") {
  const message = $("receiveLinkMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function syncReceiveLinkPresetSelection() {
  const select = $("receiveLinkPreset");
  const customField = $("receiveLinkCustomField");
  const input = $("receiveLinkInput");
  if (!select || !input) return;
  const isCustom = select.value === "__custom__";
  if (customField) customField.hidden = !isCustom;
  if (!isCustom) {
    input.value = select.value;
  }
}

async function populateReceiveLinkPresets(preferredUrl = "") {
  const select = $("receiveLinkPreset");
  const input = $("receiveLinkInput");
  if (!select || !input) return;
  const seen = new Set();
  const options = [];
  const pushOption = (value, label) => {
    const clean = String(value || "").trim().replace(/\/$/, "");
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    options.push({ value: clean, label });
  };

  try {
    const discovered = await api("/api/trainee/discover-simulator-services", { modelScoped: false });
    const services = Array.isArray(discovered?.services) ? discovered.services : [];
    for (const item of services) {
      const statusLabel = item.healthy ? "运行中" : "已停止";
      pushOption(item.base_url, `${item.name || item.model_id} · ${item.base_url}（${statusLabel}）`);
    }
  } catch (error) {
    console.warn("自动发现本地模拟服务失败：", error);
  }
  if (preferredUrl) {
    pushOption(preferredUrl, `上次连接 · ${preferredUrl}`);
  }

  select.innerHTML = [
    ...options.map((opt) => `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.label)}</option>`),
    '<option value="__custom__">自定义地址...</option>',
  ].join("");

  const normalizedPref = String(preferredUrl || "").trim().replace(/\/$/, "");
  if (normalizedPref && seen.has(normalizedPref)) {
    select.value = normalizedPref;
  } else if (options.length > 0) {
    select.value = options[0].value;
  } else {
    select.value = "__custom__";
  }
  syncReceiveLinkPresetSelection();
}

function openReceiveLinkDialog() {
  if (state.receiveMode) return;
  const dialog = $("receiveLinkDialog");
  const input = $("receiveLinkInput");
  const select = $("receiveLinkPreset");
  if (!dialog || !input) return;
  const storedAddress = state.teacherApiBase
    || state.interactionLink
    || localStorage.getItem("polarTeacherApiUrl")
    || localStorage.getItem("polarTeacherInteractionLink")
    || "";
  let normalizedStored = storedAddress;
  try {
    normalizedStored = storedAddress ? normalizeConnectionUrl(storedAddress) : "";
  } catch (_error) {
    normalizedStored = storedAddress;
  }
  input.value = normalizedStored;
  if (select && !select.dataset.boundPresetChange) {
    select.dataset.boundPresetChange = "1";
    select.addEventListener("change", () => {
      syncReceiveLinkPresetSelection();
      if (select.value === "__custom__") {
        input.focus();
        input.select();
      }
    });
  }
  setReceiveLinkMessage(`将覆盖当前模型定义：${state.activeModelId || "--"}`);
  $("confirmReceiveLink").disabled = false;
  dialog.showModal();
  populateReceiveLinkPresets(normalizedStored);
}

function closeReceiveLinkDialog() {
  const dialog = $("receiveLinkDialog");
  if (dialog?.open) dialog.close();
}

function openReceiveWarningDialog(title, messages, summary = "") {
  const dialog = $("receiveWarningDialog");
  const titleNode = $("receiveWarningTitle");
  const summaryNode = $("receiveWarningSummary");
  const listNode = $("receiveWarningList");
  if (!dialog || !titleNode || !summaryNode || !listNode) return;
  const safeMessages = (Array.isArray(messages) ? messages : [messages])
    .filter((item) => String(item || "").trim())
    .slice(0, RECEIVE_WARNING_LIMIT);
  titleNode.textContent = title || "接收异常";
  summaryNode.textContent = summary || (safeMessages.length ? `发现 ${safeMessages.length} 项异常。` : "请检查交互链接与本地定义。");
  listNode.innerHTML = safeMessages.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  dialog.showModal();
}

function closeReceiveWarningDialog() {
  const dialog = $("receiveWarningDialog");
  if (dialog?.open) dialog.close();
}

function normalizeConnectionUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) throw new Error("请输入模拟台服务地址。");
  const url = new URL(raw);
  if (!/^https?:$/.test(url.protocol)) throw new Error("模拟台服务地址必须是 http 或 https 地址。");
  if (url.username || url.password) throw new Error("模拟台服务地址不能包含用户名或密码。");
  if (url.pathname !== "/" || url.search || url.hash) {
    url.pathname = "/";
    url.search = "";
    url.hash = "";
  }
  return url.origin;
}

function teacherConnectionFromPayload(payload = {}, fallbackLink = "") {
  const connection = payload.connection || payload.receive_state || payload;
  const serviceAddress = normalizeConnectionUrl(
    fallbackLink || connection.link || connection.interaction_link || connection.teacher_api_base || connection.teacherApiBase,
  );
  const modelId = connection.model_id || connection.teacher_model_id || connection.modelId || connection.teacherModelId
    || "";
  const encodedModelId = encodeURIComponent(modelId);
  const snapshotPath = `/api/snapshot?model_id=${encodedModelId}&trainee_view=1`;
  return {
    link: serviceAddress,
    teacherApiBase: serviceAddress,
    modelId: String(modelId),
    modelName: String(connection.model_name || connection.teacher_model_name || connection.modelName || modelId),
    snapshotPath,
    commandPath: `/api/student/commands?model_id=${encodedModelId}`,
    measurementDeltaPath: measurementDeltaPathFromSnapshotPath(snapshotPath),
    definitionArchivePath: `/api/export-definitions?format=json&model_id=${encodedModelId}`,
  };
}

function connectionApiUrl(connection, path) {
  const target = String(path || "");
  if (/^https?:\/\//i.test(target)) return target;
  const normalized = target.startsWith("/") ? target : `/${target}`;
  return `${connection.teacherApiBase}${normalized}`;
}

function hasLocalDefinitionModel(modelId) {
  return state.models.some((model) => model.id === modelId);
}

function localDefinitionModelId(preferredModelId = "") {
  if (preferredModelId && hasLocalDefinitionModel(preferredModelId)) return preferredModelId;
  if (hasLocalDefinitionModel(state.activeModelId)) return state.activeModelId;
  if (state.models.some((model) => model.id === state.localDefinitionModelId)) return state.localDefinitionModelId;
  return state.models[0]?.id || state.activeModelId || "";
}

async function fetchLocalDefinitionSnapshot(preferredModelId = "") {
  const modelId = localDefinitionModelId(preferredModelId);
  const path = modelId ? `/api/snapshot?model_id=${encodeURIComponent(modelId)}` : "/api/snapshot";
  const snapshot = await api(path, { modelScoped: false });
  return { modelId, snapshot };
}

async function ensureLocalDefinitionSnapshot(modelId = state.activeModelId) {
  const targetModelId = String(modelId || "");
  if (state.localDefinitionSnapshot && state.localDefinitionModelId === targetModelId) {
    return { modelId: targetModelId, snapshot: state.localDefinitionSnapshot };
  }
  const local = await fetchLocalDefinitionSnapshot(targetModelId);
  state.localDefinitionSnapshot = local.snapshot;
  state.localDefinitionModelId = local.modelId;
  return local;
}

async function reloadLocalDefinitionSnapshotAfterEdit(modelId = state.activeModelId) {
  const requestedModelId = String(modelId || state.activeModelId || "");
  const runtimeSnapshot = state.snapshot;
  const local = await fetchLocalDefinitionSnapshot(requestedModelId);
  if (requestedModelId !== String(state.activeModelId || "")) return false;
  state.localDefinitionSnapshot = local.snapshot;
  state.localDefinitionModelId = local.modelId;
  state.snapshot = state.receiveMode && runtimeSnapshot
    ? mergeTeacherSnapshotWithLocalDefinitions(runtimeSnapshot, runtimeSnapshot)
    : mergeSnapshot(runtimeSnapshot, local.snapshot);
  clearStaticSnapshotCacheForModel(requestedModelId);
  persistStaticSnapshotCache(state.snapshot, currentPageName());
  return true;
}

function traineeRuntimeSignalKey(devType, devName, measType = "") {
  return [
    normalizeDiagramMeasurementToken(devType),
    String(devName || "").trim(),
    normalizeDiagramMeasurementToken(measType),
  ].join("\u0000");
}

function traineeRuntimeSignalField(measType) {
  const token = normalizeDiagramMeasurementToken(measType);
  if (token === "RUN_STAT") return "run_stat";
  if (token === "STATUS") return "status";
  return "";
}

function traineeRuntimeSignalValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? (number > 0.5 ? 1 : 0) : null;
}

function traineeRuntimeSignalDisplayValue(device, field, fallback = "--") {
  const signal = device?.runtime_signals?.[field];
  if (!signal) return fallback;
  const value = traineeRuntimeSignalValue(signal.value);
  if (value === null) return signal.valid === false ? "--（遥信无效）" : fallback;
  return signal.valid === false || signal.stale ? `${value}（遥信无效）` : value;
}

function applyTraineeObservedRuntimeSignals(snapshot = {}) {
  const devices = Array.isArray(snapshot.devices) ? snapshot.devices : [];
  const deviceStates = Array.isArray(snapshot.device_states) ? snapshot.device_states : [];
  const scadaRows = Array.isArray(snapshot.measurements?.scada) ? snapshot.measurements.scada : [];
  const observedByKey = new Map();

  scadaRows.forEach((row) => {
    const field = traineeRuntimeSignalField(row?.meas_type);
    const devType = String(row?.dev_type || "").trim();
    const devName = String(row?.dev_name || "").trim();
    if (!field || !devType || !devName) return;
    const value = traineeRuntimeSignalValue(row?.value);
    const valid = Number(row?.valid ?? 1) !== 0 && value !== null;
    observedByKey.set(traineeRuntimeSignalKey(devType, devName, row.meas_type), {
      field,
      value,
      valid,
      stale: !valid,
      updated_simu_time: row?.updated_simu_time ?? null,
      updated_wall_time: row?.updated_wall_time ?? null,
      updated_absolute_minute: row?.updated_absolute_minute ?? null,
    });
  });

  const deviceByKey = new Map();
  devices.forEach((device) => {
    const devType = String(device?.dev_type || "").trim();
    const devName = String(device?.dev_name || device?.name || "").trim();
    if (!devType || !devName) return;
    const deviceKey = traineeRuntimeSignalKey(devType, devName);
    deviceByKey.set(deviceKey, device);
    const runtimeSignals = { ...(device.runtime_signals || {}) };

    ["RUN_STAT", "STATUS"].forEach((measType) => {
      const field = traineeRuntimeSignalField(measType);
      const observed = observedByKey.get(traineeRuntimeSignalKey(devType, devName, measType));
      const previous = runtimeSignals[field];
      if (observed?.valid) {
        runtimeSignals[field] = observed;
        device[field] = observed.value;
        if (field === "status") device.closed_status = observed.value;
        return;
      }
      if (observed && previous && traineeRuntimeSignalValue(previous.value) !== null) {
        runtimeSignals[field] = {
          ...previous,
          valid: false,
          stale: true,
          updated_simu_time: observed.updated_simu_time,
          updated_wall_time: observed.updated_wall_time,
          updated_absolute_minute: observed.updated_absolute_minute,
        };
        device[field] = traineeRuntimeSignalValue(previous.value);
        if (field === "status") device.closed_status = device[field];
        return;
      }
      if (observed) {
        runtimeSignals[field] = observed;
        return;
      }
      if (previous && traineeRuntimeSignalValue(previous.value) !== null) {
        device[field] = traineeRuntimeSignalValue(previous.value);
        if (field === "status") device.closed_status = device[field];
      }
    });

    if (Object.keys(runtimeSignals).length) device.runtime_signals = runtimeSignals;
  });

  deviceStates.forEach((deviceState) => {
    const devType = String(deviceState?.dev_type || "").trim();
    const devName = String(deviceState?.dev_name || deviceState?.name || "").trim();
    if (!devType || !devName) return;
    const device = deviceByKey.get(traineeRuntimeSignalKey(devType, devName));
    const cached = device?.runtime_signals?.run_stat;
    const observed = observedByKey.get(traineeRuntimeSignalKey(devType, devName, "RUN_STAT"));
    if (observed?.valid) {
      deviceState.run_stat = observed.value;
      return;
    }
    const cachedValue = traineeRuntimeSignalValue(cached?.value);
    if (cachedValue !== null) deviceState.run_stat = cachedValue;
  });

  return snapshot;
}

function mergeTeacherRuntimeDevices(localDevices = [], remoteDevices = []) {
  const remoteByKey = new Map((remoteDevices || []).map((device) => ([
    `${String(device?.dev_type || "").trim()}\u0000${String(device?.dev_name || device?.name || "").trim()}`,
    device,
  ])));
  const runtimeFields = ["run_stat", "status", "closed_status", "mode", "set_values", "soc_curr", "runtime_signals"];
  return (localDevices || []).map((localDevice) => {
    const key = `${String(localDevice?.dev_type || "").trim()}\u0000${String(localDevice?.dev_name || localDevice?.name || "").trim()}`;
    const remoteDevice = remoteByKey.get(key);
    if (!remoteDevice) return localDevice;
    const mergedDevice = { ...localDevice };
    runtimeFields.forEach((field) => {
      if (remoteDevice[field] !== undefined) mergedDevice[field] = remoteDevice[field];
    });
    return mergedDevice;
  });
}

function mergeTeacherMeasurementsWithLocalDefinitions(remoteMeasurements = {}, localDefinitionRows = []) {
  const typedKey = (item) => [
    String(item?.dev_type || "").trim().toUpperCase(),
    String(item?.dev_name || "").trim(),
    String(item?.meas_type || "").trim().toUpperCase(),
  ].join("\u0000");
  const localByName = new Map();
  const localByType = new Map();
  (localDefinitionRows || []).forEach((definition) => {
    const name = String(definition?.name || "").trim();
    const key = typedKey(definition);
    if (name) localByName.set(name, definition);
    if (key !== "\u0000\u0000") localByType.set(key, definition);
  });
  const mergeChannel = (rows) => (rows || []).map((item) => {
    const name = String(item?.name || "").trim();
    const definition = (name ? localByName.get(name) : null) || localByType.get(typedKey(item));
    if (!definition) return item;
    return {
      ...item,
      valid: definition?.valid ?? item.valid,
      weight: definition?.weight ?? item.weight,
    };
  });
  const merged = {
    ...(remoteMeasurements || {}),
    definitions: localDefinitionRows || [],
    scada: mergeChannel(remoteMeasurements?.scada),
    value_channels: ["scada"],
  };
  delete merged.real;
  return merged;
}

function mergeTeacherSnapshotWithLocalDefinitions(previousSnapshot, remoteSnapshot) {
  const localDefinitions = state.localDefinitionSnapshot || {};
  const merged = mergeSnapshot(previousSnapshot || localDefinitions, remoteSnapshot || {});
  STATIC_SNAPSHOT_KEYS.forEach((key) => {
    if (localDefinitions[key] !== undefined) merged[key] = localDefinitions[key];
  });
  if (localDefinitions.model) merged.model = localDefinitions.model;
  if (localDefinitions.devices) {
    merged.devices = mergeTeacherRuntimeDevices(localDefinitions.devices, merged.devices);
  }
  const localMeasurementDefinitions = localDefinitions.definitions?.measurement
    || localDefinitions.measurements?.definitions
    || [];
  merged.measurements = mergeTeacherMeasurementsWithLocalDefinitions(
    merged.measurements,
    localMeasurementDefinitions,
  );
  if (localDefinitions.static_meta) merged.static_meta = localDefinitions.static_meta;
  return merged;
}

function applyTeacherConnection(connection) {
  state.interactionLink = connection.link;
  state.teacherApiBase = (connection.teacherApiBase || "").replace(/\/$/, "");
  state.teacherModelId = connection.modelId;
  state.teacherModelName = connection.modelName;
  state.teacherSnapshotPath = connection.snapshotPath;
  state.teacherCommandPath = connection.commandPath;
  state.teacherMeasurementDeltaPath = connection.measurementDeltaPath;
  state.teacherDefinitionArchivePath = connection.definitionArchivePath;
  state.measurementDeltaSeq = 0;
  persistActiveModelContext({}, true);
}

function sortedUnique(values) {
  return [...new Set((values || []).map((item) => String(item || "").trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function previewList(values, limit = 8) {
  const list = Array.from(values || []);
  if (!list.length) return "无";
  const visible = list.slice(0, limit).join("，");
  return list.length > limit ? `${visible}，等 ${list.length} 项` : visible;
}

function pushSetDiff(messages, label, localValues, remoteValues) {
  const localSet = new Set(localValues || []);
  const remoteSet = new Set(remoteValues || []);
  const missing = [...localSet].filter((item) => !remoteSet.has(item)).sort((a, b) => a.localeCompare(b));
  const extra = [...remoteSet].filter((item) => !localSet.has(item)).sort((a, b) => a.localeCompare(b));
  if (missing.length) messages.push(`${label}缺少：${previewList(missing)}`);
  if (extra.length) messages.push(`${label}新增：${previewList(extra)}`);
}

function comparableScalar(value) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "number") return Number.isFinite(value) ? Number(value.toPrecision(12)) : String(value);
  if (typeof value === "boolean") return value;
  const text = String(value).trim();
  if (!text) return "";
  const number = Number(text);
  return Number.isFinite(number) ? Number(number.toPrecision(12)) : text;
}

function stableComparable(value) {
  if (Array.isArray(value)) return value.map(stableComparable);
  if (value && typeof value === "object") {
    return Object.keys(value).sort((a, b) => a.localeCompare(b)).reduce((result, key) => {
      result[key] = stableComparable(value[key]);
      return result;
    }, {});
  }
  return comparableScalar(value);
}

function stableStringify(value) {
  return JSON.stringify(stableComparable(value));
}

function textHash(text) {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function definitionDevices(snapshot = {}) {
  const map = new Map();
  (snapshot.devices || []).forEach((dev) => {
    const devType = String(dev.dev_type || dev.type || "").trim();
    const devName = String(dev.dev_name || dev.name || "").trim();
    if (!devType || !devName) return;
    map.set(`${devType}.${devName}`, {
      setTypes: sortedUnique(dev.set_types || []),
    });
  });
  return map;
}

function definitionMeasurementKeys(snapshot = {}) {
  const measurements = snapshot.measurements || {};
  const rows = measurements.definitions?.length ? measurements.definitions : measurements.scada || [];
  return sortedUnique(rows.map((row) => [
    row.name || "",
    row.dev_type || "",
    row.dev_name || "",
    String(row.meas_type || "").toUpperCase(),
  ].join("|")));
}

function definitionParameterSummary(snapshot = {}) {
  const params = snapshot.device_parameters || {};
  const result = new Map();
  Object.keys(params).sort((a, b) => a.localeCompare(b)).forEach((blockName) => {
    const rows = Array.isArray(params[blockName]) ? params[blockName] : [];
    result.set(blockName, textHash(stableStringify(rows)));
  });
  return result;
}

function definitionCurveSummary(snapshot = {}) {
  const curves = snapshot.curves || {};
  const loads = curves.loads && typeof curves.loads === "object" ? curves.loads : {};
  const loadNames = sortedUnique(Object.keys(loads));
  const loadCounts = loadNames.map((name) => `${name}:${Array.isArray(loads[name]) ? loads[name].length : 0}`);
  return {
    mode: String(curves.mode || "day"),
    stepMinutes: String(curves.time_step_minutes ?? ""),
    pointCount: String(curves.point_count ?? ""),
    weatherCount: Array.isArray(curves.weather) ? curves.weather.length : 0,
    weatherHash: textHash(stableStringify(curves.weather || [])),
    loadNames,
    loadCounts,
    loadHash: textHash(stableStringify(loadNames.map((name) => [name, loads[name] || []]))),
  };
}

function compareSnapshotDefinitions(localSnapshot, remoteSnapshot) {
  const messages = [];
  if (!localSnapshot) messages.push("本地模型定义不可用。");
  if (!remoteSnapshot) messages.push("模拟台数据不可用。");
  if (messages.length) return messages;

  const localDevices = definitionDevices(localSnapshot);
  const remoteDevices = definitionDevices(remoteSnapshot);
  pushSetDiff(messages, "模型设备", [...localDevices.keys()], [...remoteDevices.keys()]);
  [...localDevices.keys()].filter((key) => remoteDevices.has(key)).forEach((key) => {
    const localSetTypes = localDevices.get(key).setTypes;
    const remoteSetTypes = remoteDevices.get(key).setTypes;
    const localText = localSetTypes.join(",");
    const remoteText = remoteSetTypes.join(",");
    if (localText !== remoteText) {
      messages.push(`设备 ${key} 控制量定义不一致：本地 ${localText || "无"}；模拟台 ${remoteText || "无"}`);
    }
  });

  pushSetDiff(messages, "量测定义", definitionMeasurementKeys(localSnapshot), definitionMeasurementKeys(remoteSnapshot));

  const localParams = definitionParameterSummary(localSnapshot);
  const remoteParams = definitionParameterSummary(remoteSnapshot);
  pushSetDiff(messages, "设备参数表", [...localParams.keys()], [...remoteParams.keys()]);
  [...localParams.keys()].filter((key) => remoteParams.has(key)).forEach((key) => {
    if (localParams.get(key) !== remoteParams.get(key)) {
      messages.push(`设备参数表 ${key} 内容不一致。`);
    }
  });

  const localCurves = definitionCurveSummary(localSnapshot);
  const remoteCurves = definitionCurveSummary(remoteSnapshot);
  if (localCurves.mode !== remoteCurves.mode) messages.push(`仿真模式不一致：本地 ${localCurves.mode}；模拟台 ${remoteCurves.mode}`);
  if (localCurves.stepMinutes !== remoteCurves.stepMinutes) messages.push(`曲线步长不一致：本地 ${localCurves.stepMinutes || "--"}；模拟台 ${remoteCurves.stepMinutes || "--"}`);
  if (localCurves.pointCount !== remoteCurves.pointCount) messages.push(`曲线点数不一致：本地 ${localCurves.pointCount || "--"}；模拟台 ${remoteCurves.pointCount || "--"}`);
  if (localCurves.weatherCount !== remoteCurves.weatherCount || localCurves.weatherHash !== remoteCurves.weatherHash) {
    messages.push(`环境曲线定义不一致：本地 ${localCurves.weatherCount} 点；模拟台 ${remoteCurves.weatherCount} 点。`);
  }
  pushSetDiff(messages, "负荷曲线", localCurves.loadNames, remoteCurves.loadNames);
  if (localCurves.loadCounts.join("|") !== remoteCurves.loadCounts.join("|") || localCurves.loadHash !== remoteCurves.loadHash) {
    messages.push("负荷曲线数据不一致。");
  }

  return messages.slice(0, RECEIVE_WARNING_LIMIT);
}

function receiveMismatchKey(messages) {
  return (messages || []).join("\n");
}

function resetReceiveIssueStreak() {
  state.receiveReconnectAttempts = 0;
  state.receiveTransportFailureCount = 0;
  state.receiveTransportInterrupted = false;
}

function isTraineeWebTransportError(error) {
  const name = String(error?.name || "").trim().toLowerCase();
  const message = String(error?.message || error || "").trim().toLowerCase();
  return name === "typeerror" && (
    message.includes("failed to fetch")
    || message.includes("networkerror")
    || message.includes("network error")
    || message.includes("network request failed")
    || message.includes("load failed")
  );
}

function recordTraineeWebTransportIssue(error) {
  state.receiveTransportFailureCount += 1;
  state.receiveTransportInterrupted = true;
  const attempt = state.receiveTransportFailureCount;
  const logInterval = receiveMaxReconnectAttempts();
  if (attempt === 1 || attempt % logInterval === 0) {
    addRuntimeLog(
      "实时交互",
      "学员台WEB后台 /api/trainee/snapshot",
      "后台重连",
      [
        `本机学员台WEB后台暂不可用：${apiErrorText(error)}`,
        `已连续重试 ${attempt} 次；不主动停止接收，后台恢复后自动续接`,
      ],
      "warn",
      true,
    );
  }
  renderReceiveMode(`后台重连中 ${attempt}`);
}

function finishTraineeWebTransportRecovery(simTime = "") {
  if (!state.receiveTransportInterrupted) return;
  const attempts = state.receiveTransportFailureCount;
  state.receiveTransportFailureCount = 0;
  state.receiveTransportInterrupted = false;
  addRuntimeLog(
    "实时交互",
    "学员台WEB后台 /api/trainee/snapshot",
    "后台恢复",
    [`本机WEB后台访问已恢复`, `中断期间自动重试 ${attempts} 次，接收状态未被主动关闭`],
    "ok",
    true,
    simTime,
  );
}

function stopReceiveAfterPersistentIssue(result, detail = [], simTime = "") {
  const detailItems = Array.isArray(detail) ? detail.filter(Boolean) : [detail].filter(Boolean);
  const maxAttempts = receiveMaxReconnectAttempts();
  state.receiveMode = false;
  state.frozen = true;
  state.receiveEpoch += 1;
  state.receiveRequestActive = false;
  persistActiveModelContext({ receiveMode: false, frozen: true }, true);
  setTraineeReceiveActive(state.activeModelId, false).catch((error) => {
    addRuntimeLog("接收模式", "学员台服务端", "保存保护状态失败", apiErrorText(error), "warn");
  });
  addRuntimeLog(
    "实时交互",
    "接收保护",
    "停止接收",
    [`连续 ${maxAttempts} 次接收异常`, ...detailItems],
    "error",
    true,
    simTime,
  );
  noteRenewableReceiveInterruption("连续接收异常，新能源实时控制已暂停，接收恢复后将自动恢复。");
  renderReceiveMode(result || "接收异常");
  openReceiveWarningDialog(
    `${result || "接收异常"}，已停止接收`,
    [`已连续 ${maxAttempts} 次发现接收异常。`, ...detailItems],
    "请检查模拟台仿真状态、交互链接和定义文件一致性。",
  );
}

function recordReceiveIssue(type, target, result, detail = "", simTime = "") {
  state.receiveReconnectAttempts += 1;
  const attempt = state.receiveReconnectAttempts;
  const maxAttempts = receiveMaxReconnectAttempts();
  const detailItems = Array.isArray(detail) ? detail.filter(Boolean) : [detail].filter(Boolean);
  addRuntimeLog(
    type,
    target,
    result,
    [`连续告警 ${attempt}/${maxAttempts}`, ...detailItems],
    "warn",
    true,
    simTime,
  );
  if (attempt >= maxAttempts) {
    stopReceiveAfterPersistentIssue(result, detailItems, simTime);
    return false;
  }
  renderReceiveMode(`告警 ${attempt}/${maxAttempts}`);
  return true;
}

function handleReceiveDefinitionMismatch(messages, result = "定义不一致", simTime = "") {
  const detail = messages?.length ? messages : ["模拟台传入数据与本地定义不一致。"];
  const key = receiveMismatchKey(detail);
  state.definitionMismatchLastKey = key;
  return recordReceiveIssue("实时交互", "定义一致性校验", result, detail, simTime);
}

function validateTeacherSnapshotDefinitions(snapshot, result = "定义不一致") {
  if (!state.localDefinitionSnapshot) return true;
  if (!hasStaticSnapshotPayload(snapshot)) return true;
  const messages = compareSnapshotDefinitions(state.localDefinitionSnapshot, snapshot);
  if (!messages.length) {
    state.definitionMismatchLastKey = "";
    return true;
  }
  handleReceiveDefinitionMismatch(messages, result, snapshot.clock?.time || "--");
  return false;
}

function isSimulationFrozenSnapshot(snapshot = state.snapshot) {
  const simulationState = String(snapshot?.clock?.state || "").trim().toLowerCase();
  return ["paused", "stopped"].includes(simulationState);
}

function acceptTeacherSnapshot(snapshot, epoch = state.receiveEpoch) {
  if (!state.receiveMode || epoch !== state.receiveEpoch) return false;
  state.snapshotSource = "teacher";
  const clock = snapshot.clock || {};
  finishTraineeWebTransportRecovery(clock.time || "--");
  if (isSimulationFrozenSnapshot(snapshot)) {
    resetReceiveIssueStreak();
    state.lastReceiveAt = new Date().toLocaleTimeString();
    renderSnapshot(snapshot);
    renderReceiveMode();
    return true;
  }
  resetReceiveIssueStreak();
  state.lastReceiveAt = new Date().toLocaleTimeString();
  const logKey = renewableClockKey(snapshot);
  if (logKey !== state.lastTeacherSnapshotLogKey) {
    const valuesNow = currentWeatherLoad(snapshot);
    const scada = snapshot.measurements?.scada || [];
    addRuntimeLog(
      "实时交互",
      "模拟台 /api/snapshot",
      "接收成功",
      [
        `量测 ${scada.length} 点`,
        Number.isFinite(valuesNow.windSpeed) ? `风速 ${formatNumber(valuesNow.windSpeed)} m/s` : "风速 未知",
        Number.isFinite(valuesNow.solarIrradiance) ? `光照 ${formatNumber(valuesNow.solarIrradiance)} W/m2` : "光照 未知",
        `负荷 ${formatNumber(valuesNow.loadKw)} kW`,
      ],
      "ok",
      false,
      snapshot.clock?.time || "--",
    );
    state.lastTeacherSnapshotLogKey = logKey;
  }
  renderSnapshot(snapshot);
  renderReceiveMode();
  return true;
}

async function attemptTeacherReconnect(epoch) {
  if (!state.receiveMode || epoch !== state.receiveEpoch) return;
  const attempt = state.receiveReconnectAttempts;
  const maxAttempts = receiveMaxReconnectAttempts();
  renderReceiveMode(`重连中 ${attempt}/${maxAttempts}`);
  try {
    await ensureLocalDefinitionSnapshot(state.activeModelId);
    const remoteSnapshot = applyDeviceRuntimePayload(
      state.snapshot,
      await teacherSnapshotApi(currentPageName()),
    );
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    state.embeddedMeasurementDeltaReceived = false;
    const embeddedMeasurementDelta = remoteSnapshot?.measurement_delta || null;
    if (remoteSnapshot?.measurement_delta) delete remoteSnapshot.measurement_delta;
    const snapshot = mergeTeacherSnapshotWithLocalDefinitions(state.snapshot, remoteSnapshot);
    state.snapshot = snapshot;
    if (embeddedMeasurementDelta) {
      snapshot.measurement_delta = embeddedMeasurementDelta;
      applyEmbeddedMeasurementDelta(snapshot);
    }
    if (pageNeedsMeasurementDelta(currentPageName()) && !state.embeddedMeasurementDeltaReceived) {
      await refreshMeasurementDelta(false);
    }
    if (acceptTeacherSnapshot(snapshot, epoch)) {
      addRuntimeLog("实时交互", "模拟台实时链路", "重连成功", `模型 ${state.teacherModelName}`, "ok");
    }
  } catch (error) {
    if (!state.receiveMode || epoch !== state.receiveEpoch) return;
    if (isTraineeWebTransportError(error)) {
      recordTraineeWebTransportIssue(error);
      return;
    }
    renderReceiveMode(`重连等待 ${attempt}/${maxAttempts}`);
  }
}

async function setTraineeReceiveActive(modelId, active) {
  const result = await api("/api/trainee/receive", {
    method: "POST",
    modelScoped: false,
    body: JSON.stringify({ model_id: modelId, active }),
  });
  mergeBackendReceiveState(modelId, result, contextKey(modelId) === contextKey());
  return result;
}

async function startReceiveMode() {
  if (!state.modelInitialized) {
    addRuntimeLog("接收模式", "当前本地模型", "启动接收失败", "请先完成模型初始化。", "warn");
    renderReceiveMode("等待模型初始化");
    return;
  }
  const activeModelIdBeforeReceive = state.activeModelId;
  try {
    const local = await ensureLocalDefinitionSnapshot(activeModelIdBeforeReceive);
    state.snapshot = local.snapshot;
    state.measurementDeltaSeq = 0;
    state.measurementTraceHistory = [];
    resetChartPeriodOffsets("measurementTrace");
    state.lastMeasurementTraceKey = "";
    resetMeasurementHistoryHydration();
    state.commandTraceHistory = [];
    resetChartPeriodOffsets("commandTrace");
    resetRenewableTrendHistoryHydration({ clearHistory: true });
    state.lastReceiveAt = "";
    state.snapshotSource = "";
    state.lastTeacherSnapshotLogKey = "";
    persistActiveModelContext({}, true);
    drawMeasurementTraceChart();
    drawCommandTraceChart();
    drawRenewableTrendChart();
    await setTraineeReceiveActive(activeModelIdBeforeReceive, true);
    state.receiveMode = true;
    state.frozen = false;
    state.receiveEpoch += 1;
    resetReceiveIssueStreak();
    persistActiveModelContext({}, true);
    addRuntimeLog(
      "接收模式",
      "模拟台实时链路",
      "启动接收",
      `模型 ${state.teacherModelName || state.teacherModelId}；接收地址 ${teacherReceiveAddress()}`,
      "ok",
    );
    renderReceiveMode();
    await refreshRenewableControlState({ preview: false, render: currentPageName() === "renewable" });
    await refreshFromTeacher(state.receiveEpoch);
  } catch (error) {
    addRuntimeLog("接收模式", "模拟台实时链路", "启动接收失败", apiErrorText(error), "warn");
    renderReceiveMode(apiErrorText(error));
  }
}

async function initializeModelFromLink() {
  const input = $("receiveLinkInput");
  const confirmButton = $("confirmReceiveLink");
  if (!input || !confirmButton) return;
  const activeModelIdBeforeInitialize = state.activeModelId;
  confirmButton.disabled = true;
  setReceiveLinkMessage("正在下载并覆盖当前本地模型定义。");
  try {
    const normalizedLink = normalizeConnectionUrl(input.value);
    const result = await api("/api/trainee/model-initialize", {
      method: "POST",
      modelScoped: false,
      body: JSON.stringify({
        model_id: activeModelIdBeforeInitialize,
        link: normalizedLink,
      }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : state.models);
    mergeBackendReceiveState(activeModelIdBeforeInitialize, result.receive_state || {}, true);
    const connection = teacherConnectionFromPayload(result, normalizedLink);
    applyTeacherConnection(connection);
    state.activeModelId = activeModelIdBeforeInitialize;
    localStorage.setItem("polarTraineeModelId", activeModelIdBeforeInitialize);
    state.modelInitialized = true;
    state.modelInitializedAt = result.receive_state?.initialized_at || state.modelInitializedAt;
    state.receiveMode = false;
    state.frozen = false;
    state.receiveEpoch += 1;
    resetReceiveIssueStreak();
    state.measurementDeltaSeq = 0;
    state.measurementTraceHistory = [];
    resetChartPeriodOffsets("measurementTrace");
    state.lastMeasurementTraceKey = "";
    resetMeasurementHistoryHydration();
    state.commandTraceHistory = [];
    resetChartPeriodOffsets("commandTrace");
    resetRenewableTrendHistoryHydration({ clearHistory: true });
    state.lastReceiveAt = "";
    state.snapshot = null;
    state.snapshotSource = "local";
    state.localDefinitionSnapshot = null;
    state.localDefinitionModelId = "";
    invalidateManualDefinitionChanges();
    state.lastTeacherSnapshotLogKey = "";
    clearStaticSnapshotCacheForModel(activeModelIdBeforeInitialize);
    persistActiveModelContext({}, true);
    renderModelSelector();
    if ($("modelManagementDialog")?.open) renderModelManagementList();
    const localSnapshot = await refreshLocalSnapshotPayload(currentPageName());
    state.snapshotSource = "local";
    renderSnapshot(localSnapshot);
    closeReceiveLinkDialog();
    addRuntimeLog(
      "模型初始化",
      "模拟台定义下载",
      "初始化成功",
      `本地模型 ${activeModelIdBeforeInitialize} ← 远端模型 ${connection.modelName || connection.modelId}`,
      "ok",
    );
    setImportStatus(`模型初始化完成：${activeModelIdBeforeInitialize}`, "ok");
    renderReceiveMode();
  } catch (error) {
    addRuntimeLog("模型初始化", "模拟台定义下载", "初始化失败", apiErrorText(error), "warn");
    setReceiveLinkMessage(apiErrorText(error), "error");
  } finally {
    confirmButton.disabled = false;
  }
}

function runtimeLogTime() {
  return runtimeLogWallTimeText(new Date());
}

function runtimeLogWallTimeText(value) {
  if (!value) return "--";
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return value.toLocaleTimeString("zh-CN", { hour12: false });
  }
  const text = String(value || "").trim();
  if (!text) return "--";
  const isoMatch = text.match(/(?:T|\s)(\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/);
  if (isoMatch) return isoMatch[1];
  const plainTimeMatch = text.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
  if (plainTimeMatch) {
    return `${plainTimeMatch[1].padStart(2, "0")}:${plainTimeMatch[2]}:${plainTimeMatch[3] || "00"}`;
  }
  const parsed = new Date(text);
  if (Number.isFinite(parsed.getTime())) {
    return parsed.toLocaleTimeString("zh-CN", { hour12: false });
  }
  return text;
}

function runtimeLogSimTime(simTime = "") {
  const explicit = String(simTime || "").trim();
  if (explicit) return explicit;
  return state.snapshot?.clock?.time || $("simTime")?.textContent?.trim() || "--";
}

function runtimeLogSimTimeFromCommandHistory(item = {}) {
  const explicit = item.simu_time || item.sim_time || item.clock?.time || "";
  if (explicit) return runtimeLogSimTime(explicit);
  const minute = Number(item.issued_absolute_minute);
  if (Number.isFinite(minute)) return formatTraceClockMinute(minute);
  return runtimeLogSimTime();
}

function simulationClockTextFromMinute(minute, snapshot = state.snapshot || {}) {
  const numericMinute = Number(minute);
  if (!Number.isFinite(numericMinute)) return "--";
  const timeText = formatTraceClockMinute(numericMinute);
  const mode = curveDisplayMode(snapshot);
  const dayCount = curveDisplayModeDayCount(mode);
  if (dayCount <= 1) return timeText;
  let dayOfCycle = Math.floor(Math.max(0, numericMinute) / 1440) % dayCount;
  if (mode !== "year") return `第${dayOfCycle + 1}天 ${timeText}`;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  while (month < monthDays.length - 1 && dayOfCycle >= monthDays[month]) {
    dayOfCycle -= monthDays[month];
    month += 1;
  }
  return `${String(month + 1).padStart(2, "0")}-${String(dayOfCycle + 1).padStart(2, "0")} ${timeText}`;
}

function currentCommandSendTimeInfo(snapshot = state.snapshot || {}) {
  const clock = snapshot.clock || {};
  const minute = Number(clock.absolute_minute ?? clock.minute);
  const absoluteMinute = Number.isFinite(minute) ? minute : null;
  return {
    sent_wall_time: runtimeLogTime(),
    sent_simu_time: absoluteMinute === null ? runtimeLogSimTime(clock.time || "") : simulationClockTextFromMinute(absoluteMinute, snapshot),
    sent_absolute_minute: absoluteMinute,
  };
}

function withCommandSendTime(body, snapshot = state.snapshot || {}) {
  const timeInfo = currentCommandSendTimeInfo(snapshot);
  const payload = {
    ...body,
    sent_wall_time: timeInfo.sent_wall_time,
    sent_simu_time: timeInfo.sent_simu_time,
  };
  if (timeInfo.sent_absolute_minute !== null) payload.sent_absolute_minute = timeInfo.sent_absolute_minute;
  return payload;
}

function commandSentTimeInfo(entry = {}, snapshot = state.snapshot || {}) {
  const payload = entry.payload || {};
  const wallTime = runtimeLogWallTimeText(
    payload.sent_wall_time
    || payload.trainee_sent_wall_time
    || entry.sent_wall_time
    || entry.trainee_sent_wall_time
    || entry.time
    || "",
  );
  const explicitSimTime = String(
    payload.sent_simu_time
    || payload.trainee_sent_simu_time
    || entry.sent_simu_time
    || entry.trainee_sent_simu_time
    || entry.simu_time
    || entry.sim_time
    || "",
  ).trim();
  const origin = commandOrigin(entry);
  const source = String(entry.source || payload.source || "");
  const queued = String(entry.queue_state || "").trim().toLowerCase() === "waiting"
    || Number(entry.queued || 0) > 0;
  const processState = queued ? "queued" : "effective";
  const processText = queued ? "下发完成，模拟台排队" : "下发完成，立即生效";
  if (explicitSimTime) {
    return {
      wall_time: wallTime,
      simu_time: explicitSimTime,
      source,
      command_origin: origin,
      origin_text: commandOriginLabel(origin),
      process_state: processState,
      process_text: processText,
    };
  }
  const minute = Number(
    payload.sent_absolute_minute
    ?? payload.trainee_sent_absolute_minute
    ?? entry.sent_absolute_minute
    ?? entry.trainee_sent_absolute_minute
    ?? entry.issued_absolute_minute,
  );
  return {
    wall_time: wallTime,
    simu_time: Number.isFinite(minute) ? simulationClockTextFromMinute(minute, snapshot) : "--",
    source,
    command_origin: origin,
    origin_text: commandOriginLabel(origin),
    process_state: processState,
    process_text: processText,
  };
}

function manualCommandHoldsAcrossClockLifecycle(entry = {}) {
  const payload = entry.payload && typeof entry.payload === "object" ? entry.payload : entry;
  if (entry.manual_hold || entry.hold_until_cancelled || payload.manual_hold || payload.hold_until_cancelled) return true;
  if (payload.strategy && typeof payload.strategy === "object") return false;
  const source = String(entry.source || payload.source || "").trim().toLowerCase();
  if (source.includes("renewable") || source.includes("strategy")) return false;
  return source === "trainee-ui"
    || source === "student-ui"
    || source.startsWith("trainee-ui-")
    || source.startsWith("student-ui-")
    || source.includes("人工");
}

