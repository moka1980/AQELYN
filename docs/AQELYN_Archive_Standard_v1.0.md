# AQELYN Archive Standard v1.0

This standard is frozen before C-001 coding begins.

## Repository Rule
The top-level repository structure remains immutable:

```text
AQELYN/
├── archive/
├── blueprint/
├── docs/
├── src/
├── tests/
├── tools/
├── build/
├── releases/
├── scripts/
├── assets/
├── examples/
├── plugins/
├── sdk/
├── api/
└── README.md
```

## Engineering Archive Folder Standard
Each archive folder shall use this structure:

```text
archive/EA-xxxx/
├── README.md
├── EA-xxxx_Master.md
├── pdf/
│   └── EA-xxxx.pdf
├── html/
│   └── EA-xxxx.html
├── diagrams/
│   ├── Architecture.svg
│   ├── Component.svg
│   ├── Workflow.svg
│   ├── EventFlow.svg
│   └── Integration.svg
├── examples/
├── requirements/
│   ├── Requirements_Matrix.md
│   └── Traceability_Matrix.md
├── journal/
│   └── Engineering_Journal.md
├── index/
│   └── EA-xxxx_Index.md
└── manifest.json
```

## Release Rule
No FULL_COMPLETE ZIP files are stored inside archive/. Release packages are stored only under releases/.
