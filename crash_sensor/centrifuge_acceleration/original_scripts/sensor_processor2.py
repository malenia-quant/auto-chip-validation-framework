# sensor_processor2.py
import os
import math  # 新增数学库用于检查NaN
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
# import shutil
from scipy.signal import find_peaks
from scipy.stats import linregress
from configparser import ConfigParser
from scipy import optimize  # 用于曲线拟合


plt.rcParams['font.family'] = 'Times New Roman'
plt.rcParams['font.size'] = 12
plt.rcParams['lines.linewidth'] = 0.5
plt.rcParams['axes.unicode_minus'] = False


class Step2Processor:
    def __init__(
            self,
            zero_division_p: float,  # 新增正阈值
            zero_division_n: float,  # 新增负阈值
            upDown_division: float,  # 新增参数
            fixed_step: float,
            device_mode: str,
            accelerationstep_select: str,
            custom_sequence: str,
            window_size=10,
            columns=None,
            config_path='config/settings.ini'
    ):
        # 1. 先赋值 device_mode，确保 _init_device_params() 可以访问
        self.device_mode = device_mode  # 2. 调用 _init_device_params() 初始化设备相关参数
        self._init_device_params()
        self.zero_division_p = zero_division_p
        self.zero_division_n = zero_division_n

        # 3. 初始化其他属性
        self.window_size = window_size  # 初始化属性
        self.upDown_division = upDown_division  # 新增属性
        self.fixed_step = fixed_step
        self.accelerationstep_select = accelerationstep_select
        self.custom_sequence = [float(x) for x in custom_sequence.split(',')]
        self.columns = int(columns) if columns and str(columns).isdigit() else None
        self.config = ConfigParser()
        self.config.read(config_path, encoding='utf-8')

        # 4. 图形参数初始化
        plt.rcParams['font.family'] = 'Times New Roman'
        plt.rcParams['font.size'] = 12
        print(f"Initialized columns_to_process: {self.columns_to_process}")

    def _init_device_params(self):
        """根据设备模式初始化处理参数"""
        if self.device_mode in ['SingleCrashSensor', 'DoubleCrashSensor']:
            self.columns_to_process = ['z2', 'z1', 'x', 'y']
        elif self.device_mode in ['ThreeAxAccSensor']:
            self.columns_to_process = ['z2', 'z1', 'x', 'y']
        elif self.device_mode in ['TDK20685']:
            self.columns_to_process = ['GyroX', 'GyroY', 'GyroZ', 'AccX', 'AccY', 'AccZ']
        elif self.device_mode == 'SingleThreeAxAccMEMS':
            self.columns_to_process = ['x', 'y', 'z1', 'z2']
        elif self.device_mode == 'SingleThreeAxAccMEMS2':
            self.columns_to_process = ['x1', 'y1', 'z1', 'x2', 'y2', 'z2', 'z3', 'z4']
        elif self.device_mode == 'IMUFab2':
            self.columns_to_process = ['AccX', 'AccY', 'AccZ','AccZC', 'GyroX', 'GyroY', 'GyroZ', 'Temperature']
        elif self.device_mode == 'SingleCrashSensor_ASICFab2':
            self.columns_to_process = ['y']
        elif self.device_mode == 'SingleCrashSensor_batch18':
            self.columns_to_process = ['p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8', 'p9', 'p10', 'p11', 'p12', 'p13', 'p14', 'p15', 'p16', 'p17', 'p18']
        else:
            self.columns_to_process = ['z2', 'z1', 'x', 'y']

        if self.device_mode in ['SingleCrashSensor', 'DoubleCrashSensor']:
            self.start_idx =2500
            self.end_trim = 1500
            self.min_length = 1000
            self.window_size = 50  # 为该模式设置滑动窗口大小
        elif self.device_mode in ['SingleCrashSensor_ASICFab2']:
            self.start_idx = 2500
            self.end_trim = 2000
            self.min_length = 2000
            self.window_size = 50  # 为该模式设置滑动窗口大小
        elif self.device_mode in ['ThreeAxAccSensor']:
            self.start_idx = 100
            self.end_trim = 100
            self.min_length = 100
            self.window_size = 50  # 为该模式设置滑动窗口大小
        elif self.device_mode in ['SingleThreeAxAccMEMS']:
            self.start_idx = 20
            self.end_trim = 20
            self.min_length = 10
            self.window_size = 50  # 为该模式设置滑动窗口大小
        elif self.device_mode in ['SingleThreeAxAccMEMS2']:
            self.start_idx = 20
            self.end_trim = 20
            self.min_length = 10
            self.window_size = 50  # 为该模式设置滑动窗口大小
        elif self.device_mode in ['IMUFab2']:
            self.start_idx = 50
            self.end_trim = 20
            self.min_length = 10
            self.window_size = 50  # 为该模式设置滑动窗口大小
        elif self.device_mode in ['SingleCrashSensor_batch18']:
            self.start_idx = 2500
            self.end_trim = 1000
            self.min_length = 1000
            self.window_size = 50  # 为该模式设置滑动窗口大小
        else:
            self.start_idx = 300
            self.end_trim = 100
            self.min_length = 400
            self.window_size = 50  # 为该模式设置滑动窗口大小
            self.columns_to_process = ['z2', 'z1', 'x', 'y']

    def _get_mid_threshold(self):
        return (self.zero_division_p + self.zero_division_n) / 2

    def process(self, input_path, output_path):
        try:
            # 边沿检测等核心步骤应直接处理原始文件
            # 删除错误的分块处理逻辑
            # ----------------- 修正后代码 -----------------
            # Step 2.1 边沿检测
            edges_data = self.process_edges(input_path, self.zero_division_p, self.zero_division_n)
            # Step 2.2 数据裁剪
            cropped_data = self.process_cropping(edges_data)
            # Step 2.3 计算平均值
            avg_file = self.calculate_averages(cropped_data)
            # Step 2.4 生成阶梯图
            self.create_staircase_plots(
                output_dir=os.path.dirname(output_path),
                fixed_step=self.fixed_step
            )
            # Step 2.5 非线性度分析
            self.nonlinear_analysis(
                output_dir=os.path.dirname(avg_file),
                accelerationstep_select=self.accelerationstep_select,
                fixed_step=self.fixed_step,
                custom_sequence=self.custom_sequence,
                columns_usedforfitting=self.columns
            )

            self.calculate_rms_noise(os.path.dirname(output_path))
            # 合并结果保存
            # self._save_final_output(output_path)
            return True
        except Exception as e:
            import traceback
            traceback.print_exc()  # 添加错误堆栈打印
            raise RuntimeError(f"处理失败: {str(e)}")


    def process_step2(self, input_path, accelerationstep_select,
                      fixed_step, custom_sequence, columns_usedforfitting):
        """执行完整的step2处理流程"""
        try:
            # Step 2.1 处理边沿检测
            edges_data = self.process_edges(input_path, self.zero_division_p, self.zero_division_n)

            # Step 2.2 数据裁剪
            cropped_data = self.process_cropping(edges_data)

            # Step 2.3 计算平均值
            avg_file = self.calculate_averages(cropped_data)

            # Step 2.4 生成阶梯图
            merged_files = self.create_staircase_plots(
                output_dir=os.path.dirname(input_path),  # 获取输出目录
                fixed_step=fixed_step
            )

            # Step 2.5 非线性度分析
            analysis_files = self.nonlinear_analysis(avg_file, accelerationstep_select,
                                                     fixed_step, custom_sequence,
                                                     columns_usedforfitting)

            return {
                'edges_data': edges_data,
                'avg_file': avg_file,
                'merged_files': merged_files,
                'analysis_files': analysis_files
            }

        except Exception as e:
            raise RuntimeError(f"Step2处理失败: {str(e)}")

    def process_edges(self, input_path, zero_division_p, zero_division_n):
        """ 边缘检测处理（步骤2-1） """
        # 读取输入文件
        try:
            if input_path.endswith('.csv'):
                data = pd.read_csv(input_path)
                rms_path = os.path.join(os.path.dirname(input_path), "rms_og.csv")
                # 修改点：使用 .iloc[1000:6000] 获取第 1000 到 6000 行（不含第 6000 行）
                data.iloc[1000:6000].to_csv(rms_path, index=False)
                print(f"已生成1000到6000行文件: {rms_path}")
            else:
                raise ValueError("Unsupported file format")
        except Exception as e:
            raise RuntimeError(f"读取文件失败: {str(e)}")

        output_dir = os.path.join(os.path.dirname(input_path))
        columns = self.columns_to_process
        edge_data = {}
        valid_columns = 0 # 统计有效列数

        for col in columns:
            if col not in data.columns:
                print(f"警告: 数据中缺少 {col} 列，跳过处理")
                continue


            data_col = data[col].values

            # [修改点1：优化性能] 移除冗余的第二次卷积计算，复用底层平滑数据
            smoothed_data = np.convolve(data_col, np.ones(self.window_size) / self.window_size, mode='valid')
            filtered_a = smoothed_data.copy()
            filtered_b = smoothed_data.copy()

            # 应用零位分割
            filtered_a[filtered_a < self.zero_division_p] = self.zero_division_p
            filtered_b[filtered_b > self.zero_division_n] = self.zero_division_n

            # 检测边缘
            rise_edges_a = \
            np.where((filtered_a[:-1] == self.zero_division_p) & (filtered_a[1:] > self.zero_division_p))[0] + 1
            fall_edges_a = \
            np.where((filtered_a[:-1] > self.zero_division_p) & (filtered_a[1:] == self.zero_division_p))[0] + 1
            # 检测边缘
            fall_edges_b = \
            np.where((filtered_b[:-1] == self.zero_division_n) & (filtered_b[1:] < self.zero_division_n))[0] + 1
            rise_edges_b = \
            np.where((filtered_b[:-1] < self.zero_division_n) & (filtered_b[1:] == self.zero_division_n))[0] + 1

            # 提取数据段
            segments = []
            max_length = 0

            # [修改点2：重构开仓提取逻辑] 废弃基于长度的 if-elif 结构，废弃盲目的 zip 匹配。
            # 引入游标遍历逻辑，确保每一次配对都是时间序上合法的 (起点索引 < 终点索引)，避免因错位导致的 NumPy 空切片问题。

            # 处理A类边缘的数据段 (正向台阶：上升 -> 下降)
            i, j = 0, 0
            while i < len(rise_edges_a) and j < len(fall_edges_a):
                rise_idx = rise_edges_a[i]
                fall_idx = fall_edges_a[j]

                if rise_idx < fall_idx:
                    # 找到合法的上升-下降对
                    segment = data_col[rise_idx: fall_idx + self.window_size]
                    segments.append(segment)
                    max_length = max(max_length, len(segment))
                    i += 1
                    j += 1
                else:
                    # 如果下降沿在上升沿之前（通常是起始高位导致），废弃该无效的下降沿
                    j += 1

            # 处理B类边缘的数据段 (负向台阶：下降 -> 上升)
            m, n = 0, 0
            while m < len(fall_edges_b) and n < len(rise_edges_b):
                fall_idx = fall_edges_b[m]
                rise_idx = rise_edges_b[n]

                if fall_idx < rise_idx:
                    # 找到合法的下降-上升对
                    segment = data_col[fall_idx: rise_idx + self.window_size]
                    segments.append(segment)
                    max_length = max(max_length, len(segment))
                    m += 1
                    n += 1
                else:
                    # 如果上升沿在下降沿之前，废弃该无效的上升沿
                    n += 1

            # 数据有效性检查
            if not segments:
                print(f"警告：{col} 未生成有效数据段，跳过处理")
                edge_data[col] = None
                continue

            # 标准化数据长度
            padded_segments = []
            for seg in segments:
                if len(seg) < max_length:
                    pad = np.full(max_length - len(seg), np.nan)
                    padded_segments.append(np.concatenate([seg, pad]))
                else:
                    padded_segments.append(seg)

            # 保存结果
            output_df = pd.DataFrame(np.column_stack(padded_segments),
                                     columns=[f'Interval{i + 1}' for i in range(len(padded_segments))])

            output_path = os.path.join(output_dir, f"{col}_between_edges.csv")
            output_df.to_csv(output_path, index=False)
            edge_data[col] = output_path
            print(f"生成边缘数据文件: {output_path}")

        return edge_data

    def process_cropping(self, edge_data):
        """ 数据裁剪处理 (步骤2-2) """
        processed_data = {}
        for col, file_path in edge_data.items():
            try:
                df = pd.read_csv(file_path)
            except Exception as e:
                print(f"读取{file_path}失败: {str(e)}")
                continue

            # 新增列级有效性检查容器
            valid_columns = pd.DataFrame()

            print(f"\n[DEBUG]正在处理文件: {col}")
            print(f" -> 原始数据行数: {len(df)}")
            print(f" -> 当前参数设置: Start={self.start_idx}, EndTrim={self.end_trim}, MinLen={self.min_length}")

            # 废弃无用变量，保留在此作为历史参考
            # cropped = pd.DataFrame()

            for col_name in df.columns:
                # 裁剪当前列数据
                # [优化修复] 移除了外层无条件的切片赋值，避免重复计算和 :-0 带来的潜在错误
                if self.end_trim > 0:
                    cropped_col = df[col_name].iloc[self.start_idx:- self.end_trim].dropna()
                else:
                    cropped_col = df[col_name].iloc[self.start_idx:].dropna()
                print(f" -> 列'{col_name}'裁剪剩余行数: {len(cropped_col)}")

                # 单列有效性检查（新增核心逻辑）
                if len(cropped_col) > self.min_length:
                    valid_columns[col_name] = cropped_col
                else:
                    print(f"警告：列 {col_name} 裁剪后剩余数据{len(cropped_col)}，小于最小要求{self.min_length}行，已跳过")

            # 全列检查逻辑保留（兼容原有逻辑）
            if valid_columns.empty:
                print(f"警告：{col} 所有列均无效，跳过该文件")
                continue

            # --- [新增逻辑] 裁切验证完成后，按每列均值从小到大排序 ---
            # 计算有效列的均值 (仅限数值类型防止报错)
            col_means = valid_columns.mean(numeric_only=True)
            # 按照均值升序排列，获取新的列名顺序
            sorted_cols = col_means.sort_values(ascending=True).index
            # 按照新顺序重新排列 DataFrame
            valid_columns = valid_columns[sorted_cols]
            # --------------------------------------------------------

            # 仅保存有效列
            output_path = file_path.replace('_between_edges.csv', '_between_edges_processed.csv')
            valid_columns.to_csv(output_path, index=False)
            processed_data[col] = output_path

        return processed_data

    def calculate_averages(self, processed_data):
        # 收集所有通道的平均值数据
        channel_data = {}
        max_intervals = 0

        for col, file_path in processed_data.items():
            try:
                df = pd.read_csv(file_path)
                # 计算每列（Interval）的平均值
                means = df.mean().tolist()
                channel_data[col] = means
                max_intervals = max(max_intervals, len(means))
            except Exception as e:
                print(f"处理{col}时出错: {str(e)}")
                continue

        # 构建行式数据结构
        rows = []
        columns = self.columns_to_process   # 固定列顺序

        for col in columns:
            if col not in channel_data:
                print(f"警告：缺少{col}通道数据")
                continue

            # 获取该通道的平均值并填充NaN
            means = channel_data[col]
            padded_means = means + [np.nan] * (max_intervals - len(means))

            # 构建行数据
            row = [col] + padded_means
            rows.append(row)

        # 创建列名
        column_names = ['Column'] + [f'Interval{i+1}' for i in range(max_intervals)]

        # 创建DataFrame
        result_df = pd.DataFrame(rows, columns=column_names)

        # 保存结果
        output_dir = os.path.dirname(list(processed_data.values())[0])
        output_path = os.path.join(output_dir, 'final_between_edges_processed_average.csv')
        result_df.to_csv(output_path, index=False)

        print(f"生成平均值文件（行式结构）: {output_path}")
        return output_path


    def create_staircase_plots(self, output_dir, fixed_step):
        """
        生成阶梯图并保存合并数据
        参数：
        output_dir: 输出目录路径
        fixed_step: 固定步进值（来自GUI的fixed_step_var）
        """
        columns = self.columns_to_process  # 六列数据
        for col in columns:
            # 构建输入文件路径
            input_path = os.path.join(output_dir, f"{col}_between_edges_processed.csv")

            if not os.path.exists(input_path):
                print(f"警告：{input_path} 文件不存在，跳过该列")
                continue

            try:
                # 读取处理后的数据
                data = pd.read_csv(input_path)
                merged_data = []
                interval_lengths = []

                # 合并所有Interval数据
                for col_name in data.columns:
                    valid_data = data[col_name].dropna().values
                    merged_data.extend(valid_data)
                    interval_lengths.append(len(valid_data))

                # 保存合并数据
                merged_df = pd.DataFrame({'MergeData': merged_data})
                merged_output = os.path.join(output_dir, f"{col}_between_edges_processed_merge.csv")
                merged_df.to_csv(merged_output, index=False)
                print(f"已保存合并数据至：{merged_output}")

                # 生成阶梯图
                plt.figure(figsize=(10, 6))
                plt.plot(merged_data, linewidth=0.8)

                # 根据设备模式设置标题
                mode_display = {
                    'SingleThreeAxAccMEMS': 'SingleThreeAxAccMEMS',
                    'SingleThreeAxAccMEMS2': 'SingleThreeAxAccMEMS2',
                    'SingleCrashSensor': 'SingleCrashSensor',
                    'DoubleCrashSensor': 'DoubleCrashSensor',
                    'ThreeAxAccSensor': 'ThreeAxAccSensor',
                    'SingleCrashSensor_ASICFab2' : 'SingleCrashSensor_ASICFab2',
                    'TDK20685': 'TDK 20685',
                    'IMUFab2': 'IMUFab2',
                    'SingleCrashSensor_batch18': 'SingleCrashSensor_batch18'
                }.get(self.device_mode, self.device_mode)

                plt.title(f"{mode_display} - {col} ")
                plt.xlabel("Number of Sampling Points / pcs")

                # 根据设备模式设置Y轴标签
                if self.device_mode == 'TDK20685':
                    if col.startswith('Gyro'):
                        plt.ylabel('AngularVelocity / °/s')  # 陀螺仪单位
                    elif col.startswith('Acc'):
                        plt.ylabel('Acceleration / g')  # 加速度计单位
                    else:
                        plt.ylabel('Output / LSB')
                else:
                    plt.ylabel('Output / LSB')  # 其他模式统一单位

                # # 动态生成x轴标签
                # x_ticks = []
                # x_labels = []
                # current_pos = 0
                # for i, length in enumerate(interval_lengths):
                #     x_ticks.append(current_pos)
                #     start_g = fixed_step * i
                #     end_g = fixed_step * (i + 1)
                #     x_labels.append(f"{start_g}-{end_g}g")
                #     current_pos += length
                #
                # plt.xticks(x_ticks, x_labels, ha='right')
                # plt.tight_layout()

                # 动态生成对称加速度标签
                x_ticks = []
                x_labels = []
                current_pos = 0
                acceleration_sequence = [-8, -6, -4, -2, 2, 4, 6, 8]  # 自定义加速度序列

                for i, (length, accel) in enumerate(zip(interval_lengths, acceleration_sequence)):
                    x_ticks.append(current_pos)
                    x_labels.append(f"{accel}g")  # 直接使用加速度值作为标签
                    current_pos += length


                # 保存图像
                plot_path = os.path.join(output_dir, f"{col}_between_edges_processed_merge.png")
                plt.savefig(plot_path, dpi=300, bbox_inches='tight')
                plt.close()
                print(f"已生成阶梯图：{plot_path}")

            except Exception as e:
                print(f"生成 {col} 阶梯图时出错：{str(e)}")
                continue

    def nonlinear_analysis(self, output_dir, accelerationstep_select, fixed_step, custom_sequence, columns_usedforfitting=None):
        try:
            # 读取平均值文件
            avg_path = os.path.join(output_dir, "final_between_edges_processed_average.csv")
            if not hasattr(self, 'cached_df'):
                self.cached_df = pd.read_csv(avg_path).set_index('Column')
            df = self.cached_df
            # 初始化interval_cols防止未定义
            interval_cols = []
            # 列筛选逻辑加强
            if not df.empty:
                # 获取所有Interval列（加强容错处理）
                interval_cols = [col for col in df.columns if col.startswith('Interval') and col in df]
                # 处理列数限制
                if columns_usedforfitting and isinstance(columns_usedforfitting, int) and columns_usedforfitting > 0:
                    interval_cols = interval_cols[:columns_usedforfitting]
                # 二次有效性检查
                if not interval_cols:
                    raise ValueError("未找到有效的Interval列，请检查输入文件格式")
                df = df[interval_cols]


            # 准备加速度序列
            if accelerationstep_select == "fixed_step":
                used_intervals = len(interval_cols)  # 使用实际参与拟合的列数
                accelerations = [fixed_step * (i+1) for i in range(used_intervals)]
            elif accelerationstep_select == "custom_sequence":
                accelerations = custom_sequence
            else:
                raise ValueError("无效的加速度模式")

            columns_usedforfitting = int(self.columns) if self.columns else None

            # 限制使用的列数
            interval_cols = [col for col in df.columns if col.startswith('Interval')]
            if columns_usedforfitting and columns_usedforfitting > 0:
                interval_cols = interval_cols[:columns_usedforfitting]

            df = df[interval_cols]
            print(f"[DEBUG] 实际使用列名: {interval_cols}")

            # interval_cols = df.columns.tolist()  # 从DataFrame获取实际列名
            # if columns_usedforfitting  is not None and (columns_usedforfitting > 0):
            #     actual_cols = min(columns_usedforfitting, len(interval_cols))
            #     interval_cols = interval_cols[:actual_cols]
            #     # interval_cols = interval_cols[:columns_usedforfitting]
            # print(f"[DEBUG] 可用区间列: {interval_cols}")
            # print(f"[DEBUG] 实际使用列数: {len(interval_cols)}")

            for channel in df.index:
                # 提取有效数据
                output_data = df.loc[channel].dropna().values
                valid_indices = ~pd.isna(df.loc[channel])
                valid_accel = np.array(accelerations)[valid_indices]

                # 数据有效性检查
                if len(output_data) < 2:
                    print(f"跳过{channel}通道：有效数据点不足（{len(output_data)}个）")
                    continue

                # 执行线性回归
                slope, intercept, r_value, _, _ = linregress(valid_accel, output_data)
                fitted = slope * valid_accel + intercept
                nonlinearity = (output_data - fitted) / (output_data.max()-output_data.min()) # 双边需要同时max和min
                # nonlinearity = (output_data - fitted) / (output_data.max()*2)  # 单边需要只使用max

                # 保存通道专属结果
                result_df = pd.DataFrame({
                    'Acceleration_g': valid_accel,
                    'ActualOutput_LSB': output_data,
                    'FittedOutput_LSB': fitted,
                    'NonLinearity_%': nonlinearity*100,
                    'Slope': slope  # 新增斜率列
                })

                # 保存通道专属结果

                result_path = os.path.join(output_dir, f"{channel}_nonlinearity_analysis.csv")
                result_df.to_csv(result_path, index=False)

                # 生成通道专属图表（示例）
                plt.figure(figsize=(8,6))
                plt.plot(valid_accel, output_data, 'bo-', label=f'{channel}_Actual')
                plt.plot(valid_accel, fitted, 'r--', label='Fitted')
                plt.title(f"{channel} Nonlinearity Analysis")

                columns = self.columns_to_process
                for col in columns:
                    if self.device_mode == 'TDK20685':
                        if col.startswith('Gyro'):
                            plt.xlabel('AngularVelocity / °/s')  # 陀螺仪单位
                        elif col.startswith('Acc'):
                            plt.xlabel('Acceleration / g')  # 加速度计单位
                        else:
                            plt.xlabel('Output / LSB')
                    else:
                        plt.xlabel('Input / g')  # 其他模式统一单位

                plt.ylabel("Output / LSB")
                plt.legend()
                plt.grid(True)
                plt.savefig(os.path.join(output_dir, f"{channel}_fitting.png"), dpi=300)
                plt.close()

        except Exception as e:
            print(f"非线性分析失败：{str(e)}")
            raise

    # 在Step2Processor类中添加以下方法
    def calculate_rms_noise(self, output_dir):
        """计算RMS噪声并直接使用非线性分析文件中的slope值"""
        rms_og_path = os.path.join(output_dir, "rms_og.csv")
        if not os.path.exists(rms_og_path):
            raise FileNotFoundError(f"找不到前置文件: {rms_og_path}")

        # 读取前n行原始数据
        data = pd.read_csv(rms_og_path)

        results = []
        for col in self.columns_to_process:
            if col not in data.columns:
                continue

            # 计算均值
            mean_val = data[col].mean()

            # 计算RMS噪声
            noise = np.sqrt(((data[col] - mean_val) ** 2).mean())
            zero_bias_lsb = data[col].mean()
            final_noise = (noise / 2) * 1000  # 转换为mg
            zero_bias = (zero_bias_lsb  / 2) * 1000 # 转换为mg



            # noise = np.sqrt(((data[col]) ** 2).mean())

            # 直接读取非线性分析文件中的slope
            # analysis_path = os.path.join(output_dir, f"{col}_nonlinearity_analysis.csv")
            # if not os.path.exists(analysis_path):
            #     print(f"警告：{col}的非线性分析文件不存在，跳过该通道")
            #     continue
            #
            # try:
            #     analysis_df = pd.read_csv(analysis_path)
            #     # 验证数据有效性
            #     if 'Slope' not in analysis_df.columns:
            #         raise KeyError("CSV文件中缺少Slope列")
            #     if analysis_df.empty:
            #         raise ValueError("CSV文件为空")
            #
            #     # 取第一个非空斜率值
            #     slope = analysis_df['Slope'].dropna().iloc[0]
            #     # nonlinearity_max = analysis_df['NonLinearity_%'].dropna().iloc[0].max()
            #     nonlinearity_max = analysis_df['NonLinearity_%'].dropna().abs().max()
            #     print(f"[DEBUG] {col} Slope值: {slope} (来自文件: {analysis_path})")
            #
            # except (KeyError, IndexError, ValueError) as e:
            #     print(f"读取{col}的slope失败: {str(e)}")
            #     continue

            # 计算最终噪声值（单位：mg）
            # final_noise = (noise / abs(slope)) * 1000  # 转换为mg
            # zero_bias = (zero_bias_lsb  / abs(slope)) * 1000 # 转换为mg
            final_noise = (noise / 2) * 1000  # 转换为mg
            zero_bias = (zero_bias_lsb  / 2) * 1000 # 转换为mg

            results.append({
                'Channel': col,
                'Zero_Bias(mg)': zero_bias,
                'RMS_Noise(mg)': final_noise,
                # 'Slope_used': slope,
                # 'NonLinearity_max_%':nonlinearity_max

                # 'Data_Source': os.path.basename(analysis_path)  # 记录数据来源
            })

        # 保存结果
        result_df = pd.DataFrame(results)
        output_path = os.path.join(output_dir, "rms_analysis.csv")
        result_df.to_csv(output_path, index=False)
        print(f"RMS噪声分析结果已保存至：{output_path}")
        return output_path



