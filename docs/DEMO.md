# 演示环境说明

## 本机演示

启动：

```powershell
.\scripts\start-local.ps1
```

访问：

- 前端：[http://127.0.0.1:8080](http://127.0.0.1:8080)
- OpenAPI：[http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs)
- 指标：[http://127.0.0.1:8080/metrics](http://127.0.0.1:8080/metrics)

本机默认读取 `.env`：生成模型为 Ollama `qwen2.5:7b`，Embedding 为 `qwen3-embedding:0.6b`，元数据和开发向量模式为 SQLite。没有 Ollama 时可把 `LLM_PROVIDER=disabled`、`EMBEDDING_PROVIDER=local` 用于离线测试，但这不是生产模型路径。

演示账号：

| 账号 | 用途 |
| --- | --- |
| `admin / admin123` | 组织管理员，查看治理、成员、审计和全部演示数据 |
| `engineer / engineer123` | 研发成员，验证工程组文档可见性 |
| `finance / finance123` | 财务成员，验证受限文档和越权拒绝 |
| `otheradmin / other123` | 另一租户管理员，验证跨租户隔离 |

演示数据库只包含脱敏的制度、事故响应、报销和预算样例。禁止上传真实企业文件、密钥、客户数据或个人敏感信息。演示密码仅适合本机开发，部署前必须关闭 `DEMO_MODE` 并更换 JWT 密钥。

## Compose 演示

```powershell
docker compose up --build
```

Compose 会启动 FastAPI、PGVector、Ollama、Redis、Celery worker 和模型初始化任务，入口仍为 `http://127.0.0.1:8080`。生产/Compose 上传使用 `TASK_QUEUE=celery`，文档上传后先显示 `queued`，再由 worker 推进到 `parsing`、`embedding`、`indexed` 或 `failed`。

当前开发机未安装 Docker，因此 Compose、PGVector、Redis 和 Celery 只完成制品和配置审查，未声称已经实机验证。首次部署必须额外执行镜像构建、模型拉取、健康检查、故障重试、备份恢复和权限冒烟测试。

## 云演示边界

项目没有配置公网服务器、域名、TLS、SSO 或云凭据，因此没有可宣称的公网演示地址。若部署临时云演示，应使用独立演示数据、只读账号、IP 白名单、TLS 和最小保留周期，禁止把本机演示账号或真实企业数据带到公网。

## 演示脚本

先执行无破坏性的服务冒烟检查：

```powershell
.\scripts\smoke.ps1
```

它会验证健康检查、管理员登录、文档分页和 `/metrics`，不会上传、删除或修改数据。

1. 使用 `admin` 登录，在“文档库”上传一个 TXT 或 PDF，观察状态从处理中变为已索引。
2. 在“权限与审计”调整 BM25、重排序、相似度阈值和严格 RAG。
3. 使用 `engineer` 提问，点击回答下方引用卡片查看片段；再用 `finance` 验证无权引用不会出现。
4. 上传同一文件两次，确认弹窗显示重复文档告警；对文档上传新版本并在版本窗口回退。
5. 打开“会话历史”切换对话，提交点赞/点踩，并在管理员审计表查看问答事件。
