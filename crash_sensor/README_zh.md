# Crash Sensor (碰撞传感器芯片) 综合验证工程平台

作者: mozial

---

## 1. 架构总览与模块划分

为清晰解耦量产终测、瞬态掉电复位、电源循环冲击与基础电参数分析，所有与碰撞传感器相关的模块已在 `crash_sensor/` 目录下完成清晰的独立分立与归类：

```text
crash_sensor/
│
├── ft_production_test/         # 【模块 1：量产终测 FT 系统】(原 CrashSensor_FT 规范化归类)
│   ├── core/                  # 71 项测试规格定义 (test_specs.py)、硬件抽象层与 Word/Excel 报表生成器
│   ├── tasks/                 # 5 大测试流 (Stream 1~7: 直流静态/协议稳态/交互/初始化时序/欠压复位)
│   ├── ft_gui_main.py         # 产线测试台桌面交互测试软件
│   ├── ft_master_flow.py      # 自动化测试流水线总调度主控
│   ├── sds5054_task.py        # 鼎阳 SDS5054 示波器量产波形与参数提取
│   ├── dg5072_task.py         # Rigol DG5072 信号源供电时序控制
│   └── ni_task.py             # NI-DAQ 数据采集与开关矩阵调度
│
├── ucut_micro_cut/            # 【模块 2：uCut 毫秒级瞬态掉电复位测试】(原 dg5072_control 独立分立)
│   ├── dg5072_ucut.py         # 16-bit 易失 ARB 波形合成与 RAM 4 秒无缝热覆写短时间掉电注入
│   ├── pyserial_ucut.py       # 修调指令发送与掉电恢复非易失寄存器保持性校验
│   ├── sds5054_ucut.py        # 示波器双通道波形采集与故障/恢复态精准抓取
│   └── ucut_control.py        # 24 组测试矩阵自动调度与 Excel Shmoo Plot 故障分布图生成
│
├── dp2031_power_cycle/        # 【模块 3：DP2031 快慢上电电源循环测试】(原 dp2031_control 独立分立)
│   ├── dp2031_control.py      # DP2031 双通道控制：CH1 偏置供电，CH2 快慢电压切换循环与 CANFD 采集
│   └── power_cycle_collect.py # 自动化上下电循环冲击长时记录 (10s 运行采集 + 3min 倒计时断电等待)
│
├── centrifuge_acceleration/   # 【模块 4：离心机高 G 值动态标定系统】(独立专项分立)
│   ├── data_processor/        # 阶梯转速稳态区间提取 (CentrifugeProcessor) 与桌面 GUI
│   ├── data_conlidation/      # MTP 标定前/后数据集与校准曲线拟合
│   └── tests/                 # 标定算法与数据提取单元测试 (36/36 100% 通过)
│
├── ft_electrical_parameter/   # 【模块 5：芯片基础电学参数测试】(原 main 与 simple_version 规范收敛)
│   ├── main/                  # CANFD 采集、示波器参数提取与零偏计算综合主控
│   │   ├── main_controller_simple.py   # 综合电学参数测试自动化主控
│   │   ├── add_scale_and_nonlinearity.py # 满量程折算与非线性度计算
│   │   ├── consolidate_results.py      # 批次测试结果汇总与报表生成器
│   │   └── repair_20260517_rms.py      # 历史测试数据 RMS 补充计算与修复脚本
│   └── simple_version/        # 万用表静态电流与示波器基础测量脚本
│
└── zlgcan_file/               # 【模块 6：周立功 ZLG CAN/CAN-FD 通信底层】(供应商 SDK 保持原样)
    ├── zlgcan_python_251211/  # 官方驱动 DLL 与 Python 绑定 (zlgcan.py, kerneldlls)
    ├── zcanpro_canfd200u.py   # USBCANFD-200U 纯读采集工具 (ISO CAN-FD 1M/2M，使能 120Ω 终端电阻)
    └── pz_zero_bias.py        # 传感器零偏 (Zero Bias) 批量统计与绘图
```

---

## 2. 各模块调用 ZLG CAN 文件的路径适配说明

由于 `zlgcan_file` 保持在 `crash_sensor/zlgcan_file` 原样不动，各独立模块采用**多路径动态自适应探测**技术加载 DLL 依赖，彻底消除跨项目调用与路径混淆风险，无需手动改动系统环境变量：

```python
# 路径自适应逻辑：向上回溯探测 zlgcan_file 目录
candidates = [
    os.path.join(workspace_root, "zlgcan_file"),
    os.path.abspath(os.path.join(current_dir, "..", "zlgcan_file")),
    os.path.abspath(os.path.join(current_dir, "..", "..", "..", "zlgcan_file")),
    r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file",
]
```

- `centrifuge_acceleration/`：`can_collector.py` 经实测自动命中并挂载 `crash_sensor/zlgcan_file`，`is_available()` 状态完全就绪。
- `dp2031_power_cycle/`：`dp2031_control.py` 与 `power_cycle_collect.py` 优先关联同级 `crash_sensor/zlgcan_file`。
- `ft_electrical_parameter/`：`main_controller_simple.py` 与 `repair_20260517_rms.py` 正确命中驱动。
- `ucut_micro_cut/`：聚焦于信号源 ARB 注入与示波器/串口联动，测试结果直接输出至独立测试数据目录。

---

## 3. 各功能模块快速启动命令

### 3.1 运行量产终测 (FT) 桌面程序
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ft_production_test
python ft_gui_main.py
```

### 3.2 运行 24 组 uCut 掉电矩阵自动化测试与 Shmoo 图绘制
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ucut_micro_cut
python ucut_control.py
# 终端输入 'a' 回车，全自动运行并输出带有颜色判定矩阵的 Excel 报告
```

### 3.3 运行 DP2031 芯片快慢上电电源循环测试
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\dp2031_power_cycle
python dp2031_control.py
# 或长时间循环采集: python power_cycle_collect.py
```

### 3.4 运行离心机加速度标定处理桌面程序
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\data_processor
python main.py --mode gui
```

### 3.5 启动电参数综合测量循环与非线性度分析
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\ft_electrical_parameter\main
python main_controller_simple.py
```

### 3.6 启动 USBCANFD-200U 实时读取记录工具
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file
python zcanpro_canfd200u.py
```
