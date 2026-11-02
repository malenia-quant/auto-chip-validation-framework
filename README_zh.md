# 汽车芯片与系统自动化验证工程平台

涵盖多款汽车芯片与车载电子子系统的工业级自动化测试、研发特性分析及排产数据处理工程。

作者：mozial

---

## 总体工程目录划分

```text
auto-chip-validation-framework/
│
├── crash_sensor/              # 【核心项目 1：碰撞传感器 (Crash Sensor) 综合工程平台】
│   ├── ft_production_test/    # 1. 碰撞传感器量产终测 (FT) 系统 (原 CrashSensor_FT 统一收敛)
│   ├── ucut_micro_cut/        # 2. uCut 毫秒级瞬态掉电复位测试专项 (原 dg5072_control 独立分立)
│   ├── dp2031_power_cycle/    # 3. DP2031 快慢上电电源循环测试专项 (原 dp2031_control 独立分立)
│   ├── centrifuge_acceleration/# 4. 离心机高 G 值动态标定与阶梯平台处理专项 (独立文件夹)
│   ├── ft_electrical_parameter/# 5. 芯片基础电学参数测量与非线性度分析专项
│   ├── zlgcan_file/           # 6. 周立功 ZLG CAN/CAN-FD 通信底层驱动 (保持官方原样) 与上层采集工具
│   ├── README_zh.md           # [crash_sensor 中文架构文档]
│   └── README.md              # [crash_sensor English Architecture Document]
│
├── tpms/                      # 【核心项目 2：胎压监测系统 (TPMS) 排产数据与测试工程】
│   ├── processor/             # 三级优先级智能打标引擎、多生产基地数据合并与校验器
│   ├── tests/                 # 完备的自动化测试套件与异常边角 Case 校验
│   ├── gui.py                 # 生产排产数据处理桌面交互软件
│   ├── README.md              # [tpms 详细中文业务规则与使用文档]
│   └── README_en.md           # [tpms English Architecture & User Guide]
│
├── common/                    # 【通用参考库：面向对象仪器驱动、DSP 与测试套件】
│   ├── drivers/               # 仪器驱动抽象层 (BaseInstrument, DG5072, DP2031, SDS5054, Keithley)
│   ├── analysis/              # 信号滤波去噪、曼彻斯特软解码与异常清洗算法
│   ├── config/                # 集中外置 YAML 配置文件
│   ├── tests/                 # 通用回归测试套件 (27/27 100% 通过)
│   ├── README_zh.md           # [common 中文参考手册]
│   └── README.md              # [common English Reference Manual]
│
├── requirements.txt           # 统一的环境依赖声明
└── .gitignore                 # 临时缓存与日志忽略配置
```

---

## 项目快速入口

| 业务板块 | 目录路径 | 说明 |
|---|---|---|
| **碰撞传感器量产终测 (FT)** | [crash_sensor/ft_production_test/](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_production_test) | 68 项 Master Spec V21 全流程自动化、示波器当前采样（10.03Ω）解码判定与 Word/Excel FT 报表。 |
| **uCut 瞬态掉电复位测试** | [crash_sensor/ucut_micro_cut/](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ucut_micro_cut) | DG5072 易失 ARB 波形无继电器热覆写注入、串口修调寄存器保持校验与 24 组 Shmoo Plot 矩阵。 |
| **DP2031 快慢上电电源循环** | [crash_sensor/dp2031_power_cycle/](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/dp2031_power_cycle) | Rigol DP2031 控制芯片快慢上电启动建立特性、过压过流保护及 CAN FD 报文连续监控。 |
| **离心机加速度动态标定** | [crash_sensor/centrifuge_acceleration/](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/centrifuge_acceleration) | 自适应阶梯平台提取、过渡态自动剔除、高稳态多时隙拟合灵敏度与线性度桌面软件。 |
| **芯片基础电学参数测量** | [crash_sensor/ft_electrical_parameter/](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/ft_electrical_parameter) | 万用表与示波器直流参数自动化扫描、满量程非线性度分析与历史 RMS 数据质量修复。 |
| **ZLG CAN 通信工具层** | [crash_sensor/zlgcan_file/](file:///d:/project_momo/auto-chip-validation-framework/crash_sensor/zlgcan_file) | 官方 SDK 保持原样，提供 USBCANFD-200U 纯读工具及零偏批量分析。 |
| **胎压监测系统 (TPMS)** | [tpms/](file:///d:/project_momo/auto-chip-validation-framework/tpms) | 三级优先级智能配置打标、多生产基地排产数据跨工厂汇总、桌面 GUI 与打包脚本。 |

---

## 运行环境

统一使用 Conda 虚拟环境：
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
```
测试套件执行：
```powershell
pytest tests -v
```
