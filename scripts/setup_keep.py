"""One-time Keep configuration script.
Run after docker-compose up: py scripts/setup_keep.py --data-dir ./data/openrca
"""
import argparse
import sys
import os
import time
import httpx

# Add project to path so we can import the adapter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "aiops"))

KEEP_API_URL = "http://localhost:8080"
MAX_RETRIES = 30
RETRY_INTERVAL = 2


def wait_for_keep():
    for i in range(MAX_RETRIES):
        try:
            r = httpx.get(f"{KEEP_API_URL}/healthcheck")
            if r.status_code == 200:
                print("Keep API is ready")
                return
        except httpx.ConnectError:
            pass
        print(f"Waiting for Keep API... ({i+1}/{MAX_RETRIES})")
        time.sleep(RETRY_INTERVAL)
    print("Keep API not available")
    sys.exit(1)


def create_api_key():
    r = httpx.post(
        f"{KEEP_API_URL}/settings/apikey",
        json={"name": "aiops-service"},
        auth=("admin", "admin"),
    )
    if r.status_code in (200, 201):
        key = r.json().get("apiKey", r.json().get("api_key", ""))
        print(f"API key created: {key[:8]}...")
        return key
    print(f"Failed to create API key: {r.status_code} {r.text}")
    return ""


def load_topology(api_key, data_dir, dataset="Bank"):
    try:
        from app.adapters.openrca import OpenRCAAdapter
        adapter = OpenRCAAdapter(data_dir)
        topo = adapter.load_topology(dataset)
        r = httpx.post(
            f"{KEEP_API_URL}/topology",
            json=topo,
            headers={"x-api-key": api_key},
        )
        print(f"Topology loaded: {r.status_code} ({len(topo.get('nodes', []))} nodes, {len(topo.get('edges', []))} edges)")
    except Exception as e:
        print(f"Topology loading skipped: {e}")


def main():
    parser = argparse.ArgumentParser(description="Setup Keep for AIOps MVP")
    parser.add_argument("--data-dir", default="./data/openrca", help="Path to OpenRCA data")
    parser.add_argument("--dataset", default="Bank", help="Dataset name")
    args = parser.parse_args()

    wait_for_keep()
    api_key = create_api_key()
    if api_key:
        load_topology(api_key, args.data_dir, args.dataset)
        print(f"\nAdd to .env:\nKEEP_API_KEY={api_key}")
    else:
        print("Setup incomplete: could not create API key")


if __name__ == "__main__":
    main()
