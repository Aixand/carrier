"""Summarize CI checks received through a persistent Carrier inbox."""

import argparse
import asyncio
import json

from carrier import Client


async def main(args):
    async with Client(url=args.url, credentials=args.credentials) as inbox:
        @inbox.consumer()
        async def summarize(message):
            request = message.json()
            failed = sorted(
                name for name, status in request["checks"].items()
                if status != "passed"
            )
            report = {
                "build_id": request["build_id"],
                "checks": len(request["checks"]),
                "failed": failed,
                "status": "failed" if failed else "passed",
            }
            # Reprocessing the same input must reuse the same reply key and body.
            await message.reply_json(report, idempotency_key=f"report:{message.id}")
            await message.ack()
            print(json.dumps(report, sort_keys=True), flush=True)

        print(f"Listening as {inbox.address}; press Ctrl+C to stop.", flush=True)
        await inbox.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8877")
    parser.add_argument("--credentials", default=".carrier/sdk/worker.json")
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        pass
