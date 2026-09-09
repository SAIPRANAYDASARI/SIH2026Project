from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_schemes(client: AsyncClient) -> None:
    response = await client.get("/api/v1/certification/schemes")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 5
    codes = {s["code"] for s in body}
    assert "CRS" in codes


@pytest.mark.asyncio
async def test_wizard_first_step_asks_a_question(client: AsyncClient) -> None:
    response = await client.post("/api/v1/certification/wizard", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["done"] is False
    assert body["next_question"]["field"] == "product_description"


@pytest.mark.asyncio
async def test_wizard_returns_result_for_clear_product(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/certification/wizard",
        json={"product_description": "gold jewellery"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["done"] is True
    assert body["results"][0]["scheme"]["code"] == "HALLMARKING"
    assert "source_note" in body["results"][0]["scheme"] or body["disclaimer"]
