# 测试计划与验收矩阵

## 执行命令

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
cd ..
npm run build --prefix frontend
npm run visual-check --prefix frontend
```

真实模型评估：

```powershell
.\.venv\Scripts\python.exe evaluation\run.py `
  --base-url http://127.0.0.1:8080 `
  --output artifacts\evaluation\latest.json
```

## 自动化矩阵

| 验收项 | 覆盖位置 | 断言重点 |
| --- | --- | --- |
| 基础 RAG、引用和多轮上下文 | `test_z_enterprise_features.py` | 回答关键词、文档/页码/段落引用、历史消息 |
| 无关问题拒答、幻觉降级 | `test_permissions.py`、`test_resilience.py` | 空引用、明确拒答、抽取式降级 |
| 租户、知识库、用户组和文档 ACL | `test_permissions.py`、`test_permission_management.py` | 另一租户不可见、无权资源 404、召回前过滤 |
| 知识库角色和管理员设置 | `test_permission_management.py`、`test_z_enterprise_features.py` | view/upload/edit/admin、最后管理员保护 |
| 文档格式和解析失败 | `test_z_enterprise_features.py`、`test_resilience.py` | XLSX 表格、损坏 PDF、扫描 PDF OCR 提示、Office 文件头 |
| 大文件分片和顺序校验 | `test_z_enterprise_features.py` | 分片编号、大小、完成后索引 |
| 文档版本、回退和重复检测 | `test_z_enterprise_features.py`、`test_permission_management.py` | 版本号、当前版本、重复内容 409 |
| 会话、反馈、导出和审计 | `test_z_enterprise_features.py` | 会话隔离、点赞/点踩、Markdown 导出、审计记录 |
| 分页和 ACL 计数 | `test_pagination.py` | 页头、总数、稳定分页、权限过滤后的数量 |
| 模型/Embedding 故障 | `test_resilience.py` | 友好错误、BM25 降级、无堆栈泄漏 |
| 文件安全和可观测性 | `test_resilience.py` | 魔数校验、`/metrics` 响应和指标名 |
| 前端界面 | `frontend/scripts/visual-check.mjs` | 9 张桌面/移动截图、无控制台错误、无横向溢出 |

## 当前证据

- 后端回归：30 项通过。
- 前端 TypeScript/Vite 构建：通过。
- Playwright 视觉检查：9 张截图，桌面 1440x900、移动 390x844，无控制台错误。
- 真实评估：8 条演示数据，结果见 `docs/EVALUATION_REPORT.md`；不代表生产 SLA。

## 未覆盖或需人工验收

Docker/PGVector/Redis/Celery 实机启动、并发压测、百万级向量容量、OCR、恶意文件扫描、渗透测试、恢复演练和多副本一致性。没有这些证据，不能把项目结论写成“已达到生产就绪”。
