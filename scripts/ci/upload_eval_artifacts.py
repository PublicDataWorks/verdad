"""Copy evaluation report and results files to R2 so they outlive the one-off Fly Machine."""

import argparse
import os
import sys

import boto3

CONTENT_TYPES = {".json": "application/json", ".md": "text/markdown"}


def upload(files, bucket, prefix, client):
    keys = []
    for path in files:
        key = f"{prefix.rstrip('/')}/{os.path.basename(path)}"
        content_type = CONTENT_TYPES.get(os.path.splitext(path)[1], "application/octet-stream")
        client.upload_file(path, bucket, key, ExtraArgs={"ContentType": content_type})
        keys.append(key)
    return keys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, help="key prefix inside the bucket, e.g. prompt-eval/<sha>")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    bucket = os.environ["R2_BUCKET_NAME"]
    for key in upload(args.files, bucket, args.prefix, client):
        print(f"uploaded r2://{bucket}/{key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
