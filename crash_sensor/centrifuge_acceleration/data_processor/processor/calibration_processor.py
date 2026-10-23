"""
CrashSensor 离心机标定计算引擎与 MTP 模板定位替换处理器
1. 1.5 倍量程折算与带符号补码基准
2. Span 合理性门禁校验 [S_min, S_max]，严防除零与极小值溢出
3. 核心标定公式: round(961 * 2^20 / (Span + 1))
4. before-calibration 模板定位替换 6 处地址
5. CFG22<13> 控制位置位 1 (TRIM 标定使能)
"""

import os
import re
import configparser
from typing import Dict, Optional, Tuple


class SpanGateError(ValueError):
    """跨度超出硬件合理性门禁异常"""
    pass


class CalibrationProcessor:
    """
    标定校准计算与 MTP 文件更新器
    """

    DEFAULT_SCALE_FACTOR = 1.5
    DEFAULT_CONST_NUMERATOR = 961 * (2 ** 20)  # 1007681536
    DEFAULT_SPAN_MIN = 600.0
    DEFAULT_SPAN_MAX = 3600.0

    # 标定 ADJ 寄存器地址标识
    TARGET_ADDRESSES = {
        "ADJ_MIN": "5b 5a",
        "ADJ_MAX": "58 57",
        "ADJ_MAXH": "55 54",
    }

    def __init__(
        self,
        config_path: Optional[str] = None,
        scale_factor: float = DEFAULT_SCALE_FACTOR,
        const_numerator: int = DEFAULT_CONST_NUMERATOR,
        span_min: float = DEFAULT_SPAN_MIN,
        span_max: float = DEFAULT_SPAN_MAX,
    ):
        self.scale_factor = scale_factor
        self.const_numerator = const_numerator
        self.span_min = span_min
        self.span_max = span_max

        if config_path and os.path.exists(config_path):
            self._load_config(config_path)

    def _load_config(self, config_path: str):
        cfg = configparser.ConfigParser()
        cfg.read(config_path, encoding="utf-8")
        if "Hardware" in cfg:
            self.scale_factor = cfg.getfloat("Hardware", "scale_factor", fallback=self.scale_factor)
        if "Calibration" in cfg:
            self.const_numerator = cfg.getint("Calibration", "const_numerator", fallback=self.const_numerator)
            self.span_min = cfg.getfloat("Calibration", "span_min", fallback=self.span_min)
            self.span_max = cfg.getfloat("Calibration", "span_max", fallback=self.span_max)

    def calculate_adj(self, pos_160g_mean: float, neg_160g_mean: float) -> Tuple[int, str, float]:
        """
        计算 ADJ 标定值:
        1. 放大至 240g 等效值: pos_240g = pos_160g * 1.5, neg_240g = neg_160g * 1.5
        2. 跨度 Span = pos_240g - neg_240g
        3. 硬件合理性门禁校验: Span in [span_min, span_max]
        4. 核心标定公式: adj_dec = round(961 * 2^20 / (Span + 1))
        5. 返回: (adj_dec, adj_hex, span)
        """
        # 1. 放大 1.5 倍折算
        pos_240g = float(pos_160g_mean) * self.scale_factor
        neg_240g = float(neg_160g_mean) * self.scale_factor

        # 2. 跨度 Span
        span = pos_240g - neg_240g

        # 3. 硬件门禁防除零/溢出
        if span < self.span_min or span > self.span_max:
            raise SpanGateError(
                f"Span 门禁触发: 实际跨度 {span:.2f} 不在合理区间 [{self.span_min}, {self.span_max}] 内"
            )

        # 4. 标定公式计算
        diff = span + 1.0
        adj_dec = int(round(self.const_numerator / diff))

        # 限制在 16-bit 寄存器范围 (0 ~ 65535)
        adj_dec_clamped = max(0, min(65535, adj_dec))
        adj_hex = f"{adj_dec_clamped:04X}"

        return adj_dec_clamped, adj_hex, span

    @staticmethod
    def set_cfg22_trim_enable(original_cfg22_val: int) -> int:
        """
        将 CFG22 寄存器的第 13 位 (CFG22<13>) 置 1 (TRIM 使能)
        """
        return original_cfg22_val | (1 << 13)

    def update_mtp_content(self, original_text: str, adj_hex: str) -> Tuple[str, int]:
        """
        在 MTP 模板文本中执行定位与替换:
        1. 替换 6 处修调寄存器值 (MIN, MAX, MAXH 及其镜像行) 为 adj_hex
        2. 将 CFG22<13> 配置为 1 (开启标定 TRIM 使能)
        返回: (更新后文本, 替换点计数)
        """
        updated_lines = []
        replace_count = 0
        lines = original_text.splitlines()

        addr_patterns = [
            re.compile(r"\b5b\s+5a\b", re.IGNORECASE),
            re.compile(r"\b58\s+57\b", re.IGNORECASE),
            re.compile(r"\b55\s+54\b", re.IGNORECASE),
        ]
        cfg22_pattern = re.compile(r"\bCFG22\b", re.IGNORECASE)

        for line in lines:
            new_line = line

            # 1. 检查是否为 ADJ 目标地址行或包含 ADJ 默认值的行
            is_target_addr = any(p.search(line) for p in addr_patterns)
            if is_target_addr:
                # 匹配形如 16h0, 16h0000, 16h3c10, 0x0000 等 16 进制值并替换
                if re.search(r"16h[0-9a-fA-F]+", line):
                    new_line = re.sub(r"16h[0-9a-fA-F]+", f"16h{adj_hex}", line, count=1)
                    replace_count += 1
                elif re.search(r"0x[0-9a-fA-F]+", line):
                    new_line = re.sub(r"0x[0-9a-fA-F]+", f"0x{adj_hex}", line, count=1)
                    replace_count += 1

            # 2. 检查 CFG22 控制位
            if cfg22_pattern.search(line):
                # 提取当前 CFG22 读数并置位第 13 位
                m_16h = re.search(r"16h([0-9a-fA-F]+)", line)
                m_0x = re.search(r"0x([0-9a-fA-F]+)", line)
                if m_16h:
                    curr_val = int(m_16h.group(1), 16)
                    new_val = self.set_cfg22_trim_enable(curr_val)
                    new_line = re.sub(r"16h[0-9a-fA-F]+", f"16h{new_val:04X}", line, count=1)
                    replace_count += 1
                elif m_0x:
                    curr_val = int(m_0x.group(1), 16)
                    new_val = self.set_cfg22_trim_enable(curr_val)
                    new_line = re.sub(r"0x[0-9a-fA-F]+", f"0x{new_val:04X}", line, count=1)
                    replace_count += 1

            updated_lines.append(new_line)

        return "\n".join(updated_lines), replace_count

    def process_mtp_template(self, template_path: str, output_path: str, adj_hex: str) -> bool:
        """
        读取 template_path，定位替换后写入 output_path
        """
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"MTP 标定模板未找到: {template_path}")

        with open(template_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        updated_content, replace_count = self.update_mtp_content(content, adj_hex)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

        return replace_count > 0
