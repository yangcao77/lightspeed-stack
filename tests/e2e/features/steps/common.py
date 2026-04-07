"""Implementation of common test steps."""

import os

from behave import given  # pyright: ignore[reportAttributeAccessIssue]
from behave.runner import Context

from tests.e2e.utils.utils import (
    absolute_repo_path,
    create_config_backup,
    is_prow_environment,
    restart_container,
    switch_config,
    wait_for_container_health,
)


@given("The service is started locally")
def service_is_started_locally(context: Context) -> None:
    """Check the service status.

    Populate the Behave context with local service endpoint values read from
    environment variables.

    Parameters:
    ----------
        context (Context): Behave context object to receive the endpoint attributes.
    """
    assert context is not None
    context.hostname = os.getenv("E2E_LSC_HOSTNAME", "localhost")
    context.port = os.getenv("E2E_LSC_PORT", "8080")
    context.hostname_llama = os.getenv("E2E_LLAMA_HOSTNAME", "localhost")
    context.port_llama = os.getenv("E2E_LLAMA_PORT", "8321")


@given('the Lightspeed stack configuration directory is "{directory}"')
def set_lightspeed_stack_config_directory(context: Context, directory: str) -> None:
    """Store the repo-relative config folder for ``The service uses the ... configuration``.

    ``configure_service`` joins this path with either
    ``<server-mode|library-mode>/<file>`` when those subdirs exist under ``directory``,
    or ``<file>`` alone for a flat directory (local Docker and Prow).

    Parameters:
        context: Behave context; sets ``lightspeed_stack_config_directory``.
        directory: Path relative to the repository root (e.g. ``tests/e2e/configuration``).
    """
    context.lightspeed_stack_config_directory = directory.strip().rstrip("/")


@given("The service uses the {config_name} configuration")  # type: ignore
def configure_service(context: Context, config_name: str) -> None:
    """Switch to the given configuration if not already active.

    On first call creates a backup of the current config, switches to the
    named config, and restarts the container.  Subsequent calls within
    the same feature are no-ops (detected by backup file existence in Docker
    or backup key presence in Prow).

    Build path from ``lightspeed_stack_config_directory`` (directory step),
    defaulting base to ``tests/e2e/configuration`` if that step was omitted; then
    ``server-mode`` / ``library-mode`` subdir when present, else flat. On Prow the
    resolved path is made absolute from the repo root so ``switch_config`` works
    regardless of cwd.

    Parameters:
    ----------
        context (Context): Behave context.
        config_name (str): Config filename (e.g. lightspeed-stack-inline-rag.yaml).
    """
    if not is_prow_environment() and os.path.exists("lightspeed-stack.yaml.backup"):
        return

    mode_dir = "library-mode" if context.is_library_mode else "server-mode"
    raw_base = getattr(context, "lightspeed_stack_config_directory", None)
    if raw_base and str(raw_base).strip():
        base = str(raw_base).strip().rstrip("/")
    else:
        base = "tests/e2e/configuration"
    mode_base = os.path.join(base, mode_dir)
    if is_prow_environment():
        abs_mode_base = absolute_repo_path(mode_base)
        abs_base = absolute_repo_path(base)
        if os.path.isdir(abs_mode_base):
            config_path = os.path.join(abs_mode_base, config_name)
        else:
            config_path = os.path.join(abs_base, config_name)
    else:
        if os.path.isdir(mode_base):
            config_path = os.path.join(mode_base, config_name)
        else:
            config_path = os.path.join(base, config_name)
    create_config_backup("lightspeed-stack.yaml")
    switch_config(config_path)


@given("The service is restarted")
def restart_service(context: Context) -> None:
    """Restart the lightspeed-stack container and wait for it to be healthy.

    Parameters:
    ----------
        context (Context): Behave context.
    """
    restart_container("lightspeed-stack")
    # Library mode needs extra time to load embedding models after restart
    wait_for_container_health("lightspeed-stack", max_attempts=12)


@given("The system is in default state")
def system_in_default_state(context: Context) -> None:
    """Check the default system state.

    Ensure the Behave test context is present for steps that assume the system
    is in its default state.

    Parameters:
    ----------
        context (Context): Behave Context instance used to store and share test state.

    Raises:
    ------
        AssertionError: If `context` is None.
    """
    assert context is not None
