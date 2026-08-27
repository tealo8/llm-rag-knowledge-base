from __future__ import annotations

from .conftest import auth
from .test_z_enterprise_features import upload_text


def test_documents_pagination_applies_search_and_stable_headers(client, tokens):
    created = []
    for index in range(3):
        response = upload_text(
            client,
            tokens["admin"],
            f"pagination-{index}.txt",
            f"分页测试内容 {index}",
            title=f"分页样本 {index}",
        )
        assert response.status_code == 201
        created.append(response.json()["id"])
    try:
        first = client.get(
            "/api/documents",
            params={"knowledge_base_id": "kb-default-org-acme", "q": "分页样本", "page": 1, "page_size": 2},
            headers=auth(tokens["admin"]),
        )
        second = client.get(
            "/api/documents",
            params={"knowledge_base_id": "kb-default-org-acme", "q": "分页样本", "page": 2, "page_size": 2},
            headers=auth(tokens["admin"]),
        )
        assert first.status_code == second.status_code == 200
        assert first.headers["x-total-count"] == "3"
        assert first.headers["x-total-pages"] == "2"
        assert len(first.json()) == 2 and len(second.json()) == 1
        assert {item["id"] for item in first.json()}.isdisjoint({item["id"] for item in second.json()})
    finally:
        for document_id in created:
            assert client.delete(f"/api/documents/{document_id}", headers=auth(tokens["admin"])).status_code == 204


def test_document_pagination_count_is_acl_filtered(client, tokens):
    created = client.post(
        "/api/knowledge-bases",
        headers=auth(tokens["admin"]),
        json={"name": "分页权限库", "slug": "pagination-acl", "description": "分页 ACL"},
    )
    assert created.status_code == 201
    knowledge_base_id = created.json()["id"]
    try:
        assert client.put(
            f"/api/knowledge-bases/{knowledge_base_id}/access",
            headers=auth(tokens["admin"]),
            json={"user_id": "user-engineer", "permission": "view"},
        ).status_code == 204
        restricted = upload_text(
            client,
            tokens["admin"],
            "acl-page.txt",
            "只有财务可以查看",
            knowledge_base_id=knowledge_base_id,
            visibility="restricted",
            user_ids=["user-finance"],
        )
        assert restricted.status_code == 201
        listing = client.get(
            "/api/documents",
            params={"knowledge_base_id": knowledge_base_id, "page": 1, "page_size": 2},
            headers=auth(tokens["engineer"]),
        )
        assert listing.status_code == 200
        assert listing.json() == []
        assert listing.headers["x-total-count"] == "0"
    finally:
        for row in client.get(
            "/api/documents",
            params={"knowledge_base_id": knowledge_base_id, "include_versions": "true", "page_size": 100},
            headers=auth(tokens["admin"]),
        ).json():
            assert client.delete(f"/api/documents/{row['id']}", headers=auth(tokens["admin"])).status_code == 204
        assert client.delete(f"/api/knowledge-bases/{knowledge_base_id}", headers=auth(tokens["admin"])).status_code == 204


def test_admin_users_and_audit_pagination(client, tokens):
    users = client.get(
        "/api/admin/users", params={"page": 1, "page_size": 2}, headers=auth(tokens["admin"])
    )
    assert users.status_code == 200
    assert len(users.json()) == 2
    assert int(users.headers["x-total-count"]) >= 3
    audit = client.get(
        "/api/admin/audit", params={"page": 1, "page_size": 2}, headers=auth(tokens["admin"])
    )
    assert audit.status_code == 200
    assert len(audit.json()) <= 2
    assert int(audit.headers["x-total-count"]) >= len(audit.json())
