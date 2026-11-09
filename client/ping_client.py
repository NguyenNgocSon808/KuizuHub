#!/usr/bin/env python3
"""Send a Phase 0 PING to KuizuHub and print the JSON response."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.app.services.network_client import NetworkClient, NetworkClientError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--request-id", default="phase0-ping")
    arguments = parser.parse_args()
    try:
        response = NetworkClient(arguments.host, arguments.port).ping(request_id=arguments.request_id)
    except NetworkClientError as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(response, ensure_ascii=False))
    return 0 if response.get("type") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
