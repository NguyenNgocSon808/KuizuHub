#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${PORT:-5050}"

make -C "$repository_root/server" all
"$repository_root/server/build/kuizuhub-server" "$port" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true' EXIT

sleep 0.2
for client_number in 1 2 3; do
    python3 "$repository_root/client/ping_client.py" --port "$port" --request-id "three-client-$client_number"
done
