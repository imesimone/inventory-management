"""
Tests for restocking API endpoints.
"""
from datetime import datetime, timedelta

import pytest

from mock_data import restocking_orders


@pytest.fixture(autouse=True)
def reset_restocking_orders():
    """Clear submitted restocking orders around every test."""
    # Clear in place: main.py holds a reference to this same list object,
    # so rebinding the name would leave the app's list untouched
    restocking_orders.clear()
    yield
    restocking_orders.clear()


def make_order(items, budget=100000):
    """Build a restocking order request body."""
    return {"items": items, "budget": budget}


class TestRestockingEndpoints:
    """Test suite for restocking-related endpoints."""

    def test_demand_forecasts_restocking_fields(self, client):
        """Test that demand forecasts include restocking cost and lead time."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0

        for forecast in data:
            assert isinstance(forecast["unit_cost"], (int, float))
            assert forecast["unit_cost"] > 0
            assert isinstance(forecast["supplier_name"], str)
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["lead_time_days"] > 0

    def test_create_restocking_order(self, client):
        """Test submitting a restocking order."""
        response = client.post(
            "/api/restocking-orders",
            json=make_order([{"sku": "WDG-001", "quantity": 100}]),
        )
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert order["id"] == "1"

    def test_restocking_order_structure(self, client):
        """Test that a submitted order has the full response structure."""
        response = client.post(
            "/api/restocking-orders",
            json=make_order([{"sku": "GSK-203", "quantity": 50}]),
        )
        order = response.json()

        for field in [
            "id", "order_number", "items", "total_value", "budget",
            "status", "submitted_date", "lead_time_days", "expected_delivery",
        ]:
            assert field in order

        assert len(order["items"]) == 1
        item = order["items"][0]
        for field in ["sku", "name", "quantity", "unit_cost", "supplier_name", "lead_time_days"]:
            assert field in item
        assert item["sku"] == "GSK-203"
        assert item["name"] == "High-Temperature Gasket"
        assert item["quantity"] == 50

    def test_restocking_order_total_calculation(self, client):
        """Test that the order total is quantity times server-side unit cost."""
        response = client.post(
            "/api/restocking-orders",
            json=make_order([
                {"sku": "WDG-001", "quantity": 100},
                {"sku": "GSK-203", "quantity": 200},
            ]),
        )
        order = response.json()

        calculated_total = sum(i["quantity"] * i["unit_cost"] for i in order["items"])
        assert abs(order["total_value"] - calculated_total) < 0.01
        # 100 x 12.50 + 200 x 6.75
        assert abs(order["total_value"] - 2600.0) < 0.01

    def test_restocking_order_ignores_client_unit_cost(self, client):
        """Test that a client-supplied price cannot change the order total."""
        response = client.post(
            "/api/restocking-orders",
            json=make_order([{"sku": "WDG-001", "quantity": 10, "unit_cost": 0.01}]),
        )
        assert response.status_code == 201

        order = response.json()
        assert abs(order["total_value"] - 125.0) < 0.01

    def test_restocking_order_lead_time_calculation(self, client):
        """Test that order lead time is the longest item lead time."""
        response = client.post(
            "/api/restocking-orders",
            json=make_order([
                {"sku": "WDG-001", "quantity": 10},  # 14 days
                {"sku": "GSK-203", "quantity": 10},  # 7 days
            ]),
        )
        order = response.json()
        assert order["lead_time_days"] == 14

        submitted = datetime.fromisoformat(order["submitted_date"])
        expected = datetime.fromisoformat(order["expected_delivery"])
        assert expected - submitted == timedelta(days=14)

    def test_create_restocking_order_empty_items(self, client):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restocking-orders", json=make_order([]))
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_restocking_order_zero_quantity(self, client):
        """Test that a quantity of zero is rejected."""
        response = client.post(
            "/api/restocking-orders",
            json=make_order([{"sku": "WDG-001", "quantity": 0}]),
        )
        assert response.status_code == 400
        assert "quantity" in response.json()["detail"].lower()

    def test_create_restocking_order_unknown_sku(self, client):
        """Test that a SKU outside the demand forecast is rejected."""
        response = client.post(
            "/api/restocking-orders",
            json=make_order([{"sku": "NOPE-999", "quantity": 5}]),
        )
        assert response.status_code == 400
        assert "NOPE-999" in response.json()["detail"]

    def test_create_restocking_order_over_budget(self, client):
        """Test that an order above the budget is rejected and not stored."""
        response = client.post(
            "/api/restocking-orders",
            json=make_order([{"sku": "MTR-304", "quantity": 35}], budget=1000),
        )
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()

        assert client.get("/api/restocking-orders").json() == []

    def test_create_restocking_order_missing_fields(self, client):
        """Test that a malformed request body returns a validation error."""
        response = client.post("/api/restocking-orders", json={"items": []})
        assert response.status_code == 422

    def test_get_restocking_orders_empty(self, client):
        """Test getting restocking orders when none are submitted."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_restocking_orders_newest_first(self, client):
        """Test that submitted orders are listed newest first."""
        first = client.post(
            "/api/restocking-orders",
            json=make_order([{"sku": "WDG-001", "quantity": 1}]),
        ).json()
        second = client.post(
            "/api/restocking-orders",
            json=make_order([{"sku": "GSK-203", "quantity": 1}]),
        ).json()

        response = client.get("/api/restocking-orders")
        assert response.status_code == 200

        data = response.json()
        assert [o["id"] for o in data] == [second["id"], first["id"]]
        assert first["order_number"] != second["order_number"]

    def test_restocking_orders_do_not_affect_orders(self, client):
        """Test that submitted restocking orders stay out of the main orders list."""
        before = client.get("/api/orders").json()
        client.post(
            "/api/restocking-orders",
            json=make_order([{"sku": "WDG-001", "quantity": 1}]),
        )
        after = client.get("/api/orders").json()

        assert len(after) == len(before)
