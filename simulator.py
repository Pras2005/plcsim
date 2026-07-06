#!/usr/bin/env python3
"""
PLC Multi-Machine Simulator
Flask + Flask-SocketIO application that simulates multiple PLC machines.
"""

import json
import math
import os
import random
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "plc": {
        "enabled": False,
        "ip": "192.168.1.5",
        "port": 502,
        "device_id": 1,
    },
    "simulator": {
        "machine_count": 1,
        "update_interval": 1.0,
        "web_port": 8080,
        "register_block_size": 10,
    },
    "tags": [
        {
            "name": "status",
            "label": "Status",
            "type": "bitfield",
            "register_offset": 0,
            "bits": {
                "power": 0,
                "auto": 1,
                "running": 2,
                "estop": 3,
                "alarm": 4,
                "door_open": 5,
            },
        },
        {
            "name": "speed",
            "label": "Speed",
            "type": "analog",
            "register_offset": 1,
            "unit": "RPM",
            "min": 0,
            "max": 100,
            "warn_high": 85,
            "alarm_high": 95,
        },
        {
            "name": "temperature",
            "label": "Temperature",
            "type": "analog",
            "register_offset": 2,
            "unit": "°C",
            "min": 0,
            "max": 100,
            "warn_high": 55,
            "alarm_high": 70,
        },
        {
            "name": "vibration",
            "label": "Vibration",
            "type": "analog",
            "register_offset": 3,
            "unit": "mm/s",
            "min": 0,
            "max": 50,
            "warn_high": 30,
            "alarm_high": 40,
        },
        {
            "name": "load",
            "label": "Load",
            "type": "analog",
            "register_offset": 4,
            "unit": "%",
            "min": 0,
            "max": 100,
            "warn_high": 85,
            "alarm_high": 95,
        },
        {
            "name": "cycle_count",
            "label": "Cycle Count",
            "type": "counter",
            "register_offset": 5,
            "unit": "cycles",
        },
    ],
}


def load_config() -> dict:
    """Load configuration from config.json, falling back to defaults."""
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        # Ensure required keys exist by merging with defaults
        for key in DEFAULT_CONFIG:
            if key not in cfg:
                cfg[key] = DEFAULT_CONFIG[key]
        return cfg
    except FileNotFoundError:
        print(f"[WARN] Config file not found at {CONFIG_PATH}, using defaults.")
        return dict(DEFAULT_CONFIG)
    except json.JSONDecodeError as exc:
        print(f"[WARN] Config file invalid JSON ({exc}), using defaults.")
        return dict(DEFAULT_CONFIG)


# Runtime config – mutable dict shared across threads
config: dict = load_config()
config_lock = threading.Lock()


def save_config(cfg: dict):
    """Save configuration to config.json on disk."""
    try:
        with config_lock:
            data_to_save = json.loads(json.dumps(cfg))
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2)
        print(f"[INFO] Configuration saved to {CONFIG_PATH}")
    except Exception as exc:
        print(f"[WARN] Failed to save config to disk: {exc}")

# ---------------------------------------------------------------------------
# Machine simulation
# ---------------------------------------------------------------------------


class Machine:
    """Independently simulates a single PLC machine."""

    def __init__(self, machine_id: int):
        self.machine_id = machine_id
        self.name = f"Machine {machine_id + 1}"
        # Offset cycle start so machines don't run in sync
        self.cycle = machine_id * 7
        self.cycle_count = 0
        self.override_state = "auto"

    def tick(self) -> dict:
        """Advance one simulation cycle and return tag values."""
        # --- status bitfield ---
        power = 1
        auto = 1
        
        if self.override_state == "active":
            cycle_running = 1
            estop = 0
            alarm = 0
        elif self.override_state == "stopped":
            cycle_running = 0
            estop = 1
            alarm = 0
        elif self.override_state == "idle":
            cycle_running = 0
            estop = 0
            alarm = 0
        else: # auto
            cycle_running = 1 if (self.cycle % 30) < 20 else 0
            estop = 0
            alarm = 1 if random.randint(1, 100) <= 3 else 0
            
        door = 0

        status_raw = (
            (power << 0)
            | (auto << 1)
            | (cycle_running << 2)
            | (estop << 3)
            | (alarm << 4)
            | (door << 5)
        )

        # --- analog values ---
        if cycle_running:
            speed = 70 + int(10 * math.sin(self.cycle / 5))
            temperature = 45 + random.randint(-2, 2)
            vibration = 20 + random.randint(-3, 3)
            load = 75 + random.randint(-5, 5)
            if self.cycle % 30 == 0:
                self.cycle_count += 1
        else:
            speed = 0
            temperature = 35 + random.randint(-1, 1)
            vibration = 2 + random.randint(-1, 1)
            load = 10 + random.randint(-1, 1)  # ~10% standby load when machine is powered but idle

        tags = {
            "status": {
                "raw": status_raw,
                "power": bool(power),
                "auto": bool(auto),
                "running": bool(cycle_running),
                "estop": bool(estop),
                "alarm": bool(alarm),
                "door_open": bool(door),
            },
            "speed": speed,
            "temperature": temperature,
            "vibration": vibration,
            "load": load,
            "cycle_count": self.cycle_count,
        }

        current_cycle = self.cycle
        self.cycle += 1

        return {
            "id": self.machine_id,
            "name": self.name,
            "tags": tags,
            "cycle": current_cycle,
            "override_state": self.override_state,
        }

    def register_values(self) -> list[int]:
        """Return the last tick's register-compatible integer values."""
        # Re-derive from current state (after tick was called)
        t = self.tags_snapshot if hasattr(self, "tags_snapshot") else {}
        status_raw = t.get("status", {}).get("raw", 0) if isinstance(t.get("status"), dict) else 0
        return [
            status_raw,
            t.get("speed", 0),
            t.get("temperature", 0),
            t.get("vibration", 0),
            t.get("load", 0),
            t.get("cycle_count", 0),
        ]


# Machine pool
machines: list[Machine] = []
machines_lock = threading.Lock()


def sync_machines(target_count: int):
    """Create or remove Machine instances to match target_count."""
    with machines_lock:
        current = len(machines)
        if target_count > current:
            for i in range(current, target_count):
                machines.append(Machine(i))
        elif target_count < current:
            del machines[target_count:]


# ---------------------------------------------------------------------------
# Modbus client helpers
# ---------------------------------------------------------------------------

modbus_client = None
modbus_lock = threading.Lock()


def get_modbus_client():
    """Lazily create / return a Modbus TCP client if PLC is enabled."""
    global modbus_client
    with modbus_lock:
        plc_cfg = config.get("plc", {})
        if not plc_cfg.get("enabled", False):
            # Close existing client if PLC was just disabled
            if modbus_client is not None:
                try:
                    modbus_client.close()
                except Exception:
                    pass
                modbus_client = None
            return None

        if modbus_client is None:
            try:
                from pymodbus.client import ModbusTcpClient

                modbus_client = ModbusTcpClient(
                    plc_cfg.get("ip", "192.168.1.5"),
                    port=plc_cfg.get("port", 502),
                )
                if not modbus_client.connect():
                    print("[WARN] Could not connect to PLC – continuing simulation only.")
                    modbus_client = None
                else:
                    print(f"[INFO] Connected to PLC at {plc_cfg['ip']}:{plc_cfg['port']}")
            except ImportError:
                print("[WARN] pymodbus not installed – Modbus disabled.")
                modbus_client = None
            except Exception as exc:
                print(f"[WARN] Modbus connection failed ({exc}) – continuing simulation only.")
                modbus_client = None
        return modbus_client


def write_holding_registers_helper(client, address, values, device_id):
    attempts = (
        {"device_id": device_id},
        {"slave": device_id},
        {"unit": device_id},
        {},
    )
    last_error = None
    for kwargs in attempts:
        try:
            return client.write_registers(address=address, values=values, **kwargs)
        except TypeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("Could not write registers")


def write_modbus_registers(machine: Machine, data: dict):
    """Write a machine's tag values to Modbus registers."""
    client = get_modbus_client()
    if client is None:
        return
    try:
        plc_cfg = config.get("plc", {})
        sim_cfg = config.get("simulator", {})
        block_size = sim_cfg.get("register_block_size", 10)
        device_id = plc_cfg.get("device_id", 1)
        base_addr = machine.machine_id * block_size

        tags = data["tags"]
        values = [
            tags["status"]["raw"],
            tags["speed"],
            tags["temperature"],
            tags["vibration"],
            tags["load"],
            tags["cycle_count"],
        ]

        write_holding_registers_helper(client, base_addr, values, device_id)
    except Exception as exc:
        print(f"[WARN] Modbus write failed for {machine.name}: {exc}. Resetting connection.")
        with modbus_lock:
            if modbus_client is not None:
                try:
                    modbus_client.close()
                except Exception:
                    pass
                modbus_client = None


# ---------------------------------------------------------------------------
# Modbus server helpers (for localhost development)
# ---------------------------------------------------------------------------

modbus_server_thread = None
modbus_server_running_on = None  # (ip, port)
modbus_server_lock = threading.Lock()

def check_and_start_modbus_server():
    global modbus_server_thread, modbus_server_running_on
    
    with config_lock:
        plc_cfg = config.get("plc", {})
        enabled = plc_cfg.get("enabled", False)
        ip = plc_cfg.get("ip", "192.168.1.5")
        port = plc_cfg.get("port", 502)
        
    is_local = ip in ("127.0.0.1", "localhost", "0.0.0.0")
    if not (enabled and is_local):
        return
        
    current_addr = (ip, port)
    with modbus_server_lock:
        if modbus_server_running_on == current_addr:
            return
            
        if modbus_server_running_on is not None:
            print(f"[WARN] Modbus server already running on {modbus_server_running_on}. Restart the application to change port/IP.")
            return

        try:
            from pymodbus.server import StartTcpServer
            from pymodbus.datastore.context import SimDevice, DataType
            from pymodbus.simulator.simdata import SimData
        except ImportError as e:
            print(f"[WARN] Cannot import pymodbus server classes: {e}. Local Modbus server disabled.")
            return

        # Create SimDevice with wildcard id=0 so it accepts any slave ID
        simdata = SimData(address=0, count=1000, datatype=DataType.REGISTERS, values=[0]*1000)
        device = SimDevice(id=0, simdata=simdata)
        
        def run_server():
            global modbus_server_running_on
            print(f"[INFO] Starting local Modbus TCP server on {ip}:{port}")
            modbus_server_running_on = current_addr
            try:
                StartTcpServer(device, address=(ip, port))
            except Exception as e:
                print(f"[WARN] Modbus TCP server failed to start on {ip}:{port}: {e}")
                with modbus_server_lock:
                    modbus_server_running_on = None
                
        modbus_server_thread = threading.Thread(target=run_server, daemon=True)
        modbus_server_thread.start()


# ---------------------------------------------------------------------------
# Flask + SocketIO setup
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    template_folder=os.path.join(BASE_DIR, "templates"),
)
app.config["SECRET_KEY"] = "plc-simulator-secret"

socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# ---------------------------------------------------------------------------
# Helper: build config payload for clients
# ---------------------------------------------------------------------------


def build_config_payload() -> dict:
    """Build the config_data payload from the runtime config."""
    with config_lock:
        plc = config.get("plc", {})
        sim = config.get("simulator", {})
        tags_raw = config.get("tags", [])

    tags_out = []
    for t in tags_raw:
        entry: dict = {"name": t["name"], "label": t["label"], "type": t["type"]}
        for optional_key in ("unit", "min", "max", "warn_high", "alarm_high"):
            if optional_key in t:
                entry[optional_key] = t[optional_key]
        tags_out.append(entry)

    return {
        "machine_count": sim.get("machine_count", 1),
        "update_interval": sim.get("update_interval", 1.0),
        "plc_enabled": plc.get("enabled", False),
        "plc_ip": plc.get("ip", "192.168.1.5"),
        "plc_port": plc.get("port", 502),
        "plc_device_id": plc.get("device_id", 1),
        "tags": tags_out,
    }


def apply_config_update(data: dict):
    """Merge incoming config updates into the runtime config."""
    global modbus_client
    with config_lock:
        if "machine_count" in data:
            config["simulator"]["machine_count"] = int(data["machine_count"])
        if "update_interval" in data:
            config["simulator"]["update_interval"] = float(data["update_interval"])
        if "plc_enabled" in data:
            config["plc"]["enabled"] = bool(data["plc_enabled"])
        if "plc_ip" in data:
            config["plc"]["ip"] = str(data["plc_ip"])
        if "plc_port" in data:
            config["plc"]["port"] = int(data["plc_port"])
        if "plc_device_id" in data:
            config["plc"]["device_id"] = int(data["plc_device_id"])
        if "tags" in data:
            config["tags"] = data["tags"]

    # Sync machine pool to new count
    sync_machines(config["simulator"]["machine_count"])

    # Save to disk
    save_config(config)

    # Check/restart local Modbus server
    check_and_start_modbus_server()

    # Disconnect client to force reconnect on next loop iteration
    with modbus_lock:
        if modbus_client is not None:
            try:
                modbus_client.close()
            except Exception:
                pass
            modbus_client = None


# ---------------------------------------------------------------------------
# REST API routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(build_config_payload())


@app.route("/api/config", methods=["POST"])
def api_update_config():
    data = request.get_json(force=True)
    apply_config_update(data)
    return jsonify(build_config_payload())


# ---------------------------------------------------------------------------
# Socket.IO event handlers
# ---------------------------------------------------------------------------


@socketio.on("connect")
def handle_connect():
    print("[INFO] Client connected")


@socketio.on("disconnect")
def handle_disconnect():
    print("[INFO] Client disconnected")


@socketio.on("get_config")
def handle_get_config(_data=None):
    emit("config_data", build_config_payload())


@socketio.on("update_config")
def handle_update_config(data):
    apply_config_update(data)
    # Broadcast updated config to ALL connected clients
    socketio.emit("config_data", build_config_payload())


@socketio.on("set_machine_state")
def handle_set_machine_state(data):
    """Set the override state of a machine."""
    machine_id = int(data.get("machine_id", 0))
    state_name = str(data.get("state", "auto")).lower()
    
    with machines_lock:
        if 0 <= machine_id < len(machines):
            machines[machine_id].override_state = state_name
            print(f"[INFO] Set machine {machine_id} override state to {state_name}")


# ---------------------------------------------------------------------------
# Background simulation thread
# ---------------------------------------------------------------------------

simulation_running = True


def simulation_loop():
    """Background thread that drives all machines and emits data."""
    global simulation_running

    while simulation_running:
        with config_lock:
            interval = config["simulator"].get("update_interval", 1.0)

        # Ensure machine pool is in sync
        with config_lock:
            target_count = config["simulator"].get("machine_count", 1)
        sync_machines(target_count)

        # Tick all machines
        machine_data_list = []
        with machines_lock:
            for m in machines:
                data = m.tick()
                machine_data_list.append(data)

        # Build payload
        payload = {
            "machines": machine_data_list,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") +
                         f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
        }

        # Emit via WebSocket
        socketio.emit("machine_data", payload)

        # Optional Modbus writes
        with machines_lock:
            for i, m in enumerate(machines):
                if i < len(machine_data_list):
                    write_modbus_registers(m, machine_data_list[i])

        # Console output
        print_machine_data(machine_data_list)

        time.sleep(interval)


def print_machine_data(machine_data_list: list[dict]):
    """Print machine data to console in a compact format."""
    for md in machine_data_list:
        tags = md["tags"]
        status = tags["status"]
        print(
            f"[{md['name']}] "
            f"Cycle:{md['cycle']:4d} | "
            f"Status:{status['raw']:02d} | "
            f"Speed:{tags['speed']:3d} | "
            f"Temp:{tags['temperature']:2d} | "
            f"Vib:{tags['vibration']:2d} | "
            f"Load:{tags['load']:2d} | "
            f"Count:{tags['cycle_count']}"
        )


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------


def print_banner():
    """Print a startup banner with current configuration."""
    sim = config.get("simulator", {})
    plc = config.get("plc", {})
    tag_names = [t["name"] for t in config.get("tags", [])]

    banner = f"""
╔══════════════════════════════════════════════════════╗
║             PLC Multi-Machine Simulator              ║
╠══════════════════════════════════════════════════════╣
║  Machines     : {sim.get('machine_count', 1):<37d}║
║  Interval     : {sim.get('update_interval', 1.0):<37.1f}║
║  Web Port     : {sim.get('web_port', 8080):<37d}║
║  PLC Enabled  : {str(plc.get('enabled', False)):<37s}║
║  PLC Address  : {plc.get('ip', 'N/A') + ':' + str(plc.get('port', 502)):<37s}║
║  Tags         : {', '.join(tag_names):<37s}║
╚══════════════════════════════════════════════════════╝
"""
    try:
        print(banner)
    except UnicodeEncodeError:
        plain_banner = f"""
+------------------------------------------------------+
|             PLC Multi-Machine Simulator              |
+------------------------------------------------------+
  Machines     : {sim.get('machine_count', 1)}
  Interval     : {sim.get('update_interval', 1.0)}s
  Web Port     : {sim.get('web_port', 8080)}
  PLC Enabled  : {str(plc.get('enabled', False))}
  PLC Address  : {plc.get('ip', 'N/A')}:{plc.get('port', 502)}
  Tags         : {', '.join(tag_names)}
+------------------------------------------------------+
"""
        print(plain_banner)


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------


def shutdown_handler(signum, frame):
    global simulation_running, modbus_client
    print("\n[INFO] Shutting down simulator...")
    simulation_running = False
    with modbus_lock:
        if modbus_client is not None:
            try:
                modbus_client.close()
            except Exception:
                pass
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print_banner()

    # Initialize machine pool
    sync_machines(config["simulator"].get("machine_count", 1))

    # Start Modbus server if running in local mode
    check_and_start_modbus_server()

    # Start background simulation thread
    sim_thread = threading.Thread(target=simulation_loop, daemon=True)
    sim_thread.start()

    # Run Flask-SocketIO server
    web_port = config["simulator"].get("web_port", 8080)
    print(f"[INFO] Starting server on http://0.0.0.0:{web_port}")
    socketio.run(
        app,
        host="0.0.0.0",
        port=web_port,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
