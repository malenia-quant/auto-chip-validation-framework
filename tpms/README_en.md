# TPMS Vehicle Classification Tagger & Cross-Facility Production Consolidator

Author: mozial

## 1. Overview
The `tpms/` project is an automated industrial data processor tailored for automotive manufacturing and TPMS (Tire Pressure Monitoring System) engineering. It handles monthly production scheduling plans across manufacturing facilities, labels vehicle TPMS equipment configurations based on multi-tier priority rules, and consolidates multi-plant production matrices into standard executive Excel spreadsheets.

---

## 2. Three-Tier Labeling Hierarchy

The labeling engine evaluates each line item in accordance with the following precedence:

1. **Priority 1 (Export & Territory Matching)**:
   - Matches against `国家列表.xlsx` and global keyword patterns (e.g. GCC, Europe, RHD, Australia, etc.).
   - If matched, the `配置` (Configuration) field is immediately marked as **`出口` (Export)**.
2. **Priority 2 (TPMS Configuration Matrix Matching)**:
   - Evaluates against `车型分类规范.xlsx` (with sheets corresponding to Direct TPMS, Indirect TPMS, Tire Burst Protection, Standalone ECU, etc.).
   - Matches vehicle series code patterns and suffixes (e.g., `-10`, `-10型`).
   - Appends the corresponding specification sheet name (e.g., `爆胎`, `直接式`).
3. **Priority 3 (Default Fallback)**:
   - Rows without priority 1 or 2 matches leave the configuration cell blank.

---

## 3. Directory Structure

```text
tpms/
├── data/                               # Reference specifications and test dataset
│   ├── 车型分类规范.xlsx               # Configuration specification workbook
│   ├── 国家列表.xlsx                   # Export country/region reference database
│   ├── raw/                            # Facility input files (*-月计划 *.xlsx)
│   └── output/                         # Processed and consolidated workbooks
├── processor/                          # Core business logic
│   ├── tagger.py                       # 3-tier precedence tagging engine
│   ├── consolidator.py                 # Multi-plant consolidator with timestamp footers
│   └── config_manager.py               # Specification loader and schema validator
├── tests/                              # Pytest test suites (100% pass)
│   ├── test_tagger.py
│   ├── test_consolidator.py
│   ├── test_corner_cases.py
│   └── test_gui_smoke.py
├── gui.py                              # Desktop graphical application (Tkinter)
├── main.py                             # Command-line entry point
├── build_exe.bat                       # PyInstaller packaging script
└── requirements.txt                    # Python dependencies (openpyxl, pandas, pytest)
```

---

## 4. Execution & Quickstart

### Launch Desktop GUI
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
cd D:\project_momo\auto-chip-validation-framework\tpms
python gui.py
```

### Run Batch Processing via CLI
```powershell
python main.py --raw-dir ./data/raw --output-dir ./data/output
```

### Execute Test Suite
```powershell
pytest tests -v
```
