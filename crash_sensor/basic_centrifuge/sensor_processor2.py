# -*- coding: utf-8 -*-
"""
basic_centrifuge - Step 2 离心机台阶提取与非线性度分析处理器
功能说明:
1. 阶梯边缘检测 (process_edges): 卷积滤波与正负阈值双边沿捕获稳态区间。
2. 稳态数据裁剪 (process_cropping): 滤除爬坡过渡态并按均值排序。
3. 稳态均值聚合 (calculate_averages): 汇总各通道各加速度台阶均值。
4. 阶梯曲线生成 (create_staircase_plots): 合并全时段稳态数据并绘制台阶图。
5. 拟合与非线性度评定 (nonlinear_analysis): 最小二乘法线性回归与拟合度评估。
6. 零偏与 RMS 噪声评定 (calculate_rms_noise): 稳态零点均值与本底噪声计算。
"""

import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import linregress


class Step2Processor:
    """Step 2 离心机稳态台阶提取、非线性度与 RMS 噪声分析器"""

    # 各设备模式默认配置: (通道列表, start_idx, end_trim, min_length)
    DEVICE_SPECS = {
        'SingleCrashSensor': (['z2', 'z1', 'x', 'y'], 2500, 1500, 1000),
        'DoubleCrashSensor': (['z2', 'z1', 'x', 'y'], 2500, 1500, 1000),
        'ThreeAxAccSensor': (['z2', 'z1', 'x', 'y'], 100, 100, 100),
        'TDK20685': (['GyroX', 'GyroY', 'GyroZ', 'AccX', 'AccY', 'AccZ'], 300, 100, 400),
        'SingleThreeAxAccMEMS': (['x', 'y', 'z1', 'z2'], 20, 20, 10),
        'SingleThreeAxAccMEMS2': (['x1', 'y1', 'z1', 'x2', 'y2', 'z2', 'z3', 'z4'], 20, 20, 10),
        'IMUFab2': (['AccX', 'AccY', 'AccZ', 'AccZC', 'GyroX', 'GyroY', 'GyroZ', 'Temperature'], 50, 20, 10),
        'SingleCrashSensor_ASICFab2': (['y'], 2500, 2000, 2000),
        'SingleCrashSensor_batch18': ([f'p{i}' for i in range(1, 19)], 2500, 1000, 1000),
    }

    def __init__(
        self,
        zero_division_p: float = 35.0,
        zero_division_n: float = -35.0,
        upDown_division: float = 0.0,
        fixed_step: float = 20.0,
        device_mode: str = 'SingleCrashSensor',
        accelerationstep_select: str = 'custom_sequence',
        custom_sequence: str = '-120, -80, -40, 40, 80, 120',
        window_size: int = 50,
        columns: int = None,
        config_path: str = None
    ):
        self.device_mode = device_mode
        self.zero_division_p = float(zero_division_p)
        self.zero_division_n = float(zero_division_n)
        self.upDown_division = float(upDown_division)
        self.fixed_step = float(fixed_step)
        self.accelerationstep_select = accelerationstep_select
        self.window_size = window_size
        self.columns = int(columns) if columns and str(columns).isdigit() else None

        # 解析自定义步进序列
        if isinstance(custom_sequence, str):
            self.custom_sequence = [float(x.strip()) for x in custom_sequence.split(',') if x.strip()]
        else:
            self.custom_sequence = list(custom_sequence)

        # 初始化设备相关参数
        cols, start, end, min_len = self.DEVICE_SPECS.get(
            self.device_mode,
            (['z2', 'z1', 'x', 'y'], 300, 100, 400)
        )
        self.columns_to_process = cols
        self.start_idx = start
        self.end_trim = end
        self.min_length = min_len

        # 图形全局配置
        plt.rcParams['font.family'] = 'Times New Roman'
        plt.rcParams['font.size'] = 12
        plt.rcParams['lines.linewidth'] = 0.5
        plt.rcParams['axes.unicode_minus'] = False

    def process(self, input_path: str, output_path: str) -> bool:
        """主执行流程：边缘检测 -> 数据裁剪 -> 均值计算 -> 阶梯图绘制 -> 非线性度与噪声评定"""
        try:
            output_dir = os.path.dirname(output_path)
            # Step 2.1 边沿检测
            edges_data = self.process_edges(input_path, self.zero_division_p, self.zero_division_n)
            # Step 2.2 数据裁剪
            cropped_data = self.process_cropping(edges_data)
            # Step 2.3 计算平均值
            avg_file = self.calculate_averages(cropped_data)
            # Step 2.4 生成阶梯图
            self.create_staircase_plots(output_dir=output_dir, fixed_step=self.fixed_step)
            # Step 2.5 非线性度分析
            self.nonlinear_analysis(
                output_dir=os.path.dirname(avg_file),
                accelerationstep_select=self.accelerationstep_select,
                fixed_step=self.fixed_step,
                custom_sequence=self.custom_sequence,
                columns_usedforfitting=self.columns
            )
            # Step 2.6 RMS 噪声评定
            self.calculate_rms_noise(output_dir)
            return True
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"Step2 处理失败: {str(e)}")

    def process_step2(self, *args, **kwargs):
        """兼容接口，直接转发到 process()"""
        return self.process(*args, **kwargs)

    def process_edges(self, input_path: str, zero_division_p: float, zero_division_n: float) -> dict:
        """Step 2.1 边缘检测处理：提取台阶过渡区间"""
        if not input_path.endswith('.csv'):
            raise ValueError(f"不支持的文件格式: {input_path}")

        data = pd.read_csv(input_path)
        output_dir = os.path.dirname(input_path)

        # 留存前 1000~6000 点作为静态零偏与 RMS 噪声样本
        rms_path = os.path.join(output_dir, "rms_og.csv")
        sample_slice = data.iloc[1000:6000] if len(data) >= 6000 else data
        sample_slice.to_csv(rms_path, index=False)

        edge_data = {}
        for col in self.columns_to_process:
            if col not in data.columns:
                continue

            data_col = data[col].values
            if len(data_col) < self.window_size:
                continue

            # 卷积平滑滤波
            smoothed = np.convolve(data_col, np.ones(self.window_size) / self.window_size, mode='valid')
            filtered_a = smoothed.copy()
            filtered_b = smoothed.copy()

            filtered_a[filtered_a < zero_division_p] = zero_division_p
            filtered_b[filtered_b > zero_division_n] = zero_division_n

            # 正向与负向边缘跳变检测
            rise_edges_a = np.where((filtered_a[:-1] == zero_division_p) & (filtered_a[1:] > zero_division_p))[0] + 1
            fall_edges_a = np.where((filtered_a[:-1] > zero_division_p) & (filtered_a[1:] == zero_division_p))[0] + 1
            fall_edges_b = np.where((filtered_b[:-1] == zero_division_n) & (filtered_b[1:] < zero_division_n))[0] + 1
            rise_edges_b = np.where((filtered_b[:-1] < zero_division_n) & (filtered_b[1:] == zero_division_n))[0] + 1

            segments = []
            max_length = 0

            # 游标配对处理 A 类边缘 (正向台阶)
            i, j = 0, 0
            while i < len(rise_edges_a) and j < len(fall_edges_a):
                rise_idx, fall_idx = rise_edges_a[i], fall_edges_a[j]
                if rise_idx < fall_idx:
                    seg = data_col[rise_idx : fall_idx + self.window_size]
                    segments.append(seg)
                    max_length = max(max_length, len(seg))
                    i += 1
                    j += 1
                else:
                    j += 1

            # 游标配对处理 B 类边缘 (负向台阶)
            m, n = 0, 0
            while m < len(fall_edges_b) and n < len(rise_edges_b):
                fall_idx, rise_idx = fall_edges_b[m], rise_edges_b[n]
                if fall_idx < rise_idx:
                    seg = data_col[fall_idx : rise_idx + self.window_size]
                    segments.append(seg)
                    max_length = max(max_length, len(seg))
                    m += 1
                    n += 1
                else:
                    n += 1

            if not segments:
                edge_data[col] = None
                continue

            # 对齐填充保存
            padded = [
                np.pad(s, (0, max_length - len(s)), constant_values=np.nan) if len(s) < max_length else s
                for s in segments
            ]
            output_df = pd.DataFrame(np.column_stack(padded), columns=[f'Interval{k+1}' for k in range(len(padded))])
            col_edge_path = os.path.join(output_dir, f"{col}_between_edges.csv")
            output_df.to_csv(col_edge_path, index=False)
            edge_data[col] = col_edge_path

        return edge_data

    def process_cropping(self, edge_data: dict) -> dict:
        """Step 2.2 数据裁剪处理：剔除过渡扰动段并按均值排序"""
        processed_data = {}
        for col, file_path in edge_data.items():
            if not file_path or not os.path.exists(file_path):
                continue

            try:
                df = pd.read_csv(file_path)
            except Exception:
                continue

            valid_columns = pd.DataFrame()
            for col_name in df.columns:
                series = df[col_name].dropna()
                if self.end_trim > 0:
                    cropped = series.iloc[self.start_idx : -self.end_trim]
                else:
                    cropped = series.iloc[self.start_idx :]

                if len(cropped) > self.min_length:
                    valid_columns[col_name] = cropped.reset_index(drop=True)

            if valid_columns.empty:
                continue

            # 按列均值由小到大排序 (负加速度 -> 正加速度)
            col_means = valid_columns.mean(numeric_only=True)
            sorted_cols = col_means.sort_values(ascending=True).index
            valid_columns = valid_columns[sorted_cols]

            output_path = file_path.replace('_between_edges.csv', '_between_edges_processed.csv')
            valid_columns.to_csv(output_path, index=False)
            processed_data[col] = output_path

        return processed_data

    def calculate_averages(self, processed_data: dict) -> str:
        """Step 2.3 计算各区间均值并导出汇总表"""
        channel_data = {}
        max_intervals = 0

        for col, file_path in processed_data.items():
            try:
                df = pd.read_csv(file_path)
                means = df.mean().tolist()
                channel_data[col] = means
                max_intervals = max(max_intervals, len(means))
            except Exception:
                continue

        rows = []
        for col in self.columns_to_process:
            if col not in channel_data:
                continue
            means = channel_data[col]
            padded_means = means + [np.nan] * (max_intervals - len(means))
            rows.append([col] + padded_means)

        column_names = ['Column'] + [f'Interval{i+1}' for i in range(max_intervals)]
        result_df = pd.DataFrame(rows, columns=column_names)

        output_dir = os.path.dirname(list(processed_data.values())[0])
        output_path = os.path.join(output_dir, 'final_between_edges_processed_average.csv')
        result_df.to_csv(output_path, index=False)
        return output_path

    def create_staircase_plots(self, output_dir: str, fixed_step: float):
        """Step 2.4 生成阶梯拼接图与合并 CSV"""
        for col in self.columns_to_process:
            input_path = os.path.join(output_dir, f"{col}_between_edges_processed.csv")
            if not os.path.exists(input_path):
                continue

            try:
                data = pd.read_csv(input_path)
                merged_data = []
                for col_name in data.columns:
                    valid_pts = data[col_name].dropna().values
                    merged_data.extend(valid_pts)

                # 保存合并数据
                merged_path = os.path.join(output_dir, f"{col}_between_edges_processed_merge.csv")
                pd.DataFrame({'MergeData': merged_data}).to_csv(merged_path, index=False)

                # 绘图
                plt.figure(figsize=(10, 6))
                plt.plot(merged_data, linewidth=0.8)
                plt.title(f"{self.device_mode} - {col}")
                plt.xlabel("Number of Sampling Points / pcs")

                if self.device_mode == 'TDK20685':
                    ylabel = 'AngularVelocity / °/s' if col.startswith('Gyro') else 'Acceleration / g'
                else:
                    ylabel = 'Output / LSB'
                plt.ylabel(ylabel)
                plt.grid(True, linestyle='--', alpha=0.5)

                plot_path = os.path.join(output_dir, f"{col}_between_edges_processed_merge.png")
                plt.savefig(plot_path, dpi=200, bbox_inches='tight')
                plt.close()

            except Exception as e:
                print(f"生成 {col} 阶梯图异常: {e}")

    def nonlinear_analysis(
        self,
        output_dir: str,
        accelerationstep_select: str,
        fixed_step: float,
        custom_sequence: list,
        columns_usedforfitting: int = None
    ):
        """Step 2.5 最小二乘法非线性度分析与拟合出图"""
        avg_path = os.path.join(output_dir, "final_between_edges_processed_average.csv")
        if not os.path.exists(avg_path):
            return

        df = pd.read_csv(avg_path).set_index('Column')
        interval_cols = [c for c in df.columns if str(c).startswith('Interval')]

        limit = columns_usedforfitting or self.columns
        if limit and limit > 0:
            interval_cols = interval_cols[:limit]

        if not interval_cols:
            return

        df = df[interval_cols]

        # 构造加速度梯度序列
        if accelerationstep_select == "fixed_step":
            accelerations = [fixed_step * (i + 1) for i in range(len(interval_cols))]
        else:
            accelerations = custom_sequence[:len(interval_cols)]

        for channel in df.index:
            output_data = df.loc[channel].dropna().values
            valid_indices = ~pd.isna(df.loc[channel])
            valid_accel = np.array(accelerations[:len(valid_indices)])[valid_indices]

            if len(output_data) < 2:
                continue

            # 线性拟合
            slope, intercept, r_value, _, _ = linregress(valid_accel, output_data)
            fitted = slope * valid_accel + intercept
            span = output_data.max() - output_data.min()
            nonlinearity = (output_data - fitted) / span if span != 0 else np.zeros_like(output_data)

            result_df = pd.DataFrame({
                'Acceleration_g': valid_accel,
                'ActualOutput_LSB': output_data,
                'FittedOutput_LSB': fitted,
                'NonLinearity_%': nonlinearity * 100,
                'Slope': slope
            })
            result_df.to_csv(os.path.join(output_dir, f"{channel}_nonlinearity_analysis.csv"), index=False)

            # 绘制拟合图
            plt.figure(figsize=(8, 6))
            plt.plot(valid_accel, output_data, 'bo-', label=f'{channel}_Actual')
            plt.plot(valid_accel, fitted, 'r--', label=f'Fitted (Slope={slope:.3f})')
            plt.title(f"{channel} Nonlinearity Analysis (R²={r_value**2:.4f})")
            plt.xlabel('Input / g')
            plt.ylabel('Output / LSB')
            plt.legend()
            plt.grid(True, linestyle='--', alpha=0.6)
            plt.savefig(os.path.join(output_dir, f"{channel}_fitting.png"), dpi=200, bbox_inches='tight')
            plt.close()

    def calculate_rms_noise(self, output_dir: str) -> str:
        """Step 2.6 计算通道静态零偏 (Zero Bias) 与 RMS 本底噪声 (mg)"""
        rms_og_path = os.path.join(output_dir, "rms_og.csv")
        if not os.path.exists(rms_og_path):
            return ""

        data = pd.read_csv(rms_og_path)
        results = []

        for col in self.columns_to_process:
            if col not in data.columns:
                continue

            mean_val = data[col].mean()
            noise = np.sqrt(((data[col] - mean_val) ** 2).mean())

            # 统一折算为物理量毫克 (mg)
            final_noise = (noise / 2.0) * 1000.0
            zero_bias = (mean_val / 2.0) * 1000.0

            results.append({
                'Channel': col,
                'Zero_Bias(mg)': zero_bias,
                'RMS_Noise(mg)': final_noise
            })

        result_df = pd.DataFrame(results)
        output_path = os.path.join(output_dir, "rms_analysis.csv")
        result_df.to_csv(output_path, index=False)
        return output_path
