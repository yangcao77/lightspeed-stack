# Authentication and Authorization

Lightspeed Core Stack implements a modular authentication and authorization
system with multiple authentication methods. Authorization is configurable
through role-based access control.

## Configuration

The authentication system is configured via the `authentication` section in
the Lightspeed Core Stack configuration file (`lightspeed-stack.yaml`).

```yaml
authentication:
  module: <module-name>
  # Module-specific configuration options
```

## Available Modules

| Module | Use Case | Documentation |
|--------|----------|---------------|
| `noop` | Development only - no security | [No-op Modules](noop.md) |
| `noop-with-token` | Development with token passthrough | [No-op Modules](noop.md) |
| `k8s` | Kubernetes/OpenShift deployments | [Kubernetes](kubernetes.md) |
| `jwk-token` | JWT/OAuth2 authentication | [JWK Token](jwk-token.md) |
| `api-key-token` | Static API key authentication | [API Key Token](api-key-token.md) |
| `rh-identity` | Red Hat Hybrid Cloud Console | [Red Hat Identity](rh-identity.md) |

## Choosing a Module

### Production Deployments

- **Kubernetes/OpenShift**: Use `k8s` for native cluster authentication
- **Red Hat Console**: Use `rh-identity` when behind console.redhat.com
- **OAuth2/OIDC**: Use `jwk-token` with your identity provider
- **Simple API Access**: Use `api-key-token` for service-to-service auth

### Development

- **Local Testing**: Use `noop` for quick iteration without auth overhead
- **Token Testing**: Use `noop-with-token` to test token passthrough behavior

## Authentication Flow

```
Request → Authentication Module → User Identity → Role Resolution → Access Check → Endpoint
```

Each authentication module extracts user identity (user_id, username) from the
request. The authorization system then determines what actions the user can
perform based on their assigned roles.

## Authentication Tuple

All authentication modules return a consistent tuple containing:

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | `str` | Unique identifier for the user |
| `username` | `str` | Human-readable username |
| `skip_userid_check` | `bool` | Whether to skip user ID validation |
| `token` | `str` | Authentication token (if applicable) |

This tuple is used by downstream components for authorization and audit logging.

## Authorization

For role-based access control configuration, see [Authorization](authorization.md).
