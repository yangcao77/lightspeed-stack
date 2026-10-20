# Client-owned context with shields on `/v1/responses`

|                          |                                                                          |
|--------------------------|--------------------------------------------------------------------------|
| **Date**                 | 2026-10-19                                                               |
| **Component**            | lightspeed-stack                                                         |
| **Authors**              | Andrej Šimurka                                                           |
| **Spike**                | [LCORE-4801](https://redhat.atlassian.net/browse/LCORE-4801)             |

## Overview

**The problem**: Clients that own their own context (`store: false`, no conversation id) resend the full history on every `/v1/responses` call. Shields moderate the entire extracted `input`. Once a blocked turn is in that history, every later request is refused — even when the new user turn is clean. Sessions become unusable until the client clears or edits history. The other supported pattern (conversation id + server-side store) is an alternative, but does not fit these clients. Disabling shields is not acceptable where guardrails are required.

**Why this hits `/v1/responses` consumers**: Goose, OpenCode, Codex, and similar agents treat LCORE as a stateless model endpoint. They already own context. Today, shield refusals use `modr-` response ids; clients keep those items in history. LCORE then re-moderates them forever. Conversation-managed clients (`conversation` + `store: true`) typically send only the newest turn as `input`, so they are largely unaffected.

**The recommendation**: Go with an opt-in **custom request header** (Option **1b**) that tells LCORE to apply shields only to input items *after* the last moderated refusal (`modr-…`) already present in the resent history. Default remains today’s full-input moderation — **no breaking change**. Precedent: `X-LCS-Merge-Server-Tools` (backend-centric opt-in for clients; no client code required beyond sending the header).

**Product stance**: For opted-in client-owned-context sessions, continuation after a refused turn is allowed when the client resends history. Blocked text may still be present in model context if the client keeps it; the shield window only skips re-judging already-refused prefix content. Deployments that require “blocked content must never enter the model” should keep the default (no header).

---

## Behavioral options

### Option 1a — Request-body boolean

Per-request boolean (e.g. `shield_after_last_refusal: true`) on the Responses payload. When set, LCORE finds the **last** moderated item in `input` (the most recent item whose id is `modr-…`) and applies shields only to the suffix after that item.

| | |
|--|--|
| **Pros** | Explicit in the JSON body; easy to discover in OpenAPI; mirrors other LCORE request extensions (`shield_ids`). |
| **Cons** | Requires every client SDK/schema update; harder to roll out “backend-only” without client changes. |

**Verdict**: Viable; not preferred (client schema churn).

### Option 1b — Custom header (selected)

Same moderation-window semantics as 1a, enabled by a custom header, analogous to [`X-LCS-Merge-Server-Tools`](../../devel_doc/responses.md#server-tool-merging).

Proposed name:

```http
X-LCS-Shield-After-Last-Refusal: true
```

Behavior when `true`:

1. Client resends full history including one or more prior refusal items with id `modr-…`.
2. LCORE locates the **last** moderated item in `input` (the most recent `modr-…`).
3. Shields run only on text extracted from items **after** that refusal.
4. If no `modr-` item is present, behavior matches today (moderate full input).

| | |
|--|--|
| **Pros** | Backend-centric; Goose needs only a static header (same pattern as tool merge); OpenAI-compatible body unchanged; easy to document next to existing `X-LCS-*` headers; default off → no breaking change for conversation/`store` clients. |
| **Cons** | Header discoverability weaker than a body field; clients must retain `modr-` items in history for the window to work (or else full history is moderated again). |

**Verdict**: **Selected** after agreement.

### Option 2 — Integer window (`shield_input_items: N`)

Client sends how many of the **most recent** input items to moderate. LCORE truncates the moderation window from the end; older items are not shield-scanned.

| | |
|--|--|
| **Pros** | Precise client control; no dependency on `modr-` ids remaining in history. |
| **Cons** | Client must track “which turn was blocked” and keep `N` correct across edits/compaction; more complex client logic required; easy to misconfigure (`N` too small → skip bad new content; `N` too large → re-poison). |

**Verdict**: Possible later if header mode proves insufficient.

---

## Client guidance

**When to use what**

| Pattern | Use when |
|---------|----------|
| `conversation` + `store: true` | Server-owned history; shields see only the new turn. |
| Full history + `store: false` | Client-owned context. Send `X-LCS-Shield-After-Last-Refusal: true` if shields are enabled. |

**On shield refusal**

1. Response id is `modr-…` (not `resp_…`); HTTP typically still 200 with refusal text.
2. Keep the refusal item in client history (do not strip `modr-`).
3. Continue; send the same header on subsequent requests. LCORE skips re-moderating the prefix up through that refusal and judges only newer turns.
4. Optional: client may still drop/edit the offending user turn for a cleaner transcript; if no `modr-` remains, full-input moderation applies again.

**No other Goose code required** beyond the header (same rollout model as `X-LCS-Merge-Server-Tools`).

---
