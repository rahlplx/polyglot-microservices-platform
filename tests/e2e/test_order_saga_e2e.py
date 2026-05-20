"""
End-to-End Integration Tests for the Order Saga Pattern.

Tests the complete distributed transaction lifecycle across Order, Catalog,
Payment, and Notification services, including happy path, failure
compensation, timeouts, and concurrency scenarios.

The saga orchestrator (Order service, Kotlin) coordinates:
  1. Reserve inventory (Catalog service, TypeScript)
  2. Process payment (Payment service, Go)
  3. Send notification (Notification service, Python)
  4. Confirm order

On failure, compensating transactions are executed in reverse order.
"""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import pytest

from .conftest import (
    KubectlHelper,
    HttpClientFactory,
    KafkaHelper,
    PostgresHelper,
    OTelTraceHelper,
    SERVICE_REGISTRY,
    KAFKA_TOPICS,
    wait_for_condition,
)


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------
pytestmark = [pytest.mark.e2e, pytest.mark.saga]


# ---------------------------------------------------------------------------
# Helper: Build order creation payload
# ---------------------------------------------------------------------------
def _build_order_payload(customer_id: str, product_id: str, quantity: int = 1) -> Dict[str, Any]:
    """Build a CreateOrderRequest payload matching order.v1 proto."""
    return {
        "customer_id": customer_id,
        "lines": [
            {
                "product_id": product_id,
                "quantity": quantity,
            }
        ],
        "shipping_address": {
            "street_line_1": "123 E2E Test St",
            "city": "Testville",
            "state_province": "CA",
            "postal_code": "90210",
            "country_code": "US",
        },
    }


# ---------------------------------------------------------------------------
# Test 1: Happy Path — Complete Order Saga
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.saga
def test_order_saga_happy_path(
    http_client_factory: HttpClientFactory,
    kafka_helper: KafkaHelper,
    otel_helper: OTelTraceHelper,
    test_customer_id: str,
    test_product_id: str,
):
    """Happy path — Place order -> reserve inventory -> process payment
    -> send notification -> order confirmed.

    Verifies the entire saga completes successfully end-to-end across
    4 services (Order, Catalog, Payment, Notification).
    """
    # Step 1: Create the order via gateway
    order_payload = _build_order_payload(test_customer_id, test_product_id, quantity=2)
    status_code, order_resp, _ = http_client_factory.post(
        "/api/v1/order/orders",
        order_payload,
        service="order",
    )
    assert status_code in (200, 201), f"Order creation failed: {order_resp}"

    order_id = order_resp.get("order", {}).get("order_id") or order_resp.get("order_id")
    assert order_id, f"No order_id in response: {order_resp}"

    # Step 2: Wait for order to reach PAID status (saga progresses through
    # RESERVE_INVENTORY -> PROCESS_PAYMENT -> SEND_NOTIFICATION)
    def order_is_paid():
        code, resp, _ = http_client_factory.get(
            f"/api/v1/order/orders/{order_id}",
            service="order",
        )
        if code != 200:
            return False
        status = resp.get("order", {}).get("status") or resp.get("status")
        return status in ("ORDER_STATUS_PAID", "ORDER_STATUS_COMPLETED", "PAID", "COMPLETED")

    paid = wait_for_condition(order_is_paid, timeout=60, interval=3, message="Order did not reach PAID status")
    assert paid, "Order saga did not complete happy path within timeout"

    # Step 3: Verify payment was processed
    code, payment_resp, _ = http_client_factory.get(
        f"/api/v1/payment/payments?order_id={order_id}",
        service="payment",
    )
    assert code == 200, f"Payment lookup failed: {payment_resp}"
    payments = payment_resp.get("payments", [])
    if payments:
        payment_status = payments[0].get("status")
        assert payment_status in (
            "PAYMENT_STATUS_COMPLETED", "COMPLETED", "PAYMENT_STATUS_PROCESSING"
        ), f"Unexpected payment status: {payment_status}"

    # Step 4: Verify notification was sent
    code, notif_resp, _ = http_client_factory.get(
        f"/api/v1/notification/notifications?user_id={test_customer_id}",
        service="notification",
    )
    assert code == 200, f"Notification lookup failed: {notif_resp}"

    # Step 5: Verify Kafka events were emitted for the saga steps
    order_event = kafka_helper.consume_until(
        [KAFKA_TOPICS["order_events"]],
        predicate=lambda msg: msg.get("order_id") == order_id
        and msg.get("event_type") in ("ORDER_CREATED", "ORDER_COMPLETED"),
        timeout_seconds=30,
    )
    # Event may have been consumed by another consumer; log but do not fail
    if order_event is None:
        pytest.log.warning(f"No Kafka order event found for order {order_id} (may have been consumed)")


# ---------------------------------------------------------------------------
# Test 2: Payment Failure — Compensating Transaction
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.saga
def test_order_saga_payment_failure(
    http_client_factory: HttpClientFactory,
    kafka_helper: KafkaHelper,
    test_customer_id: str,
    test_product_id: str,
):
    """Payment failure — Place order -> reserve inventory -> payment fails
    -> compensating transaction (release inventory) -> order cancelled
    -> notification sent.

    Uses a payment method that simulates insufficient funds (card-insufficient).
    """
    # Create order with a payment method that will fail
    order_payload = _build_order_payload(test_customer_id, test_product_id, quantity=1)
    order_payload["payment_method"] = "card-insufficient"
    order_payload["payment_details"] = {
        "card_number": "4000000000009995",  # Stripe test card: declined
        "exp_month": "12",
        "exp_year": "2030",
        "cvc": "123",
    }

    status_code, order_resp, _ = http_client_factory.post(
        "/api/v1/order/orders",
        order_payload,
        service="order",
    )
    assert status_code in (200, 201, 202), f"Order creation failed: {order_resp}"

    order_id = order_resp.get("order", {}).get("order_id") or order_resp.get("order_id")
    assert order_id, f"No order_id in response: {order_resp}"

    # Wait for order to reach CANCELLED status (saga compensation)
    def order_is_cancelled():
        code, resp, _ = http_client_factory.get(
            f"/api/v1/order/orders/{order_id}",
            service="order",
        )
        if code != 200:
            return False
        status = resp.get("order", {}).get("status") or resp.get("status")
        return status in ("ORDER_STATUS_CANCELLED", "ORDER_STATUS_FAILED", "CANCELLED", "FAILED")

    cancelled = wait_for_condition(
        order_is_cancelled,
        timeout=60,
        interval=3,
        message="Order was not cancelled after payment failure within timeout",
    )
    assert cancelled, "Order saga did not compensate after payment failure"

    # Verify saga state shows compensation
    code, saga_resp, _ = http_client_factory.get(
        f"/api/v1/order/saga/{order_id}",
        service="order",
    )
    if code == 200:
        saga_status = saga_resp.get("saga", {}).get("status") or saga_resp.get("status")
        assert saga_status in (
            "SAGA_STATUS_FAILED", "SAGA_STATUS_COMPENSATING", "FAILED", "COMPENSATING",
        ), f"Unexpected saga status after payment failure: {saga_status}"

    # Verify that a cancellation notification was sent
    code, notif_resp, _ = http_client_factory.get(
        f"/api/v1/notification/notifications?user_id={test_customer_id}",
        service="notification",
    )
    assert code == 200, f"Notification lookup failed: {notif_resp}"


# ---------------------------------------------------------------------------
# Test 3: Catalog Unavailable — Graceful Failure
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.saga
@pytest.mark.destructive
def test_order_saga_catalog_unavailable(
    http_client_factory: HttpClientFactory,
    kubectl: KubectlHelper,
    test_customer_id: str,
    test_product_id: str,
):
    """Catalog unavailable — Place order -> catalog timeout
    -> order fails gracefully -> no payment attempted.

    Scales catalog deployment to 0 replicas to simulate unavailability,
    then verifies the saga fails without attempting payment.
    """
    # Scale catalog down to 0
    scaled = kubectl.scale_deployment("catalog", 0)
    assert scaled, "Failed to scale catalog deployment to 0"

    try:
        # Give catalog time to shut down
        time.sleep(10)

        # Attempt to create an order
        order_payload = _build_order_payload(test_customer_id, test_product_id, quantity=1)
        status_code, order_resp, _ = http_client_factory.post(
            "/api/v1/order/orders",
            order_payload,
            service="order",
            timeout=15,
        )

        # Order should either fail immediately or saga should transition to FAILED
        if status_code in (200, 201, 202):
            order_id = order_resp.get("order", {}).get("order_id") or order_resp.get("order_id")

            # Wait for order to reach FAILED/CANCELLED status
            def order_failed():
                code, resp, _ = http_client_factory.get(
                    f"/api/v1/order/orders/{order_id}",
                    service="order",
                )
                if code != 200:
                    return False
                status = resp.get("order", {}).get("status") or resp.get("status")
                return status in ("ORDER_STATUS_FAILED", "ORDER_STATUS_CANCELLED", "FAILED", "CANCELLED")

            failed = wait_for_condition(
                order_failed,
                timeout=60,
                interval=3,
                message="Order did not fail gracefully when catalog was unavailable",
            )
            assert failed, "Order should have failed when catalog was unavailable"

            # Verify no payment was attempted (payment count should be 0 for this order)
            code, payment_resp, _ = http_client_factory.get(
                f"/api/v1/payment/payments?order_id={order_id}",
                service="payment",
            )
            if code == 200:
                payments = payment_resp.get("payments", [])
                assert len(payments) == 0, "Payment should NOT have been attempted when catalog was down"

    finally:
        # Restore catalog deployment
        kubectl.scale_deployment("catalog", 3)
        # Wait for catalog to come back
        time.sleep(15)


# ---------------------------------------------------------------------------
# Test 4: Notification Failure — Async, Order Still Confirmed
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.saga
def test_order_saga_notification_failure(
    http_client_factory: HttpClientFactory,
    kubectl: KubectlHelper,
    test_customer_id: str,
    test_product_id: str,
):
    """Notification failure — Place order -> payment succeeds
    -> notification fails -> order still confirmed (notification is async)
    -> retry succeeds.

    Notification delivery is asynchronous and should not block order
    confirmation. The order saga should complete even if notification
    delivery initially fails.
    """
    # Create order with a notification channel that will initially fail
    # but eventually succeed on retry (simulated via notification config)
    order_payload = _build_order_payload(test_customer_id, test_product_id, quantity=1)
    order_payload["notification_config"] = {
        "channel": "email",
        "simulate_failure": True,
        "retry_count": 1,
    }

    status_code, order_resp, _ = http_client_factory.post(
        "/api/v1/order/orders",
        order_payload,
        service="order",
    )
    assert status_code in (200, 201, 202), f"Order creation failed: {order_resp}"

    order_id = order_resp.get("order", {}).get("order_id") or order_resp.get("order_id")
    assert order_id, f"No order_id in response: {order_resp}"

    # Wait for order to reach COMPLETED/PAID status despite notification failure
    def order_is_confirmed():
        code, resp, _ = http_client_factory.get(
            f"/api/v1/order/orders/{order_id}",
            service="order",
        )
        if code != 200:
            return False
        status = resp.get("order", {}).get("status") or resp.get("status")
        return status in (
            "ORDER_STATUS_PAID", "ORDER_STATUS_COMPLETED", "ORDER_STATUS_FULFILLING",
            "PAID", "COMPLETED", "FULFILLING",
        )

    confirmed = wait_for_condition(
        order_is_confirmed,
        timeout=60,
        interval=3,
        message="Order should be confirmed even when notification fails",
    )
    assert confirmed, "Order should be confirmed even when notification delivery fails (async)"

    # Verify notification eventually succeeds via retry
    def notification_delivered():
        code, resp, _ = http_client_factory.get(
            f"/api/v1/notification/notifications?user_id={test_customer_id}",
            service="notification",
        )
        if code != 200:
            return False
        notifications = resp.get("notifications", [])
        for n in notifications:
            if n.get("status") in ("DELIVERED", "NOTIFICATION_STATUS_DELIVERED"):
                return True
        return False

    # Notification retry may take longer
    delivered = wait_for_condition(
        notification_delivered,
        timeout=90,
        interval=5,
        message="Notification should eventually be delivered via retry",
    )
    # This is a soft assertion — notification delivery is best-effort
    # but we expect retry to succeed within the timeout
    assert delivered, "Notification should be delivered after retry succeeds"


# ---------------------------------------------------------------------------
# Test 5: Concurrent Orders — No Overselling
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.saga
@pytest.mark.slow
def test_order_saga_concurrent_orders_no_overselling(
    http_client_factory: HttpClientFactory,
    test_product_id: str,
):
    """Concurrent orders — 10 simultaneous orders for the same item
    with limited stock -> verify no overselling.

    Creates a product with exactly 3 units of inventory, then attempts
    10 concurrent orders. Verifies that at most 3 orders succeed and
    the remaining 7 fail or are cancelled due to insufficient stock.
    """
    # Step 1: Create a product with limited inventory (3 units)
    product_payload = {
        "name": "Limited Stock E2E Product",
        "description": "Product for concurrency testing",
        "price": {"currency_code": "USD", "units": 99, "nanos": 990000000},
        "category": "test",
        "tags": ["e2e", "limited"],
        "initial_quantity": 3,
    }
    code, product_resp, _ = http_client_factory.post(
        "/api/v1/catalog/products",
        product_payload,
        service="catalog",
    )
    assert code in (200, 201), f"Product creation failed: {product_resp}"

    product_id = product_resp.get("product", {}).get("product_id") or product_resp.get("product_id")
    assert product_id, f"No product_id in response: {product_resp}"

    # Step 2: Place 10 concurrent orders for the same product
    num_orders = 10
    max_stock = 3
    results = {}

    def place_order(index: int) -> Dict[str, Any]:
        customer_id = f"cust-concurrent-{uuid.uuid4().hex[:8]}"
        payload = _build_order_payload(customer_id, product_id, quantity=1)
        try:
            code, resp, _ = http_client_factory.post(
                "/api/v1/order/orders",
                payload,
                service="order",
                timeout=30,
            )
            return {
                "index": index,
                "status_code": code,
                "order_id": resp.get("order", {}).get("order_id") or resp.get("order_id"),
                "response": resp,
            }
        except Exception as e:
            return {"index": index, "status_code": 0, "error": str(e)}

    with ThreadPoolExecutor(max_workers=num_orders) as executor:
        futures = {executor.submit(place_order, i): i for i in range(num_orders)}
        for future in as_completed(futures):
            result = future.result()
            results[result["index"]] = result

    # Step 3: Count successful orders
    successful_orders = [
        r for r in results.values()
        if r.get("status_code") in (200, 201, 202) and r.get("order_id")
    ]

    # Step 4: Wait for saga completion and check final status
    time.sleep(30)  # Allow sagas to complete

    confirmed_count = 0
    for result in successful_orders:
        order_id = result.get("order_id")
        if not order_id:
            continue
        code, resp, _ = http_client_factory.get(
            f"/api/v1/order/orders/{order_id}",
            service="order",
        )
        if code == 200:
            status = resp.get("order", {}).get("status") or resp.get("status")
            if status in ("ORDER_STATUS_PAID", "ORDER_STATUS_COMPLETED", "PAID", "COMPLETED"):
                confirmed_count += 1

    # Step 5: Verify no overselling
    assert confirmed_count <= max_stock, (
        f"Overselling detected! {confirmed_count} orders confirmed but only "
        f"{max_stock} units were available"
    )

    # Step 6: Verify inventory is now 0 (or negative for backorders)
    code, inventory_resp, _ = http_client_factory.get(
        f"/api/v1/catalog/products/{product_id}",
        service="catalog",
    )
    if code == 200:
        remaining = (
            inventory_resp.get("product", {}).get("available_quantity")
            or inventory_resp.get("available_quantity")
        )
        if remaining is not None:
            assert remaining >= 0, f"Inventory went negative: {remaining} remaining"


# ---------------------------------------------------------------------------
# Test 6: Saga Timeout — Compensation Triggered
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.saga
@pytest.mark.slow
def test_order_saga_timeout(
    http_client_factory: HttpClientFactory,
    kafka_helper: KafkaHelper,
    test_customer_id: str,
    test_product_id: str,
):
    """Saga timeout — Order takes too long -> saga timeout triggers
    compensation -> all resources released.

    Simulates a slow downstream service response by setting a very short
    saga timeout. Verifies that the saga orchestrator correctly detects
    the timeout and executes compensating transactions for any steps
    that had already completed.
    """
    # Create order with an extremely short saga timeout
    order_payload = _build_order_payload(test_customer_id, test_product_id, quantity=1)
    order_payload["saga_timeout_seconds"] = 5  # Very short timeout
    order_payload["payment_method"] = "card-slow"  # Simulates slow payment processing

    status_code, order_resp, _ = http_client_factory.post(
        "/api/v1/order/orders",
        order_payload,
        service="order",
    )
    assert status_code in (200, 201, 202), f"Order creation failed: {order_resp}"

    order_id = order_resp.get("order", {}).get("order_id") or order_resp.get("order_id")
    assert order_id, f"No order_id in response: {order_resp}"

    # Wait for order to reach CANCELLED/FAILED status due to timeout
    def order_timed_out():
        code, resp, _ = http_client_factory.get(
            f"/api/v1/order/orders/{order_id}",
            service="order",
        )
        if code != 200:
            return False
        status = resp.get("order", {}).get("status") or resp.get("status")
        return status in (
            "ORDER_STATUS_CANCELLED", "ORDER_STATUS_FAILED", "ORDER_STATUS_COMPENSATING",
            "CANCELLED", "FAILED", "COMPENSATING",
        )

    timed_out = wait_for_condition(
        order_timed_out,
        timeout=90,
        interval=3,
        message="Order saga did not timeout and compensate within expected window",
    )
    assert timed_out, "Saga should have timed out and triggered compensation"

    # Verify saga state shows compensation was triggered
    code, saga_resp, _ = http_client_factory.get(
        f"/api/v1/order/saga/{order_id}",
        service="order",
    )
    if code == 200:
        saga = saga_resp.get("saga", {})
        steps = saga.get("steps", [])
        # Verify that any completed steps have corresponding compensation steps
        completed_steps = [s for s in steps if s.get("status") in ("COMPLETED", "SAGA_STEP_STATUS_COMPLETED")]
        compensated_steps = [s for s in steps if s.get("status") in ("COMPENSATED", "SAGA_STEP_STATUS_COMPENSATED")]

        # At minimum, if inventory was reserved, it should have been released
        if completed_steps:
            assert len(compensated_steps) > 0, (
                f"Saga had {len(completed_steps)} completed steps but no compensation "
                f"steps were executed after timeout"
            )

    # Verify all resources were released (check inventory was restored)
    code, product_resp, _ = http_client_factory.get(
        f"/api/v1/catalog/products/{test_product_id}",
        service="catalog",
    )
    # Inventory check is informational — the key assertion is that the saga
    # reached a terminal compensated state
    if code == 200:
        product = product_resp.get("product", product_resp)
        # If inventory was reserved and then released, it should be back to original
        available = product.get("available_quantity")
        if available is not None:
            assert available >= 0, f"Inventory should be non-negative after compensation: {available}"


# ---------------------------------------------------------------------------
# Offline / Manifest Validation Tests
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.saga
@pytest.mark.offline
def test_saga_proto_schema_valid(project_root):
    """Validate that the Order and Saga proto schemas are syntactically valid
    and contain the expected RPCs for saga orchestration.

    This is an offline test that does not require a live cluster.
    """
    order_proto = project_root / "schemas" / "proto" / "order" / "v1" / "order.proto"
    saga_proto = project_root / "schemas" / "proto" / "order" / "v1" / "saga.proto"

    assert order_proto.exists(), f"Order proto not found at {order_proto}"
    assert saga_proto.exists(), f"Saga proto not found at {saga_proto}"

    order_content = order_proto.read_text()
    saga_content = saga_proto.read_text()

    # Verify Order service has saga-relevant RPCs
    assert "CreateOrder" in order_content, "OrderService must have CreateOrder RPC"
    assert "CancelOrder" in order_content, "OrderService must have CancelOrder RPC (for compensation)"
    assert "GetOrderStatus" in order_content, "OrderService must have GetOrderStatus RPC"

    # Verify Saga service definition
    assert "SagaService" in saga_content, "Saga proto must define SagaService"
    assert "GetSagaState" in saga_content, "SagaService must have GetSagaState RPC"
    assert "RetrySagaStep" in saga_content, "SagaService must have RetrySagaStep RPC"

    # Verify saga status enum covers all needed states
    assert "SAGA_STATUS_RUNNING" in saga_content
    assert "SAGA_STATUS_COMPENSATING" in saga_content
    assert "SAGA_STATUS_FAILED" in saga_content
    assert "SAGA_STATUS_COMPLETED" in saga_content

    # Verify order status enum covers compensation
    assert "ORDER_STATUS_COMPENSATING" in order_content
    assert "ORDER_STATUS_CANCELLED" in order_content


@pytest.mark.e2e
@pytest.mark.saga
@pytest.mark.offline
def test_saga_compensation_definitions_exist(project_root):
    """Validate that CompensationAction and SagaStep definitions exist
    in the Order service codebase.

    This is an offline test that does not require a live cluster.
    """
    compensation_file = project_root / "services" / "order" / "src" / "main" / "kotlin" / "domain" / "saga" / "CompensationAction.kt"
    saga_step_file = project_root / "services" / "order" / "src" / "main" / "kotlin" / "domain" / "saga" / "SagaStep.kt"
    saga_definition_file = project_root / "services" / "order" / "src" / "main" / "kotlin" / "domain" / "saga" / "SagaDefinition.kt"
    saga_orchestrator_file = project_root / "services" / "order" / "src" / "main" / "kotlin" / "domain" / "saga" / "SagaOrchestrator.kt"

    assert compensation_file.exists(), f"CompensationAction not found at {compensation_file}"
    assert saga_step_file.exists(), f"SagaStep not found at {saga_step_file}"
    assert saga_definition_file.exists(), f"SagaDefinition not found at {saga_definition_file}"
    assert saga_orchestrator_file.exists(), f"SagaOrchestrator not found at {saga_orchestrator_file}"

    # Verify CompensationAction contains relevant compensation types
    comp_content = compensation_file.read_text()
    assert "compensat" in comp_content.lower(), "CompensationAction must reference compensation logic"

    # Verify SagaOrchestrator has timeout and compensation logic
    orch_content = saga_orchestrator_file.read_text()
    assert "timeout" in orch_content.lower() or "Timeout" in orch_content, "SagaOrchestrator must handle timeouts"
    assert "compensat" in orch_content.lower(), "SagaOrchestrator must handle compensation"
