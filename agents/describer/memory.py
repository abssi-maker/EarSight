"""
Established-facts memory for the describer.

One append-only list per job, persisted to GCS so the describer can resume
after a restart without re-describing facts it already narrated.

GCS key: gs://BUCKET/jobs/{job_id}/established_facts.json
"""

import json
import os
from typing import Optional

from agents.shared.gcs import download_json, make_uri, upload_json


def load(job_id: str) -> list[str]:
    """Load the established-facts list for a job. Returns [] if not found."""
    uri = make_uri(job_id, "established_facts.json")
    try:
        data = download_json(uri)
        return data.get("facts", [])
    except Exception:
        return []


def save(job_id: str, facts: list[str]) -> None:
    """Persist the established-facts list to GCS."""
    uri = make_uri(job_id, "established_facts.json")
    upload_json({"facts": facts}, uri)
