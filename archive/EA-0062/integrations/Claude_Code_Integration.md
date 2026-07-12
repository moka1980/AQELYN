Claude Code integration shall provide a parallel task workflow optimized for repository-aware implementation.

The portal shall generate Claude Code task bundles containing:
- START_HERE excerpt.
- Current EA summary.
- Relevant source files.
- Target implementation paths.
- Test paths.
- Review checklist.
- Guardrails.
- Expected commit boundaries.

Claude Code system guidance:
1. Read START_HERE.md.
2. Read EA-0058, EA-0059, EA-0060, and EA-0061.
3. Read the current EA package.
4. Inspect existing code before editing.
5. Implement the smallest compliant increment.
6. Run tests and static checks.
7. Update traceability and implementation status.
8. Never restructure the repository.
9. Never invent undocumented features.

Claude Code output shall include:
- Files changed.
- Tests run.
- Requirements satisfied.
- Known limitations.
- Next recommended EA task.