"""
ZLG CANFD-200U 实时硬件采集控制器
参考 ft_electrical_parameter/main/main_controller_simple.py 对 zlgcan_file 的调用模式
支持非阻塞子进程采集、平稳停止、最新文件提取与自动归档
"""

import os
import sys
import time
import shutil
import threading
import subprocess
from typing import Optional, Callable, Tuple, List


class CanCaptureError(Exception):
    """CAN 数据采集异常"""
    pass


class ZLGCanCollector:
    """
    ZLG CANFD-200U 硬件数据采集管理引擎
    """

    def __init__(self, zlgcan_dir: Optional[str] = None):
        self.zlgcan_dir = zlgcan_dir or self._find_zlgcan_dir()
        self.canfd_script = os.path.join(self.zlgcan_dir, "zcanpro_canfd200u.py")
        self.data_folder = os.path.join(self.zlgcan_dir, "pz_test_data")
        self.python_exe = sys.executable
        self.stop_event = threading.Event()
        self.current_proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    @classmethod
    def _find_zlgcan_dir(cls) -> str:
        """多路径自适应探测 zlgcan_file 目录"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        workspace_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))

        candidates = [
            os.path.join(workspace_root, "zlgcan_file"),
            os.path.abspath(os.path.join(current_dir, "..", "..", "..", "zlgcan_file")),
            r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file",
            os.path.abspath(os.path.join(current_dir, "..", "..", "zlgcan_file")),
            os.path.abspath(os.path.join(current_dir, "..", "zlgcan_file")),
        ]

        for c in candidates:
            if os.path.isdir(c) and os.path.exists(os.path.join(c, "zcanpro_canfd200u.py")):
                return c

        return candidates[0]

    def is_available(self) -> Tuple[bool, str]:
        """检查采集驱动与脚本是否就绪"""
        if not os.path.isdir(self.zlgcan_dir):
            return False, f"未找到 zlgcan_file 驱动目录: {self.zlgcan_dir}"
        if not os.path.isfile(self.canfd_script):
            return False, f"未找到采集脚本: {self.canfd_script}"
        return True, "ZLG 驱动与脚本已就绪"

    @staticmethod
    def _safe_send_stop(proc: Optional[subprocess.Popen]):
        """安全向子进程发送停止指令，避免重复关闭管道产生异常"""
        if proc and proc.poll() is None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    try:
                        proc.stdin.write(b"\r\n")
                    except TypeError:
                        proc.stdin.write("\r\n")
                    proc.stdin.flush()
                    proc.stdin.close()
            except Exception:
                pass

    def stop_capture(self):
        """发送停止采集信号，通知采集子进程平稳落盘并释放硬件资源"""
        self.stop_event.set()
        with self._lock:
            self._safe_send_stop(self.current_proc)

    def cleanup(self):
        """强制释放并清理任何残留的 CAN 采集子进程，防止 USB 硬件独占"""
        self.stop_event.set()
        with self._lock:
            if self.current_proc:
                if self.current_proc.poll() is None:
                    self._safe_send_stop(self.current_proc)
                    try:
                        self.current_proc.wait(timeout=2.0)
                    except Exception:
                        try:
                            self.current_proc.kill()
                            self.current_proc.wait(timeout=0.5)
                        except Exception:
                            pass
                self.current_proc = None

        # 终结系统中任何由于异常退出残留的 zcanpro_canfd200u 孤儿进程
        if sys.platform == "win32":
            try:
                ps_cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like \'*zcanpro_canfd200u*\' -and $_.Name -eq \'python.exe\' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"'
                subprocess.run(ps_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            except Exception:
                pass

    def close_device(self) -> Tuple[bool, str]:
        """关闭 CAN 盒设备并释放句柄"""
        try:
            self.cleanup()
            return True, "CAN 盒设备已成功关闭，USB 通道已彻底释放"
        except Exception as e:
            return False, f"关闭 CAN 盒时发生异常: {e}"

    def open_device(self) -> Tuple[bool, str]:
        """探测并测试打开 CAN 盒设备"""
        is_ok, msg = self.is_available()
        if not is_ok:
            return False, msg
        # 确保之前没有残留占用
        self.cleanup()
        return True, "USBCANFD-200U 设备检测就绪，可随时开启采集"

    def get_latest_csv(self, after_timestamp: Optional[float] = None) -> Optional[str]:
        """
        从 pz_test_data 文件夹中获取最新的 CSV 记录文件
        """
        if not os.path.exists(self.data_folder):
            return None

        files = [
            os.path.join(self.data_folder, f)
            for f in os.listdir(self.data_folder)
            if f.lower().endswith(".csv")
        ]
        if not files:
            return None

        if after_timestamp is not None:
            valid_files = [f for f in files if os.path.getmtime(f) >= (after_timestamp - 2.0)]
            if valid_files:
                return max(valid_files, key=os.path.getmtime)
            latest = max(files, key=os.path.getmtime)
            if os.path.getmtime(latest) >= (after_timestamp - 5.0):
                return latest
            return None

        return max(files, key=os.path.getmtime)

    def capture(
        self,
        duration_sec: Optional[float] = None,
        target_dir: Optional[str] = None,
        target_filename: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """
        执行一次 CANFD 硬件实时采集 (支持人工点击停止与异常预警)
        
        :param duration_sec: 最大采集持续时长（秒，若为 None 或 <=0 则一直采直到手动停止）
        :param target_dir: 目标归档保存目录（可选）
        :param target_filename: 目标保存文件名（可选）
        :param log_callback: 文本日志回调函数
        :param progress_callback: 进度回调函数 (已采集秒数, 目标参考秒数)
        :return: 最终生成的 CSV 文件完整绝对路径
        """
        is_ok, msg = self.is_available()
        if not is_ok:
            raise CanCaptureError(msg)

        # 启动前清理任何可能残留的孤儿进程
        self.cleanup()
        self.stop_event.clear()

        def _log(text: str):
            if log_callback:
                try:
                    log_callback(text)
                except Exception:
                    pass

        max_dur_text = f"{duration_sec:.1f} 秒 (可随时点击手动停止)" if duration_sec and duration_sec > 0 else "无限制 (人工手动停止)"
        _log("\n=======================================================")
        _log("[*] 启动 ZLG CANFD-200U 硬件实时采集...")
        _log(f"[*] 驱动目录: {self.zlgcan_dir}")
        _log(f"[*] 采集脚本: {self.canfd_script}")
        _log(f"[*] 计划时长: {max_dur_text}")
        _log("[*] [操作指引]: 请在看到启动提示后，立即给转台/器件上电！")
        _log("=======================================================")

        capture_start_time = time.time()
        captured_output_lines = []

        # 构建子进程执行参数与目标落盘路径
        cmd = [self.python_exe, self.canfd_script]
        expected_csv_path = None
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
            if not target_filename:
                target_filename = f"CrashSensor_Capture_{int(time.time())}.csv"
            expected_csv_path = os.path.abspath(os.path.join(target_dir, target_filename))
            cmd.extend(["--output", expected_csv_path])

        # 辅助多编码自适应解码函数，彻底根绝 Windows 跨进程管道乱码
        def _decode_bytes(raw_bytes: bytes) -> str:
            for enc in ("utf-8", "gb18030", "gbk", "cp936"):
                try:
                    return raw_bytes.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw_bytes.decode("utf-8", errors="replace")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            # 以纯二进制管道模式启动 zcanpro_canfd200u.py 子进程，避免标准库在 Windows 下错误应用 cp936 解码
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                cwd=self.zlgcan_dir,
                env=env,
            )
            with self._lock:
                self.current_proc = proc
        except Exception as e:
            raise CanCaptureError(f"无法启动 CAN 采集子进程: {e}")

        # 启动后台读取线程捕获子进程输出
        def _read_stdout():
            try:
                for line_bytes in iter(proc.stdout.readline, b""):
                    clean_l = _decode_bytes(line_bytes).strip()
                    if clean_l:
                        captured_output_lines.append(clean_l)
                        # 实时转发所有有意义的日志给 GUI 日志视窗
                        _log(f" [CAN硬件] {clean_l}")
                proc.stdout.close()
            except Exception:
                pass

        reader_t = threading.Thread(target=_read_stdout, daemon=True)
        reader_t.start()

        # 实时循环监测，支持人工点击停止按钮
        ref_duration = float(duration_sec) if duration_sec and duration_sec > 0 else 60.0
        while not self.stop_event.is_set():
            time.sleep(0.2)
            elapsed = time.time() - capture_start_time
            if progress_callback:
                try:
                    progress_callback(int(elapsed), int(ref_duration))
                except Exception:
                    pass

            # 检查子进程是否提前退出了 (例如打不开硬件设备)
            if proc.poll() is not None:
                exit_code = proc.returncode
                reader_t.join(timeout=1)
                err_detail = "\n".join(captured_output_lines[-10:])
                raise CanCaptureError(
                    f"ZLG 采集进程在结束前异常终止 (退出码: {exit_code})！\n"
                    f"可能原因: USBCANFD 设备未连接、被其他上位机占用或驱动异常。\n"
                    f"硬件输出摘要:\n{err_detail}"
                )

            # 若设定了最大时长且已超时
            if duration_sec and duration_sec > 0 and elapsed >= duration_sec:
                _log(f"[*] 已达到预定最大采集时长 ({duration_sec:.1f}s)，自动停止采集。")
                break

        _log("[*] 正在向采集进程发送平稳停止信号并等待数据完全落盘...")

        with self._lock:
            self._safe_send_stop(proc)

        # 等待其 finally 流程执行完毕 (允许最多 10.0 秒供异步 CSV 写入线程写盘及硬件复位)
        if proc.poll() is None:
            try:
                proc.wait(timeout=10.0)
                _log(" [+] CAN 采集进程平稳终止，硬件资源与所有缓存数据已安全落盘释放。")
            except subprocess.TimeoutExpired:
                _log(" [!] 警告: CAN 采集进程清理超时 (10s)，正在强制终止...")
                proc.kill()
                proc.wait()

        with self._lock:
            self.current_proc = None

        reader_t.join(timeout=2)

        # 查找生成的 CSV 报文文件
        _log("[*] 正在核验落盘的原始 CANFD CSV 记录文件...")
        # 轮询等待片刻文件写盘
        latest_csv = None
        for _ in range(10):
            if expected_csv_path and os.path.exists(expected_csv_path) and os.path.getsize(expected_csv_path) > 0:
                latest_csv = expected_csv_path
                break
            time.sleep(0.2)

        if not latest_csv:
            if expected_csv_path and os.path.exists(expected_csv_path):
                latest_csv = expected_csv_path
            else:
                latest_csv = self.get_latest_csv(after_timestamp=capture_start_time)

        if not latest_csv or not os.path.exists(latest_csv):
            err_detail = "\n".join(captured_output_lines[-10:])
            raise CanCaptureError(
                f"未能检测到本次运行新生成的 CAN CSV 记录文件！\n"
                f"检查路径: {expected_csv_path or self.data_folder}\n"
                f"硬件输出摘要:\n{err_detail}"
            )

        # 【核心校验】：严格核验采集到的有效数据帧行数 (扣除表头)
        valid_row_count = 0
        try:
            import csv as py_csv
            with open(latest_csv, mode="r", encoding="utf-8", errors="ignore") as f:
                reader = py_csv.reader(f)
                _header = next(reader, None)
                for _ in reader:
                    valid_row_count += 1
        except Exception as read_err:
            _log(f" [!] 警告: 读取 CSV 行数校验时异常: {read_err}")

        file_size_kb = os.path.getsize(latest_csv) / 1024.0
        _log(f" [+] 成功获取原始采集数据: {os.path.abspath(latest_csv)} ({file_size_kb:.1f} KB, 有效数据帧: {valid_row_count} 帧)")

        if valid_row_count == 0:
            err_detail = "\n".join(captured_output_lines[-10:])
            raise CanCaptureError(
                f"【采集数据为空】本次采集到的 CAN 数据帧数量为 0 帧 (文件仅包含表头)！\n\n"
                f"排查建议：\n"
                f"1. 上电顺序：请确认先点击开始采集，再对转台/器件上电；\n"
                f"2. 物理线路：请检查 CAN_H / CAN_L 接线是否松动或未接 120 欧姆终端电阻；\n"
                f"3. 供电板状态：确认转台供电板 1~4 是否正常供电并在发送数据；\n"
                f"4. 硬件复位：可点击顶部的【关闭CAN盒】重新重置连接。\n"
                f"\n硬件输出日志摘要:\n{err_detail}"
            )

        # 若指定了目标存储目录且当前文件不在该目录中，复制并归档
        if target_dir and latest_csv != expected_csv_path:
            os.makedirs(target_dir, exist_ok=True)
            if not target_filename:
                target_filename = os.path.basename(latest_csv)
            final_path = os.path.join(target_dir, target_filename)
            shutil.copy(latest_csv, final_path)
            _log(f" [+] 原始数据已成功转存至目标目录: {final_path}")
            return os.path.abspath(final_path)

        return os.path.abspath(latest_csv)
