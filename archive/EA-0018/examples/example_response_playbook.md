# Example Response Playbook Records

## 54.1 Example Response Action

```yaml
response_id: RESP-0001
playbook: PB-CONTAIN-HOST-v1
status: in_progress
owner: incident_commander_01
timestamp: 2026-07-07T12:00:00Z
incident: INC-1001
```

## 54.2 Example Playbook

```yaml
playbook_id: PB-CONTAIN-HOST
version: v1
workflow:
  - validate_incident
  - request_approval
  - isolate_host
  - collect_evidence
  - notify_mission_owner
approvals:
  - incident_commander
  - mission_owner
```

## 54.3 Example Approval

```yaml
approval_id: APR-2001
approver: mission_owner_01
decision: approved
timestamp: 2026-07-07T12:05:00Z
scope: isolate_asset_ASSET-0002
```

## 54.4 Example Response Event

```json
{
  "event_type": "response.started",
  "response_id": "RESP-0001",
  "playbook_id": "PB-CONTAIN-HOST",
  "incident_id": "INC-1001",
  "source_engine": "aqelyn_automated_response_orchestration_engine"
}
```
