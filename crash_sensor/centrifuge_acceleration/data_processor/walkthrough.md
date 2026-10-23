# CrashSensor 离心机测试数据自动化处理软件 — 交付与验证报告 (最终工业量产版)

## 一、 项目工程概况

根据原厂需求文档（图 1/8 至图 8/8）与工业量产实操边界，已在 `ft_centrifuge_data_processor` 中完成了基于 CG904 碰撞传感器的离心机自动化处理软件开发与测试用例验证。

- **Conda 虚拟环境**：`D:\project_momo\project_venv\venv_crashsensor` (Python 3.11.15)
- **生产代码目录**：[data_processor/](file:///d:/project_momo/crash_sensor/ft_centrifuge_data_processor/data_processor)
- **原始参考资产**：`original_scripts/`（保持只读，底层协议无缝继承）
- **数据输出规范**：`Data_Consolidation/`（规范归档目录树）
- **测试套件**：[tests/](file:///d:/project_momo/crash_sensor/ft_centrifuge_data_processor/tests)（21 项测试全部通过）

---

## 二、 关键技术优化与深水区细节锁定

### 1. 消除 max/min 极性掩盖陷阱，建立工装物理极性强校验门禁
- **隐患识别**：首测时若发生工装接反、器件插反导致 Axis1 与 Axis2 同正或同负，单纯使用 `max(ax1, ax2)` 和 `min(ax1, ax2)` 会掩盖物理极性错误，强行算出一个正的 Span 并通过标定门禁。
- **工程落地**：在 `ResultConsolidator.classify_devices` 中严格依据工装类别进行极性门禁拦截：
  - **工装 A**：强制要求 $\text{Axis1} > 0$ 且 $\text{Axis2} < 0$；
  - **工装 B**：强制要求 $\text{Axis2} > 0$ 且 $\text{Axis1} < 0$；
  - 若符号不符或同向，立即拦截归入 `AbnormalFunction_List`（标记为“物理极性反转/工装异常”），严禁送入标定计算。

### 2. 11 位 Hex 器件码精确位宽对齐
- **重构函数**：`CentrifugeCANParser.format_11digit_device_code`。
- **消除兜底截断**：废弃 `[:11].zfill(11)` 模糊逻辑，改用严格位掩码格式化：
  - 产线标准 `29_28_27`：`CFG29<15:0>`（4位 Hex） + `CFG28<15:0>`（4位 Hex） + `CFG27<11:0>`（3位 Hex）$= 11$ 位 Hex（对齐示例 `00030020001`）；
  - 标称标准 `27_28_29`：`CFG27<15:0>`（4位 Hex） + `CFG28<15:0>`（4位 Hex） + `CFG29<11:0>`（3位 Hex）$= 11$ 位 Hex。

### 3. 清理模拟数据硬编码，全面打通动态时序提取管道
- **动态波形提取**：在 `CentrifugeCANParser` 中实现 `extract_dynamic_acceleration_series`，支持从 64 字节 CAN 数据流或多列工位时序表中提取各通道动态波形。
- **稳态均值计算**：在 `CentrifugeProcessor` 中实现 `compute_slot_steady_means`，结合工装 A/B 属性，运用边沿识别、前 30 帧过渡态过滤与 $\le 50$ 点稳态截取计算真实均值。
- **GUI 与 CLI 无缝对接**：在 `gui.py`（首测与定向复测）与 `main.py`（CLI 批处理）中彻底移除演示硬编码，优先使用实测提取的动态均值；针对无波形的纯 ID 扫描文件提供友好提示并保底运行。

### 4. 有符号数基准与 Span 硬件门禁
- 严格继承 `>512 则 -1024` 补码还原标准，确保 $\text{Output}_{(+240\text{g})}$ 与 $\text{Output}_{(-240\text{g})}$ 具备真实物理正负极性。
- 设立合理性门禁 $\text{Span} \in [S_{\min}, S_{\max}]$（默认 $[600, 3600]$），彻底拦截断路、接触抖动与除零/溢出风险。
- 标定公式核心分子为 $961 \times 2^{20} = 1,007,681,536$，四舍五入转 16 进制写入 6 处地址，并将 `CFG22<13>` 置 1 开启 TRIM 使能。

### 5. 双阶段 CAN 报文拓扑：前 24 条 0x1XX (ID读取) 与后续 0x25X (动态加速度)
- **协议依据**：严格遵循需求原件**图 6/8 与图 7/8 第 4 节**规范。
- **前 24 条报文 (ID 扫描阶段)**：
  - `MAKE_CAN_ID(HEX)` 依次为 `0x111` ~ `0x146` (共 24 个槽位)；
  - 每行 64 字节，包含 32 组 `[02, val]`，用于读取 16 个配置寄存器 (CFG26~CFG33)，解析芯片 UID 与 11 位器件码。
- **第 25 条报文起 (离心机运转采集阶段)**：
  - `MAKE_CAN_ID(HEX)` 变为以供电板为单位的 `0x25X` 格式：`0x25A` (#1板), `0x25B` (#2板), `0x25C` (#3板), `0x25D` (#4板)；
  - `DATA(HEX)` 为 48 字节加速度时序数据：每板 6 路 PSI5 通道，每通道 3 个 timeslot，每 timeslot 占 2 字节（两两一组合并，考虑 3 的倍数数据组，timeslot1 承载 10-bit 补码加速度，后接 12 字节保留位）；
- **引擎优化**：
  - `CentrifugeCANParser.parse_can_raw_csv`：解析前 24 条 `0x1XX` 提取器件信息，遇到 `0x25X` 自动跳过；
  - `CentrifugeCANParser.extract_dynamic_acceleration_series`：跳过前 24 条寄存器行，精确解包 `0x25A`~`0x25D` 的各通道动态加速度波形！

---

## 三、 测试用例执行结果 (22 / 22 PASSED)

使用 Conda 环境 `D:\project_momo\project_venv\venv_crashsensor\python.exe` 运行 pytest：

```
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor
collected 21 items

tests/test_calibration_processor.py::TestCalibrationProcessor::test_calculate_adj_normal PASSED [  4%]
tests/test_calibration_processor.py::TestCalibrationProcessor::test_calculate_adj_within_16bit_range PASSED [  9%]
tests/test_calibration_processor.py::TestCalibrationProcessor::test_span_gate_protection PASSED [ 14%]
tests/test_calibration_processor.py::TestCalibrationProcessor::test_cfg22_trim_enable_bit PASSED [ 19%]
tests/test_calibration_processor.py::TestCalibrationProcessor::test_mtp_template_replacement PASSED [ 23%]
tests/test_can_data_parser.py::TestCentrifugeCANParser::test_global_slot_index_mapping PASSED [ 28%]
tests/test_can_data_parser.py::TestCentrifugeCANParser::test_4in1_group_slots_distribution PASSED [ 33%]
tests/test_can_data_parser.py::TestCentrifugeCANParser::test_4in1_filename_builder PASSED [ 38%]
tests/test_can_data_parser.py::TestCentrifugeCANParser::test_4in1_filename_with_ng_placeholder PASSED [ 42%]
tests/test_can_data_parser.py::TestCentrifugeCANParser::test_4in1_filename_all_ng PASSED [ 47%]
tests/test_can_data_parser.py::TestCentrifugeCANParser::test_signed_acceleration_twos_complement PASSED [ 52%]
tests/test_can_data_parser.py::TestCentrifugeCANParser::test_64byte_clean_bridge_payload_inheritance PASSED [ 57%]
tests/test_centrifuge_processor.py::TestCentrifugeProcessor::test_steady_state_cropping PASSED [ 61%]
tests/test_centrifuge_processor.py::TestCentrifugeProcessor::test_edge_detection_and_mean_calculation PASSED [ 66%]
tests/test_centrifuge_processor.py::TestCentrifugeProcessor::test_staircase_plot_creation PASSED [ 71%]
tests/test_integration.py::TestEndToEndPipeline::test_full_pipeline_flow PASSED [ 76%]
tests/test_result_consolidator.py::TestResultConsolidatorAndMerger::test_fixture_ab_polarity_alignment PASSED [ 80%]
tests/test_result_consolidator.py::TestResultConsolidatorAndMerger::test_data_merger_stitch_logic PASSED [ 85%]
tests/test_result_consolidator.py::TestResultConsolidatorAndMerger::test_tri_lists_classification_and_export PASSED [ 90%]
tests/test_result_consolidator.py::TestResultConsolidatorAndMerger::test_rework_to_normal_yield_closure PASSED [ 95%]
tests/test_result_consolidator.py::TestResultConsolidatorAndMerger::test_fixture_polarity_inversion_gate PASSED [100%]

============================= 21 passed in 2.04s ==============================
```

---

## 四、 快速启动指引

### 1. 启动 GUI 交互控制台
```powershell
& "D:\project_momo\project_venv\venv_crashsensor\python.exe" "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor\main.py" --mode gui
```

### 2. 执行 CLI 命令行批处理
```powershell
& "D:\project_momo\project_venv\venv_crashsensor\python.exe" "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor\main.py" --mode cli --lot LOT1 --axis1 "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_conlidation\Centrifuge1\Data_Consolidation\2026\09\Normal_Lot\LOT1\CrashSensor_Centrifuge1_OriginalData_Axis1_20260907_120000.csv" --axis2 "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_conlidation\Centrifuge1\Data_Consolidation\2026\09\Normal_Lot\LOT1\CrashSensor_Centrifuge1_OriginalData_Axis2_20260907_120000.csv" --output "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_conlidation"
```

### 3. 分步独立执行核心脚本进行验证 (step_by_step_verify.py)
```powershell
# 验证 Step 1: CAN 报文解包、UID 解码与 4-in-1 芯片合并命名
& "D:\project_momo\project_venv\venv_crashsensor\python.exe" "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor\step_by_step_verify.py" --step 1

# 验证 Step 2: 动态加速度边沿检测与过渡态裁剪 (≤50点稳态均值提取)
& "D:\project_momo\project_venv\venv_crashsensor\python.exe" "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor\step_by_step_verify.py" --step 2

# 验证 Step 3: 1.5倍量程折算、Span 硬件门禁拦截与 MTP 模板替换
& "D:\project_momo\project_venv\venv_crashsensor\python.exe" "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor\step_by_step_verify.py" --step 3

# 验证 Step 4: 首测双轴聚合、工装极性门禁与三大清单导出
& "D:\project_momo\project_venv\venv_crashsensor\python.exe" "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor\step_by_step_verify.py" --step 4

# 验证 Step 5: 模式 B 脱机补测数据缝合 (Data Merger) 与良率闭环
& "D:\project_momo\project_venv\venv_crashsensor\python.exe" "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor\step_by_step_verify.py" --step 5

# 全量一键顺序执行 Steps 1 ~ 5
& "D:\project_momo\project_venv\venv_crashsensor\python.exe" "d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor\step_by_step_verify.py" --step all
```
