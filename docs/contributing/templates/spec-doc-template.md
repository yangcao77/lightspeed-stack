Reference: [conversation-compaction.md](../../design/conversation-compaction/conversation-compaction.md) (LCORE-1311)

|                    |                                           |
|--------------------|-------------------------------------------|
| **Date**           | TODO                                      |
| **Component**      | TODO                                      |
| **Authors**        | TODO                                      |
| **Feature**        | TODO: [LCORE-XXXX](https://redhat.atlassian.net/browse/LCORE-XXXX) |
| **Spike**          | TODO: [LCORE-XXXX](https://redhat.atlassian.net/browse/LCORE-XXXX) |
| **Links**          | TODO                                      |

# What

TODO: What does this feature do?

# Why

TODO: What problem does this solve? What happens today without it?

# Requirements

TODO: Numbered, testable requirements. For each, it should be easy to provide clear acceptance criteria.

- **R1:**
- **R2:**

# Use Cases

TODO: User stories in "As a [role], I want [X], so that [Y]" format.

- **U1:**
- **U2:**

# Architecture

## Overview

TODO: Flow diagram showing the request/response path with the new feature.

```text
TODO: flow diagram
```

TODO: Add subsections below for each relevant component. Delete any that don't apply, add feature-specific ones.

## Trigger mechanism

TODO: When and how the feature activates.

## Storage / data model changes

TODO: Schema changes, which backends need updates.

## Configuration

TODO: YAML config example and configuration class.

``` yaml
TODO: config example
```

``` python
TODO: configuration class
```

## API changes

TODO: New or changed fields in request/response models.

## Error handling

TODO: How errors are surfaced — new error types, HTTP status codes, recovery behavior.

## Security considerations

TODO: Auth, access control, data sensitivity implications. Remove if not applicable.

## Migration / backwards compatibility

TODO: Schema migrations, API versioning, feature flags for gradual rollout. Remove if not applicable.

# Implementation Suggestions

## Key files and insertion points

TODO: Table of files to create or modify.

| File | What to do |
|------|------------|
| TODO | TODO       |

## Insertion point detail

TODO: Where the feature hooks into existing code — function name, what's available at that point, what the code should do.

## Config pattern

All config classes extend `ConfigurationBase` which sets `extra="forbid"`.
Use `Field()` with defaults, title, and description.  Add
`@model_validator(mode="after")` for cross-field validation if needed.

Example config files go in `examples/`.

## Test patterns

- Framework: pytest + pytest-asyncio + pytest-mock.  unittest is banned by ruff.
- Mock Llama Stack client: `mocker.AsyncMock(spec=AsyncLlamaStackClient)`.
- Patch at module level: `mocker.patch("utils.module.function_name", ...)`.
- Async mocking pattern: see `tests/unit/utils/test_shields.py`.
- Config validation tests: see `tests/unit/models/config/`.

TODO: Describe any feature-specific test considerations (e.g., tests that need a running service, special fixtures, concurrency testing).

# Open Questions for Future Work

TODO: Things explicitly deferred and why.

-
-

# Changelog

TODO: Record significant changes after initial creation.

| Date | Change | Reason |
|------|--------|--------|
|      | Initial version |        |

# Appendix A

TODO: Supporting material — PoC evidence, API comparisons, reference sources. Add appendices as needed.
