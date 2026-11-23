#!/usr/bin/env python3
"""S-415 -- print the Linux x ARM64 battery-port register."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from samverk.battery_port_arm import register, render_register_log

if __name__ == "__main__":
    sys.stdout.write(render_register_log(register()))
