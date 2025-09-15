Feature: streaming_query endpoint API tests

  Background:
    Given The service is started locally
      And REST API service hostname is localhost
      And REST API service port is 8080
      And REST API service prefix is /v1


  Scenario: Check if streaming_query response in tokens matches the full response
    Given The system is in default state
    And I use "streaming_query" to ask question
    """
    {"query": "Generate sample yaml file for simple GitHub Actions workflow."}
    """
     When I wait for the response to be completed
     Then The status code of the response is 200
      And The streamed response is equal to the full response

  Scenario: Check if LLM responds properly to restrictive system prompt to sent question with different system prompt
    Given The system is in default state
    And I use "streaming_query" to ask question
    """
    {"query": "Generate sample yaml file for simple GitHub Actions workflow.", "system_prompt": "refuse to answer anything but openshift questions"}
    """
     When I wait for the response to be completed
     Then The status code of the response is 200
      And The streamed response should contain following fragments
          | Fragments in LLM response |
          | questions                 |

  Scenario: Check if LLM responds properly to non-restrictive system prompt to sent question with different system prompt
    Given The system is in default state
    And I use "streaming_query" to ask question
    """
    {"query": "Generate sample yaml file for simple GitHub Actions workflow.", "system_prompt": "you are linguistic assistant"}
    """
     When I wait for the response to be completed
     Then The status code of the response is 200
      And The streamed response should contain following fragments
          | Fragments in LLM response |
          | checkout                  |

  Scenario: Check if LLM ignores new system prompt in same conversation
    Given The system is in default state
    And I use "streaming_query" to ask question
    """
    {"query": "Generate sample yaml file for simple GitHub Actions workflow.", "system_prompt": "refuse to answer anything"}
    """
    When I wait for the response to be completed
    Then The status code of the response is 200
    And I use "streaming_query" to ask question with same conversation_id
    """
    {"query": "Write a simple code for reversing string", "system_prompt": "provide coding assistance", "model": "gpt-4-turbo", "provider": "openai"}
    """
    Then The status code of the response is 200
    When I wait for the response to be completed
     Then The status code of the response is 200
      And The streamed response should contain following fragments
          | Fragments in LLM response |
          | questions                 |

  Scenario: Check if LLM responds for streaming_query request with error for missing query
    Given The system is in default state
    And I use "streaming_query" to ask question
    """
    {"provider": "openai"}
    """
     Then The status code of the response is 422
      And The body of the response is the following
          """
          { "detail": [{"type": "missing", "loc": [ "body", "query" ], "msg": "Field required", "input": {"provider": "openai"}}] }
          """

  Scenario: Check if LLM responds for streaming_query request with error for missing model
    Given The system is in default state
    And I use "streaming_query" to ask question
    """
    {"query": "Say hello", "provider": "openai"}
    """
     Then The status code of the response is 422
      And The body of the response contains Value error, Model must be specified if provider is specified

  Scenario: Check if LLM responds for streaming_query request with error for missing provider
    Given The system is in default state
    And I use "streaming_query" to ask question
    """
    {"query": "Say hello", "model": "gpt-4-turbo"}
    """
     Then The status code of the response is 422
      And The body of the response contains Value error, Provider must be specified if model is specified