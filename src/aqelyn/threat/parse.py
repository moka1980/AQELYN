"""Pure parser for the handed-in CISA KEV catalog (EA-0014, S-002).

Mirrors `supplychain/parse.py` and `vuln/parse.py`: an already-decoded document goes
in, records come out. **No I/O, no network, no subprocess** — whoever fetches the
catalog hands it in.

**The decision that dominates this module:**

> **Presence in KEV means *known exploited*. Absence means *not in the catalog of
> known-exploited* — which is emphatically NOT *not exploited*.**

CISA KEV is a **positive-only** catalog. It asserts that listed vulnerabilities are
being exploited; it makes no claim whatsoever about the ones it omits. A mapper that
reads absence as `known: not exploited` would assign a **favourable known** to
essentially every record, on the strength of a source that never spoke about them —
the empty-means-safe family (ECR-0013, ECR-0040, ECR-0064, ECR-0066) arriving through
the platform's newest input, and the only instance so far that would corrupt *every*
record rather than one.

So this module answers only what KEV can answer. `lookup()` returns an entry or
`None`, and **`None` means "the catalog does not speak to this CVE"** — never "this
CVE is not exploited". Turning that into a factor is the caller's job, and the
caller must produce `unknown`.

**The catalog is pinned.** A finding citing KEV must cite *which* KEV: the catalog is
dated and versioned, and a derivation that replays against a moving target does not
replay at all (ECR-0067's shape arriving through data rather than code).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aqelyn.conventions.errors import ThreatConfigInvalid


@dataclass(frozen=True)
class KevEntry:
    """One catalogued vulnerability. Mapped narrowly, on purpose.

    KEV carries `dueDate`, `requiredAction`, `notes`, `cwes` and more. Only what the
    exploitation factor consumes is mapped: **an unused mapped field is a future
    migration for no benefit.**
    """

    cve_id: str
    vendor_project: str
    product: str
    date_added: str
    known_ransomware_campaign_use: bool


@dataclass(frozen=True)
class KevCatalog:
    """A pinned catalog. `catalog_version` is what a citing derivation records."""

    catalog_version: str
    date_released: str
    entries: Mapping[str, KevEntry]

    def lookup(self, cve_id: str) -> KevEntry | None:
        """The entry for `cve_id`, or `None` if the catalog does not speak to it.

        **`None` is not a negative finding.** It means this CVE is absent from a
        catalog of known-exploited vulnerabilities, which says nothing about whether
        it is exploited. Callers turn `None` into `unknown`, never into a favourable
        `known`.
        """
        return self.entries.get(cve_id.strip().upper())


def parse_kev(document: Mapping[str, Any]) -> KevCatalog:
    """Map a CISA KEV catalog document to a pinned, CVE-keyed catalog."""
    catalog_version = _text(document.get("catalogVersion"), field="catalogVersion")
    date_released = _text(document.get("dateReleased"), field="dateReleased")

    raw = document.get("vulnerabilities")
    if not isinstance(raw, list) or not raw:
        raise ThreatConfigInvalid("KEV catalog contains no vulnerabilities")

    entries: dict[str, KevEntry] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise ThreatConfigInvalid("KEV vulnerability entry is not an object")
        cve_id = _text(item.get("cveID"), field="cveID").upper()
        entries[cve_id] = KevEntry(
            cve_id=cve_id,
            vendor_project=_text(item.get("vendorProject"), field="vendorProject"),
            product=_text(item.get("product"), field="product"),
            date_added=_text(item.get("dateAdded"), field="dateAdded"),
            # KEV writes "Known" / "Unknown". Anything that is not an explicit
            # "Known" is not treated as a ransomware claim -- but note this is a
            # narrowing of a positive assertion, not an inference about absence.
            known_ransomware_campaign_use=(
                str(item.get("knownRansomwareCampaignUse", "")).strip().lower() == "known"
            ),
        )

    if not entries:
        raise ThreatConfigInvalid("KEV catalog yielded no usable entries")
    return KevCatalog(
        catalog_version=catalog_version,
        date_released=date_released,
        entries=entries,
    )


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ThreatConfigInvalid(f"KEV {field} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class KevExploitationProvider:
    """EA-0014 exploitation factor sourced from a pinned KEV catalog.

    Satisfies `vuln.ThreatExploitProvider`. **KEV augments; it does not adjudicate.**

    | KEV state | factor |
    |---|---|
    | CVE **present** | `known`, high — citing the catalog version and entry |
    | CVE **absent** | **`unknown`** — the source cannot assert for this record |

    Absence produces `unknown`, never a favourable `known` of any polarity. It is
    ECR-0066's third reason category: **the provider is wired and working, the source
    simply cannot speak to this record, and there is nothing to do about it.**

    That distinction matters for the density report, which ranks by unknown count on
    the premise that unknowns are *closable*. A positive-only source is structurally
    incapable of covering a factor — nothing in threat intelligence asserts *"we
    checked, and this is not being exploited"* — so without the third category,
    `threat` would sit near the top of the roadmap forever, recommending work that
    cannot be done.
    """

    catalog: KevCatalog
    exploited_value: float = 1.0

    async def exploitation_factor(self, vulnerability: Any) -> Any:
        from aqelyn.vuln.engine import PriorityFactor

        entry = self.catalog.lookup(vulnerability.cve_id)
        if entry is None:
            return PriorityFactor(
                0.0,
                f"kev:{self.catalog.catalog_version}:absent",
                (
                    "CISA KEV does not list this CVE. KEV is a positive-only catalog of "
                    "known-exploited vulnerabilities, so absence is not evidence that the "
                    "vulnerability is unexploited -- the source cannot assert for this record."
                ),
                status="unknown",
                unknown_cause="source_cannot_assert",
            )
        ransomware = (
            " (known ransomware campaign use)" if entry.known_ransomware_campaign_use else ""
        )
        return PriorityFactor(
            self.exploited_value,
            f"kev:{self.catalog.catalog_version}:{entry.cve_id}",
            (
                f"CISA KEV lists this CVE as known-exploited, added {entry.date_added}, "
                f"affecting {entry.vendor_project} {entry.product}{ransomware}."
            ),
        )
