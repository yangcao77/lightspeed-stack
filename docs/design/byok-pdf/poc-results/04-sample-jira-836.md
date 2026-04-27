<!-- image -->

Spaces

/

<!-- image -->

/ Lightspeed Core

/

Add parent

LCORE-836

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

## Streaml i ne   l i ghtspeed-stack   conf i g

<!-- image -->

<!-- image -->

## Key   deta i ls

F i eld   Tab Pr i or i t i zat i on Release Test i ng SFDC Portfol i o   Solut i ons Bus i ness

Descr i pt i on

## Feature   Overv i ew

Currently, the Lightspeed stack requires operators to manage two separate configuration files:

- run.yaml : For the underlying Llama Stack (e.g., inference endpoints, tools, vector stores).
- lightspeed-stack.yaml : For Lightspeed Core settings (e.g., authentication, data collection, server settings).

This dual-file system increases complexity and the potential for misconfiguration. This feature proposes merging all required settings into the primary lightspeed-stack.yaml. Lightspeed Core will be responsible for managing the necessary Llama Stack configuration from this single, unified source of truth.

The goal is to simplify the deployment and management experience for all downstream Lightspeed teams by providing a single, coherent configuration file.

Welcome to Atlassian Cloud! To report issues, raise a support ticket here.

Create

<!-- image -->

<!-- image -->

To Do

<!-- image -->

Improve Feature

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

<!-- image -->

We should evaluate the option of having the possibility of overriding the llama-stack configuration even in this single-config file model, to support some edge cases where Lightspeed teams need to configure the underlying llama-stack directly.

## Acceptance   cr i ter i a

- All necessary configurations required for Lightspeed assistants to operate previously set in run.yaml can now be defined within the lightspeed-stack.yaml file.
- Lightspeed Core correctly parses the unified configuration and applies the appropriate settings to the underlying Llama Stack services at runtime.
- The need for downstream teams to manually create or modify a separate run.yaml is completely eliminated.
- The stack deploys and operates correctly using only the single lightspeed-stack.yaml file.
- All relevant documentation is updated to reflect the new, single-file configuration process.

## Env i ronment

Add text

Blocked   Reason None

Release   Note   Text

None

G i t   Pull   Request

Add text

Contr i but i ng   Groups

Add groups

Blocked

False

Ready

False

Need   Info   From

Add people

Release   Note   Type

Add   opt i on

S i ze

Add   opt i on

Release   Note   Status Add   opt i on

Sync   Fa i lure   Flag Add   labels

Or i g i nal   story   po i nts

Add   number

Bugz i lla   Bug

Add   URL

Start   date

<!-- image -->

<!-- image -->

## [LCORE-836] Streamline lightspeed-stack config - Red Hat Issue Tracker

<!-- image -->

Parent

Add   parent

- Automation

Rule executions

<!-- image -->

- Atlassian project

Link to sha

<!-- image -->

Created October 15, 2025 at 1:34 PM Updated 3 days ago

<!-- image -->