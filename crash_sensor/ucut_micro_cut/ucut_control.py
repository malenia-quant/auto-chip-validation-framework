import sys
import os
import time
import pyvisa

# 将当前目录加入系统路径，以便导入模块
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from dg5072_ucut import (
    DG5072Controller, 
    CASES_24_CONFIG, 
    V_BASE, 
    V_SYNC_HIGH, 
    MANUAL_V_CUT_LOW, 
    MANUAL_UCUT_DURATION_US, 
    MANUAL_UCUT_START_US,
    DEBUG_CONTINUOUS as DG_DEBUG_CONTINUOUS
)
from sds5054_ucut import SDS_Frame_Validator
from pyserial_ucut import PyserialUcut

import threading

# =============================================================================
# 全局测试配置区 (用户控制开关)
# =============================================================================
# [开关] 是否开启 4秒硬注入 / 无限循环连续输出 (True=开启无限连续注入跳过验证，False=正常4秒注入)
ENABLE_DEBUG_CONTINUOUS = False 

# [开关] 是否开启 I2C 串口指令与判定 (若为 False，则不使用串口)
ENABLE_I2C_CHECK = True

# [开关] 是否在注入前发送命令进行修调配置 (依赖上方串口开关，若为 False，只打开电源开关，不发送指令)
ENABLE_I2C_TRIM = True

# [开关] 是否开启 5054 严格波形判定与解码 (若为 False，则只抓取保存原始波形不判定)
ENABLE_5054_CHECK = True
# =============================================================================

def plot_ucut_24_areas_to_excel(all_cases_summary, excel_path):
    try:
        from openpyxl import load_workbook
        from openpyxl.styles import PatternFill, Alignment, Font, Border, Side
    except ImportError:
        print("[-] 缺少 openpyxl，无法在 Excel 中绘制 uCut 分布图。")
        return

    wb = load_workbook(excel_path)
    if 'Shmoo_Plot' not in wb.sheetnames:
        ws = wb.create_sheet('Shmoo_Plot')
    else:
        ws = wb['Shmoo_Plot']
        
    green_fill = PatternFill(start_color="92D050", end_color="92D050", fill_type="solid")
    red_fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
    gray_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
    light_green_fill = PatternFill(start_color="CCFFCC", end_color="CCFFCC", fill_type="solid")
    
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    bold_font = Font(bold=True)
    
    def get_case_result(cid):
        for summary in all_cases_summary:
            if summary.get("Case 编号") == f"Case {cid}":
                i2c_after = summary.get("恢复后 I2C", "N/A")
                after_status = summary.get("恢复后判定 (After)", "N/A")
                is_fail = False
                if "FAIL" in str(i2c_after).upper() or "FAIL" in str(after_status).upper():
                    is_fail = True
                return not is_fail
        return None
        
    ws.column_dimensions['A'].width = 15
    ws.column_dimensions['B'].width = 25
    for col in ['C', 'D', 'E', 'F', 'G', 'H']:
        ws.column_dimensions[col].width = 12
        
    ws.merge_cells('A1:H1')
    ws['A1'] = 'uCut Shmoo Plot (24 Cases Verification)'
    ws['A1'].alignment = center_align
    ws['A1'].font = Font(bold=True, size=14)
    
    ws.merge_cells('C2:H2')
    ws['C2'] = 'Normal Operating Region (Vdd > 4.5V)'
    ws['C2'].fill = light_green_fill
    ws['C2'].alignment = center_align
    ws['C2'].font = Font(color="008000", bold=True)
    
    ws['B2'] = '> Vdd_min (> 4.5V)'
    ws['B3'] = '> Vdd_reset (1.6V - 4.5V)'
    ws['B5'] = '< Vdd_reset (Below 1.6V)'
    
    ws.merge_cells('C7:D7')
    ws['C7'] = '< 33 us'
    ws.merge_cells('E7:F7')
    ws['E7'] = '33 us ~ 4 ms'
    ws.merge_cells('G7:H7')
    ws['G7'] = '> 4 ms'
    
    for col in ['C', 'E', 'G']:
        ws[f'{col}7'].alignment = center_align
        ws[f'{col}7'].font = bold_font
        
    def fill_4_cases(start_row, start_col, start_cid):
        for i in range(4):
            cid = start_cid + i
            r = start_row + (1 if i > 1 else 0)
            c = start_col + (i % 2)
            
            cell = ws.cell(row=r, column=c)
            res = get_case_result(cid)
            
            if res is None:
                text, fill = 'N/A', gray_fill
            elif res == True:
                text, fill = 'PASS', green_fill
            else:
                text, fill = 'FAIL', red_fill
                
            cell.value = f"C{cid}\n{text}"
            cell.fill = fill
            cell.alignment = center_align
            cell.border = thin_border
            cell.font = bold_font

    fill_4_cases(3, 3, 1)
    fill_4_cases(5, 3, 5)
    fill_4_cases(3, 5, 9)
    fill_4_cases(5, 5, 13)
    fill_4_cases(3, 7, 17)
    fill_4_cases(5, 7, 21)
    
    wb.save(excel_path)
    print(f"[+] uCut 分布图已绘制到 Excel: {excel_path} 的 Shmoo_Plot 工作表中")

def capture_sds5054(sds_validator, phase_name, dut_base_name, enable_5054_check=True):
    if not enable_5054_check:
        print(f"\n[*] 5054 开关已关闭，跳过 SDS5054 波形采集与判定。")
        return "N/A", ["N/A", "N/A", "N/A", "N/A"]
        
    dut_name = f"{dut_base_name}_{phase_name}"
    print(f"\n[*] 启动 SDS5054 捕获与判定 ({dut_name})...")
    
    t, v1, v2, s = sds_validator.fetch_waveform()
    if t is not None and v2 is not None:
        if enable_5054_check:
            # 自动检测同步脉冲及后续响应
            success, reports, vddi = sds_validator.analyze(t, v1, v2, s, dut_name)
            
            decimal_vals = []
            for r in reports[:4]:
                decimal_vals.append(r.get('decimal_val', 'N/A'))
            while len(decimal_vals) < 4:
                decimal_vals.append('N/A')
                
            if success:
                sds_validator.save_to_csv(dut_name, reports, vddi)
                print(f"\n[Result] PASS - {dut_name} 验证成功，数据已保存至 CSV。")
                return "PASS", decimal_vals
            else:
                print(f"\n[Result] FAIL - {dut_name} 验证失败或波形不符合规范。")
                return "FAIL", decimal_vals
    else:
        print(f"\n[Result] ERROR - {dut_name} 波形获取失败。")
        return "ERROR", ["N/A", "N/A", "N/A", "N/A"]

def main():
    EXECUTION_MODE = 2
    
    # 资源地址，可根据实际情况修改
    DG5072_VISA_RESOURCE = "USB0::0x1AB1::0x0640::DG5T264700198::INSTR" 
    # 如果示波器是通过 USB 或确定了 IP，可填写至下方。如果为空字符串或 None，则会自动搜索
    SDS5054_VISA_RESOURCE = ""

    print("="*60)
    print(" 联合主控脚本: 依次执行 DG5072 (注入) 与 SDS5054 (多阶段检测) ")
    print("="*60)

    # 1. 初始化 DG5072
    try:
        dg_controller = DG5072Controller(DG5072_VISA_RESOURCE)
        print("[DG5072] 信号发生器连接成功")
    except Exception as e:
        print(f"[!] DG5072 连接失败: {e}")
        return

    # 2. 初始化 SDS5054
    sds_validator = SDS_Frame_Validator()
    if sds_validator.connect(resource_name=SDS5054_VISA_RESOURCE if SDS5054_VISA_RESOURCE else None):
        # 如果需要配置示波器，可取消下方注释
        # sds_validator.setup()
        print("[SDS5054] 示波器连接成功")
    else:
        print("[!] SDS5054 连接失败")
        if ENABLE_5054_CHECK:
            dg_controller.close()
            return

    # 3. 初始化 PyserialUcut (请确认您的 COM 端口是否为 COM7)
    try:
        ucut_serial = PyserialUcut(port='COM7', baudrate=115200)
        print("[串口] PyserialUcut 实例创建成功")
    except Exception as e:
        print(f"[!] 串口 初始化失败: {e}")
        ucut_serial = None

    try:
        while True:
            print("\n==================================================")
            print(f"当前执行模式: [{'手动模式(1)' if EXECUTION_MODE == 1 else '矩阵模式(2)'}] | 持续输出 Debug: [{'开启' if ENABLE_DEBUG_CONTINUOUS else '关闭 (4秒)'}]")
            print("可用操作指令:")
            print("  [1-24] : 依次执行对应的 24 种 Spec 测试用例 (包含注入中和注入后两次抓取)")
            print("  [a]    : 自动轮询执行所有 24 种情况 (自动新建 24cycles_时间戳 文件夹)")
            print("  [m]    : 触发 MANUAL 手动单次测试并双重检测")
            print("  [q]    : 退出测试并断开仪器")
            print("==================================================")
            
            user_input = input("mozial (联调)> 请输入操作指令: ").strip().lower()
            
            if user_input == 'q':
                print("测试序列已终止。")
                break
                
            cases_to_run = []
            if user_input == 'a':
                cases_to_run = list(range(1, 25))
                timestamp = time.strftime('%Y%m%d_%H%M%S')
                custom_dir = os.path.join(current_dir, f"24cycles_{timestamp}")
                os.makedirs(custom_dir, exist_ok=True)
                sds_validator.output_dir = custom_dir
                print(f"\n[*] 自动轮循模式开启，所有数据与图像将保存在: {custom_dir}")
            elif user_input == 'm':
                cases_to_run = ['m']
                sds_validator.output_dir = os.path.join(current_dir, f"Test_Results_{time.strftime('%Y%m%d')}")
                if not os.path.exists(sds_validator.output_dir): os.makedirs(sds_validator.output_dir)
            else:
                try:
                    case_id = int(user_input)
                    if case_id < 1 or case_id > 24:
                        print("输入错误: 用例编号必须在 1 到 24 之间。")
                        continue
                    cases_to_run = [case_id]
                    sds_validator.output_dir = os.path.join(current_dir, f"Test_Results_{time.strftime('%Y%m%d')}")
                    if not os.path.exists(sds_validator.output_dir): os.makedirs(sds_validator.output_dir)
                except ValueError:
                    print("输入错误: 无效的指令，请重新输入。")
                    continue
                    
            all_cases_summary = []
            
            for cid in cases_to_run:
                kwargs = {}
                if cid == 'm':
                    print("\n---> 开始执行 [手动配置测试] <---")
                    kwargs = {
                        'v_base': V_BASE, 
                        'v_sync_high': V_SYNC_HIGH, 
                        'v_cut_low': MANUAL_V_CUT_LOW,
                        'ucut_duration_us': MANUAL_UCUT_DURATION_US,
                        'ucut_start_us': MANUAL_UCUT_START_US,
                        'debug_continuous': ENABLE_DEBUG_CONTINUOUS
                    }
                    dut_name = "Manual_Test"
                    # [修复] 绕过莫名其妙的 signature 报错，直接通过属性传递
                    dg_controller.serial_controller = ucut_serial if ENABLE_I2C_CHECK else None
                    dg_controller.enable_trim = ENABLE_I2C_TRIM
                else:
                    cfg = CASES_24_CONFIG[cid]
                    print(f"\n---> 开始执行 Case {cid} <---")
                    print(f"提取参数: 跌落至 {cfg['v_cut_low']}V, 持续 {cfg['duration_us']}us, 注入位置 {cfg['start_us']}us")
                    
                    kwargs = {
                        'v_base': V_BASE,
                        'v_sync_high': V_SYNC_HIGH,
                        'v_cut_low': cfg["v_cut_low"],
                        'ucut_duration_us': cfg["duration_us"],
                        'ucut_start_us': cfg["start_us"],
                        'debug_continuous': ENABLE_DEBUG_CONTINUOUS
                    }
                    dut_name = f"Case_{cid}"
                    # [修复] 绕过莫名其妙的 signature 报错，直接通过属性传递
                    dg_controller.serial_controller = ucut_serial if ENABLE_I2C_CHECK else None
                    dg_controller.enable_trim = ENABLE_I2C_TRIM

                phase2_start_event = threading.Event()
                kwargs['phase2_start_event'] = phase2_start_event

                # 开启独立线程执行 DG5072 注入流程 (以便主线程能够精确控制示波器抓取时间点)
                dg_thread = threading.Thread(target=dg_controller.load_and_execute_4sec_test, kwargs=kwargs)
                dg_thread.start()

                # 依次执行第二步：示波器多阶段捕获
                if not ENABLE_DEBUG_CONTINUOUS:
                    print(f"\n[*] 正在后台执行 DG5072 注入，等待第一阶段正常上电及串口修调指令完毕...")
                    # 注入流程：
                    # 阶段1：1秒纯净心跳 + 串行执行修调命令
                    phase2_start_event.wait()
                    
                    if ENABLE_5054_CHECK:
                        print(f"\n[*] 进入阶段2，故障注入开始。准备在注入 2.0 秒时触发 SDS5054 抓取...")
                        # 阶段2：4秒故障注入，我们在 2.0 秒时触发示波器
                        time.sleep(2.0) 
                        dur_status, dur_data = capture_sds5054(sds_validator, "During_Injection", dut_name, ENABLE_5054_CHECK)
                    else:
                        print(f"\n[*] 5054 开关已关闭，跳过 During_Injection 捕获等待。")
                        dur_status, dur_data = "N/A", ["N/A", "N/A", "N/A", "N/A"]
                    
                    # 等待 DG5072 流程彻底结束 (阶段3结束)
                    dg_thread.join()
                    
                    if ENABLE_5054_CHECK:
                        print("\n[*] 4秒注入已结束，等待 2 秒进行恢复后抓取...")
                        time.sleep(2.0)
                        aft_status, aft_data = capture_sds5054(sds_validator, "After_Injection", dut_name, ENABLE_5054_CHECK)
                    else:
                        print("\n[*] 4秒注入已结束。")
                        aft_status, aft_data = "N/A", ["N/A", "N/A", "N/A", "N/A"]
                    
                    if ucut_serial and ENABLE_I2C_CHECK:
                        if not ENABLE_5054_CHECK:
                            print("\n[*] 等待 2 秒确保恢复供电稳定，进行最后一次串口检查...")
                            time.sleep(2.0)
                        else:
                            print("\n[*] 进行最后一次串口检查...")
                        ucut_serial.verify_after_recovery()
                        
                    print(f"\n[*] 测试 {dut_name} 全流程结束。")
                    
                    case_summary = {
                        "Case 编号": f"Case {cid}",
                        "注入前 I2C": ucut_serial.last_pre_result if (ucut_serial and ENABLE_I2C_CHECK) else "N/A",
                        "恢复后 I2C": ucut_serial.last_post_result if (ucut_serial and ENABLE_I2C_CHECK) else "N/A",
                    }
                    if ENABLE_5054_CHECK:
                        case_summary.update({
                            "注入时判定 (During)": dur_status,
                            "注入 Data1": dur_data[0] if dur_data else "N/A",
                            "注入 Data2": dur_data[1] if dur_data else "N/A",
                            "注入 Data3": dur_data[2] if dur_data else "N/A",
                            "注入 Data4": dur_data[3] if dur_data else "N/A",
                            "恢复后判定 (After)": aft_status,
                            "恢复后 Data1": aft_data[0] if aft_data else "N/A",
                            "恢复后 Data2": aft_data[1] if aft_data else "N/A",
                            "恢复后 Data3": aft_data[2] if aft_data else "N/A",
                            "恢复后 Data4": aft_data[3] if aft_data else "N/A"
                        })
                    if user_input == 'a':
                        all_cases_summary.append(case_summary)
                else:
                    dg_thread.join()
                    print(f"\n[!] 测试 {dut_name} 当前处于 Debug 无限循环输出模式，跳过自动检测。请使用示波器手动抓取波形。")
            
            if user_input == 'a':
                print("\n========== 24 种情况自动轮循测试全部完成 ==========")
                try:
                    import pandas as pd
                    excel_path = os.path.join(custom_dir, f"Summary_24_Cases_{timestamp}.xlsx")
                    df = pd.DataFrame(all_cases_summary)
                    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                        df.to_excel(writer, sheet_name='Summary', startrow=5, index=False)
                        workbook = writer.book
                        worksheet = writer.sheets['Summary']
                        worksheet.cell(row=1, column=1, value="I2C 注入前判定条件：发送三次指令，分别验证进入修调(01)、写IO_SEL(02)、退修调(00)")
                        worksheet.cell(row=2, column=1, value="I2C 恢复后判定条件：等待2秒恢复供电后，验证第八组数据是否为 00")
                        if ENABLE_5054_CHECK:
                            worksheet.cell(row=3, column=1, value="Data1~Data4：分别代表示波器单次捕获内，4个同步脉冲解析出的十进制有效载荷数据 (Decimal Value)")
                    print(f"[+] 全局 XLSX 汇总报告已成功生成: {excel_path}")
                    
                    # 生成分布图
                    plot_ucut_24_areas_to_excel(all_cases_summary, excel_path)
                    
                except Exception as ex:
                    print(f"[-] 生成 XLSX 汇总报告或分布图失败: {ex}")

    except pyvisa.VisaIOError as e:
        print(f"VISA 通信失败: {e}")
    except Exception as e:
        print(f"发生未知错误: {e}")
    finally:
        if dg_controller is not None:
            dg_controller.close()
        if sds_validator and sds_validator.inst:
            sds_validator.inst.close()
        print("仪器连接已安全释放。")

if __name__ == "__main__":
    main()
