# Example Software Supply Chain Records

## 52.1 Example Software Component

```yaml
component_id: SWC-0001
name: example-library
version: 2.4.1
publisher: trusted_vendor
package_type: npm
```

## 52.2 Example SBOM Document

```yaml
sbom_id: SBOM-2001
format: CycloneDX
generated_at: 2026-07-07T12:00:00Z
integrity_hash: sha256:example
component_count: 186
```

## 52.3 Example Provenance Record

```yaml
provenance_id: PROV-3001
publisher: trusted_vendor
signature_status: valid
trust_score: 0.92
```

## 52.4 Example Software Supply Chain Event

```json
{
  "event_type": "dependency.risk.detected",
  "component_id": "SWC-0001",
  "risk_score": 84,
  "source_engine": "aqelyn_software_supply_chain_security_sbom_intelligence_engine"
}
```
