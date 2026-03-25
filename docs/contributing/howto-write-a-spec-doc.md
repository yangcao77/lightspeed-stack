# How to write a spec doc

A spec doc is the permanent in-repo feature specification.  It is the single
source of truth for what the feature does and how it works.  All implementation
JIRAs reference it.  Agentic coding tools read it for guidance.

**Claude Code shortcut**: `/spec-doc` creates one interactively.

## When to write one

- As part of a spike (see [howto-run-a-spike.md](howto-run-a-spike.md), step 6).
- When a feature is well-understood but not yet documented.
- When an existing feature needs a retroactive spec.

## How to write one

Use [spec-doc-template.md](templates/spec-doc-template.md).

### Location

Place the spec doc at `docs/design/<feature>/<feature>.md`.

### Filling in the template

**What**: Describes the feature.

**Why**: The problem it solves.

**Requirements (Rx)**: Numbered requirements.  For each requirement it should be
easy to provide clear acceptance criteria.

**Use Cases (Ux)**: "As a [role], I want [X], so that [Y]."

**Architecture**: Flow diagram, then subsections for each component.  Include
where things live (file paths), function signatures, schemas, configuration.

**Implementation Suggestions**: File paths, insertion points, code patterns,
test patterns.  Be specific — this section is read by both humans and agentic
coding tools.

**Latency and Cost**: How the feature affects performance.  Include if
applicable to the feature.

**Open Questions**: Things explicitly deferred, and why.

**Changelog**: Record significant changes after initial creation.  Date, what
changed, why.

**Appendices**: PoC evidence, API comparisons, reference sources.

### Relationship to the spike doc

The spike doc records everything that was considered.

The spec doc records the approved decisions.

### Keeping it up to date

The spec doc is a living document.  Update it when:
- A decision is changed.
- Implementation reveals something the spec didn't anticipate.
- A reviewer raises a point that changes the design.
