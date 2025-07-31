#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk
import serial
import time
import json
import tkinter.messagebox as messagebox
import sys
import traceback
import serial.tools.list_ports
import threading
from tkinter import filedialog
import datetime
from protocol import (
    PU_FRAME_HEAD, PU_FUN_READ, PU_FUN_WRITE, PU_FUN_UPGRADE, PU_FUN_UPGRADE_CRC,
    PU_FUN_MCU_RESET, PU_FUN_CONNECT, PU_FUN_MCU_WRITE_ALARM, PU_FUN_MCU_WRITE_CONFIG, PU_FUN_MCU_WRITE_DATA,
    PU_ACK_WITH_DATA, PU_ACK_NO_DATA,
    PU_STATUS_OK, PU_STATUS_NO_FUNCODE, PU_STATUS_CRC_ERROR, PU_STATUS_ADDRESS_ERROR, PU_STATUS_NO_PERMISSION,
    PU_STATUS_DATA_ERROR, PU_STATUS_WRITE_FLASHDB_ERROR, PU_STATUS_RW_I2C_ERROR, PU_STATUS_DATA_LENGTH_ERROR,
    PU_STATUS_UPGRADE_PACKAGE_CRC_ERROR,
    calculate_crc16, to_signed, generate_read_command, generate_write_command, parse_response,
    calculate_complete_addr, generate_e0_handshake, generate_upgrade_packets, generate_upgrade_crc_command,
    UPGRADE_PACKET_SIZE
)
from uart_interface import UARTInterface
from log_manager import LogManager
from label_manager import LabelManager
from item_manager import ItemManager
import utils
from uart_service import UARTService


RECYCLE_TIME = 0.5
class UARTTestGUI:
    def __init__(self, root):
        try:
            #根窗口
            self.root = root
            
            # Configure styles 一些风格用于后面子模块的显示
            self.style = ttk.Style()
            self.style.configure("Module.TFrame", borderwidth=2, relief="raised")
            self.style.configure("Submodule.TFrame", borderwidth=1, relief="solid")
            self.style.configure("ModuleHeader.TFrame", background="#e1e1e1")
            self.style.configure("SubmoduleHeader.TFrame", background="#f0f0f0")
            
            # Serial port configuration 串口接口初始化
            self.uart = UARTInterface()
            
            # Dictionary to store variables and frames 初始化变量存储结构
            self.result_vars = {}
            self.input_vars = {}
            self.write_status_vars = {}
            self.module_frames = {}
            self.submodule_frames = {}
            self.module_states = {}
            self.submodule_states = {}
            
            # Store references for language updates 
            self.module_labels = {}                 #模块标签
            self.submodule_labels = {}              #子模块标签
            self.module_read_buttons = {}           #模块读取按钮
            self.module_write_buttons = {}          #模块写入按钮
            self.submodule_read_buttons = {}
            self.submodule_write_buttons = {}
            self.item_read_buttons = {}
            self.item_write_buttons = {}
            
            # 管理类实例化
            self.log_manager = LogManager()         #
            self.label_manager = LabelManager()
            self.item_manager = ItemManager(language=self.label_manager.current_language)
            # 日志回调绑定
            self.log_manager.set_log_callback(self._log_callback)
            
            # Load labels
            self.current_language = self.label_manager.current_language
            self.load_labels()
            
            # 设置默认串口
            self.default_port = 'COM1' if sys.platform == 'win32' else '/dev/ttyS0'
            
            # 创建主界面
            self.create_widgets()
            
            # 加载配置文件
            try:
                self.create_items()
            except Exception as e:
                messagebox.showerror("Error", f"加载配置文件失败：\n{str(e)}")
                raise
            
            # 在 __init__ 或 create_items 后
            self.addr_map = {}
            for item in self.items:
                addr = int(item['index'], 16)
                self.addr_map[addr] = item

            self.uart_service = UARTService(
                self.uart,
                log_func=self.add_to_log,
                gui_update_callback=self.update_item_display,
                addr_map=self.addr_map,
                f0_response_getter=lambda: self.f0_response_var.get(),  # 新增
                response_40_50_getter=lambda: self.response_40_50_var.get()  # 新增
            )
            self.loop_running = False  # <--- 在这里加上
                
        except Exception as e:
            error_msg = str(e)
            error_details = traceback.format_exc()
            with open('error_log.txt', 'w', encoding='utf-8') as f:
                f.write(f"GUI初始化错误: {error_msg}\n")
                f.write("详细信息:\n")
                f.write(error_details)
            raise

    # 标签相关
    def load_labels(self):
        self.label_manager.load_labels()
        self.labels = self.label_manager.labels
        self.current_language = self.label_manager.current_language

    def get_label(self, key):
        return self.label_manager.get_label(key)

    def toggle_language(self):
        self.current_language = "CN" if self.current_language == "EN" else "EN"
        self.label_manager.set_language(self.current_language)
        self.item_manager.set_language(self.current_language)
        self.update_interface_language()

    def update_interface_language(self):
        """Update all interface elements with new language"""
        # Update language button
        self.language_btn.configure(text=self.get_label("language"))
        
        # Update serial configuration frame
        self.serial_frame.configure(text=self.get_label("serial_config"))
        self.port_label.configure(text=self.get_label("port"))
        self.baudrate_label.configure(text=self.get_label("baudrate"))
        self.data_bits_label.configure(text=self.get_label("data_bits"))
        self.stop_bits_label.configure(text=self.get_label("stop_bits"))
        self.parity_label.configure(text=self.get_label("parity"))
        
        # Update connection button text based on connection status
        if self.uart.is_open():
            self.connect_btn.configure(text=self.get_label("disconnect"))
            self.status_label.configure(text=self.get_label("connected"))
        else:
            self.connect_btn.configure(text=self.get_label("connect"))
            self.status_label.configure(text=self.get_label("disconnected"))
            
        self.refresh_btn.configure(text=self.get_label("refresh"))
        self.read_all_btn.configure(text=self.get_label("read_all"))
        self.write_all_btn.configure(text=self.get_label("write_all"))
        self.upgrade_btn.configure(text=self.get_label("upgrade_mcu")) # Update upgrade button text
        self.loop_button.configure(text=self.get_label("cycle_send"))
        self.f0_response_checkbox.configure(text=self.get_label("F0_response"))
        self.response_40_50_checkbox.configure(text=self.get_label("40/50_report"))
        # Update communication log frame
        self.log_frame.configure(text=self.get_label("communication_log"))
        self.clear_log_btn.configure(text=self.get_label("clear_log"))
        self.save_log_checkbox.configure(text=self.get_label("save_log"))
        # Clear and recreate all items to update their language
        self.recreate_items()

    def recreate_items(self):
        """Recreate all items with current language"""
        # Save the current scroll position
        current_scroll = self.canvas.yview()
        
        # Clear existing items
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        #save item tracking dictionaries  
        old_result_values ={k:v.get() for k,v in self.result_vars.items()}
        old_input_values ={k:v.get() for k,v in self.input_vars.items()if v is not None}
        old_write_status_values ={k:v.get() for k,v in self.write_status_vars.items()if v is not None}
        # Clear item tracking dictionaries
        self.organized_items = {}
        self.module_states = {}
        self.submodule_states = {}
        self.item_read_buttons = {}
        self.item_write_buttons = {}
        self.result_vars = {}
        self.input_vars = {}
        self.write_status_vars = {}
        
        # Recreate items
        self.create_items(old_result_values, old_input_values, old_write_status_values)
        
        # Restore scroll position
        self.canvas.yview_moveto(current_scroll[0])

    # 参数项相关
    def create_items(self, old_result_values=None, old_input_values=None, old_write_status_values=None):
        self.item_manager.load_items()
        self.items = self.item_manager.items
        self.organized_items = self.item_manager.get_organized_items()

        # Clear existing frames
        self.module_frames.clear()
        self.submodule_frames.clear()

        # Organize items by module and submodule
        self.organized_items = {}
        for item in self.items:
            module = item.get("Module" if self.current_language == "EN" else "模块", "Uncategorized")
            submodule = item.get("Submodule" if self.current_language == "EN" else "子模块", "Others")
            
            if module not in self.organized_items:
                self.organized_items[module] = {}
                self.module_states[module] = True
            
            if submodule not in self.organized_items[module]:
                self.organized_items[module][submodule] = []
                self.submodule_states[f"{module}_{submodule}"] = True
            
            self.organized_items[module][submodule].append(item)

        # Create frames for each module
        current_row = 0
        for module in self.organized_items:
            # Create module header
            module_frame = ttk.Frame(self.scrollable_frame)
            module_frame.grid(row=current_row, column=0, sticky='ew', pady=2)
            module_frame.columnconfigure(0, weight=1)
            current_row += 1
            
            # Create module header with expand/collapse button
            self.create_module_header(module, module_frame)
            
            # Create content frame for this module
            content_frame = ttk.Frame(self.scrollable_frame)
            content_frame.grid(row=current_row, column=0, sticky='ew')
            content_frame.columnconfigure(0, weight=1)
            current_row += 1
            self.module_frames[module] = content_frame
            
            # Create submodules
            submodule_row = 0
            for submodule in self.organized_items[module]:
                # Create submodule header
                submodule_frame = ttk.Frame(content_frame)
                submodule_frame.grid(row=submodule_row, column=0, sticky='ew', pady=2)
                submodule_frame.columnconfigure(0, weight=1)
                submodule_row += 1
                
                # Create submodule header with expand/collapse button
                self.create_submodule_header(module, submodule, submodule_frame)
                
                # Create items for this submodule
                items_frame = ttk.Frame(content_frame)
                items_frame.grid(row=submodule_row, column=0, sticky='ew')
                items_frame.columnconfigure(0, weight=1)
                submodule_row += 1
                self.submodule_frames[(module, submodule)] = items_frame
                
                # Create individual item frames
                item_row = 0
                for item in self.organized_items[module][submodule]:
                    item_frame = self.create_item_frame(items_frame, item, old_result_values, old_input_values, old_write_status_values)
                    if item_frame:
                        item_frame.grid(row=item_row, column=0, sticky='ew', pady=2)
                        item_row += 1

            # Apply current expansion state
            if not self.module_states.get(module, True):
                content_frame.grid_remove()

            # Apply submodule expansion states
            for submodule in self.organized_items[module]:
                state_key = f"{module}_{submodule}"
                if not self.submodule_states.get(state_key, True):
                    if (module, submodule) in self.submodule_frames:
                        self.submodule_frames[(module, submodule)].grid_remove()

    def create_item_frame(self, parent, item, old_result_values=None, old_input_values=None, old_write_status_values=None):
        """Create a frame for displaying and controlling a single item"""
        try:
            # Create a frame for this item
            item_frame = ttk.Frame(parent)
            item_frame.grid(row=0, column=0, sticky='ew', pady=2)
           

            # Configure column weights for better layout
            item_frame.columnconfigure(0, weight=0)  # Label column - fixed
            item_frame.columnconfigure(1, weight=0)  # Read button - fixed
            item_frame.columnconfigure(2, weight=1)  # Result entry - expandable
            item_frame.columnconfigure(3, weight=0)  # Write button - fixed
            item_frame.columnconfigure(4, weight=1)  # Write entry - expandable
            item_frame.columnconfigure(5, weight=1)  # Status entry - expandable

            # Create item label with tooltip
            display_text = item.get('item' if self.current_language == 'EN' else '项目', '')
            item_label = ttk.Label(item_frame, text=display_text, width=47, anchor='w')
            item_label.grid(row=0, column=0, padx=(40, 5), sticky='w')
            item['label_widget'] = item_label
            
            # Create tooltip for the label
            self.create_tooltip(item_label, 
                              f"Address: {item['index']}\n"
                              f"Description: {item.get('item' if self.current_language == 'EN' else '项目', '')}\n"
                              f"Permission: {item.get('permission', 'R')}")

            # Create read button and result display
            read_btn = ttk.Button(item_frame, text=self.get_label("read"), width=6,
                                command=lambda: self.read_item(item))
            read_btn.grid(row=0, column=1, padx=2)
            #key = item.get('item' if self.current_language == 'EN' else '项目', '')
            key = item.get('index', '')
            self.item_read_buttons[key] = read_btn

            result_var = tk.StringVar(value=old_result_values.get(key, '')if old_result_values else '')
            result_entry = ttk.Entry(item_frame, textvariable=result_var,
                                   state='readonly', width=15)
            result_entry.grid(row=0, column=2, padx=2, sticky='ew')
            self.result_vars[key] = result_var

            # Create write button and input field if item is writable
            permission = item.get("permission", "R")

            # 只读项不显示写按钮和输入框
            if "W" in permission:
                write_btn = ttk.Button(item_frame, text=self.get_label("write"), width=6,
                                      command=lambda: self.write_item(item))
                write_btn.grid(row=0, column=3, padx=2)
                self.item_write_buttons[key] = write_btn

                #only use write data when there is no old value 
                if old_input_values and key in old_input_values:
                    write_var = tk.StringVar(value=old_input_values[key])
                elif 'write data' in item:
                    write_var = tk.StringVar(value=str(item['write data']))
                else:
                    write_var = tk.StringVar(value='')
                write_entry = ttk.Entry(item_frame, textvariable=write_var, width=15)
                write_entry.grid(row=0, column=4, padx=2, sticky='ew')
                self.input_vars[key] = write_var

                # Create write status display
                write_status_var = tk.StringVar(value=old_write_status_values.get(key, '')if old_write_status_values else '')
                write_status_entry = ttk.Entry(item_frame, textvariable=write_status_var,
                                              state='readonly', width=15)
                write_status_entry.grid(row=0, column=5, padx=2, sticky='ew')
                self.write_status_vars[key] = write_status_var
            else:
                # 没有写权限时，写相关控件不显示
                self.item_write_buttons[key] = None
                self.input_vars[key] = None
                self.write_status_vars[key] = None

            return item_frame
            
        except Exception as e:
            error_msg = str(e)
            error_details = traceback.format_exc()
            with open('error_log.txt', 'a', encoding='utf-8') as f:
                f.write(f"创建项目框架错误: {error_msg}\n")
                f.write("详细信息:\n")
                f.write(error_details)
            raise

    # 工具函数替换
    def create_tooltip(self, widget, text):
        utils.create_tooltip(widget, text)

    def format_bytes(self, data):
        return utils.format_bytes(data)

    def read_item(self, item):
        """Read value for a single item"""
        if not self.check_connection():
            return
        if not self.uart_service.is_mcu_connected():
            messagebox.showwarning("Warning", "MCU not connected. Please wait for handshake.")
            return
        addr_hex = item['index']
        def on_response(result, error=None):
            if error:
                if error == 'timeout':
                    self.result_vars[item['index']].set("timeout")
                    self.add_to_log(f"read {addr_hex} timeout")
                else:
                    self.result_vars[item['index']].set("err")
                    self.add_to_log(f"read {addr_hex} error: {error}")
            else:
                if result['status'] == 'success':
                    self.result_vars[item['index']].set(str(result['data']))
                elif result['status'] == 'error':
                    self.result_vars[item['index']].set(f"{result['status_code']:02X}")
                    self.add_to_log(f"read {addr_hex} status_code: {result['status_code']:02X}")
                else:
                    self.result_vars[item['index']].set("err")
                    self.add_to_log(f"read {addr_hex} unknown result: {result}")
        threading.Thread(target=lambda: self.uart_service.read_item(item, on_response), daemon=True).start()

    def write_item(self, item):
        """Write value for a single item"""
        if not self.check_connection():
            return
        if not self.uart_service.is_mcu_connected():
            messagebox.showwarning("Warning", "MCU not connected. Please wait for handshake.")
            return
        addr_hex = item['index']
        if item['index'] not in self.input_vars:
            self.write_status_vars[item['index']].set("err")
            return
        value_str = self.input_vars[item['index']].get().strip()
        if not value_str:
            self.write_status_vars[item['index']].set("err")
            return
        try:
            value = int(value_str, 16) if value_str.startswith('0x') else int(value_str)
        except ValueError:
            self.write_status_vars[item['index']].set("err")
            return
        def on_response(result, error=None):
            if error:
                if error == 'timeout':
                    self.write_status_vars[item['index']].set("timeout")
                    self.add_to_log(f"write {addr_hex} timeout")
                else:
                    self.write_status_vars[item['index']].set("err")
                    self.add_to_log(f"write {addr_hex} error: {error}")
            else:
                if result['status'] == 'success':
                    self.write_status_vars[item['index']].set("Write OK")
                elif result['status'] == 'error':
                    self.write_status_vars[item['index']].set(f"{result['status_code']:02X}")
                    self.add_to_log(f"write {addr_hex} status_code: {result['status_code']:02X}")
                else:
                    self.write_status_vars[item['index']].set("err")
                    self.add_to_log(f"write {addr_hex} unknown result: {result}")
        threading.Thread(target=lambda: self.uart_service.write_item(item, value, on_response), daemon=True).start()

    def create_widgets(self):
        try:
            # Create main frame with padding
            self.main_frame = ttk.Frame(self.root, padding="5")
            self.main_frame.pack(fill=tk.BOTH, expand=True)
            self.main_frame.columnconfigure(0, weight=1) #列
            # 合理分配三行高度
            self.main_frame.rowconfigure(0, weight=0)  # 语言切换
            self.main_frame.rowconfigure(1, weight=0)  # 串口配置
            self.main_frame.rowconfigure(2, weight=0)  # 全局读写按钮
            self.main_frame.rowconfigure(3, weight=1)  # 模块/参数区
            self.main_frame.rowconfigure(4, weight=1)  # 日志区

            # 语言切换按钮
            self.language_btn = ttk.Button(self.main_frame, text=self.get_label("language"),
                                         command=self.toggle_language, width=8)
            self.language_btn.grid(row=0, column=0, sticky='ne', pady=(0, 5))

            # 串口配置框
            self.serial_frame = ttk.LabelFrame(self.main_frame, text=self.get_label("serial_config"), padding="5")
            self.serial_frame.grid(row=1, column=0, sticky='ew', pady=(0, 5))
            for i in range(7):
                self.serial_frame.columnconfigure(i, weight=1)
            # ... 省略串口配置内容 ...
            # Row 1: Port and Baudrate
            self.port_label = ttk.Label(self.serial_frame, text=self.get_label("port"))
            self.port_label.grid(row=0, column=0, padx=5, pady=2)
            
            self.port_var = tk.StringVar(value=self.default_port)
            self.port_combo = ttk.Combobox(self.serial_frame, textvariable=self.port_var)
            self.port_combo.grid(row=0, column=1, padx=5, pady=2, sticky='ew')
            
            self.baudrate_label = ttk.Label(self.serial_frame, text=self.get_label("baudrate"))
            self.baudrate_label.grid(row=0, column=2, padx=5, pady=2)
            
            self.baud_var = tk.StringVar(value='115200')
            self.baud_combo = ttk.Combobox(self.serial_frame, textvariable=self.baud_var)
            self.baud_combo['values'] = ('9600', '19200', '38400', '57600', '115200')
            self.baud_combo.grid(row=0, column=3, padx=5, pady=2, sticky='ew')
            
            # Row 2: Data bits, Stop bits, Parity
            self.data_bits_label = ttk.Label(self.serial_frame, text=self.get_label("data_bits"))
            self.data_bits_label.grid(row=1, column=0, padx=5, pady=2)
            
            self.data_bits_var = tk.StringVar(value='8')
            self.data_bits_combo = ttk.Combobox(self.serial_frame, textvariable=self.data_bits_var)
            self.data_bits_combo['values'] = ('5', '6', '7', '8')
            self.data_bits_combo.grid(row=1, column=1, padx=5, pady=2, sticky='ew')
            
            self.stop_bits_label = ttk.Label(self.serial_frame, text=self.get_label("stop_bits"))
            self.stop_bits_label.grid(row=1, column=2, padx=5, pady=2)
            
            self.stop_bits_var = tk.StringVar(value='1')
            self.stop_bits_combo = ttk.Combobox(self.serial_frame, textvariable=self.stop_bits_var)
            self.stop_bits_combo['values'] = ('1', '1.5', '2')
            self.stop_bits_combo.grid(row=1, column=3, padx=5, pady=2, sticky='ew')
            
            self.parity_label = ttk.Label(self.serial_frame, text=self.get_label("parity"))
            self.parity_label.grid(row=1, column=4, padx=5, pady=2)
            
            self.parity_var = tk.StringVar(value='N')
            self.parity_combo = ttk.Combobox(self.serial_frame, textvariable=self.parity_var)
            self.parity_combo['values'] = ('N', 'E', 'O')
            self.parity_combo.grid(row=1, column=5, padx=5, pady=2, sticky='ew')
            
            # Connect button and status
            self.connect_btn = ttk.Button(self.serial_frame, text=self.get_label("connect"),
                                        command=self.toggle_connection)
            self.connect_btn.grid(row=0, column=4, rowspan=1, padx=5, pady=2, sticky='ew')

            self.status_label = ttk.Label(self.serial_frame, text=self.get_label("disconnected"),
                                        foreground="red")
            self.status_label.grid(row=0, column=5, rowspan=1, padx=5, pady=2)
            
            # Refresh port list button
            self.refresh_btn = ttk.Button(self.serial_frame, text=self.get_label("refresh"),
                                        command=self.refresh_ports)
            self.refresh_btn.grid(row=0, column=6, padx=5, pady=2, sticky='ew')

            # Create global Read All and Write All buttons frame
            global_btn_frame = ttk.Frame(self.main_frame)
            global_btn_frame.grid(row=2, column=0, sticky='e', pady=(0, 5))

            self.read_all_btn = ttk.Button(global_btn_frame, text=self.get_label("read_all"),
                                         command=self.read_all, width=12)
            self.read_all_btn.pack(side=tk.LEFT, padx=2)

            self.write_all_btn = ttk.Button(global_btn_frame, text=self.get_label("write_all"),
                                          command=self.write_all, width=12)
            self.write_all_btn.pack(side=tk.LEFT, padx=2)

            # 新增"upgrade mcu"按钮
            self.upgrade_btn = ttk.Button(global_btn_frame, text=self.get_label("upgrade_mcu"), command=self.upgrade_mcu, width=14)
            self.upgrade_btn.pack(side=tk.LEFT, padx=2)

            # 在升级按钮旁边加循环发送按钮
            self.loop_button = ttk.Button(global_btn_frame, text=self.get_label("cycle_send"), command=self.toggle_loop_send)
            self.loop_button.pack(side=tk.LEFT, padx=2)

            #f0 回复勾选框
            self.f0_response_var = tk.BooleanVar(value=True)
            self.f0_response_checkbox = ttk.Checkbutton(
                global_btn_frame, text=self.get_label("F0_response"), variable=self.f0_response_var
            )
            self.f0_response_checkbox.pack(side=tk.LEFT, padx=2)

            #40/50回复勾选框
            self.response_40_50_var = tk.BooleanVar(value=True)
            self.response_40_50_checkbox = ttk.Checkbutton(
                global_btn_frame, text=self.get_label("40/50_report"), variable=self.response_40_50_var
            )
            self.response_40_50_checkbox.pack(side=tk.LEFT, padx=2)


            # Create canvas and scrollbar for items
            canvas_frame = ttk.Frame(self.main_frame)
            canvas_frame.grid(row=3, column=0, columnspan=2, sticky='nsew')
            canvas_frame.grid_columnconfigure(0, weight=1)
            canvas_frame.grid_rowconfigure(0, weight=1)

            self.canvas = tk.Canvas(canvas_frame)
            scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
            self.scrollable_frame = ttk.Frame(self.canvas)

            self.scrollable_frame.bind(
                "<Configure>",
                lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            )

            # 创建画布窗口
            self.canvas_window = self.canvas.create_window(
                (0, 0),
                window=self.scrollable_frame,
                anchor="nw",
                width=self.canvas.winfo_width()  # 设置初始宽度
            )

            # 绑定画布大小变化事件
            self.canvas.bind('<Configure>', self.on_canvas_configure)
            
            # 配置画布和滚动条
            self.canvas.configure(yscrollcommand=scrollbar.set)
            self.canvas.grid(row=0, column=0, sticky='nsew')
            scrollbar.grid(row=0, column=1, sticky='ns')

            # 配置画布框架
            self.scrollable_frame.columnconfigure(0, weight=1)

            # 添加鼠标滚轮支持
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)


            # Update communication log frame
            self.log_frame = ttk.LabelFrame(self.main_frame, text=self.get_label("communication_log"),
                                          padding="5")
            self.log_frame.grid(row=4, column=0, sticky='nsew', pady=(5, 0))
            self.log_frame.columnconfigure(0, weight=1)
            self.log_frame.rowconfigure(0, weight=1)

            # Create text widget for logging with scrollbar
            self.log_text = tk.Text(self.log_frame, height=6, wrap=tk.WORD)
            log_scrollbar = ttk.Scrollbar(self.log_frame, orient="vertical",
                                        command=self.log_text.yview)
            self.log_text.configure(yscrollcommand=log_scrollbar.set)
            
            self.log_text.grid(row=0, column=0, sticky='nsew')
            log_scrollbar.grid(row=0, column=1, sticky='ns')

            # Configure log text widget禁止输入
            self.log_text.configure(state='disabled')

            # Add clear log button
            self.clear_log_btn = ttk.Button(self.log_frame, text=self.get_label("clear_log"),
                                          command=self.clear_log)
            self.clear_log_btn.grid(row=1, column=0, columnspan=2, pady=(5,0))
            
            # Save Log checkbox
            self.save_log_var = tk.BooleanVar(value=False)
            self.save_log_checkbox = ttk.Checkbutton(
                self.log_frame, text=self.get_label("save_log"), variable=self.save_log_var, command=self.on_save_log_toggle
            )
            self.save_log_checkbox.grid(row=2, column=0, sticky='w', padx=5, pady=(0, 5))

            self.log_file_path = None  # 保存日志文件路径
            
            # Initialize port list
            self.refresh_ports()
            
        except Exception as e:
            error_msg = str(e)
            error_details = traceback.format_exc()
            with open('error_log.txt', 'w', encoding='utf-8') as f:
                f.write(f"创建界面错误: {error_msg}\n")
                f.write("详细信息:\n")
                f.write(error_details)
            raise

    def _on_mousewheel(self, event):
        """处理鼠标滚轮事件"""
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception as e:
            # 忽略滚动错误
            pass

    def on_canvas_configure(self, event):
        """处理画布大小变化事件"""
        try:
            # 更新滚动区域
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            
            # 更新画布窗口宽度以匹配画布
            if hasattr(self, 'canvas_window'):
                self.canvas.itemconfig(self.canvas_window, width=event.width)
                
        except Exception as e:
            # 记录错误但不抛出以防止崩溃
            with open('error_log.txt', 'a', encoding='utf-8') as f:
                f.write(f"\n窗口调整错误: {str(e)}\n")
                f.write(traceback.format_exc())

    def refresh_ports(self):
        """Refresh the available serial ports list"""
        ports = UARTInterface.list_ports()
        self.port_combo['values'] = ports
        if ports and not self.port_var.get() in ports:
            self.port_var.set(ports[0])

    def toggle_connection(self):
        """Toggle serial port connection"""
        if not self.uart.is_open():
            try:
                # Check if port is selected
                port = self.port_var.get()
                if not port:
                    messagebox.showwarning("Warning", "Please select a serial port")
                    return
                self.uart.open(
                    port=port,
                    baudrate=int(self.baud_var.get()),
                    bytesize=int(self.data_bits_var.get()),
                    stopbits=float(self.stop_bits_var.get()),
                    parity=self.parity_var.get(),
                    timeout=1
                )
                self.status_label.config(text="Connected", foreground="green")
                self.connect_btn.config(text="Disconnect")
                self.port_combo.state(['disabled'])
                self.baud_var.set(self.baud_var.get())
                # Start listener and handshake via uart_service
                self.uart_service.start_listener()
                self.uart_service.start_e0_handshake()
            except serial.SerialException as e:
                error_msg = str(e)
                if "PermissionError" in error_msg:
                    messagebox.showerror("Error", f"Cannot open port, it may be in use\n{port}")
                elif "FileNotFoundError" in error_msg:
                    messagebox.showerror("Error", f"Port not found\n{port}")
                else:
                    messagebox.showerror("Error", f"Failed to connect:\n{error_msg}")
            except Exception as e:
                messagebox.showerror("Error", f"Connection error:\n{str(e)}")
        else:
            try:
                self.uart.close()
                self.status_label.config(text="Disconnected", foreground="red")
                self.connect_btn.config(text="Connect")
                self.port_combo.state(['!disabled'])
                # Stop listener via uart_service
                self.uart_service.stop_listener()
            except Exception as e:
                messagebox.showerror("Error", f"Error disconnecting:\n{str(e)}")

    def create_module_header(self, module, content_frame):
        # Create header frame
        header_frame = ttk.Frame(content_frame, style="ModuleHeader.TFrame")
        header_frame.grid(row=0, column=0, sticky='ew')
        header_frame.columnconfigure(1, weight=1)
        
        # Create expand/collapse button
        button_text = "[-]" if self.module_states.get(module, True) else "[+]"
        button = ttk.Button(header_frame, text=button_text, width=3,
                          command=lambda: self.toggle_module(module, button))
        button.grid(row=0, column=0, padx=5, pady=2)
        
        # Create module label (without "Module:" prefix)
        module_label = ttk.Label(header_frame, text=module)
        module_label.grid(row=0, column=1, sticky='w', padx=5, pady=2)
        self.module_labels[module] = module_label
        
        # Create module-level Read All and Write All buttons
        read_btn = ttk.Button(header_frame, text=self.get_label("read_all"),
                            command=lambda: self.read_module(module), width=12)
        read_btn.grid(row=0, column=2, padx=2, pady=2)
        self.module_read_buttons[module] = read_btn
        
        write_btn = ttk.Button(header_frame, text=self.get_label("write_all"),
                             command=lambda: self.write_module(module), width=12)
        write_btn.grid(row=0, column=3, padx=2, pady=2)
        self.module_write_buttons[module] = write_btn
        
        return header_frame

    def create_submodule_header(self, module, submodule, content_frame):
        # Create header frame
        header_frame = ttk.Frame(content_frame, style="SubmoduleHeader.TFrame")
        header_frame.grid(row=0, column=0, sticky='ew')
        header_frame.columnconfigure(1, weight=1)
        
        # Create expand/collapse button
        button_text = "[-]" if self.submodule_states.get(f"{module}_{submodule}", True) else "[+]"
        button = ttk.Button(header_frame, text=button_text, width=3,
                          command=lambda: self.toggle_submodule(module, submodule, button))
        button.grid(row=0, column=0, padx=(20, 5), pady=2)
        
        # Create submodule label (without "Submodule:" prefix)
        submodule_label = ttk.Label(header_frame, text=submodule)
        submodule_label.grid(row=0, column=1, sticky='w', padx=5, pady=2)
        self.submodule_labels[f"{module}_{submodule}"] = submodule_label
        
        # Create submodule-level Read All and Write All buttons
        read_btn = ttk.Button(header_frame, text=self.get_label("read_all"),
                            command=lambda: self.read_submodule(module, submodule), width=12)
        read_btn.grid(row=0, column=2, padx=2, pady=2)
        self.submodule_read_buttons[f"{module}_{submodule}"] = read_btn
        
        write_btn = ttk.Button(header_frame, text=self.get_label("write_all"),
                             command=lambda: self.write_submodule(module, submodule), width=12)
        write_btn.grid(row=0, column=3, padx=2, pady=2)
        self.submodule_write_buttons[f"{module}_{submodule}"] = write_btn
        
        return header_frame

    def check_connection(self):
        """Check if serial port is connected"""
        if not self.uart.is_open():
            messagebox.showwarning("Warning", "Serial port not connected. Please connect first!")
            return False
        return True

    def read_all(self):
        """Print read commands for all items"""
        if not self.check_connection():
            return
            
        print("=== Reading All Items ===")
        for module in self.organized_items.values():
            for submodule in module.values():
                for item in submodule:
                    self.read_item(item)
    
    def write_all(self):
        """Print write commands for writable items"""
        if not self.check_connection():
            return
            
        print("=== Writing All Writable Items ===")
        for module in self.organized_items.values():
            for submodule in module.values():
                for item in submodule:
                    if "W" in item["permission"]:
                        self.write_item(item)
    
    def read_module(self, module):
        """Read all items in a module"""
        if not self.check_connection():
            return
            
        print(f"=== Reading All Items in Module: {module} ===")
        for submodule in self.organized_items[module].values():
            for item in submodule:
                self.read_item(item)

    def write_module(self, module):
        """Write all writable items in a module"""
        if not self.check_connection():
            return
            
        print(f"=== Writing All Items in Module: {module} ===")
        for submodule in self.organized_items[module].values():
            for item in submodule:
                if "W" in item["permission"]:
                    self.write_item(item)

    def read_submodule(self, module, submodule):
        """Read all items in a submodule"""
        if not self.check_connection():
            return
            
        print(f"=== Reading All Items in Submodule: {submodule} ===")
        for item in self.organized_items[module][submodule]:
            self.read_item(item)

    def write_submodule(self, module, submodule):
        """Write all writable items in a submodule"""
        if not self.check_connection():
            return
            
        print(f"=== Writing All Items in Submodule: {submodule} ===")
        for item in self.organized_items[module][submodule]:
            if "W" in item["permission"]:
                self.write_item(item)
    
    def toggle_module(self, module, button):
        """Toggle module expansion state"""
        try:
            if self.module_states[module]:  # Currently expanded
                button.configure(text="[+]")
                self.module_states[module] = False
                if module in self.module_frames:
                    self.module_frames[module].grid_remove()
            else:  # Currently collapsed
                button.configure(text="[-]")
                self.module_states[module] = True
                if module in self.module_frames:
                    self.module_frames[module].grid()
        except Exception as e:
            print(f"Error in toggle_module: {e}")

    def toggle_submodule(self, module, submodule, button):
        """Toggle submodule expansion state"""
        try:
            state_key = f"{module}_{submodule}"
            if self.submodule_states.get(state_key, True):  # Currently expanded
                button.configure(text="[+]")
                self.submodule_states[state_key] = False
                if (module, submodule) in self.submodule_frames:
                    self.submodule_frames[(module, submodule)].grid_remove()
            else:  # Currently collapsed
                button.configure(text="[-]")
                self.submodule_states[state_key] = True
                if (module, submodule) in self.submodule_frames:
                    self.submodule_frames[(module, submodule)].grid()
        except Exception as e:
            print(f"Error in toggle_submodule: {e}")
    def toggle_loop_send(self):
        if not self.loop_running:
            # 检查串口连接
            if not self.check_connection():
                messagebox.showwarning("警告", "请先连接串口！")
                return
            if not self.uart_service.is_mcu_connected():
                messagebox.showwarning("Warning", "MCU not connected. Please wait for handshake.")
                return
            self.loop_running = True
            self.loop_button.config(text="stop send")
            threading.Thread(target=self.loop_send_items, daemon=True).start()
        else:
            self.loop_running = False
            self.loop_button.config(text="cycle send")

    def loop_send_items(self):
        while self.loop_running:
            if not self.check_connection():
                self.add_to_log("串口未连接，循环发送已停止。")
                self.loop_running = False
                self.loop_button.config(text="cycle send")
                break
            if not self.uart_service.is_mcu_connected():
                self.add_to_log("MCU not connected. Please wait for handshake.")
                self.loop_running = False
                self.loop_button.config(text="cycle send")
                break
            for item in self.items:
                if not self.loop_running:
                    break
                permission = item.get('permission', '')
                # 先read
                event = threading.Event()
                def read_cb(result, error=None):
                    if error:
                        self.result_vars[item['index']].set("timeout")
                        self.add_to_log(f"Read {item.get('name', item.get('index'))} timeout")
                    event.set()
                self.uart_service.read_item(item, callback=read_cb)
                event.wait(timeout=2.0)
                if permission == 'W':
                    # 再write，写入当前显示框的值或默认值
                    value = 0
                    addr_hex = f"0x{int(str(item['index']), 16):04X}"
                    if addr_hex in self.input_vars:
                        try:
                            value = int(self.input_vars[addr_hex].get())
                        except Exception:
                            value = 0
                    event2 = threading.Event()
                    def write_cb(result, error=None):
                        if error:
                            self.write_status_vars[item['index']].set("timeout")
                            self.add_to_log(f"Write {item.get('name', item.get('index'))} timeout")
                        event2.set()
                    self.uart_service.write_item(item, value, callback=write_cb)
                    event2.wait(timeout=2.0)
            # 可加延时，避免过快
            time.sleep(RECYCLE_TIME)
    def __del__(self):
        self.uart.close()

    def clear_log(self):
        """Clear the communication log"""
        self.log_manager.clear_log()

    def add_to_log(self, message):
        self.log_manager.add_log(message)

    def format_bytes(self, data):
        return utils.format_bytes(data)

    # Remove protocol/serial/handshake/timeout logic now handled by uart_service
    # def handle_handshake(self, data): ...
    # def start_e0_handshake(self): ...
    # def start_serial_listener(self): ...
    # def handle_serial_data(self, data): ...
    # def check_pending_timeouts(self): ...

    def on_save_log_toggle(self):
        if self.save_log_var.get():
            # 勾选时弹出文件保存对话框
            file_path = filedialog.asksaveasfilename(
                title="Select Log File",
                defaultextension=".txt",
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
            )
            if file_path:
                self.log_manager.set_log_file_path(file_path)
                # 立即保存当前log内容到文件
                self.save_current_log_to_file()
            else:
                # 用户取消选择，取消勾选
                self.save_log_var.set(False)
                self.log_manager.set_log_file_path(None)
        else:
            # 取消勾选时，清除路径
            self.log_manager.set_log_file_path(None)

    def save_current_log_to_file(self):
        log_content = self.log_text.get("1.0", tk.END)
        self.log_manager.save_current_log_to_file(log_content)

    def upgrade_mcu(self):
        if not self.check_connection():
            return
        if not self.uart_service.is_mcu_connected():
            messagebox.showwarning("Warning", "MCU not connected. Please wait for handshake.")
            return
        file_path = filedialog.askopenfilename(
            title="Select MCU Upgrade .bin File",
            filetypes=[("BIN Files", "*.bin"), ("All Files", "*.*")]
        )
        if not file_path:
            return
        try:
            with open(file_path, 'rb') as f:
                bin_data = f.read()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read bin file:\n{e}")
            return
        def on_progress(current, total):
            self.add_to_log(f"Upgrade progress: {current}/{total}")
        def do_upgrade():
            success, msg = self.uart_service.upgrade_mcu(bin_data, progress_callback=on_progress)
            if success:
                messagebox.showinfo("Upgrade", msg)
            else:
                messagebox.showerror("Upgrade Error", msg)
        threading.Thread(target=do_upgrade, daemon=True).start()

    def _log_callback(self, message):
        def append_log():
            try:
                if message == "__CLEAR__":
                    self.log_text.configure(state='normal')
                    self.log_text.delete(1.0, tk.END)
                    self.log_text.configure(state='disabled')
                else:
                    self.log_text.configure(state='normal')
                    self.log_text.insert(tk.END, message + '\n')
                    self.log_text.see(tk.END)
                    self.log_text.configure(state='disabled')
                #self.root.update_idletasks()  # 强制刷新
            except Exception as e:
                print("Log append error:", e)
        self.root.after(0, append_log)

    def update_item_display(self, addr, value):
        # addr 是 int 类型，转成 0xXXXX 格式字符串
        addr_hex = f"0x{addr:04X}"
        signed_value = to_signed(value, bits=32)
        if addr_hex in self.result_vars:
            self.result_vars[addr_hex].set(str(signed_value))
            #self.add_to_log(f"MCU report: {addr_hex} = {signed_value}")
        else:
            #self.add_to_log(f"MCU report: Unknown address {addr_hex} = {signed_value}")
            pass

if __name__ == "__main__":
    root = tk.Tk()
    app = UARTTestGUI(root)
    root.mainloop() 
