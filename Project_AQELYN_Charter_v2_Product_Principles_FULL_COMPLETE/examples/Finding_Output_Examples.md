# Finding Output Examples

## Example 1 - Weak Authentication

Problem: Your administrator account does not have multi-factor authentication enabled.

Risk: If the password is stolen, an attacker may access administrative functions.

Evidence:
- MFA status: Disabled
- Account role: Administrator
- Last password change: 420 days ago

Fix: Enable MFA for the administrator account.

Expert details:
- Policy: SEC-AUTH-004
- Identity object: identity.admin.local
- Evidence ID: EV-AUTH-0001

## Example 2 - Expiring Certificate

Problem: A certificate used by your web service expires soon.

Risk: Users may be unable to connect securely if the certificate expires.

Evidence:
- Expiration: 12 days
- Service: public web portal
- Certificate chain: valid

Fix: Renew the certificate before expiration.
