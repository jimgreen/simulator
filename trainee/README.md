# 学员端

在本目录使用 Python 3.11 或更新版本运行：

```powershell
python -m pip install -r requirements.txt
python -X utf8 run.py
```

Web 默认地址为 http://127.0.0.1:18720/，可在 `startup.json` 修改，也可用 `--host` 和 `--port` 覆盖。
数据根目录由 `startup.json` 的 `data_dir` 设置。当前学员端的数据目录是 `D:\codex\workspace\simulation\qinling\simulator\trainee`，其中 `models/` 存放模型，`runtime/` 存放运行状态。Web 和程序日志写入应用目录下的 `log/`。

本文件夹包含业务代码和潮流内核。移动应用时，将 `data_dir` 指向对应的数据根目录即可独立运行。

`python -I run.py --check` 可检查解释器、依赖版本和实际模块路径，不启动服务。

## 后台启动与教员联动

在任意工作目录执行本文件夹的 `start.ps1`，会隐藏后台窗口、验证健康状态并复用已启动的同一服务。其他程序占用端口时会报错。可用 `-Python <python.exe路径>` 指定解释器。

```powershell
& D:\codex\simulator\trainee\start.ps1
```

学员端自带本地计算内核。“启动接收”前需先完成“模型初始化”，可连接本地教员模型服务，例如 http://127.0.0.1:18716/。初始化会覆盖当前选中学员模型的定义，请先选好目标模型。完成后可接收本地教员数据与图形。

## 文件归属

- `run.py`、`start.ps1`、`startup.json`、`requirements.txt`：本端入口、启动配置和依赖。
- `simu/`：服务、控制逻辑与学员 Web；`simu_loop.py`、`scripts/` 和 `src/`：本地仿真与潮流内核。
- 数据根目录下的 `models/` 存放模型、曲线和 SVG，`lf/lf.para` 存放潮流参数，`runtime/` 存放本端运行结果。
- `log/`：启动和 Web 日志；`tests/`：本端独立运行验证。

`startup.json` 中的相对路径以本应用目录为起点。可用 `--models-dir` 或 `--runtime-dir` 覆盖相应目录，潮流参数仍从 `data_dir` 下读取。

## 验证

```powershell
python -m unittest discover -s tests -p test_standalone.py -v
```

测试将应用和模型数据分别复制到临时目录，从另一工作目录以隔离模式启动，验证路径和一次实际潮流计算。运行结果写入临时数据目录。
