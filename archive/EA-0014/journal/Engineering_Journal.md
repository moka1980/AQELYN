# Engineering Journal

## Journal Entry - EA-0014

EA-0014 was created to archive completion of IS-014 - AQELYN Threat Intelligence Fusion Engine.

The archive records the expansion of AQELYN into threat intelligence fusion. IS-014 defines the structure needed to register sources, ingest feeds, normalize indicators, maintain actor and campaign intelligence, map TTPs, score confidence, correlate intelligence, bind evidence, update risk, update mission threat context, and generate threat reports.

The engineering design preserves the fixed AQELYN repository structure and maintains backward compatibility with previously completed engines.

## Lessons Learned

Threat intelligence must be modeled separately from risk intelligence. Risk intelligence consumes threat context, but the Threat Intelligence Fusion Engine owns feed ingestion, source confidence, indicator lifecycle, actor attribution, campaign tracking, and threat correlation.

## Governance Note

EA-0014 follows the master-document publication workflow. The Markdown file is the authoritative source, and PDF/HTML representations are generated from the same content.
