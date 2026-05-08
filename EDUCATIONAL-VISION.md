# Bare-Metal PLATO: The Educational Vision

## The Self-Defeating Agent

The most important agent in the fleet is the one that works itself out of a job.

### The Problem
Controlling an IoT device today means learning C, ESP-IDF, MCP protocols, PLATO APIs, and the specific quirks of your hardware. That's months of ramp-up for a teacher who just wants 30 temperature sensors, or a farmer who wants a smart irrigation controller, or a maker who has an idea but no embedded experience.

### The Solution
The agent system acts as equipment operator and mechanic. The human lives at the application level:

```
Human: "I want a sensor that waters plants when the soil is dry"
                          ↓
Agent reads the device room. Discovers: moisture sensor, relay, WiFi.
Agent writes the firmware: if moisture < threshold → activate relay.
Agent tests in simulation. Agent deploys. Agent documents.
                          ↓
Human: sees a tile that says "watering: ON, moisture: 12%"
                          ↓
A smaller model now runs the routine. The first agent moves on.
```

### The Bootstrapping Loop

1. **Large model arrives** — expensive, smart, reads the device room
2. **Learns the device's MO** — what sensors, what actuators, what protocols
3. **Writes the behavior** — tests in simulation, deploys to real hardware
4. **Documents everything** — "This device does X. Here's how to control it."
5. **Smaller model takes over** — the workflow is now stable and predictable
6. **Large model moves to the next** — another device, another frontier

Each iteration makes the system cheaper to run. The expensive model trains the workflow; the cheap model runs it.

### The Two User Groups

**Technical Developers**
- See the IoT device as a MUD room — walk in, chat with NPCs, learn the customs
- PLATO room = device interface, completely discoverable
- MCP = natural conversation protocol
- Zero documentation required — the device describes itself

**Educators & Makers ("Vibe Coders")**
- Describe what they want in natural language
- The agent handles everything below the application layer
- "I want a greenhouse controller that waters when dry" → done
- No C, no ESP-IDF, no MCP — just describe and the agent operates the equipment

### The Dojo for Hardware

Every IoT device is a training ground:
- Every interaction generates PLATO tiles
- Tiles train custom models for device control
- Simulation environments let agents practice before touching real hardware
- LoRAs trained on PLATO interaction patterns transfer across environments
- "Non-model improving perception" — agents learn to read telemetry better without changing the underlying model

### The Pipe Dream

A classroom of 30 ESP32s. The teacher describes what they want. The agent system:
1. Discovers all 30 devices via PLATO
2. Reads each device's capability tiles
3. Writes identical firmware for all of them
4. Flashes each one via the bootloader
5. Creates a classroom PLATO room with all 30 devices
6. The teacher sees 30 tiles updating in real-time

The agent worked itself out of the equipment operator job in one session.
The students focus on application. The hardware just works.
