import math
from collections import Counter

import numpy as np

from .embeddings import FakeEmbedder
from .models import Citation, Claim, PolicyChunk
from .safety import injection_like
from .text import normalize


class PolicyError(Exception):
    def __init__(self, code):
        self.code = code


def render_rule(rule):
    """Training corpus uses canonical sentences so structured limits are grounded in quoted text."""
    kind = rule.get("kind")
    fixed = {
        "trip_fields": "Yêu cầu công tác cần có điểm đến, ngày đi, ngày về và mục đích.",
        "approval": "Chỉ tạo draft tác nghiệp khi approval mô phỏng của chuyến đi là approved; pending hoặc rejected phải dừng.",
        "visa": "Với Singapore trong bộ dữ liệu training, checklist cần có bước nhờ reviewer kiểm tra yêu cầu nhập cảnh mô phỏng.",
        "insurance": "Checklist trước chuyến đi cần có bước kiểm tra bảo hiểm công tác mô phỏng với reviewer.",
        "receipts": "Mọi dòng chi phí cần chứng từ và ngày chi; thiếu thông tin phải bổ sung trước khi rà soát hoàn tất.",
        "expense_review": "Rà soát chi phí chỉ tạo bản nháp cho reviewer; không xác nhận hoàn tiền hay phê duyệt chi phí.",
        "delay": "Khi chuyến bay mô phỏng bị delay, chuẩn bị support draft cho Travel Operations; không tự đổi vé hay chi tiền.",
        "cancellation": "Khi chuyến bay mô phỏng bị hủy, chuẩn bị escalation draft và chuyển người phụ trách xem xét.",
    }
    if kind in fixed and set(rule) == {"kind"}:
        return fixed[kind]
    if kind == "daily_limit" and set(rule) == {"kind", "category", "currency", "limit_minor"}:
        if rule["category"] not in {"meal", "hotel", "transport"} or rule["currency"] not in {"SGD"}:
            raise PolicyError("invalid_policy_rule")
        limit = rule["limit_minor"]
        if type(limit) is not int or not 0 < limit <= 1000000:
            raise PolicyError("invalid_policy_rule")
        return f"Ngưỡng rà soát training cho {rule['category']} là {limit} minor units {rule['currency']}/ngày; vượt ngưỡng cần reviewer xem xét."
    raise PolicyError("invalid_policy_rule")


def rule_key(chunk):
    r = chunk["rule"]
    return (r["kind"], r.get("category"), r.get("currency"), tuple(sorted(chunk["destinations"])))


def grounded_claim(chunk):
    parsed = PolicyChunk.model_validate(chunk)
    quote = render_rule(parsed.rule)
    if injection_like(parsed.text) or quote not in parsed.text:
        raise PolicyError("ungrounded_policy_rule")
    citation = Citation.model_validate({key: getattr(parsed, key) for key in Citation.model_fields})
    return Claim(text=quote, quote=quote, citation=citation).model_dump()


class PolicyIndex:
    """Small hybrid index: lexical BM25 and deterministic hashed vectors, filtered before ranking."""

    def __init__(self, chunks):
        self.chunks = [PolicyChunk.model_validate(c).model_dump() for c in chunks]
        self.embedder = FakeEmbedder()

    def search(self, query, category, role, workflow, destination, max_results):
        eligible = [c for c in self.chunks if c["active"] and c["category"] == category
                    and role in c["access_roles"] and workflow in c["workflows"]
                    and ("*" in c["destinations"] or destination in c["destinations"])]
        groups = {}
        for c in eligible:
            groups.setdefault(rule_key(c), []).append(c)
        if any(len(group) > 1 for group in groups.values()):
            raise PolicyError("policy_version_conflict")
        rejected, safe = [], []
        for c in eligible:
            try:
                grounded_claim(c)
            except PolicyError:
                rejected.append(c["chunk_id"])
            else:
                safe.append(c)
        if not safe:
            return {"chunks": [], "scores": [], "rejected_chunks": rejected}
        terms = normalize(query).split()
        generic = {"chinh", "sach", "quy", "dinh", "training", "policy", "toi", "can", "gi", "ve", "nhu", "nao"}
        important = set(terms) - generic
        docs = [normalize(c["text"] + " " + c["section"]).split() for c in safe]
        avg_len = sum(map(len, docs)) / len(docs)
        qvec = self.embedder.embed_query(query)
        scored = []
        for c, doc in zip(safe, docs):
            counts = Counter(doc)
            bm25 = 0.0
            for term in set(terms):
                df = sum(term in d for d in docs)
                idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
                tf = counts[term]
                bm25 += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * len(doc) / avg_len))
            cosine = float(np.dot(qvec, self.embedder.embed_query(c["text"])))
            if important & set(doc):
                scored.append((bm25 + max(0, cosine), c))
        scored.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
        selected = [(score, c) for score, c in scored[:max_results] if score > 0.02]
        return {"chunks": [c for _, c in selected], "scores": [round(s, 6) for s, _ in selected],
                "rejected_chunks": rejected}
