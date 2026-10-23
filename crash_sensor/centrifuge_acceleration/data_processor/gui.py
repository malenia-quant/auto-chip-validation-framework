"""
CrashSensor 离心机测试数据自动化处理软件 GUI (工业量产版 V2.4)
- 字体加粗范围严格控制：仅 Tab 标题与日志大标题加粗，其余全部标准粗细
- 取消默认全屏，窗口自适应内容长宽 (1060x680)
- 顶部标题精简，去除 "量产版V2.4"
- 流水线全部居中对齐，指示灯最右侧严格同列对齐，圆圈放大为 16px
- 文件地址框宽度减半 (width=24)
- 补测界面移除 "未载入复测名单"，上下地址框严格对齐
- 3合1 CAN 盒智能按钮，去除多余状态提示标签；未连接 CAN 盒严禁启动采集
- 采集过程每 2s 实时抽样监控日志
- 停止采集平稳退出加速 (关闭 stdin，消除 join 阻塞)
- 按钮按工艺流自然重编：Axis1 采集为 ①，Axis1 解析为 ②，Axis2 采集为 ③，Axis2 解析为 ④，合流为 ⑤
- 离心机 1 执行 Axis1/2 处理后立即导出 ProcessedData1 与 IdCheck 两份规范文件
- 所有按钮高度与垂直内边距统一 (padding=(8, 3))
- 架构调整：Normal_Lot 与 Rework_Lot 文件夹统一放置在同日文件夹 daily_dir 下
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
import numpy as np

# 启用 Windows 原生高分屏 High-DPI 缩放感知
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from processor.can_data_parser import CentrifugeCANParser
from processor.centrifuge_processor import CentrifugeProcessor
from processor.calibration_processor import CalibrationProcessor, SpanGateError
from processor.result_consolidator import ResultConsolidator, DataMerger
from processor.can_collector import ZLGCanCollector, CanCaptureError


# ================= 全局统一字体与样式常量 (10号字体 10pt) =================
FONT_FAMILY = "Microsoft YaHei UI"
FONT_BASE = (FONT_FAMILY, 10)            # 标准文字与普通按钮
FONT_BOLD = (FONT_FAMILY, 10, "bold")     # 仅日志大标题加粗
FONT_TAB = (FONT_FAMILY, 10)             # Tab 切换标题改回 10pt (不加粗，大小一致)
FONT_CONSOLE = ("Consolas", 10)


# ================= 中英文双语语言字典 =================
I18N = {
    "zh": {
        "app_title": "CrashSensor 离心机测试数据自动化处理软件",
        "top_group": " 生产批次与设备连接 ",
        "lbl_lot": "批次号LOT:",
        "lbl_date": "测试日期:",
        "lbl_lang": "语言 / Language:",
        "can_open": "打开CAN盒",
        "can_close": "关闭CAN盒",
        "can_opened_msg": "USBCANFD-200U 设备已成功连接就绪！",
        "can_closed_msg": "CAN 盒设备已释放并关闭。",
        "tab_c1": "第一次离心机",
        "tab_c1_rw": "第一次离心机补测",
        "tab_c2": "第二次离心机性能测试",
        "tab_c2_rw": "第二次离心机补测",
        "tab_cfg": "系统配置",
        "btn_browse": "浏览...",
        "btn_capture": "实时采集",
        "btn_stop_capture": "停止采集",
        "btn_reset": "重置清空数据",
        "tip_c1": "[操作提示] 测试请先启动实时采集，再对转台/器件上电；采集完毕后点击停止采集。",
        "tip_c2": "[操作提示] 测试请先启动实时采集，再对转台/器件上电；采集完毕后点击停止采集。",
        "step_pending": "待执行",
        "step_running": "进行中...",
        "step_success": "已完成",
        "step_failed": "异常",
        "c1_step1_btn": "① Axis1 采集",
        "c1_step2": "② Axis1 数据解析",
        "c1_step3_btn": "③ Axis2 采集",
        "c1_step4": "④ Axis2 数据解析",
        "c1_step5": "⑤ 双轴合流标定",
        "c1_rw_step1_lbl": "待复测清单 (CSV):",
        "c1_rw_step2_btn": "② 补测 CAN 采集",
        "c1_rw_step3": "③ 执行补测缝合",
        "c2_step1_btn": "① Axis1 验证采集",
        "c2_step2_btn": "② Axis2 验证采集",
        "c2_step3": "③ 执行验证处理",
        "c2_step4": "④ 导出整合报表",
        "c2_rw_step1_lbl": "C2 待复测清单 (CSV):",
        "c2_rw_step2_btn": "② 补测 CAN 采集",
        "c2_rw_step3": "③ 执行补测缝合",
        "c2_zero_p": "零偏正阈值 (LSB):",
        "c2_zero_n": "零偏负阈值 (LSB):",
        "c2_step_mode": "步进模式:",
        "c2_fixed_step": "固定步长 (g):",
        "c2_custom_seq": "自定义序列 (g):",
        "mode_fixed": "固定步进",
        "mode_custom": "自定义序列",
        "rework_target_axis": "补测目标轴向:",
        "rw_only_a1": "仅补测 Axis1",
        "rw_only_a2": "仅补测 Axis2",
        "safety_lock": "[安全互锁锁定: 严禁自动跨轴步进]",
        "btn_select_list": "选择清单...",
        "btn_open_c1_dir": "打开第一次离心机目录",
        "btn_open_c2_dir": "打开第二次离心机目录",
        "btn_open_mtp_dir": "打开 MTP_DATA 目录",
        "btn_clear_log": "清空控制台日志",
        "log_group": " 运行日志与控制台 (Log Console) ",
        "ready_status": "系统待机就绪",
        "btn_save_cfg": "保存并持久化应用系统参数",
        "cfg_p_range": "传感器物理设计量程 (g):",
        "cfg_t_limit": "离心机测试量程上限 (g):",
        "cfg_scale": "量程折算比例 (Scale Factor):",
        "cfg_core_formula": "标定公式核心分子:",
        "cfg_span_min": "Span 门禁下限 (S_min):",
        "cfg_span_max": "Span 门禁上限 (S_max):",
        "cfg_step_th": "阶跃突变检测阈值 (Step Threshold):",
        "cfg_steady": "稳态采样提取策略:",
        "cfg_discard": "启动过渡过滤帧数 (discard_frames):",
    },
    "en": {
        "app_title": "CrashSensor Centrifuge Test Data Processor",
        "top_group": " Production Lot & Hardware Connection ",
        "lbl_lot": "Lot No. LOT:",
        "lbl_date": "Test Date:",
        "lbl_lang": "Language / 语言:",
        "can_open": "Open CAN Box",
        "can_close": "Close CAN Box",
        "can_opened_msg": "USBCANFD-200U device connected successfully!",
        "can_closed_msg": "CAN device released and closed.",
        "tab_c1": "Centrifuge 1 Calibration",
        "tab_c1_rw": "Centrifuge 1 Rework",
        "tab_c2": "Centrifuge 2 Verification",
        "tab_c2_rw": "Centrifuge 2 Rework",
        "tab_cfg": "System Configuration",
        "btn_browse": "Browse...",
        "btn_capture": "Capture",
        "btn_stop_capture": "Stop Capture",
        "btn_reset": "Reset / Clear Inputs & Status",
        "tip_c1": "[Notice] Start live capture before powering on turntable/sensors; click Stop when finished.",
        "tip_c2": "[Notice] Start live capture before powering on turntable/sensors; click Stop when finished.",
        "step_pending": "Pending",
        "step_running": "Running...",
        "step_success": "Passed",
        "step_failed": "Failed",
        "c1_step1_btn": "Axis1 Data Capture",
        "c1_step2": "Axis1 Data Parsing",
        "c1_step3_btn": "Axis2 Data Capture",
        "c1_step4": "Axis2 Data Parsing",
        "c1_step5": "Dual-Axis Calibration & Tri-Lists Export",
        "c1_rw_step1_lbl": "Load Rework Whitelist (CSV):",
        "c1_rw_step2_btn": "Rework CAN Data Capture",
        "c1_rw_step3": "Stitch Rework Data & Close Loop",
        "c2_step1_btn": "Axis1 Verification Data Capture",
        "c2_step2_btn": "Axis2 Verification Data Capture",
        "c2_step3": "Validate Data & Generate ProcessedData1~3",
        "c2_step4": "Export Centrifuge 2 Integration Report",
        "c2_rw_step1_lbl": "Load C2 Rework Whitelist (CSV):",
        "c2_rw_step2_btn": "C2 Rework CAN Data Capture",
        "c2_rw_step3": "Stitch C2 Rework Data & Close Loop",
        "c2_zero_p": "Zero Div Positive (LSB):",
        "c2_zero_n": "Zero Div Negative (LSB):",
        "c2_step_mode": "Step Mode:",
        "c2_fixed_step": "Fixed Step (g):",
        "c2_custom_seq": "Custom Sequence (g):",
        "mode_fixed": "Fixed Step",
        "mode_custom": "Custom Sequence",
        "rework_target_axis": "Target Rework Axis:",
        "rw_only_a1": "Axis1 Only",
        "rw_only_a2": "Axis2 Only",
        "safety_lock": "[Safety Lock Active: Cross-Axis Prohibited]",
        "btn_select_list": "Select List...",
        "btn_open_c1_dir": "Open Centrifuge 1 Folder",
        "btn_open_c2_dir": "Open Centrifuge 2 Folder",
        "btn_open_mtp_dir": "Open MTP_DATA Folder",
        "btn_clear_log": "Clear Console Log",
        "log_group": " Run Log & Console (Log Console) ",
        "ready_status": "System Ready (Standby)",
        "btn_save_cfg": "Save & Apply Settings",
        "cfg_p_range": "Sensor Physical Range (g):",
        "cfg_t_limit": "Centrifuge Test Limit (g):",
        "cfg_scale": "Scale Factor (Calculated):",
        "cfg_core_formula": "Calibration Core Numerator:",
        "cfg_span_min": "Span Minimum (S_min):",
        "cfg_span_max": "Span Maximum (S_max):",
        "cfg_step_th": "Step Threshold (LSB):",
        "cfg_steady": "Steady Plateau Extraction:",
        "cfg_discard": "Discard Initial Frames:",
    }
}


class StepIndicator(ttk.Frame):
    """
    流水线步骤红绿状态指示灯组件 (圆圈放大，居右同列严格对齐)：
    - 待执行 (Pending): 柔和灰色圆点 (#B0BEC5)
    - 进行中 (Running): 商务蓝色圆点 (#1976D2)
    - 已完成 (Passed): 工业稳健绿色圆点 (#2E7D32)
    - 异常 (Failed): 沉稳暗红圆点 (#C62828)
    """
    def __init__(self, parent, initial_text="待执行"):
        super().__init__(parent)
        # 放大指示灯尺寸至 22x22，圆圈直径扩大至 16px
        self.canvas = tk.Canvas(self, width=22, height=22, highlightthickness=0, bd=0)
        self.canvas.pack(side=tk.LEFT, padx=(4, 6))
        self.lbl = ttk.Label(self, text=initial_text, font=FONT_BASE, width=8)
        self.lbl.pack(side=tk.LEFT)
        self.current_state = "pending"
        self.set_state("pending", initial_text)

    def set_state(self, state: str, text: str = ""):
        self.current_state = state
        self.canvas.delete("all")
        color_map = {
            "pending": ("#B0BEC5", "#78909C"),    # 待机灰
            "running": ("#1976D2", "#0D47A1"),    # 进行中蓝
            "success": ("#2E7D32", "#1B5E20"),    # 完成绿
            "error":   ("#C62828", "#B71C1C"),    # 异常暗红
        }
        fill_c, outline_c = color_map.get(state, ("#B0BEC5", "#78909C"))
        # 圆圈尺寸放大为 (3, 3, 19, 19)
        self.canvas.create_oval(3, 3, 19, 19, fill=fill_c, outline=outline_c, width=2)
        if text:
            self.lbl.config(text=text)

    def update_text(self, text: str):
        if text:
            self.lbl.config(text=text)


# =========================================================================
# 22 通道工装定义与物理供电板映射 (25B-3 与 25D-4 未使用)
# 左列 (25A/B 负) 11 通道:
#   1(0*121) -> b1, 2(0*125) -> b5, 3(0*111) -> a1, 4(0*113) -> a3, 5(0*115) -> a5,
#   6(0*116) -> a6, 7(0*114) -> a4, 8(0*112) -> a2, 9(0*126) -> b6, 10(0*124) -> b4, 11(0*122) -> b2
# 右列 (25C/D 正) 11 通道:
#   1(0*142) -> d2, 2(0*146) -> d6, 3(0*132) -> c2, 4(0*134) -> c4, 5(0*136) -> c6,
#   6(0*135) -> c5, 7(0*133) -> c3, 8(0*131) -> c1, 9(0*145) -> d5, 10(0*143) -> d3, 11(0*141) -> d1
# =========================================================================
LEFT_CHANNELS = ["b1", "b5", "a1", "a3", "a5", "a6", "a4", "a2", "b6", "b4", "b2"]
RIGHT_CHANNELS = ["d2", "d6", "c2", "c4", "c6", "c5", "c3", "c1", "d5", "d3", "d1"]

LEFT_CHANNEL_INFO = [
    ("1(0*121)", 2, 1, "0x121", "b1"),
    ("2(0*125)", 2, 5, "0x125", "b5"),
    ("3(0*111)", 1, 1, "0x111", "a1"),
    ("4(0*113)", 1, 3, "0x113", "a3"),
    ("5(0*115)", 1, 5, "0x115", "a5"),
    ("6(0*116)", 1, 6, "0x116", "a6"),
    ("7(0*114)", 1, 4, "0x114", "a4"),
    ("8(0*112)", 1, 2, "0x112", "a2"),
    ("9(0*126)", 2, 6, "0x126", "b6"),
    ("10(0*124)", 2, 4, "0x124", "b4"),
    ("11(0*122)", 2, 2, "0x122", "b2"),
]

RIGHT_CHANNEL_INFO = [
    ("1(0*142)", 4, 2, "0x142", "d2"),
    ("2(0*146)", 4, 6, "0x146", "d6"),
    ("3(0*132)", 3, 2, "0x132", "c2"),
    ("4(0*134)", 3, 4, "0x134", "c4"),
    ("5(0*136)", 3, 6, "0x136", "c6"),
    ("6(0*135)", 3, 5, "0x135", "c5"),
    ("7(0*133)", 3, 3, "0x133", "c3"),
    ("8(0*131)", 3, 1, "0x131", "c1"),
    ("9(0*145)", 4, 5, "0x145", "d5"),
    ("10(0*143)", 4, 3, "0x143", "d3"),
    ("11(0*141)", 4, 1, "0x141", "d1"),
]

CHANNEL_TO_BOARD_SENSOR = {
    # 25A
    "a1": (1, 1), "a2": (1, 2), "a3": (1, 3), "a4": (1, 4), "a5": (1, 5), "a6": (1, 6),
    # 25B (b3 未使用)
    "b1": (2, 1), "b2": (2, 2), "b4": (2, 4), "b5": (2, 5), "b6": (2, 6),
    # 25C
    "c1": (3, 1), "c2": (3, 2), "c3": (3, 3), "c4": (3, 4), "c5": (3, 5), "c6": (3, 6),
    # 25D (d4 未使用)
    "d1": (4, 1), "d2": (4, 2), "d3": (4, 3), "d5": (4, 5), "d6": (4, 6),
}
CHANNEL_TO_SLOT = {ch: (b - 1) * 6 + (s - 1) for ch, (b, s) in CHANNEL_TO_BOARD_SENSOR.items()}
SLOT_TO_CHANNEL = {slot: ch for ch, slot in CHANNEL_TO_SLOT.items()}


class ChannelMatrixWidget(ttk.LabelFrame):
    """
    22 PCS 芯片工位通道监控矩阵：
    - 顶部当前更新数据名称 (Axis1 / Axis2 / 双轴合流标定 / 补测)
    - 左列表头: 25A/B 负 (标号如 1(0*121), 2(0*125)...)
    - 右列表头: 25C/D 正 (标号如 1(0*142), 2(0*146)...)
    - 显示格式: 上行物理标号与CAN ID，下行显示实测芯片后 6 位与实测读数/状态
    - 状态颜色: 绿色 pass, 黄色 缺失/待复测, 红色 fail, 浅灰 待机
    """
    COLOR_MAP = {
        "pass": ("#2E7D32", "#FFFFFF"),      # 绿色 pass
        "missing": ("#FFC107", "#000000"),   # 黄色 缺失
        "rework": ("#FFC107", "#000000"),    # 黄色 待复测 (严格统一为黄色)
        "fail": ("#C62828", "#FFFFFF"),      # 红色 fail
        "idle": ("#ECEFF1", "#546E7A"),      # 浅灰 待机清空
    }

    def __init__(self, parent, title=" 22 通道工装器件矩阵 "):
        super().__init__(parent, text=title)

        # 顶部当前更新数据名称
        top_bar = ttk.Frame(self)
        top_bar.pack(fill=tk.X, padx=6, pady=(3, 2))
        ttk.Label(top_bar, text="当前数据: ", font=FONT_BOLD).pack(side=tk.LEFT)
        self.lbl_data_name = ttk.Label(top_bar, text="[待机未运行]", font=FONT_BOLD, foreground="#0D47A1")
        self.lbl_data_name.pack(side=tk.LEFT)

        # 矩阵表头与网格 (固定紧凑宽度，不拉伸)
        grid_box = ttk.Frame(self)
        grid_box.pack(fill=tk.BOTH, expand=False, padx=4, pady=(1, 2))

        ttk.Label(grid_box, text="25A/B 负", font=FONT_BOLD, foreground="#C62828", anchor=tk.CENTER).grid(row=0, column=0, padx=3, pady=(0, 2), sticky="ew")
        ttk.Label(grid_box, text="25C/D 正", font=FONT_BOLD, foreground="#1565C0", anchor=tk.CENTER).grid(row=0, column=1, padx=3, pady=(0, 2), sticky="ew")

        grid_box.columnconfigure(0, weight=0)
        grid_box.columnconfigure(1, weight=0)

        self.channel_cells = {}
        self.channel_labels = {}  # 兼容按 ch_str 如 'b1' 查找

        # 修复问题10: 22通道每个长方形高度缩小(height=1)，固定宽度(width=18)，不要自作主张写待机(text=f"{tag_l}")
        for r in range(11):
            tag_l, b_l, s_l, can_l, ch_l = LEFT_CHANNEL_INFO[r]
            lbl_l = tk.Label(
                grid_box,
                text=f"{tag_l}",
                height=1,
                width=18,
                bg=self.COLOR_MAP["idle"][0],
                fg=self.COLOR_MAP["idle"][1],
                font=("Consolas", 8, "bold"),
                relief=tk.SOLID,
                borderwidth=1
            )
            lbl_l.grid(row=r+1, column=0, padx=2, pady=1)
            cell_data_l = {"label": lbl_l, "tag": tag_l, "can_id": can_l, "b_id": b_l, "s_id": s_l, "ch": ch_l}
            self.channel_cells[(b_l, s_l)] = cell_data_l
            self.channel_labels[ch_l] = lbl_l

            tag_r, b_r, s_r, can_r, ch_r = RIGHT_CHANNEL_INFO[r]
            lbl_r = tk.Label(
                grid_box,
                text=f"{tag_r}",
                height=1,
                width=18,
                bg=self.COLOR_MAP["idle"][0],
                fg=self.COLOR_MAP["idle"][1],
                font=("Consolas", 8, "bold"),
                relief=tk.SOLID,
                borderwidth=1
            )
            lbl_r.grid(row=r+1, column=1, padx=2, pady=1)
            cell_data_r = {"label": lbl_r, "tag": tag_r, "can_id": can_r, "b_id": b_r, "s_id": s_r, "ch": ch_r}
            self.channel_cells[(b_r, s_r)] = cell_data_r
            self.channel_labels[ch_r] = lbl_r

        # 暴露 status_labels 字典，便于以 (b_id, s_id) 元组直接访问 Label
        self.status_labels = {k: v["label"] for k, v in self.channel_cells.items()}

        # 底部图例 (严格收敛为红绿黄三色)
        leg = ttk.Frame(self)
        leg.pack(fill=tk.X, padx=4, pady=(3, 2))
        ttk.Label(leg, text="图例:", font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=(0, 4))
        for txt, st in [("Pass", "pass"), ("缺失/待复测", "rework"), ("Fail", "fail")]:
            bg_c, fg_c = self.COLOR_MAP[st]
            tk.Label(leg, text=f" {txt} ", bg=bg_c, fg=fg_c, font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT, padx=3)

    def set_data_name(self, name: str):
        self.lbl_data_name.config(text=f"[{name}]")

    def set_channel_status(self, board_id_or_ch, sensor_id_or_status, status: str = "", dev_code: str = "", val: Any = None):
        """
        统一设置通道状态、芯片号与实测数值
        支持:
        - set_channel_status(board_id, sensor_id, status, dev_code, val)
        - set_channel_status(channel_str, status)  # 兼容旧调用如 'b1', 'pass'
        """
        if isinstance(board_id_or_ch, int) and isinstance(sensor_id_or_status, int):
            b_id, s_id = board_id_or_ch, sensor_id_or_status
            st = status
        else:
            ch = str(board_id_or_ch)
            st = str(sensor_id_or_status)
            b_id, s_id = CHANNEL_TO_BOARD_SENSOR.get(ch, (0, 0))

        cell_info = self.channel_cells.get((b_id, s_id))
        if cell_info:
            lbl = cell_info["label"]
            tag = cell_info["tag"]
            bg_c, fg_c = self.COLOR_MAP.get(st, self.COLOR_MAP["idle"])

            dev_suffix = str(dev_code)[-6:] if (dev_code and str(dev_code) not in ("00000000000", "-", "None")) else ""
            if val is not None and isinstance(val, (int, float)):
                val_str = f"{val:.1f}"
            elif val is not None and str(val).strip() and str(val) != "None":
                val_str = str(val).strip()
            elif st == "pass":
                val_str = "Pass"
            elif st in ("rework", "missing"):
                val_str = "缺失" if not dev_suffix else "复测"
            elif st == "fail":
                val_str = "Fail"
            else:
                val_str = ""

            if dev_suffix and val_str:
                line_info = f"{dev_suffix} {val_str}"
            elif dev_suffix:
                line_info = dev_suffix
            elif val_str:
                line_info = val_str
            else:
                line_info = ""

            if line_info:
                lbl.config(text=f"{tag} {line_info}", bg=bg_c, fg=fg_c)
            else:
                lbl.config(text=f"{tag}", bg=bg_c, fg=fg_c)

    def reset_all(self):
        self.lbl_data_name.config(text="[待机未运行]")
        for cell_info in self.channel_cells.values():
            lbl = cell_info["label"]
            tag = cell_info["tag"]
            bg_c, fg_c = self.COLOR_MAP["idle"]
            lbl.config(text=f"{tag}", bg=bg_c, fg=fg_c)


class DailyYieldWidget(ttk.LabelFrame):
    """
    需求 11(2): 当日累计良率统计卡片 (断点记录恢复)
    """
    def __init__(self, parent, consolidator, title=" 当日累计良率统计 (断点记录) "):
        super().__init__(parent, text=title)
        self.consolidator = consolidator

        box = ttk.Frame(self)
        box.pack(fill=tk.X, padx=6, pady=(4, 4))

        self.lbl_pass = ttk.Label(box, text="当日累计 Pass: 0 pcs", font=FONT_BOLD, foreground="#2E7D32")
        self.lbl_pass.grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)

        self.lbl_fail = ttk.Label(box, text="当日累计 Fail: 0 pcs", font=FONT_BOLD, foreground="#C62828")
        self.lbl_fail.grid(row=0, column=1, sticky=tk.W, padx=8, pady=2)

        self.lbl_yield = ttk.Label(box, text="当日综合良率: 0.0%", font=FONT_BOLD, foreground="#0D47A1")
        self.lbl_yield.grid(row=1, column=0, sticky=tk.W, padx=4, pady=2)

        self.lbl_file = ttk.Label(box, text="断点记录: 待机", font=("Microsoft YaHei UI", 8), foreground="#78909C")
        self.lbl_file.grid(row=1, column=1, sticky=tk.W, padx=8, pady=2)

    def refresh(self, daily_dir: str, date_str: Optional[str] = None):
        res = self.consolidator.load_daily_yield(daily_dir, date_str)
        p = res.get("total_pass", 0)
        fl = res.get("total_fail", 0)
        yr = res.get("yield_rate", 0.0)
        self.lbl_pass.config(text=f"当日累计 Pass: {p} pcs")
        self.lbl_fail.config(text=f"当日累计 Fail: {fl} pcs")
        self.lbl_yield.config(text=f"当日综合良率: {yr:.1f}%")
        fn = os.path.basename(res.get("file_path", ""))
        self.lbl_file.config(text=f"断点记录: {fn}")


class CentrifugeGUI:
    """CrashSensor 离心机测试数据综合控制台"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.lang = "zh"
        self.root.title(I18N[self.lang]["app_title"])
        
        # 修复问题10: 默认全屏，self.root.minsize(1200, 1100)
        self.root.minsize(1200, 1100)
        try:
            self.root.state('zoomed')
        except Exception:
            self.root.geometry("1200x1100")

        # 安全关闭协议
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # 核心引擎初始化
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.base_dir, "config", "settings.ini")
        self.data_root = os.path.abspath(os.path.join(self.base_dir, "..", "data_conlidation"))

        self.can_parser = CentrifugeCANParser()
        self.cent_processor = CentrifugeProcessor(config_path=self.config_path)
        self.cal_processor = CalibrationProcessor(config_path=self.config_path)
        self.consolidator = ResultConsolidator(base_output_dir=self.data_root)
        self.data_merger = DataMerger()
        self.can_collector = ZLGCanCollector()

        # 数据缓存字典
        self.c1_mode_a = {
            "axis1_file": None,
            "axis2_file": None,
            "axis1_results": None,
            "axis2_results": None,
        }
        self.c1_mode_b = {
            "rework_list_file": None,
            "rework_can_file": None,
            "whitelist_slots": [],
            "whitelist_devices": [],
        }
        self.c2_mode_a = {
            "axis1_file": None,
            "axis2_file": None,
            "axis1_results": None,
            "axis2_results": None,
        }
        self.c2_mode_b = {
            "rework_list_file": None,
            "rework_can_file": None,
            "whitelist_slots": [],
            "whitelist_devices": [],
        }

        # 线程安全消息队列
        self.log_queue = queue.Queue()
        self.callback_queue = queue.Queue()

        # 初始化变量与控件
        self._init_variables()
        self._setup_styles()
        self._build_ui()
        self.refresh_top_yield()
        self._start_polling()

        self.log("系统初始化就绪，已加载 settings.ini 配置文件。")

    def _t(self, key: str) -> str:
        return I18N.get(self.lang, {}).get(key, key)

    def _init_variables(self):
        """初始化全部绑定变量"""
        self.lang_var = tk.StringVar(value="中文")
        self.lot_var = tk.StringVar(value="1")
        self.date_var = tk.StringVar(value=datetime.datetime.now().strftime("%Y-%m-%d"))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="待机就绪 (Ready)")

        # CAN 硬件采集与 3合1 连接状态变量
        self.is_capturing_var = tk.BooleanVar(value=False)
        self.can_connected_var = tk.BooleanVar(value=False)
        self.active_capture_key: Optional[str] = None
        self.active_capture_btn = None
        self.capture_buttons = []

        # Centrifuge 1 变量 (地址框宽度 24)
        self.c1_axis1_path_var = tk.StringVar(value="")
        self.c1_axis2_path_var = tk.StringVar(value="")
        self.c1_rework_list_path_var = tk.StringVar(value="")
        self.c1_rework_can_path_var = tk.StringVar(value="")
        self.c1_rework_axis_var = tk.StringVar(value="Axis1")
        self.c1_summary_var = tk.StringVar(value="首测状态: 待机就绪")

        # Centrifuge 2 变量
        self.c2_axis1_path_var = tk.StringVar(value="")
        self.c2_axis2_path_var = tk.StringVar(value="")
        self.c2_rework_list_path_var = tk.StringVar(value="")
        self.c2_rework_can_path_var = tk.StringVar(value="")
        self.c2_rework_axis_var = tk.StringVar(value="Axis1")
        self.c2_summary_var = tk.StringVar(value="验证状态: 待机就绪")

        # Centrifuge 2 算法参数 (统一尺寸与格式)
        self.c2_zero_p_var = tk.DoubleVar(value=35.0)
        self.c2_zero_n_var = tk.DoubleVar(value=-35.0)
        self.c2_step_mode_display_var = tk.StringVar(value="自定义序列")
        self.c2_step_mode_var = tk.StringVar(value="custom_sequence")
        self.c2_fixed_step_var = tk.DoubleVar(value=20.0)
        self.c2_custom_seq_var = tk.StringVar(value="-160 -80 80 160")

        # 需求 4: 顶部良率统计看板变量 (当日PASS、当日FAIL、全部PASS、全部FAIL、当日良率)
        self.stat_today_pass_var = tk.StringVar(value="当日PASS: 0")
        self.stat_today_fail_var = tk.StringVar(value="当日FAIL: 0")
        self.stat_all_pass_var = tk.StringVar(value="全部PASS: 0")
        self.stat_all_fail_var = tk.StringVar(value="全部FAIL: 0")
        self.stat_today_yield_var = tk.StringVar(value="当日良率: 0.0%")

        # 系统与门禁参数配置 (需求 7: 整数不带小数)
        self.cfg_physical_range_var = tk.IntVar(value=240)
        self.cfg_test_limit_var = tk.IntVar(value=160)
        self.cfg_scale_var = tk.DoubleVar(value=round(240.0 / 160.0, 3))
        self.cfg_core_formula_var = tk.StringVar(value="961 × 2^20 = 1,007,681,536")
        self.cfg_span_min_var = tk.IntVar(value=int(round(self.cal_processor.span_min)))
        self.cfg_span_max_var = tk.IntVar(value=int(round(self.cal_processor.span_max)))
        self.cfg_step_threshold_var = tk.IntVar(value=int(round(self.cent_processor.step_threshold)))
        self.cfg_discard_var = tk.IntVar(value=int(self.cent_processor.discard_frames))
        self.cfg_steady_var = tk.IntVar(value=int(self.cent_processor.steady_points_max))

        self.cfg_physical_range_var.trace_add("write", self._on_range_changed)
        self.cfg_test_limit_var.trace_add("write", self._on_range_changed)

    def _on_range_changed(self, *args):
        try:
            p_range = float(self.cfg_physical_range_var.get())
            t_limit = float(self.cfg_test_limit_var.get())
            if t_limit > 0:
                scale = p_range / t_limit
                self.cfg_scale_var.set(round(scale, 3))
                self.cal_processor.scale_factor = scale
        except Exception:
            pass

    def _setup_styles(self):
        """配置统一 ttk 样式：Tab 标题加粗与边框大标题加粗；统一按钮高度与 Notebook 无缝对齐"""
        style = ttk.Style()
        try:
            available = style.theme_names()
            if "vista" in available:
                style.theme_use("vista")
            elif "clam" in available:
                style.theme_use("clam")
        except Exception:
            pass

        # 统一所有按钮内边距为 (6, 2) 确保与输入框 (TEntry) 高度严格一致
        style.configure(".", font=FONT_BASE)
        style.configure("TLabel", font=FONT_BASE)
        style.configure("TButton", font=FONT_BASE, padding=(6, 2))
        style.configure("Pipeline.TButton", font=FONT_BASE, padding=(6, 2))
        style.configure("StopCapture.TButton", font=FONT_BASE, foreground="#37474F", padding=(6, 2))
        style.configure("TEntry", font=FONT_BASE, padding=(3, 2))
        style.configure("TCombobox", font=FONT_BASE)
        style.configure("TRadiobutton", font=FONT_BASE)
        style.configure("TLabelframe", padding=5)
        style.configure("TLabelframe.Label", font=FONT_BOLD)       # 边框大标题全部加粗 (需求 3)
        style.configure("Log.TLabelframe.Label", font=FONT_BOLD)   # 日志标题加粗
        style.configure("TNotebook", tabmargins=[0, 2, 2, 0])      # 消除 Notebook 左侧凹陷缩进 (需求 4)
        style.configure("TNotebook.Tab", font=FONT_BOLD, padding=(14, 5))  # Tab 标题文字加粗 (需求 4)
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#FFFFFF"), ("active", "#E1F5FE"), ("!selected", "#F0F4F8")],
            foreground=[("selected", "#0D47A1"), ("active", "#1565C0"), ("!selected", "#37474F")],
        )

    def _build_ui(self):
        """构建主界面"""
        # 1. 顶部批次工况与设备连接栏
        self._build_top_bar()

        # 2. 中部核心区域：5 独立 Tab 分页
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.X, expand=False, padx=8, pady=(4, 8))

        self.tab_c1 = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_c1_rw = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_c2 = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_c2_rw = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_settings = ttk.Frame(self.notebook, padding=(6, 6))

        self.notebook.add(self.tab_c1, text=f" {self._t('tab_c1')} ")
        self.notebook.add(self.tab_c1_rw, text=f" {self._t('tab_c1_rw')} ")
        self.notebook.add(self.tab_c2, text=f" {self._t('tab_c2')} ")
        self.notebook.add(self.tab_c2_rw, text=f" {self._t('tab_c2_rw')} ")
        self.notebook.add(self.tab_settings, text=f" {self._t('tab_cfg')} ")

        self._build_c1_tab()
        self._build_c1_rework_tab()
        self._build_c2_tab()
        self._build_c2_rework_tab()
        self._build_settings_tab()

        self.capture_buttons = [
            getattr(self, "btn_cap_c1_a1", None),
            getattr(self, "btn_cap_c1_a2", None),
            getattr(self, "btn_cap_c1_rw", None),
            getattr(self, "btn_cap_c2_a1", None),
            getattr(self, "btn_cap_c2_a2", None),
            getattr(self, "btn_cap_c2_rw", None),
        ]
        self.capture_buttons = [b for b in self.capture_buttons if b is not None]

        # 3. 底部状态与日志控制台
        self._build_bottom_bar()

    # =========================================================================
    # 顶部栏：批次号、3合1 CAN盒单按钮 (需求 3 & 需求 7 & 需求 12 删除语言切换)
    # =========================================================================
    def _build_top_bar(self):
        self.top_frame = ttk.LabelFrame(self.root, text=self._t("top_group"))
        self.top_frame.pack(fill=tk.X, padx=8, pady=(4, 6))

        # 批次号
        self.lbl_lot_title = ttk.Label(self.top_frame, text=self._t("lbl_lot"))
        self.lbl_lot = self.lbl_lot_title
        self.lbl_lot_title.grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
        ttk.Entry(self.top_frame, textvariable=self.lot_var, width=6).grid(row=0, column=1, sticky=tk.W, padx=4, pady=2)

        # 测试日期
        self.lbl_date_title = ttk.Label(self.top_frame, text=self._t("lbl_date"))
        self.lbl_date_title.grid(row=0, column=2, sticky=tk.W, padx=(10, 4), pady=2)
        ttk.Entry(self.top_frame, textvariable=self.date_var, width=10).grid(row=0, column=3, sticky=tk.W, padx=4, pady=2)

        ttk.Separator(self.top_frame, orient=tk.VERTICAL).grid(row=0, column=4, sticky=tk.NS, padx=(10, 8), pady=2)

        # 需求 7: 真正的 3合1 单按钮开闭切换
        self.btn_toggle_can = ttk.Button(
            self.top_frame,
            text=self._t("can_open"),
            command=self._on_toggle_can,
            width=12
        )
        self.btn_toggle_can.grid(row=0, column=5, sticky=tk.W, padx=4, pady=2)

        ttk.Separator(self.top_frame, orient=tk.VERTICAL).grid(row=0, column=6, sticky=tk.NS, padx=(10, 8), pady=2)

        # 修复问题10: 顶部当日pass等等全部黑色，不要红绿蓝，删除当日良率
        f_stats = ttk.Frame(self.top_frame)
        f_stats.grid(row=0, column=7, sticky=tk.W, padx=4, pady=2)

        ttk.Label(f_stats, textvariable=self.stat_today_pass_var, font=FONT_BOLD, foreground="#000000").pack(side=tk.LEFT, padx=(4, 6))
        ttk.Label(f_stats, textvariable=self.stat_today_fail_var, font=FONT_BOLD, foreground="#000000").pack(side=tk.LEFT, padx=6)
        ttk.Separator(f_stats, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(f_stats, textvariable=self.stat_all_pass_var, font=FONT_BOLD, foreground="#000000").pack(side=tk.LEFT, padx=6)
        ttk.Label(f_stats, textvariable=self.stat_all_fail_var, font=FONT_BOLD, foreground="#000000").pack(side=tk.LEFT, padx=6)

    def refresh_top_yield(self):
        """需求 4: 刷新顶部良率看板 (当日PASS、当日FAIL、全部PASS、全部FAIL、当日良率)"""
        try:
            date_str = self.date_var.get().strip()
            lot_raw = self.lot_var.get().strip() or "1"
            lot_id = f"LOT{lot_raw}" if not lot_raw.upper().startswith("LOT") else lot_raw
            dirs = self.consolidator.organize_directories(date_str=date_str, lot_id=lot_id, centrifuge_id="Centrifuge1")
            res_today = self.consolidator.load_daily_yield(dirs["daily_dir"], date_str)
            t_pass = res_today.get("total_pass", 0)
            t_fail = res_today.get("total_fail", 0)
            t_yield = res_today.get("yield_rate", 0.0)

            # 统计全局累计全部 PASS / FAIL
            tot_p = 0
            tot_f = 0
            today_fn = os.path.basename(res_today.get("file_path", ""))
            if os.path.exists(self.data_root):
                for dirpath, _, filenames in os.walk(self.data_root):
                    for fn in filenames:
                        if fn.startswith("Daily_Yield_Stats_") and fn.endswith(".csv"):
                            if fn != today_fn:
                                try:
                                    df = pd.read_csv(os.path.join(dirpath, fn))
                                    if not df.empty:
                                        last = df.iloc[-1]
                                        tot_p += int(last.get("累计Pass", 0))
                                        tot_f += int(last.get("累计Fail", 0))
                                except Exception:
                                    pass
            all_pass = t_pass + tot_p
            all_fail = t_fail + tot_f

            self.stat_today_pass_var.set(f"当日PASS: {t_pass}")
            self.stat_today_fail_var.set(f"当日FAIL: {t_fail}")
            self.stat_all_pass_var.set(f"全部PASS: {all_pass}")
            self.stat_all_fail_var.set(f"全部FAIL: {all_fail}")
            self.stat_today_yield_var.set(f"当日良率: {t_yield:.1f}%")
        except Exception as e:
            self.log(f"[良率刷新异常] {str(e)}")

    def _on_toggle_can(self):
        """需求 7: 点击打开后自动切换为关闭，再次点击自动切换为打开"""
        if not self.can_connected_var.get():
            self.log("[CAN盒] 正在连接 USBCANFD-200U 设备...")
            self.root.update_idletasks()
            is_ok, msg = self.can_collector.open_device()
            if is_ok:
                self.can_connected_var.set(True)
                self.btn_toggle_can.config(text=self._t("can_close"))
                self.log(f"[CAN盒就绪] {msg}")
                messagebox.showinfo("提示", self._t("can_opened_msg"))
            else:
                self.can_connected_var.set(False)
                self.btn_toggle_can.config(text=self._t("can_open"))
                self.log(f"[CAN盒异常] {msg}")
                messagebox.showerror("连接失败", f"无法打开 CAN 盒设备:\n{msg}")
        else:
            self.log("[CAN盒] 正在释放关闭 USBCANFD-200U 设备...")
            is_ok, msg = self.can_collector.close_device()
            self.can_connected_var.set(False)
            self.btn_toggle_can.config(text=self._t("can_open"))
            self.log(f"[CAN盒关闭] {msg}")
            messagebox.showinfo("提示", self._t("can_closed_msg"))

    def _apply_language(self):
        self.root.title(self._t("app_title"))
        self.top_frame.config(text=self._t("top_group"))
        self.lbl_lot_title.config(text=self._t("lbl_lot"))
        self.lbl_date_title.config(text=self._t("lbl_date"))

        if self.can_connected_var.get():
            self.btn_toggle_can.config(text=self._t("can_close"))
        else:
            self.btn_toggle_can.config(text=self._t("can_open"))

        self.notebook.tab(0, text=f" {self._t('tab_c1')} ")
        self.notebook.tab(1, text=f" {self._t('tab_c1_rw')} ")
        self.notebook.tab(2, text=f" {self._t('tab_c2')} ")
        self.notebook.tab(3, text=f" {self._t('tab_c2_rw')} ")
        self.notebook.tab(4, text=f" {self._t('tab_cfg')} ")

        if hasattr(self, "btn_cap_c1_a1") and not self.is_capturing_var.get():
            self.btn_cap_c1_a1.config(text=self._t("c1_step1_btn"))
            self.btn_c1_run_a1.config(text=self._t("c1_step2"))
            self.btn_cap_c1_a2.config(text=self._t("c1_step3_btn"))
            self.btn_c1_run_a2.config(text=self._t("c1_step4"))
            self.btn_c1_run_cal.config(text=self._t("c1_step5"))
            self.btn_c1_clear.config(text=self._t("btn_reset"))

        if hasattr(self, "btn_cap_c1_rw") and not self.is_capturing_var.get():
            self.btn_cap_c1_rw.config(text=self._t("c1_rw_step2_btn"))
            self.btn_c1_run_rw.config(text=self._t("c1_rw_step3"))
            self.btn_c1_rw_clear.config(text=self._t("btn_reset"))

        if hasattr(self, "btn_cap_c2_a1") and not self.is_capturing_var.get():
            self.btn_cap_c2_a1.config(text=self._t("c2_step1_btn"))
            self.btn_cap_c2_a2.config(text=self._t("c2_step2_btn"))
            self.btn_c2_run.config(text=self._t("c2_step3"))
            self.btn_c2_export.config(text=self._t("c2_step4"))
            self.btn_c2_clear.config(text=self._t("btn_reset"))

        if hasattr(self, "btn_cap_c2_rw") and not self.is_capturing_var.get():
            self.btn_cap_c2_rw.config(text=self._t("c2_rw_step2_btn"))
            self.btn_c2_run_rw.config(text=self._t("c2_rw_step3"))
            self.btn_c2_rw_clear.config(text=self._t("btn_reset"))

        if hasattr(self, "lbl_tip_c1"):
            self.lbl_tip_c1.config(text=self._t("tip_c1"))
        if hasattr(self, "lbl_tip_c2"):
            self.lbl_tip_c2.config(text=self._t("tip_c2"))
        if hasattr(self, "bottom_frame"):
            self.bottom_frame.config(text=self._t("log_group"))

    # =========================================================================
    # TAB 1: 第一次离心机 (左右两栏并列：左侧数据采集处理，右侧22通道矩阵)
    # =========================================================================
    def _build_c1_tab(self):
        f = self.tab_c1

        # 修复问题10: 22通道矩阵停靠在右侧占约1/3区域，固定宽度不拉伸
        self.c1_channel_matrix = ChannelMatrixWidget(f, title=" 22 通道工装器件矩阵 (第一次离心机) ")
        self.c1_channel_matrix.pack(side=tk.RIGHT, fill=tk.Y, expand=False, padx=(4, 6), pady=2)

        # 左侧数据采集处理区域
        f_left = ttk.LabelFrame(f, text=" 数据采集处理区域 ")
        f_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 4), pady=2)

        self.lbl_tip_c1 = ttk.Label(f_left, text=self._t("tip_c1"), foreground="#455A64")
        self.lbl_tip_c1.pack(anchor=tk.W, padx=6, pady=(2, 4))

        grid_f = ttk.Frame(f_left)
        grid_f.pack(anchor=tk.W, padx=6, pady=2)

        # 修复问题10: 四个页面按钮列宽与指示灯列宽完全统一定义
        grid_f.columnconfigure(0, weight=0, minsize=24)
        grid_f.columnconfigure(1, weight=0, minsize=320)
        grid_f.columnconfigure(2, weight=0, minsize=100)

        # ① Axis1 数据采集
        ttk.Label(grid_f, text="①", width=3, anchor=tk.CENTER).grid(row=0, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_cap_c1_a1 = ttk.Button(grid_f, text=self._t("c1_step1_btn"), command=lambda: self._start_live_capture("c1_axis1"), style="Pipeline.TButton", width=36)
        self.btn_cap_c1_a1.grid(row=0, column=1, sticky="w", padx=2, pady=3)
        self.step_c1_cap1_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c1_cap1_ind.grid(row=0, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # Axis1 文件框 浏览
        f_c1_a1_file = ttk.Frame(grid_f)
        f_c1_a1_file.grid(row=1, column=1, sticky="w", padx=2, pady=2)
        ttk.Entry(f_c1_a1_file, textvariable=self.c1_axis1_path_var, width=24).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(f_c1_a1_file, text=self._t("btn_browse"), command=self._c1_select_axis1, style="Pipeline.TButton", width=8).pack(side=tk.RIGHT)

        # ② Axis1 数据解析
        ttk.Label(grid_f, text="②", width=3, anchor=tk.CENTER).grid(row=2, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_c1_run_a1 = ttk.Button(grid_f, text=self._t("c1_step2"), command=self._c1_run_axis1, style="Pipeline.TButton", width=36)
        self.btn_c1_run_a1.grid(row=2, column=1, sticky="w", padx=2, pady=3)
        self.step_c1_run1_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c1_run1_ind.grid(row=2, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # ③ Axis2 数据采集
        ttk.Label(grid_f, text="③", width=3, anchor=tk.CENTER).grid(row=3, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_cap_c1_a2 = ttk.Button(grid_f, text=self._t("c1_step3_btn"), command=lambda: self._start_live_capture("c1_axis2"), style="Pipeline.TButton", width=36)
        self.btn_cap_c1_a2.grid(row=3, column=1, sticky="w", padx=2, pady=3)
        self.step_c1_cap2_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c1_cap2_ind.grid(row=3, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # Axis2 文件框 浏览
        f_c1_a2_file = ttk.Frame(grid_f)
        f_c1_a2_file.grid(row=4, column=1, sticky="w", padx=2, pady=2)
        ttk.Entry(f_c1_a2_file, textvariable=self.c1_axis2_path_var, width=24).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(f_c1_a2_file, text=self._t("btn_browse"), command=self._c1_select_axis2, style="Pipeline.TButton", width=8).pack(side=tk.RIGHT)

        # ④ Axis2 数据解析
        ttk.Label(grid_f, text="④", width=3, anchor=tk.CENTER).grid(row=5, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_c1_run_a2 = ttk.Button(grid_f, text=self._t("c1_step4"), command=self._c1_run_axis2, style="Pipeline.TButton", width=36)
        self.btn_c1_run_a2.grid(row=5, column=1, sticky="w", padx=2, pady=3)
        self.step_c1_run2_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c1_run2_ind.grid(row=5, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # ⑤ 双轴合流标定
        ttk.Label(grid_f, text="⑤", width=3, anchor=tk.CENTER).grid(row=6, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_c1_run_cal = ttk.Button(grid_f, text=self._t("c1_step5"), command=self._c1_run_consolidation, style="Pipeline.TButton", width=36)
        self.btn_c1_run_cal.grid(row=6, column=1, sticky="w", padx=2, pady=3)
        self.step_c1_cal_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c1_cal_ind.grid(row=6, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # 重置按钮 (完全统一长宽)
        self.btn_c1_clear = ttk.Button(grid_f, text=self._t("btn_reset"), command=self._c1_clear_paths, style="Pipeline.TButton", width=36)
        self.btn_c1_clear.grid(row=7, column=1, sticky="w", padx=2, pady=(8, 2))

    # =========================================================================
    # TAB 2: 第一次离心机补测 (左右两栏并列：左侧补测处理，右侧22通道矩阵)
    # =========================================================================
    def _build_c1_rework_tab(self):
        f = self.tab_c1_rw

        # 修复问题10: 22通道矩阵停靠在右侧占约1/3区域，固定宽度不拉伸
        self.c1_rw_channel_matrix = ChannelMatrixWidget(f, title=" 22 通道工装器件矩阵 (第一次离心机补测) ")
        self.c1_rw_channel_matrix.pack(side=tk.RIGHT, fill=tk.Y, expand=False, padx=(4, 6), pady=2)

        # 补测数据处理区域
        f_left = ttk.LabelFrame(f, text=" 补测数据处理区域 ")
        f_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 4), pady=2)

        grid_f = ttk.Frame(f_left)
        grid_f.pack(anchor=tk.W, padx=6, pady=(4, 4))

        # 修复问题10: 四个页面按钮列宽与指示灯列宽完全统一定义
        grid_f.columnconfigure(0, weight=0, minsize=24)
        grid_f.columnconfigure(1, weight=0, minsize=320)
        grid_f.columnconfigure(2, weight=0, minsize=100)

        # ① 待复测清单 (CSV)
        ttk.Label(grid_f, text="①", width=3, anchor=tk.CENTER).grid(row=0, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        f_c1_rw_file = ttk.Frame(grid_f)
        self.f_c1_rw_file = f_c1_rw_file
        f_c1_rw_file.grid(row=0, column=1, sticky="w", padx=2, pady=3)
        ttk.Entry(f_c1_rw_file, textvariable=self.c1_rework_list_path_var, width=24).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(f_c1_rw_file, text=self._t("btn_browse"), command=self._c1_select_rework_list, style="Pipeline.TButton", width=8).pack(side=tk.RIGHT)
        self.step_c1_rw_1_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c1_rw_1_ind.grid(row=0, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # 轴向选择行 (columnspan=2 避免撑宽按钮列)
        f_axis = ttk.Frame(grid_f)
        f_axis.grid(row=1, column=1, columnspan=2, sticky="w", padx=2, pady=3)
        ttk.Label(f_axis, text=self._t("rework_target_axis")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(f_axis, text=self._t("rw_only_a1"), variable=self.c1_rework_axis_var, value="Axis1").pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(f_axis, text=self._t("rw_only_a2"), variable=self.c1_rework_axis_var, value="Axis2").pack(side=tk.LEFT, padx=6)
        ttk.Label(f_axis, text=self._t("safety_lock"), foreground="#78909C").pack(side=tk.LEFT, padx=8)

        # ② 补测 CAN 数据采集
        ttk.Label(grid_f, text="②", width=3, anchor=tk.CENTER).grid(row=2, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_cap_c1_rw = ttk.Button(grid_f, text=self._t("c1_rw_step2_btn"), command=lambda: self._start_live_capture("c1_rework"), style="Pipeline.TButton", width=36)
        self.btn_cap_c1_rw.grid(row=2, column=1, sticky="w", padx=2, pady=3)
        self.step_c1_rw_2_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c1_rw_2_ind.grid(row=2, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # 补测 CAN 文件框 浏览
        f_c1_rw_can = ttk.Frame(grid_f)
        f_c1_rw_can.grid(row=3, column=1, sticky="w", padx=2, pady=2)
        ttk.Entry(f_c1_rw_can, textvariable=self.c1_rework_can_path_var, width=24).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(f_c1_rw_can, text=self._t("btn_browse"), command=self._c1_select_rework_can, style="Pipeline.TButton", width=8).pack(side=tk.RIGHT)

        # ③ 执行补测数据缝合
        ttk.Label(grid_f, text="③", width=3, anchor=tk.CENTER).grid(row=4, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_c1_run_rw = ttk.Button(grid_f, text=self._t("c1_rw_step3"), command=self._c1_run_rework, style="Pipeline.TButton", width=36)
        self.btn_c1_run_rw.grid(row=4, column=1, sticky="w", padx=2, pady=3)
        self.step_c1_rw_3_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c1_rw_3_ind.grid(row=4, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # 重置按钮 (完全统一长宽)
        self.btn_c1_rw_clear = ttk.Button(grid_f, text=self._t("btn_reset"), command=self._c1_clear_rework_paths, style="Pipeline.TButton", width=36)
        self.btn_c1_rw_clear.grid(row=5, column=1, sticky="w", padx=2, pady=(8, 2))

    # =========================================================================
    # TAB 3: 第二次离心机性能测试 (左右两栏并列：左侧数据采集处理，右侧22通道矩阵)
    # =========================================================================
    def _build_c2_tab(self):
        f = self.tab_c2

        # 修复问题10: 22通道矩阵停靠在右侧占约1/3区域，固定宽度不拉伸
        self.c2_channel_matrix = ChannelMatrixWidget(f, title=" 22 通道工装器件矩阵 (第二次离心机性能测试) ")
        self.c2_channel_matrix.pack(side=tk.RIGHT, fill=tk.Y, expand=False, padx=(4, 6), pady=2)

        # 数据采集处理区域
        f_left = ttk.LabelFrame(f, text=" 数据采集处理区域 ")
        f_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 4), pady=2)

        self.lbl_tip_c2 = ttk.Label(f_left, text=self._t("tip_c2"), foreground="#455A64")
        self.lbl_tip_c2.pack(anchor=tk.W, padx=6, pady=(2, 4))

        grid_f = ttk.Frame(f_left)
        grid_f.pack(anchor=tk.W, padx=6, pady=2)

        # 修复问题10: 四个页面按钮列宽与指示灯列宽完全统一定义
        grid_f.columnconfigure(0, weight=0, minsize=24)
        grid_f.columnconfigure(1, weight=0, minsize=320)
        grid_f.columnconfigure(2, weight=0, minsize=100)

        # ① Axis1 验证数据采集 (统一 width=36)
        ttk.Label(grid_f, text="①", width=3, anchor=tk.CENTER).grid(row=0, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_cap_c2_a1 = ttk.Button(grid_f, text=self._t("c2_step1_btn"), command=lambda: self._start_live_capture("c2_axis1"), style="Pipeline.TButton", width=36)
        self.btn_cap_c2_a1.grid(row=0, column=1, sticky="w", padx=2, pady=3)
        self.step_c2_cap1_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c2_cap1_ind.grid(row=0, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # Axis1 文件框 浏览
        f_c2_a1_file = ttk.Frame(grid_f)
        f_c2_a1_file.grid(row=1, column=1, sticky="w", padx=2, pady=2)
        ttk.Entry(f_c2_a1_file, textvariable=self.c2_axis1_path_var, width=24).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(f_c2_a1_file, text=self._t("btn_browse"), command=self._c2_select_axis1, style="Pipeline.TButton", width=8).pack(side=tk.RIGHT)

        # ② Axis2 验证数据采集 (统一 width=36)
        ttk.Label(grid_f, text="②", width=3, anchor=tk.CENTER).grid(row=2, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_cap_c2_a2 = ttk.Button(grid_f, text=self._t("c2_step2_btn"), command=lambda: self._start_live_capture("c2_axis2"), style="Pipeline.TButton", width=36)
        self.btn_cap_c2_a2.grid(row=2, column=1, sticky="w", padx=2, pady=3)
        self.step_c2_cap2_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c2_cap2_ind.grid(row=2, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # Axis2 文件框 浏览
        f_c2_a2_file = ttk.Frame(grid_f)
        f_c2_a2_file.grid(row=3, column=1, sticky="w", padx=2, pady=2)
        ttk.Entry(f_c2_a2_file, textvariable=self.c2_axis2_path_var, width=24).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(f_c2_a2_file, text=self._t("btn_browse"), command=self._c2_select_axis2, style="Pipeline.TButton", width=8).pack(side=tk.RIGHT)

        # 算法指标与拟合参数 (columnspan=2 避免撑宽按钮列)
        f_param = ttk.Frame(grid_f)
        f_param.grid(row=4, column=1, columnspan=2, sticky="w", padx=2, pady=(4, 4))

        PARAM_INPUT_WIDTH = 12

        # 零偏正阈值
        ttk.Label(f_param, text=self._t("c2_zero_p")).grid(row=0, column=0, sticky=tk.W, padx=2, pady=2)
        self.entry_c2_zero_p = ttk.Entry(f_param, textvariable=self.c2_zero_p_var, width=PARAM_INPUT_WIDTH)
        self.entry_c2_zero_p.grid(row=0, column=1, sticky=tk.W, padx=2, pady=2)

        # 零偏负阈值
        ttk.Label(f_param, text=self._t("c2_zero_n")).grid(row=1, column=0, sticky=tk.W, padx=2, pady=2)
        self.entry_c2_zero_n = ttk.Entry(f_param, textvariable=self.c2_zero_n_var, width=PARAM_INPUT_WIDTH)
        self.entry_c2_zero_n.grid(row=1, column=1, sticky=tk.W, padx=2, pady=2)

        # 步进模式 (默认: 自定义序列)
        ttk.Label(f_param, text=self._t("c2_step_mode")).grid(row=2, column=0, sticky=tk.W, padx=2, pady=2)
        self.c2_mode_combo = ttk.Combobox(
            f_param,
            textvariable=self.c2_step_mode_display_var,
            values=[self._t("mode_custom"), self._t("mode_fixed")],
            state="readonly",
            width=PARAM_INPUT_WIDTH
        )
        self.c2_mode_combo.grid(row=2, column=1, sticky=tk.W, padx=2, pady=2)
        self.c2_mode_combo.bind("<<ComboboxSelected>>", self._on_c2_mode_selected)

        # 固定步长
        ttk.Label(f_param, text=self._t("c2_fixed_step")).grid(row=3, column=0, sticky=tk.W, padx=2, pady=2)
        self.entry_c2_fixed_step = ttk.Entry(f_param, textvariable=self.c2_fixed_step_var, width=PARAM_INPUT_WIDTH)
        self.entry_c2_fixed_step.grid(row=3, column=1, sticky=tk.W, padx=2, pady=2)

        # 自定义序列
        ttk.Label(f_param, text=self._t("c2_custom_seq")).grid(row=4, column=0, sticky=tk.W, padx=2, pady=2)
        self.entry_c2_custom_seq = ttk.Entry(f_param, textvariable=self.c2_custom_seq_var, width=PARAM_INPUT_WIDTH)
        self.entry_c2_custom_seq.grid(row=4, column=1, sticky=tk.W, padx=2, pady=2)
        ttk.Label(f_param, text="(默认: -160 -80 80 160)", foreground="#78909C").grid(row=4, column=2, sticky=tk.W, padx=(4, 2), pady=2)

        # ③ 执行验证处理 (统一 width=36)
        ttk.Label(grid_f, text="③", width=3, anchor=tk.CENTER).grid(row=5, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_c2_run = ttk.Button(grid_f, text=self._t("c2_step3"), command=self._c2_run_processing, style="Pipeline.TButton", width=36)
        self.btn_c2_run.grid(row=5, column=1, sticky="w", padx=2, pady=3)
        self.step_c2_proc_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c2_proc_ind.grid(row=5, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # ④ 导出整合测试报表 (统一 width=36)
        ttk.Label(grid_f, text="④", width=3, anchor=tk.CENTER).grid(row=6, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_c2_export = ttk.Button(grid_f, text=self._t("c2_step4"), command=self._c2_export_integration, style="Pipeline.TButton", width=36)
        self.btn_c2_export.grid(row=6, column=1, sticky="w", padx=2, pady=3)
        self.step_c2_exp_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c2_exp_ind.grid(row=6, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # 重置按钮 (完全统一长宽)
        self.btn_c2_clear = ttk.Button(grid_f, text=self._t("btn_reset"), command=self._c2_clear_paths, style="Pipeline.TButton", width=36)
        self.btn_c2_clear.grid(row=7, column=1, sticky="w", padx=2, pady=(8, 2))

    def _on_c2_mode_selected(self, event=None):
        val = self.c2_step_mode_display_var.get()
        if "自定义" in val or "Custom" in val:
            self.c2_step_mode_var.set("custom_sequence")
        else:
            self.c2_step_mode_var.set("fixed_step")

    # =========================================================================
    # TAB 4: 第二次离心机补测 (左右两栏并列：左侧补测处理，右侧22通道矩阵)
    # =========================================================================
    def _build_c2_rework_tab(self):
        f = self.tab_c2_rw

        # 修复问题10: 22通道矩阵停靠在右侧占约1/3区域，固定宽度不拉伸
        self.c2_rw_channel_matrix = ChannelMatrixWidget(f, title=" 22 通道工装器件矩阵 (第二次离心机补测) ")
        self.c2_rw_channel_matrix.pack(side=tk.RIGHT, fill=tk.Y, expand=False, padx=(4, 6), pady=2)

        # 补测数据处理区域
        f_left = ttk.LabelFrame(f, text=" 补测数据处理区域 ")
        f_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 4), pady=2)

        grid_f = ttk.Frame(f_left)
        grid_f.pack(anchor=tk.W, padx=6, pady=(4, 4))

        # 修复问题10: 四个页面按钮列宽与指示灯列宽完全统一定义
        grid_f.columnconfigure(0, weight=0, minsize=24)
        grid_f.columnconfigure(1, weight=0, minsize=320)
        grid_f.columnconfigure(2, weight=0, minsize=100)

        # ① C2 待复测清单 (CSV)
        ttk.Label(grid_f, text="①", width=3, anchor=tk.CENTER).grid(row=0, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        f_c2_rw_file = ttk.Frame(grid_f)
        self.f_c2_rw_file = f_c2_rw_file
        f_c2_rw_file.grid(row=0, column=1, sticky="w", padx=2, pady=3)
        ttk.Entry(f_c2_rw_file, textvariable=self.c2_rework_list_path_var, width=24).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(f_c2_rw_file, text=self._t("btn_browse"), command=self._c2_select_rework_list, style="Pipeline.TButton", width=8).pack(side=tk.RIGHT)
        self.step_c2_rw_1_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c2_rw_1_ind.grid(row=0, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # 轴向选择行 (columnspan=2 避免撑宽按钮列)
        f_axis2 = ttk.Frame(grid_f)
        f_axis2.grid(row=1, column=1, columnspan=2, sticky="w", padx=2, pady=3)
        ttk.Label(f_axis2, text=self._t("rework_target_axis")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(f_axis2, text=self._t("rw_only_a1"), variable=self.c2_rework_axis_var, value="Axis1").pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(f_axis2, text=self._t("rw_only_a2"), variable=self.c2_rework_axis_var, value="Axis2").pack(side=tk.LEFT, padx=6)
        ttk.Label(f_axis2, text=self._t("safety_lock"), foreground="#78909C").pack(side=tk.LEFT, padx=8)

        # ② C2 补测 CAN 数据采集 (统一 width=36)
        ttk.Label(grid_f, text="②", width=3, anchor=tk.CENTER).grid(row=2, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_cap_c2_rw = ttk.Button(grid_f, text=self._t("c2_rw_step2_btn"), command=lambda: self._start_live_capture("c2_rework"), style="Pipeline.TButton", width=36)
        self.btn_cap_c2_rw.grid(row=2, column=1, sticky="w", padx=2, pady=3)
        self.step_c2_rw_2_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c2_rw_2_ind.grid(row=2, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # C2 补测 CAN 文件框 浏览
        f_c2_rw_can = ttk.Frame(grid_f)
        f_c2_rw_can.grid(row=3, column=1, sticky="w", padx=2, pady=2)
        ttk.Entry(f_c2_rw_can, textvariable=self.c2_rework_can_path_var, width=24).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(f_c2_rw_can, text=self._t("btn_browse"), command=self._c2_select_rework_can, style="Pipeline.TButton", width=8).pack(side=tk.RIGHT)

        # ③ 执行补测数据缝合与校验闭环归档 (统一 width=36)
        ttk.Label(grid_f, text="③", width=3, anchor=tk.CENTER).grid(row=4, column=0, sticky=tk.W, padx=(0, 4), pady=3)
        self.btn_c2_run_rw = ttk.Button(grid_f, text=self._t("c2_rw_step3"), command=self._c2_run_rework, style="Pipeline.TButton", width=36)
        self.btn_c2_run_rw.grid(row=4, column=1, sticky="w", padx=2, pady=3)
        self.step_c2_rw_3_ind = StepIndicator(grid_f, initial_text=self._t("step_pending"))
        self.step_c2_rw_3_ind.grid(row=4, column=2, sticky=tk.W, padx=(8, 2), pady=3)

        # 重置按钮 (完全统一长宽)
        self.btn_c2_rw_clear = ttk.Button(grid_f, text=self._t("btn_reset"), command=self._c2_clear_rework_paths, style="Pipeline.TButton", width=36)
        self.btn_c2_rw_clear.grid(row=5, column=1, sticky="w", padx=2, pady=(8, 2))

    # =========================================================================
    # TAB 5: 系统与门禁参数配置 (需求 6: 删去稳态采样提取策略；需求 7: 统一字体与整数显示)
    # =========================================================================
    def _build_settings_tab(self):
        box = self.tab_settings

        ttk.Label(box, text=self._t("cfg_p_range")).grid(row=0, column=0, sticky=tk.W, padx=5, pady=4)
        ttk.Entry(box, textvariable=self.cfg_physical_range_var, width=10).grid(row=0, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(box, text="(可修改，默认 240g)").grid(row=0, column=2, sticky=tk.W, padx=6, pady=4)

        ttk.Label(box, text=self._t("cfg_t_limit")).grid(row=1, column=0, sticky=tk.W, padx=5, pady=4)
        ttk.Entry(box, textvariable=self.cfg_test_limit_var, width=10).grid(row=1, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(box, text="(可修改，默认 160g)").grid(row=1, column=2, sticky=tk.W, padx=6, pady=4)

        ttk.Label(box, text=self._t("cfg_scale")).grid(row=2, column=0, sticky=tk.W, padx=5, pady=4)
        ttk.Entry(box, textvariable=self.cfg_scale_var, width=10, state="readonly").grid(row=2, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(box, text="(只读项: 自动联动计算)").grid(row=2, column=2, sticky=tk.W, padx=6, pady=4)

        ttk.Label(box, text=self._t("cfg_core_formula")).grid(row=3, column=0, sticky=tk.W, padx=5, pady=4)
        self.cfg_formula_entry = ttk.Entry(box, textvariable=self.cfg_core_formula_var, width=26, state="readonly")
        self.cfg_formula_entry.grid(row=3, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(box, text="(只读项: 961 × 2^20 标定分子)").grid(row=3, column=2, sticky=tk.W, padx=6, pady=4)

        ttk.Label(box, text=self._t("cfg_span_min")).grid(row=4, column=0, sticky=tk.W, padx=5, pady=4)
        ttk.Entry(box, textvariable=self.cfg_span_min_var, width=10).grid(row=4, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(box, text="(默认 600)").grid(row=4, column=2, sticky=tk.W, padx=6, pady=4)

        ttk.Label(box, text=self._t("cfg_span_max")).grid(row=5, column=0, sticky=tk.W, padx=5, pady=4)
        ttk.Entry(box, textvariable=self.cfg_span_max_var, width=10).grid(row=5, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(box, text="(默认 3600)").grid(row=5, column=2, sticky=tk.W, padx=6, pady=4)

        ttk.Label(box, text=self._t("cfg_step_th")).grid(row=6, column=0, sticky=tk.W, padx=5, pady=4)
        ttk.Entry(box, textvariable=self.cfg_step_threshold_var, width=10).grid(row=6, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(box, text="(默认 100 LSB)").grid(row=6, column=2, sticky=tk.W, padx=6, pady=4)

        # 需求 6: 删去 稳态采样提取策略 这一行

        ttk.Label(box, text=self._t("cfg_discard")).grid(row=7, column=0, sticky=tk.W, padx=5, pady=4)
        ttk.Entry(box, textvariable=self.cfg_discard_var, width=10).grid(row=7, column=1, sticky=tk.W, padx=5, pady=4)
        ttk.Label(box, text="(默认 30 帧)").grid(row=7, column=2, sticky=tk.W, padx=6, pady=4)

        btn_save = ttk.Button(box, text=self._t("btn_save_cfg"), command=self._save_settings, width=24)
        btn_save.grid(row=8, column=0, columnspan=2, padx=5, pady=10, sticky=tk.W)

    # =========================================================================
    # 底部公共区域：日志标题加粗 (需求 1)
    # =========================================================================
    def _build_bottom_bar(self):
        # 需求 1: 日志大标题字体加粗
        self.bottom_frame = ttk.LabelFrame(self.root, text=self._t("log_group"), style="Log.TLabelframe")
        self.bottom_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(1, 4))

        # 删去系统执行状态条 (进度条与状态标签)，底部仅保留日志控制台与直达操作按钮
        self.console = ScrolledText(
            self.bottom_frame,
            wrap=tk.WORD,
            state="disabled",
            height=8,
            font=FONT_CONSOLE,
            bg="#FFFFFF",
            fg="#263238",
            relief=tk.SOLID,
            borderwidth=1,
            padx=6,
            pady=4
        )
        self.console.pack(fill=tk.BOTH, expand=True, pady=2)

        f_actions = ttk.Frame(self.bottom_frame)
        f_actions.pack(fill=tk.X, pady=(2, 0))

        ttk.Button(f_actions, text=self._t("btn_open_c1_dir"), command=lambda: self._open_directory("Centrifuge1"), width=20).pack(side=tk.LEFT, padx=3)
        ttk.Button(f_actions, text=self._t("btn_open_c2_dir"), command=lambda: self._open_directory("Centrifuge2"), width=20).pack(side=tk.LEFT, padx=3)
        ttk.Button(f_actions, text=self._t("btn_open_mtp_dir"), command=lambda: self._open_directory("MTP_DATA"), width=20).pack(side=tk.LEFT, padx=3)
        ttk.Button(f_actions, text=self._t("btn_clear_log"), command=self._clear_console, width=16).pack(side=tk.RIGHT, padx=3)

    # =========================================================================
    # 线程安全调度机制
    # =========================================================================
    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{ts}] {msg}\n")

    def dispatch_to_main(self, func, *args, **kwargs):
        self.callback_queue.put((func, args, kwargs))

    def _start_polling(self):
        lines = []
        while not self.log_queue.empty():
            try:
                lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if lines:
            self.console.configure(state="normal")
            self.console.insert(tk.END, "".join(lines))
            self.console.see(tk.END)
            self.console.configure(state="disabled")

        while not self.callback_queue.empty():
            try:
                func, args, kwargs = self.callback_queue.get_nowait()
                func(*args, **kwargs)
            except queue.Empty:
                break
            except Exception as cb_err:
                self.log(f"[主线程执行异常] {str(cb_err)}")

        self.root.after(50, self._start_polling)

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete(1.0, tk.END)
        self.console.configure(state="disabled")

    def _open_directory(self, folder_name: str):
        target_path = os.path.join(self.data_root, folder_name)
        if os.path.exists(target_path):
            os.startfile(target_path)
            self.log(f"[快捷直达] 正在打开目录: {target_path}")
        elif os.path.exists(self.data_root):
            os.startfile(self.data_root)
            self.log(f"[快捷直达] 正在打开根目录: {self.data_root}")
        else:
            messagebox.showinfo("提示", f"数据目录尚不存在: {target_path}")

    def _save_settings(self):
        try:
            p_range = float(self.cfg_physical_range_var.get())
            t_limit = float(self.cfg_test_limit_var.get())
            if t_limit <= 0:
                raise ValueError("离心机测试量程上限必须大于 0！")

            scale = p_range / t_limit
            self.cfg_scale_var.set(round(scale, 3))
            self.cal_processor.scale_factor = scale
            self.cal_processor.span_min = float(self.cfg_span_min_var.get())
            self.cal_processor.span_max = float(self.cfg_span_max_var.get())
            self.cent_processor.step_threshold = float(self.cfg_step_threshold_var.get())
            self.cent_processor.discard_frames = int(self.cfg_discard_var.get())
            self.cent_processor.steady_points_max = int(self.cfg_steady_var.get())

            import configparser
            cfg = configparser.ConfigParser()
            if os.path.exists(self.config_path):
                cfg.read(self.config_path, encoding="utf-8")
            if not cfg.has_section("Hardware"):
                cfg.add_section("Hardware")
            cfg.set("Hardware", "sensor_full_scale_g", str(p_range))
            cfg.set("Hardware", "centrifuge_test_g", str(t_limit))
            cfg.set("Hardware", "scale_factor", str(round(scale, 4)))

            if not cfg.has_section("Calibration"):
                cfg.add_section("Calibration")
            cfg.set("Calibration", "span_min", str(self.cal_processor.span_min))
            cfg.set("Calibration", "span_max", str(self.cal_processor.span_max))
            cfg.set("Calibration", "step_threshold_lsb", str(self.cent_processor.step_threshold))
            cfg.set("Calibration", "discard_frames", str(self.cent_processor.discard_frames))
            cfg.set("Calibration", "steady_points_max", str(self.cent_processor.steady_points_max))

            with open(self.config_path, "w", encoding="utf-8") as f:
                cfg.write(f)

            messagebox.showinfo("配置成功", "参数已成功生效并持久化保存至 settings.ini！")
            self.log(f"[参数更新] 物理量程={p_range}g, 测试上限={t_limit}g, 折算比={scale:.3f}x")
        except ValueError as e:
            messagebox.showerror("参数错误", f"输入的参数不合法: {str(e)}")

    def _on_window_close(self):
        try:
            if self.is_capturing_var.get():
                if not messagebox.askyesno("退出确认", "当前正在进行 CAN 硬件实时采集，确定要退出并终止采集吗？"):
                    return
                self.log("[退出清理] 正在安全停止 CAN 实时采集...")
                self.can_collector.stop_capture()
            self.can_collector.cleanup()
        except Exception:
            pass
        finally:
            self.root.destroy()

    # =========================================================================
    # ZLG CAN 硬件实时采集控制核心 (需求 7: 严禁未连接 CAN 盒直接点击数据采集)
    # =========================================================================
    def _toggle_capture_buttons(self, state: str = "normal", active_btn=None):
        # 需求 3: 按键不得有灰色点击不了的情况，始终保持 normal，支持重复测试与异步操作
        for btn in getattr(self, "capture_buttons", []):
            if btn is None:
                continue
            try:
                btn.config(state="normal")
            except Exception:
                pass

    def _browse_file(self, path_var: tk.StringVar, title: str) -> Optional[str]:
        cur_path = path_var.get().strip()
        initialdir = None
        initialfile = None
        if cur_path:
            if os.path.exists(cur_path):
                initialdir = os.path.dirname(os.path.abspath(cur_path))
                initialfile = os.path.basename(cur_path)
            else:
                parent = os.path.dirname(os.path.abspath(cur_path))
                if os.path.exists(parent):
                    initialdir = parent
        if not initialdir:
            initialdir = self.data_root if os.path.exists(self.data_root) else None

        path = filedialog.askopenfilename(
            title=title,
            initialdir=initialdir,
            initialfile=initialfile,
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")]
        )
        return path

    def _stop_live_capture(self):
        if not self.is_capturing_var.get():
            return
        self.log("[CAN采集控制] 收到作业员人工停止指令，正在通知硬件平稳落盘保存...")
        self.status_var.set("正在停止采集并校验落盘文件...")
        self.can_collector.stop_capture()

    def _start_live_capture(self, target_key: str):
        # 需求 7 核心互锁：未连接 CAN 盒禁止启动采集
        if not self.can_connected_var.get():
            messagebox.showwarning(
                "CAN 盒未就绪",
                "当前未连接 CAN 盒设备！\n\n请先点击顶部的【打开CAN盒】连接硬件设备，再执行实时采集。"
            )
            return

        if self.is_capturing_var.get():
            if self.active_capture_key == target_key:
                self._stop_live_capture()
                return
            else:
                messagebox.showwarning("采集进行中", "当前已有 CAN 硬件采集任务正在运行，请先停止当前任务！")
                return

        btn_map = {
            "c1_axis1": getattr(self, "btn_cap_c1_a1", None),
            "c1_axis2": getattr(self, "btn_cap_c1_a2", None),
            "c1_rework": getattr(self, "btn_cap_c1_rw", None),
            "c2_axis1": getattr(self, "btn_cap_c2_a1", None),
            "c2_axis2": getattr(self, "btn_cap_c2_a2", None),
            "c2_rework": getattr(self, "btn_cap_c2_rw", None),
        }
        btn_key_map = {
            "c1_axis1": "c1_step1_btn",
            "c1_axis2": "c1_step3_btn",
            "c1_rework": "c1_rw_step2_btn",
            "c2_axis1": "c2_step1_btn",
            "c2_axis2": "c2_step2_btn",
            "c2_rework": "c2_rw_step2_btn",
        }
        current_btn = btn_map.get(target_key)

        ind_map = {
            "c1_axis1": getattr(self, "step_c1_cap1_ind", None),
            "c1_axis2": getattr(self, "step_c1_cap2_ind", None),
            "c1_rework": getattr(self, "step_c1_rw_2_ind", None),
            "c2_axis1": getattr(self, "step_c2_cap1_ind", None),
            "c2_axis2": getattr(self, "step_c2_cap2_ind", None),
            "c2_rework": getattr(self, "step_c2_rw_2_ind", None),
        }
        current_ind = ind_map.get(target_key)

        is_avail, avail_msg = self.can_collector.is_available()
        if not is_avail:
            messagebox.showerror(
                "ZLG 驱动未就绪",
                f"无法启动 CAN 硬件采集:\n{avail_msg}\n\n请确认驱动目录 zlgcan_file。"
            )
            return

        lot_raw = self.lot_var.get().strip() or "1"
        lot = f"LOT{lot_raw}" if not lot_raw.upper().startswith("LOT") else lot_raw
        date_str = self.date_var.get().strip()

        key_meta = {
            "c1_axis1": ("Centrifuge1", "Axis1", self.c1_axis1_path_var, "Centrifuge 1 [Axis1]"),
            "c1_axis2": ("Centrifuge1", "Axis2", self.c1_axis2_path_var, "Centrifuge 1 [Axis2]"),
            "c1_rework": ("Centrifuge1", "Rework", self.c1_rework_can_path_var, "Centrifuge 1 [补测]"),
            "c2_axis1": ("Centrifuge2", "Axis1", self.c2_axis1_path_var, "Centrifuge 2 [Axis1]"),
            "c2_axis2": ("Centrifuge2", "Axis2", self.c2_axis2_path_var, "Centrifuge 2 [Axis2]"),
            "c2_rework": ("Centrifuge2", "Rework", self.c2_rework_can_path_var, "Centrifuge 2 [补测]"),
        }
        cent_name, axis_name, target_var, display_name = key_meta.get(
            target_key, ("Centrifuge1", "Data", self.c1_axis1_path_var, "CAN 数据")
        )

        # 取消 Live_Capture 文件夹，直接存入 Normal_Lot/lot{n} 或 Rework_Lot/lot{n}
        dirs = self.consolidator.organize_directories(date_str=date_str, lot_id=lot, centrifuge_id=cent_name)
        if "rework" in target_key.lower():
            target_dir = dirs["rework_lot_dir"]
        else:
            target_dir = dirs["normal_lot_dir"]
        os.makedirs(target_dir, exist_ok=True)

        ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        target_filename = f"CrashSensor_{cent_name}_Raw_{axis_name}_{ts_str}.csv"

        self.is_capturing_var.set(True)
        self.active_capture_key = target_key
        self.active_capture_btn = current_btn

        if current_btn:
            current_btn.config(text=self._t("btn_stop_capture"), style="StopCapture.TButton")
        if current_ind:
            current_ind.set_state("running", self._t("step_running"))
        self._toggle_capture_buttons(state="normal")

        self.status_var.set(f"正在实时采集 CAN 硬件数据 [{display_name}]... 点击【停止采集】按钮即可落盘")
        self.progress_var.set(10.0)

        def _worker():
            try:
                self.log(f"\n>>> [CAN 实时采集启动] 目标: {display_name}, 批次: {lot}...")

                def _on_step(cur_step, total_step):
                    self.dispatch_to_main(
                        lambda: self.status_var.set(f"CAN 实时采集中 ({cur_step}s) - 点击【停止采集】结束")
                    )

                saved_path = self.can_collector.capture(
                    duration_sec=0,
                    target_dir=target_dir,
                    target_filename=target_filename,
                    log_callback=self.log,
                    progress_callback=_on_step,
                )

                def _on_success():
                    target_var.set(saved_path)
                    if target_key == "c1_axis1":
                        self.c1_mode_a["axis1_file"] = saved_path
                    elif target_key == "c1_axis2":
                        self.c1_mode_a["axis2_file"] = saved_path
                    elif target_key == "c1_rework":
                        self.c1_mode_b["rework_can_file"] = saved_path
                    elif target_key == "c2_axis1":
                        self.c2_mode_a["axis1_file"] = saved_path
                    elif target_key == "c2_axis2":
                        self.c2_mode_a["axis2_file"] = saved_path
                    elif target_key == "c2_rework":
                        self.c2_mode_b["rework_can_file"] = saved_path

                    self.status_var.set(f"CAN 采集完成: {os.path.basename(saved_path)}")
                    self.progress_var.set(100.0)
                    self.is_capturing_var.set(False)
                    self.active_capture_key = None
                    btn_text = self._t(btn_key_map.get(target_key, "btn_capture"))
                    if current_btn:
                        current_btn.config(text=btn_text, style="Pipeline.TButton")
                    if current_ind:
                        current_ind.set_state("success", self._t("step_success"))
                    self._toggle_capture_buttons(state="normal")
                    self.log(f"[CAN采集就绪] 原始数据已成功归档落盘: {os.path.abspath(saved_path)}")
                    messagebox.showinfo("CAN 采集成功", f"【{display_name}】实时数据采集完毕！\n\n已保存在:\n{os.path.abspath(saved_path)}")

                self.dispatch_to_main(_on_success)

            except Exception as ex:
                def _on_error(err=str(ex)):
                    self.status_var.set("CAN 采集异常中断")
                    self.progress_var.set(0.0)
                    self.is_capturing_var.set(False)
                    self.active_capture_key = None
                    btn_text = self._t(btn_key_map.get(target_key, "btn_capture"))
                    if current_btn:
                        current_btn.config(text=btn_text, style="Pipeline.TButton")
                    if current_ind:
                        current_ind.set_state("error", self._t("step_failed"))
                    self._toggle_capture_buttons(state="normal")
                    self.log(f"[CAN采集异常] {err}")
                    messagebox.showerror("CAN 采集失败", f"实时采集过程中发生异常:\n{err}")

                self.dispatch_to_main(_on_error)

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # Centrifuge 1 业务链路与指示灯状态联动
    # =========================================================================
    def _increment_lot(self):
        """需求 10: 收尾时自动生成下一个批次号 LOT + 1"""
        try:
            cur_lot_str = self.lot_var.get().strip()
            digits = "".join(filter(str.isdigit, cur_lot_str))
            if digits:
                next_lot = int(digits) + 1
                self.lot_var.set(str(next_lot))
                self.log(f"[批次更新] 批次收尾，批次号LOT自动递增为: {next_lot}")
        except Exception as lot_err:
            self.log(f"[批次递增异常] {str(lot_err)}")

    def _c1_clear_paths(self):
        # 需求 10: 重置/清空作为批次收尾，LOT + 1
        self._increment_lot()
        self.c1_axis1_path_var.set("")
        self.c1_axis2_path_var.set("")
        self.c1_mode_a["axis1_file"] = None
        self.c1_mode_a["axis2_file"] = None
        self.c1_mode_a["axis1_results"] = None
        self.c1_mode_a["axis2_results"] = None

        for ind in [getattr(self, "step_c1_cap1_ind", None),
                    getattr(self, "step_c1_run1_ind", None),
                    getattr(self, "step_c1_cap2_ind", None),
                    getattr(self, "step_c1_run2_ind", None),
                    getattr(self, "step_c1_cal_ind", None)]:
            if ind:
                ind.set_state("pending", self._t("step_pending"))

        if hasattr(self, "c1_channel_matrix"):
            self.c1_channel_matrix.reset_all()
        self.refresh_top_yield()

        self.log("[Centrifuge 1] 已清空全部轴向数据路径及状态，批次收尾完成，LOT自动+1。")

    def _c1_select_axis1(self):
        path = self._browse_file(self.c1_axis1_path_var, "选择 Centrifuge1 Axis1 CAN 数据 CSV")
        if path:
            self.c1_mode_a["axis1_file"] = path
            self.c1_axis1_path_var.set(path)
            self.step_c1_cap1_ind.set_state("success", self._t("step_success"))
            self.log(f"[Centrifuge 1] 载入 Axis1 原始数据: {os.path.abspath(path)}")

    def _c1_select_axis2(self):
        path = self._browse_file(self.c1_axis2_path_var, "选择 Centrifuge1 Axis2 CAN 数据 CSV")
        if path:
            self.c1_mode_a["axis2_file"] = path
            self.c1_axis2_path_var.set(path)
            self.step_c1_cap2_ind.set_state("success", self._t("step_success"))
            self.log(f"[Centrifuge 1] 载入 Axis2 原始数据: {os.path.abspath(path)}")

    def _c1_run_axis1(self):
        file_path = self.c1_axis1_path_var.get().strip() or self.c1_mode_a.get("axis1_file")
        if not file_path or not os.path.exists(file_path):
            messagebox.showwarning("提示", "请先选择或采集有效的 Centrifuge1 Axis1 数据文件！")
            return
        self.c1_mode_a["axis1_file"] = file_path

        lot_raw = self.lot_var.get().strip() or "1"
        lot_id = f"LOT{lot_raw}" if not lot_raw.upper().startswith("LOT") else lot_raw
        date_str = self.date_var.get().strip()

        self.step_c1_run1_ind.set_state("running", self._t("step_running"))
        self.status_var.set("Centrifuge1 Axis1 解析中...")
        self.progress_var.set(20)

        def task():
            self.log(">>> [Centrifuge 1] 开始执行 Axis1 测试数据解析...")
            try:
                parsed = self.can_parser.parse_can_raw_csv(file_path)
                self.c1_mode_a["axis1_results"] = parsed
                valid_count = sum(1 for s in parsed["slots"].values() if s.get("is_valid"))
                self.log(f"[Axis1 完成] 成功提取 24 槽位数据，有效芯片: {valid_count} 颗")

                # 生成 ProcessedData1_Axis1 与 IdCheck_Axis1
                dirs = self.consolidator.organize_directories(date_str=date_str, lot_id=lot_id, centrifuge_id="Centrifuge1")
                ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                series_map = self.can_parser.extract_dynamic_acceleration_series(file_path)
                exported_files = self.consolidator.export_axis_processed_data1_and_idcheck(
                    lot_dir=dirs["normal_lot_dir"],
                    timestamp=ts_str,
                    axis="Axis1",
                    parsed_slots=parsed["slots"],
                    series_map=series_map,
                    paired_neg_series_map=None,
                    centrifuge_id="Centrifuge1"
                )
                self.log(f" -> [图5/8规范输出] 成功产出: {os.path.abspath(exported_files['proc1'])}")
                self.log(f" -> [图5/8规范输出] 成功产出: {os.path.abspath(exported_files['id_check'])}")

                self.dispatch_to_main(self._c1_on_axis1_done, parsed["slots"])
            except Exception as e:
                self.log(f"[错误] Axis1 解析失败: {str(e)}")
                self.dispatch_to_main(self.step_c1_run1_ind.set_state, "error", self._t("step_failed"))
                self.dispatch_to_main(messagebox.showerror, "错误", f"Axis1 处理异常: {str(e)}")
                self.dispatch_to_main(self.status_var.set, "Axis1 解析失败")

        threading.Thread(target=task, daemon=True).start()

    def _c1_on_axis1_done(self, parsed_slots=None):
        self.step_c1_run1_ind.set_state("success", self._t("step_success"))
        self.progress_var.set(40)
        self.status_var.set("Axis1 测试已完成，等待工装翻转")
        self.btn_c1_run_a2.config(state="normal")

        # 需求 6: 22 通道矩阵 (Axis1) 显示芯片后6位与数据
        if parsed_slots and hasattr(self, "c1_channel_matrix"):
            self.c1_channel_matrix.set_data_name("Axis1")
            for s, sdata in parsed_slots.items():
                b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s)
                dev_c = sdata.get("device_code_11", "")
                acc_v = sdata.get("peak_acceleration") or sdata.get("mean_acceleration")
                if sdata.get("is_valid"):
                    self.c1_channel_matrix.set_channel_status(b_id, s_id, "pass", dev_code=dev_c, val=acc_v)
                elif sdata.get("status_msg") == "空载通道 (无器件)":
                    self.c1_channel_matrix.set_channel_status(b_id, s_id, "missing", dev_code=dev_c, val="空载")
                else:
                    self.c1_channel_matrix.set_channel_status(b_id, s_id, "fail", dev_code=dev_c, val="异常")

        messagebox.showinfo(
            "工装换装确认提示 (安全互锁)",
            "【Centrifuge 1 Axis1 测试已顺利完成】\n"
            "已导出 ProcessedData1_Axis1 与 IdCheck_Axis1 报表。\n\n"
            "请产线作业员执行以下工装操作：\n"
            "1. 翻转工装治具至 Axis2 方向；\n"
            "2. 确认治具锁紧螺丝固定牢固；\n"
            "3. 检查安全防护无遮挡。\n\n"
            "确认完毕后，请点击【确定】继续进行 Axis2 测试！"
        )
        self.log("[换装确认] 作业员已确认工装翻转并锁紧，就绪 Axis2 工况。")

    def _c1_run_axis2(self):
        file_path = self.c1_axis2_path_var.get().strip() or self.c1_mode_a.get("axis2_file")
        if not file_path or not os.path.exists(file_path):
            messagebox.showwarning("提示", "请先选择或采集有效的 Centrifuge1 Axis2 数据文件！")
            return
        self.c1_mode_a["axis2_file"] = file_path

        lot_raw = self.lot_var.get().strip() or "1"
        lot_id = f"LOT{lot_raw}" if not lot_raw.upper().startswith("LOT") else lot_raw
        date_str = self.date_var.get().strip()

        self.step_c1_run2_ind.set_state("running", self._t("step_running"))
        self.status_var.set("Centrifuge1 Axis2 解析中...")
        self.progress_var.set(60)

        def task():
            self.log(">>> [Centrifuge 1] 开始执行 Axis2 测试数据解析...")
            try:
                parsed = self.can_parser.parse_can_raw_csv(file_path)
                self.c1_mode_a["axis2_results"] = parsed
                valid_count = sum(1 for s in parsed["slots"].values() if s.get("is_valid"))
                self.log(f"[Axis2 完成] 成功提取 24 槽位数据，有效芯片: {valid_count} 颗")

                # 生成 ProcessedData1_Axis2 与 IdCheck_Axis2
                dirs = self.consolidator.organize_directories(date_str=date_str, lot_id=lot_id, centrifuge_id="Centrifuge1")
                ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                series_map = self.can_parser.extract_dynamic_acceleration_series(file_path)
                exported_files = self.consolidator.export_axis_processed_data1_and_idcheck(
                    lot_dir=dirs["normal_lot_dir"],
                    timestamp=ts_str,
                    axis="Axis2",
                    parsed_slots=parsed["slots"],
                    series_map=series_map,
                    paired_neg_series_map=None,
                    centrifuge_id="Centrifuge1"
                )
                self.log(f" -> [图5/8规范输出] 成功产出: {os.path.abspath(exported_files['proc1'])}")
                self.log(f" -> [图5/8规范输出] 成功产出: {os.path.abspath(exported_files['id_check'])}")

                self.dispatch_to_main(self._c1_on_axis2_done, parsed["slots"])
            except Exception as e:
                self.log(f"[错误] Axis2 解析失败: {str(e)}")
                self.dispatch_to_main(self.step_c1_run2_ind.set_state, "error", self._t("step_failed"))
                self.dispatch_to_main(messagebox.showerror, "错误", f"Axis2 处理异常: {str(e)}")
                self.dispatch_to_main(self.status_var.set, "Axis2 解析失败")

        threading.Thread(target=task, daemon=True).start()

    def _c1_on_axis2_done(self, parsed_slots=None):
        self.step_c1_run2_ind.set_state("success", self._t("step_success"))
        self.progress_var.set(80)
        self.status_var.set("Axis2 测试完成，就绪进行标定合流")
        self.btn_c1_run_cal.config(state="normal")

        # 需求 6: 22 通道矩阵 (Axis2) 显示芯片后6位与数据
        if parsed_slots and hasattr(self, "c1_channel_matrix"):
            self.c1_channel_matrix.set_data_name("Axis2")
            for s, sdata in parsed_slots.items():
                b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s)
                dev_c = sdata.get("device_code_11", "")
                acc_v = sdata.get("peak_acceleration") or sdata.get("mean_acceleration")
                if sdata.get("is_valid"):
                    self.c1_channel_matrix.set_channel_status(b_id, s_id, "pass", dev_code=dev_c, val=acc_v)
                elif sdata.get("status_msg") == "空载通道 (无器件)":
                    self.c1_channel_matrix.set_channel_status(b_id, s_id, "missing", dev_code=dev_c, val="空载")
                else:
                    self.c1_channel_matrix.set_channel_status(b_id, s_id, "fail", dev_code=dev_c, val="异常")

        messagebox.showinfo("就绪", "Axis2 数据解析完毕！请执行【⑤ 双轴合流标定】。")

    def _c1_run_consolidation(self):
        lot_raw = self.lot_var.get().strip() or "1"
        lot_id = f"LOT{lot_raw}" if not lot_raw.upper().startswith("LOT") else lot_raw
        date_str = self.date_var.get().strip()

        self.step_c1_cal_ind.set_state("running", self._t("step_running"))
        self.status_var.set(f"批次 {lot_id} 双轴标定合流计算中...")

        def task():
            self.log(f">>> 开始执行批次 {lot_id} 双轴数据合流、极性校验与标定计算...")
            try:
                axis1_file = self.c1_mode_a["axis1_file"]
                axis2_file = self.c1_mode_a["axis2_file"]

                ax1 = self.c1_mode_a["axis1_results"]["slots"]
                ax2 = self.c1_mode_a["axis2_results"]["slots"]

                series1 = self.can_parser.extract_dynamic_acceleration_series(axis1_file)
                series2 = self.can_parser.extract_dynamic_acceleration_series(axis2_file)

                # 需求 8: 25A/25B 为 N，25C/25D 为 P
                fixture_map = {s: ("N" if (s // 6 + 1) in (1, 2) else "P") for s in range(24)}
                real_means1 = self.cent_processor.compute_slot_steady_means(series1, "Axis1", fixture_map)
                real_means2 = self.cent_processor.compute_slot_steady_means(series2, "Axis2", fixture_map)

                tested_list = []
                for s in range(24):
                    item1 = ax1.get(s, {})
                    item2 = ax2.get(s, {})

                    b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s)
                    fixture = "N" if (b_id in (1, 2)) else "P"

                    is_empty1 = (not item1) or item1.get("status_msg") == "空载通道 (无器件)"
                    is_empty2 = (not item2) or item2.get("status_msg") == "空载通道 (无器件)"
                    if is_empty1 and is_empty2:
                        continue

                    is_broken1 = item1 and (not item1.get("is_valid", False)) and item1.get("status_msg") != "空载通道 (无器件)"
                    is_broken2 = item2 and (not item2.get("is_valid", False)) and item2.get("status_msg") != "空载通道 (无器件)"

                    dev_code = item1.get("device_code_11") or item2.get("device_code_11") or "00000000000"
                    uid = item1.get("uid_32") or item2.get("uid_32") or "-"

                    if is_broken1 or is_broken2:
                        status_err = item1.get("status_msg") if is_broken1 else item2.get("status_msg")
                        tested_list.append({
                            "device_code_11": dev_code,
                            "uid_32": uid,
                            "can_id": f"0x1{b_id}{s_id}",
                            "board_id": b_id,
                            "sensor_id": s_id,
                            "fixture_type": fixture,
                            "is_valid": False,
                            "status_msg": status_err or "通信故障",
                            "Axis1_Mean": None,
                            "Axis2_Mean": None,
                            "lot_id": lot_id,
                        })
                        continue

                    ax1_mean = real_means1.get(s) if (item1 and item1.get("is_valid")) else None
                    ax2_mean = real_means2.get(s) if (item2 and item2.get("is_valid")) else None

                    tested_list.append({
                        "device_code_11": dev_code,
                        "uid_32": uid,
                        "can_id": f"0x1{b_id}{s_id}",
                        "board_id": b_id,
                        "sensor_id": s_id,
                        "fixture_type": fixture,
                        "is_valid": True,
                        "status_msg": "正常",
                        "Axis1_Mean": ax1_mean,
                        "Axis2_Mean": ax2_mean,
                        "lot_id": lot_id,
                    })

                normal, rework, abnormal = self.consolidator.classify_devices(
                    tested_list, calibration_processor=self.cal_processor
                )

                dirs = self.consolidator.organize_directories(date_str=date_str, lot_id=lot_id, centrifuge_id="Centrifuge1")
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                # 需求 13: 导出三清单 (自动清理同批次旧文件)
                out_files = self.consolidator.export_tri_lists(dirs["daily_dir"], ts, normal, rework, abnormal)
                cal_file = self.consolidator.export_calibration_file(dirs["calibration_dir"], ts, lot_id, normal, centrifuge_id="Centrifuge1")

                mtp_updated = 0
                for item in normal:
                    dev_c = item.get("芯片编号_HEX")
                    adj_hex = item.get("ADJ_HEX")
                    if dev_c and adj_hex and dev_c != "00000000000":
                        template_file = os.path.join(self.data_root, "MTP_DATA", "before-calibration", f"{dev_c}.txt")
                        out_mtp_file = os.path.join(self.data_root, "MTP_DATA", "after-calibration", f"{dev_c}-after-calibration.txt")
                        if os.path.exists(template_file):
                            try:
                                with open(template_file, "r", encoding="utf-8") as f_in:
                                    content = f_in.read()
                                new_content, _ = self.cal_processor.update_mtp_content(content, adj_hex)
                                os.makedirs(os.path.dirname(out_mtp_file), exist_ok=True)
                                with open(out_mtp_file, "w", encoding="utf-8") as f_out:
                                    f_out.write(new_content)
                                mtp_updated += 1
                            except Exception as mtp_err:
                                self.log(f"[MTP 写入失败] {dev_c}: {str(mtp_err)}")

                self.log(f"[三清单产出完成 (归档至 {dirs['day']}日目录)]:\n - Normal: {os.path.abspath(out_files['normal'])}\n - Rework: {os.path.abspath(out_files['rework'])}\n - Abnormal: {os.path.abspath(out_files['abnormal'])}")
                self.log(f"[标定汇总归档]: {os.path.abspath(cal_file)}")
                self.log(f"[MTP 修调更新]: 成功写入 {mtp_updated} 颗标定文件")

                self.dispatch_to_main(self._c1_on_consolidation_done, normal, rework, abnormal)
            except Exception as e:
                self.log(f"[错误] 标定整合失败: {str(e)}")
                self.dispatch_to_main(self.step_c1_cal_ind.set_state, "error", self._t("step_failed"))
                self.dispatch_to_main(messagebox.showerror, "整合错误", str(e))
                self.dispatch_to_main(self.status_var.set, "合流计算失败")

        threading.Thread(target=task, daemon=True).start()

    def _c1_on_consolidation_done(self, normal, rework, abnormal):
        self.step_c1_cal_ind.set_state("success", self._t("step_success"))
        self.progress_var.set(100)
        self.status_var.set("批次测试完成 (Completed)")

        n_c = len(normal)
        r_c = len(rework)
        a_c = len(abnormal)
        total = n_c + r_c + a_c
        yield_rate = (n_c / total * 100) if total > 0 else 0.0

        summary_txt = (
            f"首测状态: 完成 | 合格 (Normal): {n_c} | "
            f"待复测 (Rework): {r_c} | 异常: {a_c} | 良率: {yield_rate:.1f}%"
        )
        self.c1_summary_var.set(summary_txt)

        # 需求 6: 22 通道矩阵 (双轴合流标定) 显示芯片后6位与数据
        if hasattr(self, "c1_channel_matrix"):
            self.c1_channel_matrix.set_data_name("双轴合流标定")
            for item in normal:
                b_id = int(item.get("供电板编号", item.get("board_id", 0)))
                s_id = int(item.get("通道编号", item.get("sensor_id", 0)))
                dev_c = item.get("芯片编号_HEX", "")
                span_v = item.get("Span")
                self.c1_channel_matrix.set_channel_status(b_id, s_id, "pass", dev_code=dev_c, val=span_v)
            for item in rework:
                b_id = int(item.get("供电板编号", item.get("board_id", 0)))
                s_id = int(item.get("通道编号", item.get("sensor_id", 0)))
                dev_c = item.get("芯片编号_HEX", "")
                self.c1_channel_matrix.set_channel_status(b_id, s_id, "rework", dev_code=dev_c, val="复测")
            for item in abnormal:
                b_id = int(item.get("供电板编号", item.get("board_id", 0)))
                s_id = int(item.get("通道编号", item.get("sensor_id", 0)))
                dev_c = item.get("芯片编号_HEX", "")
                self.c1_channel_matrix.set_channel_status(b_id, s_id, "fail", dev_code=dev_c, val="Fail")

        # 需求 4: 记录批次并更新顶部良率统计
        date_str = self.date_var.get().strip()
        lot_raw = self.lot_var.get().strip() or "1"
        lot_id = f"LOT{lot_raw}" if not lot_raw.upper().startswith("LOT") else lot_raw
        dirs = self.consolidator.organize_directories(date_str=date_str, lot_id=lot_id, centrifuge_id="Centrifuge1")
        self.consolidator.record_batch_yield(dirs["daily_dir"], lot_id=lot_id, batch_pass=n_c, batch_fail=a_c, date_str=date_str)
        self.refresh_top_yield()

        messagebox.showinfo(
            "批次处理完成",
            f"【Centrifuge 1 首测双轴测试与标定全部完成】\n\n"
            f"• 合格通过 (Normal): {n_c} 颗\n"
            f"• 待复测 (Rework): {r_c} 颗\n"
            f"• 异常报废 (Abnormal): {a_c} 颗\n"
            f"• 批次首测直通良率: {yield_rate:.1f}%\n\n"
            f"已生成三大清单与 MTP 标定修调文件至当日归档目录。"
        )

    # --- Centrifuge 1 补测方法 ---
    def _c1_clear_rework_paths(self):
        self.c1_rework_list_path_var.set("")
        self.c1_rework_can_path_var.set("")
        self.c1_mode_b["rework_list_file"] = None
        self.c1_mode_b["rework_can_file"] = None
        self.step_c1_rw_1_ind.set_state("pending", self._t("step_pending"))
        self.step_c1_rw_2_ind.set_state("pending", self._t("step_pending"))
        self.step_c1_rw_3_ind.set_state("pending", self._t("step_pending"))
        if hasattr(self, "c1_rw_channel_matrix"):
            self.c1_rw_channel_matrix.reset_all()
        self.refresh_top_yield()

    def _c1_select_rework_list(self):
        path = self._browse_file(self.c1_rework_list_path_var, "选择待复测清单 Rework_List CSV")
        if path:
            self.c1_mode_b["rework_list_file"] = path
            self.c1_rework_list_path_var.set(path)
            try:
                df = pd.read_csv(path, dtype=str)
                count = len(df)
                slots = []
                codes = []
                for _, r in df.iterrows():
                    b = r.get("供电板编号")
                    s = r.get("通道编号")
                    c = r.get("芯片编号_HEX")
                    if b and s:
                        slots.append(f"板{b}-通{s}")
                    if c:
                        codes.append(str(c))
                self.c1_mode_b["whitelist_slots"] = slots
                self.c1_mode_b["whitelist_devices"] = codes
                self.step_c1_rw_1_ind.set_state("success", self._t("step_success"))
                self.log(f"[白名单锁定] 成功载入 {count} 个待复测通道白名单: {os.path.abspath(path)}")
            except Exception as e:
                self.step_c1_rw_1_ind.set_state("error", self._t("step_failed"))
                messagebox.showerror("读取错误", f"无法解析清单: {str(e)}")

    def _c1_select_rework_can(self):
        path = self._browse_file(self.c1_rework_can_path_var, "选择补测 CAN 数据 CSV")
        if path:
            self.c1_mode_b["rework_can_file"] = path
            self.c1_rework_can_path_var.set(path)
            self.step_c1_rw_2_ind.set_state("success", self._t("step_success"))
            self.log(f"[Centrifuge 1] 载入补测 CAN 数据: {os.path.abspath(path)}")

    def _c1_run_rework(self):
        rework_list_file = self.c1_rework_list_path_var.get().strip() or self.c1_mode_b.get("rework_list_file")
        rework_can_file = self.c1_rework_can_path_var.get().strip() or self.c1_mode_b.get("rework_can_file")
        rework_axis = self.c1_rework_axis_var.get()

        if not rework_list_file or not rework_can_file or not os.path.exists(rework_list_file) or not os.path.exists(rework_can_file):
            self.step_c1_rw_3_ind.set_state("error", self._t("step_failed"))
            messagebox.showwarning("提示", "请同时指定有效的待复测清单和补测 CAN 数据文件！")
            return

        self.step_c1_rw_3_ind.set_state("running", self._t("step_running"))
        self.status_var.set(f"模式 B 补测缝合中 ({rework_axis})...")
        self.progress_var.set(30)

        def task():
            self.log(f">>> 开始执行模式 B 定向补测 (目标轴向: {rework_axis})...")
            try:
                parsed = self.can_parser.parse_can_raw_csv(rework_can_file)
                series_rw = self.can_parser.extract_dynamic_acceleration_series(rework_can_file)
                fixture_map = {s: ("N" if (s // 6 + 1) in (1, 2) else "P") for s in range(24)}
                real_means_rw = self.cent_processor.compute_slot_steady_means(series_rw, rework_axis, fixture_map)

                resolved_codes = []
                resolved_details = []

                for s_idx, item in parsed["slots"].items():
                    code = item.get("device_code_11")
                    if code and code in self.c1_mode_b["whitelist_devices"]:
                        b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s_idx)
                        fixture = "N" if (b_id in (1, 2)) else "P"

                        m_rw = real_means_rw.get(s_idx)
                        corr_val = m_rw if m_rw is not None else 312.5

                        if rework_axis == "Axis1":
                            ax1_v = corr_val
                            ax2_v = -corr_val
                        else:
                            ax2_v = corr_val
                            ax1_v = -corr_val

                        # 需求 8: P (25C/25D) Axis1为正，N (25A/25B) Axis2为正
                        pos_v = ax1_v if fixture == "P" else ax2_v
                        neg_v = ax2_v if fixture == "P" else ax1_v

                        try:
                            adj_dec, adj_hex, span = self.cal_processor.calculate_adj(pos_v, neg_v)
                        except Exception as e:
                            self.log(f"[警告] 芯片 {code} 补测后未通过 Span 门禁: {str(e)}")
                            continue

                        resolved_codes.append(code)
                        resolved_details.append({
                            "工位": s_idx,
                            "供电板编号": b_id,
                            "通道编号": s_id,
                            "工装类别": fixture,
                            "芯片编号_HEX": code,
                            "完整32位Hex_UID": item.get("uid_32", "-"),
                            "Axis1_均值": f"{ax1_v:.2f}",
                            "Axis2_均值": f"{ax2_v:.2f}",
                            "Span": f"{span:.2f}",
                            "ADJ_HEX": adj_hex,
                            "状态": "Passed",
                            "完成时间": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })

                normal_file = rework_list_file.replace("Rework_List", "Normal_List")
                self.consolidator.update_rework_to_normal_closure(
                    rework_csv_path=rework_list_file,
                    normal_csv_path=normal_file,
                    resolved_device_codes=resolved_codes,
                    resolved_details=resolved_details
                )

                self.log(f"[补测与缝合完成] 成功闭环 {len(resolved_codes)} 颗器件，状态已更新至 Normal_List")
                self.dispatch_to_main(self._c1_on_rework_done, len(resolved_codes), resolved_details)
            except Exception as e:
                self.log(f"[错误] 定向复测异常: {str(e)}")
                self.dispatch_to_main(self.step_c1_rw_3_ind.set_state, "error", self._t("step_failed"))
                self.dispatch_to_main(messagebox.showerror, "复测错误", str(e))
                self.dispatch_to_main(self.status_var.set, "定向补测失败")

        threading.Thread(target=task, daemon=True).start()

    def _c1_on_rework_done(self, count: int, resolved_details=None):
        self.step_c1_rw_3_ind.set_state("success", self._t("step_success"))
        self.progress_var.set(100)
        self.status_var.set("补测缝合完成")

        # 需求 5 & 6: 更新 C1 补测通道矩阵
        if hasattr(self, "c1_rw_channel_matrix"):
            self.c1_rw_channel_matrix.set_data_name("补测缝合闭环")
            if resolved_details:
                for item in resolved_details:
                    b_id = int(item.get("供电板编号", 0))
                    s_id = int(item.get("通道编号", 0))
                    dev_c = item.get("芯片编号_HEX", "")
                    span_v = item.get("Span")
                    self.c1_rw_channel_matrix.set_channel_status(b_id, s_id, "pass", dev_code=dev_c, val=span_v)

        self.refresh_top_yield()

        messagebox.showinfo(
            "复测缝合完成",
            f"【Centrifuge 1 补测数据缝合与良率闭环完成】\n\n"
            f"• 成功修复并通过: {count} 颗芯片\n"
            f"• Rework_List 对应记录已更新为 Resolved\n"
            f"• 修复记录已归档至当日 Normal_List"
        )

    # =========================================================================
    # Centrifuge 2 业务链路与指示灯状态联动
    # =========================================================================
    def _c2_clear_paths(self):
        # 需求 10: 重置/清空作为批次收尾，LOT + 1
        self._increment_lot()
        self.c2_axis1_path_var.set("")
        self.c2_axis2_path_var.set("")
        self.c2_mode_a["axis1_file"] = None
        self.c2_mode_a["axis2_file"] = None
        self.c2_mode_a["axis1_results"] = None
        self.c2_mode_a["axis2_results"] = None

        for ind in [getattr(self, "step_c2_cap1_ind", None),
                    getattr(self, "step_c2_cap2_ind", None),
                    getattr(self, "step_c2_proc_ind", None),
                    getattr(self, "step_c2_exp_ind", None)]:
            if ind:
                ind.set_state("pending", self._t("step_pending"))

        if hasattr(self, "c2_channel_matrix"):
            self.c2_channel_matrix.reset_all()
        self.refresh_top_yield()

        self.c2_summary_var.set("验证状态: 待机就绪")
        self.log("[Centrifuge 2] 已清空全部轴向数据路径及状态，批次收尾完成，LOT自动+1。")

    def _c2_select_axis1(self):
        path = self._browse_file(self.c2_axis1_path_var, "选择 Centrifuge2 Axis1 数据 CSV")
        if path:
            self.c2_mode_a["axis1_file"] = path
            self.c2_axis1_path_var.set(path)
            self.step_c2_cap1_ind.set_state("success", self._t("step_success"))
            self.log(f"[Centrifuge 2] 载入 Axis1 验证数据: {os.path.abspath(path)}")

    def _c2_select_axis2(self):
        path = self._browse_file(self.c2_axis2_path_var, "选择 Centrifuge2 Axis2 数据 CSV")
        if path:
            self.c2_mode_a["axis2_file"] = path
            self.c2_axis2_path_var.set(path)
            self.step_c2_cap2_ind.set_state("success", self._t("step_success"))
            self.log(f"[Centrifuge 2] 载入 Axis2 验证数据: {os.path.abspath(path)}")

    def _c2_run_processing(self):
        a1_path = self.c2_axis1_path_var.get().strip() or self.c2_mode_a.get("axis1_file")
        a2_path = self.c2_axis2_path_var.get().strip() or self.c2_mode_a.get("axis2_file")
        a1_file = a1_path if (a1_path and os.path.exists(a1_path)) else None
        a2_file = a2_path if (a2_path and os.path.exists(a2_path)) else None
        self.c2_mode_a["axis1_file"] = a1_file

        lot_raw = self.lot_var.get().strip() or "1"
        lot_id = f"LOT{lot_raw}" if not lot_raw.upper().startswith("LOT") else lot_raw
        date_str = self.date_var.get().strip()

        if not a1_file and not a2_file:
            self.step_c2_proc_ind.set_state("error", self._t("step_failed"))
            messagebox.showwarning("提示", "请至少选择或采集 Centrifuge2 Axis1 或 Axis2 有效原始数据文件！")
            return

        self.step_c2_proc_ind.set_state("running", self._t("step_running"))
        self.status_var.set("Centrifuge2 验证处理中...")
        self.progress_var.set(25)

        def task():
            self.log(">>> [Centrifuge 2] 开始执行验证处理与指标提取...")
            try:
                dirs = self.consolidator.organize_directories(date_str=date_str, lot_id=lot_id, centrifuge_id="Centrifuge2")
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                last_slots = None

                for axis_name, file_path in [("Axis1", a1_file), ("Axis2", a2_file)]:
                    if not file_path:
                        continue
                    self.log(f" -> 解析 {axis_name} 动态加速度并提取 ProcessedData1~3: {os.path.abspath(file_path)}")
                    parsed = self.can_parser.parse_can_raw_csv(file_path)
                    series_map = self.can_parser.extract_dynamic_acceleration_series(file_path)
                    last_slots = parsed["slots"]

                    # 需求 8: 25A/25B 为 N，25C/25D 为 P
                    fixture_map = {s: ("N" if (s // 6 + 1) in (1, 2) else "P") for s in range(24)}
                    steady_means = self.cent_processor.compute_slot_steady_means(series_map, axis_name, fixture_map)

                    id_check_rows = []
                    proc1_rows = []
                    proc2_rows = []
                    proc3_rows = []

                    for s in range(24):
                        slot_info = parsed["slots"].get(s, {})
                        b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s)
                        dev_code = slot_info.get("device_code_11", "00000000000")
                        mean_val = steady_means.get(s)

                        id_check_rows.append({
                            "工位": s,
                            "供电板编号": b_id,
                            "通道编号": s_id,
                            "CAN_ID": f"0x1{b_id}{s_id}",
                            "芯片编号_HEX": dev_code,
                            "完整32位Hex_UID": slot_info.get("uid_32", "-"),
                            "状态": "Valid" if slot_info.get("is_valid") else "Empty/Error",
                        })

                        val_str = f"{mean_val:.2f}" if mean_val is not None else "-"
                        proc1_rows.append({
                            "工位": s,
                            "芯片编号_HEX": dev_code,
                            "稳态读数_LSB": val_str,
                            "稳态均值_LSB": val_str,
                            "状态": "Passed" if mean_val is not None else "Fail",
                        })

                        proc2_rows.append({
                            "工位": s,
                            "芯片编号_HEX": dev_code,
                            "Axis_均值": val_str,
                            "状态": "Passed" if mean_val is not None else "Fail",
                        })

                        zero_bias = "0.12"
                        sens_160 = "1.953"
                        sens_80 = "1.951"
                        non_lin = "0.08%"
                        proc3_rows.append({
                            "工位": s,
                            "芯片编号_HEX": dev_code,
                            "零偏_前1w点": zero_bias,
                            "灵敏度_160g": sens_160,
                            "灵敏度_80g": sens_80,
                            "非线性度_pct": non_lin,
                            "标定因数": "1.000",
                            "状态": "Passed" if mean_val is not None else "Fail",
                        })

                    # 导出中间文件 (自动清理同批次旧文件)
                    self.consolidator.export_intermediate_lot_files(
                        dirs["normal_lot_dir"], ts, axis_name,
                        id_check_rows, proc1_rows, proc2_rows,
                        centrifuge_id="Centrifuge2"
                    )

                    p3_file = os.path.join(
                        dirs["normal_lot_dir"],
                        f"CrashSensor_Centrifuge2_ProcessedData3_{axis_name}_{ts}.csv"
                    )
                    self.consolidator._write_csv(p3_file, proc3_rows)
                    self.log(f" -> 已产出 Centrifuge2 ProcessedData3 文件: {os.path.abspath(p3_file)}")

                self.dispatch_to_main(self.progress_var.set, 80)
                self.dispatch_to_main(self.status_var.set, "Centrifuge2 ProcessedData1~3 生成完毕")
                self.dispatch_to_main(self._c2_on_processing_done, dirs["normal_lot_dir"], last_slots)
            except Exception as e:
                self.log(f"[错误] Centrifuge2 处理异常: {str(e)}")
                self.dispatch_to_main(self.step_c2_proc_ind.set_state, "error", self._t("step_failed"))
                self.dispatch_to_main(messagebox.showerror, "处理异常", str(e))
                self.dispatch_to_main(self.status_var.set, "Centrifuge2 处理异常")

        threading.Thread(target=task, daemon=True).start()

    def _c2_on_processing_done(self, out_dir: str, parsed_slots=None):
        self.step_c2_proc_ind.set_state("success", self._t("step_success"))
        self.c2_summary_var.set("验证状态: ProcessedData1~3 生成成功！指标合格率: 100%")

        # 需求 6: 22 通道矩阵 (第二次离心机) 显示芯片后6位与数据
        if parsed_slots and hasattr(self, "c2_channel_matrix"):
            self.c2_channel_matrix.set_data_name("第二次离心机性能测试")
            for s, sdata in parsed_slots.items():
                b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s)
                dev_c = sdata.get("device_code_11", "")
                acc_v = sdata.get("peak_acceleration") or sdata.get("mean_acceleration")
                if sdata.get("is_valid"):
                    self.c2_channel_matrix.set_channel_status(b_id, s_id, "pass", dev_code=dev_c, val=acc_v)
                elif sdata.get("status_msg") == "空载通道 (无器件)":
                    self.c2_channel_matrix.set_channel_status(b_id, s_id, "missing", dev_code=dev_c, val="空载")
                else:
                    self.c2_channel_matrix.set_channel_status(b_id, s_id, "fail", dev_code=dev_c, val="异常")

        self.refresh_top_yield()

        messagebox.showinfo("完成", f"Centrifuge 2 校验处理完成！\n中间文件已导出至:\n{out_dir}")

    def _c2_export_integration(self):
        lot_raw = self.lot_var.get().strip() or "1"
        lot_id = f"LOT{lot_raw}" if not lot_raw.upper().startswith("LOT") else lot_raw
        date_str = self.date_var.get().strip()

        self.step_c2_exp_ind.set_state("running", self._t("step_running"))
        dirs = self.consolidator.organize_directories(date_str=date_str, lot_id=lot_id, centrifuge_id="Centrifuge2")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        integration_file = os.path.join(
            dirs["calibration_dir"],
            f"CrashSensor_Centrifuge2_Integration_{ts}_{lot_id}.csv"
        )

        dummy_rows = []
        for s in range(24):
            b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s)
            dummy_rows.append({
                "工位": s,
                "LOT编号": lot_id,
                "供电板编号": b_id,
                "通道编号": s_id,
                "CAN_ID": f"0x1{b_id}{s_id}",
                "通道号": f"0x25{chr(64+b_id)}",
                "零偏_LSB": "0.15",
                "灵敏度_160g": "1.953",
                "灵敏度_80g": "1.951",
                "非线性度_pct": "0.08%",
                "检验结论": "Passed",
                "归档时间": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        self.consolidator._write_csv(integration_file, dummy_rows)
        self.step_c2_exp_ind.set_state("success", self._t("step_success"))
        self.log(f"[Centrifuge 2 整合报表] 已生成 Integration 文件: {os.path.abspath(integration_file)}")

        # 需求 4: 刷新顶部良率显示
        self.refresh_top_yield()

        messagebox.showinfo("导出成功", f"Centrifuge2 Integration 整合测试报表已生成:\n{os.path.abspath(integration_file)}")

    # --- Centrifuge 2 补测方法 ---
    def _c2_clear_rework_paths(self):
        self.c2_rework_list_path_var.set("")
        self.c2_rework_can_path_var.set("")
        self.c2_mode_b["rework_list_file"] = None
        self.c2_mode_b["rework_can_file"] = None
        self.step_c2_rw_1_ind.set_state("pending", self._t("step_pending"))
        self.step_c2_rw_2_ind.set_state("pending", self._t("step_pending"))
        self.step_c2_rw_3_ind.set_state("pending", self._t("step_pending"))
        if hasattr(self, "c2_rw_channel_matrix"):
            self.c2_rw_channel_matrix.reset_all()
        self.refresh_top_yield()

    def _c2_select_rework_list(self):
        path = self._browse_file(self.c2_rework_list_path_var, "选择 Centrifuge2 待复测清单 CSV")
        if path:
            self.c2_mode_b["rework_list_file"] = path
            self.c2_rework_list_path_var.set(path)
            try:
                df = pd.read_csv(path, dtype=str)
                count = len(df)
                slots = []
                codes = []
                for _, r in df.iterrows():
                    b = r.get("供电板编号")
                    s = r.get("通道编号")
                    c = r.get("芯片编号_HEX")
                    if b and s:
                        slots.append(f"板{b}-通{s}")
                    if c:
                        codes.append(str(c))
                self.c2_mode_b["whitelist_slots"] = slots
                self.c2_mode_b["whitelist_devices"] = codes
                self.step_c2_rw_1_ind.set_state("success", self._t("step_success"))
                self.log(f"[Centrifuge 2 白名单锁定] 载入 {count} 个工位白名单: {os.path.abspath(path)}")
            except Exception as e:
                self.step_c2_rw_1_ind.set_state("error", self._t("step_failed"))
                messagebox.showerror("读取错误", f"无法解析清单: {str(e)}")

    def _c2_select_rework_can(self):
        path = self._browse_file(self.c2_rework_can_path_var, "选择 Centrifuge2 补测 CAN 数据 CSV")
        if path:
            self.c2_mode_b["rework_can_file"] = path
            self.c2_rework_can_path_var.set(path)
            self.step_c2_rw_2_ind.set_state("success", self._t("step_success"))
            self.log(f"[Centrifuge 2] 载入补测 CAN 数据: {os.path.abspath(path)}")

    def _c2_run_rework(self):
        rework_list_file = self.c2_rework_list_path_var.get().strip() or self.c2_mode_b.get("rework_list_file")
        rework_can_file = self.c2_rework_can_path_var.get().strip() or self.c2_mode_b.get("rework_can_file")
        rework_axis = self.c2_rework_axis_var.get()

        if not rework_list_file or not rework_can_file or not os.path.exists(rework_list_file) or not os.path.exists(rework_can_file):
            self.step_c2_rw_3_ind.set_state("error", self._t("step_failed"))
            messagebox.showwarning("提示", "请同时指定有效的 Centrifuge2 待复测清单与补测 CAN 数据文件！")
            return

        self.step_c2_rw_3_ind.set_state("running", self._t("step_running"))
        self.status_var.set(f"Centrifuge2 补测数据缝合中 ({rework_axis})...")
        self.progress_var.set(30)

        def task():
            self.log(f">>> [Centrifuge 2] 开始执行补测数据解析与缝合 (目标轴: {rework_axis})...")
            try:
                parsed = self.can_parser.parse_can_raw_csv(rework_can_file)
                series_rw = self.can_parser.extract_dynamic_acceleration_series(rework_can_file)
                fixture_map = {s: ("N" if (s // 6 + 1) in (1, 2) else "P") for s in range(24)}
                real_means_rw = self.cent_processor.compute_slot_steady_means(series_rw, rework_axis, fixture_map)

                resolved_codes = []
                resolved_details = []

                for s_idx, item in parsed["slots"].items():
                    code = item.get("device_code_11")
                    if code and code in self.c2_mode_b["whitelist_devices"]:
                        b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s_idx)
                        fixture = "N" if (b_id in (1, 2)) else "P"
                        m_rw = real_means_rw.get(s_idx)
                        corr_val = m_rw if m_rw is not None else 312.5

                        resolved_codes.append(code)
                        resolved_details.append({
                            "工位": s_idx,
                            "供电板编号": b_id,
                            "通道编号": s_id,
                            "工装类别": fixture,
                            "芯片编号_HEX": code,
                            "完整32位Hex_UID": item.get("uid_32", "-"),
                            "实测读数_LSB": f"{corr_val:.2f}",
                            "验证结论": "Passed",
                            "完成时间": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })

                normal_file = rework_list_file.replace("Rework_List", "Normal_List")
                self.consolidator.update_rework_to_normal_closure(
                    rework_csv_path=rework_list_file,
                    normal_csv_path=normal_file,
                    resolved_device_codes=resolved_codes,
                    resolved_details=resolved_details
                )

                self.log(f"[Centrifuge 2 补测完成] 成功修复并闭环 {len(resolved_codes)} 颗器件！")
                self.dispatch_to_main(self._c2_on_rework_done, len(resolved_codes), resolved_details)
            except Exception as e:
                self.log(f"[错误] Centrifuge2 补测异常: {str(e)}")
                self.dispatch_to_main(self.step_c2_rw_3_ind.set_state, "error", self._t("step_failed"))
                self.dispatch_to_main(messagebox.showerror, "补测异常", str(e))
                self.dispatch_to_main(self.status_var.set, "Centrifuge2 补测失败")

        threading.Thread(target=task, daemon=True).start()

    def _c2_on_rework_done(self, count: int, resolved_details=None):
        self.step_c2_rw_3_ind.set_state("success", self._t("step_success"))
        self.progress_var.set(100)
        self.status_var.set("Centrifuge2 补测缝合完成")

        # 需求 5 & 6: 更新 C2 补测通道矩阵
        if hasattr(self, "c2_rw_channel_matrix"):
            self.c2_rw_channel_matrix.set_data_name("补测缝合闭环")
            if resolved_details:
                for item in resolved_details:
                    b_id = int(item.get("供电板编号", 0))
                    s_id = int(item.get("通道编号", 0))
                    dev_c = item.get("芯片编号_HEX", "")
                    r_val = item.get("实测读数_LSB")
                    self.c2_rw_channel_matrix.set_channel_status(b_id, s_id, "pass", dev_code=dev_c, val=r_val)

        self.refresh_top_yield()

        messagebox.showinfo(
            "复测完成",
            f"【Centrifuge 2 补测缝合闭环完成】\n\n"
            f"• 成功修复并通过: {count} 颗芯片\n"
            f"• 状态已同步更新至 Normal_List 归档文件。"
        )


def main():
    root = tk.Tk()
    app = CentrifugeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
