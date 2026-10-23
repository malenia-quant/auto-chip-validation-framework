# Auto Chip & Module Validation Engineering Framework

Industrial-grade validation, testing, and production data processing workspace covering multiple automotive chips and subsystems.

Author: mozial

---

## Workspace Projects Architecture / 工程子项目划分

```text
auto-chip-validation-framework/
│
├── crash_sensor/              # [Core Project 1] Crash Sensor Comprehensive Validation Platform
│   ├── ft_production_test/    # 1. FT Mass-Production Test System (Unified from CrashSensor_FT)
│   ├── ucut_micro_cut/        # 2. uCut Micro-Interruption & Shmoo Plot Suite (Standalone from dg5072_control)
│   ├── dp2031_power_cycle/    # 3. DP2031 Power-Cycle & Power-On Ramp Verification (Standalone from dp2031_control)
│   ├── centrifuge_acceleration/# 4. Centrifuge High-G Calibration & Plateau Engine (Standalone Folder)
│   ├── ft_electrical_parameter/# 5. Electrical Parameter Characterization & Non-Linearity Math
│   ├── zlgcan_file/           # 6. ZLG CAN/CAN-FD Communication Drivers (Official SDK Kept Intact)
│   ├── README_zh.md           # [crash_sensor Architecture Document (Chinese)]
│   └── README.md              # [crash_sensor Architecture Document (English)]
│
├── tpms/                      # [Project 3] Tire Pressure Monitoring System Data & Production Processor
│   ├── processor/             # 3-tier tagging engine, multi-plant consolidator, config loader
│   ├── tests/                 # Unit & regression tests for corner cases and schema validation
│   ├── gui.py                 # Desktop GUI for production schedule consolidation
│   ├── README.md              # [中文使用与业务规则文档]
│   └── README_en.md           # [English Architecture & User Guide]
│
├── common/                    # [Shared Reference Library: OOP Drivers, DSP & Test Suites]
│   ├── drivers/               # Instrument driver abstraction layer (BaseInstrument, DG5072, DP2031, etc.)
│   ├── analysis/              # Signal filtering, Manchester decoding & data cleaning algorithms
│   ├── config/                # Centralized YAML configuration profiles
│   ├── tests/                 # Automated test suite (27/27 passing)
│   ├── README_zh.md           # [common Chinese Reference Manual]
│   └── README.md              # [common English Reference Manual]
│
├── requirements.txt           # Unified Python dependencies
└── .gitignore                 # Cache & log ignore rules
```

---

## Detailed Project Navigation / 各子项目独立文档入口

| 项目目录 | 业务定位与核心覆盖 | 独立文档链接 |
|---|---|---|
| **`crash_sensor/ft_production_test/`** | 碰撞传感器量产终测（FT）：基于 71 项 Master Spec V21 规范，自动化执行 Stream 1-7 测试流，包含示波器波形解码与标准报表生成。 | [中文文档](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_production_test/README_zh.md) \| [English](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_production_test/README.md) |
| **`crash_sensor/`** | 碰撞传感器研发与标定：包含 uCut 瞬态微跌落热覆写注入（`dg5072_ucut`）、离心机加速度阶梯平台提取与 ZLG CAN-FD 数据采集。 | [中文文档](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/README_zh.md) \| [English](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/README.md) |
| **`tpms/`** | 胎压监测系统生产与排产数据处理：三级优先级配置打标、多生产基地数据汇总及桌面应用打包。 | [中文文档](file:///d:/project_momo/auto-chip-validation-framework/tpms/README.md) \| [English](file:///d:/project_momo/auto-chip-validation-framework/tpms/README_en.md) |

---

## Quickstart / 运行环境

统一使用 Conda 虚拟环境：
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
```
各子项目的执行范例请查阅对应子项目根目录下的独立 `README`。
