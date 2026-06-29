# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Context variables for request-scoped state propagation.

These contextvars allow values like correlation_id to flow through:
  HTTP request → middleware → route handler → DB layer → Celery task

Note: Celery tasks run in separate threads. Use worker.py's ContextTask
base class to propagate correlation IDs across thread boundaries.
"""

import contextvars

# Correlation ID for tracing a single request through all layers
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")
