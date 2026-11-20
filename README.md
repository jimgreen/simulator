# 环境相依数字孪生电力系统模拟器

这是从 `D:\codex\power_simu_web` 教员台提炼出的独立仿真服务。它用环境、负荷和柴发曲线驱动数字孪生，提供 SCADA 实时遥测/遥信，并通过 `D:\codex\scada` 中现成的 `server.iec104_server.IEC104Server` 发布 IEC 60870-5-104 四遥数据。

## 启动

```powershell
cd D:\codex\simulator
python .\server.py --host 0.0.0.0 --port 8780 --scada-root D:\codex\scada --iec104-bind 0.0.0.0 --iec104-port 2404
```

浏览器访问 `http://127.0.0.1:8780/`。只运行 Web 仿真时加 `--no-iec104`，也可以执行 `.\start.ps1` 使用默认参数。

完整功能说明见 [`web/simulator_functionality.html`](web/simulator_functionality.html)，服务启动后可通过 `http://127.0.0.1:8780/simulator_functionality.html` 打开。

### 工作区根目录与运行态

使用 `--workspace-root D:\codex\workspace` 设置 Web 文件访问根目录（默认同名目录），
也可通过 `start.ps1 -WorkspaceRoot D:\codex\workspace` 启动。
`realtime/qinling` 是实时态，`simulation/qinling` 是仿真态，两份目录相互独立。

独立页面 `/workspace.html` 分页浏览电网数据库、边界数据和 SVG，支持目录跳转、按名称筛选和加载。
所有 Web 路径相对于根目录，例如 `simulation/qinling/sqldb/model`；不允许绝对路径、`..`、符号链接或联接点。
边界和图形导入接口支持 `{"path":"根目录内的相对文件路径"}`，也支持上传。
数据库浏览接口为 `/api/workspace?directory=simulation/qinling/sqldb/model&kind=database&page=1&page_size=8`，仅列出目录与 `devices.sqlite3`。

### 仿真内核电网数据库

内核启动时直接读取 SQLite 业务模型库，默认目录为 `D:\codex\workspace\simulation\qinling\sqldb\model`，
文件名固定为 `devices.sqlite3`。支持 RTDB 内嵌字段定义及普通命名字段表，采用只读连接和单次事务读取一致快照，
不修改业务模型表。缺失、损坏或无有效电网节点的数据库会报错，不会退回演示模型或 E 文件。

在独立页面 `/model.html` 输入根目录内的相对目录，可校验、保存并加载、重载当前库、分页查看表与记录数量。
校验不影响正在运行的模型；加载失败保留当前模型和目录配置。切换或重载会重置设备运行状态、曲线及图形，
需要重新加载对应边界和 SVG。目录保存在仿真状态 SQLite 库，重启后重新读取电网数据库并恢复匹配模型的运行状态。
配置优先级：显式 `--model-directory` > 当前根目录对应的已保存目录 > 默认目录。

```powershell
python .\server.py --workspace-root D:\codex\workspace --model-directory simulation/qinling/sqldb/model --no-iec104
# 启动参数也接受根目录内的绝对目录；Web 只接受相对目录。
.\start.ps1 -ModelDirectory D:\codex\workspace\simulation\qinling\sqldb\model
```

储能效率、SOC 及上下限支持比例或百分数；大于 1 且不超过 100 的值按百分数转换并提供提示。

scdfe_s 点表数据库也限制在该根目录内。默认优先使用
`simulation/qinling/sqldb/scada/scdfe_s.sqlite3`，不存在时使用
`simulation/scdfe_s.sqlite3`；可通过 `--scada-db` 指定其他根目录内的相对路径。
服务不会自动启动第二套 SCADA 通信进程；共用 2404 端口时使用 `--no-iec104`。

实时结果自动写入上述 **scdfe_s 点数据库**，与 `--no-iec104` 开关无关。优先读取同目录 `scdfe_d.sqlite3`（兼容 `devices.sqlite3`）中的 `device → device_measurement → scada_point_mapping`，也可用 `--mapping-db` 指定根目录内的映射库。按设备表名/模型索引/设备名匹配，使用映射中的真实 RTU/点号；秦岭现有映射为 RTU 1、YC 1366 点、YX 473 点。映射模式的“一键生成”只核对已有点表，不重编点号；独立 scdfe_s 服务从点库发布。没有映射库的独立测试模型才使用自动生成的 RTU 104 点表。

每次计算、暂停时设备操作或单步计算后，后台线程通过现成的 `SimulatorStore.update_rows` 在同一事务内更新 YC/YX 的值、质量、毫秒刷新时间及原始量字段，不覆盖 YK/YT 命令。发布值按 `(计算量换算到量测单位 - offset) / scale` 反算，和 scdfe_d 的 `采集值 * scale + offset` 对应；禁用、设备不匹配、未计算及非法换算的量测保留最后值并标记 IV。映射修改自动重载，重复目标点拒绝写入，失败重试最新帧。

`python create_measurement_mapping.py` 使用 SCADA 现有重建接口，以 `realtime/qinling/sqldb/scada/scdfe_d.sqlite3` 的同一只读快照，生成 `simulation/qinling/sqldb/simulator/scdfe_s.sqlite3` 和 `simulation/qinling/sqldb/scada/scdfe_d.sqlite3` 两份**设备量测映射库**。两份均绑定 simulation 模型及采集库，保留比例、偏移、启用和量测配置，清空参考库的历史量测，内置结构可由 RTDB 读取。目标已存在时拒绝覆盖；simulator 默认使用 scada 目录下的映射库。注意 simulator 目录下这份 `scdfe_s.sqlite3` 是映射副本，实际 IEC104 点值仍写入 scada 目录下的 `scdfe_s.sqlite3`。

独立页面 `/publication.html` 和 `GET /api/scdfe/realtime` 显示目标相对路径、RTU、批次、写入耗时及错误。暂停期间保留最后一帧的时间。scdfe_s 发布端必须选择**同一数据库和 RTU**并加载点表，其现有数据库监视线程负责发布变化；写库成功不等同于客户端已收到。`realtime/...` 与 `simulation/...` 的数据库相互独立。

每次计算后的设备结果同时写入 `simulation/qinling/sqldb/simulator/devices.sqlite3`（与配置库 `simulator.sqlite3` 同目录）。按模型设备块分表，例如 `ACGenerator`、`DCGenerator`、`ACLoad`、`ACBreak`，逐设备保存有功结果、质量码、实际投运/开关状态、SOC、可用功率、请求功率、限幅原因、计算帧号和仿真时刻；`SimulationFrame` 保存当前帧的计算方法、收敛、残差与发布 RTU。每库整帧事务更新，模型切换后清除过期设备行；结构变化同步更新内置 RTDB 定义，RTDB 无需外置表定义即可打开。

设备表和 scdfe_s 点表来自同一锁定快照，使用相同采样时间。两库是独立 SQLite 事务，短暂写入期间可能看到前后两帧；状态接口分别报告两路成功帧号，失败自动重试最新帧。当前内核计算方法为 `embedded-balance-power-flow`，仅保存实际已算出的量；未计算的设备功率为 NULL、质量码 IV=128，不以零冒充节点/支路潮流，也不生成未求解的无功和电压结果。

无映射库时，内置 IEC 104 公共地址默认 1、RTU 默认 104；映射模式以库内定义为准，由 scdfe_s 发布服务加载。

Web 界面按功能拆分为多个独立 HTML 页面：`/` 总览、`/trend.html` 趋势、`/diagnostics.html` 诊断、`/events.html` 事件、`/model.html` 电网数据库、`/model-summary.html` 模型摘要、`/curves.html` 曲线编辑、`/boundary.html` 边界导入、`/realtime.html` 实时曲线、`/diagram.html` 电网图形、`/devices.html` 设备操作、`/topology.html` 拓扑编辑、`/flow.html` 潮流状态、`/scada.html` IEC 104 服务和 `/points.html` 四遥点表。每页保留仿真时钟和统一导航，页面之间不再把不同功能挤在同一个 HTML 中；页面固定在浏览器视口内，不显示整体横向或纵向滚动条。

## 功能

- 从可配置目录读取固定文件 `devices.sqlite3`，按业务模型设备扩展运行点表。
- 一键写入 `scdfe_s` 的 `fes_yc_define`、`fes_yx_define`、`fes_yk_define` 和 IEC 104 地址映射。
- 风速、辐照、气温、负荷、柴发和储能功率曲线插值；风光出力随环境和导入设备容量变化。
- 储能按设备独立积分 SOC，支持容量、充放电效率、SOC 上下限和加权系统 SOC 汇总。
- IEC 104 或 Web 遥控设备投运状态，支持并网断路器、柴油机和储能设备操作。
- 拓扑节点/支路联锁；拓扑孤岛设备自动退出并重新计算功率平衡。
- 每次状态变化执行嵌入式功率平衡，提供收敛、迭代次数、不平衡量并主动上送 YC/YX。
- 仿真时钟启动、暂停、单步、归零和 0.1～20 倍速度控制。
- 页面支持设备搜索、类型/状态筛选、分页、跨页勾选、批量投退/分合闸、单设备功率设定和跟随曲线；还支持曲线预设、JSON 导出、快照导出，以及空格暂停、N 单步、Ctrl+E 导出快照快捷键。
- Web 轮询使用聚合概览接口；曲线按通道预编译并二分插值，拓扑设备判定采用索引查询，计算分支避免重复的内置出力计算，减少每步重复扫描。
- 数据库模型的风光储柴类型按 `AC/DC*Gen` 参数表引用解析，光伏使用参考辐照度/温度与温度系数，储能按充放电功率、效率和 SOC 能量边界限幅，并在设备快照中给出请求功率、实际功率和限制原因。
- 总览页使用 `profile=dashboard` 聚合快照，设备页使用 `profile=devices` 轻量快照，避免每秒传输完整设备、拓扑、遥测和 SVG 测量；设备输入草稿跨刷新保留，支持批量统一功率、批量恢复曲线和每页 12/24/48 台切换，SVG 右键菜单支持功率设定和恢复曲线。
- 总览页支持并网、孤网、外部电网失电、设备恢复、设备全停五种一键场景，并记录操作来源与结果。

## 外部模型、边界与电网图形

电网数据库页管理内核的 SQLite 数据源；Web 不再使用 E、JSON、ZIP 上传替换内核模型。
沿用 power_simu_web 表语义，AC/DC 节点使用不同命名空间，设备保留原 block、idx、名称、参数和图形别名。
边界与 SVG 在各自独立页面加载；数据库切换或重载后清空旧图形，避免操作错配。
E/JSON/ZIP 的解析库仍保留供离线转换与测试使用。

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
Web 提交的修改持久保存，服务重启后恢复同一电网模型的曲线、SVG、设备投退、功率设定、拓扑、场景、时钟与 SOC。

## Web 修改与仿真状态持久化

默认数据库：`D:\codex\workspace\simulation\qinling\sqldb\simulator\simulator.sqlite3`。
可用 `--state-directory` 或 `start.ps1 -StateDirectory` 指定根目录内的其他目录。
`devices.sqlite3` 继续作为只读业务模型源；Web 修改独立保存至 simulator 库。

- 每次 Web 提交在 SQLite 事务中保存成功后才返回成功并发布实时数据；数据库写入失败会回滚内存修改。
- 环境风速/辐照/温度、总负荷与分设备负荷、柴发/储能/源出力曲线均保存于 `simulator_state` 的 `model.curves`；仿真倍速、步长、时刻、SOC 和运行状态保存于 `runtime`。所有保存/导入/应用按钮直接提交数据库，曲线编辑框中的未提交草稿需点击“保存曲线”。
- 切换电网数据库后再切回，或重新加载同一电网时，恢复该模型已保存的曲线、参数和运行状态。业务模型内容变化时使用新的配置分区，避免旧设备状态套用到新模型。
- `simulator_state` 按模型内容摘要和配置分区保存模型覆盖、边界曲线、SVG、设备/拓扑、时钟/SOC、四遥生成定义与结果、IEC104 启停意图及页面偏好。
- `simulator_operations` 保留成功提交的操作日志；独立 `/storage.html` 页面查看路径、最近保存时间、恢复情况与分页日志。
- 连续运行的时钟、SOC、近期历史和事件每 5 秒保存一次，正常退出再保存；异常中断最多丢失约 5 秒自动演进，已提交 Web 修改立即持久化。
- 恢复使用检查点，不重放单步或控制指令，也不把停机时间计入仿真。业务模型内容改变时不套用旧状态，旧模型状态保留在库中。
- 设备筛选、每页数量、SVG 测量显示及缩放平移在 SQLite 中记忆。编辑器未点击保存的草稿仍不作为生效配置。
- 工作目录浏览页记录最后成功打开的相对目录和文件类型，重新进入或重启后自动恢复；带目录/类型参数的链接优先。历史目录失效时返回根目录，网络暂时失败不会覆盖历史选择。电网模型库切换成功后沿用已保存的数据库目录。
- 首次启动可读取原 `runtime/model_source.json` 迁移目录选择；迁移后不再写该文件。显式 `--no-iec104` 优先于已保存的启动意图。
- 四遥定义先存入 simulator 库，再同步现有 scdfe_s 数据库；外部同步失败单独报告，已保存定义仍保留以供再次同步。

### RTDB 内置结构同步

`simulator.sqlite3` 使用 RTDB 的分组表格式，逻辑表为 `simulator_state` 和 `simulator_operations`。
数据库同时包含 `rtdb_schema_database`、`rtdb_schema_tables`、`rtdb_schema_columns`，
以及每表的结构指纹、行数元数据和计数触发器，RTDB 无需外部 JSON/Python 定义即可打开。
原普通 SQLite 状态库在启动时事务迁移，保留配置、操作日志、原编号及自增编号上界。

后续新增或修改 simulator 自有表时，统一调用 `SimulatorStateStore.update_schema(mappings)`；
独立数据库使用 `rtdb_schema.apply_schema(connection, path, mappings)`，传入 RTDB 的 `head + columns` 定义。
物理表、字段映射、主键/索引、默认值和内置定义在同一事务内提交；任何一步失败全部回滚。
字段重排按逻辑名称迁移，新增字段应用默认值；已有值不符合新类型或主键冲突时拒绝迁移。
仿真必需字段不能删除或改变类型/主键，重启保留额外字段和中文标签。
不要绕过此入口直接执行 `CREATE TABLE` / `ALTER TABLE`。

结构定义与指纹复用同级 `D:\codex\rtdb\core` 的接口（隔离模块命名，避免与 SCADA 的 `core` 冲突）。
RTDB Web 工作区选择 `simulation/qinling/sqldb/simulator`，再选择 `simulator.sqlite3`；
表结构更新后重新选择数据库以刷新已打开的结构缓存。业务模型库仍只读，scdfe_s 仍由其现有接口管理。

接口：`GET /api/storage`、`GET /api/storage/operations?limit=200`、`GET /api/preferences?page=devices`、
`POST /api/preferences`（`{"page":"devices","values":{"devicePageSize":"24"}}`）。

验证：`python -m unittest discover -s tests -v`。
测试覆盖定义包资源、边界校验/叠加、SVG 清理、设备操作、实际遥信、
暂停状态下桥接发布调用和导入失败保持原状态。

## 内部归一化模型示例（非 Web 导入接口）

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

有柴发曲线时，曲线作为柴油机出力输入；设备容量按导入模型汇总。业务模型中不存在的发电类型不生成虚拟出力。

## Web/API

- `GET /api/health`：服务、模型和 IEC 104 状态。
- `GET /api/overview`：一次返回运行快照和健康状态，适合 Web 总览轮询。
- `GET /api/events`：读取最近仿真操作记录和联锁结果。
- `GET /api/snapshot`、`GET /api/history`：完整仿真快照和历史趋势。
- `GET /api/scada/telemetry`：按 IEC 104 点号返回实时 YC/YX，同时保留命名量测。
- `GET /api/power-flow`：潮流计算视图。
- `GET /api/points`：当前 YC/YX/YK 点定义及导入设备扩展点。
- `GET /api/model`、`GET /api/model/detail`：模型摘要和详情。
- `GET /api/model/source`：当前数据库目录、文件、表统计和加载时间。
- `POST /api/model/source/validate`：校验目录中的 `devices.sqlite3`，不切换模型。
- `POST /api/model/source`：读取数据库、切换模型并保存目录；请求 `{"directory":"simulation/qinling/sqldb/model"}`，省略目录则重载当前库。文件名不可更改。
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
