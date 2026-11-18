# 环境相依数字孪生电力系统模拟器

这是从 `D:\codex\power_simu_web` 教员台提炼出的独立仿真服务。它用环境、负荷和柴发曲线驱动数字孪生，提供 SCADA 实时遥测/遥信，并通过 `D:\codex\scada` 中现成的 `server.iec104_server.IEC104Server` 发布 IEC 60870-5-104 四遥数据。

## 启动

```powershell
cd D:\codex\simulator
python .\server.py --host 0.0.0.0 --port 8780 --scada-root D:\codex\scada --iec104-bind 0.0.0.0 --iec104-port 2404
```

浏览器访问 `http://127.0.0.1:8780/`。只运行 Web 仿真时加 `--no-iec104`，也可以执行 `.\start.ps1` 使用默认参数。

完整功能说明见 [`web/simulator_functionality.html`](web/simulator_functionality.html)，服务启动后可通过 `http://127.0.0.1:8780/simulator_functionality.html` 打开。

默认 IEC 104 公共地址为 1、RTU 标识为 104。模型导入或点表生成后会动态重建 IEC 104 运行点表。

Web 界面按功能拆分为多个页面：`/` 运行总览、`/model.html` 模型管理、`/curves.html` 曲线设置、`/devices.html` 设备与拓扑、`/scada.html` SCADA/IEC 104。每页保留仿真时钟和统一导航；页面内部使用功能标签切换，固定在浏览器视口内，不显示整体横向或纵向滚动条。

## 功能

- 导入 JSON、power_simu_web 定义 ZIP 或 E-file，并按设备和模型点扩展运行点表。
- 一键写入 `scdfe_s` 的 `fes_yc_define`、`fes_yx_define`、`fes_yk_define` 和 IEC 104 地址映射。
- 风速、辐照、气温、负荷、柴发和储能功率曲线插值；风光出力随环境和导入设备容量变化。
- 储能充放电功率和 SOC 更新，支持 `energy_kwh`/`capacity_kwh`。
- IEC 104 或 Web 遥控设备投运状态，支持并网断路器、柴油机和储能设备操作。
- 拓扑节点/支路联锁；拓扑孤岛设备自动退出并重新计算功率平衡。
- 每次状态变化执行嵌入式功率平衡，提供收敛、迭代次数、不平衡量并主动上送 YC/YX。
- 仿真时钟启动、暂停、单步、归零和 0.1～20 倍速度控制。
- 页面支持设备批量投退、曲线预设、JSON 导出、快照导出，以及空格暂停、N 单步、Ctrl+E 导出快照快捷键。
- Web 轮询使用聚合概览接口；曲线采用预排序索引和二分插值，拓扑设备判定采用索引查询，减少重复扫描。
- 总览页支持并网、孤网、外部电网失电、设备恢复、设备全停五种一键场景，并记录操作来源与结果。

## 模型 JSON 示例

```json
{
  "name": "风储微网",
  "devices": [
    {"id": "wind-1", "name": "风机1", "type": "wind", "rated_kw": 80, "run": true},
    {"id": "pv-1", "name": "光伏1", "type": "pv", "rated_kw": 60, "run": true},
    {"id": "diesel-1", "name": "柴发1", "type": "diesel", "rated_kw": 180, "run": true},
    {"id": "battery-1", "name": "储能1", "type": "battery", "rated_kw": 100, "energy_kwh": 240, "run": true}
  ],
  "topology": {"nodes": [], "edges": []},
  "curves": {
    "weather": [{"minute": 0, "wind_speed_mps": 7, "solar_irradiance_w_m2": 0, "air_temp_c": -20, "load_kw": 160}],
    "load": [],
    "diesel": [{"minute": 0, "diesel_kw": 120}],
    "battery": [{"minute": 0, "battery_kw": 0}]
  }
}
```

有柴发曲线时，曲线直接作为柴油机出力输入；设备容量按导入模型汇总，未导入对应设备时使用内置演示容量。

## Web/API

- `GET /api/health`：服务、模型和 IEC 104 状态。
- `GET /api/overview`：一次返回运行快照和健康状态，适合 Web 总览轮询。
- `GET /api/events`：读取最近仿真操作记录和联锁结果。
- `GET /api/snapshot`、`GET /api/history`：完整仿真快照和历史趋势。
- `GET /api/scada/telemetry`：按 IEC 104 点号返回实时 YC/YX，同时保留命名量测。
- `GET /api/power-flow`：潮流计算视图。
- `GET /api/points`：当前 YC/YX/YK 点定义及导入设备扩展点。
- `GET /api/model`、`GET /api/model/detail`、`POST /api/model/import`：模型管理；导入请求使用 `{"filename":"model.json","data_base64":"..."}` 或 `{"model":{...}}`。
- `GET/POST /api/curves`：读取或更新 `weather`、`load`、`diesel`、`battery` 曲线。
- `GET /api/devices`、`POST /api/devices/state`：查看并切换设备投运状态。
- `POST /api/devices/states`：批量切换多个设备投运状态，并只执行一次拓扑联锁和功率计算。
- `POST /api/scenario`：执行 `grid`、`island`、`blackout`、`restart`、`all_stop` 一键运行场景。
- `GET/POST /api/topology`：查看或更新拓扑节点/支路；更新后会触发联锁和功率计算。
- `GET /api/scdfe/points`、`POST /api/scdfe/points/generate`：查看并一键生成 `scdfe_s` 实时点定义。
- `POST /api/commands`：设备遥控命令，例如 `{"kind":"yk","point_no":2,"value":1}`。
- `POST /api/clock`：`start`、`pause`、`step`、`reset`、`speed`（`value` 为速度倍数）。
- `GET /api/iec104/status`、`POST /api/iec104/start`、`POST /api/iec104/stop`：IEC 104 服务控制。

## 数据流

```text
环境/负荷/柴发曲线 → 数字孪生步进 → 风光能力、储能 SOC、设备状态、功率平衡
                                  ├→ Web SCADA API
                                  └→ scdfe_s IEC 104：YC/YX 主动上送、YK 回调
```

## 验证

```powershell
python -m py_compile digital_twin.py model_import.py scdfe_points.py iec104_bridge.py server.py
node --check web/app.js
```

服务进程依赖 `D:\codex\scada\server\iec104_server.py`；若该目录不可用，Web 仿真仍可用，但 IEC 104 会显示为不可用。
