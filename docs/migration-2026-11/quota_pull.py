"""Pull the Gemini API (generativelanguage.googleapis.com) per-model quota limits for one or more GCP projects.

Needs a logged-in gcloud (``gcloud auth login``); API keys cannot read quotas. Run from anywhere:

    python docs/migration-2026-11/quota_pull.py 815787511264:pdw-gemini 371204627224:verdad-factchecking

Writes <name>.json (raw Service Usage response) and <name>.tsv in the cwd and prints one line per model-specific
bucket: model, quota name, unit, default limit, effective limit, OVERRIDE when they differ (an override is a
Google-applied cap or raise). The Oct 31 2026 snapshot is reports/quota_table.txt.
"""

import json
import subprocess
import sys
import urllib.request

URL = (
    "https://serviceusage.googleapis.com/v1beta1/projects/{num}/services/"
    "generativelanguage.googleapis.com/consumerQuotaMetrics?view=FULL&pageSize=500"
)


def access_token() -> str:
    return subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()


def pull(num: str, token: str) -> dict:
    req = urllib.request.Request(URL.format(num=num), headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def rows(data: dict) -> list[tuple]:
    out = []
    for metric in data.get("metrics", []):
        name = metric.get("displayName", "")
        for limit in metric.get("consumerQuotaLimits", []):
            unit = limit.get("unit", "")
            for bucket in limit.get("quotaBuckets", []):
                model = bucket.get("dimensions", {}).get("model")
                if not model:
                    continue
                default, effective = bucket.get("defaultLimit"), bucket.get("effectiveLimit")
                out.append((model, name, unit, default, effective, "OVERRIDE" if default != effective else ""))
    return sorted(out)


def main(targets: list[str]) -> None:
    token = access_token()
    for target in targets:
        num, _, name = target.partition(":")
        name = name or num
        data = pull(num, token)
        if "error" in data:
            print(f"=== {name}: {data['error'].get('message')}")
            continue
        with open(f"{name}.json", "w") as f:
            json.dump(data, f, indent=1)
        table = rows(data)
        with open(f"{name}.tsv", "w") as f:
            for r in table:
                f.write("\t".join(str(x) for x in r) + "\n")
        print(f"\n=== {name} ({num}) ===")
        for model, qname, unit, default, effective, flag in table:
            print(f"{model:<24} {qname[:60]:<60} {unit:<14} default={str(default):>9} eff={str(effective):>9} {flag}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
