"""
CalibrationProcessor 单元测试用例集
对应 TC-CALC-001, TC-CALC-002, TC-SPAN-001, TC-SPAN-002, TC-MTP-001, TC-MTP-002
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data_processor")))

from processor.calibration_processor import CalibrationProcessor, SpanGateError


class TestCalibrationProcessor:
    """测试标定计算核心算法、Span 门禁与 MTP 模板定位替换"""

    def test_calculate_adj_normal(self):
        """TC-CALC-001 & TC-SPAN-001: 正常输入标定计算与 1.5 倍量程折算"""
        processor = CalibrationProcessor(
            scale_factor=1.5,
            const_numerator=961 * (2 ** 20),
            span_min=600.0,
            span_max=3600.0
        )
        # 输入: +160g 读数 850.0, -160g 读数 -850.0
        # pos_240g = 1275.0, neg_240g = -1275.0
        # span = 1275 - (-1275) = 2550.0
        # diff = 2551.0
        # calc = 961 * 1048576 / 2551.0 = 1007681536 / 2551.0 = 395014.32...
        # 截断在 16-bit 最大 65535
        adj_dec, adj_hex, span = processor.calculate_adj(850.0, -850.0)

        assert span == 2550.0
        assert adj_dec == 65535
        assert adj_hex == "FFFF"

    def test_calculate_adj_within_16bit_range(self):
        """测试在 16-bit 范围内的真实物理读数"""
        processor = CalibrationProcessor(
            scale_factor=1.5,
            const_numerator=961 * (2 ** 20),
            span_min=600.0,
            span_max=50000.0
        )
        # 假设跨度等效为 25000: diff = 25001 -> 1007681536 / 25001 = 40305 -> 0x9D71
        # pos_160g = 8333.333333333334, neg_160g = -8333.333333333334
        pos_160g = 25000.0 / (2 * 1.5)
        neg_160g = -pos_160g
        adj_dec, adj_hex, span = processor.calculate_adj(pos_160g, neg_160g)

        assert round(span) == 25000
        assert adj_dec == round(1007681536 / 25001)
        assert adj_hex == f"{adj_dec:04X}"

    def test_span_gate_protection(self):
        """TC-SPAN-002 & TC-CALC-002: Span 门禁异常拦截 (防除零/极小值溢出)"""
        processor = CalibrationProcessor(span_min=600.0, span_max=3600.0)

        # 异常 1: 读数接近 0 (断路/未连接)，跨度仅为 30 < 600
        with pytest.raises(SpanGateError) as exc_info:
            processor.calculate_adj(10.0, -10.0)
        assert "Span 门禁触发" in str(exc_info.value)

        # 异常 2: 负向读数误用绝对值，导致 span 约为 0
        with pytest.raises(SpanGateError):
            processor.calculate_adj(850.0, 840.0)

        # 异常 3: 读数严重飞出超上限
        with pytest.raises(SpanGateError):
            processor.calculate_adj(3000.0, -3000.0)

    def test_cfg22_trim_enable_bit(self):
        """TC-MTP-002: 测试 CFG22 寄存器第 13 位置位 1 (TRIM 使能)"""
        processor = CalibrationProcessor()

        # 初始未标定 (0x0000) -> 置位后应为 0x2000 (1 << 13 = 8192 = 0x2000)
        new_cfg = processor.set_cfg22_trim_enable(0x0000)
        assert new_cfg == 0x2000

        # 原已有低位配置 (0x0015) -> 置位后应为 0x2015
        new_cfg2 = processor.set_cfg22_trim_enable(0x0015)
        assert new_cfg2 == 0x2015

        # 原本已开启 (0x2015) -> 置位后保持 0x2015
        assert processor.set_cfg22_trim_enable(0x2015) == 0x2015

    def test_mtp_template_replacement(self, tmp_path):
        """TC-MTP-001: 校验 MTP 模板文本定位替换 6 处地址及 CFG22<13> 置位"""
        processor = CalibrationProcessor()

        sample_template = """// MTP Configuration File Before Calibration
REG_ADJ_MIN  5b 5a  DATA: 16h0
REG_ADJ_MAX  58 57  DATA: 16h0
REG_ADJ_MAXH 55 54  DATA: 16h3c10
CTRL_REG     CFG22  VAL: 16h0010
OTHER_REG    31 30  DATA: 16h0001
"""
        template_file = tmp_path / "sample_before.txt"
        output_file = tmp_path / "sample_after.txt"

        template_file.write_text(sample_template, encoding="utf-8")

        success = processor.process_mtp_template(str(template_file), str(output_file), "3C2A")
        assert success

        updated_text = output_file.read_text(encoding="utf-8")

        # 验证 5b 5a, 58 57, 55 54 替换为了 16h3C2A
        assert "5b 5a  DATA: 16h3C2A" in updated_text
        assert "58 57  DATA: 16h3C2A" in updated_text
        assert "55 54  DATA: 16h3C2A" in updated_text

        # 验证 CFG22 的 16h0010 置位第 13 位变成了 16h2010 (0x0010 | 0x2000 = 0x2010)
        assert "CFG22  VAL: 16h2010" in updated_text

        # 验证无关寄存器保持不变
        assert "OTHER_REG    31 30  DATA: 16h0001" in updated_text
