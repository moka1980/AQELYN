# Example Forensics Records

## 54.1 Example Evidence Artifact

```yaml
artifact_id: ART-0001
evidence_id: EVID-0001
artifact_type: memory_image
source: endpoint-001
hash:
  sha256: 7a0f...example
collected_at: 2026-07-07T12:00:00Z
```

## 54.2 Example Chain of Custody

```yaml
custody_id: COC-1001
evidence: EVID-0001
collector: forensic_analyst_01
timestamp: 2026-07-07T12:05:00Z
transfers:
  - from: forensic_analyst_01
    to: evidence_custodian_01
    timestamp: 2026-07-07T12:30:00Z
    verified: true
```

## 54.3 Example Timeline

```yaml
timeline_id: TL-2001
events:
  - timestamp: 2026-07-07T11:55:00Z
    event: suspicious_process_started
    evidence: EVID-0001
  - timestamp: 2026-07-07T12:01:00Z
    event: outbound_connection_detected
    evidence: EVID-0002
```

## 54.4 Example Forensic Event

```json
{
  "event_type": "evidence.verified",
  "evidence_id": "EVID-0001",
  "hash_algorithm": "SHA-256",
  "verification_status": "passed",
  "source_engine": "aqelyn_digital_forensics_engine"
}
```
