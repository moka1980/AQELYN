"""T7 - the C-001 walking skeleton (EA-0001 §9).

kernel start -> object created -> object.created event -> subscriber records
evidence -> finding raised citing that evidence + object -> healthy -> stop.
Runs on in-memory infra with no external services.
"""

from datetime import UTC, datetime

from aqelyn.conventions import ActorRef, new_id
from aqelyn.events import Event
from aqelyn.evidence import EvidenceRecord
from aqelyn.findings import Automation, Finding, Remediation
from aqelyn.kernel import create_inmemory_runtime
from aqelyn.objects import AQObject, SourceRef

SYS = ActorRef(actor_type="system", actor_id="skeleton")


async def test_c001_walking_skeleton() -> None:
    rt = create_inmemory_runtime()
    await rt.kernel.start()

    raised: list[Finding] = []

    async def on_object_created(event: Event) -> None:
        oid = event.subject.object_ids[0]
        now = datetime.now(UTC)
        rec = await rt.evidence_store.add(
            EvidenceRecord(
                id="",
                evidence_type="config.snapshot",
                schema_version=1,
                subject=event.subject,
                collected_at=now,
                recorded_at=now,
                collector=SYS,
                source_id=new_id("src"),
                method="skeleton",
                content={"observed": True},
                content_hash="",
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )
        finding = await rt.finding_store.raise_finding(
            Finding(
                id="",
                finding_type="aqelyn.finding.demo.exists",
                schema_version=1,
                dedup_key=oid,
                title="Demo finding for the walking skeleton",
                severity="low",
                severity_score=10.0,
                what_happened="A new object was observed.",
                why_it_matters="Confirms the end-to-end path works.",
                how_determined="Reacted to aqelyn.object.created and recorded evidence.",
                risk_of_inaction="None; this is a foundation self-test.",
                evidence_ids=[rec.id],
                affected_object_ids=[oid],
                remediation=Remediation(
                    summary="No action needed.",
                    difficulty="trivial",
                    expected_outcome="Skeleton proven end-to-end.",
                ),
                automation=Automation(eligibility="none"),
                source_engine="skeleton",
                first_detected_at=now,
                last_detected_at=now,
            )
        )
        raised.append(finding)

    await rt.event_bus.subscribe("aqelyn.object.created", on_object_created)

    now = datetime.now(UTC)
    await rt.object_store.upsert(
        AQObject(
            id="",
            object_type="generic",
            schema_version=1,
            display_name="skeleton-object",
            sources=[SourceRef(source_id=new_id("src"), observed_at=now, method="skeleton")],
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
            created_by=SYS,
            updated_by=SYS,
        )
    )

    # A finding was raised, citing real evidence that verifies.
    assert len(raised) == 1
    finding = raised[0]
    assert finding.evidence_ids
    assert (await rt.evidence_store.verify(finding.evidence_ids[0])).ok

    state = await rt.kernel.health()
    assert state.phase in ("running", "degraded")
    assert state.services["_kernel"].ready is True

    await rt.kernel.stop()
    assert rt.kernel.phase == "stopped"
    assert any(e.event_type == "aqelyn.kernel.runtime_stopped" for e in rt.event_bus.log)
