# -*- coding: utf-8 -*-
"""
basic_centrifuge - Step 1 传感器原始数据处理器
支持多种加速度传感器与陀螺仪（TDK20685、SingleCrashSensor、ThreeAxAccSensor、MEMS 等）
的原始数据清洗、解析、换算与通道分组保存。
"""

import os
import sys
import re
import csv
from configparser import ConfigParser
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # 设置为非交互式后端
import matplotlib.pyplot as plt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)


class SensorProcessor:
    """Step 1 传感器数据清洗与通道分组处理器"""

    # 预设各设备模式的输出列名
    DEVICE_COLUMNS = {
        'TDK20685': ['GyroX', 'GyroY', 'GyroZ', 'AccX', 'AccY', 'AccZ'],
        'SingleThreeAxAccMEMS': ['x', 'y', 'z1', 'z2'],
        'SingleThreeAxAccMEMS2': ['x1', 'y1', 'z1', 'x2', 'y2', 'z2', 'z3', 'z4'],
        'SingleCrashSensor_ASICFab2': ['y'],
        'SingleCrashSensor_batch18': [f'S{i}' for i in range(1, 19)],
        'ThreeAxAccSensor': ['z2', 'z1', 'x', 'y'],
        'SingleCrashSensor': ['z2', 'z1', 'x', 'y'],
        'DoubleCrashSensor': ['z2', 'z1', 'x', 'y'],
    }

    def __init__(self, config_path=None):
        self.config = ConfigParser()
        self._load_config(config_path)
        self.device_mode = self.config.get('DEVICE', 'mode', fallback='SingleCrashSensor')
        self.input_file = ""
        self.output_file = ""
        self.grouped_data = {}

    def _load_config(self, custom_path=None):
        """安全加载配置文件，缺失时使用健壮默认值"""
        paths_to_try = [
            custom_path,
            os.path.join(os.path.dirname(__file__), 'config', 'settings.ini'),
            os.path.join(PROJECT_ROOT, 'config', 'settings.ini'),
        ]
        loaded = False
        for p in paths_to_try:
            if p and os.path.exists(p):
                try:
                    self.config.read(p, encoding='utf-8')
                    loaded = True
                    break
                except Exception:
                    pass

        if not loaded:
            if not self.config.has_section('DEVICE'):
                self.config.add_section('DEVICE')
            self.config.set('DEVICE', 'mode', 'SingleCrashSensor')
            if not self.config.has_section('TDK20685'):
                self.config.add_section('TDK20685')
            self.config.set('TDK20685', 'Acc_Range', '16.384')
            self.config.set('TDK20685', 'Gyro_Range', '655.36')

    def process(self, input_path: str, output_file: str):
        """主入口：设置路径并执行数据清洗与提取"""
        self.input_file = input_path
        self.output_file = output_file
        self.process_data()

    def process_data(self):
        """逐行解析原始文件并按 CAN ID 进行分组导出"""
        self.grouped_data = {}
        target_col_index = 20
        required_columns = 21

        try:
            with open(self.input_file, 'r', newline='', encoding='utf-8-sig', errors='ignore') as f:
                reader = csv.reader(f)
                for line_num, row in enumerate(reader):
                    try:
                        if len(row) < required_columns:
                            continue

                        current_str = row[target_col_index].strip()
                        result_row = self._parse_row_by_mode(current_str, line_num)

                        if result_row is not None:
                            col14_value = row[13].strip()
                            key = col14_value[2:] if col14_value.startswith(('0x', '0X')) else col14_value
                            if key in ['251', '259']:
                                continue
                            if key not in self.grouped_data:
                                self.grouped_data[key] = []
                            self.grouped_data[key].append(result_row)

                    except Exception as row_error:
                        print(f"第 {line_num + 1} 行解析异常: {row_error}")
                        continue

        except FileNotFoundError:
            print(f"错误：输入文件 {self.input_file} 不存在")
            return
        except Exception as e:
            print(f"处理数据异常: {e}")
            import traceback
            traceback.print_exc()
            return
        finally:
            self._save_grouped_results()

    def _parse_row_by_mode(self, current_str: str, line_num: int):
        """分派给对应的模式解析器"""
        mode = self.device_mode
        if mode == 'TDK20685':
            return self._process_tdk20685(current_str, line_num)
        elif mode == 'SingleThreeAxAccMEMS':
            return self._process_three_ax_acc_mems(current_str, line_num, num_groups=4)
        elif mode == 'SingleThreeAxAccMEMS2':
            return self._process_three_ax_acc_mems(current_str, line_num, num_groups=8)
        elif mode in ('ThreeAxAccSensor', 'DoubleCrashSensor'):
            return self._process_dual_byte_sensor(current_str, line_num)
        elif mode == 'SingleCrashSensor':
            return self._process_single_crash_sensor(current_str, line_num)
        elif mode == 'SingleCrashSensor_ASICFab2':
            return self._process_single_crash_sensor_asicfab2(current_str, line_num)
        elif mode == 'SingleCrashSensor_batch18':
            return self._process_single_crash_sensor_batch18(current_str, line_num)
        else:
            raise ValueError(f"不支持的设备模式: {mode}")

    def _get_column_names(self):
        return self.DEVICE_COLUMNS.get(self.device_mode, ['z2', 'z1', 'x', 'y'])

    def _save_grouped_results(self):
        """按分组保存清洗结果并自动生成时序图"""
        if not self.output_file:
            return

        for key, data in self.grouped_data.items():
            if not data or not key:
                continue

            base_path = os.path.splitext(self.output_file)[0]
            group_folder = f"{base_path}_{key}"
            os.makedirs(group_folder, exist_ok=True)

            folder_name = os.path.basename(group_folder)
            csv_path = os.path.join(group_folder, f"{folder_name}.csv")

            df = pd.DataFrame(data, columns=self._get_column_names())
            df.to_csv(csv_path, index=False)
            self._generate_plots(df, key=key, group_folder=group_folder)

    # --------------------------------------------------------------------------
    # 具体设备数据解码逻辑
    # --------------------------------------------------------------------------

    def _process_tdk20685(self, current_str: str, line_num: int):
        """处理 TDK20685 陀螺仪与加速度数据 (6通道)"""
        current_str = current_str.strip()
        # 跳过已知无效同步或全FF帧
        if re.match(r'^(01\s+00\s+00\s+00\s+00\s+00\s+00\s+00|ff\s+ff(\s+ff)+)$', current_str, re.IGNORECASE):
            return None

        parts = [p for p in re.split(r'\s+', current_str) if p]
        if len(parts) != 12:
            return None

        # 补码与十进制转换
        gyro_range = float(self.config.get('TDK20685', 'Gyro_Range', fallback='655.36'))
        acc_range = float(self.config.get('TDK20685', 'Acc_Range', fallback='16.384'))

        final_values = []
        for j in range(6):
            hex_pair = parts[2 * j] + parts[2 * j + 1]
            try:
                dec = int(hex_pair, 16)
                if dec >= 0x8000:
                    dec -= 0x10000
                # 前3路陀螺仪，后3路加速度计
                val = (dec * gyro_range / 32768.0) if j < 3 else (dec * acc_range / 32768.0)
                final_values.append(val)
            except ValueError:
                final_values.append(np.nan)

        return final_values if len(final_values) == 6 else None

    def _process_three_ax_acc_mems(self, current_str: str, line_num: int, num_groups: int = 4):
        """统一处理 SingleThreeAxAccMEMS (4组) 与 MEMS2 (8组)"""
        expected_len = num_groups * 8
        expected_parts = num_groups * 4

        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != expected_len:
            return None

        parts = re.split(r'\s+', current_str.strip())
        if len(parts) != expected_parts:
            return None

        combined = [''.join(parts[4 * j : 4 * j + 4]) for j in range(num_groups)]
        try:
            decimals = [int(h, 16) for h in combined]
            # 计算电容值 (pF)
            final_values = (np.array(decimals) * (4.096 / 8388608.0) - 4.096).tolist()
            return final_values if len(final_values) == num_groups else None
        except ValueError:
            return None

    def _process_dual_byte_sensor(self, current_str: str, line_num: int):
        """处理 ThreeAxAccSensor 与 DoubleCrashSensor（4个两字节16进制数）"""
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 16:
            return None

        parts = re.split(r'\s+', current_str.strip())
        if len(parts) != 8 or parts[2].lower() == 'ff':
            return None

        combined = [parts[2 * j] + parts[2 * j + 1] for j in range(4)]
        try:
            decimals = [int(h, 16) for h in combined]
            return decimals if len(decimals) == 4 else None
        except ValueError:
            return None

    def _process_single_crash_sensor(self, current_str: str, line_num: int):
        """处理 SingleCrashSensor 数据 (累加换算并返回4元素结构)"""
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 16:
            return [None, None, None, None]

        parts = re.split(r'\s+', current_str.strip())
        if len(parts) != 8 or parts[2].lower() == 'ff':
            return [None, None, None, None]

        try:
            val_5 = int(parts[4], 16) * 65536
            val_6_7 = int(parts[5] + parts[6], 16)
            total_sum = val_5 + val_6_7
            decimal_value = (total_sum * 4.096 / 8388608.0) - 4.096
            return [decimal_value, None, None, None]
        except ValueError:
            return [None, None, None, None]

    def _process_single_crash_sensor_asicfab2(self, current_str: str, line_num: int):
        """处理 SingleCrashSensor_ASICFab2 拼接前两列"""
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 16:
            return None

        parts = re.split(r'\s+', current_str.strip())
        if len(parts) != 8 or parts[0].lower() == 'ff':
            return None

        try:
            decimal_value = int(parts[0] + parts[1], 16)
            if decimal_value > 512:
                decimal_value -= 1024
            if decimal_value == 496:
                return None
            return [decimal_value]
        except ValueError:
            return None

    def _process_single_crash_sensor_batch18(self, current_str: str, line_num: int):
        """处理 SingleCrashSensor_batch18 (18通道)"""
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 96:
            return None

        parts = re.split(r'\s+', current_str.strip())
        if len(parts) != 48:
            return None

        combined = [parts[2 * j] + parts[2 * j + 1] for j in range(18)]
        try:
            decimals = [int(h, 16) for h in combined]
            # 补码转换并过滤 496
            processed = [
                None if x == 496 else (x - 1024 if x > 512 else x)
                for x in decimals
            ]
            return processed if len(processed) == 18 else None
        except ValueError:
            return None

    # --------------------------------------------------------------------------
    # 绘图逻辑
    # --------------------------------------------------------------------------

    def _generate_plots(self, df: pd.DataFrame, key: str = None, group_folder: str = ""):
        """生成时序波形图"""
        plt.rcParams['font.family'] = 'Times New Roman'
        plt.rcParams['font.size'] = 14
        plt.rcParams['lines.linewidth'] = 0.5

        for col in df.columns:
            if df[col].isna().all():
                continue

            plt.figure(figsize=(10, 6))
            ax = plt.gca()
            plt.plot(df[col], '-')
            plt.title(str(col))
            plt.xlabel('Number of Sampling Points / pcs')

            if self.device_mode == 'TDK20685':
                if str(col).startswith('Gyro'):
                    plt.ylabel('AngularVelocity / LSB')
                elif str(col).startswith('Acc'):
                    plt.ylabel('Acceleration / LSB')
                else:
                    plt.ylabel('Output / LSB')
            elif 'MEMS' in self.device_mode:
                plt.ylabel('Capacitance / pF')
            else:
                plt.ylabel('Output / LSB')

            plt.grid(True, linestyle='--', alpha=0.6)
            ax.set_xlim(left=0)

            base_name = f'Step1_output_data_{col}_filtered'
            filename = f'{base_name}_{key}.png' if key else f'{base_name}.png'
            plot_path = os.path.join(group_folder, filename)
            plt.savefig(plot_path, dpi=200, bbox_inches='tight')
            plt.close()
