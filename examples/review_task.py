"""Prepare a small worker/reviewer task or verify its artifact and Carrier sign-off."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from carrier import Client

TASK = "revenue-001"
EXPECTED = b"Net revenue: 1175.00\n"


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    (root / "work").mkdir()
    (root / "policy").mkdir()
    (root / "work" / "metrics.json").write_text(
        json.dumps(
            {"task_id": TASK, "gross_revenue": "1250.00", "refunds": "75.00"}, indent=2
        )
        + "\n"
    )
    (root / "policy" / "report-policy.json").write_text(
        json.dumps(
            {
                "task_id": TASK,
                "subtract_refunds": True,
                "decimal_places": 2,
                "format": "Net revenue: <amount> followed by one newline",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Worker project: {root / 'work'}\nReviewer policy: {root / 'policy'}")


async def verify(args):
    root = args.task.resolve()
    artifact = root / "work" / "report.txt"
    if artifact.read_bytes() != EXPECTED:
        raise ValueError("report.txt did not satisfy the independent acceptance check")
    digest = hashlib.sha256(EXPECTED).hexdigest()
    receipt = root / "review-receipt.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved["reviewer"] != args.reviewer or saved["artifact_sha256"] != digest:
            raise ValueError(
                "Saved review receipt does not match this reviewer and artifact"
            )
        async with Client(url=args.url, credentials=args.credentials) as inbox:
            # Retrying acknowledgment is safe after a lost response.
            await inbox.ack(saved["message_id"])
        print(json.dumps(saved, indent=2))
        return
    async with Client(url=args.url, credentials=args.credentials) as inbox:
        page = await inbox.wait(timeout=args.timeout)
        for message in page.messages:
            if message.sender != args.reviewer:
                continue
            try:
                body = message.json()
            except ValueError:
                continue
            if not isinstance(body, dict) or body.get("task_id") != TASK:
                continue
            if (
                body.get("status") != "accepted"
                or body.get("artifact_sha256") != digest
            ):
                raise ValueError(
                    "Reviewer did not accept this exact artifact; inspect its message"
                )
            saved = {
                "message_id": message.id,
                "reviewer": message.sender,
                "task_id": TASK,
                "artifact_sha256": digest,
            }
            # Save the evidence before acknowledging the completion message.
            with receipt.open("x", encoding="utf-8") as stream:
                json.dump(saved, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            await message.ack()
            print(json.dumps(saved, indent=2))
            return
    raise RuntimeError(
        "No matching reviewer sign-off; unrelated messages remain pending"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8877")
    parser.add_argument("--credentials")
    parser.add_argument(
        "--reviewer", help="Actual Carrier address from the reviewer binding"
    )
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.task.resolve())
    else:
        if not args.credentials or not args.reviewer or args.timeout <= 0:
            parser.error(
                "verify requires credentials, reviewer address, and positive timeout"
            )
        asyncio.run(verify(args))
