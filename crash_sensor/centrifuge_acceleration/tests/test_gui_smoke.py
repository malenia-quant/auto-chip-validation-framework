"""
单元测试：Centrifuge GUI 5 Tab 结构、多语言切换与 3合1 CAN 盒控制测试
"""

import sys
import os
import pytest
from unittest.mock import patch

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(BASE_DIR, "data_processor"))

import tkinter as tk
from gui import CentrifugeGUI


def test_gui_initialization_and_tabs():
    root = tk.Tk()
    app = CentrifugeGUI(root)

    # 1. 验证 5 个独立 Tab 分页与新命名 (需求 1)
    tab_count = app.notebook.index('end')
    assert tab_count == 5, f"预期 5 个 Tab 分页，实际为 {tab_count}"
    assert "第一次离心机" in app.notebook.tab(0, "text")
    assert "第一次离心机补测" in app.notebook.tab(1, "text")
    assert "第二次离心机性能测试" in app.notebook.tab(2, "text")
    assert "第二次离心机补测" in app.notebook.tab(3, "text")
    assert "系统配置" in app.notebook.tab(4, "text")

    # 2. 验证语言选择控件已按需求 12 移除 (只保留中文界面)
    assert not hasattr(app, "lang_combo")

    # 3. 验证 3合1 CAN 盒开闭状态自动切换
    with patch("tkinter.messagebox.showinfo"), patch("tkinter.messagebox.showerror"):
        # 初始断开
        assert app.can_connected_var.get() is False
        assert "打开CAN盒" in app.btn_toggle_can.cget("text")

        # 点击打开
        app._on_toggle_can()
        assert app.can_connected_var.get() is True
        assert "关闭CAN盒" in app.btn_toggle_can.cget("text")

        # 再次点击关闭释放
        app._on_toggle_can()
        assert app.can_connected_var.get() is False
        assert "打开CAN盒" in app.btn_toggle_can.cget("text")

        # 4. 验证红绿指示灯状态
        assert hasattr(app, "step_c1_cap1_ind")
        assert hasattr(app, "step_c1_run1_ind")
        assert hasattr(app, "step_c1_cap2_ind")
        assert hasattr(app, "step_c1_run2_ind")
        assert hasattr(app, "step_c1_cal_ind")

        app.step_c1_cap1_ind.set_state("running", "运行中")
        assert app.step_c1_cap1_ind.current_state == "running"
        app.step_c1_cap1_ind.set_state("success", "已完成")
        assert app.step_c1_cap1_ind.current_state == "success"

        # 5. 验证硬件采集互锁：CAN盒未连接时禁止启动采集
        app.can_connected_var.set(False)
        with patch("tkinter.messagebox.showwarning") as mock_warn:
            app._start_live_capture("c1_axis1")
            mock_warn.assert_called_once()
            assert app.is_capturing_var.get() is False

        # 6. 验证自定义序列默认值应为 -160 -80 80 160
        assert app.c2_custom_seq_var.get() == "-160 -80 80 160"

        # 7. 验证参数输入控件与变量绑定
        assert app.c2_zero_p_var.get() == 35.0
        assert app.c2_zero_n_var.get() == -35.0
        assert app.c2_fixed_step_var.get() == 20.0
        # 修复问题9: 正负阈值、步进、固定步长、自定义序列输入框长度保持一致
        assert app.entry_c2_zero_p.cget('width') == app.entry_c2_zero_n.cget('width')
        assert app.entry_c2_zero_p.cget('width') == app.c2_mode_combo.cget('width')
        assert app.entry_c2_zero_p.cget('width') == app.entry_c2_fixed_step.cget('width')
        assert app.entry_c2_zero_p.cget('width') == app.entry_c2_custom_seq.cget('width')


        # 8. 验证结构与尺寸需求：
        # (1) 删去系统执行状态条，底部只保留 log 控制台与操作按钮
        assert not hasattr(app, "progress_bar")
        assert not hasattr(app, "lbl_status")
        assert hasattr(app, "console")

        # (2) 窗口尺寸保持为 1200x1100 (修复问题10)
        assert app.root.minsize() == (1200, 1100)

        # (3) 验证需求 1: 第二次离心机步进模式默认值为“自定义序列”
        assert app.c2_step_mode_display_var.get() == "自定义序列"
        assert app.c2_step_mode_var.get() == "custom_sequence"

        # (4) 修复问题10: 四个页面的所有操作按键与重置按键全部统一为 width=36
        all_main_buttons = [
            app.btn_cap_c1_a1, app.btn_c1_run_a1, app.btn_cap_c1_a2, app.btn_c1_run_a2, app.btn_c1_run_cal, app.btn_c1_clear,
            app.btn_cap_c1_rw, app.btn_c1_run_rw, app.btn_c1_rw_clear,
            app.btn_cap_c2_a1, app.btn_cap_c2_a2, app.btn_c2_run, app.btn_c2_export, app.btn_c2_clear,
            app.btn_cap_c2_rw, app.btn_c2_run_rw, app.btn_c2_rw_clear
        ]
        for btn in all_main_buttons:
            assert btn.cget("width") == 36, f"按钮 {btn} 宽度应为 36，实际为 {btn.cget('width')}"

        # (5) 验证需求 4: 顶部 CAN 盒右侧良率统计变量
        assert hasattr(app, "stat_today_pass_var")
        assert hasattr(app, "stat_today_fail_var")
        assert hasattr(app, "stat_all_pass_var")
        assert hasattr(app, "stat_all_fail_var")

        # (6) 验证需求 5 & 7: 4个测试页面均有 22 通道工装器件矩阵
        assert hasattr(app, "c1_channel_matrix")
        assert hasattr(app, "c1_rw_channel_matrix")
        assert hasattr(app, "c2_channel_matrix")
        assert hasattr(app, "c2_rw_channel_matrix")

        # (7) 修复问题10: 通道标法严格为 text=f"{tag_l}"，不得写入“待机”
        lbl_text = app.c1_channel_matrix.status_labels[(2, 1)].cget("text")
        assert lbl_text == "1(0*121)", f"预期为纯标号 1(0*121)，实际为 {lbl_text}"
        assert "待机" not in lbl_text

        # 9. 验证批次号与收尾自增逻辑 (需求 10)：
        # (1) 批次号标签与初始默认值
        assert app.lbl_lot.cget("text") == "批次号LOT:"
        assert app.lot_var.get() == "1"

        # (2) 合流完成不自增 LOT (保持为 1)
        app._c1_on_consolidation_done(normal=[], rework=[], abnormal=[])
        assert app.lot_var.get() == "1"

        # (3) 验证矩阵在状态更新后显示数据，在“重置清空数据”后纯净清空且不写待机
        app.c1_channel_matrix.set_channel_status(2, 1, "pass", "902830", 852.1)
        lbl_after_pass = app.c1_channel_matrix.status_labels[(2, 1)].cget("text")
        assert "902830" in lbl_after_pass
        assert "852.1" in lbl_after_pass

        # 点击重置清空按钮，LOT+1 且矩阵所有单元格重置为原始纯标号
        app._c1_clear_paths()
        assert app.lot_var.get() == "2"
        lbl_after_reset = app.c1_channel_matrix.status_labels[(2, 1)].cget("text")
        assert lbl_after_reset == "1(0*121)"
        assert "待机" not in lbl_after_reset

        # (4) 所有核心按键均保持 normal 可点击状态
        for btn in [app.btn_c1_run_a1, app.btn_c1_run_a2, app.btn_c1_run_cal, app.btn_cap_c1_a1, app.btn_cap_c1_a2]:
            assert str(btn.cget("state")) == "normal"

    root.destroy()

