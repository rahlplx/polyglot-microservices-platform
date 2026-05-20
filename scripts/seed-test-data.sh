#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Test Data Seed Script — Polyglot Microservices Platform
# ---------------------------------------------------------------------------
# Seeds the E2E test environment with test data:
#   - Test products in catalog (10 items with various prices)
#   - Test payment methods (valid card, expired card, insufficient funds card)
#   - Test users with different roles
#   - Kafka topics with test events
#   - Test database state in PostgreSQL
#
# Usage:
#   ./scripts/seed-test-data.sh [--namespace NS] [--cluster NAME] [--verbose]
#
# Options:
#   --namespace NS   Target Kubernetes namespace [default: production]
#   --cluster NAME   Kind cluster name [default: polyglot-e2e]
#   --verbose        Enable verbose output
#   -h, --help       Show this help message
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Defaults ---
NAMESPACE="production"
CLUSTER_NAME="polyglot-e2e"
VERBOSE=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GATEWAY_URL="http://localhost:8080"

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --cluster)   CLUSTER_NAME="$2"; shift 2 ;;
    --verbose)   VERBOSE="-v"; shift ;;
    -h|--help)
      sed -n '3,18p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "============================================================"
echo "  Test Data Seed Script"
echo "  Namespace: ${NAMESPACE}"
echo "  Gateway:   ${GATEWAY_URL}"
echo "============================================================"

PASS=0
FAIL=0

# --- Helper function ---
seed_item() {
  local name="$1"
  local endpoint="$2"
  local payload="$3"

  echo -n "  [SEED] ${name} ... "

  HTTP_CODE=$(curl -sf -o /dev/null -w '%{http_code}' \
    -X POST \
    -H "Content-Type: application/json" \
    -d "${payload}" \
    "${GATEWAY_URL}${endpoint}" 2>/dev/null || echo "000")

  if [[ "${HTTP_CODE}" =~ ^(200|201|202)$ ]]; then
    echo "OK (${HTTP_CODE})"
    PASS=$((PASS + 1))
  else
    echo "FAIL (${HTTP_CODE})"
    FAIL=$((FAIL + 1))
  fi
}

# --- Wait for gateway to be available ---
echo ""
echo "--- Waiting for gateway ---"
for i in $(seq 1 30); do
  if curl -sf -o /dev/null "${GATEWAY_URL}/healthz" 2>/dev/null; then
    echo "  Gateway is ready"
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "  WARNING: Gateway not available, some seed operations may fail"
  fi
  sleep 5
done

# --- Seed 1: Test Products in Catalog ---
echo ""
echo "--- Seeding Catalog Products (10 items) ---"

PRODUCTS=(
  # name|description|price_units|price_nanos|category|tags|quantity
  "E2E Widget Alpha|Standard widget for testing|10|990000000|widgets|e2e,test|100"
  "E2E Widget Beta|Premium widget with features|24|990000000|widgets|e2e,test,premium|50"
  "E2E Gadget Gamma|Compact gadget|5|990000000|gadgets|e2e,test|200"
  "E2E Gadget Delta|Advanced gadget|49|990000000|gadgets|e2e,test,advanced|30"
  "E2E Tool Epsilon|Basic tool|3|490000000|tools|e2e,test|500"
  "E2E Tool Zeta|Professional tool|19|990000000|tools|e2e,test,professional|75"
  "E2E Component Eta|Standard component|7|990000000|components|e2e,test|150"
  "E2E Component Theta|High-precision component|99|990000000|components|e2e,test,precision|20"
  "E2E Accessory Iota|General accessory|1|990000000|accessories|e2e,test|1000"
  "E2E Accessory Kappa|Premium accessory|14|990000000|accessories|e2e,test,premium|80"
)

for product in "${PRODUCTS[@]}"; do
  IFS='|' read -r name desc units nanos category tags quantity <<< "${product}"

  # Convert tags to JSON array
  TAGS_JSON=$(echo "${tags}" | sed 's/,/","/g' | sed 's/^/"/;s/$/"/')

  PAYLOAD=$(cat <<EOF
{
  "name": "${name}",
  "description": "${desc}",
  "price": {
    "currency_code": "USD",
    "units": ${units},
    "nanos": ${nanos}
  },
  "category": "${category}",
  "tags": [${TAGS_JSON}],
  "initial_quantity": ${quantity}
}
EOF
)

  seed_item "${name}" "/api/v1/catalog/products" "${PAYLOAD}"
done

# --- Seed 2: Test Payment Methods ---
echo ""
echo "--- Seeding Payment Methods ---"

PAYMENT_METHODS=(
  # name|card_number|exp_month|exp_year|type|description
  "Valid Test Card|4242424242424242|12|2030|card-valid|Standard valid test card"
  "Expired Test Card|4000000000000069|01|2020|card-expired|Expired test card for failure scenarios"
  "Insufficient Funds|4000000000009995|12|2030|card-insufficient|Card that always declines for insufficient funds"
  "Slow Processing|4000000000003220|12|2030|card-slow|Card that simulates slow processing"
  "Bank Transfer|bt_test_12345||2030|bank_transfer|Test bank transfer method"
)

for method in "${PAYMENT_METHODS[@]}"; do
  IFS='|' read -r name card_num exp_m exp_y mtype desc <<< "${method}"

  if [[ -n "${exp_m}" ]]; then
    DETAILS="{\"card_number\":\"${card_num}\",\"exp_month\":\"${exp_m}\",\"exp_year\":\"${exp_y}\"}"
  else
    DETAILS="{\"account_id\":\"${card_num}\"}"
  fi

  PAYLOAD=$(cat <<EOF
{
  "name": "${name}",
  "type": "${mtype}",
  "description": "${desc}",
  "details": ${DETAILS}
}
EOF
)

  seed_item "${name}" "/api/v1/payment/methods" "${PAYLOAD}"
done

# --- Seed 3: Test Users ---
echo ""
echo "--- Seeding Test Users ---"

USERS=(
  # user_id|email|display_name|role
  "e2e-admin|e2e-admin@test.example.org|E2E Admin User|admin"
  "e2e-operator|e2e-operator@test.example.org|E2E Operator User|operator"
  "e2e-viewer|e2e-viewer@test.example.org|E2E Viewer User|viewer"
  "e2e-customer-1|e2e-cust1@test.example.org|E2E Test Customer 1|customer"
  "e2e-customer-2|e2e-cust2@test.example.org|E2E Test Customer 2|customer"
  "e2e-customer-3|e2e-cust3@test.example.org|E2E Test Customer 3|customer"
)

for user in "${USERS[@]}"; do
  IFS='|' read -r uid email name role <<< "${user}"

  PAYLOAD=$(cat <<EOF
{
  "user_id": "${uid}",
  "email": "${email}",
  "display_name": "${name}",
  "role": "${role}",
  "notification_preferences": {
    "channels": [
      {"channel": "email", "enabled": true},
      {"channel": "push", "enabled": true}
    ],
    "quiet_hours": {
      "start_time": "22:00",
      "end_time": "08:00",
      "timezone": "UTC"
    }
  }
}
EOF
)

  seed_item "${name}" "/api/v1/notification/preferences" "${PAYLOAD}"
done

# --- Seed 4: Kafka Test Events ---
echo ""
echo "--- Seeding Kafka Test Events ---"

# Check if kubectl is available and port-forward to Kafka
KAFKA_AVAILABLE=false
if command -v kubectl &>/dev/null; then
  # Try to verify Kafka is running
  if kubectl -n "${NAMESPACE}" get deployment kafka -o name 2>/dev/null | grep -q kafka; then
    KAFKA_AVAILABLE=true
    echo "  Kafka deployment found"
  else
    echo "  Kafka deployment not found, skipping Kafka seed"
  fi
fi

if [[ "${KAFKA_AVAILABLE}" == "true" ]]; then
  echo "  Producing test events to Kafka topics..."

  # Produce test order events
  for i in $(seq 1 5); do
    ORDER_ID="seed-order-$(printf '%03d' ${i})"
    EVENT=$(cat <<EOF
{
  "event_type": "ORDER_CREATED",
  "order_id": "${ORDER_ID}",
  "customer_id": "e2e-customer-$((i % 3 + 1))",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "metadata": {"seed": true, "sequence": ${i}}
}
EOF
)
    # If kafka-console-producer is available, produce directly
    # Otherwise, the events will be produced via the order service API
    echo -n "  [SEED] ${ORDER_ID} ... "
    echo "SKIPPED (use order API instead)"
  done
fi

# --- Seed 5: Database State ---
echo ""
echo "--- Seeding Database State ---"

# Try to connect to PostgreSQL via kubectl port-forward
DB_SEEDED=false

# Check if postgres is running
if kubectl -n "${NAMESPACE}" get deployment postgres -o name 2>/dev/null | grep -q postgres; then
  echo "  PostgreSQL deployment found, seeding database..."

  # Port-forward to PostgreSQL
  PF_PID=""
  kubectl -n "${NAMESPACE}" port-forward svc/postgres 15432:5432 &>/dev/null &
  PF_PID=$!
  sleep 5

  # Try to seed the database
  if command -v psql &>/dev/null; then
    PGPASSWORD="platform_admin" psql -h localhost -p 15432 -U platform_admin -d polyglot_platform -c "
      -- Create test order statuses
      INSERT INTO orders (order_id, customer_id, status, total_amount, created_at)
      VALUES
        ('seed-order-001', 'e2e-customer-1', 'COMPLETED', 1099, NOW() - INTERVAL '2 days'),
        ('seed-order-002', 'e2e-customer-2', 'COMPLETED', 2499, NOW() - INTERVAL '1 day'),
        ('seed-order-003', 'e2e-customer-1', 'CANCELLED', 599, NOW() - INTERVAL '12 hours'),
        ('seed-order-004', 'e2e-customer-3', 'PENDING', 799, NOW() - INTERVAL '1 hour'),
        ('seed-order-005', 'e2e-customer-2', 'PAID', 3499, NOW() - INTERVAL '30 minutes')
      ON CONFLICT (order_id) DO NOTHING;
    " 2>/dev/null && echo "  [OK  ] Order seed data inserted" || echo "  [WARN] Order seed data may have failed"

    DB_SEEDED=true
  else
    echo "  [WARN] psql not available, skipping direct DB seed"
  fi

  # Kill port-forward
  if [[ -n "${PF_PID}" ]]; then
    kill "${PF_PID}" 2>/dev/null || true
  fi
else
  echo "  PostgreSQL deployment not found, skipping DB seed"
fi

# --- Seed 6: Schema Registry ---
echo ""
echo "--- Seeding Schema Registry ---"

# Register initial schemas for CDC topics
SCHEMAS=(
  # subject|schema_type|schema_definition
  "order-events-value|AVRO|{\"type\":\"record\",\"name\":\"OrderEvent\",\"namespace\":\"platform.order.events\",\"fields\":[{\"name\":\"order_id\",\"type\":\"string\"},{\"name\":\"customer_id\",\"type\":\"string\"},{\"name\":\"status\",\"type\":\"string\"},{\"name\":\"total_amount\",\"type\":\"string\"},{\"name\":\"created_at\",\"type\":\"string\"}]}"
  "payment-events-value|AVRO|{\"type\":\"record\",\"name\":\"PaymentEvent\",\"namespace\":\"platform.payment.events\",\"fields\":[{\"name\":\"payment_id\",\"type\":\"string\"},{\"name\":\"order_id\",\"type\":\"string\"},{\"name\":\"status\",\"type\":\"string\"},{\"name\":\"amount\",\"type\":\"string\"},{\"name\":\"created_at\",\"type\":\"string\"}]}"
  "catalog-events-value|AVRO|{\"type\":\"record\",\"name\":\"CatalogEvent\",\"namespace\":\"platform.catalog.events\",\"fields\":[{\"name\":\"product_id\",\"type\":\"string\"},{\"name\":\"name\",\"type\":\"string\"},{\"name\":\"price\",\"type\":\"string\"},{\"name\":\"action\",\"type\":\"string\"},{\"name\":\"created_at\",\"type\":\"string\"}]}"
)

for schema_entry in "${SCHEMAS[@]}"; do
  IFS='|' read -r subject stype sdef <<< "${schema_entry}"

  PAYLOAD=$(cat <<EOF
{
  "subject": "${subject}",
  "schema_type": "${stype}",
  "schema": "${sdef}"
}
EOF
)

  seed_item "Schema:${subject}" "/api/v1/schema-registry/schemas" "${PAYLOAD}"
done

# --- Results ---
echo ""
echo "============================================================"
echo "  Seed Results"
echo "  PASS: ${PASS}"
echo "  FAIL: ${FAIL}"
echo "============================================================"

if [[ ${FAIL} -gt 0 ]]; then
  echo ""
  echo "  WARNING: Some seed operations failed."
  echo "  Tests that depend on seed data may not behave as expected."
fi

exit 0
