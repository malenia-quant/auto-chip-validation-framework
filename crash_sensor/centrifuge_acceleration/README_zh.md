# CrashSensor 离心机加速度标定与数据分析系统

作者: mozial

---

## 1. 模块定位与核心功能

本模块为汽车级碰撞传感器芯片（Crash Sensor, CG904 等型号）离心机动态高 G 值加速度标定与数据后处理系统。

在芯片量产与特性测试中，通过将待测芯片放置于精密离心机上，经历阶梯式转速旋转（产生 0G、80G、160G 等阶梯离心力），记录芯片两轴（Axis1, Axis2）的动态响应。本模块负责实时采集 CAN 数据流、解析 24 通道数据报文、自动识别与剔除旋转过渡态、提取高精稳态区间均值、执行 1.5 倍量程折算与 Span 硬件门禁拦截，生成芯片 MTP 烧录参数，并自动化缝合首测与补测数据闭环。

---

## 2. 模块目录结构

```text
crash_sensor/centrifuge_acceleration/
├── data_processor/                  # 离心机核心处理引擎与应用入口
│   ├── main.py                      # CLI 批处理与 GUI 控制台双模主程序入口
│   ├── gui.py                       # 高分屏 Tkinter/ttk 工业级图形控制台 (含中英文双语)
│   ├── config/                      # 标定限额与系统参数配置 (settings.ini)
│   ├── processor/                   # 核心算法处理引擎层
│   │   ├── can_collector.py         # ZLG CAN 数据采集控制器 (自适应定位 zlgcan_file)
│   │   ├── can_data_parser.py       # 24 通道报文解包、UID 解码与 4-in-1 芯片合并命名
│   │   ├── centrifuge_processor.py  # 动态加速度阶梯平台识别与过渡态裁剪算法
│   │   ├── calibration_processor.py # 1.5倍折算、Span 硬件门禁、标定系数与 MTP 模板替换
│   │   └── result_consolidator.py   # 双轴聚合、工装极性门禁、数据缝合与三大清单导出
│   ├── walkthrough.md               # 离心机模块详细测试与验证手册
│   └── implementation_plan.md       # 架构设计与量产实施方案
├── data_conlidation/                # 离心机数据归档与批次结果存储目录
│   └── Centrifuge1/                 # 1号离心机原始与清洗聚合结果
├── tests/                           # 完备的单元测试与集成测试套件 (36/36 100% 通过)
├── README_zh.md                     # [当前文档] 中文技术与操作手册
└── README.md                        # English Technical & Operation Manual
```

---

## 3. 系统架构与数据流管道

```text
  [离心机旋转机台] ----(CAN FD 1M/2M)----> [USBCANFD-200U 盒]
                                                  |
                                                  v
                                      [processor/can_collector.py]
                                      (自适应定位 crash_sensor/zlgcan_file)
                                                  |
                                                  v
                                      [processor/can_data_parser.py]
                                      - 提取 0x25A~0x25D 报文
                                      - 24-Slot 映射与 4-in-1 芯片分组
                                                  |
                                                  v
                                      [processor/centrifuge_processor.py]
                                      - 自适应多级转速阶梯检测 (0G/80G/160G)
                                      - 裁剪过渡态波动，提取稳态均值
                                                  |
                                                  v
                                      [processor/calibration_processor.py]
                                      - 1.5倍量程折算与 Span Gate 门禁拦截
                                      - 敏感度标定与 MTP 烧录 Hex 生成
                                                  |
                                                  v
                                      [processor/result_consolidator.py]
                                      - Data Merger 首测/补测良率闭环
                                      - 导出 PASS/FAIL/REWORK 三大清单
```

---

## 4. ZLG CAN 驱动多路径自适应探测机制

本模块通过 `can_collector.py` 内部内置的多路径向上回溯算法，自动探查并加载位于 `crash_sensor/zlgcan_file` 的官方 SDK 及其 DLL 依赖，无需手动改动系统环境变量：

```python
# 候选路径探测列表
candidates = [
    os.path.join(workspace_root, "zlgcan_file"),
    os.path.abspath(os.path.join(current_dir, "..", "..", "..", "zlgcan_file")),
    r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file",
    os.path.abspath(os.path.join(current_dir, "..", "..", "zlgcan_file")),
    os.path.abspath(os.path.join(current_dir, "..", "zlgcan_file")),
]
```

经集成测试与硬件模拟校验，系统自动命中 `crash_sensor/zlgcan_file`，`is_available()` 校验 100% 通过。

---

## 5. 快速启动与操作指引

### 5.1 环境准备
激活专用 Conda 虚拟环境：
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
```

### 5.2 启动桌面图形控制台 (GUI)
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor
python main.py --mode gui
# 或直接运行: python gui.py
```

### 5.3 运行 CLI 批处理全流程
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor
python main.py --mode cli --lot LOT1 `
  --axis1 "..\data_conlidation\Centrifuge1\Data_Consolidation\2026\09\Normal_Lot\LOT1\CrashSensor_Centrifuge1_OriginalData_Axis1_20260907_120000.csv" `
  --axis2 "..\data_conlidation\Centrifuge1\Data_Consolidation\2026\09\Normal_Lot\LOT1\CrashSensor_Centrifuge1_OriginalData_Axis2_20260907_120000.csv" `
  --output "..\data_conlidation"
```

### 5.4 执行单元与集成测试套件
```powershell
cd D:\project_momo\auto-chip-validation-framework
D:\project_momo\project_venv\venv_crashsensor\python.exe -m pytest crash_sensor\centrifuge_acceleration\tests\ -v
# 输出: 36 passed in 10.92s
```
