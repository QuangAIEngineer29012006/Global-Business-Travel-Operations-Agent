"""
demo.py - Demo ngắn chạy cả 3 workflow bắt buộc (pre_trip, in_trip, post_trip) trên dữ liệu giả lập.

Cách chạy:
  python demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from dev_systems import MockSystems  # noqa: E402
from workflows import run_agent  # noqa: E402


DEMO_SCENARIOS = [
    {
        "label": "Workflow 1A — Trước chuyến đi (pre_trip: đã phê duyệt, đủ điều kiện)",
        "request": {
            "request_id": "REQ-DEMO-PRE-002",
            "actor": {"role": "employee", "actor_id": "EMP-002"},
            "session_id": "SES-DEMO-002",
            "message": "Tôi chuẩn bị công tác Tokyo chuyến TRIP-2026-002, đã đủ điều kiện chưa?",
            "context": {"trip_id": "TRIP-2026-002"},
        },
    },
    {
        "label": "Workflow 1B — Trước chuyến đi (pre_trip: approval đang pending -> awaiting_approval)",
        "request": {
            "request_id": "REQ-DEMO-PRE-001",
            "actor": {"role": "employee", "actor_id": "EMP-001"},
            "session_id": "SES-DEMO-001",
            "message": "Tôi chuẩn bị công tác Singapore TRIP-2026-001, đã đủ điều kiện chưa?",
            "context": {"trip_id": "TRIP-2026-001"},
        },
    },
    {
        "label": "Workflow 2 — Trong chuyến đi (in_trip: chuyến bay bị delay 150 phút -> tạo escalation draft)",
        "request": {
            "request_id": "REQ-DEMO-IN-002",
            "actor": {"role": "employee", "actor_id": "EMP-002"},
            "session_id": "SES-DEMO-002",
            "message": "Chuyến bay đi Tokyo trong TRIP-2026-002 bị delay 150 phút, hỗ trợ giúp tôi.",
            "context": {"trip_id": "TRIP-2026-002"},
        },
    },
    {
        "label": "Workflow 3 — Sau chuyến đi (post_trip: kiểm tra expense bằng phép tính xác định + policy)",
        "request": {
            "request_id": "REQ-DEMO-POST-003",
            "actor": {"role": "employee", "actor_id": "EMP-003"},
            "session_id": "SES-DEMO-003",
            "message": "Rà soát báo cáo chi phí EXP-2026-003 sau chuyến công tác Bangkok.",
            "context": {"report_id": "EXP-2026-003"},
        },
    },
]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ms = MockSystems(policy_semantic_mode="keyword")
    for idx, item in enumerate(DEMO_SCENARIOS, 1):
        print("=" * 84)
        print(f"[{idx}/{len(DEMO_SCENARIOS)}] {item['label']}")
        print("-" * 84)
        r = run_agent(item["request"], ms)
        print(f"Workflow    : {r['workflow']}")
        print(f"Outcome     : {r['status']} ({r['reason_code']})")
        print(f"Message     : {r['message']}")
        if r.get("next_action"):
            print(f"Next Action : {r['next_action']}")
        print(f"Steps       : {r['steps']} | Evidence Citations: {[e['chunk_id'] for e in r['evidence']]}")
        print("Artifacts   :", json.dumps(r["artifacts"], ensure_ascii=False))
        trace_actions = [f"{t['phase']}:{t['action']}({t['observation_status']})" for t in r["trace"]]
        print("Trace Flow  :", " -> ".join(trace_actions))
    print("=" * 84)


if __name__ == "__main__":
    main()
