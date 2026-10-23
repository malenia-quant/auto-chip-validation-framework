# CrashSensor 芯片基础电学参数自动化测试套件

作者: mozial

---

## 1. 模块定位与功能边界

本模块专用于汽车碰撞传感器芯片（Crash Sensor）的**基础电学参数（Electrical Parameters）测量、满量程特性分析与数据清洗**。

核心能力涵盖：
1. **综合电学参数自动化测量**：通过 [main/main_controller_simple.py](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_electrical_parameter/main/main_controller_simple.py) 联动万用表、示波器与 CANFD 采集盒，全自动扫描静态功耗、直流电压与通信电平。
2. **满量程折算与非线性度分析**：通过 [main/add_scale_and_nonlinearity.py](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_electrical_parameter/main/add_scale_and_nonlinearity.py) 计算多工作点下的灵敏度与满量程非线性度偏差。
3. **测试数据汇流与报表整合**：通过 [main/consolidate_results.py](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_electrical_parameter/main/consolidate_results.py) 汇总合并不同批次测试结果。
4. **历史数据质量修复**：通过 [main/repair_20260517_rms.py](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_electrical_parameter/main/repair_20260517_rms.py) 重算零偏 RMS 与波动率指标。

> [!NOTE]
> **相关专项测试独立分立提示**：
> - **uCut 短时间掉电微中断容限测试**（原 `dg5072_control`）已独立分立至 [crash_sensor/ucut_micro_cut/](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ucut_micro_cut)；
> - **Rigol DP2031 快慢上电循环冲击测试**（原 `dp2031_control`）已独立分立至 [crash_sensor/dp2031_power_cycle/](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/dp2031_power_cycle)。

---

## 2. 模块目录结构

```text
crash_sensor/ft_electrical_parameter/
├── main/                           # 综合电学参数测试主控与数据汇流
│   ├── main_controller_simple.py   # CANFD 采集、示波器参数提取与零偏计算综合主控
│   ├── consolidate_results.py      # 批次测试结果汇总与报表生成器
│   ├── add_scale_and_nonlinearity.py # 满量程折算与非线性度计算
│   └── repair_20260517_rms.py      # 历史测试数据 RMS 补充计算与修复脚本
├── simple_version/                 # 简易万用表与示波器仪表测量脚本
│   ├── sds5054.py                  # 示波器参数快速抓取
│   └── dmm6500.py                  # 万用表静态电流与阻抗测量
├── README_zh.md                    # [当前文档] 中文技术与操作手册
└── README.md                       # English Technical & Operation Manual
```

---

## 3. ZLG CAN 驱动多路径自适应探测机制

在 `main_controller_simple.py` 和 `repair_20260517_rms.py` 中，内置动态路径探测机制，自动关联同级 `crash_sensor/zlgcan_file`，彻底避免硬编码绝对路径：

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

## 4. 快速启动与操作指引

### 4.1 环境准备
激活专用 Conda 虚拟环境：
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
```

### 4.2 启动电参数综合测量循环
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ft_electrical_parameter\main
python main_controller_simple.py
```

### 4.3 执行满量程非线性度分析
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ft_electrical_parameter\main
python add_scale_and_nonlinearity.py
```
