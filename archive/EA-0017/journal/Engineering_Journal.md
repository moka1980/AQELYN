# Engineering Journal

## Journal Entry - EA-0017

EA-0017 was created to archive completion of IS-017 - AQELYN Threat Detection & Analytics Engine.

The archive records the expansion of AQELYN into real-time threat detection and analytics. IS-017 defines the structure needed to detect threats, analyze behavior, identify anomalies, correlate signals, score threats, map detections to ATT&CK-style techniques, predict likely threat progression, publish detection events, and support SOC operations with evidence-backed analytics.

The engineering design preserves the fixed AQELYN repository structure and maintains backward compatibility with previously completed engines.

## Lessons Learned

Detection analytics must be modeled separately from SOC operations, threat intelligence, and digital forensics. Threat intelligence supplies indicators and context, digital forensics supplies evidence and timelines, SOC consumes detections operationally, and the Threat Detection & Analytics Engine owns real-time detection, behavioral analytics, correlation, scoring, mapping, and prediction.

## Governance Note

EA-0017 follows the master-document publication workflow. The Markdown file is the authoritative source, and PDF/HTML representations are generated from the same content.
