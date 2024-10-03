import os
import requests
from dotenv import load_dotenv
from google.cloud import bigquery_storage

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
DATASET_ID = os.getenv("GOOGLE_BIGQUERY_DATASET_ID")
TABLE_ID = os.getenv("GOOGLE_BIGQUERY_TABLE_ID")

# TODO: get access token from env
ACCESS_TOKEN = "test-token"
DATASET_LOCATION = "us-central1"


def read_from_big_query_storage_table():
    client = bigquery_storage.BigQueryReadClient()
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
        "model": "publishers/google/models/gemini-1.5-flash-002",
        "inputConfig": {"instancesFormat": "bigquery", "bigquerySource": {"inputUri": input_uri}},
        "outputConfig": {"predictionsFormat": "bigquery", "bigqueryDestination": {"outputUri": output_uri}},
    }

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
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
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }
    url = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{project_number}/locations/us-central1/publishers/google/models/gemini-1.5-flash-002:streamGenerateContent"
    response = requests.post(url, headers=headers, json=request_body)
    print(response.json())


def get_job_status(job_id):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    url = f"https://{DATASET_LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{DATASET_LOCATION}/batchPredictionJobs/{job_id}"
    response = requests.get(url, headers=headers)
    print(response.json())


if __name__ == "__main__":
    # read_from_big_query_storage_table()
    request_batch_prediction()
    # get_job_status("6471119163506032640")
    # request_online_prediction()
