import hashlib
import json
from dataclasses import asdict

from school_lab.domain.models import AnalysisContext, Submission


def stable_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def submission_hash(submission: Submission) -> str:
    return stable_hash(asdict(submission))


def config_hash(context: AnalysisContext) -> str:
    return stable_hash(context.config_payload())
