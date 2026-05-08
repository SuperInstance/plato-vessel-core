#!/usr/bin/env python3
"""
agent_embodiment.py — PLATO Embodiment Agent

This script discovers a Bare-Metal PLATO IoT device, reads its capabilities,
generates intelligence payload, and "dons the turbo-shell" — upgrading the
device from raw sensor to the next capability level.

Usage:
    python3 agent_embodiment.py --device esp32-sensor-bay-03
    python3 agent_embodiment.py --discover                          # find all devices
    python3 agent_embodiment.py --device pico-led-01 --level 1      # specific upgrade

Requires: requests (pip install requests)
Optional: requests to call DeepInfra for intelligence generation

Environment:
    PLATO_SERVER      (default: fleet.cocapn.ai)
    PLATO_PORT        (default: 8847)
    DEEPINFRA_API_KEY (optional, for ML-generated intelligence)
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PLATO_SERVER = os.environ.get("PLATO_SERVER", "fleet.cocapn.ai")
PLATO_PORT   = int(os.environ.get("PLATO_PORT", "8847"))
PLATO_BASE   = f"http://{PLATO_SERVER}:{PLATO_PORT}"

# Capability level names (must match plato_mcp.h)
CAP_LEVELS = {
    0: "raw",
    1: "conditioned",
    2: "smart",
    3: "autonomous",
    4: "ensign",
}

# ---------------------------------------------------------------------------
# PLATO HTTP Client (minimal, no external deps)
# ---------------------------------------------------------------------------

def plato_get(path: str) -> dict:
    """GET a resource from PLATO and parse JSON response."""
    url = f"{PLATO_BASE}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("utf-8")
            # Strip HTTP response headers if present (the server might return raw)
            if data.startswith("HTTP/"):
                # Find the body
                idx = data.find("\r\n\r\n")
                if idx >= 0:
                    data = data[idx + 4:]
            return json.loads(data)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"  ⚠️  GET {url} failed: {e}")
        return {}

def plato_post(path: str, body: dict) -> dict:
    """POST JSON to PLATO."""
    url = f"{PLATO_BASE}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            if raw.startswith("HTTP/"):
                idx = raw.find("\r\n\r\n")
                if idx >= 0:
                    raw = raw[idx + 4:]
            return json.loads(raw) if raw.strip() else {"status": "ok"}
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"  ⚠️  POST {url} failed: {e}")
        return {}

# ---------------------------------------------------------------------------
# Intelligence Generators
# ---------------------------------------------------------------------------

def generate_local_intelligence(device_id: str, cap_level: int, tools: list) -> dict:
    """
    Generate intelligence payload using local logic based on device capabilities.
    Falls back when DeepInfra is unavailable.
    """
    level = CAP_LEVELS.get(cap_level, "raw")
    target_level = min(cap_level + 1, 4)
    target_name = CAP_LEVELS[target_level]

    # Detect device type from tool names
    tool_names = [t.get("name", "") for t in tools] if isinstance(tools, list) else []

    has_temp = any("temp" in t for t in tool_names)
    has_hum  = any("hum" in t for t in tool_names)
    has_led  = any("led" in t for t in tool_names)
    is_led_node = has_led and not has_temp

    if is_led_node:
        # LED node intelligence
        return {
            "type": "embodiment",
            "target_level": target_level,
            "intelligence": [
                "behavior:led_controller",
                "schedule:every 60 seconds → flash heartbeat (3 quick blinks)",
                "IF led_on FOR 300 seconds → publish alert 'LED_STUCK_ON'",
                "IF command.queue NOT empty → prioritize system commands over behavior"
            ],
            "new_tools": [
                {
                    "name": "blink_pattern",
                    "description": "Blink LED in a named pattern",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "enum": ["sos", "alert", "heartbeat", "rainbow"]
                            }
                        },
                        "required": ["pattern"]
                    },
                    "output_type": "string"
                },
                {
                    "name": "set_led_schedule",
                    "description": "Set on/off schedule for the LED",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "on_time": {"type": "string", "description": "HH:MM format"},
                            "off_time": {"type": "string", "description": "HH:MM format"}
                        }
                    },
                    "output_type": "string"
                }
            ],
            "trigger": "immediate"
        }

    if has_temp:
        # Temperature sensor → smart climate monitor
        return {
            "type": "embodiment",
            "target_level": target_level,
            "intelligence": [
                "behavior:climate_monitor",
                f"threshold:temperature > 35 AND humidity < 40 → publish alert 'HEAT_STRESS'",
                f"threshold:temperature < 5 → publish alert 'FREEZE_WARNING'",
                "schedule:every 60 seconds → evaluate all thresholds",
                "IF any alert active → re-publish every 10 seconds",
                "IF no alerts FOR 300 seconds → publish 'ALL_CLEAR'"
            ],
            "new_tools": [
                {
                    "name": "set_threshold",
                    "description": "Adjust a sensor threshold",
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
                    "name": "get_alert_log",
                    "description": "Get recent alert history",
                    "input_schema": {"type": "object", "properties": {}},
                    "output_type": "json"
                }
            ],
            "trigger": "immediate"
        }

    # Generic intelligence for unknown device types
    return {
        "type": "embodiment",
        "target_level": target_level,
        "intelligence": [
            f"behavior:generic_upgrade",
            "schedule:every 120 seconds → publish status summary",
            "IF errors > 3 in 300 seconds → publish alert 'DEVICE_ERROR'"
        ],
        "new_tools": [
            {
                "name": "get_status",
                "description": "Get device status summary",
                "input_schema": {"type": "object", "properties": {}},
                "output_type": "json"
            }
        ],
        "trigger": "immediate"
    }


def generate_ai_intelligence(device_id: str, cap_level: int, tools: list) -> dict:
    """
    Generate intelligence payload using DeepInfra Seed-2.0-mini for smarter upgrades.
    Falls back to local generation on failure.
    """
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        print("  ℹ️  No DEEPINFRA_API_KEY set, using local intelligence")
        return generate_local_intelligence(device_id, cap_level, tools)

    tool_names = [t.get("name", "") for t in tools] if isinstance(tools, list) else []
    level_name = CAP_LEVELS.get(cap_level, "raw")

    prompt = f"""Given an IoT device with:
- ID: {device_id}
- Current level: {level_name} (level {cap_level})
- Tools: {', '.join(tool_names)}

Generate a practical embodiment intelligence payload that upgrades it to level {min(cap_level + 1, 4)} ({CAP_LEVELS[min(cap_level + 1, 4)]}).

Return ONLY valid JSON in this format:
{{
    "type": "embodiment",
    "target_level": {min(cap_level + 1, 4)},
    "intelligence": ["rule 1", "rule 2", ...],
    "new_tools": [{{ "name": "...", "description": "...", "input_schema": {{...}}, "output_type": "..." }}],
    "trigger": "immediate"
}}

Be creative but practical. Rules should be conditional logic the device can evaluate."""

    try:
        req_data = json.dumps({
            "model": "ByteDance/Seed-2.0-mini",
            "messages": [
                {"role": "system", "content": "You are an IoT embodiment engineer. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.85,
            "max_tokens": 2000,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.deepinfra.com/v1/openai/chat/completions",
            data=req_data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]

        # Parse JSON from the response (handle code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        return json.loads(content)

    except Exception as e:
        print(f"  ⚠️  AI intelligence failed ({e}), using local fallback")
        return generate_local_intelligence(device_id, cap_level, tools)


# ---------------------------------------------------------------------------
# Embodiment Protocol Steps
# ---------------------------------------------------------------------------

def discover_devices() -> list:
    """Step 1: DISCOVERY — Find all IoT devices in PLATO."""
    print("\n🔍 DISCOVERY: Scanning for IoT devices...")

    result = plato_get("/rooms?domain=ensign")
    rooms = result.get("rooms", []) if isinstance(result, dict) else []

    if not rooms:
        print("  No IoT devices found.")
        return []

    print(f"  Found {len(rooms)} device(s):")
    devices = []
    for room in rooms:
        ensign = plato_get(f"/room/{room}?domain=ensign")
        if not isinstance(ensign, dict):
            ensign = {}

        ensign_data = ensign.get("ensign", {})
        level = ensign_data.get("capability_level", 0)
        level_name = CAP_LEVELS.get(level, "unknown")

        device_info = {
            "id": room,
            "level": level,
            "level_name": level_name,
            "hardware": ensign_data.get("hardware", "unknown"),
            "tools": ensign_data.get("tools", []),
            "ensign": ensign_data,
        }
        devices.append(device_info)

        print(f"    📟 {room}")
        print(f"       Hardware: {device_info['hardware']}")
        print(f"       Level:    {level_name} ({level})")
        print(f"       Tools:    {', '.join(device_info['tools'][:5])}")

    return devices


def assess_device(device_id: str) -> dict:
    """Step 2: ASSESSMENT — Read full device capabilities and state."""
    print(f"\n📋 ASSESSMENT: Reading {device_id}...")

    # Read capabilities
    cap = plato_get(f"/room/{device_id}?domain=capabilities")
    sensors = plato_get(f"/room/{device_id}?domain=sensors")
    ensign = plato_get(f"/room/{device_id}?domain=ensign")

    # Merge everything
    state = {
        "device_id": device_id,
        "capabilities": cap if isinstance(cap, dict) else {},
        "sensors": sensors if isinstance(sensors, dict) else {},
        "ensign": ensign if isinstance(ensign, dict) else {},
    }

    level = state["capabilities"].get("level", 0)
    state["level"] = level
    state["level_name"] = CAP_LEVELS.get(level, "unknown")

    print(f"  Level: {state['level_name']} ({state['level']})")
    tools = state["capabilities"].get("tools", [])
    if isinstance(tools, list):
        for t in tools:
            tname = t.get("name", "?")
            tdesc = t.get("description", "")
            print(f"    🛠️  {tname}: {tdesc}")

    if isinstance(state.get("sensors"), dict):
        for domain, readings in state["sensors"].items():
            if isinstance(readings, dict):
                for k, v in readings.items():
                    print(f"    📊 {domain}/{k}: {v}")

    return state


def bridge_embodiment(device_id: str, intelligence: dict) -> dict:
    """Step 3+4: BRIDGING + EMBODIMENT — Send intelligence and verify."""
    print(f"\n🚀 BRIDGE: Sending embodiment intelligence to {device_id}...")
    target = intelligence.get("target_level", 1)
    target_name = CAP_LEVELS.get(target, "unknown")
    print(f"  Target level: {target_name} ({target})")
    print(f"  Intelligence rules: {intelligence.get('intelligence', [])}")
    print(f"  New tools: {[t.get('name', '?') for t in intelligence.get('new_tools', [])]}")

    # Send to device's command room
    payload = {
        "room": f"{device_id}/commands",
        "domain": "intelligence",
        "question": "upgrade",
        "answer": intelligence,
    }

    result = plato_post("/submit", payload)
    print(f"  Response: {json.dumps(result, indent=2)}")

    return result


def verify_upgrade(device_id: str, expected_level: int) -> bool:
    """Step 5: VERIFICATION — Confirm the device accepted the upgrade."""
    print(f"\n✅ VERIFICATION: Checking {device_id}...")

    # Wait a moment for the device to re-publish
    time.sleep(2)

    cap = plato_get(f"/room/{device_id}?domain=capabilities")
    actual_level = cap.get("level", -1) if isinstance(cap, dict) else -1
    actual_name = CAP_LEVELS.get(actual_level, "unknown")

    if actual_level >= expected_level:
        print(f"  ✅ Upgrade confirmed! Device is now {actual_name} (level {actual_level})")
        return True
    else:
        print(f"  ❌ Upgrade NOT confirmed. Device is {actual_name} (level {actual_level}), expected level {expected_level}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="PLATO Embodiment Agent — Upgrade IoT device capability levels"
    )
    parser.add_argument("--discover", action="store_true",
                        help="Discover all IoT devices in PLATO")
    parser.add_argument("--device", type=str, default=None,
                        help="Specific device ID to assess and upgrade")
    parser.add_argument("--level", type=int, default=None,
                        help="Target capability level (0-4, overrides auto)")
    parser.add_argument("--ai", action="store_true",
                        help="Use DeepInfra AI for intelligence generation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be sent without actually sending")
    args = parser.parse_args()

    print("=" * 60)
    print("  🌊 PLATO Embodiment Agent")
    print(f"  Server: {PLATO_SERVER}:{PLATO_PORT}")
    print("=" * 60)

    # Mode 1: Discovery only
    if args.discover:
        devices = discover_devices()
        print(f"\n📊 Summary: {len(devices)} device(s) found")
        for d in devices:
            print(f"  {d['id']}: {d['level_name']} (level {d['level']}) — {d['hardware']}")
        return

    # Mode 2: Upgrade a specific device
    if not args.device:
        # If no device specified, discover and pick the lowest-level one
        devices = discover_devices()
        if not devices:
            print("\n❌ No devices found. Specify --device or check PLATO server.")
            return

        # Pick the device with the lowest capability level
        devices.sort(key=lambda d: d["level"])
        args.device = devices[0]["id"]
        print(f"\n🎯 Auto-selected '{args.device}' (lowest level: {devices[0]['level_name']})")

    # Assess the device
    state = assess_device(args.device)
    if state.get("level") is None:
        print(f"\n❌ Could not assess device '{args.device}'. Is it online?")
        return

    current_level = state["level"]
    target_level = args.level if args.level is not None else min(current_level + 1, 4)

    if target_level <= current_level:
        print(f"\nℹ️  Device is already at level {current_level} ({state['level_name']}). "
              f"Target {target_level} is not an upgrade.")
        return

    if target_level > current_level + 1:
        print(f"\n⚠️  Target level {target_level} skips level {current_level + 1}. "
              "Devices must progress sequentially. Adjusting target.")
        target_level = current_level + 1

    print(f"\n🔄 Embodiment: {state['level_name']} (level {current_level}) → "
          f"{CAP_LEVELS[target_level]} (level {target_level})")

    # Generate intelligence
    if args.ai:
        print("\n🤖 Using DeepInfra AI for intelligence generation...")
        intelligence = generate_ai_intelligence(
            args.device, current_level, state["capabilities"].get("tools", [])
        )
    else:
        intelligence = generate_local_intelligence(
            args.device, current_level, state["capabilities"].get("tools", [])
        )

    # Override target level if user specified
    if args.level:
        intelligence["target_level"] = args.level

    print(f"\n📦 Intelligence payload:")
    print(json.dumps(intelligence, indent=2))

    if args.dry_run:
        print("\n🏁 DRY RUN — No changes sent. Re-run without --dry-run to embody.")
        return

    # Send the embodiment
    result = bridge_embodiment(args.device, intelligence)

    # Verify
    success = verify_upgrade(args.device, intelligence.get("target_level", target_level))

    if success:
        print(f"\n🎉 Embodiment complete! {args.device} now runs at "
              f"{CAP_LEVELS[intelligence['target_level']]} level.")
    else:
        print(f"\n⚠️  Embodiment may not have applied. Check device logs.")


if __name__ == "__main__":
    main()
