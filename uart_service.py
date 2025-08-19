import time
import threading
from protocol import generate_read_command, generate_write_command, parse_response, generate_upgrade_packets, generate_upgrade_crc_command, calculate_crc16, generate_status_response, validate_value_for_type, to_signed
from protocol import (
    PU_FRAME_HEAD,MIN_PACKET_SIZE,UPGRADE_PACKET_SIZE,
    PU_FUN_READ, PU_FUN_WRITE, PU_FUN_UPGRADE, PU_FUN_UPGRADE_CRC,
    PU_FUN_MCU_RESET, PU_FUN_CONNECT,
    PU_FUN_MCU_WRITE_ALARM, PU_FUN_MCU_WRITE_CONFIG, PU_FUN_MCU_WRITE_DATA,
    PU_ACK_WITH_DATA, PU_ACK_NO_DATA
    
)
from protocol import (
    PU_STATUS_OK,
    PU_STATUS_NO_FUNCODE,
    PU_STATUS_CRC_ERROR,
    PU_STATUS_ADDRESS_ERROR,
    PU_STATUS_NO_PERMISSION,
    PU_STATUS_DATA_ERROR,
    PU_STATUS_WRITE_FLASHDB_ERROR,
    PU_STATUS_RW_I2C_ERROR,
    PU_STATUS_DATA_LENGTH_ERROR,
    PU_STATUS_UPGRADE_PACKAGE_CRC_ERROR
)

ALLOWED_FUN_CODES = {
    PU_FUN_READ, PU_FUN_WRITE, PU_FUN_UPGRADE, PU_FUN_UPGRADE_CRC,
    PU_FUN_MCU_RESET, PU_FUN_CONNECT,
    PU_FUN_MCU_WRITE_ALARM, PU_FUN_MCU_WRITE_CONFIG, PU_FUN_MCU_WRITE_DATA,
    PU_ACK_WITH_DATA, PU_ACK_NO_DATA

} 

class UARTService:
    def __init__(self, uart_interface, log_func=None, gui_update_callback=None, addr_map=None, f0_response_getter=None, response_40_50_getter=None):
        self.uart = uart_interface
        self.log_func = log_func or (lambda msg: None)
        self.gui_update_callback = gui_update_callback  # 新增
        self.pending_requests = {}
        self.pending_lock = threading.Lock()
        self.listener_thread = None
        self.running = False
        self.e0_handshake_thread = None
        self.e0_handshake_stop = threading.Event()
        self.mcu_connected = False
        self.addr_map = addr_map or {}  # 新增
        self.f0_response_getter = f0_response_getter or (lambda: False)
        self.response_40_50_getter = response_40_50_getter or (lambda: False)
    def start_listener(self):
        if self.listener_thread and self.listener_thread.is_alive():
            return
        self.running = True
        t = threading.Thread(target=self._listen, daemon=True)
        t.start()
        self.listener_thread = t

    def stop_listener(self):
        self.running = False
        if self.listener_thread:
            self.listener_thread.join(timeout=1)
            self.listener_thread = None

    def _listen(self):
        recv_buffer = bytearray()
        while self.running and self.uart.is_open():
            try:
                if self.uart.in_waiting() > 0:
                    recv_buffer += self.uart.read(self.uart.in_waiting())
                # 粘包处理循环
                while len(recv_buffer) >= MIN_PACKET_SIZE:
                    #在log中打印recv_buffer
                    #self.log_func(f"Recv buffer: {' '.join(f'{b:02X}' for b in recv_buffer)}")
                    # 1. 找包头
                    idx = recv_buffer.find(PU_FRAME_HEAD)
                    if idx == -1:
                        # 没有包头，全部丢弃
                        #在log中打印无效包
                        self.log_func(f"discard packet: NO HEAD{' '.join(f'{b:02X}' for b in recv_buffer)}")
                        recv_buffer.clear()
                        break
                    if idx > 0:
                        # 丢弃包头前的无效数据
                        recv_buffer = recv_buffer[idx:]
                    # 2. 检查最小长度
                    if len(recv_buffer) < MIN_PACKET_SIZE:
                        break  # 等待更多数据
                    # 3. 检查FUN_CODE
                    fun_code = recv_buffer[1]
                    if fun_code not in ALLOWED_FUN_CODES:
                        # FUN_CODE非法，丢弃当前包头到下一个包头之间的所有数据
                        next_head = recv_buffer[1:].find(PU_FRAME_HEAD)
                        if next_head == -1:
                            # 后面没有包头，全部丢弃
                            invalid_packet = recv_buffer[:]
                            self.log_func(
                                f"discard packet: INVALID FUN_CODE: 0x{fun_code:02X}, discard packet: " +
                                ' '.join(f'{b:02X}' for b in invalid_packet)
                            )
                            recv_buffer.clear()
                            break
                        else:
                            # 丢弃到下一个包头
                            invalid_packet = recv_buffer[:next_head+1]
                            self.log_func(
                                f"Invalid FUN_CODE: 0x{fun_code:02X}, discard packet: " +
                                ' '.join(f'{b:02X}' for b in invalid_packet)
                            )
                            recv_buffer = recv_buffer[next_head + 1:]
                        continue
                    # 4. 读取LEN字段
                    data_len = (recv_buffer[2] << 8) | recv_buffer[3]
                    total_len = 1 + 1 + 2 + data_len + 2  # 包头+FUN_CODE+LEN+DATA+CRC
                    if len(recv_buffer) < total_len:
                        break  # 数据还不够，等待下次
                    # 5. 取出完整包
                    packet = recv_buffer[:total_len]
                    #在log中打印packet
                    self.log_func(f"recv packet: {' '.join(f'{b:02X}' for b in packet)}")
                    fun_code = packet[1]
                    # 6. 处理包
                    if fun_code in (PU_FUN_CONNECT, PU_FUN_MCU_RESET):  # 只对E0/F0做握手处理
                        if self.handle_handshake(packet):
                            recv_buffer = recv_buffer[total_len:]
                            continue
                    self.handle_serial_data(packet)
                    recv_buffer = recv_buffer[total_len:]
                time.sleep(0.01)
            except Exception as e:
                self.log_func(f"Listener error: {e}")
                break

    def handle_handshake(self, data):
        # 检查是否为握手帧，如果是则自动回复
        # 握手帧格式: 5A F0 00 00 + CRC(2字节)
        if len(data) == 6 and data[0] == PU_FRAME_HEAD and data[1] == PU_FUN_MCU_RESET and data[2] == 0x00 and data[3] == 0x00:
            received_crc = (data[4] << 8) | data[5]
            calculated_crc = calculate_crc16(data[:4], 4)
            if received_crc == calculated_crc:
                try:
                    self.log_func("MCU RESET")
                    if self.f0_response_getter():
                        self.uart.write(data)
                        self.log_func("Recv handshake, sent handshake reply.")
                except Exception as e:
                    self.log_func(f"Handshake reply failed: {e}")
                return True
            else:
                if self.f0_response_getter():
                    self.send_status_response(PU_FUN_MCU_RESET, PU_STATUS_CRC_ERROR)
                    return False
        # 检查E0握手回复
        if len(data) == 6 and data[0] == PU_FRAME_HEAD and data[1] == PU_FUN_CONNECT and data[2] == 0x00 and data[3] == 0x00:
            received_crc = (data[4] << 8) | data[5]
            calculated_crc = calculate_crc16(data[:4], 4)
            if received_crc == calculated_crc:
                self.mcu_connected = True
                self.log_func("MCU connected")
                self.e0_handshake_stop.set()
                return True
        return False

    def start_e0_handshake(self):
        self.mcu_connected = False
        self.e0_handshake_stop.clear()
        def handshake_loop():
            not_connected_logged = False
            while not self.mcu_connected and self.uart.is_open() and not self.e0_handshake_stop.is_set():
                try:
                    # 发送E0握手包
                    from protocol import generate_e0_handshake
                    e0_packet = generate_e0_handshake()
                    self.uart.write(e0_packet)
                    self.log_func("Send: " + ' '.join(f'{b:02X}' for b in e0_packet))
                    if not not_connected_logged:
                        self.log_func("MCU not connected")
                        not_connected_logged = True
                    time.sleep(0.5)
                except Exception as e:
                    break
        t = threading.Thread(target=handshake_loop, daemon=True)
        t.start()
        self.e0_handshake_thread = t

    def send_status_response(self, fun_code, status_code):
        #fun_code 是60 就不需要回复
        if fun_code == PU_FUN_MCU_WRITE_DATA:
            return
        resp = generate_status_response(fun_code, status_code)
        self.uart.write(resp)
        self.log_func(f"Send: {' '.join(f'{b:02X}' for b in resp)}")

    def handle_serial_data(self, data):
        try:
            # 1. CRC校验
            received_crc = (data[-2] << 8) | data[-1]
            calculated_crc = calculate_crc16(data[:-2], len(data)-2)
            fun_code = data[1]
            data_len = (data[2] << 8) | data[3]
            # 2. 处理MCU主动上报包
            if fun_code in (0x40, 0x50, 0x60):
                if received_crc != calculated_crc:
                    if self.response_40_50_getter():
                        self.send_status_response(fun_code, PU_STATUS_CRC_ERROR)
                        self.log_func("serial_data: CRC error, discard: " + ' '.join(f'{b:02X}' for b in data))
                        return
                if data_len % 6 != 0:
                    if self.response_40_50_getter():
                        self.send_status_response(fun_code, PU_STATUS_DATA_LENGTH_ERROR)
                        self.log_func(f"serial_data: invalid data_len for report, discard: " + ' '.join(f'{b:02X}' for b in data))
                        return
                status_code = PU_STATUS_OK
                for i in range(0, data_len, 6):
                    addr = (data[4+i] << 8) | data[5+i]
                    raw_value = (data[6+i] << 24) | (data[7+i] << 16) | (data[8+i] << 8) | data[9+i]
                    item = self.addr_map.get(addr)
                    if item is None:
                        status_code = PU_STATUS_ADDRESS_ERROR
                        self.log_func(f"MCU report: addr=0x{addr:04X}, value={raw_value}, status=ADDR_ERROR")
                        break
                    else:
                        # Parse value according to item type
                        try:
                            data_type = item.get('type', 'int32_t')
                            raw_data = data[6+i:10+i]  # 4 bytes
                            from protocol import unpack_value_by_type
                            parsed_value = unpack_value_by_type(raw_data, data_type)
                            self.log_func(f"MCU report: addr=0x{addr:04X}, value={parsed_value} ({data_type}), status=OK")
                            if self.gui_update_callback:
                                self.gui_update_callback(addr, parsed_value)
                        except Exception as e:
                            # Fallback to original parsing
                            signed_value = to_signed(raw_value, bits=32)
                            self.log_func(f"MCU report: addr=0x{addr:04X}, value={signed_value} (fallback), status=OK")
                            if self.gui_update_callback:
                                self.gui_update_callback(addr, signed_value)
                if self.response_40_50_getter():
                    self.send_status_response(fun_code, status_code)
                return

            # 3. 其它包按原有逻辑处理
            if len(data) >= 8:
                resp_type = data[1]
                if resp_type in (0x11, 0xF1):  # PU_ACK_WITH_DATA, PU_ACK_NO_DATA
                    addr = (data[4] << 8) | data[5] if resp_type == 0x11 else None
                    with self.pending_lock:
                        for req_id, req in list(self.pending_requests.items()):
                            if req['type'] == 'read' and resp_type == 0x11 and req['addr'] == addr:
                                data_type = req.get('data_type', 'int32_t')
                                result = parse_response(data, is_write=False, expected_addr=addr, data_type=data_type)
                                req['callback'](result)
                                del self.pending_requests[req_id]
                                return
                            elif req['type'] == 'write' and resp_type == 0xF1:
                                result = parse_response(data, is_write=True)
                                req['callback'](result)
                                del self.pending_requests[req_id]
                                return
                            # === 新增升级包应答处理 ===
                            elif req['type'] == 'upgrade' and resp_type == 0xF1:
                                # 针对升级数据包
                                if 'pack_index' in req and isinstance(req['pack_index'], int) and data[4] == PU_FUN_UPGRADE:
                                    result = parse_response(data, is_write=True)
                                    req['callback'](result)
                                    del self.pending_requests[req_id]
                                    return
                                # 针对升级CRC校验包
                                elif req.get('pack_index') == 'crc' and data[4] == PU_FUN_UPGRADE_CRC:
                                    result = parse_response(data, is_write=True)
                                    req['callback'](result)
                                    del self.pending_requests[req_id]
                                    return
        except Exception as e:
            self.log_func(f"Error parsing serial data: {e}")

    def read_item(self, item, callback, timeout=2.0):
        addr = int(item['index'], 16)
        data_type = item.get('type', 'int32_t')
        cmd = generate_read_command(addr)
        request_id = f"read_{addr}_{int(time.time()*1000)}"
        def on_response(result, error=None):
            callback(result, error)
        with self.pending_lock:
            self.pending_requests[request_id] = {
                'item': item,
                'type': 'read',
                'addr': addr,
                'data_type': data_type,
                'time': time.time(),
                'callback': on_response
            }
        self.uart.write(cmd)
        self.log_func(f"Send: {' '.join(f'{b:02X}' for b in cmd)}")
        # 等待应答
        event = threading.Event()
        def cb_wrap(result, error=None):
            callback(result, error)
            event.set()
        self.pending_requests[request_id]['callback'] = cb_wrap
        if not event.wait(timeout=timeout):
            callback(None, error='timeout')
            with self.pending_lock:
                if request_id in self.pending_requests:
                    del self.pending_requests[request_id]

    def write_item(self, item, value, callback, timeout=2.0):
        addr = int(item['index'], 16)
        data_type = item.get('type', 'int32_t')
        cmd = generate_write_command(addr, value, data_type)
        request_id = f"write_{addr}_{int(time.time()*1000)}"
        def on_response(result, error=None):
            callback(result, error)
        with self.pending_lock:
            self.pending_requests[request_id] = {
                'item': item,
                'type': 'write',
                'addr': addr,
                'data_type': data_type,
                'time': time.time(),
                'callback': on_response
            }
        self.uart.write(cmd)
        self.log_func(f"Send: {' '.join(f'{b:02X}' for b in cmd)}")
        # 等待应答
        event = threading.Event()
        def cb_wrap(result, error=None):
            callback(result, error)
            event.set()
        self.pending_requests[request_id]['callback'] = cb_wrap
        if not event.wait(timeout=timeout):
            callback(None, error='timeout')
            with self.pending_lock:
                if request_id in self.pending_requests:
                    del self.pending_requests[request_id]

    def upgrade_mcu(self, bin_data, progress_callback=None, timeout=2.0, max_retries=3):
        if len(bin_data) % UPGRADE_PACKET_SIZE != 0:
            self.log_func("upgrade failed bin size error")
            return False, "upgrade failed bin size error"
        packets = generate_upgrade_packets(bin_data)
        for upgrade_attempt in range(max_retries):
            self.log_func(f"Upgrade attempt {upgrade_attempt+1}/{max_retries}")
            # 1. 发送所有数据包
            for i, frame in enumerate(packets):
                retry_count = 0
                while retry_count < max_retries:
                    ack_event = threading.Event()
                    ack_result = {'ok': False, 'status_code': None}
                    def ack_callback(result, error=None):
                        if error:
                            ack_result['ok'] = False
                        else:
                            if result['status'] == 'success' or (result.get('status_code', 0) == PU_STATUS_OK):
                                ack_result['ok'] = True
                            else:
                                ack_result['ok'] = False
                            ack_result['status_code'] = result.get('status_code', None)
                        ack_event.set()
                    with self.pending_lock:
                        self.pending_requests[f'upgrade_{i}_{int(time.time()*1000)}'] = {
                            'type': 'upgrade',
                            'pack_index': i,
                            'time': time.time(),
                            'callback': ack_callback
                        }
                    self.uart.write(frame)
                    self.log_func(f"Send upgrade pack {i+1}/{len(packets)} (try {retry_count+1}): {' '.join(f'{b:02X}' for b in frame[:16])} ... [{len(frame)} bytes]")
                    if ack_event.wait(timeout=timeout):
                        if ack_result['ok']:
                            break
                        else:
                            self.log_func(f"Upgrade pack {i+1} failed, status: {ack_result['status_code']}")
                            return False, f"Upgrade pack {i+1} failed, status: {ack_result['status_code']}"
                    else:
                        retry_count += 1
                        self.log_func(f"Upgrade pack {i+1} timeout, retry {retry_count}")
                        if retry_count >= max_retries:
                            return False, f"Upgrade pack {i+1} timeout after {max_retries} retries"
                    if progress_callback:
                        progress_callback(i+1, len(packets))
                    time.sleep(0.05)
            # 2. 发送升级CRC校验命令
            crc_cmd = generate_upgrade_crc_command(bin_data, len(packets))
            crc_ack_event = threading.Event()
            crc_ack_result = {'ok': False, 'status_code': None}
            def crc_ack_callback(result, error=None):
                if error:
                    crc_ack_result['ok'] = False
                else:
                    if result['status'] == 'success' or (result.get('status_code', 0) == PU_STATUS_OK):
                        crc_ack_result['ok'] = True
                    else:
                        crc_ack_result['ok'] = False
                    crc_ack_result['status_code'] = result.get('status_code', None)
                crc_ack_event.set()
            with self.pending_lock:
                self.pending_requests[f'upgrade_crc_{int(time.time()*1000)}'] = {
                    'type': 'upgrade',
                    'pack_index': 'crc',
                    'time': time.time(),
                    'callback': crc_ack_callback
                }
            try:
                self.uart.write(crc_cmd)
                self.log_func(f"Send upgrade CRC command: {' '.join(f'{b:02X}' for b in crc_cmd)}")
            except Exception as e:
                self.log_func(f"Error sending upgrade CRC command: {e}")
                return False, f"Failed to send upgrade CRC command: {e}"
            # 3. 等待CRC回复
            if crc_ack_event.wait(timeout=10.0):
                if crc_ack_result['ok']:
                    self.log_func("Upgrade success")
                    return True, f"Upgrade file sent, total {len(packets)} packets."
                else:
                    self.log_func(f"Upgrade CRC check failed, status: {crc_ack_result['status_code']}, retrying whole upgrade...")
                    continue  # 整个升级流程重试
            else:
                self.log_func("Upgrade CRC check timeout, retrying whole upgrade...")
                continue  # 整个升级流程重试
        return False, f"Upgrade failed after {max_retries} attempts."

    def is_mcu_connected(self):
        return self.mcu_connected 

