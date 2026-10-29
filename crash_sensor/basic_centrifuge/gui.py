# -*- coding: utf-8 -*-
"""
basic_centrifuge - 离心机两步法数据处理图形化交互平台 (GUI)
功能概览:
- Step 1: 原始离心机测试数据解析、通道拆分与时域波形图批量生成。
- Step 2: 稳态台阶边缘捕获、数据截断、各区间均值聚合、阶梯图合成、最小二乘法非线性度拟合及 RMS 噪声计算。
- 批量处理: 支持整目录 TXT 自动转 CSV 及多子文件夹 Step2 批量分析。
"""

import os
import sys
import threading
from io import TextIOBase
from queue import Queue
from configparser import ConfigParser

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 兼容模块导入
try:
    from sensor_processor1 import SensorProcessor
    from sensor_processor2 import Step2Processor
except ImportError:
    from .sensor_processor1 import SensorProcessor
    from .sensor_processor2 import Step2Processor


def resource_path(relative_path: str) -> str:
    """获取资源文件绝对路径 (支持 PyInstaller 打包与常规开发环境)"""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class ConsoleRedirector(TextIOBase):
    """标准输出重定向到 GUI 文本控件"""

    def __init__(self, gui_instance):
        super().__init__()
        self.gui = gui_instance

    def write(self, s):
        if s:
            self.gui.thread_safe_print(s)
        return len(s)

    def flush(self):
        pass


class SensorGUI:
    """离心机两步法数据处理主窗口"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Sensor Data Processor - GUI (basic_centrifuge)")
        self.root.geometry("620x720")

        # 消息缓冲队列
        self.output_queue = Queue()
        self.after_id = None
        self.processing = False
        self.selected_files = []
        self.csv_output_dir = None

        # 设备模式配置清单
        self.mode_options = [
            'SingleCrashSensor',
            'SingleCrashSensor_ASICFab2',
            'SingleCrashSensor_batch18',
            'DoubleCrashSensor',
            'ThreeAxAccSensor',
            'TDK20685',
            'SingleThreeAxAccMEMS',
            'SingleThreeAxAccMEMS2',
            'IMUFab2'
        ]

        # 量程可选配置
        self.acc_ranges = [16.384, 32.768, 65.536, 4.096, 8.192]
        self.gyro_ranges = [328, 655.36, 1311, 1966, 218, 437, 874, 61, 123, 246, 492, 41, 82, 164]

        # 初始化配置读取
        self.config = ConfigParser()
        self.config_file = resource_path("config/settings.ini")
        self._load_config()

        # UI 绑定变量
        self.device_mode_var = tk.StringVar(value=self.config.get('DEVICE', 'mode', fallback='SingleCrashSensor'))
        self.acc_range_var = tk.DoubleVar(value=float(self.config.get('TDK20685', 'Acc_Range', fallback='16.384')))
        self.gyro_range_var = tk.DoubleVar(value=float(self.config.get('TDK20685', 'Gyro_Range', fallback='655.36')))
        self.file_path_var = tk.StringVar()
        self.zero_division_p_var = tk.DoubleVar(value=35.0)
        self.zero_division_n_var = tk.DoubleVar(value=-35.0)
        self.fixed_step_var = tk.DoubleVar(value=20.0)
        self.columns_usedforfitting_var = tk.StringVar(value="None")
        self.customSequence_step_var = tk.StringVar(value='-120, -80, -40, 40, 80, 120')
        self.accelerationStep_select_var = tk.StringVar(value='custom_sequence')
        self.progress_var = tk.DoubleVar(value=0.0)

        # 构建界面布局
        self.create_widgets()

        # 标准输出重定向
        sys.stdout = ConsoleRedirector(self)

    # --------------------------------------------------------------------------
    # 控制台重定向与日志处理
    # --------------------------------------------------------------------------

    def thread_safe_print(self, message: str):
        """线程安全地向日志控制台投递文本"""
        self.output_queue.put(message)
        if not self.after_id:
            self.after_id = self.root.after(100, self._process_output_queue)

    def _process_output_queue(self):
        """批量排空队列并写入文本框"""
        messages = []
        while not self.output_queue.empty():
            messages.append(self.output_queue.get())

        if messages:
            self.console.configure(state='normal')
            self.console.insert(tk.END, ''.join(messages))
            self.console.see(tk.END)
            self.console.configure(state='disabled')

        self.after_id = self.root.after(200, self._process_output_queue) if not self.output_queue.empty() else None

    def _print_console(self, message: str):
        self.thread_safe_print(message + "\n")

    # --------------------------------------------------------------------------
    # 配置文件安全读写
    # --------------------------------------------------------------------------

    def _load_config(self):
        """安全加载配置，缺失时自动生成默认文件"""
        if os.path.exists(self.config_file):
            try:
                self.config.read(self.config_file, encoding='utf-8')
                return
            except Exception:
                pass

        # 默认配置回退
        if not self.config.has_section('DEVICE'):
            self.config.add_section('DEVICE')
        self.config.set('DEVICE', 'mode', 'SingleCrashSensor')

        if not self.config.has_section('TDK20685'):
            self.config.add_section('TDK20685')
        self.config.set('TDK20685', 'Acc_Range', '16.384')
        self.config.set('TDK20685', 'Gyro_Range', '655.36')

        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                self.config.write(f)
        except Exception:
            pass

    def _save_config(self):
        """持久化当前界面配置"""
        self.config['DEVICE']['mode'] = self.device_mode_var.get()
        self.config['TDK20685']['Acc_Range'] = str(self.acc_range_var.get())
        self.config['TDK20685']['Gyro_Range'] = str(self.gyro_range_var.get())
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                self.config.write(f)
        except Exception as e:
            self._print_console(f"配置保存失败: {e}")

    # --------------------------------------------------------------------------
    # 界面构建
    # --------------------------------------------------------------------------

    def create_widgets(self):
        pad_cfg = {'padx': 6, 'pady': 4}

        # 1. 文件选择
        ttk.Label(self.root, text="Select File(s):").grid(row=0, column=0, sticky=tk.W, **pad_cfg)
        ttk.Entry(self.root, textvariable=self.file_path_var, width=42).grid(row=0, column=1, sticky=tk.EW, **pad_cfg)
        ttk.Button(self.root, text="Browse", command=self.select_file).grid(row=0, column=2, **pad_cfg)

        # 2. 设备模式
        ttk.Label(self.root, text="Device Mode:").grid(row=1, column=0, sticky=tk.W, **pad_cfg)
        device_combo = ttk.Combobox(
            self.root,
            textvariable=self.device_mode_var,
            values=self.mode_options,
            state="readonly"
        )
        device_combo.grid(row=1, column=1, sticky=tk.EW, **pad_cfg)
        ttk.Button(self.root, text="APP 说明", command=self.show_app_help).grid(row=1, column=2, **pad_cfg)

        # 3. TDK20685 专属量程
        ttk.Label(self.root, text="TDK20685 Acc Range:").grid(row=2, column=0, sticky=tk.W, **pad_cfg)
        ttk.Combobox(self.root, textvariable=self.acc_range_var, values=self.acc_ranges, state="readonly").grid(
            row=2, column=1, sticky=tk.EW, **pad_cfg
        )

        ttk.Label(self.root, text="TDK20685 Gyro Range:").grid(row=3, column=0, sticky=tk.W, **pad_cfg)
        ttk.Combobox(self.root, textvariable=self.gyro_range_var, values=self.gyro_ranges, state="readonly").grid(
            row=3, column=1, sticky=tk.EW, **pad_cfg
        )

        # 4. Step 1 操作区
        self.process_btn = ttk.Button(
            self.root,
            text="Start Step 1 (Data Processing & Split)",
            command=self.process_data
        )
        self.process_btn.grid(row=4, column=1, sticky=tk.EW, **pad_cfg)

        self.folder_btn = ttk.Button(
            self.root,
            text="Convert TXT Folder to CSV",
            command=self.select_and_convert_folder
        )
        self.folder_btn.grid(row=5, column=1, sticky=tk.EW, **pad_cfg)

        # 5. Step 2 参数配置
        ttk.Separator(self.root, orient='horizontal').grid(row=6, column=0, columnspan=3, sticky=tk.EW, pady=6)

        ttk.Label(self.root, text="Zero_Division_P (正阈值):").grid(row=7, column=0, sticky=tk.W, **pad_cfg)
        ttk.Entry(self.root, textvariable=self.zero_division_p_var).grid(row=7, column=1, sticky=tk.EW, **pad_cfg)

        ttk.Label(self.root, text="Zero_Division_N (负阈值):").grid(row=8, column=0, sticky=tk.W, **pad_cfg)
        ttk.Entry(self.root, textvariable=self.zero_division_n_var).grid(row=8, column=1, sticky=tk.EW, **pad_cfg)

        ttk.Label(self.root, text="AccelerationStep Mode:").grid(row=9, column=0, sticky=tk.W, **pad_cfg)
        ttk.Combobox(
            self.root,
            textvariable=self.accelerationStep_select_var,
            values=['custom_sequence', 'fixed_step'],
            state="readonly"
        ).grid(row=9, column=1, sticky=tk.EW, **pad_cfg)

        ttk.Label(self.root, text="Fixed Step (g):").grid(row=10, column=0, sticky=tk.W, **pad_cfg)
        ttk.Entry(self.root, textvariable=self.fixed_step_var).grid(row=10, column=1, sticky=tk.EW, **pad_cfg)

        ttk.Label(self.root, text="Custom Sequence (g):").grid(row=11, column=0, sticky=tk.W, **pad_cfg)
        custom_seq_combo = ttk.Combobox(
            self.root,
            textvariable=self.customSequence_step_var,
            values=[
                "-120, -80, -40, 40, 80, 120",
                "-240, -160, -80, 80, 160, 240",
                "-8, -6, -4, -2, 2, 4, 6, 8",
                "2, 4, 8, 16, 32"
            ]
        )
        custom_seq_combo.grid(row=11, column=1, sticky=tk.EW, **pad_cfg)

        ttk.Label(self.root, text="Columns Used For Fitting:").grid(row=12, column=0, sticky=tk.W, **pad_cfg)
        ttk.Entry(self.root, textvariable=self.columns_usedforfitting_var).grid(row=12, column=1, sticky=tk.EW, **pad_cfg)

        # 6. Step 2 操作区
        self.step2_btn = ttk.Button(
            self.root,
            text="Start Step 2 (Plateau, NonLinearity & RMS)",
            command=self.process_data_step2
        )
        self.step2_btn.grid(row=13, column=1, sticky=tk.EW, **pad_cfg)

        self.batch_step2_btn = ttk.Button(
            self.root,
            text="Batch Process Step 2 (Folder Scan)",
            command=self.select_batch_step2_folder
        )
        self.batch_step2_btn.grid(row=14, column=1, sticky=tk.EW, **pad_cfg)

        # 7. 控制台输出
        self.console = ScrolledText(
            self.root,
            wrap=tk.WORD,
            state='disabled',
            height=12,
            font=('Consolas', 9),
            padx=4,
            pady=4
        )
        self.console.grid(row=15, column=0, columnspan=3, padx=6, pady=8, sticky=tk.NSEW)

        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(15, weight=1)

    # --------------------------------------------------------------------------
    # 文件选择与转换
    # --------------------------------------------------------------------------

    def select_file(self):
        file_paths = filedialog.askopenfilenames(
            filetypes=[("CSV / TXT Files", "*.csv;*.txt"), ("All Files", "*.*")]
        )
        if file_paths:
            self.selected_files = list(file_paths)
            self.file_path_var.set("; ".join(self.selected_files))
            self._print_console(f"已选中 {len(self.selected_files)} 个输入文件。")

    def select_and_convert_folder(self):
        folder_path = filedialog.askdirectory()
        if not folder_path:
            return

        base_name = os.path.basename(folder_path.rstrip(os.sep))
        self.csv_output_dir = os.path.join(os.path.dirname(folder_path), f"{base_name}_csvconvert")
        os.makedirs(self.csv_output_dir, exist_ok=True)

        threading.Thread(target=self._convert_folder_thread, args=(folder_path,), daemon=True).start()

    def _convert_folder_thread(self, folder_path: str):
        try:
            count = 0
            for root, _, files in os.walk(folder_path):
                for file in files:
                    if file.lower().endswith(".txt"):
                        txt_path = os.path.join(root, file)
                        rel_dir = os.path.relpath(root, folder_path)
                        target_dir = os.path.join(self.csv_output_dir, rel_dir)
                        os.makedirs(target_dir, exist_ok=True)
                        csv_path = os.path.join(target_dir, os.path.splitext(file)[0] + ".csv")
                        self.convert_txt_to_csv(txt_path, csv_path)
                        count += 1

            self.root.after(0, messagebox.showinfo, "转换完成", f"共转换 {count} 个文件至:\n{self.csv_output_dir}")
        except Exception as e:
            self.root.after(0, messagebox.showerror, "错误", f"文件夹转换失败: {str(e)}")

    def convert_txt_to_csv(self, txt_path: str, csv_path: str):
        columns = ['AccX', 'AccY', 'AccZ', 'AccZC', 'GyroX', 'GyroY', 'GyroZ', 'Temperature']
        try:
            df = pd.read_csv(txt_path, sep=r'\t|,', engine='python', header=None, names=columns)
            df.to_csv(csv_path, index=False)
            self._print_console(f"已转换: {os.path.basename(txt_path)}")
        except Exception as e:
            self._print_console(f"转换失败: {txt_path} - {e}")

    # --------------------------------------------------------------------------
    # Step 1 数据处理流程
    # --------------------------------------------------------------------------

    def process_data(self):
        if self.processing:
            return

        if not self.selected_files and self.file_path_var.get().strip():
            self.selected_files = [p.strip() for p in self.file_path_var.get().split(';') if os.path.exists(p.strip())]

        if not self.selected_files:
            messagebox.showerror("错误", "请先选择需要处理的输入文件！")
            return

        self._save_config()
        self.processing = True
        self.process_btn.config(text="Step 1 处理中...", state=tk.DISABLED)

        threading.Thread(target=self._step1_processing_thread, daemon=True).start()

    def _step1_processing_thread(self):
        total_files = len(self.selected_files)
        success_count = 0
        errors = []
        last_dir = ""

        try:
            for idx, input_path in enumerate(self.selected_files):
                try:
                    dir_name = os.path.dirname(input_path)
                    base, ext = os.path.splitext(os.path.basename(input_path))
                    output_file = os.path.join(dir_name, f"{base}_processed{ext}")

                    self._print_console(f"[{idx+1}/{total_files}] Step 1 正在处理: {os.path.basename(input_path)}")

                    processor = SensorProcessor()
                    processor.device_mode = self.device_mode_var.get()
                    processor.config['TDK20685']['Acc_Range'] = str(self.acc_range_var.get())
                    processor.config['TDK20685']['Gyro_Range'] = str(self.gyro_range_var.get())
                    processor.process(input_path, output_file)

                    success_count += 1
                    last_dir = dir_name

                except Exception as file_e:
                    err = f"[失败] {os.path.basename(input_path)}: {file_e}"
                    errors.append(err)
                    self._print_console(err)

            # 完成回调
            def on_done():
                self.processing = False
                self.process_btn.config(text="Start Step 1 (Data Processing & Split)", state=tk.NORMAL)
                summary = f"\n=== Step 1 处理完毕 ===\n共 {total_files} 个文件，成功 {success_count} 个，失败 {len(errors)} 个。"
                self._print_console(summary)
                if errors:
                    messagebox.showwarning("处理完成 (含错误)", f"处理完毕，但有 {len(errors)} 个文件失败，请查看日志。")
                else:
                    messagebox.showinfo("处理完成", f"全部 {total_files} 个文件 Step 1 处理成功！")
                if last_dir and os.path.exists(last_dir):
                    os.startfile(last_dir)

            self.root.after(0, on_done)

        except Exception as e:
            def on_fatal():
                self.processing = False
                self.process_btn.config(text="Start Step 1 (Data Processing & Split)", state=tk.NORMAL)
                messagebox.showerror("致命错误", f"批处理线程异常: {e}")
            self.root.after(0, on_fatal)

    # --------------------------------------------------------------------------
    # Step 2 单文件与批量处理流程
    # --------------------------------------------------------------------------

    def _get_step2_params(self) -> dict:
        cols = self.columns_usedforfitting_var.get().strip()
        cols_val = int(cols) if cols.isdigit() and int(cols) > 0 else None

        return {
            'zero_division_p': float(self.zero_division_p_var.get()),
            'zero_division_n': float(self.zero_division_n_var.get()),
            'fixed_step': float(self.fixed_step_var.get()),
            'device_mode': self.device_mode_var.get(),
            'accelerationstep_select': self.accelerationStep_select_var.get(),
            'custom_sequence': self.customSequence_step_var.get(),
            'columns': cols_val
        }

    def process_data_step2(self):
        """单文件 Step 2 处理流程"""
        if self.processing:
            return

        input_path = self.file_path_var.get().strip().split(';')[0].strip()
        if not input_path or not os.path.exists(input_path):
            messagebox.showerror("错误", "请先选择有效的输入文件 (或完成 Step 1 处理)！")
            return

        try:
            params = self._get_step2_params()
        except ValueError as ve:
            messagebox.showerror("参数错误", f"请检查输入的数值参数: {ve}")
            return

        self.processing = True
        self.step2_btn.config(text="Step 2 处理中...", state=tk.DISABLED)

        threading.Thread(target=self._step2_single_thread, args=(input_path, params), daemon=True).start()

    def _step2_single_thread(self, input_path: str, params: dict):
        try:
            output_dir = os.path.dirname(input_path)
            base, ext = os.path.splitext(os.path.basename(input_path))
            output_path = os.path.join(output_dir, f"{base}_step2{ext}")

            self._print_console(f"=== 开始 Step 2 处理: {os.path.basename(input_path)} ===")
            processor = Step2Processor(**params)
            processor.process(input_path, output_path)

            def on_success():
                self.processing = False
                self.step2_btn.config(text="Start Step 2 (Plateau, NonLinearity & RMS)", state=tk.NORMAL)
                self._print_console(f"[完成] Step 2 分析报告已输出至目录: {output_dir}")
                messagebox.showinfo("完成", f"Step 2 分析完成！输出位于:\n{output_dir}")
                if os.path.exists(output_dir):
                    os.startfile(output_dir)

            self.root.after(0, on_success)

        except Exception as e:
            def on_fail():
                self.processing = False
                self.step2_btn.config(text="Start Step 2 (Plateau, NonLinearity & RMS)", state=tk.NORMAL)
                messagebox.showerror("Step 2 异常", f"处理失败: {e}")
            self.root.after(0, on_fail)

    def select_batch_step2_folder(self):
        """批量扫描目录并执行 Step 2"""
        if self.processing:
            return

        folder_path = filedialog.askdirectory()
        if not folder_path:
            return

        try:
            params = self._get_step2_params()
        except ValueError as ve:
            messagebox.showerror("参数错误", f"请检查输入的数值参数: {ve}")
            return

        # 扫描包含 merged_data.csv 或已拆分 csv 的子目录
        files_to_process = []
        for root, _, files in os.walk(folder_path):
            if "merged_data.csv" in files:
                files_to_process.append(os.path.join(root, "merged_data.csv"))
            else:
                for f in files:
                    if f.endswith(".csv") and not any(k in f for k in ['between_edges', 'analysis', 'rms', 'step2']):
                        files_to_process.append(os.path.join(root, f))
                        break

        if not files_to_process:
            messagebox.showwarning("未发现文件", "在选定目录中未找到待处理的数据 CSV 文件！")
            return

        self.processing = True
        self.batch_step2_btn.config(text="批量处理中...", state=tk.DISABLED)

        threading.Thread(target=self._batch_step2_thread, args=(files_to_process, params), daemon=True).start()

    def _batch_step2_thread(self, file_list: list, params: dict):
        total = len(file_list)
        success_count = 0
        failed_details = []

        self._print_console(f"=== 开始 Step 2 批量任务，共 {total} 个目标 ===")

        for idx, input_path in enumerate(file_list):
            folder_name = os.path.basename(os.path.dirname(input_path))
            try:
                self._print_console(f"[{idx+1}/{total}] 正在处理: {folder_name} -> {os.path.basename(input_path)}")
                output_path = os.path.join(os.path.dirname(input_path), "step2_summary.csv")

                processor = Step2Processor(**params)
                processor.process(input_path, output_path)
                success_count += 1
                self._print_console("   -> [成功]")

            except Exception as e:
                err_msg = str(e)
                failed_details.append(f"{folder_name}: {err_msg}")
                self._print_console(f"   -> [失败]: {err_msg}")

        def on_batch_done():
            self.processing = False
            self.batch_step2_btn.config(text="Batch Process Step 2 (Folder Scan)", state=tk.NORMAL)
            report = f"批量处理完成！\n成功: {success_count} 个\n失败: {len(failed_details)} 个"
            if failed_details:
                report += "\n\n部分失败名单:\n" + "\n".join(failed_details[:10])
            messagebox.showinfo("批量结果", report)

        self.root.after(0, on_batch_done)

    # --------------------------------------------------------------------------
    # 帮助说明
    # --------------------------------------------------------------------------

    def show_app_help(self):
        """显示帮助说明窗口"""
        help_path = resource_path("config/help.txt")
        content = "离心机数据处理应用说明 (basic_centrifuge):\n\n"
        if os.path.exists(help_path):
            with open(help_path, 'r', encoding='utf-8') as f:
                content += f.read()
        else:
            content += (
                "1. Step 1 (原始数据清洗与拆分):\n"
                "   - 选择原始采集文件 (.csv / .txt)。\n"
                "   - 设定设备型号 (SingleCrashSensor, TDK20685, MEMS 等)。\n"
                "   - 点击 Start Step 1，自动按 CAN ID 通道拆分并绘制初始时序波形图。\n\n"
                "2. Step 2 (阶梯稳态与性能评定):\n"
                "   - 设置零位正负分割阈值 (Zero_Division_P / N)。\n"
                "   - 设置加速度梯度 (固定步进或自定义梯度序列)。\n"
                "   - 点击 Start Step 2，自动提取各稳态段、计算均值、绘制阶梯图并输出非线性度与 RMS 噪声。\n\n"
                "3. 批量功能:\n"
                "   - Convert TXT Folder to CSV: 递归遍历目录将原始 TXT 转换为标准 CSV。\n"
                "   - Batch Process Step 2: 扫描目录中所有子文件夹并批量生成评定报告。"
            )

        help_win = tk.Toplevel(self.root)
        help_win.title("APP 使用说明")
        help_win.geometry("640x500")

        text_area = ScrolledText(help_win, wrap=tk.WORD, font=('Microsoft YaHei', 10), padx=8, pady=8)
        text_area.pack(expand=True, fill='both')
        text_area.insert(tk.END, content)
        text_area.configure(state='disabled')


def main():
    root = tk.Tk()
    app = SensorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
