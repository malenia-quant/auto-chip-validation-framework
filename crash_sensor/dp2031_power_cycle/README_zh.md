# CrashSensor Rigol DP2031 芯片快慢上电循环控制与启动特性测试系统

作者: mozial

---

## 1. 模块定位与核心功能

本模块专用于汽车碰撞传感器芯片（Crash Sensor）的**电源上下电循环冲击（Power-Cycle Stress）与快慢上电启动建立特性（Power-On Ramp Verification）**测试。

在车载复杂供电环境下，蓄电池上电、ECU 缓启动或快速继电器闭合会带来不同斜率的电压上升沿（快上电、慢上电）。本模块通过控制 Rigol DP2031 线性直流电源，模拟芯片在各种上下电极限工况下的供电冲击，并实时捕获 CAN 启动报文，验证芯片是否能正常启动、复位电路行为及长期循环下的工作稳定性。

---

## 2. 模块目录结构

```text
crash_sensor/dp2031_power_cycle/
├── dp2031_control.py           # DP2031 双通道控制：CH1 恒定供电，CH2 高低电平快慢循环切换与 CANFD 采集
├── power_cycle_collect.py      # 长时间自动循环上下电测试 (10s 运行采集 + 3min 断电恢复)，监测启动报文
├── README_zh.md                # [当前文档] 中文技术与操作手册
└── README.md                   # English Technical & Operation Manual
```

---

## 3. 核心测试脚本说明

### 3.1 双通道快慢上电循环与 CAN 实时监控 (dp2031_control.py)
- **供电通道划分**：
  - `CH1`：作为核心偏置/逻辑恒定供电（如 6.0V / 100mA 限流）。
  - `CH2`：作为被测功能脚高低电平快慢循环跳变源（如 2.0V 高电平 / 1.0V 低电平，2.0s 周期循环）。
- **CAN 联动**：在电压跳变过程中持续通过 USBCANFD-200U 盒监听总线并发送周期控制帧（`CMD_INTERVAL = 0.02s`），实时绘制响应曲线并保存数据。

### 3.2 自动化长时间上下电循环冲击测试 (power_cycle_collect.py)
- **循环机制**：
  - 开启 DP2031 输出（如 12.0V / 1.0A，OVP 13.5V, OCP 1.5A 保护门禁）；
  - 持续抓取芯片启动阶段的 CAN FD 报文 10 秒；
  - 自动切断电源输出并进入 3 分钟倒计时断电等待；
  - 自动重复上述循环，每次测试结果按批次和时间戳独立归档至 CSV。
- **安全保障**：脚本捕获异常中断与正常退出时，均具备硬保护逻辑，强制下发 SCPI 指令关闭输出通道，杜绝待测器件意外带电。

---

## 4. ZLG CAN 驱动多路径自适应探测

本模块位于 `crash_sensor/dp2031_power_cycle/`，内部脚本优先探测同级目录下的 `crash_sensor/zlgcan_file`，彻底避免硬编码绝对路径：

```python
script_dir = os.path.dirname(os.path.abspath(__file__))
candidate_dirs = [
    os.path.abspath(os.path.join(script_dir, "..", "zlgcan_file", "zlgcan_python_251211")),
    r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file\zlgcan_python_251211",
    os.path.abspath(os.path.join(script_dir, "..", "..", "zlgcan_file", "zlgcan_python_251211")),
]
zlgcan_real_dir = next((d for d in candidate_dirs if os.path.exists(d)), candidate_dirs[0])
```

---

## 5. 快速启动与操作指引

### 5.1 环境准备
激活专用 Conda 虚拟环境：
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
```

### 5.2 执行双通道快慢上电循环测试
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\dp2031_power_cycle
python dp2031_control.py
```

### 5.3 启动长时间上下电自动化循环采集
```powershell
cd D:\project_momo\auto-chip-validation-framework\crash_sensor\dp2031_power_cycle
python power_cycle_collect.py
```
