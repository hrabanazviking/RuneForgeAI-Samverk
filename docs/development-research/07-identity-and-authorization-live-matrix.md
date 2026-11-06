# Identity and authorization as a product-wide executable matrix

## Trusty identity types

| Principal | Source | Key limitation |
|---|---|---|
| Anonymous | no credential | only public reads |
| Browser user | session cookie | session + CSRF for state-changing browser forms |
| Git HTTP user | Basic/PAT | transport rights only, no forged cookie session |
| SSH personal key | server-resolved fingerprint | account state and repo grants |
| SSH deploy key | bound repo/key grant | no other repo; write only if explicitly approved |
| API token | scope/resource-limited bearer | account permission ∩ token scope |
| Webhook delivery worker | internal queue | outbound event only, not implicit user admin |
| Samtal linked principal | explicit cross-app proof | scoped bridge, never silent full trust |

## Central decision shape

```text
authorize(principal, action, resource, request_context)
  → DENY(private_not_found | explicit_forbidden | expired | ...)
  → ALLOW(permission_snapshot)
```

Use one server-law function underneath web, Git and API adapters. A GET rendering method must not bypass the policy just because it is read-only; private blob content is still protected. When permissions change, invalidate or re-evaluate cached decisions.

## Role × action proof table

| Action | Anonymous | Reader | Writer | Owner/admin |
|---|---:|---:|---:|---:|
| Public repository read | yes | yes | yes | yes |
| Private repository read | no | grant only | grant only | grant only |
| Issue comment | no | policy-dependent | yes if repo permits | yes |
| Push normal branch | no | no | permitted | permitted |
| Change protected branch | no | no | only if policy permits | only if policy permits |
| Issue moderation | no | no | no | yes |
| Manage PAT or 2FA | no | own account only | own account only | own account only |
| Delete repository | no | no | no | authorized owner + sudo gate |

This is an **illustrative test-plan table**; exact role semantics and site policy must be ratified in the permissions design record before implementation.

## Mandatory non-disclosure tests

Ask for a private repo, nonexistent repo and private LFS OID as anonymous, ungranted user, scoped token and wrong deploy key. Compare not only status but body, redirects, headers and coarse timing; avoid informative oracle differences. Test repo names that differ only in case on portable filesystems.

## Credential lifecycle

Session revocation, account suspension, token expiry, scope narrowing, SSH key removal and org-team membership change must affect the **next** action. Test one request immediately before and one after mutation, including a Git fetch and queued webhook. Authorized users may receive useful error reasons; strangers must not learn private resource existence.

## Browser-specific boundaries

Cookie-authenticated POST needs CSRF; API PAT and Git HTTP token routes need strong token verification, constrained CORS and request limits, not fake browser CSRF tokens. On privileged account changes, require fresh reauthentication and audit.

## Security reference set

- NIST SP 800-63B-4: https://csrc.nist.gov/pubs/sp/800/63/b/4/final
- WebAuthn Level 3 (2026 Recommendation): https://www.w3.org/TR/webauthn-3/
- OWASP ASVS 5: https://asvs.owasp.org/
- OWASP Authorization Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
