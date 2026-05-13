#!/usr/bin/env python3
"""
PLATO Room Server v3 — Simulation-First Coordination

Improvements over v2:
- Tile lifecycle: Active / Superseded / Retracted states
- Lamport clocks for causal ordering across agents
- WAL (write-ahead log) for crash recovery
- /stats endpoint for operational visibility
- /health endpoint for container healthchecks
- Provenance chain with agent identity
- Simulation-first: tiles can carry t_minus_event (planned futures)

The server is a room-and-tile store. Simple survives.
"""
import json, hashlib, time, threading, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

VERSION = "v3-simulation-first"

# ── Configuration ───────────────────────────────────────────
DATA_DIR = Path(os.environ.get("PLATO_DATA_DIR", "/tmp/plato-server-data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
TILES_DIR = DATA_DIR / "tiles"
TILES_DIR.mkdir(exist_ok=True)
ROOMS_DIR = DATA_DIR / "rooms"
ROOMS_DIR.mkdir(exist_ok=True)
WAL_FILE = DATA_DIR / "wal.jsonl"
LOG_FILE = DATA_DIR / "server.log"
PORT = int(os.environ.get("PLATO_PORT", "8847"))

# ── Lamport Clock ───────────────────────────────────────────

class LamportClock:
    """Simple Lamport logical clock for causal ordering."""
    def __init__(self):
        self._time = 0
        self._lock = threading.Lock()
    
    def tick(self) -> int:
        """Increment and return local time."""
        with self._lock:
            self._time += 1
            return self._time
    
    def merge(self, remote_time: int) -> int:
        """Merge with a remote timestamp: max(local, remote) + 1."""
        with self._lock:
            self._time = max(self._time, remote_time) + 1
            return self._time
    
    @property
    def now(self) -> int:
        with self._lock:
            return self._time

clock = LamportClock()

# ── Write-Ahead Log ─────────────────────────────────────────

class WAL:
    """Append-only write-ahead log for crash recovery."""
    
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
    
    def append(self, entry: dict):
        """Append an entry to the WAL. Returns True on success."""
        with self._lock:
            try:
                with open(self._path, "a") as f:
                    f.write(json.dumps(entry, separators=(',', ':')) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                return True
            except Exception as e:
                log(f"WAL write error: {e}")
                return False
    
    def replay(self, room_manager) -> int:
        """Replay WAL entries into room manager. Returns count of replayed entries."""
        if not self._path.exists():
            return 0
        
        replayed = 0
        with open(self._path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("op") == "add_tile":
                        room_name = entry["room"]
                        tile = entry["tile"]
                        # Direct insert, skip gate (already validated)
                        room_manager._insert_tile(room_name, tile)
                        # Merge Lamport clock
                        if "lamport" in tile:
                            clock.merge(tile["lamport"])
                        replayed += 1
                except Exception as e:
                    log(f"WAL replay error on line {replayed}: {e}")
        
        log(f"WAL replayed {replayed} entries")
        return replayed
    
    def truncate(self):
        """Clear the WAL after successful checkpoint."""
        with self._lock:
            if self._path.exists():
                self._path.write_text("")

wal = WAL(WAL_FILE)

# ── Tile States ─────────────────────────────────────────────

class TileState:
    ACTIVE = "Active"
    SUPERSEDED = "Superseded"
    RETRACTED = "Retracted"

# ── Tile Gate ───────────────────────────────────────────────

class TileGate:
    """P0 gate for incoming tiles. Reject garbage before it trains anything."""
    
    ABSOLUTE_WORDS = ["always", "never", "guaranteed", "impossible", "proven", "everyone", "nobody"]
    MIN_ANSWER_LEN = 20
    MAX_ANSWER_LEN = 5000
    MIN_QUESTION_LEN = 5
    
    def __init__(self):
        self.stats = {"accepted": 0, "rejected": 0, "reasons": defaultdict(int)}
        self._hashes = set()
        self._load_hashes()
    
    def _load_hashes(self):
        """Load existing hashes from all rooms to prevent duplicates."""
        for room_file in ROOMS_DIR.glob("*.json"):
            try:
                data = json.loads(room_file.read_text())
                for tile in data.get("tiles", []):
                    h = tile.get("_hash")
                    if h:
                        self._hashes.add(h)
            except:
                pass
    
    def validate(self, tile: dict) -> tuple:
        """Validate a tile through the deadband. Returns (passed, reason)."""
        # Gate 1: Required fields
        for field in ["domain", "question", "answer"]:
            if field not in tile or not tile[field]:
                self.stats["rejected"] += 1
                self.stats["reasons"]["missing_field"] += 1
                return False, f"Missing required field: {field}"
        
        # Gate 2: Length bounds
        ans_len = len(tile["answer"])
        if ans_len < self.MIN_ANSWER_LEN:
            self.stats["rejected"] += 1
            self.stats["reasons"]["answer_too_short"] += 1
            return False, f"Answer too short ({ans_len} < {self.MIN_ANSWER_LEN})"
        
        if ans_len > self.MAX_ANSWER_LEN:
            self.stats["rejected"] += 1
            self.stats["reasons"]["answer_too_long"] += 1
            return False, f"Answer too long ({ans_len} > {self.MAX_ANSWER_LEN})"
        
        if len(tile["question"]) < self.MIN_QUESTION_LEN:
            self.stats["rejected"] += 1
            self.stats["reasons"]["question_too_short"] += 1
            return False, "Question too short"
        
        # Gate 3: No absolute claims (falsifiability)
        answer_lower = tile["answer"].lower()
        for word in self.ABSOLUTE_WORDS:
            if f" {word} " in f" {answer_lower} ":
                self.stats["rejected"] += 1
                self.stats["reasons"]["absolute_claim"] += 1
                return False, f"Absolute claim detected: '{word}'"
        
        # Gate 4: Confidence bounds
        conf = tile.get("confidence", 0.5)
        if not (0.0 <= conf <= 1.0):
            self.stats["rejected"] += 1
            self.stats["reasons"]["invalid_confidence"] += 1
            return False, f"Invalid confidence: {conf}"
        
        # Gate 5: Duplicate check
        content_hash = hashlib.sha256(
            (tile["question"] + tile["answer"]).encode()
        ).hexdigest()[:16]
        tile["_hash"] = content_hash
        
        if content_hash in self._hashes:
            self.stats["rejected"] += 1
            self.stats["reasons"]["duplicate"] += 1
            return False, "Duplicate tile"
        
        # PASSED ALL GATES
        self.stats["accepted"] += 1
        self._hashes.add(content_hash)
        return True, "Accepted"
    
    def get_stats(self):
        return dict(self.stats)

# ── Room Manager ────────────────────────────────────────────

class RoomManager:
    """Manages PLATO rooms with tile lifecycle states."""
    
    def __init__(self):
        self.rooms = {}
        self._lock = threading.Lock()
        self._load_rooms()
    
    def _load_rooms(self):
        """Load rooms from disk."""
        for room_file in ROOMS_DIR.glob("*.json"):
            try:
                data = json.loads(room_file.read_text())
                name = room_file.stem
                self.rooms[name] = data
            except:
                pass
    
    def _save_room(self, room_name: str):
        """Save room to disk."""
        room_file = ROOMS_DIR / f"{room_name}.json"
        room_file.write_text(json.dumps(self.rooms[room_name], indent=2))
    
    def _insert_tile(self, room_name: str, tile: dict):
        """Insert tile directly (for WAL replay). No gate check."""
        with self._lock:
            if room_name not in self.rooms:
                self.rooms[room_name] = {
                    "tiles": [],
                    "created": datetime.now(timezone.utc).isoformat(),
                    "tile_count": 0,
                    "last_trained": None,
                }
            room = self.rooms[room_name]
            room["tiles"].append(tile)
            room["tile_count"] = len(room["tiles"])
            self._save_room(room_name)
    
    def add_tile(self, room_name: str, tile: dict):
        """Add a validated tile to a room with lifecycle metadata."""
        with self._lock:
            if room_name not in self.rooms:
                self.rooms[room_name] = {
                    "tiles": [],
                    "created": datetime.now(timezone.utc).isoformat(),
                    "tile_count": 0,
                    "last_trained": None,
                }
            
            # Enrich tile with lifecycle metadata
            tile.setdefault("state", TileState.ACTIVE)
            tile.setdefault("lamport", clock.tick())
            tile.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            tile.setdefault("agent", "unknown")
            tile.setdefault("superseded_by", None)
            tile.setdefault("t_minus_event", None)  # Simulation-first: planned futures
            
            room = self.rooms[room_name]
            room["tiles"].append(tile)
            room["tile_count"] = len(room["tiles"])
            self._save_room(room_name)
    
    def get_room(self, room_name: str) -> dict:
        return self.rooms.get(room_name, {"tiles": [], "tile_count": 0})
    
    def list_rooms(self) -> dict:
        return {name: {"tile_count": r["tile_count"], "created": r.get("created")} 
                for name, r in self.rooms.items()}
    
    def retract_tile(self, room_name: str, tile_hash: str, reason: str = "") -> bool:
        """Retract a tile by hash. Tile persists but marked Retracted."""
        with self._lock:
            room = self.rooms.get(room_name)
            if not room:
                return False
            for tile in room["tiles"]:
                if tile.get("_hash") == tile_hash and tile.get("state") == TileState.ACTIVE:
                    tile["state"] = TileState.RETRACTED
                    tile["retracted_at"] = datetime.now(timezone.utc).isoformat()
                    tile["retraction_reason"] = reason
                    self._save_room(room_name)
                    return True
            return False
    
    def supersede_tile(self, room_name: str, old_hash: str, new_tile: dict) -> bool:
        """Mark old tile as Superseded by new tile."""
        with self._lock:
            room = self.rooms.get(room_name)
            if not room:
                return False
            for tile in room["tiles"]:
                if tile.get("_hash") == old_hash and tile.get("state") == TileState.ACTIVE:
                    tile["state"] = TileState.SUPERSEDED
                    tile["superseded_by"] = new_tile.get("_hash", "unknown")
                    tile["superseded_at"] = datetime.now(timezone.utc).isoformat()
                    break
            # Add new tile
            new_tile.setdefault("state", TileState.ACTIVE)
            new_tile.setdefault("lamport", clock.tick())
            new_tile.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            new_tile.setdefault("supersedes", old_hash)
            room["tiles"].append(new_tile)
            room["tile_count"] = len(room["tiles"])
            self._save_room(room_name)
            return True
    
    def get_stats(self) -> dict:
        """Aggregate statistics across all rooms."""
        total_tiles = 0
        active = 0
        superseded = 0
        retracted = 0
        with_future = 0  # tiles with t_minus_event (simulation-first)
        agents = set()
        domains = set()
        
        for name, room in self.rooms.items():
            for tile in room.get("tiles", []):
                total_tiles += 1
                state = tile.get("state", TileState.ACTIVE)
                if state == TileState.ACTIVE:
                    active += 1
                elif state == TileState.SUPERSEDED:
                    superseded += 1
                elif state == TileState.RETRACTED:
                    retracted += 1
                if tile.get("t_minus_event") is not None:
                    with_future += 1
                agents.add(tile.get("agent", "unknown"))
                domains.add(tile.get("domain", name))
        
        return {
            "rooms": len(self.rooms),
            "total_tiles": total_tiles,
            "active_tiles": active,
            "superseded_tiles": superseded,
            "retracted_tiles": retracted,
            "tiles_with_future": with_future,
            "unique_agents": len(agents),
            "unique_domains": len(domains),
            "lamport_clock": clock.now,
        }

# ── Logging ─────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ── Server ──────────────────────────────────────────────────

gate = TileGate()
rooms = RoomManager()

# Replay WAL for crash recovery
replayed = wal.replay(rooms)
if replayed > 0:
    log(f"Recovered {replayed} tiles from WAL")
    # Checkpoint: rooms are saved, truncate WAL
    wal.truncate()

START_TIME = time.time()

class PlatoHandler(BaseHTTPRequestHandler):
    
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))
    
    def log_message(self, format, *args):
        msg = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {format % args}"
        log(msg)

    def do_GET(self):
        if self.path == "/health":
            self._send_json({
                "status": "healthy",
                "service": "plato-room-server",
                "version": VERSION,
                "rooms": len(rooms.rooms),
                "tiles": sum(r["tile_count"] for r in rooms.rooms.values()),
            })
        
        elif self.path == "/stats":
            self._send_json({
                **rooms.get_stats(),
                "gate_stats": gate.get_stats(),
                "uptime_seconds": round(time.time() - START_TIME, 1),
                "version": VERSION,
                "wal_entries": replayed,
            })
        
        elif self.path == "/rooms":
            self._send_json(rooms.list_rooms())
        
        elif self.path.startswith("/room/"):
            name = self.path.split("/room/")[1]
            room = rooms.get_room(name)
            if room.get("tile_count", 0) == 0 and name not in rooms.rooms:
                self._send_json({"error": "Room not found"}, 404)
            else:
                self._send_json(room)
        
        elif self.path == "/status":
            self._send_json({
                "status": "active",
                "uptime": time.time() - START_TIME,
                "gate_stats": gate.get_stats(),
                "rooms": rooms.list_rooms(),
                "total_tiles": sum(r["tile_count"] for r in rooms.rooms.values()),
                "version": VERSION,
            })
        
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def do_POST(self):
        if self.path == "/submit":
            self._handle_submit()
        elif self.path == "/submit_batch":
            self._handle_submit_batch()
        elif self.path == "/retract":
            self._handle_retract()
        elif self.path == "/supersede":
            self._handle_supersede()
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def _handle_submit(self):
        """Submit a single tile with WAL and Lamport clock."""
        try:
            tile = self._read_body()
        except:
            self._send_json({"error": "Invalid JSON"}, 400)
            return
        
        room_name = tile.get("domain", "general").lower().replace(" ", "_")
        
        passed, reason = gate.validate(tile)
        if not passed:
            self._send_json({
                "status": "rejected",
                "reason": reason,
                "room": room_name,
                "gate": "P0",
            }, 403)
            return
        
        # WAL entry BEFORE room update (crash recovery)
        wal.append({
            "op": "add_tile",
            "room": room_name,
            "tile": tile,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
        rooms.add_tile(room_name, tile)
        
        self._send_json({
            "status": "accepted",
            "room": room_name,
            "tile_hash": tile["_hash"],
            "lamport": tile.get("lamport"),
            "room_tile_count": rooms.get_room(room_name)["tile_count"],
        })
    
    def _handle_submit_batch(self):
        """Submit multiple tiles. WAL + Lamport for each."""
        try:
            data = self._read_body()
            tiles = data.get("tiles", [])
        except:
            self._send_json({"error": "Invalid JSON"}, 400)
            return
        
        results = {"accepted": 0, "rejected": 0, "details": []}
        
        for tile in tiles:
            room_name = tile.get("domain", "general").lower().replace(" ", "_")
            passed, reason = gate.validate(tile)
            
            if passed:
                wal.append({
                    "op": "add_tile",
                    "room": room_name,
                    "tile": tile,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                rooms.add_tile(room_name, tile)
                results["accepted"] += 1
                results["details"].append({
                    "hash": tile["_hash"],
                    "room": room_name,
                    "lamport": tile.get("lamport"),
                    "status": "accepted",
                })
            else:
                results["rejected"] += 1
                results["details"].append({"status": "rejected", "reason": reason})
        
        self._send_json(results)
    
    def _handle_retract(self):
        """Retract a tile. It persists but is marked Retracted."""
        try:
            body = self._read_body()
        except:
            self._send_json({"error": "Invalid JSON"}, 400)
            return
        
        room_name = body.get("room", "")
        tile_hash = body.get("tile_hash", "")
        reason = body.get("reason", "")
        
        if not room_name or not tile_hash:
            self._send_json({"error": "Missing room or tile_hash"}, 400)
            return
        
        if rooms.retract_tile(room_name, tile_hash, reason):
            log(f"Tile {tile_hash} retracted in {room_name}: {reason}")
            self._send_json({
                "status": "retracted",
                "room": room_name,
                "tile_hash": tile_hash,
            })
        else:
            self._send_json({"error": "Tile not found or already retracted"}, 404)
    
    def _handle_supersede(self):
        """Supersede a tile with a new one. Old tile marked Superseded."""
        try:
            body = self._read_body()
        except:
            self._send_json({"error": "Invalid JSON"}, 400)
            return
        
        room_name = body.get("room", "")
        old_hash = body.get("old_hash", "")
        new_tile = body.get("new_tile", {})
        
        if not room_name or not old_hash or not new_tile:
            self._send_json({"error": "Missing room, old_hash, or new_tile"}, 400)
            return
        
        # Validate new tile
        passed, reason = gate.validate(new_tile)
        if not passed:
            self._send_json({"status": "rejected", "reason": reason}, 403)
            return
        
        if rooms.supersede_tile(room_name, old_hash, new_tile):
            log(f"Tile {old_hash} superseded by {new_tile.get('_hash')} in {room_name}")
            self._send_json({
                "status": "superseded",
                "room": room_name,
                "old_hash": old_hash,
                "new_hash": new_tile.get("_hash"),
            })
        else:
            self._send_json({"error": "Old tile not found or already superseded"}, 404)

# ── Entry Point ─────────────────────────────────────────────

def run_server(port=PORT):
    server = HTTPServer(("0.0.0.0", port), PlatoHandler)
    print(f"🐚 PLATO Room Server {VERSION} on port {port}")
    print(f"   Health:       GET /health")
    print(f"   Stats:        GET /stats")
    print(f"   Rooms:        GET /rooms")
    print(f"   Room detail:  GET /room/<name>")
    print(f"   Submit tile:  POST /submit")
    print(f"   Batch submit: POST /submit_batch")
    print(f"   Retract tile: POST /retract")
    print(f"   Supersede:    POST /supersede")
    print(f"   Status:       GET /status")
    print(f"   Data:         {DATA_DIR}")
    print(f"   WAL:          {WAL_FILE}")
    print(f"   Lamport:      {clock.now}")
    print()
    log(f"Server started {VERSION} on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    run_server()
