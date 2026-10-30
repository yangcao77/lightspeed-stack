"""Unit tests for the workflow run-level policy configuration (issue #51 Phase 2)."""

# pylint: disable=too-few-public-methods,protected-access

from typing import Any

import pytest
from pydantic import ValidationError

from models.config import Configuration, WorkflowEngineConfiguration
from workflow import limits

from .test_workflow_catalog_configuration import _engine


def _policy_engine(rules: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    """Governed-mode workflow_engine config carrying the given policy rules."""
    return _engine(policy={"rules": rules}, **overrides)


def _error(config: dict[str, Any]) -> str:
    """Return the lower-cased validation error for an invalid engine config."""
    with pytest.raises(ValidationError) as exc_info:
        WorkflowEngineConfiguration.model_validate(config)
    return str(exc_info.value).lower()


def _root(
    engine: dict[str, Any], authentication: dict[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    """Minimal root configuration dict with the given engine and auth blocks."""
    config: dict[str, Any] = {
        "name": "test",
        "service": {},
        "llama_stack": {
            "use_as_library_client": True,
            "library_client_config_path": "tests/configuration/run.yaml",
        },
        "user_data_collection": {},
        "database": {
            "postgres": {"host": "localhost", "db": "x", "user": "u", "password": "p"}
        },
        "workflow_engine": engine,
    }
    if authentication is not None:
        config["authentication"] = authentication
    config.update(extra)
    return config


JWK_AUTH: dict[str, Any] = {
    "module": "jwk-token",
    "jwk_config": {
        "url": "https://example.com/jwks",
        "jwt_configuration": {
            "role_rules": [
                {
                    "jsonpath": "$.roles[*]",
                    "operator": "contains",
                    "value": "dev",
                    "roles": ["dev"],
                }
            ]
        },
    },
}
ACCESS_RULES: dict[str, Any] = {"access_rules": [{"role": "dev", "actions": ["query"]}]}
GRANTING_RULES: list[dict[str, Any]] = [{"role": "dev", "providers": ["claude-prod"]}]
WILDCARD_RULES: list[dict[str, Any]] = [{"role": "*", "providers": ["claude-prod"]}]


class TestPolicyLoad:
    """Load-time checks on the policy block."""

    def test_valid_policy_loads(self) -> None:
        """A full rule loads and keeps its values."""
        config = WorkflowEngineConfiguration.model_validate(
            _policy_engine(
                [
                    {
                        "role": "dev",
                        "providers": ["claude-prod"],
                        "skills": ["*"],
                        "tools": ["bash"],
                        "images": ["img:1"],
                        "service_accounts": ["sa"],
                        "namespaces": ["ns"],
                        "spawn_modes": ["ephemeral"],
                        "advisory": True,
                        "limits": {"max_retries": 2, "max_tokens": 10},
                    }
                ]
            )
        )
        assert config.policy is not None
        rule = config.policy.rules[0]
        assert rule.advisory is True
        assert rule.limits.max_retries == 2
        assert rule.skills == ["*"]

    def test_no_policy_by_default(self) -> None:
        """Omitting policy keeps it None."""
        assert WorkflowEngineConfiguration.model_validate(_engine()).policy is None

    def test_defaults(self) -> None:
        """Advisory defaults to False and grants to None."""
        config = WorkflowEngineConfiguration.model_validate(
            _policy_engine([{"role": "*"}])
        )
        assert config.policy is not None
        rule = config.policy.rules[0]
        assert rule.advisory is False
        assert rule.providers is None
        assert rule.inherit == []

    def test_requires_governed_mode(self) -> None:
        """Policy without a provider catalog fails."""
        assert "governed" in _error(
            {"enabled": True, "policy": {"rules": [{"role": "*"}]}}
        )

    def test_unknown_provider(self) -> None:
        """A provider grant must name a catalog entry."""
        assert "nope" in _error(
            _policy_engine([{"role": "dev", "providers": ["nope"]}])
        )

    def test_wildcard_provider_allowed(self) -> None:
        """'*' is not looked up in the catalog."""
        WorkflowEngineConfiguration.model_validate(
            _policy_engine([{"role": "dev", "providers": ["*"]}])
        )

    def test_unknown_inherit_role(self) -> None:
        """Inherit must name a role defined by some rule."""
        assert "ghost" in _error(
            _policy_engine([{"role": "dev", "inherit": ["ghost"]}])
        )

    def test_inherit_cycle(self) -> None:
        """Cyclic inheritance fails."""
        assert "cycle" in _error(
            _policy_engine(
                [
                    {"role": "a", "inherit": ["b"]},
                    {"role": "b", "inherit": ["a"]},
                ]
            )
        )

    def test_self_inherit_cycle(self) -> None:
        """A role inheriting itself is a cycle."""
        assert "cycle" in _error(_policy_engine([{"role": "a", "inherit": ["a"]}]))

    @pytest.mark.parametrize(
        "field",
        [
            "providers",
            "skills",
            "tools",
            "images",
            "service_accounts",
            "namespaces",
            "spawn_modes",
        ],
    )
    def test_wildcard_mixed_with_entries(self, field: str) -> None:
        """'*' next to other values in a list grant fails."""
        value = ["claude-prod", "*"] if field == "providers" else ["x", "*"]
        assert "'*'" in _error(_policy_engine([{"role": "dev", field: value}]))

    @pytest.mark.parametrize("field", ["skills", "tools", "images", "spawn_modes"])
    def test_wildcard_alone_ok(self, field: str) -> None:
        """'*' alone is accepted."""
        WorkflowEngineConfiguration.model_validate(
            _policy_engine([{"role": "dev", field: ["*"]}])
        )

    def test_unknown_rule_key_rejected(self) -> None:
        """Unknown keys fail (extra=forbid)."""
        assert _error(_policy_engine([{"role": "dev", "bogus": 1}]))


class TestReservedFields:
    """Phase 3 fields load only at their default."""

    @pytest.mark.parametrize(
        "field,value",
        [
            ("mcp", ["srv"]),
            ("inline_mcp", True),
            ("inline_mcp_hosts", ["example.com"]),
            ("mcp_secrets", ["s"]),
            ("ssrf", True),
        ],
    )
    def test_non_default_rejected(self, field: str, value: Any) -> None:
        """Each reserved field fails with the Phase 3 message."""
        error = _error(_policy_engine([{"role": "dev", field: value}]))
        assert "not supported until phase 3" in error
        assert field in error

    @pytest.mark.parametrize(
        "field,value",
        [
            ("mcp", None),
            ("mcp", []),
            ("inline_mcp", False),
            ("inline_mcp_hosts", None),
            ("inline_mcp_hosts", []),
            ("mcp_secrets", []),
            ("ssrf", False),
        ],
    )
    def test_default_accepted(self, field: str, value: Any) -> None:
        """Default values load."""
        WorkflowEngineConfiguration.model_validate(
            _policy_engine([{"role": "dev", field: value}])
        )


class TestLimits:
    """Hard caps and numeric typing."""

    def test_cap_constants(self) -> None:
        """Hard caps are pinned."""
        assert limits.MAX_POLICY_STEP_TIMEOUT_SECONDS == 3600
        assert limits.MAX_POLICY_WORKFLOW_SECONDS == 86400
        assert limits.MAX_POLICY_RETRIES == 5
        assert limits.MAX_POLICY_TOKENS == 1_000_000

    @pytest.mark.parametrize(
        "field,cap",
        [
            ("max_step_timeout_seconds", limits.MAX_POLICY_STEP_TIMEOUT_SECONDS),
            ("max_workflow_seconds", limits.MAX_POLICY_WORKFLOW_SECONDS),
            ("max_retries", limits.MAX_POLICY_RETRIES),
            ("max_tokens", limits.MAX_POLICY_TOKENS),
        ],
    )
    def test_cap_boundary(self, field: str, cap: int) -> None:
        """Equal to the cap passes; cap + 1 fails."""
        WorkflowEngineConfiguration.model_validate(
            _policy_engine([{"role": "dev", "limits": {field: cap}}])
        )
        assert field in _error(
            _policy_engine([{"role": "dev", "limits": {field: cap + 1}}])
        )

    @pytest.mark.parametrize("value", ["unbounded", "10", 1.5, True, -1])
    def test_non_int_or_negative_rejected(self, value: Any) -> None:
        """Strings (including 'unbounded'), floats, bools and negatives fail."""
        assert _error(
            _policy_engine([{"role": "dev", "limits": {"max_tokens": value}}])
        )

    def test_unbounded_message(self) -> None:
        """The unbounded rejection is explicit."""
        assert "unbounded" in _error(
            _policy_engine([{"role": "dev", "limits": {"max_tokens": "unbounded"}}])
        )


class TestInheritClosure:
    """Transitive inherit closure computed at load."""

    @staticmethod
    def _config() -> WorkflowEngineConfiguration:
        """Engine config with a three-level inherit chain."""
        return WorkflowEngineConfiguration.model_validate(
            _policy_engine(
                [
                    {"role": "base", "tools": ["a"]},
                    {"role": "mid", "inherit": ["base"], "tools": ["b"]},
                    {"role": "top", "inherit": ["mid"], "tools": ["c"]},
                    {"role": "other", "tools": ["z"]},
                    {"role": "*", "tools": ["w"]},
                ]
            )
        )

    def test_transitive(self) -> None:
        """A role gets its own rule plus every inherited rule."""
        policy = self._config().policy
        assert policy is not None
        tools = sorted(t for r in policy.rules_for({"top"}) for t in r.tools or [])
        assert tools == ["a", "b", "c"]

    def test_union_of_roles_and_unknown_role_ignored(self) -> None:
        """Several roles union; roles with no rule contribute nothing."""
        policy = self._config().policy
        assert policy is not None
        rules = policy.rules_for({"base", "other", "nobody", "*"})
        assert sorted(t for r in rules for t in r.tools or []) == ["a", "w", "z"]

    def test_empty(self) -> None:
        """No roles gives no rules."""
        policy = self._config().policy
        assert policy is not None
        assert not policy.rules_for(set())

    def test_duplicate_role_rules_both_apply(self) -> None:
        """Two rules for the same role both apply."""
        config = WorkflowEngineConfiguration.model_validate(
            _policy_engine(
                [{"role": "a", "tools": ["x"]}, {"role": "a", "tools": ["y"]}]
            )
        )
        assert config.policy is not None
        assert len(config.policy.rules_for({"a"})) == 2


class TestAuthModuleCheck:
    """D8: non-wildcard grants need roles that only jwk-token can supply."""

    def test_jwk_with_rules_ok(self) -> None:
        """jwk-token with role_rules and access_rules loads."""
        Configuration.model_validate(
            _root(_policy_engine(GRANTING_RULES), JWK_AUTH, authorization=ACCESS_RULES)
        )

    def test_jwk_without_access_rules_fails(self) -> None:
        """Missing access_rules means the middleware gives only '*'."""
        with pytest.raises(ValidationError, match="jwk-token"):
            Configuration.model_validate(
                _root(_policy_engine(GRANTING_RULES), JWK_AUTH)
            )

    def test_jwk_without_role_rules_fails(self) -> None:
        """Missing role_rules means the middleware gives only '*'."""
        auth = {
            "module": "jwk-token",
            "jwk_config": {"url": "https://example.com/jwks"},
        }
        with pytest.raises(ValidationError, match="role_rules"):
            Configuration.model_validate(
                _root(_policy_engine(GRANTING_RULES), auth, authorization=ACCESS_RULES)
            )

    @pytest.mark.parametrize(
        "authentication",
        [
            None,
            {"module": "noop"},
            {"module": "noop-with-token"},
            {"module": "rh-identity", "rh_identity_config": {}},
            {
                "module": "trusted-proxy",
                "trusted_proxy_config": {"allowed_service_accounts": []},
            },
        ],
    )
    def test_other_modules_fail_for_non_wildcard_grant(
        self, authentication: dict[str, Any] | None
    ) -> None:
        """Every other module only yields '*', so a role grant is unreachable."""
        with pytest.raises(ValidationError, match="jwk-token"):
            Configuration.model_validate(
                _root(
                    _policy_engine(GRANTING_RULES),
                    authentication,
                    authorization=ACCESS_RULES,
                )
            )

    @pytest.mark.parametrize("authentication", [None, {"module": "noop"}, JWK_AUTH])
    def test_wildcard_only_policy_loads(
        self, authentication: dict[str, Any] | None
    ) -> None:
        """A policy that only grants to '*' works with any module."""
        Configuration.model_validate(
            _root(_policy_engine(WILDCARD_RULES), authentication)
        )

    def test_empty_non_wildcard_role_ok(self) -> None:
        """A non-wildcard role that grants nothing needs no jwk-token."""
        Configuration.model_validate(
            _root(_policy_engine(WILDCARD_RULES + [{"role": "dev"}]))
        )

    def test_inherited_grant_counts(self) -> None:
        """A non-wildcard role that inherits a granting rule needs jwk-token."""
        rules = [
            {"role": "*", "providers": ["claude-prod"]},
            {"role": "dev", "inherit": ["*"]},
        ]
        with pytest.raises(ValidationError, match="jwk-token"):
            Configuration.model_validate(_root(_policy_engine(rules)))

    @pytest.mark.parametrize(
        "rule",
        [
            {"role": "dev", "advisory": True},
            {"role": "dev", "limits": {"max_retries": 1}},
        ],
    )
    def test_limit_or_advisory_counts_as_grant(self, rule: dict[str, Any]) -> None:
        """Advisory and limits are grants too."""
        with pytest.raises(ValidationError, match="jwk-token"):
            Configuration.model_validate(_root(_policy_engine([rule])))

    def test_no_policy_unaffected(self) -> None:
        """Without a policy, auth modules are unconstrained."""
        Configuration.model_validate(_root(_engine()))
