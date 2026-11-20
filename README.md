# 教员端与学员端

根目录仅保留两个应用文件夹和仓库元数据。程序、依赖、模型、运行结果、日志及测试均由各自应用管理。

| 应用 | 使用说明 | 默认地址 |
| --- | --- | --- |
| 教员端 | [simulator/README.md](simulator/README.md) | http://127.0.0.1:18710/ |
| 学员端 | [trainee/README.md](trainee/README.md) | http://127.0.0.1:18720/ |

```powershell
.\simulator\start.ps1
.\trainee\start.ps1
```

首次使用时，分别按两端说明安装各自 `requirements.txt` 中的依赖。两端的 `startup.json` 控制各自监听端口、模型目录和运行目录，均可单独移动和运行。
