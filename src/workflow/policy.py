"""Run-level authorization of workflow submissions (issue #51, Phase 2).

``authorize_workflow_submission`` decides whether a principal may run an
``EffectivePlan`` and returns every denial reason at once. It implements the
mode matrix of the Phase 2 plan:

* **Hard rule, every mode:** an ephemeral step without a configured spawner
  is denied.
* **No policy** (``workflow_engine.policy`` unset) keeps the Phase 0a rules:
  admins may use spawn ``none``/``local``, custom images and advisory mode;
  non-admins may not. The one deliberate tightening is that non-admins are
  denied inline MCP server entries; admin inline MCP passes through to the
  executor's own gates. Named MCP, provider, skills, tools, service accounts,
  namespaces and limits are not checked.
* **Policy present:** deny by default, admins included. Spawn ``none``/
  ``local`` additionally requires admin, and granting it to a non-admin never
  overrides that. Custom images need an ``images`` grant (the legacy admin
  image override is intentionally gone); the spawner's default image and
  default service account are the only implicit grants. Named and inline MCP
  are denied for everyone until Phase 3.

Grant semantics: a list grant that is missing, null or ``[]`` grants nothing;
``["*"]`` grants any value; a principal's grant is the union over the rules
of its roles (always including ``"*"``) and their inherit closure. ``advisory``
is OR-ed across rules. Each numeric limit is ``min(max over rules, hard cap)``
with an absent limit counting as 0.

Several checked values are declared budgets rather than runtime limits: the
upstream executor does not consume ``permissions.max_tokens``, does not hard
kill ``none``/``ephemeral`` steps at ``timeout_seconds`` and has no workflow
deadline, so ``max_workflow_seconds`` is checked against the declared budget
(the sum over agent steps of ``timeout x (max_retries + 1)``, approval waits
and overhead excluded). These checks are submission-time only and are not
security boundaries.

Each denial carries an ``AuditReason`` and a JSON pointer taken from the plan
(indices and fixed keys only); those two fields are safe to audit. Its
``message`` is for the caller and may name the denied value, so it must never
be logged or put in an audit record. The module is pure: no I/O, no logging.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Optional

from models.config import POLICY_WILDCARD, PolicyRule, WorkflowPolicy
from workflow.audit import AuditReason
from workflow.effective import (
    DEFAULT_SPAWN_MODE,
    DEFAULT_STEP_TIMEOUT_SECONDS,
    STEPS_POINTER,
    EffectivePlan,
    ImageSource,
    PlanValue,
    StepPlan,
)
from workflow.limits import (
    MAX_POLICY_RETRIES,
    MAX_POLICY_STEP_TIMEOUT_SECONDS,
    MAX_POLICY_TOKENS,
    MAX_POLICY_WORKFLOW_SECONDS,
)

# JSON pointers of request fields that are not part of a step plan.
PROVIDER_POINTER: Final[str] = "/provider"
WORKFLOW_ADVISORY_POINTER: Final[str] = "/definition/advisory"
DEFINITION_SKILLS_IMAGE_POINTER: Final[str] = "/definition/skills/image"
RUN_SANDBOX_IMAGE_POINTER: Final[str] = "/sandbox_image"

# Spawn modes that run outside a sandbox and always require admin.
PRIVILEGED_SPAWN_MODES: Final[frozenset[str]] = frozenset({"none", "local"})

# Spawn mode that needs a configured spawner.
EPHEMERAL_SPAWN_MODE: Final[str] = DEFAULT_SPAWN_MODE

# Image sources the caller chose (the others are service or executor defaults).
_CALLER_IMAGE_SOURCES: Final[frozenset[ImageSource]] = frozenset(
    {ImageSource.STEP, ImageSource.SPEC, ImageSource.REQUEST}
)


@dataclass(frozen=True)
class Principal:
    """The caller a submission is authorized for.

    Attributes:
        user_id: Identifier from the auth layer.
        is_admin: Whether the caller holds the ADMIN action.
        roles: The caller's roles (``request.state.user_roles``); ``"*"`` is
            always added so wildcard rules apply to everyone.
    """

    user_id: str
    is_admin: bool
    roles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        """Normalize roles to a frozenset that includes the wildcard role."""
        object.__setattr__(self, "roles", frozenset(self.roles) | {POLICY_WILDCARD})


@dataclass(frozen=True)
class PolicyDenial:
    """One reason a submission is denied.

    Attributes:
        reason: Reason code; safe to audit.
        path: JSON pointer into the request body, built from indices and
            fixed keys only; safe to audit.
        message: Short caller-facing explanation. It may name the denied
            value, so it must never be logged or audited.
    """

    reason: AuditReason
    path: str
    message: str


@dataclass(frozen=True)
class PolicyDecision:
    """Outcome of authorizing a submission.

    Attributes:
        denials: Every denial, in check order, without duplicate
            ``(reason, path)`` pairs. Empty means allowed.
    """

    denials: tuple[PolicyDenial, ...] = ()

    @property
    def allowed(self) -> bool:
        """Whether the submission is allowed, meaning there are no denials.

        Returns:
            True when there are no denials.
        """
        return not self.denials

    @property
    def reasons(self) -> tuple[AuditReason, ...]:
        """Distinct reason codes in first-seen order (audit-safe).

        Returns:
            The reason codes.
        """
        return tuple(dict.fromkeys(d.reason for d in self.denials))

    @property
    def paths(self) -> tuple[str, ...]:
        """JSON pointers of the denials, in order (audit-safe).

        Returns:
            The pointers.
        """
        return tuple(d.path for d in self.denials)


@dataclass(frozen=True)
class _ListGrant:
    """Union of one list grant over a principal's rules.

    Attributes:
        any_value: True when some rule grants ``["*"]``.
        values: The explicitly granted values.
    """

    any_value: bool
    values: frozenset[str]

    def allows(self, value: str) -> bool:
        """Whether a value is granted.

        Parameters:
            value: The requested value.

        Returns:
            True when the value is granted.
        """
        return self.any_value or value in self.values


@dataclass(frozen=True)
class _Grants:  # pylint: disable=too-many-instance-attributes
    """Everything a principal is granted under a policy.

    Attributes:
        providers: Granted catalog provider names.
        skills: Granted skills.
        tools: Granted tools.
        images: Granted sandbox images.
        service_accounts: Granted service accounts.
        namespaces: Granted namespaces.
        spawn_modes: Granted spawn modes.
        advisory: Whether advisory mode is granted.
        max_step_timeout_seconds: Effective step timeout limit.
        max_workflow_seconds: Effective declared workflow budget limit.
        max_retries: Effective retry limit.
        max_tokens: Effective declared token budget limit.
    """

    providers: _ListGrant
    skills: _ListGrant
    tools: _ListGrant
    images: _ListGrant
    service_accounts: _ListGrant
    namespaces: _ListGrant
    spawn_modes: _ListGrant
    advisory: bool
    max_step_timeout_seconds: int
    max_workflow_seconds: int
    max_retries: int
    max_tokens: int


def _list_grant(rules: Sequence[PolicyRule], name: str) -> _ListGrant:
    """Union one list grant over rules (missing, null and [] grant nothing).

    Parameters:
        rules: The principal's rules.
        name: Name of the list grant on ``PolicyRule``.

    Returns:
        The unioned grant.
    """
    values: set[str] = set()
    for rule in rules:
        values.update(getattr(rule, name) or ())
    return _ListGrant(
        any_value=POLICY_WILDCARD in values,
        values=frozenset(values - {POLICY_WILDCARD}),
    )


def _limit(rules: Sequence[PolicyRule], name: str, hard_cap: int) -> int:
    """Compute an effective numeric limit: min(max over rules, hard cap).

    Parameters:
        rules: The principal's rules.
        name: Name of the limit on ``PolicyLimits``.
        hard_cap: The hard cap for the limit.

    Returns:
        The effective limit; 0 when no rule sets it.
    """
    configured = (getattr(rule.limits, name) for rule in rules)
    return min(max((v for v in configured if v is not None), default=0), hard_cap)


def _grants_for(policy: WorkflowPolicy, roles: Iterable[str]) -> _Grants:
    """Compute a principal's grants from the inherit closure of its roles.

    Parameters:
        policy: The workflow policy.
        roles: The principal's roles, including ``"*"``.

    Returns:
        The principal's grants.
    """
    rules = policy.rules_for(roles)
    return _Grants(
        providers=_list_grant(rules, "providers"),
        skills=_list_grant(rules, "skills"),
        tools=_list_grant(rules, "tools"),
        images=_list_grant(rules, "images"),
        service_accounts=_list_grant(rules, "service_accounts"),
        namespaces=_list_grant(rules, "namespaces"),
        spawn_modes=_list_grant(rules, "spawn_modes"),
        advisory=any(rule.advisory for rule in rules),
        max_step_timeout_seconds=_limit(
            rules, "max_step_timeout_seconds", MAX_POLICY_STEP_TIMEOUT_SECONDS
        ),
        max_workflow_seconds=_limit(
            rules, "max_workflow_seconds", MAX_POLICY_WORKFLOW_SECONDS
        ),
        max_retries=_limit(rules, "max_retries", MAX_POLICY_RETRIES),
        max_tokens=_limit(rules, "max_tokens", MAX_POLICY_TOKENS),
    )


def _path(value: PlanValue[Any], fallback: str) -> str:
    """Return a plan value's pointer, or a fallback for executor defaults.

    Parameters:
        value: The plan value.
        fallback: Pointer used when the value is a default (no pointer).

    Returns:
        A JSON pointer.
    """
    return value.path if value.path is not None else fallback


def _spawner_denials(
    plan: EffectivePlan, spawner_configured: bool
) -> list[PolicyDenial]:
    """Apply the hard rule: ephemeral steps need a configured spawner.

    Parameters:
        plan: The effective plan.
        spawner_configured: Whether a spawner_configuration exists.

    Returns:
        One denial per ephemeral step when no spawner is configured.
    """
    if spawner_configured:
        return []
    return [
        PolicyDenial(
            AuditReason.SPAWN_MODE_NOT_ALLOWED,
            _path(step.spawn, step.path),
            "ephemeral steps require spawner_configuration",
        )
        for step in plan.steps
        if step.spawn.value == EPHEMERAL_SPAWN_MODE
    ]


def _caller_images(
    plan: EffectivePlan, definition_skills_image: Optional[str]
) -> list[tuple[str, str]]:
    """List images the caller chose, with their pointers.

    Parameters:
        plan: The effective plan.
        definition_skills_image: ``definition.skills.image``, if any.

    Returns:
        ``(image, pointer)`` pairs: the request image, the definition skills
        image, and each step image chosen by the step, the spec or the request.
    """
    images: list[tuple[str, str]] = []
    if plan.run_sandbox_image:
        images.append((plan.run_sandbox_image, RUN_SANDBOX_IMAGE_POINTER))
    if definition_skills_image:
        images.append((definition_skills_image, DEFINITION_SKILLS_IMAGE_POINTER))
    for step in plan.steps:
        if step.sandbox_image_source in _CALLER_IMAGE_SOURCES:
            images.append(
                (step.sandbox_image.value, _path(step.sandbox_image, step.path))
            )
    return images


def _is_default_image(
    image: str, plan: EffectivePlan, default_sandbox_image: Optional[str]
) -> bool:
    """Whether an image is the spawner default (an implicit grant).

    Parameters:
        image: The image.
        plan: The effective plan.
        default_sandbox_image: The spawner's configured default image.

    Returns:
        True when the image is the spawner default.
    """
    return image in {default_sandbox_image, plan.spawner_default_image} - {None}


def _mcp_entries(step: StepPlan) -> list[tuple[bool, str, Any]]:
    """List a step's MCP server entries.

    Parameters:
        step: The step plan.

    Returns:
        ``(is_inline, pointer, entry)`` triples; a string entry is a named
        catalog reference, anything else is treated as inline.
    """
    servers = step.mcp_servers.value or ()
    base = _path(step.mcp_servers, step.path)
    return [
        (not isinstance(entry, str), f"{base}/{index}", entry)
        for index, entry in enumerate(servers)
    ]


def _legacy_denials(
    plan: EffectivePlan,
    *,
    default_sandbox_image: Optional[str],
    advisory: bool,
    definition_skills_image: Optional[str],
) -> list[PolicyDenial]:
    """Apply the Phase 0a non-admin rules plus the inline MCP tightening.

    Parameters:
        plan: The effective plan.
        default_sandbox_image: The spawner's configured default image.
        advisory: Whether the definition requests advisory mode.
        definition_skills_image: ``definition.skills.image``, if any.

    Returns:
        Denials for spawn none/local, advisory, custom images and inline MCP.
    """
    denials: list[PolicyDenial] = []
    for step in plan.steps:
        if step.spawn.value in PRIVILEGED_SPAWN_MODES:
            denials.append(
                PolicyDenial(
                    AuditReason.SPAWN_MODE_NOT_ALLOWED,
                    _path(step.spawn, step.path),
                    f"spawn mode '{step.spawn.value}' requires admin",
                )
            )
    if advisory:
        denials.append(
            PolicyDenial(
                AuditReason.POLICY_DENIED,
                WORKFLOW_ADVISORY_POINTER,
                "advisory mode requires admin",
            )
        )
    for image, path in _caller_images(plan, definition_skills_image):
        if not _is_default_image(image, plan, default_sandbox_image):
            denials.append(
                PolicyDenial(
                    AuditReason.IMAGE_NOT_ALLOWED,
                    path,
                    f"custom sandbox image '{image}' requires admin",
                )
            )
    for step in plan.steps:
        for is_inline, path, _ in _mcp_entries(step):
            if is_inline:
                denials.append(
                    PolicyDenial(
                        AuditReason.MCP_NOT_ALLOWED,
                        path,
                        "inline MCP servers require admin",
                    )
                )
    return denials


def _grant_denial(
    grant: _ListGrant, value: str, path: str, label: str
) -> list[PolicyDenial]:
    """Deny a value that a list grant does not cover.

    Parameters:
        grant: The list grant.
        value: The requested value.
        path: JSON pointer of the value.
        label: Human name of the grant kind for the message.

    Returns:
        A single denial, or an empty list when granted.
    """
    if grant.allows(value):
        return []
    return [
        PolicyDenial(
            AuditReason.POLICY_DENIED, path, f"{label} '{value}' is not granted"
        )
    ]


def _limit_denial(value: int, limit: int, path: str, label: str) -> list[PolicyDenial]:
    """Deny a numeric value above its effective limit.

    Parameters:
        value: The requested value.
        limit: The effective limit.
        path: JSON pointer of the value.
        label: Human name of the value for the message.

    Returns:
        A single denial, or an empty list when within the limit.
    """
    if value <= limit:
        return []
    return [
        PolicyDenial(
            AuditReason.LIMIT_EXCEEDED,
            path,
            f"{label} {value} exceeds the limit of {limit}",
        )
    ]


def _step_spawn_denials(
    step: StepPlan, grants: _Grants, is_admin: bool
) -> list[PolicyDenial]:
    """Check a step's spawn mode under a policy.

    Parameters:
        step: The step plan.
        grants: The principal's grants.
        is_admin: Whether the principal is an admin.

    Returns:
        Denials for the spawn mode.
    """
    mode = step.spawn.value
    path = _path(step.spawn, step.path)
    if mode in PRIVILEGED_SPAWN_MODES and not is_admin:
        return [
            PolicyDenial(
                AuditReason.SPAWN_MODE_NOT_ALLOWED,
                path,
                f"spawn mode '{mode}' requires admin",
            )
        ]
    if not grants.spawn_modes.allows(mode):
        return [
            PolicyDenial(
                AuditReason.SPAWN_MODE_NOT_ALLOWED,
                path,
                f"spawn mode '{mode}' is not granted",
            )
        ]
    return []


def _step_name_denials(step: StepPlan, grants: _Grants) -> list[PolicyDenial]:
    """Check a step's skills, tools and namespaces under a policy.

    ``permissions.allowed_tools`` is checked against the ``tools`` grant like
    ``step.tools``. ``denied_tools`` only restricts, so it needs no grant.

    Parameters:
        step: The step plan.
        grants: The principal's grants.

    Returns:
        One denial per entry that is not granted.
    """
    checks: tuple[tuple[PlanValue[Any], _ListGrant, str], ...] = (
        (step.allowed_skills, grants.skills, "skill"),
        (step.tools, grants.tools, "tool"),
        (step.allowed_tools, grants.tools, "tool"),
        (step.target_namespaces, grants.namespaces, "namespace"),
    )
    denials: list[PolicyDenial] = []
    for value, grant, label in checks:
        base = _path(value, step.path)
        for index, name in enumerate(value.value or ()):
            denials.extend(_grant_denial(grant, name, f"{base}/{index}", label))
    return denials


def _step_service_account_denials(
    step: StepPlan, grants: _Grants, default_service_account: Optional[str]
) -> list[PolicyDenial]:
    """Check a step's service account under a policy.

    Unset and empty-string service accounts both mean the spawner default
    (the executor treats an empty legacy value as absent), which is an
    implicit grant, as is the configured default service account.

    Parameters:
        step: The step plan.
        grants: The principal's grants.
        default_service_account: The spawner's default service account.

    Returns:
        Denials for the service account.
    """
    account = step.service_account.value
    if not account or account == default_service_account:
        return []
    return _grant_denial(
        grants.service_accounts,
        account,
        _path(step.service_account, step.path),
        "service account",
    )


def _step_limit_denials(step: StepPlan, grants: _Grants) -> list[PolicyDenial]:
    """Check a step's timeouts, retries and token budget under a policy.

    ``permissions.timeout_seconds`` defaults to the runtime's 600 seconds
    and is checked against the step timeout limit, so omitting it never
    bypasses the check. An omitted ``permissions.max_tokens`` asks for an
    unlimited budget and is always denied. Step timeouts for ``none`` and
    ``ephemeral`` steps and ``max_tokens`` are declared budgets that the
    upstream runtime does not enforce.

    Parameters:
        step: The step plan.
        grants: The principal's grants.

    Returns:
        Denials for values above their effective limits.
    """
    timeout_limit = grants.max_step_timeout_seconds
    permissions_path = step.permissions_path or step.path
    perm_timeout = step.permissions_timeout_seconds
    denials = _limit_denial(
        step.timeout_seconds.value,
        timeout_limit,
        _path(step.timeout_seconds, step.path),
        "step timeout_seconds",
    )
    denials += _limit_denial(
        (
            perm_timeout.value
            if perm_timeout.value is not None
            else DEFAULT_STEP_TIMEOUT_SECONDS
        ),
        timeout_limit,
        _path(perm_timeout, permissions_path),
        "permissions.timeout_seconds",
    )
    denials += _limit_denial(
        step.max_retries.value,
        grants.max_retries,
        _path(step.max_retries, step.path),
        "max_retries",
    )
    if step.max_tokens.value is None:
        denials.append(
            PolicyDenial(
                AuditReason.LIMIT_EXCEEDED,
                permissions_path,
                "permissions.max_tokens must be declared "
                f"(limit {grants.max_tokens})",
            )
        )
    else:
        denials += _limit_denial(
            step.max_tokens.value,
            grants.max_tokens,
            _path(step.max_tokens, permissions_path),
            "permissions.max_tokens",
        )
    return denials


def _policy_denials(  # pylint: disable=too-many-arguments
    plan: EffectivePlan,
    principal: Principal,
    policy: WorkflowPolicy,
    *,
    default_sandbox_image: Optional[str],
    default_service_account: Optional[str],
    advisory: bool,
    definition_skills_image: Optional[str],
) -> list[PolicyDenial]:
    """Apply the deny-by-default policy rules.

    Parameters:
        plan: The effective plan.
        principal: The caller.
        policy: The workflow policy.
        default_sandbox_image: The spawner's configured default image.
        default_service_account: The spawner's default service account.
        advisory: Whether the definition requests advisory mode.
        definition_skills_image: ``definition.skills.image``, if any.

    Returns:
        Every denial under the policy.
    """
    grants = _grants_for(policy, principal.roles)
    denials = _grant_denial(
        grants.providers, plan.provider, PROVIDER_POINTER, "provider"
    )
    if advisory and not grants.advisory:
        denials.append(
            PolicyDenial(
                AuditReason.POLICY_DENIED,
                WORKFLOW_ADVISORY_POINTER,
                "advisory mode is not granted",
            )
        )
    for image, path in _caller_images(plan, definition_skills_image):
        if not _is_default_image(image, plan, default_sandbox_image) and not (
            grants.images.allows(image)
        ):
            denials.append(
                PolicyDenial(
                    AuditReason.IMAGE_NOT_ALLOWED,
                    path,
                    f"sandbox image '{image}' is not granted",
                )
            )
    for step in plan.steps:
        denials += _step_spawn_denials(step, grants, principal.is_admin)
        denials += _step_service_account_denials(step, grants, default_service_account)
        denials += _step_name_denials(step, grants)
        denials += [
            PolicyDenial(
                AuditReason.MCP_NOT_ALLOWED,
                path,
                "MCP servers are not allowed under the workflow policy",
            )
            for _, path, _ in _mcp_entries(step)
        ]
        denials += _step_limit_denials(step, grants)
    denials += _limit_denial(
        plan.declared_workflow_budget_seconds,
        grants.max_workflow_seconds,
        STEPS_POINTER,
        "declared workflow budget (seconds)",
    )
    return denials


def _dedupe(denials: Iterable[PolicyDenial]) -> tuple[PolicyDenial, ...]:
    """Drop identical denials, keeping the first.

    Identity is ``(reason, path, message)``: a spec-level value inherited by
    several steps produces one denial, while distinct violations that share a
    fallback path (for example a step timeout and a missing max_tokens) are
    all kept.

    Parameters:
        denials: Denials in check order.

    Returns:
        The distinct denials, in order.
    """
    seen: set[tuple[AuditReason, str, str]] = set()
    unique: list[PolicyDenial] = []
    for denial in denials:
        key = (denial.reason, denial.path, denial.message)
        if key not in seen:
            seen.add(key)
            unique.append(denial)
    return tuple(unique)


def authorize_workflow_submission(  # pylint: disable=too-many-arguments
    plan: EffectivePlan,
    principal: Principal,
    policy: Optional[WorkflowPolicy],
    *,
    spawner_configured: bool,
    default_sandbox_image: Optional[str],
    default_service_account: Optional[str] = None,
    advisory: bool = False,
    definition_skills_image: Optional[str] = None,
) -> PolicyDecision:
    """Authorize a workflow submission, returning every denial together.

    Pure function: no I/O, no logging. See the module docstring for the mode
    matrix and grant semantics. The workflow budget and token checks compare
    declared budgets, not runtime deadlines.

    Parameters:
        plan: Effective plan from ``build_effective_plan``.
        principal: The caller.
        policy: ``workflow_engine.policy``, or None for the Phase 0a rules.
        spawner_configured: Whether a spawner_configuration exists.
        default_sandbox_image: The spawner's configured default image (an
            implicit grant).
        default_service_account: A service account treated as an implicit
            grant. Production passes None today (the spawner configuration
            has no service-account field), so only unset and empty service
            accounts are implicitly granted.
        advisory: ``definition.advisory``.
        definition_skills_image: ``definition.skills.image``, if any.

    Returns:
        The decision; ``allowed`` is False when there is any denial.
    """
    denials = _spawner_denials(plan, spawner_configured)
    if policy is None:
        if not principal.is_admin:
            denials += _legacy_denials(
                plan,
                default_sandbox_image=default_sandbox_image,
                advisory=advisory,
                definition_skills_image=definition_skills_image,
            )
    else:
        denials += _policy_denials(
            plan,
            principal,
            policy,
            default_sandbox_image=default_sandbox_image,
            default_service_account=default_service_account,
            advisory=advisory,
            definition_skills_image=definition_skills_image,
        )
    return PolicyDecision(denials=_dedupe(denials))
