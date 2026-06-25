#!/usr/bin/env python3
"""
PLC Simulator — Desktop GUI
CustomTkinter-based industrial dashboard for simulating multiple PLC machines.

Run:  python simulator_gui.py
"""

import customtkinter as ctk
import tkinter as tk
import math
import random
import json
import os
import threading
from datetime import datetime

# ─── Configuration ──────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "plc": {"enabled": False, "ip": "192.168.1.5", "port": 502, "device_id": 1},
    "simulator": {
        "machine_count": 1, "update_interval": 1.0,
        "web_port": 8080, "register_block_size": 10,
    },
    "tags": [
        {"name": "status", "label": "Status", "type": "bitfield", "register_offset": 0,
         "bits": {"power": 0, "auto": 1, "running": 2, "estop": 3, "alarm": 4, "door_open": 5}},
        {"name": "speed", "label": "Speed", "type": "analog", "register_offset": 1,
         "unit": "RPM", "min": 0, "max": 100, "warn_high": 85, "alarm_high": 95},
        {"name": "temperature", "label": "Temperature", "type": "analog", "register_offset": 2,
         "unit": "°C", "min": 0, "max": 100, "warn_high": 55, "alarm_high": 70},
        {"name": "vibration", "label": "Vibration", "type": "analog", "register_offset": 3,
         "unit": "mm/s", "min": 0, "max": 50, "warn_high": 30, "alarm_high": 40},
        {"name": "load", "label": "Load", "type": "analog", "register_offset": 4,
         "unit": "%", "min": 0, "max": 100, "warn_high": 85, "alarm_high": 95},
        {"name": "cycle_count", "label": "Cycle Count", "type": "counter",
         "register_offset": 5, "unit": "cycles"},
    ],
}


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        for key in DEFAULT_CONFIG:
            if key not in cfg:
                cfg[key] = DEFAULT_CONFIG[key]
        return cfg
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


config = load_config()

# ─── Color Palette ──────────────────────────────────────────────────────────

C = {
    "bg":          "#060b18",
    "toolbar":     "#0a1020",
    "card":        "#0f172a",
    "card_border": "#1e293b",
    "led_row":     "#080e1e",
    "counter_bg":  "#070c18",
    "input":       "#0c1424",
    "primary":     "#00d4ff",
    "success":     "#00ff88",
    "warning":     "#ffaa00",
    "alarm":       "#ff3344",
    "idle":        "#334155",
    "led_off":     "#1a2030",
    "text":        "#e2e8f0",
    "text_dim":    "#94a3b8",
    "text_dark":   "#475569",
    "gauge_track": "#1a2235",
}

# Font family — fallback if not installed
FONT_MAIN = "Inter"
FONT_MONO = "JetBrains Mono"


# ─── Machine Simulation ────────────────────────────────────────────────────

class Machine:
    """Simulates one PLC machine with 6 standard tags."""

    def __init__(self, machine_id: int):
        self.id = machine_id
        self.name = f"Machine {machine_id + 1}"
        self.cycle = machine_id * 7  # offset so machines don't sync
        self.cycle_count = 0
        self.data: dict = {}

    def tick(self) -> dict:
        power = 1
        auto = 1
        running = 1 if (self.cycle % 30) < 20 else 0
        estop = 0
        alarm = 1 if random.randint(1, 100) <= 3 else 0
        door = 0

        status_raw = (
            (power) | (auto << 1) | (running << 2)
            | (estop << 3) | (alarm << 4) | (door << 5)
        )

        if running:
            speed = 70 + int(10 * math.sin(self.cycle / 5))
            temperature = 45 + random.randint(-2, 2)
            vibration = 20 + random.randint(-3, 3)
            load = 75 + random.randint(-5, 5)
        else:
            speed, temperature, vibration, load = 0, 35, 3, 0

        if self.cycle % 30 == 0:
            self.cycle_count += 1

        self.cycle += 1

        self.data = {
            "status": {
                "raw": status_raw,
                "power": bool(power), "auto": bool(auto),
                "running": bool(running), "estop": bool(estop),
                "alarm": bool(alarm), "door_open": bool(door),
            },
            "speed": speed, "temperature": temperature,
            "vibration": vibration, "load": load,
            "cycle_count": self.cycle_count,
        }
        return self.data


# ─── Gauge Widget ───────────────────────────────────────────────────────────

class GaugeWidget(tk.Canvas):
    """Circular arc gauge rendered on a tkinter Canvas."""

    ARC_SWEEP = 270
    ARC_START = 225  # 7:30 position (counterclockwise fills)

    def __init__(self, parent, label="", unit="", min_val=0, max_val=100,
                 warn_high=None, alarm_high=None, size=120):
        super().__init__(parent, width=size, height=size + 24,
                         bg=C["card"], highlightthickness=0, bd=0)
        self.s = size
        self.min_val = min_val
        self.max_val = max_val
        self.warn_high = warn_high
        self.alarm_high = alarm_high
        self._unit = unit

        pad = 14
        cx, cy = size / 2, size / 2

        # Background arc (full sweep)
        self.bg_arc = self.create_arc(
            pad, pad, size - pad, size - pad,
            start=self.ARC_START, extent=-self.ARC_SWEEP,
            style="arc", outline=C["gauge_track"], width=9,
        )
        # Fill arc (starts empty)
        self.fill_arc = self.create_arc(
            pad, pad, size - pad, size - pad,
            start=self.ARC_START, extent=0,
            style="arc", outline=C["primary"], width=9,
        )
        # Center value text
        self.val_text = self.create_text(
            cx, cy - 4, text="0",
            font=(FONT_MONO, 17, "bold"), fill=C["text"],
        )
        # Unit text below value
        self.unit_text = self.create_text(
            cx, cy + 16, text=unit,
            font=(FONT_MAIN, 8), fill=C["text_dark"],
        )
        # Label below gauge
        self.create_text(
            cx, size + 10, text=label.upper(),
            font=(FONT_MAIN, 8, "bold"), fill=C["text_dim"],
        )

    def set_value(self, value):
        rng = max(1, self.max_val - self.min_val)
        ratio = max(0.0, min(1.0, (value - self.min_val) / rng))
        extent = -(self.ARC_SWEEP * ratio)

        # Color by threshold
        color = C["primary"]
        if self.alarm_high is not None and value >= self.alarm_high:
            color = C["alarm"]
        elif self.warn_high is not None and value >= self.warn_high:
            color = C["warning"]

        self.itemconfig(self.fill_arc, extent=extent, outline=color)
        self.itemconfig(self.val_text, text=str(int(value)))


# ─── LED Widget ─────────────────────────────────────────────────────────────

class LEDWidget(tk.Canvas):
    """Small LED circle with label."""

    def __init__(self, parent, label="", size=12, bg_color=None):
        bg = bg_color or C["led_row"]
        w = max(38, len(label) * 7 + 6)
        super().__init__(parent, width=w, height=size + 20,
                         bg=bg, highlightthickness=0, bd=0)
        self.cx = w / 2

        # LED circle
        r = size / 2
        self.led = self.create_oval(
            self.cx - r, 4, self.cx + r, 4 + size,
            fill=C["led_off"], outline="",
        )
        # Label
        self.create_text(
            self.cx, size + 12, text=label,
            font=(FONT_MAIN, 7, "bold"), fill=C["text_dark"],
        )

    def set_active(self, active, color=None):
        if active and color:
            self.itemconfig(self.led, fill=color)
        else:
            self.itemconfig(self.led, fill=C["led_off"])


# ─── Machine Card ──────────────────────────────────────────────────────────

class MachineCard(ctk.CTkFrame):
    """Card displaying one machine's real-time data."""

    LED_DEFS = [
        ("power",    "PWR",    "success"),
        ("auto",     "AUTO",   "primary"),
        ("running",  "RUN",    "success"),
        ("estop",    "E-STOP", "alarm"),
        ("alarm",    "ALARM",  "warning"),
        ("door_open","DOOR",   "alarm"),
    ]

    GAUGE_DEFAULTS = {
        "speed":       ("Speed",     "RPM",  0, 100, 85, 95),
        "temperature": ("Temp",      "°C",   0, 100, 55, 70),
        "vibration":   ("Vibration", "mm/s", 0,  50, 30, 40),
        "load":        ("Load",      "%",    0, 100, 85, 95),
    }

    def __init__(self, parent, machine_id, name, tag_config):
        super().__init__(
            parent, fg_color=C["card"],
            border_color=C["card_border"], border_width=1,
            corner_radius=12,
        )
        self.machine_id = machine_id
        self.tag_config = tag_config
        self.leds: dict[str, LEDWidget] = {}
        self.gauges: dict[str, GaugeWidget] = {}
        self._build(name)

    def _tag_meta(self, name):
        """Get tag config with fallback defaults."""
        for t in self.tag_config:
            if t.get("name") == name:
                return t
        d = self.GAUGE_DEFAULTS.get(name)
        if d:
            return {"name": name, "label": d[0], "unit": d[1],
                    "min": d[2], "max": d[3], "warn_high": d[4], "alarm_high": d[5]}
        return {"name": name, "label": name, "unit": "", "min": 0, "max": 100}

    def _build(self, name):
        # ── Header ──
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(14, 6))

        ctk.CTkLabel(hdr, text=name, font=(FONT_MAIN, 15, "bold"),
                     text_color=C["text"]).pack(side="left")

        # Overall status LED (small canvas)
        self.overall_cv = tk.Canvas(hdr, width=16, height=16,
                                     bg=C["card"], highlightthickness=0, bd=0)
        self.overall_cv.pack(side="right")
        self.overall_dot = self.overall_cv.create_oval(2, 2, 14, 14,
                                                        fill=C["idle"], outline="")

        # ── Status LEDs row ──
        led_frame = tk.Frame(self, bg=C["led_row"],
                             highlightthickness=1,
                             highlightbackground=C["card_border"],
                             padx=4, pady=4)
        led_frame.pack(fill="x", padx=12, pady=(0, 8))

        for key, label, _ in self.LED_DEFS:
            led = LEDWidget(led_frame, label=label, size=12, bg_color=C["led_row"])
            led.pack(side="left", expand=True)
            self.leds[key] = led

        # ── Gauges (2×2 grid) ──
        gauge_frame = tk.Frame(self, bg=C["card"])
        gauge_frame.pack(fill="x", padx=8, pady=(0, 4))
        gauge_frame.grid_columnconfigure((0, 1), weight=1)

        for i, tag_name in enumerate(["speed", "temperature", "vibration", "load"]):
            meta = self._tag_meta(tag_name)
            g = GaugeWidget(
                gauge_frame,
                label=meta.get("label", tag_name),
                unit=meta.get("unit", ""),
                min_val=meta.get("min", 0),
                max_val=meta.get("max", 100),
                warn_high=meta.get("warn_high"),
                alarm_high=meta.get("alarm_high"),
                size=115,
            )
            g.grid(row=i // 2, column=i % 2, padx=6, pady=4)
            self.gauges[tag_name] = g

        # ── Cycle Counter ──
        cnt_frame = ctk.CTkFrame(self, fg_color=C["counter_bg"],
                                  corner_radius=8, border_width=1,
                                  border_color="#0a2a1a")
        cnt_frame.pack(fill="x", padx=12, pady=(4, 14))

        cnt_inner = ctk.CTkFrame(cnt_frame, fg_color="transparent")
        cnt_inner.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(cnt_inner, text="CYCLE COUNT",
                     font=(FONT_MAIN, 9, "bold"),
                     text_color=C["text_dark"]).pack(side="left")

        self.cycle_label = ctk.CTkLabel(
            cnt_inner, text="000000",
            font=(FONT_MONO, 16, "bold"), text_color=C["success"],
        )
        self.cycle_label.pack(side="right")

    # ── Update ──

    def update_data(self, data: dict):
        status = data.get("status", {})

        # Overall LED
        if status.get("estop"):
            self.overall_cv.itemconfig(self.overall_dot, fill=C["alarm"])
        elif status.get("alarm"):
            self.overall_cv.itemconfig(self.overall_dot, fill=C["warning"])
        elif status.get("running"):
            self.overall_cv.itemconfig(self.overall_dot, fill=C["success"])
        else:
            self.overall_cv.itemconfig(self.overall_dot, fill=C["idle"])

        # Status LEDs
        for key, _, color_key in self.LED_DEFS:
            self.leds[key].set_active(status.get(key, False), C[color_key])

        # Gauges
        for tag_name, gauge in self.gauges.items():
            gauge.set_value(data.get(tag_name, 0))

        # Cycle counter
        self.cycle_label.configure(
            text=str(data.get("cycle_count", 0)).zfill(6)
        )

        # Border glow
        if status.get("running") and not status.get("estop"):
            self.configure(border_color="#0e4a5a")
        elif status.get("estop") or status.get("alarm"):
            self.configure(border_color="#3a1525")
        else:
            self.configure(border_color=C["card_border"])


# ─── Main Application ──────────────────────────────────────────────────────

class PLCSimulatorApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title("PLC Simulator")
        self.geometry("1100x780")
        self.minsize(600, 500)
        self.configure(fg_color=C["bg"])

        self.machines: list[Machine] = []
        self.cards: list[MachineCard] = []
        self.modbus_client = None
        self.tag_config = config.get("tags", [])
        self._tick_count = 0
        self._last_cols = 0

        self._build_ui()
        self._sync_machines()
        self._tick()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI Construction ──

    def _build_ui(self):
        # ── Toolbar ──
        toolbar = ctk.CTkFrame(self, fg_color=C["toolbar"], height=52, corner_radius=0)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        # Brand (left)
        brand = ctk.CTkFrame(toolbar, fg_color="transparent")
        brand.pack(side="left", padx=16)
        ctk.CTkLabel(brand, text="🏭", font=(FONT_MAIN, 18)).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(brand, text="PLC Simulator",
                     font=(FONT_MAIN, 15, "bold"),
                     text_color=C["primary"]).pack(side="left")

        # Controls (right)
        ctrls = ctk.CTkFrame(toolbar, fg_color="transparent")
        ctrls.pack(side="right", padx=16)

        # Machines
        ctk.CTkLabel(ctrls, text="Machines:", font=(FONT_MAIN, 11),
                     text_color=C["text_dim"]).pack(side="left", padx=(0, 4))
        self.machine_count_var = tk.IntVar(value=config["simulator"]["machine_count"])
        ctk.CTkEntry(ctrls, width=48, font=(FONT_MONO, 12),
                     textvariable=self.machine_count_var,
                     fg_color=C["input"], border_color=C["card_border"],
                     justify="center").pack(side="left", padx=(0, 14))

        # Interval
        ctk.CTkLabel(ctrls, text="Interval:", font=(FONT_MAIN, 11),
                     text_color=C["text_dim"]).pack(side="left", padx=(0, 4))
        self.interval_var = tk.DoubleVar(value=config["simulator"]["update_interval"])
        ctk.CTkEntry(ctrls, width=48, font=(FONT_MONO, 12),
                     textvariable=self.interval_var,
                     fg_color=C["input"], border_color=C["card_border"],
                     justify="center").pack(side="left")
        ctk.CTkLabel(ctrls, text="s", font=(FONT_MAIN, 11),
                     text_color=C["text_dark"]).pack(side="left", padx=(2, 14))

        # PLC toggle
        self.plc_var = tk.BooleanVar(value=config["plc"]["enabled"])
        ctk.CTkSwitch(ctrls, text="PLC", font=(FONT_MAIN, 11),
                      text_color=C["text_dim"], variable=self.plc_var,
                      progress_color=C["primary"],
                      button_color=C["text_dim"],
                      button_hover_color=C["primary"]).pack(side="left", padx=(0, 14))

        # Apply
        ctk.CTkButton(ctrls, text="Apply", width=70,
                      font=(FONT_MAIN, 11, "bold"),
                      fg_color=C["primary"], text_color="#000",
                      hover_color="#33ddff",
                      command=self._apply_config).pack(side="left")

        # Separator
        ctk.CTkFrame(self, fg_color=C["card_border"], height=1,
                     corner_radius=0).pack(fill="x")

        # ── Machine Grid (scrollable) ──
        self.scroll = ctk.CTkScrollableFrame(self, fg_color=C["bg"],
                                              scrollbar_button_color=C["card_border"],
                                              scrollbar_button_hover_color=C["text_dark"])
        self.scroll.pack(fill="both", expand=True, padx=10, pady=10)
        self.scroll.bind("<Configure>", self._on_resize)

        # ── Console (bottom) ──
        console_wrap = ctk.CTkFrame(self, fg_color=C["toolbar"], height=90,
                                     corner_radius=0)
        console_wrap.pack(fill="x")
        console_wrap.pack_propagate(False)

        self.console = ctk.CTkTextbox(
            console_wrap, font=(FONT_MONO, 10),
            fg_color=C["toolbar"], text_color=C["text_dim"],
            height=80, wrap="none", activate_scrollbars=True,
            scrollbar_button_color=C["card_border"],
        )
        self.console.pack(fill="both", expand=True, padx=8, pady=4)

    # ── Machine Management ──

    def _sync_machines(self):
        target = config["simulator"]["machine_count"]

        while len(self.machines) < target:
            mid = len(self.machines)
            m = Machine(mid)
            self.machines.append(m)
            card = MachineCard(self.scroll, mid, m.name, self.tag_config)
            self.cards.append(card)

        while len(self.machines) > target:
            self.machines.pop()
            self.cards.pop().destroy()

        self._layout_cards()
        self._log(f"Running {len(self.machines)} machine(s)")

    def _on_resize(self, event=None):
        w = self.scroll.winfo_width()
        cols = max(1, w // 340)
        if cols != self._last_cols:
            self._last_cols = cols
            self._layout_cards(cols)

    def _layout_cards(self, cols=None):
        if cols is None:
            cols = max(1, self.scroll.winfo_width() // 340)
            if cols < 1:
                cols = 1
        for i, card in enumerate(self.cards):
            card.grid(row=i // cols, column=i % cols,
                      padx=8, pady=8, sticky="nsew")
        for c in range(cols):
            self.scroll.grid_columnconfigure(c, weight=1)

    # ── Config ──

    def _apply_config(self):
        try:
            count = max(1, min(20, int(self.machine_count_var.get())))
        except (ValueError, tk.TclError):
            count = 1
        try:
            interval = max(0.1, min(10.0, float(self.interval_var.get())))
        except (ValueError, tk.TclError):
            interval = 1.0

        config["simulator"]["machine_count"] = count
        config["simulator"]["update_interval"] = interval
        config["plc"]["enabled"] = self.plc_var.get()

        self.machine_count_var.set(count)
        self.interval_var.set(interval)

        self._sync_machines()
        self._log(f"Config: {count} machine(s), {interval}s interval, "
                  f"PLC {'ON' if self.plc_var.get() else 'OFF'}")

    # ── Simulation Tick ──

    def _tick(self):
        for i, machine in enumerate(self.machines):
            data = machine.tick()
            if i < len(self.cards):
                self.cards[i].update_data(data)

            # Modbus
            if config["plc"]["enabled"]:
                self._write_modbus(machine, data)

        # Console log (every 5th tick)
        self._tick_count += 1
        if self._tick_count % 5 == 0:
            for m in self.machines:
                d = m.data
                if not d:
                    continue
                s = d["status"]
                flags = (f"{'P' if s['power'] else '-'}"
                         f"{'A' if s['auto'] else '-'}"
                         f"{'R' if s['running'] else '-'}"
                         f"{'E' if s['estop'] else '-'}"
                         f"{'!' if s['alarm'] else '-'}"
                         f"{'D' if s['door_open'] else '-'}")
                self._log(
                    f"[{m.name}] Cyc:{m.cycle:4d} [{flags}] "
                    f"Spd:{d['speed']:3d} Tmp:{d['temperature']:2d} "
                    f"Vib:{d['vibration']:2d} Ld:{d['load']:3d} "
                    f"Cnt:{d['cycle_count']}"
                )

        interval_ms = int(config["simulator"]["update_interval"] * 1000)
        self.after(interval_ms, self._tick)

    # ── Modbus ──

    def _write_modbus(self, machine: Machine, data: dict):
        if self.modbus_client is None:
            try:
                from pymodbus.client import ModbusTcpClient
                ip = config["plc"]["ip"]
                port = config["plc"]["port"]
                self.modbus_client = ModbusTcpClient(ip, port=port)
                if not self.modbus_client.connect():
                    self._log(f"⚠ Modbus connect failed → {ip}:{port}")
                    self.modbus_client = None
                    config["plc"]["enabled"] = False
                    self.plc_var.set(False)
                    return
                self._log(f"✅ Modbus connected → {ip}:{port}")
            except Exception as e:
                self._log(f"⚠ Modbus error: {e}")
                self.modbus_client = None
                config["plc"]["enabled"] = False
                self.plc_var.set(False)
                return
        try:
            block = config["simulator"].get("register_block_size", 10)
            dev = config["plc"].get("device_id", 1)
            base = machine.id * block
            vals = [
                data["status"]["raw"], data["speed"],
                data["temperature"], data["vibration"],
                data["load"], data["cycle_count"],
            ]
            self.modbus_client.write_registers(address=base, values=vals, slave=dev)
        except Exception as e:
            self._log(f"⚠ Modbus write [{machine.name}]: {e}")

    # ── Console ──

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.console.insert("end", f"[{ts}] {msg}\n")
        self.console.see("end")
        # trim to last 200 lines
        try:
            lines = int(self.console.index("end-1c").split(".")[0])
            if lines > 200:
                self.console.delete("1.0", f"{lines - 200}.0")
        except Exception:
            pass

    # ── Cleanup ──

    def _on_close(self):
        if self.modbus_client:
            try:
                self.modbus_client.close()
            except Exception:
                pass
        self.destroy()


# ─── Entry Point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    app = PLCSimulatorApp()
    app.mainloop()
