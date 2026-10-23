# Common 工业级通用仪器驱动与算法参考库

作者: mozial

---

## 1. 模块定位与作用

本目录为车载芯片自动化测试与硬件在环（HIL）验证的**通用硬件驱动与算法参考库**。
已将原根目录下零散的通用组件（`drivers/`、`analysis/`、`config/`、`tests/`）统一收敛至此，用于为未来新芯片自动化测试、新台架脚本开发提供标准化的面向对象仪器通信与底层数学算法支持。

---

## 2. 目录结构

```text
common/
├── drivers/                   # 通用程控仪器驱动抽象层 (PyVISA / TCP Socket)
│   ├── base_instrument.py     # 统一基类 BaseInstrument (会话超时重试、状态自检与安全退出)
│   ├── generator_dg5072.py    # Rigol DG5072 信号源驱动 (易失 ARB 波形合成与电平转换)
│   ├── power_supply_dp2031.py # Rigol DP2031 程控直流电源驱动 (过压/过流保护与安全下电)
│   ├── scope_sds5054.py       # 鼎阳 SDS5054 数字示波器驱动 (快速波形传输与参数统计)
│   ├── dmm_keithley6500.py    # 吉时利 Keithley DMM6500 高精度数字万用表驱动
│   └── exceptions.py          # 框架统一硬件异常体系定义
│
├── analysis/                  # 跨项目通用数学与信号算法层
│   ├── signal_processing.py   # 曼彻斯特/PSI5 解码器 (PSI5Decoder)、直方图双峰电平分析与滤波
│   └── data_cleaning.py       # IQR 四分位距离群值过滤与统计汇总器
│
├── config/                    # 集中外置参数配置
│   ├── test_profile.yaml      # 仪器网络 IP、端口与基准门限配置表
│   └── loader.py              # 配置自适应加载器
│
├── tests/                     # 单元与集成自动化测试套件 (27 项用例全部通过)
│   ├── conftest.py            # pytest 全局 Hardware Fixture (支持 --mock 与 --live 切换)
│   ├── test_integration_hil.py# 驱动连接守卫与配置装载验证
│   ├── test_signal_analysis.py# 信号去噪、曼彻斯特解码与统计清洗测试
│   └── test_ucut_task.py      # 12 组 PSI5 电压映射与 ARB 波形合成参数化校验
│
├── README_zh.md               # [当前文档] 中文参考手册
└── README.md                  # English Reference Manual
```

---

## 3. 快速运行与测试

在激活虚拟环境的前提下，可以直接在工程中运行通用库的自动化测试套件：
```powershell
conda activate D:\project_momo\project_venv\venv_crashsensor
python -m pytest common/tests/ -v
# 输出: 27 passed in ~2.6s
```
