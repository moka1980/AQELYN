# Example Cryptographic Security Records

## 52.1 Example Secret Asset

```yaml
secret_id: SEC-0001
secret_type: api_key
owner: platform_security_team
storage_location: vault://prod/payments/api-key
```

## 52.2 Example Cryptographic Key

```yaml
key_id: KEY-2001
algorithm: AES-256
strength: strong
rotation_date: 2026-10-07
owner: data_security_team
```

## 52.3 Example Certificate Asset

```yaml
certificate_id: CERT-3001
issuer: enterprise_internal_ca
expiration_date: 2026-08-15
validation_status: valid
```

## 52.4 Example Cryptographic Event

```json
{
  "event_type": "certificate.expiring",
  "certificate_id": "CERT-3001",
  "days_until_expiration": 30,
  "source_engine": "aqelyn_secrets_security_cryptographic_asset_intelligence_engine"
}
```
