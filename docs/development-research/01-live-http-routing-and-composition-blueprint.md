# Live HTTP integration blueprint: from Python services to a working forge

**Priority:** immediate parallel track with S-153+. **Current gap:** `samverk/server.py` supports root and health GET only; it does not yet mount the existing repo, issue, review or transport services.

## Architectural contract

```text
TCP / TLS / reverse-proxy policy
  → bounded HTTP parse and route classification
  → one of: browser-cookie route | token API | Git smart-HTTP | LFS
  → identity and token/session resolution
  → permission and CSRF where applicable
  → input validation + request budget
  → established service/store in samverk/
  → transaction + audit/outbox
  → safe HTML/JSON/Git binary response
```

**Critical caveat:** S-009's current blanket state-changing CSRF gate cannot simply guard smart-Git HTTP POSTs, which use transport authentication and binary protocol payloads rather than browser cookie/form tokens. Split route types explicitly. Cookie-authenticated browser mutations **must** retain CSRF; token-authenticated Git/API routes need their own anti-abuse/auth rules. Never globally disable CSRF to make a clone work.

## Candidate route ledger (proposal, not implemented)

| Family | Example route shape | Existing source seam | Required auth |
|---|---|---|---|
| Session | `GET/POST /login`, `POST /logout` | `login.py`, `sessions.py`, `http_security.py` | Cookie+CSRF on mutations |
| Repository | `GET /{owner}/{repo}` | `repositories.py`, `repo_home.py` | read permission |
| Tree | `GET /{owner}/{repo}/tree/{ref}/{path}` | `file_browser.py`, `repo_paths.py` | read permission |
| Blob | `GET /{owner}/{repo}/blob/{ref}/{path}` | `blob_view.py` | read permission |
| Issue | `GET/POST /{owner}/{repo}/issues[/...] ` | `issues.py`, comments/labels | authenticated write + CSRF |
| Pull request | `GET/POST /{owner}/{repo}/pulls[/...] ` | `pull_requests.py`, `pull_request_forks.py` | per action |
| Review | `POST /{owner}/{repo}/pulls/{n}/reviews` | `pull_request_reviews.py` | reviewer permission + CSRF |
| Git advertise | `GET /{owner}/{repo}.git/info/refs?service=...` | `git_http.py` | service-specific read/write gate |
| Git RPC | `POST /{owner}/{repo}.git/git-upload-pack` / `git-receive-pack` | `git_http.py`, `receive_gate.py` | HTTP Basic/token transport, no browser cookie assumption |
| LFS | `POST /{owner}/{repo}.git/info/lfs/objects/batch` | `lfs_api.py`, locks | LFS-scoped identity |

These routes are illustrative. Record final canonical URL shape and compatibility redirect policy in the actual route register before implementation.

## Build in narrow vertical cuts

1. **Read-only proof:** wire GET repo home/tree/blob and a unified private-repo not-found mapping. Start real server; read one public repo and refuse a private one.
2. **Session proof:** login/logout + CSRF form mutation + token mint page. Verify cookies, SameSite, TLS flags and reauth.
3. **Write proof:** create repository and issue with role and audit check. Ensure user sees outcome and error path.
4. **Transport proof:** wire smart-Git advertise/upload/receive preserving binary streams; don't serialize pack into JSON. Run real Git CLI clone/push/pull.
5. **PR proof:** open/review/merge after S-153–S-168 algorithms are ready; verify audit and changed refs.
6. **Refinement:** link common navigation, errors, forms, search and long-running worker tasks into a coherent interface; eventually pass Part XX visual gate.

## Safety checks on every route

- Fixed path matching before decoding untrusted ref segments; path normalization by trusted helper, not string concatenation.
- Bound headers, request body length, read timeout, concurrency, response streaming; fail before dangerous allocations.
- Recheck authorization in service call, not only outer router or hidden UI button.
- HTML must pass escaping and CSP; JSON must have explicit UTF-8/content type; Git pack responses are opaque binary with protocol MIME.
- Uniform structured errors for unauthorized/private/nonexistent resources where disclosure matters; no stack traces.
- Request/response telemetry contains trace ID, duration and safe reason, not secrets or private file content.

## Definition of integrated

A route is not integrated until a live HTTP test starts `samverk serve`, sends a successful request, sends a deliberately unauthorized request, and checks the SQLite/Git state and audit consequences. Put its status in a route matrix: **service code / routed / real HTTP test / browser task passed / deployment test**.

## Primary sources

- https://www.rfc-editor.org/rfc/rfc9110.html
- https://git-scm.com/docs/gitprotocol-http
- https://git-scm.com/docs/gitprotocol-v2
- https://docs.python.org/3/library/http.server.html
- https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
