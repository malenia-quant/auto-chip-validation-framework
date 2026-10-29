
import sys
import os
from configparser import ConfigParser  # 新增的导入语句
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
import re
import pandas as pd
import numpy as np
import csv
import matplotlib
matplotlib.use('Agg')  # 设置为非交互式后端

class SensorProcessor:

    def process(self, input_path, output_file):
        self.input_file = input_path
        self.output_file = output_file  # 新增字段存储完整输出路径
        self.process_data()

    def __init__(self):
        self.config = ConfigParser()
        # 修改为带编码的读取方式
        config_path = os.path.join(project_root, 'config/settings.ini')
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config.read_file(f)
        self.config.read(os.path.join(project_root, 'config/settings.ini'))
        self.device_mode = self.config['DEVICE']['mode']
        # 移除从配置文件读取路径的逻辑
        self.input_file = ""  # 初始化空路径
        self.output_folder = ""
        self.grouped_data = {}

    def process_data(self):
        grouped_data= self.grouped_data  # 存储不同分类的数据
        result = []
        try:
            # 使用csv模块逐行读取处理
            with open(self.input_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                for line_num, row in enumerate(reader):
                    try:
                        # 列数检查（根据设备模式动态判断）
                        required_columns = {
                            'TDK20685': 21,
                            'SingleThreeAxAccMEMS': 21,
                            'SingleThreeAxAccMEMS2': 21,
                            'ThreeAxAccSensor': 21,
                            'SingleCrashSensor': 21,
                            'SingleCrashSensor_ASICFab2': 21,
                            'DoubleCrashSensor': 21,
                            'SingleCrashSensor_batch18': 21
                        }.get(self.device_mode, 21)

                        if len(row) < required_columns:
                            print(f"第{line_num + 1}行列数不足{required_columns}，实际{len(row)}列，已跳过")
                            continue

                        # 动态获取目标列索引
                        target_col_index = {
                            'TDK20685': 20,
                            'SingleThreeAxAccMEMS': 20,
                            'SingleThreeAxAccMEMS2': 20,
                            'ThreeAxAccSensor': 20,
                            'SingleCrashSensor': 20,
                            'SingleCrashSensor_ASICFab2': 20,
                            'DoubleCrashSensor': 20,
                            'SingleCrashSensor_batch18': 20
                        }.get(self.device_mode, 20)
                        current_str = row[target_col_index].strip()

                        if self.device_mode == 'TDK20685':
                            result_row = self._process_tdk20685(current_str, line_num)
                        elif self.device_mode == 'SingleThreeAxAccMEMS':
                            result_row = self._process_single_three_ax_acc_mems(current_str, line_num)
                        elif self.device_mode == 'SingleThreeAxAccMEMS2':
                            result_row = self._process_single_three_ax_acc_mems2(current_str, line_num)
                        elif self.device_mode == 'ThreeAxAccSensor':
                            result_row = self._process_three_ax_acc_sensor(current_str, line_num)
                        elif self.device_mode == 'SingleCrashSensor':
                            result_row = self._process_single_crash_sensor(current_str, line_num)
                        elif self.device_mode == 'SingleCrashSensor_ASICFab2':
                            result_row = self._process_single_crash_sensor_asicfab2(current_str, line_num)
                        elif self.device_mode == 'DoubleCrashSensor':
                            result_row = self._process_double_crash_sensor(current_str, line_num)
                        elif self.device_mode == 'SingleCrashSensor_batch18':
                            result_row = self._process_single_crash_sensor_batch18(current_str, line_num)
                        else:
                            raise ValueError(f"不支持的设备模式: {self.device_mode}")

                        # 将数据按第14列值分组
                        col14_value = row[13].strip()
                        if result_row is not None:
                            key = col14_value[2:]  # 去掉前缀0x（如0x21a → 21a）
                            if key in ['251', '259']:
                                continue
                            result.append(result_row)

                            if key not in grouped_data:
                                grouped_data[key] = []
                            grouped_data[key].append(result_row)

                    except Exception as row_error:  # 捕获单行处理错误
                        print(f"第{line_num + 1}行处理失败：{str(row_error)}")
                        continue  # 跳过错误行继续执行

        except FileNotFoundError:
            print(f"错误：输入文件 {self.input_file} 不存在")
        except pd.errors.EmptyDataError:
            print(f"错误：文件 {self.input_file} 为空")
        except Exception as e:  # 捕获其他未预料的错误
            print(f"程序发生未预期错误：{str(e)}")
            import traceback
            traceback.print_exc()  # 打印完整堆栈信息

        finally:
            for key, data in grouped_data.items():
                if not data:
                    continue
                if not key:
                    print(f"警告：分组 key 为空，跳过该组数据")
                    continue  # [PASS] 创建分组专用文件夹
                base_path = os.path.splitext(self.output_file)[0]  # 原文件路径（如 output_data）
                group_folder = f"{base_path}_{key}"  # 新文件夹路径（如 output_data_21a）
                os.makedirs(group_folder, exist_ok=True)  # 创建文件夹（若已存在则跳过）

                # [PASS] 生成分组 CSV 文件
                folder_name = os.path.basename(group_folder)  # 获取文件夹名称（如 "output_data_21a"）
                new_output_path = os.path.join(group_folder, f"{folder_name}.csv")
                df = pd.DataFrame(data, columns=self._get_column_names())
                df.to_csv(new_output_path, index=False)
                # [PASS] 生成图片并保存到分组文件夹
                self._generate_plots(df, new_output_path, key=key, group_folder=group_folder)

    def _get_column_names(self):
        if self.device_mode == 'TDK20685':
            return ['GyroX', 'GyroY', 'GyroZ', 'AccX', 'AccY', 'AccZ']
        elif self.device_mode == 'SingleThreeAxAccMEMS':
            return ['x', 'y', 'z1', 'z2']
        elif self.device_mode == 'SingleThreeAxAccMEMS2':
            return ['x1', 'y1', 'z1', 'x2', 'y2', 'z2', 'z3', 'z4']
        elif self.device_mode == 'SingleCrashSensor_ASICFab2':
            return ['y']
        elif self.device_mode == 'SingleCrashSensor_batch18':
            return ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8', 'S9', 'S10', 'S11', 'S12', 'S13', 'S14', 'S15', 'S16', 'S17', 'S18']
            # return ['S1', 'S2', 'S3', 'S4', 'S5', 'S6']

        else:
            return ['z2', 'z1', 'x', 'y']

    def _process_tdk20685(self, current_str: str, line_num: int) -> list or None:
        """
        处理 TDK20685 设备模式的数据
        :param current_str: 当前行的原始字符串
        :param line_num: 行号（从0开始）
        :return: 处理后的数值列表（6个值）或 None（无效数据）
        """
        # 1. 去除前后空格
        current_str = current_str.strip()

        # 2. 跳过无效模式（01 00... 和 ff ff...）
        if re.match(r'^01\s+00\s+00\s+00\s+00\s+00\s+00\s+00$', current_str):
            print(f"第{line_num + 1}行：跳过 01 00... 模式")
            return None
        if re.match(r'^ff\s+ff\s+ff\s+ff\s+ff\s+ff\s+ff\s+ff$', current_str):
            print(f"第{line_num + 1}行：跳过 ff ff... 模式")
            return None
        if re.match(r'^ff\s+ff\s+ff\s+ff\s+ff\s+ff\s+ff\s+ff\s+ff\s+ff\s+ff\s+ff$', current_str):
            print(f"第{line_num + 1}行：跳过 ff ff... 模式")
            return None

        # 3. 移除所有空格并检查长度
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 4:
            print(f"第{line_num + 1}行：长度异常（应为4字符，实际：{len(stripped_str)}）")
            return None

        # 4. 分割字符串并过滤空元素
        parts = re.split('\s+', current_str)
        if len(parts) != 12:
            print(f"第{line_num + 1}行：分割异常（应为12列，实际：{len(parts)}）")
            parts = [p for p in parts if p]  # 过滤空元素
            if len(parts) != 12:
                print(f"第{line_num + 1}行：修复后仍不满足12列，跳过")
                return None


        # # 5. 检测到 parts[2] 为 'ff' 时跳过
        # # 放宽数据有效性检查 ★
        # # 检测到parts[2]为'ff'时直接跳过该行
        # if parts[2] == 'ff':
        #     print(f"第{line_num + 1}行：检测到 parts[2] 为 'ff'，跳过")
        #     return None

        # 6. 补码处理优化
        special_hex = set([f"{hex1}{hex2}"
                           for hex1 in '89abcdef'
                           for hex2 in '0123456789abcdef'])  # 修正补码范围
        need_twos_complement = [False] * 6

        # 检查特殊十六进制值
        for j in [0, 2, 4, 6, 8, 10]:  # 对应原始索引1,3,5,7,9,11
            hex_val = parts[j].lower()
            if hex_val in special_hex:
                group_idx = j // 2
                need_twos_complement[group_idx] = True

        # 7. 拼接十六进制字符串
        combined = []
        for j in range(6):
            idx = 2 * j  # 第一个元素的位置：0,2,4,6
            combined.append(parts[idx] + parts[idx + 1])  # 拼接两个两位字符串

        # 8. 转换为十进制并处理补码
        final_values = []
        for k in range(6):
            try:
                dec = int(combined[k], 16)
                if need_twos_complement[k]:
                    dec -= 65536
            except ValueError:
                print(f"第{line_num + 1}行第{k + 1}组转换失败")
                dec = np.nan

            # 应用不同计算公式（从配置文件获取参数）
            gyro_range = float(self.config.get('TDK20685', 'Gyro_Range', fallback='655.36'))
            acc_range = float(self.config.get('TDK20685', 'Acc_Range', fallback='16.384'))

            if k < 3:
                # final = dec
                final = dec * gyro_range / 32768 # 标准转换成陀螺仪角速度
            else:
                # final = dec
                final = dec * acc_range / 32768 # 标准转换成加计加速度
            final_values.append(final)
        # 9. 数据有效性检查
        if len(final_values) != 6:
            print(f"第{line_num + 1}行：转换后数据长度异常（应为6，实际：{len(final_values)}")
            return None
        return final_values

    def _process_single_three_ax_acc_mems(self, current_str: str, line_num: int) -> list or None:
        """
        处理 SingleThreeAxAccMEMS 设备模式的数据
        :param current_str: 当前行的原始字符串
        :param line_num: 行号（从0开始）
        :return: 处理后的数值列表（4个值）或 None（无效数据）
        """
        # 1. 移除所有空白字符并检查长度
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 32:
            print(f"第{line_num + 1}行：警告 - 去除空格后长度应为32（实际：{len(stripped_str)}）")
            return None    # 2. 使用正则表达式分割字符串（处理多个空格）
        parts = re.split('\s+', current_str.strip())
        if len(parts) != 16:
            print(f"第{line_num + 1}行：警告 - 分割后应为16列（实际：{len(parts)}）")
            return None    # 3. 组合为四个四位十六进制字符串
        combined = []
        for j in range(4):
            idx = 4 * j  # 第一个元素的位置：0,4,8,12
            combined.append(
                parts[idx] + parts[idx + 1] + parts[idx + 2] + parts[idx + 3]  # 拼接四个两位字符串
            )

        # 4. 转换为十进制并计算最终值
        try:
            decimals = [int(h, 16) for h in combined]
        except ValueError as e:
            print(f"第{line_num + 1}行：数据转换失败，可能包含非十六进制字符: {e}")
            return None

        final_values = np.array(decimals) * (4.096 / 8388608) - 4.096  # 计算最终值

        # 5. 数据有效性检查
        if len(final_values) != 4:
            print(f"第{line_num + 1}行：数据转换后长度不为4，无法处理")
            return None
        return final_values.tolist()  # 返回列表格式

    def _process_single_three_ax_acc_mems2(self, current_str: str, line_num: int) -> list or None:
        """
        处理 SingleThreeAxAccMEMS2 设备模式的数据（数据量翻倍）
        :param current_str: 当前行的原始字符串
        :param line_num: 行号（从0开始）
        :return: 处理后的数值列表（8个值）或 None（无效数据）
        """
        # 1. 移除所有空白字符并检查长度
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 64:
            print(f"第{line_num + 1}行：警告 - 去除空格后长度应为64（实际：{len(stripped_str)}）")
            return None

        # 2. 使用正则表达式分割字符串（处理多个空格）
        parts = re.split(r'\s+', current_str.strip())
        if len(parts) != 32:
            print(f"第{line_num + 1}行：警告 - 分割后应为32列（实际：{len(parts)}）")
            return None

        # 3. 组合为八个四位十六进制字符串
        combined = []
        for j in range(8):  # 8组数据
            idx = 4 * j  # 起始位置：0,4,8,...,28
            combined.append(
                parts[idx] + parts[idx + 1] + parts[idx + 2] + parts[idx + 3]  # 每组4个两位十六进制
            )

        # 4. 转换为十进制并计算最终值
        try:
            decimals = [int(h, 16) for h in combined]
        except ValueError as e:
            print(f"第{line_num + 1}行：数据转换失败，可能包含非十六进制字符: {e}")
            return None

        final_values = np.array(decimals) * (4.096 / 8388608) - 4.096  # 保持原计算方式

        # 5. 数据有效性检查
        if len(final_values) != 8:
            print(f"第{line_num + 1}行：数据转换后长度不为8，无法处理")
            return None

        return final_values.tolist()

    def _process_three_ax_acc_sensor(self, current_str: str, line_num: int) -> list or None:
        """
        处理 ThreeAxAccSensor 设备模式的数据
        :param current_str: 当前行的原始字符串
        :param line_num: 行号（从0开始）
        :return: 处理后的数值列表（4个值）或 None（无效数据）
        """
        # 1. 移除所有空白字符并检查长度
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 16:
            print(f"第{line_num + 1}行：警告 - 去除空格后长度应为16（实际：{len(stripped_str)}）")
            return None

        # 2. 使用正则表达式分割字符串（处理多个空格）
        parts = re.split('\s+', current_str.strip())
        if len(parts) != 8:
            print(f"第{line_num + 1}行：警告 - 分割后应为8列（实际：{len(parts)}）")
            return None

        # 3. 检测到 parts[2] 为 'ff' 时跳过
        if parts[2] == 'ff':
            print(f"第{line_num + 1}行：检测到 parts[2] 为 'ff'，跳过")
            return None

        # 4. 组合为四个两位十六进制字符串
        combined = []
        for j in range(4):
            idx = 2 * j  # 第一个元素的位置：0,2,4,6
            combined.append(parts[idx] + parts[idx + 1])  # 拼接两个两位字符串    # 5. 转换为十进制并计算最终值
        try:
            decimals = [int(h, 16) for h in combined]
        except ValueError as e:
            print(f"第{line_num + 1}行：数据转换失败，可能包含非十六进制字符: {e}")
            return None

        final_values = np.array(decimals)  #恢复LSB码值
        # final_values = np.array(decimals) * (5 / 65536)  # 第一次流片住转换电压值

        # 6. 数据有效性检查
        if len(final_values) != 4:
            print(f"第{line_num + 1}行：数据转换后长度不为4，无法处理")
            return None

        return final_values.tolist()  # 返回列表格式

    # def _process_single_crash_sensor(self, current_str: str, line_num: int) -> list or None:
    #     """
    #     处理 SingleCrashSensor 设备模式的数据
    #     :param current_str: 当前行的原始字符串
    #     :param line_num: 行号（从0开始）
    #     :return: 处理后的数值列表（4个值）或 None（无效数据）
    #     """
    #     # 1. 移除所有空白字符并检查长度
    #     stripped_str = re.sub(r'\s+', '', current_str)
    #     if len(stripped_str) != 16:
    #         print(f"第{line_num + 1}行：警告 - 去除空格后长度应为16（实际：{len(stripped_str)}）")
    #         return None  # 2. 使用正则表达式分割字符串（处理多个空格）
    #     parts = re.split('\s+', current_str.strip())
    #     if len(parts) != 8:
    #         print(f"第{line_num + 1}行：警告 - 分割后应为8列（实际：{len(parts)}）")
    #         return None  # 3. 检测到 parts[2] 为 'ff' 时跳过
    #     if parts[2] == 'ff':
    #         print(f"第{line_num + 1}行：检测到 parts[2] 为 'ff'，跳过")
    #         return None  # 4. 组合为四个两位十六进制字符串
    #     combined = []
    #     for j in range(4):
    #         idx = 2 * j  # 第一个元素的位置：0,2,4,6
    #         combined.append(parts[idx] + parts[idx + 1])  # 拼接两个两位字符串
    #
    #     # 5. 转换为十进制并计算最终值
    #     try:
    #         decimals = [int(h, 16) for h in combined]
    #     except ValueError as e:
    #         print(f"第{line_num + 1}行：数据转换失败，可能包含非十六进制字符: {e}")
    #         return None
    #
    #     final_values = np.array(decimals)  # 计算最终值
    #     # final_values = np.array(decimals) * (5 / 65536)  # 计算最终值
    #
    #     # 6. 数据有效性检查
    #     if len(final_values) != 4:
    #         print(f"第{line_num + 1}行：数据转换后长度不为4，无法处理")
    #         return None
    #
    #     return final_values.tolist()  # 返回列表格式

    def _process_single_crash_sensor(self, current_str: str, line_num: int) -> list or None:
        # 1. 移除所有空白字符并检查长度
        stripped_str = re.sub(pattern=r'\s+', repl='', string=current_str)
        if len(stripped_str) != 16:
            # 增加对表头的静默拦截，避免误报
            if 'DATA' in current_str.upper():
                print(f"第{line_num + 1}行: 识别为表头 '{current_str.strip()}'，自动跳过解析")
            else:
                print(f"第{line_num + 1}行: 警告 - 去除空格后长度应为16 (实际: {len(stripped_str)}) ")
            # 【关键修改】异常退出也必须严格返回 4 个元素的占位列表
            return [None, None, None, None]  # 2. 使用正则表达式分割字符串 (处理多个空格)

        parts = re.split(pattern=r'\s+', string=current_str.strip())
        if len(parts) != 8:
            print(f"第{line_num + 1}行: 警告 - 分割后应为8列 (实际: {len(parts)}) ")
            return [None, None, None, None]  # 3. 检测到 parts[2] 为 'ff' 时跳过

        if parts[2] == 'ff':
            print(f"第{line_num + 1}行: 检测到 parts[2] 为 'ff', 跳过")
            return [None, None, None, None]  # 4. 组合为四个两位十六进制字符串

        # 新增变量获取
        col_5_hex = parts[4]
        combined_6_7_hex = parts[5] + parts[6]

        # 5. 转换为十进制并计算最终值
        try:
            # 转换第五列(parts[4])为十进制并 * 65536
            val_5 = int(col_5_hex, 16) * 65536

            # 6列7列拼接(parts[5]+parts[6])转换十进制
            val_6_7 = int(combined_6_7_hex, 16)

            # 两个数累加 * 4.096 / 8388608 - 4.096 (保持浮点数不转整数)
            total_sum = val_5 + val_6_7
            decimal_value = (total_sum * 4.096 / 8388608) - 4.096

            # 【核心架构适配修改】使用 None 进行占位填充，凑齐 4 个元素
            decimals = [decimal_value, None, None, None]

        except ValueError as e:
            print(f"第{line_num + 1}行: 数据转换失败，可能包含非十六进制字符: {e}")
            return [None, None, None, None]

        final_values = np.array(decimals, dtype=object)  # 计算最终值
        # # final_values = np.array(decimals) * (5 / 65536) # 计算最终值

        # 6. 数据有效性检查
        if len(final_values) != 4:
            print(f"第{line_num + 1}行: 数据转换后长度不为4, 无法处理")
            return [None, None, None, None]

        return final_values.tolist()  # 返回列表格式

    def _process_single_crash_sensor_asicfab2(self, current_str: str, line_num: int) -> list or None:
        """
        处理 SingleCrashSensor 设备模式的数据（拼接第一列和第二列）
        :param current_str: 当前行的原始字符串
        :param line_num: 行号（从0开始）
        :return: 处理后的数值列表（1个值）或 None（无效数据）
        """
        # 1. 移除所有空白字符并检查长度
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 16:
            print(f"第{line_num + 1}行：警告 - 去除空格后长度应为16（实际：{len(stripped_str)}）")
            return None  # 2. 使用正则表达式分割字符串（处理多个空格）
        parts = re.split(r'\s+', current_str.strip())
        if len(parts) != 8:
            print(f"第{line_num + 1}行：警告 - 分割后应为8列（实际：{len(parts)}）")
            return None  # 3. 检测到 parts[0] 为 'ff' 时跳过
        if parts[0] == 'ff':
            print(f"第{line_num + 1}行：检测到 parts[0] 为 'ff'，跳过")
            return None  # 4. 拼接第一列和第二列（两位 + 两位 = 四位十六进制字符串）
        combined = parts[0] + parts[1]

        # 5. 转换为十进制并计算最终值
        try:
            decimal_value = int(combined, 16)
        except ValueError as e:
            print(f"第{line_num + 1}行：数据转换失败，可能包含非十六进制字符: {e}")
            return None  # 6. 如果值大于 512，减去 1024
        if decimal_value > 512:
            decimal_value -= 1024  # 7. 跳过值为 496 的情况
        if decimal_value == 496:
            print(f"第{line_num + 1}行：转换后的值为496，跳过")
        # if decimal_value == -492:
        #     print(f"第{line_num + 1}行：转换后的值为-492，跳过")
        # if decimal_value == 512:
        #     print(f"第{line_num + 1}行：转换后的值为512，跳过")

            return None  # 8. 数据有效性检查（确保只处理一个值）
        if not isinstance(decimal_value, (int, float)):
            print(f"第{line_num + 1}行：数据转换后非有效数值")
            return None  # 9. 返回单个值的列表
        return [decimal_value]

    def _process_double_crash_sensor(self, current_str: str, line_num: int) -> list or None:
        """
        处理 DoubleCrashSensor 设备模式的数据
        :param current_str: 当前行的原始字符串
        :param line_num: 行号（从0开始）
        :return: 处理后的数值列表（4个值）或 None（无效数据）
        """
        # 1. 移除所有空白字符并检查长度
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 16:
            print(f"第{line_num + 1}行：警告 - 去除空格后长度应为16（实际：{len(stripped_str)}）")
            return None

        # 2. 使用正则表达式分割字符串（处理多个空格）
        parts = re.split('\s+', current_str.strip())
        if len(parts) != 8:
            print(f"第{line_num + 1}行：警告 - 分割后应为8列（实际：{len(parts)}）")
            return None

        # 3. 检测到 parts[2] 为 'ff' 时跳过
        if parts[2] == 'ff':
            print(f"第{line_num + 1}行：检测到 parts[2] 为 'ff'，跳过")
            return None

        # 4. 组合为四个两位十六进制字符串
        combined = []
        for j in range(4):
            idx = 2 * j  # 第一个元素的位置：0,2,4,6
            combined.append(parts[idx] + parts[idx + 1])  # 拼接两个两位字符串    # 5. 转换为十进制并计算最终值
        try:
            decimals = [int(h, 16) for h in combined]
        except ValueError as e:
            print(f"第{line_num + 1}行：数据转换失败，可能包含非十六进制字符: {e}")
            return None

        final_values = np.array(decimals)   # 计算最终值    # 6. 数据有效性检查
        # final_values = np.array(decimals) * (5 / 65536)  # 计算最终值    # 6. 数据有效性检查

        if len(final_values) != 4:
            print(f"第{line_num + 1}行：数据转换后长度不为4，无法处理")
            return None

        return final_values.tolist()  # 返回列表格式

    def _process_single_crash_sensor_batch18(self, current_str: str, line_num: int) -> list or None:
        """
        处理 DoubleCrashSensor 设备模式的数据
        :param current_str: 当前行的原始字符串
        :param line_num: 行号（从0开始）
        :return: 处理后的数值列表（4个值）或 None（无效数据）
        """
        # 1. 移除所有空白字符并检查长度
        stripped_str = re.sub(r'\s+', '', current_str)
        if len(stripped_str) != 96:
            print(f"第{line_num + 1}行：警告 - 去除空格后长度应为96（实际：{len(stripped_str)}）")
            return None

        # 2. 使用正则表达式分割字符串（处理多个空格）
        parts = re.split('\s+', current_str.strip())
        if len(parts) != 48:
            print(f"第{line_num + 1}行：警告 - 分割后应为48列（实际：{len(parts)}）")
            return None

        # # 3. 检测到 parts[2] 为 'ff' 时跳过
        # if parts[2] == 'ff':
        #     print(f"第{line_num + 1}行：检测到 parts[2] 为 'ff'，跳过")
        #     return None

        # 4. 组合为四个两位十六进制字符串
        combined = []
        for j in range(18):
            idx = 2 * j  # 第一个元素的位置：0,2,4,6
            combined.append(parts[idx] + parts[idx + 1])  # 拼接两个两位字符串

        # 5. 转换为十进制并计算最终值
        try:
            decimals = [int(h, 16) for h in combined]  # 转换为整数列表
        except ValueError as e:
            print(f"第{line_num + 1}行：数据转换失败，可能包含非十六进制字符: {e}")
            return None  # [PASS] 修复1：对每个元素处理（>512则减1024）
        decimals = [x - 1024 if x > 512 else x for x in decimals]
        # 关键修改：将496替换为None（不是跳过整行！）
        decimals = [None if x == 496 else x for x in decimals]  # 496 → None

        # 6. 数据有效性检查
        final_values = np.array(decimals)   # 计算最终值

        if len(final_values) != 18:
            print(f"第{line_num + 1}行：数据转换后长度不为18,（实际：{len(final_values)}）,无法处理")
            return None

        # # 6.1 筛选第0、3、6、9、12、15组数据，并重新赋值给final_values
        # selected_indices = [0, 3, 6, 9, 12, 15]  # 需要筛选的索引
        # final_values = [final_values[i] for i in selected_indices]  # 重新赋值给final_values
        # if len(final_values) != 6:
        #     print(f"第{line_num + 1}行：数据筛选后长度不为6,（实际：{len(final_values)}）,无法处理")
        #     return None

        # 6.2 筛选第0、3、6、9、12、15组数据，并重新赋值给final_values
        selected_indices = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]  # 需要筛选的索引
        final_values = [final_values[i] for i in selected_indices]  # 重新赋值给final_values
        if len(final_values) != 18:
            print(f"第{line_num + 1}行：数据筛选后长度不为6,（实际：{len(final_values)}）,无法处理")
            return None

        return final_values  # 返回列表格式

    def _get_unit(self, column_name):
        unit_map = {
            'Acc': 'g',
            'Gyro': 'dps',
            'Crash': 'g',
            'Temperature': '℃'
        }
        for key in unit_map:
            if key in column_name:
                return unit_map[key]
        return ''

    def _generate_plots(self, df, output_path, key=None, group_folder=None):
        import matplotlib.pyplot as plt
        plt.rcParams['font.family'] = 'Times New Roman'
        plt.rcParams['font.size'] = 14
        plt.rcParams['lines.linewidth'] = 0.5
        for col in df.columns:
            # 检查该列是否全部为空
            if df[col].isna().all():
                print(f"警告：列 {col} 全部为空，跳过图片生成")
                continue

            plt.figure(figsize=(10, 6))
            ax = plt.gca()
            plt.plot(df[col], '-')
            plt.title(col)
            plt.xlabel('Number of Sampling Points / pcs')
            if self.device_mode == 'TDK20685':
                if col.startswith('Gyro'):
                    plt.ylabel('AngularVelocity / LSB') # LSB值
                    # plt.ylabel('AngularVelocity / °/s')  # 角速度值
                elif col.startswith('Acc'):
                    plt.ylabel('Acceleration / LSB') # LSB值
                    # plt.ylabel('Acceleration / g') # 加速度值
                else:
                    plt.ylabel('Output / LSB')
                    # plt.ylabel('Output Voltage / V')
            elif self.device_mode == 'SingleThreeAxAccMEMS':
                plt.ylabel('Capacitance / pF')
            elif self.device_mode == 'SingleThreeAxAccMEMS2':
                plt.ylabel('Capacitance / pF')
            else:
                plt.ylabel('Output / LSB')
            plt.grid(True, linestyle='--', alpha=0.6)
            ax.set_xlim(left=0)
            # [PASS] 使用传递的 group_folder
            base_name = f'Step1_output_data_{col}_filtered'
            if key:
                filename = f'{base_name}_{key}.png'
            else:
                filename = f'{base_name}.png'
            plot_path = os.path.join(group_folder, filename)  # [PASS] 正确拼接路径
            plt.savefig(plot_path, dpi=300, bbox_inches='tight')
            plt.close()


