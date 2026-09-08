"""
GCS helper utilities shared across all EarSight agents.

Uses google-cloud-storage. Credentials come from the environment:
  GOOGLE_APPLICATION_CREDENTIALS or ADC (Application Default Credentials).
"""

import datetime
import json
import os
from pathlib import Path

from google.cloud import storage


def _client() -> storage.Client:
    return storage.Client()


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    """Parse gs://bucket/path/to/object → (bucket, blob_name)."""
    assert uri.startswith("gs://"), f"Not a GCS URI: {uri}"
    without_scheme = uri[5:]
    bucket, _, blob_name = without_scheme.partition("/")
    return bucket, blob_name


def download_to_file(gcs_uri: str, dest_path: str) -> str:
    """Download a GCS object to a local file. Returns dest_path."""
    bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
    client = _client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(dest_path)
    return dest_path


def upload_from_file(local_path: str, gcs_uri: str, content_type: str = "application/octet-stream") -> str:
    """Upload a local file to GCS. Returns the gcs_uri."""
    bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
    client = _client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path, content_type=content_type)
    return gcs_uri


def upload_json(data: dict, gcs_uri: str) -> str:
    """Upload a dict as JSON to GCS. Returns the gcs_uri."""
    bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
    client = _client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json")
    return gcs_uri


def download_json(gcs_uri: str) -> dict:
    """Download and parse a JSON object from GCS."""
    bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
    client = _client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return json.loads(blob.download_as_text())


def make_uri(job_id: str, filename: str) -> str:
    """Build a GCS URI for a job artefact: gs://BUCKET/jobs/{job_id}/{filename}."""
    bucket = os.environ["GCS_BUCKET"]
    return f"gs://{bucket}/jobs/{job_id}/{filename}"


def signed_url(gcs_uri: str, hours: int = 6) -> str:
    """
    Generate a signed HTTPS URL for a GCS object, valid for `hours` hours.

    On Cloud Run, credentials are compute-engine tokens with no local private key.
    We pass service_account_email + access_token so the client library signs via
    the IAM SignBlob API instead of a local key.

    Note: if signing still fails at runtime, the service account needs
    roles/iam.serviceAccountTokenCreator on itself.
    """
    import google.auth
    import google.auth.transport.requests

    bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    service_account_email = credentials.service_account_email
    access_token = credentials.token

    client = _client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    url = blob.generate_signed_url(
        expiration=datetime.timedelta(hours=hours),
        method="GET",
        version="v4",
        service_account_email=service_account_email,
        access_token=access_token,
    )
    return url
