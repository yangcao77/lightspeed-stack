@Proxy
@skip-in-library-mode
Feature: Proxy and TLS networking tests for Llama Stack providers

  Verify that the Lightspeed Stack works correctly when Llama Stack's
  remote inference providers are configured with proxy and TLS settings
  via the run.yaml NetworkConfig.

  Background:
    Given The service is started locally
      And REST API service prefix is /v1

  @TunnelProxy
  Scenario: LLM traffic is routed through a configured tunnel proxy
    Given A tunnel proxy is running on port 8888
      And Llama Stack is configured to route inference through the tunnel proxy
      And The lightspeed stack is restarted with the proxy-configured Llama Stack
     When I send a query "What is 2+2?" to the LLM
     Then The LLM responds successfully
      And The tunnel proxy handled at least 1 CONNECT request to the LLM provider

  @InterceptionProxy
  Scenario: LLM traffic works through interception proxy with correct CA
    Given An interception proxy with trustme CA is running on port 8889
      And Llama Stack is configured to route inference through the interception proxy with CA cert
      And The lightspeed stack is restarted with the proxy-configured Llama Stack
     When I send a query "What is 2+2?" to the LLM
     Then The LLM responds successfully
      And The interception proxy intercepted at least 1 connection

  @TLSVersion
  Scenario: TLS version configuration is respected
    Given Llama Stack is configured with minimum TLS version "TLSv1.2"
      And The lightspeed stack is restarted with the TLS-configured Llama Stack
     When I send a query "What is 2+2?" to the LLM
     Then The LLM responds successfully
