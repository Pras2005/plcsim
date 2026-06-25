import time
import math
import random
from pymodbus.client import ModbusTcpClient

PLC_IP = "192.168.1.5"
PLC_PORT = 502
DEVICE_ID = 1

client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

if not client.connect():
    print("Failed to connect to PLC")
    exit()

print("Connected to PLC")

cycle = 0
cycle_count = 0

try:
    while True:

        power = 1
        auto = 1
        cycle_running = 1 if (cycle % 30) < 20 else 0
        estop = 0
        alarm = 1 if random.randint(1,100) <= 3 else 0
        door = 0

        status = (
            (power << 0) |
            (auto << 1) |
            (cycle_running << 2) |
            (estop << 3) |
            (alarm << 4) |
            (door << 5)
        )

        if cycle_running:
            speed = 70 + int(10*math.sin(cycle/5))
            temperature = 45 + random.randint(-2,2)
            vibration = 20 + random.randint(-3,3)
            load = 75 + random.randint(-5,5)
        else:
            speed = 0
            temperature = 35
            vibration = 3
            load = 0

        if cycle % 30 == 0:
            cycle_count += 1

        values = [
            status, # MW0
            speed, # MW1
            temperature, # MW2
            vibration, # MW3
            load, # MW4
            cycle_count # MW5
        ]

        client.write_registers(
            address=0,
            values=values,
            device_id=DEVICE_ID
        )

        print(
            f"Cycle:{cycle:4d} | "
            f"Status:{status:02d} | "
            f"Speed:{speed:3d} | "
            f"Temp:{temperature:2d} | "
            f"Vib:{vibration:2d} | "
            f"Load:{load:2d} | "
            f"Count:{cycle_count}"
        )

        cycle += 1
        time.sleep(1)

except KeyboardInterrupt:
    print("\nSimulator stopped.")
    client.close()
