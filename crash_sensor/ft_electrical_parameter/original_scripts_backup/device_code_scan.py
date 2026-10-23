"""
CG904 碰撞传感器批量编号处理与解析程序
开发人员: mozial
功能说明:
1. 读取批量测试生成的 CSV 原始数据文件。
2. 识别 CAN 拓扑 ID (0x111 ~ 0x146)，路由解析板号(1~4)与传感器通道号(1~6)，输出纯数字。
3. 校验 64 字节底层状态，剔除 01 f0 空通道及链路状态异常帧。
4. 解构 32 组 [状态, 数据] 结构，提取 32 个有效 4-bit 十六进制数（UID）。
5. 将前 4 位 Hex 剥离为 CFG26 (非编号位/非数据位)，其余按规范映射至 CFG27~CFG33。
6. 根据 CFG28 美式周规则（年-周-天）逆向精确计算出 YYYY-MM-DD 真实生产日期。
7. 芯片编号同时输出十六进制 (HEX) 与十进制 (DEC) 格式。
8. 映射并输出完整的文字性说明、原始数据及解析结果。
"""

import csv
import datetime
import os

# ==============================================================================
# 顶部用户配置区
# ==============================================================================
INPUT_CSV_PATH = "4_board_6PSI.csv"  # 输入的原始测试 CSV 文件路径
OUTPUT_CSV_PATH = "parsed_sensor_summary.csv"  # 输出的解析结果 CSV 文件路径


class CG904DataParser:
    """
    CG904 碰撞传感器批量编号处理与解析引擎
    开发人员: mozial
    """

    # 16 个有效 8-bit 寄存器序列（从 CFG26 到 CFG33，每组均跳过第 3 个奇偶校验字节）
    # 总共 16 个寄存器 = 32 个 Hex 字符
    REGISTER_SEQUENCE = [
        "31", "30",  # CFG26_1: 非编号位 (剔除 2F 校验位)
        "2E", "2D",  # CFG27_1: 芯片编号 (剔除 2C 校验位)
        "2B", "2A",  # CFG28_1: 生产日期 (剔除 29 校验位)
        "28", "27",  # CFG29_1: 备用序号与上位机编号 (剔除 26 校验位)
        "25", "24",  # CFG30_1: 芯片版本与制造商代码 (剔除 23 校验位)
        "22", "21",  # CFG31_1: 备用传感器类型等 (剔除 20 校验位)
        "1F", "1E",  # CFG32_1: 备用传感器生产日期 (剔除 1D 校验位)
        "1C", "1B",  # CFG33_1: 备用产线/批次/代码 (剔除 1A 校验位)
    ]

    def __init__(self, input_file: str, output_file: str):
        self.input_file = input_file
        self.output_file = output_file
        self.empty_channel_pattern = "01 f0"

    def _clean_bridge_payload(self, raw_hex_str: str) -> tuple:
        """
        开发人员: mozial
        功能: 将 64 字节的 CG904 CAN 负载清洗为 32 个纯净的 4-bit 十六进制数。
        返回: (is_valid: bool, clean_nibbles: list, error_msg: str)
        """
        tokens = [t.strip() for t in raw_hex_str.strip().split() if t.strip()]
        if len(tokens) != 64:
            return False, [], f"数据长度异常: 实际 {len(tokens)} 字节, 预期 64 字节"

        # 检查是否为空载通道
        if all(token.lower() in ("01", "f0") for token in tokens[:10]):
            return False, [], "空载通道 (无器件)"

        clean_nibbles = []
        for i in range(32):
            status_byte = int(tokens[i * 2], 16)
            data_byte = int(tokens[i * 2 + 1], 16)

            # 校验转换板通道状态 (0x02 为正常通信标志位)
            if status_byte != 0x02:
                return False, [], f"第 {i+1} 组数据状态异常 (Status: 0x{status_byte:02X})"

            # 提取低 4 位真实载荷
            valid_nibble = data_byte & 0x0F
            clean_nibbles.append(valid_nibble)

        return True, clean_nibbles, "正常"

    def _assemble_registers(self, clean_nibbles: list) -> dict:
        """
        开发人员: mozial
        功能: 将清洗出的 32 个半字节，两两按照大端规则合并为 16 个 8-bit 寄存器值。
        """
        register_map = {}
        for reg_idx, reg_name in enumerate(self.REGISTER_SEQUENCE):
            high_nibble = clean_nibbles[reg_idx * 2]
            low_nibble = clean_nibbles[reg_idx * 2 + 1]
            register_map[reg_name] = (high_nibble << 4) | low_nibble
        return register_map

    def _decode_mfg_date(self, year_2digit: int, week_num: int, day_of_week: int) -> tuple:
        """
        开发人员: mozial
        功能: 按照美式规则（周日为起点，第零周为1月1日至首个周日前），将 年-周-天 还原为真实 YYYY-MM-DD 日期。
        返回: (formatted_date_str: str, debug_str: str)
        """
        full_year = 2000 + year_2digit
        debug_str = f"20{year_2digit:02d}年 第{week_num}周 星期{day_of_week}"

        try:
            # %U: 一年中的周数（00-53），以星期日为一周的开始，第一个星期日之前的天数算在第 0 周
            # %w: 星期几，0 表示星期日，6 表示星期六
            date_str = f"{full_year} {week_num:02d} {day_of_week}"
            calc_date = datetime.datetime.strptime(date_str, "%Y %U %w").date()
            return calc_date.strftime("%Y-%m-%d"), debug_str
        except ValueError:
            return "日期解析异常", debug_str

    def _decode_business_fields(self, reg_map: dict) -> dict:
        """
        开发人员: mozial
        功能: 严格依照最新《器件码命名规则》提取全部业务字段
        改动说明:
        1. 芯片编号重命名为 芯片编号_HEX，并新增 芯片编号_DEC 输出十进制数值。
        2. 生产日期_编码解析 列调整至 生产日期_真实日期 列之前。
        """
        fields = {}

        # 0. 完整 32 位 Hex UID 拼接
        full_32_hex = "".join([f"{reg_map[r]:02X}" for r in self.REGISTER_SEQUENCE])
        fields["完整32位Hex_UID"] = full_32_hex

        # 1. CFG26_1 (31-30): 非编号位（最开始4位Hex）
        cfg26_val = (reg_map["31"] << 8) | reg_map["30"]
        fields["CFG26(非编号位_前4位Hex)"] = f"0x{cfg26_val:04X}"

        # 2. CFG27_1 (2E-2D): 芯片编号 <15:0>，输出 HEX 与 DEC
        cfg27_val = (reg_map["2E"] << 8) | reg_map["2D"]
        fields["芯片编号_HEX"] = f"0x{cfg27_val:04X}"
        fields["芯片编号_DEC"] = str(cfg27_val)

        # 3. CFG28_1 (2B-2A): 生产日期 (编码解析排在真实日期前)
        cfg28_val = (reg_map["2B"] << 8) | reg_map["2A"]
        year_code = (cfg28_val >> 9) & 0x7F   # <15:9> 7位 年份后两位
        week_code = (cfg28_val >> 3) & 0x3F   # <8:3>  6位 本年第几周
        day_code = cfg28_val & 0x07           # <2:0>  3位 本周第几天 (0=周日)

        real_date_str, date_raw_desc = self._decode_mfg_date(year_code, week_code, day_code)
        fields["生产日期_编码解析"] = date_raw_desc
        fields["生产日期_真实日期"] = real_date_str

        # 4. CFG29_1 (28-27): 备用-第三部分序号 与 烧录上位机编号
        cfg29_val = (reg_map["28"] << 8) | reg_map["27"]
        sn_part3_spare = (cfg29_val >> 4) & 0x0FFF  # <15:4> 12位
        host_id = cfg29_val & 0x0F                  # <3:0> 4位
        fields["备用_第三部分序号"] = f"0x{sn_part3_spare:03X}"
        fields["烧录上位机编号"] = f"{host_id} (二进制: {bin(host_id)[2:].zfill(4)})"

        # 5. CFG30_1 (25-24): 烧录芯片版本号 与 备用-传感器制造商代码
        cfg30_val = (reg_map["25"] << 8) | reg_map["24"]
        ver_high = (cfg30_val >> 12) & 0x0F         # 主版本
        ver_low = (cfg30_val >> 8) & 0x0F           # 次版本
        mfg_code_spare = cfg30_val & 0xFF           # <7:0> 8位
        fields["烧录芯片版本号"] = f"v{ver_high}.{ver_low}"
        fields["备用_传感器制造商代码"] = f"0x{mfg_code_spare:02X}"

        # 6. CFG31_1 (22-21): 备用参数
        cfg31_val = (reg_map["22"] << 8) | reg_map["21"]
        sensor_type_spare = (cfg31_val >> 10) & 0x0F      # <13:10> 4位
        satellite_info_spare = (cfg31_val >> 6) & 0x0F    # <9:6> 4位
        housing_code_spare = cfg31_val & 0x3F             # <5:0> 6位
        fields["备用_传感器类型"] = f"0x{sensor_type_spare:X}"
        fields["备用_Satellite_information"] = f"0x{satellite_info_spare:X}"
        fields["备用_Satellite_housing_code"] = f"0x{housing_code_spare:02X}"

        # 7. CFG32_1 (1F-1E): 备用-传感器生产日期 <13:0>
        cfg32_val = (reg_map["1F"] << 8) | reg_map["1E"]
        mfg_date_spare = cfg32_val & 0x3FFF
        fields["备用_传感器生产日期"] = f"0x{mfg_date_spare:04X}"

        # 8. CFG33_1 (1C-1B): 备用产线、批次、代号
        cfg33_val = (reg_map["1C"] << 8) | reg_map["1B"]
        line_num_spare = (cfg33_val >> 8) & 0x0F     # <11:8> 4位
        batch_num_spare = (cfg33_val >> 4) & 0x0F    # <7:4> 4位
        satellite_code_spare = cfg33_val & 0x0F      # <3:0> 4位
        fields["备用_传感器生产产线编号"] = f"0x{line_num_spare:X}"
        fields["备用_传感器生产批次"] = f"0x{batch_num_spare:X}"
        fields["备用_Satellite_code"] = f"0x{satellite_code_spare:X}"

        return fields

    def execute(self):
        """
        主控流程：执行 CSV 读取、路由、解析、展示与结果保存
        """
        if not os.path.exists(self.input_file):
            print(f"[错误] 无法找到输入文件: {self.input_file}")
            return

        results = []
        with open(self.input_file, mode="r", encoding="utf-8-sig") as infile:
            reader = csv.DictReader(infile)
            for row_idx, row in enumerate(reader, start=1):
                can_id_raw = row.get("MAKE_CAN_ID(HEX)", "").strip()
                data_raw = row.get("DATA(HEX)", "").strip()

                if not can_id_raw or not data_raw:
                    continue

                try:
                    can_id_val = int(can_id_raw, 16)
                except ValueError:
                    continue

                # 提取纯数字编号
                board_id = (can_id_val - 0x100) // 0x10
                sensor_id = (can_id_val - 0x100) % 0x10

                if not (1 <= board_id <= 4 and 1 <= sensor_id <= 6):
                    continue

                is_valid, clean_nibbles, status_msg = self._clean_bridge_payload(data_raw)

                parsed_row = {
                    "行号": row_idx,
                    "CAN_ID": can_id_raw,
                    "供电板编号": board_id,     # 纯数字
                    "通道编号": sensor_id,       # 纯数字
                    "状态信息": status_msg,
                    "原始DATA(HEX)": data_raw,
                }

                if is_valid:
                    reg_map = self._assemble_registers(clean_nibbles)
                    business_fields = self._decode_business_fields(reg_map)
                    parsed_row.update(business_fields)
                else:
                    empty_placeholders = {
                        "完整32位Hex_UID": "-",
                        "CFG26(非编号位_前4位Hex)": "-",
                        "芯片编号_HEX": "-",
                        "芯片编号_DEC": "-",
                        "生产日期_编码解析": "-",
                        "生产日期_真实日期": "-",
                        "备用_第三部分序号": "-",
                        "烧录上位机编号": "-",
                        "烧录芯片版本号": "-",
                        "备用_传感器制造商代码": "-",
                        "备用_传感器类型": "-",
                        "备用_Satellite_information": "-",
                        "备用_Satellite_housing_code": "-",
                        "备用_传感器生产日期": "-",
                        "备用_传感器生产产线编号": "-",
                        "备用_传感器生产批次": "-",
                        "备用_Satellite_code": "-",
                    }
                    parsed_row.update(empty_placeholders)

                results.append(parsed_row)

        # 终端格式化打印展示
        print(f"\n成功解析 {len(results)} 路传感器数据:\n" + "=" * 120)
        for res in results:
            print(
                f"[板号: {res['供电板编号']} | 通道: {res['通道编号']}] (CAN ID: {res['CAN_ID']}) | 状态: {res['状态信息']}"
            )
            if res["状态信息"] == "正常":
                print(f"  ├─ 完整UID (32-Hex): {res['完整32位Hex_UID']}")
                print(
                    f"  ├─ 基础结构: 非编号位={res['CFG26(非编号位_前4位Hex)']}, 芯片编号(HEX)={res['芯片编号_HEX']}, 芯片编号(DEC)={res['芯片编号_DEC']}, 上位机编号={res['烧录上位机编号']}, 版本={res['烧录芯片版本号']}"
                )
                print(
                    f"  └─ 生产日期: 编码详情={res['生产日期_编码解析']} -> 真实日期={res['生产日期_真实日期']}"
                )
            print("-" * 120)

        # 导出结果至 CSV 文件
        if results:
            fieldnames = list(results[0].keys())
            with open(self.output_file, mode="w", encoding="utf-8-sig", newline="") as outfile:
                writer = csv.DictWriter(outfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(results)
            print(f"\n[完成] 完整结构化结果已输出至: {self.output_file}")


if __name__ == "__main__":
    parser = CG904DataParser(input_file=INPUT_CSV_PATH, output_file=OUTPUT_CSV_PATH)
    parser.execute()