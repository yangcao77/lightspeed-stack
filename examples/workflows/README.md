# Workflows on K8s: operator setup and caller guide (post-stack#51)

This folder is a self-contained, end-to-end worked example of the design in
[stack#51, revision 3](https://github.com/jameswnl/lightspeed-stack/issues/51#issuecomment-5911977694):
lightspeed-stack as the sole policy/secret boundary in front of cloud-agents.

> **Status: target state, being built (feature-level TDD).** This folder
> defines where issue #51 and cloud-agents#269 end up. Landed so far:
> Phase 0a (caller `credentials_secret` -> 400; custom images, `advisory`
> and `spawn: none/local` need admin -> 403; size and count caps), Phase 1
> (the provider catalog, secret registry and defaults load, and
> `/v1/workflows/run` resolves providers through them: the stack builds the
> credential reference, the same-entry rule holds, overrides are rewritten to
> executor types), Phase 2 (`workflow_engine.policy`: per-role grants and
> limits checked on every submission, with a structured audit event per
> request) and a **reduced Phase 3**: secretless, catalog-only MCP (see
> "Phase 3 scope" below). The original Phase 3 and security acceptance
> criteria are not complete: secret delivery, inline host grants, `mcp_secrets`
> and SSRF confinement are deferred and stay visible in `cases.yaml`.
> `tests/unit/cloud_agents/test_workflow_contract.py` runs the Phase 0-3 cases
> of `cases.yaml` against the real handler (through `@authorize`) and config,
> and skips the rest. `verify.py` runs the same cases for real, the `phase: 4`
> ones against the reference model in `reference_gate.py`, and checks that
> `deferred` ones carry a reason.

> **Auth prerequisite.** Role-based policy and the admin gates need an auth
> module that resolves roles: `jwk-token` with populated `role_rules` and
> `access_rules` (used here). `rh-identity` and `trusted-proxy` only resolve
> the `*` role, so only wildcard policy is usable with them. With `k8s`,
> `noop`, `noop-with-token` or `api-key` the resolvers are no-ops: callers only have the `*` role,
> `access_rules` are ignored and every caller counts as admin, so the
> admin-only denials below do not apply.

## Contents

| File | Author | Purpose |
|---|---|---|
| `README.md` (this file) | — | Detailed steps: operator setup + authoring + triggering |
| `lightspeed-stack.yaml` | Operator | Provider catalog, secret registry, MCP catalog, policy, spawner |
| `k8s-secrets.yaml` | Operator | Inference and infrastructure Secret values (no MCP Secrets: catalog MCP is secretless) |
| `triage-github-issue.yaml` | Caller | 2-step triage flow (role `agent-user`) |
| `kb-answer-with-approval.yaml` | Caller | Research → human approval → answer (role `agent-support`) |
| `admin-inline-mcp.yaml` | Caller (admin) | Inline MCP server with a registry secret ref (role `agent-admin`); rejected before start until secret delivery lands (Phase 4 target) |
| `post-269-overrides.yaml` | Operator | What changes after cloud-agents#269 (K8s-bound inference credentials, leases) |
| `k8s-deployment.yaml` | Operator | Hardened Deployment, NetworkPolicy; no Secret read RBAC (default, pre-269) |
| `post-269-rbac.yaml` | Operator | Opt-in Role + RoleBinding: stack `get` on the inference Secret, post-269 only |
| `external-secrets.yaml` | Operator | Production source of the Secrets (External Secrets Operator + Vault) |
| `cases.yaml` | Contract | 93 request/config cases with the expected status; `phase: 4` and `deferred` cases stay visible with a reason |
| `reference_gate.py` | Contract | Reference model of the inline-MCP checks (Phase 4) and the post-#269 credential check only; deleted when those land |
| `contract_util.py` | Contract | Case patching and the real-endpoint driver shared by `verify.py` and the unit test |
| `verify.py` | Contract | Runs everything above plus deployment cross-checks |

Assumed deployment: namespace `lightspeed`, stack Deployment + ConfigMap,
Postgres, OpenShell gateway for ephemeral sandboxes.

## Goal coverage (issue #51 acceptance criteria)

Each criterion maps to something in this folder that `verify.py` checks, so
"done" for a phase means more of these run against the real stack.

| #51 criterion | Where it shows up | Checked by |
|---|---|---|
| `ProviderSelection` / `SecretRef` contract | `provider: {name, model, credential_ref?}` in the requests below | `cases.yaml` (credential_ref match / mismatch) |
| Provider-profile and secret registry | `workflow_engine.providers` / `secrets` / `default_*` | load checks, both stages |
| Reject caller-chosen env var / physical ids | `credentials_secret` on run provider and `definition.provider`, unknown provider keys | `cases.yaml` § credentials (400) |
| AuthZ: provider, model, credential, MCP, skills, tools, spawn, images, service accounts, namespaces, limits | `workflow_engine.policy.rules` | `cases.yaml` § policy / spawn / limits (403) |
| In-process handoff contract | Part 3, "After cloud-agents#269" | `post-269-overrides.yaml` run through the same cases |
| Process-boundary handoff contract | same section (lease redeemed over mTLS) | design only; Phase 6 |
| No secret values in payloads, state, logs | requests carry logical names only; `k8s-secrets.yaml` has placeholders only | `verify.py` secrets checks; Phase 4 canary suite later |
| Named MCP (secretless catalog) | `mcp_servers[*].workflow_enabled`, policy `mcp` | `cases.yaml` § MCP (real, Phase 3) |
| Inline MCP URLs / literal headers / host grants | `admin-inline-mcp.yaml`, `inline_mcp_hosts` | `phase: 4` cases against the reference model; inline MCP is admin-only or denied today |
| OpenShell provider injection for ephemeral | `spawner` block, README Step 6 | config schema check |
| `none` / `local` restrictions | admin-only on workflows | `cases.yaml` § spawn |
| Rotation and revocation | Step 8 (pre-#269 rules, Reloader) and Part 3 (post-#269) | documented; lease tests in Phase 6 |
| Cleanup, redaction, cross-principal tests | not examples; Phase 4 / 6 test suites | cross-principal: `agent-support` vs triage, `agent-user` vs KB |
| Deployment docs: K8s secrets, external managers, OpenShell | `k8s-secrets.yaml` (dev), `external-secrets.yaml`, `k8s-deployment.yaml` | `verify.py` deployment cross-checks |
| Limits (`MAX_*`) | byte, step, MCP and secret-header caps | `cases.yaml` § limits (413 / 422) |

## Phase 3 scope: secretless, catalog-only MCP

Only what can be verified today is built. A `workflow_enabled` catalog server
is offered to steps by name and carries no credential: no `secret_headers`
field, no `authorization_headers`, no propagated `headers`, no credentials in
the URL or query string. A server that needs a credential cannot be used from a
workflow yet. That is intended; it fails closed.

Behaviour changes to know about:

- A named reference that matches no `workflow_enabled` entry is a 400 in every
  mode, with the same text for an unknown and a disabled name. The executor
  used to drop such names silently.
- Without a policy, named servers need no grant: every `WORKFLOW_START` caller
  can use every `workflow_enabled` server. Enabling a server is the opt-in, so
  do not enable one whose URL points at a metadata or control-plane endpoint,
  or one that carries credentials in the URL or query.
- Legacy admins (no policy) lose raw inline `secret_headers`
  (`{secret_name, key}` is a 400 for everyone). Any other non-empty inline
  `secret_headers` value, including the logical `{name: ...}` ref, fails the
  typed parse (422) before the run starts, because nothing can deliver it.
- A caller-sent run-level `mcp_servers` is a 400; the stack builds that list
  from the catalog entries the definition references.

Status precedence on `POST /v1/workflows/run`: 413 size; 400 forbidden fields
(run-level `mcp_servers`, raw `{secret_name, key}`, `credentials_secret`); 422
count caps; 422 shape (typed parse, including unsupported `secret_headers`); 400
catalog resolution (unknown provider, `mcp_unknown`, `mcp_name_conflict`); 403
policy (all denials at once, including a missing `mcp` grant); 422 executor
validation. Nothing is persisted or started on any of them. A known, enabled
server without a grant is a 403, so the 400 does not hide which names exist.

An `mcp` grant means every tool on that server. The executor enforces only
which servers a step gets; finite `allowed_tools` are not enforced for MCP
tools, on any spawn mode. Because catalog servers are secretless, they need no
secret delivery on any spawn mode (`none` and `local` still need their own
grants). Whether a step can actually use them on `spawn: ephemeral` depends on
the sandbox provider; see the next section.

### Where catalog MCP is verified (and where it is not)

Catalog MCP is verified end to end only for `spawn: none` and `spawn: local`:
a real subprocess MCP server and a real-LLM e2e run. `spawn: ephemeral` is not
covered the same way, because it depends on which sandbox provider runs the
step. As observed in `lightspeed-agentic-sandbox` at commit `619fb0c`
(`src/lightspeed_agentic/`):

- `openai`: wires MCP servers (`providers/openai.py:206-224`).
- `claude`: never passes `mcp_servers` to the SDK options
  (`providers/claude.py:90-100`).
- `gemini`: not wired; there is a TODO (`providers/gemini.py:92`).

So an ephemeral step on claude or gemini silently runs without the granted MCP
servers. It fails closed (no server is reachable) but gives no error. The
deployed sandbox image build was not verified, only that source commit, so do
not assume granted MCP servers are available on ephemeral claude or gemini
steps. A stack-side rejection or a sandbox capability check for this case is
future work; see the cross-repo plan comment
https://github.com/jameswnl/lightspeed-stack/issues/51#issuecomment-6521645859.

Related, for future secrets and not the secretless catalog: the openai
provider's header resolver expects a `file:` string prefix (`mcp.py:26`), while
the stack writes `{"file": path}` dicts. Resolve that before secret delivery.

Trust and logging:

- Catalog URLs are operator-trusted and not SSRF-confined. MCP clients follow
  redirects, so a catalog URL also grants its redirect destinations. Loopback
  and IP literals load (local development uses them); this is not
  private-network protection.
- The canary/log guarantee (no caller-supplied token-shaped text in logs,
  audit, 4xx bodies beyond caller-facing denial messages) covers
  stack-controlled surfaces: submission, audit and our post-call
  `workflow_authorized` / `start_failed` records. It does not cover
  executor-internal logs, which log step names after `start`.

Deferred (stay in `cases.yaml` as `phase: 4` or `deferred`, each needs its own
reviewed plan before any work):

- **Secret delivery.** The OpenShell spawner reads the secret value from an
  env var named by `secret_name` and uses `key` only as a file name, so it does
  not fetch a K8s Secret key. A missing value logs a warning and continues, so
  the server would run unauthenticated; delivery needs fail-closed behaviour and
  runtime-only acquisition. The ephemeral bearer round-trip test must pass first.
- **Redirect leak.** `httpx` strips only `Authorization` on a cross-origin
  redirect, so headers such as `X-API-Key` would follow it. Any future secret
  support must enforce no redirects (or a redirect-safe transport) for
  secret-bearing servers.
- **Mount paths.** Validate `SecretBinding.key` for path safety, and reject two
  refs on one server that target the same file name
  (`/var/secrets/mcp/{server}/{key}`).
- **Inline host grants and SSRF confinement.** `inline_mcp`, `inline_mcp_hosts`,
  `mcp_secrets` and `ssrf` stay reserved (config load fails). Confinement needs
  redirect and resolved-address enforcement or an egress boundary.
- **`MCP_ALLOWED_SECRETS`.** Not generated or written now, since no secrets are
  injected. When it returns it must treat unset and explicitly empty
  differently and compare parsed sets, not raw strings.

---

## The two documents (read this first)

Everything in this folder is one of two documents. They are authored by
different people, live in different places, and are joined by the stack at
submit time:

| | `lightspeed-stack.yaml` | Workflow definition YAML |
|---|---|---|
| Author | Operator (platform team) | Caller (API user / pipeline) |
| Lives in | ConfigMap mounted into stack pods | `POST /v1/workflows/run` request body |
| Contains | Catalogs, secret bindings, policy, spawner, MCP URLs | Steps, prompts, logical names, schemas |
| Secrets | Backend *bindings* only (env var / K8s Secret names), never values | Nothing secret-related — logical names only |

Core principle: workflow payloads may contain logical references to approved
configuration, but never secret material. The stack resolves every logical
name against its catalogs, checks policy for the caller's roles, and only
then persists and starts the run — otherwise 400 (unknown to the deployment)
or 403 (exists, but not for you) before anything is saved.

---

## Part 1 — Operator setup (once per deployment, K8s)

### Step 1. Put API keys and secrets in K8s Secrets

Keys live only in K8s Secrets. In production, do not apply values by hand:
`external-secrets.yaml` syncs every Secret below from Vault through External
Secrets Operator (`k8s-secrets.yaml` is the bootstrap/dev equivalent with
`CHANGEME` placeholders; `verify.py` checks both define the same Secrets and
keys). The Secrets:

- `lightspeed-inference-creds`: `ANTHROPIC_API_KEY`, `OPENAI_TEAM_B_KEY`
  (inference keys; pre-cloud-agents#269 bindings must be `backend: env`
  because cloud-agents reads `os.environ` by key).
- `openshell-gateway-tls`: mTLS client identity for stack → gateway.
- `lightspeed-postgres`: `password` for the workflow-state database.
- `lightspeed-postgres-tls`: CA for `ssl_mode: verify-full`.

```bash
# Fill in every CHANGEME value first, then:
kubectl apply -n lightspeed -f k8s-secrets.yaml      # dev / bootstrap
kubectl apply -n lightspeed -f external-secrets.yaml  # production
```

`k8s-deployment.yaml` wires them into the stack Deployment (non-root,
read-only rootfs, no capabilities, digest-pinned image, default-deny egress
NetworkPolicy, no Secret-read RBAC before #269). Excerpt — inference
keys and DB password as env, TLS as mounted files:

```yaml
# lightspeed-stack Deployment (excerpt)
env:
  - name: ANTHROPIC_API_KEY
    valueFrom: {secretKeyRef: {name: lightspeed-inference-creds, key: ANTHROPIC_API_KEY}}
  - name: OPENAI_TEAM_B_KEY
    valueFrom: {secretKeyRef: {name: lightspeed-inference-creds, key: OPENAI_TEAM_B_KEY}}
  - name: POSTGRES_PASSWORD
    valueFrom: {secretKeyRef: {name: lightspeed-postgres, key: password}}
volumeMounts:
  - {name: gw-tls, mountPath: /etc/openshell-tls, readOnly: true}
volumes:
  - name: gw-tls
    secret: {secretName: openshell-gateway-tls}
```

Pre-#269 the stack's ServiceAccount needs no `get` on any Secret (inference
keys arrive as env and catalog MCP is secretless). Post-#269 it needs `get` on
the inference Secret only (`resourceNames`, least privilege; `verify.py` checks
the list matches the registry).

### Step 2. Define the provider catalog, secret registry, and defaults

In `lightspeed-stack.yaml` under `workflow_engine` (`PLAN(stack#51)`):

- `providers`: one entry per logical provider. Each has exactly one
  `credential`, so choosing a credential means choosing an entry.
  `executor_type` must be in cloud-agents `APPROVED_INFERENCE_PROVIDERS`;
  `allowed_models: null` means any model (`[]` fails load).
- `secrets`: logical ref → backend binding (`env` / `k8s` / `file`).
- `default_provider` / `default_model`: the only defaults on cloud-agents
  paths. `inference.default_*` become Llama Stack-only.

This example ships two entries: `claude-prod` (anthropic,
`inference/anthropic-prod`, models pinned) and
`openai-team-b` (openai, `inference/openai-team-b`, any model).

Config load fails fast instead of misbehaving at runtime: unknown
`executor_type`, dangling ref, `allowed_models: []`, or bad defaults.

### Step 3. Register secretless MCP servers

Each `mcp_servers[*]` entry carries the operator-owned URL. Add
`workflow_enabled: true` to offer it to workflow steps by name (default
`false`). This example has `github-readonly` and `kb-search`, both secretless.
There is no `secret_headers` field in this phase (the load rejects it).

Catalog URLs are trusted operator input. They are not SSRF-confined (MCP
clients follow redirects, so a catalog URL also grants its redirect
destinations), and they are not private-network protection. Do not embed
credentials in a URL or its query string (an enabled entry whose URL has a
query string or fragment triggers a startup warning); entries with
`user:pass@` are refused at load. A policy `mcp` grant (a list of catalog names, or `["*"]`)
gives every tool on that server, and an unknown name and a non-enabled name
are indistinguishable from a 400 but a known enabled server without a grant
is a 403. See "Phase 3 scope" above for the full list of behaviour changes.

Refused at load for `workflow_enabled` entries: any `authorization_headers`
(including request-bound `client`/`oauth`/`kubernetes`), non-empty propagated
`headers` (e.g. `x-rh-identity`; a detached run has no incoming request, and
silently dropping an identity header would run the server without the caller's
identity), `require_approval` other than `never`, non-http(s) or hostless URLs,
userinfo in the URL, names not matching `^[a-z0-9][a-z0-9-]{0,62}$`, and a name
shared with any other `mcp_servers` entry. A policy `mcp` entry naming a server
that is not `workflow_enabled` also fails the load.

### Step 4. Provide skills via the sandbox image, govern with policy

Skills are directories baked into the sandbox image — the plan does not
change skill packaging:

```dockerfile
FROM quay.io/example/lightspeed-agentic-sandbox@sha256:a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4
COPY ./skills/triage /skills/triage
COPY ./skills/kb-search /skills/kb-search
```

Enforcement differs by spawn mode: ephemeral gets a per-spawn Landlock
read-only grant on `/skills/<name>`; none/local get a
`SkillsCapability(include=[...])` allow-list. Default is least privilege:
omitted `allowed_skills` means no skills visible, not all. Which roles may
request which skill names is policy (next step). `advisory: true` (blanket
filesystem read in the sandbox) needs an explicit grant.

### Step 5. Write policy rules per role

`workflow_engine.policy.rules`: each rule names a `role` (`"*"` matches every
caller) and grants lists (`providers`, `skills`, `tools`, `images`,
`service_accounts`, `namespaces`, `spawn_modes`), an `advisory` flag and
numeric `limits`. A principal's grant is the union of the rules for its roles
and everything they `inherit`; a missing or empty list grants nothing and
`["*"]` grants any value. Nothing is granted by default except the spawner's
default image, and unset or empty service accounts (the spawner
configuration has no default service account today). Coarse RBAC (`WORKFLOW_START` etc.
in `authorization`) still gates "may submit at all"; policy gates "may use
this". The policy requires governed mode (a `providers` catalog), and a policy
that grants anything to a role other than `*` requires `jwk-token` auth with
`role_rules` and `access_rules`.

`tools` governs a step's `tools` and `permissions.allowed_tools`;
`denied_tools` only restricts and needs no grant. The executor gives advisory
sandboxes read access to all of `/skills` regardless of `allowed_skills`, so
granting `advisory` effectively grants every skill.

#### Tools on ephemeral steps (`tools_not_enforceable`)

A finite `tools` grant would be a promise nobody keeps today, so in policy mode
every ephemeral agent step needs an explicit wildcard `tools` grant (`["*"]`
after the union and inherit closure). A missing, null, `[]` or finite grant is
a 403 with reason `tools_not_enforceable`, pointing at the step's `permissions`
object (the spec-level one when inherited, the step itself when permissions
are defaulted). It does not matter what `allowed_tools` the request declares
or omits, and a finite operator grant is never promoted to a wildcard.

The wildcard authorizes the sandbox's default, unrestricted tool access. It
does not promise that a caller-supplied finite `allowed_tools` list is
enforced: that list is not enforced (see the evidence below).

| Spawn mode | `tools` grant check | Notes |
|---|---|---|
| `ephemeral` | explicit `["*"]` required, else `tools_not_enforceable` | wildcard passes whatever `allowed_tools` says |
| `none`, `local` | `step.tools` and `allowed_tools` names checked against the grant | admin only; the direct runner never reads `permissions.allowed_tools` and omitted `step.tools` means no tools; this README does not claim `allowed_tools` or `denied_tools` is enforced there |
| no policy | not checked | unchanged |

Consumer evidence (read from the code; the deployed image
`quay.io/jameswong/lightspeed-agentic-sandbox:latest` is a floating tag whose
build could not be verified, so treat this as the source at HEAD `619fb0c`):

- Producer: the installed cloud-agents sends `allowedTools` / `deniedTools`
  only when the list is truthy (`cloud_agents/workflow/core/step_runner.py:399-402`,
  `executor/temporal/activities.py:619-622`), so omitted, null and `[]` are
  identical on the wire: nothing is sent. `tests/unit/cloud_agents/test_workflow_producer_seam.py`
  runs that code and pins it. It documents the producer only.
- Consumer (`lightspeed-agentic-sandbox`, `src/lightspeed_agentic/`):
  `RunRequest` in `routes/models.py` has no `allowedTools` / `deniedTools`
  fields; `routes/query.py:163` (with `tools.py:5`) always passes
  `DEFAULT_ALLOWED_TOOLS` = Bash, Read, Glob, Grep, Skill; the Claude provider
  runs with `permission_mode=bypassPermissions` (`providers/claude.py:95-97`),
  and the SDK treats `allowed_tools` as an auto-approve list, not a restriction.

So today the sandbox does not enforce `permissions.allowed_tools` or
`denied_tools` for ephemeral steps. A captured `allowedTools` field is not
proof of enforcement. Sandbox-side enforcement is an upstream assumption that
is not met, which is why the policy fails closed instead of trusting a finite
grant.

Restricting ephemeral steps to a finite tool list needs a separately reviewed
cross-repo capability: the sandbox accepts `allowedTools` / `deniedTools` and
enforces them (`tools=` / `disallowed_tools=`), the producer sends `[]` as
deny-all instead of dropping it, negative execution tests are bound to every
effective image digest and provider, and unknown images and providers fail
closed. Until then the wildcard grant is the only way to authorize ephemeral
execution.

Limits: each is `min(max over the caller's rules, hard cap)`, and an absent
limit grants 0. Hard caps: step timeout 3600s, workflow 86400s, 5 retries,
1,000,000 tokens. Because an omitted `permissions.max_tokens` counts as
unlimited, every agent step must declare one.

This example's roles:

- `*`: spawn mode `ephemeral`.
- `agent-user` (triage flow): `claude-prod`, skill `triage`, tools `["*"]`,
  service account `workflow-runner`, namespace
  `sandbox-workloads`, limits (900s per step, 3600s workflow, 2 retries,
  200k tokens).
- `agent-support` (KB flow): `openai-team-b`, skill `kb-search`, tools
  `["*"]`, service account `kb-runner`, same namespace, limits (1200s,
  3600s, 1 retry, 200k tokens).
- `agent-restricted`: the triage grants with a finite `tools` list
  (`github.read`). Ephemeral submissions are a 403 `tools_not_enforceable`;
  it is here as the worked rejection case.
- `agent-admin`: inherits both, plus `azure-eu`, `local`/`none` spawn (these
  also require admin, even if granted to someone else) and `advisory`. The
  legacy admin image override is gone in policy mode: admins need an `images`
  grant like everyone else.

`mcp` grants catalog servers by name (`["*"]` = every `workflow_enabled`
entry; missing, null or `[]` = none; union across roles). The example gives
`agent-user` `github-readonly`, `agent-support` `kb-search` and `agent-admin`
`["*"]`. A grant means every tool on that server. `inline_mcp`,
`inline_mcp_hosts`, `mcp_secrets` and `ssrf` are reserved: they fail config
load, so the example does not carry them. Inline MCP is admin-only without a
policy and denied for every caller with one.

#### What the limits mean at runtime

Only `max_retries` is enforced at runtime by the upstream executor (transient
failures only). The rest are declared budgets: the policy checks what a
submission declares, once, at submission. Nothing re-checks them while the run
executes.

| Limit | What the runtime does | Status |
|---|---|---|
| `max_retries` | enforced by the executor | enforced at runtime |
| step `timeout_seconds` for `none` and `ephemeral` | `none`: a per-LLM-request timeout; `ephemeral`: never read | declared budget |
| step `timeout_seconds` for `local` | hard kill of the subprocess | enforced upstream |
| `permissions.timeout_seconds` | per-operation HTTP timeout on the sandbox call, not a wall-clock ceiling | declared budget |
| `permissions.max_tokens` | no consumer | declared budget |
| workflow seconds (`max_workflow_seconds`) | no workflow deadline exists; the checked value is the sum over agent steps of `step_timeout x (max_retries + 1)`, excluding approval waits and overhead | declared budget |

The declared budgets are checked at submission only and are not security
boundaries: a run that declares a small budget is not stopped from exceeding
it. If the upstream executor starts enforcing one of them, the same declared
value becomes the limit.

### Step 6. Configure the spawner (OpenShell gateway on K8s)

```yaml
spawner:
  type: openshell
  openshell_gateway_url: "openshell-gateway.lightspeed.svc:443"
  openshell_workspace: lcore-prod
  sandbox_image: quay.io/example/lightspeed-agentic-sandbox@sha256:a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4
  openshell_tls_ca: /etc/openshell-tls/ca.crt      # from openshell-gateway-tls
  openshell_tls_cert: /etc/openshell-tls/tls.crt
  openshell_tls_key: /etc/openshell-tls/tls.key
  max_pods: 50
```

The gateway owns the K8s-vs-Podman compute decision; the stack proxies
sandbox lifecycle through it. Ephemeral sandboxes receive credentials via
OpenShell provider injection — placeholder in the sandbox env, value only in
the supervisor proxy.

### Step 7. Deploy and verify the boundary

```bash
kubectl -n lightspeed create configmap lightspeed-config \
  --from-file=lightspeed-stack.yaml=./lightspeed-stack.yaml
kubectl apply -f k8s-deployment.yaml
kubectl -n lightspeed rollout status deploy/lightspeed-stack
kubectl -n lightspeed logs deploy/lightspeed-stack | grep -i "config\|provider\|mcp"
```

Expected: clean start. Then
prove the denials from Part 2: caller-sent `credentials_secret` → 400,
unknown provider/MCP name → 400, valid-but-ungranted item → 403 with reasons,
`spawn: none` as `agent-user` on workflows → 403.

### Step 8. Rotation and revocation on K8s (pre-cloud-agents#269 rules)

- Update the value in Vault; External Secrets syncs the K8s Secret within
  `refreshInterval` and Reloader (annotation on the Deployment) **rolls the
  stack pods** so they pick up the new env values. By hand: `kubectl edit
  secret` + `kubectl rollout restart`. In-flight sandbox steps finish on the old value; new submissions
  use the new one after restart.
- Removing a ref from `secrets`/`policy` affects new submissions only —
  running steps are unaffected.
- After cloud-agents#269 (lease handoff), revocation fails closed at the
  next step (`credential_revoked`) and rotation applies at the next
  `acquire_value` with no restart.

---

## Part 2 — Caller: author and trigger a workflow (per run)

### Step 9. Author the `WorkflowDefinition`

Schema: `apiVersion` / `kind: AgentWorkflow` / `metadata` / `spec`, optional
top-level `provider` default and `skills` image. Per step:

- **Input**: `spec.input_prompt`, per-step `prompt` templates with
  `{{ steps.X.output.Y }}` references, per-step `context` dicts.
- **Output**: per-step `output_key` (state key) and optional `output_schema`
  (dict/JSON-schema constraining that step's output). No workflow-level
  output schema — results are read from state/transcripts.
- **Needs**: `mcp_servers` (catalog **names**), `allowed_skills`, `tools` /
  `permissions` (service account, `allowed_tools`, `max_tokens`),
  `target_namespaces`, `timeout_seconds`, `max_retries`, `spawn`.
- **Provider**: run-level `ProviderSelection {name, model, credential_ref?}`
  travels in the API request, not the definition. Optional
  `definition.provider` and per-step `inference_provider` must resolve to the
  **same catalog entry** as the run provider (same-entry rule; model may
  differ). Omit `credentials_secret` everywhere — it is rejected (400).
- **Never include**: secret values, raw `{secret_name, key}` headers, env var
  names, K8s Secret names, arbitrary images.

Merge rules the policy engine applies per step (same precedence as
cloud-agents' normalizer): `spawn` = step → workflow → `ephemeral`;
`mcp_servers` / `allowed_skills` / `permissions` / `service_account` = step →
workflow where `None` inherits and `[]` means explicitly empty;
`sandbox_image` = step `spawn_config` → workflow `spawn_config` → run value
→ spawner default; provider = step → `definition.provider` → run provider.

The workflow definitions in this folder (plus `admin-inline-mcp.yaml`, Part 3):

- `triage-github-issue.yaml`: triage → report; inherits run provider
  `claude-prod`; workflow-default MCP/skills with the `report` step opting
  out via `[]`.
- `kb-answer-with-approval.yaml`: research → human-approval `review` →
  respond; `definition.provider` = run entry `openai-team-b`; `research`
  overrides to model `gpt-4o-mini` on the same entry (allowed).

### Step 10. Trigger it: `POST /v1/workflows/run`

The definition travels inline in `definition`; the run-level provider is a
logical `ProviderSelection`. No secret material anywhere in the request.
The 8-step gate (authenticate → size → parse → catalog → policy → executor
validate → persist/start → audit) runs before anything is saved → `202`.

Triage flow (as `agent-user`):

```bash
DEFN=$(python3 -c "import json,yaml;print(json.dumps(yaml.safe_load(open('triage-github-issue.yaml'))))")
curl -s -X POST https://lightspeed.example.com/v1/workflows/run \
  -H "Authorization: Bearer $USER_TOKEN" -H 'Content-Type: application/json' \
  -d "$(jq -n --argjson defn "$DEFN" '{definition: $defn,
        provider: {name: "claude-prod", model: "claude-sonnet-4-5"}}')"
# -> 202 {"workflow_id": "<id>", "status": "running"}
```

KB flow (as `agent-support`):

```bash
DEFN=$(python3 -c "import json,yaml;print(json.dumps(yaml.safe_load(open('kb-answer-with-approval.yaml'))))")
curl -s -X POST https://lightspeed.example.com/v1/workflows/run \
  -H "Authorization: Bearer $SUPPORT_TOKEN" -H 'Content-Type: application/json' \
  -d "$(jq -n --argjson defn "$DEFN" '{definition: $defn,
        provider: {name: "openai-team-b", model: "gpt-4o"}}')"
# -> 202 {"workflow_id": "<id>", "status": "running"}
```

### Step 11. Follow the run; approve the gate

```bash
# Status / transcripts (both flows)
curl -s https://lightspeed.example.com/v1/workflows/<id> \
  -H "Authorization: Bearer $TOKEN"
curl -s https://lightspeed.example.com/v1/workflows/<id>/transcripts \
  -H "Authorization: Bearer $TOKEN"

# KB flow pauses at the `review` step; a role with workflow_approve continues it:
curl -s -X POST https://lightspeed.example.com/v1/workflows/<id>/approve \
  -H "Authorization: Bearer $SUPPORT_TOKEN" -H 'Content-Type: application/json' \
  -d '{"step_name": "review", "decision": "approved", "approver": "support-lead"}'

# Cancel a running workflow (role needs workflow_cancel):
curl -s -X POST https://lightspeed.example.com/v1/workflows/<id>/cancel \
  -H "Authorization: Bearer $TOKEN"
```

Denials to try: add `"credentials_secret"` to the request → 400; unknown
provider/MCP name → 400; `openai-team-b` as `agent-user` → 403; a step naming
a different catalog entry than the run provider → 400 (same-entry rule);
`spawn: none` as non-admin on workflows → 403.

---

## Part 3 — Other surfaces

> Chat on cloud-agents (`/query/direct`) is out of scope here; it was removed and is
> tracked in [#59](https://github.com/jameswnl/lightspeed-stack/issues/59).

### Admin inline MCP

`admin-inline-mcp.yaml` is the Phase 4 target for the exception path: `https`
only, no userinfo, host in `inline_mcp_hosts`, no literal headers, and
`secret_headers` as registry refs (`{name: mcp/incidents}`) that the stack
rewrites to cloud-agents' form and that must also be granted via
`mcp_secrets`. None of that is built. Today the file is rejected with a 422
before the run starts (the executor cannot deliver the ref), a raw
`{secret_name, key}` is a 400, and inline MCP without `secret_headers` is
admin-only without a policy and a 403 for everyone with one. `cases.yaml`
keeps the Phase 4 expectations. Prefer a catalog entry; follow-up: named
workflow templates so trusted pipelines do not need inline MCP.

### Audit events

Every decision leaves one structured, names-only event on the dedicated
`audit` logger (route it to its own sink). Examples of what operators should
see for the flows above:

```json
{"event": "workflow_authorized", "principal": "alice", "roles": ["agent-user"],
 "workflow_id": "wf-8f2c", "provider": "claude-prod", "model": "claude-sonnet-4-5",
 "credential_ref": "inference/anthropic-prod", "mcp_servers": ["github-readonly"],
 "spawn": {"triage": "ephemeral", "report": "ephemeral"}}
{"event": "workflow_denied", "principal": "alice", "status": 403,
 "reasons": ["provider 'openai-team-b' not granted"]}
{"event": "secret_accessed", "workflow_id": "wf-8f2c", "step": "triage",
 "purpose": "inference:anthropic", "ref": "inference/anthropic-prod",
 "backend": "k8s", "outcome": "granted"}
{"event": "lease_released", "workflow_id": "wf-8f2c", "step": "triage",
 "purpose": "inference:anthropic", "reason": "completed"}
```

No secret value appears in any event, log line, span attribute, metric label,
state record, transcript or API response (Phase 4 canary suite).

### After cloud-agents#269 (`post-269-overrides.yaml`)

The default `k8s-deployment.yaml` gives the stack ServiceAccount no Secret
reads. Once #269 lands, apply the overlay deliberately (it is not in the
default apply set):

```bash
kubectl apply -f post-269-rbac.yaml   # get on lightspeed-inference-creds only
```

`verify.py` runs every case against both stages, so you can see exactly what
changes:

| | Before cloud-agents#269 | After |
|---|---|---|
| Inference credential binding | `backend: env`; stack must be restarted to rotate | `backend: k8s`; read by the stack through the lease provider |
| Handoff | names (`env` key, K8s Secret name) | short-lived lease per step, redeemed then released; cross-process via mTLS |
| Revocation | new submissions only | next step fails closed (`credential_revoked`) |
| Rotation | restart | next lease, no restart |
| Same-entry rule | enforced | can relax (each step has its own lease) |
| `spawn: none` / `local` | admin-only (process-wide env) | admin-only lifted once cloud-agents isolates them |
| Stack RBAC | none (no Secrets read via the API) | `get` on the inference Secret |

## Gaps in the plan found while building these examples

Folded into the plan in revision 3 (phase in brackets):

1. **Inline MCP refs vs the typed parse.** cloud-agents' `MCPServerConfig`
   accepts `secret_headers` only as `{secret_name, key}` (`extra=forbid`), so a
   registry ref `{name: ...}` fails the typed parse with 422. Phase 3 keeps
   that as the answer (no rewrite hook). A rewrite for the shape check is
   modelled in `reference_gate._shape_copy` for Phase 4.
2. **`MCP_ALLOWED_SECRETS` and inline-granted secrets.** Deferred with secret
   delivery: nothing generates it now. The generator must cover secrets that
   are reachable only through `mcp_secrets`, and treat unset and empty
   differently.
3. **`ADMIN` is never in `authorized_actions`.** Admin gates use the access
   resolver with roles stored on `request.state.user_roles` (PR #57), and no-op
   auth modules (`k8s`, `noop`, `api-key`) make every caller admin [0a done;
   load check in Phase 2, decision D8].
4. **`Authorization` header values.** The K8s Secret would hold the full header
   value (including `Bearer `); confirm cloud-agents does not add a prefix
   (part of the deferred secret delivery round-trip test).

---

## Verification

`verify.py` is the executable contract. Run it from the repo root with the
project venv:

```bash
uv run python examples/workflows/verify.py
```

What it checks (~137 assertions):

- Every file parses; all three definitions pass the real cloud-agents
  `WorkflowDefinition` shape check.
- `lightspeed-stack.yaml` loads through the real `WorkflowEngineConfiguration`
  catalog, defaults, policy) and passes the remaining load-time check in
  both stages (post-#269 credential bindings), and each load failure is also
  pinned as a negative case.
- `cases.yaml`: cases up to `IMPLEMENTED_PHASE` (credentials, catalog, policy,
  spawn, images, advisory, limits, named MCP) run against the real handler and
  config. `phase: 4` cases (inline MCP with host grants) run in `pre269` and
  `post269` against the reference model; `deferred` cases run nowhere and must
  carry a `deferred_reason`.
- The example, MCP catalog and policy `mcp` grants included, validates against
  the current `Configuration` schema.
- The real `JwtRolesResolver` / `GenericAccessResolver` give the roles and
  admin semantics the policy assumes.
- Deployment cross-checks: env injection matches the registry, no MCP
  Secrets or `MCP_ALLOWED_SECRETS`, RBAC `resourceNames` match the K8s-bound
  Secrets, pod hardening,
  digest-pinned images, and the dev and External Secrets sources agree.

Each case in `cases.yaml` carries a `phase`. The unit test
`tests/unit/cloud_agents/test_workflow_contract.py` runs the cases up to
`IMPLEMENTED_PHASE` (in `contract_util.py`, currently 3) against the real
handler, including `@authorize` with the example's access rules and the case's
`as` roles (`stack_set` patches the stack config for one case, for example to
drop the policy), and the real configuration. It compares status plus
`denied_contains` when a case sets it, and skips later cases.
`reference_gate.py` is a model of the design for Phase 4 (inline MCP), not the
implementation. Finishing a phase means raising `IMPLEMENTED_PHASE`, dropping
the matching `PENDING_ENGINE_KEYS`, and deleting that part of the reference.

## Production checklist

- Images pinned by digest (stack, sandbox, policy `images`).
- Values only in the secret manager; K8s Secrets synced, never committed.
- Role-resolving auth (`jwk-token` with `role_rules` and `access_rules`), not
  `k8s`/`noop`; `rh-identity` and `trusted-proxy` only resolve the `*` role.
- `ssl_mode: verify-full` to Postgres; mTLS to the OpenShell gateway.
- Least-privilege RBAC by `resourceNames`; default-deny egress NetworkPolicy.
- Audit logger routed to a separate sink; alerts on `workflow_denied` spikes.
- Rotation runbook: pre-#269 restart via Reloader; post-#269 next lease.
- Deprecation window for the legacy `{name, model}` provider form
  (`Deprecation` / `Sunset` headers) communicated to callers before Phase 1.
