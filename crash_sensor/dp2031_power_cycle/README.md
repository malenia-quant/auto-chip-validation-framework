# Crash Sensor Rigol DP2031 Power-Cycle & Power-On Ramp Verification Suite

Author: mozial

---

## 1. Overview and Core Scope

This module is dedicated to automated **power-cycle stress and power-on ramp rate verification** for automotive crash sensor ASICs using the Rigol DP2031 programmable DC power supply.

In automotive electrical environments, supply rails experience varying rise times (fast ramp vs slow ramp) during cold cranking, ignition transients, or relay closures. This suite automates cyclic power cycling to verify whether the chip boots normally, evaluates internal brownout reset circuits, and monitors CAN bus startup frames.

---

## 2. Directory Structure

```text
crash_sensor/dp2031_power_cycle/
├── dp2031_control.py           # Dual-channel power supply control: CH1 bias, CH2 high/low voltage transitions & CANFD logging
├── power_cycle_collect.py      # Automated cyclical power-on stress testing (10s capture + 3min idle countdown)
├── README_zh.md                # Chinese Technical and Operation Manual
└── README.md                   # [Current Document] English Technical and Operation Manual
```

---

## 3. Core Test Capabilities

### 3.1 Dual-Channel Power Ramp & Voltage Transitions (dp2031_control.py)
- **CH1**: Provides steady bias/logic power (e.g. 6.0V, 100mA compliance).
- **CH2**: Injects fast/slow cyclic transitions between high and low voltages (e.g. 2.0V to 1.0V with a 2.0s period).
- Synchronously monitors USBCANFD-200U bus frames and sends periodic control commands (`CMD_INTERVAL = 0.02s`).

### 3.2 Long-Term Automated Power Cycling (power_cycle_collect.py)
- Connects to Rigol DP2031 via VISA with OVP/OCP protection guards (e.g. 12.0V / 1.0A with 13.5V OVP, 1.5A OCP).
- Engages power output, records CAN FD startup frames for 10 seconds.
- Turns power OFF and enters a 3-minute resting countdown.
- Repeats cyclically and persists session data into timestamped CSV records.
- Implements strict safety teardown: automatically forces power output OFF on script exit or unexpected errors.

---

## 4. ZLG CAN Driver Path Resolution

`dp2031_power_cycle` is located at `crash_sensor/dp2031_power_cycle/` and resolves the sibling driver directory `crash_sensor/zlgcan_file`:

```python
script_dir = os.path.dirname(os.path.abspath(__file__))
candidate_dirs = [
    os.path.abspath(os.path.join(script_dir, "..", "zlgcan_file", "zlgcan_python_251211")),
    r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file\zlgcan_python_251211",
    os.path.abspath(os.path.join(script_dir, "..", "..", "zlgcan_file", "zlgcan_python_251211")),
]
zlgcan_real_dir = next((d for d in candidate_dirs if os.path.exists(d)), candidate_dirs[0])
```

---

## 5. Quickstart Guide

### 5.1 Environment Activation
Activate the designated Conda environment:
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
```

### 5.2 Execute Dual-Channel Power-Cycle Test
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\dp2031_power_cycle
python dp2031_control.py
```

### 5.3 Execute Automated Power Cycling Stress Test
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\dp2031_power_cycle
python power_cycle_collect.py
```
