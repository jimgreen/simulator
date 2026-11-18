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
- 储能按设备独立积分 SOC，支持容量、充放电效率、SOC 上下限和加权系统 SOC 汇总。
- IEC 104 或 Web 遥控设备投运状态，支持并网断路器、柴油机和储能设备操作。
- 拓扑节点/支路联锁；拓扑孤岛设备自动退出并重新计算功率平衡。
- 每次状态变化执行嵌入式功率平衡，提供收敛、迭代次数、不平衡量并主动上送 YC/YX。
- 仿真时钟启动、暂停、单步、归零和 0.1～20 倍速度控制。
- 页面支持设备搜索、类型/状态筛选、分页、跨页勾选、批量投退/分合闸、单设备功率设定和跟随曲线；还支持曲线预设、JSON 导出、快照导出，以及空格暂停、N 单步、Ctrl+E 导出快照快捷键。
- Web 轮询使用聚合概览接口；曲线按通道预编译并二分插值，拓扑设备判定采用索引查询，计算分支避免重复的内置出力计算，减少每步重复扫描。
- E-file 的风光储柴类型按 `AC/DC*Gen` 参数表引用解析，光伏使用参考辐照度/温度与温度系数，储能按充放电功率、效率和 SOC 能量边界限幅，并在设备快照中给出请求功率、实际功率和限制原因。
- 总览页使用 `profile=dashboard` 聚合快照，设备页使用 `profile=devices` 轻量快照，避免每秒传输完整设备、拓扑、遥测和 SVG 测量；设备输入草稿跨刷新保留，支持批量统一功率、批量恢复曲线和每页 12/24/48 台切换，SVG 右键菜单支持功率设定和恢复曲线。
- 总览页支持并网、孤网、外部电网失电、设备恢复、设备全停五种一键场景，并记录操作来源与结果。

## 外部模型、边界与电网图形

模型管理页可导入单个 E 文件、simulator JSON 或定义 ZIP。ZIP 优先读取
model.e，可同时携带 meas.e、control.e、curves.e（优先于 curves.json）和 diagram.svg。
AC/DC 节点使用不同命名空间；设备保留原 block、idx、名称、参数和图形别名。
切换模型会一起切换图形；新模型未携带图形时清空旧图形，避免操作错配。

曲线设置页的“外部边界导入”支持 CSV、TSV、JSON、weather.e、curves.e、ZIP，
UTF-8/GB18030 编码。时间为日内 0–1440 分钟或 HH:MM[:SS]，每天循环，
区间线性插值，首尾之外保持端点值。支持风速、辐照、气温、气压、湿度、总负荷、
柴发和储能功率，也支持参考工程 JSON 的 loads 和 sources（电力 p_set）。
部分通道导入不会覆盖未提供的通道；NA/空值为缺失数据。重复时间、无效时间和非有限值报错。
设备负荷曲线优先于总负荷，设备源曲线优先于同类总功率曲线；匹配不到设备的外部曲线拒绝应用。
曲线预览和编辑均分页，编辑器按曲线选择，实时刷新不会覆盖未保存编辑。

独立页面 `/diagram.html` 提供 SVG 导入、缩放、平移、适应窗口和设备定位。
按照 power_simu_web 的规则，网页运行脚本绑定 dev-id / use[id][name] 与 dev 下的 mt/mti，
mti 语义优先，支持命名测量 data-meas-name / data-scada-name / data-real-name。
有功、运行状态、开关实际合位和储能 SOC 随仿真刷新，退出设备灰显；
开关使用 `_state_0` / `_state_1` 或 data-open-href / data-closed-href 切换图符。
仅模型或 SVG 版本改变时重新编译绑定，轮询只更新数值和状态。
上传 SVG 的内嵌脚本、事件处理器和外部活动资源会被清除；实时驱动由 simulator 的 diagram.js 提供。

- 设备右键：实时状态、投入/退出；开关额外提供分闸/合闸，电源设备可设定功率或恢复跟随曲线，退出状态禁止合闸。
- 空白右键：适应窗口、缩放、测量数值显示/隐藏、刷新。
- 操作同步设备和拓扑，重算功率并调用 scdfe_s 桥接发布 YC/YX；暂停时也可操作。
- 设备投运请求与拓扑可运行状态分开，解除隔离后可自动恢复请求为投入的设备。

新增接口：`GET /api/diagram`，`POST /api/diagram/import`，
`POST /api/boundary/import`（导入均使用 filename + data_base64）；
`POST /api/devices/operate` 使用 `{"device_id":"DCBreak:1","action":"open"}`，
action 支持 start、stop、open、close。

当前计算引擎仍为简化功率平衡，并未移植参考工程的完整 AC/DC 潮流求解器。
节点电压、无功、支路电流/潮流等未计算量在 SVG 中显示 `--`，不使用导出模型的初始零值冒充实时值。
储能 SOC 按设备独立计算并按能量加权汇总；拓扑判定为节点与相邻支路联锁，并非完整孤岛带电分析。
氢热等非电力源曲线保留并提示，不参与电力计算；control.e 定义保留，未提供任意控制脚本执行。
导入内容与最近 200 条操作记录驻留内存，服务重启后需重新导入模型包。

验证：`python -m unittest discover -s tests -v`。
测试覆盖定义包资源、边界校验/叠加、SVG 清理、设备操作、实际遥信、
暂停状态下桥接发布调用和导入失败保持原状态。

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

有柴发曲线时，曲线作为柴油机出力输入；设备容量按导入模型汇总。无设备的内置演示模型使用演示容量，已导入模型中不存在的发电类型不生成虚拟出力。

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
- `POST /api/devices/actions`：原子执行混合设备操作。请求为 `{"actions":[{"device_id":"diesel-1","action":"set_power","value":25}]}`；action 支持 `start`、`stop`、`open`、`close`、`set_power`、`follow_curve`，整批校验失败时不改变任何设备。
- `POST /api/scenario`：执行 `grid`、`island`、`blackout`、`restart`、`all_stop` 一键运行场景。
- `GET/POST /api/topology`：查看或更新拓扑节点/支路；更新后会触发联锁和功率计算。
- `GET /api/scdfe/points`、`POST /api/scdfe/points/generate`：查看并一键生成 `scdfe_s` 实时点定义。
- `POST /api/commands`：设备遥控命令，例如 `{"kind":"yk","point_no":2,"value":1}`。
- `POST /api/clock`：`start`、`pause`、`step`、`reset`、`speed`（`value` 为速度倍数）和 `seek`（`value` 为秒数或 `HH:MM[:SS]`）。单步始终推进一个配置步长，速度只作用于后台时钟。
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
python -m unittest discover -s tests -v
python tests/check_iec104_wire.py
node --check web/app.js
node --check web/diagram.js
node --check web/boundary.js
```

服务进程依赖 `D:\codex\scada\server\iec104_server.py`；若该目录不可用，Web 仿真仍可用，但 IEC 104 会显示为不可用。
