import sys, json
sys.path.insert(0, "src")
from dev_systems import MockSystems
from workflows import run_agent

ms = MockSystems()   # đọc fixture trong data/mock-systems

request = {
    "request_id": "REQ-2026-001",
    "actor": {"role": "employee", "actor_id": "EMP-001"},
    "session_id": "SES-001",
    "message": "Tôi chuẩn bị công tác Singapore, đã đủ điều kiện chưa?",
    "context": {"trip_id": "TRIP-2026-001"},
}

r = run_agent(request, ms)
print(r["status"], "-", r["reason_code"])
print(r["message"])
print(json.dumps(r["artifacts"], ensure_ascii=False, indent=2))
print("Evidence:", [e["chunk_id"] for e in r["evidence"]])