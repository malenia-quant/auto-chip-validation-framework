"""
CG904 离心机测试 CAN 数据解析器与 4-in-1 芯片合并命名器
继承并封装 device_code_scan.py 中的 CG904DataParser 底层解析逻辑
"""

import os
import csv
import re
from typing import Dict, List, Optional, Tuple
import pandas as pd

from .device_code_scan import CG904DataParser


class CentrifugeCANParser(CG904DataParser):
    """
    离心机 CAN 数据帧解析引擎
    1. 继承 CG904DataParser 的 64 字节清洗、01 f0 空载识别、UID 组装及美式周规则解码。
    2. 扩展 24 通道多板拓扑排序 (Board 1~4 x Sensor 1~6)。
    3. 扩展 4-in-1 芯片合并命名器 (6 组 x 4 槽位，缺失补 00000000000)。
    4. 扩展带符号补码转换 (>512 则 -1024) 的动态加速度提取。
    """

    TOTAL_BOARDS = 4
    SENSORS_PER_BOARD = 6
    TOTAL_CHANNELS = 24
    GROUPS_4IN1_COUNT = 6
    NG_PLACEHOLDER = "00000000000"

    def __init__(self, input_file: Optional[str] = None, output_file: Optional[str] = None):
        super().__init__(input_file=input_file or "", output_file=output_file or "")

    @staticmethod
    def get_global_slot_index(board_id: int, sensor_id: int) -> int:
        """
        计算 24 通道全局槽位索引 (0 ~ 23)
        排序规则：Board ID 升序 (1~4) -> Sensor ID 升序 (1~6)
        """
        if not (1 <= board_id <= 4 and 1 <= sensor_id <= 6):
            raise ValueError(f"工位超限: Board {board_id}, Sensor {sensor_id}")
        return (board_id - 1) * 6 + (sensor_id - 1)

    @staticmethod
    def get_slot_from_global_index(slot_index: int) -> Tuple[int, int]:
        """由全局槽位索引 (0 ~ 23) 反算 (Board ID, Sensor ID)"""
        if not (0 <= slot_index < 24):
            raise ValueError(f"槽位索引超限: {slot_index}")
        board_id = (slot_index // 6) + 1
        sensor_id = (slot_index % 6) + 1
        return board_id, sensor_id

    @classmethod
    def get_4in1_group_slots(cls, group_idx: int) -> List[int]:
        """
        获取指定 4-in-1 组 (0 ~ 5) 对应的 4 个全局槽位索引
        Group 0: 0, 1, 2, 3   (Board 1 [Ch 1, 2, 3, 4])
        Group 1: 4, 5, 6, 7   (Board 1 [Ch 5, 6] + Board 2 [Ch 1, 2])
        Group 2: 8, 9, 10, 11 (Board 2 [Ch 3, 4, 5, 6])
        Group 3: 12, 13, 14, 15 (Board 3 [Ch 1, 2, 3, 4])
        Group 4: 16, 17, 18, 19 (Board 3 [Ch 5, 6] + Board 4 [Ch 1, 2])
        Group 5: 20, 21, 22, 23 (Board 4 [Ch 3, 4, 5, 6])
        """
        if not (0 <= group_idx < cls.GROUPS_4IN1_COUNT):
            raise ValueError(f"组号超限: {group_idx}")
        start = group_idx * 4
        return list(range(start, start + 4))

    @staticmethod
    def format_11digit_device_code(
        cfg27_val: int,
        cfg28_val: int,
        cfg29_val: int,
        field_order: str = "29_28_27"
    ) -> str:
        """
        按照器件码规范生成严格 11 位 Hex 编码，严密对接下位机烧录格式。
        支持两种物理拼接规则:
        1. '29_28_27' (产线标准，与示例 00030020001 严格一致):
           - CFG29 (4位 Hex): 备用高位与上位机编号
           - CFG28 (4位 Hex): 生产日期压缩码 (美式周规则)
           - CFG27 (3位 Hex): 芯片编号低12位
           - 拼接: 4 + 4 + 3 = 11 位 Hex
        2. '27_28_29' (文档名义第一部分/第二部分/第三部分顺序):
           - CFG27 (4位 Hex): 芯片编号完整16位
           - CFG28 (4位 Hex): 生产日期压缩码
           - CFG29 (3位 Hex): 备用与上位机代号低12位
           - 拼接: 4 + 4 + 3 = 11 位 Hex
        """
        part_date_4 = f"{cfg28_val & 0xFFFF:04X}"

        if field_order == "27_28_29":
            part_sn_4 = f"{cfg27_val & 0xFFFF:04X}"
            part_host_3 = f"{cfg29_val & 0x0FFF:03X}"
            return f"{part_sn_4}{part_date_4}{part_host_3}"
        else:
            # 默认 '29_28_27' 对齐 00030020001 产线标准
            part_host_4 = f"{cfg29_val & 0xFFFF:04X}"
            part_sn_3 = f"{cfg27_val & 0x0FFF:03X}"
            return f"{part_host_4}{part_date_4}{part_sn_3}"

    def extract_device_code_from_registers(self, reg_map: dict, field_order: str = "29_28_27") -> str:
        """从解析出的 16 个寄存器中提取并组装严格 11 位 Hex 器件码"""
        cfg27_val = (reg_map["2E"] << 8) | reg_map["2D"]
        cfg28_val = (reg_map["2B"] << 8) | reg_map["2A"]
        cfg29_val = (reg_map["28"] << 8) | reg_map["27"]
        return self.format_11digit_device_code(cfg27_val, cfg28_val, cfg29_val, field_order=field_order)

    def build_4in1_filename(self, chip_codes: List[Optional[str]]) -> str:
        """
        4-in-1 芯片合并命名器:
        传入 4 个槽位的器件编号（不足4个、NG、空载则补 00000000000）
        输出: {chip1}-{chip2}-{chip3}-{chip4}-LOG.txt
        """
        slots = []
        for i in range(4):
            code = chip_codes[i] if i < len(chip_codes) and chip_codes[i] else self.NG_PLACEHOLDER
            # 确保每个编号清洗为合规的 11 位大写字符串
            code_str = str(code).strip().upper()
            if len(code_str) != 11 or code_str == "-" or not re.match(r"^[0-9A-F]{11}$", code_str):
                code_str = self.NG_PLACEHOLDER
            slots.append(code_str)
        return f"{'-'.join(slots)}-LOG.txt"

    def generate_all_4in1_filenames(self, slot_device_map: Dict[int, Optional[str]]) -> List[str]:
        """
        根据全局 24 槽位的器件字典生成全部 6 组 4-in-1 文件名
        """
        filenames = []
        for g in range(self.GROUPS_4IN1_COUNT):
            group_slots = self.get_4in1_group_slots(g)
            group_codes = [slot_device_map.get(s) for s in group_slots]
            fn = self.build_4in1_filename(group_codes)
            filenames.append(fn)
        return filenames

    @staticmethod
    def to_signed_acceleration(val: int) -> int:
        """
        带符号补码转换：
        > 512 减去 1024 还原为真实的物理加速度读数
        (继承 sensor_processor1.py 产线标准)
        """
        return val - 1024 if val > 512 else val

    def parse_can_raw_csv(self, csv_file: str) -> Dict[str, any]:
        """
        完整读取并解析一个离心机 CAN 测试 CSV 文件
        返回:
        {
            "slots": { slot_index: { parsed_row } },
            "filenames_4in1": [ 6 个文件名 ],
            "raw_dataframe": pd.DataFrame,
            "abnormal_channels": [ (board_id, sensor_id, reason) ]
        }
        """
        if not os.path.exists(csv_file):
            raise FileNotFoundError(f"文件不存在: {csv_file}")

        slot_data = {}
        abnormal_list = []

        with open(csv_file, mode="r", encoding="utf-8-sig") as infile:
            reader = csv.DictReader(infile)
            for row_idx, row in enumerate(reader, start=1):
                # 兼容多种常见的 CAN 报文 CSV 列名命名 (如 ZLG zcanpro 生成的 ID/Data_Hex 或产线格式 MAKE_CAN_ID(HEX)/DATA(HEX))
                can_id_raw = (row.get("MAKE_CAN_ID(HEX)") or row.get("ID") or row.get("can_id") or row.get("CAN_ID") or "").strip()
                data_raw = (row.get("DATA(HEX)") or row.get("Data_Hex") or row.get("Data") or row.get("DATA") or "").strip()
                if not can_id_raw or not data_raw:
                    continue

                try:
                    can_id_val = int(can_id_raw, 16)
                except ValueError:
                    continue

                # 遇到 0x25X 动态加速度报文时跳过（该阶段为离心机运转加速度数据，不包含底层芯片配置寄存器）
                if can_id_val in (0x25A, 0x25B, 0x25C, 0x25D):
                    continue

                # 【核心业务规则变更】：固定使用 0x1xx (0x100~0x1FF) 作为器件码判断帧，不再限制前30帧！
                # 即使前面有异常干扰帧，只要在后续数据流中出现合法的 0x1xx 器件码帧即可正常识别
                if not (0x100 <= can_id_val <= 0x1FF):
                    continue

                board_id = (can_id_val - 0x100) // 0x10
                sensor_id = (can_id_val - 0x100) % 0x10

                if not (1 <= board_id <= 4 and 1 <= sensor_id <= 6):
                    continue

                slot_idx = self.get_global_slot_index(board_id, sensor_id)
                # 若此前已成功解析出该工位的合法有效器件码，不再被后续重复帧覆盖
                if slot_idx in slot_data and slot_data[slot_idx]["is_valid"]:
                    continue

                is_valid, clean_nibbles, status_msg = self._clean_bridge_payload(data_raw)

                parsed_item = {
                    "row_idx": row_idx,
                    "can_id": can_id_raw,
                    "board_id": board_id,
                    "sensor_id": sensor_id,
                    "slot_index": slot_idx,
                    "is_valid": is_valid,
                    "status_msg": status_msg,
                    "device_code_11": self.NG_PLACEHOLDER,
                    "uid_32": "-",
                }

                if is_valid:
                    reg_map = self._assemble_registers(clean_nibbles)
                    business_fields = self._decode_business_fields(reg_map)
                    device_code = self.extract_device_code_from_registers(reg_map)
                    parsed_item.update(business_fields)
                    parsed_item["device_code_11"] = device_code
                    parsed_item["uid_32"] = business_fields.get("完整32位Hex_UID", "-")
                    cfg27 = (reg_map["2E"] << 8) | reg_map["2D"]
                    cfg28 = (reg_map["2B"] << 8) | reg_map["2A"]
                    cfg29 = (reg_map["28"] << 8) | reg_map["27"]
                    parsed_item["cfg27_val"] = cfg27
                    parsed_item["cfg28_val"] = cfg28
                    parsed_item["cfg29_val"] = cfg29
                    parsed_item["芯片器件码"] = f"{cfg29:04X}{cfg28:04X}{cfg27:04X}"
                else:
                    if status_msg != "空载通道 (无器件)":
                        abnormal_list.append((board_id, sensor_id, status_msg))

                slot_data[slot_idx] = parsed_item

        # 整理 24 通道映射字典
        slot_device_map = {}
        for s in range(self.TOTAL_CHANNELS):
            item = slot_data.get(s)
            if item and item.get("is_valid"):
                slot_device_map[s] = item["device_code_11"]
            else:
                slot_device_map[s] = None

        filenames_4in1 = self.generate_all_4in1_filenames(slot_device_map)

        return {
            "slots": slot_data,
            "slot_device_map": slot_device_map,
            "filenames_4in1": filenames_4in1,
            "abnormal_channels": abnormal_list,
        }

    def extract_dynamic_acceleration_series(self, csv_file: str) -> Dict[int, List[float]]:
        """
        从实机测试 CSV 文件中提取 24 个工位的动态加速度时序数据 (用于离心机加减速边沿识别与稳态计算)
        严格遵循图 6/8 与图 7/8 规范:
        - 0x1XX (前24条) 为芯片烧录与 UID 寄存器读取，不作为动态加速度。
        - 0x25X (0x25A~0x25D) 为离心机运转期间的 4 块供电板加速度数据:
          * 0x25A: #1 板 (0x111~0x116, Slot 0~5)
          * 0x25B: #2 板 (0x121~0x126, Slot 6~11)
          * 0x25C: #3 板 (0x131~0x136, Slot 12~17)
          * 0x25D: #4 板 (0x141~0x146, Slot 18~23)
          * 考虑3的倍数数据组: 每路传感器包含 3 个 timeslot (各2字节)，timeslot1 为有效加速度。
        返回: { slot_index: [ acc_0, acc_1, acc_2, ... ] }
        """
        if not os.path.exists(csv_file):
            raise FileNotFoundError(f"文件不存在: {csv_file}")

        series_map: Dict[int, List[float]] = {s: [] for s in range(self.TOTAL_CHANNELS)}
        board_can_map = {
            0x25A: 1,
            0x25B: 2,
            0x25C: 3,
            0x25D: 4,
        }

        with open(csv_file, mode="r", encoding="utf-8-sig") as infile:
            reader = csv.DictReader(infile)
            fieldnames = reader.fieldnames or []

            # 形式 A: 包含 CAN ID 与 DATA 载荷的时序流 (兼容 MAKE_CAN_ID(HEX) / ID 以及 DATA(HEX) / Data_Hex)
            has_can_id_col = any(c in fieldnames for c in ["MAKE_CAN_ID(HEX)", "ID", "can_id", "CAN_ID"])
            has_data_col = any(c in fieldnames for c in ["DATA(HEX)", "Data_Hex", "Data", "DATA"])

            if has_can_id_col and has_data_col:
                has_25x = False
                temp_1xx_series: Dict[int, List[float]] = {s: [] for s in range(self.TOTAL_CHANNELS)}

                for row in reader:
                    can_id_raw = (row.get("MAKE_CAN_ID(HEX)") or row.get("ID") or row.get("can_id") or row.get("CAN_ID") or "").strip()
                    data_raw = (row.get("DATA(HEX)") or row.get("Data_Hex") or row.get("Data") or row.get("DATA") or "").strip()
                    if not can_id_raw or not data_raw:
                        continue
                    try:
                        can_id_val = int(can_id_raw, 16)
                    except ValueError:
                        continue

                    # 1. 规范 0x25X 格式 (0x25A ~ 0x25D，图 6/8 与图 7/8 工业标准)
                    if can_id_val in board_can_map:
                        has_25x = True
                        board_id = board_can_map[can_id_val]
                        tokens = [t for t in data_raw.strip().split() if t]
                        # 每块供电板 6 路 PSI5 通道，每通道 3 个 timeslot，每 timeslot 2 字节
                        # 第 s 路传感器的 timeslot1 位于 tokens[(s-1)*6] (高字节) 与 tokens[(s-1)*6 + 1] (低字节)
                        for s_id in range(1, 7):
                            slot_idx = self.get_global_slot_index(board_id, s_id)
                            h_idx = (s_id - 1) * 6
                            l_idx = h_idx + 1
                            if l_idx < len(tokens):
                                th = tokens[h_idx].lower()
                                tl = tokens[l_idx].lower()
                                # 检查空载或异常状态 (如 01 f0 或 01 00)
                                if (th, tl) in [("01", "f0"), ("01", "00"), ("00", "00")]:
                                    continue
                                try:
                                    raw_code = (int(tokens[h_idx], 16) << 8) | int(tokens[l_idx], 16)
                                    acc_val = float(self.to_signed_acceleration(raw_code & 0x03FF))
                                    series_map[slot_idx].append(acc_val)
                                except ValueError:
                                    continue

                    # 2. 仿真/历史 0x1XX 逐行时序流 (仅当全文件无 0x25X 报文时作为保底兼容)
                    elif 0x111 <= can_id_val <= 0x146:
                        board_id = (can_id_val - 0x100) // 0x10
                        sensor_id = (can_id_val - 0x100) % 0x10
                        if 1 <= board_id <= 4 and 1 <= sensor_id <= 6:
                            slot_idx = self.get_global_slot_index(board_id, sensor_id)
                            tokens = [t for t in data_raw.strip().split() if t]
                            if len(tokens) >= 4:
                                if tokens[0].lower() in ("01", "f0") and tokens[1].lower() in ("01", "f0"):
                                    continue
                                try:
                                    raw_code = (int(tokens[1], 16) << 8) | int(tokens[3], 16)
                                    acc_val = float(self.to_signed_acceleration(raw_code & 0x03FF))
                                    temp_1xx_series[slot_idx].append(acc_val)
                                except (ValueError, IndexError):
                                    continue

                if not has_25x:
                    # 仅当文件中完全没有 0x25X 报文时，启用 0x1XX 保底数据
                    for s in range(self.TOTAL_CHANNELS):
                        series_map[s].extend(temp_1xx_series[s])

            # 形式 B: 已经分列的工位时序表 (如列名为 "0", "1" 或 "B1_S1", "Slot_0" 等)
            else:
                infile.seek(0)
                df = pd.read_csv(infile)
                for col in df.columns:
                    target_slot = None
                    col_str = str(col).strip()
                    if col_str.isdigit() and 0 <= int(col_str) < 24:
                        target_slot = int(col_str)
                    elif col_str.startswith("Slot_"):
                        target_slot = int(col_str.replace("Slot_", ""))
                    elif "_" in col_str:
                        # 如 B1_S1
                        parts = col_str.split("_")
                        if len(parts) == 2 and parts[0].startswith("B") and parts[1].startswith("S"):
                            try:
                                b = int(parts[0][1:])
                                s = int(parts[1][1:])
                                target_slot = self.get_global_slot_index(b, s)
                            except ValueError:
                                pass
                    if target_slot is not None and 0 <= target_slot < 24:
                        vals = pd.to_numeric(df[col], errors="coerce").dropna().tolist()
                        series_map[target_slot].extend([float(v) for v in vals])

        return series_map
