"""Operator-catalog MCP references in workflow definitions (issue #51, Phase 3).

A string in a step's or the spec's ``mcp_servers`` list names an entry of the
operator catalog: the ``workflow_enabled`` entries of the configuration's
``mcp_servers``. Catalog entries are secretless (enforced at configuration
load), so the stack hands the executor only ``{name, url}`` for each.

Three pure helpers, none of which does I/O or logs:

* ``validate_mcp_references`` walks every raw ``mcp_servers`` occurrence (the
  spec list and every step list, approval steps included, even a spec list
  that every step overrides) and raises ``McpReferenceError`` (400) for a
  name that is not a ``workflow_enabled`` entry (``mcp_unknown``; one fixed
  message for an unknown and a disabled name) or a name clash
  (``mcp_name_conflict``: an inline entry named like an enabled catalog
  entry, or a name used twice in one list).
* ``effective_mcp_servers`` / ``step_mcp_servers`` give, per agent step, the
  effective list (step, else spec; ``[]`` is explicitly empty), split into
  named catalog references and inline entry pointers. Inline entries are
  kept as pointers only, so no inline name, URL or header name can leak
  through these outputs into an audit record. ``mcp_audit_summary`` reduces
  them to catalog names plus an inline count.
* ``build_workflow_mcp_servers`` builds ``workflow_input["mcp_servers"]``.

Run-level union vs per-step scoping: the executor resolves each step's names
against the single run-level ``workflow_input["mcp_servers"]`` list
(``resolve_mcp_servers`` in ``build_step_input`` and again in the step
runner), using the step's own normalized ``mcp_servers``. The run-level list
is therefore the deduplicated union of the catalog servers that some agent
step's effective list names, and a step still receives only the servers it
names itself; servers no step references are never injected.

Error details and audit fields are built from fixed messages and JSON
pointers (indices and fixed keys only); caller strings are never echoed.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fastapi import status

from models.config import ModelContextProtocolServer
from workflow.audit import AuditReason, json_pointer
from workflow.effective import EffectivePlan, StepPlan
from workflow.submission_guard import SubmissionRejected

MCP_UNKNOWN_MESSAGE: Final[str] = (
    "mcp_servers names a server that is not available to workflows; use a "
    "workflow-enabled catalog name."
)
MCP_NAME_CONFLICT_MESSAGE: Final[str] = (
    "mcp_servers repeats a server name in one list, or an inline entry uses "
    "the name of a catalog server."
)

_MESSAGES: Final[dict[AuditReason, str]] = {
    AuditReason.MCP_UNKNOWN: MCP_UNKNOWN_MESSAGE,
    AuditReason.MCP_NAME_CONFLICT: MCP_NAME_CONFLICT_MESSAGE,
}


@dataclass(frozen=True)
class McpProblem:
    """One bad MCP reference.

    Attributes:
        reason: ``mcp_unknown`` or ``mcp_name_conflict``.
        path: JSON pointer of the entry (indices and fixed keys only).
    """

    reason: AuditReason
    path: str


class McpReferenceError(SubmissionRejected):
    """A 400 for bad MCP references, carrying every problem at once.

    The detail is built from fixed messages and pointers only, so it is the
    same for an unknown and a disabled name and never echoes caller input.

    Attributes:
        problems: The problems in walk order.
    """

    def __init__(self, problems: Sequence[McpProblem]) -> None:
        """Initialize the error.

        Parameters:
            problems: The problems, at least one.
        """
        reasons = tuple(dict.fromkeys(p.reason for p in problems))
        detail = " ".join(
            f"{_MESSAGES[reason]} "
            f"({', '.join(p.path for p in problems if p.reason == reason)})"
            for reason in reasons
        )
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail,
            reasons=reasons,
            paths=[p.path for p in problems],
        )
        self.problems: tuple[McpProblem, ...] = tuple(problems)


def _enabled_catalog(
    catalog: Sequence[ModelContextProtocolServer],
) -> dict[str, ModelContextProtocolServer]:
    """Index the workflow-enabled catalog entries by name.

    Parameters:
        catalog: The configuration's ``mcp_servers``.

    Returns:
        Enabled entries keyed by name.
    """
    return {server.name: server for server in catalog if server.workflow_enabled}


def _raw_lists(definition: Mapping[str, Any]) -> Iterator[tuple[list[Any], str]]:
    """Yield every raw ``mcp_servers`` list with its pointer.

    Malformed containers are skipped; the typed parse answers those.

    Parameters:
        definition: Workflow definition.

    Yields:
        ``(entries, pointer)`` for the spec list and each step list.
    """
    spec = definition.get("spec")
    if not isinstance(spec, Mapping):
        return
    servers = spec.get("mcp_servers")
    if isinstance(servers, list):
        yield servers, json_pointer("definition", "spec", "mcp_servers")
    steps = spec.get("steps")
    if not isinstance(steps, list):
        return
    for index, step in enumerate(steps):
        servers = step.get("mcp_servers") if isinstance(step, Mapping) else None
        if isinstance(servers, list):
            yield servers, json_pointer(
                "definition", "spec", "steps", index, "mcp_servers"
            )


def _list_problems(
    entries: Sequence[Any], base: str, enabled: Mapping[str, Any]
) -> list[McpProblem]:
    """Check one raw list for unknown names and name clashes.

    Parameters:
        entries: The raw entries.
        base: Pointer of the list.
        enabled: Enabled catalog entries keyed by name.

    Returns:
        The problems, in entry order.
    """
    problems: list[McpProblem] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        path = f"{base}/{index}"
        if isinstance(entry, str):
            name: Any = entry
            if name not in enabled:
                problems.append(McpProblem(AuditReason.MCP_UNKNOWN, path))
                continue
        elif isinstance(entry, Mapping):
            name = entry.get("name")
            if not isinstance(name, str):
                continue
            if name in enabled:
                problems.append(McpProblem(AuditReason.MCP_NAME_CONFLICT, path))
                continue
        else:
            continue
        if name in seen:
            problems.append(McpProblem(AuditReason.MCP_NAME_CONFLICT, path))
        seen.add(name)
    return problems


def validate_mcp_references(
    definition: Mapping[str, Any],
    catalog: Sequence[ModelContextProtocolServer],
) -> None:
    """Validate every raw MCP reference in a definition against the catalog.

    Covers the spec list and every step list, including lists no agent step
    ends up using. Inline entries are only checked for name clashes; the
    policy decides whether they are allowed.

    Parameters:
        definition: Workflow definition (not modified).
        catalog: The configuration's ``mcp_servers``.

    Raises:
        McpReferenceError: 400 listing every ``mcp_unknown`` and
            ``mcp_name_conflict`` problem by pointer.
    """
    enabled = _enabled_catalog(catalog)
    problems: list[McpProblem] = []
    for entries, base in _raw_lists(definition):
        problems += _list_problems(entries, base, enabled)
    if problems:
        raise McpReferenceError(problems)


@dataclass(frozen=True)
class NamedMcpRef:
    """A named catalog reference in a step's effective list.

    Attributes:
        name: The referenced catalog name.
        path: JSON pointer of the entry (step list, or the inherited spec list).
    """

    name: str
    path: str


@dataclass(frozen=True)
class StepMcpServers:
    """The effective MCP servers of one agent step.

    Inline entries are kept as pointers only: their names, URLs and headers
    are never exposed here.

    Attributes:
        step_index: Index of the step in ``spec.steps``.
        step_path: JSON pointer of the step.
        named: Named catalog references, in list order.
        inline_paths: Pointers of inline entries, in list order.
    """

    step_index: int
    step_path: str
    named: tuple[NamedMcpRef, ...]
    inline_paths: tuple[str, ...]

    @property
    def names(self) -> tuple[str, ...]:
        """Referenced catalog names, in list order.

        Returns:
            The names.
        """
        return tuple(ref.name for ref in self.named)

    @property
    def inline_count(self) -> int:
        """Number of inline entries.

        Returns:
            The count.
        """
        return len(self.inline_paths)


def step_mcp_servers(step: StepPlan) -> StepMcpServers:
    """Split a step's effective MCP list into named and inline entries.

    Entries that are neither strings nor mappings are counted as inline so
    the policy still denies them in policy mode; the typed parse rejects them
    before this runs.

    Parameters:
        step: The step plan (its ``mcp_servers`` is step, else spec).

    Returns:
        The step's effective servers.
    """
    base = step.mcp_servers.path or step.path
    named: list[NamedMcpRef] = []
    inline: list[str] = []
    for index, entry in enumerate(step.mcp_servers.value or ()):
        path = f"{base}/{index}"
        if isinstance(entry, str):
            named.append(NamedMcpRef(entry, path))
        else:
            inline.append(path)
    return StepMcpServers(step.index, step.path, tuple(named), tuple(inline))


def effective_mcp_servers(plan: EffectivePlan) -> tuple[StepMcpServers, ...]:
    """Return the effective MCP servers of every agent step.

    Approval steps run no agent and get no servers.

    Parameters:
        plan: The effective plan.

    Returns:
        One entry per agent step, in definition order.
    """
    return tuple(step_mcp_servers(step) for step in plan.steps)


def build_workflow_mcp_servers(
    steps: Sequence[StepMcpServers],
    catalog: Sequence[ModelContextProtocolServer],
) -> list[dict[str, str]]:
    """Build ``workflow_input["mcp_servers"]`` from the effective lists.

    The result is the deduplicated union, in first-reference order, of the
    catalog servers the steps name, each as exactly ``{name, url}`` (never
    headers, secret headers or credentials; ``MCPServerConfig`` is
    ``extra="forbid"``). Per-step scoping is kept by the executor, which
    resolves each step's own names against this list.

    Parameters:
        steps: Output of ``effective_mcp_servers``.
        catalog: The configuration's ``mcp_servers``.

    Returns:
        Fresh dicts, one per referenced catalog server.

    Raises:
        McpReferenceError: ``mcp_unknown`` for a name that is not an enabled
            entry (fail closed if references were not validated first).
    """
    enabled = _enabled_catalog(catalog)
    unknown = [
        McpProblem(AuditReason.MCP_UNKNOWN, ref.path)
        for step in steps
        for ref in step.named
        if ref.name not in enabled
    ]
    if unknown:
        raise McpReferenceError(list(dict.fromkeys(unknown)))
    names = dict.fromkeys(ref.name for step in steps for ref in step.named)
    return [{"name": name, "url": enabled[name].url} for name in names]


@dataclass(frozen=True)
class McpAuditSummary:
    """Audit-safe MCP facts for a submission.

    Attributes:
        catalog_names: Sorted, deduplicated enabled catalog names in use.
        inline_count: Number of distinct inline entries in use.
    """

    catalog_names: tuple[str, ...]
    inline_count: int


def mcp_audit_summary(
    steps: Sequence[StepMcpServers],
    catalog: Sequence[ModelContextProtocolServer],
) -> McpAuditSummary:
    """Reduce the effective lists to audit-safe facts.

    Only enabled catalog names are reported, so a name that did not pass
    validation can never reach an audit record. An inline entry inherited by
    several steps from the spec counts once.

    Parameters:
        steps: Output of ``effective_mcp_servers``.
        catalog: The configuration's ``mcp_servers``.

    Returns:
        The summary.
    """
    enabled = _enabled_catalog(catalog)
    names = {ref.name for step in steps for ref in step.named if ref.name in enabled}
    inline = {path for step in steps for path in step.inline_paths}
    return McpAuditSummary(catalog_names=tuple(sorted(names)), inline_count=len(inline))
