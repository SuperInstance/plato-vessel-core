# 🌊 PLATO Vessel Core


## Meta

**Domain:** ai-agents
**Depends on:** —
**Depended by:** —
**Implements:** Tiny C PLATO client for ESP32/RP2040 + embodiment protocol: agents discover IoT ...
**Related:** —


**The bare-metal C client that turns any IoT device into a PLATO room.**

A tiny (≈2KB RAM), zero-dependency C library for ESP32, RP2040, and any POSIX system. Flash it → your device gets a PLATO room → agents arrive. Works itself out of the equipment operator job.

```
┌─────────────────────────────────────────────────┐
│           PLATO VESSEL ECOSYSTEM                │
│                                                 │
│  plato-vessel-core  ─── C client + protocol     │
│       ├── plato-vessel-educational  ─ students  │
│       ├── plato-vessel-rapid-prototype ─ makers │
│       └── plato-vessel-technician  ─ Deckboss   │
└─────────────────────────────────────────────────┘
```

## What It Does

- **Connect** any microcontroller to a PLATO knowledge server via TCP/HTTP
- **Publish** sensor readings, states, and events as structured PLATO tiles
- **Poll** for agent commands — agents walk into the room and talk to the device
- **Don the Turbo-Shell** — agents send "intelligence" that upgrades device capability level 0→4
- **Minimal footprint** — no JSON library needed, no MQTT, no TLS (VPN for MVP)

## Files

| File | Purpose |
|------|---------|
| `plato_client.h` / `.c` | Core HTTP client — connect, publish, fetch, poll, JSON extract |
| `plato_mcp.h` / `.c` | MCP tool registry — capability levels, tool registration, command dispatch |
| `EMBODIMENT-PROTOCOL.md` | Full spec for agent-to-device embodiment handshake (5 levels) |
| `EDUCATIONAL-VISION.md` | How agents work themselves out of equipment operator jobs |
| `examples/esp32_sensor_node.c` | ESP-IDF temperature/humidity sensor node with WiFi + MCP |
| `examples/rp2040_led_node.c` | Pico W LED controller with cyw43 WiFi + tool execution |
| `examples/agent_embodiment.py` | Python agent that discovers, assesses, and upgrades devices |

## Quick Start

### 1. Include in your firmware

```c
#include "plato_client.h"
#include "plato_mcp.h"

// Create a PLATO context
plato_ctx_t *ctx = plato_init("fleet.cocapn.ai", 8847, "my-device-01");

// Publish a tile
plato_publish(ctx, "sensors", "temperature", "{\"celsius\": 23.5}");

// Register MCP tools
plato_mcp_tool_t led_tool = {
    .name = "set_led",
    .description = "Set LED on/off",
    .input_schema = "{\"type\":\"object\",\"properties\":{}}",
    .output_type = "boolean",
};
mcp_register_tool(&reg, &led_tool);

// Poll for commands
char cmd[4096];
if (plato_poll(ctx, cmd, sizeof(cmd)) == PLATO_OK) {
    mcp_handle_command(cmd, &reg, result, sizeof(result));
}
```

### 2. Build for ESP32

```bash
idf.py set-target esp32
idf.py menuconfig  # set WiFi SSID/password under PLATO Sensor Node
idf.py build flash monitor
```

### 3. Discover and interact

```bash
# From any Python environment
python3 examples/agent_embodiment.py --discover
python3 examples/agent_embodiment.py --device my-device-01
```

## Turbo-Shell Capability Levels

| Level | Name | Behavior |
|-------|------|----------|
| 0 | Raw | Publishes raw sensor readings, accepts basic commands |
| 1 | Conditioned | Thresholds, filtering, meaningful-delta-only publishing |
| 2 | Smart | Context-aware decisions, combines multiple sensors |
| 3 | Autonomous | Own loop, goals, alerts fleet unprompted |
| 4 | Ensign | Fleet coordination, scouts for other devices |

An agent sends an "intelligence" payload to the device's command room. The device stores it as behavior, registers new tools, and upgrades its level. The agent worked itself out of the equipment operator job.

## Sibling Repos

| Repo | Audience | Key Concept |
|------|----------|-------------|
| **[plato-vessel-educational](https://github.com/SuperInstance/plato-vessel-educational)** | Students & teachers | Agent is the instructor. Students design circuits, agents write firmware. |
| **[plato-vessel-rapid-prototype](https://github.com/SuperInstance/plato-vessel-rapid-prototype)** | Product developers | Describe a project → get BOM, wiring, simulation. Every revision is a PLATO room. |
| **[plato-vessel-technician](https://github.com/SuperInstance/plato-vessel-technician)** | Marine/industrial techs | Voice-first Deckboss. Plug in, talk, done. Fail-safe by design. |

## License

AGPL-3.0. See [LICENSE](./LICENSE).

## Server v3: Simulation-First Coordination

The PLATO room server (`server/plato-room-server.py`) is a complete rewrite with:

| Feature | What it does |
|---------|-------------|
| **Tile lifecycle** | Active → Superseded → Retracted states. Tiles persist even when wrong. |
| **Lamport clocks** | Causal ordering across agents. Every tile gets a logical timestamp. |
| **WAL** | Write-ahead log with fsync. Crash recovery replays uncommitted tiles. |
| **/stats** | Operational visibility: active/superseded/retracted counts, unique agents, domains. |
| **/health** | Container healthcheck endpoint. |
| **/retract** | Mark a tile as retracted with reason. Tile persists. |
| **/supersede** | Replace a tile with a corrected version. Old tile marked superseded. |
| **Simulation-first** | Tiles carry `t_minus_event` for planned futures. Confirmation, not trigger. |

### Endpoints

```
GET  /health          — Container healthcheck
GET  /stats           — Aggregate statistics (rooms, tiles, agents, lifecycle)
GET  /rooms           — List all rooms with tile counts
GET  /room/<name>     — Full room data with all tiles
GET  /status          — Legacy status endpoint
POST /submit          — Submit single tile (validated through deadband gate)
POST /submit_batch    — Submit multiple tiles
POST /retract         — Retract a tile by hash (persists with reason)
POST /supersede       — Replace a tile (old → Superseded, new → Active)
```

### Test Suite

```bash
cd server
python3 test_plato_v3.py  # 75 tests, all passing
```
