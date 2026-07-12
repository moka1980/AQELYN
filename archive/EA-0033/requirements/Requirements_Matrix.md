ID,Name,Requirement,Component,Verification
REQ-FR-033-001,Identity discovery,Discover identities from supported identity providers through connector integrations.,ARC-033-001,TC-033-001
REQ-FR-033-002,Continuous synchronization,"Support scheduled, incremental and event-driven synchronization.",ARC-033-002,TC-033-002
REQ-FR-033-003,Identity normalization,Transform provider records into AQELYN Universal Object Model objects.,ARC-033-003,TC-033-003
REQ-FR-033-004,Identity inventory,Maintain normalized inventory of all discovered identities with provenance.,ARC-033-004,TC-033-004
REQ-FR-033-005,Identity classification,"Classify identities as human, service, machine, application, federated or temporary.",ARC-033-005,TC-033-005
REQ-FR-033-006,Authentication assessment,"Evaluate MFA, passwordless, FIDO2, credential age and legacy authentication.",ARC-033-006,TC-033-006
REQ-FR-033-007,Authorization assessment,"Evaluate roles, privilege grants, toxic combinations and excess access.",ARC-033-006,TC-033-007
REQ-FR-033-008,Lifecycle assessment,"Detect dormant, orphaned, expired, disabled and ownerless identities.",ARC-033-006,TC-033-008
REQ-FR-033-009,Policy evaluation,Evaluate identities against policy controls from the AQELYN Policy Engine.,ARC-033-012,TC-033-009
REQ-FR-033-010,Compliance evaluation,Map posture findings to compliance obligations and control evidence.,ARC-033-012,TC-033-010
REQ-FR-033-011,Risk scoring,Calculate deterministic Identity Security Posture Score from 0 to 100.,ARC-033-007,TC-033-011
REQ-FR-033-012,Drift detection,Detect deviations between current state and approved identity baselines.,ARC-033-008,TC-033-012
REQ-FR-033-013,Recommendation generation,Generate prioritized remediation recommendations for detected findings.,ARC-033-009,TC-033-013
REQ-FR-033-014,Event publication,Publish identity posture events to the AQELYN Event Bus.,ARC-033-014,TC-033-014
REQ-FR-033-015,Historical tracking,Maintain historical posture assessments and queryable trends.,ARC-033-015,TC-033-015
REQ-FR-033-016,Evidence association,Associate every finding with evidence stored by AQELYN Evidence Engine.,ARC-033-010,TC-033-016
REQ-FR-033-017,Knowledge graph integration,Update identity relationships in the AQELYN Knowledge Graph.,ARC-033-011,TC-033-017
REQ-FR-033-018,Trust integration,Consume Trust Scores as weighted inputs for posture evaluation.,ARC-033-013,TC-033-018
REQ-FR-033-019,Workflow integration,Initiate remediation workflows when configured.,ARC-033-009,TC-033-019
REQ-FR-033-020,Mission awareness,Prioritize posture risk using mission criticality.,ARC-033-013,TC-033-020
