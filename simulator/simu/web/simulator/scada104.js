const get = (id) => document.getElementById(id);
const text = (tag, value, className = "") => {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
};

let loadedPointScope = "";
let pointItemsByNo = new Map();

function initThemeToggle() {
  const btn = get("themeToggleButton");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    if (next === "dark") document.documentElement.dataset.theme = "dark";
    else delete document.documentElement.dataset.theme;
    try {
      localStorage.setItem("polarUiTheme", next);
    } catch (_e) {}
  });
}

function confirmScadaCommand(detailText) {
  const dialog = get("scadaConfirmDialog");
  const detailNode = get("scadaConfirmDetail");
  const cancelBtn = get("scadaConfirmCancel");
  const okBtn = get("scadaConfirmOk");
  if (!dialog || !cancelBtn || !okBtn || typeof dialog.showModal !== "function") {
    return Promise.resolve(window.confirm(detailText));
  }
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

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || data.error || `HTTP ${response.status}`);
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
}

async function loadControlPoints(force = false) {
  const rtu = get("rtu").value;
  const kind = get("kind").value;
  const pointSelect = get("point");
  const scope = `${rtu}:${kind}`;
  if (!rtu) {
    loadedPointScope = "";
    pointItemsByNo = new Map();
    pointSelect.replaceChildren(new Option("请先选择模型", ""));
    pointSelect.disabled = true;
    return;
  }
  if (!force && scope === loadedPointScope) return;
  loadedPointScope = scope;
  const prevValue = pointSelect.value;
  try {
    const data = await api(`/api/simulator104/points?rtu_id=${encodeURIComponent(rtu)}&kind=${encodeURIComponent(kind)}`);
    const items = Array.isArray(data.items) ? data.items : [];
    pointItemsByNo = new Map();
    const options = [new Option(items.length ? "选择控制点" : "暂无可用控制点", "")];
    for (const item of items) {
      pointItemsByNo.set(String(item.pnt_no), item);
      const label = `${item.pnt_no} · ${item.name || item.source_name}${item.disabled ? "（已禁操）" : ""}`;
      const option = new Option(label, String(item.pnt_no));
      if (item.disabled) option.disabled = true;
      options.push(option);
    }
    pointSelect.replaceChildren(...options);
    pointSelect.disabled = items.length === 0;
    if (options.some((opt) => opt.value === prevValue && !opt.disabled)) {
      pointSelect.value = prevValue;
    }
  } catch (error) {
    loadedPointScope = "";
    pointSelect.replaceChildren(new Option(`加载失败：${error.message}`, ""));
    pointSelect.disabled = true;
  }
}

async function refresh() {
  try {
    const state = await api("/api/simulator104/status");
    get("database").textContent = state.database;
    get("bridgeError").textContent = Object.entries(state.errors).map(([key, value]) => `${key}：${value}`).join(" · ");
    const selected = get("rtu").value;
    const options = [new Option("选择模型", "")];
    const rows = state.models.map((model) => {
      if (model.online && model.running) options.push(new Option(`${model.model} · RTU ${model.rtu_id}`, model.rtu_id));
      const row = document.createElement("tr");
      const endpoint = model.endpoint;
      const address = endpoint?.host && endpoint?.port ? `${endpoint.host}:${endpoint.port}` : "—";
      row.append(text("td", model.model));
      row.append(text("td", String(model.rtu_id), "num"));
      row.append(text("td", address, "mono"));

      const statusCell = document.createElement("td");
      const statusText = model.online ? (model.running ? "正在同步" : "通道停止") : "模型离线";
      const statusCls = model.online ? (model.running ? "pill is-ok" : "pill is-warn") : "pill is-off";
      statusCell.append(text("span", statusText, statusCls));
      row.append(statusCell);

      row.append(text("td", ["yc", "yx", "yk", "yt"].map((kind) => model.points[kind]).join(" / "), "num"));
      const cell = document.createElement("td");
      const link = text("a", "编辑点表");
      link.href = `/points?rtu_id=${encodeURIComponent(model.rtu_id)}`;
      cell.append(link);
      row.append(cell);
      return row;
    });
    if (!rows.length) {
      const cell = text("td", "暂无在线模型，请在教员端启动模型服务。", "empty");
      cell.colSpan = 6;
      const row = document.createElement("tr");
      row.append(cell);
      rows.push(row);
    }
    get("modelRows").replaceChildren(...rows);
    get("rtu").replaceChildren(...options);
    const nextRtu = options.some((option) => option.value === selected)
      ? selected
      : (options.length === 2 ? options[1].value : "");
    get("rtu").value = nextRtu;
    await loadControlPoints(false);
  } catch (error) {
    get("bridgeError").textContent = error.message;
  } finally {
    setTimeout(refresh, 1800);
  }
}

get("rtu").addEventListener("change", () => loadControlPoints(true));
get("kind").addEventListener("change", () => {
  syncValueInputMode();
  loadControlPoints(true);
});

get("commandForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const rtu = Number(get("rtu").value);
  const kind = get("kind").value;
  const point = Number(get("point").value);
  const value = kind === "yk" ? Number(get("valueSelect").value) : Number(get("value").value);
  const receipt = get("receipt");
  get("send").disabled = true;
  try {
    if (!rtu || !Number.isSafeInteger(point) || point <= 0 || !Number.isFinite(value)) {
      throw new Error("请选择有效模型、控制点并填写指令值。");
    }
    if (kind === "yk" && value !== 0 && value !== 1) throw new Error("遥控指令值只能为 0 或 1。");
    const cached = pointItemsByNo.get(String(point));
    const displayName = cached?.name || `${kind.toUpperCase()}/${point}`;
    const valueLabel = kind === "yk" ? (value === 1 ? "1（合/投入）" : "0（分/退出）") : String(value);
    const confirmed = await confirmScadaCommand(`目标：RTU ${rtu} · ${displayName} → ${valueLabel}`);
    if (!confirmed) return;
    const result = await api(`/api/rtus/${rtu}/commands/${kind}/${point}`, { value });
    if (result.item?.applied_to_simulator !== true) throw new Error("尚未收到模型接受回执。");
    receipt.textContent = `模型已接受 ${displayName} = ${valueLabel}`;
    receipt.classList.remove("is-error", "error");
  } catch (error) {
    receipt.textContent = error.message;
    receipt.classList.add("is-error");
  } finally {
    get("send").disabled = false;
  }
});

initThemeToggle();
syncValueInputMode();
refresh();
