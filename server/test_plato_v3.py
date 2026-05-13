#!/usr/bin/env python3
"""
Test suite for PLATO Room Server v3.

Tests: Lamport clocks, WAL crash recovery, tile lifecycle, /stats, /health,
supersede, retract, simulation-first t_minus_event, gate validation, batch submit.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

# Config: use a temp dir for test data
TEST_DIR = tempfile.mkdtemp(prefix="plato-test-")
os.environ["PLATO_DATA_DIR"] = TEST_DIR
os.environ["PLATO_PORT"] = "18847"

# Import server module
sys.path.insert(0, os.path.dirname(__file__))
from plato_room_server import (
    LamportClock, WAL, TileGate, RoomManager, TileState,
    gate, rooms, wal, clock, VERSION
)

PORT = 18847
BASE = f"http://localhost:{PORT}"
PASSED = 0
FAILED = 0

def test(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        print(f"  ❌ {name} — {detail}")

def api(method, path, body=None):
    """Make HTTP request to test server."""
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def make_tile(domain="test", question=None, answer=None, confidence=0.7, agent="test_agent"):
    return {
        "domain": domain,
        "question": question or f"What is the answer to test question {time.time()}?",
        "answer": answer or f"This is a sufficiently long test answer that passes the minimum length gate. The answer is 42 and this should be accepted by the tile validation system.",
        "confidence": confidence,
        "agent": agent,
    }

# ─────────────────────────────────────────────────────────────
# Unit Tests (no server needed)
# ─────────────────────────────────────────────────────────────

print("\n🔬 Lamport Clock")
lc = LamportClock()
t1 = lc.tick()
t2 = lc.tick()
t3 = lc.tick()
test("monotonic increase", t1 < t2 < t3, f"{t1}, {t2}, {t3}")
t4 = lc.merge(100)
test("merge with remote", t4 == 101, f"expected 101, got {t4}")
t5 = lc.tick()
test("tick after merge continues", t5 == 102, f"expected 102, got {t5}")

print("\n🔬 WAL (Write-Ahead Log)")
wal_path = Path(TEST_DIR) / "test_wal.jsonl"
test_wal = WAL(wal_path)
test_wal.append({"op": "add_tile", "room": "test", "tile": {"_hash": "abc123", "lamport": 1}})
test_wal.append({"op": "add_tile", "room": "test", "tile": {"_hash": "def456", "lamport": 2}})
test("WAL file exists", wal_path.exists())
test("WAL has 2 lines", len(wal_path.read_text().strip().split("\n")) == 2)
test_wal.truncate()
test("WAL truncate clears file", wal_path.read_text() == "")

print("\n🔬 Tile Gate")
tg = TileGate()
valid_tile = make_tile()
passed, reason = tg.validate(valid_tile)
test("valid tile passes gate", passed, reason)

bad_tile = {"domain": "test", "question": "hi", "answer": "short"}
passed, reason = tg.validate(bad_tile)
test("short answer rejected", not passed, reason)

absolute_tile = make_tile(answer="This is always guaranteed to work perfectly in every possible scenario and situation.")
passed, reason = tg.validate(absolute_tile)
test("absolute claim rejected", not passed, reason)

dup_tile = valid_tile.copy()
passed, reason = tg.validate(dup_tile)
test("duplicate rejected", not passed, reason)

print("\n🔬 Room Manager")
rm = RoomManager()
tile1 = make_tile(domain="engine")
tile1["_hash"] = "hash1"
tile1["lamport"] = 10
tile1["state"] = TileState.ACTIVE
tile1["timestamp"] = "2026-01-01T00:00:00Z"
tile1["agent"] = "forgemaster"
rm._insert_tile("engine", tile1)

test("room created after insert", "engine" in rm.rooms)
test("tile count = 1", rm.rooms["engine"]["tile_count"] == 1)
test("tile has ACTIVE state", rm.rooms["engine"]["tiles"][0]["state"] == TileState.ACTIVE)

# Test retract
rm.retract_tile("engine", "hash1", "measurement error")
test("tile retracted", rm.rooms["engine"]["tiles"][0]["state"] == TileState.RETRACTED)
test("retraction reason recorded", rm.rooms["engine"]["tiles"][0].get("retraction_reason") == "measurement error")

# Test supersede
tile2 = make_tile(domain="engine")
tile2["_hash"] = "hash2"
rm.rooms["engine"]["tiles"].append(tile2)  # add a fresh active tile for superseding
rm.rooms["engine"]["tile_count"] = 2
# Manually set state
rm.rooms["engine"]["tiles"][1]["state"] = TileState.ACTIVE
rm.rooms["engine"]["tiles"][1]["_hash"] = "hash2"

new_tile = make_tile(domain="engine")
new_tile["_hash"] = "hash3"
rm.supersede_tile("engine", "hash2", new_tile)
test("old tile superseded", rm.rooms["engine"]["tiles"][1]["state"] == TileState.SUPERSEDED)
test("new tile added", rm.rooms["engine"]["tile_count"] == 3)
test("new tile supersedes old", rm.rooms["engine"]["tiles"][2].get("supersedes") == "hash2")

print("\n🔬 Room Manager Stats")
# Use isolated data dir for stats test
stats_dir = tempfile.mkdtemp(prefix="plato-stats-test-")
os.makedirs(stats_dir + "/rooms", exist_ok=True)
rm2 = RoomManager()
rm2.rooms = {}  # Fresh rooms, no disk leak
rm2._save_room = lambda n: None  # No disk writes for this test
for i in range(5):
    t = make_tile(domain="domain_a")
    t["_hash"] = f"stat_hash_{i}"
    t["state"] = TileState.ACTIVE
    t["lamport"] = i + 1
    t["agent"] = "agent_1"
    t["timestamp"] = "2026-01-01T00:00:00Z"
    rm2._insert_tile("domain_a", t)

# Add retracted tile
t_r = make_tile(domain="domain_a")
t_r["_hash"] = "retracted_hash"
t_r["state"] = TileState.RETRACTED
t_r["agent"] = "agent_2"
rm2._insert_tile("domain_a", t_r)

# Add tile with t_minus_event
t_f = make_tile(domain="domain_b")
t_f["_hash"] = "future_hash"
t_f["state"] = TileState.ACTIVE
t_f["agent"] = "agent_1"
t_f["t_minus_event"] = 3600  # 1 hour from now
rm2._insert_tile("domain_b", t_f)

stats = rm2.get_stats()
test("stats rooms = 2", stats["rooms"] == 2, f"got {stats['rooms']}")
test("stats total_tiles = 7", stats["total_tiles"] == 7, f"got {stats['total_tiles']}")
test("stats active = 6", stats["active_tiles"] == 6, f"got {stats['active_tiles']}")
test("stats retracted = 1", stats["retracted_tiles"] == 1, f"got {stats['retracted_tiles']}")
test("stats tiles_with_future = 1", stats["tiles_with_future"] == 1, f"got {stats['tiles_with_future']}")
test("stats unique_agents = 2", stats["unique_agents"] == 2, f"got {stats['unique_agents']}")
test("stats unique_domains = 2", stats["unique_domains"] == 2, f"got {stats['unique_domains']}")

# ─────────────────────────────────────────────────────────────
# Integration Tests (start server)
# ─────────────────────────────────────────────────────────────

print("\n🔬 Integration Tests (HTTP server)")

# Start server in background thread
from http.server import HTTPServer
from plato_room_server import PlatoHandler

# Reset global state for clean integration test
import plato_room_server as srv
srv.rooms = srv.RoomManager()
srv.gate = srv.TileGate()
srv.wal = srv.WAL(Path(TEST_DIR) / "wal.jsonl")
srv.clock = srv.LamportClock()
srv.wal._path = Path(TEST_DIR) / "wal.jsonl"

server = HTTPServer(("127.0.0.1", PORT), PlatoHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
time.sleep(0.3)

# Test /health
status, data = api("GET", "/health")
test("/health returns 200", status == 200)
test("/health has version", data.get("version") == VERSION)
test("/health has rooms count", "rooms" in data)
test("/health has tiles count", "tiles" in data)

# Test /stats
status, data = api("GET", "/stats")
test("/stats returns 200", status == 200)
test("/stats has lamport_clock", "lamport_clock" in data)
test("/stats has active_tiles", "active_tiles" in data)
test("/stats has superseded_tiles", "superseded_tiles" in data)
test("/stats has retracted_tiles", "retracted_tiles" in data)
test("/stats has tiles_with_future", "tiles_with_future" in data)
test("/stats has unique_agents", "unique_agents" in data)
test("/stats has uptime_seconds", "uptime_seconds" in data)

# Test /rooms
status, data = api("GET", "/rooms")
test("/rooms returns 200", status == 200)
test("/rooms is dict", isinstance(data, dict))

# Test POST /submit
tile = make_tile(domain="integration_test")
status, data = api("POST", "/submit", tile)
test("/submit accepts valid tile", status == 200, f"got {status}: {data}")
test("/submit returns tile_hash", "_hash" in data or "tile_hash" in data)
test("/submit returns lamport", "lamport" in data)

# Test duplicate rejection
status, data = api("POST", "/submit", tile)
test("/submit rejects duplicate", status == 403)

# Test /room/<name>
status, data = api("GET", "/room/integration_test")
test("/room/<name> returns 200", status == 200)
test("/room has tiles", "tiles" in data)
test("/room tile has state", data["tiles"][0].get("state") == TileState.ACTIVE)
test("/room tile has lamport", isinstance(data["tiles"][0].get("lamport"), int))
test("/room tile has timestamp", "timestamp" in data["tiles"][0])

# Test POST /retract
status, data = api("POST", "/retract", {
    "room": "integration_test",
    "tile_hash": data.get("tiles", [{}])[0].get("_hash", "unknown"),
    "reason": "test retraction",
})
# Get the hash from the submit response
tile2 = make_tile(domain="retract_test")
status2, data2 = api("POST", "/submit", tile2)
test("submit for retract accepted", status2 == 200)
hash_to_retract = data2["tile_hash"]

status, data = api("POST", "/retract", {
    "room": "retract_test",
    "tile_hash": hash_to_retract,
    "reason": "measured incorrectly",
})
test("/retract returns 200", status == 200, f"got {status}")
test("/retract confirms retracted", data.get("status") == "retracted")

# Verify retraction in room
status, room_data = api("GET", "/room/retract_test")
retracted_tiles = [t for t in room_data.get("tiles", []) if t.get("state") == TileState.RETRACTED]
test("room has retracted tile", len(retracted_tiles) == 1)
test("retraction reason stored", retracted_tiles[0].get("retraction_reason") == "measured incorrectly")

# Test POST /supersede
tile3 = make_tile(domain="supersede_test")
status3, data3 = api("POST", "/submit", tile3)
old_hash = data3["tile_hash"]

new_tile = make_tile(domain="supersede_test", answer="This is the corrected answer that replaces the original with better data from re-measurement.")
status, data = api("POST", "/supersede", {
    "room": "supersede_test",
    "old_hash": old_hash,
    "new_tile": new_tile,
})
test("/supersede returns 200", status == 200, f"got {status}: {data}")
test("/supersede confirms superseded", data.get("status") == "superseded")

# Verify supersede in room
status, room_data = api("GET", "/room/supersede_test")
superseded = [t for t in room_data.get("tiles", []) if t.get("state") == TileState.SUPERSEDED]
active = [t for t in room_data.get("tiles", []) if t.get("state") == TileState.ACTIVE]
test("room has 1 superseded tile", len(superseded) == 1, f"got {len(superseded)}")
test("room has 1 active tile (new)", len(active) == 1, f"got {len(active)}")
test("new tile supersedes old", active[0].get("supersedes") == old_hash if active else False)

# Test simulation-first: tile with t_minus_event
future_tile = make_tile(domain="sim_test")
future_tile["t_minus_event"] = 1800  # 30 minutes from now
future_tile["question"] = "What happens when engine temp reaches 195F?"
future_tile["answer"] = "Simulation predicts normal operation at 195F with exhaust < 380F. Confirm with actual sensor reading when T-0 arrives."
status, data = api("POST", "/submit", future_tile)
test("simulation-first tile accepted", status == 200, f"got {status}")

# Verify t_minus_event in room
status, room_data = api("GET", "/room/sim_test")
future_tiles = [t for t in room_data.get("tiles", []) if t.get("t_minus_event") is not None]
test("room has future tile", len(future_tiles) == 1)
test("future tile has t_minus_event=1800", future_tiles[0].get("t_minus_event") == 1800 if future_tiles else False)

# Test /stats after all operations
status, data = api("GET", "/stats")
test("/stats shows tiles_with_future > 0", data["tiles_with_future"] >= 1)
test("/stats shows retracted > 0", data["retracted_tiles"] >= 1)
test("/stats shows superseded > 0", data["superseded_tiles"] >= 1)
test("/stats lamport advanced", data["lamport_clock"] > 0)

# Test batch submit
batch = [make_tile(domain="batch_test") for _ in range(3)]
status, data = api("POST", "/submit_batch", {"tiles": batch})
test("/submit_batch returns 200", status == 200)
test("/submit_batch all accepted", data["accepted"] == 3, f"got {data.get('accepted')}")

# Test 404
status, data = api("GET", "/nonexistent")
test("unknown path returns 404", status == 404)

# Test /room/<nonexistent>
status, data = api("GET", "/room/nonexistent_room_xyz")
test("nonexistent room returns 404", status == 404)

# Test invalid JSON
req = urllib.request.Request(f"{BASE}/submit", data=b"not json",
    headers={"Content-Type": "application/json"}, method="POST")
try:
    urllib.request.urlopen(req, timeout=5)
    test("invalid JSON returns 400", False, "no error raised")
except urllib.error.HTTPError as e:
    test("invalid JSON returns 400", e.code == 400)

# Test missing field
status, data = api("POST", "/submit", {"domain": "test"})
test("missing fields returns 403", status == 403)

# ── WAL Crash Recovery Test ─────────────────────────────────

print("\n🔬 WAL Crash Recovery")

# Write WAL entries manually
test_wal_path = Path(TEST_DIR) / "crash_test_wal.jsonl"
test_wal = WAL(test_wal_path)
for i in range(5):
    test_wal.append({
        "op": "add_tile",
        "room": f"crash_room_{i % 2}",
        "tile": {
            "_hash": f"crash_hash_{i}",
            "domain": f"crash_room_{i % 2}",
            "question": f"Crash test question {i}?",
            "answer": f"Crash test answer {i} — long enough to pass validation gate.",
            "lamport": i + 1,
            "state": TileState.ACTIVE,
            "timestamp": "2026-01-01T00:00:00Z",
        }
    })

test("WAL has 5 entries", len(test_wal_path.read_text().strip().split("\n")) == 5)

# Replay into fresh room manager
crash_rm = RoomManager()
replay_count = test_wal.replay(crash_rm)
test("replayed 5 entries", replay_count == 5, f"got {replay_count}")
test("crash_room_0 has 3 tiles", crash_rm.rooms.get("crash_room_0", {}).get("tile_count") == 3)
test("crash_room_1 has 2 tiles", crash_rm.rooms.get("crash_room_1", {}).get("tile_count") == 2)

# ── Summary ─────────────────────────────────────────────────

server.shutdown()

print(f"\n{'='*50}")
print(f"  PLATO Server v3 Test Results")
print(f"  ✅ Passed: {PASSED}")
print(f"  ❌ Failed: {FAILED}")
print(f"  Total: {PASSED + FAILED}")
print(f"{'='*50}")

# Cleanup
import shutil
shutil.rmtree(TEST_DIR, ignore_errors=True)

sys.exit(1 if FAILED > 0 else 0)
