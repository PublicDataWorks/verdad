import json
import os
import requests
from dotenv import load_dotenv
from google.cloud import bigquery_storage
from google.oauth2 import service_account
from google.auth import default
from google.auth.transport.requests import Request

from processing_pipeline.constants import GEMINI_1_5_FLASH

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
DATASET_ID = os.getenv("GOOGLE_BIGQUERY_DATASET_ID")
TABLE_ID = os.getenv("GOOGLE_BIGQUERY_TABLE_ID")

# TODO: get access token from env
DATASET_LOCATION = "us-central1"


def get_access_token():
    # Try loading service account credentials first
    try:
        credentials = service_account.Credentials.from_service_account_file(
            "credentials.json", scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    except Exception:
        # Fallback to default credentials if service account fails
        credentials, project = default()

    # Refresh token if needed and return the access token
    credentials.refresh(Request())
    return credentials.token


def read_from_big_query_storage_table():
    # Create credentials object
    try:
        credentials = service_account.Credentials.from_service_account_file(
            "credentials.json", scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    except Exception:
        credentials, _ = default()

    # Initialize client with credentials
    client = bigquery_storage.BigQueryReadClient(credentials=credentials)
    table = "projects/{}/datasets/{}/tables/{}".format(PROJECT_ID, DATASET_ID, TABLE_ID)

    read_session = bigquery_storage.types.ReadSession()
    read_session.table = table
    read_session.data_format = bigquery_storage.types.DataFormat.AVRO
    read_session.read_options.selected_fields = ["id", "request", "response", "status"]

    parent = "projects/{}".format(PROJECT_ID)
    session = client.create_read_session(
        parent=parent,
        read_session=read_session,
        max_stream_count=1,
    )
    reader = client.read_rows(session.streams[0].name)
    rows = reader.rows(session)

    try:
        for row in rows:
            print(row)
    except EOFError:
        pass


def request_batch_prediction():
    input_uri = f"bq://{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    output_uri = f"bq://{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

    request_body = {
        "displayName": "batch_prediction",
        "model": f"publishers/google/models/{GEMINI_1_5_FLASH}",
        "inputConfig": {"instancesFormat": "bigquery", "bigquerySource": {"inputUri": input_uri}},
        "outputConfig": {"predictionsFormat": "bigquery", "bigqueryDestination": {"outputUri": output_uri}},
    }

    headers = {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }
    url = f"https://{DATASET_LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{DATASET_LOCATION}/batchPredictionJobs"
    response = requests.post(url, headers=headers, json=request_body)
    print(response.json())


def request_online_prediction():
    request_body = {
        "contents": {
            "role": "user",
            "parts": [
                {"text": "Good morning, how are you?"},
            ],
        }
    }
    project_number = "1024948154020"
    headers = {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }
    url = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{project_number}/locations/us-central1/publishers/google/models/{GEMINI_1_5_FLASH}:streamGenerateContent"
    response = requests.post(url, headers=headers, json=request_body)
    print(json.dumps(response.json(), indent=2))


def get_job_status(job_id):
    headers = {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
    }
    url = f"https://{DATASET_LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{DATASET_LOCATION}/batchPredictionJobs/{job_id}"
    response = requests.get(url, headers=headers)
    print(response.json())


if __name__ == "__main__":
    # read_from_big_query_storage_table()
    # get_job_status("6471119163506032640")
    # request_online_prediction()
    request_batch_prediction()
