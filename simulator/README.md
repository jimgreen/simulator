# 教员端

在本目录使用 Python 3.11 或更新版本运行：

```powershell
python -m pip install -r requirements.txt
python -X utf8 run.py
```

Web 默认地址为 http://127.0.0.1:18710/，可在 `startup.json` 修改，也可用 `--host` 和 `--port` 覆盖。
模型保存在 `data/models/`，运行状态保存在 `data/runtime/`，Web 和程序日志写入 `log/`。

本文件夹包含全部业务代码、潮流内核和模型，移动到其他目录后仍可独立运行。所有默认目录相对于本文件夹解析，不需要原项目或另一个控制台。

`python -I run.py --check` 可检查解释器、依赖版本和实际模块路径，不启动服务。

## 后台启动

在任意工作目录执行本文件夹的 `start.ps1`，会隐藏后台窗口并验证健康状态。已运行的同一服务会复用，其他程序占用端口时会报错。可用 `-Python <python.exe路径>` 指定解释器。

```powershell
& D:\codex\simulator\simulator\start.ps1
```

教员端在模型列表中分别启动、停止模型子服务，默认从 18711 分配端口；子服务的生命周期独立于教员端页面。秦岭站当前默认模型服务地址为 http://127.0.0.1:18716/，可用于学员端模型初始化。

## 文件归属

- `run.py`、`start.ps1`、`startup.json`、`requirements.txt`：本端入口、启动配置和依赖。
- `simu/`：服务、控制逻辑与教员 Web；`simu_loop.py`、`scripts/` 和 `src/`：本地仿真与潮流内核。
- `data/models/`：模型、曲线、SVG；`data/lf/`：潮流参数；`data/runtime/`：本端运行结果与服务登记。
- `log/`：启动、Web 和模型子服务日志；`tests/`：本端独立运行验证。

`startup.json` 的相对目录基于本文件夹解析；命令行参数优先。修改文件夹位置后无需调整根仓库路径。原根目录旧版数字孪生、SQLite/IEC104 适配入口及历史产物已按当前调用关系清理，不属于本端运行链路。

## 验证

```powershell
python -m unittest discover -s tests -p test_standalone.py -v
```

测试将本端复制到临时目录，以隔离模式从另一工作目录启动，禁止读取原仓库和原项目，再验证模块来源和一次实际潮流计算。所有输出都写到临时副本。
