# TPMS 车型分类打标与全基地数据汇总软件

专为汽车研发与制造月度排产计划数据打标、单基地文件规范化处理及全基地车型数据跨工厂合并汇总而设计的自动化工业软件。

---

## 核心业务规范实现

根据企业打标规范，本软件严格按三级优先级判定每行车型的“配置”属性：

### 1. 车型及车型分类打标规范
- **优先级 1（国家划分/出口匹配）**：
  - 参考文件：《国家列表.xlsx》或《地区列表.xlsx》（涵盖全世界主权国家、常用中文简称、官方全称别名及地区关键字，如沙特、日本、德国、澳洲、欧标、东南亚、右舵、出口等）。
  - **命中条件**：“车型”或“生产车系”列出现国家/地区列表中提及的国家、中文简称、别名或出口关键字（中国、亚洲、亚太等本土保护词除外）。
  - **打标动作**：“配置”列优先标注为 **`出口`**。
- **优先级 2（车型分类规范匹配）**：
  - 参考文件：《车型分类规范.xlsx》（各 Sheet 对应一种配置类型，例如 Sheet 命名为“爆胎”、“直接式”、“间接式”、“独立控制器”等）。
  - **命中条件 A**：“车型”列包含《车型分类规范》中提及的分类全称（如 `EWEK-10型` 或 `EWEK-10`）或直接包含 Sheet 名/直接配置词（如“爆胎”）。
  - **命中条件 B**：“生产车系”包含《车型分类规范》中的一级/二级车型代码，且“车型”列包含二级/三级代码搭配符号文字的组合（如 `-10` 或 `-10型`）。
  - **关键例外**：只有孤立的 `10` 不计入 Sheet 分类（排除纯数字误判）。
  - **打标动作**：在表格数据最后一列追加表头为“配置”的数据列，记录所属 Sheet 名（如 `爆胎`）。
- **优先级 3（默认未设计行）**：
  - 未匹配优先级 1 与 2 的数据行，“配置”列置空（空白单元格）。

---

### 2. 文件命名与数据汇总规范
- **单基地原始文件**：`★秘密★抚州-月计划 MFZ202637002.xlsx`，系统自动正则识别生产基地（如“抚州”）。
- **单基地处理后文件**：`★秘密★抚州-月计划 MFZ202637002_processed.xlsx`，末尾追加“配置”列。
- **全基地汇总文件**：`★秘密★全基地车型数据汇总.xlsx`（并自动同步生成带时间戳副本 `★秘密★全基地车型数据汇总_YYYYMMDD_HHMM.xlsx`）。
- **全基地合并列排序规范**：
  `{基地} + {大车系} + {生产车系} + {车型} + {原始表格中后续数据, eg. 9月计划排产... 12月计划排产} + {配置}`
- **尾部时间戳备注（特别需求）**：
  在合并后的汇总 Excel 表格尾部自动追加合并备注行，格式精确到年月日小时分钟：
  `备注：数据汇总生成时间 YYYY年MM月DD日 HH时MM分`

---

## 软件目录架构

```
d:\project_momo\auto-chip-validation-framework\tpms\
├── data/                               # 模板规范与测试数据存放目录
│   ├── 车型分类规范.xlsx               # 车型分类规范模板（含“爆胎”、“胎压监测”等Sheet）
│   ├── 国家列表.xlsx                   # 出口国家匹配参考库
│   ├── raw/                            # 模拟单基地原始月计划文件
│   │   ├── ★秘密★抚州-月计划 MFZ202637002.xlsx
│   │   ├── ★秘密★常州-月计划 MCZ202637003.xlsx
│   │   └── ★秘密★合肥-月计划 MHF202637004.xlsx
│   └── output/                         # 输出目录（存放 processed 文件与汇总表）
├── processor/                          # 核心业务逻辑层
│   ├── __init__.py
│   ├── tagger.py                       # 优先级1-3打标引擎
│   ├── consolidator.py                 # 单基地处理与全基地汇总引擎（含尾部时间戳备注）
│   └── config_manager.py               # 规范文件加载与校验器
├── tests/                              # 自动化测试套件 (12/12 100% 通过)
│   ├── __init__.py
│   ├── test_tagger.py                  # 打标优先级测试（覆盖各种边界case与排除规则）
│   ├── test_consolidator.py            # 单基地处理与全基地汇总测试
│   ├── test_integration.py             # 完整端到端集成测试
│   └── test_gui_smoke.py               # GUI 启动与冒烟测试
├── generate_test_dataset.py            # 一键重建规范模板与全部测试数据集脚本
├── gui.py                              # 工业级 GUI 界面 (严格参考 ft_centrifuge 配色)
├── main.py                             # 主入口脚本 (支持 GUI / CLI 双模式)
├── requirements.txt                    # 依赖清单
└── README.md                           # 说明文档
```

---

## 快速使用指南

### 1. 依赖安装与运行环境
使用已配置好的 Python 虚拟环境（如 `venv_crashsensor`）：
```powershell
pip install -r requirements.txt
```

### 2. 启动图形化界面 (GUI)
运行主程序即可打开工业级 GUI 界面：
```powershell
python main.py
```
- **Tab 1 单基地月计划批量打标**：选择文件或文件夹，一键处理生成 `*_processed.xlsx`。
- **Tab 2 全基地数据合并与汇总**：选择待合并的处理文件，一键汇总并生成尾部带有年月日小时分钟备注的汇总报表。
- **Tab 3 数据表格实时预览与校验**：即时预览 Excel 表格内容及各分类统计结果。
- **顶部按钮**：支持一键重新生成标准模板与全套测试数据集。

### 3. 命令行批处理模式 (CLI)
支持通过命令行无头运行：
```powershell
python main.py --cli
```

### 4. 运行自动化测试套件（开发环境）
```powershell
pytest tests/ -v
```
所有 12 个测试用例均通过验证，覆盖优先级打标、例外排除、单基地格式化、全基地汇总、时间戳备注以及 GUI 冒烟测试。

### 5. 打包为 Windows 可执行程序 (.exe)
本项目提供一键打包脚本及详细命令行（默认排除 pytest、matplotlib、scipy 等非必要开发测试依赖，体积仅 ~41MB）：

#### 方式 1：双击运行打包脚本
- 直接双击运行项目根目录下的 `build_exe.bat` 即可全自动生成单文件 `dist\TPMS.exe`。

#### 方式 2：命令行打包（PowerShell）
```powershell
# 1. 确保虚拟环境与 DLL 路径就绪
$env:PATH = "D:\project_momo\project_venv\venv_crashsensor\Library\bin;$env:PATH"

# 2. 单文件免安装 EXE 打包命令（排除 pytest 等多余依赖，自带默认规范配置）
& "D:\project_momo\project_venv\venv_crashsensor\python.exe" -m PyInstaller `
    --noconfirm `
    --onefile `
    --windowed `
    --name "TPMS" `
    --paths "D:\project_momo\project_venv\venv_crashsensor\Library\bin" `
    --add-data "data;data" `
    --exclude-module pytest `
    --exclude-module matplotlib `
    --exclude-module scipy `
    main.py
```
打包成功后，可在 `dist/TPMS.exe` 获取独立的绿色单文件软件，直接发给同事即可双击使用，无需安装 Python 环境。
