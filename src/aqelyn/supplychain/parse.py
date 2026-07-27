"""Pure parsers for handed-in SPDX and CycloneDX documents (EA-0030 Q2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aqelyn.conventions.errors import SBOMParseError
from aqelyn.supplychain.models import (
    ComponentIdentity,
    ComponentIdentityKind,
    DependencyRelationship,
    DependencyScope,
    SBOMDocument,
    SoftwareComponent,
)


@dataclass(frozen=True)
class ParsedSBOM:
    components: tuple[SoftwareComponent, ...]
    relationships: tuple[DependencyRelationship, ...]
    # ECR-0064 Gap 3: coverage travels with the result, so a consumer can see what the
    # document held versus what was ingested without re-deriving it -- the way
    # `inventory()` carries `degraded`. Fields rather than a widened return: `X ->
    # tuple[X, int]` keeps `len()`, `if`, `for`, `[0]` and `in` legal while changing
    # their meaning, invisibly to `mypy --strict` (rule 23).
    total_components: int = 0
    skipped_non_package: int = 0
    """Components whose `type` is not package-like (e.g. CycloneDX `file` entries).

    **Expected, not a coverage gap** -- these were never in scope for package
    analysis, so this count is provenance for auditing the ingest and SHALL NOT feed
    EA-0024 coverage, which would inflate a gap that does not exist."""
    skipped_malformed: int = 0
    """Package-like components missing both supported coordinates -- **a genuine
    signal, and the document is malformed.**

    In practice this is always `0` on a successfully parsed document: EA-0030
    *quarantines* a partial SBOM rather than ingesting it partially, so the parser
    refuses instead of skipping. The field exists so the two skip reasons stay
    distinct rather than collapsing into one total, and so a future caller that
    chooses tolerance has somewhere honest to record it. **Refusal is the strongest
    form of acting on the signal** -- stronger than any count."""


PACKAGE_COMPONENT_TYPES: frozenset[str] = frozenset(
    ("library", "application", "framework", "container", "firmware", "device", "platform")
)
"""CycloneDX component types that denote a package.

`file`, `operating-system` and `data` legitimately carry no `purl`; requiring one
universally was a misreading of the format, not strictness (ECR-0064 Gap 3). Real
`syft` output for `postgres:16` is 146 `library`, 1 `operating-system` and 7 220
`file` components.
"""


@dataclass(frozen=True)
class _ComponentInput:
    ref: str
    identity_kind: ComponentIdentityKind
    purl: str | None
    cpe: str | None
    name: str
    version: str
    component_type: str
    locations: list[str]
    licenses: list[str]
    supplier: str | None
    hashes: dict[str, str]
    scope: DependencyScope

    @property
    def identity(self) -> ComponentIdentity:
        value = self.purl if self.identity_kind == "purl" else self.cpe
        if value is None:
            raise SBOMParseError("component identity is incomplete")
        return ComponentIdentity(kind=self.identity_kind, value=value)


def parse_sbom(doc: SBOMDocument, *, tenant_id: str | None) -> ParsedSBOM:
    """Normalize a complete handed-in document without performing any I/O."""

    if doc.evidence_id is None:
        raise SBOMParseError("SBOM is partial: evidence_id is required")
    if doc.format == "spdx":
        return _parse_spdx(doc, tenant_id=tenant_id)
    if doc.format == "cyclonedx":
        return _parse_cyclonedx(doc, tenant_id=tenant_id)
    raise SBOMParseError(f"unsupported SBOM format: {doc.format!r}")


def _parse_cyclonedx(doc: SBOMDocument, *, tenant_id: str | None) -> ParsedSBOM:
    raw = doc.raw
    if raw.get("bomFormat") != "CycloneDX":
        raise SBOMParseError("CycloneDX document is missing bomFormat=CycloneDX")
    raw_components = _mapping_list(raw.get("components"), field="CycloneDX components")
    if not raw_components:
        raise SBOMParseError("CycloneDX document contains no components")

    inputs: list[_ComponentInput] = []
    skipped_non_package = 0
    skipped_malformed = 0
    for item in raw_components:
        component_type = str(item.get("type", "")).strip().lower()
        if component_type and component_type not in PACKAGE_COMPONENT_TYPES:
            skipped_non_package += 1
            continue
        inputs.append(_cyclonedx_component(item))
    if not inputs:
        raise SBOMParseError("CycloneDX document contains no package components")
    by_ref = _unique_refs(inputs)
    dependencies = _mapping_list(raw.get("dependencies", []), field="CycloneDX dependencies")
    root_ref = _cyclonedx_root_ref(raw)
    direct_refs: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for dependency in dependencies:
        source_ref = _text(dependency.get("ref"), field="CycloneDX dependency ref")
        targets = _text_list(
            dependency.get("dependsOn", []), field="CycloneDX dependency dependsOn"
        )
        if source_ref != root_ref and source_ref not in by_ref:
            raise SBOMParseError(f"CycloneDX dependency references unknown source {source_ref!r}")
        for target_ref in targets:
            if target_ref not in by_ref:
                raise SBOMParseError(
                    f"CycloneDX dependency references unknown target {target_ref!r}"
                )
            if source_ref == root_ref:
                direct_refs.add(target_ref)
                if source_ref in by_ref and source_ref != target_ref:
                    pairs.append((source_ref, target_ref))
            elif source_ref != target_ref:
                pairs.append((source_ref, target_ref))

    if root_ref is not None and root_ref in by_ref:
        direct_refs.add(root_ref)
    if not direct_refs:
        direct_refs = _roots(by_ref, pairs)
    return _build_result(
        doc,
        tenant_id=tenant_id,
        inputs=inputs,
        pairs=pairs,
        direct_refs=direct_refs,
        total_components=len(raw_components),
        skipped_non_package=skipped_non_package,
        skipped_malformed=skipped_malformed,
    )


def _parse_spdx(doc: SBOMDocument, *, tenant_id: str | None) -> ParsedSBOM:
    raw = doc.raw
    version = raw.get("spdxVersion")
    if not isinstance(version, str) or not version.startswith("SPDX-"):
        raise SBOMParseError("SPDX document is missing a valid spdxVersion")
    raw_packages = _mapping_list(raw.get("packages"), field="SPDX packages")
    if not raw_packages:
        raise SBOMParseError("SPDX document contains no packages")

    inputs = [_spdx_component(item) for item in raw_packages]
    by_ref = _unique_refs(inputs)
    relationships = _mapping_list(raw.get("relationships", []), field="SPDX relationships")
    described: set[str] = set()
    raw_pairs: list[tuple[str, str]] = []
    for relationship in relationships:
        relation = _text(
            relationship.get("relationshipType"), field="SPDX relationshipType"
        ).upper()
        source_ref = _text(relationship.get("spdxElementId"), field="SPDX relationship source")
        target_ref = _text(relationship.get("relatedSpdxElement"), field="SPDX relationship target")
        if relation == "DESCRIBES" and source_ref == "SPDXRef-DOCUMENT":
            if target_ref not in by_ref:
                raise SBOMParseError(f"SPDX DESCRIBES references unknown package {target_ref!r}")
            described.add(target_ref)
            continue
        if relation == "DEPENDENCY_OF":
            source_ref, target_ref = target_ref, source_ref
            relation = "DEPENDS_ON"
        if relation != "DEPENDS_ON":
            continue
        if source_ref not in by_ref or target_ref not in by_ref:
            raise SBOMParseError("SPDX dependency relationship references an unknown package")
        if source_ref != target_ref:
            raw_pairs.append((source_ref, target_ref))

    direct_refs = set(described)
    direct_refs.update(target for source, target in raw_pairs if source in described)
    if not direct_refs:
        direct_refs = _roots(by_ref, raw_pairs)
    return _build_result(
        doc,
        tenant_id=tenant_id,
        inputs=inputs,
        pairs=raw_pairs,
        direct_refs=direct_refs,
    )


def _build_result(
    doc: SBOMDocument,
    *,
    tenant_id: str | None,
    inputs: Sequence[_ComponentInput],
    pairs: Sequence[tuple[str, str]],
    direct_refs: set[str],
    total_components: int = 0,
    skipped_non_package: int = 0,
    skipped_malformed: int = 0,
) -> ParsedSBOM:
    if doc.evidence_id is None:
        raise SBOMParseError("SBOM is partial: evidence_id is required")
    by_ref = {item.ref: item for item in inputs}
    components_by_identity: dict[tuple[str, str], SoftwareComponent] = {}
    for item in inputs:
        component = SoftwareComponent(
            tenant_id=tenant_id,
            identity_kind=item.identity_kind,
            purl=item.purl,
            cpe=item.cpe,
            name=item.name,
            version=item.version,
            component_type=item.component_type,
            locations=item.locations,
            licenses=item.licenses,
            supplier=item.supplier,
            hashes=item.hashes,
            direct=item.ref in direct_refs,
            source_id=doc.source_id,
            observed_at=doc.observed_at,
            evidence_id=doc.evidence_id,
        )
        identity_key = (component.identity.kind, component.identity.value)
        existing = components_by_identity.get(identity_key)
        if existing is not None and _component_values(existing) != _component_values(component):
            raise SBOMParseError(
                f"SBOM contains conflicting duplicate component {component.identity.value!r}"
            )
        if existing is None:
            components_by_identity[identity_key] = component
        else:
            components_by_identity[identity_key] = existing.model_copy(
                update={
                    "direct": existing.direct or component.direct,
                    "locations": sorted({*existing.locations, *component.locations}),
                },
                deep=True,
            )

    relationships: dict[tuple[str, str, str, str, str], DependencyRelationship] = {}
    for source_ref, target_ref in pairs:
        source = by_ref[source_ref]
        target = by_ref[target_ref]
        if source.identity == target.identity:
            continue
        key = (
            source.identity.kind,
            source.identity.value,
            target.identity.kind,
            target.identity.value,
            target.scope,
        )
        relationships[key] = DependencyRelationship(
            from_identity=source.identity,
            to_identity=target.identity,
            scope=target.scope,
        )
    return ParsedSBOM(
        components=tuple(components_by_identity[key] for key in sorted(components_by_identity)),
        relationships=tuple(relationships[key] for key in sorted(relationships)),
        total_components=total_components or len(inputs),
        skipped_non_package=skipped_non_package,
        skipped_malformed=skipped_malformed,
    )


def _cyclonedx_component(item: Mapping[str, Any]) -> _ComponentInput:
    ref = _text(item.get("bom-ref"), field="CycloneDX bom-ref")
    purl = _purl(item.get("purl"), field="CycloneDX purl") if "purl" in item else None
    cpe = _cpe(item.get("cpe"), field="CycloneDX cpe") if "cpe" in item else None
    if purl is None and cpe is None:
        raise SBOMParseError("CycloneDX package is partial: a purl or cpe coordinate is required")
    licenses: list[str] = []
    for entry in _sequence(item.get("licenses", []), field="CycloneDX licenses"):
        if isinstance(entry, str):
            licenses.append(_text(entry, field="CycloneDX license"))
            continue
        if not isinstance(entry, Mapping):
            raise SBOMParseError("CycloneDX license must be a string or object")
        if "expression" in entry:
            licenses.append(_text(entry.get("expression"), field="CycloneDX license expression"))
            continue
        license_data = entry.get("license")
        if not isinstance(license_data, Mapping):
            raise SBOMParseError("CycloneDX license object is partial")
        licenses.append(
            _text(
                license_data.get("id", license_data.get("name")),
                field="CycloneDX license id",
            )
        )
    supplier_value = item.get("supplier")
    supplier = None
    if isinstance(supplier_value, Mapping):
        supplier = _optional_text(supplier_value.get("name"), field="CycloneDX supplier")
    elif supplier_value is not None:
        supplier = _text(supplier_value, field="CycloneDX supplier")
    hashes = {
        _text(value.get("alg"), field="CycloneDX hash algorithm").lower(): _text(
            value.get("content"), field="CycloneDX hash content"
        )
        for value in _mapping_list(item.get("hashes", []), field="CycloneDX hashes")
    }
    return _ComponentInput(
        ref=ref,
        identity_kind="purl" if purl is not None else "cpe",
        purl=purl,
        cpe=cpe,
        name=_text(item.get("name"), field="CycloneDX component name"),
        version=_text(item.get("version"), field="CycloneDX component version"),
        component_type=_text(item.get("type"), field="CycloneDX component type"),
        locations=_cyclonedx_locations(item),
        licenses=sorted(set(licenses)),
        supplier=supplier,
        hashes=hashes,
        scope=_dependency_scope(item.get("scope")),
    )


def _spdx_component(item: Mapping[str, Any]) -> _ComponentInput:
    licenses = []
    for key in ("licenseConcluded", "licenseDeclared"):
        value = item.get(key)
        if isinstance(value, str) and value.strip() and value not in {"NOASSERTION", "NONE"}:
            licenses.append(value)
    purl: str | None = None
    cpe: str | None = None
    for ref in _mapping_list(item.get("externalRefs", []), field="SPDX externalRefs"):
        kind = _text(ref.get("referenceType"), field="SPDX referenceType").lower()
        if kind == "purl" or kind.endswith("package-manager"):
            purl = _purl(ref.get("referenceLocator"), field="SPDX purl")
        elif "cpe" in kind:
            cpe = _cpe(ref.get("referenceLocator"), field="SPDX cpe")
    if purl is None and cpe is None:
        raise SBOMParseError("SPDX package is partial: purl or cpe externalRef is required")
    hashes = {
        _text(value.get("algorithm"), field="SPDX checksum algorithm").lower(): _text(
            value.get("checksumValue"), field="SPDX checksum value"
        )
        for value in _mapping_list(item.get("checksums", []), field="SPDX checksums")
    }
    supplier = _optional_text(item.get("supplier"), field="SPDX supplier")
    if supplier is not None and ":" in supplier:
        supplier = supplier.split(":", 1)[1].strip()
    purpose = _optional_text(item.get("primaryPackagePurpose"), field="SPDX package purpose")
    return _ComponentInput(
        ref=_text(item.get("SPDXID"), field="SPDX package id"),
        identity_kind="purl" if purl is not None else "cpe",
        purl=purl,
        cpe=cpe,
        name=_text(item.get("name"), field="SPDX package name"),
        version=_text(item.get("versionInfo"), field="SPDX package version"),
        component_type=(purpose or "library").lower(),
        locations=[],
        licenses=sorted(set(licenses)),
        supplier=supplier,
        hashes=hashes,
        scope="runtime",
    )


def _cyclonedx_root_ref(raw: Mapping[str, Any]) -> str | None:
    metadata = raw.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    component = metadata.get("component")
    if not isinstance(component, Mapping):
        return None
    return _optional_text(component.get("bom-ref"), field="CycloneDX root bom-ref")


def _unique_refs(inputs: Sequence[_ComponentInput]) -> dict[str, _ComponentInput]:
    result: dict[str, _ComponentInput] = {}
    for item in inputs:
        existing = result.get(item.ref)
        if existing is not None and existing != item:
            raise SBOMParseError(f"SBOM reuses component reference {item.ref!r}")
        result[item.ref] = item
    return result


def _roots(by_ref: Mapping[str, _ComponentInput], pairs: Sequence[tuple[str, str]]) -> set[str]:
    incoming = {target for _, target in pairs}
    return set(by_ref) - incoming


def _dependency_scope(value: object) -> DependencyScope:
    if value is None or value == "required":
        return "runtime"
    if value == "optional":
        return "optional"
    if value in {"excluded", "development", "dev"}:
        return "dev"
    raise SBOMParseError(f"unsupported dependency scope: {value!r}")


def _component_values(component: SoftwareComponent) -> dict[str, Any]:
    return {
        "identity_kind": component.identity_kind,
        "purl": component.purl,
        "cpe": component.cpe,
        "name": component.name,
        "version": component.version,
        "component_type": component.component_type,
        "licenses": component.licenses,
        "supplier": component.supplier,
        "hashes": component.hashes,
    }


def _mapping_list(value: object, *, field: str) -> list[Mapping[str, Any]]:
    sequence = _sequence(value, field=field)
    if not all(isinstance(item, Mapping) for item in sequence):
        raise SBOMParseError(f"{field} must contain objects")
    return [item for item in sequence if isinstance(item, Mapping)]


def _sequence(value: object, *, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise SBOMParseError(f"{field} must be an array")
    return value


def _text_list(value: object, *, field: str) -> list[str]:
    return [_text(item, field=field) for item in _sequence(value, field=field)]


def _purl(value: object, *, field: str) -> str:
    selected = _text(value, field=field)
    if not selected.startswith("pkg:"):
        raise SBOMParseError(f"{field} must be a package URL")
    return selected


def _cpe(value: object, *, field: str) -> str:
    selected = _text(value, field=field)
    if not selected.startswith("cpe:"):
        raise SBOMParseError(f"{field} must be a CPE coordinate")
    return selected


def _cyclonedx_locations(item: Mapping[str, Any]) -> list[str]:
    locations: set[str] = set()
    evidence = item.get("evidence")
    if isinstance(evidence, Mapping):
        for occurrence in _mapping_list(
            evidence.get("occurrences", []),
            field="CycloneDX evidence occurrences",
        ):
            locations.add(
                _text(
                    occurrence.get("location"),
                    field="CycloneDX occurrence location",
                )
            )
    for prop in _mapping_list(item.get("properties", []), field="CycloneDX properties"):
        name = _text(prop.get("name"), field="CycloneDX property name")
        if name.startswith("syft:location:") and name.endswith(":path"):
            locations.add(_text(prop.get("value"), field="CycloneDX location property"))
    return sorted(locations)


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field=field)


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SBOMParseError(f"{field} must not be empty")
    return value.strip()
