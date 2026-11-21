# 教员端与学员端

根目录保留两个应用文件夹和仓库元数据。模型、潮流参数及运行数据由各应用的 `startup.json` 指向工作区数据目录。

| 应用 | 使用说明 | 默认地址 |
| --- | --- | --- |
| 教员端 | [simulator/README.md](simulator/README.md) | http://127.0.0.1:18710/ |
| 学员端 | [trainee/README.md](trainee/README.md) | http://127.0.0.1:18720/ |

```powershell
.\simulator\start.ps1
.\trainee\start.ps1
```

首次使用时，分别按两端说明安装各自 `requirements.txt` 中的依赖，并检查 `startup.json` 的 `data_dir`。当前数据根目录分别为 `D:\codex\workspace\simulation\qinling\simulator\simulator` 与 `D:\codex\workspace\simulation\qinling\simulator\trainee`。
