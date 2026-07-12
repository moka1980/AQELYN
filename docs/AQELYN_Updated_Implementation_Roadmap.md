# AQELYN - Updated Implementation Roadmap

## Coding Order

1. C-001 Foundation Runtime: Kernel, Universal Object Model, Event Bus, Evidence primitives, configuration, logging, test harness.
2. C-002 Core Services: Knowledge Graph, Trust Engine, Policy Engine, Mission Engine, Workflow Engine stubs.
3. C-003 Identity Foundation: ISPM, machine identity governance, identity inventory and relationship model.
4. C-004 Asset Foundation: Asset Discovery and Inventory Engine (EA-0057) because every later scan and assessment depends on canonical assets.
5. C-005 Endpoint Platform: Endpoint Intelligence (EA-0052) followed by Endpoint Security Assessment (EA-0053).
6. C-006 Exposure Platform: Web Intelligence (EA-0054), Attack Surface Discovery (EA-0055), Vulnerability Intelligence (EA-0056).
7. C-007 Correlation and Risk: cross-engine scoring, prioritization, knowledge graph enrichment and evidence consolidation.
8. C-008 Automation: workflow remediation, reporting, API hardening, UI/API integration, deployment packaging.

## First Coding Milestone

Build a runnable Python package under `src/aqelyn` with typed modules, tests, and CLI smoke test. No production scanning is enabled in C-001. The first milestone validates architecture, object/event contracts and evidence flow.

## Safety Requirements

All endpoint, web and attack surface functions must enforce explicit scope. No unauthorized scanning, credential extraction, exploit execution, destructive checks or personal-content collection is permitted.
