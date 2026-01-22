# Kubernetes Authentication (`k8s`)

Kubernetes-based authentication for running Lightspeed Stack in Kubernetes or
OpenShift environments. Users must have a valid Kubernetes token and appropriate
RBAC permissions.

## Overview

The `k8s` authentication module:
1. Validates bearer tokens via the Kubernetes TokenReview API
2. Performs authorization checks using SubjectAccessReview (SAR)
3. Checks access to a configured virtual path (default: `/ls-access`) with `get` verb
4. Extracts user ID and username from token claims

## RBAC Requirements

Users must have the `get` permission on the Kubernetes RBAC non-resource URL
`/ls-access`. Create a ClusterRole and ClusterRoleBinding:

```yaml
# Allow GET on non-resource URL /ls-access
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: lightspeed-access
rules:
  - nonResourceURLs: ["/ls-access"]
    verbs: ["get"]
---
# Bind to a user, group, or service account
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: lightspeed-access-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: lightspeed-access
subjects:
  - kind: User            # or ServiceAccount, Group
    name: SOME_USER_OR_SA
    apiGroup: rbac.authorization.k8s.io
```

## Configuration

### In-Cluster Deployment

When deploying inside a Kubernetes cluster, connection details are automatically
detected:

```yaml
authentication:
  module: k8s
```

### External Deployment

When running outside the cluster or connecting to external clusters, specify
connection details:

```yaml
authentication:
  module: k8s
  k8s_cluster_api: https://kubernetes.default.svc
  k8s_ca_cert_path: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
  skip_tls_verification: false  # optional, insecure
```

### Configuration Options

| Option | Required | Description |
|--------|----------|-------------|
| `k8s_cluster_api` | No | Kubernetes API server URL (auto-detected in-cluster) |
| `k8s_ca_cert_path` | No | Path to CA certificate for TLS verification |
| `skip_tls_verification` | No | Skip TLS verification (insecure, not recommended) |

## Behavior

### Token Validation

1. Extract bearer token from `Authorization` header
2. Submit token to Kubernetes TokenReview API
3. Verify authentication success
4. Extract user identity from token claims

### Authorization Check

1. Create SubjectAccessReview for the virtual path
2. Check if user has `get` permission on `/ls-access`
3. Reject request if access is denied

### Special Cases

- **kube:admin user**: Uses cluster ID as user ID for consistent identification

## Request Example

```bash
# Get your Kubernetes token
TOKEN=$(kubectl create token my-service-account)

# Make authenticated request
curl http://localhost:8080/v1/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "Hello"}'
```

## Troubleshooting

### Common Issues

| Error | Cause | Solution |
|-------|-------|----------|
| 401 Unauthorized | Invalid or expired token | Refresh token or check service account |
| 403 Forbidden | Missing RBAC permissions | Add ClusterRoleBinding for user/SA |
| Connection refused | Wrong API server URL | Check `k8s_cluster_api` setting |
| Certificate error | TLS verification failed | Check `k8s_ca_cert_path` or use valid certs |

### Debugging

Check token validity:
```bash
kubectl auth can-i get /ls-access --as=system:serviceaccount:namespace:sa-name
```

Check service account permissions:
```bash
kubectl auth can-i --list --as=system:serviceaccount:namespace:sa-name
```
