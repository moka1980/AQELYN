"""ECR-0102: `aqelyn collect` — a customer runs this on their own machine.

Writes a collection directory that `aqelyn <dir>` renders and
`aqelyn surface --collection <dir>` serves. That closes the loop: collect, ingest, look.

Read-only by construction. It runs `hostname`, `uname -r`, `ss -tlnH`, a firewall status
query and `apt-get -s upgrade` (simulate — changes nothing), and reads two files. It opens
no network connection and writes only inside the output directory.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aqelyn.collect.checks import observations_for
from aqelyn.collect.host import HostFacts, read_host_facts

POSTURE_SCHEMA = "aqelyn.posture.collection/v0"

_EMPTY_VULNS: dict[str, Any] = {"matches": []}


def build_documents(facts: HostFacts, *, collected_at: datetime) -> dict[str, Any]:
    """Assemble the collection documents from gathered facts. Pure."""

    subject_ref = facts.hostname or "unidentified-host"
    observations = list(observations_for(facts, subject_ref=subject_ref))
    stamp = collected_at.isoformat()

    posture = {
        # Key deliberately not "schema": GC-004's census attributes a bare
        # "schema" constant to the exempt lake.schema field, and weakening that
        # guard to suit a dict key would be the wrong trade.
        "document_schema": POSTURE_SCHEMA,
        "collected_at": stamp,
        "method": "aqelyn collect - read-only local inspection",
        "observations": observations,
    }
    manifest = {
        "collection_id": f"self-scan-{collected_at.strftime('%Y%m%d-%H%M%S')}",
        "collected_at": stamp,
        "collector": "aqelyn collect",
        "authorization": "run by the operator on their own machine",
        "host": {
            "hostname": facts.hostname,
            "os": facts.os_name,
            "kernel": facts.kernel,
        },
        "scope": {
            "included": [
                "operating system and kernel as the host reports them",
                "listening TCP sockets (ss -tlnH)",
                "host firewall state",
                "pending package updates (apt-get -s upgrade, simulate only)",
                "sshd PasswordAuthentication directive",
            ],
            "excluded": [
                "any network scanning, of this host or any other",
                "file contents, user data, credentials, browser history",
                "any write, mutation or configuration change",
                "mobile devices - a host collector cannot reach them",
            ],
        },
        "unmeasured": list(facts.unreadable),
        "results_summary": {
            "observations": len(observations),
            "facts_unreadable": len(facts.unreadable),
        },
    }
    # vulns.json is required by the collection contract. An empty match list is honest:
    # this collector does not do vulnerability matching, and says so in the manifest.
    return {
        "posture.json": posture,
        "collection-manifest.json": manifest,
        "vulns.json": {
            **_EMPTY_VULNS,
            "descriptor": {"name": "aqelyn-collect", "timestamp": stamp},
        },
    }


def write_collection(directory: Path, documents: dict[str, Any]) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, document in sorted(documents.items()):
        path = directory / name
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)
        written.append(path)
    return written


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aqelyn collect",
        description="Inspect this machine read-only and write a collection directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="directory to write posture.json, collection-manifest.json and vulns.json into",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    facts = read_host_facts()
    documents = build_documents(facts, collected_at=datetime.now(UTC))
    written = write_collection(args.output, documents)

    posture = documents["posture.json"]
    observations = posture["observations"]
    print(f"Wrote {len(written)} documents to {args.output}")
    print(f"  {len(observations)} observations, {len(facts.unreadable)} facts unreadable")
    for observation in observations:
        print(f"  {observation['severity']:>8}  {observation['what_happened']}")
    if facts.unreadable:
        # Say it out loud. A quiet collector that skipped half its checks looks identical
        # to one that ran them and found nothing.
        print(f"  not measured: {', '.join(facts.unreadable)}")
    print(f"\nNext: aqelyn surface --collection {args.output}")
    return 0
