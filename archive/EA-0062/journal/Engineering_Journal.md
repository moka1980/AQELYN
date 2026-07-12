Decision: Create EA-0062 as an internal engineering system rather than a static documentation page.
Rationale: AQELYN has a large architecture baseline. A portal reduces navigation burden, improves AI-agent compliance, and keeps implementation status traceable.

Decision: Include both Codex and Claude Code integration.
Rationale: The project will likely use multiple AI coding agents. They require consistent constraints and task boundaries.

Decision: Portal state must be auditable.
Rationale: Engineering status, quality gates, and review state affect implementation trust.

Open consideration: first implementation can be static-document backed, with database integration added incrementally.