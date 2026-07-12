# ADR-0001 — Runtime, Deployment Target, and Core Technology Stack

**Status:** Accepted
**Date:** 2026-07-11
**Applies to:** All AQELYN Engineering Archives from EA-0001 onward
**Supersedes:** Informal guidance in `docs/Hosting_Recommendation_one_com.pdf`

---

## 1. Why this ADR exists

Every AQELYN module inherits its runtime, datastore, event mechanism, and
packaging from a single set of decisions. Until those are fixed, the
foundation specs (EA-0001 Kernel, EA-0002 Universal Object Model, EA-0003
Event Bus, EA-0004 Evidence Engine) cannot be written concretely, because
their interfaces depend on these choices. This ADR fixes them **once** so
the specs and code stay consistent.

A guiding constraint from the project charter: AQELYN must run in a
**local-first / privacy-preserving** mode *and* a centrally governed
enterprise mode from the same architecture. Every decision below is chosen
to keep that dual mode possible.

---

## 2. Context

### 2.1 What the platform actually needs to run

- A long-running orchestration process (the Kernel) that starts, health-checks, and stops subsystems.
- An in-process (later networked) event bus.
- A durable system of record for the Universal Object Model, Evidence records, and Findings.
- Background/worker execution for assessments.
- A typed HTTP API.
- Reproducible, portable deployment across three environments: local dev, staging, production.

This is a **modular application platform**, not a website.

### 2.2 Hosting is a deployment choice, not an architecture choice

The host is deliberately **not** fixed. Development starts on the local
machine; any full-control server can host it later. one.com was evaluated
(below) as one candidate and found constraining in its *managed* tier — the
lesson generalizes to any managed/shared web-hosting plan. Oracle Cloud,
Hetzner, and the major clouds are all acceptable; pick at staging time.

**one.com evaluation (verified 2026-07-11), kept as reference:**

| Item | Finding |
|---|---|
| Managed Cloud Server M | 4 vCPU / 8 GB RAM / 200 GB NVMe / 1 Gbit/s, includes Redis Cache |
| Managed pre-installed stack | Ubuntu + Apache + MariaDB + PHP + Nginx (proxy) + **Plesk** |
| Managed customization | "customization options may be limited" (provider statement) |
| Data residency | Copenhagen, ISO 27001 certified, GDPR-aligned, 7-day backups |
| Unmanaged / general VPS | OpenStack-based, full root, SSH-key access, supports Python/Node/Docker |

**Assessment:** The **Managed** tier is a Plesk/LAMP web-hosting environment.
It is a poor primary runtime for a custom multi-service Python platform:
one.com manages only the web stack, not custom services, so the managed
benefit does not cover AQELYN's actual processes, while the Plesk
constraints and auto-patching can disrupt them. The **data-residency and
compliance posture (EU, ISO 27001, GDPR) is a genuine asset** for AQELYN's
privacy-first positioning and should be retained.

---

## 3. Decisions

### D1 — Deployment target
- **Requirement, not a vendor:** the runtime target is **any host that gives
  full root/administrator control** — the freedom to run Docker, custom
  services, and PostgreSQL. The platform is host-agnostic by design (see §4).
- **Development starts local.** The first target is the **developer's own
  machine** (Docker Desktop / native). C-001's walking skeleton must run end
  to end locally before any server is provisioned. No hosting is required to
  begin coding.
- **Acceptable hosts** (any of): a local machine; an unmanaged root-access
  VPS; a general cloud VM such as **Oracle Cloud** (its Always-Free
  Ampere/ARM tier is a strong low-cost option), Hetzner, AWS, GCP, Azure,
  DigitalOcean, etc. EU-resident hosting is preferred where the privacy-first
  positioning matters, but is a deployment choice, not an architecture one.
- **Avoid:** managed/shared "web hosting" tiers (Plesk/cPanel LAMP stacks)
  as the *application* runtime — they constrain custom services and only
  manage the web stack. Such a plan may host the public marketing/docs site
  only.
- **Sizing (any provider):** early dev ~2 vCPU / 4 GB / ~40–100 GB; serious
  dev + staging ~4 vCPU / 8 GB / ~200 GB; production-like ~8 vCPU / 16 GB /
  ~400 GB. Oracle's free ARM allocation (up to 4 vCPU / 24 GB) comfortably
  covers dev and staging.
- **ARM note:** if using an ARM host (e.g. Oracle Ampere), build multi-arch
  Docker images (`linux/amd64` + `linux/arm64`). Kept trivial by the
  portability principle in §4.

### D2 — Language & runtime
- **Python 3.12**, fully type-annotated, `mypy --strict` and `ruff` enforced
  (per EA-0058 and the existing `pyproject.toml.example`).

### D3 — Application shape (the important one)
- **Modular monolith first**, not microservices. A single deployable
  process runs the Kernel + in-process Event Bus + engines-as-modules,
  behind clean interfaces. Rationale: fits a single VPS, matches the C-001
  walking-skeleton goal, and avoids premature distributed-systems
  complexity. The **interfaces are designed so any module can be split into
  its own service later without changing callers.**

### D4 — API layer
- **FastAPI + Uvicorn.** Async, typed, automatic OpenAPI (supports the
  charter's evidence/traceability transparency and EA-0062 portal APIs).

### D5 — System of record
- **PostgreSQL 16** for the Object Model, Evidence store, and Findings.
- Chosen over the managed box's MariaDB for: `JSONB`, strong constraints and
  foreign keys, append-only + hash-chain friendliness for Evidence, and
  richer relationship queries for the object graph. Portable to any host.

### D6 — Event transport
- **An `EventBus` interface with two implementations:**
  - `InMemoryEventBus` — used for C-001 and all unit tests.
  - `RedisStreamsEventBus` — used from C-002 onward (Redis is available on
    Managed M+ and trivial to self-host on unmanaged).
- Application code depends only on the interface, never on Redis directly.

### D7 — Background work
- Start **in-process** (asyncio tasks) in C-001. Introduce a separate worker
  process only when a real engine needs it. No Celery/broker complexity in
  the foundation.

### D8 — Packaging & reproducibility
- **Docker + docker-compose** as the primary deployment unit (app, Postgres,
  Redis). **`systemd` service** provided as a fallback for environments where
  Docker is not permitted. This is the portability guarantee.

### D9 — Configuration & secrets
- **12-factor**: all config via environment variables, loaded with
  `pydantic-settings`. **No secrets in the repo** (enforced in CI). `.env`
  for local only; real secrets via the host's secret store.

### D10 — Edge / TLS
- **Nginx reverse proxy + Let's Encrypt TLS**, HTTPS-only, SSH-key-only
  admin, no development APIs exposed publicly (per the existing security
  checklist).

---

## 4. Portability principle (non-negotiable)

The foundation must **not** encode one.com, Plesk, or any single host into
application code or schemas. Host-specific concerns live only in deployment
config (Docker/compose/systemd/Nginx). This keeps AQELYN's dual local-first /
enterprise-cloud requirement intact and prevents lock-in.

---

## 5. Consequences

**Positive**
- Runs on the chosen host today; runs on a laptop, a different cloud, or an
  enterprise datacentre unchanged.
- Modular-monolith keeps C-001 achievable while preserving a clean path to
  services.
- EU data residency supports the privacy-first product promise.

**Costs / risks**
- If the user prefers Managed VPS for ops relief, D1 requires a support
  confirmation step, or a two-box split (managed website + unmanaged app).
- Self-managing an unmanaged VPS re-adds the hardening/patching/backup work
  that "managed" would have covered — the existing security checklist
  becomes the operator's responsibility.

**Deferred (own future ADRs)**
- **Scanning execution model.** Active scanning from a hosting-provider VPS
  likely breaches acceptable-use policy. Scanning (C-005/C-006) will need
  agent/client-side execution or dedicated scanner nodes. Decide in a
  dedicated ADR before EA-0052+.
- **Knowledge-graph store** (EA-0005). Start modeled inside PostgreSQL;
  evaluate a dedicated graph engine only if query needs demand it.

---

## 6. Open decision needed from you

Nothing here blocks the foundation. The only deployment-time choice is
**which host you eventually deploy to** (local → Oracle Cloud / other VM),
and that can be decided at staging time. Development begins on the local
machine regardless.
