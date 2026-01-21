# E2E Test Configuration Files

This directory contains configuration files used for end-to-end testing of Lightspeed Core.

## Directory Structure

- `server-mode/` - Configurations for testing when LCore connects to a separate Llama Stack service
- `library-mode/` - Configurations for testing when LCore embeds Llama Stack as a library

## Common Configuration Features

### Default Configurations (`lightspeed-stack.yaml`)

Both server-mode and library-mode default configurations include:

1. **MCP Servers** - Used for testing MCP-related endpoints:
   - `github-api` - Uses client-provided auth (Authorization header)
   - `gitlab-api` - Uses client-provided auth (X-API-Token header)
   - `k8s-service` - Uses kubernetes auth (not client-provided)
   - `public-api` - No authentication (not client-provided)

   These servers test the `/v1/mcp-auth/client-options` endpoint, which should return only servers accepting client-provided authentication (`github-api` and `gitlab-api`).

2. **Authentication** - Set to `noop` for most tests

3. **User Data Collection** - Enabled for feedback and transcripts testing

### Special-Purpose Configurations

- `lightspeed-stack-auth-noop-token.yaml` - For authorization testing
- `lightspeed-stack-invalid-feedback-storage.yaml` - For negative feedback testing
- `lightspeed-stack-no-cache.yaml` - For cache-disabled scenarios
