# CrashSensor 离心机测试数据自动化处理软件 — 实施方案 (V2.1 工业量产终版)

## 一、 项目背景与工程边界条件

本项目针对**基于 CG904 芯片的汽车级碰撞传感器（CrashSensor）**离心机 FT（Final Test）生产测试流程，构建高度自动化、高鲁棒性且闭环的数据处理与标定软件系统。

在量产工程落地中，系统需满足以下核心边界条件：
1. **测试轴向**：双轴向（Axis1 与 Axis2）分步测试与配对。
2. **物理离心机与传感器量程的换算**：
   - 传感器真实设计物理量程为 **$\pm 240\text{g}$**。
   - 工厂量产离心机硬件最大转速限制为 **$\pm 160\text{g}$**。
   - 必须通过严格的数学模型，将 $\pm 160\text{g}$ 实测均值**折算放大 1.5 倍**获得 $\pm 240\text{g}$ 等效值，再代入标定公式计算写入 MTP。
3. **协议规范**：64 字节 CG904 CAN 报文通过桥接板传输，采用 32 组 `[状态字节, 数据字节]` 编码，低 4 位有效负载，跳校验位大端拼接。
4. **命名与追踪**：11 位 Hex 器件码，采用美式周规则解析日期，支持产线标准的 **4-in-1 芯片合并命名器**。
5. **量产闭环与批次管理**：严格以 `Data_Consolidation` 为根目录，支持首测正常批次（`LOTn`）与脱机补测批次（`Rework_Lot`），自动维护 `Normal_List`、`Rework_List`、`AbnormalFunction_List`，并提供数据缝合模块（Data Merger）进行跨批次配对标定。

---

## 二、 核心算法与底层协议规范（深水区工程细节锁定）

### 2.1 离心机 1 量程折算、极性基准与 Span 门禁（图 8/8 规则订正）

系统在第一次离心机测试（Centrifuge 1）中执行 $\pm 160\text{g}$ 测试，用于计算器件的 MTP 灵敏度标定修调寄存器。

```
                       【Centrifuge 1 标定计算数学管道】
+-----------------------+      丢弃前30帧过渡态      +----------------------------+
|  CAN原始动态数据采样  | ------------------------> | 截取稳定段采样点 (<=50点)  |
+-----------------------+                           +----------------------------+
                                                                   |
                                                                   v 补码转换 (>512 减 1024)
                                                    +----------------------------+
                                                    | +160g实测均值, -160g实测均值|
                                                    +----------------------------+
                                                                   |
                                                                   v x 1.5 比例折算
                                                    +----------------------------+
                                                    | +240g等效值, -240g等效值   |
                                                    +----------------------------+
                                                                   |
                                                                   v Span 合理性门禁校验 [S_min, S_max]
                                                    +----------------------------+
                                                    | 计算 ADJ 寄存器修调值      |
                                                    +----------------------------+
                                                                   |
                                                                   v round() 四舍五入转 16 进制
                                                    +----------------------------+
                                                    | 写入 MTP 对应 ADJ 寄存器   |
                                                    +----------------------------+
```

#### 1. 极性基准与补码转换规范（消除除零与溢出陷阱）
- 底层原始数据通过 10-bit/16-bit 载荷提取，原始数值为无符号整型（围绕 512 偏置）。
- 继承 `sensor_processor1.py` 经产线验证的补码还原规则：
  $$\text{Signed\_Value} = x - 1024 \quad (\text{若 } x > 512) \quad \text{否则 } x$$
- 补码转换后，输出为带真实符号的有符号数（$+160\text{g}$ 输出为正值，$-160\text{g}$ 输出为负值）。

#### 2. 量程折算与跨度（Span）计算
将实测值等效放大至 $\pm 240\text{g}$ 设计量程：
$$\text{Output}_{(+240\text{g})} = \text{实测值}_{(+160\text{g}\text{稳定均值})} \times 1.5$$
$$\text{Output}_{(-240\text{g})} = \text{实测值}_{(-160\text{g}\text{稳定均值})} \times 1.5$$

定义跨度（Span）：
$$\text{Span} = \text{Output}_{(+240\text{g})} - \text{Output}_{(-240\text{g})}$$

#### 3. 硬件合理性门禁（Span Gate）
为避免传感器断路、未安装、接触抖动导致 $\text{Span} \approx 0$ 引发除零或严重溢出，代码中强制设立 Span 合理性阈值拦截：
$$\text{Span} \in [S_{\min}, S_{\max}] \quad (\text{默认 } S_{\min} = 600, S_{\max} = 3600，支持配置文件修改)$$
- 若 $\text{Span} < S_{\min}$ 或 $\text{Span} > S_{\max}$，立即阻断标定计算，将该芯片判定为 **`AbnormalFunction`** 并记录报警日志，严禁向 MTP 写入异常畸变值。

#### 4. 标定公式核心计算
通过门禁校验后，执行标定核心运算：
$$\text{ADJ\_CALC} = \frac{961 \times 2^{20}}{\text{Span} + 1}$$
- 分子实质为 $961 \times 1,048,576 = 1,007,681,536$。
- 计算结果执行 `round()` 四舍五入取整，转换为 4 位 16 进制字符串（如 `0x3C10`）。
- 精确写入 MTP 对应的 3 组 ADJ 寄存器：
  - `ADJ_DATA_TRANS_MIN`（地址 `5b 5a`）
  - `ADJ_DATA_TRANS_MAX`（地址 `58 57`）
  - `ADJ_DATA_TRANS_MAXH`（地址 `55 54`）

#### 5. 采样窗口与算法复用
- 直接复用 `sensor_processor2.py` 的成熟算法：
  - 边沿检测：`process_edges` 提取上升沿/下降沿。
  - 数据裁剪：`process_cropping` 设置 `start_idx = 30`（丢弃前 30 帧过渡震颤态），截取稳态区间长度 $\le 50$ 点。
  - 均值计算：复用 `calculate_averages` 计算稳态平均值。

---

### 2.2 CG904 CAN 报文解包与资产继承（直接复用 `device_code_scan.py`）

为了保证协议解析一致性，`can_data_parser.py` **绝不重复编写报文清洗代码**，直接从 `processor.device_code_scan` 中引入并继承 `CG904DataParser`：

```python
from processor.device_code_scan import CG904DataParser

class CentrifugeCANParser(CG904DataParser):
    """
    继承 CG904DataParser 底层 64 字节报文解构、01 f0 空载识别、UID 提取与美式周规则解析能力
    扩展：多板拓扑排序与 4-in-1 命名组装引擎
    """
```

#### 报文协议规则固化：
1. **拓扑映射**：CAN ID `0x111` ~ `0x146` 严格解析为 Board ID (1~4) 与 Sensor ID (1~6)，总计 24 个硬件工位。
2. **空载过滤**：前 10 字节为 `01 f0` 时自动判定为空载，静默旁路。
3. **清洗与大端拼接**：32 组 `[状态字节, 数据字节]`，以 `0x02` 确认正常通信，`data & 0x0F` 提取有效半字节，跳过奇偶校验位（2F, 2C, 29, 26, 23, 20, 1D, 1A），大端组装为 16 个寄存器。

---

### 2.3 24 通道拓扑排序与 4-in-1 芯片合并命名器（图 2/8、7/8）

针对产线 4 块供电板、24 个通道的物理排布，建立严格的**拓扑排序与 4-in-1 聚合规则**：

#### 1. 24 通道全局排序规则
将所有通道按**板号升序 $\to$ 传感器通道号升序**进行二维排序，形成唯一的工位索引序列（Slot 0 ~ Slot 23）：
$$\text{Global\_Slot\_Index} = (\text{Board\_ID} - 1) \times 6 + (\text{Sensor\_ID} - 1)$$

#### 2. 4-in-1 分组聚合与映射表
24 个物理通道被固定、精确划分为 **6 个 4-in-1 芯片组**（每组对应产出一个测试 LOG 文件）：

| 组号 (Group) | 覆盖板号与通道号 | 槽位数 | 对应输出文件名示例 |
|:---:|:---|:---:|:---|
| **Group 1** | Board 1 [Ch 1, 2, 3, 4] | 4 颗 | `{Dev1}-{Dev2}-{Dev3}-{Dev4}-LOG.txt` |
| **Group 2** | Board 1 [Ch 5, 6] + Board 2 [Ch 1, 2] | 4 颗 | `{Dev5}-{Dev6}-{Dev7}-{Dev8}-LOG.txt` |
| **Group 3** | Board 2 [Ch 3, 4, 5, 6] | 4 颗 | `{Dev9}-{Dev10}-{Dev11}-{Dev12}-LOG.txt` |
| **Group 4** | Board 3 [Ch 1, 2, 3, 4] | 4 颗 | `{Dev13}-{Dev14}-{Dev15}-{Dev16}-LOG.txt` |
| **Group 5** | Board 3 [Ch 5, 6] + Board 4 [Ch 1, 2] | 4 颗 | `{Dev17}-{Dev18}-{Dev19}-{Dev20}-LOG.txt` |
| **Group 6** | Board 4 [Ch 3, 4, 5, 6] | 4 颗 | `{Dev21}-{Dev22}-{Dev23}-{Dev24}-LOG.txt` |

#### 3. 单器件 11 位 Hex 码与异常占位
- 每颗芯片编码为 11 位 Hex：CFG27（4位编号）+ CFG28（4位美式周规则日期）+ CFG29（3位备用/上位机）。
- **NG 芯片与空载槽位**：若对应工位未插芯片（空载）或报文异常，**严格填入 11 个零 `00000000000` 占位**。
- 若整组 4 颗芯片均异常或空载，则生成：
  `00000000000-00000000000-00000000000-00000000000-LOG.txt`。

---

### 2.4 MTP 标定文件更新与 CFG22<13> 控制位写入（图 8/8）

采用模板定位替换，严禁从零构建文件：
1. **源模板**：读取 `MTP_DATA/before-calibration/{11位器件编号}.txt`。
2. **基准地址替换**：
   - 检索 `5b 5a`（ADJ_MIN）、`58 57`（ADJ_MAX）、`55 54`（ADJ_MAXH）及其关联数据行。
   - 将默认值精准替换为最新计算的 Hex 标定值。
3. **CFG22<13> TRIM 使能置位**：
   - 定位配置寄存器 `CFG22`。
   - 执行按位或：$\text{CFG22\_NEW} = \text{CFG22\_OLD} \mid (1 \ll 13)$，将第 13 位置 1（使能 TRIM 标定）。
4. **输出目标**：写入 `MTP_DATA/after-calibration/{11位器件编号}.txt`。

---

## 三、 量产目录体系、A/B 极性对齐与数据缝合闭环

### 3.1 规范化目录结构（按图 5/8 严格命名）

根目录严格命名为 `Data_Consolidation`：

```
Data_Consolidation/                              # 统一数据整合与归档根目录
├── 202608经测月份/                              # 按“年月+经测月份”归档
│   ├── LOT1/                                   # 流水线首测正常批次数据文件夹
│   │   ├── Raw_Data/
│   │   ├── Processed_Data/
│   │   └── Calibration/
│   │
│   ├── Rework_Lot/                             # 补测数据文件夹（脱机集中补测单/双轴）
│   │   ├── Raw_Data/
│   │   └── Processed_Data/
│   │
│   ├── Normal_List_20260818_170000.csv         # 当日正常首测/补测通过完成的器件清单
│   ├── Rework_List_20260818_170000.csv         # 当日待复测器件清单（记录缺测轴、工位、UID与状态）
│   └── AbnormalFunction_List_20260818_170000.csv # 通信异常/硬件致命损坏报废器件清单
│
├── Centrifuge2/                                # 第二次离心机（80g-160g 线性度验证）
│   └── ...
│
└── MTP_DATA/                                   # MTP 烧录模板与结果目录
    ├── before-calibration/
    └── after-calibration/
```

---

### 3.2 数据缝合模块（Data Merger）与 A/B 工装物理极性对齐

在量产测试中，A 工装与 B 工装存在物理翻转极性关系：
- **Axis1 测试**：A 工装芯片受正向加速度（$+$），B 工装芯片受负向加速度（$-$）。
- **换装翻转后 Axis2 测试**：A 工装芯片受负向加速度（$-$），B 工装芯片受正向加速度（$+$）。

#### 补测物理极性匹配机制（防盲目置负）
当脱机补测单轴（例如仅补测 Axis2）时，`DataMerger` 必须根据器件的**物理工位与工装绑定关系（A 还是 B）**精确计算极性符号：

```python
class DataMerger:
    """
    负责将 LOTn 原始批次中缺轴的数据与 Rework_Lot 补测数据进行 Join 缝合
    主键: 芯片编号_HEX (或完整 32 位 UID)
    """
    def resolve_physical_polarity(self, fixture_type: str, test_axis: str, raw_reading: float) -> float:
        """
        精确解析物理受力符号:
        - Axis1: Fixture A -> 正向 (+); Fixture B -> 负向 (-)
        - Axis2: Fixture A -> 负向 (-); Fixture B -> 正向 (+)
        """
        if test_axis == "Axis1":
            return raw_reading if fixture_type == "A" else -abs(raw_reading)
        elif test_axis == "Axis2":
            return -abs(raw_reading) if fixture_type == "A" else abs(raw_reading)
        return raw_reading
```

#### 缝合流程：
1. 以 `芯片编号_HEX` 为主键，将 `Rework_Lot` 补测数据与 `LOTn` 主数据表做 Join。
2. 填补缺失轴数据并完成 A/B 极性对齐。
3. 校验双轴数据齐全且无缺漏，生成完整记录集，输入标定计算引擎。

---

### 3.3 三清单去重与良率闭环状态流转（Tri-Lists Lifecycle）

为确保良率统计（Yield Ratio）分子分母精确闭环，三清单遵循严格的生命周期状态流转：

```
                    【三清单生命周期流转图】
                          [ 全量测试器件 ]
                                 |
           +---------------------+---------------------+
           |                     |                     |
     [ 双轴首测合格 ]       [ 单轴缺失/微异常 ]     [ 硬件致命损坏/断路 ]
           |                     |                     |
           v                     v                     v
     Normal_List            Rework_List         AbnormalFunction_List
   (Status: Passed)     (Status: Pending)         (Status: Scrapped)
                                 |
                                 v
                         进入 Rework 补测
                                 |
                 +---------------+---------------+
                 |                               |
           [ 补测合格并缝合 ]               [ 补测仍然失败 ]
                 |                               |
                 v                               v
         Rework_List 标记为 Resolved       Rework_List 标记为 Failed
                 |                               |
                 +-------------------> 汇入 AbnormalFunction_List
                 v
         追加写入 Normal_List
      (确保当天结项良率统计准确)
```

1. **初始分类**：
   - 首测双轴齐全且合格 $\to$ 直接写入 `Normal_List`。
   - 单轴缺失或接触异常 $\to$ 写入 `Rework_List`，标记状态为 `Pending`，记录缺失轴向、工位与 UID。
   - 通信彻底中断或硬件损坏 $\to$ 写入 `AbnormalFunction_List`。
2. **复测闭环更新**：
   - 当芯片在 `Rework_Lot` 中补测通过并完成缝合标定后：
     - 将 `Rework_List` 中该条目状态更新为 **`Resolved`**（或移至归档）。
     - **追加写入当班最终结项的 `Normal_List`**。
   - 若复测依然异常，状态变更为 `Failed` 并转入 `AbnormalFunction_List`。
3. **良率闭环**：
   $$\text{总产出} = \text{Count}(\text{Normal\_List}) + \text{Count}(\text{AbnormalFunction\_List}) + \text{Count}(\text{Rework\_Pending})$$
   彻底避免重复计算或数据丢失。

---

### 3.4 GUI 双工况解耦设计

- **模式 A（Normal Flow 首测模式）**：
  - Axis1 测试 $\to$ **强制模态弹窗**（“请翻转工装至 Axis2 并锁紧！”） $\to$ Axis2 测试 $\to$ 自动三清单分流。
- **模式 B（Targeted Rework 定向复测模式）**：
  - 导入 `Rework_List` $\to$ 生成工位白名单 $\to$ 操作员手动选定待补轴向 $\to$ **安全锁定：绝对禁止自动步进下一轴向** $\to$ 仅采集白名单通道，忽略 `01 f0` 空载 $\to$ 触发数据缝合器完成标定与清单状态流转。

---

## 四、 代码架构与文件规划

所有生产代码存放在 `data_processor/`，`original_scripts/` 保持只读供底层引入：

```
d:\project_momo\auto-chip-validation-framework\crash_sensor\centrifuge_acceleration\
├── data_processor/
│   ├── config/
│   │   └── settings.ini                     # S_min, S_max, 离心机参数, 目录路径
│   ├── processor/
│   │   ├── __init__.py
│   │   ├── device_code_scan.py              # 表头检测与底层 64 字节报文清洗引擎（直接复用）
│   │   ├── can_data_parser.py               # 继承 CG904DataParser，实现 24 通道排序与 4-in-1 命名
│   │   ├── centrifuge_processor.py          # 封装 sensor_processor2 的 edge/cropping 算法
│   │   ├── calibration_processor.py         # 1.5倍折算、Span门禁、961*2^20标定、MTP模板替换与CFG22<13>
│   │   └── result_consolidator.py           # Data Merger (A/B极性对齐)、三清单去重闭环
│   ├── gui.py                               # 模式 A/B 严格解耦的现代化操作界面
│   ├── main.py                              # CLI 批处理入口
│   └── requirements.txt
├── Data_Consolidation/                      # 真实量产输出目录
└── tests/                                   # 自动化单元测试与集成测试套件
```

---

## 五、 测试用例规划（Test Cases）

在 `tests/` 下建立完备的自动化测试：

| 用例 ID | 测试模块 | 核心输入条件 | 验证标准 | 优先级 |
|:---|:---|:---|:---|:---:|
| **TC-SPAN-001** | `calibration_processor` | 正常输入：$+160\text{g}$ 读数 $+850$，$-160\text{g}$ 读数 $-850$ | 补码有符号输出，$\text{Span}=2550 \in [600, 3600]$，计算出合规 Hex 并通过 | **P0** |
| **TC-SPAN-002** | `calibration_processor` | 异常输入：读数接近零，$\text{Span} = 50 < S_{\min}$ | 门禁拦截，禁止除零，抛出异常并转入 AbnormalFunction | **P0** |
| **TC-4IN1-001** | `can_data_parser` | 24 通道全局输入（Board 1~4, Sensor 1~6） | 正确排序并均分为 6 组 4-in-1，跨板通道（如 B1S5-6+B2S1-2）正确聚合成组 | **P0** |
| **TC-4IN1-002** | `can_data_parser` | 工位存在空载通道（`01 f0`）或损坏件 | 对应槽位精准以 `00000000000` 填充，不影响同组其他器件命名 | **P0** |
| **TC-REUSE-001** | `can_data_parser` | 64 字节报文解包与美式周规则 | 结果与 `device_code_scan.py` 原生运行完全一致，无逻辑偏差 | **P0** |
| **TC-REUSE-002** | `centrifuge_processor` | 阶梯数据边沿与稳态提取 | 成功应用 `start_idx=30` 过滤前 30 帧，稳态截取 $\le 50$ 点均值 | **P0** |
| **TC-POLAR-001** | `result_consolidator` | Rework 补测 Axis2，Fixture A 与 Fixture B 分别测试 | Fixture A 解析为负向，Fixture B 解析为正向，物理极性完全准确 | **P0** |
| **TC-CLOSE-001** | `result_consolidator` | 某芯片在 Rework_Lot 补测合格并缝合 | Rework_List 更新为 `Resolved`，追加写入 Normal_List，良率统计闭环精确 | **P0** |
| **TC-MTP-001** | `calibration_processor` | before-calibration 模板更新 | 6 处地址数据被精准替换为 Hex，`CFG22<13>` 成功置 1 | **P0** |
| **TC-GUI-001** | `gui` | 模式 A 流水线换装操作 | Axis1 完成后强制弹出模态对话框，操作员确认后方可步进 Axis2 | **P0** |
| **TC-GUI-002** | `gui` | 模式 B 定向复测安全锁定 | 白名单生效，空载 `01 f0` 旁路，单轴测试完毕后绝对不自动步进 | **P0** |

---

## 六、 阶段推进实施计划

- **阶段 1：环境与底层协议/命名器落地（立即启动）**
  - 在 Conda 环境 `D:\project_momo\project_venv\venv_crashsensor` 安装依赖（pandas, numpy, scipy, matplotlib）。
  - 将 `device_code_scan.py` 对接入 `data_processor/processor/`。
  - 构建 `can_data_parser.py`：实现 24 通道拓扑排序与 6 组 4-in-1 芯片合并命名器。
  - 编写并执行 `tests/test_can_data_parser.py`。
- **阶段 2：算法核心（Span门禁与稳态复用）与 MTP 模板替换**
  - 构建 `centrifuge_processor.py`：参数化继承 `sensor_processor2.py` 的边沿与裁剪算法。
  - 构建 `calibration_processor.py`：实现有符号补码转换、Span 门禁、标定公式、MTP 模板定位替换与 `CFG22<13>` 置位。
  - 编写并执行 `tests/test_calibration_processor.py`。
- **阶段 3：数据缝合引擎与三清单闭环**
  - 构建 `result_consolidator.py`：实现 A/B 极性对齐、Join 数据缝合与三清单去重流转。
  - 编写并执行 `tests/test_result_consolidator.py`。
- **阶段 4：GUI 双工况开发与集成联调**
  - 构建 `gui.py`：实现模式 A（换装弹窗）与模式 B（白名单防步进）。
  - 端到端全流程验证与交付。
