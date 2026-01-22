# JWK Token Authentication (`jwk-token`)

JSON Web Key Set (JWK) based authentication for scenarios requiring JWT token
validation. Commonly used with OAuth2/OIDC identity providers.

## Overview

The `jwk-token` module:
1. Fetches the JWK set from a configured URL
2. Validates JWT signatures against the JWK set
3. Extracts user identity from configurable JWT claims
4. Supports role extraction for authorization

## Configuration

### Basic Configuration

```yaml
authentication:
  module: jwk-token
  jwk_config:
    url: https://auth.example.com/.well-known/jwks.json
```

### Full Configuration

```yaml
authentication:
  module: jwk-token
  jwk_config:
    url: https://auth.example.com/.well-known/jwks.json
    jwt_configuration:
      user_id_claim: sub              # optional, defaults to 'sub'
      username_claim: preferred_username  # optional, defaults to 'preferred_username'
      role_rules: []                  # optional, see Role Extraction below
```

### Configuration Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `url` | Yes | - | URL to fetch JWK set |
| `user_id_claim` | No | `sub` | JWT claim for user ID |
| `username_claim` | No | `preferred_username` | JWT claim for username |
| `role_rules` | No | `[]` | Rules for extracting roles from JWT |

## Behavior

### JWK Set Caching

- JWK set is fetched from the configured URL
- Cached for 1 hour to reduce network overhead
- Automatically refreshed when cache expires

### Token Validation

1. Extract bearer token from `Authorization` header
2. Decode JWT and extract key ID (`kid`)
3. Find matching key in JWK set
4. Validate signature using the key
5. Extract user identity from claims

### Guest Access

If no `Authorization` header is present, the module returns default guest-like
credentials instead of rejecting the request.

## Role Extraction

Extract roles from JWT claims using JSONPath expressions for use with the
authorization system.

### Role Rules Configuration

```yaml
authentication:
  module: jwk-token
  jwk_config:
    url: https://auth.example.com/.well-known/jwks.json
    jwt_configuration:
      role_rules:
        # Match if realm_access.roles contains "manager"
        - jsonpath: "$.realm_access.roles[*]"
          operator: contains
          value: "manager"
          roles: ["manager"]

        # Match if org_id equals specific values
        - jsonpath: "$.org_id"
          operator: equals
          value: [["dummy_corp"]]
          roles: ["dummy_employee"]

        # Match if user is in specific groups
        - jsonpath: "$.groups[*]"
          operator: in
          value: ["developers", "qa"]
          roles: ["developer"]
          negate: false
```

### Rule Fields

| Field | Required | Description |
|-------|----------|-------------|
| `jsonpath` | Yes | JSONPath expression to extract values from JWT |
| `operator` | Yes | Comparison operator (see below) |
| `value` | Yes | Value(s) to compare against |
| `roles` | Yes | Roles to assign if rule matches |
| `negate` | No | Invert match result (default: false) |

### Operators

| Operator | Description |
|----------|-------------|
| `equals` | Exact match between extracted and configured values |
| `contains` | Extracted value contains the configured string |
| `in` | Extracted value is in the configured list |
| `match` | Regex pattern match (uses pre-compiled patterns) |

> **Note**: JSONPath expressions always yield a list of values, even for
> single-value expressions. Comparisons should account for this.

## Request Example

```bash
# Get token from your identity provider
TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."

# Make authenticated request
curl http://localhost:8080/v1/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "Hello"}'
```

## Common Identity Providers

### Keycloak

```yaml
authentication:
  module: jwk-token
  jwk_config:
    url: https://keycloak.example.com/realms/myrealm/protocol/openid-connect/certs
    jwt_configuration:
      user_id_claim: sub
      username_claim: preferred_username
      role_rules:
        - jsonpath: "$.realm_access.roles[*]"
          operator: contains
          value: "admin"
          roles: ["admin"]
```

### Auth0

```yaml
authentication:
  module: jwk-token
  jwk_config:
    url: https://your-tenant.auth0.com/.well-known/jwks.json
    jwt_configuration:
      user_id_claim: sub
      username_claim: email
```

### Azure AD

```yaml
authentication:
  module: jwk-token
  jwk_config:
    url: https://login.microsoftonline.com/{tenant-id}/discovery/v2.0/keys
    jwt_configuration:
      user_id_claim: oid
      username_claim: preferred_username
```
