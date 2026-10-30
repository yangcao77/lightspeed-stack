"""Effective per-step plan for a workflow submission (issue #51, Phase 2).

``build_effective_plan`` works out, before anything is persisted, what the
installed cloud-agents executor will actually run for each agent step: spawn
mode, sandbox image, service account, timeouts, retries, token budget, skills,
tools, namespaces and MCP servers. It reproduces ``normalize_workflow_step``,
``collapse_permissions``, ``resolve_sandbox_image``,
``workflow_defaults_from_definition`` and the ``build_step_input`` defaults in
``cloud_agents.workflow.core.execution``, and fills in executor defaults when
the request omits a value so that omission is still checked by the policy.

Every value carries a JSON pointer into the request body built from indices
and fixed keys only (never from caller strings), so the policy can name the
offending field without echoing caller input. A ``None`` path means the value
is an executor or service default rather than something the caller sent.

The function is pure: it does no I/O, does not log, and does not modify its
input.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Optional

from cloud_agents.spawner.base import SpawnConfig
from cloud_agents.workflow.core.permissions import PermissionScope
from pydantic import BaseModel, NonNegativeInt, TypeAdapter, ValidationError

from workflow.catalog import ResolvedProvider

# Runner default step timeout (``build_step_input``: ``timeout_seconds or 600``).
DEFAULT_STEP_TIMEOUT_SECONDS: Final[int] = 600

# Last fallback of ``resolve_sandbox_image`` when no image is set anywhere.
EXECUTOR_DEFAULT_SANDBOX_IMAGE: Final[str] = "sandbox:latest"

# Spawn mode used when neither the step nor the spec sets one.
DEFAULT_SPAWN_MODE: Final[str] = "ephemeral"

# Spawn modes the executor accepts.
SPAWN_MODES: Final[frozenset[str]] = frozenset({"none", "local", "ephemeral"})

# Step type of approval gates; they carry no agent execution spec.
APPROVAL_STEP_TYPE: Final[str] = "human-approval"

# Step type of agent steps (the executor default when ``type`` is omitted).
AGENT_STEP_TYPE: Final[str] = "agent"

# Reason code: step/workflow service_account conflicts with
# permissions.service_account (the executor raises ValueError after the 202).
REASON_SERVICE_ACCOUNT_CONFLICT: Final[str] = "service_account_conflict"

# Reason code: a value the executor's normalizer would reject.
REASON_INVALID_VALUE: Final[str] = "invalid_value"

# JSON pointer roots in the request body.
DEFINITION_POINTER: Final[str] = "/definition"
SPEC_POINTER: Final[str] = "/definition/spec"
STEPS_POINTER: Final[str] = "/definition/spec/steps"
RUN_SANDBOX_IMAGE_POINTER: Final[str] = "/sandbox_image"

_NON_NEGATIVE_INT: Final[TypeAdapter[int]] = TypeAdapter(NonNegativeInt)


class ImageSource(str, Enum):
    """Where a step's effective sandbox image came from."""

    STEP = "step"
    SPEC = "spec"
    REQUEST = "request"
    SPAWNER_DEFAULT = "spawner_default"
    EXECUTOR_DEFAULT = "executor_default"


class EffectivePlanError(Exception):
    """A definition the executor would reject, reported without its values.

    The message is built from the reason code and fixed JSON pointers only;
    it never contains caller values or the executor's exception text.

    Attributes:
        reason: Reason code (``service_account_conflict`` or ``invalid_value``).
        path: JSON pointer of the offending field in the request body.
        conflicting_path: JSON pointer of the other side of a conflict, or None.
    """

    def __init__(
        self, reason: str, path: str, conflicting_path: Optional[str] = None
    ) -> None:
        """Initialize the error.

        Parameters:
            reason: Reason code.
            path: JSON pointer of the offending field.
            conflicting_path: JSON pointer of the conflicting field, if any.
        """
        message = f"{reason} at {path}"
        if conflicting_path is not None:
            message += f" (conflicts with {conflicting_path})"
        super().__init__(message)
        self.reason = reason
        self.path = path
        self.conflicting_path = conflicting_path


@dataclass(frozen=True)
class PlanValue[T]:
    """An effective value and where it came from.

    Attributes:
        value: The effective value the executor will use.
        path: JSON pointer of the field it came from in the request body, or
            None when it is an executor or service default.
    """

    value: T
    path: Optional[str]


@dataclass(frozen=True)
class StepPlan:  # pylint: disable=too-many-instance-attributes
    """Effective execution values for one agent step.

    Attributes:
        index: Index of the step in ``spec.steps``.
        path: JSON pointer of the step.
        spawn: Spawn mode (step, else spec, else ``ephemeral``).
        sandbox_image: Image chosen field by field: step
            ``spawn_config.sandbox_image``, spec ``spawn_config.sandbox_image``,
            run image, then ``sandbox:latest``.
        sandbox_image_source: Which layer supplied ``sandbox_image``.
        spawn_config: Validated ``SpawnConfig`` dump, inherited as a whole
            object (step, else spec), or None.
        service_account: Effective service account after the
            ``collapse_permissions`` rule, or None for the spawner default.
        permissions_path: JSON pointer of the permissions object in effect
            (step, else spec, taken whole), or None.
        permissions_timeout_seconds: ``permissions.timeout_seconds`` from the
            permissions object in effect, or None.
        max_tokens: Declared ``permissions.max_tokens``; None means the step
            asks for an unlimited token budget.
        timeout_seconds: Step timeout (step, else spec, else 600).
        max_retries: Retries after the first attempt (step only, default 0).
        allowed_skills: Skills (step, else spec); None is unset, ``()`` is an
            explicit empty list.
        tools: Tool names (step only; omitted or null means ``()``).
        allowed_tools: ``permissions.allowed_tools`` from the permissions
            object in effect (whole-object semantics); the executor sends it
            to ephemeral sandboxes only when non-empty. None is unset or
            null and ``()`` is an explicit empty list; they are kept
            distinct here although the producer sends nothing for either.
        target_namespaces: Namespaces (step only); None is unset, ``()`` is
            an explicit empty list.
        mcp_servers: MCP server entries (step, else spec), or None.
        declared_budget_seconds: ``timeout_seconds x (max_retries + 1)``, a
            declared budget checked at submission, not a deadline.
    """

    index: int
    path: str
    spawn: PlanValue[str]
    sandbox_image: PlanValue[str]
    sandbox_image_source: ImageSource
    spawn_config: PlanValue[Optional[dict[str, Any]]]
    service_account: PlanValue[Optional[str]]
    permissions_path: Optional[str]
    permissions_timeout_seconds: PlanValue[Optional[int]]
    max_tokens: PlanValue[Optional[int]]
    timeout_seconds: PlanValue[int]
    max_retries: PlanValue[int]
    allowed_skills: PlanValue[Optional[tuple[str, ...]]]
    tools: PlanValue[tuple[str, ...]]
    allowed_tools: PlanValue[Optional[tuple[str, ...]]]
    target_namespaces: PlanValue[Optional[tuple[str, ...]]]
    mcp_servers: PlanValue[Optional[tuple[Any, ...]]]
    declared_budget_seconds: int


@dataclass(frozen=True)
class EffectivePlan:
    """What the executor will run for a workflow submission.

    ``declared_workflow_budget_seconds`` is the sum over agent steps of
    ``step timeout x (max_retries + 1)``; approval steps are excluded. It is a
    declared budget checked at submission, not a deadline: the executor has no
    workflow-level timeout, and the sum leaves out approval waits and
    overhead.

    Attributes:
        provider: Logical catalog name of the run provider.
        run_sandbox_image: Run-level image (request image, else the spawner
            default), or None.
        spawner_default_image: The spawner's default image, or None.
        skills_image: Skills image from the run context only; the
            definition-level ``skills`` field is not wired to the runner.
        steps: Plans for the agent steps, in definition order.
        approval_step_indices: Indices of human-approval steps.
        declared_workflow_budget_seconds: Declared budget (see above).
    """

    provider: str
    run_sandbox_image: Optional[str]
    spawner_default_image: Optional[str]
    skills_image: PlanValue[Optional[str]]
    steps: tuple[StepPlan, ...]
    approval_step_indices: tuple[int, ...]
    declared_workflow_budget_seconds: int


def _invalid(path: str) -> EffectivePlanError:
    """Build an ``invalid_value`` error for a path.

    Parameters:
        path: JSON pointer of the offending field.

    Returns:
        The error to raise.
    """
    return EffectivePlanError(REASON_INVALID_VALUE, path)


def _validate_model[ModelT: BaseModel](
    model: type[ModelT], data: Any, path: str
) -> ModelT:
    """Validate data with an executor model, hiding the validation text.

    The error is raised outside the ``except`` block so neither the cause nor
    the context carries the pydantic message (which echoes input values).

    Parameters:
        model: Executor pydantic model class.
        data: Raw value from the definition.
        path: JSON pointer of the value.

    Returns:
        The validated model.

    Raises:
        EffectivePlanError: ``invalid_value`` when validation fails.
    """
    try:
        return model.model_validate(data)
    except ValidationError:
        pass
    raise _invalid(path)


def _validate_retries(value: Any, path: str) -> int:
    """Validate ``max_retries`` the way ``WorkflowAgentStep`` does.

    Parameters:
        value: Raw value.
        path: JSON pointer of the value.

    Returns:
        The non-negative retry count.

    Raises:
        EffectivePlanError: ``invalid_value`` when validation fails.
    """
    try:
        return _NON_NEGATIVE_INT.validate_python(value)
    except ValidationError:
        pass
    raise _invalid(path)


def _pick(
    step: Mapping[str, Any],
    spec: Mapping[str, Any],
    key: str,
    step_path: str,
) -> tuple[Any, Optional[str]]:
    """Pick a value with the executor's step-else-workflow rule.

    ``None`` at the step inherits; the spec value is used only when it is
    not None (``workflow_defaults_from_definition``).

    Parameters:
        step: Raw step mapping.
        spec: Raw spec mapping.
        key: Field name.
        step_path: JSON pointer of the step.

    Returns:
        The value and its JSON pointer, or ``(None, None)``.
    """
    if step.get(key) is not None:
        return step[key], f"{step_path}/{key}"
    if spec.get(key) is not None:
        return spec[key], f"{SPEC_POINTER}/{key}"
    return None, None


def _str_tuple(value: Any, path: Optional[str]) -> Optional[tuple[str, ...]]:
    """Convert an optional list of strings to a tuple, keeping None.

    Parameters:
        value: Raw value (None or a list of strings).
        path: JSON pointer of the value.

    Returns:
        None, or a tuple of the strings.

    Raises:
        EffectivePlanError: ``invalid_value`` when the value is not a list of
            strings.
    """
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _invalid(path or SPEC_POINTER)
    return tuple(value)


def _check_positive_timeout(value: Any, path: str) -> int:
    """Apply the executor's strict positive-integer timeout check.

    Parameters:
        value: Raw timeout.
        path: JSON pointer of the timeout.

    Returns:
        The timeout.

    Raises:
        EffectivePlanError: ``invalid_value`` for bools, non-ints or values
            not above zero.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _invalid(path)
    return value


def _resolve_service_account(
    scope: Optional[PermissionScope],
    permissions_path: Optional[str],
    step: Mapping[str, Any],
    spec: Mapping[str, Any],
    step_path: str,
) -> PlanValue[Optional[str]]:
    """Apply the ``collapse_permissions`` service-account rule.

    The legacy service account is the step's, else the spec's (step ``None``
    inherits; an empty string does not, and counts as absent). A non-empty
    legacy value that differs from a set ``permissions.service_account`` is a
    conflict, including across layers.

    Parameters:
        scope: Permissions object in effect, or None.
        permissions_path: JSON pointer of that object, or None.
        step: Raw step mapping.
        spec: Raw spec mapping.
        step_path: JSON pointer of the step.

    Returns:
        The effective service account and its JSON pointer.

    Raises:
        EffectivePlanError: ``service_account_conflict`` on a conflict, or
            ``invalid_value`` for a non-string legacy value.
    """
    legacy, legacy_path = _pick(step, spec, "service_account", step_path)
    if legacy is not None and not isinstance(legacy, str):
        raise _invalid(legacy_path or step_path)
    scope_sa = scope.service_account if scope is not None else None
    scope_sa_path = (
        f"{permissions_path}/service_account" if scope_sa is not None else None
    )
    if legacy:
        if scope_sa is not None and scope_sa != legacy:
            raise EffectivePlanError(
                REASON_SERVICE_ACCOUNT_CONFLICT,
                legacy_path or step_path,
                conflicting_path=scope_sa_path,
            )
        if scope_sa is None:
            return PlanValue(legacy, legacy_path)
    return PlanValue(scope_sa, scope_sa_path)


def _resolve_image(
    spawn_config: Optional[SpawnConfig],
    spawn_config_path: Optional[str],
    spec: Mapping[str, Any],
    run_sandbox_image: Optional[str],
    spawner_default_image: Optional[str],
) -> tuple[PlanValue[str], ImageSource]:
    """Reproduce ``resolve_sandbox_image`` field by field.

    Parameters:
        spawn_config: Validated spawn config in effect (step, else spec).
        spawn_config_path: JSON pointer of that spawn config.
        spec: Raw spec mapping.
        run_sandbox_image: Image from the request, or None.
        spawner_default_image: The spawner's default image, or None.

    Returns:
        The effective image with its pointer, and its source.

    Raises:
        EffectivePlanError: ``invalid_value`` for a malformed spec image.
    """
    if spawn_config is not None and spawn_config.sandbox_image:
        source = (
            ImageSource.SPEC
            if spawn_config_path == f"{SPEC_POINTER}/spawn_config"
            else ImageSource.STEP
        )
        return (
            PlanValue(spawn_config.sandbox_image, f"{spawn_config_path}/sandbox_image"),
            source,
        )
    spec_config = spec.get("spawn_config")
    if spec_config is not None:
        spec_config_path = f"{SPEC_POINTER}/spawn_config"
        if not isinstance(spec_config, Mapping):
            raise _invalid(spec_config_path)
        spec_image = spec_config.get("sandbox_image")
        if spec_image:
            if not isinstance(spec_image, str):
                raise _invalid(f"{spec_config_path}/sandbox_image")
            return (
                PlanValue(spec_image, f"{spec_config_path}/sandbox_image"),
                ImageSource.SPEC,
            )
    if run_sandbox_image:
        return PlanValue(run_sandbox_image, RUN_SANDBOX_IMAGE_POINTER), (
            ImageSource.REQUEST
        )
    if spawner_default_image:
        return PlanValue(spawner_default_image, None), ImageSource.SPAWNER_DEFAULT
    return (
        PlanValue(EXECUTOR_DEFAULT_SANDBOX_IMAGE, None),
        ImageSource.EXECUTOR_DEFAULT,
    )


def _check_step_identity(
    step: Mapping[str, Any], step_path: str, step_count: int
) -> None:
    """Apply the executor's step type and one-step naming checks.

    Parameters:
        step: Raw agent step mapping.
        step_path: JSON pointer of the step.
        step_count: Number of steps in the definition.

    Raises:
        EffectivePlanError: ``invalid_value`` for an unknown type, or a
            missing name/output_key outside a one-step definition.
    """
    step_type = step.get("type")
    if step_type is not None and step_type != AGENT_STEP_TYPE:
        raise _invalid(f"{step_path}/type")
    if step_count != 1:
        for key in ("name", "output_key"):
            if step.get(key) is None:
                raise _invalid(f"{step_path}/{key}")
    if step.get("name") is not None and not step.get("name"):
        raise _invalid(f"{step_path}/name")


def _build_step_plan(  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
    index: int,
    step: Mapping[str, Any],
    spec: Mapping[str, Any],
    step_count: int,
    run_sandbox_image: Optional[str],
    spawner_default_image: Optional[str],
) -> StepPlan:
    """Build the plan for one agent step, in the executor's check order.

    Parameters:
        index: Step index in ``spec.steps``.
        step: Raw agent step mapping.
        spec: Raw spec mapping.
        step_count: Number of steps in the definition.
        run_sandbox_image: Image from the request, or None.
        spawner_default_image: The spawner's default image, or None.

    Returns:
        The step plan.

    Raises:
        EffectivePlanError: When the executor would reject the step.
    """
    step_path = f"{STEPS_POINTER}/{index}"
    _check_step_identity(step, step_path, step_count)

    raw_timeout, timeout_path = _pick(step, spec, "timeout_seconds", step_path)
    if raw_timeout is None:
        timeout = PlanValue(DEFAULT_STEP_TIMEOUT_SECONDS, None)
    else:
        timeout = PlanValue(
            _check_positive_timeout(raw_timeout, timeout_path or step_path),
            timeout_path,
        )

    raw_mcp, mcp_path = _pick(step, spec, "mcp_servers", step_path)
    if raw_mcp is not None and not isinstance(raw_mcp, list):
        raise _invalid(mcp_path or step_path)
    mcp_servers = PlanValue(
        None if raw_mcp is None else tuple(copy.deepcopy(raw_mcp)), mcp_path
    )
    raw_skills, skills_path = _pick(step, spec, "allowed_skills", step_path)
    allowed_skills = PlanValue(_str_tuple(raw_skills, skills_path), skills_path)

    raw_permissions, permissions_path = _pick(step, spec, "permissions", step_path)
    scope = (
        None
        if raw_permissions is None
        else _validate_model(
            PermissionScope, raw_permissions, permissions_path or step_path
        )
    )
    service_account = _resolve_service_account(
        scope, permissions_path, step, spec, step_path
    )
    perm_timeout = scope.timeout_seconds if scope is not None else None
    max_tokens = scope.max_tokens if scope is not None else None
    allowed_tools = (
        tuple(scope.allowed_tools)
        if scope is not None and scope.allowed_tools is not None
        else None
    )

    raw_namespaces = step.get("target_namespaces")
    namespaces_path = (
        None if raw_namespaces is None else f"{step_path}/target_namespaces"
    )

    raw_spawn, spawn_path = _pick(step, spec, "spawn", step_path)
    spawn = PlanValue(
        DEFAULT_SPAWN_MODE if raw_spawn is None else raw_spawn, spawn_path
    )
    if spawn.value not in SPAWN_MODES:
        raise _invalid(spawn_path or step_path)

    raw_spawn_config, spawn_config_path = _pick(step, spec, "spawn_config", step_path)
    spawn_config = (
        None
        if raw_spawn_config is None
        else _validate_model(
            SpawnConfig, raw_spawn_config, spawn_config_path or step_path
        )
    )
    image, image_source = _resolve_image(
        spawn_config, spawn_config_path, spec, run_sandbox_image, spawner_default_image
    )

    raw_tools = step.get("tools")
    tools_path = None if raw_tools is None else f"{step_path}/tools"
    tools = _str_tuple(raw_tools, tools_path)

    retries_path = f"{step_path}/max_retries" if "max_retries" in step else None
    retries = _validate_retries(step.get("max_retries", 0), retries_path or step_path)

    return StepPlan(
        index=index,
        path=step_path,
        spawn=spawn,
        sandbox_image=image,
        sandbox_image_source=image_source,
        spawn_config=PlanValue(
            spawn_config.model_dump() if spawn_config is not None else None,
            spawn_config_path,
        ),
        service_account=service_account,
        permissions_path=permissions_path,
        permissions_timeout_seconds=PlanValue(
            perm_timeout,
            f"{permissions_path}/timeout_seconds" if perm_timeout is not None else None,
        ),
        max_tokens=PlanValue(
            max_tokens,
            f"{permissions_path}/max_tokens" if max_tokens is not None else None,
        ),
        timeout_seconds=timeout,
        max_retries=PlanValue(retries, retries_path),
        allowed_skills=allowed_skills,
        tools=PlanValue(tools or (), tools_path),
        allowed_tools=PlanValue(
            allowed_tools,
            (
                f"{permissions_path}/allowed_tools"
                if scope is not None and scope.allowed_tools is not None
                else None
            ),
        ),
        target_namespaces=PlanValue(
            _str_tuple(raw_namespaces, namespaces_path), namespaces_path
        ),
        mcp_servers=mcp_servers,
        declared_budget_seconds=timeout.value * (retries + 1),
    )


def build_effective_plan(
    definition: Mapping[str, Any],
    run_provider: ResolvedProvider,
    *,
    run_sandbox_image: Optional[str],
    spawner_default_image: Optional[str],
    run_skills_image: Optional[str] = None,
) -> EffectivePlan:
    """Build the effective plan the executor will run for a definition.

    Pure function: no I/O, no logging, the input is not modified.

    Parameters:
        definition: Definition after ``workflow.catalog.normalize_definition``.
        run_provider: The resolved run-level provider.
        run_sandbox_image: ``sandbox_image`` from the request body, or None.
        spawner_default_image: The spawner's default image, or None.
        run_skills_image: Skills image in the run context, or None (the stack
            sends none today).

    Returns:
        The effective plan, including the declared workflow budget (a
        declared budget, not a deadline).

    Raises:
        EffectivePlanError: ``service_account_conflict`` when a step or
            workflow ``service_account`` conflicts with
            ``permissions.service_account``; ``invalid_value`` for values the
            executor's normalizer would reject. The error never carries caller
            values.
    """
    spec = definition.get("spec")
    if not isinstance(spec, Mapping):
        raise _invalid(SPEC_POINTER)
    raw_steps = spec.get("steps")
    if not isinstance(raw_steps, list):
        raise _invalid(STEPS_POINTER)

    steps: list[StepPlan] = []
    approvals: list[int] = []
    for index, step in enumerate(raw_steps):
        if not isinstance(step, Mapping):
            raise _invalid(f"{STEPS_POINTER}/{index}")
        if step.get("type") == APPROVAL_STEP_TYPE:
            approvals.append(index)
            continue
        steps.append(
            _build_step_plan(
                index,
                step,
                spec,
                len(raw_steps),
                run_sandbox_image,
                spawner_default_image,
            )
        )

    return EffectivePlan(
        provider=run_provider.catalog_name,
        run_sandbox_image=run_sandbox_image or spawner_default_image,
        spawner_default_image=spawner_default_image,
        skills_image=PlanValue(run_skills_image, None),
        steps=tuple(steps),
        approval_step_indices=tuple(approvals),
        declared_workflow_budget_seconds=sum(s.declared_budget_seconds for s in steps),
    )
