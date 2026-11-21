const get = (id) => document.getElementById(id);
const text = (tag, value) => {
  const node = document.createElement(tag);
  node.textContent = value;
  return node;
};

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || data.error || `HTTP ${response.status}`);
  return data;
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
      for (const value of [model.model, model.rtu_id, address,
        model.online ? (model.running ? "正在同步" : "通道停止") : "模型离线",
        ["yc", "yx", "yk", "yt"].map((kind) => model.points[kind]).join(" / ")]) {
        row.append(text("td", value));
      }
      const cell = document.createElement("td");
      const link = text("a", "编辑");
      link.href = `/points?rtu_id=${encodeURIComponent(model.rtu_id)}`;
      cell.append(link);
      row.append(cell);
      return row;
    });
    if (!rows.length) {
      const cell = text("td", "暂无在线模型，请在教员端启动模型服务。");
      cell.colSpan = 6;
      const row = document.createElement("tr");
      row.append(cell);
      rows.push(row);
    }
    get("modelRows").replaceChildren(...rows);
    get("rtu").replaceChildren(...options);
    get("rtu").value = options.some((option) => option.value === selected) ? selected : "";
  } catch (error) {
    get("bridgeError").textContent = error.message;
  } finally {
    setTimeout(refresh, 1800);
  }
}

get("commandForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const rtu = Number(get("rtu").value);
  const kind = get("kind").value;
  const point = Number(get("point").value);
  const value = Number(get("value").value);
  const receipt = get("receipt");
  get("send").disabled = true;
  try {
    if (!rtu || !Number.isSafeInteger(point) || point <= 0 || !Number.isFinite(value)) throw new Error("请填写有效模型、点号和指令值。");
    if (kind === "yk" && value !== 0 && value !== 1) throw new Error("遥控指令值只能为 0 或 1。");
    const {item} = await api(`/api/channels/${rtu}/points/${kind}/${point}`);
    if (!confirm(`向 RTU ${rtu} 的 ${item.name || kind.toUpperCase() + '/' + point} 下发 ${value}？`)) return;
    const result = await api(`/api/rtus/${rtu}/commands/${kind}/${point}`, {value});
    if (result.item?.applied_to_simulator !== true) throw new Error("尚未收到模型接受回执。");
    receipt.textContent = `模型已接受 ${kind.toUpperCase()} / ${point} = ${value}`;
    receipt.classList.remove("error");
  } catch (error) {
    receipt.textContent = error.message;
    receipt.classList.add("error");
  } finally {
    get("send").disabled = false;
  }
});

refresh();
