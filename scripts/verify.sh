#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

docker compose up -d --build

python3 - <<'PY'
import json
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"


def request(path, method="GET", body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read())


for _ in range(90):
    try:
        health = request("/health")
        if health["ok"]:
            break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("backend did not become healthy")

for broker_id in ("tms_a_freightflow", "tms_b_hauldesk"):
    request(f"/api/brokers/{broker_id}/pool-opt-in", method="PUT", body={"enabled": True})

loads = request("/api/brokers/tms_a_freightflow/loads")
target = next(load for load in loads if load["pickup"]["city"] == "Arlington" and load["delivery"]["city"] == "Sugar Land")
recommendation = request(f"/api/brokers/tms_a_freightflow/loads/{target['load_id']}/recommendation?pool=true")

first = recommendation["own_carriers"][0]
assert first["carrier_name"] == "IBRAHIM TRANSPORT INC", first
assert first["confidence"] == "high", first
assert recommendation["price"]["confidence"] == "high", recommendation["price"]
assert all("DELTA PRIME" not in carrier["carrier_name"].upper() for carrier in recommendation["pool_carriers"])

print("Verified API path: Ibrahim first/high confidence; pool tier excludes overlapping Delta Prime.")
PY

echo "Frontend: http://localhost:3000"
