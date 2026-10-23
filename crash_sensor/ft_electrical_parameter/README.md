# Crash Sensor Electrical Parameter Characterization Suite

Author: mozial

---

## 1. Overview and Core Scope

This module is dedicated to automated **electrical parameter characterization, full-scale linearity evaluation, and statistical data cleaning** for automotive crash sensor ICs.

Key capabilities include:
1. **Automated Electrical Parameter Sweep**: Coordinates digital multimeters, oscilloscopes, and CANFD loggers via [main/main_controller_simple.py](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_electrical_parameter/main/main_controller_simple.py) to measure supply current, quiescent power, and communication levels.
2. **Full-Scale Conversion & Non-Linearity Math**: Computes sensitivity deviations and non-linearity metrics using [main/add_scale_and_nonlinearity.py](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_electrical_parameter/main/add_scale_and_nonlinearity.py).
3. **Batch Consolidation & Reporting**: Aggregates multi-lot measurement runs via [main/consolidate_results.py](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_electrical_parameter/main/consolidate_results.py).
4. **Historical Dataset Repair**: Recomputes zero bias RMS and fluctuation metrics via [main/repair_20260517_rms.py](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_electrical_parameter/main/repair_20260517_rms.py).

> [!NOTE]
> **Standalone Testing Modules Reference**:
> - **uCut Short-Duration Power-Cut Testing** (formerly `dg5072_control`) is now independently located in [crash_sensor/ucut_micro_cut/](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ucut_micro_cut);
> - **Rigol DP2031 Power Cycling & Fast/Slow Ramp Testing** (formerly `dp2031_control`) is now independently located in [crash_sensor/dp2031_power_cycle/](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/dp2031_power_cycle).

---

## 2. Directory Structure

```text
crash_sensor/ft_electrical_parameter/
├── main/                           # Comprehensive test orchestrator and result consolidation
│   ├── main_controller_simple.py   # CANFD acquisition, oscilloscope parameter extraction, zero-bias math
│   ├── consolidate_results.py      # Batch test aggregator and report generator
│   ├── add_scale_and_nonlinearity.py # Full-scale conversion and non-linearity analysis
│   └── repair_20260517_rms.py      # Historical test dataset repair and RMS recalculation
├── simple_version/                 # Baseline standalone instrument scripts
│   ├── sds5054.py                  # Direct oscilloscope measurement
│   └── dmm6500.py                  # DMM quiescent current and resistance measurement
├── README_zh.md                    # Chinese Technical and Operation Manual
└── README.md                       # [Current Document] English Technical and Operation Manual
```

---

## 3. ZLG CAN Driver Path Resolution

Scripts inside `main/` dynamically locate `crash_sensor/zlgcan_file` without hardcoded path dependencies:

```python
workspace_root = os.path.dirname(project_root)
candidate_zlgcan_dirs = [
    os.path.join(workspace_root, "zlgcan_file"),
    r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file",
    os.path.join(project_root, "zlgcan_file"),
]
zlgcan_dir = next((d for d in candidate_zlgcan_dirs if os.path.isdir(d)), candidate_zlgcan_dirs[0])
```

---

## 4. Quickstart Guide

### 4.1 Environment Activation
Activate the designated Conda environment:
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
```

### 4.2 Start Electrical Parameter Sweep
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ft_electrical_parameter\main
python main_controller_simple.py
```

### 4.3 Execute Non-Linearity Analysis
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ft_electrical_parameter\main
python add_scale_and_nonlinearity.py
```
