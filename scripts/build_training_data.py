"""Author the synthetic training fixtures. Never uses external travel/HR systems."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from travel_agent.policy import render_rule


def build():
    users = [{"user_id": f"demo-{name}", "role": "employee", "traveler_id": f"TRV-{i:03d}"}
             for i, name in enumerate(["an", "binh", "chi", "dung"], 1)]
    users += [{"user_id": "demo-reviewer", "role": "reviewer", "traveler_id": None},
              {"user_id": "demo-approver", "role": "approver", "traveler_id": None}]
    profiles = [{"traveler_id": u["traveler_id"], "owner_id": u["user_id"],
                 "department": "Engineering" if i % 2 == 0 else "Finance",
                 "preference": {"seat": "aisle" if i % 2 == 0 else "window"}}
                for i, u in enumerate(users[:4])]
    trips, approvals, itineraries = [], [], []
    cases = [("demo-an", "TRV-001", "Singapore", "planned", "approved", "none"),
             ("demo-an", "TRV-001", "Singapore", "in_progress", "approved", "delayed"),
             ("demo-an", "TRV-001", "Tokyo", "planned", "pending", "none"),
             ("demo-binh", "TRV-002", "Seoul", "planned", "rejected", "none"),
             ("demo-an", "TRV-001", "Singapore", "planned", "approved", "none"),
             ("demo-binh", "TRV-002", "Frankfurt", "cancelled", "rejected", "cancelled"),
             ("demo-an", "TRV-001", "Singapore", "completed", "approved", "none"),
             ("demo-chi", "TRV-003", "Seoul", "in_progress", "approved", "cancelled"),
             ("demo-an", "TRV-001", "Singapore", "planned", "not_requested", "none")]
    for i, (owner, traveler, destination, status, approval, disruption) in enumerate(cases, 1):
        tid = f"TRIP-2026-{i:03d}"
        trips.append({"trip_id": tid, "traveler_id": traveler, "owner_id": owner, "destination": destination,
                      "start_date": "2026-11-20", "end_date": "2026-11-22",
                      "purpose": None if i == 5 else "Training workshop (synthetic)", "status": status})
        approvals.append({"trip_id": tid, "status": approval, "approval_id": f"APR-{i:03d}",
                          "action_summary": "Review training travel request", "mock": True})
        itineraries.append({"trip_id": tid, "flight": f"MOCK-FLIGHT-{i:03d}", "hotel": "Training Hotel",
                            "event": "Training workshop", "disruption": disruption,
                            "delay_minutes": 180 if disruption == "delayed" else 0})
    reports = []
    for i in range(1, 4):
        reports.append({"report_id": f"EXP-2026-{i:03d}", "trip_id": "TRIP-2026-007", "owner_id": "demo-an",
                        "status": "draft", "currency": "SGD", "items": [
                            {"item_id": "ITEM-01", "category": "meal", "date": "2026-11-20",
                             "amount_minor": None if i == 2 else 12000 if i == 3 else 4500,
                             "currency": "SGD", "receipt": i != 2},
                            {"item_id": "ITEM-02", "category": "hotel", "date": None if i == 2 else "2026-11-20",
                             "amount_minor": 30000 if i == 3 else 18000, "currency": "SGD", "receipt": True},
                            {"item_id": "ITEM-03", "category": "meal", "date": "2026-11-21", "amount_minor": 3000,
                             "currency": "SGD", "receipt": True}]})
    rules = [("travel", "trip_fields", ["pre_trip"], ["*"]),
             ("approval", "approval", ["pre_trip"], ["*"]),
             ("visa", "visa", ["pre_trip"], ["Singapore"]),
             ("insurance", "insurance", ["pre_trip"], ["*"]),
             ("expense", "receipts", ["expense"], ["*"]),
             ("expense", "expense_review", ["expense"], ["*"]),
             ("travel", "delay", ["in_trip"], ["*"]),
             ("travel", "cancellation", ["in_trip"], ["*"])]
    chunks = []
    for category, kind, workflows, destinations in rules:
        chunks.append({"category": category, "section": kind, "workflows": workflows,
                       "destinations": destinations, "rule": {"kind": kind}})
    for category, limit in [("meal", 6000), ("hotel", 20000), ("transport", 5000)]:
        chunks.append({"category": "expense", "section": f"daily_limit_{category}", "workflows": ["expense"],
                       "destinations": ["*"], "rule": {"kind": "daily_limit", "category": category,
                       "currency": "SGD", "limit_minor": limit}})
    for i, c in enumerate(chunks, 1):
        c.update(chunk_id=f"POL-{i:03d}@1.0", doc_id=f"TRAINING-{c['category'].upper()}",
                 source="data/policies.json", version="1.0", active=True,
                 access_roles=["employee", "reviewer", "approver"], text=render_rule(c["rule"]))
    return {"users": users, "profiles": profiles, "trips": trips, "approvals": approvals,
            "itineraries": itineraries, "reports": reports}, chunks


if __name__ == "__main__":
    data, policies = build()
    (ROOT / "data").mkdir(exist_ok=True)
    for name, value in [("training.json", data), ("policies.json", policies)]:
        (ROOT / "data" / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
