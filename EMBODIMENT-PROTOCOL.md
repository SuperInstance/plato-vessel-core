# Bare-Metal PLATO Embodiment Protocol

> **Version:** 1.0  
> **Status:** Draft for implementation  
> **Scope:** How an AI agent "dons the turbo-shell" of an IoT device, upgrading it from raw sensor to autonomous fleet participant.

---

## 1. Overview

The Embodiment Protocol defines a 5-step handshake between an agent and a Bare-Metal PLATO IoT device. Each successful cycle upgrades the device's capability level (the "turbo-shell"), giving it more autonomy and intelligence.

```
Agent                     PLATO Server                    IoT Device
  │                            │                              │
  │──── DISCOVER ────────────>│                              │
  │<─── room listing ──────── │                              │
  │                            │                              │
  │──── ASSESS (read tiles) ->│                              │
  │<─── capability tiles ──── │                              │
  │                            │                              │
  │──── BRIDGE (send intel) ->│──── intelligence ──────────>│
  │                            │                              │
  │                            │<── embodiment confirm ──────│
  │<─── upgraded level ────── │                              │
  │                            │                              │
  │       [Device now runs at next turbo-shell level]        │
```

### 1.1 Key Concepts

| Concept | Description |
|---------|-------------|
| **Room** | A named namespace in PLATO. Each device is a room. |
| **Tile** | A (domain, question, answer) triple. A room holds many tiles. |
| **Ensign** | The device's presence announcement — a special tile. |
| **Turbo-Shell** | The device's capability level. 5 levels from raw to ensign. |
| **Intelligence** | A code/spec sent by an agent that becomes the device's new behavior. |

---

## 2. Turbo-Shell Capability Levels

| Level | Name | Behavior |
|-------|------|----------|
| 0 | **Raw** | Publishes raw sensor readings, accepts basic commands |
| 1 | **Conditioned** | Applies thresholds, filters noise, publishes only meaningful deltas |
| 2 | **Smart** | Context-aware decisions, combines multiple sensors, local state machine |
| 3 | **Autonomous** | Runs its own loop, sets goals, alerts fleet without being polled |
| 4 | **Ensign** | Fleet-level coordination, scouts for other devices, publishes discovery intel |

### 2.1 Level Progression Rules

- A device **must** pass through every level sequentially (no skipping)
- An agent **may** jump a device multiple levels with a single intelligence payload that includes all intermediate behaviors
- A device **may** be downgraded by explicit agent command or watchdog timeout
- Each level adds ~2KB of behavior storage on the device

---

## 3. Message Formats

### 3.1 Ensign Interface (Device Presence)

When a device boots and connects to PLATO, it publishes an **ensign tile**:

```json
{
  "room": "pico-led-node-01",
  "domain": "ensign",
  "question": "presence",
  "answer": {
    "type": "iot_device",
    "hardware": "rp2040",
    "capability_level": 0,
    "capability_name": "raw",
    "ip": "192.168.1.42",
    "mac": "E6:12:34:56:78:9A",
    "protocol": "plato-bare-metal-v1",
    "tools": [
      {"name": "get_led", "description": "Read LED state"},
      {"name": "set_led", "description": "Set LED on/off"}
    ],
    "ttl": 300
  }
}
```

**Fields:**
- `room` — device identifier (must match PLATO room name)
- `type` — always `"iot_device"`
- `hardware` — `"esp32"`, `"rp2040"`, etc.
- `capability_level` — current turbo-shell level (0-4)
- `tools` — array of available MCP tool names
- `ttl` — seconds before the ensign expires; device must re-publish

### 3.2 Capability Tile (Device Self-Description)

Published to `domain: "capabilities"`, `question: "tools"`:

```json
{
  "level": 0,
  "level_name": "raw",
  "tools": [
    {
      "name": "get_led",
      "description": "Read the current onboard LED state (true=on, false=off)",
      "input_schema": {"type": "object", "properties": {}},
      "output_type": "boolean"
    },
    {
      "name": "set_led",
      "description": "Set the onboard LED on or off",
      "input_schema": {
        "type": "object",
        "properties": {
          "state": {"type": "boolean", "description": "true=on, false=off"}
        },
        "required": ["state"]
      },
      "output_type": "boolean"
    }
  ],
  "memory": {"free_heap": 48600, "flash_used": 124000},
  "compute": "1-core@133MHz"
}
```

### 3.3 Discovery Query (Agent → PLATO)

Agent discovers IoT devices by querying PLATO's room list:

```json
// GET /rooms?domain=ensign
// Response:
{
  "rooms": [
    "pico-led-node-01",
    "esp32-sensor-bay-03",
    "esp32-valve-controller-07"
  ]
}
```

Then the agent fetches each device's ensign tile:

```json
// GET /room/pico-led-node-01?domain=ensign
// Response:
{
  "room": "pico-led-node-01",
  "ensign": {
    "type": "iot_device",
    "hardware": "rp2040",
    "capability_level": 0,
    "capability_name": "raw",
    "tools": ["get_led", "set_led", "blink"]
  }
}
```

### 3.4 Assessment (Agent Reads Device State)

Agent fetches all tiles from the device's room:

```json
// GET /room/pico-led-node-01
// Response:
{
  "sensors": {
    "led_state": {"led": false, "level": "raw"}
  },
  "capabilities": {
    "tools": {"level": 0, "level_name": "raw", "tools": [...]}
  },
  "ensign": {
    "presence": {"type": "iot_device", "hardware": "rp2040", ...}
  }
}
```

### 3.5 Bridging (Agent Sends Intelligence)

Agent posts an **intelligence payload** to the device's command room:

```json
POST /submit
{
  "room": "pico-led-node-01/commands",
  "domain": "intelligence",
  "question": "upgrade",
  "answer": {
    "type": "embodiment",
    "target_level": 1,
    "intelligence": [
      "IF led_state == true FOR 60 seconds THEN blink 3 times",
      "IF led_state unchanged FOR 300 seconds THEN publish alert tile"
    ],
    "new_tools": [
      {
        "name": "blink_pattern",
        "description": "Blink LED in a pattern",
        "input_schema": {
          "type": "object",
          "properties": {
            "pattern": {"type": "string", "enum": ["sos", "alert", "heartbeat"]}
          }
        }
      }
    ],
    "trigger": "immediate"
  }
}
```

**Intelligence payload fields:**
- `type` — always `"embodiment"`
- `target_level` — intended turbo-shell level after upgrade
- `intelligence` — array of behavior rules (code/spec strings)
- `new_tools` — new MCP tools the device should register
- `trigger` — `"immediate"` or `"on_boot"`

### 3.6 Embodiment Confirmation (Device → Agent)

After processing the intelligence, the device responds:

```json
{
  "status": "upgraded",
  "new_level": "conditioned",
  "new_level_index": 1,
  "tools_registered": ["blink_pattern"],
  "behaviors_loaded": 2,
  "free_heap": 46200
}
```

**Error responses:**

```json
{
  "status": "error",
  "code": "LEVEL_SKIP",
  "message": "Cannot jump from level 0 to level 3. Target level must be 1."
}

{
  "status": "error",
  "code": "MEMORY",
  "message": "Insufficient heap for intelligence payload (need 4096, have 2048)"
}

{
  "status": "error",
  "code": "UNKNOWN_TOOL",
  "message": "Tool 'set_valve' is not compatible with this hardware"
}
```

---

## 4. MCP Tool Definitions for IoT Devices

### 4.1 Built-in Tools (All Devices)

Every Bare-Metal PLATO device must support these tools:

| Tool | Description | Level Required |
|------|-------------|----------------|
| `ping` | Returns device status and uptime | 0 |
| `get_capabilities` | Returns full capability tile | 0 |
| `reset` | Soft-reset the device | 1 |
| `set_poll_interval_ms` | Change how often the device polls for commands | 1 |
| `get_behavior` | Return current intelligence/behavior code | 1 |
| `forget_behavior` | Reset to factory default behavior | 2 |
| `debug_mode` | Enable verbose logging for N seconds | 2 |
| `fleet_broadcast` | Publish a message to all fleet devices | 3 |
| `scout` | Scan for nearby devices and report | 4 |

### 4.2 Tool Registration Protocol

Devices register tools via the MCP registry:

```c
plato_mcp_tool_t temp_tool = {
    .name         = "read_temperature",
    .description  = "Read ambient temperature in degrees Celsius",
    .input_schema = "{\"type\":\"object\",\"properties\":{}}",
    .output_type  = "number",
};
mcp_register_tool(&reg, &temp_tool);
```

When intelligence upgrades add new tools, the device:

1. Parses `"new_tools"` from the intelligence payload
2. Validates each tool against hardware capabilities
3. Registers them in the MCP registry
4. Rebuilds and publishes the capability tile

---

## 5. The Ensign Interface (Detailed)

The ensign is a device's first message to the fleet — its "I am here" announcement.

### 5.1 Ensign Protocol

```
1. Device boots → WiFi connect
2. Device calls plato_init(server, port, device_id)
3. Device publishes ensign tile to domain="ensign", question="presence"
4. PLATO server indexes the room as an IoT device
5. Agent queries /rooms?domain=ensign to find all devices
6. Device re-publishes ensign every TTL seconds (default: 300)
```

### 5.2 Ensign Discovery Flow

```
Agent:
  GET /rooms?domain=ensign
  → ["esp32-bay-03", "pico-led-01", "esp32-valve-07"]

Agent:
  GET /room/esp32-bay-03?domain=ensign
  → {type: "iot_device", hardware: "esp32", capability_level: 2, tools: [...]}
  GET /room/pico-led-01?domain=ensign
  → {type: "iot_device", hardware: "rp2040", capability_level: 0, tools: [...]}

Agent (decides to upgrade pico-led-01 from level 0 to level 1):
  → Reads full capability tile
  → Generates intelligence payload
  → Posts to pico-led-01/commands
  → Device confirms upgrade
  → Device re-publishes ensign at level 1
```

### 5.3 Ensign Fields Reference

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | Always `"iot_device"` |
| `hardware` | Yes | `"esp32"`, `"rp2040"`, `"esp32s3"`, etc. |
| `capability_level` | Yes | Integer 0-4 |
| `capability_name` | Yes | String: `"raw"`, `"conditioned"`, etc. |
| `ip` | No | Current IP address |
| `mac` | No | MAC address |
| `protocol` | Yes | `"plato-bare-metal-v1"` |
| `tools` | Yes | Array of tool name strings (not full defs — that's in capabilities) |
| `ttl` | Yes | Seconds until this ensign expires |
| `firmware_version` | No | Git hash or semver |
| `uptime_seconds` | No | Seconds since boot |

---

## 6. Embodiment Worked Example

### Scenario: Temperature Sensor → Smart Irrigation Controller

**Initial State:**
- Device: `esp32-sensor-bay-03`
- Level 0 (Raw)
- Publishes temperature and humidity every 30 seconds
- Tools: `read_temperature`, `read_humidity`

#### Step 1: Discovery

```python
# Agent queries PLATO for IoT devices
rooms = plato_fetch("/rooms?domain=ensign")
# → ["esp32-sensor-bay-03", "pico-led-01", ...]

# Agent fetches esp32-sensor-bay-03's ensign
ensign = plato_fetch("/room/esp32-sensor-bay-03?domain=ensign")
# → {type: "iot_device", hardware: "esp32", capability_level: 0, ...}
```

#### Step 2: Assessment

```python
# Agent reads full capability tile
cap = plato_fetch("/room/esp32-sensor-bay-03?domain=capabilities")
# → {level: 0, tools: [{name: "read_temperature"}, {name: "read_humidity"}]}

# Agent reads current sensor values
sensors = plato_fetch("/room/esp32-sensor-bay-03?domain=sensors")
# → {temperature: {celsius: 28.3}, humidity: {percent: 62}}
```

#### Step 3: Bridging (Send Intelligence)

The agent generates an intelligence payload that turns the raw sensor into an irrigation controller:

```json
{
  "room": "esp32-sensor-bay-03/commands",
  "domain": "intelligence",
  "question": "upgrade",
  "answer": {
    "type": "embodiment",
    "target_level": 2,
    "intelligence": [
      "behavior:irrigation_controller",
      "threshold:soil_moisture < 30 → publish alert 'DRY'",
      "threshold:temperature > 35 AND humidity < 40 → publish alert 'HEAT_STRESS'",
      "schedule:every 60 seconds → check all thresholds",
      "schedule:if any alert active → re-publish every 10 seconds"
    ],
    "new_tools": [
      {
        "name": "set_threshold",
        "description": "Adjust a sensor threshold value",
        "input_schema": {
          "type": "object",
          "properties": {
            "sensor": {"type": "string"},
            "min": {"type": "number"},
            "max": {"type": "number"}
          },
          "required": ["sensor", "min", "max"]
        },
        "output_type": "string"
      },
      {
        "name": "get_alert_history",
        "description": "Get recent alert history",
        "input_schema": {"type": "object", "properties": {}},
        "output_type": "json"
      }
    ],
    "trigger": "immediate"
  }
}
```

#### Step 4: Embodiment

The device receives the intelligence and:

1. Stores the behavior rules in its behavior buffer
2. Registers `set_threshold` and `get_alert_history` tools
3. Advances capability level from 0 to 2 (Raw → Smart)
4. Publishes confirmation

```json
{
  "status": "upgraded",
  "new_level": "smart",
  "new_level_index": 2,
  "tools_registered": ["set_threshold", "get_alert_history"],
  "behaviors_loaded": 4
}
```

#### Step 5: Turbo-Shell Upgraded

The device now operates at level 2:

```json
// Ensign re-published:
{
  "room": "esp32-sensor-bay-03",
  "ensign": {
    "type": "iot_device",
    "hardware": "esp32",
    "capability_level": 2,
    "capability_name": "smart",
    "tools": ["read_temperature", "read_humidity", "set_threshold", "get_alert_history"]
  }
}

// New tiles being published:
{
  "room": "esp32-sensor-bay-03",
  "domain": "alerts",
  "question": "irrigation",
  "answer": {"status": "OK", "moisture": 45, "next_check_s": 60}
}
```

---

## 7. Error Handling

### 7.1 Edge Cases

| Scenario | Behavior |
|----------|----------|
| Device disconnects mid-embodiment | Agent retries. Device re-publishes ensign on boot with previous level. |
| Intelligence too large for device RAM | Device rejects with `MEMORY` error. Agent chunks intelligence. |
| Agent sends duplicate upgrade | Device idempotently applies. Same intelligence = same level, no change. |
| Device at level 4, agent tries to go higher | Device rejects with `MAX_LEVEL` error. |
| Malformed JSON | Device returns `PARSE_ERROR`. Agent should validate before sending. |
| Network partition during bridge | Timeout after 30s. Agent retries. Device re-publishes on reconnect. |
| Multiple agents attempt embodiment simultaneously | Last write wins. First agent's intelligence is overwritten. |

### 7.2 Retry Policy

- Agent retries: 3 attempts with exponential backoff (2s, 4s, 8s)
- Device retry: re-publishes ensign every TTL seconds (default 300s)
- If device hasn't heard from its agent in 3× TTL, it may downgrade one level

### 7.3 State Persistence

- Level and behavior should persist across reboots (stored in NVS for ESP32, flash for RP2040)
- If NVS/flash write fails, device boots at level 0 (safe fallback)
- Device logs previous level to NVS before applying upgrade

---

## 8. Security Considerations (MVP)

For the MVP (no TLS):
- Devices operate on a trusted local network
- PLATO server should be firewalled from the internet
- Device ID is its own authentication (changeable via secure configuration)

Post-MVP additions:
- Device-specific API tokens
- Intelligence payload signing
- TLS 1.3 for all PLATO communication
- Agent-to-device mutual authentication

---

## 9. Implementation Checklist

- [ ] Device boots and connects to WiFi
- [ ] Device publishes ensign tile to PLATO
- [ ] Device registers built-in tools (ping, get_capabilities)
- [ ] Agent discovers device via /rooms?domain=ensign
- [ ] Agent reads capability tiles
- [ ] Agent posts intelligence to device command room
- [ ] Device receives intelligence and upgrades level
- [ ] Device registers new tools from intelligence payload
- [ ] Device re-publishes capability tile at new level
- [ ] Agent verifies upgrade was applied
- [ ] Device persists level across reboot
- [ ] Error handling for all edge cases above
