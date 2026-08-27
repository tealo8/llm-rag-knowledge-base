from __future__ import annotations

import json

from .conftest import auth


def document_titles(client, token: str) -> set[str]:
    response = client.get("/api/documents", headers=auth(token))
    assert response.status_code == 200
    return {item["title"] for item in response.json()}


def test_document_visibility_matrix(client, tokens):
    assert document_titles(client, tokens["admin"]) == {
        "研发交付规范",
        "生产事故响应手册",
        "差旅与费用报销制度",
        "管理层年度预算草案",
    }
    assert document_titles(client, tokens["engineer"]) == {
        "研发交付规范",
        "生产事故响应手册",
    }
    assert document_titles(client, tokens["finance"]) == {
        "研发交付规范",
        "差旅与费用报销制度",
    }
    assert document_titles(client, tokens["otheradmin"]) == {"星云客户数据处理规范"}


def test_retrieval_filters_before_answer_generation(client, tokens):
    engineer = client.post(
        "/api/chat",
        headers=auth(tokens["engineer"]),
        json={"query": "P0事故首次通报要求是什么？", "top_k": 6},
    )
    assert engineer.status_code == 200
    assert [item["title"] for item in engineer.json()["citations"]] == ["生产事故响应手册"]
    assert "十分钟" in engineer.json()["answer"]

    for identity in ("finance", "otheradmin"):
        denied = client.post(
            "/api/chat",
            headers=auth(tokens[identity]),
            json={"query": "P0事故首次通报要求是什么？", "top_k": 6},
        )
        assert denied.status_code == 200
        assert denied.json()["citations"] == []
        assert "没有检索到" in denied.json()["answer"]


def test_citation_chunk_cannot_be_opened_by_another_group(client, tokens):
    response = client.post(
        "/api/chat",
        headers=auth(tokens["engineer"]),
        json={"query": "P0事故首次通报要求是什么？", "top_k": 6},
    )
    citation = response.json()["citations"][0]
    path = f"/api/documents/{citation['document_id']}/chunks/{citation['chunk_id']}"
    assert client.get(path, headers=auth(tokens["engineer"])).status_code == 200
    assert client.get(path, headers=auth(tokens["finance"])).status_code == 404
    assert client.get(path, headers=auth(tokens["otheradmin"])).status_code == 404


def test_upload_role_and_group_boundaries(client, tokens):
    content = "海棠项目的发布密钥每六十天轮换一次。".encode()
    viewer_response = client.post(
        "/api/documents",
        headers=auth(tokens["finance"]),
        files={"file": ("rotation.txt", content, "text/plain")},
        data={"title": "密钥轮换", "visibility": "organization", "group_ids": "[]"},
    )
    assert viewer_response.status_code == 403

    foreign_group_response = client.post(
        "/api/documents",
        headers=auth(tokens["admin"]),
        files={"file": ("rotation.txt", content, "text/plain")},
        data={
            "title": "密钥轮换",
            "visibility": "restricted",
            "group_ids": json.dumps(["group-nebula"]),
        },
    )
    assert foreign_group_response.status_code == 403


def test_admin_audit_is_tenant_scoped(client, tokens):
    response = client.get("/api/admin/audit", headers=auth(tokens["admin"]))
    assert response.status_code == 200
    assert response.json()
    assert all(item["user_name"] != "赵宁" for item in response.json())
    assert client.get("/api/admin/audit", headers=auth(tokens["engineer"])).status_code == 403

