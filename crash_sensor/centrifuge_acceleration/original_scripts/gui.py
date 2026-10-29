import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from configparser import ConfigParser
import threading
from processor.sensor_processor import SensorProcessor
from processor.sensor_processor2 import Step2Processor
from io import TextIOBase
from tkinter.scrolledtext import ScrolledText
# 在SensorGUI类初始化中添加
from queue import Queue
import pandas as pd  # Step2Processor需要
from tkinter import messagebox  # 部分版本需要显式导入
def resource_path(relative_path):
    """ 获取资源的绝对路径 """
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath("")
    return os.path.join(base_path, relative_path)



# 新增文本信息框
# 修正输出重定向
# 在ConsoleRedirector类中添加缓冲
class ConsoleRedirector(TextIOBase):
    def __init__(self, gui_instance):
        self.gui = gui_instance  # 正确接收SensorGUI实例

    def write(self, s):
        self.gui.thread_safe_print(s)  # 调用正确的方法
        return len(s)

    def flush(self):
        # 空实现避免异常
        pass

class SensorGUI:

    # 在SensorGUI类中添加输出方法-文本信息框
    def thread_safe_print(self, message):
        # 批量处理消息优化
        self.output_queue.put(message)
        if not self.after_id:
            self._process_output_queue()

        # 修改_process_output_queue方法
    def _process_output_queue(self):
        def _process_output_queue(self):
            if self.after_id:
                self.root.after_cancel(self.after_id)
       # 批量处理队列内容
        messages = []
        while not self.output_queue.empty():
            messages.append(self.output_queue.get())

        if messages:
            # 单次更新文本框
            self.console.configure(state='normal')
            self.console.insert(tk.END, ''.join(messages))
            self.console.see(tk.END)
            self.console.configure(state='disabled')

            # 调整轮询间隔为200ms
        self.after_id = self.root.after(200, self._process_output_queue) if self.processing else None

    def __init__(self, root):

        self.root = root
        self.root.title("Sensor Data Processor - GUI")
        # 调整窗口初始尺寸
        self.root.geometry("550x600")

        # 初始化队列和定时器ID-文本信息框
        self.output_queue = Queue()
        self.after_id = None  # 新增

        # 初始化配置
        self.config = ConfigParser()
        self._load_config()

        # 设备模式选项
        self.mode_options = [
            'SingleThreeAxAccMEMS',
            'SingleThreeAxAccMEMS2',
            'SingleCrashSensor',
            'SingleCrashSensor_ASICFab2'
            'DoubleCrashSensor',
            'ThreeAxAccSensor',
            'TDK20685',
            'IMUFab2',
            'SingleCrashSensor_batch18'
        ]

        # 量程选项配置
        self.acc_ranges = [16.384, 32.768, 65.536, 4.096, 8.192]
        self.gyro_ranges = [328, 655.36, 1311, 1966, 218, 437,
                            874, 1311, 61, 123, 246, 492, 41, 82, 164]

        # 初始化变量
        self.device_mode_var = tk.StringVar(value=self.config['DEVICE']['mode'])
        self.acc_range_var = tk.DoubleVar(value=float(self.config.get('TDK20685', 'Acc_Range', fallback='16.384')))
        self.gyro_range_var = tk.DoubleVar(value=float(self.config.get('TDK20685', 'Gyro_Range', fallback='655.36')))
        self.file_path_var = tk.StringVar()
        # 替换原来的zero_division_var
        self.zero_division_p_var = tk.DoubleVar(value=35)  # 正阈值默认值
        self.zero_division_n_var = tk.DoubleVar(value=-35)  # 负阈值默认值

        self.fixed_step_var = tk.DoubleVar(value=20)
        self.columns_usedforfitting_var = tk.StringVar(value="None")
        # self.customSequence_step_var = tk.StringVar(value='-8, -6, -4, -2, 2, 4, 6, 8')
        # self.customSequence_step_var = tk.StringVar(value='-120, -60, 60, 120')
        self.customSequence_step_var = tk.StringVar(value='-120, -80, -40, 40, 80, 120')
        # self.customSequence_step_var = tk.StringVar(value='-240,-200, -160, -120, -80, -40, 40, 80, 120, 160, 200, 240')
        # self.accelerationStep_select_var = tk.StringVar(value='fixed_step')  # 改为字符串变量
        self.accelerationStep_select_var = tk.StringVar(value='custom_sequence')  # 改为字符串变量

        self.processing = False
        self.progress_var = tk.DoubleVar()

        # 构建界面
        self.create_widgets()
        self.csv_output_dir = None  # 新增变量
        #打包
        config_path = resource_path("config/settings.ini")
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        self.config = ConfigParser()
        self.config.read(config_path, encoding='utf-8')

        # 新增文本信息框
        sys.stdout = ConsoleRedirector(self)  # 传递GUI实例本身

    def _processing_thread(self):
        try:
            # 1. 获取在 process_data 中验证并保存的文件列表
            files_to_process = self.selected_files
            total_files = len(files_to_process)

            success_count = 0
            error_messages = []
            last_output_dir = ""  # 用于最后统一打开文件夹

            # 2. 开始遍历处理
            for index, input_path in enumerate(files_to_process):
                try:
                    # 获取文件名和目录
                    output_dir = os.path.dirname(input_path)
                    input_filename = os.path.basename(input_path)

                    # 动态生成带后缀的文件名
                    file_ext = os.path.splitext(input_filename)[1]
                    base_name = os.path.splitext(input_filename)[0]
                    output_filename = f"{base_name}_processed{file_ext}"
                    output_file = os.path.join(output_dir, output_filename)

                    # 打印当前进度到控制台
                    msg = f"正在处理 ({index + 1}/{total_files}): {input_filename}"
                    self.root.after(0, self._print_console, msg)

                    # 执行核心处理逻辑
                    self.processor.process(input_path, output_file)

                    success_count += 1
                    last_output_dir = output_dir  # 记录最后一个成功输出的目录

                    # 更新全局进度条 (按百分比计算)
                    progress = int(((index + 1) / total_files) * 100)
                    self.root.after(0, self.progress_var.set, progress)

                except Exception as file_e:
                    # 局部异常捕获：记录单个文件的错误，跳过该文件，继续循环
                    error_msg = f"[FAIL] 文件 {input_filename} 处理失败: {str(file_e)}"
                    error_messages.append(error_msg)
                    self.root.after(0, self._print_console, error_msg)

            # 3. 整个批处理循环结束，统一调用新的收尾回调
            self.root.after(0, self._on_batch_complete, total_files, success_count, error_messages, last_output_dir)

        except Exception as e:
            # 捕获线程级别的致命错误 (例如列表为空或其他无法预料的灾难错误)
            self.root.after(0, self._on_error, f"批处理线程发生致命错误: {str(e)}")

    # --- 新增：专门用于批处理结束的回调方法 ---
    def _on_batch_complete(self, total, success, errors, last_output_dir):
        self.auto_scroll = True
        self.console.see(tk.END)

        # 恢复UI状态
        self.processing = False
        self.process_btn.config(text="Start_DataProcessing_Step1", state=tk.NORMAL)

        # 在控制台打印总结信息
        summary_msg = f"\n=== 批处理完成 ===\n共 {total} 个文件，成功 {success} 个，失败 {len(errors)} 个。"
        self._print_console(summary_msg)

        # 弹窗提示结果
        if errors:
            messagebox.showwarning(title="处理完成 (含错误)",
                                   message=f"处理完毕！但有 {len(errors)} 个文件失败。\n请查看控制台日志了解详情。")
        else:
            messagebox.showinfo(title="处理完成", message=f"全部 {total} 个文件处理成功！")

        # 仅在最后打开一次输出目录 (避免轰炸)
        if last_output_dir and os.path.exists(last_output_dir):
            os.startfile(last_output_dir)

    def create_widgets(self):
        # 文件选择组件
        ttk.Label(self.root, text="Select File:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(self.root, textvariable=self.file_path_var, width=40).grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Button(self.root, text="Browse", command=self.select_file).grid(row=0, column=2, padx=5, pady=5)

        # 设备模式选择
        ttk.Label(self.root, text="Device Mode:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        device_mode_combo = ttk.Combobox(
            self.root,
            textvariable=self.device_mode_var,
            values=['TDK20685','SingleThreeAxAccMEMS','SingleThreeAxAccMEMS2','ThreeAxAccSensor', 'SingleCrashSensor',
                    'DoubleCrashSensor', 'IMUFab2','SingleCrashSensor_ASICFab2', 'SingleCrashSensor_batch18'],
            state="readonly"
        )
        device_mode_combo.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Button(self.root, text="APP解析", command=self.show_app_help).grid(row=1, column=2, padx=5, pady=5)

        # 加速度计量程
        ttk.Label(self.root, text="TDK20685_AccRange:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        acc_combo = ttk.Combobox(self.root, textvariable=self.acc_range_var, values=self.acc_ranges, state="readonly")
        acc_combo.grid(row=2, column=1, padx=5, pady=5, sticky=tk.EW)

        # 陀螺仪量程
        ttk.Label(self.root, text="TDK20685_GyroRange:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        gyro_combo = ttk.Combobox(self.root, textvariable=self.gyro_range_var, values=self.gyro_ranges, state="readonly")
        gyro_combo.grid(row=3, column=1, padx=5, pady=5, sticky=tk.EW)

        # 处理按钮（先创建后布局）
        self.process_btn = ttk.Button(self.root, text="Start_Data_Processing_Step1", command=self.process_data)
        self.process_btn.grid(row=4, column=1, padx=5, pady=5, sticky=tk.EW)  # 修改为单列布局

        # 新增文件夹处理按钮
        self.folder_btn = ttk.Button(self.root, text="Convert Folder to CSV", command=self.select_and_convert_folder)
        self.folder_btn.grid(row=5, column=1, padx=5, pady=5, sticky=tk.EW)  # 并排放置在第四行
        # self.step2_btn.grid(row=11, column=0, columnspan=3, pady=10)

        # 调整列权重使按钮均匀分布
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)

        # step2新增组件
        # 原Zero_division组件修改为两个输入框
        # 原zero_division组件替换为：

        ttk.Label(self.root, text="Zero_Division_P (正阈值):").grid(row=6, column=0)
        ttk.Label(self.root, text="Zero_Division_N (负阈值):").grid(row=7, column=0)
        # 修改后的正确代码
        # 修改后的Entry控件布局代码
        ttk.Entry(self.root, textvariable=self.zero_division_p_var, width=15).grid(row=6, column=1, padx=5, pady=5,
                                                                                   sticky=tk.EW)
        ttk.Entry(self.root, textvariable=self.zero_division_n_var, width=15).grid(row=7, column=1, padx=5, pady=5,
                                                                                   sticky=tk.EW)

        ttk.Label(self.root, text="(按Step1修改)").grid(row=5, column=2, padx=5, sticky=tk.E)
        ttk.Label(self.root, text="AccelerationStep_Select:").grid(row=8, column=0, padx=5, pady=5, sticky=tk.W)
        # 同时修改Combobox定义：
        mode_combo = ttk.Combobox(
            self.root,
            textvariable=self.accelerationStep_select_var,
            values=['fixed_step', 'custom_sequence'],  # 与StringVar类型匹配
            state="readonly"
        )
        mode_combo.grid(row=8, column=1, padx=5, pady=5, sticky=tk.EW)
        # ttk.Label(self.root, text="(恒定或非恒定步进)").grid(row=6, column=1, padx=5, sticky=tk.E)

        # Fixed_Step
        ttk.Label(self.root, text="Fixed_Step:").grid(row=9, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(self.root, textvariable=self.fixed_step_var, width=15).grid(row=9, column=1, padx=5, pady=5, sticky=tk.EW)
        # ttk.Label(self.root, text="(可设置恒定步进值)").grid(row=7, column=1, padx=5, sticky=tk.E)

        # CustomSequence_STEPS
        ttk.Label(self.root, text="CustomSequence_Step:").grid(row=10, column=0, padx=5, pady=5, sticky=tk.W)
        custom_sequence_combo = ttk.Combobox(
            self.root,
            textvariable=self.customSequence_step_var,
            values=[
                "2, 4, 8, 16, 32",
                "-650, -520, -390, -260, -130, 0, 130, 260, 390, 520, 650"
            ],
            state="normal"  # 允许手动编辑
        )
        custom_sequence_combo.grid(row=10, column=1, padx=5, pady=5, sticky=tk.EW)
        # ttk.Entry(self.root, textvariable=self.customSequence_step_var, width=15).grid(row=8, column=1, padx=5, pady=5, sticky=tk.EW)
        # ttk.Label(self.root, text="(可设置非恒定步进值)").grid(row=8, column=1, padx=5, sticky=tk.E)

        # Columns_UsedForFitting组件
        ttk.Label(self.root, text="Columns_UsedForFitting:").grid(row=11, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(self.root, textvariable=self.columns_usedforfitting_var, width=15).grid(row=11, column=1, padx=5, pady=5, sticky=tk.EW)
        # ttk.Label(self.root, text="(可设置前x列数据拟合)").grid(row=9, column=1, padx=5, sticky=tk.E)

        # Step2按钮
        self.step2_btn = ttk.Button(self.root, text="Start_Processing_Step2", command=self.process_data_step2)
        self.step2_btn.grid(row=12, column=1, padx=10, pady=10, sticky=tk.EW)

        # === 新增代码: 批量 Step2 按钮 ===
        self.batch_step2_btn = ttk.Button(self.root, text="Batch Process Step2 (Folder)",
                                          command=self.select_batch_step2_folder)
        self.batch_step2_btn.grid(row=13, column=1, padx=10, pady=5, sticky=tk.EW)
        # ================================

        # 控制台输出（单一定义）
        # 在创建文本框时添加优化参数
        self.console = ScrolledText(
            self.root,
            wrap=tk.WORD,
            state='disabled',
            height=10,
            font=('Consolas', 9),  # 使用等宽字体
            tabs=(4, 'center'),  # 优化制表符处理
            spacing3=1,  # 行间距优化
            padx=5,
            pady=5
        )
        # 调整console位置到第7行
        self.console.grid(row=14, column=0, columnspan=4, padx=5, pady=5, sticky=tk.NSEW)

        # 调整网格布局权重
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(14, weight=1)

    def select_file(self):
        # 改动：将 askopenfilename 改为 askopenfilenames，支持多选文件
        file_paths = filedialog.askopenfilenames(
            filetypes=[("CSV Files", "*.csv"), ("TXT Files", "*.txt"), ("All Files", "*.*")]
        )
        if file_paths:
            # 改动：增加 self.selected_files 列表来保存所有选中的路径
            self.selected_files = list(file_paths)
            # 改动：将所有路径用逗号拼接后显示在UI输入框中
            self.file_path_var.set(", ".join(self.selected_files))

            # 改动：遍历所有选定的文件，判断并触发转换逻辑
            for file_path in self.selected_files:
                if file_path.lower().endswith('.txt'):
                    # 批评提示：原有代码中的 csv_path 定义未被使用，已在此处精简，直接传 file_path
                    # 自动触发文件转换逻辑
                    self.convert_txt_to_csv(file_path)

    def _print_console(self, message):
        self.console.configure(state='normal')
        self.console.insert(tk.END, message + "\n")
        self.console.configure(state='disabled')
        self.console.see(tk.END)

    def _load_config(self):
        try:
            self.config.read('config/settings.ini', encoding='utf-8')
        except Exception as e:
            messagebox.showerror("配置错误", f"无法读取配置文件: {str(e)}")

    def process_data(self):
        if self.processing:
            return

        # 添加文件路径验证
        # 改动：修改了验证逻辑，现在检查 self.selected_files 列表是否存在且不为空
        if not hasattr(self, 'selected_files') or not self.selected_files:
            messagebox.showerror(title="错误", message="请先选择输入文件")
            return

        # 文本框
        self.auto_scroll = False  # 暂停自动滚动
        self.console.configure(state='normal')
        self.console.delete(1.0, tk.END)  # 清空前次内容

        # 保存配置（添加类型转换）
        self.config['DEVICE']['mode'] = self.device_mode_var.get()
        self.config['TDK20685']['Acc_Range'] = str(self.acc_range_var.get())  # 转换为字符串
        self.config['TDK20685']['Gyro_Range'] = str(self.gyro_range_var.get())  # 转换为字符串

        try:
            with open('config/settings.ini', 'w', encoding='utf-8') as f:
                self.config.write(f)
        except Exception as e:
            messagebox.showerror(title="保存错误", message=f"无法保存配置: {str(e)}")
            return

        # 初始化处理器
        try:
            acc_range = float(self.acc_range_var.get())
            gyro_range = float(self.gyro_range_var.get())
        except ValueError:
            messagebox.showerror(title="参数错误", message="量程必须为有效数字")
            return

        # 应补充设备模式参数（根据代码中的配置参数）
        self.processor = SensorProcessor()  # 使用原始类
        self.processor.device_mode = self.device_mode_var.get()
        self.processor.config['TDK20685']['Acc_Range'] = str(acc_range)
        self.processor.config['TDK20685']['Gyro_Range'] = str(gyro_range)

        # 启动处理线程
        self.processing = True
        self.process_btn.config(text="处理中...", state=tk.DISABLED)
        self.progress_var.set(0)

        # 关键提醒：此处的 target=self._processing_thread 内部逻辑必须由你自己修改为循环处理 self.selected_files
        threading.Thread(target=self._processing_thread, daemon=True).start()

    def select_and_convert_folder(self):
        folder_path = filedialog.askdirectory()
        if not folder_path:
            return

        # 创建输出目录
        base_name = os.path.basename(folder_path.rstrip(os.sep))
        self.csv_output_dir = os.path.join(
            os.path.dirname(folder_path),
            f"{base_name}_csvconvert"
        )
        os.makedirs(self.csv_output_dir, exist_ok=True)

        # 启动处理线程
        threading.Thread(target=self._convert_folder_thread, args=(folder_path,)).start()

    def _convert_folder_thread(self, folder_path):
        try:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if file.endswith(".txt"):
                        txt_path = os.path.join(root, file)
                        relative_path = os.path.relpath(root, folder_path)
                        csv_dir = os.path.join(self.csv_output_dir, relative_path)
                        os.makedirs(csv_dir, exist_ok=True)

                        # 转换文件
                        csv_path = os.path.join(csv_dir, file.replace(".txt", ".csv"))
                        self.convert_txt_to_csv(txt_path, csv_path)

            messagebox.showinfo("完成", f"所有文件已转换至：{self.csv_output_dir}")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def convert_txt_to_csv(self, txt_path, csv_path):
        # 读取txt文件并添加列头
        columns = ['AccX', 'AccY', 'AccZ', 'AccZC', 'GyroX', 'GyroY', 'GyroZ', 'Temperature']
        try:
            # [PASS] 修改读取方式：添加列名参数
            df = pd.read_csv(txt_path, sep='\t|,', engine='python', header=None, names=columns)  # 新增names参数
            df.to_csv(csv_path, index=False)
            self._print_console(f"已转换：{os.path.basename(txt_path)}")

            # [PASS] 传递正确的列名到绘图方法
            self._generate_column_plots(df, csv_path, columns)  # 新增columns参数
        except Exception as e:
            self._print_console(f"转换失败：{txt_path} - {str(e)}")

    def _generate_column_plots(self, df, csv_path, columns):
        """为CSV的每一列生成时序图（使用列名作为文件名）"""
        import matplotlib.pyplot as plt

        # 创建图片保存目录
        base_name = os.path.splitext(csv_path)[0]
        plot_dir = f"{base_name}_plots"
        os.makedirs(plot_dir, exist_ok=True)

        plt.ioff()  # 非交互模式

        try:
            # [PASS] 直接使用传入的列名
            for idx, col_name in enumerate(columns):  # 不再需要过滤Unnamed列
                plt.figure(figsize=(12, 6))

                # 生成时序图
                plt.plot(df.iloc[:, idx])
                plt.title(f"{col_name} - {os.path.basename(csv_path)}")  # 使用正确的列名
                plt.xlabel("Sample")
                plt.ylabel("Value")
                plt.grid(True)

                # 构建图片路径
                safe_col_name = str(col_name).replace("/", "_").replace("\\", "_")
                # filename = f"{os.path.splitext(os.path.basename(csv_path))[0]}_{safe_col_name}.png"
                filename = f"{safe_col_name}.png"
                plot_path = os.path.join(plot_dir, filename)

                plt.savefig(plot_path, dpi=150, bbox_inches='tight')
                plt.close()

            self._print_console(f"已生成图表：{plot_dir}")
        except Exception as e:
            self._print_console(f"图表生成失败：{str(e)}")
        finally:
            plt.close('all')

    # === 新增模块: 批量处理逻辑 ===
    def select_batch_step2_folder(self):
        """选择文件夹并开始批量Step2处理"""
        if self.processing:
            return

        folder_path = filedialog.askdirectory()
        if not folder_path:
            return

        # 1. 预先读取 GUI 参数 (必须在主线程进行)
        try:
            config_params = {
                'zero_division_p': float(self.zero_division_p_var.get()),
                'zero_division_n': float(self.zero_division_n_var.get()),
                'fixed_step': float(self.fixed_step_var.get()),
                'device_mode': self.device_mode_var.get(),
                'accelerationstep_select': self.accelerationStep_select_var.get(),
                'custom_sequence': self.customSequence_step_var.get(),
                'columns': self.columns_usedforfitting_var.get().strip() or None
            }
        except ValueError as e:
            messagebox.showerror("参数错误", f"请检查输入的数值格式: {str(e)}")
            return

        # 2. 扫描所有 merged_data.csv 文件
        files_to_process = []
        for root, dirs, files in os.walk(folder_path):
            if "merged_data.csv" in files:
                files_to_process.append(os.path.join(root, "merged_data.csv"))

        if not files_to_process:
            messagebox.showwarning("未找到文件", "在所选文件夹中未找到 'merged_data.csv' 文件。")
            return

        # 3. 启动批量处理线程
        self.processing = True
        self.step2_btn.config(state=tk.DISABLED)
        self.batch_step2_btn.config(text="批量处理中...", state=tk.DISABLED)

        threading.Thread(
            target=self.batch_step2_thread,
            args=(files_to_process, config_params),
            daemon=True
        ).start()

    def batch_step2_thread(self, file_list, params):
        """后台处理线程：处理文件列表并记录详细的失败信息"""
        total_files = len(file_list)
        success_count = 0
        fail_count = 0
        failed_details = []  # 用于存储失败的文件夹名和原因

        self.thread_safe_print(f"=== 开始批量任务，共 {total_files} 个文件 ===")

        for idx, input_path in enumerate(file_list):
            try:
                # 获取当前正在处理的文件夹名（用于显示进度）
                folder_name = os.path.basename(os.path.dirname(input_path))
                self.thread_safe_print(f"[{idx + 1}/{total_files}] 处理: {folder_name}")

                # 构造输出路径
                output_dir = os.path.dirname(input_path)
                file_ext = os.path.splitext(input_path)[1]
                output_path = os.path.join(output_dir, f"step2_processed{file_ext}")

                # 初始化处理器
                processor = Step2Processor(
                    upDown_division=0,
                    zero_division_p=params['zero_division_p'],
                    zero_division_n=params['zero_division_n'],
                    fixed_step=params['fixed_step'],
                    device_mode=params['device_mode'],
                    accelerationstep_select=params['accelerationstep_select'],
                    custom_sequence=params['custom_sequence'],
                    columns=params['columns']
                )

                # 执行处理
                processor.process(input_path, output_path)
                self.thread_safe_print(f"   -> [PASS] 成功")
                success_count += 1

            except Exception as e:
                error_msg = str(e)
                self.thread_safe_print(f"   -> [FAIL] 失败: {error_msg}")
                fail_count += 1

                # 记录具体是哪个文件夹失败了
                failed_folder = os.path.basename(os.path.dirname(input_path))
                failed_details.append(f"• {failed_folder} : {error_msg}")

        # 批量结束
        self.thread_safe_print(f"\n=== 批量处理完成 ===")

        # 恢复 UI 并弹窗报告
        def reset_ui():
            self.processing = False
            self.step2_btn.config(state=tk.NORMAL)
            self.batch_step2_btn.config(text="Batch Process (Multi-Folders)", state=tk.NORMAL)

            # 构建详细报告
            report_msg = f"处理完成\n\n成功: {success_count} 个文件夹\n失败: {fail_count} 个文件夹"

            if failed_details:
                report_msg += "\n\n[FAIL] 失败文件夹名单:\n"
                # 如果错误太多，截断显示，避免弹窗超出屏幕
                if len(failed_details) > 15:
                    report_msg += "\n".join(failed_details[:15])
                    report_msg += f"\n... (还有 {len(failed_details) - 15} 个错误，请查看控制台)"
                else:
                    report_msg += "\n".join(failed_details)

            messagebox.showinfo("批量处理结果", report_msg)

        self.root.after(0, reset_ui)


    # ================================

    def update_progress(self, current, total):
        progress = (current / total) * 100
        self.root.after(0, self.progress_var.set, progress)

    def _on_success(self, output_path, grouped_data):
        self.file_path_var.set(output_path)
        self.auto_scroll = True
        self.console.see(tk.END)

        # 自动打开目录
        output_dir = os.path.dirname(output_path)
        if os.path.exists(output_dir):
            os.startfile(output_dir)

        self.processing = False
        self.process_btn.config(text="Start_DataProcessing_Step1", state=tk.NORMAL)

        # success_msg = f"数据处理完成！\n输出文件：{output_path}"
        # messagebox.showinfo("完成", success_msg)

    def _on_error(self, error_msg):
        self.processing = False
        self.process_btn.config(text="Start_Data_Processing_Step1", state=tk.NORMAL)
        self.progress_var.set(0)
        messagebox.showerror("处理错误", error_msg)

    def process_data_step2(self):
        """Step2处理逻辑（自动获取Step1输出文件）"""
        try:
            input_path = self.file_path_var.get()
            if not input_path:
                raise ValueError("请先完成Step1处理")

            if not os.path.exists(input_path):
                raise FileNotFoundError(f"输入文件不存在: {input_path}")

            # 生成输出路径
            output_dir = os.path.dirname(input_path)
            file_ext = os.path.splitext(input_path)[1]
            output_path = os.path.join(output_dir, f"step2_processed{file_ext}")

            # 显示文件导入确认提示 [PASS] 新增代码
            import_msg = f"成功导入Step1输出文件：\n{os.path.basename(input_path)}"
            messagebox.showinfo("文件已加载", import_msg)

            # 自动生成Step2输出路径
            output_dir = os.path.dirname(input_path)
            file_ext = os.path.splitext(input_path)[1]
            output_path = os.path.join(output_dir, f"step2_processed{file_ext}")

            # 初始化处理器
            processor = Step2Processor(
                upDown_division=0,  # 新增参数
                zero_division_p=float(self.zero_division_p_var.get()),  # 获取正阈值
                zero_division_n=float(self.zero_division_n_var.get()),  # 获取负阈值
                fixed_step=float(self.fixed_step_var.get()),
                device_mode=self.device_mode_var.get(),
                accelerationstep_select=self.accelerationStep_select_var.get(),
                custom_sequence=self.customSequence_step_var.get(),
                columns=self.columns_usedforfitting_var.get().strip() or None
            )

            # 启动处理线程
            self.processing = True
            self.step2_btn.config(text="处理中...", state=tk.DISABLED)
            threading.Thread(target=lambda: self._step2_thread(processor, input_path, output_path), daemon=True).start()

            # 启动线程
            self.processing = True
            self.step2_btn.config(text="处理中...", state=tk.DISABLED)
            threading.Thread(
                target=lambda: self._step2_thread(processor, input_path, output_path),
                daemon=True
            ).start()

        except Exception as e:
            self.root.after(0, self._on_step2_error, str(e))

    # 处理线程的异常捕获
    def _step2_thread(self, processor, input_path, output_path):
        # try:
        #     processor.process(input_path, output_path)  # 直接使用传入的processor
        #     self.root.after(0, self._on_step2_success, output_path)
        # except Exception as e:
        #     self.root.after(0, self._on_step2_error, str(e))



        import time
        start_time = time.time()
        while not self.output_queue.empty():
            if time.time() - start_time > 10:  # 超时10秒
                break
        try:
            print("[DEBUG] 线程启动")
            input_path = self.file_path_var.get()
            output_dir = os.path.dirname(input_path)
            input_filename = os.path.basename(input_path)
            file_ext = os.path.splitext(input_filename)[1]
            output_filename = f"step2_processed{file_ext}"
            output_file = os.path.join(output_dir, output_filename)

            # 获取columns参数（新增）
            columns = self.columns_usedforfitting_var.get().strip()
            if columns.lower() == "none" or not columns:
                columns = None
            else:
                try:
                    columns = int(columns)
                except ValueError:
                    columns = None

            # 调用处理器
            # self.step2_processor.process(input_path, output_file)
            self.step2_processor = Step2Processor(
                zero_division_p=float(self.zero_division_p_var.get()),  # 从GUI获取正阈值
                zero_division_n=float(self.zero_division_n_var.get()),  # 从GUI获取负阈值
                upDown_division=0,  # 新增参数
                fixed_step=float(self.fixed_step_var.get()),
                device_mode=self.device_mode_var.get(),
                accelerationstep_select=self.accelerationStep_select_var.get(),
                custom_sequence=self.customSequence_step_var.get(),
                columns=columns
            )

            # 执行核心处理逻辑（取消注释）
            self.step2_processor.process(input_path, output_file)
            processor.process(input_path, output_path)
            self.root.after(0, self._on_step2_success, output_path)
        except Exception as e:
            import traceback
            error_msg = f"Step2处理错误:\n{str(e)}\n\n{traceback.format_exc()}"
            self.root.after(0, self._on_step2_error, error_msg)

    def _on_step2_success(self, output_path):
        """Step2成功处理"""
        self.processing = False
        self.step2_btn.config(text="Start_DataProcessing_Step2", state=tk.NORMAL)

        # success_msg = f"Step2处理完成！/n输出文件：{output_path}"
        # messagebox.showinfo("处理完成", success_msg)

        # 自动打开输出目录
        output_dir = os.path.dirname(output_path)
        if os.path.exists(output_dir):
            os.startfile(output_dir)

    def _on_step2_error(self, error_msg):
        """Step2错误处理"""
        self.processing = False
        self.step2_btn.config(text="Start_DataProcessing_Step2", state=tk.NORMAL)
        messagebox.showerror("处理错误", error_msg)

    def show_app_help(self):
        """显示APP解析文档"""
        try:
            help_path = resource_path("config/help.txt")  # 假设帮助文档在config目录
            with open(help_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 创建新窗口
            help_win = tk.Toplevel(self.root)
            help_win.title("APP使用说明")
            help_win.geometry("800x600")

            # 添加滚动文本框
            text_area = ScrolledText(help_win, wrap=tk.WORD, font=('宋体', 11))
            text_area.pack(expand=True, fill='both', padx=10, pady=10)

            # 插入内容
            text_area.insert(tk.END, content)
            text_area.configure(state='disabled')

        except FileNotFoundError:
            messagebox.showerror("错误", "帮助文档未找到！")
        except Exception as e:
            messagebox.showerror("错误", f"读取文档失败：{str(e)}")


def main():
    root = tk.Tk()
    app = SensorGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()