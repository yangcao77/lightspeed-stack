"""Observability module for telemetry and event collection.

This module provides functionality for sending telemetry events to external
systems like Splunk HEC for monitoring and analytics.
"""

from observability.splunk import send_splunk_event
from observability.telemetry import build_inference_event

__all__ = ["send_splunk_event", "build_inference_event"]
