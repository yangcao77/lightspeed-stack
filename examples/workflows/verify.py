"""Verify the examples/workflows contract (stack#51 + cloud-agents#269).

Run from anywhere with the project venv:

    uv run python examples/workflows/verify.py

1. Every file parses; the three workflow definitions pass the real
   cloud-agents ``WorkflowDefinition`` shape check.
2. ``lightspeed-stack.yaml`` passes the real config load (Phases 0-3) and the
   remaining load-time checks in ``reference_gate.py``, before and after
   cloud-agents#269 (``post-269-overrides.yaml`` merged on top).
3. ``cases.yaml``: cases up to ``IMPLEMENTED_PHASE`` run against the real
   endpoint and config (pre-269, the stage the code implements); phase 4
   cases run via ``reference_gate.py``; ``deferred`` cases run nowhere.
4. The example validates against the CURRENT ``Configuration`` (MCP catalog
   and policy ``mcp`` grants included).
5. Auth: real role and access resolvers behave as the policy assumes.
6. Deployment: Deployment, RBAC and Secrets agree with the stack config.
"""

import asyncio
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

WF_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(WF_DIR.parent.parent / "src"))
sys.path.insert(0, str(WF_DIR))

import reference_gate as gate
from contract_util import (
    case_body,
    config_load_error,
    current_schema_stack,
    deep_merge,
    engine_config,
    is_real,
    is_reference,
    load,
    load_all,
    patch,
    run_real_case_detail,
)

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    """Record and print one assertion."""
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


# ---------------------------------------------------------------- 1. parsing
stack = load("lightspeed-stack.yaml")
overrides = load("post-269-overrides.yaml")
stacks = {"pre269": stack, "post269": deep_merge(stack, overrides)}
cases = load("cases.yaml")
definitions = {
    name: load(f"{name}.yaml")
    for name in ("triage-github-issue", "kb-answer-with-approval", "admin-inline-mcp")
}
for doc in ("k8s-secrets.yaml", "external-secrets.yaml", "k8s-deployment.yaml"):
    load_all(doc)
check(True, "all YAML files parse")

from cloud_agents.workflow.core.definition import WorkflowDefinition

for name, raw in definitions.items():
    WorkflowDefinition.model_validate(gate._shape_copy(raw))  # pylint: disable=W0212
    check(True, f"{name}: WorkflowDefinition shape valid")

from cloud_agents.workflow.core.validation import validate_definition

for name, raw in definitions.items():
    problems = validate_definition(gate.executor_form(stacks["pre269"], raw))
    check(problems == [], f"{name}: passes cloud-agents validate_definition {problems}")

# ------------------------------------------------------------ 2. load checks
# The real engine configuration is the pre-269 implementation (env-bound
# inference credentials), so it loads the pre269 stack only.
engine = engine_config(stack)
check(
    engine.governed and engine.policy is not None,
    "real WorkflowEngineConfiguration loads the example (policy included)",
)
for stage, cfg in stacks.items():
    errors = gate.load_errors(cfg, stage)
    check(
        errors == [], f"{stage}: config passes the remaining load-time checks {errors}"
    )


# ------------------------------------------------------------------ 3. cases
def run(fn, *args, **kwargs):
    """Return (status, reasons) the reference gate gives."""
    try:
        fn(*args, **kwargs)
        return 202, []
    except gate.Denied as exc:
        return exc.status, exc.reasons


def assert_case(label, stage, got, reasons, case):
    """Check status and (optionally) a reason substring."""
    exp = case["expect"]
    want = exp[stage] if isinstance(exp, dict) else exp
    ok = got == want
    if ok and case.get("reason") and want != 202:
        ok = any(case["reason"].lower() in r.lower() for r in reasons)
    detail = "" if ok else f" (got {got} {reasons[:2]})"
    check(ok, f"[{stage}] {label} -> {want}{detail}")


for case in cases["workflow_cases"]:
    dflt = cases["defaults"][case["workflow"]]
    if not is_real(case) and not is_reference(case):
        check(
            bool(case.get("deferred_reason")),
            f"[deferred] {case['name']} has a deferred_reason",
        )
        continue
    if is_real(case):
        want = case["expect"]
        want = want["pre269"] if isinstance(want, dict) else want
        status, started, denied = asyncio.run(
            run_real_case_detail(case, stack, definitions, cases["defaults"])
        )
        ok = status == want and started == (status == 202)
        if ok and "denied_contains" in case:
            ok = any(case["denied_contains"] in message for message in denied)
        check(
            ok, f"[real] {case['name']} -> {want}" + ("" if ok else f" (got {status})")
        )
        continue
    for stage, cfg in stacks.items():
        body = case_body(case, definitions, cases["defaults"])
        status, reasons = run(gate.submit, body, set(case.get("as", dflt["as"])))
        assert_case(case["name"], stage, status, reasons, case)

for case in cases["config_cases"]:
    if is_real(case):
        if case.get("stage", "pre269") != "pre269":
            continue
        with tempfile.TemporaryDirectory() as tmp_dir:
            msg = config_load_error(stack, case, tmp_dir)
        ok = case["error"].lower() in msg.lower()
        check(ok, f"[real] config: {case['name']} -> load fails")
        continue
    if not is_reference(case):
        check(
            bool(case.get("deferred_reason")),
            f"[deferred] config: {case['name']} has a deferred_reason",
        )
        continue
    for stage, cfg in stacks.items():
        if case.get("stage", stage) != stage:
            continue
        errors = gate.load_errors(patch(cfg, case["set"]), stage)
        ok = any(case["error"].lower() in e.lower() for e in errors)
        extra = "" if ok else f" (got {errors})"
        check(ok, f"[{stage}] config: {case['name']} -> load fails{extra}")

# ------------------------------------------------------ 4. current schema
os.environ.setdefault("POSTGRES_PASSWORD", "test-only")
from models.config import AccessRule, Action, Configuration, JwtRoleRule

with tempfile.TemporaryDirectory() as tmp:
    Configuration.model_validate(current_schema_stack(stack, tmp))
check(
    True,
    "example validates against CURRENT Configuration schema (MCP catalog and policy included)",
)

# --------------------------------------------------------------- 5. auth
from authorization.resolvers import (
    GenericAccessResolver,
    JwtRolesResolver,
)

jwt_cfg = stack["authentication"]["jwk_config"]["jwt_configuration"]
roles_resolver = JwtRolesResolver([JwtRoleRule(**r) for r in jwt_cfg["role_rules"]])
access = GenericAccessResolver(
    [AccessRule(**r) for r in stack["authorization"]["access_rules"]]
)


def b64(data):
    """Base64url-encode a JSON object (unsigned test token part)."""
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def roles_for(token_roles):
    """Resolve roles for an unsigned token carrying the given realm roles."""
    token = ".".join(
        [b64({"alg": "none"}), b64({"realm_access": {"roles": token_roles}}), "sig"]
    )
    return asyncio.run(roles_resolver.resolve_roles(("uid", "user", False, token)))


user = roles_for(["lightspeed-agent-user"])
support = roles_for(["lightspeed-agent-support"])
admin = roles_for(["lightspeed-agent-admin"])
check(
    "agent-user" in user and "agent-support" in support and "agent-admin" in admin,
    "token roles map to agent-user/support/admin",
)
check(access.check_access(Action.WORKFLOW_START, user), "agent-user may start")
check(
    not access.check_access(Action.WORKFLOW_APPROVE, user), "agent-user may not approve"
)
check(
    access.check_access(Action.WORKFLOW_APPROVE, support), "agent-support may approve"
)
check(
    not access.check_access(Action.ADMIN, support)
    and not access.check_access(Action.ADMIN, user),
    "only agent-admin is admin",
)
check(access.check_access(Action.ADMIN, admin), "agent-admin is admin")

# ---------------------------------------------------------- 6. deployment
by_kind: dict[str, list[dict]] = {}
for d in load_all("k8s-deployment.yaml"):
    by_kind.setdefault(d["kind"], []).append(d)
pod = by_kind["Deployment"][0]["spec"]["template"]["spec"]
ctr = pod["containers"][0]
env = {e["name"]: e for e in ctr["env"]}
pre = stacks["pre269"]["workflow_engine"]["secrets"]
post = stacks["post269"]["workflow_engine"]["secrets"]

env_refs = {}
for binding in (b for b in pre if b["backend"] == "env"):
    ref = env.get(binding["env"], {}).get("valueFrom", {}).get("secretKeyRef")
    check(
        ref is not None,
        f"Deployment injects {binding['env']} from a Secret ({binding['name']})",
    )
    if ref:
        env_refs[binding["env"]] = (ref["name"], ref["key"])
check(
    not any(e["name"] == "MCP_ALLOWED_SECRETS" for e in ctr["env"]),
    "no MCP_ALLOWED_SECRETS: catalog MCP is secretless, nothing is generated",
)
check(
    not any(b["name"].startswith("mcp/") for b in pre + post),
    "no MCP secret bindings in either stage",
)

roles_by_name = {r["metadata"]["name"]: r for r in by_kind["Role"]}


def granted(role_name):
    """resourceNames the Role grants get on."""
    return set(roles_by_name[role_name]["rules"][0]["resourceNames"])


def k8s_names(secrets):
    """K8s Secret names bound with backend: k8s."""
    return {s["secret_name"] for s in secrets if s["backend"] == "k8s"}


check(
    k8s_names(pre) == set() and "lightspeed-stack-secret-reader" not in roles_by_name,
    "pre-269 binds no k8s Secrets and defines no Secret reader Role",
)
check(
    granted("lightspeed-stack-secret-reader-post-269") == k8s_names(post),
    "post-269 Role grants get on exactly the k8s-bound Secrets",
)
for role in roles_by_name.values():
    check(
        role["rules"][0]["verbs"] == ["get"],
        f"{role['metadata']['name']}: get only, by resourceName",
    )

check(pod["securityContext"]["runAsNonRoot"] is True, "pod runs as non-root")
sc = ctr["securityContext"]
check(
    sc["readOnlyRootFilesystem"]
    and not sc["allowPrivilegeEscalation"]
    and sc["capabilities"]["drop"] == ["ALL"],
    "container hardened",
)
mounts = {m["name"]: m["mountPath"] for m in ctr["volumeMounts"]}
spawner = stack["spawner"]
check(
    spawner["openshell_tls_ca"].startswith(mounts["gw-tls"]),
    "gateway TLS paths match the mount",
)
check(
    stack["database"]["postgres"]["ca_cert_path"].startswith(mounts["pg-tls"]),
    "Postgres CA path matches the mount",
)
check(
    stack["database"]["postgres"]["ssl_mode"] == "verify-full",
    "Postgres uses verify-full TLS",
)
check(
    all("@sha256:" in i for i in (ctr["image"], spawner["sandbox_image"])),
    "stack and sandbox images pinned by digest",
)
policy_images = {
    i for r in stack["workflow_engine"]["policy"]["rules"] for i in r.get("images", [])
}
check(all("@sha256:" in i for i in policy_images), "policy images pinned by digest")

# Secrets: dev manifest and External Secrets define the same names and keys,
# and cover every Secret/key the stack references in either stage.
dev_docs = load_all("k8s-secrets.yaml")
dev = {
    d["metadata"]["name"]: set((d.get("stringData") or d.get("data")).keys())
    for d in dev_docs
}
ext = {
    d["spec"]["target"]["name"]: {x["secretKey"] for x in d["spec"]["data"]}
    for d in load_all("external-secrets.yaml")
}
check(
    dev == ext,
    f"k8s-secrets.yaml and external-secrets.yaml match {sorted(set(dev) ^ set(ext))}",
)
needed = {(s["secret_name"], s["key"]) for s in post if s["backend"] == "k8s"}
needed |= set(env_refs.values())
check(
    all(k in ext.get(n, set()) for n, k in needed),
    "every referenced Secret/key exists in the secret source",
)
for d in dev_docs:
    values = (d.get("stringData") or d.get("data")).values()
    check(
        all("CHANGEME" in str(v) for v in values),
        f"{d['metadata']['name']}: placeholders only",
    )

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("ALL CHECKS PASSED")
