# FSS Extraction Agent

详细使用说明见 [README_fss_agent.md](README_fss_agent.md)。

快速运行：

```powershell
py -3.12 run_fss_agent.py --root .
```

该命令会自动完成论文信息抽取、JSON 输出、PostgreSQL 入库和 NebulaGraph 知识图谱写入。
