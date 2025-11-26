# Lightspeed Core Stack


---

# 📋 Configuration schema



## AccessRule


Rule defining what actions a role can perform.


| Field | Type | Description |
|-------|------|-------------|
| role | string |  |
| actions | array |  |


## Action


Available actions in the system.




## AuthenticationConfiguration


Authentication configuration.


| Field | Type | Description |
|-------|------|-------------|
| module | string |  |
| skip_tls_verification | boolean |  |
| k8s_cluster_api |  |  |
| k8s_ca_cert_path |  |  |
| jwk_config |  |  |
| rh_identity_config |  |  |


## AuthorizationConfiguration


Authorization configuration.


| Field | Type | Description |
|-------|------|-------------|
| access_rules | array |  |


## ByokRag


BYOK RAG configuration.


| Field | Type | Description |
|-------|------|-------------|
| rag_id | string |  |
| rag_type | string |  |
| embedding_model | string |  |
| embedding_dimension | integer |  |
| vector_db_id | string |  |
| db_path | string |  |


## CORSConfiguration


CORS configuration.

CORS or 'Cross-Origin Resource Sharing' refers to the situations when a
frontend running in a browser has JavaScript code that communicates with a
backend, and the backend is in a different 'origin' than the frontend.

Useful resources:

  - [CORS in FastAPI](https://fastapi.tiangolo.com/tutorial/cors/)
  - [Wikipedia article](https://en.wikipedia.org/wiki/Cross-origin_resource_sharing)
  - [What is CORS?](https://dev.to/akshay_chauhan/what-is-cors-explained-8f1)


| Field | Type | Description |
|-------|------|-------------|
| allow_origins | array | A list of origins allowed for cross-origin requests. An origin is the combination of protocol (http, https), domain (myapp.com, localhost, localhost.tiangolo.com), and port (80, 443, 8080). Use ['*'] to allow all origins. |
| allow_credentials | boolean | Indicate that cookies should be supported for cross-origin requests |
| allow_methods | array | A list of HTTP methods that should be allowed for cross-origin requests. You can use ['*'] to allow all standard methods. |
| allow_headers | array | A list of HTTP request headers that should be supported for cross-origin requests. You can use ['*'] to allow all headers. The Accept, Accept-Language, Content-Language and Content-Type headers are always allowed for simple CORS requests. |


## Configuration


Global service configuration.


| Field | Type | Description |
|-------|------|-------------|
| name | string |  |
| service |  |  |
| llama_stack |  |  |
| user_data_collection |  |  |
| database |  |  |
| mcp_servers | array |  |
| authentication |  |  |
| authorization |  |  |
| customization |  |  |
| inference |  |  |
| conversation_cache |  |  |
| byok_rag | array |  |
| quota_handlers |  |  |


## ConversationHistoryConfiguration


Conversation cache configuration.


| Field | Type | Description |
|-------|------|-------------|
| type |  |  |
| memory |  |  |
| sqlite |  |  |
| postgres |  |  |


## CustomProfile


Custom profile customization for prompts and validation.


| Field | Type | Description |
|-------|------|-------------|
| path | string |  |
| prompts | object |  |


## Customization


Service customization.


| Field | Type | Description |
|-------|------|-------------|
| profile_path |  |  |
| disable_query_system_prompt | boolean |  |
| system_prompt_path |  |  |
| system_prompt |  |  |
| custom_profile |  |  |


## DatabaseConfiguration


Database configuration.


| Field | Type | Description |
|-------|------|-------------|
| sqlite |  |  |
| postgres |  |  |


## InMemoryCacheConfig


In-memory cache configuration.


| Field | Type | Description |
|-------|------|-------------|
| max_entries | integer |  |


## InferenceConfiguration


Inference configuration.


| Field | Type | Description |
|-------|------|-------------|
| default_model |  |  |
| default_provider |  |  |


## JsonPathOperator


Supported operators for JSONPath evaluation.




## JwkConfiguration


JWK configuration.


| Field | Type | Description |
|-------|------|-------------|
| url | string |  |
| jwt_configuration |  |  |


## JwtConfiguration


JWT configuration.


| Field | Type | Description |
|-------|------|-------------|
| user_id_claim | string |  |
| username_claim | string |  |
| role_rules | array |  |


## JwtRoleRule


Rule for extracting roles from JWT claims.


| Field | Type | Description |
|-------|------|-------------|
| jsonpath | string |  |
| operator |  |  |
| negate | boolean |  |
| value |  |  |
| roles | array |  |


## LlamaStackConfiguration


Llama stack configuration.


| Field | Type | Description |
|-------|------|-------------|
| url |  |  |
| api_key |  |  |
| use_as_library_client |  |  |
| library_client_config_path |  |  |


## ModelContextProtocolServer


model context protocol server configuration.


| Field | Type | Description |
|-------|------|-------------|
| name | string |  |
| provider_id | string |  |
| url | string |  |


## PostgreSQLDatabaseConfiguration


PostgreSQL database configuration.

PostgreSQL database is used by Lightspeed Core Stack service for storing information about
conversation IDs. It can also be leveraged to store conversation history and information
about quota usage.

Useful resources:

- [Psycopg: connection classes](https://www.psycopg.org/psycopg3/docs/api/connections.html)
- [PostgreSQL connection strings](https://www.connectionstrings.com/postgresql/)
- [How to Use PostgreSQL in Python](https://www.freecodecamp.org/news/postgresql-in-python/)


| Field | Type | Description |
|-------|------|-------------|
| host | string | Database server host or socket directory |
| port | integer | Database server port |
| db | string | Database name to connect to |
| user | string | Database user name used to authenticate |
| password | string | Password used to authenticate |
| namespace |  | Database namespace |
| ssl_mode | string | SSL mode |
| gss_encmode | string | This option determines whether or with what priority a secure GSS TCP/IP connection will be negotiated with the server. |
| ca_cert_path |  | Path to CA certificate |


## QuotaHandlersConfiguration


Quota limiter configuration.


| Field | Type | Description |
|-------|------|-------------|
| sqlite |  |  |
| postgres |  |  |
| limiters | array |  |
| scheduler |  |  |
| enable_token_history | boolean |  |


## QuotaLimiterConfiguration


Configuration for one quota limiter.


| Field | Type | Description |
|-------|------|-------------|
| type | string |  |
| name | string |  |
| initial_quota | integer |  |
| quota_increase | integer |  |
| period | string |  |


## QuotaSchedulerConfiguration


Quota scheduler configuration.


| Field | Type | Description |
|-------|------|-------------|
| period | integer |  |


## RHIdentityConfiguration


Red Hat Identity authentication configuration.


| Field | Type | Description |
|-------|------|-------------|
| required_entitlements |  |  |


## SQLiteDatabaseConfiguration


SQLite database configuration.


| Field | Type | Description |
|-------|------|-------------|
| db_path | string | Path to file where SQLite database is stored |


## ServiceConfiguration


Service configuration.


| Field | Type | Description |
|-------|------|-------------|
| host | string |  |
| port | integer |  |
| auth_enabled | boolean |  |
| workers | integer |  |
| color_log | boolean |  |
| access_log | boolean |  |
| tls_config |  |  |
| cors |  |  |


## TLSConfiguration


TLS configuration.

Transport Layer Security (TLS) is a cryptographic protocol designed to
provide communications security over a computer network, such as the
Internet. The protocol is widely used in applications such as email,
instant messaging, and voice over IP, but its use in securing HTTPS remains
the most publicly visible.

Useful resources:

  - [FastAPI HTTPS Deployment](https://fastapi.tiangolo.com/deployment/https/)
  - [Transport Layer Security Overview](https://en.wikipedia.org/wiki/Transport_Layer_Security)
  - [What is TLS](https://www.ssltrust.eu/learning/ssl/transport-layer-security-tls)


| Field | Type | Description |
|-------|------|-------------|
| tls_certificate_path |  | SSL/TLS certificate file path for HTTPS support. |
| tls_key_path |  | SSL/TLS private key file path for HTTPS support. |
| tls_key_password |  | Path to file containing the password to decrypt the SSL/TLS private key. |


## UserDataCollection


User data collection configuration.


| Field | Type | Description |
|-------|------|-------------|
| feedback_enabled | boolean |  |
| feedback_storage |  |  |
| transcripts_enabled | boolean |  |
| transcripts_storage |  |  |
