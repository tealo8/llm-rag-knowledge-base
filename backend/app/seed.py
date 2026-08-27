from __future__ import annotations

from .db import db_session, utc_now
from .security import CurrentUser, hash_password
from .services.documents import ingest_document


ORG_ACME = "org-acme"
ORG_NEBULA = "org-nebula"
USER_ADMIN = "user-admin"
USER_ENGINEER = "user-engineer"
USER_FINANCE = "user-finance"
USER_OTHER = "user-other-admin"
GROUP_ENGINEERING = "group-engineering"
GROUP_FINANCE = "group-finance"


def seed_identities() -> None:
    with db_session() as connection:
        if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        now = utc_now()
        connection.executemany(
            "INSERT INTO organizations (id, name, slug, created_at) VALUES (?, ?, ?, ?)",
            [
                (ORG_ACME, "远川科技", "yuanchuan", now),
                (ORG_NEBULA, "星云数据", "nebula", now),
            ],
        )
        connection.executemany(
            """
            INSERT INTO users
                (id, org_id, username, display_name, email, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (USER_ADMIN, ORG_ACME, "admin", "王敏", "admin@yuanchuan.example", hash_password("admin123"), "admin", now),
                (USER_ENGINEER, ORG_ACME, "engineer", "陈磊", "engineer@yuanchuan.example", hash_password("engineer123"), "editor", now),
                (USER_FINANCE, ORG_ACME, "finance", "李娜", "finance@yuanchuan.example", hash_password("finance123"), "viewer", now),
                (USER_OTHER, ORG_NEBULA, "otheradmin", "赵宁", "admin@nebula.example", hash_password("other123"), "admin", now),
            ],
        )
        connection.executemany(
            "INSERT INTO groups (id, org_id, name, description) VALUES (?, ?, ?, ?)",
            [
                (GROUP_ENGINEERING, ORG_ACME, "研发中心", "研发、测试与运维人员"),
                (GROUP_FINANCE, ORG_ACME, "财务与行政", "财务、人事与行政人员"),
                ("group-nebula", ORG_NEBULA, "数据平台组", "星云数据平台团队"),
            ],
        )
        connection.executemany(
            "INSERT INTO user_groups (user_id, group_id) VALUES (?, ?)",
            [
                (USER_ENGINEER, GROUP_ENGINEERING),
                (USER_FINANCE, GROUP_FINANCE),
                (USER_OTHER, "group-nebula"),
            ],
        )


def _user(user_id: str) -> CurrentUser:
    with db_session() as connection:
        row = connection.execute(
            "SELECT id, org_id, username, display_name, email, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return CurrentUser(**dict(row))


async def seed_documents() -> None:
    admin = _user(USER_ADMIN)
    engineer = _user(USER_ENGINEER)
    finance = _user(USER_FINANCE)
    other = _user(USER_OTHER)

    samples = [
        (
            admin,
            "研发交付规范.md",
            "研发交付规范",
            "organization",
            [],
            """# 研发交付规范\n\n所有研发项目在进入开发阶段前，必须完成需求评审、技术方案评审和风险识别。需求负责人应在项目空间中记录验收标准。\n\n代码合并到主分支前至少需要一名非提交者完成审查。涉及鉴权、支付或个人信息处理的改动，需要安全负责人追加审查。\n\n发布前必须通过自动化测试、依赖漏洞扫描和回滚演练。普通版本应提前两个工作日提交发布申请；重大版本应提前五个工作日。\n\n线上变更窗口为每周二、周四 20:00 至 22:00。紧急修复可走应急流程，但必须在二十四小时内补齐复盘记录。""",
        ),
        (
            engineer,
            "生产事故响应手册.md",
            "生产事故响应手册",
            "restricted",
            [GROUP_ENGINEERING],
            """# 生产事故响应手册\n\nP0 事故是指核心业务完全不可用、发生大规模数据错误或确认存在严重安全事件。值班人员发现后应在五分钟内创建事故群，并通知技术负责人和业务负责人。\n\nP0 的首次状态通报必须在十分钟内发出，此后每十五分钟更新一次。恢复服务优先于定位根因，任何高风险恢复操作需要两人确认。\n\n事故恢复后二十四小时内由主责团队完成初步复盘，三个工作日内提交正式报告。报告必须包含影响范围、时间线、根因、恢复动作和长期改进项。""",
        ),
        (
            finance,
            "差旅报销制度.txt",
            "差旅与费用报销制度",
            "restricted",
            [GROUP_FINANCE],
            """员工出差前应在费用系统提交申请并取得直属经理批准。单次预计费用超过 5000 元，还需部门负责人审批。\n\n国内住宿标准为一线城市每晚不超过 600 元，其他城市每晚不超过 450 元。超出标准的部分原则上由个人承担；因会议指定酒店等原因超标的，应附书面说明。\n\n报销应在行程结束后三十个自然日内提交。发票、行程单和支付凭证必须完整，财务在材料齐全后的五个工作日内完成审核。""",
        ),
        (
            admin,
            "年度预算草案.txt",
            "管理层年度预算草案",
            "private",
            [],
            "下一财年的内部预算草案仅供管理层讨论。研发基础设施预算暂定增长百分之十八，最终数字须经董事会批准后方可对外引用。",
        ),
        (
            other,
            "客户数据规范.md",
            "星云客户数据处理规范",
            "organization",
            [],
            "星云数据的客户记录默认保留九十天。任何跨区域数据复制必须由数据保护负责人批准。该文档仅属于星云数据租户。",
        ),
    ]
    for owner, filename, title, visibility, groups, content in samples:
        await ingest_document(
            user=owner,
            filename=filename,
            content_type="text/markdown" if filename.endswith(".md") else "text/plain",
            content=content.encode("utf-8"),
            title=title,
            visibility=visibility,
            group_ids=groups,
            is_seed=True,
        )

