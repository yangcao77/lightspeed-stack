# How to organize PoC output

When a spike includes a proof-of-concept, the validation results should be
structured so that reviewers can quickly understand what was tested and what was
found.

## Directory structure

Place results in `docs/design/<feature>/poc-results/`.

Name files with a numeric prefix that reflects reading order.  Order them by
usefulness for the human reviewer:

```
poc-results/
├── 01-poc-report.txt       — findings, methodology, implications
├── 02-conversation-log.txt  — human-readable record of the PoC
├── 03-token-usage.txt       — quantitative data
├── 04-events.json           — structured event data
├── 05-summaries.txt         — extracted outputs
├── ...
└── NN-raw-data.json         — full machine-readable data
```

Not all files apply to every PoC, use ones that make sense.

## What a good report file contains

The report file (`01-poc-report.txt`) is the most important output.  A
reviewer who reads only this file should understand everything significant.

Include:

- **Glossary**: Define terms specific to the PoC.
- **PoC design**: What was tested, how, what parameters.
- **Results**: What happened, with numbers.
- **Findings**: What the results mean for the production design — what was
  proved, disproved, or surprising.
- **Implications**: How the findings influence the design decisions in the
  spike doc and spec doc.

## What NOT to include in the merge

PoC results are removed before merging the spike PR (see
[howto-run-a-spike.md](howto-run-a-spike.md), step 10).  They serve their
purpose during review and are preserved in git history.

## Naming conventions

- Use plain English filenames, not timestamps or hashes.
- Prefer `.txt` for human-readable content, `.json` for structured data.
- If there are multiple PoC runs, use separate directories or name them
  descriptively: `poc-results-5-query/`, `poc-results-50-query/`.
