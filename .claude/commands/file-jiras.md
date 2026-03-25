Parse proposed JIRAs from a spike doc and file them via the Jira API

You are filing JIRA sub-tickets for a Lightspeed Core feature.

The user will provide either a spike doc path or tell you which feature's
JIRAs to file.  They will also provide the parent JIRA ticket number.

## Credentials

Jira credentials must be in `~/.config/jira/credentials.json`.  If this file
doesn't exist, tell the user to create it (see `dev-tools/file-jiras.sh` for
the format and instructions).

## Process

1. Run `dev-tools/file-jiras.sh <spike-doc.md> <parent-ticket>` with
   `echo "quit"` piped in, so it parses and exits without filing.

2. Read every file in `/tmp/jiras/`.  For each, verify:
   - Content matches the corresponding section in the spike doc (no truncation,
     no extra content swallowed from subsequent sections).

3. Report any issues to the user.  If all files look correct, tell the user
   to run the script interactively — provide the full command including `cd`
   to the repository root:
   `cd <repo-path> && sh dev-tools/file-jiras.sh <spike-doc.md> <parent-ticket>`
