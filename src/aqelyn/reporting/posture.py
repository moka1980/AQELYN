"""ECR-0100: ingest posture observations alongside the vulnerability document.

Before this module the collection directory accepted exactly one shape - a grype-style
`vulns.json`. That meant a platform whose engines are CSPM, DSPM, SSPM and ISPM had no way
to be told a posture fact: a missing response header, a listener bound where it should not
be, a mail policy published but not enforced. Those are not CVEs and never become one.

`posture.json` is that path. Each observation must arrive with the four narrative fields a
`Finding` requires - what happened, why it matters, how it was determined, what inaction
risks - because a collector that cannot supply them has not collected enough. The document
is refused rather than back-filled.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from aqelyn.findings.models import Automation, Finding, Remediation

POSTURE_DOCUMENT = "posture.json"
POSTURE_SOURCE_ENGINE = "posture_collector"
POSTURE_FINDING_TYPE = "posture.observation"

_SEVERITIES = ("critical", "high", "medium", "low", "info")
_DIFFICULTIES = ("low", "medium", "high")

_REQUIRED_NARRATIVE = (
    "what_happened",
    "why_it_matters",
    "how_determined",
    "risk_of_inaction",
)


class PostureDocumentError(ValueError):
    """The posture document cannot be trusted, so it is refused rather than repaired."""


def _text(container: Mapping[str, Any], key: str, *, where: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PostureDocumentError(f"{where} {key} must be a non-empty string")
    return value.strip()


def validate_posture_shape(document: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """Return the observation list, or refuse the document with a located reason."""

    observations = document.get("observations")
    if not isinstance(observations, list):
        raise PostureDocumentError("posture.json observations must be a list")
    if not observations:
        raise PostureDocumentError("posture.json observations must not be empty")

    seen_ids: set[str] = set()
    for index, observation in enumerate(observations):
        where = f"posture.json observation {index}"
        if not isinstance(observation, Mapping):
            raise PostureDocumentError(f"{where} must be an object")

        observation_id = _text(observation, "observation_id", where=where)
        if observation_id in seen_ids:
            # Two observations sharing an id would collapse to one finding on the
            # store's (tenant, type, dedup_key) uniqueness and the loss would be silent.
            raise PostureDocumentError(f"{where} repeats observation_id {observation_id!r}")
        seen_ids.add(observation_id)

        for key in _REQUIRED_NARRATIVE:
            _text(observation, key, where=where)

        severity = observation.get("severity")
        if severity not in _SEVERITIES:
            raise PostureDocumentError(f"{where} severity must be one of {list(_SEVERITIES)}")

        score = observation.get("severity_score")
        if not isinstance(score, int | float) or isinstance(score, bool):
            raise PostureDocumentError(f"{where} severity_score must be a number")
        if not 0.0 <= float(score) <= 100.0:
            raise PostureDocumentError(f"{where} severity_score must be between 0 and 100")

        subject = observation.get("subject")
        if not isinstance(subject, Mapping):
            raise PostureDocumentError(f"{where} subject must be an object")
        _text(subject, "ref", where=f"{where} subject")

        remediation = observation.get("remediation")
        if not isinstance(remediation, Mapping):
            raise PostureDocumentError(f"{where} remediation must be an object")
        _text(remediation, "summary", where=f"{where} remediation")
        _text(remediation, "expected_outcome", where=f"{where} remediation")
        if remediation.get("difficulty") not in _DIFFICULTIES:
            raise PostureDocumentError(
                f"{where} remediation difficulty must be one of {list(_DIFFICULTIES)}"
            )

    return observations


def posture_dedup_key(observation: Mapping[str, Any]) -> str:
    """Stable across runs, distinct per observation.

    The finding store dedupes on (tenant_id, finding_type, dedup_key). Deriving the key from
    the subject and the check keeps a re-run of the same collection idempotent, while keeping
    two different observations of the same subject apart.
    """

    subject_ref = str((observation.get("subject") or {}).get("ref", ""))
    check = str(observation.get("check", ""))
    observation_id = str(observation.get("observation_id", ""))
    material = "\0".join((subject_ref, check, observation_id))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def observation_to_finding(
    observation: Mapping[str, Any],
    *,
    finding_id: str,
    evidence_id: str,
    observed_at: datetime,
) -> Finding:
    """Build a Finding that carries its own derivation.

    `severity_score` is taken from the observation and never recomputed downstream:
    ECR-0063 keeps it fixed under escalation so the keyset cursor stays stable.
    """

    remediation = observation.get("remediation") or {}
    subject_ref = str((observation.get("subject") or {}).get("ref", ""))
    check = str(observation.get("check", "observation"))

    return Finding(
        id=finding_id,
        finding_type=POSTURE_FINDING_TYPE,
        schema_version=1,
        dedup_key=posture_dedup_key(observation),
        title=f"{check} on {subject_ref}",
        severity=str(observation["severity"]),
        severity_score=float(observation["severity_score"]),
        what_happened=str(observation["what_happened"]),
        why_it_matters=str(observation["why_it_matters"]),
        how_determined=str(observation["how_determined"]),
        risk_of_inaction=str(observation["risk_of_inaction"]),
        evidence_ids=[evidence_id],
        remediation=Remediation(
            summary=str(remediation["summary"]),
            difficulty=str(remediation["difficulty"]),
            expected_outcome=str(remediation["expected_outcome"]),
        ),
        automation=Automation(eligibility="not_eligible"),
        source_engine=POSTURE_SOURCE_ENGINE,
        first_detected_at=observed_at,
        last_detected_at=observed_at,
    )
