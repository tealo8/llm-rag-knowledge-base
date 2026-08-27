# Docker Compose 演示部署

## 1. 环境准备

需要 Docker Desktop/Engine、Compose v2，以及至少 16 GiB 内存。首次启动会拉取 Ollama、`qwen2.5:7b`、`qwen3-embedding:0.6b`、PGVector、Redis 镜像，磁盘和网络占用会随镜像/模型版本变化。

## 2. 一键启动

```powershell
copy .env.example .env
# 生产/公开演示必须修改 JWT_SECRET，并设置 DEMO_MODE=false
docker compose up --build
```

访问：

- 前端：`http://127.0.0.1:8080`
- API：`http://127.0.0.1:8080/docs`
- 指标：`http://127.0.0.1:8080/metrics`

Compose 拓扑包含 FastAPI、PGVector、Ollama、Redis、Celery worker 和模型初始化任务。上传任务使用 `TASK_QUEUE=celery`，状态会经历 `queued -> parsing -> embedding -> indexed`，失败为 `failed`。

## 3. 演示账号

仅在 `DEMO_MODE=true` 的演示数据库中可用：

| 账号 | 角色 | 演示重点 |
| --- | --- | --- |
| `admin / admin123` | 组织管理员 | 全库、成员、权限、审计、RAG 设置 |
| `engineer / engineer123` | 普通成员 | 研发组文档、问答和引用 |
| `finance / finance123` | 只读/受限成员 | 财务文档可见性和越权拒绝 |
| `otheradmin / other123` | 另一租户管理员 | 跨租户隔离 |

演示密码不可用于生产。公开演示应创建独立只读账号、禁用上传或限制 IP。

## 4. 完整演示流程

1. 用 `admin` 登录，进入“文档库”，上传 TXT/PDF，观察状态和失败原因区域。
2. 在上传弹窗选择固定或语义分块，并设置文档可见范围。
3. 在“权限与审计”调整 BM25 开关、向量权重、reranker、相似度阈值和严格 RAG。
4. 用 `engineer` 提问，查看回答下方引用卡片，点击打开原文片段。
5. 用 `finance` 重复同一问题，验证未授权文档不会进入召回或引用。
6. 上传同一内容，确认重复文档告警；上传新版本并在版本窗口回退。
7. 打开会话历史切换对话，点选点赞/点踩，导出 Markdown 会话。
8. 用 `admin` 查看审计表和死信任务接口，执行 `scripts/smoke.ps1` 验证健康、登录、分页和指标。

## 5. 数据安全提醒

- 禁止上传企业真实合同、客户数据、密钥、身份证件和未脱敏日志。
- 本地演示数据是样例数据；公开云演示必须使用独立数据库、TLS、IP 白名单和最小保留周期。
- `DEMO_MODE=true` 只适合本地演示；生产必须设置 `APP_ENV=production`、`DEMO_MODE=false` 和随机 32 字符以上 JWT 密钥。
- Docker Compose 当前仍使用 SQLite 元数据挂载目录；多副本生产必须先迁移到受管 PostgreSQL/MySQL，并补迁移、锁、备份和一致性测试。
- 当前机器未安装 Docker，因此 Compose、PGVector、Redis、Celery 仅完成配置审查，不能声称已实机验收。

