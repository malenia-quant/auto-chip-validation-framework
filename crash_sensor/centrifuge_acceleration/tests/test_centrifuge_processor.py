"""
CentrifugeProcessor 单元测试用例集
对应 TC-CENT-001, TC-REUSE-002
"""

import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data_processor")))

from processor.centrifuge_processor import CentrifugeProcessor


class TestCentrifugeProcessor:
    """测试离心机加减速动态过滤、稳态提取与均值计算"""

    def test_steady_state_cropping(self):
        """TC-CENT-001: 校验前 30 帧过渡态过滤与不超过 50 点稳态截取"""
        processor = CentrifugeProcessor(discard_frames=30, steady_points_max=50, min_length=10)

        # 构造长度为 120 的仿真台阶段
        raw_segment = np.ones(120) * 850.0

        cropped = processor.crop_steady_state(raw_segment)
        assert cropped is not None
        # 截取长度应严格等于 steady_points_max (50 点)
        assert len(cropped) == 50
        assert np.all(cropped == 850.0)

        # 构造过短的数据段 (小于 30 帧) -> 应被判定为无效并返回 None
        short_segment = np.ones(25) * 850.0
        assert processor.crop_steady_state(short_segment) is None

        # 构造仅略大于 30 帧但不足 min_length 的数据段 -> 返回 None
        barely_segment = np.ones(35) * 850.0  # 裁剪后仅剩 5 点 < 10 点
        assert processor.crop_steady_state(barely_segment) is None

    def test_edge_detection_and_mean_calculation(self):
        """TC-REUSE-002: 仿真完整离心机阶梯信号并提取稳态均值"""
        processor = CentrifugeProcessor(
            discard_frames=30,
            steady_points_max=50,
            min_length=10,
            zero_division_p=30.0,
            zero_division_n=-30.0
        )

        # 构造带前置零位、正向台阶、中间零位、负向台阶的完整信号 (长度 600)
        signal = np.zeros(600)
        # 正向台阶: index 50 ~ 250，设定前 30 帧为上升过渡 (0 -> 850)，其后稳定在 850
        signal[50:80] = np.linspace(0, 850, 30)
        signal[80:250] = 850.0

        # 负向台阶: index 350 ~ 550，设定前 30 帧为下降过渡 (0 -> -850)，其后稳定在 -850
        signal[350:380] = np.linspace(0, -850, 30)
        signal[380:550] = -850.0

        pos_mean, neg_mean = processor.process_series_mean(signal)

        assert pos_mean is not None
        assert neg_mean is not None
        # 校验提取出的稳态均值
        assert abs(pos_mean - 850.0) < 5.0
        assert abs(neg_mean - (-850.0)) < 5.0

    def test_staircase_plot_creation(self, tmp_path):
        """测试阶梯图 PNG 生成"""
        processor = CentrifugeProcessor()
        signal = np.zeros(100)
        signal[20:80] = 500.0

        plot_path = tmp_path / "test_staircase.png"
        processor.create_staircase_plot(signal, "Test Plot", str(plot_path))

        assert plot_path.exists()
        assert plot_path.stat().st_size > 1000

    def test_adaptive_multi_stage_plateau_0_80_160_0(self):
        """TC-NEW-008: 校验新测试工况 0g -> 80g -> 160g -> 0g 多段连续突变检测与自适应无固定点数均值提取"""
        processor = CentrifugeProcessor(steady_points_max=0)

        # 构造 0g -> 80g -> 160g -> 0g 连续阶跃时序 (总长 200 帧)
        signal = np.zeros(200)
        # 0 ~ 20: 0g (基线 0 LSB)
        # 20 ~ 30: 突变加载 1 (0 -> 160 LSB, 80g)
        signal[20:30] = np.linspace(0, 160, 10)
        # 30 ~ 70: 80g 稳态平台 (40 帧，均值 160 LSB)
        signal[30:70] = 160.0 + np.random.normal(0, 0.5, 40)
        # 70 ~ 80: 突变加载 2 (160 -> 320 LSB, 160g)
        signal[70:80] = np.linspace(160, 320, 10)
        # 80 ~ 160: 160g 稳态平台 (80 帧，均值 320 LSB)
        signal[80:160] = 320.0 + np.random.normal(0, 0.5, 80)
        # 160 ~ 175: 降速停止 (320 -> 0 LSB)
        signal[160:175] = np.linspace(320, 0, 15)
        # 175 ~ 200: 0g 停止

        plateaus = processor.detect_adaptive_plateaus(signal)
        # 校验分级与均值提取
        assert plateaus["mean_0"] is not None
        assert abs(plateaus["mean_0"]) < 5.0

        assert plateaus["mean_80_pos"] is not None
        assert abs(plateaus["mean_80_pos"] - 160.0) < 5.0

        assert plateaus["mean_160_pos"] is not None
        assert abs(plateaus["mean_160_pos"] - 320.0) < 5.0

        # 160g 平台由于有 80 帧，自适应提取应远超过旧版 50 点限制
        p160_list = [p for p in plateaus["plateaus"] if p["stage"] == "160g"]
        assert len(p160_list) > 0
        assert p160_list[0]["count"] > 50  # 证明彻底解除了 50 点死板限制

        pos_m, neg_m = processor.process_series_mean(signal)
        assert pos_m is not None
        assert abs(pos_m - 320.0) < 5.0

