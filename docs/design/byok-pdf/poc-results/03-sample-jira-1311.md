## Red Hat Jira and Confluence Data Centre will be unavailable from 5 PM EDT on March 13 to 12 AM EDT on March 16 due to the migration to Atlassian Cloud

<!-- image -->

## Lightspeed Core LCORE-1311

## Conversation History Summarization (Compaction)

## Details

Type:

Feature

Resolution:

Unresolved

Priority:

Undefined

Fix Version/s:

Q2CY26

Affects Version/s:

None

Component/s:

None

Labels:

ols-lcore-migration

Blocked:

False

Blocked Reason:

None 

Ready:

False

SFDC Cases Links:

SFDC Cases Open:

0

SFDC Cases Counter:

0

Intelligence

Requested:

False

Market:

Unclassified

## Description

<!-- image -->

<!-- image -->

## LCORE Feature Request: Conversation History Summarization

## Summary

Implement intelligent conversation history summarization to maintain context when conversations approach the model's context window limit, preventing loss of important context while enabling long-running conversations.

## Background

Related ticket: OLS-2500 - [Review] : Summarize conversation when context limit is reached

## User Story

As an LCS user, I want the conversation history to be intelligently summarized when it exceeds the context window limit, so that the assistant maintains an accurate understanding of previous interactions without losing important context.

## Problem Statement

Currently, neither lightspeed-stack nor Llama Stack implements context management for long conversations:

- When context window is exceeded, requests fail with HTTP 413 (Prompt Too Long)
- No automatic truncation or summarization exists
- The truncated field in responses is hardcoded to False with TODO comments

## Technical Analysis

Current State

| Component            | Behavior                                                                                            |
|----------------------|-----------------------------------------------------------------------------------------------------|
| lightspeed-stack     | Returns PromptTooLongResponse (413) on overflow. truncated field not implemented.                   |
| Llama Stack          | Loads ALL conversation history via Conversations API + ResponsesStore. No truncation/summarization. |
| OpenAI Responses API | Has truncation parameter (auto/disabled) AND compact endpoint for summarization                     |

OpenAI API Spec (Reference Implementation)

OpenAI's Responses API includes two relevant features:

1. truncation parameter on create response:
2. auto : Drops items from beginning of conversation to fit context window
3. disabled (default): Fails with 400 error if context exceeded
2. compact endpoint ( POST /v1/responses/compact ):
5. Runs compaction/summarization pass over conversation
6. Returns compacted response object with encrypted/opaque items

## Neither feature is currently implemented in Llama Stack.

Llama Stack Storage Architecture

Llama Stack uses two storage mechanisms for conversation history:

1. Conversations API ( conversations\_api.list\_items() )
2. Stores ConversationItem objects (high-level: messages, tool calls)
3. Used for listing/managing conversations
2. ResponsesStore ( responses\_store.get\_conversation\_messages() )
5. Stores raw OpenAIMessageParam list (what actually goes to LLM)
6. Stored in conversation\_messages table
7. Source of truth for building LLM context

Both mechanisms store full history without any summarization or truncation.

## Impact Analysis

| Area               | Impact                                                              |
|--------------------|---------------------------------------------------------------------|
| Transcripts        | No impact - captures individual Q/A pairs, not conversation history |
| Conversation Cache | TBD - needs schema changes to store summary metadata                |
| Llama Stack        | Depends on implementation location                                  |

Transcripts Detail

Transcripts store individual Q/A pairs per turn. The truncated field already exists to flag when truncation occurred. If summarization happens, transcripts would still capture the original query/response for that turn - this is the intended behavior.

Conversation Cache Detail

If implemented in lightspeed-stack, the conversation cache would need schema changes.

## Design Considerations

Key Principle: Decouple Storage from LLM Context

## Storage and LLM context should be decoupled:

- Full history preserved (for UI/audit/replay)
- Summary used only when building LLM context
- User sees all messages; AI gets summarized context for older turns

This follows the pattern used by tools like Cursor/Claude - you can scroll up and see your full conversation, but the AI may only have summarized context of older turns.

Summarization Trigger

Summarization should be token-based, not turn-based (turn sizes vary significantly).

Incremental Summarization

Summary should be computed once, stored, and reused - not recomputed on every request.

## Open Questions

1. Should this be implemented in Llama Stack (where conversation history is managed) or lightspeed-stack?
2. If Llama Stack, what's the timeline/feasibility for upstream contribution?
3. How should summary storage interact with existing conversation cache schema?
4. What summarization prompt/strategy provides best context preservation?
5. How to handle model-specific context window sizes (configurable vs auto-detected)?

## Acceptance Criteria

1. When conversation history approaches context window limit, older messages are summarized (not just truncated)
2. Summary preserves clear attribution of actions (user vs assistant)
3. Summarization threshold is configurable or auto-determined based on model context window
4. Summarization is incremental (summary updated, not recomputed from scratch)
5. Full conversation history remains accessible (UI/audit) - only LLM context uses summary
6. Assistant correctly recalls and references prior context after summarization

## References

- OLS-2500: Original OLS ticket
- OpenAI Responses API
- OpenAI Compact endpoint
- OpenAI Conversation State Guide

## Attachments

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

Live updates

No child issues.

Assignee:

Assign to me

Reporter:

Votes:

- Vote for this issue 0

Watchers:

- Start watching this issue 3

Drop files to attach, or browse.

## is blocked by

## Issue Links

LCORE-1314 [Spike] Finalize scope of the feature request

IN PROGRESS

- Easy Agile Planning Poker

Quick tour

Vote

## Child issues

## Activity

## Newest first

- You can now pin up to five comments to highlight important information. Pinned comments will appear above all other comments, so they're easy to find. 

Got it

Learn more about pinned comments

- added a comment - 2026/02/11 4:29 PM  Anxhela Coba

Is the goal of the conversation history summarization task more about preventing missing information? In fine-tuning when we compress models from larger to more domain-specific they can be prone to catastrophic forgetting. I wonder if we can explore for this.. techniques like SVD ( singular vector decomposition) for this task.

ex. if we can take the embedding of the history we can apply SVD or some similar technique to help "summarize"

Pin

- added a comment - 2026/02/09 4:07 PM

Note: if it is implemented on the provider/openai API level - then this feature is locked for providers conforming to these particular endpoints.

-  Ondrej Metelka

Pin

## People

Unassigned

Ondrej Metelka 

<!-- image -->

## Dates

Created:

2026/02/09 3:45 PM

Updated:

2026/03/10 3:13 PM

## Agile