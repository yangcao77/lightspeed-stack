# No-op Authentication Modules

Development-only authentication modules that bypass or minimize security checks.
These modules are intended for local development and testing only.

> **Warning**: Never use these modules in production environments.

## No-op (`noop`)

Development authentication that completely bypasses security checks.

### Configuration

```yaml
authentication:
  module: noop
```

### Behavior

- Accepts any request without token validation
- Extracts `user_id` from query parameters (defaults to `00000000-0000-0000-0000-000`)
- Uses fixed username `lightspeed-user`
- No authorization checks performed

### Use Cases

- Local development without authentication overhead
- Quick prototyping and testing
- CI/CD pipeline testing

## No-op with Token (`noop-with-token`)

Development authentication that requires tokens but doesn't validate them.

### Configuration

```yaml
authentication:
  module: noop-with-token
```

### Behavior

- Extracts bearer token from the `Authorization` header
- Same user ID and username handling as `noop`
- Token is passed through unvalidated for downstream use
- Useful for testing token passthrough behavior

### Use Cases

- Testing downstream components that need tokens
- Verifying token extraction logic
- Development environments with partial authentication

## Request Examples

### No-op Module

```bash
# Basic request (no auth required)
curl http://localhost:8080/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Hello"}'

# With custom user_id
curl "http://localhost:8080/v1/query?user_id=test-user-123" \
  -H "Content-Type: application/json" \
  -d '{"query": "Hello"}'
```

### No-op with Token Module

```bash
# Token required but not validated
curl http://localhost:8080/v1/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer any-token-value" \
  -d '{"query": "Hello"}'
```
