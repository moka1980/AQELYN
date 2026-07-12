# AQELYN Blueprint - Volume 018

**Title:** AQELYN Core Services Architecture

**Source pages:** 421-433

--- Page 421 ---

Volume 18
AQELYN Core Services Architecture (SCSA)
Version: 1.0
Status: Draft
Vision
Everything inside AQELYN is built upon reusable Core Services.
Instead  of  each  module  implementing  its  own  logging,  scanning,  scheduling,
authentication, reporting, or notifications, they all consume common platform services.
This  reduces  duplication,  simplifies  maintenance,  and  creates  a  consistent  user
experience.
Core Service Map
                 AQELYN
Every engine uses the same services.
Chapter 1
Identity Service
The Identity Service manages:
•  Users
•  Roles
•  Permissions
•  Sessions
•  MFA
•  API Tokens
•  Service Accounts
Every authentication request passes through this service.
Chapter 2
Object Service
Responsible for:
•  Creating Objects
•  Updating Objects
•  Version History
•  Relationships


--- Page 422 ---

•  Lifecycle
•  Search
•  Object Cache
No module writes directly to storage.
Everything passes through the Object Service.
Chapter 3
Evidence Service
One of the most important services.
Responsibilities:
•  Evidence Collection
•  Evidence Validation
•  Hash Verification
•  Digital Signatures
•  Chain of Custody
•  Evidence Export
Every finding references evidence.
Chapter 4
Knowledge Service
Stores organizational knowledge.
Examples
Recurring problems
Lessons learned
Threat relationships
Asset relationships
Historical incidents
Security articles
Best practices
Knowledge grows continuously.
Chapter 5
Workflow Service
Responsible for:
Mission Workflow
Approval Workflow


--- Page 423 ---

Incident Workflow
Compliance Workflow
Investigation Workflow
Reporting Workflow
Verification Workflow
Everything becomes a workflow.
Chapter 6
Reporting Service
Every report is generated from objects.
Supported formats:
PDF
HTML
Markdown
JSON
CSV
Future support:
Word
PowerPoint
Interactive Reports
Reports become reusable templates.
Chapter 7
Notification Service
Supports:
Email
Slack
Microsoft Teams
Discord
Matrix
Signal (through a gateway)
Generic Webhooks
Future integrations can be added through plugins.
Chapter 8


--- Page 424 ---

Accessibility Service
This service continuously verifies:
WCAG compliance
Keyboard navigation
Screen reader compatibility
Color contrast
Localization completeness
Every UI component is tested against accessibility rules.
Chapter 9
Translation Service
Every string inside AQELYN is translated.
Example
English
Run Website Scan
Norwegian
Start nettsideskanning
German
Website-Scan starten
Japanese
Web
Languages become installable packages.
Chapter 10
Automation Service
Automation becomes visual.
Example
New Website


--- Page 425 ---

Users do not need programming knowledge.
Chapter 11
Health Monitoring Service
Monitors:
Platform
Workers
Memory
CPU
Queue Length
Plugin Status
Mission Progress
API Health
Object Engine
Knowledge Engine
This becomes the "heartbeat" of AQELYN.
Chapter 12
Audit Service
Everything important is audited.
Every audit entry contains:
Who
What
When
Where
Why
Result
Evidence Reference
Nothing important happens silently.
Chapter 13
Configuration Service
Configuration is treated as version-controlled objects.


--- Page 426 ---

Every configuration change records:
Previous Value
New Value
Reason
Approver
Rollback Information
Chapter 14
Secrets Service
The Secrets Service protects:
Passwords
Certificates
API Keys
Cloud Credentials
SSH Keys
OAuth Secrets
Secrets are encrypted at rest and only exposed to authorized services when required.
Chapter 15
Plugin Service
Plugins declare:
Capabilities
Permissions
Dependencies
Required API Version
Digital Signature
Supported AQELYN Version
The platform validates plugins before activation.
PS-ADR-0015
Platform Services Before Features
Status: Accepted
Decision
All reusable functionality shall be implemented as Core Services before being consumed


--- Page 427 ---

by higher-level engines.
Rationale
This  reduces  duplicated  code,  improves  consistency,  and  enables  independent  testing
and evolution of platform capabilities.
NEW CORE ENGINE
Security Verification Engine (SVE)
One problem with many security platforms is that they stop after reporting.
AQELYN shall continue until verification.
Every remediation follows this lifecycle:
Finding
Verification is an integral part of the platform, not an afterthought.
NEW CORE ENGINE
Trust Analytics Engine (TAE)
The Trust Analytics Engine analyzes trust trends across:
•  Websites
•  Endpoints
•  Mobile Devices
•  Cloud Resources
•  APIs
•  Users
•  Business Units
It provides historical insight and helps identify gradual deterioration or improvement.
NEW CORE ENGINE
Cyber Performance Engine (CPE)


--- Page 428 ---

A capability I have not seen treated as a first-class feature.
This  engine  measures  the  performance  of  cybersecurity  operations,  not  just
infrastructure.
Examples:
•  Average scan duration.
•  Mean time to detect.
•  Mean time to investigate.
•  Mean time to remediate.
•  Mean time to verify.
•  Coverage of critical assets.
•  Verification success rate.
•  Automation success rate.
Organizations  can  measure  how  effectively  they  operate  their  security  program  over
time.
NEW IDEA
AQELYN Blueprint Validator
Since we are writing such a comprehensive specification, I propose we eventually build a
Blueprint Validator into AQELYN itself.
It verifies that:
•  Every implemented module has an ADR.
•  Every API has documentation.
•  Every permission is defined.
•  Every object type has a lifecycle.
•  Every engine has automated tests.
•  Every workflow has verification steps.
•  Every UI screen meets accessibility requirements.
•  Every report template has version history.
The platform effectively checks whether it still conforms to its own architecture.
NEW IDEA
AQELYN Engineering Console
This will be available only to platform developers and administrators.
It provides insight into:
•  Object Engine internals.
•  Event Bus activity.
•  Workflow execution.
•  Plugin loading.
•  Scheduler state.
•  Memory usage.
•  Engine diagnostics.
•  Performance metrics.


--- Page 429 ---

This console supports development, debugging, and operational troubleshooting without
exposing unnecessary complexity to regular users.
The next major milestone
After this volume, we will begin specifying the domain-specific engines in detail:
•   Web  Security  Engine –  website,  API,  TLS,  headers,  authentication,  web
vulnerabilities, and authorized attack surface assessment.
•  Endpoint Security Engine – Windows, Linux, macOS.
•  Mobile Security Engine – Android and iOS (within platform security models).
•  Cloud Security Engine – AWS, Azure, Google Cloud, Kubernetes, containers.
•  Identity Security Engine – identities, MFA, privileged access, directory services.
•  Email Security Engine – SPF, DKIM, DMARC, mail infrastructure, phishing posture.
•   Network  Security  Engine –  authorized  network  discovery,  segmentation,
exposure, and configuration assessment.
These  engines  will  all  follow  the  same  architectural  principles  we  have  already
established: evidence-first, explainable, mission-driven, accessible, modular, and
built with Python and open technologies.
One final architectural principle
I want to add one principle that I think will become part of AQELYN's identity:
Every  recommendation  should  save  the  user  time,  reduce  risk,  or  improve
understanding. If it does none of those, it should not appear in the interface.
That principle will help us keep the platform powerful without overwhelming users, and it
aligns perfectly with our goal of building a Cyber Security Operating Platform that is both
professional and exceptionally easy to use.
=====[ USER ]=====
Will our system be better than CrowdStrike or claude mythos? Good and continue
=====[ ASSISTANT ]=====
Thank you. This is probably the most important strategic question you've asked so far.
The answer is:
It should not try to become "a better CrowdStrike."
Instead, it should become something different.
CrowdStrike, Microsoft Defender, Palo Alto Cortex, Tenable, Wiz, Rapid7, and others are
outstanding at specific domains. They also have thousands of engineers and decades of
development behind them. It would not be realistic to expect AQELYN to surpass
every one of them in every area.
However,  there  is  a  realistic  path  to  building  something  unique  and  highly
valuable.
Where AQELYN can be better
Instead of competing on one feature, we compete on architecture.
| Existing products | AQELYN


--- Page 430 ---

| Multiple separate products | One integrated Cyber Security Operating Platform
About CrowdStrike
entity["company","CrowdStrike","Cybersecurity  company"]  is  one  of  the  world's
leading endpoint detection and response (EDR/XDR) platforms.
They are exceptional at:
•  Endpoint telemetry.
•  Threat detection.
•  Managed threat hunting.
•  Large-scale cloud analytics.
•  Enterprise deployments.
AQELYN should integrate with products like CrowdStrike where appropriate, not
assume it replaces them in every deployment.
About Claude Mythos
If  you're  referring  to  a  security-oriented  project  or  assistant  built  on
entity["company","Anthropic","AI  company"]'s  Claude  models,  then  its  strengths  are
likely  to  be  AI-assisted  analysis  and  reasoning  rather  than  acting  as  a  complete
cybersecurity operating platform.
Our vision is different.
AI is one component of AQELYN, not the foundation.
The foundation is:
•  Evidence.
•  Objects.
•  Knowledge.
•  Trust.
•  Workflows.
•  Verification.
AI becomes an assistant—not the decision maker.
Where I think we can genuinely innovate
There are several areas where I believe AQELYN can be genuinely distinctive if
executed well.
1. Mission-Based Cybersecurity
Nobody should have to think:
"Should I run scanner A or scanner B?"
Instead they choose:
•  Secure my website.
•  Audit my company.
•  Investigate suspicious activity.
•  Check my phone.


--- Page 431 ---

•  Prepare for ISO 27001.
•  Perform an authorized bug bounty assessment.
The Mission Orchestrator selects the appropriate engines.
2. One Object Model
This remains, in my opinion, one of the strongest architectural decisions.
Everything is an object.
Not:
•  one model for incidents,
•  another for assets,
•  another for users.
One model.
That dramatically simplifies development and extensibility.
3. Cyber Memory
Imagine the platform remembering:
"This server has repeatedly lost its Content Security Policy after deployments."
or
"This  mobile  device  has  installed  and  removed  the  same  unauthorized  application  three
times."
That is organizational memory rather than just log storage.
4. Digital Twin
A living representation of the customer's security environment.
Not merely an asset inventory.
A continuously updated operational model.
5. Explainability
Every recommendation answers:
•  Why?
•  Evidence?
•  Confidence?
•  Verification?
•  Business impact?
That is valuable for analysts, auditors, and executives alike.
6. Ease of Use
This may become our biggest competitive advantage.
You have repeated one goal since the beginning:


--- Page 432 ---

The platform must be easy to use.
I completely agree.
Many enterprise security products overwhelm users with hundreds of menus, dashboards,
and alerts.
AQELYN should instead answer:
"What should I do next?"
That is a fundamentally different experience.
One idea I have been thinking about
I think we should introduce a concept called the AQELYN Compass.
Instead  of  opening  the  platform  to  dozens  of  dashboards,  the  user  first  sees  a  single
operational overview.
Mission Status
This is easy for:
•  a private user,
•  a security consultant,
•  a CISO,
•  a SOC analyst.
The  details  remain  available,  but  the  first  screen  always  answers  the  most  important
questions.
AQELYN BLUEPRINT


--- Page 433 ---

Volume 19
