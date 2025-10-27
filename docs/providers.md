# Lightspeed Core Providers

Lightspeed Core Stack (LCS) builds on top of llama-stack and its provider system.  
Any llama-stack provider can be enabled in LCS with minimal effort by installing the required dependencies and updating llama-stack configuration in `run.yaml` file.  

This document catalogs all available llama-stack providers and indicates which ones are officially supported in the current LCS version. It also provides a step-by-step guide on how to enable any llama-stack provider in LCS.  


- [Inference Providers](#inference-providers)
- [Agent Providers](#agent-providers)
- [Evaluation Providers](#evaluation-providers)
- [DatasetIO Providers](#datasetio-providers)
- [Safety Providers](#safety-providers)
- [Scoring Providers](#scoring-providers)
- [Telemetry Providers](#telemetry-providers)
- [Post Training Providers](#post-training-providers)
- [VectorIO Providers](#vectorio-providers)
- [Tool Runtime Providers](#tool-runtime-providers)
- [Files Providers](#files-providers)
- [Batches Providers](#batches-providers)
- [How to Enable a Provider](#enabling-a-llama-stack-provider)

The tables below summarize each provider category, containing the following atributes:

- **Name** – Provider identifier in llama-stack  
- **Type** – `inline` (runs inside LCS) or `remote` (external service)  
- **Pip Dependencies** – Required Python packages  
- **Supported in LCS** – Current support status (`✅` / `❌`)  
 


## Inference Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| meta-reference | inline | `accelerate`, `fairscale`, `torch`, `torchvision`, `transformers`, `zmq`, `lm-format-enforcer`, `sentence-transformers`, `torchao==0.8.0`, `fbgemm-gpu-genai==1.1.2` | ❌ |
| sentence-transformers | inline | `torch torchvision torchao>=0.12.0 --extra-index-url https://download.pytorch.org/whl/cpu`, `sentence-transformers --no-deps` | ❌ |
| anthropic | remote | `litellm` | ❌ |
| azure | remote | — | ✅ |
| bedrock | remote | `boto3` | ❌ |
| cerebras | remote | `cerebras_cloud_sdk` | ❌ |
| databricks | remote | — | ❌ |
| fireworks | remote | `fireworks-ai<=0.17.16` | ❌ |
| gemini | remote | `litellm` | ❌ |
| groq | remote | `litellm` | ❌ |
| hf::endpoint | remote | `huggingface_hub`, `aiohttp` | ❌ |
| hf::serverless | remote | `huggingface_hub`, `aiohttp` | ❌ |
| llama-openai-compat | remote | `litellm` | ❌ |
| nvidia | remote | — | ❌ |
| ollama | remote | `ollama`, `aiohttp`, `h11>=0.16.0` | ❌ |
| openai | remote | `litellm` | ✅ |
| passthrough | remote | — | ❌ |
| runpod | remote | — | ❌ |
| sambanova | remote | `litellm` | ❌ |
| tgi | remote | `huggingface_hub`, `aiohttp` | ❌ |
| together | remote | `together` | ❌ |
| vertexai | remote | `google-auth` | ✅ |
| watsonx | remote | `litellm` | ✅ |

Red Hat providers:

| Name | Version Tested | Type | Pip Dependencies | Supported in LCS |
|---|---|---|---|:---:|
| RHOAI (vllm) | latest operator | remote | `openai` | ✅ |
| RHAIIS (vllm) | 3.2.3 (on RHEL 9.20250429.0.4) | remote | `openai` | ✅ |
| RHEL AI (vllm) | 1.5.2 | remote | `openai` | ✅ |

### Azure Provider - Entra ID Authentication Guide

Lightspeed Core supports secure authentication using Microsoft Entra ID (formerly Azure Active Directory) for the Azure Inference Provider. This allows you to connect to Azure OpenAI without using API keys, by authenticating through your organization's Azure identity.

#### Lightspeed Core Configuration Requirements

To enable Entra ID authentication, the `azure_entra_id` block must be included in your LCS configuration. The `tenant_id`, `client_id`, and `client_secret` attributes are required:

| Attribute | Required | Description |
|-----------|----------|-------------|
| `tenant_id` | Yes | Azure AD tenant ID |
| `client_id` | Yes | Application (client) ID |
| `client_secret` | Yes | Client secret value |
| `scope` | No | Token scope (default: `https://cognitiveservices.azure.com/.default`) |

Example of LCS config section:

```yaml
azure_entra_id:
  tenant_id: ${env.AZURE_TENANT_ID}
  client_id: ${env.AZURE_CLIENT_ID}
  client_secret: ${env.AZURE_CLIENT_SECRET}
  # scope: "https://cognitiveservices.azure.com/.default"  # optional, this is the default
```

#### Llama Stack Configuration Requirements

Because Lightspeed builds on top of Llama Stack, certain configuration fields are required to satisfy the base Llama Stack schema. The config block for the Azure inference provider **must** include `api_key`, `api_base`, and `api_version` — Llama Stack will fail to start if any of these are missing.

**Important:** The `api_key` field must be set to `${env.AZURE_API_KEY}` exactly as shown below. This is not optional — Lightspeed uses this specific environment variable name as a placeholder for injection of the Entra ID access token. Using a different variable name will break the authentication flow.

```yaml
inference:
  - provider_id: azure
    provider_type: remote::azure
    config:
      api_key: ${env.AZURE_API_KEY}    # Must be exactly this - placeholder for Entra ID token
      api_base: ${env.AZURE_API_BASE}
      api_version: 2025-01-01-preview
```

**How it works:** At startup, Lightspeed acquires an Entra ID access token and stores it in the `AZURE_API_KEY` environment variable. When Llama Stack initializes, it reads the config, substitutes `${env.AZURE_API_KEY}` with the token value, and uses it to authenticate with Azure OpenAI. Llama Stack also calls `models.list()` during initialization to validate provider connectivity, which is why the token must be available before client initialization.

#### Access Token Lifecycle and Management

**Library mode startup:**
1. Lightspeed reads your Entra ID configuration
2. Acquires an initial access token from Microsoft Entra ID
3. Stores the token in the `AZURE_API_KEY` environment variable
4. **Then** initializes the Llama Stack library client

This ordering is critical because Llama Stack calls `models.list()` during initialization to validate provider connectivity. If the token is not set before client initialization, Azure requests will fail with authentication errors.

**Service mode startup:**

When running Llama Stack as a separate service, Lightspeed runs a pre-startup script that:
1. Reads the Entra ID configuration
2. Acquires an initial access token
3. Writes the token to the `AZURE_API_KEY` environment variable
4. **Then** Llama Stack service starts

This initial token is used solely for the `models.list()` validation call during Llama Stack startup. After startup, Lightspeed manages token refresh independently and passes fresh tokens via request headers.

**During inference requests:**
1. Before each request, Lightspeed checks if the token has expired
2. If expired, a new token is automatically acquired and the environment variable is updated
3. For library mode: the Llama Stack client is reloaded to pick up the new token
4. For service mode: the token is passed via `X-LlamaStack-Provider-Data` request headers

**Token security:**
- Access tokens are wrapped in `SecretStr` to prevent accidental logging
- Tokens are stored only in the `AZURE_API_KEY` environment variable (single source of truth)
- Each Uvicorn worker maintains its own token lifecycle independently

**Token validity:**
- Access tokens are typically valid for 1 hour
- Lightspeed refreshes tokens proactively before expiration (with a safety margin)
- Token refresh happens automatically in the background without manual intervention

#### Local Deployment Examples

**Prerequisites:** Export the required Azure Entra ID environment variables in your terminal(s):

```bash
export TENANT_ID="your-tenant-id"
export CLIENT_ID="your-client-id"
export CLIENT_SECRET="your-client-secret"
```

**Library mode** (Llama Stack embedded in Lightspeed):

```bash
# From project root
make run CONFIG=examples/lightspeed-stack-azure-entraid-lib.yaml
```

**Service mode** (Llama Stack as separate service):

```bash
# Terminal 1: Start Llama Stack service with Azure Entra ID config
make run-llama-stack CONFIG=examples/lightspeed-stack-azure-entraid-service.yaml LLAMA_STACK_CONFIG=examples/azure-run.yaml

# Terminal 2: Start Lightspeed (after Llama Stack is ready)
make run CONFIG=examples/lightspeed-stack-azure-entraid-service.yaml
```

**Note:** The `make run-llama-stack` command accepts two variables:
- `CONFIG` - Lightspeed configuration file (default: `lightspeed-stack.yaml`)
- `LLAMA_STACK_CONFIG` - Llama Stack configuration file to enrich and run (default: `run.yaml`)

---

## Agent Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| meta-reference | inline | `matplotlib`, `pillow`, `pandas`, `scikit-learn`, `mcp>=1.8.1` `aiosqlite`, `psycopg2-binary`, `redis`, `pymongo` | ✅ |

---

## Evaluation Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| meta-reference | inline | `tree_sitter`, `pythainlp`, `langdetect`, `emoji`, `nltk` | ✅ |
| meta-reference | remote | `requests` | ❌ |

---

## Datasetio Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| localfs | inline | `pandas` | ✅ |
| huggingface | remote | `datasets>=4.0.0` | ✅ |
| nvidia | remote | `datasets>=4.0.0` | ❌ |

---

## Safety Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| code-scanner | inline | `codeshield` | ❌ |
| llama-guard | inline | — | ❌ |
| prompt-guard | inline | `transformers[accelerate]`, `torch --index-url https://download.pytorch.org/whl/cpu` | ❌ |
| bedrock | remote | `boto3` | ❌ |
| nvidia | remote | `requests` | ❌ |
| sambanova | remote | `litellm`, `requests` | ❌ |

---

## Scoring Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| basic | inline | `requests` | ✅ |
| llm-as-judge | inline | — | ✅ |
| braintrust | inline | `autoevals` | ✅ |

---

## Telemetry Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| meta-reference | inline | `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` | ✅ |

---
## Post Training Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| torchtune-cpu | inline | `numpy`, `torch torchtune>=0.5.0`, `torchao>=0.12.0 --extra-index-url https://download.pytorch.org/whl/cpu`| ❌ |
| torchtune-gpu | inline | `numpy`,`torch torchtune>=0.5.0`, `torchao>=0.12.0` | ❌ |
| huggingface-gpu | inline | `trl`, `transformers`, `peft`, `datasets>=4.0.0`, `torch` | ✅ |
| nvidia | remote | `requests`, `aiohttp` | ❌ |

---
## VectorIO Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| meta-reference | inline | `faiss-cpu` | ❌ |
| chromadb | inline | `chromadb` | ❌ |
| faiss | inline | `faiss-cpu` | ✅ |
| milvus | inline | `pymilvus>=2.4.10` | ❌ |
| qdrant | inline | `qdrant-client` | ❌ |
| sqlite-vec | inline | `sqlite-vec` | ❌ |
| chromadb | remote | `chromadb-client` | ❌ |
| milvus | remote | `pymilvus>=2.4.10` | ❌ |
| pgvector | remote | `psycopg2-binary` | ❌ |
| qdrant | remote | `qdrant-client` | ❌ |
| weaviate | remote | `weaviate-client` | ❌ |

---

## Tool Runtime Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| rag-runtime | inline | `chardet`,`pypdf`, `tqdm`, `numpy`, `scikit-learn`, `scipy`, `nltk`, `sentencepiece`, `transformers` | ✅ |
| bing-search | remote | `requests` | ❌ |
| brave-search | remote | `requests` | ❌ |
| model-context-protocol | remote | `mcp>=1.8.1` | ✅ |
| tavily-search | remote | `requests` | ❌ |
| wolfram-alpha | remote | `requests` | ❌ |

---

## Files Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| localfs | inline | `sqlalchemy[asyncio]`, `aiosqlite`, `asyncpg` | ❌ |
| s3 | remote | `sqlalchemy[asyncio]`, `aiosqlite`, `asyncpg`, `boto3` | ❌ |

---

## Batches Providers

| Name | Type | Pip Dependencies | Supported in LCS |
|---|---|---|:---:|
| reference | inline | `openai` | ❌ |

---

## Enabling a Llama Stack Provider

1. **Add provider dependencies** 

    Run the following command to find out required dependencies for the desired provider (or check the tables above):
    ```bash
    uv run llama stack list-providers
    ```
    Edit your `pyproject.toml` and add the required pip packages for the provider into `llslibdev` section:
   ```toml
   llslibdev = [
     "openai>=1.0.0",
     "pymilvus>=2.4.10",
     
     # add your dependencies here
   ]
   ```

1. **Update project dependencies**

    Run the following command to update project dependencies:
    ```bash
    uv sync --group llslibdev
    ```
1. **Update llama-stack configuration**
    
    Update the llama-stack configuration in `run.yaml` as follows:
    
    Check if the corresponding API of added provider is listed in `apis` section.
    ```yaml
    apis:
        - inference
        - agents
        - eval
        ...
        # add api here if not served
    ```
    Add the provider instance under the **corresponding**       providers section:
    ```yaml
    providers:
        inference:
            - provider_id: openai
            provider_type: remote::openai
            config:
                api_key: ${env.OPENAI_API_KEY}

        agents:
            ...

        eval:
            ...       
    ```
    **Note:** The `provider_type` attribute uses schema `<type>::<name>` and comes from the deffinition on upstream.
    The `provider_id` is your local label.

    Some of APIs are associated with a set of **Resources**. Here is the mapping of APIs to resources:

    - **Inference**, **Eval** and **Post Training** are associated with **Model** resources.
    - **Safety** is associated with **Shield** resources.
    - **Tool Runtime** is associated with **ToolGroup** resources.
    - **DatasetIO** is associated with **Dataset** resources.
    - **VectorIO** is associated with **VectorDB** resources.
    - **Scoring** is associated with **ScoringFunction** resources.
    - **Eval** is associated with **Benchmark** resources.

    Update corresponding resources of the added provider in dedicated section.
    ```yaml
    providers:
        ...

    models:
    - model_id: gpt-4-turbo  # local label
        provider_id: openai
        model_type: llm
        provider_model_id: gpt-4-turbo  # provider label
    
    shields:
        ...
    ```
    **Note** It is necessary for llama-stack to know which resources to use for a given provider. This means you need to explicitly register resources (including models) before you can use them with the associated APIs.

1. **Provide credentials / secrets**  
   Make sure any required API keys or tokens are available to the stack. For example, export environment variables or configure them in your secret manager:
   ```bash
   export OPENAI_API_KEY="sk_..."
    ```
    Llama Stack supports environment variable substitution in configuration values using the `${env.VARIABLE_NAME}` syntax. 

1. **Rerun your llama-stack service**

    If you are running llama-stack as a standalone service, restart it with:
    ```bash
    uv run llama stack run run.yaml
    ```
    If you are running it within Lightspeed Core, use:
    ```bash
    make run
    ```

1. **Verify the provider**

    Check the logs to ensure the provider initialized successfully.  
    Then make a simple API call to confirm it is active and responding as expected.  

---

For a deeper understanding, see the [official llama-stack providers documentation](https://llamastack.github.io/docs/providers).
