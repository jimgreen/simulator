// 学员端模块：时钟告警、设备树、量测与控制表格及趋势图（07-measurements-commands.js）
function renderClock(clock) {
  $("simTime").textContent = clock.time || "00:00:00";
  $("simState").textContent = clock.state || "stopped";
  $("simSpeed").textContent = `x${clock.speed ?? 1}`;
  const readout = document.querySelector(".clock-readout");
  if (readout) readout.dataset.clockState = clock.state || "stopped";
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
    if (badgeText) badgeText.textContent = timedOut ? "模拟台潮流超时" : "模拟台潮流失败";
  }
  const title = $("powerFlowFailureTitle");
  const detail = $("powerFlowFailureDetail");
  if (title) {
    title.textContent = simulationPaused
      ? (timedOut ? "模拟台潮流计算超时，仿真已暂停" : "模拟台潮流计算失败，仿真已暂停")
      : (timedOut ? "模拟台潮流计算超时，本轮结果已丢弃" : "模拟台潮流计算失败，本轮结果已丢弃");
  }
  if (detail) {
    const staleFrameText = lastSuccessTime
      ? `当前画面量测为上一成功帧（${lastSuccessTime}）`
      : "当前画面没有成功潮流量测帧";
    detail.textContent = (
      `失败仿真时刻 ${simuTime}。${error}。`
      + `本轮潮流结果未采用，${staleFrameText}，请通知教员修正边界后${simulationPaused ? "再恢复运行" : "重新计算"}。`
    );
  }
}

function deviceKey(dev) {
  return `${dev.dev_type || dev.type || ""}|${dev.dev_name || dev.name || ""}`;
}

function deviceName(dev) {
  return String(dev?.dev_name || dev?.name || "");
}

function deviceType(dev) {
  return String(dev.dev_type || dev.type || "Unknown");
}

function deviceModelBlock(dev) {
  return String(dev?.model_block || dev?.raw?.model_block || "").trim();
}

function deviceFamily(dev) {
  return String(dev?.device_family || "").trim().toLowerCase();
}

function deviceIndex(dev) {
  return dev.idx ?? dev.raw?.idx ?? "";
}

function statusText(value) {
  return Number(value) ? "投入" : "退出";
}

function deviceTreeBadge(dev) {
  const run = dev.run_stat ?? dev.raw?.run_stat;
  const status = dev.status ?? dev.raw?.status;
  if (status !== undefined && status !== "") return Number(status) ? "闭合" : "断开";
  if (run !== undefined && run !== "") return Number(run) ? "投入" : "退出";
  return dev.mode || "--";
}

function devicesByType(devices) {
  const groups = new Map();
  devices.forEach((dev) => {
    const type = deviceModelBlock(dev) || "Unknown";
    if (!groups.has(type)) groups.set(type, []);
    groups.get(type).push(dev);
  });
  return Array.from(groups.entries()).sort((a, b) => {
    if (a[0] === "Environment" && b[0] !== "Environment") return -1;
    if (a[0] !== "Environment" && b[0] === "Environment") return 1;
    return a[0].localeCompare(b[0], "zh-Hans-CN");
  });
}

function isDeviceTreeGroupCollapsed(scope, groupKey) {
  return Boolean(state.collapsedDeviceTreeGroups?.[scope]?.[groupKey]);
}

function toggleDeviceTreeGroup(scope, groupKey) {
  if (!scope || !groupKey || groupKey === "all") return;
  if (!state.collapsedDeviceTreeGroups[scope]) state.collapsedDeviceTreeGroups[scope] = {};
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
  const name = deviceName(item);
  if ((devType || deviceModelBlock(item)) === "Environment" && name === "weather") return "气象";
  return name;
}

function deviceTreeSearchFields(item, devType = "") {
  const raw = item?.raw || {};
  return [
    devType,
    deviceModelBlock(item),
    deviceType(item),
    deviceName(item),
    deviceTreeVisibleName(item, devType),
    deviceIndex(item),
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
  if (scope === "model") renderTraineeModelDeviceTree();
  if (scope === "measurement") renderDeviceTree("measurementDeviceTree", "measurementTreeSummary", measurementsDevices(state.snapshot || {}), state.measurementFilter, "measurement", "measurement");
  if (scope === "control") renderDeviceTree("commandDeviceTree", "commandTreeSummary", controlDefinitionDevices(), state.controlFilter, "control", "control");
}

function renderDeviceTree(containerId, summaryId, devices, filter, scope, dataPrefix) {
  const container = $(containerId);
  if (!container) return;
  const groups = devicesByType(devices);
  const treeResult = filterDeviceTreeGroups(groups, scope);
  const total = devices.length;
  $(summaryId).textContent = deviceTreeSummary(treeResult);
  const rootActive = isDeviceTreeNodeActive(filter, "all", "");
  const rootAttr = `data-${dataPrefix}-tree-type="all" data-${dataPrefix}-tree-name=""`;
  const groupHtml = treeResult.groupEntries.map(([devType, items]) => {
    const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed(scope, devType);
    const typeActive = isDeviceTreeNodeActive(filter, devType, "");
    const parentActive = isDeviceTreeParentActive(filter, devType);
    return `
      <div class="tree-group">
        <button
          type="button"
          class="tree-node tree-type ${typeActive ? "is-active" : ""} ${parentActive ? "is-parent-active" : ""} ${isCollapsed ? "is-collapsed" : ""}"
          data-${dataPrefix}-tree-type="${escapeHtml(devType)}"
          data-${dataPrefix}-tree-name=""
          ${deviceTreeTypeAttrs(scope, devType, isCollapsed)}
        >
          ${deviceTreeTypeLabel(devType)}
          <strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => {
          const name = deviceName(dev);
          const displayName = devType === "Environment" && name === "weather" ? "气象" : name;
          const isActive = isDeviceTreeNodeActive(filter, devType, name);
          return `
            <button
              type="button"
              class="tree-node tree-child ${isActive ? "is-active" : ""}"
              data-${dataPrefix}-tree-type="${escapeHtml(devType)}"
              data-${dataPrefix}-tree-name="${escapeHtml(name)}"
            >
              <span>${escapeHtml(displayName)}</span>
              <small>${escapeHtml(deviceTreeBadge(dev))}</small>
            </button>`;
        }).join(""))}
      </div>`;
  }).join("");
  const treeHtml = `
    <button type="button" class="tree-node tree-root ${rootActive ? "is-active" : ""}" ${rootAttr}>
      <span>全部设备</span>
      <strong>${treeResult.query ? treeResult.filteredTotal : total}</strong>
    </button>
    ${groupHtml || renderDeviceTreeFilterEmpty(treeResult.query)}`;
  updateDeviceTreeHtml(container, treeHtml);
}

function selectTreeFilter(filterName, devType, devName = "", event = null, button = null, dataPrefix = "") {
  state[filterName] = updateDeviceTreeFilterSelection(
    filterName,
    devType,
    devName,
    event,
    dataPrefix,
    button,
  );
  if (filterName === "measurementFilter") renderMeasurements(state.snapshot || {});
  if (filterName === "controlFilter") renderCombinedControlPage();
}

function filteredDevices(devices, filter) {
  return (devices || []).filter((dev) => deviceFilterMatches(dev, filter));
}

function definitionBlocks(kind, snapshot = state.snapshot || {}) {
  return snapshot.definitions?.[kind] || {};
}

function definedModelDevices(snapshot = state.snapshot || {}) {
  const blocks = definitionBlocks("model", snapshot);
  return Object.entries(blocks).flatMap(([blockName, block]) => {
    const headers = Array.isArray(block.headers) ? block.headers : [];
    return (block.rows || []).map((row, index) => {
      const raw = {};
      headers.forEach((header) => {
        raw[header] = row?.[header] ?? "";
      });
      const idx = raw.idx ?? row?.idx ?? index + 1;
      const definedName = raw.name || raw.dev_name || "";
      const name = definedName || (idx !== "" ? `${blockName}_${idx}` : `${blockName}_${index + 1}`);
      return {
        dev_type: blockName,
        model_block: blockName,
        dev_name: String(name || `${blockName}_${index + 1}`),
        idx,
        raw,
        __headers: headers,
        __definition_index: index,
      };
    });
  });
}

function formatModelParamValue(value, field = "") {
  if (value === null || value === undefined || value === "") return "--";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  if (diagramDefinitionRatioField(field)) return diagramDefinitionDisplayValue(field, value);
  return String(value);
}

function compareModelRowsByIndex(left, right) {
  const leftIndex = Number(left.idx ?? left.raw?.idx);
  const rightIndex = Number(right.idx ?? right.raw?.idx);
  const indexCompare = (Number.isFinite(leftIndex) ? leftIndex : Number.POSITIVE_INFINITY)
    - (Number.isFinite(rightIndex) ? rightIndex : Number.POSITIVE_INFINITY);
  if (indexCompare) return indexCompare;
  return deviceName(left).localeCompare(deviceName(right), "zh-Hans-CN");
}

function modelAttributeRecordForDevice(dev) {
  const raw = dev.raw || {};
  const headers = Array.isArray(dev.__headers) ? dev.__headers : Object.keys(raw);
  const record = {
    dev_type: deviceType(dev),
    dev_name: deviceName(dev),
    idx: formatModelParamValue(raw.idx ?? deviceIndex(dev)),
    name: formatModelParamValue(raw.name || deviceName(dev)),
    __headers: headers,
  };
  headers.forEach((key) => {
    if (["idx", "name", "dev_name", "dev_type"].includes(key)) return;
    record[key] = formatModelParamValue(raw[key], key);
  });
  return record;
}

function modelAttributeColumns(records) {
  const fixed = ["idx", "name"];
  const seen = new Set([...fixed, "dev_type", "dev_name", "__headers"]);
  const keys = [];
  const appendKey = (key) => {
    if (!key || seen.has(key)) return;
    if (!records.some((record) => record[key] !== undefined && record[key] !== "--")) return;
    seen.add(key);
    keys.push(key);
  };
  records.forEach((record) => (record.__headers || Object.keys(record)).forEach(appendKey));
  return [...fixed, ...keys].map((key) => ({ key, label: key === "name" ? "名称" : key }));
}

function groupedModelAttributeRecords(records) {
  const groups = new Map();
  records.forEach((record) => {
    const devType = record.dev_type || "未分类";
    if (!groups.has(devType)) groups.set(devType, []);
    groups.get(devType).push(record);
  });
  return Array.from(groups.entries())
    .map(([devType, rows]) => [devType, rows.sort(compareModelRowsByIndex)])
    .sort(([left], [right]) => left.localeCompare(right, "zh-Hans-CN"));
}

function renderModelAttributeTable(rows) {
  const columns = modelAttributeColumns(rows);
  return `<table class="model-param-table">
    <thead><tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${columns.map((column) => (
      `<td class="attr-value">${escapeHtml(row[column.key] ?? "--")}</td>`
    )).join("")}</tr>`).join("")}</tbody>
  </table>`;
}

function modelFilterLabel() {
  return deviceFilterLabel(state.modelFilter);
}

function renderTraineeModelDeviceTree(snapshot = state.snapshot || {}) {
  const container = $("modelDeviceTree");
  if (!container) return;
  const devices = definedModelDevices(snapshot);
  const groups = devicesByType(devices).map(([devType, items]) => [devType, [...items].sort(compareModelRowsByIndex)]);
  const treeResult = filterDeviceTreeGroups(groups, "model");
  $("modelTreeSummary").textContent = deviceTreeSummary(treeResult);
  const treeHtml = `
    <button type="button" class="tree-node tree-root ${isDeviceTreeNodeActive(state.modelFilter, "all", "") ? "is-active" : ""}"
      data-model-tree-type="all" data-model-tree-name="">
      <span>全部设备</span><strong>${treeResult.query ? treeResult.filteredTotal : devices.length}</strong>
    </button>
    ${treeResult.groupEntries.map(([devType, items]) => {
      const isCollapsed = treeResult.query ? false : isDeviceTreeGroupCollapsed("model", devType);
      return `<div class="tree-group">
        <button type="button"
          class="tree-node tree-type ${isCollapsed ? "is-collapsed" : ""} ${isDeviceTreeNodeActive(state.modelFilter, devType, "") ? "is-active" : isDeviceTreeParentActive(state.modelFilter, devType) ? "is-parent-active" : ""}"
          data-model-tree-type="${escapeHtml(devType)}" data-model-tree-name=""
          ${deviceTreeTypeAttrs("model", devType, isCollapsed)}>
          ${deviceTreeTypeLabel(devType)}<strong>${items.length}</strong>
        </button>
        ${deviceTreeChildren(isCollapsed, items.map((dev) => `
          <button type="button"
            class="tree-node tree-child model-tree-child ${isDeviceTreeNodeActive(state.modelFilter, devType, deviceName(dev)) ? "is-active" : ""}"
            data-model-tree-type="${escapeHtml(devType)}" data-model-tree-name="${escapeHtml(deviceName(dev))}">
            <span class="model-tree-idx">${escapeHtml(formatModelParamValue(deviceIndex(dev)))}</span>
            <span class="model-tree-name">${escapeHtml(deviceName(dev))}</span>
          </button>`).join(""))}
      </div>`;
    }).join("") || renderDeviceTreeFilterEmpty(treeResult.query)}`;
  updateDeviceTreeHtml(container, treeHtml);
}

function renderTraineeModelParamTable(snapshot = state.snapshot || {}) {
  const container = $("modelParamTable");
  if (!container) return;
  const devices = definedModelDevices(snapshot);
  const filtered = filteredDevices(devices, state.modelFilter);
  const groups = groupedModelAttributeRecords(filtered.map(modelAttributeRecordForDevice));
  const availableTabs = groups.map(([devType]) => devType);
  if (!availableTabs.includes(state.activeModelParamTab)) state.activeModelParamTab = availableTabs[0] || "";
  const activeGroup = groups.find(([devType]) => devType === state.activeModelParamTab) || groups[0];
  const activeColumns = activeGroup ? modelAttributeColumns(activeGroup[1]).length : 0;
  $("modelParamSummary").textContent = groups.length > 1
    ? `${modelFilterLabel()} · ${filtered.length}/${devices.length} 台 · ${groups.length} 个分页`
    : `${modelFilterLabel()} · ${filtered.length}/${devices.length} 台 · ${activeColumns} 列属性`;
  if (!devices.length) {
    container.innerHTML = '<div class="empty-state">暂无电网模型数据</div>';
    return;
  }
  if (!activeGroup) {
    container.innerHTML = '<div class="empty-state">当前筛选无模型参数</div>';
    return;
  }
  const [activeType, activeRows] = activeGroup;
  container.innerHTML = `
    <div class="model-param-tabs" role="tablist" aria-label="设备类型参数表">
      ${groups.map(([devType, rows]) => `<button type="button" role="tab"
        class="model-param-tab ${devType === activeType ? "is-active" : ""}"
        data-model-param-tab="${escapeHtml(devType)}" aria-selected="${devType === activeType}">
        <span>${escapeHtml(devType)}</span><strong>${rows.length}</strong>
      </button>`).join("")}
    </div>
    <section class="model-param-tab-page" role="tabpanel">${renderModelAttributeTable(activeRows)}</section>`;
}

function renderTraineeModelPage(snapshot = state.snapshot || {}) {
  renderTraineeModelDeviceTree(snapshot);
  renderTraineeModelParamTable(snapshot);
}

function setTraineeModelFilter(devType, devName = "", event = null, button = null) {
  state.modelFilter = updateDeviceTreeFilterSelection(
    "modelFilter",
    devType,
    devName,
    event,
    "model",
    button,
  );
  if (devType && devType !== "all" && !devName) state.activeModelParamTab = devType;
  renderTraineeModelPage();
}

function isWeatherMeasurement(row) {
  return row?.dev_type === "Environment" && row?.dev_name === "weather";
}

function isSignalMeasurement(row) {
  return Object.prototype.hasOwnProperty.call(SIGNAL_MEASUREMENT_LABELS, String(row?.meas_type || "").toUpperCase());
}

function measurementPresentationValue(value, row = null) {
  if (value === null || value === undefined || value === "") return value;
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return String(row?.meas_type || "").toUpperCase() === "SOC" ? number * 100 : number;
}

function formatMeasurementDisplayValue(value, row = null, analogFormatter = formatNumber) {
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
  return isWeatherMeasurement(row) ? "气象" : row.dev_name || "";
}

function measurementTypeDisplay(row) {
  if (isSignalMeasurement(row)) return signalMeasurementLabel(row);
  return isWeatherMeasurement(row) ? weatherMeasurementLabel(row) : row.meas_type || "";
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

function measurementRows(snapshot = state.snapshot || {}) {
  return measurementDisplayRows(snapshot);
}

function measurementCompareRows(
  measurements = state.snapshot?.measurements || {},
  definitionRows = null,
) {
  const definitions = definitionRows
    || state.snapshot?.definitions?.measurement
    || measurements.definitions
    || [];
  const primaryRows = definitions.length
    ? definitions
    : (measurements.scada || []);
  const scadaByKey = new Map((measurements.scada || []).map((row) => [measurementKey(row), row]));
  return sortMeasurementsForDisplay(primaryRows.map((definition) => {
    const key = measurementKey(definition);
    const scada = scadaByKey.get(key);
    const scadaValue = scada?.value;
    return {
      ...definition,
      value: scadaValue ?? definition.value,
      scada_value: scadaValue,
      valid: scada?.valid ?? definition.valid,
      weight: definition.weight,
    };
  }));
}

function measurementDisplayRows(snapshot = state.snapshot || {}) {
  const measurements = snapshot.measurements || {};
  const definitions = snapshot.definitions?.measurement
    || snapshot.measurements?.definitions
    || measurements.definitions
    || [];
  return measurementCompareRows(measurements, definitions);
}

function measurementDeviceMetadataIndex(snapshot = state.snapshot || {}) {
  const metadataByKey = new Map();
  const remember = (dev) => {
    const devType = String(dev?.dev_type || dev?.type || "").trim();
    const devName = String(dev?.dev_name || dev?.name || "").trim();
    const modelBlock = deviceModelBlock(dev);
    if (!devType || !devName || !modelBlock) return;
    const key = `${devType}|${devName}`;
    const metadata = {
      ...(metadataByKey.get(key) || {}),
      model_block: modelBlock,
    };
    const family = deviceFamily(dev);
    if (family) metadata.device_family = family;
    if (Array.isArray(dev?.terminal_domains)) metadata.terminal_domains = [...dev.terminal_domains];
    const technology = String(dev?.resource_technology || "").trim();
    if (technology) metadata.resource_technology = technology;
    metadataByKey.set(key, metadata);
  };

  definedModelDevices(snapshot).forEach(remember);
  (snapshot.devices || []).forEach(remember);
  metadataByKey.set("Environment|weather", {
    model_block: "Environment",
    device_family: "environment",
  });
  return metadataByKey;
}

function measurementsDevices(snapshot = state.snapshot || {}) {
  const devices = new Map();
  const metadataByKey = measurementDeviceMetadataIndex(snapshot);
  measurementRows(snapshot).forEach((row) => {
    const key = `${row.dev_type || ""}|${row.dev_name || ""}`;
    if (!devices.has(key)) {
      devices.set(key, {
        ...(metadataByKey.get(key) || {}),
        dev_type: row.dev_type || "Measurement",
        dev_name: row.dev_name || row.name || "",
        run_stat: row.valid,
      });
    }
  });
  return Array.from(devices.values());
}

function measurementKey(meas) {
  return `${meas.idx ?? ""}|${meas.name || ""}|${meas.dev_type || ""}|${meas.dev_name || ""}|${meas.meas_type || ""}`;
}

function filteredMeasurements(rows, filter) {
  return (rows || []).filter((row) => deviceFilterMatches(row, filter));
}

function measurementTypeFilterLabel(row) {
  return measurementTypeDisplay(row) || row?.meas_type || "";
}

function measurementTableFilterFields(row) {
  return [
    measurementDisplayName(row),
    measurementDeviceDisplay(row),
    measurementTypeFilterLabel(row),
    row?.name,
    row?.idx,
    row?.dev_type,
    row?.dev_name,
    row?.meas_type,
  ];
}

function syncMeasurementTypeFilter(rows) {
  syncTableKeywordFilter("measurementKeywordFilter", state.measurementKeywordFilter);
  syncTableTypeFilter(
    "measurementTypeFilter",
    "measurementTypeFilter",
    tableFilterTypeOptions(rows, measurementTypeFilterLabel),
  );
}

function applyMeasurementTableFilters(rows) {
  const keyword = state.measurementKeywordFilter || "";
  const type = state.measurementTypeFilter || "all";
  return (rows || []).filter((row) => {
    if (!tableFilterMatchesKeyword(measurementTableFilterFields(row), keyword)) return false;
    if (type !== "all" && measurementTypeFilterLabel(row) !== type) return false;
    return true;
  });
}

function measurementTelemetryRows(rows) {
  return (rows || []).filter((row) => !isSignalMeasurement(row));
}

function measurementSignalRows(rows) {
  return (rows || []).filter((row) => isSignalMeasurement(row));
}

function setMeasurementTab(tabName) {
  state.activeMeasurementTab = tabName === "signal" ? "signal" : "telemetry";
  renderMeasurements(state.snapshot || {});
  drawMeasurementTraceChart();
}

function activeMeasurementRows(rows) {
  return state.activeMeasurementTab === "signal"
    ? measurementSignalRows(rows)
    : measurementTelemetryRows(rows);
}

function renderMeasurementTabs(telemetryRows, signalRows) {
  const activeTab = state.activeMeasurementTab === "signal" ? "signal" : "telemetry";
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
          data-measurement-tab="${tab.key}"
          aria-selected="${activeTab === tab.key ? "true" : "false"}"
        >
          <span>${tab.label}</span>
          <strong>${tab.count}</strong>
        </button>
      `).join("")}
    </div>
  `;
}

function ensureSelectedMeasurement(rows) {
  const keys = new Set(rows.map((row) => measurementKey(row)));
  if (!state.selectedMeasurementKey || !keys.has(state.selectedMeasurementKey)) {
    state.selectedMeasurementKey = rows.length ? measurementKey(rows[0]) : "";
  }
}

function measurementTableStructureKey(rows) {
  return [
    state.activeMeasurementTab || "telemetry",
    deviceTreeFilterSelection(state.measurementFilter).map((item) => deviceTreeFilterKey(item.dev_type, item.dev_name)).join("|"),
    state.measurementKeywordFilter || "",
    state.measurementTypeFilter || "all",
    rows.map((row) => measurementKey(row)).join("||"),
  ].join("::");
}

function measurementLiveCellHtml(row, field) {
  if (field === "scada") return formatMeasurementDisplayValue(measurementPresentationValue(row.scada_value, row), row);
  if (field === "status") {
    const valid = Number(row.valid) ? true : false;
    return `<span class="status-pill ${valid ? "is-ok" : "is-off"}">${valid ? "可用" : "停用"}</span>`;
  }
  return "";
}

function updateMeasurementTableLiveCells(rows) {
  const tableRows = Array.from(document.querySelectorAll("#measurementTable [data-measurement-row-key]"));
  if (tableRows.length !== rows.length) return false;
  const rowsByKey = new Map(rows.map((row) => [measurementKey(row), row]));
  for (const tableRow of tableRows) {
    const key = tableRow.dataset.measurementRowKey || "";
    const row = rowsByKey.get(key);
    if (!row) return false;
    tableRow.classList.toggle("is-selected", key === state.selectedMeasurementKey);
    tableRow.querySelectorAll("[data-measurement-live-field]").forEach((cell) => {
      const field = cell.dataset.measurementLiveField || "";
      cell.innerHTML = measurementLiveCellHtml(row, field);
      if (field === "scada") {
        const value = Number(row.scada_value || 0);
        cell.classList.toggle("value-bad", Math.abs(value) > 10000);
        cell.classList.toggle("value-warn", Math.abs(value) > 1000 && Math.abs(value) <= 10000);
      }
    });
  }
  return true;
}

function renderMeasurements(snapshot = state.snapshot || {}) {
  const container = $("measurementTable");
  if (!container) return;
  const devices = measurementsDevices(snapshot);
  renderDeviceTree("measurementDeviceTree", "measurementTreeSummary", devices, state.measurementFilter, "measurement", "measurement");
  const allRows = measurementRows(snapshot);
  const filteredRows = filteredMeasurements(allRows, state.measurementFilter);
  syncMeasurementTypeFilter(filteredRows);
  let tableFilteredRows = applyMeasurementTableFilters(filteredRows);
  if (state.measurementOnlyAbnormal) {
    tableFilteredRows = tableFilteredRows.filter(
      (item) => Number(item.valid) !== 1 || String(item.status || "normal") !== "normal",
    );
  }
  const telemetryRows = measurementTelemetryRows(tableFilteredRows);
  const signalRows = measurementSignalRows(tableFilteredRows);
  const rows = activeMeasurementRows(tableFilteredRows);
  ensureSelectedMeasurement(rows);
  const validCount = rows.filter((item) => Number(item.valid) === 1).length;
  const activeLabel = state.activeMeasurementTab === "signal" ? "遥信" : "遥测";
  const filterActive = Boolean(state.measurementOnlyAbnormal)
    || tableFilterIsActive(state.measurementKeywordFilter, state.measurementTypeFilter);
  $("measurementValidCount").textContent = filterActive
    ? `${activeLabel} ${rows.length}/${tableFilteredRows.length} 点 · 有效 ${validCount} 点 · 过滤 ${tableFilteredRows.length}/${filteredRows.length} 点`
    : `${activeLabel} ${rows.length}/${filteredRows.length} 点 · 有效 ${validCount} 点`;
  const tabHtml = renderMeasurementTabs(telemetryRows, signalRows);
  if (!allRows.length) {
    container.dataset.measurementStructureKey = "";
    container.innerHTML = `${tabHtml}<div class="measurement-type-tab-page is-active"><div class="empty-state">暂无量测数据</div></div>`;
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
  const virtualRows = virtualTableWindow("measurement", rows);
  const structureKey = [
    measurementTableStructureKey(rows),
    virtualRows.enabled ? "virtual" : "full",
    virtualRows.start,
    virtualRows.end,
  ].join("|");
  if (
    container.dataset.measurementStructureKey === structureKey
    && updateMeasurementTableLiveCells(virtualRows.rows)
  ) {
    drawMeasurementTraceChart();
    return;
  }
  container.dataset.measurementStructureKey = structureKey;
  container.innerHTML = `
    ${tabHtml}
    <div class="measurement-type-tab-page is-active">
    <div class="virtual-table-scroll" data-virtual-table="measurement">
    <table class="measurement-compare-table">
      <thead><tr><th>idx</th><th>量测名</th><th>设备</th><th>类型</th><th>量测值</th><th>状态</th></tr></thead>
      <tbody>
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, 6)}
        ${virtualRows.rows.map((item) => {
          const key = measurementKey(item);
          const valueClass = Math.abs(Number(item.scada_value || 0)) > 10000 ? "value-bad" : Math.abs(Number(item.scada_value || 0)) > 1000 ? "value-warn" : "";
          return `<tr class="${key === state.selectedMeasurementKey ? "is-selected" : ""}" data-measurement-row-key="${escapeHtml(key)}" data-measurement-select-key="${escapeHtml(key)}">
            <td>${escapeHtml(item.idx ?? "")}</td>
            <td>${escapeHtml(measurementDisplayName(item) || "")}</td>
            <td>${escapeHtml(measurementDeviceDisplay(item))}</td>
            <td>${escapeHtml(measurementTypeDisplay(item))}</td>
            <td class="numeric-cell ${valueClass}" data-measurement-live-field="scada">${formatMeasurementDisplayValue(measurementPresentationValue(item.scada_value, item), item)}</td>
            <td data-measurement-live-field="status"><span class="status-pill ${Number(item.valid) ? "is-ok" : "is-off"}">${Number(item.valid) ? "可用" : "停用"}</span></td>
          </tr>`;
        }).join("")}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, 6)}
      </tbody>
    </table>
    </div>
    </div>`;
  restoreVirtualTableScroll(container, "measurement");
  drawMeasurementTraceChart();
}

function appendMeasurementTrace(snapshot) {
  const sampledClock = snapshot.measurement_clock;
  const clock = sampledClock && Number(sampledClock.step_count ?? 0) > 0
    ? sampledClock
    : snapshot.clock || {};
  if (isSimulationFrozenSnapshot(snapshot)) return false;
  if (Number(clock.step_count ?? 0) <= 0) return false;
  const rows = measurementCompareRows(snapshot.measurements || {});
  if (!rows.some((row) => diagramTrendFiniteValue(row.scada_value) !== null)) {
    return false;
  }
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
  state.lastMeasurementTraceKey = signature;
  const point = {
    minute: Number(clock.absolute_minute ?? clock.minute ?? state.measurementTraceHistory.length) || 0,
    time: clock.time || "--",
    sim_time: clock.time || "--",
    run_id: Number(clock.run_id ?? 0) || 0,
    step_count: Number(clock.step_count ?? 0) || 0,
    measurements: {},
  };
  rows.forEach((row) => {
    const scada = diagramTrendFiniteValue(measurementPresentationValue(row.scada_value, row));
    point.measurements[measurementKey(row)] = {
      value: scada,
      scada,
      valid: Number(row.valid) === 1 ? 1 : 0,
      dev_type: row.dev_type || "",
      dev_name: row.dev_name || "",
      meas_type: row.meas_type || "",
      label: `${measurementDeviceDisplay(row) || row.name || ""} ${measurementTypeDisplay(row) || ""}`.trim(),
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
    const arrays = [frame.scada_values, frame.valid_values];
    if (arrays.some((values) => !Array.isArray(values) || values.length !== indices.length)) {
      throw new Error("历史量测数组长度不一致，历史帧已拒绝");
    }
    const minute = Number(frame.absolute_minute);
    if (!Number.isFinite(minute)) throw new Error("历史量测仿真时刻无效，历史帧已拒绝");
    const scada = diagramTrendFiniteValue(measurementPresentationValue(frame.scada_values[selectedPosition], row));
    const validValue = frame.valid_values[selectedPosition];
    return {
      minute,
      time: frame.simu_time || "--",
      sim_time: frame.simu_time || "--",
      record_time: frame.wall_time || "",
      run_id: Number(frame.run_id ?? payloadRunId) || payloadRunId,
      step_count: Number(frame.step_count ?? 0) || 0,
      history_seq: Number(frame.seq ?? 0) || 0,
      measurements: {
        [key]: {
          name: measurementDisplayName(row) || "",
          value: scada,
          scada,
          valid: validValue === null || validValue === undefined
            ? (Number(row.valid) === 1 ? 1 : 0)
            : (Number(validValue) === 1 ? 1 : 0),
          dev_type: row.dev_type || "",
          dev_name: row.dev_name || "",
          meas_type: row.meas_type || "",
          unit: diagramMeasurementUnit(row.meas_type),
          label: `${measurementDeviceDisplay(row) || row.name || ""} ${measurementTypeDisplay(row) || ""}`.trim(),
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
      if (!existing.time || existing.time === "--") existing.time = point.time;
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
  const historyPath = state.receiveMode
    ? `/api/trainee/measurement-history?indices=${definitionIndex}`
    : `/api/measurement-history?indices=${definitionIndex}`;
  const request = api(historyPath)
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

function selectedMeasurementHistoryRow() {
  if (!state.selectedMeasurementKey) return null;
  return measurementCompareRows(state.snapshot?.measurements || {}).find(
    (row) => measurementKey(row) === state.selectedMeasurementKey,
  ) || null;
}

function ensureSelectedMeasurementHistory() {
  const row = selectedMeasurementHistoryRow();
  if (!row) return;
  ensureMeasurementHistoryForRow(row).then((changed) => {
    if (changed && measurementKey(row) === state.selectedMeasurementKey) {
      drawMeasurementTraceChart();
    }
  });
}

function traceAxisStepMinutes(windowMinutes) {
  const minutes = Math.max(1, Number(windowMinutes) || 60);
  if (minutes <= 15) return 5;
  if (minutes <= 60) return 15;
  if (minutes <= 180) return 30;
  if (minutes <= 360) return 60;
  if (minutes <= 1440) return 240;
  if (minutes <= 10080) return 1440;
  if (minutes <= 43200) return 5 * 1440;
  if (minutes <= 525600) return 60 * 1440;
  return Math.max(60, Math.round(minutes / 6 / 60) * 60);
}

function traceWindowAlignmentMinutes(windowMinutes) {
  const minutes = Math.max(1, Number(windowMinutes) || 60);
  if (minutes <= 15) return 15;
  if (minutes <= 1440) return minutes;
  if (minutes >= 525600) return 525600;
  return 1440;
}

function traceHistoryMinuteBounds(history, fallbackMinute = 0) {
  let earliestMinute = Number.POSITIVE_INFINITY;
  let latestMinute = Number.NEGATIVE_INFINITY;
  (Array.isArray(history) ? history : []).forEach((point) => {
    const minute = Number(point?.minute);
    if (!Number.isFinite(minute)) return;
    earliestMinute = Math.min(earliestMinute, minute);
    latestMinute = Math.max(latestMinute, minute);
  });
  const fallback = Number.isFinite(Number(fallbackMinute)) ? Number(fallbackMinute) : 0;
  const hasHistory = Number.isFinite(earliestMinute) && Number.isFinite(latestMinute);
  return {
    earliestMinute: hasHistory ? earliestMinute : fallback,
    latestMinute: hasHistory ? latestMinute : fallback,
    hasHistory,
  };
}

function alignedTraceWindowRange(
  history,
  windowMinutes,
  fallbackMinute,
  requestedOffset = 0,
  simulationDurationMinutes = Number.POSITIVE_INFINITY,
) {
  const minutes = Math.max(1, Number(windowMinutes) || 60);
  const alignmentMinutes = traceWindowAlignmentMinutes(minutes);
  const bounds = traceHistoryMinuteBounds(history, fallbackMinute);
  const fallback = Number.isFinite(Number(fallbackMinute)) ? Number(fallbackMinute) : bounds.latestMinute;
  const latestMinute = Math.max(bounds.latestMinute, fallback);
  const currentStartMinute = Math.floor(latestMinute / alignmentMinutes) * alignmentMinutes;
  const normalizedSimulationDuration = Number(simulationDurationMinutes);
  const cycleStartMinute = Number.isFinite(normalizedSimulationDuration) && normalizedSimulationDuration > 0
    ? Math.floor((latestMinute + 1e-9) / normalizedSimulationDuration) * normalizedSimulationDuration
    : Number.NEGATIVE_INFINITY;
  const earliestMinute = bounds.hasHistory
    ? Math.max(bounds.earliestMinute, cycleStartMinute)
    : latestMinute;
  const periodNavigationAllowed = !Number.isFinite(normalizedSimulationDuration)
    || normalizedSimulationDuration <= 0
    || minutes < normalizedSimulationDuration;
  const minWindowOffset = periodNavigationAllowed && bounds.hasHistory
    ? Math.min(0, Math.floor((earliestMinute - currentStartMinute) / minutes))
    : 0;
  const normalizedOffset = periodNavigationAllowed
    ? Math.min(0, Math.trunc(Number(requestedOffset) || 0))
    : 0;
  const windowOffset = Math.max(minWindowOffset, normalizedOffset);
  const startMinute = currentStartMinute + windowOffset * minutes;
  return {
    startMinute,
    endMinute: startMinute + minutes,
    latestMinute,
    earliestMinute,
    currentStartMinute,
    windowMinutes: minutes,
    alignmentMinutes,
    axisStepMinutes: traceAxisStepMinutes(minutes),
    windowOffset,
    minWindowOffset,
    periodNavigationAllowed,
  };
}

function tracePeriodNavigationState(range = {}) {
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

function chartPeriodOffset(chartKey) {
  return Math.min(0, Math.trunc(Number(state.chartPeriodOffsets?.[chartKey]) || 0));
}

function setChartPeriodOffset(chartKey, offset) {
  state.chartPeriodOffsets = {
    ...(state.chartPeriodOffsets || {}),
    [chartKey]: Math.min(0, Math.trunc(Number(offset) || 0)),
  };
}

function resetChartPeriodOffsets(...chartKeys) {
  const keys = chartKeys.length ? chartKeys : Object.keys(state.chartPeriodOffsets || {});
  keys.forEach((chartKey) => setChartPeriodOffset(chartKey, 0));
}

function syncChartPeriodNavigation(chartKey, range) {
  const navigation = tracePeriodNavigationState(range);
  document.querySelectorAll(`[data-chart-period-nav="${chartKey}"]`).forEach((container) => {
    container.hidden = !navigation.visible;
    container.dataset.windowOffset = String(Number(range?.windowOffset) || 0);
    const previous = container.querySelector('[data-chart-period-action="previous"]');
    const current = container.querySelector('[data-chart-period-action="current"]');
    const next = container.querySelector('[data-chart-period-action="next"]');
    if (previous) previous.disabled = navigation.previousDisabled;
    if (current) current.disabled = navigation.currentDisabled;
    if (next) next.disabled = navigation.nextDisabled;
  });
  return navigation;
}

function initChartPeriodNavigation(chartKey, rangeProvider, drawChart) {
  const container = document.querySelector(`[data-chart-period-nav="${chartKey}"]`);
  if (!container || container.dataset.periodNavigationReady === "true") return;
  container.dataset.periodNavigationReady = "true";
  container.addEventListener("click", (event) => {
    const button = event.target instanceof Element
      ? event.target.closest('[data-chart-period-action]')
      : null;
    if (!button || button.disabled || !container.contains(button)) return;
    const range = rangeProvider();
    const action = button.getAttribute("data-chart-period-action") || "";
    const currentOffset = Number(range.windowOffset) || 0;
    const nextOffset = action === "previous"
      ? currentOffset - 1
      : action === "next" ? currentOffset + 1 : 0;
    setChartPeriodOffset(chartKey, nextOffset);
    drawChart();
  });
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
    curveDisplayModeDurationMinutes(),
  );
  setChartPeriodOffset("measurementTrace", range.windowOffset);
  return range;
}

function measurementTraceWindowPoints(range = measurementTraceWindowRange()) {
  const history = state.measurementTraceHistory || [];
  if (!history.length || !state.selectedMeasurementKey) return [];
  const points = history
    .map((point) => {
      const item = point.measurements[state.selectedMeasurementKey];
      if (!item || !Number.isFinite(item.value)) return null;
      return { minute: point.minute, time: point.time, value: item.value, label: item.label };
    })
    .filter(Boolean);
  return traceWindowRealPoints(points, range);
}

function formatTraceClockMinute(minute) {
  const total = ((Math.round(Number(minute) || 0) % 1440) + 1440) % 1440;
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:00`;
}

function formatYearTraceTickLabel(minute) {
  const absoluteDay = Math.floor(Math.max(0, Number(minute) || 0) / 1440);
  const year = Math.floor(absoluteDay / 365) + 1;
  let dayOfYear = absoluteDay % 365;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  while (month < monthDays.length - 1 && dayOfYear >= monthDays[month]) {
    dayOfYear -= monthDays[month];
    month += 1;
  }
  return year === 1 ? `${String(month + 1).padStart(2, "0")}月` : `第${year}年${String(month + 1).padStart(2, "0")}月`;
}

function measurementTraceTimeLabel(minute, range, index, lastIndex) {
  const targetMinute = index === lastIndex ? range.endMinute : minute;
  if (range.windowMinutes <= 1440) return formatTraceClockMinute(targetMinute);
  if (range.windowMinutes >= 525600) return formatYearTraceTickLabel(targetMinute);
  const absolute = Math.max(0, Math.round(Number(targetMinute) || 0));
  const day = Math.floor(absolute / 1440);
  const clock = formatTraceClockMinute(absolute).slice(0, 5);
  return absolute % 1440 === 0 ? `第${day + 1}天` : `第${day + 1}天 ${clock}`;
}

function measurementTracePointTimeLabel(point, range) {
  const time = String(point?.sim_time || point?.time || "").trim();
  if (time && time !== "--") return time;
  return measurementTraceTimeLabel(point?.minute, range, -1, 0);
}

function measurementTraceAxisTicks(range, canvasWidth) {
  const maxTicks = canvasWidth < 480 ? 4 : canvasWidth < 760 ? 5 : 8;
  let step = range.axisStepMinutes || traceAxisStepMinutes(range.windowMinutes);
  while (Math.floor(range.windowMinutes / step) + 1 > maxTicks) {
    step *= 2;
  }
  const ticks = [];
  for (let minute = range.startMinute; minute <= range.endMinute + 1e-9; minute += step) {
    ticks.push(minute);
  }
  if (ticks[ticks.length - 1] !== range.endMinute) ticks.push(range.endMinute);
  return ticks;
}

function resizeCanvas(canvas) {
  const ratio = canvasDevicePixelRatio();
  const { width: renderedWidth, height: renderedHeight } = canvasRenderedSize(canvas, 900, 320);
  const width = Math.floor(renderedWidth * ratio);
  const height = Math.floor(renderedHeight * ratio);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  return { width, height, ratio };
}

function drawMeasurementTraceChart() {
  const canvas = $("measurementTraceChart");
  if (!canvas) return;
  const chartKey = "measurementTrace";
  const ctx = canvas.getContext("2d");
  const { width, height, ratio } = resizeCanvas(canvas);
  const palette = chartThemePalette();
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, width, height);
  const left = 62 * ratio;
  const right = 24 * ratio;
  const top = 34 * ratio;
  const bottom = 38 * ratio;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const plot = { left, right, top, bottom };
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };
  ctx.strokeStyle = palette.grid;
  ctx.lineWidth = 1 * ratio;
  for (let i = 0; i <= 4; i += 1) {
    const y = top + (plotHeight * i) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
  }
  const range = measurementTraceWindowRange();
  syncChartPeriodNavigation("measurementTrace", range);
  const xTicks = measurementTraceAxisTicks(range, width / ratio);
  xTicks.forEach((minute, tickIndex) => {
    const x = left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
    ctx.strokeStyle = tickIndex === xTicks.length - 1 ? palette.axis : palette.gridSubtle;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotHeight);
    ctx.stroke();
    ctx.fillStyle = palette.text;
    ctx.font = `${12 * ratio}px Consolas, Microsoft YaHei, Arial`;
    ctx.textAlign = tickIndex === xTicks.length - 1 ? "right" : "left";
    const textOffset = tickIndex === 0 ? 0 : tickIndex === xTicks.length - 1 ? 0 : 4 * ratio;
    ctx.fillText(measurementTraceTimeLabel(minute, range, tickIndex, xTicks.length - 1), x + textOffset, height - 12 * ratio);
  });
  ctx.textAlign = "left";
  const points = measurementTraceWindowPoints(range);
  const seriesDefs = [
    { key: "value", field: "value", label: "量测值", color: "#c93a3a" },
  ];
  const visibleSeries = visibleChartSeries(chartKey, seriesDefs);
  const values = points.flatMap((point) => visibleSeries.map((series) => point[series.field]))
    .filter((value) => value !== null && Number.isFinite(value));
  if (!points.length || !visibleSeries.length || !values.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = "#63717a";
    ctx.font = `${13 * ratio}px Microsoft YaHei, Arial`;
    ctx.textAlign = "center";
    ctx.fillText(!visibleSeries.length ? "所有曲线已隐藏" : "暂无测点跟踪数据", width / 2, height / 2);
    ctx.textAlign = "left";
    $("measurementTraceSummary").textContent = "未选择测点";
    return;
  }
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const span = Math.max(1e-6, maxValue - minValue);
  const selectedSeries = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const hitData = [];
  visibleSeries.forEach((series) => {
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = (series.key === selectedSeries ? 3.2 : 2.4) * ratio;
    ctx.beginPath();
    let started = false;
    let previousMinute = null;
    points.forEach((point) => {
      const value = Number(point[series.field]);
      if (!Number.isFinite(value)) return;
      const x = left + ((point.minute - range.startMinute) / range.windowMinutes) * plotWidth;
      const y = top + plotHeight - ((value - minValue) / span) * plotHeight;
      pixelPoints.push({ x, y, minute: point.minute, time: point.time, value });
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
    hitData.push({ ...series, unit: "", points: pixelPoints });
  });
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    ratio,
    timeLabel: (point) => measurementTracePointTimeLabel(point, range),
    valueFormatter: formatNumber,
  });
  ctx.fillStyle = "#63717a";
  ctx.font = `${12 * ratio}px Consolas, Microsoft YaHei, Arial`;
  ctx.fillText(formatNumber(maxValue), 8 * ratio, top + 4 * ratio);
  ctx.fillText(formatNumber(minValue), 8 * ratio, top + plotHeight);
  $("measurementTraceSummary").textContent = `${points[points.length - 1].label || "测点"} · ${traceWindowDataPointCount(points)} 点`;
}

function commandTraceRunKey(dev, commandType = "run_stat") {
  return `remote-control|${deviceKey(dev)}|${commandType}`;
}

function commandTraceAdjustmentKey(dev, setType) {
  return `remote-adjustment|${deviceKey(dev)}|${setType}`;
}

function commandTraceNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function selectedCommandTraceLabel() {
  const latest = [...(state.commandTraceHistory || [])].reverse()
    .map((point) => point.commands?.[state.selectedCommandTraceKey])
    .find(Boolean);
  return latest?.label || state.selectedCommandTraceLabel || "请选择指令";
}

function commandTraceWindowRange() {
  const history = state.commandTraceHistory || [];
  const windowMinutes = Math.max(1, Number(state.commandTraceWindowMinutes) || 60);
  const fallbackMinute = Number(state.snapshot?.clock?.absolute_minute ?? state.snapshot?.clock?.minute ?? 0) || 0;
  const range = alignedTraceWindowRange(
    history,
    windowMinutes,
    fallbackMinute,
    chartPeriodOffset("commandTrace"),
    curveDisplayModeDurationMinutes(),
  );
  setChartPeriodOffset("commandTrace", range.windowOffset);
  return range;
}

function commandTraceWindowPoints(range = commandTraceWindowRange()) {
  const history = state.commandTraceHistory || [];
  if (!history.length || !state.selectedCommandTraceKey) return [];
  const points = history
    .map((point) => {
      const item = point.commands?.[state.selectedCommandTraceKey];
      if (!item) return null;
      const control = commandTraceNumber(item.control);
      const actual = commandTraceNumber(item.actual);
      return {
        minute: point.minute,
        time: point.time,
        control,
        actual,
        label: item.label,
        unit: item.unit || "",
      };
    })
    .filter(Boolean);
  return traceWindowRealPoints(points, range);
}

function appendCommandTrace(snapshot) {
  const clock = snapshot.clock || {};
  if (isSimulationFrozenSnapshot(snapshot)) return false;
  if (Number(clock.step_count ?? 0) <= 0) return;
  const devices = controlDefinitionDevices(snapshot);
  const point = {
    minute: Number(clock.absolute_minute ?? clock.minute ?? state.commandTraceHistory.length) || 0,
    time: clock.time || "--",
    commands: {},
  };
  selectedControlRows("RunStat", devices, snapshot).forEach((row) => {
    const dev = controlDeviceFromRow(row, snapshot);
    const runKey = commandTraceRunKey(dev, "run_stat");
    const pendingRun = pending.run_status.get(`${deviceKey(dev)}|run_stat`);
    const control = pendingRun ? pendingRun.run_stat : dev.run_stat;
    point.commands[runKey] = {
      control: commandTraceNumber(control),
      actual: commandTraceNumber(dev.run_stat),
      label: `${deviceType(dev)}.${deviceName(dev)}.遥控投退`,
      unit: "",
    };
  });
  selectedControlRows("CbOpenStat", devices, snapshot).forEach((row) => {
    const dev = controlDeviceFromRow(row, snapshot);
    const statusKey = commandTraceRunKey(dev, "status");
    const pendingStatus = pending.run_status.get(`${deviceKey(dev)}|status`);
    const control = pendingStatus
      ? pendingStatus.status
      : (dev.closed_status_set ?? row.closed_status_set ?? dev.status);
    const actual = remoteControlFeedbackValue(dev, "status", snapshot)
      ?? dev.closed_status
      ?? dev.status;
    point.commands[statusKey] = {
      control: commandTraceNumber(control),
      actual: commandTraceNumber(actual),
      label: `${deviceType(dev)}.${deviceName(dev)}.遥控开合`,
      unit: "",
    };
  });
  remoteAdjustmentRows(devices, snapshot).forEach((row) => {
    point.commands[row.traceKey] = {
      control: commandTraceNumber(row.controlValue),
      actual: commandTraceNumber(row.measurement),
      label: row.name,
      unit: "",
    };
  });
  state.commandTraceHistory.push(point);
  state.commandTraceHistory = compactTraceHistory(state.commandTraceHistory, state.commandTraceWindowMinutes);
}

function drawCommandTraceChart() {
  const canvas = $("commandTraceChart");
  if (!canvas) return;
  const chartKey = "commandTrace";
  const ctx = canvas.getContext("2d");
  const { width, height, ratio } = resizeCanvas(canvas);
  const palette = chartThemePalette();
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, width, height);
  const left = 62 * ratio;
  const right = 24 * ratio;
  const top = 30 * ratio;
  const bottom = 36 * ratio;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const plot = { left, right, top, bottom };
  state.chartPlotInfo = { ...(state.chartPlotInfo || {}), [chartKey]: plot };
  ctx.strokeStyle = palette.grid;
  ctx.lineWidth = 1 * ratio;
  for (let i = 0; i <= 4; i += 1) {
    const y = top + (plotHeight * i) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
  }
  const range = commandTraceWindowRange();
  syncChartPeriodNavigation("commandTrace", range);
  const xTicks = measurementTraceAxisTicks(range, width / ratio);
  xTicks.forEach((minute, tickIndex) => {
    const x = left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
    ctx.strokeStyle = tickIndex === xTicks.length - 1 ? palette.axis : palette.gridSubtle;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotHeight);
    ctx.stroke();
    ctx.fillStyle = palette.text;
    ctx.font = `${12 * ratio}px Consolas, Microsoft YaHei, Arial`;
    ctx.textAlign = tickIndex === xTicks.length - 1 ? "right" : "left";
    const textOffset = tickIndex === 0 ? 0 : tickIndex === xTicks.length - 1 ? 0 : 4 * ratio;
    ctx.fillText(measurementTraceTimeLabel(minute, range, tickIndex, xTicks.length - 1), x + textOffset, height - 12 * ratio);
  });
  ctx.textAlign = "left";
  const points = commandTraceWindowPoints(range);
  const seriesDefs = [
    { key: "control", field: "control", label: "控制值", color: "#c98820" },
    { key: "actual", field: "actual", label: "实时值", color: "#008c8c" },
  ];
  const visibleSeries = visibleChartSeries(chartKey, seriesDefs);
  const values = points.flatMap((point) => visibleSeries.map((series) => point[series.field]))
    .filter((value) => value !== null && Number.isFinite(value));
  $("commandTraceSummary").textContent = `${selectedCommandTraceLabel()} · ${traceWindowDataPointCount(points)} 点`;
  if (!state.selectedCommandTraceKey || !points.length || !visibleSeries.length || !values.length) {
    state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: [] };
    syncChartLegendButtons(chartKey);
    ctx.fillStyle = "#63717a";
    ctx.font = `${13 * ratio}px Microsoft YaHei, Arial`;
    ctx.textAlign = "center";
    ctx.fillText(
      !visibleSeries.length ? "所有曲线已隐藏" : state.selectedCommandTraceKey ? "暂无指令跟踪数据" : "请选择控制指令",
      width / 2,
      height / 2,
    );
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
  const xForMinute = (minute) => left + ((minute - range.startMinute) / range.windowMinutes) * plotWidth;
  const yForValue = (value) => top + plotHeight - ((value - minValue) / (maxValue - minValue)) * plotHeight;
  const selectedSeries = selectedChartSeriesKey(chartKey, visibleSeries[0]?.key || "");
  const hitData = [];
  const unit = points.find((point) => point.unit)?.unit || "";
  const drawSeries = (series, widthScale) => {
    const pixelPoints = [];
    ctx.strokeStyle = series.color;
    ctx.lineWidth = (series.key === selectedSeries ? widthScale + 1 : widthScale) * ratio;
    ctx.beginPath();
    let started = false;
    let previousY = Number.NaN;
    points.forEach((point) => {
      const value = point[series.field];
      if (value === null || !Number.isFinite(value)) return;
      const x = xForMinute(point.minute);
      const y = yForValue(value);
      pixelPoints.push({ x, y, minute: point.minute, time: point.time, value });
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else if (series.key === "control") {
        ctx.lineTo(x, previousY);
        if (Math.abs(y - previousY) > 1e-9) ctx.lineTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
      previousY = y;
    });
    if (started) ctx.stroke();
    hitData.push({ ...series, unit, points: pixelPoints });
  };
  visibleSeries.forEach((series) => drawSeries(series, series.key === "control" ? 2.4 : 2.2));
  state.chartSeriesHitData = { ...(state.chartSeriesHitData || {}), [chartKey]: hitData };
  syncChartLegendButtons(chartKey);
  drawChartCursor(ctx, chartKey, canvas, plot, hitData, {
    ratio,
    timeLabel: (point) => measurementTracePointTimeLabel(point, range),
    valueFormatter: formatNumber,
  });
  ctx.fillStyle = "#63717a";
  ctx.font = `${12 * ratio}px Consolas, Microsoft YaHei, Arial`;
  ctx.fillText(formatNumber(maxValue), 8 * ratio, top + 4 * ratio);
  ctx.fillText(formatNumber(minValue), 8 * ratio, top + plotHeight);
}

function definedControlRows(blockName, snapshot = state.snapshot || {}) {
  const block = definitionBlocks("control", snapshot)?.[blockName];
  const headers = Array.isArray(block?.headers) ? block.headers : [];
  return (block?.rows || []).map((row, index) => {
    const raw = {};
    headers.forEach((header) => {
      raw[header] = row?.[header] ?? "";
    });
    return {
      ...raw,
      dev_type: raw.dev_type ?? row?.dev_type ?? "",
      dev_name: raw.dev_name ?? raw.name ?? row?.dev_name ?? row?.name ?? "",
      idx: raw.idx ?? row?.idx ?? index + 1,
      __headers: headers,
      __control_block: blockName,
      __definition_index: index,
    };
  }).filter((row) => row.dev_type && row.dev_name);
}

function snapshotDevice(devType, devName, snapshot = state.snapshot || {}) {
  return (snapshot.devices || []).find((dev) => deviceType(dev) === devType && deviceName(dev) === devName) || null;
}

function remoteControlMeasuredValue(devType, devName, commandType, snapshot = state.snapshot || {}) {
  const targetType = String(devType || "").trim().toUpperCase();
  const targetName = String(devName || "").trim();
  const measurementType = commandType === "status" ? "STATUS" : "RUN_STAT";
  const row = (snapshot.measurements?.scada || []).find((item) => (
    String(item?.dev_type || "").trim().toUpperCase() === targetType
    && String(item?.dev_name || "").trim() === targetName
    && String(item?.meas_type || "").trim().toUpperCase() === measurementType
  ));
  if (!row) return null;
  if (row.valid !== undefined && row.valid !== null && row.valid !== "" && Number(row.valid) === 0) return null;
  const value = Number(row.value);
  if (Number.isFinite(value)) return value > 0.5 ? 1 : 0;
  return null;
}

function remoteControlFeedbackValue(dev, commandType, snapshot = state.snapshot || {}) {
  if (!dev) return null;
  const devType = deviceType(dev);
  const devName = deviceName(dev);
  const measured = remoteControlMeasuredValue(devType, devName, commandType, snapshot);
  if (measured !== null) return measured;
  const fieldName = commandType === "status" ? "status" : "run_stat";
  const live = snapshotDevice(devType, devName, snapshot) || {};
  const rawValue = live[fieldName] ?? live.raw?.[fieldName] ?? dev[fieldName] ?? dev.raw?.[fieldName];
  if (rawValue === undefined || rawValue === null || rawValue === "") return null;
  const value = Number(rawValue);
  return Number.isFinite(value) ? (value > 0.5 ? 1 : 0) : null;
}

function remoteControlTargetAlreadyReached(dev, commandType, targetValue, snapshot = state.snapshot || {}) {
  const currentValue = remoteControlFeedbackValue(dev, commandType, snapshot);
  return currentValue !== null && currentValue === (Number(targetValue) ? 1 : 0);
}

function controlDeviceFromRow(row, snapshot = state.snapshot || {}) {
  const live = snapshotDevice(row.dev_type, row.dev_name, snapshot) || {};
  const measuredRunStat = remoteControlMeasuredValue(row.dev_type, row.dev_name, "run_stat", snapshot);
  const measuredStatus = remoteControlMeasuredValue(row.dev_type, row.dev_name, "status", snapshot);
  return {
    ...live,
    dev_type: row.dev_type,
    dev_name: row.dev_name,
    idx: live.idx ?? live.raw?.idx ?? row.idx ?? "",
    run_stat: measuredRunStat ?? live.run_stat ?? row.run_stat ?? 1,
    status: measuredStatus ?? live.status ?? row.status ?? 1,
    mode: live.mode ?? live.raw?.control_type ?? live.raw?.ctrl_mode ?? "",
    set_values: live.set_values || {},
    raw: live.raw || {},
  };
}

function controlDefinitionDevices(snapshot = state.snapshot || {}) {
  const rows = [
    ...definedControlRows("RunStat", snapshot),
    ...definedControlRows("CbOpenStat", snapshot),
    ...definedControlRows("SetValue", snapshot),
  ];
  const devices = new Map();
  rows.forEach((row) => {
    const key = `${row.dev_type}|${row.dev_name}`;
    const device = devices.get(key) || controlDeviceFromRow(row, snapshot);
    device.__control_rows = device.__control_rows || [];
    device.__control_rows.push(row);
    if (row.__control_block === "RunStat") device.run_stat = device.run_stat ?? row.run_stat;
    if (row.__control_block === "CbOpenStat") {
      device.status = device.closed_status_set
        ?? row.closed_status_set
        ?? device.status
        ?? row.status;
    }
    if (row.__control_block === "SetValue" && row.set_type) {
      device.set_values = { ...(device.set_values || {}) };
      if (device.set_values[row.set_type] === undefined) device.set_values[row.set_type] = row.set_value;
    }
    devices.set(key, device);
  });
  return Array.from(devices.values());
}

function selectedControlRows(blockName, devices, snapshot = state.snapshot || {}) {
  const selectedKeys = new Set((devices || []).map((dev) => deviceKey(dev)));
  return definedControlRows(blockName, snapshot).filter((row) => selectedKeys.has(`${row.dev_type}|${row.dev_name}`));
}

function commandEntryMatchesControl(entry, dev, commandType, setType = "") {
  if (!entry || !dev) return false;
  if (commandType === "set_value") {
    const items = entry.normalized?.set_values || entry.payload?.set_values || [];
    return items.some((item) => (
      item.dev_type === deviceType(dev)
      && item.dev_name === deviceName(dev)
      && item.set_type === setType
    ));
  }
  const items = entry.normalized?.run_status || entry.payload?.run_status || [];
  return items.some((item) => (
    item.dev_type === deviceType(dev)
    && item.dev_name === deviceName(dev)
    && (commandType === "status"
      ? Object.prototype.hasOwnProperty.call(item, "status")
      : item.run_stat !== undefined && item.run_stat !== "")
  ));
}

function activeCommandEntryForControl(
  dev,
  commandType,
  setType = "",
  snapshot = state.snapshot || {},
  origin = "effective",
) {
  const entries = origin === "manual"
    ? allActiveCommandHistory(snapshot)
    : origin === "display"
      ? displayedCommandHistory(snapshot)
      : activeCommandHistory(snapshot);
  return [...entries].reverse().find((entry) => (
    (origin !== "manual" || commandOrigin(entry) === "manual")
    && commandEntryMatchesControl(entry, dev, commandType, setType)
  )) || null;
}

function emptyIssuedCommandInfo() {
  return {
    wall_time: "--",
    simu_time: "--",
    source: "",
    command_origin: "",
    origin_text: "--",
    process_state: "inactive",
    process_text: "未下发",
  };
}

function remoteControlIssuedTimeInfo(dev, commandType = "run_stat", snapshot = state.snapshot || {}) {
  const entry = activeCommandEntryForControl(dev, commandType, "", snapshot, "display");
  return entry ? commandSentTimeInfo(entry, snapshot) : emptyIssuedCommandInfo();
}

function commandEntryControlValue(entry, dev, commandType, setType = "") {
  if (!entry || !dev) return undefined;
  if (commandType === "set_value") {
    const items = entry.normalized?.set_values || entry.payload?.set_values || [];
    const match = items.find((item) => (
      item.dev_type === deviceType(dev)
      && item.dev_name === deviceName(dev)
      && item.set_type === setType
    ));
    return match?.set_value;
  }
  const items = entry.normalized?.run_status || entry.payload?.run_status || [];
  const match = items.find((item) => (
    item.dev_type === deviceType(dev)
    && item.dev_name === deviceName(dev)
    && (commandType === "status"
      ? Object.prototype.hasOwnProperty.call(item, "status")
      : item.run_stat !== undefined && item.run_stat !== "")
  ));
  return commandType === "status" ? match?.status : match?.run_stat;
}

function remoteControlIssuedAt(dev, commandType = "run_stat", snapshot = state.snapshot || {}) {
  return remoteControlIssuedTimeInfo(dev, commandType, snapshot).wall_time;
}

function remoteControlValueText(commandType, value) {
  if (commandType === "status") return Number(value) ? "闭合" : "断开";
  return statusText(value);
}

function remoteControlLabel(commandType) {
  return commandType === "status" ? "开关开合" : "设备投退";
}

function activeCommandCancelName(
  dev,
  commandType,
  setType = "",
  snapshot = state.snapshot || {},
  issuedTime = null,
  origin = "manual",
) {
  if (!dev) return "";
  const fieldName = commandType === "set_value" ? setType : (commandType === "status" ? "status" : "run_stat");
  if (!fieldName) return "";
  const entry = activeCommandEntryForControl(dev, commandType, setType, snapshot, origin);
  if (!entry) return "";
  return `${deviceType(dev)}.${deviceName(dev)}.${fieldName}`;
}

async function sendCommandCancel(commandName, label = "", origin = "manual") {
  const name = String(commandName || "").trim();
  const normalizedOrigin = origin === "automatic" ? "automatic" : "manual";
  const sendingKey = `${normalizedOrigin}|${name}`;
  if (!name || state.commandCancelSending.has(sendingKey)) return;
  const displayLabel = label || name;
  const actionLabel = normalizedOrigin === "manual" ? "退出人工指令" : "取消自动指令";
  const confirmed = await confirmDangerousAction({
    title: `确认${actionLabel}？`,
    target: displayLabel,
    message: `执行后将向模拟台下发取消请求，${displayLabel}将不再保持当前控制设定。`,
    confirmLabel: `确认${actionLabel}`,
  });
  if (!confirmed) return;
  const body = withCommandSendTime({
    source: "trainee-ui",
    command_origin: origin,
    cancel_commands: [{ name: commandName }],
  });
  const useInteractionLink = hasTeacherCommandConnection();
  const targetName = useInteractionLink ? teacherCommandTargetName() : "模拟台交互链接";
  state.commandCancelSending.add(sendingKey);
  addRuntimeLog("人工退出", targetName, "退出请求", `${displayLabel}；范围 ${commandOriginLabel(normalizedOrigin)}`);
  renderCombinedControlPage();
  try {
    const result = await postTeacherCommand(body);
    const cancelled = result.cancelled || result;
    const count = Number(cancelled.remote_controls || 0) + Number(cancelled.remote_adjustments || 0);
    addRuntimeLog(
      "模拟台响应",
      targetName,
      count ? "退出成功" : "无可退出指令",
      `${displayLabel}；退出 ${count} 条，缺失 ${cancelled.missing || 0} 条`,
      count ? "ok" : "warn",
    );
    await refresh();
  } catch (error) {
    addRuntimeLog("模拟台响应", targetName, "退出失败", apiErrorText(error), "error");
  } finally {
    state.commandCancelSending.delete(sendingKey);
    renderCombinedControlPage();
  }
}

function remoteControlCommandRows(devices, snapshot = state.snapshot || {}) {
  return [
    ...selectedControlRows("RunStat", devices, snapshot).map((row) => ({
      definition: row,
      dev: controlDeviceFromRow(row, snapshot),
      commandType: "run_stat",
      valueKey: "run_stat",
      typeLabel: remoteControlLabel("run_stat"),
    })),
    ...selectedControlRows("CbOpenStat", devices, snapshot).map((row) => ({
      definition: row,
      dev: controlDeviceFromRow(row, snapshot),
      commandType: "status",
      valueKey: "status",
      typeLabel: remoteControlLabel("status"),
    })),
  ].map((row) => {
    const issuedEntry = activeCommandEntryForControl(
      row.dev,
      row.commandType,
      "",
      snapshot,
      "display",
    );
    const issuedTime = remoteControlIssuedTimeInfo(row.dev, row.commandType, snapshot);
    const cancelName = activeCommandCancelName(row.dev, row.commandType, "", snapshot, issuedTime, "manual");
    return {
      ...row,
      key: `${deviceKey(row.dev)}|${row.commandType}`,
      traceKey: commandTraceRunKey(row.dev, row.commandType),
      name: `${deviceType(row.dev)}.${deviceName(row.dev)}.${remoteControlLabel(row.commandType)}`,
      category: "遥控",
      issuedTime,
      commandOrigin: issuedTime.command_origin,
      commandOriginText: issuedTime.origin_text,
      commandValue: commandEntryControlValue(issuedEntry, row.dev, row.commandType),
      cancelName,
      active: issuedTime.wall_time !== "--",
    };
  });
  drawRenewableTrendChart();
}

function commandTableTypeLabel(row) {
  if (row?.typeLabel) return row.typeLabel;
  if (row?.commandType) return remoteControlLabel(row.commandType);
  if (row?.setType) return remoteAdjustmentTypeLabel(row.setType);
  return row?.category || "";
}

function commandTableRowOrigin(row) {
  const origin = String(row?.commandOrigin || row?.issuedTime?.command_origin || "").trim().toLowerCase();
  return ["manual", "automatic"].includes(origin) ? origin : "";
}

function commandTableName(row) {
  if (row?.name) return row.name;
  if (row?.commandType) return `${deviceType(row.dev)}.${deviceName(row.dev)}.${remoteControlLabel(row.commandType)}`;
  if (row?.setType) return remoteAdjustmentName(row.dev, row.setType);
  return "";
}

function commandTableFilterFields(row) {
  return [
    commandTableName(row),
    commandTableTypeLabel(row),
    row?.category,
    row?.commandType,
    row?.setType,
    row?.key,
    row?.traceKey,
    row?.definition?.idx,
    deviceType(row?.dev || {}),
    deviceName(row?.dev || {}),
  ];
}

function syncCommandTypeFilter(rows) {
  syncTableKeywordFilter("commandKeywordFilter", state.commandKeywordFilter);
  syncTableTypeFilter(
    "commandTypeFilter",
    "commandTypeFilter",
    tableFilterTypeOptions(rows, commandTableTypeLabel),
  );
  const originSelect = $("commandOriginFilter");
  if (originSelect) originSelect.value = state.commandOriginFilter || "all";
}

function applyCommandTableFilters(rows) {
  const keyword = state.commandKeywordFilter || "";
  const type = state.commandTypeFilter || "all";
  const origin = state.commandOriginFilter || "all";
  return (rows || []).filter((row) => {
    if (state.commandOnlyActive && !row.active) return false;
    if (!tableFilterMatchesKeyword(commandTableFilterFields(row), keyword)) return false;
    if (type !== "all" && commandTableTypeLabel(row) !== type) return false;
    if (origin !== "all" && commandTableRowOrigin(row) !== origin) return false;
    return true;
  });
}

function syncCommandOnlyActiveControl() {
  const input = $("commandOnlyActive");
  const text = $("commandOnlyActiveText");
  if (input) input.checked = Boolean(state.commandOnlyActive);
  if (text) text.textContent = state.commandOnlyActive ? "是" : "否";
}

function traineeCommandTraceKey(row) {
  return String(row?.traceKey || row?.key || "");
}

function traineeCommandColumnCount(activeTab) {
  return activeTab === "remote-adjustment" ? 8 : 11;
}

function traineeCommandTableStructureKey(rows, activeTab = state.activeControlTab) {
  const filter = state.controlFilter || { dev_type: "all", dev_name: "" };
  return [
    activeTab,
    deviceTreeFilterSelection(filter).map((item) => deviceTreeFilterKey(item.dev_type, item.dev_name)).join("|"),
    state.commandKeywordFilter || "",
    state.commandTypeFilter || "all",
    state.commandOriginFilter || "all",
    state.commandOnlyActive ? "active" : "all",
    rows.map((row) => traineeCommandTraceKey(row)).join("||"),
  ].join("::");
}

function traineeCommandCancelButtonHtml(cancelName, cancelLabel, origin = "manual") {
  const sendingKey = `${origin}|${cancelName}`;
  const sending = cancelName && state.commandCancelSending.has(sendingKey);
  return `
    <button type="button" class="command-cancel-button" data-command-cancel-name="${escapeHtml(cancelName)}" data-command-cancel-label="${escapeHtml(cancelLabel)}" data-command-cancel-origin="${escapeHtml(origin)}" ${cancelName && !sending ? "" : "disabled"}>
      ${sending ? "退出中" : "退出人工"}
    </button>
  `;
}

function traineeRemoteControlLiveValue(row, field) {
  const key = `${deviceKey(row.dev)}|${row.commandType}`;
  if (field === "status") {
    return `<span class="status-pill ${Number(row.dev[row.valueKey]) ? "is-ok" : "is-off"}">${remoteControlValueText(row.commandType, row.dev[row.valueKey])}</span>`;
  }
  if (field === "control") {
    const pendingCommand = pending.run_status.get(key);
    const currentValue = Number(
      pendingCommand
        ? pendingCommand[row.valueKey]
        : row.commandValue ?? row.dev[row.valueKey],
    );
    return `
      <label class="inline-toggle">
        <input type="checkbox" data-run-key="${escapeHtml(key)}" data-command-type="${escapeHtml(row.commandType)}" ${currentValue ? "checked" : ""} />
        <span>${remoteControlValueText(row.commandType, currentValue)}</span>
      </label>
    `;
  }
  if (field === "wall_time") return escapeHtml(row.issuedTime?.wall_time || "--");
  if (field === "simu_time") return escapeHtml(row.issuedTime?.simu_time || "--");
  if (field === "origin") return escapeHtml(row.commandOriginText || "--");
  if (field === "process") {
    const processState = row.issuedTime?.process_state || "inactive";
    const processText = row.issuedTime?.process_text || "未下发";
    return `<span class="command-process-pill is-${escapeHtml(processState)}">${escapeHtml(processText)}</span>`;
  }
  if (field === "cancel") {
    return traineeCommandCancelButtonHtml(
      row.cancelName || "",
      row.name,
    );
  }
  return "";
}

function traineeRemoteAdjustmentLiveValue(row, field) {
  if (field === "measurement") return escapeHtml(formatRemoteAdjustmentValue(row.measurement));
  if (field === "control") return escapeHtml(formatRemoteAdjustmentValue(row.controlValue));
  if (field === "wall_time") return escapeHtml(row.issuedTime?.wall_time || row.issuedAt || "--");
  if (field === "simu_time") return escapeHtml(row.issuedTime?.simu_time || "--");
  if (field === "origin") return escapeHtml(row.commandOriginText || "--");
  if (field === "process") {
    const processState = row.issuedTime?.process_state || "inactive";
    const processText = row.issuedTime?.process_text || "未下发";
    return `<span class="command-process-pill is-${escapeHtml(processState)}">${escapeHtml(processText)}</span>`;
  }
  if (field === "cancel") return traineeCommandCancelButtonHtml(row.cancelName, row.name);
  return "";
}

function traineeCommandLiveCellHtml(row, field, activeTab = state.activeControlTab) {
  return activeTab === "remote-adjustment"
    ? traineeRemoteAdjustmentLiveValue(row, field)
    : traineeRemoteControlLiveValue(row, field);
}

function updateTraineeCommandTableLiveCells(container, rows, activeTab = state.activeControlTab) {
  const tableRows = Array.from(container?.querySelectorAll?.("[data-trainee-command-row-key]") || []);
  if (tableRows.length !== rows.length) return false;
  const rowsByKey = new Map(rows.map((row) => [traineeCommandTraceKey(row), row]));
  for (const tableRow of tableRows) {
    const key = tableRow.dataset.traineeCommandRowKey || "";
    const row = rowsByKey.get(key);
    if (!row) return false;
    tableRow.classList.toggle("is-selected", key === state.selectedCommandTraceKey);
    tableRow.dataset.commandTraceLabel = row.name || "";
    tableRow.querySelectorAll("[data-trainee-command-live-field]").forEach((cell) => {
      cell.innerHTML = traineeCommandLiveCellHtml(row, cell.dataset.traineeCommandLiveField || "", activeTab);
    });
  }
  return true;
}

function renderTraineeCommandRows(rows, activeTab = state.activeControlTab) {
  if (activeTab === "remote-adjustment") {
    return rows.map((row) => `<tr class="${row.traceKey === state.selectedCommandTraceKey ? "is-selected" : ""}" data-trainee-command-row-key="${escapeHtml(row.traceKey)}" data-command-trace-key="${escapeHtml(row.traceKey)}" data-command-trace-label="${escapeHtml(row.name)}" data-remote-adjustment-key="${escapeHtml(row.key)}" title="单击选中曲线，双击进行遥调操作">
      <td><span class="remote-adjustment-name-cell"><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(deviceType(row.dev))}</small></span></td>
      <td class="numeric-cell" data-trainee-command-live-field="measurement">${traineeCommandLiveCellHtml(row, "measurement", activeTab)}</td>
      <td class="numeric-cell" data-trainee-command-live-field="control">${traineeCommandLiveCellHtml(row, "control", activeTab)}</td>
      <td data-trainee-command-live-field="origin">${traineeCommandLiveCellHtml(row, "origin", activeTab)}</td>
      <td data-trainee-command-live-field="process">${traineeCommandLiveCellHtml(row, "process", activeTab)}</td>
      <td class="mono-cell command-issued-at-cell" data-trainee-command-live-field="wall_time">${traineeCommandLiveCellHtml(row, "wall_time", activeTab)}</td>
      <td class="mono-cell command-issued-at-cell" data-trainee-command-live-field="simu_time">${traineeCommandLiveCellHtml(row, "simu_time", activeTab)}</td>
      <td data-trainee-command-live-field="cancel">${traineeCommandLiveCellHtml(row, "cancel", activeTab)}</td>
    </tr>`).join("");
  }
  return rows.map((row) => {
    const key = `${deviceKey(row.dev)}|${row.commandType}`;
    const traceKey = commandTraceRunKey(row.dev, row.commandType);
    const classes = [
      pending.run_status.has(key) ? "is-pending" : "",
      traceKey === state.selectedCommandTraceKey ? "is-selected" : "",
    ].filter(Boolean).join(" ");
    return `<tr class="${classes}" data-trainee-command-row-key="${escapeHtml(traceKey)}" data-command-trace-key="${escapeHtml(traceKey)}" data-command-trace-label="${escapeHtml(row.name)}" data-run-status-command="${escapeHtml(key)}" title="单击选中曲线，双击进行遥控操作">
      <td>${escapeHtml(deviceIndex(row.dev))}</td>
      <td>${escapeHtml(row.name)}</td>
      <td>${escapeHtml(deviceName(row.dev))}</td>
      <td>${escapeHtml(deviceType(row.dev))}</td>
      <td class="run-status-command-cell" title="双击进行遥控操作" data-trainee-command-live-field="status">${traineeCommandLiveCellHtml(row, "status", activeTab)}</td>
      <td data-trainee-command-live-field="control">${traineeCommandLiveCellHtml(row, "control", activeTab)}</td>
      <td data-trainee-command-live-field="origin">${traineeCommandLiveCellHtml(row, "origin", activeTab)}</td>
      <td data-trainee-command-live-field="process">${traineeCommandLiveCellHtml(row, "process", activeTab)}</td>
      <td class="mono-cell command-issued-at-cell" data-trainee-command-live-field="wall_time">${traineeCommandLiveCellHtml(row, "wall_time", activeTab)}</td>
      <td class="mono-cell command-issued-at-cell" data-trainee-command-live-field="simu_time">${traineeCommandLiveCellHtml(row, "simu_time", activeTab)}</td>
      <td data-trainee-command-live-field="cancel">${traineeCommandLiveCellHtml(row, "cancel", activeTab)}</td>
    </tr>`;
  }).join("");
}

function renderTraineeCommandTable(rows, activeTab, emptyText, virtualRows = { beforeHeight: 0, afterHeight: 0 }) {
  if (!rows.length) return `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
  const columnCount = traineeCommandColumnCount(activeTab);
  if (activeTab === "remote-adjustment") {
    return `
      <table class="runtime-device-table remote-adjustment-table">
        <colgroup>
          <col class="remote-adjustment-name-col" />
          <col class="remote-adjustment-value-col" />
          <col class="remote-adjustment-value-col" />
          <col class="remote-adjustment-origin-col" />
          <col class="remote-adjustment-origin-col" />
          <col class="remote-adjustment-time-col" />
          <col class="remote-adjustment-time-col" />
          <col class="remote-adjustment-action-col" />
        </colgroup>
        <thead><tr><th>遥调名称</th><th>量测值</th><th>控制值</th><th>指令来源</th><th>处理状态</th><th>下发本机时刻</th><th>下发仿真时刻</th><th>操作</th></tr></thead>
        <tbody>
          ${renderVirtualSpacerRow(virtualRows.beforeHeight, columnCount)}
          ${renderTraineeCommandRows(rows, activeTab)}
          ${renderVirtualSpacerRow(virtualRows.afterHeight, columnCount)}
        </tbody>
      </table>`;
  }
  return `
    <table class="runtime-device-table">
      <thead><tr><th>idx</th><th>遥控名称</th><th>设备名称</th><th>类型</th><th>当前状态</th><th>下发状态</th><th>指令来源</th><th>处理状态</th><th>下发本机时刻</th><th>下发仿真时刻</th><th>操作</th></tr></thead>
      <tbody>
        ${renderVirtualSpacerRow(virtualRows.beforeHeight, columnCount)}
        ${renderTraineeCommandRows(rows, activeTab)}
        ${renderVirtualSpacerRow(virtualRows.afterHeight, columnCount)}
      </tbody>
    </table>`;
}

function renderTraineeCommandTableContainer(container, activeTab, rows, allRows, emptyText) {
  if (!container) return;
  const key = `traineeCommand:${activeTab}`;
  const activeRows = rows;
  const virtualRows = virtualTableWindow(`traineeCommand:${activeTab}`, activeRows);
  const structureKey = [
    traineeCommandTableStructureKey(activeRows, activeTab),
    virtualRows.enabled ? "virtual" : "full",
    virtualRows.start,
    virtualRows.end,
  ].join("|");
  container.classList.add("virtual-table-scroll");
  container.setAttribute("data-virtual-table", `traineeCommand:${activeTab}`);
  if (!rows.length) {
    container.dataset.traineeCommandStructureKey = "";
    container.innerHTML = `<div class="empty-state">${allRows.length ? escapeHtml(emptyText.filtered) : escapeHtml(emptyText.empty)}</div>`;
    return;
  }
  if (
    container.dataset.traineeCommandStructureKey === structureKey
    && updateTraineeCommandTableLiveCells(container, virtualRows.rows, activeTab)
  ) {
    return;
  }
  container.dataset.traineeCommandStructureKey = structureKey;
  container.innerHTML = renderTraineeCommandTable(virtualRows.rows, activeTab, allRows.length ? emptyText.filtered : emptyText.empty, virtualRows);
  restoreVirtualTableScroll(container, key);
}

function renderRunControls(devices, options = {}) {
  const visibleDevices = filteredDevices(devices, state.controlFilter);
  const allRows = options.rows || remoteControlCommandRows(visibleDevices);
  const rows = applyCommandTableFilters(allRows);
  renderTraineeCommandTableContainer($("runControlTable"), "remote-control", rows, allRows, {
    filtered: "当前过滤无遥控指令",
    empty: "当前筛选无遥控指令",
  });
}

function effectiveRemoteAdjustmentValue(dev, setType, snapshot = state.snapshot || {}) {
  const entry = activeCommandEntryForControl(dev, "set_value", setType, snapshot);
  if (!entry) return undefined;
  const items = entry.normalized?.set_values
    || entry.payload?.set_values
    || entry.payload?.setValues
    || entry.payload?.setpoints
    || [];
  const match = items.find((item) => (
    item?.dev_type === deviceType(dev)
    && item?.dev_name === deviceName(dev)
    && item?.set_type === setType
  ));
  if (!match) return undefined;
  const value = match.set_value ?? match.value;
  return value === "" || value === undefined || value === null ? undefined : value;
}

function converterUsesDcPowerSetpoint(dev) {
  const raw = dev?.raw || {};
  const acControlType = String(raw.ac_control_type ?? dev?.ac_control_type ?? "").trim().toUpperCase();
  const dcControlType = String(raw.dc_control_type ?? dev?.dc_control_type ?? "").trim().toUpperCase();
  return dcControlType === "P"
    || (dcControlType === "NONE" && (!acControlType || acControlType === "NONE"));
}

function currentSetValue(dev, setType, snapshot = state.snapshot || {}) {
  const key = `${deviceKey(dev)}|${setType}`;
  if (pending.set_values.has(key)) return pending.set_values.get(key).set_value;
  const effective = effectiveRemoteAdjustmentValue(dev, setType, snapshot);
  if (effective !== undefined) return effective;
  const exact = dev.set_values?.[setType];
  if (exact !== undefined) return exact;
  const raw = dev.raw || {};
  if (setType === "p_set") {
    const dcPriority = converterUsesDcPowerSetpoint(dev);
    return dev.set_values?.p_set
      ?? (dcPriority ? dev.set_values?.p_dc_set : dev.set_values?.p_ac_set)
      ?? (dcPriority ? raw.p_dc_set : raw.p_ac_set)
      ?? raw.p_set
      ?? raw.pv0
      ?? "";
  }
  if (raw[setType] !== undefined) return raw[setType];
  if (setType === "q_set") return raw.q_set ?? raw.q_ac_set ?? raw.qv0 ?? "";
  if (setType === "v_set") return raw.v_set ?? raw.v_ac_set ?? "";
  return "";
}

function remoteAdjustmentTypeLabel(setType) {
  return {
    p_set: "P有功设定",
    p_ac_set: "ACP有功设定",
    p_dc_set: "DCP有功设定",
    q_set: "Q无功设定",
    v_set: "V电压设定",
    flow_set: "气流量设定",
  }[setType] || setType;
}

function remoteAdjustmentName(dev, setType) {
  return `${deviceType(dev)}.${deviceName(dev)}.${remoteAdjustmentTypeLabel(setType)}`;
}

function remoteAdjustmentMeasurementTypeCandidates(dev, setType) {
  const setKey = String(setType || "").trim().toLowerCase();
  if (!setKey) return [];
  const measurementKey = setKey.endsWith("_set") ? setKey.slice(0, -4) : setKey;
  const exactType = measurementKey.toUpperCase();
  const quantity = measurementKey.split("_", 1)[0].toUpperCase();
  const family = String(dev?.device_family || "").trim().toLowerCase();
  const domains = new Set((Array.isArray(dev?.terminal_domains) ? dev.terminal_domains : [])
    .map((value) => String(value || "").trim().toUpperCase())
    .filter(Boolean));
  const candidates = [];
  const add = (...types) => types.forEach((type) => {
    const normalized = String(type || "").trim().toUpperCase();
    if (normalized && !candidates.includes(normalized)) candidates.push(normalized);
  });

  if (measurementKey.includes("_")) {
    add(exactType);
    return candidates;
  }
  if (measurementKey.includes("soc")) add("SOC");
  if (family === "generator") {
    add(`${quantity}_GEN`);
  } else if (family === "load") {
    add(`${quantity}_LOAD`);
  } else if (family === "converter" && domains.has("AC") && domains.has("DC")) {
    add(`${quantity}_AC`, `${quantity}_DC`);
  } else if (family === "converter") {
    add(`${quantity}_FROM`, `${quantity}_TO`);
  } else {
    add(
      `${quantity}_GEN`,
      `${quantity}_LOAD`,
      `${quantity}_AC`,
      `${quantity}_DC`,
      `${quantity}_FROM`,
      `${quantity}_TO`,
    );
  }
  add(exactType, quantity);
  return candidates;
}

function remoteAdjustmentMeasTypeMatchesSetType(measType, setType, dev = null) {
  const type = String(measType || "").toUpperCase();
  const setKey = String(setType || "").trim().toUpperCase();
  if (!type || !setKey) return false;
  if (!setKey.endsWith("_SET")) return type === setKey;
  return remoteAdjustmentMeasurementTypeCandidates(dev, setType).includes(type);
}

function remoteAdjustmentMeasurementRowIsValid(row) {
  const valid = row?.valid;
  if (valid === undefined || valid === null || valid === "") return true;
  const numeric = Number(valid);
  return !Number.isFinite(numeric) || numeric !== 0;
}

function remoteAdjustmentDeviceTypeKey(value) {
  const type = String(value || "").trim().toUpperCase();
  return type === "ACDCCONVERTER" ? "DCACCONVERTER" : type;
}

function remoteAdjustmentMeasurement(dev, setType, snapshot = state.snapshot || {}) {
  const targetType = remoteAdjustmentDeviceTypeKey(deviceType(dev));
  const targetName = String(deviceName(dev) || "").trim();
  const measurements = snapshot.measurements || {};
  const candidates = remoteAdjustmentMeasurementTypeCandidates(dev, setType);
  for (const candidate of candidates) {
    const match = (measurements.scada || []).find((row) => (
      remoteAdjustmentDeviceTypeKey(row?.dev_type) === targetType
      && String(row?.dev_name || "").trim() === targetName
      && remoteAdjustmentMeasTypeMatchesSetType(row?.meas_type, candidate)
      && remoteAdjustmentMeasurementRowIsValid(row)
      && row?.value !== undefined
      && row?.value !== null
      && String(row.value).trim() !== ""
      && Number.isFinite(Number(row.value))
    ));
    if (match) return Number(match.value);
  }
  return null;
}

function remoteAdjustmentIssuedTimeInfo(dev, setType, snapshot = state.snapshot || {}) {
  const entry = activeCommandEntryForControl(dev, "set_value", setType, snapshot, "display");
  return entry ? commandSentTimeInfo(entry, snapshot) : emptyIssuedCommandInfo();
}

function remoteAdjustmentIssuedAt(dev, setType, snapshot = state.snapshot || {}) {
  return remoteAdjustmentIssuedTimeInfo(dev, setType, snapshot).wall_time;
}

function remoteAdjustmentRows(devices, snapshot = state.snapshot || {}, options = {}) {
  return selectedControlRows("SetValue", devices, snapshot).map((definitionRow) => {
    const dev = controlDeviceFromRow(definitionRow, snapshot);
    const setType = definitionRow.set_type || "";
    const issuedTime = remoteAdjustmentIssuedTimeInfo(dev, setType, snapshot);
    const issuedEntry = activeCommandEntryForControl(
      dev,
      "set_value",
      setType,
      snapshot,
      "display",
    );
    const issuedCommandValue = commandEntryControlValue(
      issuedEntry,
      dev,
      "set_value",
      setType,
    );
    const cancelName = activeCommandCancelName(dev, "set_value", setType, snapshot, issuedTime, "manual");
    return {
      key: `${deviceKey(dev)}|${setType}`,
      traceKey: commandTraceAdjustmentKey(dev, setType),
      dev,
      setType,
      name: remoteAdjustmentName(dev, setType),
      typeLabel: remoteAdjustmentTypeLabel(setType),
      category: "遥调",
      measurement: options.includeMeasurements === false ? null : remoteAdjustmentMeasurement(dev, setType, snapshot),
      controlValue: (() => {
        if (issuedCommandValue !== undefined && issuedCommandValue !== null && issuedCommandValue !== "") {
          return issuedCommandValue;
        }
        const current = currentSetValue(dev, setType, snapshot);
        return current === "" || current === undefined || current === null ? definitionRow.set_value : current;
      })(),
      issuedAt: issuedTime.wall_time,
      issuedTime,
      commandOrigin: issuedTime.command_origin,
      commandOriginText: issuedTime.origin_text,
      cancelName,
      active: issuedTime.wall_time !== "--",
      cancelSending: state.commandCancelSending.has(`manual|${cancelName}`),
    };
  });
}

function formatRemoteAdjustmentValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  return formatNumber(value);
}

function renderSetpointControls(devices, options = {}) {
  const visibleDevices = filteredDevices(devices || [], state.controlFilter);
  const allRows = options.rows || remoteAdjustmentRows(visibleDevices);
  const rows = applyCommandTableFilters(allRows);
  renderTraineeCommandTableContainer($("setpointControlTable"), "remote-adjustment", rows, allRows, {
    filtered: "当前过滤无遥调指令",
    empty: "当前筛选无遥调指令",
  });
}

function commandTraceRowsForActiveTab(devices = controlDefinitionDevices()) {
  const visibleDevices = filteredDevices(devices || [], state.controlFilter);
  if (state.activeControlTab === "remote-adjustment") {
    return applyCommandTableFilters(remoteAdjustmentRows(visibleDevices)).map((row) => ({
      key: row.traceKey,
      label: row.name,
    }));
  }
  return applyCommandTableFilters(remoteControlCommandRows(visibleDevices)).map((row) => ({
    key: row.traceKey,
    label: row.name,
  }));
}

function ensureSelectedCommandTrace(devices = controlDefinitionDevices()) {
  const rows = commandTraceRowsForActiveTab(devices);
  if (!rows.length) {
    state.selectedCommandTraceKey = "";
    state.selectedCommandTraceLabel = "";
    return;
  }
  if (!rows.some((row) => row.key === state.selectedCommandTraceKey)) {
    state.selectedCommandTraceKey = rows[0].key;
    state.selectedCommandTraceLabel = rows[0].label;
  } else {
    const selected = rows.find((row) => row.key === state.selectedCommandTraceKey);
    state.selectedCommandTraceLabel = selected?.label || state.selectedCommandTraceLabel;
  }
}

function renderControlTabs() {
  document.querySelectorAll("[data-command-tab]").forEach((button) => {
    const isActive = button.dataset.commandTab === state.activeControlTab;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", isActive ? "true" : "false");
  });
  document.querySelectorAll("[data-command-tab-page]").forEach((page) => {
    page.classList.toggle("is-active", page.dataset.commandTabPage === state.activeControlTab);
  });
}

function renderCombinedControlPage(devices = controlDefinitionDevices()) {
  syncCommandOnlyActiveControl();
  renderDeviceTree("commandDeviceTree", "commandTreeSummary", devices, state.controlFilter, "control", "control");
  const visibleDevices = filteredDevices(devices || [], state.controlFilter);
  const activeTab = state.activeControlTab === "remote-adjustment" ? "remote-adjustment" : "remote-control";
  state.activeControlTab = activeTab;
  const remoteControlRows = remoteControlCommandRows(visibleDevices);
  const remoteAdjustmentRowsForFilter = remoteAdjustmentRows(visibleDevices, state.snapshot || {}, {
    includeMeasurements: activeTab === "remote-adjustment",
  });
  const activeRows = activeTab === "remote-adjustment"
    ? remoteAdjustmentRowsForFilter
    : remoteControlRows;
  syncCommandTypeFilter([...remoteControlRows, ...remoteAdjustmentRowsForFilter]);
  ensureSelectedCommandTrace(devices);
  if (activeTab === "remote-adjustment") {
    const runContainer = $("runControlTable");
    if (runContainer) {
      runContainer.dataset.traineeCommandStructureKey = "";
      runContainer.removeAttribute("data-virtual-table");
      runContainer.innerHTML = "";
    }
    renderSetpointControls(devices, { rows: activeRows });
  } else {
    const setpointContainer = $("setpointControlTable");
    if (setpointContainer) {
      setpointContainer.dataset.traineeCommandStructureKey = "";
      setpointContainer.removeAttribute("data-virtual-table");
      setpointContainer.innerHTML = "";
    }
    renderRunControls(devices, { rows: activeRows });
  }
  renderControlTabs();
  drawCommandTraceChart();
}

function selectCommandTraceRow(commandTraceRow) {
  state.selectedCommandTraceKey = commandTraceRow.dataset.commandTraceKey || "";
  state.selectedCommandTraceLabel = commandTraceRow.dataset.commandTraceLabel || "";
  document.querySelectorAll("[data-command-trace-key]").forEach((row) => {
    row.classList.toggle("is-selected", row.dataset.commandTraceKey === state.selectedCommandTraceKey);
  });
  drawCommandTraceChart();
}

function commandHistoryKey(item) {
  const accepted = item.accepted || {};
  return [
    item.time || "",
    item.source || "",
    accepted.run_status || 0,
    accepted.set_values || 0,
    JSON.stringify(item.payload || {}).slice(0, 240),
  ].join("|");
}

function syncCommandHistoryLogs(history = []) {
  history.slice(-30).forEach((item) => {
    const key = commandHistoryKey(item);
    if (state.seenCommandHistoryKeys.has(key)) return;
    state.seenCommandHistoryKeys.add(key);
    addRuntimeLog(
      "模拟台响应",
      "模拟台命令历史",
      "记录同步",
      [
        `来源 ${item.source || "student"}`,
        `接受投退 ${item.accepted?.run_status || 0} 条`,
        `接受设值 ${item.accepted?.set_values || 0} 条`,
        `模拟台记录 ${item.time || "--"}`,
      ],
      "ok",
      false,
      runtimeLogSimTimeFromCommandHistory(item),
    );
  });
}

function runtimeLogColgroupHtml() {
  return `<colgroup>${state.runtimeLogColumnWidths.map((width) => `<col style="width:${Math.round(width)}px">`).join("")}</colgroup>`;
}

function applyRuntimeLogColumnWidths(table, widths = state.runtimeLogColumnWidths) {
  if (!table) return;
  const normalized = widths.map((value, index) => Math.max(
    RUNTIME_LOG_COLUMN_MIN_WIDTHS[index],
    Number(value) || RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS[index],
  ));
  state.runtimeLogColumnWidths = normalized;
  table.querySelectorAll("colgroup col").forEach((column, index) => {
    if (normalized[index] !== undefined) column.style.width = `${Math.round(normalized[index])}px`;
  });
  table.style.width = `${Math.round(normalized.reduce((total, width) => total + width, 0))}px`;
  table.style.minWidth = "100%";
}

function enableRuntimeLogColumnResizing(table) {
  if (!table || table.dataset.columnResizeReady === "true") return;
  table.dataset.columnResizeReady = "true";
  applyRuntimeLogColumnWidths(table);
  const headers = Array.from(table.querySelectorAll("thead th"));
  headers.forEach((header, columnIndex) => {
    const handle = document.createElement("span");
    handle.className = "table-column-resize-handle";
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", "vertical");
    handle.setAttribute("aria-label", `调整${header.textContent.trim()}列宽`);
    handle.title = "拖动调整列宽，双击恢复默认宽度";
    handle.tabIndex = 0;
    const restoreDefault = () => {
      state.runtimeLogColumnWidths[columnIndex] = RUNTIME_LOG_COLUMN_DEFAULT_WIDTHS[columnIndex];
      applyRuntimeLogColumnWidths(table);
      localStorage.setItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY, JSON.stringify(state.runtimeLogColumnWidths));
    };
    handle.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      restoreDefault();
    });
    handle.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const step = event.shiftKey ? 24 : 8;
      state.runtimeLogColumnWidths[columnIndex] = Math.max(
        RUNTIME_LOG_COLUMN_MIN_WIDTHS[columnIndex],
        state.runtimeLogColumnWidths[columnIndex] + (event.key === "ArrowRight" ? step : -step),
      );
      applyRuntimeLogColumnWidths(table);
      localStorage.setItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY, JSON.stringify(state.runtimeLogColumnWidths));
    });
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      state.runtimeLogColumnWidths = headers.map((item, index) => Math.max(
        RUNTIME_LOG_COLUMN_MIN_WIDTHS[index],
        Math.round(item.getBoundingClientRect().width),
      ));
      applyRuntimeLogColumnWidths(table);
      const startX = event.clientX;
      const startWidth = state.runtimeLogColumnWidths[columnIndex];
      document.body.classList.add("is-resizing-table-column");
      handle.setPointerCapture?.(event.pointerId);
      const move = (moveEvent) => {
        state.runtimeLogColumnWidths[columnIndex] = Math.max(
          RUNTIME_LOG_COLUMN_MIN_WIDTHS[columnIndex],
          Math.round(startWidth + moveEvent.clientX - startX),
        );
        applyRuntimeLogColumnWidths(table);
      };
      const finish = () => {
        document.body.classList.remove("is-resizing-table-column");
        localStorage.setItem(RUNTIME_LOG_COLUMN_WIDTHS_KEY, JSON.stringify(state.runtimeLogColumnWidths));
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", finish);
        window.removeEventListener("pointercancel", finish);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", finish);
      window.addEventListener("pointercancel", finish);
    });
    header.appendChild(handle);
  });
}

function exportTraineeMeasurementsCsv() {
  const snapshot = state.snapshot || {};
  const allRows = measurementRows(snapshot);
  const filteredRows = filteredMeasurements(allRows, state.measurementFilter);
  let tableFilteredRows = applyMeasurementTableFilters(filteredRows);
  if (state.measurementOnlyAbnormal) {
    tableFilteredRows = tableFilteredRows.filter(
      (item) => Number(item.valid) !== 1 || String(item.status || "normal") !== "normal",
    );
  }
  const rows = activeMeasurementRows(tableFilteredRows);
  if (!rows.length) {
    showUiToast("当前筛选下无可导出的量测数据", "warn");
    return;
  }
  const csvCell = (val) => `"${String(val ?? "").replace(/"/g, '""')}"`;
  const lines = [
    ["idx", "量测名", "设备", "类型", "量测值", "有效性", "状态"].map(csvCell).join(","),
    ...rows.map((item) => [
      item.idx ?? "",
      measurementDisplayName(item) || "",
      measurementDeviceDisplay(item),
      measurementTypeDisplay(item),
      item.scada_value ?? "",
      Number(item.valid) === 1 ? "有效" : "无效",
      item.status || "normal",
    ].map(csvCell).join(",")),
  ];
  const blob = new Blob([`\uFEFF${lines.join("\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `trainee-measurements-${state.activeModelId || "model"}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  showUiToast(`已导出 ${rows.length} 条量测记录`, "ok", 2200);
}

function renderHistory() {
  const historyCount = $("historyCount");
  const commandHistory = $("commandHistory");
  if (!historyCount || !commandHistory) return;
  syncTraineeRuntimeLogTypeFilter();
  const allLogs = filteredTraineeRuntimeLogs();
  const logs = pagedTraineeRuntimeLogs(allLogs);
  renderTraineeRuntimeLogPager(allLogs);
  const filterOn = state.runtimeLogTypeFilter !== "all"
    || Boolean(String(state.runtimeLogKeywordFilter || "").trim())
    || Boolean(state.runtimeLogOnlyAlert);
  historyCount.textContent = filterOn
    ? `${allLogs.length}/${state.runtimeLogs.length} 条`
    : `${state.runtimeLogs.length} 条`;
  const renderKey = [
    allLogs.length,
    state.runtimeLogPage,
    state.runtimeLogSelectedSeq,
    state.runtimeLogTypeFilter,
    state.runtimeLogKeywordFilter || "",
    Boolean(state.runtimeLogOnlyAlert),
    logs.map((item) => `${item.seq}:${item.level}`).join(","),
  ].join("|");
  if (commandHistory.dataset.historyRenderKey === renderKey) {
    return;
  }
  commandHistory.dataset.historyRenderKey = renderKey;
  if (!allLogs.length) {
    commandHistory.innerHTML = '<div class="empty-state">暂无运行日志</div>';
    return;
  }
  commandHistory.innerHTML = `
    <table class="runtime-log-table runtime-log-table-resizable">
      ${runtimeLogColgroupHtml()}
      <thead><tr><th>本机时刻</th><th>仿真时刻</th><th>类型</th><th>对象</th><th>结果</th><th>概要</th></tr></thead>
      <tbody>
        ${logs.map((item) => `
          <tr
            class="runtime-log-row is-${escapeHtml(item.level || "info")}${(Number(item.seq) || 0) === state.runtimeLogSelectedSeq ? " is-selected" : ""}"
            data-runtime-log-seq="${escapeHtml(item.seq)}"
            tabindex="0"
            aria-selected="${(Number(item.seq) || 0) === state.runtimeLogSelectedSeq ? "true" : "false"}"
            aria-label="日志 ${escapeHtml(item.seq)}，双击查看详细信息"
          >
            <td>${escapeHtml(runtimeLogWallTimeText(item.wall_time))}</td>
            <td class="mono-cell">${escapeHtml(item.simu_time || "--")}</td>
            <td>${escapeHtml(item.type || "")}</td>
            <td>${escapeHtml(item.target || "")}</td>
            <td>${escapeHtml(item.result || "")}</td>
            <td class="runtime-log-detail" title="双击查看详细信息">${escapeHtml(runtimeLogSummaryText(item))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
  enableRuntimeLogColumnResizing(commandHistory.querySelector(".runtime-log-table-resizable"));
}

function renderHistoryIfMounted() {
  if (!$("historyCount") || !$("commandHistory")) return;
  renderHistory();
}

function traineeRuntimeLogTypes() {
  return Array.from(new Set(state.runtimeLogs.map((item) => String(item.type || "")).filter(Boolean)))
    .sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function syncTraineeRuntimeLogTypeFilter() {
  const select = $("traineeRuntimeLogTypeFilter");
  if (!select) return;
  const types = traineeRuntimeLogTypes();
  if (state.runtimeLogTypeFilter !== "all" && !types.includes(state.runtimeLogTypeFilter)) {
    state.runtimeLogTypeFilter = "all";
  }
  const optionsKey = types.join("|");
  if (select.dataset.optionsKey !== optionsKey) {
    select.dataset.optionsKey = optionsKey;
    select.innerHTML = ["<option value=\"all\">全部类型</option>", ...types.map((type) => (
      `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`
    ))].join("");
  }
  if (select.value !== state.runtimeLogTypeFilter) {
    select.value = state.runtimeLogTypeFilter;
  }
}

function filteredTraineeRuntimeLogs() {
  const keyword = String(state.runtimeLogKeywordFilter || "").trim().toLowerCase();
  const onlyAlert = Boolean(state.runtimeLogOnlyAlert);
  return state.runtimeLogs.filter((item) => {
    if (state.runtimeLogTypeFilter !== "all" && item.type !== state.runtimeLogTypeFilter) return false;
    if (onlyAlert && !["warn", "warning", "error", "bad"].includes(String(item.level || "").toLowerCase())) {
      return false;
    }
    if (keyword) {
      const hay = `${item.type || ""} ${item.target || ""} ${item.result || ""} ${runtimeLogSummaryText(item)}`.toLowerCase();
      if (!hay.includes(keyword)) return false;
    }
    return true;
  });
}

function traineeRuntimeLogPageCount(logs = filteredTraineeRuntimeLogs()) {
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  return Math.max(1, Math.ceil((logs || []).length / pageSize));
}

function pagedTraineeRuntimeLogs(logs = filteredTraineeRuntimeLogs()) {
  const pageSize = Math.max(1, Number(state.runtimeLogPageSize) || 20);
  const pageCount = traineeRuntimeLogPageCount(logs);
  state.runtimeLogPage = Math.min(Math.max(1, Number(state.runtimeLogPage) || 1), pageCount);
  const start = (state.runtimeLogPage - 1) * pageSize;
  return logs.slice(start, start + pageSize);
}

function renderTraineeRuntimeLogPager(logs = filteredTraineeRuntimeLogs()) {
  const pager = $("traineeRuntimeLogPager");
  if (!pager) return;
  if (!logs.length) {
    pager.innerHTML = "";
    return;
  }
  const pageCount = traineeRuntimeLogPageCount(logs);
  const page = Math.min(Math.max(1, Number(state.runtimeLogPage) || 1), pageCount);
  const start = (page - 1) * state.runtimeLogPageSize + 1;
  const end = Math.min(logs.length, page * state.runtimeLogPageSize);
  pager.innerHTML = `
    <span>${start}-${end} / ${logs.length} 条</span>
    <button type="button" data-trainee-runtime-log-page="prev" ${page <= 1 ? "disabled" : ""}>上一页</button>
    <strong>第 ${page} / ${pageCount} 页</strong>
    <button type="button" data-trainee-runtime-log-page="next" ${page >= pageCount ? "disabled" : ""}>下一页</button>
  `;
}

async function clearTraineeRuntimeLogs() {
  const confirmed = await confirmDangerousAction({
    title: "清空学员台运行日志？",
    target: `当前缓存 ${state.runtimeLogs.length} 条运行日志`,
    message: "清空后当前页面缓存的运行日志将立即移除，无法恢复。",
    confirmLabel: "确认清空",
  });
  if (!confirmed) return;
  state.runtimeLogs = [];
  state.runtimeLogSeq = 0;
  state.runtimeLogSelectedSeq = 0;
  closeRuntimeLogDetailDialog();
  state.runtimeLogPage = 1;
  state.runtimeLogTypeFilter = "all";
  state.renewableControl.logPage = 1;
  state.renewableControl.lastControlLogRenderKey = "";
  renderHistoryIfMounted();
  renderRenewableControlLogs();
  showUiToast("已清空学员台运行日志", "ok");
}

function activeCommandPreviewRows(snapshot = state.snapshot || {}) {
  const rows = [];
  const seenCommandKeys = new Set();
  [...displayedCommandHistory(snapshot)].reverse().forEach((entry) => {
    const timeInfo = commandSentTimeInfo(entry, snapshot);
    const normalized = entry.normalized || {};
    const runItems = normalized.run_status || entry.payload?.run_status || [];
    const setItems = normalized.set_values || entry.payload?.set_values || [];
    runItems.forEach((item) => {
      if (!item || typeof item !== "object") return;
      const isStatus = Object.prototype.hasOwnProperty.call(item, "status");
      const commandType = isStatus ? "status" : "run_stat";
      const value = isStatus ? item.status : item.run_stat;
      if (value === undefined || value === "") return;
      const devType = String(item.dev_type || "").trim();
      const devName = String(item.dev_name || item.name || "").trim();
      if (!devType || !devName) return;
      const commandKey = ["remote_control", devType, devName, commandType].join("|");
      if (seenCommandKeys.has(commandKey)) return;
      seenCommandKeys.add(commandKey);
      const liveDev = snapshotDevice(devType, devName, snapshot) || {};
      const measuredActualValue = remoteControlMeasuredValue(devType, devName, commandType, snapshot);
      const actualValue = measuredActualValue ?? (isStatus ? liveDev.status : liveDev.run_stat);
      rows.push({
        type: `遥控 · ${remoteControlLabel(commandType)}`,
        name: devName,
        value: remoteControlValueText(commandType, value),
        actual_value: actualValue === undefined || actualValue === ""
          ? "--"
          : remoteControlValueText(commandType, actualValue),
        wall_time: timeInfo.wall_time || "--",
        time: timeInfo.simu_time || "--",
        process_state: timeInfo.process_state || "inactive",
        process_text: timeInfo.process_text || "未下发",
      });
    });
    setItems.forEach((item) => {
      if (!item || typeof item !== "object") return;
      const devType = String(item.dev_type || "").trim();
      const devName = String(item.dev_name || item.name || "").trim();
      const setType = String(item.set_type || "").trim();
      if (!devType || !devName || !setType || item.set_value === undefined || item.set_value === "") return;
      const commandKey = ["remote_adjustment", devType, devName, setType].join("|");
      if (seenCommandKeys.has(commandKey)) return;
      seenCommandKeys.add(commandKey);
      const liveDev = snapshotDevice(devType, devName, snapshot)
        || { dev_type: devType, dev_name: devName };
      const actualValue = remoteAdjustmentMeasurement(liveDev, setType, snapshot);
      rows.push({
        type: `遥调 · ${remoteAdjustmentTypeLabel(setType)}`,
        name: devName,
        value: formatNumber(item.set_value),
        actual_value: formatRemoteAdjustmentValue(actualValue),
        wall_time: timeInfo.wall_time || "--",
        time: timeInfo.simu_time || "--",
        process_state: timeInfo.process_state || "inactive",
        process_text: timeInfo.process_text || "未下发",
      });
    });
  });
  return rows;
}

function renderActiveCommandPreview(snapshot = state.snapshot || {}) {
  const pendingSummary = $("pendingSummary");
  const pendingPreview = $("pendingPreview");
  if (!pendingSummary || !pendingPreview) return;
  const rows = activeCommandPreviewRows(snapshot);
  pendingSummary.textContent = `${rows.length} 项`;
  pendingPreview.innerHTML = rows.length ? `
    <table class="active-command-preview-table">
      <thead>
        <tr>
          <th>下发本机时刻</th>
          <th>设备</th>
          <th>指令</th>
          <th>指令值</th>
          <th>实时值</th>
          <th>处理状态</th>
          <th>仿真时刻</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((item) => `
          <tr>
            <td title="${escapeHtml(item.wall_time)}">${escapeHtml(item.wall_time)}</td>
            <td title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</td>
            <td title="${escapeHtml(item.type)}">${escapeHtml(item.type)}</td>
            <td title="${escapeHtml(item.value)}">${escapeHtml(item.value)}</td>
            <td title="${escapeHtml(item.actual_value)}">${escapeHtml(item.actual_value)}</td>
            <td><span class="command-process-pill is-${escapeHtml(item.process_state)}">${escapeHtml(item.process_text)}</span></td>
            <td title="${escapeHtml(item.time)}">${escapeHtml(item.time)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  ` : '<div class="empty-state compact">暂无当前有效或排队指令</div>';
}

function updatePendingCount() {
  const total = pending.run_status.size + pending.set_values.size;
  setOptionalText("pendingCount", total);
  setOptionalText("runPendingCount", `${pending.run_status.size} 待发`);
  setOptionalText("setpointPendingCount", `${pending.set_values.size} 待发`);
  setOptionalText("commandPendingCount", `${total} 待发`);
  setOptionalText("commandState", total ? "待发送" : "待命");
  renderActiveCommandPreview();
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  if (Math.abs(number) >= 100) return number.toFixed(1);
  return number.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

