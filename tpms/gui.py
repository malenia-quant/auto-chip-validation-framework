"""TPMS 车型打标与全基地数据汇总软件 GUI

严格遵循 ft_centrifuge 视觉与配色规范：
- 字体规范：Microsoft YaHei UI 10pt，Tab 与 LabelFrame 标题加粗，控制台采用 Consolas 10pt
- 配色体系：
  - 工业深蓝主色：#0D47A1，高亮浅蓝：#E1F5FE，选中文字：#0D47A1
  - 未选浅灰：#F0F4F8，文本板岩灰：#37474F / #263238
  - 状态指示灯：待执行 #B0BEC5 / #78909C，运行中 #1976D2 / #0D47A1，成功 #2E7D32 / #1B5E20，失败 #C62828 / #B71C1C
- 核心功能：
  1. 车型分类规范与国家列表管理
  2. 单基地月计划批量打标处理（生成 *_processed.xlsx，表尾追加“配置”列）
  3. 全基地数据合并与汇总（导出 ★秘密★全基地车型数据汇总.xlsx，并在尾部追加“年月日小时分钟”备注）
  4. 数据表格实时预览与统计卡片
  5. 线程安全日志控制台与快捷目录直达
"""

import os
import sys
import threading
import queue
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
from typing import Optional, Dict, Any, List
import pandas as pd

# Windows 原生高分屏支持
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from processor.config_manager import ConfigManager
from processor.tagger import ModelTagger
from processor.consolidator import DataConsolidator


def get_app_dir() -> str:
    """获取程序运行工作目录（打包成 exe 后返回 exe 所在目录，开发环境返回当前脚本所在目录）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_dir() -> str:
    """获取打包内置资源目录（支持 PyInstaller _MEIPASS 临时解压目录与源码目录）"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return getattr(sys, "_MEIPASS")
    return os.path.dirname(os.path.abspath(__file__))

# ================= 全局统一字体与样式常量 (10号字体 10pt) =================
FONT_FAMILY = "Microsoft YaHei UI"
FONT_BASE = (FONT_FAMILY, 10)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_TITLE = (FONT_FAMILY, 12, "bold")
FONT_CONSOLE = (FONT_FAMILY, 10)


class StepIndicator(ttk.Frame):
    """流水线步骤指示灯组件（严格沿用 ft_centrifuge 圆形指示灯样式）"""

    def __init__(self, parent, initial_text="待执行"):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, width=22, height=22, highlightthickness=0, bd=0)
        self.canvas.pack(side=tk.LEFT, padx=(4, 6))
        self.lbl = ttk.Label(self, text=initial_text, font=FONT_BASE, width=10)
        self.lbl.pack(side=tk.LEFT)
        self.current_state = "pending"
        self.set_state("pending", initial_text)

    def set_state(self, state: str, text: str = ""):
        self.current_state = state
        self.canvas.delete("all")
        color_map = {
            "pending": ("#B0BEC5", "#78909C"),  # 待机灰
            "running": ("#1976D2", "#0D47A1"),  # 进行中蓝
            "success": ("#2E7D32", "#1B5E20"),  # 完成绿
            "error":   ("#C62828", "#B71C1C"),  # 异常暗红
        }
        fill_c, outline_c = color_map.get(state, ("#B0BEC5", "#78909C"))
        self.canvas.create_oval(3, 3, 19, 19, fill=fill_c, outline=outline_c, width=2)
        if text:
            self.lbl.config(text=text)


class TPMSAppGUI:
    """TPMS 车型打标与全基地数据汇总控制台"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("TPMS 车型分类打标与全基地数据汇总系统")
        self.root.minsize(1120, 900)
        self.root.geometry("1180x900")

        self.base_dir = get_app_dir()
        self.data_dir = os.path.join(self.base_dir, "data")
        self.raw_dir = os.path.join(self.data_dir, "raw")
        self.output_dir = os.path.join(self.data_dir, "output")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        # 核心引擎
        self.config_mgr = ConfigManager()
        self.tagger = ModelTagger(self.config_mgr)
        self.consolidator = DataConsolidator(self.tagger)

        # 线程安全消息队列
        self.log_queue = queue.Queue()
        self.callback_queue = queue.Queue()

        # 变量初始化
        self._init_variables()
        self._setup_styles()
        self._build_ui()
        self._start_polling()

        # 尝试自动载入默认规范
        self._auto_load_default_specs()

    def _find_matching_file(self, folder: str, exact_names: List[str], keywords: List[str]) -> Optional[str]:
        """在指定目录下智能查找匹配的 Excel 文件（优先精确匹配，其次关键词模糊匹配）"""
        if not os.path.exists(folder):
            return None

        # 1. 优先精确匹配
        for name in exact_names:
            p = os.path.join(folder, name)
            if os.path.isfile(p):
                return p

        # 2. 关键词模糊匹配
        try:
            candidates = []
            for fname in os.listdir(folder):
                if fname.startswith("~$"):
                    continue
                if not (fname.lower().endswith(".xlsx") or fname.lower().endswith(".xls")):
                    continue
                full_p = os.path.join(folder, fname)
                if not os.path.isfile(full_p):
                    continue
                for kw in keywords:
                    if kw in fname:
                        candidates.append((len(kw), full_p))
                        break
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                return candidates[0][1]
        except Exception:
            pass

        return None

    def _detect_and_prepare_data_files(self) -> tuple[str, str]:
        """
        自动检测 exe 同目录 data 文件夹下的车型分类规范与地区列表。
        - 优先读取 exe 同级 data/ 目录中的文件（支持精确文件名及模糊关键词自动识别）。
        - 若同级 data/ 缺少相应文件，自动将内置模板释放/复制至同级 data/，便于用户直接查看与编辑。
        """
        import shutil

        # 确保运行目录下的基础目录结构完整
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        bundled_data_dir = os.path.join(get_resource_dir(), "data")

        # 1. 检测或释放 车型分类规范
        spec_file = self._find_matching_file(
            self.data_dir,
            exact_names=["车型分类规范.xlsx", "车型分类规范.xls"],
            keywords=["车型分类规范", "车型分类", "分类规范", "规范"]
        )
        if not spec_file:
            target_spec = os.path.join(self.data_dir, "车型分类规范.xlsx")
            bundled_spec = os.path.join(bundled_data_dir, "车型分类规范.xlsx")
            if os.path.exists(bundled_spec):
                try:
                    shutil.copy2(bundled_spec, target_spec)
                    spec_file = target_spec
                except Exception:
                    spec_file = bundled_spec
            else:
                spec_file = target_spec

        # 2. 检测或释放 地区列表
        region_file = self._find_matching_file(
            self.data_dir,
            exact_names=["地区列表.xlsx", "地区列表.xls", "国家列表.xlsx", "国家列表.xls"],
            keywords=["地区列表", "国家列表", "地区", "国家"]
        )
        if not region_file:
            target_region = os.path.join(self.data_dir, "地区列表.xlsx")
            for cand in ["地区列表.xlsx", "国家列表.xlsx"]:
                bundled_cand = os.path.join(bundled_data_dir, cand)
                if os.path.exists(bundled_cand):
                    try:
                        shutil.copy2(bundled_cand, target_region)
                        region_file = target_region
                        break
                    except Exception:
                        region_file = bundled_cand
                        break
            if not region_file:
                region_file = target_region

        return spec_file, region_file

    def _init_variables(self):
        # 自动检测 exe 同目录 data 文件夹下的规范文件与地区文件
        spec_file, region_file = self._detect_and_prepare_data_files()

        self.spec_path_var = tk.StringVar(value=spec_file if os.path.exists(spec_file) else "")
        self.country_path_var = tk.StringVar(value=region_file if os.path.exists(region_file) else "")

        self.input_files_var = tk.StringVar(value="")
        self.output_dir_var = tk.StringVar(value=self.output_dir)

        self.summary_name_var = tk.StringVar(value="★秘密★全基地车型汇总表.xlsx")
        self.include_ts_copy_var = tk.BooleanVar(value=True)
        self.add_footer_note_var = tk.BooleanVar(value=True)

        self.stat_processed_count_var = tk.StringVar(value="已处理单基地文件: 0 个")
        self.stat_summary_rows_var = tk.StringVar(value="车型汇总表总记录: 0 条")
        self.stat_status_var = tk.StringVar(value="系统待机就绪")

        # 缓存处理结果
        self.last_processed_files: List[str] = []
        self.last_summary_file: Optional[str] = None

    def _setup_styles(self):
        """配置与 ft_centrifuge 严格对齐的 ttk 样式"""
        style = ttk.Style()
        try:
            available = style.theme_names()
            if "vista" in available:
                style.theme_use("vista")
            elif "clam" in available:
                style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", font=FONT_BASE)
        style.configure("TLabel", font=FONT_BASE)
        style.configure("TButton", font=FONT_BASE, padding=(8, 3))
        style.configure("Accent.TButton", font=FONT_BOLD, foreground="#0D47A1", padding=(8, 3))
        style.configure("TEntry", font=FONT_BASE, padding=(3, 2))
        style.configure("TCombobox", font=FONT_BASE)
        style.configure("TCheckbutton", font=FONT_BASE)
        style.configure("TLabelframe", padding=6)
        style.configure("TLabelframe.Label", font=FONT_BOLD, foreground="#263238")
        style.configure("Log.TLabelframe.Label", font=FONT_BOLD, foreground="#000000")

        # Notebook Tab 样式
        style.configure("TNotebook", tabmargins=[0, 2, 2, 0])
        style.configure("TNotebook.Tab", font=FONT_BOLD, padding=(16, 6))
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#FFFFFF"), ("active", "#E1F5FE"), ("!selected", "#F0F4F8")],
            foreground=[("selected", "#0D47A1"), ("active", "#1565C0"), ("!selected", "#37474F")],
        )

        # Treeview 表格样式
        style.configure(
            "Treeview.Heading",
            font=FONT_BOLD,
            background="#0D47A1",
            foreground="#FFFFFF",
            relief="flat"
        )
        style.map("Treeview.Heading", background=[("active", "#1565C0")])
        style.configure("Treeview", font=FONT_BASE, rowheight=24)

    def _build_ui(self):
        """构建整体页面框架"""
        # 1. 顶部批次与规范概览栏
        self._build_top_header()

        # 2. 规范与参考库配置卡片
        self._build_spec_config_frame()

        # 3. 中部核心功能 Notebook (Tab 分页)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 4))

        self.tab_single = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_summary = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_preview = ttk.Frame(self.notebook, padding=(6, 6))

        self.notebook.add(self.tab_single, text=" ① 单基地月计划批量打标 ")
        self.notebook.add(self.tab_summary, text=" ② 全基地数据合并与汇总 ")
        self.notebook.add(self.tab_preview, text=" ③ 数据表格实时预览与校验 ")

        self._build_tab_single()
        self._build_tab_summary()
        self._build_tab_preview()

        # 4. 底部日志与控制台
        self._build_bottom_bar()

    def _build_top_header(self):
        """顶部信息看板（已移除标题与时间，统计指标左移）"""
        top_frame = ttk.LabelFrame(self.root, text=" 系统状态与生产概览 ")
        top_frame.pack(fill=tk.X, padx=8, pady=(4, 4))

        # 统计指标（左移显示）
        f_stats = ttk.Frame(top_frame)
        f_stats.pack(side=tk.LEFT, padx=6, pady=4)

        ttk.Label(f_stats, textvariable=self.stat_processed_count_var, font=FONT_BOLD, foreground="#000000").pack(side=tk.LEFT, padx=8)
        ttk.Separator(f_stats, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        ttk.Label(f_stats, textvariable=self.stat_summary_rows_var, font=FONT_BOLD, foreground="#000000").pack(side=tk.LEFT, padx=8)
        ttk.Separator(f_stats, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        ttk.Label(f_stats, textvariable=self.stat_status_var, font=FONT_BOLD, foreground="#0D47A1").pack(side=tk.LEFT, padx=8)

    def _build_spec_config_frame(self):
        """规范与参考库文件配置区"""
        frame = ttk.LabelFrame(self.root, text=" 车型分类规范与地区参考库配置 ")
        frame.pack(fill=tk.X, padx=8, pady=(2, 4))

        # 车型分类规范
        ttk.Label(frame, text="车型分类规范:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
        ttk.Entry(frame, textvariable=self.spec_path_var, width=52).grid(row=0, column=1, sticky=tk.EW, padx=4, pady=2)
        ttk.Button(frame, text="浏览...", command=self._browse_spec_file, width=8).grid(row=0, column=2, padx=4, pady=2)

        # 地区列表
        ttk.Label(frame, text="地区列表(出口):").grid(row=0, column=3, sticky=tk.W, padx=(12, 4), pady=2)
        ttk.Entry(frame, textvariable=self.country_path_var, width=36).grid(row=0, column=4, sticky=tk.EW, padx=4, pady=2)
        ttk.Button(frame, text="浏览...", command=self._browse_country_file, width=8).grid(row=0, column=5, padx=4, pady=2)

        # 操作快捷按钮
        f_btn = ttk.Frame(frame)
        f_btn.grid(row=0, column=6, padx=(12, 4), pady=2)
        ttk.Button(f_btn, text="重新载入/校验规范", command=self._reload_specs, width=16).pack(side=tk.LEFT, padx=2)
        ttk.Button(f_btn, text="打开配置目录(data)", command=lambda: self._open_folder(self.data_dir), width=16).pack(side=tk.LEFT, padx=2)

        frame.columnconfigure(1, weight=3)
        frame.columnconfigure(4, weight=2)

    def _build_tab_single(self):
        """Tab 1: 单基地月计划批量打标"""
        f = self.tab_single

        # 提示区域
        tip_frame = ttk.Frame(f)
        tip_frame.pack(fill=tk.X, pady=(2, 6))
        ttk.Label(
            tip_frame,
            text="[操作说明] 选择单基地月计划文件 (支持多选) 或指定文件夹，点击处理后将在数据最后一列追加“配置”列并导出 *_processed.xlsx",
            foreground="#37474F"
        ).pack(side=tk.LEFT)

        # 文件选择
        f_select = ttk.LabelFrame(f, text=" 输入文件与输出目录 ")
        f_select.pack(fill=tk.X, pady=(2, 6))

        ttk.Label(f_select, text="待处理文件:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=3)
        ttk.Entry(f_select, textvariable=self.input_files_var).grid(row=0, column=1, sticky=tk.EW, padx=4, pady=3)
        ttk.Button(f_select, text="选择文件(多选)...", command=self._select_raw_files, width=14).grid(row=0, column=2, padx=4, pady=3)
        ttk.Button(f_select, text="选择整个文件夹...", command=self._select_raw_folder, width=14).grid(row=0, column=3, padx=4, pady=3)

        ttk.Label(f_select, text="保存输出目录:").grid(row=1, column=0, sticky=tk.W, padx=4, pady=3)
        ttk.Entry(f_select, textvariable=self.output_dir_var).grid(row=1, column=1, sticky=tk.EW, padx=4, pady=3)
        ttk.Button(f_select, text="更改目录...", command=self._select_output_dir, width=14).grid(row=1, column=2, padx=4, pady=3)
        ttk.Button(f_select, text="载入测试样例", command=self._load_sample_files, width=14).grid(row=1, column=3, padx=4, pady=3)

        f_select.columnconfigure(1, weight=1)

        # 执行与状态栏
        f_act = ttk.Frame(f)
        f_act.pack(fill=tk.X, pady=(4, 6))

        self.btn_run_single = ttk.Button(
            f_act,
            text="① 执行批量打标处理",
            command=self._start_batch_single_processing,
            style="Accent.TButton",
            width=22
        )
        self.btn_run_single.pack(side=tk.LEFT, padx=4)

        self.step_ind_single = StepIndicator(f_act, "待执行")
        self.step_ind_single.pack(side=tk.LEFT, padx=12)

        # 列表框展示已选待处理文件
        f_box = ttk.LabelFrame(f, text=" 待处理单基地文件清单 ")
        f_box.pack(fill=tk.BOTH, expand=True, pady=(2, 2))

        self.lb_raw_files = tk.Listbox(
            f_box,
            font=FONT_BASE,
            selectmode=tk.EXTENDED,
            bg="#FFFFFF",
            fg="#263238",
            relief=tk.SOLID,
            bd=1
        )
        sb_y = ttk.Scrollbar(f_box, orient=tk.VERTICAL, command=self.lb_raw_files.yview)
        self.lb_raw_files.configure(yscrollcommand=sb_y.set)
        self.lb_raw_files.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=4)

    def _build_tab_summary(self):
        """Tab 2: 全基地数据合并与汇总"""
        f = self.tab_summary

        tip_frame = ttk.Frame(f)
        tip_frame.pack(fill=tk.X, pady=(2, 6))
        ttk.Label(
            tip_frame,
            text="[操作说明] 车型汇总表将所有的单独xlsx数据全部合并到一张表里，基地放在第一列，并在表尾生成时间备注",
            foreground="#37474F"
        ).pack(side=tk.LEFT)

        # 汇总参数设定
        f_cfg = ttk.LabelFrame(f, text=" 汇总与合并选项 ")
        f_cfg.pack(fill=tk.X, pady=(2, 6))

        ttk.Label(f_cfg, text="汇总文件名:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=3)
        ttk.Entry(f_cfg, textvariable=self.summary_name_var, width=36).grid(row=0, column=1, sticky=tk.W, padx=4, pady=3)

        ttk.Label(
            f_cfg,
            text="（自动追加 _YYYYMMDD_HHMM 时间戳，仅保留该标注时间的一份文件）",
            foreground="#1565C0",
            font=FONT_BASE
        ).grid(row=0, column=2, sticky=tk.W, padx=(8, 4), pady=3)

        ttk.Checkbutton(
            f_cfg,
            text="在表格尾部追加“年月日小时分钟”汇总生成备注行",
            variable=self.add_footer_note_var
        ).grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=4, pady=3)

        # 执行按钮与指示灯
        f_act = ttk.Frame(f)
        f_act.pack(fill=tk.X, pady=(4, 6))

        self.btn_run_summary = ttk.Button(
            f_act,
            text="② 一键执行全基地数据汇总",
            command=self._start_consolidation_processing,
            style="Accent.TButton",
            width=24
        )
        self.btn_run_summary.pack(side=tk.LEFT, padx=4)

        self.step_ind_summary = StepIndicator(f_act, "待执行")
        self.step_ind_summary.pack(side=tk.LEFT, padx=12)

        # 参与汇总的文件列表
        f_box = ttk.LabelFrame(f, text=" 参与汇总的单基地处理文件 (可自动从Tab 1联动) ")
        f_box.pack(fill=tk.BOTH, expand=True, pady=(2, 2))

        self.lb_summary_files = tk.Listbox(
            f_box,
            font=FONT_BASE,
            selectmode=tk.EXTENDED,
            bg="#FFFFFF",
            fg="#263238",
            relief=tk.SOLID,
            bd=1
        )
        sb_y = ttk.Scrollbar(f_box, orient=tk.VERTICAL, command=self.lb_summary_files.yview)
        self.lb_summary_files.configure(yscrollcommand=sb_y.set)
        self.lb_summary_files.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=4)

    def _build_tab_preview(self):
        """Tab 3: 数据表格实时预览与校验"""
        f = self.tab_preview

        # 顶部文件选择与统计栏
        f_top = ttk.Frame(f)
        f_top.pack(fill=tk.X, pady=(2, 4))

        ttk.Label(f_top, text="选择预览文件:").pack(side=tk.LEFT, padx=4)
        self.cb_preview_files = ttk.Combobox(f_top, state="readonly", width=48)
        self.cb_preview_files.pack(side=tk.LEFT, padx=4)
        self.cb_preview_files.bind("<<ComboboxSelected>>", self._on_preview_file_selected)

        ttk.Button(f_top, text="刷新列表", command=self._refresh_preview_options, width=10).pack(side=tk.LEFT, padx=4)

        self.lbl_preview_stat = ttk.Label(f_top, text="", font=FONT_BOLD, foreground="#0D47A1")
        self.lbl_preview_stat.pack(side=tk.RIGHT, padx=8)

        # Treeview 表格展示
        f_table = ttk.Frame(f)
        f_table.pack(fill=tk.BOTH, expand=True, pady=(2, 2))

        self.tree = ttk.Treeview(f_table, show="headings", selectmode="browse")
        sb_y = ttk.Scrollbar(f_table, orient=tk.VERTICAL, command=self.tree.yview)
        sb_x = ttk.Scrollbar(f_table, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)

        self.tree.grid(row=0, column=0, sticky=tk.NSEW)
        sb_y.grid(row=0, column=1, sticky=tk.NS)
        sb_x.grid(row=1, column=0, sticky=tk.EW)

        f_table.rowconfigure(0, weight=1)
        f_table.columnconfigure(0, weight=1)

    def _build_bottom_bar(self):
        """底部控制台与快捷操作按钮"""
        bottom_frame = ttk.LabelFrame(self.root, text=" 运行日志与控制台 (Log Console) ", style="Log.TLabelframe")
        bottom_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=(2, 4))

        self.console = ScrolledText(
            bottom_frame,
            wrap=tk.WORD,
            state="disabled",
            height=7,
            font=FONT_CONSOLE,
            bg="#FFFFFF",
            fg="#000000",
            relief=tk.SOLID,
            borderwidth=1,
            padx=6,
            pady=4
        )
        self.console.pack(fill=tk.BOTH, expand=True, pady=2)

        # 配置日志字体与颜色：全部统一为黑色字体，字体与上方清单框保持严格一致 (Microsoft YaHei UI 10pt)，彻底解决锯齿感
        self.console.tag_config("INFO", foreground="#000000", font=FONT_BASE)
        self.console.tag_config("SUCCESS", foreground="#000000", font=FONT_BOLD)
        self.console.tag_config("WARNING", foreground="#000000", font=FONT_BOLD)
        self.console.tag_config("ERROR", foreground="#000000", font=FONT_BOLD)

        f_actions = ttk.Frame(bottom_frame)
        f_actions.pack(fill=tk.X, pady=(2, 2))

        ttk.Button(f_actions, text="打开输出目录", command=lambda: self._open_folder(self.output_dir_var.get()), width=16).pack(side=tk.LEFT, padx=3)
        ttk.Button(f_actions, text="打开原始数据目录", command=lambda: self._open_folder(self.raw_dir), width=16).pack(side=tk.LEFT, padx=3)
        ttk.Button(f_actions, text="清空控制台日志", command=self._clear_console, width=16).pack(side=tk.RIGHT, padx=3)

    # =========================================================================
    # 线程安全调度与日志记录机制
    # =========================================================================
    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_queue.put((f"[{ts}] [{level}] {msg}\n", level))

    def dispatch(self, func, *args, **kwargs):
        self.callback_queue.put((func, args, kwargs))

    def _start_polling(self):
        items = []
        while not self.log_queue.empty():
            try:
                items.append(self.log_queue.get_nowait())
            except queue.Empty:
                break

        if items:
            self.console.configure(state="normal")
            for text, lvl in items:
                self.console.insert(tk.END, text, lvl)
            self.console.see(tk.END)
            self.console.configure(state="disabled")

        while not self.callback_queue.empty():
            try:
                func, args, kwargs = self.callback_queue.get_nowait()
                func(*args, **kwargs)
            except queue.Empty:
                break

        self.root.after(100, self._start_polling)

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", tk.END)
        self.console.configure(state="disabled")

    def _open_folder(self, folder_path: str):
        if os.path.exists(folder_path):
            os.startfile(folder_path)
        else:
            messagebox.showwarning("提示", f"目录不存在: {folder_path}")

    # =========================================================================
    # 核心业务事件处理
    # =========================================================================
    def _auto_load_default_specs(self):
        spec_p = self.spec_path_var.get().strip()
        c_p = self.country_path_var.get().strip()

        self.log(f"[自动检测] 正在定位 exe 同目录 data 文件夹: {self.data_dir}")

        if spec_p and os.path.exists(spec_p):
            self.log(f"[自动检测] 成功匹配车型分类规范: {spec_p}")
        else:
            self.log(f"[自动检测] 未在 data 目录下发现车型分类规范，请点击'浏览'指定", "WARNING")

        if c_p and os.path.exists(c_p):
            self.log(f"[自动检测] 成功匹配地区列表: {c_p}")
        else:
            self.log(f"[自动检测] 未在 data 目录下发现地区列表，请点击'浏览'指定", "WARNING")

        # 立即执行全面载入、规则解析与表格就绪自检
        self._reload_specs(show_msg=False)

    def _browse_spec_file(self):
        fp = filedialog.askopenfilename(
            title="选择车型分类规范 Excel 文件",
            filetypes=[("Excel Files", "*.xlsx *.xls")]
        )
        if fp:
            self.spec_path_var.set(fp)
            self._reload_specs()

    def _browse_country_file(self):
        fp = filedialog.askopenfilename(
            title="选择出口地区列表 Excel 文件",
            filetypes=[("Excel Files", "*.xlsx *.xls")]
        )
        if fp:
            self.country_path_var.set(fp)
            self._reload_specs()

    def _reload_specs(self, show_msg: bool = True):
        spec_p = self.spec_path_var.get().strip()
        c_p = self.country_path_var.get().strip()

        loaded_spec = False
        loaded_country = False
        spec_err = None
        country_err = None

        if spec_p:
            if not os.path.exists(spec_p):
                spec_err = f"指定的车型分类规范文件不存在: {spec_p}"
                self.log(spec_err, "ERROR")
            else:
                try:
                    sheet_rules = self.config_mgr.load_model_spec(spec_p)
                    loaded_spec = True

                    total_c0 = sum(len(r.get("major_series_rules", set())) for r in sheet_rules.values())
                    total_pairs = sum(len(set(r.get("code_pairs", []))) for r in sheet_rules.values())
                    total_empties = sum(len(r.get("empty_code_primaries", set())) for r in sheet_rules.values())
                    total_models = sum(len(r.get("full_models", set())) for r in sheet_rules.values())
                    total_rules = total_c0 + total_pairs + total_empties
                    cat_names = list(sheet_rules.keys())

                    self.log(f"[规范解析] 成功载入车型分类规范: {os.path.basename(spec_p)}", "SUCCESS")
                    self.log(f"[规范解析] 检测到 {len(cat_names)} 个配置分类: {', '.join(cat_names)} | 规则总计: {total_rules} 项 (一级大车系筛选代码 {total_c0} 个 + 二级生产车系统配 {total_empties} 个 + 二三级代码组合 {total_pairs} 组)")
                    for cat, r in sheet_rules.items():
                        c0s = list(r.get("major_series_rules", set()))
                        pairs = list(set(r.get("code_pairs", [])))
                        empties = list(r.get("empty_code_primaries", set()))
                        
                        parts = []
                        if c0s:
                            parts.append(f"{len(c0s)} 个一级大车系筛选代码(如: {', '.join(c0s[:3])})")
                        if empties:
                            parts.append(f"{len(empties)} 个二级生产车系统配(如: {', '.join(empties[:3])})")
                        if pairs:
                            sample_pairs = [f"{p[0]}-{p[1]}" for p in pairs[:3]]
                            parts.append(f"{len(pairs)} 组二三级代码细分组合(如: {', '.join(sample_pairs)})")
                        if r.get('full_models'):
                            parts.append(f"{len(r.get('full_models', set()))} 个完整车型定义")
                            
                        detail_str = "，".join(parts) if parts else "无有效规则"
                        self.log(f"  • 分类 [{cat}]: {detail_str}")

                    if total_rules == 0 and total_models == 0:
                        self.log("【警告】未在所选规范文件中提取到任何有效代码组合，请检查表头是否包含'一级大车系筛选代码'、'二级生产车系筛选代码'或'三级车型筛选代码'！", "WARNING")
                except Exception as e:
                    spec_err = str(e)
                    self.log(f"载入车型分类规范失败: {e}", "ERROR")

        if c_p:
            if not os.path.exists(c_p):
                country_err = f"指定的地区列表文件不存在: {c_p}"
                self.log(country_err, "ERROR")
            else:
                try:
                    self.config_mgr.load_country_list(c_p)
                    loaded_country = True
                    self.log(f"[地区库解析] 成功载入出口地区库: {os.path.basename(c_p)}，共包含 {len(self.config_mgr.countries)} 个国家/地区及简称。")
                except Exception as e:
                    country_err = str(e)
                    self.log(f"载入出口地区库失败: {e}", "ERROR")

        self.tagger.set_config(self.config_mgr)
        self.consolidator = DataConsolidator(self.tagger)

        if show_msg:
            if loaded_spec and not spec_err:
                cat_names = list(self.config_mgr.sheet_rules.keys())
                total_c0 = sum(len(r.get("major_series_rules", set())) for r in self.config_mgr.sheet_rules.values())
                total_pairs = sum(len(set(r.get("code_pairs", []))) for r in self.config_mgr.sheet_rules.values())
                total_empties = sum(len(r.get("empty_code_primaries", set())) for r in self.config_mgr.sheet_rules.values())
                total_models = sum(len(r.get("full_models", set())) for r in self.config_mgr.sheet_rules.values())
                total_rules = total_c0 + total_pairs + total_empties

                all_c0s = []
                for r in self.config_mgr.sheet_rules.values():
                    all_c0s.extend(list(r.get("major_series_rules", set())))
                c0_sample = f" (如: {', '.join(all_c0s[:4])})" if all_c0s else ""

                all_empties = []
                for r in self.config_mgr.sheet_rules.values():
                    all_empties.extend(list(r.get("empty_code_primaries", set())))
                empty_sample = f" (如: {', '.join(all_empties[:4])})" if all_empties else ""

                msg = f"参考规范已成功重新载入并应用！\n\n" \
                      f"车型分类规范: {os.path.basename(spec_p)}\n" \
                      f"检测到配置分类 ({len(cat_names)} 个): {', '.join(cat_names)}\n\n" \
                      f"有效规则总计: {total_rules} 项\n" \
                      f"  • 一级大车系筛选代码: {total_c0} 个{c0_sample}\n" \
                      f"  • 二级生产车系统配 (无3级代码): {total_empties} 个{empty_sample}\n" \
                      f"  • 二三级代码细分组合: {total_pairs} 组\n"
                if total_models:
                    msg += f"  • 完整车型定义: {total_models} 个\n"
                if loaded_country:
                    msg += f"\n出口地区参考库: 共 {len(self.config_mgr.countries)} 个国家/地区及简称"
                messagebox.showinfo("规范更新成功", msg)
            elif spec_err:
                messagebox.showerror("规范解析失败", f"载入车型分类规范发生错误:\n{spec_err}")
            elif not spec_p:
                messagebox.showwarning("提示", "请先选择有效的车型分类规范文件！")

    def _sync_active_specs(self):
        """在执行打标或汇总前自动核对并同步最新输入框路径的规范文件"""
        spec_p = self.spec_path_var.get().strip()
        c_p = self.country_path_var.get().strip()
        needs_reload = False
        if spec_p and spec_p != getattr(self.config_mgr, "model_spec_path", None):
            needs_reload = True
        if c_p and c_p != getattr(self.config_mgr, "country_list_path", None):
            needs_reload = True
        if needs_reload:
            self._reload_specs(show_msg=False)

    def _generate_test_data(self):
        """一键重新生成规范模板与测试数据集"""
        try:
            paths = generate_all(self.base_dir)
            self.spec_path_var.set(paths["model_spec"])
            self.country_path_var.set(paths["country_list"])
            self._reload_specs()
            self._load_sample_files()
            self.log("默认规范模板与 3 个基地的月计划测试样例已全部成功生成！", "SUCCESS")
            messagebox.showinfo("成功", "测试数据集生成完毕，已自动加载！")
        except Exception as e:
            self.log(f"生成测试数据集异常: {e}", "ERROR")
            messagebox.showerror("异常", f"生成测试数据集失败:\n{e}")

    def _select_raw_files(self):
        files = filedialog.askopenfilenames(
            title="选择待处理的单基地月计划文件 (可按Ctrl多选)",
            filetypes=[("Excel Files", "*.xlsx *.xls")]
        )
        if files:
            self._set_selected_raw_files(list(files))

    def _select_raw_folder(self):
        folder = filedialog.askdirectory(title="选择包含单基地月计划文件的文件夹")
        if folder:
            files = [
                os.path.join(folder, f) for f in os.listdir(folder)
                if f.endswith((".xlsx", ".xls")) and not f.startswith("~$") and not f.endswith("_processed.xlsx") and "全基地" not in f
            ]
            if files:
                self._set_selected_raw_files(files)
            else:
                messagebox.showinfo("提示", "所选目录中未找到符合条件的单基地月计划 Excel 文件。")

    def _load_sample_files(self):
        if os.path.exists(self.raw_dir):
            files = [
                os.path.join(self.raw_dir, f) for f in os.listdir(self.raw_dir)
                if f.endswith(".xlsx") and not f.startswith("~$")
            ]
            if files:
                self._set_selected_raw_files(files)

    def _set_selected_raw_files(self, files: List[str]):
        self.lb_raw_files.delete(0, tk.END)
        for f in files:
            self.lb_raw_files.insert(tk.END, f)
        self.input_files_var.set(f"已选择 {len(files)} 个文件")
        self.log(f"已载入 {len(files)} 个待处理单基地文件。")

    def _select_output_dir(self):
        d = filedialog.askdirectory(title="选择输出保存目录")
        if d:
            self.output_dir_var.set(d)
            self.log(f"输出保存目录已更改为: {d}")

    # =========================================================================
    # 批量单基地打标执行
    # =========================================================================
    def _start_batch_single_processing(self):
        self._sync_active_specs()
        files = list(self.lb_raw_files.get(0, tk.END))
        if not files:
            messagebox.showwarning("警告", "请先选择待处理的单基地文件！")
            return

        out_dir = self.output_dir_var.get().strip()
        if not out_dir:
            messagebox.showwarning("警告", "请先指定输出目录！")
            return

        self.btn_run_single.config(state="disabled")
        self.step_ind_single.set_state("running", "处理中...")
        self.stat_status_var.set("单基地打标处理中...")

        threading.Thread(
            target=self._worker_batch_single,
            args=(files, out_dir),
            daemon=True
        ).start()

    def _worker_batch_single(self, files: List[str], out_dir: str):
        try:
            self.log(">>> 开始执行单基地月计划批量打标处理...")
            results = self.consolidator.batch_process_files(files, output_dir=out_dir)

            processed_files = []
            for orig, proc_path, row_count in results:
                base_name = self.consolidator.extract_base_name_from_filename(orig)
                fn = os.path.basename(proc_path)
                self.log(f"[基地: {base_name}] 处理完成 -> {fn} (共 {row_count} 行有效车型，已自动选取车型汇总Sheet并剔除合计行，首列为基地)。", "SUCCESS")
                processed_files.append(proc_path)

            # 自动联动：将所有单独xlsx数据全部合并到一张表里，基地放在第一列（满足用户需求2）
            summary_name = self.summary_name_var.get().strip() or "★秘密★全基地车型汇总表.xlsx"
            self.log(f">>> 正在将所有单独xlsx数据全部合并到一张表《{summary_name}》中（基地放在第一列）...")
            summary_path, df_summary = self.consolidator.consolidate_bases(
                file_paths=processed_files,
                output_dir=out_dir,
                summary_filename=summary_name
            )
            self.last_summary_file = summary_path
            self.log(f"全基地车型汇总表合并完成: {os.path.basename(summary_path)}，共合并 {len(df_summary)} 条车型数据！", "SUCCESS")

            self.dispatch(self._on_batch_single_finished, processed_files, summary_path, len(df_summary))
        except Exception as e:
            self.log(f"单基地批量打标异常: {e}", "ERROR")
            self.dispatch(self._on_batch_single_failed, str(e))

    def _on_batch_single_finished(self, processed_files: List[str], summary_path: str, summary_rows: int):
        self.btn_run_single.config(state="normal")
        self.step_ind_single.set_state("success", "已完成")
        self.step_ind_summary.set_state("success", "已生成")
        self.stat_status_var.set("单基地打标与全基地汇总完成")
        self.stat_processed_count_var.set(f"已处理单基地文件: {len(processed_files)} 个")
        self.stat_summary_rows_var.set(f"车型汇总表总记录: {summary_rows} 条")
        self.last_processed_files = processed_files
        self.last_summary_file = summary_path

        # 自动同步至 Tab 2 汇总列表
        self.lb_summary_files.delete(0, tk.END)
        for f in processed_files:
            self.lb_summary_files.insert(tk.END, f)

        self._refresh_preview_options()
        self.cb_preview_files.set(os.path.basename(summary_path))
        self._load_file_into_preview(summary_path)

        self.log(f">>> 全部 {len(processed_files)} 个单基地文件打标完成，并已自动合并生成车型汇总表: {os.path.basename(summary_path)}！", "SUCCESS")
        messagebox.showinfo(
            "成功",
            f"成功打标处理 {len(processed_files)} 个单基地文件！\n\n已自动将所有单独数据合并到一张表里：\n{os.path.basename(summary_path)}\n（基地放在第一列，共 {summary_rows} 条记录）"
        )

    def _on_batch_single_failed(self, error_msg: str):
        self.btn_run_single.config(state="normal")
        self.step_ind_single.set_state("error", "异常")
        self.stat_status_var.set("处理异常")
        messagebox.showerror("错误", f"单基地打标失败:\n{error_msg}")

    # =========================================================================
    # 全基地数据汇总执行
    # =========================================================================
    def _start_consolidation_processing(self):
        self._sync_active_specs()
        files = list(self.lb_summary_files.get(0, tk.END))
        if not files:
            # 如果没有，从 Tab 1 取
            files = self.last_processed_files
        if not files:
            messagebox.showwarning("警告", "当前无待汇总的单基地文件，请先在Tab 1完成处理！")
            return

        out_dir = self.output_dir_var.get().strip()
        summary_name = self.summary_name_var.get().strip() or "★秘密★全基地车型数据汇总.xlsx"
        self.btn_run_summary.config(state="disabled")
        self.step_ind_summary.set_state("running", "汇总中...")
        self.stat_status_var.set("全基地数据汇总中...")

        threading.Thread(
            target=self._worker_consolidation,
            args=(files, out_dir, summary_name),
            daemon=True
        ).start()

    def _worker_consolidation(self, files: List[str], out_dir: str, summary_name: str):
        try:
            self.log(f">>> 开始执行跨基地数据汇总与合并，共 {len(files)} 个基地文件...")
            summary_path, df_summary = self.consolidator.consolidate_bases(
                file_paths=files,
                output_dir=out_dir,
                summary_filename=summary_name
            )

            self.dispatch(self._on_consolidation_finished, summary_path, len(df_summary))
        except Exception as e:
            self.log(f"全基地数据汇总异常: {e}", "ERROR")
            self.dispatch(self._on_consolidation_failed, str(e))

    def _on_consolidation_finished(self, summary_path: str, row_count: int):
        self.btn_run_summary.config(state="normal")
        self.step_ind_summary.set_state("success", "已完成")
        self.stat_status_var.set("全基地汇总完成")
        self.stat_summary_rows_var.set(f"汇总表总记录: {row_count} 条")
        self.last_summary_file = summary_path

        now_str = datetime.datetime.now().strftime("%Y年%m月%d日 %H时%M分")
        self.log(f"全基地车型数据汇总成功！输出文件: {os.path.basename(summary_path)}", "SUCCESS")
        self.log(f"已在表格尾部自动添加生成备注: [备注：数据汇总生成时间 {now_str}]", "SUCCESS")

        self._refresh_preview_options()
        self.cb_preview_files.set(os.path.basename(summary_path))
        self._load_file_into_preview(summary_path)

        # 自动切换到预览 Tab
        self.notebook.select(self.tab_preview)
        messagebox.showinfo(
            "汇总成功",
            f"全基地数据汇总已完成！\n共合并 {row_count} 行车型数据。\n尾部已备注生成时间（{now_str}）。"
        )

    def _on_consolidation_failed(self, error_msg: str):
        self.btn_run_summary.config(state="normal")
        self.step_ind_summary.set_state("error", "异常")
        self.stat_status_var.set("汇总异常")
        messagebox.showerror("错误", f"全基地数据汇总失败:\n{error_msg}")

    # =========================================================================
    # 数据表格预览
    # =========================================================================
    def _refresh_preview_options(self):
        options = []
        out_dir = self.output_dir_var.get().strip()
        if os.path.exists(out_dir):
            for f in sorted(os.listdir(out_dir)):
                if f.endswith(".xlsx") and not f.startswith("~$"):
                    options.append(f)

        self.cb_preview_files["values"] = options
        if options and not self.cb_preview_files.get():
            self.cb_preview_files.set(options[0])
            self._load_file_into_preview(os.path.join(out_dir, options[0]))

    def _on_preview_file_selected(self, event):
        fn = self.cb_preview_files.get()
        if fn:
            fp = os.path.join(self.output_dir_var.get(), fn)
            self._load_file_into_preview(fp)

    def _load_file_into_preview(self, file_path: str):
        if not os.path.exists(file_path):
            return

        try:
            df = pd.read_excel(file_path)

            # 清空现有表格
            self.tree.delete(*self.tree.get_children())

            cols = list(df.columns)
            self.tree["columns"] = cols

            for col in cols:
                self.tree.heading(col, text=col)
                # 计算自适应列宽
                max_w = max(len(str(col)) * 14, 80)
                for val in df[col].head(20):
                    val_w = sum(14 if ord(ch) > 127 else 8 for ch in str(val))
                    if val_w > max_w:
                        max_w = min(val_w, 240)
                self.tree.column(col, width=max_w, anchor="center" if col in ["基地", "配置"] else "w")

            for _, row in df.iterrows():
                vals = [str(row[c]) if pd.notna(row[c]) else "" for c in cols]
                self.tree.insert("", tk.END, values=vals)

            # 统计信息展示
            info_parts = [f"共 {len(df)} 行"]
            if "配置" in df.columns:
                cfg_series = df["配置"].fillna("").astype(str)
                vc = cfg_series.value_counts().to_dict()
                for k, count in vc.items():
                    label = k if k else "空白"
                    info_parts.append(f"{label}: {count}")

            self.lbl_preview_stat.config(text=" | ".join(info_parts))
        except Exception as e:
            self.log(f"预览加载失败: {e}", "ERROR")


def main():
    root = tk.Tk()
    app = TPMSAppGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
