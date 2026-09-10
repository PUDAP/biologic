"""Direct driver smoke test against a connected BioLogic (Windows)."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from driver import Driver

load_dotenv()

device_ip = os.getenv("BIOLOGIC_IP")
if not device_ip:
    raise ValueError(
        "BIOLOGIC_IP environment variable is not set. Please set it in your .env file or environment."
    )

machine = Driver(device_ip)

params_cv_0 = {
    "start": 0.0,
    "end": 0.5,
    "rate": 0.1,
    "step": 0.1,
    "E2": 0.0,
    "Ef": 0.0,
    "average": False,
}

data = machine.CV(
    params=params_cv_0,
    channels=[0],
)

print(data)
print("Protocol finished.")
