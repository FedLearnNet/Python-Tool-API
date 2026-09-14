import requests
import json
import io
import cbor2
import time

RELAY_ADDRESS_HTTP = "http://localhost:9140"
CONTROLLER_ADDRESS_ORCH_HTTP = "http://localhost:8002"
CONTROLLER_ADDRESS_FLCOMM_HTTP = "http://localhost:8003"
RUN_ID = "test_run_id"
PLAIN_COMM_ID = "plain_comm_id"
SMPC_COMM_ID = "smpc_comm_id"
DP_COMM_ID = "dp_comm_id"
AGGREGATOR_PLAIN_JSON = "aggregator_plain_json"
AGGREGATOR_PLAIN_CBOR = "aggregator_plain_cbor"
AGGREGATOR_SMPC = "aggregator_smpc"
AGGREGATOR_DP = "aggregator_dp"

PLAIN_DATA_SEND = 10
# SMPC: each client sends [1.0, 2.0, 3.0], coordinator should receive sum [3.0, 6.0, 9.0]
SMPC_DATA_SEND = [1.0, 2.0, 3.0]
SMPC_EXPONENT = 8
# DP: each client sends 10.0 with Laplace noise; result should be close to 10.0
DP_DATA_SEND = 10.0

NUM_CLIENTS = 3

# =============================================
# Helpers
# =============================================
def wait_for_services(address):
    max_retries = 60
    for i in range(max_retries):
        time.sleep(0.5)
        response = requests.get(address + "/healthz", timeout=5)
        if response.status_code == 200:
            return
    raise TimeoutError(f"Service at {address} is not healthy")

def request_start_learning_on_controller(client_id, client_key):
    start_learning_address = CONTROLLER_ADDRESS_ORCH_HTTP + "/start-learning"
    sendername = "client " + client_id if client_id != coordinator_id else "coordinator"
    response = requests.post(
        start_learning_address,
        json={
            "channel": channel,
            "clientId": client_id,
            "clientKey": client_key,
            "relayKey": relay_key,
            "runId": RUN_ID,
            "coordinatorId": coordinator_id,
            "maxNumClients": NUM_CLIENTS,
            "orderClientIds": client_ids,
            "appKey": client_id,
            "appVersion": "v2"
        },
        timeout=20
    )
    if response.status_code == 200:
        print(f"  Successfully requested start learning for {sendername}")
    else:
        print(f"  Failed to request start learning for {sendername}: {response.status_code} - {response.text}")

def request_receive_setup_on_controller(client_id):
    request_payload = {
        "appKey": client_id,
        "channel": channel,
        "clientId": client_id,
    }
    try:
        receive_url = f"{CONTROLLER_ADDRESS_FLCOMM_HTTP}/receive-setup"
        response = requests.post(receive_url, json=request_payload, timeout=15)
        if response.status_code == 200:
            setup_info = json.loads(response.content)
            return setup_info
        else:
            print(f"  receive-setup failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"  Error during receive-setup: {e}")
        return None

def request_send_data_on_controller(client_id, data_to_send, comm_id, toAggregator=None, fromAggregator=None, serialization_format="json", smpc=None, dp=None):
    if serialization_format not in ["json", "cbor"]:
        raise ValueError(f"Unsupported serialization format: {serialization_format}")
    send_url = f"{CONTROLLER_ADDRESS_FLCOMM_HTTP}/send-data"
    metadata = {
        "appKey": client_id,
        "channel": channel,
        "serializationUsed": serialization_format,
        "to": [],
        "fromAggregator": fromAggregator,
        "toAggregator": toAggregator,
        "communicationId": comm_id,
        "smpc": smpc,
        "dp": dp,
    }
    if serialization_format == "json":
        data_bytes = json.dumps(data_to_send).encode("utf-8")
    elif serialization_format == "cbor":
        data_bytes = cbor2.dumps(data_to_send)
    else:
        raise ValueError(f"Unsupported serialization format: {serialization_format}")
    files = {
        "metadata": (None, json.dumps(metadata), "application/json"),
        "data": ("payload.bin", io.BytesIO(data_bytes), "application/octet-stream"),
    }
    response = requests.post(send_url, files=files, timeout=10)
    if response.status_code == 200:
        print(f"  Successfully sent data for client {client_id} (comm_id={comm_id})")
    else:
        print(f"  Failed to send for client {client_id}: {response.status_code} - {response.text}")


def request_receive_data_on_controller(app_key, comm_id, to_aggregator=None, from_aggregator=None, fromClientIds=None, requested_serialization_format="json"):
    if requested_serialization_format not in ["json", "cbor"]:
        raise ValueError(f"Unsupported serialization format: {requested_serialization_format}")
    request_payload = {
        "appKey": app_key,
        "channel": channel,
        "serializationFormat": requested_serialization_format,
        "communicationId": comm_id,
        "toAggregator": to_aggregator,
        "fromAggregator": from_aggregator,
        "fromClientIds": fromClientIds,
        "clientId": None,
    }
    try:
        receive_url = f"{CONTROLLER_ADDRESS_FLCOMM_HTTP}/receive-data"
        response = requests.post(receive_url, json=request_payload, timeout=15)
        if response.status_code == 200:
            if requested_serialization_format == "json":
                return json.loads(response.content)
            elif requested_serialization_format == "cbor":
                return cbor2.loads(response.content)
        elif response.status_code == 204:
            return []
        else:
            print(f"  receive-data failed: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        print(f"  Error during receive: {e}")
        return []


def poll_receive(app_key, comm_id, expected_count, timeout_s=20, to_aggregator=None, from_aggregator=None, fromClientIds=None, requested_serialization_format="json"):
    """Poll /receive-data until expected_count messages arrive or timeout."""
    collected = []
    deadline = time.time() + timeout_s
    while len(collected) < expected_count and time.time() < deadline:
        msgs = request_receive_data_on_controller(app_key, comm_id, to_aggregator, from_aggregator, fromClientIds, requested_serialization_format)
        collected.extend(msgs)
        if len(collected) < expected_count:
            time.sleep(0.5)
    return collected

# =============================================
# Prerequisites: ensure relay server and controller are running and healthy
# =============================================
print("Checking relay server health...")
wait_for_services(RELAY_ADDRESS_HTTP)
print("Checking controller health...")
wait_for_services(CONTROLLER_ADDRESS_ORCH_HTTP)

# =============================================
# Setup: create FL run on relay server
# =============================================
create_learning_address = RELAY_ADDRESS_HTTP + "/create-fl-run"
print("Requesting start learning on relay server at " + create_learning_address)
relay_response = requests.post(
    create_learning_address,
    json={"maxNumClients": NUM_CLIENTS, "appVersion": "v2"},
    timeout=20
)
relay_response_dict = relay_response.json()
coordinator_id = relay_response_dict["coordinatorId"]
coordinator_key = relay_response_dict["coordinatorKey"]
client_ids = relay_response_dict["clientIds"]
client_id_to_client_key = relay_response_dict["clientId2ClientKey"]
channel = relay_response_dict["channel"]
relay_key = relay_response_dict["relayKey"]

# =============================================
# Start all clients and coordinator
# =============================================
print("\n--- Starting clients ---")
for client_id in client_ids:
    client_key = client_id_to_client_key[client_id]
    request_start_learning_on_controller(client_id, client_key)

print("--- Starting coordinator ---")
request_start_learning_on_controller(coordinator_id, coordinator_key)

# Give connections time to establish and exchange public keys
time.sleep(0.5)

# =============================================
# REQUEST SETUP INFO FROM CONTROLLER
# =============================================
print("\n--- Requesting setup info from controller ---")
for client_id in client_ids:
    setup_info = request_receive_setup_on_controller(client_id)
    if setup_info:
        print(f"  Client {client_id} received setup info: {setup_info}")
    else:
        print(f"  FAIL: Client {client_id} did not receive setup info")
        exit(1)

# =============================================
# PLAIN DATA TEST
# =============================================
# JSON
print("\n--- Plain data test JSON ---")
for client_id in client_ids:
    request_send_data_on_controller(client_id, PLAIN_DATA_SEND, PLAIN_COMM_ID, toAggregator=AGGREGATOR_PLAIN_JSON)

msgs_received = poll_receive(coordinator_id, PLAIN_COMM_ID, NUM_CLIENTS, to_aggregator=AGGREGATOR_PLAIN_JSON, requested_serialization_format="json")
print(f"Coordinator received {len(msgs_received)}/{NUM_CLIENTS} plain messages")
for idx, msg in enumerate(msgs_received):
    if msg["data"] != PLAIN_DATA_SEND:
        print(f"  FAIL message {idx+1}: got {msg['data']}, expected {PLAIN_DATA_SEND}")
        exit(1)
print("  All values correct")

# Broadcast back to all clients
request_send_data_on_controller(coordinator_id, PLAIN_DATA_SEND, PLAIN_COMM_ID, fromAggregator=AGGREGATOR_PLAIN_JSON)
for client_id in client_ids:
    msgs = poll_receive(client_id, PLAIN_COMM_ID, 1, from_aggregator=AGGREGATOR_PLAIN_JSON, requested_serialization_format="json")
    if not msgs:
        print(f"  FAIL: no message received for client {client_id}")
        exit(1)
    if msgs[0]["data"] != PLAIN_DATA_SEND:
        print(f"  FAIL client {client_id}: got {msgs[0]['data']}, expected {PLAIN_DATA_SEND}")
        exit(1)
print("  Broadcast received correctly by all clients")
print("Plain data test JSON PASSED")

# CBOR
print("\n--- Plain data test CBOR ---")
for client_id in client_ids:
    request_send_data_on_controller(client_id, PLAIN_DATA_SEND, PLAIN_COMM_ID, toAggregator=AGGREGATOR_PLAIN_CBOR, serialization_format="cbor")

msgs_received = poll_receive(coordinator_id, PLAIN_COMM_ID, NUM_CLIENTS, to_aggregator=AGGREGATOR_PLAIN_CBOR, requested_serialization_format="cbor")
print(f"Coordinator received {len(msgs_received)}/{NUM_CLIENTS} plain messages")
for idx, msg in enumerate(msgs_received):
    if msg["data"] != PLAIN_DATA_SEND:
        print(f"  FAIL message {idx+1}: got {msg['data']}, expected {PLAIN_DATA_SEND}")
        exit(1)
print("  All values correct")

# Broadcast back to all clients
request_send_data_on_controller(coordinator_id, PLAIN_DATA_SEND, PLAIN_COMM_ID, fromAggregator=AGGREGATOR_PLAIN_CBOR, serialization_format="cbor")
for client_id in client_ids:
    msgs = poll_receive(client_id, PLAIN_COMM_ID, 1, from_aggregator=AGGREGATOR_PLAIN_CBOR, requested_serialization_format="cbor")
    if not msgs:
        print(f"  FAIL: no message received for client {client_id}")
        exit(1)
    if msgs[0]["data"] != PLAIN_DATA_SEND:
        print(f"  FAIL client {client_id}: got {msgs[0]['data']}, expected {PLAIN_DATA_SEND}")
        exit(1)
print("  Broadcast received correctly by all clients")
print("Plain data test CBOR PASSED")

# =============================================
# DP TEST
# =============================================
print("\n--- DP test ---")
# Each client sends DP_DATA_SEND with Laplace noise.
# epsilon=10 and clippingVal=10 → no clipping (|10|<=10), sensitivity=2*10=20, scale=20/10=2.
# Expected noise is ±2 per standard deviation; tolerance bound of ±15 is very conservative.
dp_params = {
    "noisetype": "laplace",
    "epsilon": 10.0,
    "delta": 0,
    "sensitivity": None,
    "clippingVal": 10.0,
}
for client_id in client_ids:
    request_send_data_on_controller(client_id, DP_DATA_SEND, DP_COMM_ID, dp=dp_params, toAggregator=AGGREGATOR_DP)

dp_msgs = poll_receive(coordinator_id, DP_COMM_ID, NUM_CLIENTS, to_aggregator=AGGREGATOR_DP)
print(f"Coordinator received {len(dp_msgs)}/{NUM_CLIENTS} DP messages")
for idx, msg in enumerate(dp_msgs):
    val = msg["data"]
    print(f"  DP message {idx+1}: {val:.4f} (sent {DP_DATA_SEND}, noise applied)")
    # Laplace(scale=2): P(|noise|>15) < 0.0001%
    if not (-15 + DP_DATA_SEND <= val <= 15 + DP_DATA_SEND):
        print(f"  FAIL: DP value {val} too far from expected {DP_DATA_SEND}")
        exit(1)
    if val == DP_DATA_SEND:
        print(f"  FAIL: DP value {val} has no noise, which is unlikely")
        exit(1)
print("DP test PASSED (noised values within expected range)")

# =============================================
# SMPC TEST
# =============================================
print("\n--- SMPC test ---")
# All clients must send for the SAME comm_id before any aggregation triggers.
# Flow: each client shards its data → shards reach all other clients via relay →
# each client aggregates shards → sends CMD_SEND_SMPC_AGG to coordinator →
# coordinator does final aggregation → result available via receive-data.
smpc_params = {
    "useSmpc": True,
    "operation": "add",
    "exponent": SMPC_EXPONENT,
    "shards": NUM_CLIENTS,
}
for client_id in client_ids:
    request_send_data_on_controller(client_id, SMPC_DATA_SEND, SMPC_COMM_ID, toAggregator=AGGREGATOR_SMPC, smpc=smpc_params)

# SMPC pipeline has multiple hops; allow extra time
smpc_msgs = poll_receive(coordinator_id, SMPC_COMM_ID, 1, timeout_s=10, to_aggregator=AGGREGATOR_SMPC)
print(f"Coordinator received {len(smpc_msgs)} SMPC aggregation result(s)")

if not smpc_msgs:
    print("FAIL: no SMPC result received at coordinator")
    exit(1)

for idx, msg in enumerate(smpc_msgs):
    result = msg["data"]
    expected = [v * NUM_CLIENTS for v in SMPC_DATA_SEND] if isinstance(result, list) else SMPC_DATA_SEND * NUM_CLIENTS
    print(f"  SMPC result {idx+1}: {result}  (expected ≈ {expected})")
    tolerance = 0.1
    if isinstance(result, list):
        for r, e in zip(result, expected):
            if abs(r - e) > tolerance:
                print(f"  FAIL: {r} differs from expected {e} by more than {tolerance}")
                exit(1)
    else:
        if abs(result - expected) > tolerance:
            print(f"  FAIL: {result} differs from expected {expected} by more than {tolerance}")
            exit(1)
print("SMPC test PASSED")

print("\n--- All tests completed ---")
