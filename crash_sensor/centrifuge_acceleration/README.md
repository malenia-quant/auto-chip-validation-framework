# Crash Sensor Centrifuge Acceleration Calibration and Processing Suite

Author: mozial

---

## 1. Overview and Engineering Scope

This module is a production-grade automated calibration and data consolidation system for automotive crash sensor ICs (e.g., CG904 series) tested under high-G centrifugal acceleration.

During manufacturing and qualification testing, devices are mounted onto a precision centrifuge table undergoing multi-step rotation (generating 0G, 80G, 160G acceleration plateaus). This system captures raw CAN-FD data streams, parses 24-slot payloads, extracts steady-state plateaus while rejecting transition ramps, performs 1.5x range conversion with Span Gate safety checks, updates MTP trimming parameters, and consolidates initial/rework test lots.

---

## 2. Directory Structure

```text
crash_sensor/centrifuge_acceleration/
├── data_processor/                  # Core processing engine and execution entrypoints
│   ├── main.py                      # Dual-mode (CLI / GUI) application entrypoint
│   ├── gui.py                       # Industrial Tkinter GUI console with high-DPI scaling
│   ├── config/                      # Hardware limits and configuration (settings.ini)
│   ├── processor/                   # Core algorithmic processing layers
│   │   ├── can_collector.py         # ZLG CAN hardware streaming adapter with auto-discovery
│   │   ├── can_data_parser.py       # 24-channel unpacker, UID decoding, and 4-in-1 grouping
│   │   ├── centrifuge_processor.py  # Plateau segmentation and transition transient filter
│   │   ├── calibration_processor.py # 1.5x scaling, Span Gate, sensitivity math, MTP templates
│   │   └── result_consolidator.py   # Dual-axis alignment, polarity checks, and report export
│   ├── walkthrough.md               # Detailed verification walk-through manual
│   └── implementation_plan.md       # Architectural specifications
├── data_conlidation/                # Archived datasets and batch calibration outputs
│   └── Centrifuge1/                 # Centrifuge machine #1 raw data and cleaned results
├── tests/                           # Complete regression & unit test suite (36/36 passing)
├── README_zh.md                     # Chinese Technical and Operation Manual
└── README.md                        # [Current Document] English Technical and Operation Manual
```

---

## 3. Data Flow Architecture

```text
  [Centrifuge Turntable] ---(CAN FD 1M/2M)---> [USBCANFD-200U Hardware]
                                                       |
                                                       v
                                          [processor/can_collector.py]
                                          (Resolves crash_sensor/zlgcan_file)
                                                       |
                                                       v
                                          [processor/can_data_parser.py]
                                          - Decodes 0x25A~0x25D frames
                                          - 24-Slot mapping & 4-in-1 grouping
                                                       |
                                                       v
                                          [processor/centrifuge_processor.py]
                                          - Plateau edge detection (0G/80G/160G)
                                          - Crops transients, averages steady states
                                                       |
                                                       v
                                          [processor/calibration_processor.py]
                                          - 1.5x scaling & Span Gate verification
                                          - Sensitivity math & MTP Hex replacement
                                                       |
                                                       v
                                          [processor/result_consolidator.py]
                                          - Data Merger stitches initial/rework runs
                                          - Exports PASS/FAIL/REWORK lot manifests
```

---

## 4. ZLG CAN Driver Path Resolution

`processor/can_collector.py` implements an upward relative directory probe to dynamically locate `crash_sensor/zlgcan_file` without manual adjustments to the system `PATH`:

```python
candidates = [
    os.path.join(workspace_root, "zlgcan_file"),
    os.path.abspath(os.path.join(current_dir, "..", "..", "..", "zlgcan_file")),
    r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file",
    os.path.abspath(os.path.join(current_dir, "..", "..", "zlgcan_file")),
    os.path.abspath(os.path.join(current_dir, "..", "zlgcan_file")),
]
```

Verified via pytest: `is_available()` returns `(True, "ZLG 驱动与脚本已就绪")` and attaches to the driver environment.

---

## 5. Quickstart Guide

### 5.1 Environment Activation
Activate the designated Conda environment:
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
```

### 5.2 Launch Graphical Interface (GUI)
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor
python main.py --mode gui
# Or run: python gui.py
```

### 5.3 Run Headless CLI Batch Pipeline
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor
python main.py --mode cli --lot LOT1 `
  --axis1 "..\data_conlidation\Centrifuge1\Data_Consolidation\2026\09\Normal_Lot\LOT1\CrashSensor_Centrifuge1_OriginalData_Axis1_20260907_120000.csv" `
  --axis2 "..\data_conlidation\Centrifuge1\Data_Consolidation\2026\09\Normal_Lot\LOT1\CrashSensor_Centrifuge1_OriginalData_Axis2_20260907_120000.csv" `
  --output "..\data_conlidation"
```

### 5.4 Execute Test Suites
```powershell
cd D:\project_momo\auto-chip-validation-framework
D:\project_momo\project_venv\venv_crashsensor\python.exe -m pytest crash_sensor\centrifuge_acceleration\tests\ -v
```
