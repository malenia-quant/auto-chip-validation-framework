"""
单元测试：ZLG CANFD-200U 实时采集控制器测试 (test_can_collector.py)
"""

import os
import sys
import time
import pytest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(BASE_DIR, "data_processor"))

from processor.can_collector import ZLGCanCollector, CanCaptureError


def test_collector_initialization_and_path():
    collector = ZLGCanCollector()
    assert os.path.isdir(collector.zlgcan_dir), f"驱动目录不存在: {collector.zlgcan_dir}"
    assert os.path.isfile(collector.canfd_script), f"采集脚本不存在: {collector.canfd_script}"
    assert "zlgcan_file" in collector.zlgcan_dir.lower()

    is_ok, msg = collector.is_available()
    assert is_ok is True
    assert "就绪" in msg


def test_get_latest_csv_helper(tmp_path):
    test_data_dir = tmp_path / "pz_test_data"
    test_data_dir.mkdir()

    collector = ZLGCanCollector()
    collector.data_folder = str(test_data_dir)

    # 初始为空
    assert collector.get_latest_csv() is None

    # 创建第一个文件
    f1 = test_data_dir / "CAN_Record_20260907_120000.csv"
    f1.write_text("header1,header2\n")
    time.sleep(0.05)

    # 创建第二个更新的文件
    t2 = time.time()
    f2 = test_data_dir / "CAN_Record_20260907_120005.csv"
    f2.write_text("header1,header2\n")

    latest = collector.get_latest_csv()
    assert latest is not None
    assert os.path.basename(latest) == "CAN_Record_20260907_120005.csv"

    # 按时间戳过滤
    latest_filtered = collector.get_latest_csv(after_timestamp=t2 - 1.0)
    assert latest_filtered is not None
    assert os.path.basename(latest_filtered) == "CAN_Record_20260907_120005.csv"


def test_capture_error_when_unavailable():
    collector = ZLGCanCollector(zlgcan_dir=r"d:\invalid_nonexistent_path")
    with pytest.raises(CanCaptureError) as exc_info:
        collector.capture(duration_sec=1.0)
    assert "未找到 zlgcan_file" in str(exc_info.value)


def test_collector_open_and_close_device():
    collector = ZLGCanCollector()
    is_open, msg_open = collector.open_device()
    assert is_open is True
    assert "USBCANFD-200U" in msg_open

    is_close, msg_close = collector.close_device()
    assert is_close is True
    assert "已成功关闭" in msg_close


def test_collector_stop_capture():
    collector = ZLGCanCollector()
    collector.stop_capture()
    assert collector.stop_event.is_set()


def test_empty_csv_zero_row_detection(tmp_path):
    # 测试只有表头没有数据行的 CSV
    empty_csv = tmp_path / "empty_run.csv"
    empty_csv.write_text("ID,Data_Hex,Timestamp\n", encoding="utf-8")

    import csv as py_csv
    valid_row_count = 0
    with open(empty_csv, mode="r", encoding="utf-8", errors="ignore") as f:
        reader = py_csv.reader(f)
        _header = next(reader, None)
        for _ in reader:
            valid_row_count += 1

    assert valid_row_count == 0


def test_collector_start_capture_process_env_defined(tmp_path):
    from unittest.mock import MagicMock, patch
    collector = ZLGCanCollector()
    mock_proc = MagicMock()
    mock_proc.stdout.readline.return_value = b""
    mock_proc.poll.side_effect = [None, 0, 0, 0]
    dummy_csv = tmp_path / "CrashSensor_Capture_test.csv"
    dummy_csv.write_text("ID,Data_Hex,Timestamp\n1,2,3\n", encoding="utf-8")

    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch.object(collector, "get_latest_csv", return_value=str(dummy_csv)):
        collector.capture(duration_sec=0.1, target_dir=str(tmp_path), target_filename="CrashSensor_Capture_test.csv")
        assert mock_popen.call_count >= 1
        call_kwargs = mock_popen.call_args_list[-1][1]
        assert "env" in call_kwargs
        assert call_kwargs["env"]["PYTHONUNBUFFERED"] == "1"
        assert call_kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        collector.cleanup()



