import tkinter as tk
from tkinter import ttk

def format_bytes(data):
    if isinstance(data, (bytes, bytearray)):
        return ' '.join([f"{b:02X}" for b in data])
    return ' '.join([f"{b:02X}" for b in data])

def create_tooltip(widget, text):
    def show_tooltip(event):
        tooltip = tk.Toplevel()
        tooltip.wm_overrideredirect(True)
        tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
        label = ttk.Label(tooltip, text=text, justify='left', relief='solid', borderwidth=1)
        label.pack()
        def hide_tooltip():
            tooltip.destroy()
        widget.tooltip = tooltip
        widget.bind('<Leave>', lambda e: hide_tooltip())
        tooltip.bind('<Leave>', lambda e: hide_tooltip())
    widget.bind('<Enter>', show_tooltip) 