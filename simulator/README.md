# 教员端

在本目录使用 Python 3.11 或更新版本运行：

```powershell
python -m pip install -r requirements.txt
python -X utf8 run.py
```

Web 默认地址为 http://127.0.0.1:18710/，可在 `startup.json` 修改，也可用 `--host` 和 `--port` 覆盖。
数据根目录由 `startup.json` 的 `data_dir` 设置。当前教员端的数据目录是 `D:\codex\workspace\simulation\qinling\simulator\simulator`，其中 `models/` 存放模型，`runtime/` 存放运行状态。Web 和程序日志写入应用目录下的 `log/`。

本文件夹包含业务代码和潮流内核。移动应用时，将 `data_dir` 指向对应的数据根目录即可独立运行。

`python -I run.py --check` 可检查解释器、依赖版本和实际模块路径，不启动服务。

## 后台启动

在任意工作目录执行本文件夹的 `start.ps1`，会隐藏后台窗口并验证健康状态。已运行的同一服务会复用，其他程序占用端口时会报错。可用 `-Python <python.exe路径>` 指定解释器。

```powershell
& D:\codex\simulator\simulator\start.ps1
```

教员端在模型列表中分别启动、停止模型子服务，默认从 18711 分配端口；子服务的生命周期独立于教员端页面。秦岭站当前默认模型服务地址为 http://127.0.0.1:18716/，可用于学员端模型初始化。

## SCADA IEC104 联动

启动教员端和所需模型后，在另一进程启动 `scdfe_s` 联动服务。该入口复用 `D:\codex\scada` 的 Web、SQLite 点表和 IEC104 服务，Python 环境需装有 SCADA 所需依赖。

联动扩展随本目录的 `scada104-dependency.patch` 保存，验证基线为 SCADA `80fef88`。当前本机 SCADA 已有这些扩展。若在其他兼容的 SCADA 副本尚未安装，可先核对基线，再应用补丁：

```powershell
git -C D:\codex\scada apply --check D:\codex\simulator\simulator\scada104-dependency.patch
git -C D:\codex\scada apply D:\codex\simulator\simulator\scada104-dependency.patch
```

SCADA 远端旧版本也缺少联动所需的工作区接口，需先取得相应基线。补丁包含模型通道服务注入、Web 指令回调和桥接元数据识别三处扩展。

```powershell
python -X utf8 D:\codex\simulator\simulator\scada104.py
```

打开 [IEC104 联动](http://127.0.0.1:8878/simulator104) 查看每个模型的 RTU、点数、通道状态和指令回执。模型首次上线时生成专用通道和四遥点表，秦岭站沿用 RTU 1 和端口 2405。点库位于 `data_dir` 下的 `scdfe_s.sqlite3`。通过 [通道参数](http://127.0.0.1:8878/channels) 和 [四遥点表](http://127.0.0.1:8878/points) 编辑通道与测点。调整 IEC104 监听参数或信息体配置后，重启相应通道使配置生效。

同名点保留原点号和人工修改。模型定义新增点时自动分配新点号，退役点保留记录并标记不可用。模型离线时，已绑定的遥测和遥信标记无效，遥控和遥调拒绝执行。控制指令由所对应的模型接受后返回成功回执，仿真计算结果在下一帧反映。`--web-port`、`--db`、`--first-iec104-port`、`--simulator-url` 可用于独立测试或调整本机配置。

## 文件归属

- `run.py`、`start.ps1`、`startup.json`、`requirements.txt`：本端入口、启动配置和依赖。
- `simu/`：服务、控制逻辑与教员 Web；`simu_loop.py`、`scripts/` 和 `src/`：本地仿真与潮流内核。
- 数据根目录下的 `models/` 存放模型、曲线和 SVG，`lf/lf.para` 存放潮流参数，`runtime/` 存放本端运行结果与服务登记。
- `log/`：启动、Web 和模型子服务日志；`tests/`：本端独立运行验证。

`startup.json` 中的相对路径以本应用目录为起点。可用 `--models-dir` 或 `--runtime-dir` 覆盖相应目录，潮流参数仍从 `data_dir` 下读取。

## 验证

```powershell
python -m unittest discover -s tests -p test_standalone.py -v
```

测试将应用和模型数据分别复制到临时目录，从另一工作目录以隔离模式启动，验证路径和一次实际潮流计算。运行结果写入临时数据目录。
