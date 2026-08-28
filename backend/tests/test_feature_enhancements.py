from __future__ import annotations

import json

from .conftest import auth
from .test_z_enterprise_features import DEFAULT_KB, upload_text


def test_conversation_management_share_branch_and_feedback_reason(client, tokens):
    response = client.post("/api/chat", headers=auth(tokens["admin"]), json={"knowledge_base_id": DEFAULT_KB, "query": "发布前需要哪些检查？"})
    assert response.status_code == 200
    result = response.json()
    conversation_id = result["conversation_id"]
    message_id = result["message_id"]
    updated = client.patch(f"/api/conversations/{conversation_id}", headers=auth(tokens["admin"]), json={"title": "发布检查", "favorite": True})
    assert updated.status_code == 200 and updated.json()["favorite"] is True
    listed = client.get("/api/conversations", params={"knowledge_base_id": DEFAULT_KB, "favorite": "true"}, headers=auth(tokens["admin"]))
    assert listed.status_code == 200 and any(item["id"] == conversation_id for item in listed.json())
    feedback = client.put(f"/api/conversations/{conversation_id}/messages/{message_id}/feedback", headers=auth(tokens["admin"]), json={"rating": "down", "reason": "incomplete", "comment": "请补充引用"})
    assert feedback.status_code == 204
    detail = client.get(f"/api/conversations/{conversation_id}", headers=auth(tokens["admin"])).json()
    assert next(item for item in detail["messages"] if item["id"] == message_id)["feedback_reason"] == "incomplete"
    branch = client.post(f"/api/conversations/{conversation_id}/branch", headers=auth(tokens["admin"]), json={"message_id": message_id})
    assert branch.status_code == 201 and branch.json()["parent_id"] == conversation_id
    shared = client.post(f"/api/conversations/{conversation_id}/share", headers=auth(tokens["admin"]), json={"mode": "readonly", "expires_in_hours": 2, "password": "share-pass"})
    assert shared.status_code == 201
    token = shared.json()["token"]
    assert client.post(f"/api/conversations/share/{token}/access", json={"password": None}).status_code == 401
    public = client.post(f"/api/conversations/share/{token}/access", json={"password": "share-pass"})
    assert public.status_code == 200 and public.json()["mode"] == "readonly"
    assert public.headers["cache-control"] == "no-store"
    page = client.get(f"/shared/conversations/{token}")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    pdf = client.get(f"/api/conversations/{conversation_id}/export", params={"format": "pdf"}, headers=auth(tokens["admin"]))
    assert pdf.status_code == 200 and pdf.headers["content-type"].startswith("application/pdf") and pdf.content.startswith(b"%PDF-")
    assert b"STSong-Light" in pdf.content
    client.delete(f"/api/conversations/{conversation_id}", headers=auth(tokens["admin"]))
    client.delete(f"/api/conversations/{branch.json()['id']}", headers=auth(tokens["admin"]))


def test_knowledge_base_settings_switches_and_csv_preview(client, tokens):
    created = client.post("/api/knowledge-bases", headers=auth(tokens["admin"]), json={"name": "增强验收库", "slug": "enhancement-kb", "description": "功能验收"})
    assert created.status_code == 201
    kb_id = created.json()["id"]
    try:
        updated = client.patch(f"/api/knowledge-bases/{kb_id}", headers=auth(tokens["admin"]), json={"allow_qa": False, "allow_upload": True, "tags": ["验收"], "rag_settings": {"top_k": 4, "reranker_enabled": True, "system_prompt": "回答需列风险"}})
        assert updated.status_code == 200 and updated.json()["allow_qa"] is False
        denied = client.post("/api/chat", headers=auth(tokens["admin"]), json={"knowledge_base_id": kb_id, "query": "这里有什么？"})
        assert denied.status_code == 403
        uploaded = client.post("/api/documents", headers=auth(tokens["admin"]), files={"file": ("rows.csv", "名称,值\nA,100".encode(), "text/csv")}, data={"title": "CSV", "knowledge_base_id": kb_id, "visibility": "organization", "group_ids": "[]", "user_ids": "[]", "tags": json.dumps(["验收"])})
        assert uploaded.status_code == 201
        document_id = uploaded.json()["id"]
        preview = client.get(f"/api/documents/{document_id}/preview", headers=auth(tokens["admin"]))
        assert preview.status_code == 200 and "A | 100" in preview.json()["text"]
        stats = client.get(f"/api/knowledge-bases/{kb_id}/stats", headers=auth(tokens["admin"]))
        assert stats.status_code == 200 and stats.json()["document_count"] == 1
        batch = client.post("/api/documents/batch", headers=auth(tokens["admin"]), json={"document_ids": [document_id], "action": "delete"})
        assert batch.status_code == 200 and batch.json()["results"][0]["status"] == "deleted"
    finally:
        client.delete(f"/api/knowledge-bases/{kb_id}", headers=auth(tokens["admin"]))
