# AQELYN - Project Summary for Codex

AQELYN is a Cyber Security Operating Environment (CSOE) designed to unify security engineering, endpoint intelligence, identity governance, evidence management, trust evaluation, policy enforcement, workflow automation, attack surface discovery, web intelligence, vulnerability intelligence and asset inventory into one coherent platform.

The project is organized around immutable Engineering Archives (EA-0001 onward). Each archive corresponds to one implementation specification and contains the master engineering design, PDF, HTML, matrices, diagrams, journal, examples and manifest. The repository hierarchy is fixed and must not change.

The immediate coding objective is C-001 - Foundation Runtime. Coding shall begin with the Kernel, Universal Object Model, Event Bus, Evidence primitives, Policy stubs, Trust stubs and test harness. The endpoint, web, attack surface, vulnerability and asset engines added in EA-0052 through EA-0057 shall be implemented after the foundation runtime and shared service contracts are stable.

AQELYN supports both private-user and enterprise scenarios. For private use, endpoint assessment must be consent-based, privacy-preserving, local-first where possible and limited to security metadata. For enterprise use, collection is centrally governed through scope policies, agents, connectors, evidence chains and audit controls.
