"""Request a CI summary and wait for the reply to this specific request."""

import argparse
import asyncio
import json
from uuid import uuid4

from carrier import Client


async def main(args):
    async with Client(url=args.url, credentials=args.credentials) as inbox:
        question = await inbox.send_json(
            {
                "build_id": args.build_id,
                "checks": {"lint": "passed", "unit": "passed", "integration": "failed"},
            },
            to=args.to,
            idempotency_key=uuid4().hex,
        )
        try:
            answer = await inbox.wait_for_reply(question, timeout=args.timeout)
        except TimeoutError:
            raise SystemExit(
                f"No reply within {args.timeout:g} seconds. Request {question.id} "
                "is still stored and can be processed later. Read its replies "
                f"with receive(reply_to={question.id}); a timeout does not cancel it."
            ) from None
        print(json.dumps(answer.json(), indent=2, sort_keys=True))
        await answer.ack()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8877")
    parser.add_argument("--credentials", default=".carrier/sdk/requester.json")
    parser.add_argument("--to", default="sdk/report-worker")
    parser.add_argument("--build-id", default="build-1842")
    parser.add_argument("--timeout", type=float, default=30)
    asyncio.run(main(parser.parse_args()))
