# Project AQELYN Project Charter v2.0
## Product Philosophy & User Experience Principles

Project: Project AQELYN
Document: Project Charter v2.0 - Product Philosophy & User Experience Principles
Status: Approved for Pre-Coding Baseline
Date: 2026-07-09
Language: English
Scope: Applies to all future Engineering Archives, implementation milestones, user interfaces, APIs, reports, dashboards, automated recommendations, AI explanations, and remediation workflows.

---

# 1. Purpose

This Charter update establishes mandatory product and user-experience principles for Project AQELYN.

Detecting security problems is not enough. The platform must make security understandable, explainable, evidence-based, and actionable for users ranging from home users to enterprise security professionals. To that end, this document defines the human-centered security model that every finding, recommendation, workflow, report, dashboard, and automated action is required to follow.

---

# 2. Mission Statement

Project AQELYN provides an intelligent Cyber Security Operating Environment that enables users of all experience levels to understand, evaluate, and improve their security posture through evidence-driven analysis, understandable explanations, and practical remediation guidance.

Clarity, trust, transparency, privacy, and usability take priority throughout the platform, without sacrificing technical depth or engineering quality.

---

# 3. Permanent Product Principle

> Every finding must be understandable by a non-expert and actionable by an expert.

This principle is mandatory and applies across the full product lifecycle. A finding is not considered complete unless it explains what was found, why it matters, how it was determined, which evidence supports it, what should be done next, and what deeper technical details are available.

---

# 4. Product Philosophy Principles

## Principle 1 - Explain Before You Recommend

A finding must clearly explain what happened, why it matters, how AQELYN reached its conclusion, and which evidence supports it. It must also describe the risks of taking no action, the remediation steps that are recommended, and the expected outcome once those steps are complete. Recommendations never appear without an accompanying explanation.

## Principle 2 - Simplicity First

Security information is presented in language appropriate to the user's experience level. Complex technical terminology is introduced only when necessary and is always accompanied by a plain-language explanation. Understanding a security risk must never require prior knowledge of cybersecurity terminology.

## Principle 3 - Evidence Before Opinion

Recommendations are never generated from assumptions alone. Each one references collected evidence, policy evaluation, engineering rules, threat intelligence, risk calculations, or deterministic analysis, and that evidence remains accessible to the user at all times.

## Principle 4 - Human-Centered Security

The objective is to help people improve security, not to overwhelm them with technical information. Interactions should reduce uncertainty and increase confidence, encouraging secure behavior through education, understandable guidance, and actionable recommendations.

## Principle 5 - Expert Depth on Demand

A simplified finding is a starting point, not a ceiling. Progressively deeper technical information remains available behind it, and the user interface supports multiple information levels without duplicating data.

### Progressive Detail Model

| Level | Name | Question it answers |
|---|---|---|
| 1 | Summary | What is the problem? |
| 2 | Explanation | Why does it matter? |
| 3 | Evidence | What data proves it? |
| 4 | Technical Detail | What exact configuration, event, object, or rule caused it? |
| 5 | Remediation | What should be done, manually or automatically? |
| 6 | Audit Trail | What changed and when? |

## Principle 6 - Transparency by Design

Users can always see what data has been collected, why it was collected, where it is processed, how long it is retained, and who can access it. Whether an analysis runs locally, is cloud-assisted, or is enterprise-managed is stated openly. Platform behavior should never come as a surprise.

## Principle 7 - Privacy First

Privacy is a fundamental design constraint, not an optional feature. The platform supports local-only operation and offline analysis where practical, user-controlled telemetry, data minimization, explicit consent, encryption by default, and clear retention policies. Only the information required to perform the requested analysis is collected.

## Principle 8 - Security Without Fear

Alarmist messaging has no place in the product. Rather than creating anxiety, the platform explains risks objectively, prioritizes findings, recommends achievable actions, and measures improvement over time.

## Principle 9 - Progressive Guidance

Recommendations are prioritized in a fixed order: critical actions first, then high-value improvements, then best practices, and finally long-term optimization. Users should always know what to do next.

## Principle 10 - Trust Through Engineering

Wherever possible, components are deterministic, evidence-driven, traceable, auditable, reproducible, and explainable. Trust is earned through engineering quality rather than marketing claims.

---

# 5. Finding Communication Standard

User-facing findings follow a single standard structure.

## Required Finding Fields

| Field | Purpose | Required |
|---|---|---|
| Title | Plain-language summary | Yes |
| Severity | Risk level | Yes |
| What Happened | Direct explanation of the issue | Yes |
| Why It Matters | Security impact | Yes |
| Evidence | Supporting data and references | Yes |
| Affected Assets | Devices, identities, domains, applications, or services | Yes |
| Recommended Action | Clear next step | Yes |
| Fix Difficulty | Expected effort | Yes |
| Automation Eligibility | Whether AQELYN can safely fix it | Yes |
| Expert Details | Technical expansion | Yes |
| Audit Trail | History and decisions | Yes |

---

# 6. Standard User Output Pattern

Findings are rendered using a consistent pattern:

```text
Problem: What AQELYN found.
Risk: Why it matters.
Evidence: What proves it.
Fix: What should be done.
Impact: What changes after the fix.
Details: Expand for technical evidence.
```

---

# 7. Example Finding

## Non-Preferred Output

```text
Weak password detected.
```

## AQELYN-Compliant Output

```text
Problem
Your NAS administrator account is using a password that does not meet the security policy.

Why it matters
Administrative accounts can control files, backups, and system settings. If this account is compromised, an attacker may gain broad access to your data.

Evidence
- Password age: 1,247 days
- Required complexity not met
- Similar credential pattern observed in breach intelligence
- MFA is not enabled for this account

Recommended action
Change the password immediately and enable multi-factor authentication.

Fix difficulty
Low

AQELYN automation
Manual approval required before any account changes are made.

Expert details
Policy: SEC-AUTH-004
Identity object: id:nas-admin-001
Evidence record: ev-identity-auth-2391
Risk score impact: -18 points
```

---

# 8. User Experience Requirements

| UX Requirement | Description |
|---|---|
| UX-001 | Every finding shall have a non-technical summary. |
| UX-002 | Every finding shall have an expert-detail expansion. |
| UX-003 | Every recommendation shall identify expected effort. |
| UX-004 | Every recommendation shall identify expected security benefit. |
| UX-005 | Every automated remediation shall require clear user consent unless pre-approved by policy. |
| UX-006 | Every finding shall be linked to evidence. |
| UX-007 | Every user-facing explanation shall avoid unnecessary fear-based language. |
| UX-008 | The platform shall support home, SMB, enterprise, and expert communication modes. |
| UX-009 | Users shall always be able to understand what data AQELYN used to reach a conclusion. |
| UX-010 | Users shall always know what to do next. |

---

# 9. Engineering Impact

These principles are mandatory architectural requirements. They apply to all Engineering Archives, implementation specifications, and coding milestones, and to every user interface, API, report, dashboard, AI-generated explanation, automated recommendation, and documentation set, including future product modules.

In practice this means that any engine producing a finding implements the Finding Communication Standard, any engine producing remediation guidance implements the Evidence Before Opinion principle, and any user-facing workflow implements both Simplicity First and Expert Depth on Demand.

---

# 10. Acceptance Criteria

This Charter update is accepted when the principles are included in the Project Charter and referenced by future Engineering Archives, the Finding Communication Standard is included in the implementation guidelines, and the UX requirements are part of the implementation readiness baseline. Future coding milestones must treat findings and recommendations as structured objects rather than plain text, and every future UI design must support progressive disclosure from simple explanation to technical evidence.

---

# 11. Implementation Guidance for Codex

When implementing Project AQELYN, Codex should treat findings as structured, typed objects. The implementation should include a canonical `Finding` model with fields for summary, explanation, evidence, recommended actions, severity, confidence, technical details, and audit history.

Raw technical findings are never rendered directly to non-expert users. Instead, they are transformed into user-appropriate explanations using the communication mode selected for the user or organization.

---

# 12. Charter Amendment Status

This document is approved as a Project AQELYN Charter v2.0 amendment and is included in the pre-coding baseline.
