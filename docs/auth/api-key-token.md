# API Key Token Authentication (`api-key-token`)

Simple API key authentication for service-to-service communication or
controlled access scenarios.

## Overview

The `api-key-token` module validates requests by comparing the bearer token
against a pre-configured API key.

## Configuration

```yaml
authentication:
  module: api-key-token
  api_key_config:
    api_key: "your-secret-api-key"
```

### Configuration Options

| Option | Required | Description |
|--------|----------|-------------|
| `api_key` | Yes | The API key that clients must provide |

## Behavior

1. Extracts bearer token from the `Authorization` header
2. Compares token against configured `api_key`
3. Rejects request if token doesn't match
4. Uses same user ID and username handling as `noop` module

### User Identity

Since API key authentication doesn't carry user identity information:
- `user_id`: Defaults to `00000000-0000-0000-0000-000` or from query parameter
- `username`: Fixed as `lightspeed-user`

## Request Example

```bash
curl http://localhost:8080/v1/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-api-key" \
  -d '{"query": "Hello"}'
```

## Security Considerations

### Best Practices

1. **Use strong, random API keys**: Generate keys with sufficient entropy
   ```bash
   openssl rand -hex 32
   ```

2. **Store keys securely**: Use environment variables or secret management
   ```yaml
   authentication:
     module: api-key-token
     api_key_config:
       api_key: ${API_KEY}  # From environment variable
   ```

3. **Rotate keys regularly**: Implement key rotation procedures

4. **Use HTTPS**: Always use TLS in production to protect keys in transit

### Limitations

- No user identity information (shared credential)
- Single key for all clients (no granular access control)
- No automatic key rotation

### When to Use

- Internal service-to-service communication
- Simple integrations with trusted clients
- Scenarios where OAuth2/OIDC is overkill

### When NOT to Use

- User-facing applications (use `jwk-token` instead)
- Multi-tenant environments (no user distinction)
- Scenarios requiring audit trails per user
