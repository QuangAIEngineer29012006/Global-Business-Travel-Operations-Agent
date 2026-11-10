import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_systems import MockSystems  # noqa: E402
from policy_search import PolicySearchIndex  # noqa: E402


class FixtureEncoder:
    model_name = "test-fixture-encoder"

    def encode(self, texts):
        vectors = []
        for text in texts:
            normalized = text.lower()
            if "entry authorization" in normalized or "điều kiện nhập cảnh" in normalized:
                vectors.append([1.0, 0.0, 0.0])
            elif "expense receipts" in normalized or "chứng từ" in normalized:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


def test_hybrid_search_retrieves_semantic_match_and_keeps_category_and_citation_metadata():
    systems = MockSystems(policy_encoder=FixtureEncoder(), policy_semantic_mode="hybrid")

    response = systems.search_travel_policy(
        {"query": "entry authorization", "category": "visa", "max_results": 2}
    )

    assert response["ok"]
    results = response["data"]["results"]
    assert results and results[0]["chunk_id"] == "CHUNK-005"
    assert all(result["category"] == "visa" for result in results)
    assert all(result["doc_id"] and result["source"] and result["section"] and result["version"]
               for result in results)


def test_hybrid_index_persists_keyword_and_embedding_tables():
    chunks = [{
        "chunk_id": "CHUNK-TEST",
        "doc_id": "DOC-TEST",
        "source": "Test policy",
        "section": "Entry authorization",
        "page": "",
        "version": "1.0",
        "category": "visa",
        "text": "Verify entry authorization before travel.",
    }]
    index = PolicySearchIndex(chunks, encoder=FixtureEncoder(), semantic_mode="hybrid")
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE policy_chunks "
        "(chunk_id TEXT PRIMARY KEY, category TEXT, section TEXT, text TEXT)"
    )
    connection.execute(
        "INSERT INTO policy_chunks VALUES (?, ?, ?, ?)",
        ("CHUNK-TEST", "visa", "Entry authorization", "Verify entry authorization before travel."),
    )

    index.persist_to(connection)

    assert connection.execute("SELECT COUNT(*) FROM policy_chunks_fts").fetchone()[0] == 1
    embedding = connection.execute(
        "SELECT model_name, vector_json FROM policy_embeddings WHERE chunk_id = ?",
        ("CHUNK-TEST",),
    ).fetchone()
    assert embedding[0] == "test-fixture-encoder"
    assert embedding[1]


def test_search_reindexes_chunks_replaced_after_initialization():
    systems = MockSystems(policy_semantic_mode="keyword")
    systems.chunks = [{
        "chunk_id": "CHUNK-REPLACED",
        "doc_id": "DOC-TEST",
        "source": "Test policy",
        "section": "Remote work travel",
        "page": "",
        "version": "1.0",
        "category": "travel",
        "text": "Review remote work travel before departure.",
    }]

    response = systems.search_travel_policy(
        {"query": "remote work travel", "category": "travel", "max_results": 1}
    )

    assert response["data"]["results"][0]["chunk_id"] == "CHUNK-REPLACED"
