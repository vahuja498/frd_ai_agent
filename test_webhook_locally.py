#!/usr/bin/env python3
"""
Manual Test Script
Simulates an Azure DevOps webhook call to your local FRD Agent.

Usage:
    python test_webhook_locally.py
    python test_webhook_locally.py --work-item-id 1234
"""

import argparse
import json
import sys
import httpx

DEFAULT_URL = "http://localhost:8000/api/v1/webhook/azure-devops"

SAMPLE_PAYLOAD = {
    "subscriptionId": "test-sub-001",
    "notificationId": 1,
    "id": "test-event-001",
    "eventType": "workitem.updated",
    "publisherId": "tfs",
    "resource": {
        "id": 1042,
        "workItemId": 1042,
        "rev": 3,
        "fields": {
            "System.WorkItemType": "User Story",
            "System.State": "Active",
            "System.Title": "Presales Discovery - Acme Corp",
            "System.Tags": "presales; discovery",
        },
        "url": "https://dev.azure.com/your-org/your-project/_apis/wit/workitems/1042",
    },
    "resourceVersion": "1.0",
    "createdDate": "2024-11-15T10:30:00Z",
}


def main():
    parser = argparse.ArgumentParser(description="Test FRD Agent webhook locally")
    parser.add_argument("--url", default=DEFAULT_URL, help="Webhook URL")
    parser.add_argument("--work-item-id", type=int, default=1042, help="Work Item ID")
    parser.add_argument("--tag", default="presales", help="Tag to test with")
    parser.add_argument("--no-presales", action="store_true", help="Send without presales tag")
    args = parser.parse_args()

    payload = dict(SAMPLE_PAYLOAD)
    payload["resource"] = dict(payload["resource"])
    payload["resource"]["id"] = args.work_item_id
    payload["resource"]["workItemId"] = args.work_item_id
    payload["resource"]["fields"] = dict(payload["resource"]["fields"])

    if args.no_presales:
        payload["resource"]["fields"]["System.Tags"] = "in-review; backend"
        print("⚠️  Sending WITHOUT presales tag (should be ignored)")
    else:
        payload["resource"]["fields"]["System.Tags"] = f"{args.tag}; discovery"
        print(f"✅ Sending WITH tag: '{args.tag}'")

    print(f"\n📤 Sending webhook to: {args.url}")
    print(f"   Work Item ID: {args.work_item_id}")
    print(f"   Tags: {payload['resource']['fields']['System.Tags']}")

    try:
        resp = httpx.post(args.url, json=payload, timeout=30)
        print(f"\n📥 Response Status: {resp.status_code}")
        print(f"   Body: {json.dumps(resp.json(), indent=2)}")
    except httpx.ConnectError:
        print(f"\n❌ Could not connect to {args.url}")
        print("   Make sure the server is running: uvicorn app.main:app --reload")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
