/**
 * 极地微电网模拟台 · 内嵌 IEC104 联动模块
 * 与模拟台共享顶边栏、左侧导航边栏、8 套主题与统一模态确认弹窗；
 * 仅在处于 IEC104 联动页签时按需轮询，切离后立即停表并中止在途请求。
 */
(function initEmbeddedScada104Module() {
  if (typeof document === "undefined" || typeof window === "undefined") return;

  const REFRESH_INTERVAL_MS = 1800;
  const MAX_RECENT_RECEIPTS = 5;

  const get = (id) => document.getElementById(id);
  const tr = (phrase) => (typeof translatePhrase === "function" ? translatePhrase(phrase) : phrase);
  const textNode = (tag, value, className = "") => {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  };
  const apiBase = () => {
    if (typeof controlPlaneApiBase === "string" && controlPlaneApiBase) {
      return controlPlaneApiBase.replace(/\/$/, "");
    }
    return "";
  };

  let isActive = false;
  let boundSection = null;
  let activeViewTab = "service";
  let loadedPointScope = "";
  let allLoadedPoints = [];
  let pointItemsByNo = new Map();
  let pointLoadSeq = 0;
  let pointAbortController = null;
  let statusAbortController = null;
  let pointsTableAbortController = null;
  let logsAbortController = null;
  let serviceAbortController = null;
  let pointsTableReqSeq = 0;
  let logsReqSeq = 0;
  let serviceReqSeq = 0;
  let refreshTimerId = null;
  let refreshInFlight = false;
  let pendingManualRefresh = false;
  let lastRtuOptionsKey = "";
  let lastAllRtuOptionsKey = "";
  let lastServiceRowsKey = "";
  let lastRtuDefRowsKey = "";
  let lastChDefLoaded = "";
  let latestServiceOverview = null;
  let pointsTablePage = 0;
  const POINTS_PAGE_SIZE = 100;
  let loadedPointsTableItems = [];
  let loadedChannelLogItems = [];
  let pointsSortState = { col: "pnt_no", dir: "none" };
  let preferredModelName = "";
  let latestModelsList = [];
  const recentReceipts = [];

  async function api(path, body, { signal } = {}) {
    const url = `${apiBase()}${path}`;
    const init = body === undefined
      ? { signal }
      : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      };
    const response = await fetch(url, init);
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

  async function confirmAction(targetText, { title = "确认执行操作？", message = "请核对目标与指令值后再继续。", confirmLabel = "确认执行" } = {}) {
    if (typeof confirmDangerousAction === "function") {
      return confirmDangerousAction({
        title: tr(title),
        target: targetText,
        message: tr(message),
        confirmLabel: tr(confirmLabel),
      });
    }
    return window.confirm(`${title}\n${targetText}`);
  }

  function toast(msg, level = "info", duration = 2000) {
    if (typeof showUiToast === "function") {
      showUiToast(msg, level, duration);
    }
  }

  function formatTelemetryValue(val, kind) {
    if (val === null || val === undefined || val === "") return "—";
    const num = Number(val);
    if (!Number.isFinite(num)) return String(val);
    if (kind === "yx" || kind === "yk") return String(Math.round(num));
    if (Number.isInteger(num)) return String(num);
    return num.toFixed(2);
  }

  function setActiveViewTab(tab) {
    const normalized = tab === "channels" ? "service" : tab;
    if (!["service", "config", "points", "commands", "logs"].includes(normalized)) return;
    activeViewTab = normalized;
    const root = document.querySelector('section[data-page="scada104"]');
    if (!root) return;
    root.querySelectorAll("[data-scada104-tab]").forEach((btn) => {
      const active = btn.dataset.scada104Tab === normalized;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    root.querySelectorAll("[data-scada104-pane]").forEach((pane) => {
      pane.hidden = pane.dataset.scada104Pane !== normalized;
    });
    if (isActive) {
      if (normalized === "service" || normalized === "config") {
        loadServiceOverview(normalized === "config");
      } else if (normalized === "points") {
        loadPointsTable();
      } else if (normalized === "commands") {
        loadControlPoints(true);
      } else if (normalized === "logs") {
        loadChannelLogs();
      }
    }
  }

  function syncValueInputMode() {
    const kindEl = get("scada104Kind");
    const select = get("scada104ValueSelect");
    const input = get("scada104ValueInput");
    if (!kindEl || !select || !input) return;
    const isYk = kindEl.value === "yk";
    select.hidden = !isYk;
    select.required = isYk;
    select.disabled = !isYk;
    input.hidden = isYk;
    input.required = !isYk;
    input.disabled = isYk;
    updateSelectedPointMeta(false);
  }

  function updateSelectedPointMeta(prefillYtValue = false) {
    const metaNode = get("scada104PointMeta");
    const pointVal = get("scada104Point")?.value || "";
    const kind = get("scada104Kind")?.value || "yk";
    if (!metaNode) return;
    const item = pointItemsByNo.get(String(pointVal));
    if (!item) {
      metaNode.textContent = "";
      return;
    }
    const hasValue = item.value !== null && item.value !== undefined && item.value !== "";
    const valueText = hasValue ? String(item.value) : "—";
    const statusText = item.disabled ? tr("已禁操") : tr("可操作");
    metaNode.textContent = `#${item.pnt_no} ${item.source_name || item.name} · ${tr("当前值")} ${valueText} · ${statusText}`;
    if (prefillYtValue && kind === "yt" && hasValue) {
      const input = get("scada104ValueInput");
      if (input && Number.isFinite(Number(item.value))) {
        input.value = String(item.value);
      }
    }
  }

  function renderPointOptions() {
    const pointSelect = get("scada104Point");
    if (!pointSelect) return;
    const keyword = String(get("scada104PointSearch")?.value || "").trim().toLowerCase();
    const prevValue = pointSelect.value;
    const filtered = keyword
      ? allLoadedPoints.filter((item) => (
        `${item.pnt_no} ${item.name || ""} ${item.source_name || ""}`.toLowerCase().includes(keyword)
      ))
      : allLoadedPoints;

    const placeholderText = !allLoadedPoints.length
      ? tr("暂无可用控制点")
      : (filtered.length ? `${tr("控制点")} (${filtered.length}/${allLoadedPoints.length})` : tr("无匹配控制点"));
    const options = [new Option(placeholderText, "")];
    for (const item of filtered) {
      const valHint = item.value !== null && item.value !== undefined && item.value !== "" ? ` [${item.value}]` : "";
      const label = `${item.pnt_no} · ${item.name || item.source_name}${valHint}${item.disabled ? ` (${tr("已禁操")})` : ""}`;
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
    const rtu = get("scada104Rtu")?.value || "";
    const kind = get("scada104Kind")?.value || "yk";
    const pointSelect = get("scada104Point");
    if (!pointSelect) return;
    const scope = `${rtu}:${kind}`;
    if (!rtu) {
      if (pointAbortController) pointAbortController.abort();
      loadedPointScope = "";
      allLoadedPoints = [];
      pointItemsByNo = new Map();
      pointSelect.replaceChildren(new Option(tr("请先选择模型"), ""));
      pointSelect.disabled = true;
      updateSelectedPointMeta(false);
      return;
    }
    if (!force && scope === loadedPointScope) return;
    if (pointAbortController) pointAbortController.abort();
    pointAbortController = new AbortController();
    const requestSeq = ++pointLoadSeq;
    try {
      const data = await api(
        `/api/simulator104/points?rtu_id=${encodeURIComponent(rtu)}&kind=${encodeURIComponent(kind)}`,
        undefined,
        { signal: pointAbortController.signal },
      );
      if (requestSeq !== pointLoadSeq || !isActive) return;
      loadedPointScope = scope;
      const items = Array.isArray(data.items) ? data.items : [];
      allLoadedPoints = items;
      pointItemsByNo = new Map(items.map((item) => [String(item.pnt_no), item]));
      renderPointOptions();
    } catch (error) {
      if (error?.name === "AbortError" || requestSeq !== pointLoadSeq) {
        if (loadedPointScope === scope) loadedPointScope = "";
        return;
      }
      loadedPointScope = "";
      allLoadedPoints = [];
      pointItemsByNo = new Map();
      pointSelect.replaceChildren(new Option(`${tr("失败")}: ${error.message}`, ""));
      pointSelect.disabled = true;
      updateSelectedPointMeta(false);
    }
  }

  function renderPointsTableRows() {
    const tbody = get("scada104PointsTableBody");
    const pageInfo = get("scada104PointsPageInfo");
    const prevBtn = get("scada104PointsPrevBtn");
    const nextBtn = get("scada104PointsNextBtn");
    if (!tbody) return;
    const kind = get("scada104PointsKindSelect")?.value || "yc";
    const rtu = Number(get("scada104PointsRtuSelect")?.value || 0);
    const keyword = String(get("scada104PointsSearch")?.value || "").trim().toLowerCase();
    const filtered = keyword
      ? loadedPointsTableItems.filter((item) => (
        `${item.pnt_no} ${item.name || ""} ${item.source_name || ""} ${item.io_address ?? ""} ${item.io_address_hex || ""} ${item.type_name || ""}`
          .toLowerCase()
          .includes(keyword)
      ))
      : loadedPointsTableItems.slice();

    if (pointsSortState.dir !== "none") {
      const dir = pointsSortState.dir === "ascending" ? 1 : -1;
      const col = pointsSortState.col;
      filtered.sort((a, b) => {
        if (col === "pnt_no" || col === "value" || col === "io_address") {
          return (Number(a[col] ?? -Infinity) - Number(b[col] ?? -Infinity)) * dir;
        }
        return String(a[col] || "").localeCompare(String(b[col] || ""), "zh-CN") * dir;
      });
    }

    const totalPages = Math.max(1, Math.ceil(filtered.length / POINTS_PAGE_SIZE));
    if (pointsTablePage >= totalPages) pointsTablePage = totalPages - 1;
    if (pointsTablePage < 0) pointsTablePage = 0;
    const start = pointsTablePage * POINTS_PAGE_SIZE;
    const slice = filtered.slice(start, start + POINTS_PAGE_SIZE);
    if (pageInfo) pageInfo.textContent = `${filtered.length ? pointsTablePage + 1 : 0} / ${filtered.length ? totalPages : 0} (${filtered.length})`;
    if (prevBtn) prevBtn.disabled = pointsTablePage <= 0;
    if (nextBtn) nextBtn.disabled = pointsTablePage + 1 >= totalPages;

    if (!slice.length) {
      const cell = textNode("td", loadedPointsTableItems.length ? tr("无匹配点表") : tr("请选择模型查看点表"), "empty-state");
      cell.colSpan = 9;
      const trEl = document.createElement("tr");
      trEl.append(cell);
      tbody.replaceChildren(trEl);
      return;
    }

    const rows = slice.map((item) => {
      const trEl = document.createElement("tr");
      const noTd = textNode("td", String(item.pnt_no), "numeric-cell scada104-copyable");
      noTd.title = tr("点击复制点号");
      noTd.addEventListener("click", () => {
        navigator.clipboard?.writeText(String(item.pnt_no)).then(() => toast(tr("已复制到剪贴板"), "ok", 1400)).catch(() => {});
      });
      trEl.append(noTd);

      trEl.append(textNode("td", item.name || item.source_name || ""));

      const srcTd = textNode("td", item.source_name || "—", "mono-cell scada104-copyable");
      srcTd.title = tr("点击复制仿真源名");
      srcTd.addEventListener("click", () => {
        if (item.source_name) {
          navigator.clipboard?.writeText(String(item.source_name)).then(() => toast(tr("已复制到剪贴板"), "ok", 1400)).catch(() => {});
        }
      });
      trEl.append(srcTd);

      const ioaText = item.io_address !== undefined && item.io_address !== null
        ? `${item.io_address} (${item.io_address_hex || ""})`
        : "—";
      const ioaTd = textNode("td", ioaText, "mono-cell scada104-copyable");
      ioaTd.addEventListener("click", () => {
        if (item.io_address !== undefined && item.io_address !== null) {
          navigator.clipboard?.writeText(String(item.io_address)).then(() => toast(tr("已复制到剪贴板"), "ok", 1400)).catch(() => {});
        }
      });
      trEl.append(ioaTd);

      trEl.append(textNode("td", item.type_id !== undefined ? `${item.type_id} · ${item.type_name || ""}` : "—", "mono-cell"));
      trEl.append(textNode("td", String(item.time_tag || "NONE"), "mono-cell"));
      trEl.append(textNode("td", formatTelemetryValue(item.value, kind), "numeric-cell"));

      const statusTd = document.createElement("td");
      const isValid = Number(item.status) === 0;
      statusTd.append(
        textNode(
          "span",
          isValid ? tr("有效") : `${tr("无效")}(${item.status ?? 128})`,
          isValid ? "scada104-pill is-ok" : "scada104-pill is-off",
        ),
      );
      trEl.append(statusTd);

      const opTd = document.createElement("td");
      if (kind === "yk" || kind === "yt") {
        const wrap = document.createElement("div");
        wrap.className = "scada104-row-actions";
        const sendBtn = textNode("button", tr("去下发"), "compact-action-btn");
        sendBtn.type = "button";
        sendBtn.disabled = Boolean(item.disabled);
        sendBtn.addEventListener("click", async () => {
          if (get("scada104Rtu")) get("scada104Rtu").value = String(rtu);
          if (get("scada104Kind")) get("scada104Kind").value = kind;
          syncValueInputMode();
          setActiveViewTab("commands");
          await loadControlPoints(true);
          if (get("scada104Point")) {
            get("scada104Point").value = String(item.pnt_no);
            updateSelectedPointMeta(true);
            get("scada104Point").focus();
          }
        });

        const disableBtn = textNode(
          "button",
          item.disabled ? tr("启用") : tr("禁操"),
          item.disabled ? "compact-action-btn" : "compact-action-btn is-danger",
        );
        disableBtn.type = "button";
        disableBtn.addEventListener("click", async () => {
          disableBtn.disabled = true;
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
            const errEl = get("scada104BridgeError");
            if (errEl) errEl.textContent = err.message;
          } finally {
            disableBtn.disabled = false;
          }
        });
        wrap.append(sendBtn, disableBtn);
        opTd.append(wrap);
      } else {
        opTd.append(textNode("span", "—", "scada104-pill is-off"));
      }
      trEl.append(opTd);
      return trEl;
    });
    tbody.replaceChildren(...rows);
  }

  async function loadPointsTable() {
    const rtu = get("scada104PointsRtuSelect")?.value || "";
    const kind = get("scada104PointsKindSelect")?.value || "yc";
    const tbody = get("scada104PointsTableBody");
    if (!tbody) return;
    if (!rtu) {
      loadedPointsTableItems = [];
      renderPointsTableRows();
      return;
    }
    const reqSeq = ++pointsTableReqSeq;
    if (pointsTableAbortController) pointsTableAbortController.abort();
    pointsTableAbortController = new AbortController();
    try {
      const data = await api(
        `/api/simulator104/point-definitions?rtu_id=${encodeURIComponent(rtu)}&kind=${encodeURIComponent(kind)}`,
        undefined,
        { signal: pointsTableAbortController.signal },
      );
      if (reqSeq !== pointsTableReqSeq || !isActive) return;
      loadedPointsTableItems = Array.isArray(data.items) ? data.items : [];
      renderPointsTableRows();
    } catch (err) {
      if (err?.name === "AbortError" || reqSeq !== pointsTableReqSeq) return;
      loadedPointsTableItems = [];
      const cell = textNode("td", `${tr("失败")}: ${err.message}`, "empty-state");
      cell.colSpan = 9;
      const trEl = document.createElement("tr");
      trEl.append(cell);
      tbody.replaceChildren(trEl);
    }
  }

  function renderChannelLogRows() {
    const tbody = get("scada104LogsTableBody");
    if (!tbody) return;
    const levelFilter = String(get("scada104LogsLevelSelect")?.value || "all").toUpperCase();
    const keyword = String(get("scada104LogsSearch")?.value || "").trim().toLowerCase();
    const filtered = loadedChannelLogItems.filter((item) => {
      const lvl = String(item.level || "INFO").toUpperCase();
      if (levelFilter !== "ALL" && lvl !== levelFilter) return false;
      if (keyword && !`${item.time || ""} ${lvl} ${item.message || ""}`.toLowerCase().includes(keyword)) return false;
      return true;
    });
    if (!filtered.length) {
      const cell = textNode("td", tr("暂无通信日志"), "empty-state");
      cell.colSpan = 3;
      const trEl = document.createElement("tr");
      trEl.append(cell);
      tbody.replaceChildren(trEl);
      return;
    }
    const rows = filtered.map((item) => {
      const trEl = document.createElement("tr");
      trEl.append(textNode("td", String(item.time || ""), "mono-cell"));
      const lvl = String(item.level || "INFO").toUpperCase();
      const lvlTd = document.createElement("td");
      const cls = lvl === "ERROR"
        ? "scada104-pill is-danger"
        : (lvl === "WARN" || lvl === "WARNING" ? "scada104-pill is-warn" : (lvl === "INFO" ? "scada104-pill is-ok" : "scada104-pill is-off"));
      lvlTd.append(textNode("span", lvl, cls));
      trEl.append(lvlTd);
      trEl.append(textNode("td", String(item.message || ""), "scada104-log-msg"));
      return trEl;
    });
    tbody.replaceChildren(...rows);
  }

  async function loadChannelLogs() {
    const rtu = get("scada104LogsRtuSelect")?.value || "";
    const tbody = get("scada104LogsTableBody");
    if (!tbody) return;
    if (!rtu) {
      loadedChannelLogItems = [];
      const cell = textNode("td", tr("请选择模型查看通信日志"), "empty-state");
      cell.colSpan = 3;
      const trEl = document.createElement("tr");
      trEl.append(cell);
      tbody.replaceChildren(trEl);
      return;
    }
    const reqSeq = ++logsReqSeq;
    if (logsAbortController) logsAbortController.abort();
    logsAbortController = new AbortController();
    try {
      const data = await api(
        `/api/simulator104/logs?rtu_id=${encodeURIComponent(rtu)}&limit=120`,
        undefined,
        { signal: logsAbortController.signal },
      );
      if (reqSeq !== logsReqSeq || !isActive) return;
      loadedChannelLogItems = Array.isArray(data.items) ? data.items : [];
      renderChannelLogRows();
    } catch (err) {
      if (err?.name === "AbortError" || reqSeq !== logsReqSeq) return;
      loadedChannelLogItems = [];
      const cell = textNode("td", `${tr("失败")}: ${err.message}`, "empty-state");
      cell.colSpan = 3;
      const trEl = document.createElement("tr");
      trEl.append(cell);
      tbody.replaceChildren(trEl);
    }
  }

  function formatEpochMs(ms) {
    const num = Number(ms || 0);
    if (!Number.isFinite(num) || num <= 0) return "—";
    const dt = new Date(num);
    if (Number.isNaN(dt.getTime())) return "—";
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(dt.getMonth() + 1)}-${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}:${pad(dt.getSeconds())}`;
  }

  function showServiceNotice(message, isError = false) {
    const node = get("scada104ServiceNotice");
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("is-error", Boolean(isError));
  }

  function syncConfigHostPreset(host) {
    const presetSel = get("scada104CfgHostPreset");
    const customWrap = get("scada104CfgCustomHostWrap");
    const customInput = get("scada104CfgHostCustom");
    if (!presetSel) return;
    const val = String(host || "127.0.0.1").trim() || "127.0.0.1";
    const presets = new Set(["127.0.0.1", "0.0.0.0", "localhost"]);
    if (presets.has(val)) {
      presetSel.value = val;
      if (customWrap) customWrap.hidden = true;
      if (customInput) customInput.required = false;
    } else {
      presetSel.value = "__custom__";
      if (customWrap) customWrap.hidden = false;
      if (customInput) {
        customInput.value = val;
        customInput.required = true;
      }
    }
  }

  function selectedConfigHost() {
    const preset = get("scada104CfgHostPreset")?.value || "127.0.0.1";
    if (preset === "__custom__") {
      return String(get("scada104CfgHostCustom")?.value || "").trim();
    }
    return preset;
  }

  function isFocusInside(containerId) {
    const el = get(containerId);
    return Boolean(el && document.activeElement && el.contains(document.activeElement));
  }

  function populateChannelDefForm(ch, svc = null) {
    if (!ch) return;
    const cfg = svc?.config || {};
    const proto = svc?.protocol_config || {};
    const setVal = (id, v) => {
      const el = get(id);
      if (el) el.value = v === undefined || v === null ? "" : String(v);
    };
    syncConfigHostPreset(cfg.bind_ip || ch.remote_host || "127.0.0.1");
    setVal("scada104ChName", ch.name ?? "");
    setVal("scada104ChRtuAddr", ch.rtu_addr ?? ch.channel_id ?? 1);
    setVal("scada104ChPort", cfg.port ?? ch.remote_port ?? 2405);
    setVal("scada104CfgMaxConn", cfg.max_connections ?? 0);
    setVal("scada104CfgTickMs", cfg.tick_rate_ms ?? 100);
    setVal("scada104CfgSelectTimeoutMs", cfg.select_timeout_ms ?? 10000);
    setVal("scada104ChYcBegin", ch.ycbegin_addr ?? 16385);
    setVal("scada104ChYxBegin", ch.yxbegin_addr ?? 1);
    setVal("scada104ChYkBegin", ch.ykbegin_addr ?? 24577);
    setVal("scada104ChYtBegin", ch.ytbegin_addr ?? 25089);
    setVal("scada104ChYcType", ch.yc_data_type ?? 1);
    setVal("scada104ChYxType", ch.yx_data_type ?? 1);
    setVal("scada104ChYkType", ch.yk_excute_type ?? 1);
    setVal("scada104ChYtType", ch.yt_excute_type ?? 1);
    setVal("scada104CfgK", proto.k ?? cfg.k ?? ch.k ?? 12);
    setVal("scada104CfgW", proto.w ?? cfg.w ?? ch.w ?? 8);
    setVal("scada104CfgT1", proto.t1 ?? cfg.t1 ?? ch.t1 ?? 15);
    setVal("scada104CfgT2", proto.t2 ?? cfg.t2 ?? ch.t2 ?? 10);
    setVal("scada104CfgT3", proto.t3 ?? cfg.t3 ?? ch.t3 ?? 20);
    setVal("scada104CfgMaxAsdu", proto.max_asdu_length ?? cfg.max_asdu_length ?? ch.max_asdu_length ?? 249);
    setVal("scada104ChCallAll", ch.call_alldata_time ?? 60);
    setVal("scada104ChAutoAll", ch.if_autosend_alldata ?? 1);
  }

  function renderConnectionsForService(svc) {
    const tbody = get("scada104ConnectionsBody");
    const summary = get("scada104ConnSummary");
    const activeConn = Number(svc?.active_connections || 0);
    const openConn = Number(svc?.open_connections || 0);
    if (summary) {
      summary.textContent = `${activeConn} ${tr("活动")} / ${openConn} ${tr("打开")}`;
      summary.className = activeConn > 0 ? "scada104-pill is-ok" : "scada104-pill is-off";
    }
    if (!tbody) return;
    const items = Array.isArray(svc?.connections) ? svc.connections : [];
    if (!items.length) {
      const td = textNode("td", tr("暂无客户端连接记录"), "empty-state");
      td.colSpan = 3;
      const trEl = document.createElement("tr");
      trEl.append(td);
      tbody.replaceChildren(trEl);
      return;
    }
    const rows = items.map((conn) => {
      const trEl = document.createElement("tr");
      trEl.append(textNode("td", String(conn.time || conn.connected_at || "—"), "mono-cell"));
      trEl.append(textNode("td", String(conn.ip || conn.address || conn.remote || "—"), "mono-cell"));
      const stTd = document.createElement("td");
      stTd.append(textNode("span", tr(String(conn.status || "已接入")), "scada104-pill is-ok"));
      trEl.append(stTd);
      return trEl;
    });
    tbody.replaceChildren(...rows);
  }

  function renderRtuDefRows(rtus) {
    const tbody = get("scada104RtuDefRows");
    if (!tbody || isFocusInside("scada104RtuDefRows")) return;
    const key = JSON.stringify(
      (rtus || []).map((r) => [r.rtu_id, r.channel_id, r.channel_type, r.name, r.process_enable, r.packet_recording, r.process_status]),
    );
    if (key === lastRtuDefRowsKey) return;
    lastRtuDefRowsKey = key;
    if (!rtus || !rtus.length) {
      const td = textNode("td", tr("暂无 RTU 定义"), "empty-state");
      td.colSpan = 8;
      const trEl = document.createElement("tr");
      trEl.append(td);
      tbody.replaceChildren(trEl);
      return;
    }
    const rows = rtus.map((rtu) => {
      const trEl = document.createElement("tr");
      trEl.append(textNode("td", String(rtu.rtu_id), "numeric-cell"));
      trEl.append(textNode("td", String(rtu.channel_id ?? rtu.rtu_id), "numeric-cell"));
      trEl.append(textNode("td", String(rtu.channel_type || "iec104"), "mono-cell"));

      const nameTd = document.createElement("td");
      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.className = "scada104-table-input";
      nameInput.value = String(rtu.name || rtu.model || "");
      nameTd.append(nameInput);
      trEl.append(nameTd);

      const enTd = document.createElement("td");
      const enSel = document.createElement("select");
      enSel.className = "scada104-table-select";
      enSel.append(new Option(tr("启用"), "1"), new Option(tr("停用"), "0"));
      enSel.value = Number(rtu.process_enable ?? 1) ? "1" : "0";
      enTd.append(enSel);
      trEl.append(enTd);

      const recTd = document.createElement("td");
      const recSel = document.createElement("select");
      recSel.className = "scada104-table-select";
      recSel.append(new Option(tr("开启"), "1"), new Option(tr("关闭"), "0"));
      recSel.value = Number(rtu.packet_recording ?? 0) ? "1" : "0";
      recTd.append(recSel);
      trEl.append(recTd);

      const stTd = document.createElement("td");
      const active = Number(rtu.process_status || 0) === 2;
      stTd.append(textNode("span", active ? tr("运行中") : tr("已停止"), active ? "scada104-pill is-ok" : "scada104-pill is-off"));
      trEl.append(stTd);

      const opTd = document.createElement("td");
      const saveBtn = textNode("button", tr("保存"), "compact-action-btn");
      saveBtn.type = "button";
      saveBtn.addEventListener("click", async () => {
        saveBtn.disabled = true;
        try {
          await api("/api/simulator104/rtu/update", {
            rtu_id: Number(rtu.rtu_id),
            name: nameInput.value.trim(),
            process_enable: Number(enSel.value),
            packet_recording: Number(recSel.value),
          });
          lastRtuDefRowsKey = "";
          showServiceNotice(`${tr("已保存")} RTU ${rtu.rtu_id}`, false);
          toast(`${tr("已保存")} RTU ${rtu.rtu_id}`, "ok", 1800);
          await loadServiceOverview(false);
        } catch (err) {
          showServiceNotice(err.message, true);
        } finally {
          saveBtn.disabled = false;
        }
      });
      opTd.append(saveBtn);
      trEl.append(opTd);
      return trEl;
    });
    tbody.replaceChildren(...rows);
  }

  async function controlServiceProcess(action, { rtuId = null, scope = "single", label = "" } = {}) {
    if (action === "stop" || action === "restart") {
      const isAll = scope === "all";
      const title = isAll
        ? (action === "stop" ? "确认停止全部 IEC104 服务？" : "确认重启全部 IEC104 服务？")
        : (action === "stop" ? "确认停止 IEC104 通道？" : "确认重启 IEC104 服务？");
      const message = action === "stop"
        ? "停止后对应的 IEC104 通信将中断，直至重新启动。"
        : "重启期间活动 IEC104 客户端连接将短暂断开并重新监听。";
      const ok = await confirmAction(label || (isAll ? "全部 IEC104 服务" : `RTU ${rtuId}`), {
        title,
        message,
        confirmLabel: action === "stop" ? "停止通道" : "重启",
      });
      if (!ok) return;
    }
    try {
      await api("/api/simulator104/service/process", {
        action,
        scope,
        ...(rtuId !== null && rtuId !== undefined ? { rtu_id: Number(rtuId) } : {}),
      });
      lastServiceRowsKey = "";
      lastRtuDefRowsKey = "";
      showServiceNotice(`${label || "IEC104"} · ${action.toUpperCase()}`, false);
      toast(`${label || "IEC104"} · ${action.toUpperCase()}`, "ok", 1800);
      await loadServiceOverview(true);
      await refresh(true);
    } catch (err) {
      showServiceNotice(err.message, true);
    }
  }

  function renderServiceOverview(data, forcePopulate = false) {
    latestServiceOverview = data;
    const host = data?.host || {};
    const services = Array.isArray(data?.services) ? data.services : [];
    const rtus = Array.isArray(data?.rtus) ? data.rtus : [];
    const channels = Array.isArray(data?.channels) ? data.channels : [];

    const setTxt = (id, txt) => {
      const node = get(id);
      if (node) node.textContent = txt;
    };
    setTxt("scada104HostState", data?.available ? (host.bridge_alive ? tr("运行中") : tr("已停止")) : tr("未启用"));
    setTxt("scada104HostPid", host.pid ? String(host.pid) : "—");
    setTxt("scada104HostChannels", `${host.running_channels ?? 0} / ${host.total_channels ?? 0}`);
    setTxt("scada104HostFirstPort", host.first_iec104_port ? String(host.first_iec104_port) : "—");
    setTxt("scada104HostInterval", host.interval ? `${host.interval} s` : "—");
    setTxt("scada104HostStartedAt", formatEpochMs(host.started_at));

    const svcKey = JSON.stringify(
      services.map((s) => [
        s.rtu_id, s.bind_ip, s.port, s.common_address, s.running, s.pid,
        s.points?.yc ?? 0, s.points?.yx ?? 0, s.points?.yk ?? 0, s.points?.yt ?? 0,
        s.active_connections, s.open_connections, s.rx_count, s.tx_count, s.error_count, s.last_error,
      ]),
    );
    const tbody = get("scada104ServiceRows");
    if (tbody && svcKey !== lastServiceRowsKey) {
      lastServiceRowsKey = svcKey;
      if (!services.length) {
        const td = textNode("td", tr("暂无 IEC104 服务实例"), "empty-state");
        td.colSpan = 10;
        const trEl = document.createElement("tr");
        trEl.append(td);
        tbody.replaceChildren(trEl);
      } else {
        const rows = services.map((svc) => {
          const trEl = document.createElement("tr");
          trEl.append(textNode("td", `${svc.model || svc.name} · RTU ${svc.rtu_id}`));
          trEl.append(textNode("td", `${svc.bind_ip || "127.0.0.1"}:${svc.port || "—"}`, "mono-cell"));
          trEl.append(textNode("td", String(svc.common_address ?? svc.rtu_id), "numeric-cell"));

          const stTd = document.createElement("td");
          stTd.append(
            textNode(
              "span",
              svc.running ? tr("运行中") : tr("已停止"),
              svc.running ? "scada104-pill is-ok" : "scada104-pill is-warn",
            ),
          );
          trEl.append(stTd);

          trEl.append(textNode("td", svc.pid ? String(svc.pid) : "—", "mono-cell"));
          const pts = svc.points || {};
          trEl.append(textNode("td", ["yc", "yx", "yk", "yt"].map((k) => pts[k] ?? 0).join(" / "), "numeric-cell"));
          trEl.append(textNode("td", `${svc.active_connections ?? 0} / ${svc.open_connections ?? 0}`, "numeric-cell"));
          trEl.append(textNode("td", `RX ${svc.rx_count ?? 0} / TX ${svc.tx_count ?? 0}`, "mono-cell"));

          const errTd = textNode("td", svc.last_error || "—", svc.last_error ? "scada104-err-cell" : "mono-cell");
          if (svc.last_error) errTd.title = svc.last_error;
          trEl.append(errTd);

          const opTd = document.createElement("td");
          const wrap = document.createElement("div");
          wrap.className = "scada104-row-actions";
          const startStopBtn = textNode(
            "button",
            svc.running ? tr("停止") : tr("启动"),
            svc.running ? "compact-action-btn is-danger" : "compact-action-btn",
          );
          startStopBtn.type = "button";
          startStopBtn.addEventListener("click", () => {
            controlServiceProcess(svc.running ? "stop" : "start", {
              rtuId: svc.rtu_id,
              scope: "single",
              label: `${svc.model} · RTU ${svc.rtu_id} (${svc.bind_ip}:${svc.port})`,
            });
          });
          const restartBtn = textNode("button", tr("重启"), "compact-action-btn");
          restartBtn.type = "button";
          restartBtn.addEventListener("click", () => {
            controlServiceProcess("restart", {
              rtuId: svc.rtu_id,
              scope: "single",
              label: `${svc.model} · RTU ${svc.rtu_id} (${svc.bind_ip}:${svc.port})`,
            });
          });
          const pointsBtn = textNode("button", tr("点表"), "compact-action-btn");
          pointsBtn.type = "button";
          pointsBtn.addEventListener("click", () => {
            const sel = get("scada104PointsRtuSelect");
            if (sel) sel.value = String(svc.rtu_id);
            setActiveViewTab("points");
          });
          const logsBtn = textNode("button", tr("日志"), "compact-action-btn");
          logsBtn.type = "button";
          logsBtn.addEventListener("click", () => {
            const sel = get("scada104LogsRtuSelect");
            if (sel) sel.value = String(svc.rtu_id);
            setActiveViewTab("logs");
          });
          wrap.append(startStopBtn, restartBtn, pointsBtn, logsBtn);
          opTd.append(wrap);
          trEl.append(opTd);
          return trEl;
        });
        tbody.replaceChildren(...rows);
      }
    }

    const connSel = get("scada104ConnRtuSelect");
    if (connSel) {
      const prev = connSel.value;
      const opts = services.length
        ? services.map((s) => new Option(`${s.model} · RTU ${s.rtu_id}`, String(s.rtu_id)))
        : [new Option(tr("选择模型"), "")];
      const nextKey = opts.map((o) => `${o.value}:${o.text}`).join("|");
      if (connSel.dataset.optKey !== nextKey) {
        connSel.dataset.optKey = nextKey;
        connSel.replaceChildren(...opts);
        if (opts.some((o) => o.value === prev)) connSel.value = prev;
        else if (opts.length) connSel.value = opts[0].value;
      }
      const connSvc = services.find((s) => String(s.rtu_id) === String(connSel.value)) || services[0] || null;
      renderConnectionsForService(connSvc);
    }

    renderRtuDefRows(rtus);

    const chSel = get("scada104ChDefSelect");
    if (chSel) {
      const prev = chSel.value;
      const opts = channels.length
        ? channels.map((c) => new Option(`CH ${c.channel_id} · ${c.name || c.model || ""} (${c.remote_host}:${c.remote_port})`, String(c.channel_id)))
        : [new Option(tr("暂无通道"), "")];
      const nextKey = opts.map((o) => `${o.value}:${o.text}`).join("|");
      if (chSel.dataset.optKey !== nextKey) {
        chSel.dataset.optKey = nextKey;
        chSel.replaceChildren(...opts);
        if (opts.some((o) => o.value === prev)) chSel.value = prev;
        else if (opts.length) chSel.value = opts[0].value;
      }
      const activeCh = channels.find((c) => String(c.channel_id) === String(chSel.value)) || channels[0] || null;
      const activeSvc = activeCh
        ? services.find((s) => String(s.channel_id) === String(activeCh.channel_id) || String(s.rtu_id) === String(activeCh.rtu_id)) || null
        : null;
      if (activeCh && (forcePopulate || lastChDefLoaded !== String(activeCh.channel_id)) && !isFocusInside("scada104ChDefForm")) {
        populateChannelDefForm(activeCh, activeSvc);
        lastChDefLoaded = String(activeCh.channel_id);
      }
    }
  }

  async function loadServiceOverview(forcePopulate = false) {
    const reqSeq = ++serviceReqSeq;
    if (serviceAbortController) serviceAbortController.abort();
    serviceAbortController = new AbortController();
    try {
      const data = await api("/api/simulator104/service", undefined, {
        signal: serviceAbortController.signal,
      });
      if (reqSeq !== serviceReqSeq || !isActive) return;
      renderServiceOverview(data, forcePopulate);
    } catch (err) {
      if (err?.name === "AbortError" || reqSeq !== serviceReqSeq) return;
      showServiceNotice(err.message, true);
    }
  }

  function pushReceiptHistory(message, isError = false) {
    const now = new Date();
    const stamp = [now.getHours(), now.getMinutes(), now.getSeconds()]
      .map((n) => String(n).padStart(2, "0"))
      .join(":");
    recentReceipts.unshift({ stamp, message, isError });
    if (recentReceipts.length > MAX_RECENT_RECEIPTS) recentReceipts.length = MAX_RECENT_RECEIPTS;
    const list = get("scada104RecentReceipts");
    if (!list) return;
    const nodes = recentReceipts.map((entry) => {
      const li = document.createElement("li");
      if (entry.isError) li.className = "is-error";
      li.append(textNode("span", entry.message), textNode("span", entry.stamp, "mono-cell"));
      return li;
    });
    list.replaceChildren(...nodes);
  }

  function clearPolling() {
    if (refreshTimerId !== null) {
      clearTimeout(refreshTimerId);
      refreshTimerId = null;
    }
    if (statusAbortController) statusAbortController.abort();
    if (pointAbortController) pointAbortController.abort();
    if (pointsTableAbortController) pointsTableAbortController.abort();
    if (logsAbortController) logsAbortController.abort();
    if (serviceAbortController) serviceAbortController.abort();
  }

  function scheduleNextRefresh(delayMs = REFRESH_INTERVAL_MS) {
    if (refreshTimerId !== null) {
      clearTimeout(refreshTimerId);
      refreshTimerId = null;
    }
    if (!isActive || document.hidden) return;
    if (activeViewTab === "points" && get("scada104PausePointsRefresh")?.checked) return;
    refreshTimerId = setTimeout(() => {
      refreshTimerId = null;
      refresh(false);
    }, delayMs);
  }

  function syncAuxiliaryRtuSelects(models) {
    const key = models.map((m) => `${m.rtu_id}:${m.model}`).join("|");
    if (key === lastAllRtuOptionsKey) return;
    lastAllRtuOptionsKey = key;
    for (const id of ["scada104PointsRtuSelect", "scada104LogsRtuSelect"]) {
      const sel = get(id);
      if (!sel) continue;
      const prev = sel.value;
      const opts = models.length
        ? models.map((m) => new Option(`${m.model} · RTU ${m.rtu_id}`, String(m.rtu_id)))
        : [new Option(tr("选择模型"), "")];
      sel.replaceChildren(...opts);
      if (opts.some((opt) => opt.value === prev)) sel.value = prev;
      else if (opts.length) sel.value = opts[0].value;
    }
  }

  async function refresh(manual = false) {
    if (!isActive || (document.hidden && !manual)) return;
    if (refreshInFlight) {
      if (manual) pendingManualRefresh = true;
      return;
    }
    refreshInFlight = true;
    if (statusAbortController) statusAbortController.abort();
    statusAbortController = new AbortController();
    try {
      const payload = await api("/api/simulator104/status", undefined, {
        signal: statusAbortController.signal,
      });
      if (!isActive) return;
      const models = Array.isArray(payload?.models) ? payload.models : [];
      latestModelsList = models;
      const errors = payload?.errors && typeof payload.errors === "object" ? payload.errors : {};
      const dbNode = get("scada104Database");
      if (dbNode) dbNode.textContent = payload?.database ? `${payload.database}` : "";
      const errNode = get("scada104BridgeError");
      if (errNode) {
        errNode.textContent = Object.entries(errors)
          .map(([k, v]) => `${k}：${v}`)
          .join(" · ");
      }
      const extLink = get("scada104ExternalLink");
      if (extLink) {
        // 104 服务定义与管控已全量内嵌在本页，不外链独立 scdfe_s Web。
        extLink.href = "#";
        extLink.hidden = true;
      }

      syncAuxiliaryRtuSelects(models);

      const rtuSel = get("scada104Rtu");
      const selectedRtu = rtuSel?.value || "";
      const onlineModels = models.filter((m) => m?.online && m?.running);
      const rtuOptionsKey = onlineModels.map((m) => `${m.rtu_id}:${m.model}`).join("|");
      if (rtuSel && rtuOptionsKey !== lastRtuOptionsKey) {
        lastRtuOptionsKey = rtuOptionsKey;
        const options = [new Option(tr("选择模型"), "")];
        for (const m of onlineModels) {
          options.push(new Option(`${m.model} · RTU ${m.rtu_id}`, String(m.rtu_id)));
        }
        rtuSel.replaceChildren(...options);
        const nextRtu = options.some((opt) => opt.value === selectedRtu)
          ? selectedRtu
          : (options.length === 2 ? options[1].value : "");
        rtuSel.value = nextRtu;
      }
      applyPreferredModelSelection(models);

      await loadControlPoints(false);
      const pausedPoints = Boolean(get("scada104PausePointsRefresh")?.checked);
      if (activeViewTab === "service" || activeViewTab === "config") {
        await loadServiceOverview(false);
      } else if (activeViewTab === "points" && (manual || !pausedPoints)) {
        await loadPointsTable();
      } else if (activeViewTab === "logs") {
        await loadChannelLogs();
      }
    } catch (error) {
      if (error?.name !== "AbortError") {
        const errEl = get("scada104BridgeError");
        if (errEl) errEl.textContent = error.message;
      }
    } finally {
      refreshInFlight = false;
      if (pendingManualRefresh && isActive) {
        pendingManualRefresh = false;
        refresh(true);
      } else {
        scheduleNextRefresh(REFRESH_INTERVAL_MS);
      }
    }
  }

  function bindDebouncedSearch(inputEl, handler, delayMs = 150) {
    if (!inputEl) return;
    let timer = null;
    let composing = false;
    inputEl.addEventListener("compositionstart", () => { composing = true; });
    inputEl.addEventListener("compositionend", () => {
      composing = false;
      clearTimeout(timer);
      handler();
    });
    inputEl.addEventListener("blur", () => { composing = false; });
    inputEl.addEventListener("input", () => {
      if (composing) return;
      clearTimeout(timer);
      timer = setTimeout(handler, delayMs);
    });
  }

  function bindEventsOnce() {
    const section = document.querySelector('section[data-page="scada104"]');
    if (!section || boundSection === section) return;
    boundSection = section;

    section.querySelectorAll("[data-scada104-tab]").forEach((btn) => {
      btn.addEventListener("click", () => setActiveViewTab(btn.dataset.scada104Tab));
    });

    get("scada104StartAllBtn")?.addEventListener("click", () => controlServiceProcess("start", { scope: "all", label: "全部 IEC104 服务" }));
    get("scada104RestartAllBtn")?.addEventListener("click", () => controlServiceProcess("restart", { scope: "all", label: "全部 IEC104 服务" }));
    get("scada104StopAllBtn")?.addEventListener("click", () => controlServiceProcess("stop", { scope: "all", label: "全部 IEC104 服务" }));
    get("scada104ReloadServiceBtn")?.addEventListener("click", () => loadServiceOverview(true));
    get("scada104ReloadConfigBtn")?.addEventListener("click", () => {
      lastRtuDefRowsKey = "";
      lastChDefLoaded = "";
      loadServiceOverview(true);
    });
    get("scada104ConnRtuSelect")?.addEventListener("change", () => {
      const rtu = get("scada104ConnRtuSelect")?.value || "";
      const svc = (latestServiceOverview?.services || []).find((s) => String(s.rtu_id) === String(rtu)) || null;
      renderConnectionsForService(svc);
    });
    get("scada104CfgHostPreset")?.addEventListener("change", () => {
      const isCustom = get("scada104CfgHostPreset")?.value === "__custom__";
      const wrap = get("scada104CfgCustomHostWrap");
      const input = get("scada104CfgHostCustom");
      if (wrap) wrap.hidden = !isCustom;
      if (input) {
        input.required = isCustom;
        if (isCustom) input.focus();
      }
    });
    get("scada104ChDefSelect")?.addEventListener("change", () => {
      const cid = get("scada104ChDefSelect")?.value || "";
      const ch = (latestServiceOverview?.channels || []).find((c) => String(c.channel_id) === String(cid));
      const svc = ch
        ? (latestServiceOverview?.services || []).find((s) => String(s.channel_id) === String(ch.channel_id) || String(s.rtu_id) === String(ch.rtu_id)) || null
        : null;
      if (ch) {
        populateChannelDefForm(ch, svc);
        lastChDefLoaded = String(ch.channel_id);
      }
    });
    get("scada104ChDefForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const cid = Number(get("scada104ChDefSelect")?.value || 0);
      const saveBtn = get("scada104SaveChDefBtn");
      if (!cid) {
        showServiceNotice("请先选择目标通道", true);
        return;
      }
      if (saveBtn) saveBtn.disabled = true;
      try {
        await api("/api/simulator104/channel-define/update", {
          channel_id: cid,
          apply_restart: Boolean(get("scada104CfgAutoRestart")?.checked),
          name: String(get("scada104ChName")?.value || "").trim(),
          rtu_addr: Number(get("scada104ChRtuAddr")?.value || 1),
          remote_host: selectedConfigHost(),
          remote_port: Number(get("scada104ChPort")?.value || 2405),
          max_connections: Number(get("scada104CfgMaxConn")?.value || 0),
          tick_rate_ms: Number(get("scada104CfgTickMs")?.value || 100),
          select_timeout_ms: Number(get("scada104CfgSelectTimeoutMs")?.value || 10000),
          ycbegin_addr: Number(get("scada104ChYcBegin")?.value || 16385),
          yxbegin_addr: Number(get("scada104ChYxBegin")?.value || 1),
          ykbegin_addr: Number(get("scada104ChYkBegin")?.value || 24577),
          ytbegin_addr: Number(get("scada104ChYtBegin")?.value || 25089),
          yc_data_type: Number(get("scada104ChYcType")?.value || 1),
          yx_data_type: Number(get("scada104ChYxType")?.value || 1),
          yk_excute_type: Number(get("scada104ChYkType")?.value || 1),
          yt_excute_type: Number(get("scada104ChYtType")?.value || 1),
          k: Number(get("scada104CfgK")?.value || 12),
          w: Number(get("scada104CfgW")?.value || 8),
          t1: Number(get("scada104CfgT1")?.value || 15),
          t2: Number(get("scada104CfgT2")?.value || 10),
          t3: Number(get("scada104CfgT3")?.value || 20),
          max_asdu_length: Number(get("scada104CfgMaxAsdu")?.value || 249),
          call_alldata_time: Number(get("scada104ChCallAll")?.value || 60),
          if_autosend_alldata: Number(get("scada104ChAutoAll")?.value || 1),
        });
        lastServiceRowsKey = "";
        lastChDefLoaded = "";
        showServiceNotice(`${tr("已保存")} CH ${cid}`, false);
        toast(`${tr("已保存")} CH ${cid}`, "ok", 2000);
        await loadServiceOverview(true);
        await refresh(true);
      } catch (err) {
        showServiceNotice(err.message, true);
      } finally {
        if (saveBtn) saveBtn.disabled = false;
      }
    });
    get("scada104PointsPrevBtn")?.addEventListener("click", () => {
      if (pointsTablePage > 0) {
        pointsTablePage -= 1;
        renderPointsTableRows();
      }
    });
    get("scada104PointsNextBtn")?.addEventListener("click", () => {
      pointsTablePage += 1;
      renderPointsTableRows();
    });

    get("scada104Rtu")?.addEventListener("change", () => {
      loadControlPoints(true);
    });
    get("scada104Kind")?.addEventListener("change", () => {
      syncValueInputMode();
      loadControlPoints(true);
    });
    get("scada104Point")?.addEventListener("change", () => updateSelectedPointMeta(true));
    bindDebouncedSearch(get("scada104PointSearch"), () => renderPointOptions(), 150);
    get("scada104RefreshPointsBtn")?.addEventListener("click", () => loadControlPoints(true));
    get("scada104PointsRtuSelect")?.addEventListener("change", () => {
      pointsTablePage = 0;
      loadPointsTable();
    });
    get("scada104PointsKindSelect")?.addEventListener("change", () => {
      pointsTablePage = 0;
      loadPointsTable();
    });
    bindDebouncedSearch(get("scada104PointsSearch"), () => {
      pointsTablePage = 0;
      renderPointsTableRows();
    }, 150);
    get("scada104ReloadPointsBtn")?.addEventListener("click", () => loadPointsTable());
    get("scada104LogsRtuSelect")?.addEventListener("change", () => loadChannelLogs());
    get("scada104LogsLevelSelect")?.addEventListener("change", () => renderChannelLogRows());
    bindDebouncedSearch(get("scada104LogsSearch"), () => renderChannelLogRows(), 150);
    get("scada104ReloadLogsBtn")?.addEventListener("click", () => loadChannelLogs());

    section.querySelectorAll("th.is-sortable[data-scada104-sort]").forEach((th) => {
      th.addEventListener("click", (event) => {
        event.stopPropagation();
        const col = th.dataset.scada104Sort;
        const nextDir = pointsSortState.col !== col
          ? "ascending"
          : (pointsSortState.dir === "ascending" ? "descending" : (pointsSortState.dir === "descending" ? "none" : "ascending"));
        pointsSortState = { col, dir: nextDir };
        section.querySelectorAll("th.is-sortable[data-scada104-sort]").forEach((node) => {
          node.setAttribute("aria-sort", node === th ? nextDir : "none");
        });
        renderPointsTableRows();
      });
    });

    get("scada104PausePointsRefresh")?.addEventListener("change", () => {
      if (activeViewTab === "points" && get("scada104PausePointsRefresh")?.checked) {
        if (refreshTimerId !== null) {
          clearTimeout(refreshTimerId);
          refreshTimerId = null;
        }
      } else if (isActive) {
        refresh(true);
      }
    });

    get("scada104CommandForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const rtu = Number(get("scada104Rtu")?.value || 0);
      const kind = get("scada104Kind")?.value || "yk";
      const point = Number(get("scada104Point")?.value || 0);
      const rawValueText = kind === "yk"
        ? String(get("scada104ValueSelect")?.value ?? "").trim()
        : String(get("scada104ValueInput")?.value ?? "").trim();
      const receipt = get("scada104Receipt");
      const sendBtn = get("scada104SendBtn");
      if (sendBtn) sendBtn.disabled = true;
      try {
        ["scada104Rtu", "scada104Point", "scada104ValueInput", "scada104ValueSelect"].forEach((id) => {
          get(id)?.removeAttribute("aria-invalid");
        });
        if (!rtu) {
          get("scada104Rtu")?.setAttribute("aria-invalid", "true");
          get("scada104Rtu")?.focus();
          throw new Error("请选择有效模型。");
        }
        if (!Number.isSafeInteger(point) || point <= 0) {
          get("scada104Point")?.setAttribute("aria-invalid", "true");
          get("scada104Point")?.focus();
          throw new Error("请选择有效控制点。");
        }
        if (!rawValueText) {
          const el = kind === "yk" ? get("scada104ValueSelect") : get("scada104ValueInput");
          el?.setAttribute("aria-invalid", "true");
          el?.focus();
          throw new Error("请填写指令值（不能为空）。");
        }
        const value = Number(rawValueText);
        if (!Number.isFinite(value)) {
          get("scada104ValueInput")?.setAttribute("aria-invalid", "true");
          get("scada104ValueInput")?.focus();
          throw new Error("指令值必须为有效数字。");
        }
        if (kind === "yk" && value !== 0 && value !== 1) {
          get("scada104ValueSelect")?.setAttribute("aria-invalid", "true");
          get("scada104ValueSelect")?.focus();
          throw new Error("遥控指令值只能为 0 或 1。");
        }
        const cached = pointItemsByNo.get(String(point));
        const displayName = cached?.name || `${kind.toUpperCase()}/${point}`;
        const valueLabel = kind === "yk" ? (value === 1 ? "1（合/投入）" : "0（分/退出）") : String(value);
        const confirmed = await confirmAction(
          `RTU ${rtu} · ${displayName} → ${valueLabel}`,
          {
            title: "确认下发仿真指令？",
            message: "确认后将立即通过 IEC104 联动通道下发至目标模型。",
            confirmLabel: "确认下发",
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
        const msg = `${tr("已发送")}: ${displayName} = ${valueLabel}`;
        if (receipt) {
          receipt.textContent = msg;
          receipt.classList.remove("is-error");
        }
        pushReceiptHistory(`RTU ${rtu} · ${displayName} → ${valueLabel}`, false);
        toast(msg, "ok", 2200);
        if (!isActive) return;
        await loadControlPoints(true);
        refresh(true);
      } catch (error) {
        if (receipt) {
          receipt.textContent = error.message;
          receipt.classList.add("is-error");
        }
        pushReceiptHistory(`${tr("失败")}: ${error.message}`, true);
      } finally {
        if (sendBtn) sendBtn.disabled = false;
      }
    });

    syncValueInputMode();
  }

  function applyPreferredModelSelection(models = latestModelsList) {
    if (!preferredModelName || !Array.isArray(models) || !models.length) return;
    const matched = models.find((m) => String(m?.model || "") === preferredModelName);
    if (!matched) return;
    const targetRtu = String(matched.rtu_id);
    const rtuSel = get("scada104Rtu");
    if (rtuSel && matched.online && matched.running && Array.from(rtuSel.options).some((o) => o.value === targetRtu)) {
      if (rtuSel.value !== targetRtu) {
        rtuSel.value = targetRtu;
        loadControlPoints(true);
      }
    }
    for (const id of ["scada104PointsRtuSelect", "scada104LogsRtuSelect"]) {
      const sel = get(id);
      if (sel && Array.from(sel.options).some((o) => o.value === targetRtu)) {
        sel.value = targetRtu;
      }
    }
  }

  function syncActiveModel(modelName, { refreshNow = true } = {}) {
    preferredModelName = String(modelName || "").trim();
    if (!isActive) return;
    if (refreshNow) {
      lastServiceRowsKey = "";
      refresh(true);
    } else {
      applyPreferredModelSelection(latestModelsList);
    }
  }

  function onLanguageChange() {
    lastRtuOptionsKey = "";
    lastAllRtuOptionsKey = "";
    lastServiceRowsKey = "";
    lastRtuDefRowsKey = "";
    if (!isActive) return;
    renderPointOptions();
    renderPointsTableRows();
    renderChannelLogRows();
    if (latestServiceOverview) renderServiceOverview(latestServiceOverview, false);
    refresh(true);
  }

  function setActive(active) {
    const next = Boolean(active);
    if (next) {
      isActive = true;
      bindEventsOnce();
      if (typeof state !== "undefined" && state?.activeModelId) {
        preferredModelName = String(state.activeModelId);
      }
      lastServiceRowsKey = "";
      refresh(true);
    } else {
      isActive = false;
      clearPolling();
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!isActive) return;
    if (document.hidden) clearPolling();
    else refresh(true);
  });

  window.Scada104Module = {
    setActive,
    refresh,
    setActiveViewTab,
    syncActiveModel,
    onLanguageChange,
  };

  // 若初始直达 /scada104 且主路由已挂载该页签，脚本就绪后立即激活轮询
  if (document.querySelector('section[data-page="scada104"].is-active')) {
    setActive(true);
  }
})();
