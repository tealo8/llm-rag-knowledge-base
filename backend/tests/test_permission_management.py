from __future__ import annotations

from .conftest import auth


def find_document(client, token: str, title: str) -> dict:
    response = client.get("/api/documents", headers=auth(token))
    assert response.status_code == 200
    return next(item for item in response.json() if item["title"] == title)


def find_user(client, token: str, username: str) -> dict:
    response = client.get("/api/admin/users", headers=auth(token))
    assert response.status_code == 200
    return next(item for item in response.json() if item["username"] == username)


def test_admin_can_change_existing_document_acl(client, tokens):
    document = find_document(client, tokens["admin"], "生产事故响应手册")
    endpoint = f"/api/documents/{document['id']}/permissions"

    before = client.post(
        "/api/chat",
        headers=auth(tokens["finance"]),
        json={"query": "P0事故首次通报要求是什么？", "top_k": 6},
    )
    assert before.json()["citations"] == []

    changed = client.patch(
        endpoint,
        headers=auth(tokens["admin"]),
        json={"visibility": "restricted", "group_ids": ["group-finance"]},
    )
    assert changed.status_code == 200
    assert [group["id"] for group in changed.json()["groups"]] == ["group-finance"]

    after = client.post(
        "/api/chat",
        headers=auth(tokens["finance"]),
        json={"query": "P0事故首次通报要求是什么？", "top_k": 6},
    )
    assert [item["title"] for item in after.json()["citations"]] == ["生产事故响应手册"]

    restored = client.patch(
        endpoint,
        headers=auth(tokens["admin"]),
        json={"visibility": "restricted", "group_ids": ["group-engineering"]},
    )
    assert restored.status_code == 200


def test_admin_can_change_member_role_and_groups(client, tokens):
    finance = find_user(client, tokens["admin"], "finance")
    endpoint = f"/api/admin/users/{finance['id']}/access"

    changed = client.patch(
        endpoint,
        headers=auth(tokens["admin"]),
        json={"role": "editor", "group_ids": ["group-engineering"]},
    )
    assert changed.status_code == 200
    assert changed.json()["role"] == "editor"
    assert [group["id"] for group in changed.json()["groups"]] == ["group-engineering"]
    assert "生产事故响应手册" in {
        item["title"]
        for item in client.get("/api/documents", headers=auth(tokens["finance"])).json()
    }

    restored = client.patch(
        endpoint,
        headers=auth(tokens["admin"]),
        json={"role": "viewer", "group_ids": ["group-finance"]},
    )
    assert restored.status_code == 200


def test_admin_management_safety_boundaries(client, tokens):
    admin = find_user(client, tokens["admin"], "admin")
    last_admin = client.patch(
        f"/api/admin/users/{admin['id']}/access",
        headers=auth(tokens["admin"]),
        json={"role": "viewer", "group_ids": []},
    )
    assert last_admin.status_code == 409

    cross_tenant = client.patch(
        "/api/admin/users/user-other-admin/access",
        headers=auth(tokens["admin"]),
        json={"role": "viewer", "group_ids": []},
    )
    assert cross_tenant.status_code == 404


def test_admin_can_create_and_delete_unused_group(client, tokens):
    created = client.post(
        "/api/admin/groups",
        headers=auth(tokens["admin"]),
        json={"name": "法务与合规", "description": "合同与合规审查人员"},
    )
    assert created.status_code == 201
    group_id = created.json()["id"]

    duplicate = client.post(
        "/api/admin/groups",
        headers=auth(tokens["admin"]),
        json={"name": "法务与合规", "description": "重复组"},
    )
    assert duplicate.status_code == 409

    deleted = client.delete(f"/api/admin/groups/{group_id}", headers=auth(tokens["admin"]))
    assert deleted.status_code == 204

