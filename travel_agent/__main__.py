import argparse
import json
import uuid
from pathlib import Path

from .agent import TravelAgent
from .config import Settings
from .models import PreferenceRequest, RunRequest
from .storage import StoreError


def print_result(result):
    prefs = result["response"]["preferences_applied"]
    if prefs.get("preferred_output_format") == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        state, response = result["state"], result["response"]
        print(f"{state['workflow']}: {state['outcome']} ({response['reason']})")
        print(response["summary"])
        for claim in response["policy_claims"]:
            print(f"- {claim['text']} [{claim['citation']['chunk_id']}]")
        calc = response["facts"].get("calculate_expense_summary")
        if calc:
            print(f"Total: {calc['total_minor']} minor units {calc['currency']} (deterministic)")
        print(f"run_id={state['run_id']} steps={state['step_count']} retrievals={state['retrieval_calls']} retries={state['retry_count']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Training travel agent. No booking, sending, payment or publishing.")
    parser.add_argument("--user", default="demo-an")
    parser.add_argument("--token", help="Existing training session token (optional)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("message")
    run.add_argument("--request-id", default=None)
    run.add_argument("--workflow", choices=["pre_trip", "in_trip", "expense", "status", "policy", "direct", "rewrite"])
    run.add_argument("--output", type=Path)
    demo = sub.add_parser("demo")
    demo.add_argument("--output", type=Path, default=Path("artifacts/demo.json"))
    sub.add_parser("session")
    sub.add_parser("users")
    prefs = sub.add_parser("preferences")
    prefs.add_argument("action", choices=["view", "save", "delete"])
    prefs.add_argument("--language", choices=["vi", "en"])
    prefs.add_argument("--format", choices=["markdown", "json"])
    approval = sub.add_parser("approve")
    approval.add_argument("trip_id")
    approval.add_argument("status", choices=["approved", "rejected"])
    args = parser.parse_args(argv)
    agent = TravelAgent(Settings.from_env())
    if args.command == "users":
        print(json.dumps(agent.store.dataset["users"], ensure_ascii=False, indent=2))
        return
    issued = agent.store.create_session(args.user) if not args.token else None
    if args.command == "session":
        print(json.dumps(issued or agent.store.authenticate("Bearer " + args.token), indent=2))
        return
    session = agent.store.authenticate("Bearer " + (args.token or issued["token"]))
    if args.command == "preferences":
        if args.action == "save":
            value = PreferenceRequest(remember=True, response_language=args.language, preferred_output_format=args.format)
            agent.store.save_preferences(session["user_id"], value.model_dump(exclude={"remember"}, exclude_none=True))
        elif args.action == "delete":
            agent.store.delete_preferences(session["user_id"])
        print(json.dumps(agent.store.preferences(session["user_id"]), indent=2))
    elif args.command == "approve":
        print(json.dumps(agent.store.resolve_mock_approval(session, args.trip_id, args.status), indent=2))
    elif args.command == "run":
        result = agent.run(session, RunRequest(message=args.message, request_id=args.request_id or uuid.uuid4().hex,
                                              workflow=args.workflow))
        print_result(result)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    else:
        results = []
        for i, message in enumerate(["Chuẩn bị công tác TRIP-2026-001", "TRIP-2026-002 bị delay",
                                     "Rà soát chi phí EXP-2026-001", "Rà soát chi phí EXP-2026-003",
                                     "Chuẩn bị công tác TRIP-2026-003"]):
            result = agent.run(session, RunRequest(message=message, request_id=f"demo-{uuid.uuid4().hex}", case_id=f"demo_{i+1}"))
            print_result(result)
            results.append(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        print("Demo evidence:", args.output)


if __name__ == "__main__":
    try:
        main()
    except StoreError as err:
        raise SystemExit(err.code) from None
