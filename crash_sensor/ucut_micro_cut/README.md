# Crash Sensor uCut (Micro-Interruption) Characterization Suite

Author: mozial

---

## 1. Overview and Core Scope

This module is a dedicated hardware-in-the-loop (HIL) automated test suite designed for characterization and boundary validation of automotive crash sensor ICs under supply line micro-interruptions (uCut).

In automotive power networks, transient power drops occur due to engine cranking, relay bouncing, or inductive load switching. The uCut test suite injects 24 distinct fault conditions across variable drop depths and pulse widths to determine the safe operating area, brown-out reset behavior, and register retention performance.

---

## 2. Directory Structure

```text
crash_sensor/ucut_micro_cut/
├── dg5072_ucut.py         # Rigol DG5072 ARB driver with volatile RAM 16-bit waveform synthesis
├── pyserial_ucut.py       # Serial / I2C hardware controller for trimming and register verification
├── sds5054_ucut.py        # Siglent SDS5054 oscilloscope driver, edge triggering, and waveform analysis
├── ucut_control.py        # 24-case matrix test orchestrator and Excel Shmoo Plot report generator
├── README_zh.md           # Chinese Technical and Operation Manual
└── README.md              # [Current Document] English Technical and Operation Manual
```

---

## 3. Architecture and Testbench Integration

```text
+-------------------------------------------------------------+
|               PC Host Master Controller (ucut_control.py)   |
+--------------------+---------------------+------------------+
                     |                     |
     PyVISA (USB/TCP)|      PySerial (COM) |   PyVISA (TCP/VXI-11)
                     v                     v                  v
+------------------------+  +--------------------+  +----------------------+
|  Rigol DG5072          |  |  USB-to-Serial/I2C |  |  Siglent SDS5054     |
|  - 16-bit ARB download |  |  - Power rail ctrl |  |  - CH1: Supply VDD   |
|  - 4s RAM hot-reload   |  |  - Pre-trim config |  |  - CH2: PSI5 current |
|  - Transient synthesis |  |  - Retention check |  |  - Pulse width stats |
+-----------+------------+  +---------+----------+  +----------+-----------+
            |                         |                        |
            +------------+------------+                        |
                         |                                     |
                         v                                     |
              +-----------------------+                        |
              | Device Under Test(DUT)+------------------------+
              +-----------------------+
```

---

## 4. Key Engineering Implementation Details

### 4.1 Volatile ARB Hot-Reloading (dg5072_ucut.py)
- Eliminates mechanical relay switching jitter, arc erosion, and inductive transients.
- Synthesizes 16-bit custom binary waveforms directly into Rigol DG5072 internal `VOLATILE` RAM, generating composite sequences of base voltage (`V_BASE`), sync header pulses (`V_SYNC_HIGH`), and micro-cut faults (`V_CUT_LOW`).
- Implements strict hardware sequence guards: generator outputs are fully initialized and stabilized before connecting supply rails.

### 4.2 Non-Volatile Register Retention (pyserial_ucut.py)
- Injects hardware trimming configurations via serial/I2C prior to fault execution.
- Interrogates on-chip register states post-recovery to guarantee zero state corruption.

### 4.3 Oscilloscope Acquisition and Protocol Validation (sds5054_ucut.py)
- Channel 1 monitors the DUT supply rail; Channel 2 monitors the drop voltage across a 10.03-ohm sense resistor for PSI5 communication current.
- Automatically calculates falling edge duration, true cut depth, and post-cut recovery response latency.

### 4.4 Automated Shmoo Plot Generation (ucut_control.py)
- Sweeps through the 24-point test matrix covering drop voltages from 0V to 11V and pulse widths from 10us to 5000us.
- Automatically produces a color-coded Excel report with a dedicated `Shmoo_Plot` sheet (Green: Pass, Red: Fail, Grey: Marginal).

---

## 5. Quickstart Guide

### 5.1 Environment Activation
Activate the designated Conda environment:
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
```

### 5.2 Execute Matrix Test
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ucut_micro_cut
python ucut_control.py
```

### 5.3 Interactive Commands
- Type `a` and hit Enter: Automatically runs all 24 cases sequentially.
- Type a case index (e.g. `5`) and hit Enter: Evaluates the specific test case.
- Results are saved into an Excel file containing summary tables and the visual Shmoo Plot.
