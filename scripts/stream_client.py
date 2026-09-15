"""Tests the SSE stream without a browser — pretty-prints each event as it arrives.

    python scripts/stream_client.py --file tests/fixtures/claims/CLM-001.pdf
    python scripts/stream_client.py --url https://<alb> --file tests/fixtures/claims/CLM-006.pdf
"""

import argparse
import json

import httpx


def stream_claim(base_url: str, file_path: str) -> None:
    url = f"{base_url}/v1/claims/adjudicate"
    with (
        open(file_path, "rb") as f,
        httpx.Client(timeout=None) as client,
        client.stream("POST", url, files={"file": f}) as response,
    ):
        event_name = "message"
        for line in response.iter_lines():
            if not line:
                continue
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                raw = line[len("data:") :].strip()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = raw
                print(f"[{event_name}] {json.dumps(data)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    stream_claim(args.url, args.file)


if __name__ == "__main__":
    main()
