"""S-002: the KEV parser, and the one decision that dominates the milestone.

CISA KEV is **positive-only**. Presence means known exploited; absence means *not in
the catalog of known-exploited*, which is emphatically not *not exploited*. A mapper
reading absence as a favourable `known` would assign one to essentially every record
on the strength of a source that never spoke about them.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from aqelyn.conventions.errors import ThreatConfigInvalid
from aqelyn.threat.parse import KevExploitationProvider, parse_kev

#: Two real entries, copied verbatim from the shipped CISA catalog rather than
#: invented -- the parser is checked against the format the source actually emits.
KEV_DOCUMENT: dict[str, Any] = {
    "title": "CISA Catalog of Known Exploited Vulnerabilities",
    "catalogVersion": "2026.07.24",
    "dateReleased": "2026-07-24T17:40:56.0086Z",
    "count": 2,
    "vulnerabilities": [
        {
            "cveID": "CVE-2026-16232",
            "vendorProject": "Check Point",
            "product": "SmartConsole",
            "vulnerabilityName": "Check Point SmartConsole Vulnerability",
            "dateAdded": "2026-07-24",
            "shortDescription": "...",
            "requiredAction": "Apply mitigations.",
            "dueDate": "2026-08-14",
            "knownRansomwareCampaignUse": "Unknown",
            "notes": "",
            "cwes": [],
        },
        {
            "cveID": "CVE-2021-44228",
            "vendorProject": "Apache",
            "product": "Log4j2",
            "vulnerabilityName": "Apache Log4j2 Remote Code Execution",
            "dateAdded": "2021-12-10",
            "shortDescription": "...",
            "requiredAction": "Apply updates.",
            "dueDate": "2021-12-24",
            "knownRansomwareCampaignUse": "Known",
            "notes": "",
            "cwes": [],
        },
    ],
}


class _Vulnerability:
    def __init__(self, cve_id: str) -> None:
        self.cve_id = cve_id


def _factor(cve_id: str) -> Any:
    catalog = parse_kev(KEV_DOCUMENT)
    provider = KevExploitationProvider(catalog=catalog)
    return asyncio.run(provider.exploitation_factor(_Vulnerability(cve_id)))


def test_threat_parse_kev_document() -> None:
    catalog = parse_kev(KEV_DOCUMENT)

    assert catalog.catalog_version == "2026.07.24"
    assert len(catalog.entries) == 2
    entry = catalog.lookup("CVE-2021-44228")
    assert entry is not None
    assert entry.vendor_project == "Apache"
    assert entry.known_ransomware_campaign_use is True
    # Narrow mapping: dueDate / requiredAction / notes / cwes are deliberately absent.
    assert not hasattr(entry, "due_date")


def test_threat_parse_lookup_is_case_insensitive() -> None:
    catalog = parse_kev(KEV_DOCUMENT)

    assert catalog.lookup("cve-2021-44228") is not None
    assert catalog.lookup("  CVE-2021-44228  ") is not None


def test_threat_parse_absence_is_unknown() -> None:
    """THE decision. Absence must never produce a favourable `known`.

    A test asserting only that absence yields a low *value* would pass against a
    mapper that returns `known: 0.0` -- which is the defect: a confident claim of
    "not exploited" that the source never made. The assertion is on `status`.
    """
    factor = _factor("CVE-2005-2541")

    assert factor.status == "unknown", (
        "absence produced a known factor -- KEV is positive-only and says nothing "
        "about CVEs it omits"
    )
    assert factor.unknown_cause == "source_cannot_assert"
    assert "positive-only" in factor.reason
    assert "not evidence" in factor.reason


def test_threat_parse_presence_is_known_and_cites_the_catalog() -> None:
    factor = _factor("CVE-2021-44228")

    assert factor.status == "known"
    assert factor.value == 1.0
    # Pinned: a finding citing KEV must cite WHICH KEV, or the derivation replays
    # against a moving target (ECR-0067's shape arriving through data).
    assert "2026.07.24" in factor.source
    assert "known ransomware campaign use" in factor.reason


def test_threat_parse_absent_and_present_are_distinguishable() -> None:
    """Rule 24 at specification time: the control must be able to fail.

    A suite exercising only absence passes against a mapper that returns `unknown`
    for everything; one exercising only presence passes against a mapper that returns
    `known` for everything. Both are driven, and asserted to differ.
    """
    present, absent = _factor("CVE-2021-44228"), _factor("CVE-2005-2541")

    assert present.status != absent.status
    assert present.value > absent.value


def test_threat_parse_rejects_a_catalog_without_a_version() -> None:
    """An unpinnable catalog is refused rather than cited vaguely."""
    document = {**KEV_DOCUMENT}
    del document["catalogVersion"]

    with pytest.raises(ThreatConfigInvalid, match="catalogVersion"):
        parse_kev(document)


def test_threat_parse_rejects_an_empty_catalog() -> None:
    with pytest.raises(ThreatConfigInvalid, match="no vulnerabilities"):
        parse_kev({**KEV_DOCUMENT, "vulnerabilities": []})
