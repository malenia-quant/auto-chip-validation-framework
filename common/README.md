# Common Hardware Drivers and DSP Reference Library

Author: mozial

---

## 1. Overview and Scope

This directory serves as a shared reference library containing standardized, object-oriented hardware drivers, signal-processing algorithms, and integration fixtures.
Components (`drivers/`, `analysis/`, `config/`, `tests/`) have been unified into `common/` to keep the workspace root clean while providing extensible building blocks for future chip characterization scripts.

---

## 2. Directory Structure

```text
common/
├── drivers/                   # Standardized Instrument Drivers Layer (PyVISA / TCP Socket)
│   ├── base_instrument.py     # BaseInstrument base class with retries and safe teardown
│   ├── generator_dg5072.py    # Rigol DG5072 waveform generator driver (volatile ARB upload)
│   ├── power_supply_dp2031.py # Rigol DP2031 programmable DC power supply driver (OVP/OCP guards)
│   ├── scope_sds5054.py       # Siglent SDS5054 DSO driver (IEEE 488.2 binary waveform transfers)
│   ├── dmm_keithley6500.py    # Keithley DMM6500 high-precision multimeter driver
│   └── exceptions.py          # Unified instrument driver exception hierarchy
│
├── analysis/                  # DSP and Math Algorithms Layer
│   ├── signal_processing.py   # Manchester PLL decoder (PSI5Decoder), bimodal histogram, glitch filters
│   └── data_cleaning.py       # IQR outlier rejection and statistical summarizer
│
├── config/                    # Externalized YAML Configuration Layer
│   ├── test_profile.yaml      # VISA resource strings, network IPs, and limits
│   └── loader.py              # Profile loader
│
├── tests/                     # Automated Regression Test Suite (27/27 Passing)
│   ├── conftest.py            # Hardware fixtures supporting --mock and --live execution
│   ├── test_integration_hil.py# Connection guards and configuration validation
│   ├── test_signal_analysis.py# Signal denoising, Manchester decoding, and statistics
│   └── test_ucut_task.py      # PSI5 voltage mapping & ARB synthesis tests
│
├── README_zh.md               # Chinese Reference Manual
└── README.md                  # [Current Document] English Reference Manual
```

---

## 3. Running Test Suites

```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
python -m pytest common/tests/ -v
# Output: 27 passed in ~2.6s
```
