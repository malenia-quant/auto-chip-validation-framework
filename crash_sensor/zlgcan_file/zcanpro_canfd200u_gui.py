# -*- coding:utf-8 -*-
"""
    ZLGCAN CANFD-200U Decoupled Controller GUI
    A premium, high-performance, and thread-safe industrial controller GUI.
    Aesthetics & Layout inspired by ZCanPro. Utilizing clean English typography (Segoe UI).
"""

import sys
import os
import time
import csv
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from datetime import datetime
from ctypes import *

# ================= Environment & Driver Configuration =================
script_dir = os.path.dirname(os.path.abspath(__file__))
zlgcan_real_dir = os.path.join(script_dir, "zlgcan_python_251211")
kernel_dir = os.path.join(zlgcan_real_dir, "kerneldlls")

# 1. 提升 Python 包搜索优先级
sys.path.insert(0, zlgcan_real_dir)

# 2. 针对 Python 3.8+ (包括 3.11) 必须注册 DLL 安全目录
if hasattr(os, 'add_dll_directory'):
    try:
        os.add_dll_directory(zlgcan_real_dir)
        if os.path.exists(kernel_dir):
            os.add_dll_directory(kernel_dir)
    except Exception as e:
        print(f"Warning: Failed to add DLL directory: {e}")

# 3. 兼容老版本及 C 底层查找，注入环境变量
os.environ['PATH'] = zlgcan_real_dir + os.pathsep + kernel_dir + os.pathsep + os.environ['PATH']

# 4. 终极物理隔离打破：强行将当前工作目录切换到驱动文件夹进行导入
DLL_AVAILABLE = False
original_cwd = os.getcwd()
try:
    os.chdir(zlgcan_real_dir)
    from zlgcan import *
    DLL_AVAILABLE = True
    print(f"成功在指定目录加载 Zlgcan 环境，并已注册子依赖库目录")
except Exception as e:
    DLL_AVAILABLE = False
    print(f"[-] Failed to load ZLGCAN drivers: {e}")
finally:
    os.chdir(original_cwd)

# ================= Thread-Safe CSV Recorder =================
class CSVRecorder:
    def __init__(self):
        self.file = None
        self.writer = None
        self.filepath = None
        self.queue = queue.Queue()
        self.thread = None
        self.active = False
        self.lock = threading.Lock()
        
    def start(self, filepath=None):
        with self.lock:
            if self.active:
                return self.filepath
            if filepath:
                self.filepath = filepath
            else:
                save_dir = os.path.join(script_dir, "pz_test_data")
                os.makedirs(save_dir, exist_ok=True)
                filename = datetime.now().strftime("CAN_Record_%Y%m%d_%H%M%S.csv")
                self.filepath = os.path.join(save_dir, filename)
            self.file = open(self.filepath, 'w', newline='', encoding='utf-8')
            self.writer = csv.writer(self.file)
            self.writer.writerow(['Timestamp', 'Channel', 'Protocol', 'Direction', 'ID', 'FrameType', 'FrameFormat', 'DLC', 'Data'])
            
            self.active = True
            self.thread = threading.Thread(target=self._write_loop, daemon=True)
            self.thread.start()
            return self.filepath
            
    def _write_loop(self):
        while self.active or not self.queue.empty():
            try:
                row = self.queue.get(timeout=0.1)
                if self.writer is not None:
                    self.writer.writerow(row)
            except queue.Empty:
                continue
                
    def write(self, row):
        if self.active:
            self.queue.put(row)
                
    def stop(self):
        with self.lock:
            if not self.active:
                return None
            self.active = False
            
        if self.thread is not None:
            self.thread.join(timeout=2.0)
            self.thread = None
            
        with self.lock:
            if self.file is not None:
                self.file.close()
                path = self.filepath
                self.file = None
                self.writer = None
                self.filepath = None
                
                # Clear remainder of the queue
                while not self.queue.empty():
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        break
                        
                return path
            return None

# ================= Main GUI Application Class =================
class ZCanProGuiApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ZLGCAN CANFD-200U Decoupled Controller")
        self.root.geometry("1100x820")
        self.root.minsize(1050, 750)
        
        # Engine variables
        self.zcanlib = None
        self.device_handle = INVALID_DEVICE_HANDLE
        self.chn_handles = []
        self.thread_flag = False
        
        # Listening & Logging state
        self.is_listening = False
        self.is_logging = False
        self.csv_recorder = CSVRecorder()
        
        # Thread-safe Communication Queues
        self.gui_queue = queue.Queue()
        
        # List sending configurations
        self.list_send_active = False
        
        # Configure overall themes
        self.setup_styles()
        
        # Build UI layout
        self.build_ui()
        
        # Load Zlgcan Library
        self.load_zlgcan_library()
        
        # Start GUI polling handlers
        self.poll_queues()

    def setup_styles(self):
        self.root.configure(bg="#f4f5f7")
        style = ttk.Style()
        style.theme_use("vista")
        
        # Custom Fonts (Segoe UI for Interface, Consolas for Monospace logs)
        self.title_font = ("Segoe UI", 16, "bold")
        self.header_font = ("Segoe UI Semibold", 11)
        self.regular_font = ("Segoe UI", 10)
        self.bold_font = ("Segoe UI", 10, "bold")
        self.console_font = ("Consolas", 10)
        
        # TTK Widget Styling
        style.configure(".", font=self.regular_font, background="#f4f5f7")
        style.configure("TLabel", background="#f4f5f7", foreground="#2d3748")
        style.configure("TLabelframe", background="#f4f5f7", borderwidth=1, relief="solid")
        style.configure("TLabelframe.Label", font=self.header_font, foreground="#4b5563")
        
        # Buttons Style
        style.configure("TButton", font=self.regular_font, padding=4)
        style.configure("Action.TButton", font=self.bold_font, padding=6)
        
        # Custom Accent Notebook
        style.configure("TNotebook", background="#e5e7eb")
        style.configure("TNotebook.Tab", font=self.header_font, padding=(12, 6))

    def build_ui(self):
        # 1. Main Header
        header_frame = tk.Frame(self.root, bg="#2d3748", height=60)
        header_frame.pack(fill=tk.X, side=tk.TOP)
        header_frame.pack_propagate(False)
        
        title_lbl = tk.Label(header_frame, text="ZLGCAN CANFD-200U DECOUPLED CONTROLLER", font=self.title_font, fg="#ffffff", bg="#2d3748")
        title_lbl.pack(side=tk.LEFT, padx=15, pady=12)
        
        # LED Status Indicator
        self.status_led = tk.Canvas(header_frame, width=16, height=16, bg="#2d3748", highlightthickness=0)
        self.status_led.pack(side=tk.RIGHT, padx=(5, 20), pady=18)
        self.led_circle = self.status_led.create_oval(2, 2, 14, 14, fill="#e74c3c")  # Red initially
        
        self.status_lbl = tk.Label(header_frame, text="● DISCONNECTED", font=self.bold_font, fg="#fc8181", bg="#2d3748")
        self.status_lbl.pack(side=tk.RIGHT, padx=5, pady=18)

        # 2. Main Tabbed Control (Notebook)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.tab_monitor = ttk.Frame(self.notebook)
        self.tab_list_send = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_monitor, text="  Control & Monitor (监控接收)  ")
        self.notebook.add(self.tab_list_send, text="  List Sender (列表发送)  ")
        
        self.build_monitor_tab()
        self.build_list_sender_tab()

    def build_monitor_tab(self):
        # Left Side: Configurations and Sending Controls
        left_pane = ttk.Frame(self.tab_monitor, padding=(5, 5), width=380)
        left_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)
        left_pane.pack_propagate(False)
        
        # Pane 1: Hardware Connection
        conn_frame = ttk.LabelFrame(left_pane, text=" Hardware Connection Setup ")
        conn_frame.pack(fill=tk.X, pady=(5, 5), padx=5)
        
        grid_conn = ttk.Frame(conn_frame, padding=5)
        grid_conn.pack(fill=tk.X)
        
        ttk.Label(grid_conn, text="Device Type:").grid(row=0, column=0, sticky=tk.W, pady=3, padx=2)
        self.dev_type_combo = ttk.Combobox(grid_conn, values=["USBCANFD-200U"], width=18, state="readonly")
        self.dev_type_combo.set("USBCANFD-200U")
        self.dev_type_combo.grid(row=0, column=1, sticky=tk.W, pady=3, padx=2)
        
        ttk.Label(grid_conn, text="Device Idx:").grid(row=1, column=0, sticky=tk.W, pady=3, padx=2)
        self.dev_idx_spin = ttk.Spinbox(grid_conn, from_=0, to=10, width=5)
        self.dev_idx_spin.set(0)
        self.dev_idx_spin.grid(row=1, column=1, sticky=tk.W, pady=3, padx=2)
        
        btn_grid = ttk.Frame(conn_frame, padding=5)
        btn_grid.pack(fill=tk.X)
        self.btn_connect = ttk.Button(btn_grid, text="Open Device", command=self.action_open_device)
        self.btn_connect.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.btn_disconnect = ttk.Button(btn_grid, text="Close Device", command=self.action_close_device, state=tk.DISABLED)
        self.btn_disconnect.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=2)

        # Pane 2: Channel Parameters & Controls
        chn_frame = ttk.LabelFrame(left_pane, text=" Channel Configuration ")
        chn_frame.pack(fill=tk.X, pady=5, padx=5)
        
        grid_chn = ttk.Frame(chn_frame, padding=5)
        grid_chn.pack(fill=tk.X)
        
        ttk.Label(grid_chn, text="Nominal Baud (Arbitration):").grid(row=0, column=0, sticky=tk.W, pady=3, padx=2)
        self.nom_baud_combo = ttk.Combobox(grid_chn, values=["1000000", "500000", "250000"], width=10, state="readonly")
        self.nom_baud_combo.set("1000000")  # Default 1Mbps
        self.nom_baud_combo.grid(row=0, column=1, sticky=tk.W, pady=3, padx=2)
        
        ttk.Label(grid_chn, text="Data Baud (CANFD Domain):").grid(row=1, column=0, sticky=tk.W, pady=3, padx=2)
        self.data_baud_combo = ttk.Combobox(grid_chn, values=["2000000", "4000000", "1000000"], width=10, state="readonly")
        self.data_baud_combo.set("2000000")  # Default 2Mbps
        self.data_baud_combo.grid(row=1, column=1, sticky=tk.W, pady=3, padx=2)
        
        self.res_var = tk.BooleanVar(value=True)
        self.chk_res = ttk.Checkbutton(grid_chn, text="Enable 120Ω Terminal Resistor", variable=self.res_var)
        self.chk_res.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=5, padx=2)
        
        btn_chn_grid = ttk.Frame(chn_frame, padding=5)
        btn_chn_grid.pack(fill=tk.X)
        self.btn_start_chn = ttk.Button(btn_chn_grid, text="Start Channels", command=self.action_start_channels, state=tk.DISABLED)
        self.btn_start_chn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.btn_stop_chn = ttk.Button(btn_chn_grid, text="Reset Channels", command=self.action_reset_channels, state=tk.DISABLED)
        self.btn_stop_chn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=2)

        # Pane 3: Preset Frame Sender
        preset_frame = ttk.LabelFrame(left_pane, text=" Decoupled Transmission (TX) Presets ")
        preset_frame.pack(fill=tk.X, pady=5, padx=5)
        
        btn_preset_grid = ttk.Frame(preset_frame, padding=5)
        btn_preset_grid.pack(fill=tk.X)
        
        self.btn_tx_write = ttk.Button(btn_preset_grid, text="Write Flash (写flash)", command=self.action_send_write_flash, state=tk.DISABLED)
        self.btn_tx_write.pack(fill=tk.X, pady=3)
        self.btn_tx_read = ttk.Button(btn_preset_grid, text="Read Flash (读flash)", command=self.action_send_read_flash, state=tk.DISABLED)
        self.btn_tx_read.pack(fill=tk.X, pady=3)
        
        self.btn_tx_seq = ttk.Button(preset_frame, text=" Sequential Send [Write -> Read] (顺序发送) ", command=self.action_send_sequential, style="Action.TButton", state=tk.DISABLED)
        self.btn_tx_seq.pack(fill=tk.X, padx=8, pady=(2, 8))

        # Pane 4: Custom Frame Sender
        custom_frame = ttk.LabelFrame(left_pane, text=" Custom Frame Transmission ")
        custom_frame.pack(fill=tk.X, pady=5, padx=5)
        
        grid_custom = ttk.Frame(custom_frame, padding=5)
        grid_custom.pack(fill=tk.X)
        
        ttk.Label(grid_custom, text="Frame ID (Hex):").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.ent_tx_id = ttk.Entry(grid_custom, width=12)
        self.ent_tx_id.insert(0, "251")
        self.ent_tx_id.grid(row=0, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(grid_custom, text="Protocol Type:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.tx_proto_combo = ttk.Combobox(grid_custom, values=["CANFD_BRS", "CANFD", "CAN"], width=10, state="readonly")
        self.tx_proto_combo.set("CANFD_BRS")
        self.tx_proto_combo.grid(row=1, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(grid_custom, text="DLC Length:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.tx_dlc_spin = ttk.Spinbox(grid_custom, from_=1, to=64, width=5)
        self.tx_dlc_spin.set(8)
        self.tx_dlc_spin.grid(row=2, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(grid_custom, text="Data Bytes (Hex):").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.ent_tx_data = ttk.Entry(grid_custom, width=28)
        self.ent_tx_data.insert(0, "01 11 22 33 44 55 66 77")
        self.ent_tx_data.grid(row=3, column=1, sticky=tk.W, pady=2)
        
        self.btn_send_custom = ttk.Button(custom_frame, text="Send Custom Frame", command=self.action_send_custom, state=tk.DISABLED)
        self.btn_send_custom.pack(fill=tk.X, padx=8, pady=(4, 8))

        # Right Side: Receiver Control & Console Log
        right_pane = ttk.Frame(self.tab_monitor, padding=(5, 5))
        right_pane.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Receiver Status Bar
        rx_control_frame = ttk.LabelFrame(right_pane, text=" Monitor & CSV Dynamic Logger ")
        rx_control_frame.pack(fill=tk.X, pady=(5, 5), padx=5)
        
        ctrl_layout = ttk.Frame(rx_control_frame, padding=5)
        ctrl_layout.pack(fill=tk.X)
        
        self.btn_toggle_listen = ttk.Button(ctrl_layout, text=" Start Real-time Listening (实时监听) ", command=self.action_toggle_listen, state=tk.DISABLED)
        self.btn_toggle_listen.pack(side=tk.LEFT, padx=5, pady=2)
        
        self.btn_toggle_csv = ttk.Button(ctrl_layout, text=" Start CSV Recording (保存CSV) ", command=self.action_toggle_logging)
        self.btn_toggle_csv.pack(side=tk.LEFT, padx=15)
        
        btn_open_folder = ttk.Button(ctrl_layout, text="Open CSV Folder", command=self.action_open_csv_folder)
        btn_open_folder.pack(side=tk.RIGHT, padx=5, pady=2)
        
        # Console Log ScrolledText Frame
        console_frame = ttk.Frame(right_pane, padding=5)
        console_frame.pack(fill=tk.BOTH, expand=True)
        
        console_header = ttk.Frame(console_frame)
        console_header.pack(fill=tk.X, pady=(0, 2))
        
        ttk.Label(console_header, text="Real-time Traffic Logger (Consolas Monospace):", font=self.bold_font).pack(side=tk.LEFT)
        
        btn_clear_log = ttk.Button(console_header, text="Clear Logs", command=self.action_clear_logs)
        btn_clear_log.pack(side=tk.RIGHT, padx=2)
        
        self.log_text = ScrolledText(console_frame, font=self.console_font, background="#1e222b", foreground="#abb2bf", insertbackground="#ffffff")
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Console logger tags setup for coloring
        self.log_text.tag_config("TX", foreground="#61afef", font=("Consolas", 10, "bold"))      # Light Blue
        self.log_text.tag_config("RX", foreground="#98c379", font=("Consolas", 10, "bold"))      # Light Green
        self.log_text.tag_config("ERROR", foreground="#e06c75", font=("Consolas", 10, "bold"))   # Light Red
        self.log_text.tag_config("SYSTEM", foreground="#d19a66")  # Orange

    def build_list_sender_tab(self):
        # Treeview grid for sequence list send
        grid_frame = ttk.Frame(self.tab_list_send, padding=10)
        grid_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(grid_frame, text="Sequence List Sender (列表发送):", font=self.bold_font).pack(anchor=tk.W, pady=(0, 5))
        
        columns = ("Index", "Status", "ID(0x)", "Protocol", "Length", "Name", "Data", "Type", "Format", "Interval(ms)")
        self.tree_list = ttk.Treeview(grid_frame, columns=columns, show="headings", height=15)
        self.tree_list.pack(fill=tk.BOTH, expand=True)
        
        # Setup Column headings & sizes
        col_widths = {
            "Index": 50, "Status": 80, "ID(0x)": 80, "Protocol": 100, 
            "Length": 60, "Name": 120, "Data": 220, "Type": 80, 
            "Format": 80, "Interval(ms)": 90
        }
        for col in columns:
            self.tree_list.heading(col, text=col)
            self.tree_list.column(col, width=col_widths[col], anchor=tk.CENTER)
            
        # Default entries matching the User attachment
        self.tree_list.insert("", tk.END, values=("0", "Ready", "251", "CANFD_BRS", "8", "写flash", "01 11 22 33 44 55 66 77", "标准帧", "数据帧", "10"))
        self.tree_list.insert("", tk.END, values=("1", "Ready", "251", "CANFD_BRS", "8", "读flash", "02 11 22 33 44 55 66 77", "标准帧", "数据帧", "10"))
        
        # Bottom controls for list send
        ctrl_frame = ttk.LabelFrame(self.tab_list_send, text=" Transmission Mode Parameters ", padding=10)
        ctrl_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=10)
        
        flex_layout = ttk.Frame(ctrl_frame)
        flex_layout.pack(fill=tk.X)
        
        # Transmit mode dropdown
        ttk.Label(flex_layout, text="Send Mode:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.combo_list_mode = ttk.Combobox(flex_layout, values=["Sequential (顺序发送模式)", "Simultaneous (同时发送)"], width=20, state="readonly")
        self.combo_list_mode.set("Sequential (顺序发送模式)")
        self.combo_list_mode.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        
        # Failure Action dropdown
        ttk.Label(flex_layout, text="On Failure:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.combo_list_fail = ttk.Combobox(flex_layout, values=["Stop on Failure (失败停止)", "Continue (忽略继续)"], width=20, state="readonly")
        self.combo_list_fail.set("Stop on Failure (失败停止)")
        self.combo_list_fail.grid(row=0, column=3, padx=5, pady=5, sticky=tk.W)
        
        # List Cycles
        ttk.Label(flex_layout, text="Cycles:").grid(row=0, column=4, padx=5, pady=5, sticky=tk.W)
        self.ent_list_cycles = ttk.Entry(flex_layout, width=8)
        self.ent_list_cycles.insert(0, "1")
        self.ent_list_cycles.grid(row=0, column=5, padx=5, pady=5, sticky=tk.W)
        
        # Global Send Interval
        ttk.Label(flex_layout, text="Send Speed:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.combo_list_speed = ttk.Combobox(flex_layout, values=["1x (1倍速度)", "2x (2倍速度)"], width=15, state="readonly")
        self.combo_list_speed.set("1x (1倍速度)")
        self.combo_list_speed.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        
        ttk.Label(flex_layout, text="Send Gap (ms):").grid(row=1, column=2, padx=5, pady=5, sticky=tk.W)
        self.ent_list_gap = ttk.Entry(flex_layout, width=8)
        self.ent_list_gap.insert(0, "0")
        self.ent_list_gap.grid(row=1, column=3, padx=5, pady=5, sticky=tk.W)
        
        # Big list send execute trigger button
        self.btn_list_send = ttk.Button(flex_layout, text=" Start List Transmission (列表发送) ", style="Action.TButton", command=self.action_list_send, state=tk.DISABLED)
        self.btn_list_send.grid(row=0, column=6, rowspan=2, padx=25, pady=5, sticky=tk.NSEW)

    # ================= ZLGCAN DLL Engine Control Handlers =================
    def load_zlgcan_library(self):
        if not DLL_AVAILABLE:
            self.write_sys_log("[ERROR] ZLGCAN driver library 'zlgcan.dll' not found in path! Please inspect installation folder.", "ERROR")
            messagebox.showerror("Driver Missing", "ZLGCAN DLL library could not be loaded. Please ensure the drivers are installed.")
            return
        
        self.write_sys_log(f"[SYSTEM] Drivers loaded from path: {zlgcan_real_dir}", "SYSTEM")
        try:
            self.zcanlib = ZCAN()
            self.write_sys_log("[SYSTEM] ZCAN engine initialized successfully. Ready to open hardware device.", "SYSTEM")
        except Exception as e:
            self.write_sys_log(f"[ERROR] Exception during ZCAN engine instantiation: {e}", "ERROR")

    def action_open_device(self):
        if not DLL_AVAILABLE:
            messagebox.showerror("Error", "ZLGCAN driver is unavailable.")
            return
            
        self.write_sys_log("[SYSTEM] Attempting to open USBCANFD-200U device...", "SYSTEM")
        dev_idx = int(self.dev_idx_spin.get())
        
        self.device_handle = self.zcanlib.OpenDevice(ZCAN_USBCANFD_200U, dev_idx, 0)
        if self.device_handle == INVALID_DEVICE_HANDLE:
            self.write_sys_log("[ERROR] Open Device failed! Device might be occupied by ZCanPro software or disconnected.", "ERROR")
            messagebox.showerror("Connection Failed", "Unable to open device. Ensure it is connected and not occupied by other software.")
            return
            
        self.write_sys_log(f"[SYSTEM] Device opened successfully. Handle: {self.device_handle}", "SYSTEM")
        
        # Retrieve device parameters
        info = self.zcanlib.GetDeviceInf(self.device_handle)
        if info:
            self.write_sys_log(f"[SYSTEM] Hardware: {info.hw_type.strip()} | Firm: {info.fw_version} | SN: {info.serial}", "SYSTEM")
        
        # Modify visual status to Connected
        self.status_lbl.config(text="● CONNECTED", fg="#68d391")
        self.status_led.itemconfig(self.led_circle, fill="#2ecc71")
        
        # Toggle buttons
        self.btn_connect.config(state=tk.DISABLED)
        self.btn_disconnect.config(state=tk.NORMAL)
        self.btn_start_chn.config(state=tk.NORMAL)

    def action_close_device(self):
        # Stop listening/logging first
        if self.is_listening:
            self.action_toggle_listen()
            
        if self.device_handle != INVALID_DEVICE_HANDLE:
            # Stop channels if active
            self.action_reset_channels()
            
            self.write_sys_log("[SYSTEM] Closing ZLGCAN device connection...", "SYSTEM")
            ret = self.zcanlib.CloseDevice(self.device_handle)
            if ret == 1:
                self.write_sys_log("[SYSTEM] Device connection closed successfully.", "SYSTEM")
            else:
                self.write_sys_log("[ERROR] Device Close returned failure.", "ERROR")
            self.device_handle = INVALID_DEVICE_HANDLE
            
        # Modify visual status to Disconnected
        self.status_lbl.config(text="● DISCONNECTED", fg="#fc8181")
        self.status_led.itemconfig(self.led_circle, fill="#e74c3c")
        
        # Toggle buttons
        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.DISABLED)
        self.btn_start_chn.config(state=tk.DISABLED)
        self.btn_stop_chn.config(state=tk.DISABLED)
        self.disable_sending_buttons()

    def action_start_channels(self):
        if self.device_handle == INVALID_DEVICE_HANDLE:
            return
            
        self.write_sys_log("[SYSTEM] Initializing and configuring Channels...", "SYSTEM")
        self.chn_handles = []
        
        # Get active channel numbers
        info = self.zcanlib.GetDeviceInf(self.device_handle)
        chn_count = info.can_num if info else 2
        
        nom_baud = self.nom_baud_combo.get()
        data_baud = self.data_baud_combo.get()
        res_val = "1" if self.res_var.get() else "0"
        
        for chn in range(chn_count):
            self.write_sys_log(f"[SYSTEM] Configuring CH{chn}... standard=ISO, abit={nom_baud}, dbit={data_baud}, resistance={res_val}", "SYSTEM")
            
            # 1. standard CANFD ISO configuration (0 = ISO, 1 = Non-ISO)
            self.zcanlib.ZCAN_SetValue(self.device_handle, str(chn) + "/canfd_standard", "0".encode("utf-8"))
            # 2. Baudrates
            self.zcanlib.ZCAN_SetValue(self.device_handle, str(chn) + "/canfd_abit_baud_rate", nom_baud.encode("utf-8"))
            self.zcanlib.ZCAN_SetValue(self.device_handle, str(chn) + "/canfd_dbit_baud_rate", data_baud.encode("utf-8"))
            # 3. Terminal resistor
            self.zcanlib.ZCAN_SetValue(self.device_handle, str(chn) + "/initenal_resistance", res_val.encode("utf-8"))
            # 4. Enable TX echo back to log both TX and RX frames
            self.zcanlib.ZCAN_SetValue(self.device_handle, str(chn) + "/set_device_tx_echo", "1".encode("utf-8"))
            
            # Setup channel init struct
            init_cfg = ZCAN_CHANNEL_INIT_CONFIG()
            init_cfg.can_type = ZCAN_TYPE_CANFD
            init_cfg.config.canfd.mode = 0  # normal mode
            
            chn_handle = self.zcanlib.InitCAN(self.device_handle, chn, init_cfg)
            if chn_handle is None:
                self.write_sys_log(f"[ERROR] Failed to initialize CH{chn}", "ERROR")
                messagebox.showerror("Error", f"Failed to initialize CH{chn}")
                return
                
            # Start channel
            ret = self.zcanlib.StartCAN(chn_handle)
            if ret != ZCAN_STATUS_OK:
                self.write_sys_log(f"[ERROR] Failed to start CH{chn}", "ERROR")
                messagebox.showerror("Error", f"Failed to start CH{chn}")
                return
                
            self.chn_handles.append(chn_handle)
            self.write_sys_log(f"[SYSTEM] CH{chn} started. Handle: {chn_handle}", "SYSTEM")
            
        self.status_lbl.config(text="● RUNNING", fg="#48bb78")
        self.status_led.itemconfig(self.led_circle, fill="#48bb78")
        
        self.btn_start_chn.config(state=tk.DISABLED)
        self.btn_stop_chn.config(state=tk.NORMAL)
        self.btn_toggle_listen.config(state=tk.NORMAL)
        self.enable_sending_buttons()
        
        # Automatically toggle Listening ON upon start
        if not self.is_listening:
            self.action_toggle_listen()

    def action_reset_channels(self):
        if self.is_listening:
            self.action_toggle_listen()
            
        if self.chn_handles:
            self.write_sys_log("[SYSTEM] Resetting all CANFD channels...", "SYSTEM")
            for i, chn_handle in enumerate(self.chn_handles):
                ret = self.zcanlib.ResetCAN(chn_handle)
                if ret == 1:
                    self.write_sys_log(f"[SYSTEM] CH{i} reset successfully.", "SYSTEM")
            self.chn_handles = []
            
        self.status_lbl.config(text="● CONNECTED", fg="#68d391")
        self.status_led.itemconfig(self.led_circle, fill="#2ecc71")
        
        self.btn_start_chn.config(state=tk.NORMAL)
        self.btn_stop_chn.config(state=tk.DISABLED)
        self.btn_toggle_listen.config(state=tk.DISABLED)
        self.disable_sending_buttons()

    def enable_sending_buttons(self):
        self.btn_tx_write.config(state=tk.NORMAL)
        self.btn_tx_read.config(state=tk.NORMAL)
        self.btn_tx_seq.config(state=tk.NORMAL)
        self.btn_send_custom.config(state=tk.NORMAL)
        self.btn_list_send.config(state=tk.NORMAL)

    def disable_sending_buttons(self):
        self.btn_tx_write.config(state=tk.DISABLED)
        self.btn_tx_read.config(state=tk.DISABLED)
        self.btn_tx_seq.config(state=tk.DISABLED)
        self.btn_send_custom.config(state=tk.DISABLED)
        self.btn_list_send.config(state=tk.DISABLED)

    # ================= Thread-Safe Live Listening (RX) Handlers =================
    def action_toggle_listen(self):
        if self.is_listening:
            # STOP listening
            self.is_listening = False
            self.thread_flag = False
            
            # Safely join background receive threads to ensure they exit completely
            if hasattr(self, 'rx_threads'):
                for t in self.rx_threads:
                    if t.is_alive():
                        t.join(timeout=0.5)
                self.rx_threads = []
                
            self.btn_toggle_listen.config(text=" Start Real-time Listening (实时监听) ")
            self.write_sys_log("[SYSTEM] Listening thread stopped.", "SYSTEM")
        else:
            # START listening
            if not self.chn_handles:
                messagebox.showwarning("Warning", "Channels are not started!")
                return
            self.is_listening = True
            self.thread_flag = True
            self.btn_toggle_listen.config(text=" Stop Real-time Listening (停止监听) ")
            
            # Start background receive threads
            self.rx_threads = []
            for i, chn_handle in enumerate(self.chn_handles):
                t = threading.Thread(target=self.rx_worker_thread, args=(chn_handle, i), daemon=True)
                self.rx_threads.append(t)
                t.start()
            
            self.write_sys_log("[SYSTEM] Background listening threads spawned.", "SYSTEM")

    def rx_worker_thread(self, chn_handle, chn_idx):
        while self.thread_flag:
            time.sleep(0.005)
            
            # Probing CAN packets
            rcv_num = self.zcanlib.GetReceiveNum(chn_handle, ZCAN_TYPE_CAN)
            if rcv_num and self.thread_flag:
                msgs, rcv_num = self.zcanlib.Receive(chn_handle, min(rcv_num, 100), 100)
                for msg in msgs[:rcv_num]:
                    self.parse_and_enqueue_frame(msg, "CAN", chn_idx)
                    
            # Probing CANFD packets
            rcv_canfd_num = self.zcanlib.GetReceiveNum(chn_handle, ZCAN_TYPE_CANFD)
            if rcv_canfd_num and self.thread_flag:
                msgs_fd, rcv_canfd_num = self.zcanlib.ReceiveFD(chn_handle, min(rcv_canfd_num, 100), 100)
                for msg in msgs_fd[:rcv_canfd_num]:
                    self.parse_and_enqueue_frame(msg, "CANFD", chn_idx)

    def parse_and_enqueue_frame(self, msg, protocol, chn_idx):
        frame = msg.frame
        
        # Check TX/RX direction based on frame tags
        if protocol == "CAN":
            direction = "TX" if frame._pad & 0x20 else "RX"
            frame_type = "Extended" if frame.can_id & (1 << 31) else "Standard"
            frame_format = "Remote" if frame.can_id & (1 << 30) else "Data"
            can_id = frame.can_id & 0x1FFFFFFF
            dlc = frame.can_dlc
            data_bytes = frame.data[:dlc]
        else:  # CANFD
            direction = "TX" if frame.flags & 0x20 else "RX"
            frame_type = "Extended" if frame.can_id & (1 << 31) else "Standard"
            frame_format = "Data"  # CANFD has no remote frame
            can_id = frame.can_id & 0x1FFFFFFF
            dlc = frame.len
            data_bytes = frame.data[:dlc]
            if frame.flags & 0x1:
                protocol = "CANFD_BRS"
                
        # Format values for display/CSV
        timestamp_str = f"{msg.timestamp:.6f}" if hasattr(msg, "timestamp") else f"{time.time():.4f}"
        can_id_str = f"{can_id:X}"
        data_str = " ".join([f"{num:02X}" for num in data_bytes])
        
        log_line = f"[{timestamp_str}] CH{chn_idx} | {protocol:<9} | {direction} | ID: {can_id_str:<4} | DLC: {dlc:<2} | Data: {data_str}"
        
        # Push to GUI ScrolledText queue
        self.gui_queue.put((direction, log_line))
        
        # Push to CSV recorder directly
        if self.is_logging:
            self.csv_recorder.write([timestamp_str, f"CH{chn_idx}", protocol, direction, f"0x{can_id_str}", frame_type, frame_format, dlc, data_str])

    # ================= Decoupled CSV Logging Handlers =================
    def action_toggle_logging(self):
        if self.is_logging:
            # Currently logging, so STOP it
            self.stop_csv_logging()
        else:
            # Not logging, so START it
            default_name = datetime.now().strftime("CAN_Record_%Y%m%d_%H%M%S.csv")
            save_dir = os.path.join(script_dir, "pz_test_data")
            os.makedirs(save_dir, exist_ok=True)
            
            filepath = filedialog.asksaveasfilename(
                initialdir=save_dir,
                initialfile=default_name,
                title="Select CSV Save Location",
                filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
                defaultextension=".csv"
            )
            if not filepath:
                return  # User clicked cancel
                
            self.start_csv_logging(filepath)

    def start_csv_logging(self, filepath=None):
        path = self.csv_recorder.start(filepath)
        self.is_logging = True
        self.btn_toggle_csv.config(text=" Stop CSV Recording (停止保存CSV) ")
        self.write_sys_log(f"[SYSTEM] CSV Dynamic Recording enabled. Saving to: {path}", "SYSTEM")

    def stop_csv_logging(self):
        self.is_logging = False
        path = self.csv_recorder.stop()
        self.btn_toggle_csv.config(text=" Start CSV Recording (保存CSV) ")
        if path:
            self.write_sys_log(f"[SYSTEM] CSV Dynamic Recording stopped. Saved to: {path}", "SYSTEM")

    def action_open_csv_folder(self):
        save_dir = os.path.join(script_dir, "pz_test_data")
        os.makedirs(save_dir, exist_ok=True)
        os.startfile(save_dir)
        self.write_sys_log(f"[SYSTEM] Directory opened in Explorer: {save_dir}", "SYSTEM")

    # ================= Decoupled Command Transmit (TX) Handlers =================
    def transmit_frame(self, chn_idx, id_val, dlc, protocol, data_bytes):
        if self.device_handle == INVALID_DEVICE_HANDLE or not self.chn_handles:
            messagebox.showerror("Error", "Device or Channel is not running!")
            return False
            
        chn_handle = self.chn_handles[chn_idx]
        
        if protocol in ["CANFD", "CANFD_BRS"]:
            msg = ZCAN_TransmitFD_Data()
            msg.transmit_type = 0
            msg.frame.can_id = id_val
            msg.frame.len = dlc
            # flags: bit5 = Tx echo, bit0 = BRS Acceleration
            msg.frame.flags = 0x20
            if protocol == "CANFD_BRS":
                msg.frame.flags |= 0x1
                
            for j in range(min(dlc, len(data_bytes))):
                msg.frame.data[j] = data_bytes[j]
                
            ret = self.zcanlib.TransmitFD(chn_handle, msg, 1)
        else:  # CAN Standard
            msg = ZCAN_Transmit_Data()
            msg.transmit_type = 0
            msg.frame.can_id = id_val
            msg.frame.can_dlc = dlc
            msg.frame._pad = 0x20  # TX echo back
            
            for j in range(min(dlc, len(data_bytes))):
                msg.frame.data[j] = data_bytes[j]
                
            ret = self.zcanlib.Transmit(chn_handle, msg, 1)
            
        return ret == 1

    def action_send_write_flash(self):
        self.write_sys_log("[TX] Sending command: [写flash] ...", "TX")
        success = self.transmit_frame(0, 0x251, 8, "CANFD_BRS", [0x01, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77])
        if success:
            self.write_sys_log("[TX] Command [写flash] successfully transmitted.", "TX")
        else:
            self.write_sys_log("[ERROR] Command [写flash] transmission failed!", "ERROR")

    def action_send_read_flash(self):
        self.write_sys_log("[TX] Sending command: [读flash] ...", "TX")
        success = self.transmit_frame(0, 0x251, 8, "CANFD_BRS", [0x02, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77])
        if success:
            self.write_sys_log("[TX] Command [读flash] successfully transmitted.", "TX")
        else:
            self.write_sys_log("[ERROR] Command [读flash] transmission failed!", "ERROR")

    def action_send_sequential(self):
        # Sequential transmitting matching user screenshot: stop on failure, 0ms gap, 1x speed
        self.write_sys_log("[SYSTEM] Starting sequential preset sending [写flash -> 读flash] (Stop on Failure, Gap: 0ms)...", "SYSTEM")
        
        # 1. Write Flash
        self.write_sys_log("[TX] Step 1/2: Transmitting [写flash]...", "TX")
        success = self.transmit_frame(0, 0x251, 8, "CANFD_BRS", [0x01, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77])
        if not success:
            self.write_sys_log("[ERROR] Step 1 [写flash] failed! Sequential sending aborted.", "ERROR")
            return
        self.write_sys_log("[TX] Step 1 [写flash] succeeded.", "TX")
        
        # 0ms interval gap
        
        # 2. Read Flash
        self.write_sys_log("[TX] Step 2/2: Transmitting [读flash]...", "TX")
        success = self.transmit_frame(0, 0x251, 8, "CANFD_BRS", [0x02, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77])
        if not success:
            self.write_sys_log("[ERROR] Step 2 [读flash] failed! Transmitting aborted.", "ERROR")
            return
        self.write_sys_log("[TX] Step 2 [读flash] succeeded. Sequential preset transmitting finished.", "TX")

    def action_send_custom(self):
        try:
            id_val = int(self.ent_tx_id.get(), 16)
        except ValueError:
            messagebox.showerror("Error", "Invalid Hex Frame ID!")
            return
            
        try:
            dlc = int(self.tx_dlc_spin.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid DLC!")
            return
            
        proto = self.tx_proto_combo.get()
        
        data_str = self.ent_tx_data.get().strip()
        try:
            data_bytes = [int(x, 16) for x in data_str.split()]
        except ValueError:
            messagebox.showerror("Error", "Invalid Hex data format! Use space separated bytes, e.g. 00 11 22")
            return
            
        self.write_sys_log(f"[TX] Transmitting custom frame ID: {id_val:X} | Protocol: {proto}...", "TX")
        success = self.transmit_frame(0, id_val, dlc, proto, data_bytes)
        if success:
            self.write_sys_log("[TX] Custom frame sent successfully.", "TX")
        else:
            self.write_sys_log("[ERROR] Custom frame transmission failed!", "ERROR")

    # ================= Tab 2: Professional List Sender Logic =================
    def action_list_send(self):
        if self.list_send_active:
            # STOP active list send
            self.list_send_active = False
            self.btn_list_send.config(text=" Start List Transmission (列表发送) ")
            self.write_sys_log("[SYSTEM] List send terminated by user.", "SYSTEM")
        else:
            # START list send in background thread to keep GUI fully responsive
            cycles_str = self.ent_list_cycles.get().strip()
            gap_str = self.ent_list_gap.get().strip()
            try:
                cycles = int(cycles_str)
                gap_ms = int(gap_str)
            except ValueError:
                messagebox.showerror("Error", "Invalid cycles or gap values!")
                return
                
            self.list_send_active = True
            self.btn_list_send.config(text=" Stop Transmission (停止列表发送) ")
            
            t = threading.Thread(target=self.list_send_worker, args=(cycles, gap_ms), daemon=True)
            t.start()

    def list_send_worker(self, cycles, global_gap_ms):
        self.write_sys_log(f"[SYSTEM] List Send Thread initiated. Cycles: {cycles} | Gap: {global_gap_ms}ms...", "SYSTEM")
        
        # Read parameters
        fail_stop = self.combo_list_fail.get() == "Stop on Failure (失败停止)"
        
        for cycle in range(cycles):
            if not self.list_send_active:
                break
                
            self.write_sys_log(f"[SYSTEM] >>> Starting List Send Cycle {cycle + 1}/{cycles} <<<", "SYSTEM")
            
            # Fetch all list rows from Treeview
            items = self.tree_list.get_children()
            
            for item_idx, item in enumerate(items):
                if not self.list_send_active:
                    break
                    
                values = self.tree_list.item(item, "values")
                name = values[5]
                id_hex = values[2]
                proto = values[3]
                dlc = int(values[4])
                data_hex = values[6]
                row_gap = int(values[9])
                
                # Update status in treeview
                self.tree_list.item(item, values=(values[0], "Sending...", id_hex, proto, dlc, name, data_hex, values[7], values[8], row_gap))
                self.write_sys_log(f"[TX] [Cycle {cycle+1}] Transmitting: {name} (ID: {id_hex}, Data: {data_hex})...", "TX")
                
                # Parse data
                try:
                    data_bytes = [int(x, 16) for x in data_hex.split()]
                    id_val = int(id_hex, 16)
                except Exception as e:
                    self.write_sys_log(f"[ERROR] Failed parsing command data row {item_idx}: {e}", "ERROR")
                    self.tree_list.item(item, values=(values[0], "Parse Err", id_hex, proto, dlc, name, data_hex, values[7], values[8], row_gap))
                    continue
                    
                # Transmit
                success = self.transmit_frame(0, id_val, dlc, proto, data_bytes)
                
                if success:
                    self.tree_list.item(item, values=(values[0], "Success", id_hex, proto, dlc, name, data_hex, values[7], values[8], row_gap))
                    self.write_sys_log(f"[TX] Transmission of '{name}' succeeded.", "TX")
                else:
                    self.tree_list.item(item, values=(values[0], "Failed", id_hex, proto, dlc, name, data_hex, values[7], values[8], row_gap))
                    self.write_sys_log(f"[ERROR] Transmission of '{name}' failed!", "ERROR")
                    
                    if fail_stop:
                        self.write_sys_log("[ERROR] 'Stop on Failure' is active. Aborting sequential list send cycle.", "ERROR")
                        self.list_send_active = False
                        self.btn_list_send.config(text=" Start List Transmission (列表发送) ")
                        return
                
                # Wait item interval + global gap
                total_sleep = (row_gap + global_gap_ms) / 1000.0
                if total_sleep > 0:
                    time.sleep(total_sleep)
                    
        self.list_send_active = False
        self.btn_list_send.config(text=" Start List Transmission (列表发送) ")
        self.write_sys_log("[SYSTEM] List Send execution complete.", "SYSTEM")

    # ================= UI & Logging Utilities =================
    def write_sys_log(self, text, log_type="SYSTEM"):
        # Post logging work to thread safe queue
        self.gui_queue.put((log_type, text))

    def append_log(self, log_type, text):
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted_text = f"[{now}] {text}\n"
        self.log_text.insert(tk.END, formatted_text, log_type)
        self.log_text.see(tk.END)

    def action_clear_logs(self):
        self.log_text.delete("1.0", tk.END)
        self.write_sys_log("[SYSTEM] Console log window cleared.", "SYSTEM")

    # ================= Thread Polling Routines =================
    def poll_queues(self):
        # Process items in the GUI queue, up to 50 items per cycle to prevent freezing
        processed = 0
        inserted_any = False
        
        while processed < 50 and not self.gui_queue.empty():
            try:
                log_type, text = self.gui_queue.get_nowait()
                now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                formatted_text = f"[{now}] {text}\n"
                self.log_text.insert(tk.END, formatted_text, log_type)
                processed += 1
                inserted_any = True
            except queue.Empty:
                break
                
        if inserted_any:
            # Scroll to the end once at the end of the batch
            self.log_text.see(tk.END)
            
            # Limit text lines to prevent RAM exhaustion
            current_lines = int(self.log_text.index('end-1c').split('.')[0])
            if current_lines > 2000:
                self.log_text.delete("1.0", f"{current_lines - 1800}.0")
                
        self.root.after(50, self.poll_queues)

    def on_close(self):
        # Safe exit cleanup
        self.thread_flag = False
        self.is_listening = False
        self.list_send_active = False
        
        self.stop_csv_logging()
        self.action_close_device()
        self.root.destroy()

# ================= Application Boot Entry Point =================
if __name__ == "__main__":
    root = tk.Tk()
    app = ZCanProGuiApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
