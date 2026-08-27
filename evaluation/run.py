from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


ACCOUNTS = {
    "admin": "admin123",
    "engineer": "engineer123",
    "finance": "finance123",
    "otheradmin": "other123",
}


def login(client: httpx.Client, identity: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": identity, "password": ACCOUNTS[identity]},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 1)


def evaluate(base_url: str, dataset_path: Path) -> dict[str, Any]:
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    with httpx.Client(base_url=base_url, timeout=180) as client:
        tokens = {identity: login(client, identity) for identity in ACCOUNTS}
        knowledge_bases: dict[str, str] = {}
        for identity, token in tokens.items():
            response = client.get(
                "/api/knowledge-bases",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            spaces = response.json()
            if not spaces:
                raise RuntimeError(f"{identity} 没有可访问的知识库")
            knowledge_bases[identity] = spaces[0]["id"]
        for case in cases:
            headers = {"Authorization": f"Bearer {tokens[case['identity']]}"}
            response = client.post(
                "/api/chat",
                headers=headers,
                json={
                    "query": case["query"],
                    "knowledge_base_id": knowledge_bases[case["identity"]],
                    "top_k": 6,
                },
            )
            response.raise_for_status()
            payload = response.json()
            citations = payload["citations"]
            titles = [item["title"] for item in citations]
            expected = case.get("expected_titles", [])
            ranks = [titles.index(title) + 1 for title in expected if title in titles]
            recall = len(ranks) / len(expected) if expected else 1.0
            reciprocal_rank = 1 / min(ranks) if ranks else (1.0 if not expected else 0.0)
            leakage = any(title in titles for title in case.get("forbidden_titles", []))
            refusal_ok = True
            if case.get("expect_refusal"):
                refusal_ok = not citations and ("没有检索到" in payload["answer"] or "资料不足" in payload["answer"])
            answer_terms_ok = all(term in payload["answer"] for term in case.get("answer_contains", []))
            citation_ok = all(item["index"] == index for index, item in enumerate(citations, 1))
            for citation in citations:
                opened = client.get(
                    f"/api/documents/{citation['document_id']}/chunks/{citation['chunk_id']}",
                    headers=headers,
                )
                citation_ok = citation_ok and opened.status_code == 200
            results.append(
                {
                    "id": case["id"],
                    "identity": case["identity"],
                    "titles": titles,
                    "recall_at_5": recall,
                    "reciprocal_rank": reciprocal_rank,
                    "acl_leakage": leakage,
                    "refusal_ok": refusal_ok,
                    "answer_terms_ok": answer_terms_ok,
                    "citation_valid": citation_ok,
                    "latency_ms": payload["retrieval"]["latency_ms"],
                    "retrieval_mode": payload["retrieval"].get("retrieval_mode"),
                    "generation_mode": payload["retrieval"].get("generation_mode"),
                    "generation_model": payload["retrieval"].get("generation_model"),
                }
            )

    retrieval_cases = [item for item in results if next(case for case in cases if case["id"] == item["id"])["expected_titles"]]
    refusal_cases = [item for item in results if next(case for case in cases if case["id"] == item["id"] ).get("expect_refusal")]
    latencies = [float(item["latency_ms"]) for item in results]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "dataset": str(dataset_path),
        "case_count": len(results),
        "metrics": {
            "recall_at_5": round(statistics.mean(item["recall_at_5"] for item in retrieval_cases), 4),
            "mrr_at_5": round(statistics.mean(item["reciprocal_rank"] for item in retrieval_cases), 4),
            "acl_leakage_rate": round(statistics.mean(item["acl_leakage"] for item in results), 4),
            "refusal_accuracy": round(statistics.mean(item["refusal_ok"] for item in refusal_cases), 4),
            "citation_validity": round(statistics.mean(item["citation_valid"] for item in results), 4),
            "answer_key_term_accuracy": round(statistics.mean(item["answer_terms_ok"] for item in results), 4),
            "latency_p50_ms": percentile(latencies, 0.5),
            "latency_p95_ms": percentile(latencies, 0.95),
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the versioned RAG and ACL evaluation set")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("dataset.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.base_url.rstrip("/"), args.dataset)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
