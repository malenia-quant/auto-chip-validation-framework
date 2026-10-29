"""GUI 冒烟测试 (test_gui_smoke.py)

验证：
1. GUI 模块正常导入
2. 根窗口与核心组件正常初始化
3. 指示灯状态切换无异常
4. 资源释放与退出安全
"""

import os
import sys
import tkinter as tk
import pytest

_tpms_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _tpms_dir not in sys.path:
    sys.path.insert(0, _tpms_dir)

# Unload any previously cached conflicting 'gui' from another test package
if 'gui' in sys.modules and not hasattr(sys.modules['gui'], 'TPMSAppGUI'):
    del sys.modules['gui']

from gui import TPMSAppGUI, StepIndicator


class TestGUISmoke:

    @pytest.fixture
    def tk_root(self):
        root = tk.Tk()
        root.withdraw()  # 隐藏测试窗口
        yield root
        try:
            root.destroy()
        except Exception:
            pass

    def test_gui_instantiation(self, tk_root):
        """测试 GUI 主窗口及全部 Tab 初始化"""
        app = TPMSAppGUI(tk_root)
        assert app is not None
        assert app.notebook is not None
        assert app.notebook.index("end") == 3  # 3 个核心 Tab

        # 检查核心组件存在
        assert hasattr(app, "btn_run_single")
        assert hasattr(app, "btn_run_summary")
        assert hasattr(app, "console")

        # 检查指示灯状态切换
        app.step_ind_single.set_state("running", "运行中")
        assert app.step_ind_single.current_state == "running"
        app.step_ind_single.set_state("success", "已完成")
        assert app.step_ind_single.current_state == "success"

        # 检查控制台与日志颜色为黑色字体，字体与上方文件列表框保持严格一致
        assert app.console.cget("fg") == "#000000"
        assert "Microsoft YaHei UI" in str(app.console.cget("font"))
        assert "Microsoft YaHei UI" in str(app.lb_raw_files.cget("font"))
        assert app.console.tag_cget("INFO", "foreground") == "#000000"
        assert app.console.tag_cget("SUCCESS", "foreground") == "#000000"
        assert app.console.tag_cget("WARNING", "foreground") == "#000000"
        assert app.console.tag_cget("ERROR", "foreground") == "#000000"

        # 检查高度修改为 900
        assert tk_root.minsize()[1] == 900

        # 检查右侧“生成测试用例/模板”按钮已删除
        found_gen_btn = False
        def _check_btn(w):
            nonlocal found_gen_btn
            if isinstance(w, tk.Widget) or isinstance(w, tk.ttk.Widget):
                try:
                    if "生成测试用例" in str(w.cget("text")):
                        found_gen_btn = True
                except Exception:
                    pass
                for child in w.winfo_children():
                    _check_btn(child)
        _check_btn(tk_root)
        assert not found_gen_btn, "生成测试用例/模板按钮应当已被删除！"

        # 检查日志输出
        app.log("GUI 自动化冒烟测试通过。")
