"""
CentrifugeCANParser 单元测试用例集
对应 TC-CAN-001, TC-CAN-002, TC-4IN1-001, TC-4IN1-002, TC-REUSE-001
"""

import os
import sys
import pytest

# 添加待测模块路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data_processor")))

from processor.can_data_parser import CentrifugeCANParser


class TestCentrifugeCANParser:
    """测试 CAN 数据解析与 4-in-1 芯片合并命名器"""

    def test_global_slot_index_mapping(self):
        """测试 24 通道全局索引计算与反算"""
        parser = CentrifugeCANParser()

        # 首个通道 Board 1, Sensor 1 -> Slot 0
        assert parser.get_global_slot_index(1, 1) == 0
        assert parser.get_slot_from_global_index(0) == (1, 1)

        # 跨板临界通道 Board 1, Sensor 6 -> Slot 5
        assert parser.get_global_slot_index(1, 6) == 5
        assert parser.get_slot_from_global_index(5) == (1, 6)

        # Board 2, Sensor 1 -> Slot 6
        assert parser.get_global_slot_index(2, 1) == 6
        assert parser.get_slot_from_global_index(6) == (2, 1)

        # 最后一个通道 Board 4, Sensor 6 -> Slot 23
        assert parser.get_global_slot_index(4, 6) == 23
        assert parser.get_slot_from_global_index(23) == (4, 6)

        # 越界异常校验
        with pytest.raises(ValueError):
            parser.get_global_slot_index(5, 1)
        with pytest.raises(ValueError):
            parser.get_global_slot_index(1, 7)
        with pytest.raises(ValueError):
            parser.get_slot_from_global_index(24)

    def test_4in1_group_slots_distribution(self):
        """测试 6 组 4-in-1 的槽位划分完全覆盖 0~23"""
        parser = CentrifugeCANParser()
        all_slots = []
        for g in range(6):
            slots = parser.get_4in1_group_slots(g)
            assert len(slots) == 4
            all_slots.extend(slots)

        assert all_slots == list(range(24))

        # 跨板组检验
        # Group 1: 包含 Board 1 Sensor 5,6 和 Board 2 Sensor 1,2
        g1_slots = parser.get_4in1_group_slots(1)
        assert g1_slots == [4, 5, 6, 7]
        assert [parser.get_slot_from_global_index(s) for s in g1_slots] == [
            (1, 5), (1, 6), (2, 1), (2, 2)
        ]

    def test_4in1_filename_builder(self):
        """TC-NAME-001 / TC-4IN1-001: 测试标准 4 颗芯片命名与中划线拼接"""
        parser = CentrifugeCANParser()
        chips = ["00030020001", "00030020002", "00030020003", "00030020004"]
        filename = parser.build_4in1_filename(chips)
        assert filename == "00030020001-00030020002-00030020003-00030020004-LOG.txt"

    def test_4in1_filename_with_ng_placeholder(self):
        """TC-NAME-002 / TC-4IN1-002: 中间存在 NG 或空槽时补齐 00000000000"""
        parser = CentrifugeCANParser()
        # 仅传入两颗芯片
        chips = ["00030020001", None, "00030020003"]
        filename = parser.build_4in1_filename(chips)
        assert filename == "00030020001-00000000000-00030020003-00000000000-LOG.txt"

    def test_4in1_filename_all_ng(self):
        """TC-NAME-003: 全 NG 时生成 4 个 00000000000"""
        parser = CentrifugeCANParser()
        filename = parser.build_4in1_filename([])
        assert filename == "00000000000-00000000000-00000000000-00000000000-LOG.txt"

    def test_signed_acceleration_twos_complement(self):
        """测试带符号补码转换 (>512 则 -1024)"""
        parser = CentrifugeCANParser()
        # 静态零位周围
        assert parser.to_signed_acceleration(0) == 0
        assert parser.to_signed_acceleration(300) == 300
        assert parser.to_signed_acceleration(512) == 512
        # 负向加速度 (如 513 -> -511, 850 -> -174, 1023 -> -1)
        assert parser.to_signed_acceleration(513) == -511
        assert parser.to_signed_acceleration(850) == -174
        assert parser.to_signed_acceleration(1024) == 0

    def test_64byte_clean_bridge_payload_inheritance(self):
        """TC-REUSE-001: 校验底层 64 字节清洗与 01 f0 空载过滤继承正确性"""
        parser = CentrifugeCANParser()

        # 空载报文测试
        empty_raw = "01 f0 " * 32
        is_valid, clean_nibbles, msg = parser._clean_bridge_payload(empty_raw)
        assert not is_valid
        assert msg == "空载通道 (无器件)"

        # 正常报文测试 (32组 [0x02, data])
        normal_tokens = []
        for i in range(32):
            normal_tokens.append("02")
            normal_tokens.append(f"{i % 16:02X}")
        normal_raw = " ".join(normal_tokens)

        is_valid, clean_nibbles, msg = parser._clean_bridge_payload(normal_raw)
        assert is_valid
        assert len(clean_nibbles) == 32
        assert msg == "正常"
        assert clean_nibbles[0] == 0
        assert clean_nibbles[1] == 1

        # 异常状态字节测试
        corrupt_tokens = list(normal_tokens)
        corrupt_tokens[2] = "01"  # 第 2 组状态为 0x01
        corrupt_raw = " ".join(corrupt_tokens)
        is_valid_c, _, msg_c = parser._clean_bridge_payload(corrupt_raw)
        assert not is_valid_c
        assert "状态异常" in msg_c

    def test_0x25x_can_acceleration_decoding(self, tmp_path):
        """TC-CAN-003: 校验图 6/8 与图 7/8 规范中 0x25X (0x25A~0x25D) 动态加速度解析"""
        parser = CentrifugeCANParser()
        csv_file = tmp_path / "test_25x_stream.csv"

        # 构造仿真 CSV：前 24 条 0x1XX 芯片写数据，随后 0x25A 动态加速度帧
        rows = ["MAKE_CAN_ID(HEX),DATA(HEX)"]
        # 1. 24 条 0x1XX 报文
        for b in range(1, 5):
            for s in range(1, 7):
                payload = " ".join(["02", "00"] * 32)
                rows.append(f"0x1{b}{s},{payload}")

        # 2. 0x25A 报文：
        # Channel 1 (Slot 0): timeslot1 为 01 40 (+320 LSB)
        # Channel 2 (Slot 1): timeslot1 为 02 C0 (-320 LSB)
        # Channel 6 (Slot 5): timeslot1 为 01 f0 (空载)
        tokens_25a = []
        # Ch 1 (+320)
        tokens_25a.extend(["01", "40", "01", "f0", "01", "f0"])
        # Ch 2 (-320)
        tokens_25a.extend(["02", "C0", "01", "f0", "01", "f0"])
        # Ch 3, 4, 5
        for _ in range(3):
            tokens_25a.extend(["01", "40", "01", "f0", "01", "f0"])
        # Ch 6 (空载)
        tokens_25a.extend(["01", "f0", "01", "f0", "01", "f0"])
        # 12 字节保留位
        tokens_25a.extend(["02", "10", "02", "10", "02", "10", "02", "1E", "02", "10", "02", "10"])

        rows.append(f"0x25A,{' '.join(tokens_25a)}")

        with open(csv_file, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(rows))

        # 1. 检验 parse_can_raw_csv 成功跳过 0x25A，纯提取 24 槽位
        res_parsed = parser.parse_can_raw_csv(str(csv_file))
        assert len(res_parsed["slots"]) == 24

        # 2. 检验 extract_dynamic_acceleration_series 正确提取 0x25A 动态加速度
        series = parser.extract_dynamic_acceleration_series(str(csv_file))
        # Slot 0 (Board 1, Sensor 1) 应为 +320.0
        assert len(series[0]) == 1
        assert series[0][0] == 320.0
        # Slot 1 (Board 1, Sensor 2) 应为 -320.0
        assert len(series[1]) == 1
        assert series[1][0] == -320.0
        # Slot 5 (Board 1, Sensor 6) 空载应为 0 点
        assert len(series[5]) == 0

    def test_zcanpro_column_headers_and_anywhere_0x1xx_scan(self, tmp_path):
        """TC-CAN-004: 校验 zcanpro 导出的 ID,Data_Hex 列名以及突破前30帧限制识别 0x1xx"""
        parser = CentrifugeCANParser()
        csv_file = tmp_path / "test_zcanpro_format.csv"

        # 构造前 50 行非 0x1xx 的干扰杂帧 (模拟转台上电前或前面出现的异常帧)
        rows = ["ID,Data_Hex"]
        for i in range(50):
            rows.append(f"0x7E{i % 10},00 11 22 33 44 55 66 77")

        # 第 51 行以后才出现合法的 0x111 ~ 0x146 报文
        for b in range(1, 5):
            for s in range(1, 7):
                payload = " ".join(["02", "00"] * 32)
                rows.append(f"0x1{b}{s},{payload}")

        with open(csv_file, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(rows))

        # 验证解析器能够免疫前 50 行异常帧，全文件捕获 0x1xx 器件码帧
        res_parsed = parser.parse_can_raw_csv(str(csv_file))
        assert len(res_parsed["slots"]) == 24
        slot_0 = res_parsed["slots"][0]
        assert slot_0["is_valid"] is True
        assert slot_0["can_id"] == "0x111"


