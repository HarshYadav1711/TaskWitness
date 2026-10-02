"""Headed operator UI acceptance helper (Validated Plan Demo Mode).

Not part of the product UI. Used for Phase 7 manual/automated acceptance.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

from taskwitness.operator.app import create_app
from taskwitness.operator.runtime import OperatorRuntime
from taskwitness.schemas import TaskSpec

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision", choices=["approved", "rejected"], default="approved")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--headed", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--slow-mo", type=int, default=50)
    parser.add_argument("--pause-once", action="store_true")
    parser.add_argument("--demo-plan", default="examples/base-plan.json")
    parser.add_argument("--arm-fault", action="store_true")
    args = parser.parse_args(argv)

    if args.arm_fault:
        from demo_env.app import get_db_path
        from demo_env.db import arm_fail_after_send_commit_once, connect

        conn = connect(get_db_path())
        try:
            arm_fail_after_send_commit_once(conn)
            conn.commit()
        finally:
            conn.close()
        print("Armed fail_after_send_commit_once")

    port = _free_port()
    spec = TaskSpec.model_validate_json(
        (ROOT / args.demo_plan).read_text(encoding="utf-8")
    )
    journal = ROOT / ".taskwitness" / f"accept-{port}.sqlite3"
    journal.parent.mkdir(parents=True, exist_ok=True)
    if journal.exists():
        journal.unlink()

    runtime = OperatorRuntime(
        base_url=args.base_url,
        headed=args.headed,
        slow_mo_ms=args.slow_mo,
        journal_path=journal,
        evidence_root=ROOT / "evidence",
        source_root=ROOT,
        demo_task_spec=spec,
    )
    app = create_app(runtime)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)

    op_url = f"http://127.0.0.1:{port}/operator"
    print(f"Operator acceptance UI: {op_url}")
    print(f"Decision={args.decision} pause_once={args.pause_once} arm_fault={args.arm_fault}")

    result = {
        "run_id": None,
        "verification": None,
        "evidence_path": None,
        "final_message": None,
        "authority": None,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(op_url, wait_until="domcontentloaded")
        page.get_by_role("button", name="Start validated plan").click()

        paused_once = False
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            dialog = page.locator("#approval-dialog")
            pause_btn = page.locator("#btn-pause")
            resume_btn = page.locator("#btn-resume")

            if args.pause_once and not paused_once and not dialog.is_visible():
                if pause_btn.is_visible():
                    pause_btn.click()
                    # Wait for PAUSED label or resume control.
                    for _ in range(40):
                        if resume_btn.is_visible() or "PAUSED" in page.locator("#run-state-label").inner_text():
                            break
                        page.wait_for_timeout(200)
                    if resume_btn.is_visible():
                        resume_btn.click()
                        paused_once = True
                        print("Pause/Resume exercised at safe checkpoint")

            if dialog.is_visible():
                btn_id = "btn-approve" if args.decision == "approved" else "btn-reject"
                try:
                    dialog.locator(f"#{btn_id}").click(force=True, timeout=3000)
                except Exception:
                    page.evaluate(f"document.getElementById('{btn_id}')?.click()")
                page.wait_for_timeout(500)
                continue

            ver = page.locator("#verify-summary").inner_text().strip()
            if ver and ver not in {"—", "VERIFYING…"}:
                result["run_id"] = page.locator("#meta-run-id").inner_text().strip()
                result["verification"] = ver
                result["final_message"] = page.locator("#verify-message").inner_text().strip()
                if page.locator("#evidence-box").is_visible():
                    result["evidence_path"] = page.locator("#evidence-path").inner_text().strip()
                # Authority from snapshot API
                import json
                from urllib.request import urlopen

                with urlopen(f"http://127.0.0.1:{port}/api/runs/{result['run_id']}") as resp:
                    snap = json.loads(resp.read().decode("utf-8"))
                result["authority"] = (snap.get("task_spec") or {}).get("authority")
                result["verified_complete"] = snap.get("verified_complete")
                result["execution_state"] = snap.get("execution_state")
                break
            page.wait_for_timeout(200)
        else:
            browser.close()
            server.should_exit = True
            print("TIMEOUT", result)
            return 1

        browser.close()

    server.should_exit = True
    print(result)
    if args.decision == "approved":
        ok = result.get("verified_complete") is True and result.get("verification") in {
            "VERIFIED",
            "PASSED",
        }
    else:
        ok = (
            result.get("verified_complete") is False
            and result.get("verification") == "INCOMPLETE"
            and result.get("final_message") != "Goal verified"
        )
    if result.get("authority", {}).get("send_message") is not False:
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
