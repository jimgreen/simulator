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
  let activeViewTab = "channels";
  let loadedPointScope = "";
  let allLoadedPoints = [];
  let pointItemsByNo = new Map();
  let pointLoadSeq = 0;
  let pointAbortController = null;
  let statusAbortController = null;
  let pointsTableAbortController = null;
  let logsAbortController = null;
  let pointsTableReqSeq = 0;
  let logsReqSeq = 0;
  let refreshTimerId = null;
  let refreshInFlight = false;
  let pendingManualRefresh = false;
  let lastModelsRenderKey = "";
  let lastRtuOptionsKey = "";
  let lastAllRtuOptionsKey = "";
  let loadedPointsTableItems = [];
  let loadedChannelLogItems = [];
  let pointsSortState = { col: "pnt_no", dir: "none" };
  let imeComposing = false;
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
    if (!["channels", "points", "logs"].includes(tab)) return;
    activeViewTab = tab;
    const root = document.querySelector('section[data-page="scada104"]');
    if (!root) return;
    root.querySelectorAll("[data-scada104-tab]").forEach((btn) => {
      const active = btn.dataset.scada104Tab === tab;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    root.querySelectorAll("[data-scada104-pane]").forEach((pane) => {
      pane.hidden = pane.dataset.scada104Pane !== tab;
    });
    if (isActive) {
      if (tab === "points") loadPointsTable();
      else if (tab === "logs") loadChannelLogs();
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
    loadedPointScope = scope;
    try {
      const data = await api(
        `/api/simulator104/points?rtu_id=${encodeURIComponent(rtu)}&kind=${encodeURIComponent(kind)}`,
        undefined,
        { signal: pointAbortController.signal },
      );
      if (requestSeq !== pointLoadSeq || !isActive) return;
      const items = Array.isArray(data.items) ? data.items : [];
      allLoadedPoints = items;
      pointItemsByNo = new Map(items.map((item) => [String(item.pnt_no), item]));
      renderPointOptions();
    } catch (error) {
      if (error?.name === "AbortError" || requestSeq !== pointLoadSeq) return;
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
    if (!tbody) return;
    const kind = get("scada104PointsKindSelect")?.value || "yc";
    const rtu = Number(get("scada104PointsRtuSelect")?.value || 0);
    const keyword = String(get("scada104PointsSearch")?.value || "").trim().toLowerCase();
    const filtered = keyword
      ? loadedPointsTableItems.filter((item) => (
        `${item.pnt_no} ${item.name || ""} ${item.source_name || ""}`.toLowerCase().includes(keyword)
      ))
      : loadedPointsTableItems.slice();

    if (pointsSortState.dir !== "none") {
      const dir = pointsSortState.dir === "ascending" ? 1 : -1;
      const col = pointsSortState.col;
      filtered.sort((a, b) => {
        if (col === "pnt_no" || col === "value") {
          return (Number(a[col] ?? -Infinity) - Number(b[col] ?? -Infinity)) * dir;
        }
        return String(a[col] || "").localeCompare(String(b[col] || ""), "zh-CN") * dir;
      });
    }

    if (!filtered.length) {
      const cell = textNode("td", loadedPointsTableItems.length ? tr("无匹配点表") : tr("请选择模型查看点表"), "empty-state");
      cell.colSpan = 6;
      const trEl = document.createElement("tr");
      trEl.append(cell);
      tbody.replaceChildren(trEl);
      return;
    }

    const rows = filtered.map((item) => {
      const trEl = document.createElement("tr");
      const noTd = textNode("td", String(item.pnt_no), "numeric-cell scada104-copyable");
      noTd.title = tr("点击复制点号");
      noTd.addEventListener("click", () => {
        navigator.clipboard?.writeText(String(item.pnt_no)).then(() => toast(tr("已复制到剪贴板"), "ok", 1400)).catch(() => {});
      });
      trEl.append(noTd);

      trEl.append(textNode("td", item.name || item.source_name || ""));

      const srcTd = textNode("td", item.source_name || "", "mono-cell scada104-copyable");
      srcTd.title = tr("点击复制仿真源名");
      srcTd.addEventListener("click", () => {
        if (item.source_name) {
          navigator.clipboard?.writeText(String(item.source_name)).then(() => toast(tr("已复制到剪贴板"), "ok", 1400)).catch(() => {});
        }
      });
      trEl.append(srcTd);

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
          setActiveViewTab("channels");
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
        `/api/simulator104/points?rtu_id=${encodeURIComponent(rtu)}&kind=${encodeURIComponent(kind)}`,
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
      cell.colSpan = 6;
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

  async function controlChannel(model, action) {
    if (action === "stop") {
      const ok = await confirmAction(
        `${model.model} · RTU ${model.rtu_id} (${model.endpoint?.host || ""}:${model.endpoint?.port || ""})`,
        {
          title: "确认停止 IEC104 通道？",
          message: "停止后该模型的 IEC104 主站/子站通信将中断，直至重新启动。",
          confirmLabel: "停止通道",
        },
      );
      if (!ok) return;
    }
    try {
      await api("/api/simulator104/channel", { rtu_id: Number(model.rtu_id), action });
      await refresh(true);
    } catch (err) {
      const errEl = get("scada104BridgeError");
      if (errEl) errEl.textContent = err.message;
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
  }

  function scheduleNextRefresh(delayMs = REFRESH_INTERVAL_MS) {
    if (refreshTimerId !== null) {
      clearTimeout(refreshTimerId);
      refreshTimerId = null;
    }
    if (!isActive || document.hidden) return;
    refreshTimerId = setTimeout(() => {
      refreshTimerId = null;
      refresh(false);
    }, delayMs);
  }

  function syncSelectedModelRowHighlight() {
    const activeRtu = get("scada104Rtu")?.value || "";
    document.querySelectorAll("#scada104ModelRows tr[data-rtu-id]").forEach((row) => {
      row.classList.toggle("is-selected", row.dataset.rtuId === activeRtu);
    });
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
        const extUrl = String(payload?.scada_web_url || "").trim();
        extLink.href = extUrl || "#";
        extLink.hidden = !extUrl;
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

      const activeRtu = rtuSel?.value || "";
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
      const tbody = get("scada104ModelRows");
      if (tbody && modelsRenderKey !== lastModelsRenderKey) {
        lastModelsRenderKey = modelsRenderKey;
        const rows = models.map((model) => {
          const row = document.createElement("tr");
          const isOnlineRunning = Boolean(model.online && model.running);
          row.dataset.rtuId = String(model.rtu_id);
          if (isOnlineRunning) row.classList.add("is-selectable");
          if (String(model.rtu_id) === activeRtu) row.classList.add("is-selected");
          const ep = model.endpoint;
          const address = ep?.host && ep?.port ? `${ep.host}:${ep.port}` : "—";
          row.append(textNode("td", String(model.model || "")));
          row.append(textNode("td", String(model.rtu_id ?? ""), "numeric-cell"));
          row.append(textNode("td", address, "mono-cell"));

          const statusCell = document.createElement("td");
          const statusText = model.online ? (model.running ? tr("正在同步") : tr("已停止")) : tr("离线");
          const statusCls = model.online ? (model.running ? "scada104-pill is-ok" : "scada104-pill is-warn") : "scada104-pill is-off";
          statusCell.append(textNode("span", statusText, statusCls));
          row.append(statusCell);

          const pts = model.points || {};
          row.append(textNode("td", ["yc", "yx", "yk", "yt"].map((k) => pts[k] ?? 0).join(" / "), "numeric-cell"));

          const actionCell = document.createElement("td");
          const box = document.createElement("div");
          box.className = "scada104-row-actions";
          const toggleBtn = textNode(
            "button",
            model.running ? tr("停止") : tr("启动"),
            model.running ? "compact-action-btn is-danger" : "compact-action-btn",
          );
          toggleBtn.type = "button";
          toggleBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            controlChannel(model, model.running ? "stop" : "start");
          });
          const pointsBtn = textNode("button", tr("点表"), "compact-action-btn");
          pointsBtn.type = "button";
          pointsBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const sel = get("scada104PointsRtuSelect");
            if (sel) sel.value = String(model.rtu_id);
            setActiveViewTab("points");
          });
          const logsBtn = textNode("button", tr("日志"), "compact-action-btn");
          logsBtn.type = "button";
          logsBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const sel = get("scada104LogsRtuSelect");
            if (sel) sel.value = String(model.rtu_id);
            setActiveViewTab("logs");
          });
          box.append(toggleBtn, pointsBtn, logsBtn);
          actionCell.append(box);
          row.append(actionCell);
          return row;
        });
        if (!rows.length) {
          const cell = textNode("td", tr("暂无在线模型，请在教员端启动模型服务。"), "empty-state");
          cell.colSpan = 6;
          const row = document.createElement("tr");
          row.append(cell);
          rows.push(row);
        }
        tbody.replaceChildren(...rows);
      } else {
        syncSelectedModelRowHighlight();
      }

      await loadControlPoints(false);
      const pausedPoints = Boolean(get("scada104PausePointsRefresh")?.checked);
      if (activeViewTab === "points" && (manual || !pausedPoints)) await loadPointsTable();
      else if (activeViewTab === "logs") await loadChannelLogs();
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
    inputEl.addEventListener("compositionstart", () => { imeComposing = true; });
    inputEl.addEventListener("compositionend", () => {
      imeComposing = false;
      clearTimeout(timer);
      handler();
    });
    inputEl.addEventListener("input", () => {
      if (imeComposing) return;
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

    get("scada104ModelRows")?.addEventListener("click", (event) => {
      if (event.target instanceof Element && event.target.closest("a, button")) return;
      const row = event.target instanceof Element ? event.target.closest("tr.is-selectable[data-rtu-id]") : null;
      if (!row) return;
      const rtuSel = get("scada104Rtu");
      const targetRtu = row.dataset.rtuId || "";
      if (rtuSel && targetRtu && rtuSel.value !== targetRtu) {
        rtuSel.value = targetRtu;
        syncSelectedModelRowHighlight();
        loadControlPoints(true);
      }
    });

    get("scada104Rtu")?.addEventListener("change", () => {
      syncSelectedModelRowHighlight();
      loadControlPoints(true);
    });
    get("scada104Kind")?.addEventListener("change", () => {
      syncValueInputMode();
      loadControlPoints(true);
    });
    get("scada104Point")?.addEventListener("change", () => updateSelectedPointMeta(true));
    bindDebouncedSearch(get("scada104PointSearch"), () => renderPointOptions(), 150);
    get("scada104RefreshStatusBtn")?.addEventListener("click", () => refresh(true));
    get("scada104RefreshPointsBtn")?.addEventListener("click", () => loadControlPoints(true));
    get("scada104PointsRtuSelect")?.addEventListener("change", () => loadPointsTable());
    get("scada104PointsKindSelect")?.addEventListener("change", () => loadPointsTable());
    bindDebouncedSearch(get("scada104PointsSearch"), () => renderPointsTableRows(), 150);
    get("scada104ReloadPointsBtn")?.addEventListener("click", () => loadPointsTable());
    get("scada104LogsRtuSelect")?.addEventListener("change", () => loadChannelLogs());
    get("scada104LogsLevelSelect")?.addEventListener("change", () => renderChannelLogRows());
    bindDebouncedSearch(get("scada104LogsSearch"), () => renderChannelLogRows(), 150);
    get("scada104ReloadLogsBtn")?.addEventListener("click", () => loadChannelLogs());

    section.querySelectorAll("th.is-sortable[data-scada104-sort]").forEach((th) => {
      th.addEventListener("click", () => {
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

  function setActive(active) {
    const next = Boolean(active);
    if (next) {
      isActive = true;
      bindEventsOnce();
      lastModelsRenderKey = "";
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
  };

  // 若初始直达 /scada104 且主路由已挂载该页签，脚本就绪后立即激活轮询
  if (document.querySelector('section[data-page="scada104"].is-active')) {
    setActive(true);
  }
})();
