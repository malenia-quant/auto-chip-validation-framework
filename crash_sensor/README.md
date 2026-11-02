# Crash Sensor Validation and Calibration Platform

Author: mozial

---

## 1. Modular Directory Structure

To clearly decouple production testing, micro-cut fault injection, power-cycle stress, centrifuge calibration, and electrical characterization, all crash sensor-related workflows are categorized inside `crash_sensor/`:

```text
crash_sensor/
│
├── ft_production_test/         # [Module 1: FT Production Test] (Categorized from CrashSensor_FT)
│   ├── core/                  # Master test specs (68 items), hardware layer, Word/Excel reports
│   ├── tasks/                 # 5 Test Streams (DC static, protocol PHY, interactive, init, LVD)
│   ├── ft_gui_main.py         # Production bench graphical test interface
│   ├── ft_master_flow.py      # Automated pipeline orchestrator
│   ├── sds5054_task.py        # Siglent SDS5054 waveform capture & parameter extraction
│   ├── dg5072_task.py         # Rigol DG5072 power timing generator
│   └── ni_task.py             # NI-DAQ data acquisition & switch matrix
│
├── ucut_micro_cut/            # [Module 2: Micro-Cut Fault Injection] (Standalone from dg5072_control)
│   ├── dg5072_ucut.py         # 16-bit volatile ARB generation and RAM hot-swapping
│   ├── pyserial_ucut.py       # Pre-fault trimming command injection & register verification
│   ├── sds5054_ucut.py        # Dual-channel acquisition and transient capture
│   └── ucut_control.py        # 24-case matrix test orchestrator & Shmoo plot Excel generator
│
├── dp2031_power_cycle/        # [Module 3: DP2031 Power-Cycle & Power-On Ramp] (Standalone from dp2031_control)
│   ├── dp2031_control.py      # Dual-channel control: CH1 bias, CH2 high/low transitions & CANFD logging
│   └── power_cycle_collect.py # Automated long-term cyclical stress testing (10s run + 3min idle countdown)
│
├── centrifuge_acceleration/   # [Module 4: Centrifuge High-G Calibration] (Standalone folder)
│   ├── data_processor/        # Plateau detection engine (CentrifugeProcessor) & desktop GUI
│   ├── data_conlidation/      # MTP calibration dataset matching & polynomial curve fitting
│   └── tests/                 # Unit and regression test suites (36/36 passing)
│
├── ft_electrical_parameter/   # [Module 5: Electrical Parameter Characterization]
│   ├── main/                  # CANFD acquisition, oscilloscope parameter extraction, zero-bias math
│   │   ├── main_controller_simple.py   # Test orchestrator
│   │   ├── add_scale_and_nonlinearity.py # Non-linearity and full-scale conversion
│   │   ├── consolidate_results.py      # Batch test aggregator
│   │   └── repair_20260517_rms.py      # Historical dataset repair & RMS calculation
│   └── simple_version/        # Standalone DMM and oscilloscope measurement scripts
│
├── basic_centrifuge/          # [Module 6: Basic Centrifuge Processing & Sensor Analytics]
│   ├── gui.py                 # Two-step interactive desktop app (Step1 split / Step2 plateau & performance / TXT batch)
│   ├── sensor_processor1.py   # Step 1: Raw test data decoding, two's complement conversion & channel grouping
│   ├── sensor_processor2.py   # Step 2: Convolution filtering, dual-threshold edge detection & non-linearity/RMS noise
│   └── device_code_scan.py    # CG904 batch test CAN payload decoding & chip ID / production date calculation
│
└── zlgcan_file/               # [Module 7: ZLG CAN / CAN-FD Communications] (Official SDK kept intact)
    ├── zlgcan_python_251211/  # Vendor DLL drivers and examples (zlgcan.py, kerneldlls)
    ├── zcanpro_canfd200u.py   # USBCANFD-200U lightweight logger (ISO CAN-FD 1M/2M, 120-ohm enabled)
    └── pz_zero_bias.py        # Zero bias batch analytics & chart generation
```

---

## 2. ZLG CAN Driver Path Resolution

`zlgcan_file` remains untouched at `crash_sensor/zlgcan_file`. The modules adopt an upward relative candidate path detection mechanism:
```python
candidates = [
    os.path.join(workspace_root, "zlgcan_file"),
    os.path.abspath(os.path.join(current_dir, "..", "zlgcan_file")),
    os.path.abspath(os.path.join(current_dir, "..", "..", "..", "zlgcan_file")),
    r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file",
]
```
- `centrifuge_acceleration/` automatically resolves to `crash_sensor/zlgcan_file`.
- `dp2031_power_cycle/` locates sibling `crash_sensor/zlgcan_file`.
- `ft_electrical_parameter/` resolves to unified drivers.

---

## 3. Quickstart Commands

```powershell
# Activate dedicated Conda environment
conda activate D:\project_momo\project_venv\venv_crashsensor

# 1. Run FT Production GUI
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ft_production_test
python ft_gui_main.py

# 2. Run 24-Case Automated uCut Test Matrix
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ucut_micro_cut
python ucut_control.py

# 3. Run DP2031 Power-Cycle & Power-On Ramp Verification
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\dp2031_power_cycle
python dp2031_control.py

# 4. Launch Centrifuge Acceleration Processor GUI
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor
python main.py --mode gui

# 5. Run Electrical Parameter Sweep
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ft_electrical_parameter\main
python main_controller_simple.py

# 6. Run CAN-FD 200U Logger
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file
python zcanpro_canfd200u.py

# 7. Launch Basic Centrifuge Processing & Analytics (basic_centrifuge)
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\basic_centrifuge
# Launch two-step GUI (Step 1 raw split + Step 2 plateau/non-linearity/RMS)
python gui.py

# Or run CG904 batch CAN payload decoding & chip ID / date parser
python device_code_scan.py
```
