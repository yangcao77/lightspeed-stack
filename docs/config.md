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
| k8s_cluster_api | string |  |
| k8s_ca_cert_path | string |  |
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
| name | string | Name of the service. That value will be used in REST API endpoints. |
| service |  | This section contains Lightspeed Core Stack service configuration. |
| llama_stack |  | This section contains Llama Stack configuration. Lightspeed Core Stack service can call Llama Stack in library mode or in server mode. |
| user_data_collection |  | This section contains configuration for subsystem that collects user data(transcription history and feedbacks). |
| database |  | Configuration for database to store conversation IDs and other runtime data |
| mcp_servers | array | MCP (Model Context Protocol) servers provide tools and capabilities to the AI agents. These are configured in this section. Only MCP servers defined in the lightspeed-stack.yaml configuration are available to the agents. Tools configured in the llama-stack run.yaml are not accessible to lightspeed-core agents. |
| authentication |  | Authentication configuration |
| authorization |  | Lightspeed Core Stack implements a modular authentication and authorization system with multiple authentication methods. Authorization is configurable through role-based access control. Authentication is handled through selectable modules configured via the module field in the authentication configuration. |
| customization |  | It is possible to customize Lightspeed Core Stack via this section. System prompt can be customized and also different parts of the service can be replaced by custom Python modules. |
| inference |  | One LLM provider and one its model might be selected as default ones. When no provider+model pair is specified in REST API calls (query endpoints), the default provider and model are used. |
| conversation_cache |  |  |
| byok_rag | array | BYOK RAG configuration. This configuration can be used to reconfigure Llama Stack through its run.yaml configuration file |
| quota_handlers |  | Quota handlers configuration |


## ConversationHistoryConfiguration


Conversation history configuration.


| Field | Type | Description |
|-------|------|-------------|
| type | string |  |
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
| profile_path | string |  |
| disable_query_system_prompt | boolean |  |
| system_prompt_path | string |  |
| system_prompt | string |  |
| custom_profile |  |  |


## DatabaseConfiguration


Database configuration.


| Field | Type | Description |
|-------|------|-------------|
| sqlite |  | SQLite database configuration |
| postgres |  | PostgreSQL database configuration |


## InMemoryCacheConfig


In-memory cache configuration.


| Field | Type | Description |
|-------|------|-------------|
| max_entries | integer | Maximum number of entries stored in the in-memory cache |


## InferenceConfiguration


Inference configuration.


| Field | Type | Description |
|-------|------|-------------|
| default_model | string |  |
| default_provider | string |  |


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
| jsonpath | string | JSONPath expression to evaluate against the JWT payload |
| operator |  | JSON path comparison operator |
| negate | boolean | If set to true, the meaning of the rule is negated |
| value |  | Value to compare against |
| roles | array | Roles to be assigned if the rule matches |


## LlamaStackConfiguration


Llama stack configuration.

Llama Stack is a comprehensive system that provides a uniform set of tools
for building, scaling, and deploying generative AI applications, enabling
developers to create, integrate, and orchestrate multiple AI services and
capabilities into an adaptable setup.

Useful resources:

  - [Llama Stack](https://www.llama.com/products/llama-stack/)
  - [Python Llama Stack client](https://github.com/llamastack/llama-stack-client-python)
  - [Build AI Applications with Llama Stack](https://llamastack.github.io/)


| Field | Type | Description |
|-------|------|-------------|
| url | string | URL to Llama Stack service; used when library mode is disabled |
| api_key | string | API key to access Llama Stack service |
| use_as_library_client | boolean | When set to true Llama Stack will be used in library mode, not in server mode (default) |
| library_client_config_path | string | Path to configuration file used when Llama Stack is run in library mode |


## ModelContextProtocolServer


Model context protocol server configuration.

MCP (Model Context Protocol) servers provide tools and
capabilities to the AI agents. These are configured by this structure.
Only MCP servers defined in the lightspeed-stack.yaml configuration are
available to the agents. Tools configured in the llama-stack run.yaml
are not accessible to lightspeed-core agents.

Useful resources:

- [Model Context Protocol](https://modelcontextprotocol.io/docs/getting-started/intro)
- [MCP FAQs](https://modelcontextprotocol.io/faqs)
- [Wikipedia article](https://en.wikipedia.org/wiki/Model_Context_Protocol)


| Field | Type | Description |
|-------|------|-------------|
| name | string | MCP server name that must be unique |
| provider_id | string | MCP provider identification |
| url | string | URL of the MCP server |


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
| namespace | string | Database namespace |
| ssl_mode | string | SSL mode |
| gss_encmode | string | This option determines whether or with what priority a secure GSS TCP/IP connection will be negotiated with the server. |
| ca_cert_path | string | Path to CA certificate |


## QuotaHandlersConfiguration


Quota limiter configuration.

It is possible to limit quota usage per user or per service or services
(that typically run in one cluster). Each limit is configured as a separate
_quota limiter_. It can be of type `user_limiter` or `cluster_limiter`
(which is name that makes sense in OpenShift deployment).


| Field | Type | Description |
|-------|------|-------------|
| sqlite |  | SQLite database configuration |
| postgres |  | PostgreSQL database configuration |
| limiters | array | Quota limiters configuration |
| scheduler |  | Quota scheduler configuration |
| enable_token_history | boolean | Enables storing information about token usage history |


## QuotaLimiterConfiguration


Configuration for one quota limiter.

There are three configuration options for each limiter:

1. ``period`` is specified in a human-readable form, see
   https://www.postgresql.org/docs/current/datatype-datetime.html#DATATYPE-INTERVAL-INPUT
   for all possible options. When the end of the period is reached, the
   quota is reset or increased.
2. ``initial_quota`` is the value set at the beginning of the period.
3. ``quota_increase`` is the value (if specified) used to increase the
   quota when the period is reached.

There are two basic use cases:

1. When the quota needs to be reset to a specific value periodically (for
   example on a weekly or monthly basis), set ``initial_quota`` to the
   required value.
2. When the quota needs to be increased by a specific value periodically
   (for example on a daily basis), set ``quota_increase``.


| Field | Type | Description |
|-------|------|-------------|
| type | string | Quota limiter type, either user_limiter or cluster_limiter |
| name | string | Human readable quota limiter name |
| initial_quota | integer | Quota set at beginning of the period |
| quota_increase | integer | Delta value used to increase quota when period is reached |
| period | string | Period specified in human readable form |


## QuotaSchedulerConfiguration


Quota scheduler configuration.


| Field | Type | Description |
|-------|------|-------------|
| period | integer | Quota scheduler period specified in seconds |


## RHIdentityConfiguration


Red Hat Identity authentication configuration.


| Field | Type | Description |
|-------|------|-------------|
| required_entitlements | array |  |


## SQLiteDatabaseConfiguration


SQLite database configuration.


| Field | Type | Description |
|-------|------|-------------|
| db_path | string | Path to file where SQLite database is stored |


## ServiceConfiguration


Service configuration.

Lightspeed Core Stack is a REST API service that accepts requests
on a specified hostname and port. It is also possible to enable
authentication and specify the number of Uvicorn workers. When more
workers are specified, the service can handle requests concurrently.


| Field | Type | Description |
|-------|------|-------------|
| host | string | Service hostname |
| port | integer | Service port |
| auth_enabled | boolean | Enables the authentication subsystem |
| workers | integer | Number of Uvicorn worker processes to start |
| color_log | boolean | Enables colorized logging |
| access_log | boolean | Enables logging of all access information |
| tls_config |  | Transport Layer Security configuration for HTTPS support |
| cors |  | Cross-Origin Resource Sharing configuration for cross-domain requests |


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
| tls_certificate_path | string | SSL/TLS certificate file path for HTTPS support. |
| tls_key_path | string | SSL/TLS private key file path for HTTPS support. |
| tls_key_password | string | Path to file containing the password to decrypt the SSL/TLS private key. |


## UserDataCollection


User data collection configuration.


| Field | Type | Description |
|-------|------|-------------|
| feedback_enabled | boolean |  |
| feedback_storage | string |  |
| transcripts_enabled | boolean |  |
| transcripts_storage | string |  |
