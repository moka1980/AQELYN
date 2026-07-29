"""Drive handed-in collection documents through shipped owners for P-001."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import AQError
from aqelyn.events import Subject
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.evidence.models import EvidenceRecord
from aqelyn.findings import Finding
from aqelyn.findings.memory import InMemoryFindingStore
from aqelyn.threat.parse import KevExploitationProvider, parse_kev
from aqelyn.vuln import VulnerabilityIntelligenceEngine
from aqelyn.vuln.memory import InMemoryVulnerabilityStore
from aqelyn.vuln.models import VulnerabilityRecord, VulnPriority
from aqelyn.vuln.parse import RejectedMatch, parse_grype

_VULNERABILITY_DOCUMENT = "vulns.json"
_KEV_DOCUMENT = "kev.json"
_COLLECTION_MANIFEST = "collection-manifest.json"
_REPORT_SOURCE_ID = "src_019fa1f100007a119000000000000001"
_SCANNER_CONFIDENCE = 0.9


class ReportInputError(RuntimeError):
    """A handed-in collection cannot be represented honestly."""


@dataclass(frozen=True)
class ReportSource:
    name: str
    sha256: str


@dataclass(frozen=True)
class ReportFinding:
    finding: Finding
    priority: VulnPriority
    vulnerability: VulnerabilityRecord

    @property
    def unknown_count(self) -> int:
        return sum(
            1
            for factor in self.priority.factors.values()
            if isinstance(factor, Mapping) and factor.get("status") == "unknown"
        )

    @property
    def has_known_exploitation(self) -> bool:
        factor = self.priority.factors.get("threat")
        value = factor.get("value") if isinstance(factor, Mapping) else None
        return (
            isinstance(factor, Mapping)
            and factor.get("status") == "known"
            and isinstance(value, int | float)
            and not isinstance(value, bool)
            and float(value) > 0.0
        )


@dataclass(frozen=True)
class CollectionAnalysis:
    observed_at: datetime
    generated_at: datetime
    input_fingerprint: str
    sources: tuple[ReportSource, ...]
    scanner_matches: int
    represented_records: int
    rejected_matches: tuple[RejectedMatch, ...]
    findings: tuple[ReportFinding, ...]

    @property
    def unknown_factor_count(self) -> int:
        return sum(item.unknown_count for item in self.findings)


def load_collection_documents(
    directory: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None, datetime, tuple[ReportSource, ...], str]:
    """Load only the documents the report consumes, without collecting anything."""

    selected = directory.resolve()
    if not selected.is_dir():
        raise ReportInputError(f"collection directory does not exist: {selected}")

    vulnerability_path = selected / _VULNERABILITY_DOCUMENT
    vulnerability_document, vulnerability_digest = _read_json_object(
        vulnerability_path,
        label="vulnerability document",
    )

    kev_path = selected / _KEV_DOCUMENT
    kev_loaded = _read_json_object(kev_path, label="KEV document") if kev_path.is_file() else None
    kev_document = kev_loaded[0] if kev_loaded is not None else None

    manifest_path = selected / _COLLECTION_MANIFEST
    manifest_loaded = (
        _read_json_object(manifest_path, label="collection manifest")
        if manifest_path.is_file()
        else None
    )
    manifest = manifest_loaded[0] if manifest_loaded is not None else None
    observed_at = _observation_time(vulnerability_document, manifest)

    source_items = [
        ReportSource(name=vulnerability_path.name, sha256=vulnerability_digest),
    ]
    if kev_loaded is not None:
        source_items.append(ReportSource(name=kev_path.name, sha256=kev_loaded[1]))
    if manifest_loaded is not None:
        source_items.append(ReportSource(name=manifest_path.name, sha256=manifest_loaded[1]))
    sources = tuple(sorted(source_items, key=lambda item: item.name))
    fingerprint = _input_fingerprint(selected, sources)
    return vulnerability_document, kev_document, observed_at, sources, fingerprint


async def analyze_collection(directory: Path) -> CollectionAnalysis:
    """Create findings through the real evidence, vulnerability, and finding owners."""

    (
        vulnerability_document,
        kev_document,
        observed_at,
        sources,
        fingerprint,
    ) = load_collection_documents(directory)
    _validate_grype_shape(vulnerability_document)
    try:
        parsed = parse_grype(
            vulnerability_document,
            scanner="grype",
            confidence=_SCANNER_CONFIDENCE,
            observed_at=observed_at,
        )
        threat_provider = (
            KevExploitationProvider(catalog=parse_kev(kev_document))
            if kev_document is not None
            else None
        )
    except AQError as exc:
        raise ReportInputError(f"collection document was refused: {exc}") from exc

    evidence_store = InMemoryEvidenceStore(mode="local")
    subject_id = new_id("obj")
    vulnerability_source = next(
        source for source in sources if source.name == _VULNERABILITY_DOCUMENT
    )
    evidence = await evidence_store.add(
        EvidenceRecord(
            id="",
            evidence_type="vulnerability.scan_document",
            schema_version=1,
            subject=Subject(object_ids=[subject_id]),
            collected_at=observed_at,
            recorded_at=observed_at,
            collector=ActorRef(actor_type="system", actor_id="aqelyn-report"),
            source_id=_REPORT_SOURCE_ID,
            method="handed-in file",
            content={
                "document": vulnerability_source.name,
                "sha256": vulnerability_source.sha256,
            },
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )
    evidenced_records = [
        record.model_copy(
            update={
                "basis": [
                    basis.model_copy(update={"evidence_id": evidence.id}, deep=True)
                    for basis in record.basis
                ]
            },
            deep=True,
        )
        for record in parsed.records
    ]

    vulnerability_store = InMemoryVulnerabilityStore(mode="local")
    finding_store = InMemoryFindingStore(
        mode="local",
        evidence_exists=evidence_store.exists,
    )
    engine = VulnerabilityIntelligenceEngine(
        vulnerability_store,
        threat_provider=threat_provider,
        finding_store=finding_store,
    )
    stored = await engine.ingest(records=evidenced_records, tenant_id=None)
    unique_records = {record.id: record for record in stored}

    by = ActorRef(actor_type="system", actor_id="aqelyn-report")
    findings: list[ReportFinding] = []
    for vulnerability in unique_records.values():
        priority = await engine.prioritize(vulnerability.id, tenant_id=None)
        finding = await engine.raise_vulnerability(priority, by=by)
        findings.append(
            ReportFinding(
                finding=finding,
                priority=priority,
                vulnerability=vulnerability,
            )
        )
    findings.sort(
        key=lambda item: (
            not item.has_known_exploitation,
            -item.priority.score,
            item.vulnerability.cve_id,
            item.vulnerability.asset_ref.ref_id,
        )
    )

    matches = vulnerability_document.get("matches")
    scanner_matches = len(matches) if isinstance(matches, list) else 0
    return CollectionAnalysis(
        observed_at=observed_at,
        generated_at=datetime.now(UTC),
        input_fingerprint=fingerprint,
        sources=sources,
        scanner_matches=scanner_matches,
        represented_records=len(unique_records),
        rejected_matches=parsed.rejected,
        findings=tuple(findings),
    )


def _read_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise ReportInputError(f"{label} is unavailable: {path.name}")
    try:
        raw = path.read_bytes()
        decoded = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportInputError(f"{label} is not readable JSON: {path.name}") from exc
    if not isinstance(decoded, dict):
        raise ReportInputError(f"{label} must contain a JSON object: {path.name}")
    return cast(dict[str, Any], decoded), hashlib.sha256(raw).hexdigest()


def _validate_grype_shape(document: Mapping[str, Any]) -> None:
    matches = document.get("matches")
    if not isinstance(matches, list):
        raise ReportInputError("vulns.json matches must be a list")
    for index, match in enumerate(matches):
        if not isinstance(match, Mapping):
            raise ReportInputError(f"vulns.json match {index} must be an object")
        vulnerability = match.get("vulnerability", {})
        artifact = match.get("artifact", {})
        if not isinstance(vulnerability, Mapping):
            raise ReportInputError(f"vulns.json match {index} vulnerability must be an object")
        if not isinstance(artifact, Mapping):
            raise ReportInputError(f"vulns.json match {index} artifact must be an object")


def _observation_time(
    vulnerability_document: Mapping[str, Any],
    manifest: Mapping[str, Any] | None,
) -> datetime:
    descriptor = vulnerability_document.get("descriptor")
    if isinstance(descriptor, Mapping):
        timestamp = descriptor.get("timestamp")
        if isinstance(timestamp, str) and timestamp.strip():
            return _parse_timestamp(timestamp, field="vulns.json descriptor.timestamp")
    if manifest is not None:
        collected_at = manifest.get("collected_at")
        if isinstance(collected_at, str) and collected_at.strip():
            return _parse_timestamp(
                collected_at,
                field="collection-manifest.json collected_at",
            )
    raise ReportInputError(
        "no content observation time is available in vulns.json or collection-manifest.json"
    )


def _parse_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReportInputError(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReportInputError(f"{field} must include a UTC offset")
    return parsed.astimezone(UTC)


def _input_fingerprint(directory: Path, sources: tuple[ReportSource, ...]) -> str:
    digest = hashlib.sha256()
    for source in sources:
        digest.update(source.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.sha256.encode("ascii"))
        digest.update(b"\0")
    # The absolute path is intentionally excluded: moving an identical private corpus
    # does not change what the report describes.
    if not sources:
        raise ReportInputError(f"no report inputs found in {directory}")
    return digest.hexdigest()
