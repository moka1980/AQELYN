Representative backend APIs:
GET /api/v1/archives
GET /api/v1/archives/{ea_id}
GET /api/v1/archives/{ea_id}/requirements
GET /api/v1/archives/{ea_id}/traceability
GET /api/v1/implementation/status
PATCH /api/v1/implementation/{ea_id}/status
GET /api/v1/dependencies
GET /api/v1/mission-control
POST /api/v1/agents/codex/task
POST /api/v1/agents/claude-code/task
POST /api/v1/agents/cursor/rules
GET /api/v1/ci/status
GET /api/v1/releases/readiness
POST /api/v1/change-requests

All APIs shall follow EA-0058 naming, error handling, logging, authentication, and observability rules.