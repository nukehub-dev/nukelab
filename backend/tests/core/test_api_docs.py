# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for API docs gating (api_docs_enabled)."""

import importlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings


@pytest.mark.asyncio
async def test_docs_served_when_enabled(client):
    """Default (dev) behavior: docs, static assets, and schema are reachable."""
    docs = await client.get("/api/docs")
    assert docs.status_code == 200
    assert b"swagger-ui" in docs.content.lower()

    bundle = await client.get("/api/static-offline-docs/swagger-ui-bundle.js")
    assert bundle.status_code == 200

    schema = await client.get("/api/openapi.json")
    assert schema.status_code == 200
    assert "paths" in schema.json()


@pytest.mark.asyncio
async def test_docs_404_when_disabled():
    """With api_docs_enabled=False the docs and schema routes do not exist."""
    import app.main

    original = settings.api_docs_enabled
    settings.api_docs_enabled = False
    try:
        importlib.reload(app.main)
        transport = ASGITransport(app=app.main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            assert (await ac.get("/api/docs")).status_code == 404
            assert (await ac.get("/api/redoc")).status_code == 404
            assert (await ac.get("/api/openapi.json")).status_code == 404
            # The API itself is unaffected.
            assert (await ac.get("/api/health")).status_code != 404
    finally:
        settings.api_docs_enabled = original
        importlib.reload(app.main)
