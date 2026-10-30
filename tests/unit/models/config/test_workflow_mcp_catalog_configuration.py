"""Unit tests for the workflow MCP catalog configuration (issue #51 Phase 3, T1)."""

# pylint: disable=too-few-public-methods

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from models.config import Configuration, ModelContextProtocolServer

from .test_workflow_catalog_configuration import _engine
from .test_workflow_policy_configuration import (
    ACCESS_RULES,
    JWK_AUTH,
    _policy_engine,
    _root,
)


def _server(name: str = "kb", **overrides: Any) -> dict[str, Any]:
    """A workflow-enabled catalog entry; ``overrides`` replace keys."""
    entry: dict[str, Any] = {
        "name": name,
        "url": "http://kb.internal:8080/mcp",
        "workflow_enabled": True,
    }
    entry.update(overrides)
    return entry


def _config(
    servers: list[dict[str, Any]], rules: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Root config dict with the given catalog and optional policy rules."""
    engine = _policy_engine(rules) if rules is not None else _engine()
    return _root(engine, mcp_servers=servers)


def _load_error(
    servers: list[dict[str, Any]], rules: list[dict[str, Any]] | None = None
) -> str:
    """Return the lower-cased load error for an invalid root config."""
    with pytest.raises(ValidationError) as exc_info:
        Configuration.model_validate(_config(servers, rules))
    return str(exc_info.value).lower()


class TestWorkflowEnabledField:
    """The workflow_enabled flag."""

    def test_defaults_false(self) -> None:
        """Entries are not workflow-enabled unless asked."""
        server = ModelContextProtocolServer(name="a", url="http://a/mcp")
        assert server.workflow_enabled is False

    def test_description_present(self) -> None:
        """The field is documented, including the trust statement."""
        schema = ModelContextProtocolServer.model_json_schema()
        description = schema["properties"]["workflow_enabled"]["description"]
        assert "trusted" in description

    def test_no_secret_headers_field(self) -> None:
        """No secret_headers in this phase."""
        schema = ModelContextProtocolServer.model_json_schema()
        assert "secret_headers" not in schema["properties"]
        with pytest.raises(ValidationError):
            ModelContextProtocolServer.model_validate(
                _server(secret_headers={"Authorization": {"name": "x"}})
            )

    def test_valid_enabled_entry_loads(self) -> None:
        """A secretless enabled entry loads and survives."""
        config = Configuration.model_validate(_config([_server()]))
        assert [s.name for s in config.mcp_servers] == ["kb"]
        assert config.mcp_servers[0].workflow_enabled is True

    def test_https_with_query_ok(self) -> None:
        """https is accepted."""
        Configuration.model_validate(
            _config([_server(url="https://kb.example.com/mcp?x=1")])
        )


class TestSecretlessChecks:
    """Credential-bearing configuration is refused on enabled entries."""

    @pytest.mark.parametrize("value", ["client", "oauth", "kubernetes"])
    def test_special_authorization_header_values(self, value: str) -> None:
        """Request-bound sources fail the load (not silently dropped)."""
        error = _load_error([_server(authorization_headers={"Authorization": value})])
        assert "kb" in error
        assert "authorization_headers" in error

    def test_file_authorization_header(self, tmp_path: Path) -> None:
        """A file-path secret fails and its content is not echoed."""
        secret = tmp_path / "tok"
        secret.write_text("s3cret-canary")
        error = _load_error([_server(authorization_headers={"X-Key": str(secret)})])
        assert "authorization_headers" in error
        assert "s3cret-canary" not in error

    def test_propagated_headers(self) -> None:
        """Propagated headers fail."""
        error = _load_error([_server(headers=["x-rh-identity"])])
        assert "kb" in error
        assert "headers" in error

    @pytest.mark.parametrize(
        "approval",
        ["always", {"always": ["a"]}, {"never": ["a"]}, {"always": [], "never": []}],
    )
    def test_require_approval_must_be_never(self, approval: Any) -> None:
        """Only the plain 'never' is accepted."""
        error = _load_error([_server(require_approval=approval)])
        assert "require_approval" in error

    def test_require_approval_never_ok(self) -> None:
        """Explicit never loads."""
        Configuration.model_validate(_config([_server(require_approval="never")]))

    def test_not_enabled_entries_keep_working(self, tmp_path: Path) -> None:
        """Entries not enabled keep credentials and loose names, as before."""
        secret = tmp_path / "tok"
        secret.write_text("v")
        config = Configuration.model_validate(
            _config(
                [
                    _server(),
                    {
                        "name": "Legacy_Server",
                        "url": "http://legacy:1/mcp",
                        "authorization_headers": {"Authorization": str(secret)},
                        "headers": ["x-rh-identity"],
                        "require_approval": "always",
                    },
                ]
            )
        )
        assert [s.name for s in config.mcp_servers] == ["kb", "Legacy_Server"]

    def test_disabled_kubernetes_entry_still_removed_by_auth_check(self) -> None:
        """The existing silent removal still applies to non-enabled entries."""
        config = Configuration.model_validate(
            _config(
                [
                    {
                        "name": "k",
                        "url": "http://k/mcp",
                        "authorization_headers": {"Authorization": "kubernetes"},
                    }
                ]
            )
        )
        assert not config.mcp_servers


class TestUrlRules:
    """URL shape for enabled entries."""

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://kb/mcp",
            "file:///etc/passwd",
            "kb/mcp",
            "//kb/mcp",
            "http://",
            "http:///path",
            "http://kb:notaport/mcp",
            "",
        ],
    )
    def test_bad_urls_rejected(self, url: str) -> None:
        """Non-http(s), hostless and unparsable URLs fail."""
        error = _load_error([_server(url=url)])
        assert "kb" in error
        assert "url" in error

    @pytest.mark.parametrize(
        "url",
        [
            "http://user:pass-canary@kb/mcp",
            "https://token-canary@kb/mcp",
            "https://:pw-canary@kb/mcp",
        ],
    )
    def test_userinfo_rejected_without_echo(self, url: str) -> None:
        """Userinfo fails and the credential-looking text is not echoed."""
        error = _load_error([_server(url=url)])
        assert "userinfo" in error
        assert "canary" not in error

    def test_query_not_echoed(self) -> None:
        """A bad URL with a query string never leaks the query."""
        error = _load_error([_server(url="ftp://kb/mcp?token=query-canary")])
        assert "query-canary" not in error

    def test_disabled_entry_url_not_checked(self) -> None:
        """Entries not enabled keep working as before."""
        Configuration.model_validate(_config([{"name": "x", "url": "ftp://odd/mcp"}]))


class TestNameRules:
    """Name shape and uniqueness for enabled entries."""

    @pytest.mark.parametrize(
        "name",
        ["Kb", "kb_1", "-kb", "kb.x", "kb/x", "", "a" * 64, "kb ", "../x", "kb\n"],
    )
    def test_bad_names_rejected(self, name: str) -> None:
        """Names that cannot be a mount path component fail."""
        assert "name" in _load_error([_server(name=name)])

    @pytest.mark.parametrize("name", ["k", "0kb", "kb-1", "a" * 63])
    def test_good_names_accepted(self, name: str) -> None:
        """Valid names load."""
        Configuration.model_validate(_config([_server(name=name)]))

    def test_duplicate_enabled_names(self) -> None:
        """Two enabled entries with one name fail."""
        error = _load_error([_server(), _server()])
        assert "kb" in error
        assert "unique" in error

    def test_duplicate_with_disabled_entry(self) -> None:
        """Uniqueness is checked against the whole catalog."""
        error = _load_error([{"name": "kb", "url": "http://other/mcp"}, _server()])
        assert "kb" in error
        assert "unique" in error

    def test_duplicate_with_disabled_entry_listed_after(self) -> None:
        """Order does not matter."""
        assert "unique" in _load_error(
            [_server(), {"name": "kb", "url": "http://other/mcp"}]
        )


class TestCheckOrdering:
    """The secretless check runs before auth-header resolution."""

    def test_kubernetes_header_fails_instead_of_being_dropped(self) -> None:
        """Under noop auth the legacy check would silently drop the entry."""
        config = _config(
            [_server(authorization_headers={"Authorization": "kubernetes"})]
        )
        config["authentication"] = {"module": "noop"}
        with pytest.raises(ValidationError) as exc_info:
            Configuration.model_validate(config)
        assert "authorization_headers" in str(exc_info.value)


class TestPolicyMcpGrant:
    """The mcp policy grant."""

    def test_wildcard_grant_loads(self) -> None:
        """['*'] loads with an enabled server."""
        config = Configuration.model_validate(
            _config([_server()], [{"role": "*", "mcp": ["*"]}])
        )
        assert config.workflow_engine.policy.rules[0].mcp == ["*"]  # type: ignore

    def test_named_grant_loads(self) -> None:
        """Naming enabled servers loads."""
        Configuration.model_validate(
            _config([_server(), _server("b")], [{"role": "*", "mcp": ["kb", "b"]}])
        )

    @pytest.mark.parametrize("value", [None, []])
    def test_missing_null_empty_grant_nothing(self, value: Any) -> None:
        """No grant; a rule with only that grants nothing."""
        config = Configuration.model_validate(
            _config([_server()], [{"role": "*", "mcp": value}])
        )
        assert not config.workflow_engine.policy.rules[0].grants_anything()  # type: ignore

    def test_grant_counts_as_granting(self) -> None:
        """mcp makes a rule grant something."""
        config = Configuration.model_validate(
            _config([_server()], [{"role": "*", "mcp": ["kb"]}])
        )
        assert config.workflow_engine.policy.rules[0].grants_anything()  # type: ignore

    def test_unknown_name_rejected(self) -> None:
        """Naming a server that is not in the catalog fails."""
        error = _load_error([_server()], [{"role": "*", "mcp": ["nope"]}])
        assert "nope" in error
        assert "mcp" in error

    def test_disabled_name_rejected(self) -> None:
        """Naming a non-enabled server fails."""
        error = _load_error(
            [{"name": "plain", "url": "http://p/mcp"}],
            [{"role": "*", "mcp": ["plain"]}],
        )
        assert "plain" in error
        assert "workflow_enabled" in error

    def test_wildcard_mixed_rejected(self) -> None:
        """'*' next to other entries fails."""
        assert "'*'" in _load_error([_server()], [{"role": "*", "mcp": ["*", "kb"]}])

    def test_wildcard_with_no_enabled_servers_loads(self) -> None:
        """'*' over an empty set is harmless."""
        Configuration.model_validate(_config([], [{"role": "*", "mcp": ["*"]}]))

    def test_union_across_roles(self) -> None:
        """Rules for several roles union like other list grants."""
        raw = _config(
            [_server(), _server("b")],
            [
                {"role": "*", "mcp": ["kb"]},
                {"role": "dev", "inherit": ["*"], "mcp": ["b"]},
            ],
        )
        raw["authentication"] = JWK_AUTH
        raw["authorization"] = ACCESS_RULES
        config = Configuration.model_validate(raw)
        rules = config.workflow_engine.policy.rules_for(["dev"])  # type: ignore
        granted = {name for rule in rules for name in rule.mcp or []}
        assert granted == {"kb", "b"}

    def test_d8_needs_jwk_for_non_wildcard_role(self) -> None:
        """An mcp grant for a non-'*' role needs jwk-token."""
        with pytest.raises(ValidationError) as exc_info:
            Configuration.model_validate(
                _config([_server()], [{"role": "dev", "mcp": ["kb"]}])
            )
        assert "jwk-token" in str(exc_info.value)

    def test_d8_needs_role_and_access_rules(self) -> None:
        """jwk-token without access_rules fails."""
        config = _config([_server()], [{"role": "dev", "mcp": ["kb"]}])
        config["authentication"] = JWK_AUTH
        with pytest.raises(ValidationError):
            Configuration.model_validate(config)

    def test_d8_ok_with_jwk_and_rules(self) -> None:
        """jwk-token with both rule sets loads."""
        config = _config([_server()], [{"role": "dev", "mcp": ["kb"]}])
        config["authentication"] = JWK_AUTH
        config["authorization"] = ACCESS_RULES
        Configuration.model_validate(config)


class TestStillReserved:
    """Other Phase 3 policy fields stay rejected."""

    @pytest.mark.parametrize(
        "field,value",
        [
            ("inline_mcp", True),
            ("inline_mcp_hosts", ["example.com"]),
            ("mcp_secrets", ["s"]),
            ("ssrf", True),
        ],
    )
    def test_non_default_rejected(self, field: str, value: Any) -> None:
        """Each fails at root load."""
        error = _load_error([_server()], [{"role": "*", "mcp": ["*"], field: value}])
        assert "not supported" in error
        assert field in error
