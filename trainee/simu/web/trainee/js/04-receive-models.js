// 学员端模块：指令日志、模型管理、实时接收状态机与页面导航（04-receive-models.js）
function commandOrigin(entry = {}) {
  const payload = entry.payload && typeof entry.payload === "object" ? entry.payload : entry;
  const explicit = String(entry.command_origin || payload.command_origin || "").trim().toLowerCase();
  if (["manual", "human", "operator", "人工"].includes(explicit)) return "manual";
  if (["automatic", "auto", "strategy", "自动"].includes(explicit)) return "automatic";
  return manualCommandHoldsAcrossClockLifecycle(entry) ? "manual" : "automatic";
}

function commandOriginLabel(originOrEntry = "") {
  const origin = typeof originOrEntry === "string"
    ? String(originOrEntry).trim().toLowerCase()
    : commandOrigin(originOrEntry);
  if (origin === "manual") return "人工";
  if (origin === "automatic") return "自动";
  return "--";
}

function activeCommandHistory(snapshot = state.snapshot || {}) {
  const currentMinute = Number(snapshot.clock?.absolute_minute ?? snapshot.clock?.minute ?? 0) || 0;
  const currentRunId = Number(snapshot.clock?.run_id ?? 0) || 0;
  const commandEntries = Array.isArray(snapshot.commands?.effective)
    ? snapshot.commands.effective
    : (snapshot.commands?.history || []);
  return [...commandEntries].filter((entry) => {
    if (!entry?.eligible_source) return false;
    if (entry.cancelled) return false;
    const manualHold = manualCommandHoldsAcrossClockLifecycle(entry);
    if (!manualHold) {
      const entryRunId = Number(entry.run_id);
      if (!Number.isFinite(entryRunId) || entryRunId !== currentRunId) return false;
    }
    const accepted = entry.accepted || {};
    const acceptedCount = Number(accepted.run_status || 0) + Number(accepted.set_values || 0);
    if (manualHold) return acceptedCount > 0;
    const issued = Number(entry.issued_absolute_minute);
    const expires = Number(entry.expires_at_absolute_minute);
    if (!Number.isFinite(issued) || !Number.isFinite(expires)) return false;
    return acceptedCount > 0 && currentMinute < expires && issued <= currentMinute;
  });
}

function queuedCommandHistory(snapshot = state.snapshot || {}) {
  const currentMinute = Number(snapshot.clock?.absolute_minute ?? snapshot.clock?.minute ?? 0) || 0;
  const currentRunId = Number(snapshot.clock?.run_id ?? 0) || 0;
  const commandEntries = Array.isArray(snapshot.commands?.queued) ? snapshot.commands.queued : [];
  return [...commandEntries].filter((entry) => {
    if (!entry?.eligible_source || entry.cancelled) return false;
    const manualHold = manualCommandHoldsAcrossClockLifecycle(entry);
    if (!manualHold) {
      const entryRunId = Number(entry.run_id);
      if (!Number.isFinite(entryRunId) || entryRunId !== currentRunId) return false;
    }
    const accepted = entry.accepted || {};
    const acceptedCount = Number(accepted.run_status || 0) + Number(accepted.set_values || 0);
    if (manualHold) return acceptedCount > 0;
    const issued = Number(entry.issued_absolute_minute);
    const expires = Number(entry.expires_at_absolute_minute);
    if (!Number.isFinite(issued) || !Number.isFinite(expires)) return false;
    return acceptedCount > 0 && currentMinute < expires && issued <= currentMinute;
  });
}

function displayedCommandHistory(snapshot = state.snapshot || {}) {
  // Keep the effective owner last so it wins if an automatic fallback is
  // simultaneously queued behind a manual command.
  return [...queuedCommandHistory(snapshot), ...activeCommandHistory(snapshot)];
}

function allActiveCommandHistory(snapshot = state.snapshot || {}) {
  const currentMinute = Number(snapshot.clock?.absolute_minute ?? snapshot.clock?.minute ?? 0) || 0;
  const currentRunId = Number(snapshot.clock?.run_id ?? 0) || 0;
  const history = Array.isArray(snapshot.commands?.history) ? snapshot.commands.history : [];
  const queued = Array.isArray(snapshot.commands?.queued) ? snapshot.commands.queued : [];
  const effective = Array.isArray(snapshot.commands?.effective) ? snapshot.commands.effective : [];
  return [...history, ...queued, ...effective].filter((entry) => {
    if (!entry?.eligible_source || entry.cancelled) return false;
    const manualHold = manualCommandHoldsAcrossClockLifecycle(entry);
    if (!manualHold) {
      const entryRunId = Number(entry.run_id);
      if (!Number.isFinite(entryRunId) || entryRunId !== currentRunId) return false;
    }
    const accepted = entry.accepted || {};
    const acceptedCount = Number(accepted.run_status || 0) + Number(accepted.set_values || 0);
    if (manualHold) return acceptedCount > 0;
    const issued = Number(entry.issued_absolute_minute);
    const expires = Number(entry.expires_at_absolute_minute);
    if (!Number.isFinite(issued) || !Number.isFinite(expires)) return false;
    return acceptedCount > 0 && currentMinute < expires && issued <= currentMinute;
  });
}

function addRuntimeLog(type, target, result, detail = "", level = "info", renderNow = true, simuTime = "", scope = "") {
  state.runtimeLogSeq += 1;
  state.runtimeLogs.unshift({
    seq: state.runtimeLogSeq,
    wall_time: runtimeLogTime(),
    simu_time: runtimeLogSimTime(simuTime),
    type,
    target,
    result,
    detail,
    level,
    scope,
  });
  state.runtimeLogs = state.runtimeLogs.slice(
    0,
    Math.max(50, Math.round(activeRuntimeSetting("runtime_log_cache_limit"))),
  );
  if (renderNow) renderHistoryIfMounted();
}

function runtimeLogDetailText(detail) {
  if (Array.isArray(detail)) return detail.filter(Boolean).join("；");
  if (detail && typeof detail === "object") {
    return Object.entries(detail)
      .map(([key, value]) => `${key}: ${value}`)
      .join("；");
  }
  return String(detail || "");
}

function runtimeLogDetailLines(item = {}) {
  const detail = item.full_detail !== undefined && item.full_detail !== null
    ? item.full_detail
    : item.detail;
  const source = Array.isArray(detail) ? detail : [detail];
  const lines = source.flatMap((part) => {
    if (part && typeof part === "object" && !Array.isArray(part)) {
      return Object.entries(part).map(([key, value]) => `${key}: ${value}`);
    }
    return runtimeLogDetailText(part).split(/[；\n]+/);
  }).map((line) => String(line || "").trim()).filter(Boolean);
  return lines.length ? lines : ["该条日志没有附加详细信息。"];
}

function runtimeLogSummaryText(item = {}) {
  const lines = runtimeLogDetailLines(item);
  const preferred = lines.find((line) => /^(?:结果|告警|缺失测点|求解|指令|撤销|下发)/.test(line));
  const summary = String(preferred || lines[0] || "--")
    .replace(/^(?:计算摘要|控制响应|输入边界|详细信息)\s*[：:]?\s*/, "")
    .trim() || "--";
  return summary.length > 120 ? `${summary.slice(0, 117)}...` : summary;
}

function runtimeLogBySeq(seq) {
  const normalizedSeq = Number(seq) || 0;
  return state.runtimeLogs.find((item) => (Number(item?.seq) || 0) === normalizedSeq) || null;
}

function selectRuntimeLogRow(seq) {
  const normalizedSeq = Number(seq) || 0;
  if (!runtimeLogBySeq(normalizedSeq)) return false;
  state.runtimeLogSelectedSeq = normalizedSeq;
  document.querySelectorAll("#commandHistory [data-runtime-log-seq]").forEach((row) => {
    const selected = (Number(row.dataset.runtimeLogSeq) || 0) === normalizedSeq;
    row.classList.toggle("is-selected", selected);
    row.setAttribute("aria-selected", String(selected));
  });
  return true;
}

function openRuntimeLogDetailDialog(seq) {
  const item = runtimeLogBySeq(seq);
  const dialog = $("runtimeLogDetailDialog");
  const meta = $("runtimeLogDetailMeta");
  const body = $("runtimeLogDetailBody");
  if (!item || !dialog || !meta || !body) return;
  selectRuntimeLogRow(item.seq);
  $("runtimeLogDetailSequence").textContent = `日志 #${Number(item.seq) || "--"}`;
  meta.innerHTML = `
    <div><dt>本机时刻</dt><dd>${escapeHtml(runtimeLogWallTimeText(item.wall_time))}</dd></div>
    <div><dt>仿真时刻</dt><dd>${escapeHtml(item.simu_time || "--")}</dd></div>
    <div><dt>类型 / 对象</dt><dd>${escapeHtml([item.type, item.target].filter(Boolean).join(" · ") || "--")}</dd></div>
    <div><dt>结果</dt><dd class="is-${escapeHtml(item.level || "info")}">${escapeHtml(item.result || "--")}</dd></div>`;
  body.innerHTML = runtimeLogDetailLines(item)
    .map((line) => `<li><span>${escapeHtml(line)}</span></li>`)
    .join("");
  if (!dialog.open) dialog.showModal();
}

function closeRuntimeLogDetailDialog() {
  const dialog = $("runtimeLogDetailDialog");
  if (dialog?.open) dialog.close();
}

function handleRuntimeLogTableActivation(event) {
  if (event.type === "keydown" && event.key !== "Enter") return;
  const row = event.target instanceof Element ? event.target.closest("[data-runtime-log-seq]") : null;
  if (!row) return;
  selectRuntimeLogRow(row.dataset.runtimeLogSeq);
  if (event.type === "dblclick" || event.type === "keydown") {
    event.preventDefault();
    openRuntimeLogDetailDialog(row.dataset.runtimeLogSeq);
  }
}

function setImportStatus(text, kind = "") {
  const target = $("importStatus");
  if (!target) return;
  target.textContent = text || "";
  target.classList.toggle("is-error", kind === "error");
  target.classList.toggle("is-ok", kind === "ok");
}

function normalizeModels(models = state.models) {
  return (Array.isArray(models) ? models : [])
    .map((model) => ({
      ...model,
      id: String(model?.id || model?.model_id || "").trim(),
      name: String(model?.name || model?.model_name || model?.id || model?.model_id || "").trim(),
    }))
    .filter((model) => model.id);
}

function modelById(modelId) {
  const targetId = String(modelId || "");
  return normalizeModels().find((model) => model.id === targetId) || null;
}

function isModelNameTaken(name, ignoreId = "") {
  const normalized = String(name || "").trim();
  const ignored = String(ignoreId || "").trim();
  return normalizeModels().some((model) => (model.id === normalized || model.name === normalized) && model.id !== ignored);
}

function traineeReceiveStateForModel(modelId) {
  return activeModelContext(modelId);
}

function modelManagementState(model) {
  const modelId = String(model?.id || "");
  const context = traineeReceiveStateForModel(modelId);
  if (!context.modelInitialized) return "uninitialized";
  if (context.receiveMode) return "received";
  return "stopped";
}

function modelManagementStateText(value) {
  return {
    received: "已接收",
    uninitialized: "未初始化",
    stopped: "已停止",
  }[value] || value || "--";
}

function canEditManagedModel(model) {
  const stateText = modelManagementState(model);
  return stateText !== "received";
}

function setModelManagementMessage(text, kind = "") {
  const message = $("modelManagementMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function ensureSelectedManagementModelId(models = normalizeModels()) {
  if (!models.length) {
    state.selectedManagementModelId = "";
    return "";
  }
  const selectedId = String(state.selectedManagementModelId || "");
  if (selectedId && models.some((model) => model.id === selectedId)) return selectedId;
  const activeId = String(state.activeModelId || "");
  const nextId = activeId && models.some((model) => model.id === activeId) ? activeId : models[0].id;
  state.selectedManagementModelId = nextId;
  return nextId;
}

function selectedManagementModelId() {
  return ensureSelectedManagementModelId();
}

function selectedManagementModel() {
  return modelById(selectedManagementModelId());
}

function updateModelContextMenuActions() {
  const models = normalizeModels();
  const selected = selectedManagementModel();
  const hasSelected = Boolean(selected);
  const editable = selected ? canEditManagedModel(selected) : false;
  const lifecycleState = selected ? modelManagementState(selected) : "";
  const menu = $("modelContextMenu");
  const lifecycleButton = menu?.querySelector('[data-model-context-action="lifecycle"]');
  const exportButton = menu?.querySelector('[data-model-context-action="export"]');
  const cloneButton = menu?.querySelector('[data-model-context-action="clone"]');
  const deleteButton = menu?.querySelector('[data-model-context-action="delete"]');
  if (lifecycleButton) {
    lifecycleButton.textContent = lifecycleState === "uninitialized"
      ? "初始化"
      : (lifecycleState === "received" ? "停止接收" : "启动接收");
    lifecycleButton.disabled = !hasSelected || state.modelLifecycleOperationActive;
    lifecycleButton.title = !hasSelected
      ? "请选择模型"
      : `${lifecycleButton.textContent} ${selected.name || selected.id || "选中模型"}`;
  }
  if (exportButton) exportButton.disabled = !hasSelected;
  if (cloneButton) cloneButton.disabled = !hasSelected;
  if (deleteButton) {
    const canDelete = hasSelected && models.length > 1 && editable;
    deleteButton.disabled = !canDelete;
    deleteButton.title = !hasSelected
      ? "请选择模型"
      : (models.length <= 1
        ? "至少需要保留一个模型"
        : (editable ? "删除选中的本地模型" : "模型正在接收或运行中，不能删除"));
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
  const models = normalizeModels();
  if (!models.length) {
    list.innerHTML = '<div class="model-management-empty">暂无本地模型</div>';
    state.selectedManagementModelId = "";
    updateModelContextMenuActions();
    return;
  }
  const selectedId = ensureSelectedManagementModelId(models);
  const branchHtml = models.map((model) => {
    const isActive = model.id === state.activeModelId;
    const isSelected = model.id === selectedId;
    const operationState = modelManagementState(model);
    return `
      <div
        class="model-management-item ${isActive ? "is-active" : ""} ${isSelected ? "is-selected" : ""}"
        role="treeitem"
        tabindex="0"
        aria-selected="${isSelected ? "true" : "false"}"
        data-model-id="${escapeHtml(model.id)}"
      >
        <span class="model-management-node-mark" aria-hidden="true"></span>
        <strong class="model-node-name">${escapeHtml(model.name || model.id)}</strong>
        <div class="model-item-badges">
          ${isActive ? '<span class="model-current-pill">当前</span>' : ""}
          <span class="model-state-pill" data-state="${escapeHtml(operationState)}">${escapeHtml(modelManagementStateText(operationState))}</span>
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
    <div class="model-management-branches" role="group">${branchHtml}</div>
  `;
  updateModelContextMenuActions();
}

async function openModelManagementDialog() {
  const dialog = $("modelManagementDialog");
  if (!dialog) return;
  if (!dialog.open) dialog.showModal();
  setModelManagementMessage("正在读取模型列表...");
  try {
    await loadModels();
    ensureSelectedManagementModelId();
    renderModelManagementList();
    setModelManagementMessage("右键模型节点可按状态初始化、启动接收或停止接收，也可导出、复制或删除。", "ok");
  } catch (error) {
    renderModelManagementList();
    setModelManagementMessage(apiErrorText(error), "error");
  }
}

function closeModelManagementDialog() {
  closeModelContextMenu();
  const dialog = $("modelManagementDialog");
  if (dialog?.open) dialog.close();
}

function closeModelContextMenu() {
  const menu = $("modelContextMenu");
  if (menu) menu.hidden = true;
}

function positionModelContextMenu(menu, x, y) {
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  requestAnimationFrame(() => {
    const rect = menu.getBoundingClientRect();
    const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
    const maxTop = Math.max(8, window.innerHeight - rect.height - 8);
    menu.style.left = `${Math.max(8, Math.min(x, maxLeft))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, maxTop))}px`;
  });
}

function handleModelManagementAction(event) {
  closeModelContextMenu();
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  setSelectedManagementModel(item.dataset.modelId || "");
  setModelManagementMessage("右键模型节点可按状态初始化、启动接收或停止接收，也可导出、复制或删除。", "ok");
}

function handleModelManagementKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  event.preventDefault();
  setSelectedManagementModel(item.dataset.modelId || "");
}

function openModelContextMenu(event) {
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  event.preventDefault();
  setSelectedManagementModel(item.dataset.modelId || "");
  const menu = $("modelContextMenu");
  if (!menu) return;
  updateModelContextMenuActions();
  menu.hidden = false;
  positionModelContextMenu(menu, event.clientX, event.clientY);
}

function setNewModelMessage(text, kind = "") {
  const message = $("newModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function setNewModelBusy(isBusy) {
  const confirm = $("confirmNewModel");
  const input = $("newModelName");
  const button = $("newModelButton");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "新建中" : "新建";
  }
  if (input) input.disabled = isBusy;
  if (button) button.disabled = isBusy;
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

function validateNewModelForm(showBlank = false) {
  const input = $("newModelName");
  const confirm = $("confirmNewModel");
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
  if (confirm) confirm.disabled = false;
  setNewModelMessage("");
  return true;
}

function openNewModelDialog() {
  const dialog = $("newModelDialog");
  const input = $("newModelName");
  if (!dialog || !input) return;
  input.value = uniqueNewModelName("新模型");
  setNewModelMessage("");
  validateNewModelForm();
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

function closeNewModelDialog() {
  const dialog = $("newModelDialog");
  if (dialog?.open) dialog.close();
  setNewModelMessage("");
  setNewModelBusy(false);
}

async function createNewModelSlot() {
  const input = $("newModelName");
  const name = String(input?.value || "").trim();
  if (!validateNewModelForm(true)) {
    input?.focus();
    return;
  }
  setNewModelBusy(true);
  setNewModelMessage("正在创建待初始化的本地模型...");
  addRuntimeLog("模型管理", "学员台 /api/trainee/models/create", "新建请求", name);
  try {
    const result = await api("/api/trainee/models/create", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.selected_model_id || name;
    state.modelContexts[contextKey(newModelId)] = defaultModelContext(newModelId);
    persistModelContextsToStorage();
    closeNewModelDialog();
    state.selectedManagementModelId = newModelId;
    renderModelSelector();
    renderModelManagementList();
    setModelManagementMessage(`已新建待初始化模型：${name}`, "ok");
    setImportStatus(`已新建待初始化模型：${name}`, "ok");
    addRuntimeLog("模型管理", "学员台 /api/trainee/models/create", "新建成功", `模型 ${name}`, "ok");
  } catch (error) {
    const message = apiErrorText(error);
    if (message.includes("已存在")) await loadModels();
    setNewModelMessage(message.includes("已存在") ? `${message}，请输入新的模型名称。` : message, "error");
    setImportStatus(message, "error");
    addRuntimeLog("模型管理", "学员台 /api/trainee/models/create", "新建失败", message, "error");
  } finally {
    setNewModelBusy(false);
    if ($("newModelDialog")?.open) validateNewModelForm();
  }
}

function setCloneModelMessage(text, kind = "") {
  const message = $("cloneModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function uniqueCloneModelName(sourceName = "模型") {
  const base = String(sourceName || "模型").trim().replace(/_copy\d*$/i, "") || "模型";
  let candidate = `${base}_copy`;
  let index = 2;
  while (isModelNameTaken(candidate)) {
    candidate = `${base}_copy${index}`;
    index += 1;
  }
  return candidate;
}

function validateCloneModelName(showBlank = false) {
  const input = $("cloneModelName");
  const confirm = $("confirmCloneModel");
  const name = String(input?.value || "").trim();
  if (!name) {
    if (confirm) confirm.disabled = true;
    setCloneModelMessage(showBlank ? "请输入新模型名称。" : "", showBlank ? "error" : "");
    return false;
  }
  if (isModelNameTaken(name)) {
    if (confirm) confirm.disabled = true;
    setCloneModelMessage(`模型已存在：${name}，请输入新的模型名称。`, "error");
    return false;
  }
  if (confirm) confirm.disabled = false;
  setCloneModelMessage("");
  return true;
}

function openCloneModelDialog(modelId = selectedManagementModelId()) {
  const source = modelById(modelId);
  if (!source) {
    setModelManagementMessage("请选择要复制的模型。", "error");
    return;
  }
  state.cloneSourceModelId = source.id;
  $("cloneModelSourceName").textContent = source.name || source.id;
  const input = $("cloneModelName");
  if (input) input.value = uniqueCloneModelName(source.name || source.id);
  setCloneModelMessage("");
  validateCloneModelName();
  const dialog = $("cloneModelDialog");
  if (!dialog?.open) dialog?.showModal();
  requestAnimationFrame(() => {
    input?.focus();
    input?.select();
  });
}

function closeCloneModelDialog() {
  const dialog = $("cloneModelDialog");
  if (dialog?.open) dialog.close();
  state.cloneSourceModelId = "";
  setCloneModelMessage("");
}

async function cloneManagedModel() {
  const sourceId = state.cloneSourceModelId || selectedManagementModelId();
  const input = $("cloneModelName");
  const name = String(input?.value || "").trim();
  if (!sourceId || !validateCloneModelName(true)) return;
  const confirm = $("confirmCloneModel");
  if (confirm) {
    confirm.disabled = true;
    confirm.textContent = "复制中";
  }
  try {
    const result = await api("/api/models/clone", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({ model_id: sourceId, name }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.active_model_id || name;
    closeCloneModelDialog();
    state.selectedManagementModelId = newModelId;
    renderModelSelector();
    renderModelManagementList();
    setModelManagementMessage(`已复制模型：${name}`, "ok");
    addRuntimeLog("模型管理", "学员台 /api/models/clone", "复制成功", `${sourceId} → ${name}`, "ok");
  } catch (error) {
    const message = apiErrorText(error);
    if (message.includes("已存在")) await loadModels();
    setCloneModelMessage(message.includes("已存在") ? `${message}，请输入新的模型名称。` : message, "error");
    addRuntimeLog("模型管理", "学员台 /api/models/clone", "复制失败", message, "error");
  } finally {
    if (confirm) {
      confirm.textContent = "复制";
      validateCloneModelName();
    }
  }
}

function blobFromBase64(dataBase64, contentType) {
  const binary = atob(dataBase64 || "");
  const chunkSize = 65536;
  const chunks = [];
  for (let offset = 0; offset < binary.length; offset += chunkSize) {
    const slice = binary.slice(offset, offset + chunkSize);
    const bytes = new Uint8Array(slice.length);
    for (let idx = 0; idx < slice.length; idx += 1) bytes[idx] = slice.charCodeAt(idx);
    chunks.push(bytes);
  }
  return new Blob(chunks, { type: contentType || "application/zip" });
}

function downloadBlob(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

function safeExportFilename(filename) {
  const cleaned = String(filename || "model_definitions.zip").replace(/[\\/:*?"<>|]/g, "_");
  return cleaned.toLowerCase().endsWith(".zip") ? cleaned : `${cleaned}.zip`;
}

async function exportDefinitionsArchive(modelId = selectedManagementModelId(), actionButton = null) {
  const targetModelId = String(modelId || "").trim();
  if (!targetModelId) {
    setModelManagementMessage("请选择要导出的模型。", "error");
    return;
  }
  const button = actionButton;
  const originalText = button?.textContent || "";
  if (button) {
    button.disabled = true;
    button.textContent = "导出中";
  }
  try {
    const payload = await api("/api/export-definitions?format=json&model_id=" + encodeURIComponent(targetModelId), {
      modelScoped: false,
    });
    const filename = safeExportFilename(payload.filename || `${targetModelId}_definitions.zip`);
    downloadBlob(blobFromBase64(payload.data_base64, payload.content_type), filename);
    setModelManagementMessage(`已导出模型：${targetModelId}`, "ok");
    addRuntimeLog("模型管理", "学员台 /api/export-definitions", "导出成功", targetModelId, "ok");
  } catch (error) {
    const message = apiErrorText(error);
    setModelManagementMessage(message, "error");
    addRuntimeLog("模型管理", "学员台 /api/export-definitions", "导出失败", message, "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function deleteManagedModel(modelId = selectedManagementModelId()) {
  const target = modelById(modelId);
  const models = normalizeModels();
  if (!target) {
    setModelManagementMessage("请选择要删除的模型。", "error");
    return;
  }
  if (models.length <= 1) {
    setModelManagementMessage("至少需要保留一个模型。", "error");
    return;
  }
  if (!canEditManagedModel(target)) {
    setModelManagementMessage("模型正在接收或运行中，不能删除。", "error");
    return;
  }
  const modelName = target.name || target.id;
  const confirmed = await confirmDangerousAction({
    title: "永久删除该本地模型？",
    target: `模型：${modelName}`,
    message: "此操作将永久删除本地模型文件夹、定义与全部运行数据，无法恢复。",
    confirmLabel: "确认删除",
  });
  if (!confirmed) return;
  const deletedActiveModel = String(target.id || "") === String(state.activeModelId || "");
  setModelManagementMessage(`正在删除模型：${modelName}`);
  try {
    const result = await api("/api/models/delete", {
      modelScoped: false,
      method: "POST",
      body: JSON.stringify({ model_id: target.id }),
    });
    delete state.modelContexts[contextKey(target.id)];
    persistModelContextsToStorage();
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const nextId = state.models.some((model) => model.id === state.activeModelId)
      ? state.activeModelId
      : (result.active_model_id || state.models[0]?.id || "");
    state.selectedManagementModelId = deletedActiveModel
      ? nextId
      : (state.models.some((model) => model.id === state.selectedManagementModelId)
        ? state.selectedManagementModelId
        : (state.activeModelId || nextId));
    if (deletedActiveModel) {
      setActiveModel(nextId, true);
    } else {
      renderModelSelector();
      renderModelManagementList();
    }
    setModelManagementMessage(`已删除模型：${modelName}`, "ok");
    addRuntimeLog("模型管理", "学员台 /api/models/delete", "删除成功", modelName, "ok");
  } catch (error) {
    await loadModels();
    renderModelManagementList();
    const message = apiErrorText(error);
    setModelManagementMessage(message, "error");
    addRuntimeLog("模型管理", "学员台 /api/models/delete", "删除失败", message, "error");
  }
}

function handleModelContextMenuAction(event) {
  const button = event.target instanceof Element ? event.target.closest("[data-model-context-action]") : null;
  if (!button || button.disabled) return;
  const action = button.dataset.modelContextAction || "";
  closeModelContextMenu();
  switch (action) {
    case "lifecycle":
      handleSelectedManagementModelLifecycle();
      break;
    case "export":
      exportDefinitionsArchive(selectedManagementModelId(), button);
      break;
    case "clone":
      openCloneModelDialog(selectedManagementModelId());
      break;
    case "delete":
      deleteManagedModel(selectedManagementModelId());
      break;
    default:
      break;
  }
}

async function initializeSelectedManagementModel(modelId = selectedManagementModelId()) {
  const target = modelById(modelId);
  if (!target) {
    setModelManagementMessage("请选择要初始化的模型。", "error");
    return;
  }
  if (modelManagementState(target) !== "uninitialized") return;
  try {
    if (target.id !== state.activeModelId) await setActiveModel(target.id, false);
    closeModelManagementDialog();
    openReceiveLinkDialog();
  } catch (error) {
    setModelManagementMessage(`打开初始化窗口失败：${apiErrorText(error)}`, "error");
  }
}

async function setManagedModelReceiveActive(modelId, active) {
  const target = modelById(modelId);
  if (!target || state.modelLifecycleOperationActive) return;
  const context = traineeReceiveStateForModel(target.id);
  if (!context.modelInitialized) {
    setModelManagementMessage("模型尚未初始化，请先执行初始化。", "error");
    return;
  }
  if (Boolean(context.receiveMode) === Boolean(active)) return;
  const actionText = active ? "启动接收" : "停止接收";
  const modelName = target.name || target.id;
  state.modelLifecycleOperationActive = true;
  updateModelContextMenuActions();
  setModelManagementMessage(`正在${actionText}：${modelName}`);
  try {
    if (target.id === state.activeModelId) {
      if (active) {
        await startReceiveMode();
        if (!state.receiveMode) throw new Error("启动接收失败，请检查模型初始化信息和交互链路。");
      } else {
        await toggleReceiveMode();
        if (state.receiveMode) throw new Error("停止接收失败。");
      }
    } else {
      await setTraineeReceiveActive(target.id, active);
    }
    renderModelManagementList();
    setModelManagementMessage(`已${actionText}：${modelName}`, "ok");
    addRuntimeLog("模型管理", modelName, actionText, "操作成功", "ok");
  } catch (error) {
    try {
      await syncActiveReceiveStateFromBackend(target.id);
    } catch (_syncError) {
      // Keep the last known model state when the local service cannot be queried.
    }
    renderModelManagementList();
    const message = apiErrorText(error);
    setModelManagementMessage(`${actionText}失败：${message}`, "error");
    addRuntimeLog("模型管理", modelName, `${actionText}失败`, message, "warn");
  } finally {
    state.modelLifecycleOperationActive = false;
    updateModelContextMenuActions();
  }
}

function handleSelectedManagementModelLifecycle() {
  const target = selectedManagementModel();
  if (!target) {
    setModelManagementMessage("请选择要操作的模型。", "error");
    return;
  }
  const lifecycleState = modelManagementState(target);
  if (lifecycleState === "uninitialized") {
    initializeSelectedManagementModel(target.id);
    return;
  }
  setManagedModelReceiveActive(target.id, lifecycleState !== "received");
}

function renderModelSelector() {
  const selector = $("modelSelector");
  const localModels = state.models.length ? state.models : [{ id: state.activeModelId || "", name: "默认模型" }];
  const hasActiveModel = localModels.some((model) => model.id === state.activeModelId);
  const externalModel = state.activeModelId && !hasActiveModel
    ? [{ id: state.activeModelId, name: state.teacherModelName || state.snapshot?.model?.name || state.activeModelId }]
    : [];
  const models = [...localModels, ...externalModel];
  let activeModelId = state.activeModelId || models[0]?.id || "";
  if (selector) {
    const modelOptionsKey = JSON.stringify(models.map((model) => [model.id, model.name || model.id]));
    if (selector.dataset.modelOptionsKey !== modelOptionsKey) {
      selector.innerHTML = models.map((model) => `
        <option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)}</option>
      `).join("");
      selector.dataset.modelOptionsKey = modelOptionsKey;
    }
    selector.value = activeModelId;
    selector.disabled = models.length <= 1;
    activeModelId = selector.value;
  }
  const active = models.find((model) => model.id === activeModelId) || models[0] || {};
  const activeModelName = $("activeModelName");
  if (activeModelName) {
    activeModelName.textContent = active.name || active.id || "默认模型";
  }
}

async function setActiveModel(modelId, shouldRefresh = true) {
  persistActiveModelContext({}, true);
  const nextId = modelId || state.models[0]?.id || "";
  state.modelSwitchEpoch = Number(state.modelSwitchEpoch || 0) + 1;
  if (state.measurementDeltaAbortController) {
    try { state.measurementDeltaAbortController.abort(); } catch (_e) {}
    state.measurementDeltaAbortController = null;
  }
  state.measurementDeltaRequestActive = false;
  state.refreshRequestActive = false;
  state.receiveRequestActive = false;
  state.activeModelId = nextId;
  state.deviceRuntimeSignature = "";
  state.deviceRuntimeNeedsFullRefresh = false;
  state.deviceRuntimeWarning = "";
  localStorage.setItem("polarTraineeModelId", nextId);
  restoreModelContext(nextId);
  resetMeasurementHistoryHydration();
  resetReceiveIssueStreak();
  pending.run_status.clear();
  pending.set_values.clear();
  if (!state.receiveMode) state.frozen = false;
  state.localDefinitionSnapshot = null;
  state.localDefinitionModelId = "";
  invalidateManualDefinitionChanges();
  state.selectedMeasurementKey = "";
  state.selectedCommandTraceKey = "";
  state.selectedCommandTraceLabel = "";
  state.modelFilter = { dev_type: "all", dev_name: "" };
  state.activeModelParamTab = "";
  state.activeCurveDisplayKey = "wind_speed_mps";
  state.selectedCurveDisplayKeys = ["wind_speed_mps"];
  state.hiddenCurveDisplayKeys = [];
  state.curveDisplayCursor = { visible: false, x: 0, y: 0, index: 0 };
  state.curveDisplayLegendHitBoxes = [];
  state.lastCurveDisplayRenderKey = "";
  state.lastCurveDisplayTableKey = "";
  state.chartSeriesHidden = {};
  state.chartSeriesSelected = {};
  state.chartLegendSeriesHidden = {};
  state.chartCursors = {};
  state.chartSeriesHitData = {};
  state.chartPlotInfo = {};
  resetChartPeriodOffsets("measurementTrace");
  resetChartPeriodOffsets("commandTrace");
  resetChartPeriodOffsets("renewableTrend");
  state.measurementFilter = { dev_type: "all", dev_name: "" };
  state.controlFilter = { dev_type: "all", dev_name: "" };
  state.activeControlTab = "remote-control";
  state.deviceTreeSelectionAnchors = {};
  resetWebRuntimeSettingsState();
  restartRefreshScheduler();
  resetRenewableControlView(nextId);
  renderModelSelector();
  if ($("modelManagementDialog")?.open) renderModelManagementList();
  updatePendingCount();
  await loadWebRuntimeSettings();
  if (shouldRefresh) await refresh();
}

async function loadModels() {
  try {
    const catalog = await api("/api/models", { modelScoped: false });
    state.models = Array.isArray(catalog.models) ? catalog.models : [];
    try {
      const receiveStates = await api("/api/trainee/receive-states", { modelScoped: false });
      mergeReceiveStatesFromBackend(receiveStates.items || {});
    } catch (_error) {
      // Older trainee services may not have receive-state persistence; local contexts still work.
    }
    const preferred = state.activeModelId || catalog.active_model_id || state.models[0]?.id || "";
    const exists = state.models.some((model) => model.id === preferred);
    const nextId = exists ? preferred : state.models[0]?.id || "";
    const activeModelAlreadyLoaded = Boolean(
      nextId
      && nextId === state.activeModelId
      && String(state.snapshot?.model?.id || "") === nextId
    );
    if (activeModelAlreadyLoaded) renderModelSelector();
    else await setActiveModel(nextId, false);
    if ($("modelManagementDialog")?.open) renderModelManagementList();
  } catch (_error) {
    state.models = [];
    renderModelSelector();
    if ($("modelManagementDialog")?.open) renderModelManagementList();
  }
}

async function refreshLocalSnapshotPayload(page = currentPageName()) {
  const reqModelId = state.activeModelId;
  const reqEpoch = Number(state.modelSwitchEpoch || 0);
  state.embeddedMeasurementDeltaReceived = false;
  const rawResponse = await api(snapshotPollPath(page));
  if (state.activeModelId !== reqModelId || Number(state.modelSwitchEpoch || 0) !== reqEpoch) {
    return null;
  }
  let snapshot = mergeSnapshot(
    state.snapshot,
    applyDeviceRuntimePayload(state.snapshot, rawResponse),
  );
  let embeddedMeasurementDelta = snapshot?.measurement_delta || null;
  if (snapshot?.measurement_delta) delete snapshot.measurement_delta;
  snapshot = restoreStaticSnapshotCache(snapshot, page);
  let missingStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
  if (missingStaticKeys.length) {
    const rawStatic = await api(snapshotPollPath(page, missingStaticKeys));
    if (state.activeModelId !== reqModelId || Number(state.modelSwitchEpoch || 0) !== reqEpoch) {
      return null;
    }
    const staticIncoming = applyDeviceRuntimePayload(snapshot, rawStatic);
    if (staticIncoming?.measurement_delta) {
      embeddedMeasurementDelta = staticIncoming.measurement_delta;
      delete staticIncoming.measurement_delta;
    }
    snapshot = mergeSnapshot(snapshot, staticIncoming);
    snapshot = restoreStaticSnapshotCache(snapshot, page);
    missingStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
  }
  state.snapshot = snapshot;
  if (embeddedMeasurementDelta) {
    snapshot.measurement_delta = embeddedMeasurementDelta;
    applyEmbeddedMeasurementDelta(snapshot);
  }
  if (!missingStaticKeys.length) persistStaticSnapshotCache(state.snapshot, page);
  return snapshot;
}

async function refresh() {
  const requestedModelId = state.activeModelId;
  const switchEpoch = Number(state.modelSwitchEpoch || 0);
  if (!state.receiveMode) await syncActiveReceiveStateBeforeRefresh();
  if (state.activeModelId !== requestedModelId || Number(state.modelSwitchEpoch || 0) !== switchEpoch) {
    return;
  }
  if (state.receiveMode) {
    await refreshFromTeacher(state.receiveEpoch);
    return;
  }
  const page = currentPageName();
  const bootstrapFrozenSnapshot = frozenSnapshotNeedsBootstrap(state.snapshot, page);
  if (state.frozen && !bootstrapFrozenSnapshot) {
    renderReceiveMode();
    if (currentPageName() === "renewable") await refreshRenewableControlState({ preview: false });
    return;
  }
  if (state.refreshRequestActive) return;
  state.refreshRequestActive = true;
  try {
    const snapshot = await refreshLocalSnapshotPayload(page);
    if (!snapshot || state.activeModelId !== requestedModelId || Number(state.modelSwitchEpoch || 0) !== switchEpoch) {
      return;
    }
    if (
      !bootstrapFrozenSnapshot
      && pageNeedsMeasurementDelta(page)
      && !state.embeddedMeasurementDeltaReceived
    ) {
      await refreshMeasurementDelta(false);
    }
    if (state.activeModelId !== requestedModelId || Number(state.modelSwitchEpoch || 0) !== switchEpoch) {
      return;
    }
    state.refreshConsecutiveFailures = 0;
    $("connectionDot").className = "ok";
    $("connectionText").textContent = "在线";
    state.snapshotSource = "local";
    if (page === "renewable") {
      await refreshRenewableControlState({ preview: false, render: false });
    }
    renderSnapshot(snapshot);
  } catch (_error) {
    if (state.activeModelId !== requestedModelId || Number(state.modelSwitchEpoch || 0) !== switchEpoch) {
      return;
    }
    state.refreshConsecutiveFailures = Math.min(10, (state.refreshConsecutiveFailures || 0) + 1);
    const retrySec = Math.max(1, Math.round(refreshSchedulerIntervalMs() / 1000));
    $("connectionDot").className = "off";
    $("connectionText").textContent = `离线（${retrySec}s 后重试）`;
    if (page === "renewable") await refreshRenewableControlState({ preview: false });
  } finally {
    if (Number(state.modelSwitchEpoch || 0) === switchEpoch) {
      state.refreshRequestActive = false;
    }
  }
}

async function refreshFromTeacher(epoch = state.receiveEpoch) {
  if (state.receiveRequestActive) return;
  const requestedModelId = state.activeModelId;
  const switchEpoch = Number(state.modelSwitchEpoch || 0);
  state.receiveRequestActive = true;
  try {
    const page = currentPageName();
    await ensureLocalDefinitionSnapshot(requestedModelId);
    if (state.activeModelId !== requestedModelId || Number(state.modelSwitchEpoch || 0) !== switchEpoch) {
      return;
    }
    const uiFrame = await api(traineeUiFramePath(page));
    if (state.activeModelId !== requestedModelId || Number(state.modelSwitchEpoch || 0) !== switchEpoch) {
      return;
    }
    const frameSnapshot = applyTraineeUiFrame(uiFrame);
    if (!state.receiveMode || epoch !== state.receiveEpoch || !frameSnapshot) {
      renderReceiveMode();
      return;
    }
    const remoteSnapshot = applyDeviceRuntimePayload(
      state.snapshot,
      frameSnapshot,
    );
    state.embeddedMeasurementDeltaReceived = false;
    const embeddedMeasurementDelta = remoteSnapshot?.measurement_delta || null;
    if (remoteSnapshot?.measurement_delta) delete remoteSnapshot.measurement_delta;
    const snapshot = mergeTeacherSnapshotWithLocalDefinitions(state.snapshot, remoteSnapshot);
    if (
      !state.receiveMode
      || epoch !== state.receiveEpoch
      || state.activeModelId !== requestedModelId
      || Number(state.modelSwitchEpoch || 0) !== switchEpoch
    ) {
      return;
    }
    state.snapshot = snapshot;
    if (embeddedMeasurementDelta) {
      snapshot.measurement_delta = embeddedMeasurementDelta;
      applyEmbeddedMeasurementDelta(snapshot);
    }
    if (pageNeedsMeasurementDelta(page) && !state.embeddedMeasurementDeltaReceived) {
      await refreshMeasurementDelta(false);
    }
    if (page === "renewable") {
      await ensureRenewableTrendHistoryForVisibleSeries({ render: false });
    }
    if (state.activeModelId !== requestedModelId || Number(state.modelSwitchEpoch || 0) !== switchEpoch) {
      return;
    }
    state.refreshConsecutiveFailures = 0;
    acceptTeacherSnapshot(state.snapshot, epoch);
  } catch (_error) {
    if (
      !state.receiveMode
      || epoch !== state.receiveEpoch
      || state.activeModelId !== requestedModelId
      || Number(state.modelSwitchEpoch || 0) !== switchEpoch
    ) {
      return;
    }
    state.refreshConsecutiveFailures = Math.min(10, (state.refreshConsecutiveFailures || 0) + 1);
    const retrySec = Math.max(1, Math.round(refreshSchedulerIntervalMs() / 1000));
    $("connectionDot").className = "off";
    if (isTraineeWebTransportError(_error)) {
      $("connectionText").textContent = `后台重连（${retrySec}s）`;
      recordTraineeWebTransportIssue(_error);
      return;
    }
    $("connectionText").textContent = `正在重连（${retrySec}s）`;
    const shouldContinue = recordReceiveIssue(
      "实时交互",
      "模拟台 /api/snapshot",
      "通讯失败",
      [`数据接收失败：${apiErrorText(_error)}`, "将尝试自动重连模拟台交互链接"],
    );
    if (shouldContinue) await attemptTeacherReconnect(epoch);
  } finally {
    if (Number(state.modelSwitchEpoch || 0) === switchEpoch) {
      state.receiveRequestActive = false;
    }
  }
}

function renderSnapshot(snapshot) {
  state.frontendDiagnostics.snapshotRenderCount += 1;
  applyTraineeObservedRuntimeSignals(snapshot);
  state.snapshot = snapshot;
  // 仅在 activeModelId 尚未初始化时兜底，禁止用异步迟到的旧模型快照反写当前选中模型。
  if (!state.activeModelId && state.snapshotSource !== "teacher" && snapshot.model?.id) {
    state.activeModelId = snapshot.model.id;
  }
  renderModelSelector();
  renderClock(snapshot.clock || {});
  renderPowerFlowFailureAlert(snapshot);
  const runId = Number(snapshot.clock?.run_id ?? 0);
  const stepCount = Number(snapshot.clock?.step_count ?? 0);
  const traceLifecycleChanged = state.traceRunId !== null && (
    runId !== state.traceRunId
    || (state.traceStepCount !== null && stepCount < state.traceStepCount)
  );
  if (traceLifecycleChanged) {
    state.measurementTraceHistory = [];
    resetChartPeriodOffsets("measurementTrace");
    state.lastMeasurementTraceKey = "";
    resetMeasurementHistoryHydration();
    state.commandTraceHistory = [];
    resetChartPeriodOffsets("commandTrace");
    resetRenewableTrendHistoryHydration({ clearHistory: true });
    state.selectedMeasurementKey = "";
  }
  state.traceRunId = runId;
  state.traceStepCount = stepCount;
  renderReceiveMode();
  appendMeasurementTrace(snapshot);
  appendCommandTrace(snapshot);
  syncCommandHistoryLogs(snapshot.commands?.history || []);
  updatePendingCount();
  renderActiveTraineePage(snapshot);
  if (currentPageName() === "measurements") {
    ensureSelectedMeasurementHistory();
  }
  refreshDiagramDeviceCommandDialog(snapshot);
  refreshRemoteControlDialog(snapshot);
  refreshRemoteAdjustmentDialog(snapshot);
  persistActiveModelContext();
}

function renderReceiveMode(extraText = "") {
  const button = $("traineeRunToggle");
  const initializeButton = $("modelInitializeButton");
  const stateText = $("receiveStateText");
  const sourceText = $("teacherSourceText");
  const teacherModelDisplayName = $("teacherModelDisplayName");
  const connectionDot = $("connectionDot");
  const connectionText = $("connectionText");
  const simulationPaused = Boolean(state.receiveMode && isSimulationFrozenSnapshot(state.snapshot));
  if (button) {
    button.textContent = state.receiveMode ? "停止接收" : "启动接收";
    button.disabled = !state.receiveMode && !state.modelInitialized;
    button.classList.toggle("is-running", state.receiveMode);
    button.title = !state.receiveMode && !state.modelInitialized ? "请先完成当前模型的模型初始化" : "";
  }
  if (initializeButton) {
    initializeButton.disabled = state.receiveMode;
    initializeButton.title = state.receiveMode ? "停止接收后才能重新初始化模型" : "";
  }
  if (connectionDot && connectionText) {
    connectionDot.className = extraText ? "off" : simulationPaused ? "frozen" : state.receiveMode ? "ok" : state.frozen ? "" : "ok";
    connectionText.textContent = extraText || (simulationPaused ? "模拟台暂停，已冻结" : state.receiveMode ? "接收中" : state.frozen ? "已冻结" : "在线");
  }
  if (stateText) {
    const label = simulationPaused
      ? "已冻结"
      : state.receiveMode
        ? "运行接收"
      : state.frozen
        ? "已冻结"
        : state.modelInitialized
          ? "已初始化"
          : "待初始化";
    stateText.textContent = extraText || label;
  }
  if (sourceText) {
    const receiveAddress = teacherReceiveAddress();
    const receiveAddressText = displayReceiveAddress(receiveAddress);
    sourceText.title = receiveAddress;
    sourceText.textContent = receiveAddressText || "--";
  }
  if (teacherModelDisplayName) {
    teacherModelDisplayName.textContent = state.teacherModelName || state.teacherModelId || "--";
  }
  const quickBtn = $("renewableQuickConnectBtn");
  if (quickBtn) {
    if (state.receiveMode) {
      quickBtn.hidden = true;
    } else if (!state.modelInitialized) {
      quickBtn.hidden = false;
      quickBtn.dataset.quickAction = "init";
      quickBtn.textContent = typeof translatePhrase === "function" ? translatePhrase("模型初始化") : "模型初始化";
    } else {
      quickBtn.hidden = false;
      quickBtn.dataset.quickAction = "start";
      quickBtn.textContent = typeof translatePhrase === "function" ? translatePhrase("启动接收") : "启动接收";
    }
  }
}

async function refreshTraineeDiagnostics() {
  const container = $("traineeDiagnosticsSummary");
  const updatedEl = $("traineeDiagnosticsUpdatedAt");
  if (!container) return;
  const tr = (text) => (typeof translatePhrase === "function" ? translatePhrase(text) : text);
  if (updatedEl) updatedEl.textContent = tr("刷新中");
  const startedAt = performance.now();
  let diag = null;
  let health = null;
  let errorText = "";
  try {
    const [diagRes, healthRes] = await Promise.allSettled([
      api("/api/trainee/diagnostics"),
      api("/api/health", { modelScoped: false }),
    ]);
    if (diagRes.status === "fulfilled") diag = diagRes.value;
    else errorText = apiErrorText(diagRes.reason);
    if (healthRes.status === "fulfilled") health = healthRes.value;
  } catch (err) {
    errorText = apiErrorText(err);
  }
  const rttMs = Math.round(performance.now() - startedAt);
  const nowStr = new Date().toTimeString().slice(0, 8);
  if (updatedEl) updatedEl.textContent = `${nowStr} (${rttMs} ms)`;

  const snap = state.snapshot || {};
  const compute = snap.compute || {};
  const computeMs = compute.duration_ms ?? compute.elapsed_ms ?? diag?.compute_ms ?? diag?.last_compute_ms;
  const syncAgeSec = diag?.age_seconds ?? diag?.stale_seconds ?? diag?.frame_age_seconds;
  const consecutiveFailures = diag?.consecutive_failures ?? diag?.failure_count ?? 0;
  const rows = [
    [tr("连接地址"), teacherReceiveAddress() || "--"],
    [tr("教员端模型"), state.teacherModelName || state.teacherModelId || "--"],
    [tr("模型初始化"), state.modelInitialized ? tr("已初始化") : tr("待初始化")],
    [tr("数据接收"), state.receiveMode ? tr("接收中") : (state.frozen ? tr("已冻结") : tr("已停止"))],
    [tr("接口往返延迟"), `${rttMs} ms`],
    [tr("最近帧延迟"), Number.isFinite(Number(syncAgeSec)) ? `${Number(syncAgeSec).toFixed(2)} s` : "--"],
    [tr("连续失败次数"), String(consecutiveFailures)],
    [tr("单步求解耗时"), Number.isFinite(Number(computeMs)) ? `${Number(computeMs).toFixed(1)} ms` : "--"],
    [tr("仿真时钟"), `${snap.clock?.time || "--"} (${snap.clock?.state || "stopped"})`],
    [tr("后端服务状态"), health?.status || (health?.ok ? "ok" : (errorText ? tr("异常") : "--"))],
    [tr("前端累计请求"), `${state.frontendDiagnostics?.requestCount || 0}`],
    [tr("最后诊断错误"), String(diag?.last_error || errorText || "—")],
  ];
  container.innerHTML = rows.map(([label, val]) => `
    <div class="trainee-diag-item">
      <dt>${escapeHtml(label)}</dt>
      <dd class="mono-cell">${escapeHtml(String(val ?? "--"))}</dd>
    </div>
  `).join("");
}

function openTraineeDiagnosticsDialog() {
  const dialog = $("traineeDiagnosticsDialog");
  if (!dialog) return;
  if (!dialog.open && typeof dialog.showModal === "function") {
    dialog.showModal();
  }
  refreshTraineeDiagnostics();
}

function closeTraineeDiagnosticsDialog() {
  const dialog = $("traineeDiagnosticsDialog");
  if (dialog?.open) dialog.close();
}

function curveMinute(snapshot) {
  const clock = snapshot.clock || {};
  const absoluteMinute = Number(clock.absolute_minute ?? clock.minute ?? 0) || 0;
  const durationMinutes = curveDisplayConfig(snapshot).durationMinutes;
  return durationMinutes > 0 ? ((absoluteMinute % durationMinutes) + durationMinutes) % durationMinutes : absoluteMinute;
}

function interpolateCurve(points, minute, key, defaultValue = 0) {
  const pairs = (points || [])
    .map((point) => ({ minute: Number(point.minute), value: optionalNumber(point?.[key]) }))
    .filter((point) => Number.isFinite(point.minute) && Number.isFinite(point.value))
    .sort((left, right) => left.minute - right.minute);
  if (!pairs.length) return defaultValue;
  if (pairs.length === 1) return pairs[0].value;
  const target = Number(minute) || 0;
  let left = pairs[0];
  let right = pairs[pairs.length - 1];
  for (let idx = 0; idx < pairs.length - 1; idx += 1) {
    if (pairs[idx].minute <= target && target <= pairs[idx + 1].minute) {
      left = pairs[idx];
      right = pairs[idx + 1];
      break;
    }
  }
  if (target <= pairs[0].minute) return pairs[0].value;
  if (target >= pairs[pairs.length - 1].minute) return pairs[pairs.length - 1].value;
  const span = Math.max(1e-9, right.minute - left.minute);
  return left.value + ((target - left.minute) / span) * (right.value - left.value);
}

function renderTeacherWeather(snapshot) {
  const valuesNow = currentWeatherLoad(snapshot);
  const values = {
    teacherWind: Number.isFinite(valuesNow.windSpeed) ? `${formatNumber(valuesNow.windSpeed)} m/s` : "--",
    teacherSolar: Number.isFinite(valuesNow.solarIrradiance) ? `${formatNumber(valuesNow.solarIrradiance)} W/m2` : "--",
    teacherTemp: `${formatNumber(valuesNow.airTemp)} ℃`,
    teacherLoad: `${formatNumber(valuesNow.loadKw)} kW`,
    teacherWeatherTime: snapshot.clock?.time || "--",
  };
  Object.entries(values).forEach(([id, text]) => {
    const node = $(id);
    if (node) node.textContent = text;
  });
}

function toNumber(value, defaultValue = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : defaultValue;
}

function optionalNumber(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function clamp(value, minValue, maxValue) {
  return Math.min(maxValue, Math.max(minValue, value));
}

function commandNumber(value) {
  const number = Math.abs(value) < 0.0005 ? 0 : value;
  return Number(number.toFixed(3));
}

function weatherMeasurementState(snapshot, measType) {
  const measurements = snapshot.measurements || {};
  const row = (measurements.scada || []).find((item) => (
    item.dev_type === "Environment"
    && item.dev_name === "weather"
    && String(item.meas_type || "").toUpperCase() === measType
  ));
  if (row) {
    const valid = Number(row.valid ?? 1) === 1;
    return { present: true, valid, value: valid ? optionalNumber(row.value) : null };
  }
  return { present: false, valid: false, value: null };
}

function currentWeatherLoad(snapshot = state.snapshot || {}) {
  const curves = snapshot.curves || {};
  const boundary = snapshot.curve_boundary || {};
  const minute = curveMinute(snapshot);
  const weather = curves.weather || [];
  const loads = curves.loads || {};
  const boundaryPoint = boundary.point || {};
  let loadTotal = Object.values(loads).reduce((total, points) => (
    total + interpolateCurve(points, minute, "p_kw", 0)
  ), 0);
  if (!Object.keys(loads).length && Number.isFinite(Number(boundary.load_total))) {
    loadTotal = Number(boundary.load_total);
  }
  if (!Number.isFinite(loadTotal) || loadTotal <= 0) {
    loadTotal = estimateLoadFromDevices(snapshot.devices || []);
  }
  const windMeasurement = weatherMeasurementState(snapshot, "WIND_SPEED");
  const solarMeasurement = weatherMeasurementState(snapshot, "SOLAR_IRRADIANCE");
  const windSpeed = windMeasurement.valid && Number.isFinite(windMeasurement.value)
    ? windMeasurement.value
    : weather.length
      ? interpolateCurve(weather, minute, "wind_speed_mps", null)
      : optionalNumber(boundaryPoint.wind_speed_mps);
  const solarIrradiance = solarMeasurement.valid && Number.isFinite(solarMeasurement.value)
    ? solarMeasurement.value
    : weather.length
      ? interpolateCurve(weather, minute, "solar_irradiance_w_m2", null)
      : optionalNumber(boundaryPoint.solar_irradiance_w_m2);
  return {
    minute: Number(boundary.target_minute ?? minute) || minute,
    windSpeed,
    windSpeedKnown: Number.isFinite(windSpeed),
    solarIrradiance,
    solarIrradianceKnown: Number.isFinite(solarIrradiance),
    airTemp: weather.length ? interpolateCurve(weather, minute, "air_temp_c", 25) : Number(boundaryPoint.air_temp_c ?? 25),
    loadKw: loadTotal,
  };
}

function latestRuntimeLog(snapshot, type) {
  return [...(snapshot.runtime_logs || [])].reverse().find((item) => item?.type === type) || null;
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
  const liveSoc = averageStorageSocRatio(snapshot);
  const logSoc = storageSocPercentFromText(text);
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
    soc: structured.soc
      ?? (Number.isFinite(liveSoc)
        ? liveSoc * 100
        : Number.isFinite(logSoc)
          ? logSoc
          : storageSocPercentFromText(controlText)),
    generation: structured.generation ?? matchedNumber(text, /电源发电总功率\s*([-+\d.]+)/),
    consumption: structured.consumption ?? matchedNumber(text, /用电及充电总功率\s*([-+\d.]+)/),
    balance: structured.balance ?? matchedNumber(text, /功率差额\s*([-+\d.]+)/),
  };
  power.flowGroups = normalizeOverviewFlowGroups(summary.flowGroups, power);
  return power;
}

function formatOverviewNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toFixed(2);
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

function overviewClamp(value, minValue, maxValue) {
  return Math.min(maxValue, Math.max(minValue, value));
}

function overviewLoadFlowColor(greenPowerShare) {
  const percent = overviewClamp(Number(greenPowerShare), 0, 100);
  if (!Number.isFinite(percent)) return "#4978c4";
  const hue = 2 + percent * 1.18;
  return `hsl(${hue.toFixed(1)}, 62%, 42%)`;
}

function overviewFlowStyle(powerValue, maxPower) {
  const power = overviewFlowPowerValue(powerValue);
  const base = Math.max(1, overviewFlowPowerValue(maxPower));
  const active = power > 1e-6;
  const ratio = active ? overviewClamp(Math.sqrt(power / base), 0, 1) : 0;
  const thickness = active ? 2 + ratio * 6 : 2;
  const headSize = active ? 8 + ratio * 9 : 8;
  const headHalf = active ? 5 + ratio * 5 : 5;
  const opacity = active ? 0.58 + ratio * 0.34 : 0.24;
  const duration = active ? 1.4 - ratio * 0.42 : 1.4;
  return {
    active,
    thickness: `${thickness.toFixed(2)}px`,
    headSize: `${headSize.toFixed(2)}px`,
    headHalf: `${headHalf.toFixed(2)}px`,
    opacity: opacity.toFixed(2),
    duration: `${duration.toFixed(2)}s`,
  };
}

function setOverviewFlowVisualElement(element, powerValue, maxPower, color) {
  if (!element) return;
  const visual = overviewFlowStyle(powerValue, maxPower);
  element.dataset.flowActive = visual.active ? "true" : "false";
  element.style.setProperty("--flow-color", color);
  element.style.setProperty("--flow-thickness", visual.thickness);
  element.style.setProperty("--flow-head-size", visual.headSize);
  element.style.setProperty("--flow-head-half", visual.headHalf);
  element.style.setProperty("--flow-opacity", visual.opacity);
  element.style.setProperty("--flow-duration", visual.duration);
}

function setOverviewFlowVisual(id, powerValue, maxPower, color) {
  setOverviewFlowVisualElement($(id), powerValue, maxPower, color);
}

function overviewFlowGroupMeta(group) {
  const status = OVERVIEW_FLOW_STATUS_LABELS[group.status] || "待量测";
  const count = `${group.onlineCount}/${group.totalCount} 台`;
  if (["fuelCell", "electrolyzer", "hydrogenStorage"].includes(group.category)) {
    return `${status} · 数量 ${count}`;
  }
  if (group.category !== "storage") return `${status} · ${count}`;
  const soc = Number.isFinite(group.soc) ? `${formatOverviewNumber(group.soc)}%` : "--";
  return `${status} · SOC ${soc} · ${count}`;
}

function overviewHydrogenActiveTarget(group) {
  const mode = String(group.controlMode || "").trim().toUpperCase();
  if (mode === "FLOW") {
    return {
      label: group.category === "fuelCell" ? "耗气目标" : "产气目标",
      value: overviewGasFlowText(group.targetGasFlow),
    };
  }
  if (["P", "PQ"].includes(mode)) {
    return {
      label: group.category === "fuelCell" ? "发电目标" : "耗电目标",
      value: overviewPowerText(group.targetPower),
    };
  }
  return { label: "有效目标", value: "--" };
}

function renderOverviewFlowGroups(power) {
  const groups = power.flowGroups || {};
  const visibleGroups = OVERVIEW_FLOW_GROUP_DEFINITIONS
    .map((definition) => groups[definition.key])
    .filter((group) => group?.present);
  const maxPower = Math.max(1, ...visibleGroups.map((group) => overviewFlowPowerValue(group.power)));
  const { greenPowerShare } = overviewGreenMetrics(power);

  OVERVIEW_FLOW_GROUP_DEFINITIONS.forEach((definition) => {
    const group = groups[definition.key] || { present: false };
    const node = document.querySelector(`[data-overview-group="${definition.key}"]`);
    const wrapper = document.querySelector(`[data-overview-group-wrapper="${definition.key}"]`);
    if (!node) return;
    node.hidden = !group.present;
    if (wrapper) wrapper.hidden = !group.present;
    if (!group.present) return;
    node.dataset.flowDirection = group.flowDirection;
    node.dataset.operatingState = group.status;
    const powerNode = node.querySelector("[data-overview-power]");
    const targetNode = node.querySelector("[data-overview-target]");
    const maxAvailableNode = node.querySelector("[data-overview-max-available]");
    const gasFlowNode = node.querySelector("[data-overview-gas-flow]");
    const targetGasFlowNode = node.querySelector("[data-overview-target-gas-flow]");
    const gasPressureNode = node.querySelector("[data-overview-gas-pressure]");
    const socNode = node.querySelector("[data-overview-soc]");
    const metaNode = node.querySelector("[data-overview-meta]");
    const countNode = node.querySelector("[data-overview-count]");
    const activeTargetLabelNode = node.querySelector("[data-overview-active-target-label]");
    const activeTargetNode = node.querySelector("[data-overview-active-target]");
    if (powerNode) powerNode.textContent = overviewPowerText(group.power);
    if (targetNode) targetNode.textContent = overviewPowerText(group.targetPower);
    if (maxAvailableNode) maxAvailableNode.textContent = overviewPowerText(group.maxAvailablePower);
    if (gasFlowNode) gasFlowNode.textContent = overviewGasFlowText(group.gasFlow);
    if (targetGasFlowNode) targetGasFlowNode.textContent = overviewGasFlowText(group.targetGasFlow);
    if (gasPressureNode) gasPressureNode.textContent = overviewGasPressureText(group.gasPressure);
    if (socNode) socNode.textContent = overviewPercentText(group.soc);
    if (metaNode) metaNode.textContent = overviewFlowGroupMeta(group);
    if (countNode) countNode.textContent = `${group.onlineCount}/${group.totalCount} 台`;
    const activeTarget = ["fuelCell", "electrolyzer"].includes(definition.key)
      ? overviewHydrogenActiveTarget(group)
      : null;
    if (activeTargetLabelNode) activeTargetLabelNode.textContent = activeTarget?.label || "有效目标";
    if (activeTargetNode) activeTargetNode.textContent = activeTarget?.value || "--";
    const tooltipParts = [
      node.querySelector("span")?.textContent || "设备",
      `当前 ${overviewPowerText(group.power)}`,
    ];
    if (activeTarget) tooltipParts.push(`${activeTarget.label} ${activeTarget.value}`);
    else tooltipParts.push(`目标 ${overviewPowerText(group.targetPower)}`);
    if (["dcWind", "dcSolar", "acWind", "acSolar"].includes(definition.key)) {
      tooltipParts.push(`最大可发 ${overviewPowerText(group.maxAvailablePower)}`);
    }
    if (["fuelCell", "electrolyzer"].includes(definition.key)) {
      tooltipParts.push(`气流实时 ${overviewGasFlowText(group.gasFlow)}`);
    }
    if (definition.key === "hydrogenStorage") {
      tooltipParts.push(`气流量 ${overviewGasFlowText(group.gasFlow)}`);
      tooltipParts.push(`储气压力 ${overviewGasPressureText(group.gasPressure)}`);
      tooltipParts.push(`SOC ${overviewPercentText(group.soc)}`);
    }
    tooltipParts.push(overviewFlowGroupMeta(group));
    node.title = tooltipParts.join(" · ");
    const flowPower = group.flowDirection === "idle" ? 0 : group.power;
    const color = definition.category === "load" ? overviewLoadFlowColor(greenPowerShare) : definition.color;
    setOverviewFlowVisualElement(node, flowPower, maxPower, color);
    if (wrapper) {
      wrapper.dataset.storageFlow = group.status === "discharge" ? "discharge" : group.status === "charge" ? "charge" : "idle";
      wrapper.dataset.operatingState = group.status;
      setOverviewFlowVisualElement(wrapper, flowPower, maxPower, color);
    }
  });

  document.querySelectorAll("[data-overview-region]").forEach((region) => {
    if (region.id === "overviewGridFormingStack") return;
    const regionKey = region.dataset.overviewRegion;
    region.hidden = !visibleGroups.some((group) => group.region === regionKey);
  });
  const formingStack = $("overviewGridFormingStack");
  if (formingStack) formingStack.hidden = !visibleGroups.some((group) => group.region === "forming");

  const hydrogenLinkState = (name, group, value, maxValue, direction, color, present) => {
    const link = document.querySelector(`[data-hydrogen-link="${name}"]`);
    if (!link) return;
    link.hidden = !present;
    link.dataset.flowDirection = direction;
    setOverviewFlowVisualElement(link, value, maxValue, color);
  };
  const fuelCellGroup = groups.fuelCell;
  const hydrogenStorageGroup = groups.hydrogenStorage;
  const electrolyzerGroup = groups.electrolyzer;
  const maxHydrogenPower = Math.max(
    1,
    overviewFlowPowerValue(fuelCellGroup?.power),
    overviewFlowPowerValue(electrolyzerGroup?.power),
  );
  const maxHydrogenFlow = Math.max(
    1,
    overviewFlowPowerValue(fuelCellGroup?.gasFlow),
    overviewFlowPowerValue(electrolyzerGroup?.gasFlow),
    overviewFlowPowerValue(hydrogenStorageGroup?.gasFlow),
  );
  hydrogenLinkState(
    "fuel-cell-electric",
    fuelCellGroup,
    fuelCellGroup?.power,
    maxHydrogenPower,
    Number(fuelCellGroup?.power) >= 0 ? "left" : "right",
    "#16856a",
    Boolean(fuelCellGroup?.present),
  );
  hydrogenLinkState(
    "fuel-cell-gas",
    fuelCellGroup,
    fuelCellGroup?.gasFlow,
    maxHydrogenFlow,
    Number(fuelCellGroup?.gasFlow) >= 0 ? "left" : "right",
    "#287ea0",
    Boolean(fuelCellGroup?.present && hydrogenStorageGroup?.present),
  );
  hydrogenLinkState(
    "electrolyzer-gas",
    electrolyzerGroup,
    electrolyzerGroup?.gasFlow,
    maxHydrogenFlow,
    Number(electrolyzerGroup?.gasFlow) >= 0 ? "left" : "right",
    "#287ea0",
    Boolean(electrolyzerGroup?.present && hydrogenStorageGroup?.present),
  );
  hydrogenLinkState(
    "electrolyzer-electric",
    electrolyzerGroup,
    electrolyzerGroup?.power,
    maxHydrogenPower,
    Number(electrolyzerGroup?.power) >= 0 ? "left" : "right",
    "#b56a22",
    Boolean(electrolyzerGroup?.present),
  );

  const converterGroup = groups.acdcConverter;
  const aggregateTrunkPower = visibleGroups
    .filter((group) => !["load", "converter", "electrolyzer", "hydrogenStorage"].includes(group.category))
    .reduce((total, group) => total + overviewFlowPowerValue(group.power), 0);
  const trunkPower = converterGroup?.present && Number.isFinite(converterGroup.power)
    ? converterGroup.power
    : aggregateTrunkPower;
  const trunk = $("overviewEnergyMainTrunk");
  if (trunk) trunk.dataset.flowDirection = converterGroup?.flowDirection || "toAc";
  setOverviewFlowVisual("overviewEnergyMainTrunk", trunkPower, maxPower, "#2f9e62");
}

function renderEnergyFlowVisuals(power) {
  renderOverviewFlowGroups(power);
}

function setOverviewText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function setOptionalText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function overviewBottomHeightBounds() {
  const dashboard = document.querySelector(".overview-dashboard");
  const dashboardHeight = dashboard?.getBoundingClientRect().height || 0;
  const dashboardStyle = dashboard ? getComputedStyle(dashboard) : null;
  const mainGrid = document.querySelector(".overview-main-grid");
  const statusHeight = document.querySelector(".overview-status-panel")?.getBoundingClientRect().height || 68;
  const splitterHeight = $("overviewBottomSplitter")?.getBoundingClientRect().height || 10;
  const mainMinHeight = Number.parseFloat(mainGrid ? getComputedStyle(mainGrid).minHeight : "") || 180;
  const rowGap = Number.parseFloat(dashboardStyle?.rowGap || dashboardStyle?.gap || "") || 12;
  const reservedHeight = statusHeight + mainMinHeight + splitterHeight + rowGap * 3;
  const dynamicMax = dashboardHeight > 0 ? dashboardHeight - reservedHeight : OVERVIEW_BOTTOM_MAX_HEIGHT;
  const maxHeight = Math.max(
    OVERVIEW_BOTTOM_MIN_HEIGHT,
    Math.min(OVERVIEW_BOTTOM_MAX_HEIGHT, dynamicMax),
  );
  return { min: OVERVIEW_BOTTOM_MIN_HEIGHT, max: maxHeight };
}

function applyOverviewBottomHeight(value, persist = false) {
  const bounds = overviewBottomHeightBounds();
  const numericValue = Number(value);
  const nextHeight = Math.round(clamp(
    Number.isFinite(numericValue) ? numericValue : OVERVIEW_BOTTOM_DEFAULT_HEIGHT,
    bounds.min,
    bounds.max,
  ));
  state.overviewBottomHeight = nextHeight;
  const dashboard = document.querySelector(".overview-dashboard");
  if (dashboard) dashboard.style.setProperty("--overview-bottom-height", `${nextHeight}px`);
  const splitter = $("overviewBottomSplitter");
  if (splitter) {
    splitter.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
    splitter.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
    splitter.setAttribute("aria-valuenow", String(nextHeight));
    splitter.setAttribute("aria-valuetext", `${nextHeight}px`);
  }
  if (persist) localStorage.setItem(OVERVIEW_BOTTOM_HEIGHT_KEY, String(nextHeight));
}

function beginOverviewBottomSplitterDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const splitter = $("overviewBottomSplitter");
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  if (!splitter || !bottomGrid) return;
  event.preventDefault();
  const currentHeight = bottomGrid.getBoundingClientRect().height || state.overviewBottomHeight;
  state.overviewBottomSplitDrag = {
    pointerId: event.pointerId,
    startY: event.clientY,
    startHeight: currentHeight,
  };
  splitter.classList.add("is-dragging");
  document.body.classList.add("is-overview-splitter-dragging");
  if (splitter.setPointerCapture && event.pointerId !== undefined) {
    try {
      splitter.setPointerCapture(event.pointerId);
    } catch (error) {
      // Synthetic or cancelled pointer events do not always have capturable pointers.
    }
  }
}

function handleOverviewBottomSplitterDrag(event) {
  const drag = state.overviewBottomSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  event.preventDefault();
  applyOverviewBottomHeight(drag.startHeight - (event.clientY - drag.startY));
}

function finishOverviewBottomSplitterDrag(event) {
  const drag = state.overviewBottomSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event?.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  const splitter = $("overviewBottomSplitter");
  if (splitter) {
    splitter.classList.remove("is-dragging");
    if (splitter.releasePointerCapture && drag.pointerId !== undefined) {
      try {
        splitter.releasePointerCapture(drag.pointerId);
      } catch (error) {
        // Pointer capture may already be gone if the pointer left the window.
      }
    }
  }
  document.body.classList.remove("is-overview-splitter-dragging");
  state.overviewBottomSplitDrag = null;
  applyOverviewBottomHeight(state.overviewBottomHeight, true);
}

function handleOverviewBottomSplitterKeydown(event) {
  let nextHeight = null;
  if (event.key === "ArrowUp") nextHeight = state.overviewBottomHeight + 16;
  if (event.key === "ArrowDown") nextHeight = state.overviewBottomHeight - 16;
  if (event.key === "PageUp") nextHeight = state.overviewBottomHeight + 48;
  if (event.key === "PageDown") nextHeight = state.overviewBottomHeight - 48;
  if (event.key === "Home") nextHeight = OVERVIEW_BOTTOM_MIN_HEIGHT;
  if (event.key === "End") nextHeight = overviewBottomHeightBounds().max;
  if (nextHeight === null) return;
  event.preventDefault();
  applyOverviewBottomHeight(nextHeight, true);
}

function initOverviewBottomSplitter() {
  const splitter = $("overviewBottomSplitter");
  if (!splitter) return;
  if (splitter.dataset.splitterReady === "true") return;
  splitter.dataset.splitterReady = "true";
  applyOverviewBottomHeight(state.overviewBottomHeight);
  splitter.addEventListener("pointerdown", beginOverviewBottomSplitterDrag);
  splitter.addEventListener("keydown", handleOverviewBottomSplitterKeydown);
  window.addEventListener("pointermove", handleOverviewBottomSplitterDrag);
  window.addEventListener("pointerup", finishOverviewBottomSplitterDrag);
  window.addEventListener("pointercancel", finishOverviewBottomSplitterDrag);
  window.addEventListener("resize", () => applyOverviewBottomHeight(state.overviewBottomHeight, true));
}

function overviewBottomColumnRatioBounds() {
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  const splitter = $("overviewBottomColumnSplitter");
  const gridWidth = bottomGrid?.getBoundingClientRect().width || 0;
  const splitterWidth = splitter?.getBoundingClientRect().width || 12;
  const contentWidth = Math.max(0, gridWidth - splitterWidth);
  if (contentWidth < OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX * 2) {
    return { min: 0, max: 100, contentWidth };
  }
  const minRatio = (OVERVIEW_BOTTOM_COLUMN_MIN_WIDTH_PX / contentWidth) * 100;
  return { min: minRatio, max: 100 - minRatio, contentWidth };
}

function applyOverviewBottomColumnRatio(ratio, persist = false) {
  const numericRatio = Number(ratio);
  const requestedRatio = Number.isFinite(numericRatio) ? numericRatio : OVERVIEW_BOTTOM_COLUMN_DEFAULT_RATIO;
  const bounds = overviewBottomColumnRatioBounds();
  const nextRatio = Number(clamp(requestedRatio, bounds.min, bounds.max).toFixed(2));
  state.overviewBottomColumnRatio = nextRatio;
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  if (bottomGrid) {
    bottomGrid.style.setProperty("--overview-bottom-left-ratio", `${nextRatio}fr`);
    bottomGrid.style.setProperty("--overview-bottom-right-ratio", `${Number((100 - nextRatio).toFixed(2))}fr`);
  }
  const splitter = $("overviewBottomColumnSplitter");
  if (splitter) {
    splitter.setAttribute("aria-valuemin", bounds.min.toFixed(2));
    splitter.setAttribute("aria-valuemax", bounds.max.toFixed(2));
    splitter.setAttribute("aria-valuenow", String(nextRatio));
    splitter.setAttribute("aria-valuetext", `左侧 ${nextRatio.toFixed(2)}%，右侧 ${(100 - nextRatio).toFixed(2)}%`);
  }
  if (persist) localStorage.setItem(OVERVIEW_BOTTOM_COLUMN_RATIO_KEY, String(nextRatio));
}

function beginOverviewBottomColumnSplitterDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const splitter = $("overviewBottomColumnSplitter");
  const bottomGrid = document.querySelector(".overview-bottom-grid");
  if (!splitter || !bottomGrid) return;
  const bounds = overviewBottomColumnRatioBounds();
  if (bounds.contentWidth <= 0) return;
  event.preventDefault();
  state.overviewBottomColumnSplitDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startRatio: state.overviewBottomColumnRatio,
    contentWidth: bounds.contentWidth,
  };
  splitter.classList.add("is-dragging");
  document.body.classList.add("is-overview-column-splitter-dragging");
  if (splitter.setPointerCapture && event.pointerId !== undefined) {
    try {
      splitter.setPointerCapture(event.pointerId);
    } catch (error) {
      // Synthetic or cancelled pointer events do not always have capturable pointers.
    }
  }
}

function handleOverviewBottomColumnSplitterDrag(event) {
  const drag = state.overviewBottomColumnSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  event.preventDefault();
  const deltaRatio = ((event.clientX - drag.startX) / drag.contentWidth) * 100;
  applyOverviewBottomColumnRatio(drag.startRatio + deltaRatio);
}

function finishOverviewBottomColumnSplitterDrag(event) {
  const drag = state.overviewBottomColumnSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event?.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  const splitter = $("overviewBottomColumnSplitter");
  if (splitter) {
    splitter.classList.remove("is-dragging");
    if (splitter.releasePointerCapture && drag.pointerId !== undefined) {
      try {
        splitter.releasePointerCapture(drag.pointerId);
      } catch (error) {
        // Pointer capture may already be gone if the pointer left the window.
      }
    }
  }
  document.body.classList.remove("is-overview-column-splitter-dragging");
  state.overviewBottomColumnSplitDrag = null;
  applyOverviewBottomColumnRatio(state.overviewBottomColumnRatio, true);
}

function handleOverviewBottomColumnSplitterKeydown(event) {
  const bounds = overviewBottomColumnRatioBounds();
  let nextRatio = null;
  if (event.key === "ArrowLeft") nextRatio = state.overviewBottomColumnRatio - 2;
  if (event.key === "ArrowRight") nextRatio = state.overviewBottomColumnRatio + 2;
  if (event.key === "PageUp") nextRatio = state.overviewBottomColumnRatio - 8;
  if (event.key === "PageDown") nextRatio = state.overviewBottomColumnRatio + 8;
  if (event.key === "Home") nextRatio = bounds.min;
  if (event.key === "End") nextRatio = bounds.max;
  if (nextRatio === null) return;
  event.preventDefault();
  applyOverviewBottomColumnRatio(nextRatio, true);
}

function initOverviewBottomColumnSplitter() {
  const splitter = $("overviewBottomColumnSplitter");
  if (!splitter) return;
  if (splitter.dataset.splitterReady === "true") return;
  splitter.dataset.splitterReady = "true";
  applyOverviewBottomColumnRatio(state.overviewBottomColumnRatio);
  splitter.addEventListener("pointerdown", beginOverviewBottomColumnSplitterDrag);
  splitter.addEventListener("keydown", handleOverviewBottomColumnSplitterKeydown);
  window.addEventListener("pointermove", handleOverviewBottomColumnSplitterDrag);
  window.addEventListener("pointerup", finishOverviewBottomColumnSplitterDrag);
  window.addEventListener("pointercancel", finishOverviewBottomColumnSplitterDrag);
  window.addEventListener("resize", () => applyOverviewBottomColumnRatio(overviewInitialBottomColumnRatio()));
}

function verticalSplitDefaultRatio(splitId) {
  return VERTICAL_SPLIT_DEFAULTS[splitId] || VERTICAL_SPLIT_DEFAULT_RATIO;
}

function verticalSplitContainer(splitId) {
  return Array.from(document.querySelectorAll("[data-vertical-split]"))
    .find((container) => container.dataset.verticalSplit === splitId) || null;
}

function verticalSplitBounds(container) {
  if (!container) return { min: 20, max: 80 };
  const rect = container.getBoundingClientRect();
  const splitter = container.querySelector("[data-vertical-splitter]");
  const splitterHeight = splitter?.getBoundingClientRect().height || 10;
  const availableHeight = rect.height > 0 ? rect.height - splitterHeight : 0;
  if (availableHeight <= 0) return { min: 20, max: 80 };
  const minTop = Number(container.dataset.verticalSplitMinTop) || VERTICAL_SPLIT_MIN_TOP_PX;
  const minBottom = Number(container.dataset.verticalSplitMinBottom) || VERTICAL_SPLIT_MIN_BOTTOM_PX;
  const minRatio = clamp((minTop / availableHeight) * 100, 8, 88);
  const maxRatio = clamp(100 - (minBottom / availableHeight) * 100, 12, 92);
  if (minRatio <= maxRatio) return { min: minRatio, max: maxRatio };
  if (container.hasAttribute("data-vertical-split-min-bottom")) {
    const bottomPriorityRatio = clamp(maxRatio, 8, 92);
    return { min: bottomPriorityRatio, max: bottomPriorityRatio };
  }
  const centerRatio = clamp(50, 8, 92);
  return { min: centerRatio, max: centerRatio };
}

function applyVerticalSplit(splitId, ratio, persist = false, redraw = false) {
  const container = verticalSplitContainer(splitId);
  if (!container) return;
  const bounds = verticalSplitBounds(container);
  const numericRatio = Number(ratio);
  const nextRatio = Math.round(clamp(
    Number.isFinite(numericRatio) ? numericRatio : verticalSplitDefaultRatio(splitId),
    bounds.min,
    bounds.max,
  ) * 10) / 10;
  state.verticalSplitRatios[splitId] = nextRatio;
  container.style.setProperty("--vertical-split-top", `${nextRatio}%`);
  const splitter = container.querySelector(`[data-vertical-splitter="${splitId}"]`);
  if (splitter) {
    splitter.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
    splitter.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
    splitter.setAttribute("aria-valuenow", String(nextRatio));
    splitter.setAttribute("aria-valuetext", `${nextRatio}%`);
  }
  if (persist) localStorage.setItem(VERTICAL_SPLIT_STORAGE_KEY, JSON.stringify(state.verticalSplitRatios));
  if (redraw) redrawVerticalSplitContent(splitId);
}

function redrawVerticalSplitContent(splitId) {
  requestAnimationFrame(() => {
    if (splitId === "trainee-curves") drawCurveDisplay(state.snapshot || {});
    if (splitId === "trainee-measurements") drawMeasurementTraceChart();
    if (splitId === "trainee-commands") drawCommandTraceChart();
    if (splitId === "trainee-renewable" && state.renewableControl.detailTab === "trend") drawRenewableTrendChart();
  });
}

function beginVerticalSplitterDrag(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const splitter = event.currentTarget;
  const splitId = splitter?.dataset.verticalSplitter || "";
  const container = verticalSplitContainer(splitId);
  if (!splitter || !container) return;
  event.preventDefault();
  const containerRect = container.getBoundingClientRect();
  const splitterRect = splitter.getBoundingClientRect();
  state.verticalSplitDrag = {
    splitId,
    pointerId: event.pointerId,
    startY: event.clientY,
    startTopPx: splitterRect.top - containerRect.top,
    availableHeight: Math.max(1, containerRect.height - splitterRect.height),
  };
  splitter.classList.add("is-dragging");
  document.body.classList.add("is-vertical-splitter-dragging");
  if (splitter.setPointerCapture && event.pointerId !== undefined) {
    try {
      splitter.setPointerCapture(event.pointerId);
    } catch (error) {
      // Pointer capture can fail for synthetic events during tests.
    }
  }
}

function handleVerticalSplitterDrag(event) {
  const drag = state.verticalSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  event.preventDefault();
  const nextTopPx = drag.startTopPx + (event.clientY - drag.startY);
  applyVerticalSplit(drag.splitId, (nextTopPx / drag.availableHeight) * 100, false, true);
}

function finishVerticalSplitterDrag(event) {
  const drag = state.verticalSplitDrag;
  if (!drag) return;
  if (drag.pointerId !== undefined && event?.pointerId !== undefined && drag.pointerId !== event.pointerId) return;
  const splitter = document.querySelector(`[data-vertical-splitter="${drag.splitId}"]`);
  if (splitter) {
    splitter.classList.remove("is-dragging");
    if (splitter.releasePointerCapture && drag.pointerId !== undefined) {
      try {
        splitter.releasePointerCapture(drag.pointerId);
      } catch (error) {
        // Pointer capture may already be released.
      }
    }
  }
  document.body.classList.remove("is-vertical-splitter-dragging");
  state.verticalSplitDrag = null;
  applyVerticalSplit(drag.splitId, state.verticalSplitRatios[drag.splitId], true, true);
}

function handleVerticalSplitterKeydown(event) {
  const splitId = event.currentTarget?.dataset.verticalSplitter || "";
  const currentRatio = state.verticalSplitRatios[splitId] || verticalSplitDefaultRatio(splitId);
  const bounds = verticalSplitBounds(verticalSplitContainer(splitId));
  let nextRatio = null;
  if (event.key === "ArrowUp") nextRatio = currentRatio - 2;
  if (event.key === "ArrowDown") nextRatio = currentRatio + 2;
  if (event.key === "PageUp") nextRatio = currentRatio - 8;
  if (event.key === "PageDown") nextRatio = currentRatio + 8;
  if (event.key === "Home") nextRatio = bounds.min;
  if (event.key === "End") nextRatio = bounds.max;
  if (nextRatio === null) return;
  event.preventDefault();
  applyVerticalSplit(splitId, nextRatio, true, true);
}

function initVerticalSplitters() {
  document.querySelectorAll("[data-vertical-splitter]").forEach((splitter) => {
    const splitId = splitter.dataset.verticalSplitter || "";
    if (!splitId) return;
    applyVerticalSplit(splitId, state.verticalSplitRatios[splitId] || verticalSplitDefaultRatio(splitId));
    if (splitter.dataset.verticalSplitterReady === "true") return;
    splitter.dataset.verticalSplitterReady = "true";
    splitter.addEventListener("pointerdown", beginVerticalSplitterDrag);
    splitter.addEventListener("keydown", handleVerticalSplitterKeydown);
    splitter.addEventListener("dblclick", () => {
      applyVerticalSplit(splitId, verticalSplitDefaultRatio(splitId), true, true);
    });
  });
  if (document.body.dataset.verticalSplitterResizeReady === "true") return;
  document.body.dataset.verticalSplitterResizeReady = "true";
  window.addEventListener("pointermove", handleVerticalSplitterDrag);
  window.addEventListener("pointerup", finishVerticalSplitterDrag);
  window.addEventListener("pointercancel", finishVerticalSplitterDrag);
  window.addEventListener("resize", () => {
    document.querySelectorAll("[data-vertical-split]").forEach((container) => {
      const splitId = container.dataset.verticalSplit || "";
      applyVerticalSplit(splitId, state.verticalSplitRatios[splitId], true, true);
    });
  });
}

function overviewClockText(snapshot) {
  const clock = snapshot.clock || {};
  const timeText = clock.time || "--";
  const mode = curveDisplayMode(snapshot);
  const dayCount = curveDisplayModeDayCount(mode);
  if (dayCount <= 1) return timeText;
  const dayIndex = Math.floor((Number(clock.absolute_minute ?? clock.minute ?? 0) || 0) / 1440) % dayCount;
  if (mode !== "year") return `第${dayIndex + 1}天 ${timeText}`;
  const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let month = 0;
  let day = dayIndex;
  while (month < monthDays.length - 1 && day >= monthDays[month]) {
    day -= monthDays[month];
    month += 1;
  }
  return `${String(month + 1).padStart(2, "0")}-${String(day + 1).padStart(2, "0")} ${timeText}`;
}

function renderTraineeOverviewEvents() {
  const container = $("traineeOverviewEvents");
  if (!container) return;
  const logs = state.runtimeLogs.slice(0, 8);
  setOverviewText("overviewEventCount", `${logs.length} 条`);
  const renderKey = logs.length
    ? logs.map((item) => `${item.seq ?? ""}:${item.wall_time || ""}:${item.type || ""}:${item.result || ""}`).join("|")
    : "__empty__";
  if (container.dataset.eventsKey === renderKey) return;
  container.dataset.eventsKey = renderKey;
  if (logs.length) {
    container.innerHTML = logs.map((item) => `
      <div class="overview-event-item is-clickable-row" data-overview-event-jump="history" title="点击查看运行日志">
        <time>${escapeHtml(item.wall_time || "--")}</time>
        <strong>${escapeHtml(item.type || "运行")}</strong>
        <span title="${escapeHtml(runtimeLogDetailText(item.detail))}">${escapeHtml(item.result || runtimeLogDetailText(item.detail) || "完成")}</span>
      </div>
    `).join("");
    return;
  }
  container.innerHTML = '<div class="overview-event-item"><time>--</time><strong>系统</strong><span>等待接收教员台数据</span></div>';
}

function renderTraineeOverviewDashboard(snapshot) {
  const clock = snapshot.clock || {};
  const measurements = measurementDisplayRows(snapshot);
  const validCount = measurements.filter((item) => Number(item.valid) === 1).length;
  const totalMeasurements = measurements.length;
  const weather = currentWeatherLoad(snapshot);
  const power = parsePowerFlowOverview(snapshot);
  const receiveDot = $("overviewReceiveDot");
  if (receiveDot) {
    receiveDot.classList.toggle("is-running", state.receiveMode);
    receiveDot.classList.toggle("is-paused", state.frozen && !state.receiveMode);
  }
  setOverviewText("overviewMode", curveDisplayModeLabel(snapshot));
  const effectiveStepSeconds = Number(
    clock.effective_step_seconds
      ?? snapshot.system_parameters?.effective_step_seconds
      ?? ((clock.step_seconds ?? 1) * (clock.speed ?? 1)),
  );
  setOverviewText("overviewStep", formatTraineeClockDuration(effectiveStepSeconds));
  setOverviewText("measureCount", `${totalMeasurements} 点`);
  setOverviewText("validCount", `${validCount} 可用`);

  setOverviewText("teacherWind", Number.isFinite(weather.windSpeed) ? `${formatOverviewNumber(weather.windSpeed)} m/s` : "--");
  setOverviewText("teacherSolar", Number.isFinite(weather.solarIrradiance) ? `${formatOverviewNumber(weather.solarIrradiance)} W/m²` : "--");
  setOverviewText("teacherTemp", `${formatOverviewNumber(weather.airTemp)} ℃`);
  setOverviewText("teacherLoad", overviewPowerText(weather.loadKw));
  setOverviewText("teacherWeatherTime", overviewClockText(snapshot));

  const { greenPower, greenPowerShare } = overviewGreenMetrics(power);
  setOverviewText("overviewFlowGreenPower", overviewPowerText(greenPower));
  setOverviewText("overviewFlowGreenShare", overviewPercentText(greenPowerShare));
  renderOverviewFlowGroups(power);
  renderTraineeOverviewEvents();
}

function renderActiveTraineePage(snapshot = state.snapshot || {}, force = false) {
  const activePage = currentPageName();
  if (activePage !== "diagram") {
    hideDiagramTooltip(state.pageSections?.diagram?.querySelector?.("#modelDiagramCanvas") || null);
  }
  if (activePage === "overview") {
    renderTeacherWeather(snapshot);
    renderTraineeOverviewDashboard(snapshot);
    initOverviewBottomSplitter();
    initOverviewBottomColumnSplitter();
    return;
  }
  if (activePage === "model") {
    syncModelSubtabDom();
    if (state.activeModelSubtab === "manual-changes") {
      renderManualDefinitionChanges();
      const activeDefinitionRevision = Number(snapshot?.static_meta?.definitions?.revision) || 0;
      if (
        (
          state.manualDefinitionChangesLoadedModelId !== state.activeModelId
          || (activeDefinitionRevision && activeDefinitionRevision !== state.manualDefinitionChangesRevision)
        )
        && !state.manualDefinitionChangesLoading
        && !state.manualDefinitionChangesResetting
        && !state.manualDefinitionChangesRetrying
      ) {
        loadManualDefinitionChanges();
      }
      return;
    }
    renderTraineeModelPage(snapshot);
    return;
  }
  if (activePage === "diagram") {
    renderModelDiagramPage(snapshot);
    return;
  }
  if (activePage === "curves") {
    renderCurveDisplay(snapshot, force);
    return;
  }
  if (activePage === "measurements") {
    renderMeasurements(snapshot);
    return;
  }
  if (activePage === "commands") {
    renderCombinedControlPage();
    return;
  }
  if (activePage === "renewable") {
    renderRenewableControl(snapshot);
    return;
  }
  if (activePage === "manual-changes") {
    renderManualDefinitionChanges();
    const activeDefinitionRevision = Number(snapshot?.static_meta?.definitions?.revision) || 0;
    if (
      (
        state.manualDefinitionChangesLoadedModelId !== state.activeModelId
        || (activeDefinitionRevision && activeDefinitionRevision !== state.manualDefinitionChangesRevision)
      )
      && !state.manualDefinitionChangesLoading
      && !state.manualDefinitionChangesResetting
      && !state.manualDefinitionChangesRetrying
    ) {
      loadManualDefinitionChanges();
    }
    return;
  }
  if (activePage === "parameters") {
    renderWebRuntimeSettings();
    if (state.webRuntimeLoadedModelId !== state.activeModelId && !state.webRuntimeLoading) {
      loadWebRuntimeSettings();
    }
    return;
  }
  if (activePage === "history") {
    renderHistory();
  }
}

