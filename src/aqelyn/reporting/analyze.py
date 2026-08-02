"""Drive handed-in collection documents through shipped owners for P-001."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import AQError
from aqelyn.events import Subject
from aqelyn.evidence.models import EvidenceRecord
from aqelyn.findings import Finding
from aqelyn.kernel import AQELYNConfig, Runtime, create_inmemory_runtime
from aqelyn.threat.parse import KevExploitationProvider, parse_kev
from aqelyn.vuln.models import VulnerabilityRecord, VulnPriority
from aqelyn.vuln.parse import RejectedMatch, parse_grype

_VULNERABILITY_DOCUMENT = "vulns.json"
_KEV_DOCUMENT = "kev.json"
_COLLECTION_MANIFEST = "collection-manifest.json"
_REPORT_SOURCE_ID = "src_019fa1f100007a119000000000000001"
_SCANNER_CONFIDENCE = 0.9


class ReportInputError(RuntimeError):
    """A handed-in collection cannot be represented honestly."""


class _VulnerabilityPublisher(Protocol):
    async def ingest(
        self,
        *,
        records: Sequence[VulnerabilityRecord],
        tenant_id: str | None,
    ) -> list[VulnerabilityRecord]: ...

    async def prioritize(
        self,
        vulnerability_id: str,
        *,
        tenant_id: str | None,
    ) -> VulnPriority: ...

    async def raise_vulnerability(self, priority: VulnPriority, *, by: ActorRef) -> Finding: ...


class _FindingReader(Protocol):
    async def query(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Finding], str | None]: ...


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

    runtime = create_inmemory_runtime(AQELYNConfig(tenant_mode="local"))
    _apply_reporting_vulnerability_profile(runtime, threat_provider=threat_provider)
    evidence_store = runtime.evidence_store
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

    vulnerability_service = cast(
        _VulnerabilityPublisher,
        runtime.kernel.get_service("vuln_engine"),
    )
    finding_reader = cast(
        _FindingReader,
        runtime.kernel.get_service("finding_read"),
    )
    stored = await vulnerability_service.ingest(records=evidenced_records, tenant_id=None)
    unique_records = {record.id: record for record in stored}

    by = ActorRef(actor_type="system", actor_id="aqelyn-report")
    generated: dict[str, tuple[VulnPriority, VulnerabilityRecord]] = {}
    for vulnerability in unique_records.values():
        priority = await vulnerability_service.prioritize(vulnerability.id, tenant_id=None)
        finding = await vulnerability_service.raise_vulnerability(priority, by=by)
        generated[finding.id] = priority, vulnerability

    read_findings = await _read_all_findings(
        finding_reader,
        expected_count=len(generated),
    )
    if set(generated) != {finding.id for finding in read_findings}:
        raise ReportInputError("registered finding read did not return the findings just published")
    findings = [
        ReportFinding(
            finding=finding,
            priority=generated[finding.id][0],
            vulnerability=generated[finding.id][1],
        )
        for finding in read_findings
    ]
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


def _apply_reporting_vulnerability_profile(
    runtime: Runtime,
    *,
    threat_provider: KevExploitationProvider | None,
) -> None:
    """Preserve P-001's provider semantics while moving ownership into Runtime."""

    engine = runtime.vuln_engine
    engine.threat_provider = threat_provider
    engine.exposure_provider = None
    engine.mission_provider = None
    engine.baseline_provider = None
    engine.coverage_provider = None
    engine.trend_provider = None


async def _read_all_findings(
    reader: _FindingReader,
    *,
    expected_count: int,
) -> list[Finding]:
    findings, next_cursor = await reader.query(
        tenant_id=None,
        limit=max(expected_count, 1),
        cursor=None,
    )
    if next_cursor is not None or len(findings) != expected_count:
        raise ReportInputError("registered finding read did not return the generated cardinality")
    return findings


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
