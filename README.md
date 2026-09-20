# plcsim

A robust Python-based Industrial Machine Simulator that mimics PLC (Programmable Logic Controller) telemetry, featuring both a graphical desktop application and a web-based interface.

## Overview
`plcsim` generates realistic simulated data for industrial machinery (e.g., speed, temperature, vibration, load) and exposes this telemetry via Modbus TCP. It is designed to act as a mock data source for testing SCADA systems, HMI dashboards, or IIoT data pipelines. The project provides two separate frontends to control the simulation:
1. **Web UI** (`simulator.py`): A Flask and Socket.IO based dashboard.
2. **Desktop UI** (`simulator_gui.py`): A native desktop application built with `customtkinter`.

## Core Features and Domain Models
- **Machine Simulation**: Simulates the state of industrial assets over time, generating analog variables (speed, temp, vibration) using sine waves, noise profiles, and physics-based momentum rules.
- **State Machine**: Machines can be toggled between states (Auto, Manual, E-Stop, Alarm, Idle, Running).
- **Modbus TCP Integration**: 
  - **Client Mode**: Writes simulated registers to an external Modbus PLC.
  - **Server Mode**: Hosts a local PyModbus TCP Server allowing external IIoT platforms to poll the simulator directly.

## Prerequisites
- Python 3.10+
- `flask`, `flask_socketio`
- `customtkinter`, `tkinter`
- `pymodbus`
- (All dependencies listed in `requirements.txt`)

## Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone git@github.com:Pras2005/plcsim.git
   cd plcsim
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Usage / Running Locally

### Option 1: Web-based Simulator
Start the Flask/Socket.IO web server:
```bash
python simulator.py
```
- Access the web interface at: `http://127.0.0.1:5001`
- Configure Modbus IP, update intervals, and machine count from the web UI.

### Option 2: Desktop GUI Simulator
Start the CustomTkinter desktop interface:
```bash
python simulator_gui.py
```
- A graphical window will open allowing direct manipulation of machines and monitoring of the integrated Modbus server.

## Project Structure
```text
plcsim
├── simulator.py         # Flask & Socket.IO web application entry point
├── simulator_gui.py     # CustomTkinter desktop GUI entry point
├── plc.py               # Core logic for machine simulation and Modbus mapping
├── config.json          # Configuration file for machine tags and network settings
├── requirements.txt     # Python dependencies
├── static/              # Web UI static assets (CSS, JS)
│   └── js/
│       └── app.js       # WebSocket and UI updating logic for the web dashboard
└── templates/           # Web UI HTML templates
    └── index.html       # Main web dashboard layout
```
