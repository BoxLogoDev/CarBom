#!/usr/bin/env python3
"""CarBom verification helper.

Drives the real public surface the way a user/integrator does:
- doctor: read-only health check (Python, required files, demo JS syntax).
- drive: replay one fixed scenario through the public engine API and
  capture guidance + care report evidence as JSON and text files.

Standard library only. Run from anywhere; the project root is resolved
from this file's location (scripts/ -> verify-carbom -> skills ->
.cursor -> project root).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]

REQUIRED_FILES = (
    "engine/__init__.py",
    "engine/signals.py",
    "engine/session.py",
    "engine/guidance.py",
    "engine/profiles.py",
    "engine/report.py",
    "engine/adapters/simulator.py",
    "engine/adapters/vehicle_sdk.py",
    "demo/index.html",
    "demo/styles.css",
    "demo/demo.js",
)

EXPECTED_FINAL_STATE = {
    "dropoff_normal": "COMPLETED",
    "forgotten_rising_temp": "EXCEPTION",
    "pet_dropoff": "COMPLETED",
}


def cmd_doctor(_args: argparse.Namespace) -> int:
    ok = True
    print(f"project_root: {PROJECT_ROOT}")
    print(f"python: {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info < (3, 10):
        print("FAIL: Python >= 3.10 is required")
        ok = False
    for rel in REQUIRED_FILES:
        exists = (PROJECT_ROOT / rel).is_file()
        print(f"{'OK  ' if exists else 'FAIL'} file {rel}")
        ok = ok and exists
    node_check = subprocess.run(
        ["node", "--check", str(PROJECT_ROOT / "demo" / "demo.js")],
        capture_output=True,
        text=True,
    )
    print(f"{'OK  ' if node_check.returncode == 0 else 'FAIL'} node --check demo/demo.js")
    if node_check.returncode != 0:
        print(node_check.stderr.strip())
        ok = False
    print("doctor:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def cmd_drive(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(PROJECT_ROOT))
    from engine.adapters.simulator import replay_scenario
    from engine.guidance import DestinationContext, guidance_for_session
    from engine.report import report_for_session
    from engine.session import CareSession

    session = CareSession()
    final_state = replay_scenario(session, args.scenario)
    guidance = guidance_for_session(session, context=DestinationContext.DROPOFF)
    report = report_for_session(session)

    evidence = {
        "scenario": args.scenario,
        "final_state": final_state.name,
        "expected_final_state": EXPECTED_FINAL_STATE[args.scenario],
        "passenger_present": session.passenger_present,
        "current_snapshot": {
            "cabin_temp_c": session.current_snapshot.cabin_temp_c,
            "timestamp": session.current_snapshot.timestamp,
        },
        "transitions": [
            {
                "from_state": t.from_state.name,
                "to_state": t.to_state.name,
                "reason": t.reason,
                "timestamp": t.timestamp,
            }
            for t in session.history
        ],
        "guidance": {
            "level": guidance.level.name,
            "text": guidance.text,
            "reason": guidance.reason,
        },
        "report": {
            "final_state": report.final_state.name,
            "completed": report.completed,
            "exception_occurred": report.exception_occurred,
            "exception_count": report.exception_count,
            "transition_count": report.transition_count,
            "max_cabin_temp_c": report.max_cabin_temp_c,
            "duration_seconds": report.duration_seconds,
            "summary": report.summary,
        },
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"drive-{args.scenario}.json"
    txt_path = out_dir / f"drive-{args.scenario}.txt"
    json_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        f"scenario: {args.scenario}",
        f"final_state: {evidence['final_state']} (expected {evidence['expected_final_state']})",
        f"passenger_present: {evidence['passenger_present']}",
        "transitions:",
        *(
            f"  {t['from_state']} -> {t['to_state']} ({t['reason']}) @ {t['timestamp']}"
            for t in evidence["transitions"]
        ),
        f"guidance: {evidence['guidance']['level']} / {evidence['guidance']['reason']} / {evidence['guidance']['text']}",
        f"report: {evidence['report']['summary']}",
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"evidence: {json_path}")
    print(f"evidence: {txt_path}")

    if evidence["final_state"] != evidence["expected_final_state"]:
        print("FAIL: final state does not match the expected scenario outcome")
        return 1
    if evidence["report"]["final_state"] != evidence["final_state"]:
        print("FAIL: report final_state disagrees with session state")
        return 1
    if evidence["guidance"]["level"] == "":
        print("FAIL: guidance missing")
        return 1
    print("drive: OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="read-only health check")
    drive = sub.add_parser("drive", help="replay one fixed scenario and capture evidence")
    drive.add_argument("--scenario", choices=sorted(EXPECTED_FINAL_STATE), required=True)
    drive.add_argument("--out", required=True, help="evidence output directory")
    args = parser.parse_args()
    if args.command == "doctor":
        return cmd_doctor(args)
    return cmd_drive(args)


if __name__ == "__main__":
    raise SystemExit(main())
