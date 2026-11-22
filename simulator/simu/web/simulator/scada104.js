const get = (id) => document.getElementById(id);
const text = (tag, value, className = "") => {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
};

const REFRESH_INTERVAL_MS = 1800;
const MAX_RECENT_RECEIPTS = 5;

let activeViewTab = "channels";
let loadedPointScope = "";
let allLoadedPoints = [];
let pointItemsByNo = new Map();
let pointLoadSeq = 0;
let pointAbortController = null;
let statusAbortController = null;
let refreshTimerId = null;
let refreshInFlight = false;
let lastModelsRenderKey = "";
let lastRtuOptionsKey = "";
let lastAllRtuOptionsKey = "";
let latestModels = [];
let loadedPointsTableItems = [];
const recentReceipts = [];

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

function applyUiTheme(themeId, { persist = true } = {}) {
  const resolved = normalizeUiTheme(themeId);
  const meta = UI_THEME_MAP.get(resolved) || UI_THEME_PRESETS[0];
  document.documentElement.dataset.theme = meta.id;
  document.documentElement.dataset.colorScheme = meta.scheme;
  const selector = get("themeSelector");
  if (selector && selector.value !== meta.id) {
    selector.value = meta.id;
  }
  if (persist) {
    try {
      localStorage.setItem("polarUiTheme", meta.id);
    } catch (_e) {}
  }
}

function initThemeToggle() {
  const selector = get("themeSelector");
  let initialTheme = document.documentElement.dataset.theme;
  try {
    const stored = localStorage.getItem("polarUiTheme");
    if (stored) initialTheme = stored;
  } catch (_e) {}
  applyUiTheme(initialTheme, { persist: false });
  if (selector) {
    selector.addEventListener("change", () => {
      applyUiTheme(selector.value, { persist: true });
    });
  }
  window.addEventListener("storage", (event) => {
    if (event.key === "polarUiTheme") {
      applyUiTheme(event.newValue, { persist: false });
    }
  });
  if (typeof initUiI18n === "function") {
    initUiI18n();
  }
}

function setActiveViewTab(tab) {
  if (!["channels", "points", "logs"].includes(tab)) return;
  activeViewTab = tab;
  document.querySelectorAll("[data-view-tab]").forEach((btn) => {
    const active = btn.dataset.viewTab === tab;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-view-pane]").forEach((pane) => {
    pane.hidden = pane.dataset.viewPane !== tab;
  });
  if (tab === "points") loadPointsTable();
  else if (tab === "logs") loadChannelLogs();
}

function confirmScadaCommand(detailText, { title = "确认执行操作？", danger = false, confirmLabel = "确认执行" } = {}) {
  const dialog = get("scadaConfirmDialog");
  const titleNode = get("scadaConfirmTitle");
  const detailNode = get("scadaConfirmDetail");
  const cancelBtn = get("scadaConfirmCancel");
  const okBtn = get("scadaConfirmOk");
  if (!dialog || !cancelBtn || !okBtn || typeof dialog.showModal !== "function") {
    return Promise.resolve(window.confirm(`${title}\n${detailText}`));
  }
  if (dialog.open) return Promise.resolve(false);
  dialog.classList.toggle("is-danger", Boolean(danger));
  if (titleNode) titleNode.textContent = title;
  okBtn.className = danger ? "danger" : "primary";
  okBtn.textContent = confirmLabel;
  if (detailNode) detailNode.textContent = detailText;
  return new Promise((resolve) => {
    let settled = false;
    const finish = (accepted) => {
      if (settled) return;
      settled = true;
      cancelBtn.removeEventListener("click", onCancel);
      okBtn.removeEventListener("click", onOk);
      dialog.removeEventListener("cancel", onDialogCancel);
      if (dialog.open) dialog.close();
      resolve(accepted);
    };
    const onCancel = () => finish(false);
    const onOk = () => finish(true);
    const onDialogCancel = (event) => {
      event.preventDefault();
      finish(false);
    };
    cancelBtn.addEventListener("click", onCancel);
    okBtn.addEventListener("click", onOk);
    dialog.addEventListener("cancel", onDialogCancel);
    dialog.showModal();
    cancelBtn.focus();
  });
}

async function api(path, body, { signal } = {}) {
  const init = body === undefined
    ? { signal }
    : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    };
  const response = await fetch(path, init);
  const rawText = await response.text();
  let data = null;
  if (rawText) {
    try {
      data = JSON.parse(rawText);
    } catch (_parseErr) {
      data = null;
    }
  }
  if (!response.ok) {
    const message = data?.error?.message || data?.error || rawText.trim().slice(0, 160) || `HTTP ${response.status}`;
    throw new Error(message);
  }
  if (data === null) {
    throw new Error(`接口返回了非 JSON 内容（HTTP ${response.status}）`);
  }
  return data;
}

function syncValueInputMode() {
  const kind = get("kind").value;
  const select = get("valueSelect");
  const input = get("value");
  const isYk = kind === "yk";
  select.hidden = !isYk;
  select.required = isYk;
  select.disabled = !isYk;
  input.hidden = isYk;
  input.required = !isYk;
  input.disabled = isYk;
  updateSelectedPointMeta(false);
}

function updateSelectedPointMeta(prefillYtValue = false) {
  const metaNode = get("pointMeta");
  const pointVal = get("point")?.value || "";
  const kind = get("kind")?.value || "yk";
  if (!metaNode) return;
  const item = pointItemsByNo.get(String(pointVal));
  if (!item) {
    metaNode.textContent = "";
    return;
  }
  const hasValue = item.value !== null && item.value !== undefined && item.value !== "";
  const valueText = hasValue ? String(item.value) : "—";
  const statusText = item.disabled ? "已禁止操作" : "可操作";
  metaNode.textContent = `当前测点：#${item.pnt_no} ${item.source_name || item.name} · 当前值 ${valueText} · ${statusText}`;
  if (prefillYtValue && kind === "yt" && hasValue) {
    const input = get("value");
    if (input && Number.isFinite(Number(item.value))) {
      input.value = String(item.value);
    }
  }
}

function renderPointOptions() {
  const pointSelect = get("point");
  const keyword = String(get("pointSearch")?.value || "").trim().toLowerCase();
  const prevValue = pointSelect.value;
  const filtered = keyword
    ? allLoadedPoints.filter((item) => {
      const hay = `${item.pnt_no} ${item.name || ""} ${item.source_name || ""}`.toLowerCase();
      return hay.includes(keyword);
    })
    : allLoadedPoints;

  const placeholderText = !allLoadedPoints.length
    ? "暂无可用控制点"
    : (filtered.length ? `选择控制点（${filtered.length}/${allLoadedPoints.length}）` : "无匹配控制点");
  const options = [new Option(placeholderText, "")];
  for (const item of filtered) {
    const valHint = item.value !== null && item.value !== undefined && item.value !== "" ? ` [${item.value}]` : "";
    const label = `${item.pnt_no} · ${item.name || item.source_name}${valHint}${item.disabled ? "（已禁操）" : ""}`;
    const option = new Option(label, String(item.pnt_no));
    if (item.disabled) option.disabled = true;
    options.push(option);
  }
  pointSelect.replaceChildren(...options);
  pointSelect.disabled = filtered.length === 0;
  if (options.some((opt) => opt.value === prevValue && !opt.disabled)) {
    pointSelect.value = prevValue;
  }
  updateSelectedPointMeta(false);
}

async function loadControlPoints(force = false) {
  const rtu = get("rtu").value;
  const kind = get("kind").value;
  const pointSelect = get("point");
  const scope = `${rtu}:${kind}`;
  if (!rtu) {
    if (pointAbortController) pointAbortController.abort();
    loadedPointScope = "";
    allLoadedPoints = [];
    pointItemsByNo = new Map();
    pointSelect.replaceChildren(new Option("请先选择模型", ""));
    pointSelect.disabled = true;
    updateSelectedPointMeta(false);
    return;
  }
  if (!force && scope === loadedPointScope) return;
  if (pointAbortController) pointAbortController.abort();
  pointAbortController = new AbortController();
  const requestSeq = ++pointLoadSeq;
  loadedPointScope = scope;
  try {
    const data = await api(
      `/api/simulator104/points?rtu_id=${encodeURIComponent(rtu)}&kind=${encodeURIComponent(kind)}`,
      undefined,
      { signal: pointAbortController.signal },
    );
    if (requestSeq !== pointLoadSeq) return;
    const items = Array.isArray(data.items) ? data.items : [];
    allLoadedPoints = items;
    pointItemsByNo = new Map(items.map((item) => [String(item.pnt_no), item]));
    renderPointOptions();
  } catch (error) {
    if (error?.name === "AbortError" || requestSeq !== pointLoadSeq) return;
    loadedPointScope = "";
    allLoadedPoints = [];
    pointItemsByNo = new Map();
    pointSelect.replaceChildren(new Option(`加载失败：${error.message}`, ""));
    pointSelect.disabled = true;
    updateSelectedPointMeta(false);
  }
}

function renderPointsTableRows() {
  const tbody = get("pointsTableBody");
  if (!tbody) return;
  const kind = get("pointsKindSelect")?.value || "yc";
  const rtu = Number(get("pointsRtuSelect")?.value || 0);
  const keyword = String(get("pointsTableSearch")?.value || "").trim().toLowerCase();
  const filtered = keyword
    ? loadedPointsTableItems.filter((item) => (
      `${item.pnt_no} ${item.name || ""} ${item.source_name || ""}`.toLowerCase().includes(keyword)
    ))
    : loadedPointsTableItems;
  if (!filtered.length) {
    const cell = text("td", loadedPointsTableItems.length ? "无匹配测点" : "暂无测点数据", "empty");
    cell.colSpan = 6;
    const tr = document.createElement("tr");
    tr.append(cell);
    tbody.replaceChildren(tr);
    return;
  }
  const rows = filtered.map((item) => {
    const tr = document.createElement("tr");
    tr.append(text("td", String(item.pnt_no), "num"));
    tr.append(text("td", item.name || item.source_name || ""));
    tr.append(text("td", item.source_name || "", "mono"));
    const valStr = item.value === null || item.value === undefined ? "—" : String(item.value);
    tr.append(text("td", valStr, "num"));

    const statusTd = document.createElement("td");
    const isValid = Number(item.status) === 0;
    const pill = text("span", isValid ? "有效" : `无效(${item.status ?? 128})`, isValid ? "pill is-ok" : "pill is-off");
    statusTd.append(pill);
    tr.append(statusTd);

    const opTd = document.createElement("td");
    if (kind === "yk" || kind === "yt") {
      const btn = text("button", item.disabled ? "恢复操作" : "禁止操作", item.disabled ? "row-btn" : "row-btn is-danger");
      btn.type = "button";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api("/api/simulator104/points/disable", {
            rtu_id: rtu,
            kind,
            pnt_no: item.pnt_no,
            disabled: !item.disabled,
          });
          await loadPointsTable();
          await loadControlPoints(true);
        } catch (err) {
          get("bridgeError").textContent = err.message;
        } finally {
          btn.disabled = false;
        }
      });
      opTd.append(btn);
    } else {
      opTd.append(text("span", "只读", "pill is-off"));
    }
    tr.append(opTd);
    return tr;
  });
  tbody.replaceChildren(...rows);
}

async function loadPointsTable() {
  const rtu = get("pointsRtuSelect")?.value || "";
  const kind = get("pointsKindSelect")?.value || "yc";
  const tbody = get("pointsTableBody");
  if (!tbody) return;
  if (!rtu) {
    loadedPointsTableItems = [];
    renderPointsTableRows();
    return;
  }
  try {
    const data = await api(`/api/simulator104/points?rtu_id=${encodeURIComponent(rtu)}&kind=${encodeURIComponent(kind)}`);
    loadedPointsTableItems = Array.isArray(data.items) ? data.items : [];
    renderPointsTableRows();
  } catch (err) {
    loadedPointsTableItems = [];
    const cell = text("td", `加载点表失败：${err.message}`, "empty");
    cell.colSpan = 6;
    const tr = document.createElement("tr");
    tr.append(cell);
    tbody.replaceChildren(tr);
  }
}

async function loadChannelLogs() {
  const rtu = get("logsRtuSelect")?.value || "";
  const tbody = get("logsTableBody");
  if (!tbody) return;
  if (!rtu) {
    const cell = text("td", "请选择模型查看通信日志", "empty");
    cell.colSpan = 3;
    const tr = document.createElement("tr");
    tr.append(cell);
    tbody.replaceChildren(tr);
    return;
  }
  try {
    const data = await api(`/api/simulator104/logs?rtu_id=${encodeURIComponent(rtu)}&limit=120`);
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      const cell = text("td", "暂无通道通信日志", "empty");
      cell.colSpan = 3;
      const tr = document.createElement("tr");
      tr.append(cell);
      tbody.replaceChildren(tr);
      return;
    }
    const rows = items.map((item) => {
      const tr = document.createElement("tr");
      tr.append(text("td", String(item.time || ""), "mono"));
      const lvl = String(item.level || "INFO").toUpperCase();
      const lvlTd = document.createElement("td");
      const cls = lvl === "ERROR" ? "pill is-warn" : (lvl === "INFO" ? "pill is-ok" : "pill is-off");
      lvlTd.append(text("span", lvl, cls));
      tr.append(lvlTd);
      tr.append(text("td", String(item.message || ""), "log-msg"));
      return tr;
    });
    tbody.replaceChildren(...rows);
  } catch (err) {
    const cell = text("td", `加载通信日志失败：${err.message}`, "empty");
    cell.colSpan = 3;
    const tr = document.createElement("tr");
    tr.append(cell);
    tbody.replaceChildren(tr);
  }
}

async function controlChannel(model, action) {
  if (action === "stop") {
    const ok = await confirmScadaCommand(
      `目标：${model.model} · RTU ${model.rtu_id}（${model.endpoint?.host || ""}:${model.endpoint?.port || ""}）`,
      { title: "确认停止 IEC104 通道？", danger: true, confirmLabel: "确认停止" },
    );
    if (!ok) return;
  }
  try {
    await api("/api/simulator104/channel", { rtu_id: Number(model.rtu_id), action });
    await refresh(true);
  } catch (err) {
    get("bridgeError").textContent = `通道控制失败：${err.message}`;
  }
}

function pushReceiptHistory(message, isError = false) {
  const now = new Date();
  const stamp = [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
  recentReceipts.unshift({ stamp, message, isError });
  if (recentReceipts.length > MAX_RECENT_RECEIPTS) {
    recentReceipts.length = MAX_RECENT_RECEIPTS;
  }
  const list = get("recentReceipts");
  if (!list) return;
  const nodes = recentReceipts.map((entry) => {
    const li = document.createElement("li");
    if (entry.isError) li.className = "is-error";
    li.append(text("span", entry.message), text("span", entry.stamp));
    return li;
  });
  list.replaceChildren(...nodes);
}

function scheduleNextRefresh(delayMs = REFRESH_INTERVAL_MS) {
  if (refreshTimerId !== null) {
    clearTimeout(refreshTimerId);
    refreshTimerId = null;
  }
  if (document.hidden) return;
  refreshTimerId = setTimeout(() => {
    refreshTimerId = null;
    refresh(false);
  }, delayMs);
}

function syncSelectedModelRowHighlight() {
  const activeRtu = get("rtu")?.value || "";
  document.querySelectorAll("#modelRows tr[data-rtu-id]").forEach((row) => {
    row.classList.toggle("is-selected", row.dataset.rtuId === activeRtu);
  });
}

function syncAuxiliaryRtuSelects(models) {
  const key = models.map((m) => `${m.rtu_id}:${m.model}`).join("|");
  if (key === lastAllRtuOptionsKey) return;
  lastAllRtuOptionsKey = key;
  for (const id of ["pointsRtuSelect", "logsRtuSelect"]) {
    const sel = get(id);
    if (!sel) continue;
    const prev = sel.value;
    const opts = models.length
      ? models.map((m) => new Option(`${m.model} · RTU ${m.rtu_id}`, String(m.rtu_id)))
      : [new Option("暂无模型", "")];
    sel.replaceChildren(...opts);
    if (opts.some((opt) => opt.value === prev)) sel.value = prev;
    else if (opts.length) sel.value = opts[0].value;
  }
}

async function refresh(manual = false) {
  if (document.hidden && !manual) return;
  if (refreshInFlight) return;
  refreshInFlight = true;
  if (statusAbortController) statusAbortController.abort();
  statusAbortController = new AbortController();
  try {
    const state = await api("/api/simulator104/status", undefined, {
      signal: statusAbortController.signal,
    });
    const models = Array.isArray(state?.models) ? state.models : [];
    latestModels = models;
    const errors = state?.errors && typeof state.errors === "object" ? state.errors : {};
    get("database").textContent = state?.database ? `点库：${state.database}（托管于模拟台 Web）` : "";
    get("bridgeError").textContent = Object.entries(errors)
      .map(([key, value]) => `${key}：${value}`)
      .join(" · ");

    const extLink = get("externalScadaLink");
    if (extLink) {
      const extUrl = String(state?.scada_web_url || "").trim();
      if (extUrl) {
        extLink.href = extUrl;
        extLink.hidden = false;
      } else {
        extLink.hidden = true;
      }
    }

    syncAuxiliaryRtuSelects(models);

    const selectedRtu = get("rtu").value;
    const onlineModels = models.filter((model) => model?.online && model?.running);
    const rtuOptionsKey = onlineModels.map((m) => `${m.rtu_id}:${m.model}`).join("|");
    if (rtuOptionsKey !== lastRtuOptionsKey) {
      lastRtuOptionsKey = rtuOptionsKey;
      const options = [new Option("选择模型", "")];
      for (const model of onlineModels) {
        options.push(new Option(`${model.model} · RTU ${model.rtu_id}`, String(model.rtu_id)));
      }
      get("rtu").replaceChildren(...options);
      const nextRtu = options.some((opt) => opt.value === selectedRtu)
        ? selectedRtu
        : (options.length === 2 ? options[1].value : "");
      get("rtu").value = nextRtu;
    }

    const activeRtu = get("rtu").value;
    const modelsRenderKey = JSON.stringify(
      models.map((m) => [
        m.model,
        m.rtu_id,
        m.endpoint?.host || "",
        m.endpoint?.port || "",
        Boolean(m.online),
        Boolean(m.running),
        m.points?.yc ?? 0,
        m.points?.yx ?? 0,
        m.points?.yk ?? 0,
        m.points?.yt ?? 0,
      ]),
    );
    if (modelsRenderKey !== lastModelsRenderKey) {
      lastModelsRenderKey = modelsRenderKey;
      const rows = models.map((model) => {
        const row = document.createElement("tr");
        const isOnlineRunning = Boolean(model.online && model.running);
        row.dataset.rtuId = String(model.rtu_id);
        if (isOnlineRunning) {
          row.classList.add("is-selectable");
          row.title = "点击选中该模型下发指令";
        }
        if (String(model.rtu_id) === activeRtu) {
          row.classList.add("is-selected");
        }
        const endpoint = model.endpoint;
        const address = endpoint?.host && endpoint?.port ? `${endpoint.host}:${endpoint.port}` : "—";
        row.append(text("td", String(model.model || "")));
        row.append(text("td", String(model.rtu_id ?? ""), "num"));
        row.append(text("td", address, "mono"));

        const statusCell = document.createElement("td");
        const statusText = model.online ? (model.running ? "正在同步" : "通道停止") : "模型离线";
        const statusCls = model.online ? (model.running ? "pill is-ok" : "pill is-warn") : "pill is-off";
        statusCell.append(text("span", statusText, statusCls));
        row.append(statusCell);

        const pts = model.points || {};
        row.append(text("td", ["yc", "yx", "yk", "yt"].map((kind) => pts[kind] ?? 0).join(" / "), "num"));

        const actionCell = document.createElement("td");
        const box = document.createElement("div");
        box.className = "row-actions";
        const toggleBtn = text(
          "button",
          model.running ? "停止" : "启动",
          model.running ? "row-btn is-danger" : "row-btn",
        );
        toggleBtn.type = "button";
        toggleBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          controlChannel(model, model.running ? "stop" : "start");
        });
        const pointsBtn = text("button", "点表", "row-btn");
        pointsBtn.type = "button";
        pointsBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          const sel = get("pointsRtuSelect");
          if (sel) sel.value = String(model.rtu_id);
          setActiveViewTab("points");
        });
        const logsBtn = text("button", "日志", "row-btn");
        logsBtn.type = "button";
        logsBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          const sel = get("logsRtuSelect");
          if (sel) sel.value = String(model.rtu_id);
          setActiveViewTab("logs");
        });
        box.append(toggleBtn, pointsBtn, logsBtn);
        actionCell.append(box);
        row.append(actionCell);
        return row;
      });
      if (!rows.length) {
        const cell = text("td", "暂无在线模型，请在模拟台启动模型服务。", "empty");
        cell.colSpan = 6;
        const row = document.createElement("tr");
        row.append(cell);
        rows.push(row);
      }
      get("modelRows").replaceChildren(...rows);
    } else {
      syncSelectedModelRowHighlight();
    }
    await loadControlPoints(false);
    if (activeViewTab === "points" && manual) await loadPointsTable();
    else if (activeViewTab === "logs" && manual) await loadChannelLogs();
  } catch (error) {
    if (error?.name !== "AbortError") {
      get("bridgeError").textContent = error.message;
    }
  } finally {
    refreshInFlight = false;
    scheduleNextRefresh(REFRESH_INTERVAL_MS);
  }
}

document.querySelectorAll("[data-view-tab]").forEach((btn) => {
  btn.addEventListener("click", () => setActiveViewTab(btn.dataset.viewTab));
});

get("modelRows").addEventListener("click", (event) => {
  if (event.target instanceof Element && event.target.closest("a, button")) return;
  const row = event.target instanceof Element ? event.target.closest("tr.is-selectable[data-rtu-id]") : null;
  if (!row) return;
  const rtuSelect = get("rtu");
  const targetRtu = row.dataset.rtuId || "";
  if (rtuSelect && targetRtu && rtuSelect.value !== targetRtu) {
    rtuSelect.value = targetRtu;
    syncSelectedModelRowHighlight();
    loadControlPoints(true);
  }
});

get("rtu").addEventListener("change", () => {
  syncSelectedModelRowHighlight();
  loadControlPoints(true);
});

get("kind").addEventListener("change", () => {
  syncValueInputMode();
  loadControlPoints(true);
});

get("point").addEventListener("change", () => {
  updateSelectedPointMeta(true);
});

get("pointSearch")?.addEventListener("input", () => {
  renderPointOptions();
});

get("refreshStatusBtn")?.addEventListener("click", () => {
  refresh(true);
});

get("refreshPointsBtn")?.addEventListener("click", () => {
  loadControlPoints(true);
});

get("pointsRtuSelect")?.addEventListener("change", () => loadPointsTable());
get("pointsKindSelect")?.addEventListener("change", () => loadPointsTable());
get("pointsTableSearch")?.addEventListener("input", () => renderPointsTableRows());
get("reloadPointsTableBtn")?.addEventListener("click", () => loadPointsTable());
get("logsRtuSelect")?.addEventListener("change", () => loadChannelLogs());
get("reloadLogsBtn")?.addEventListener("click", () => loadChannelLogs());

get("commandForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const rtu = Number(get("rtu").value);
  const kind = get("kind").value;
  const point = Number(get("point").value);
  const rawValueText = kind === "yk"
    ? String(get("valueSelect").value ?? "").trim()
    : String(get("value").value ?? "").trim();
  const receipt = get("receipt");
  get("send").disabled = true;
  try {
    if (!rtu || !Number.isSafeInteger(point) || point <= 0) {
      throw new Error("请选择有效模型与控制点。");
    }
    if (!rawValueText) {
      throw new Error("请填写指令值（不能为空）。");
    }
    const value = Number(rawValueText);
    if (!Number.isFinite(value)) {
      throw new Error("指令值必须为有效数字。");
    }
    if (kind === "yk" && value !== 0 && value !== 1) {
      throw new Error("遥控指令值只能为 0 或 1。");
    }
    const cached = pointItemsByNo.get(String(point));
    const displayName = cached?.name || `${kind.toUpperCase()}/${point}`;
    const valueLabel = kind === "yk" ? (value === 1 ? "1（合/投入）" : "0（分/退出）") : String(value);
    const isHighRisk = kind === "yk" && value === 0;
    const confirmed = await confirmScadaCommand(
      `目标：RTU ${rtu} · ${displayName} → ${valueLabel}`,
      {
        title: "确认下发仿真指令？",
        danger: isHighRisk,
        confirmLabel: isHighRisk ? "确认分闸/退出" : "确认下发",
      },
    );
    if (!confirmed) return;
    const result = await api("/api/simulator104/commands", {
      rtu_id: rtu,
      kind,
      pnt_no: point,
      value,
    });
    if (result.item?.applied_to_simulator !== true) throw new Error("尚未收到模型接受回执。");
    const msg = `模型已接受 ${displayName} = ${valueLabel}`;
    receipt.textContent = msg;
    receipt.classList.remove("is-error", "error");
    pushReceiptHistory(`RTU ${rtu} · ${displayName} → ${valueLabel}`, false);
    await loadControlPoints(true);
    refresh(true);
  } catch (error) {
    receipt.textContent = error.message;
    receipt.classList.add("is-error");
    pushReceiptHistory(`失败：${error.message}`, true);
  } finally {
    get("send").disabled = false;
  }
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (refreshTimerId !== null) {
      clearTimeout(refreshTimerId);
      refreshTimerId = null;
    }
    return;
  }
  refresh(true);
});

initThemeToggle();
syncValueInputMode();
refresh(true);
