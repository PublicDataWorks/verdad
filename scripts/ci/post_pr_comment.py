"""Create or update the one PR comment that carries a marker string. Stdlib only, runs in the worker image."""

import argparse
import json
import os
import sys
import urllib.request

API = "https://api.github.com"


def github_request(method, url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def find_comment_id(comments, marker):
    return next((c["id"] for c in comments if marker in (c.get("body") or "")), None)


def list_comments(repo, pr, token, request=github_request):
    comments, page = [], 1
    while True:
        batch = request("GET", f"{API}/repos/{repo}/issues/{pr}/comments?per_page=100&page={page}", token)
        comments += batch
        if len(batch) < 100:
            return comments
        page += 1


def upsert_comment(repo, pr, marker, body, token, request=github_request):
    comment_id = find_comment_id(list_comments(repo, pr, token, request), marker)
    if comment_id is not None:
        request("PATCH", f"{API}/repos/{repo}/issues/comments/{comment_id}", token, {"body": body})
        return "updated"
    request("POST", f"{API}/repos/{repo}/issues/{pr}/comments", token, {"body": body})
    return "created"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--marker", required=True, help="string that identifies the comment to update")
    parser.add_argument("--body-file", required=True)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 1
    with open(args.body_file) as f:
        body = f.read()
    if args.marker not in body:
        body = f"{args.marker}\n{body}"
    print(f"Comment {upsert_comment(args.repo, args.pr, args.marker, body, token)} on {args.repo}#{args.pr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
