// 教员端前端模块：API 通信层、模型生命周期管理与学员交互链接。

function apiErrorPayload(error) {
  if (error?.payload && typeof error.payload === "object") return error.payload;
  try {
    const parsed = JSON.parse(error?.message || "");
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch (_parseError) {
    return null;
  }
}

function apiErrorText(error) {
  return apiErrorPayload(error)?.error || error?.message || "操作失败";
}

function modelKey(value) {
  const text = String(value ?? "").trim();
  const cleaned = Array.from(text).map((char) => (
    /[\p{L}\p{N}_-]/u.test(char) ? char : "_"
  )).join("").replace(/^_+|_+$/g, "");
  return (cleaned || "default").toLocaleLowerCase();
}

function normalizeModels(models) {
  const seen = new Set();
  const unique = [];
  (models || []).forEach((model) => {
    const keys = [modelKey(model.id), modelKey(model.name || model.id)];
    if (keys.some((key) => seen.has(key))) return;
    keys.forEach((key) => seen.add(key));
    unique.push(model);
  });
  return unique;
}

function isModelNameTaken(name) {
  const key = modelKey(name);
  return normalizeModels(state.models).some((model) => (
    modelKey(model.id) === key || modelKey(model.name || model.id) === key
  ));
}

function uniqueCloneName(baseName) {
  const base = String(baseName || "model").trim().replace(/\s+/g, "_") || "model";
  const taken = new Set();
  normalizeModels(state.models).forEach((model) => {
    taken.add(modelKey(model.id));
    taken.add(modelKey(model.name || model.id));
  });
  const first = `${base}_copy`;
  if (!taken.has(modelKey(first))) return first;
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${base}_copy_${index}`;
    if (!taken.has(modelKey(candidate))) return candidate;
  }
  return `${base}_copy_${Date.now()}`;
}

function modelCloneDefaultName() {
  const active = state.models.find((model) => model.id === state.activeModelId) || state.models[0] || {};
  const base = String(active.name || active.id || "model").replace(/\s+/g, "_");
  return uniqueCloneName(base);
}

function setCloneModelBusy(isBusy) {
  const confirm = $("confirmCloneModel");
  const input = $("cloneModelName");
  if (confirm) {
    confirm.disabled = isBusy;
    confirm.textContent = isBusy ? "复制中" : "复制";
  }
  if (input) input.disabled = isBusy;
}

async function cloneCurrentModel() {
  const input = $("cloneModelName");
  const name = String(input?.value || "").trim();
  if (!validateCloneModelName(true)) {
    input?.focus();
    return;
  }
  setCloneModelBusy(true);
  setCloneModelMessage("正在复制模型文件夹...");
  try {
    const sourceModelId = state.cloneSourceModelId || state.activeModelId || "";
    const result = await api("/api/models/clone", {
      modelScoped: false,
      controlPlane: true,
      method: "POST",
      body: JSON.stringify({ model_id: sourceModelId, name }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.active_model_id || name;
    state.selectedManagementModelId = newModelId;
    closeCloneModelDialog();
    renderModelSelector();
    renderModelManagementList();
  } catch (error) {
    setCloneModelMessage(apiErrorText(error), "error");
  } finally {
    setCloneModelBusy(false);
    if (!$("cloneModelDialog").hidden) validateCloneModelName();
  }
}

function setImportModelMessage(text, kind = "") {
  const message = $("importModelMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function suggestedImportModelName(filename) {
  return String(filename || "导入模型")
    .replace(/\.zip$/i, "")
    .replace(/_definitions_\d{8}_\d{6}$/i, "")
    .replace(/_definitions$/i, "")
    .trim() || "导入模型";
}

function validateImportModelName(showBlank = false) {
  const input = $("importModelName");
  const confirm = $("confirmImportModel");
  if (importModelCreationComplete) {
    if (confirm) confirm.disabled = true;
    return true;
  }
  const name = String(input?.value || "").trim();
  if (!name) {
    if (confirm) confirm.disabled = true;
    setImportModelMessage(showBlank ? "请输入新模型名称。" : "", showBlank ? "error" : "");
    return false;
  }
  if (isModelNameTaken(name)) {
    if (confirm) confirm.disabled = true;
    setImportModelMessage(`模型已存在：${name}，请输入新的模型名称。`, "error");
    return false;
  }
  if (confirm) confirm.disabled = false;
  setImportModelMessage("");
  return true;
}

function openImportModelDialog(file) {
  const dialog = $("importModelDialog");
  const input = $("importModelName");
  if (!dialog || !input || !file) return;
  pendingImportDefinitionFile = file;
  importModelCreationComplete = false;
  renderModelPreflightResult("importModel", null);
  const active = state.models.find((model) => model.id === state.activeModelId) || state.models[0] || {};
  $("importModelFilename").textContent = file.name;
  $("importTemplateModelName").textContent = active.name || active.id || "当前模型";
  input.value = suggestedImportModelName(file.name);
  dialog.hidden = false;
  validateImportModelName();
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

function closeImportModelDialog() {
  const dialog = $("importModelDialog");
  if (dialog) dialog.hidden = true;
  pendingImportDefinitionFile = null;
  importModelCreationComplete = false;
  renderModelPreflightResult("importModel", null);
  const fileInput = $("importDefinitionsInput");
  if (fileInput) fileInput.value = "";
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 32768;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function setImportModelBusy(isBusy) {
  const confirm = $("confirmImportModel");
  const input = $("importModelName");
  const button = $("importDefinitionsButton");
  const cancel = $("cancelImportModel");
  const disabled = isBusy || importModelCreationComplete;
  if (confirm) {
    confirm.disabled = disabled;
    confirm.textContent = importModelCreationComplete ? "已导入" : (isBusy ? "预校核中" : "导入");
  }
  if (input) input.disabled = disabled;
  if (button) button.disabled = isBusy;
  if (cancel) cancel.textContent = importModelCreationComplete ? "关闭" : "取消";
}

async function importDefinitionModel() {
  const file = pendingImportDefinitionFile;
  const input = $("importModelName");
  const name = String(input?.value || "").trim();
  if (!file || !validateImportModelName(true)) {
    input?.focus();
    return;
  }
  renderModelPreflightResult("importModel", null);
  setImportModelBusy(true);
  setImportModelMessage("正在预校核必要字段、E/SVG 匹配性和潮流收敛性；通过后才正式写入...");
  try {
    const dataBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const result = await api("/api/models/import-definitions", {
      modelScoped: false,
      controlPlane: true,
      method: "POST",
      body: JSON.stringify({
        create_model: true,
        name,
        filename: file.name,
        data_base64: dataBase64,
      }),
    });
    state.models = normalizeModels(Array.isArray(result.models) ? result.models : []);
    const newModelId = result.model?.id || result.active_model_id || name;
    renderModelPreflightResult("importModel", result.validation);
    importModelCreationComplete = true;
    state.selectedManagementModelId = newModelId;
    renderModelSelector();
    renderModelManagementList();
    setImportModelMessage("定义包预校核通过并已正式导入。", "ok");
    setModelManagementMessage("定义包预校核通过并已正式导入。", "ok");
  } catch (error) {
    renderModelPreflightResult("importModel", apiErrorPayload(error)?.validation);
    const message = apiErrorText(error);
    if (message.includes("已存在")) await loadModels();
    setImportModelMessage(
      message.includes("已存在") ? `${message}，请输入新的模型名称。` : message,
      "error",
    );
  } finally {
    setImportModelBusy(false);
  }
}

const SIMULATOR_PAGE_ROUTES = {
  "/": "overview",
  "/overview": "overview",
  "/model": "model",
  "/diagram": "diagram",
  "/curves": "curves",
  "/faults": "faults",
  "/modes": "modes",
  "/parameters": "parameters",
  "/manual-changes": "manual-changes",
  "/runtime": "runtime",
  "/measurements": "measurements",
  "/logs": "logs",
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
  return SIMULATOR_PAGE_ROUTES[normalizePagePath(location.pathname)] || fallback;
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
  const previousPage = state.activePage || currentPageName();
  if (previousPage === "curves" && target !== "curves") cancelCurveRequests();
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
    renderActiveSimulatorPage(state.snapshot, true);
    if (target === "manual-changes") loadManualDefinitionChanges();
    if (state.snapshot && !hasStaticSnapshotPayload(state.snapshot, staticSnapshotKeysForPage(target))) {
      refresh();
    }
  });
}

function captureServiceSuggestion(payload) {
  const suggestion = payload?.service_suggestion;
  const host = String(suggestion?.host || "").trim();
  const port = Number(suggestion?.port);
  if (host && Number.isInteger(port) && port >= 1 && port <= 65535) {
    state.serviceSuggestion = { host, port };
  }
  return state.serviceSuggestion;
}

function modelServiceEndpoint(model) {
  const service = model?.service || {};
  const baseUrl = String(service.base_url || "").trim();
  let parsedBaseUrl = null;
  if (baseUrl) {
    try {
      parsedBaseUrl = new URL(baseUrl);
    } catch (_error) {
      parsedBaseUrl = null;
    }
  }
  const host = String(service.host || parsedBaseUrl?.hostname || "127.0.0.1").trim() || "127.0.0.1";
  const port = Number(service.port || parsedBaseUrl?.port);
  const normalizedPort = Number.isInteger(port) ? port : 0;
  const fallbackAccessLink = parsedBaseUrl?.host || (normalizedPort ? `${host}:${normalizedPort}` : host);
  return {
    host,
    port: normalizedPort,
    accessLink: String(service.access_link || fallbackAccessLink),
  };
}

function renderOverviewServiceLink(snapshot = state.snapshot) {
  const modelId = String(state.activeModelId || snapshot?.model?.id || "");
  const model = state.models.find((item) => String(item?.id || "") === modelId);
  const accessLink = model ? modelServiceEndpoint(model).accessLink : "--";
  setOverviewText("overviewServiceLink", accessLink || "--");
}

function validateServiceAddressInputs(hostInputId, portInputId) {
  const host = String($(hostInputId)?.value || "").trim();
  const port = Number($(portInputId)?.value);
  const hostPattern = /^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/;
  if (
    !host
    || host.includes("://")
    || host.includes(":")
    || host.includes("/")
    || host.includes("\\")
    || host.includes("..")
    || /\s/.test(host)
    || !hostPattern.test(host)
  ) {
    return { ok: false, host, port, message: "请输入有效的 IPv4 地址或主机名，不要包含协议、端口或路径。" };
  }
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return { ok: false, host, port, message: "端口必须是 1-65535 之间的整数。" };
  }
  return { ok: true, host, port, accessLink: `${host}:${port}`, message: "" };
}

function updateServiceAddressPreview(hostInputId, portInputId, previewId) {
  const host = String($(hostInputId)?.value || "").trim() || "--";
  const port = String($(portInputId)?.value || "").trim() || "--";
  const preview = $(previewId);
  if (preview) preview.textContent = `${host}:${port}`;
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

function activeModelService() {
  const model = state.models.find((item) => item.id === state.activeModelId);
  if (model?.service) return model.service;
  return directSimulatorServiceMode
    ? {
        state: "running",
        healthy: true,
        base_url: directSimulatorServiceApiBase,
      }
    : {};
}

function activeModelServiceBase() {
  if (directSimulatorServiceMode) return directSimulatorServiceApiBase;
  return String(activeModelService().base_url || "").replace(/\/$/, "");
}

function activeModelServiceRunning() {
  if (directSimulatorServiceMode) {
    return Boolean(state.activeModelId && directSimulatorServiceApiBase);
  }
  const service = activeModelService();
  return service.state === "running" && service.healthy !== false && Boolean(service.base_url);
}

function modelServiceDependentControlsDisabled() {
  return !activeModelServiceRunning();
}

function renderModelServiceDependentControls() {
  const controlsDisabled = modelServiceDependentControlsDisabled();
  const topbar = document.querySelector(".topbar");
  if (topbar) topbar.classList.toggle("is-model-service-stopped", controlsDisabled);

  const traineeLinkButton = $("traineeLinkButton");
  if (traineeLinkButton) {
    traineeLinkButton.disabled = controlsDisabled;
    traineeLinkButton.setAttribute("aria-disabled", controlsDisabled ? "true" : "false");
    traineeLinkButton.title = controlsDisabled ? "请先启动选中模型的模拟服务" : "生成学员台交互链接";
  }

  renderCurveModeControls();
  renderClockControlAvailability();
}

function recordFrontendRequestDiagnostics(path, response, durationMs) {
  const diagnostics = state.frontendDiagnostics;
  const responseBytes = Math.max(0, Number(response?.headers?.get?.("Content-Length")) || 0);
  diagnostics.requestCount += 1;
  diagnostics.responseBytes += responseBytes;
  diagnostics.requestDurationMs += Math.max(0, Number(durationMs) || 0);
  if (/\/api\/snapshot(?:\?|$)/.test(String(path || ""))) {
    diagnostics.snapshotRequestCount += 1;
    diagnostics.snapshotResponseBytes += responseBytes;
  }
}

async function api(path, options = {}) {
  const {
    modelScoped = true,
    controlPlane = false,
    timeoutMs = frontendRequestTimeoutMs(),
    signal: callerSignal,
    ...fetchOptions
  } = options;
  if (directSimulatorServiceMode && controlPlane) {
    throw new Error("直连模拟服务界面不提供代理控制面操作");
  }
  const targetPath = modelScoped ? modelScopedPath(path) : path;
  const requestBase = controlPlane ? controlPlaneApiBase : activeModelServiceBase();
  if (!requestBase) {
    throw new Error("选中模型的模拟服务尚未启动");
  }
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
    const response = await fetch(`${requestBase}${targetPath}`, {
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

function controlPlaneApi(path, options = {}) {
  return api(path, {
    ...options,
    modelScoped: false,
    controlPlane: true,
  });
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
            <input
              type="checkbox"
              data-manual-change-select-all
              aria-label="选择全部人工修改"
              ${allSelected ? "checked" : ""}
            />
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
                <input
                  type="checkbox"
                  data-manual-change-id="${escapeHtml(changeId)}"
                  aria-label="选择 ${escapeHtml(change.object_label || change.object_name || changeId)}"
                  ${checked ? "checked" : ""}
                />
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
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  `;
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
    captureServiceSuggestion(result);
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
    if (state.snapshot) {
      state.snapshot.static_meta = {
        ...(state.snapshot.static_meta || {}),
        ...(result.static_meta || {}),
      };
      delete state.snapshot.definitions;
      delete state.snapshot.device_parameters;
    }
    refresh();
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
    if (state.snapshot) {
      state.snapshot.static_meta = {
        ...(state.snapshot.static_meta || {}),
        ...(result.static_meta || {}),
      };
      delete state.snapshot.definitions;
      delete state.snapshot.device_parameters;
    }
    refresh();
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
  "diagram": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters", "diagram"],
  "curves": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "faults": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "modes": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "parameters": ["settings"],
  "manual-changes": [],
  "runtime": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "measurements": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"],
  "logs": [],
};

const CACHEABLE_STATIC_KEYS = STATIC_SNAPSHOT_KEYS.filter((key) => key !== "curves");
let staticCacheStoreMemory = null;

function staticSnapshotKeysForPage(page = currentPageName()) {
  return STATIC_SNAPSHOT_KEYS_BY_PAGE[page] || STATIC_SNAPSHOT_KEYS;
}

function hasStaticSnapshotPayload(snapshot, requiredKeys = STATIC_SNAPSHOT_KEYS) {
  return Boolean(snapshot && requiredKeys.every((key) => snapshot[key] !== undefined));
}

function staticMetaSignature(meta) {
  return JSON.stringify(meta || null);
}

function staticMetaMatches(left, right) {
  return staticMetaSignature(left) === staticMetaSignature(right);
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
  if (!snapshot?.model?.id || !snapshot.static_meta) return snapshot;
  const requiredKeys = staticSnapshotKeysForPage(page).filter((key) => CACHEABLE_STATIC_KEYS.includes(key));
  if (!requiredKeys.length) return snapshot;
  const entry = readStaticCacheStore()[snapshot.model.id];
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
  if (!snapshot?.model?.id || !snapshot.static_meta) return;
  const requiredKeys = staticSnapshotKeysForPage(page).filter((key) => (
    CACHEABLE_STATIC_KEYS.includes(key)
    && snapshot[key] !== undefined
    && snapshot.static_meta?.[key] !== undefined
  ));
  if (!requiredKeys.length) return;
  const store = readStaticCacheStore();
  const entry = store[snapshot.model.id] || { fields: {} };
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
  store[snapshot.model.id] = { updatedAt: Date.now(), fields };
  if (writeStaticCacheStore(pruneStaticCacheStore(store))) return;
  requiredKeys.forEach((key) => {
    if (fields[key]?.value?.svg) delete fields[key];
  });
  store[snapshot.model.id] = { updatedAt: Date.now(), fields };
  writeStaticCacheStore(pruneStaticCacheStore(store));
}

function staticSnapshotMissingKeys(snapshot, requiredKeys = STATIC_SNAPSHOT_KEYS) {
  return (requiredKeys || []).filter((key) => snapshot?.[key] === undefined);
}

function pageNeedsMeasurementDelta(page = currentPageName()) {
  return ["overview", "diagram", "runtime", "measurements"].includes(page);
}

function pageNeedsRuntimeLogDelta(page = currentPageName()) {
  return ["overview", "logs"].includes(page);
}

function pageNeedsDevices(page = currentPageName()) {
  return ["overview", "diagram", "faults", "modes", "runtime"].includes(page);
}

function pageNeedsDeviceStates(page = currentPageName()) {
  return page === "diagram";
}

function pageNeedsCommands(page = currentPageName()) {
  return ["overview", "diagram", "runtime"].includes(page);
}

function pageNeedsCommandHistory(page = currentPageName()) {
  return page === "runtime";
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

function mergeSnapshot(previous, incoming) {
  if (!previous || !incoming) return incoming;
  const merged = { ...previous, ...incoming };
  const previousModelId = String(previous.model?.id || "");
  const incomingModelId = String(incoming.model?.id || "");
  const modelChanged = Boolean(previousModelId && incomingModelId && previousModelId !== incomingModelId);
  STATIC_SNAPSHOT_KEYS.forEach((key) => {
    if (incoming[key] !== undefined) return;
    const incomingMeta = incoming.static_meta?.[key];
    const previousMeta = previous.static_meta?.[key];
    const revisionChanged = Boolean(
      incomingMeta
      && previousMeta
      && !staticMetaMatches(incomingMeta, previousMeta)
    );
    if (modelChanged || revisionChanged) {
      delete merged[key];
      return;
    }
    if (previous[key] !== undefined) merged[key] = previous[key];
  });
  if (modelChanged && incoming.device_states === undefined) delete merged.device_states;
  if (incoming.runtime_logs === undefined) delete merged.runtime_logs;
  return merged;
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
        : []
    );
  const params = new URLSearchParams();
  const compactDeviceRuntime = !Array.isArray(forceStaticKeys) && canUseCompactDeviceRuntime(page);
  if (!Array.isArray(forceStaticKeys) && pageNeedsRuntimeLogDelta(page)) {
    params.set("logs", "1");
    params.set("runtime_log_after_seq", String(state.runtimeLogBackendSeq || 0));
    params.set("log_limit", String(Math.max(20, Math.round(activeRuntimeSetting("runtime_log_delta_batch_size")))));
  } else {
    params.set("logs", "0");
  }
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
  if (requiredStaticKeys.length) {
    params.set("static", requiredStaticKeys.join(","));
  } else {
    params.set("lite", "1");
  }
  return `/api/snapshot?${params.toString()}`;
}

function apiUrl(path, modelScoped = true) {
  const targetPath = modelScoped ? modelScopedPath(path) : path;
  return `${activeModelServiceBase()}${targetPath}`;
}

function mergeRuntimeLogItems(items = [], { reset = false, latestSeq = 0, total = null } = {}) {
  if (reset) state.runtimeLogs = [];
  const bySeq = new Map();
  state.runtimeLogs.forEach((item) => {
    const seq = Number(item.seq) || 0;
    if (seq) bySeq.set(seq, item);
  });
  (items || []).forEach((item, index) => {
    const normalized = normalizeRuntimeLog(item, index + 1);
    const seq = Number(normalized.seq) || 0;
    if (seq) bySeq.set(seq, normalized);
  });
  state.runtimeLogs = Array.from(bySeq.values())
    .sort((left, right) => Number(right.seq || 0) - Number(left.seq || 0))
    .slice(0, Math.max(50, Math.round(activeRuntimeSetting("runtime_log_cache_limit"))));
  const nextBackendSeq = Math.max(
    Number(latestSeq) || 0,
    state.runtimeLogs.reduce((maxSeq, item) => Math.max(maxSeq, Number(item.seq) || 0), 0),
  );
  state.runtimeLogBackendSeq = reset ? nextBackendSeq : Math.max(
    Number(state.runtimeLogBackendSeq) || 0,
    nextBackendSeq,
  );
  if (Number.isFinite(Number(total))) {
    state.runtimeLogTotal = Math.max(Number(total) || 0, state.runtimeLogs.length);
  } else {
    state.runtimeLogTotal = Math.max(Number(state.runtimeLogTotal) || 0, state.runtimeLogs.length);
  }
  state.runtimeLogSeq = Math.max(state.runtimeLogSeq, state.runtimeLogBackendSeq);
}

function applyEmbeddedRuntimeLogDelta(snapshot) {
  const payload = snapshot?.runtime_logs_delta;
  state.embeddedRuntimeLogDeltaReceived = Boolean(payload);
  if (!payload) return false;
  delete snapshot.runtime_logs_delta;
  mergeRuntimeLogItems(payload.items || payload.logs || [], {
    reset: Boolean(payload.reset),
    latestSeq: payload.latest_seq,
    total: payload.total,
  });
  return true;
}

async function refreshRuntimeLogs(renderNow = false) {
  if (state.runtimeLogRequestActive) return;
  state.runtimeLogRequestActive = true;
  try {
    const batchSize = Math.max(20, Math.round(activeRuntimeSetting("runtime_log_delta_batch_size")));
    const payload = await api(`/api/runtime-logs?after_seq=${state.runtimeLogBackendSeq}&limit=${batchSize}`);
    const items = payload.items || payload.logs || [];
    const receivedLatestSeq = items.reduce(
      (maxSeq, item) => Math.max(maxSeq, Number(item.seq) || 0),
      Number(state.runtimeLogBackendSeq) || 0,
    );
    mergeRuntimeLogItems(items, {
      reset: Boolean(payload.reset),
      latestSeq: receivedLatestSeq || payload.latest_seq,
      total: payload.total,
    });
    if (renderNow && currentPageName() === "logs") renderRuntimeLogs();
  } catch (error) {
    console.error("运行日志增量刷新失败", error);
  } finally {
    state.runtimeLogRequestActive = false;
  }
}

async function fetchRuntimeLogHistoryPage(renderNow = false) {
  if (state.runtimeLogHistoryRequestActive || state.runtimeLogTypeFilter !== "all") return;
  const oldestSeq = state.runtimeLogs.reduce((minSeq, item) => {
    const seq = Number(item.seq) || 0;
    return seq > 0 ? Math.min(minSeq, seq) : minSeq;
  }, Number.POSITIVE_INFINITY);
  if (!Number.isFinite(oldestSeq) || oldestSeq <= 1) return;
  state.runtimeLogHistoryRequestActive = true;
  try {
    const batchSize = Math.max(20, Math.round(activeRuntimeSetting("runtime_log_history_batch_size")));
    const payload = await api(`/api/runtime-logs?before_seq=${oldestSeq}&limit=${batchSize}`);
    mergeRuntimeLogItems(payload.items || payload.logs || [], {
      latestSeq: payload.latest_seq,
      total: payload.total,
    });
    if (renderNow && currentPageName() === "logs") renderRuntimeLogs();
  } catch (error) {
    console.error("运行日志历史分页拉取失败", error);
  } finally {
    state.runtimeLogHistoryRequestActive = false;
  }
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
        real_value: flags & 2 ? row?.[1] : null,
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
    || !Array.isArray(payload.real_values)
    || payload.real_values.length !== expectedValueCount
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
      + `真值=${payload.real_values?.length ?? "非数组"}，量测=${payload.scada_values?.length ?? "非数组"}，`
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
  const currentReal = Array.isArray(measurements.real) ? measurements.real : [];
  const currentScada = Array.isArray(measurements.scada) ? measurements.scada : [];
  const realRows = definitions.map((definition, index) => {
    const row = currentReal[index] || {};
    Object.assign(row, definition);
    row.value = payload.real_values[index];
    row.valid = payload.valid_values[index] ?? definition.valid ?? row.valid;
    row.weight = definition.weight ?? row.weight;
    row.status = statusValues?.[index] ?? definition.status ?? row.status;
    row.fixed_value = fixedValues?.[index] ?? definition.fixed_value ?? row.fixed_value;
    row.updated_simu_time = simuTime;
    row.updated_wall_time = wallTime;
    row.updated_absolute_minute = absoluteMinute;
    return row;
  });
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
  measurements.real = realRows;
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
    measurements.real = [];
    measurements.scada = [];
  }
  const definitionsByName = new Map(definitions.map((row) => [measurementNameKey(row), row]));
  const channelIndexes = {
    real: measurementChannelIndex(measurements.real || []),
    scada: measurementChannelIndex(measurements.scada || []),
  };
  let changed = false;
  compactMeasurementDeltaItems(payload).forEach((item) => {
    if (!item?.name) return;
    if (item.deleted) {
      ensureMeasurementChannelRow(measurements, definitionsByName, "real", item, channelIndexes.real);
      ensureMeasurementChannelRow(measurements, definitionsByName, "scada", item, channelIndexes.scada);
      changed = true;
      return;
    }
    const realRow = item.real_value !== undefined && item.real_value !== null
      ? ensureMeasurementChannelRow(measurements, definitionsByName, "real", item, channelIndexes.real)
      : null;
    const scadaRow = item.scada_value !== undefined && item.scada_value !== null
      ? ensureMeasurementChannelRow(measurements, definitionsByName, "scada", item, channelIndexes.scada)
      : null;
    if (realRow) {
      realRow.value = item.real_value;
      if (item.valid !== undefined && item.valid !== null) realRow.valid = item.valid;
      if (item.weight !== undefined && item.weight !== null) realRow.weight = item.weight;
      realRow.updated_simu_time = item.updated_simu_time;
      realRow.updated_wall_time = item.updated_wall_time;
      realRow.updated_absolute_minute = item.updated_absolute_minute;
      changed = true;
    }
    if (scadaRow) {
      scadaRow.value = item.scada_value;
      if (item.valid !== undefined && item.valid !== null) scadaRow.valid = item.valid;
      if (item.weight !== undefined && item.weight !== null) scadaRow.weight = item.weight;
      scadaRow.updated_simu_time = item.updated_simu_time;
      scadaRow.updated_wall_time = item.updated_wall_time;
      scadaRow.updated_absolute_minute = item.updated_absolute_minute;
      changed = true;
    }
  });
  measurements.real = Array.from(channelIndexes.real.values());
  measurements.scada = Array.from(channelIndexes.scada.values());
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
  const reqModelId = state.activeModelId;
  const reqEpoch = Number(state.modelSwitchEpoch || 0);
  state.measurementDeltaRequestActive = true;
  try {
    const payload = await api(`/api/measurements/delta?after_seq=${state.measurementDeltaSeq}&compact=1`);
    if (state.activeModelId !== reqModelId || Number(state.modelSwitchEpoch || 0) !== reqEpoch) {
      return false;
    }
    const changed = applyMeasurementDelta(payload);
    if (changed) hydrateMeasurementBackedDeviceRuntime(state.snapshot);
    if (changed && renderNow && currentPageName() === "measurements") renderMeasurementCompareTable();
    return changed;
  } catch (error) {
    if (!state._lastMeasDeltaErr) {
      console.error("量测增量刷新失败", error);
      state._lastMeasDeltaErr = String(error?.message || error);
    }
    return false;
  } finally {
    state.measurementDeltaRequestActive = false;
  }
}

async function refreshSnapshotPayload(page = currentPageName()) {
  const reqModelId = state.activeModelId;
  const reqEpoch = Number(state.modelSwitchEpoch || 0);
  state.embeddedMeasurementDeltaReceived = false;
  state.embeddedRuntimeLogDeltaReceived = false;
  const response = await api(snapshotPollPath(page));
  // 切换模型后丢弃迟到的旧模型响应，绝不污染新模型快照、日志与缓存。
  if (state.activeModelId !== reqModelId || Number(state.modelSwitchEpoch || 0) !== reqEpoch) {
    return null;
  }
  applyEmbeddedRuntimeLogDelta(response);
  const incoming = applyDeviceRuntimePayload(state.snapshot, response);
  let embeddedMeasurementDelta = incoming?.measurement_delta || null;
  if (incoming?.measurement_delta) delete incoming.measurement_delta;
  let snapshot = mergeSnapshot(state.snapshot, incoming);
  snapshot = restoreStaticSnapshotCache(snapshot, page);
  let requiredStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
  if (requiredStaticKeys.length) {
    const staticResponse = await api(snapshotPollPath(page, requiredStaticKeys));
    if (state.activeModelId !== reqModelId || Number(state.modelSwitchEpoch || 0) !== reqEpoch) {
      return null;
    }
    const staticIncoming = applyDeviceRuntimePayload(snapshot, staticResponse);
    if (staticIncoming?.measurement_delta) {
      embeddedMeasurementDelta = staticIncoming.measurement_delta;
      delete staticIncoming.measurement_delta;
    }
    snapshot = mergeSnapshot(snapshot, staticIncoming);
    snapshot = restoreStaticSnapshotCache(snapshot, page);
    requiredStaticKeys = staticSnapshotMissingKeys(snapshot, staticSnapshotKeysForPage(page));
  }
  if (!requiredStaticKeys.length) persistStaticSnapshotCache(snapshot, page);
  state.snapshot = snapshot;
  state._lastMeasDeltaErr = "";
  if (embeddedMeasurementDelta) {
    snapshot.measurement_delta = embeddedMeasurementDelta;
    applyEmbeddedMeasurementDelta(snapshot);
  }
  return snapshot;
}

function filenameFromDisposition(disposition, fallback) {
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition || "");
  if (encoded?.[1]) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch (_error) {
      return fallback;
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition || "");
  return plain?.[1] || fallback;
}

function blobFromBase64(dataBase64, contentType) {
  const binary = atob(dataBase64 || "");
  const chunkSize = 65536;
  const chunks = [];
  for (let offset = 0; offset < binary.length; offset += chunkSize) {
    const slice = binary.slice(offset, offset + chunkSize);
    const bytes = new Uint8Array(slice.length);
    for (let idx = 0; idx < slice.length; idx += 1) {
      bytes[idx] = slice.charCodeAt(idx);
    }
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

async function exportDefinitionsArchive(modelId = state.activeModelId, actionButton = null) {
  const button = actionButton;
  const originalText = button?.textContent || "";
  if (button) button.disabled = true;
  try {
    let directoryHandle = null;
    if (typeof window.showDirectoryPicker === "function") {
      if (button) button.textContent = "选择目录";
      directoryHandle = await window.showDirectoryPicker({
        id: "simu-definition-export",
        mode: "readwrite",
        startIn: "downloads",
      });
    }
    if (button) button.textContent = "导出中";
    const targetModelId = String(modelId || state.activeModelId || "").trim();
    const exportPath = targetModelId
      ? `/api/export-definitions?format=json&model_id=${encodeURIComponent(targetModelId)}`
      : "/api/export-definitions?format=json";
    const payload = await api(exportPath, { modelScoped: false });
    const blob = blobFromBase64(payload.data_base64, payload.content_type);
    const filename = safeExportFilename(filenameFromDisposition("", payload.filename || "model_definitions.zip"));
    if (directoryHandle) {
      const fileHandle = await directoryHandle.getFileHandle(filename, { create: true });
      const writable = await fileHandle.createWritable();
      await writable.write(blob);
      await writable.close();
      if (button) button.textContent = "已导出";
    } else {
      downloadBlob(blob, filename);
    }
  } catch (error) {
    if (error?.name === "AbortError") return;
    showUiToast(`导出定义包失败：${apiErrorText(error)}`, "error", 3600);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function deleteManagedModel(modelId) {
  const target = state.models.find((model) => model.id === modelId);
  if (!target) return;
  if (normalizeModels(state.models).length <= 1) {
    setModelManagementMessage("至少需要保留一个模型。", "error");
    return;
  }
  if (modelClockState(target) !== "stopped") {
    setModelManagementMessage("模型运行中或暂停中，不能删除。", "error");
    return;
  }
  const modelName = target.name || target.id || modelId;
  const confirmed = await confirmDangerousAction({
    title: "永久删除该模型？",
    target: `模型：${modelName}`,
    message: "此操作将永久删除该模型的文件夹、定义文件及全部历史运行数据，无法恢复。",
    confirmLabel: "确认删除",
  });
  if (!confirmed) {
    return;
  }
  const deletedActiveModel = String(target.id || "") === String(state.activeModelId || "");
  setModelManagementMessage(`正在删除模型：${modelName}`);
  try {
    const result = await api("/api/models/delete", {
      modelScoped: false,
      controlPlane: true,
      method: "POST",
      body: JSON.stringify({ model_id: modelId }),
    });
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
  } catch (error) {
    await loadModels();
    renderModelManagementList();
    setModelManagementMessage(apiErrorText(error), "error");
  }
}

function handleModelManagementAction(event) {
  closeModelContextMenu();
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  const modelId = item.dataset.modelId || "";
  if (!modelId) return;
  setSelectedManagementModel(modelId);
  setModelManagementMessage("右键模型节点可启动或停止服务，也可导出、复制、修改或删除。", "ok");
}

function handleModelManagementKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  closeModelContextMenu();
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  event.preventDefault();
  const modelId = item.dataset.modelId || "";
  setSelectedManagementModel(modelId);
  setModelManagementMessage("右键模型节点可启动或停止服务，也可导出、复制、修改或删除。", "ok");
}

function closeModelContextMenu() {
  const menu = $("modelContextMenu");
  if (!menu) return;
  menu.hidden = true;
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

function openModelContextMenu(event) {
  const item = event.target instanceof Element ? event.target.closest(".model-management-item[data-model-id]") : null;
  if (!item) return;
  event.preventDefault();
  const modelId = item.dataset.modelId || "";
  if (!modelId) return;
  setSelectedManagementModel(modelId);
  const menu = $("modelContextMenu");
  if (!menu) return;
  updateModelContextMenuActions();
  menu.hidden = false;
  positionModelContextMenu(menu, event.clientX, event.clientY);
}

function handleModelContextMenuAction(event) {
  const button = event.target instanceof Element ? event.target.closest("[data-model-context-action]") : null;
  if (!button || button.disabled) return;
  const action = button.dataset.modelContextAction || "";
  closeModelContextMenu();
  switch (action) {
    case "service-toggle":
      toggleSelectedManagementModelService();
      break;
    case "export":
      exportDefinitionsArchive(selectedManagementModelId(), button);
      break;
    case "clone":
      openCloneModelDialog(selectedManagementModelId());
      break;
    case "update":
      openUpdateModelDialog(selectedManagementModelId());
      break;
    case "delete":
      deleteManagedModel(selectedManagementModelId());
      break;
    default:
      break;
  }
}

function setTraineeLinkMessage(text, kind = "") {
  const message = $("traineeLinkMessage");
  if (!message) return;
  message.textContent = text || "";
  message.classList.toggle("is-error", kind === "error");
  message.classList.toggle("is-ok", kind === "ok");
}

function closeTraineeLinkDialog() {
  const dialog = $("traineeLinkDialog");
  if (dialog) dialog.hidden = true;
}

function activeModelInfo() {
  const selector = $("modelSelector");
  const selectedId = selector?.value || state.activeModelId || state.snapshot?.model?.id || state.models[0]?.id || "";
  return state.models.find((model) => model.id === selectedId)
    || (state.snapshot?.model?.id === selectedId ? state.snapshot.model : null)
    || { id: selectedId, name: selectedId || "默认模型" };
}

function generatedTraineeLink(modelId) {
  void modelId;
  const serviceBase = activeModelServiceBase();
  if (!serviceBase) return "";
  return serviceBase;
}

function modelServiceStateLabel(service = activeModelService()) {
  const labels = {
    running: "运行中",
    starting: "启动中",
    stopping: "停止中",
    failed: "异常",
    stopped: "已停止",
  };
  return labels[service.state] || "未知";
}

function renderModelServiceControl() {
  if (directSimulatorServiceMode) {
    renderModelServiceDependentControls();
    return;
  }
  const service = activeModelService();
  const stateElement = $("modelServiceState");
  const button = $("modelServiceToggle");
  const serviceState = service.state || "stopped";
  if (stateElement) {
    stateElement.textContent = modelServiceStateLabel(service);
    stateElement.dataset.state = serviceState;
    stateElement.title = service.error || service.base_url || "";
  }
  renderModelServiceDependentControls();
  if (!button) return;
  const running = serviceState === "running";
  button.textContent = running ? "停止" : "启动";
  button.dataset.action = running ? "stop" : "start";
  button.disabled = (
    !state.activeModelId
    || state.modelServiceOperationActive
    || serviceState === "starting"
    || serviceState === "stopping"
  );
  button.title = service.base_url
    ? `${running ? "停止" : "启动"} ${service.base_url}`
    : `${running ? "停止" : "启动"}选中模型的模拟服务`;
}

function setTraineeLinkCopyEnabled(enabled) {
  const copyButton = $("copyTraineeLink");
  if (copyButton) copyButton.disabled = !enabled;
}

async function openTraineeLinkDialog() {
  const dialog = $("traineeLinkDialog");
  const input = $("traineeLinkValue");
  const modelName = $("traineeLinkModelName");
  const button = $("traineeLinkButton");
  if (!dialog || !input || !modelName) return;
  const currentModel = activeModelInfo();
  dialog.hidden = false;
  input.value = generatedTraineeLink(currentModel.id);
  modelName.textContent = currentModel.name || currentModel.id || "--";
  setTraineeLinkCopyEnabled(Boolean(input.value));
  setTraineeLinkMessage("模拟台服务地址已自动生成，正在校验服务。", input.value ? "ok" : "");
  input.focus();
  input.select();
  if (button) button.disabled = true;
  try {
    const payload = await api("/api/trainee-link", { modelScoped: false });
    input.value = payload.link || input.value;
    modelName.textContent = payload.model_name || payload.model_id || "--";
    setTraineeLinkCopyEnabled(Boolean(input.value));
    setTraineeLinkMessage("将此服务地址发给学员台；具体接口路径由学员台内部组织。", "ok");
    input.focus();
    input.select();
  } catch (error) {
    setTraineeLinkCopyEnabled(Boolean(input.value));
    setTraineeLinkMessage(`已按当前模型生成服务地址，但校验失败：${apiErrorText(error)}`, "error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function copyTraineeLink() {
  const input = $("traineeLinkValue");
  if (!input?.value) {
    setTraineeLinkMessage("暂无可复制的模拟台服务地址。", "error");
    return;
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(input.value);
    } else {
      input.focus();
      input.select();
      document.execCommand("copy");
    }
    setTraineeLinkMessage("模拟台服务地址已复制。", "ok");
  } catch (_error) {
    input.focus();
    input.select();
    setTraineeLinkMessage("复制失败，请手动复制输入框中的服务地址。", "error");
  }
}

function renderModelSelector() {
  const selector = $("modelSelector");
  if (!selector) return;
  state.models = normalizeModels(state.models);
  const models = state.models.length ? state.models : [{ id: state.activeModelId || "", name: "默认模型" }];
  const modelOptionsKey = JSON.stringify(models.map((model) => [model.id, model.name || model.id]));
  if (selector.dataset.modelOptionsKey !== modelOptionsKey) {
    selector.innerHTML = models.map((model) => `
      <option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)}</option>
    `).join("");
    selector.dataset.modelOptionsKey = modelOptionsKey;
  }
  selector.value = state.activeModelId || models[0]?.id || "";
  selector.disabled = models.length <= 1;
  const active = models.find((model) => model.id === selector.value) || models[0] || {};
  $("activeModelName").textContent = active.name || active.id || "默认模型";
  renderOverviewServiceLink();
  renderModelServiceControl();
  if (!$("modelManagementDialog")?.hidden) renderModelManagementList();
}

async function setActiveModel(modelId, shouldRefresh = true) {
  const nextId = modelId || state.models[0]?.id || "";
  if (state.activeModelId === nextId && shouldRefresh) {
    await loadWebRuntimeSettings();
    await refresh();
    return;
  }
  cancelCurveRequests();
  state.modelSwitchEpoch = Number(state.modelSwitchEpoch || 0) + 1;
  state.refreshRequestActive = false;
  state.activeModelId = nextId;
  state.selectedManagementModelId = nextId;
  state.deviceRuntimeSignature = "";
  state.deviceRuntimeNeedsFullRefresh = false;
  state.deviceRuntimeWarning = "";
  localStorage.setItem("polarSimulatorModelId", nextId);
  invalidateManualDefinitionChanges();
  state.snapshot = null;
  state.settingsLoaded = false;
  state.deviceFaults = [];
  state.measurementFaults = [];
  state.modes = [];
  state.runtimeLogs = [];
  state.runtimeLogTypeFilter = "all";
  state.runtimeLogSeq = 0;
  state.runtimeLogBackendSeq = 0;
  state.runtimeLogTotal = 0;
  state.lastRuntimeLogKey = "";
  state.measurementDeltaSeq = 0;
  state.systemParameters = {
    clock_speed: 1,
    compute_interval_seconds: 1,
    storage_initial_soc: 0.5,
    remote_adjustment_response_ratio: 0.7,
  };
  state.systemParametersDirty = false;
  state.systemParametersSaving = false;
  resetWebRuntimeSettingsState();
  restartRefreshScheduler();
  state.runtimeTraceHistory = [];
  resetChartPeriodOffsets("runtimeTrace");
  state.lastRuntimeTraceKey = "";
  state.measurementTraceHistory = [];
  resetChartPeriodOffsets("measurementTrace");
  state.lastMeasurementTraceKey = "";
  resetMeasurementHistoryHydration();
  state.traceRunId = null;
  state.traceStepCount = null;
  state.selectedMeasurementKey = "";
  state.modeFilter = { dev_type: "all", dev_name: "" };
  state.faultDeviceFilter = { dev_type: "all", dev_name: "" };
  state.faultMeasurementFilter = { dev_type: "all", dev_name: "", key: "" };
  state.modelDeviceFilter = { dev_type: "all", dev_name: "" };
  state.activeModelParamTab = "";
  state.runtimeDeviceFilter = { dev_type: "all", dev_name: "" };
  state.activeRuntimeCommandTab = "remote_control";
  state.measurementCompareFilter = { dev_type: "all", dev_name: "" };
  state.deviceTreeSelectionAnchors = {};
  state.activeCurveKey = "wind_speed_mps";
  state.selectedCurveKeys = ["wind_speed_mps"];
  state.curveEditKey = "";
  state.curveSummary = null;
  state.curveSummaryLoadedModelId = "";
  state.curveSummaryRequest = null;
  state.curveSummaryRequestModelId = "";
  state.curveSummaryAbortController = null;
  state.curveSeriesRequestKey = "";
  state.curveSeriesRequest = null;
  state.curveSeriesAbortController = null;
  state.curveEditorLoadRequest = null;
  state.curveEditorLoadRequestKey = "";
  state.curveLoadError = "";
  state.curveDataRevision += 1;
  state.lastCurveEditorRenderKey = "";
  state.lastCurveEditorTableKey = "";
  state.curveDirtyKeys = new Set();
  state.curveDirtyKeysByMode = {};
  state.curvePersistedMode = "";
  state.curveSeries = {};
  state.curveSeriesByMode = {};
  state.curvesLoadedModelId = "";
  renderModelSelector();
  if (currentPageName() === "curves") renderCurveEditorLoading("正在加载曲线摘要...");
  renderModelServiceControl();
  if (activeModelServiceRunning()) {
    await loadWebRuntimeSettings();
    if (shouldRefresh) await refresh();
  } else {
    $("simState").textContent = "stopped";
    if (typeof syncClockTriggerSummary === "function") syncClockTriggerSummary("stopped");
    const solverInfo = $("solverInfo");
    if (solverInfo) solverInfo.textContent = "模拟服务已停止";
  }
}

async function loadModels({ preserveSelection = true } = {}) {
  if (directSimulatorServiceMode) {
    try {
      await loadDirectSimulatorServiceModel();
    } catch (error) {
      console.error("直连模拟服务模型加载失败", error);
    } finally {
      state.modelsLoaded = true;
    }
    return;
  }
  try {
    const catalog = await api("/api/models", { modelScoped: false, controlPlane: true });
    captureServiceSuggestion(catalog);
    state.models = normalizeModels(Array.isArray(catalog.models) ? catalog.models : []);
    state.serviceCatalogLastLoadedAt = Date.now();
    const preferred = (preserveSelection ? state.activeModelId : "") || catalog.active_model_id || state.models[0]?.id || "";
    const exists = state.models.some((model) => model.id === preferred);
    await setActiveModel(exists ? preferred : state.models[0]?.id || "", false);
  } catch (_error) {
    state.models = [];
    renderModelSelector();
  } finally {
    state.modelsLoaded = true;
  }
}

async function loadDirectSimulatorServiceModel() {
  state.activeModelId = "";
  try {
    const catalog = await api("/api/models", { modelScoped: false });
    const source = normalizeModels(Array.isArray(catalog.models) ? catalog.models : [])[0]
      || {
        id: String(catalog.active_model_id || "").trim(),
        name: String(catalog.active_model_id || "").trim(),
      };
    const modelId = String(source.id || catalog.active_model_id || "").trim();
    if (!modelId) throw new Error("模拟服务未返回当前模型标识");
    state.models = [{
      ...source,
      id: modelId,
      name: source.name || modelId,
      service: {
        ...(source.service || {}),
        state: "running",
        healthy: true,
        base_url: directSimulatorServiceApiBase,
      },
    }];
    state.serviceCatalogLastLoadedAt = Date.now();
    await setActiveModel(modelId, false);
  } catch (error) {
    state.models = [];
    state.activeModelId = "";
    renderModelSelector();
    throw error;
  }
}

async function refreshServiceCatalog(force = false) {
  if (directSimulatorServiceMode) return state.models;
  const modalOpen = Boolean($("modelManagementModal") && !$("modelManagementModal").hidden);
  const minIntervalMs = modalOpen ? 3000 : 10000;
  if (!force && Date.now() - state.serviceCatalogLastLoadedAt < minIntervalMs) return state.models;
  if (state.serviceCatalogRequestActive) return state.models;
  state.serviceCatalogRequestActive = true;
  try {
    const catalog = await api("/api/simulator-services", {
      modelScoped: false,
      controlPlane: true,
      timeoutMs: 3000,
    });
    captureServiceSuggestion(catalog);
    const nextModels = normalizeModels(Array.isArray(catalog.models) ? catalog.models : []);
    const nextKey = nextModels
      .map((m) => `${m.id}:${m.name}:${m.service?.state || ""}:${m.service?.healthy ? 1 : 0}:${m.service?.port || ""}`)
      .join("|");
    state.models = nextModels;
    state.serviceCatalogLastLoadedAt = Date.now();
    state._lastCatalogError = "";
    if (force || nextKey !== state._lastCatalogRenderKey) {
      state._lastCatalogRenderKey = nextKey;
      renderModelSelector();
    }
    return state.models;
  } catch (error) {
    const msg = String(error?.message || error);
    if (state._lastCatalogError !== msg) {
      state._lastCatalogError = msg;
      console.error("模拟服务目录刷新失败", error);
    }
    return state.models;
  } finally {
    state.serviceCatalogRequestActive = false;
  }
}

async function setModelServiceRunning(modelId, shouldRun, { managementAction = false } = {}) {
  if (directSimulatorServiceMode) return;
  const targetModelId = String(modelId || "").trim();
  if (!targetModelId || state.modelServiceOperationActive) return;
  const targetModel = state.models.find((model) => String(model.id || "") === targetModelId);
  if (!targetModel) {
    if (managementAction) setModelManagementMessage("请选择要操作的模型。", "error");
    return;
  }
  const serviceState = String(targetModel?.service?.state || "stopped");
  if (serviceState === "starting" || serviceState === "stopping") return;
  const running = serviceState === "running";
  if (running === shouldRun) return;
  const path = shouldRun ? "/api/simulator-services/start" : "/api/simulator-services/stop";
  const actionText = shouldRun ? "启动" : "停止";
  const modelName = targetModel.name || targetModel.id || targetModelId;
  state.modelServiceOperationActive = true;
  targetModel.service = targetModel.service || {};
  targetModel.service.state = shouldRun ? "starting" : "stopping";
  renderModelServiceControl();
  renderModelManagementList();
  if (managementAction) setModelManagementMessage(`正在${actionText}模拟服务：${modelName}`);
  try {
    const payload = await api(path, {
      method: "POST",
      body: JSON.stringify({ model_id: targetModelId }),
      modelScoped: false,
      controlPlane: true,
      timeoutMs: shouldRun ? 45000 : 15000,
    });
    state.models = normalizeModels(Array.isArray(payload.models) ? payload.models : state.models);
    state.serviceCatalogLastLoadedAt = Date.now();
    renderModelSelector();
    if (targetModelId === state.activeModelId) {
      if (activeModelServiceRunning()) {
        resetWebRuntimeSettingsState();
        await loadWebRuntimeSettings(true);
        await refresh();
      } else {
        state.snapshot = null;
        $("simState").textContent = "stopped";
        if (typeof syncClockTriggerSummary === "function") syncClockTriggerSummary("stopped");
        const solverInfo = $("solverInfo");
        if (solverInfo) solverInfo.textContent = "模拟服务已停止";
      }
    }
    if (managementAction) setModelManagementMessage(`已${actionText}模拟服务：${modelName}`, "ok");
  } catch (error) {
    await refreshServiceCatalog(true);
    const message = apiErrorText(error);
    if (targetModelId === state.activeModelId) {
      const stateElement = $("modelServiceState");
      if (stateElement) {
        stateElement.textContent = "操作失败";
        stateElement.dataset.state = "failed";
        stateElement.title = message;
      }
    }
    if (managementAction) setModelManagementMessage(`${actionText}模拟服务失败：${message}`, "error");
  } finally {
    state.modelServiceOperationActive = false;
    renderModelServiceControl();
    renderModelManagementList();
  }
}

async function toggleActiveModelService() {
  if (!state.activeModelId) return;
  await setModelServiceRunning(
    state.activeModelId,
    activeModelService().state !== "running",
  );
}

async function toggleSelectedManagementModelService() {
  const selected = selectedManagementModel();
  if (!selected) {
    setModelManagementMessage("请选择要操作的模型。", "error");
    return;
  }
  await setModelServiceRunning(
    selected.id,
    String(selected?.service?.state || "stopped") !== "running",
    { managementAction: true },
  );
}

