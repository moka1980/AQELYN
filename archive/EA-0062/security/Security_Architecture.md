Security controls:
- OIDC authentication.
- RBAC authorization.
- Audit logging for state changes.
- Signed release status records.
- Read-only architecture baseline unless user has Architect role.
- AI task generation sandboxing.
- No secrets stored in generated prompts.
- GitHub tokens stored only in approved secret storage.
- Sensitive integration tokens never exposed in frontend state.
- Rate limiting on mutation endpoints.

The portal is an internal engineering system and must be treated as a high-value governance application.