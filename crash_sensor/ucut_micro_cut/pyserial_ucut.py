import serial
import time
import colorama
from colorama import Fore, Style

# 初始化 colorama 以支持终端彩色输出
colorama.init()

class PyserialUcut:
    def __init__(self, port='COM1', baudrate=115200, timeout=1):
        """
        初始化串口参数
        :param port: 串口号 (例如 'COM1', 'COM3')
        :param baudrate: 波特率
        :param timeout: 超时时间(秒)
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.last_pre_result = "N/A"
        self.last_post_result = "N/A"

    def open(self):
        if self.ser is None or not self.ser.is_open:
            try:
                self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
                print(f"{Fore.GREEN}成功打开串口 {self.port}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}FALSE: 打开串口失败 - {e}{Style.RESET_ALL}")
                raise

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"{Fore.GREEN}成功关闭串口 {self.port}{Style.RESET_ALL}")

    def send_and_receive(self, cmd_name, hex_str, delay=0.3):
        """
        发送十六进制指令并接收应答。
        包含300毫秒的串行发送间隔以确保设备有足够时间回复。
        """
        print(f"[{cmd_name}] 发送: {hex_str}")
        cmd_bytes = bytes.fromhex(hex_str.replace(" ", ""))
        self.ser.write(cmd_bytes)
        
        # 每行命令发送间隔最好在200毫秒
        time.sleep(delay)
        
        # 读取缓冲区中所有可用的应答数据
        response = self.ser.read_all()
        resp_hex = " ".join([f"{b:02X}" for b in response])
        print(f"[{cmd_name}] 应答: {resp_hex}")
        return response

    def open_power_switch(self):
        """
        首先发送一次进修调再退修调，用以打开开关让信号发生器供电进来。
        """
        try:
            self.open()
            print("mozial: [串行执行] 准备打开 PCB 供电开关...")
            self.send_and_receive("开关: 写进入修调", "EA 2A 0B 01 00 28 00 09 FF 22 8B")
            self.send_and_receive("开关: 退修调", "EA 2A 0B 01 00 00 00 09 FF 33 8B")
            print("mozial: [串行执行] 供电开关已打开。")
        except Exception as e:
            print(f"{Fore.RED}FALSE: 打开供电开关时发生异常 - {e}{Style.RESET_ALL}")

    def run_pre_injection_sequence(self):
        """
        发生在第一次正常上电与 ucut 注入之间的核心修调指令序列。
        """
        try:
            self.open()
            
            # 1. 发送: 写进入修调
            self.send_and_receive("发送1: 写进入修调", "EA 2A 0B 01 00 28 00 09 FF 22 8B")
            
            # 2. 发送: 读进入修调，验证第八组数据(Index 7)是否从00变成了01
            resp_enter = self.send_and_receive("发送2: 读进入修调", "EA 2A 0B 01 00 00 00 08 FE 00 D7")
            if len(resp_enter) >= 8 and resp_enter[7] == 0x01:
                print(f"{Fore.GREEN}PASS: 成功进入修调，第八组数据为 01{Style.RESET_ALL}")
            else:
                val = f"{resp_enter[7]:02X}" if len(resp_enter) >= 8 else "None"
                print(f"{Fore.RED}FALSE: 未成功进入修调，第八组数据为 {val}{Style.RESET_ALL}")
                self.last_pre_result = "FAIL"
                return False
                
            # 3. 发送: 读TEST_IO_SEL (原数据) - 方便对比前后数据差异，验证原本是00
            resp_read_before = self.send_and_receive("发送3: 读TEST_IO_SEL(前)", "EA 2A 0B 01 00 00 00 08 A5 00 D7")
            if len(resp_read_before) >= 8:
                print(f"当前 TEST_IO_SEL 第八组数据为: {resp_read_before[7]:02X}")
                
            # 4. 发送: 配置TEST_IO_SEL
            self.send_and_receive("发送4: 配置TEST_IO_SEL", "EA 2A 0B 01 00 00 00 09 A1 02 D9")
            
            # 5. 发送: 读TEST_IO_SEL (配置后)，验证第八组数据是否从00变成了02
            resp_read_after = self.send_and_receive("发送5: 读TEST_IO_SEL(后)", "EA 2A 0B 01 00 00 00 08 A5 00 D7")
            if len(resp_read_after) >= 8 and resp_read_after[7] == 0x02:
                print(f"{Fore.GREEN}PASS: 成功写入 TEST_IO_SEL，对比前后数据第八组数据变为 02{Style.RESET_ALL}")
                self.last_pre_result = "PASS"
                return True
            else:
                val = f"{resp_read_after[7]:02X}" if len(resp_read_after) >= 8 else "None"
                print(f"{Fore.RED}FALSE: 写入 TEST_IO_SEL 失败，第八组数据为 {val}{Style.RESET_ALL}")
                self.last_pre_result = "FAIL"
                return False
                
        except Exception as e:
            print(f"{Fore.RED}FALSE: 运行过程中发生异常 - {e}{Style.RESET_ALL}")
            self.last_pre_result = "FAIL"
            return False

    def verify_after_recovery(self):
        """
        在最后恢复正常功能之后再进行一次验证
        """
        try:
            if not self.ser or not self.ser.is_open:
                self.open()
                
            # 6. 发送: 读TEST_IO_SEL (最后正常上电状态)
            resp_recover = self.send_and_receive("发送6: 读TEST_IO_SEL(恢复后)", "EA 2A 0B 01 00 00 00 08 A5 00 D7")
            if len(resp_recover) >= 8 and resp_recover[7] == 0x02:
                 print(f"{Fore.GREEN}PASS: 恢复后验证成功，第八组数据仍为 02{Style.RESET_ALL}")
                 self.last_post_result = "PASS"
                 return True
            else:
                 val = f"{resp_recover[7]:02X}" if len(resp_recover) >= 8 else "None"
                 print(f"{Fore.RED}FALSE: 恢复后验证失败，第八组数据为 {val}{Style.RESET_ALL}")
                 self.last_post_result = "FAIL"
                 return False
        except Exception as e:
            print(f"{Fore.RED}FALSE: 验证过程中发生异常 - {e}{Style.RESET_ALL}")
            self.last_post_result = "FAIL"
            return False

def main():
    # 测试时可以修改为实际连接的 COM 端口，请根据设备管理器的端口进行修改
    COM_PORT = 'COM1'
    BAUDRATE = 115200
    
    ucut_controller = PyserialUcut(port=COM_PORT, baudrate=BAUDRATE)
    
    print("========== 开始执行 ucut 注入前修调指令 ==========")
    success = ucut_controller.run_pre_injection_sequence()
    
    if success:
        print("\n========== 等待4秒恢复正常功能 ==========")
        time.sleep(4)
        
        print("\n========== 执行恢复后验证指令 ==========")
        ucut_controller.verify_after_recovery()
        
    ucut_controller.close()

if __name__ == '__main__':
    # 脚本单独运行时执行这里进行测试
    main()
