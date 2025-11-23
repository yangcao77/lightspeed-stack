# Lightspeed Core Stack

---

# 📋 Configuration options



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


| Field | Type | Description |
|-------|------|-------------|
| allow_origins | array |  |
| allow_credentials | boolean |  |
| allow_methods | array |  |
| allow_headers | array |  |


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


| Field | Type | Description |
|-------|------|-------------|
| host | string |  |
| port | integer |  |
| db | string |  |
| user | string |  |
| password | string |  |
| namespace |  |  |
| ssl_mode | string |  |
| gss_encmode | string |  |
| ca_cert_path |  |  |


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
| db_path | string |  |


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


| Field | Type | Description |
|-------|------|-------------|
| tls_certificate_path |  |  |
| tls_key_path |  |  |
| tls_key_password |  |  |


## UserDataCollection


User data collection configuration.


| Field | Type | Description |
|-------|------|-------------|
| feedback_enabled | boolean |  |
| feedback_storage |  |  |
| transcripts_enabled | boolean |  |
| transcripts_storage |  |  |
