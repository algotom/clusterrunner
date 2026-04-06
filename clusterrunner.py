import os
import sys
import ast
import csv
import shlex
import time
import socket
import signal
import textwrap
import json
import platform
import argparse
import threading
import queue
import logging
import tkinter as tk
import tkinter.font as tkFont
from datetime import datetime
from tkinter import ttk, messagebox, simpledialog, filedialog
import paramiko

try:
    from idlelib.colorizer import ColorDelegator
    from idlelib.percolator import Percolator
except ImportError:
    ColorDelegator = None
    Percolator = None

# ==============================================================================
#                          Configuration & Constants
# ==============================================================================

FONT_FAMILY = "Segoe UI" if os.name == "nt" else "Helvetica"
FONT_SIZE = 12
HEADER_FONT_SIZE = 12
CONSOLE_FONT = 10
CODE_FONT_SIZE = 11
FONT_WEIGHT = "normal"
TTK_THEME = "clam"

BG_COLOR_OUTPUT = "#f0f0f0"
FG_COLOR_OUTPUT = "black"
LISTBOX_SELECT_BG = "#cce8ff"
LISTBOX_SELECT_FG = "black"
PATH_COLOR = "#0055aa"
LINE_NUM_BG = "#e0e0e0"
LINE_NUM_FG = "#555555"

MAIN_WIN_RATIO = 0.85
CHILD_WIN_RATIO = 0.8
TEXT_WIN_RATIO = 0.8
# Job monitor refresh time
REFRESH_TIME = 2

TYPE_MAP = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}


# ==============================================================================
#                          Utility Functions
# ==============================================================================


def get_config_path():
    """
    Get path to save a config file depending on the OS system.
    """
    home = os.path.expanduser("~")
    if platform.system() == "Windows":
        return os.path.join(home, "AppData", "Roaming", "ClusterRunner",
                            "cluster_runner_config.json")
    elif platform.system() == "Darwin":
        return os.path.join(home, "Library", "Application Support",
                            "ClusterRunner", "cluster_runner_config.json")
    else:
        return os.path.join(home, ".cluster_runner",
                            "cluster_runner_config.json")


def load_config():
    """
    Load the config file.
    """
    config_path = get_config_path()
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_config(data):
    """
    Save data (dictionary) to the config file (json format).
    """
    config_path = get_config_path()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(data, f)


def find_possible_scripts(folder):
    if not os.path.isdir(folder):
        return []
    return [f for f in os.listdir(folder) if f.endswith('.py')]


def get_script_arguments(script_path):
    """
    Inspect a script's argparse.ArgumentParser.add_argument calls.

    Returns:
        (arguments, has_argparse)

    where:
        arguments   list of (raw_flag, clean_name, help_text, arg_type,
                    required, default_value) or empty if no
                    argparse.add_argument was found.

        has_argparse = True  if we detected at least one .add_argument call
                       False if no argparse usage was detected (or parse failed)
    """
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        print(f"Error reading {script_path}: {e}")
        return [], False

    try:
        tree = ast.parse(source, filename=script_path)
    except SyntaxError as e:
        print(f"Syntax error parsing {script_path}: {e}")
        return [], False

    arguments = []
    has_argparse = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute)
                and func.attr == "add_argument"):
            continue
        has_argparse = True

        flags = []
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                flags.append(arg.value)
        if not flags:
            continue
        raw_flag = flags[0]
        clean_name = raw_flag.lstrip("-")
        # ---- Keyword args ----
        kw_map = {}
        for kw in node.keywords:
            if kw.arg is None:
                continue
            kw_map[kw.arg] = kw.value
        help_text = ""
        if "help" in kw_map and isinstance(kw_map["help"], ast.Constant):
            if isinstance(kw_map["help"].value, str):
                help_text = kw_map["help"].value
        # type
        arg_type = str
        if "type" in kw_map:
            t_node = kw_map["type"]
            if isinstance(t_node, ast.Name):
                arg_type = TYPE_MAP.get(t_node.id, str)
            elif isinstance(t_node, ast.Attribute):
                # e.g. module.int -> ignore or map if you like
                arg_type = str
        # required
        required = False
        if "required" in kw_map:
            r_node = kw_map["required"]
            if isinstance(r_node, ast.Constant) \
                    and isinstance(r_node.value, bool):
                required = r_node.value
        # default
        default_value = None
        if "default" in kw_map:
            d_node = kw_map["default"]
            try:
                default_value = ast.literal_eval(d_node)
            except Exception:
                # Fallback: string repr for non-literal defaults
                default_value = None
        arguments.append((raw_flag, clean_name, help_text, arg_type,
                          required, default_value))
    return arguments, has_argparse


def get_scan_list(scan_input, target_type=float):
    result = []
    if len(scan_input) == 0:
        return None
    parts = [part.strip() for part in scan_input.split(',')]
    for part in parts:
        part = part.strip()
        try:
            val = ast.literal_eval(part)
            result.append(val)
        except (ValueError, SyntaxError):
            result.append(part)
    try:
        if target_type == int:
            return [int(float(x)) for x in result]
        else:
            return [target_type(x) for x in result]
    except Exception as e:
        print(f"Error converting scan list to {target_type}: {e}")
        return None


# ==============================================================================
#                          Editor Panel
# ==============================================================================


class EditorPanel(ttk.Frame):

    def __init__(self, parent, file_path, refresh_callback, close_callback):
        super().__init__(parent)
        self.file_path = file_path
        self.filename = os.path.basename(file_path)
        self.directory = os.path.dirname(file_path)
        self.refresh_callback = refresh_callback
        self.close_callback = close_callback
        # Toolbar
        toolbar = ttk.Frame(self, padding=2)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        self.btn_edit = ttk.Button(toolbar, text="Edit",
                                   command=self.enable_editing,
                                   style="Small.TButton")
        self.btn_edit.pack(side=tk.LEFT, padx=2)
        self.btn_save = ttk.Button(toolbar, text="Save (Ctrl+S)",
                                   command=self.save_file, state=tk.DISABLED,
                                   style="Small.TButton")
        self.btn_save.pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y,
                                                       padx=5)

        ttk.Label(toolbar, text="Name:",
                  font=(FONT_FAMILY, 8)).pack(side=tk.LEFT, padx=2)
        self.entry_new_name = ttk.Entry(toolbar,
                                        width=12, font=(FONT_FAMILY, 9))
        self.entry_new_name.pack(side=tk.LEFT, padx=2)

        self.btn_copy = ttk.Button(toolbar, text="Copy", command=self.copy_file,
                                   style="Small.TButton")
        self.btn_copy.pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y,
                                                       padx=5)

        self.btn_delete = ttk.Button(toolbar, text="Delete",
                                     command=self.delete_file,
                                     style="Small.TButton")
        self.btn_delete.pack(side=tk.LEFT, padx=2)
        # Close "X" Button
        self.btn_close = ttk.Button(toolbar, text="X", width=2,
                                    command=lambda: self.close_callback(self),
                                    style="Small.TButton")
        self.btn_close.pack(side=tk.RIGHT, padx=2)
        self.lbl_info = ttk.Label(toolbar, text=self.filename,
                                  foreground="blue",
                                  font=(FONT_FAMILY, 9, "bold"))
        self.lbl_info.pack(side=tk.RIGHT, padx=5)
        # Main Content
        content_frame = ttk.Frame(self)
        content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.vsb = ttk.Scrollbar(content_frame, orient="vertical")
        self.hsb = ttk.Scrollbar(content_frame, orient="horizontal")
        # Line Numbers
        self.line_numbers = tk.Text(content_frame, width=4, padx=4, takefocus=0,
                                    border=0, background=LINE_NUM_BG,
                                    foreground=LINE_NUM_FG, state='disabled',
                                    font=("Consolas", CODE_FONT_SIZE))
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)
        # Text Area
        self.text_area = tk.Text(content_frame, wrap="none",
                                 font=("Consolas", CODE_FONT_SIZE), undo=True,
                                 yscrollcommand=self.vsb.set,
                                 xscrollcommand=self.hsb.set)
        self.text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Configure Scrollbars
        self.vsb.config(command=self._on_vsb_scroll)
        self.hsb.config(command=self.text_area.xview)
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.hsb.pack(side=tk.BOTTOM, fill=tk.X)
        # Events
        self.text_area.bind("<Configure>", lambda e: self.after_idle(
            self._update_line_numbers))
        self.text_area.bind("<KeyPress>", lambda e: self.after_idle(
            self._update_line_numbers))
        self.text_area.bind("<Button-1>", lambda e: self.after_idle(
            self._update_line_numbers))
        self.text_area.bind("<MouseWheel>", lambda e: self.after_idle(
            self._update_line_numbers))
        self.text_area.bind("<Control-s>", self.save_file)
        self.text_area.bind("<Tab>", self._insert_spaces)
        self.text_area.bind("<Shift-Tab>", self._remove_indent)
        # Syntax Highlighting
        if ColorDelegator and Percolator:
            self.percolator = Percolator(self.text_area)
            self.color_delegator = ColorDelegator()
            self.percolator.insertfilter(self.color_delegator)

        self.load_content()

    def _on_vsb_scroll(self, *args):
        self.text_area.yview(*args)
        self.line_numbers.yview(*args)

    def _update_line_numbers(self, event=None):
        lines = int(self.text_area.index('end-1c').split('.')[0])
        line_content = "\n".join(str(i) for i in range(1, lines + 1))
        self.line_numbers.config(state='normal')
        self.line_numbers.delete('1.0', tk.END)
        self.line_numbers.insert('1.0', line_content)
        self.line_numbers.config(state='disabled')
        self.line_numbers.yview_moveto(self.text_area.yview()[0])

    def _insert_spaces(self, event):
        """Replace Tab key with 4 spaces"""
        self.text_area.insert("insert", " " * 4)
        return "break"

    def _remove_indent(self, event):
        """Handle Shift+Tab to remove 4 spaces"""
        line_start = self.text_area.index("insert linestart")
        line_end = self.text_area.index("insert lineend")
        line = self.text_area.get(line_start, line_end)

        if line.startswith(" " * 4):
            self.text_area.delete(line_start, f"{line_start}+4c")

        return "break"

    def load_content(self):
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete('1.0', tk.END)
        try:
            with open(self.file_path, 'r') as f:
                content = f.read().replace("\t", " " * 4)
            self.text_area.insert('1.0', content)
        except Exception as e:
            self.text_area.insert('1.0', f"# Error: {e}")

        self.after_idle(self._update_line_numbers)
        self.text_area.config(state=tk.DISABLED)
        self.reset_buttons()

    def reset_buttons(self):
        self.btn_edit.config(state=tk.NORMAL)
        self.btn_save.config(state=tk.DISABLED)
        self.btn_copy.config(state=tk.NORMAL)
        self.btn_delete.config(state=tk.NORMAL)

    def enable_editing(self):
        self.text_area.config(state=tk.NORMAL)
        self.btn_edit.config(state=tk.DISABLED)
        self.btn_save.config(state=tk.NORMAL)
        self.text_area.focus_set()

    def save_file(self, event=None):
        if str(self.btn_save['state']) == 'disabled':
            return
        content = self.text_area.get('1.0', 'end-1c')
        try:
            with open(self.file_path, 'w') as f:
                f.write(content)
            messagebox.showinfo("Success", "File saved.", parent=self)
            if self.refresh_callback:
                self.refresh_callback()
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def copy_file(self):
        new_name = self.entry_new_name.get().strip()
        if not new_name:
            base, ext = os.path.splitext(self.filename)
            c = 1
            while True:
                cand = f"{base}_copy_{c}{ext}"
                if not os.path.exists(os.path.join(self.directory, cand)):
                    new_name = cand
                    break
                c += 1
        else:
            if not new_name.endswith(".py"):
                new_name += ".py"
        new_path = os.path.join(self.directory, new_name)
        if os.path.exists(new_path):
            messagebox.showerror("Error", "File exists.", parent=self)
            return
        try:
            content = self.text_area.get('1.0', 'end-1c')
            with open(new_path, 'w') as f:
                f.write(content)
            if self.refresh_callback:
                self.refresh_callback()
            # Reload this pane
            self.file_path = new_path
            self.filename = new_name
            self.directory = os.path.dirname(new_path)
            self.lbl_info.config(text=self.filename)
            self.entry_new_name.delete(0, tk.END)
            messagebox.showinfo("Success", f"Copied to {new_name}", parent=self)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def delete_file(self):
        if messagebox.askyesno("Confirm", f"Delete '{self.filename}'?",
                               parent=self):
            try:
                os.remove(self.file_path)
                if self.refresh_callback:
                    self.refresh_callback()
                self.close_callback(self)
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=self)


class CodeEditorWindow(tk.Toplevel):
    def __init__(self, parent, refresh_callback):
        super().__init__(parent)
        self.refresh_callback = refresh_callback
        self.title("Script Editor")

        self.screen_width = self.winfo_screenwidth()
        self.screen_height = self.winfo_screenheight()
        width = int(self.screen_width * TEXT_WIN_RATIO)
        height = int(self.screen_height * TEXT_WIN_RATIO)
        x = (self.screen_width - width) // 2
        y = (self.screen_height - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)
        self.panes = []
        self.lift_window()

    def add_file(self, file_path):
        # Check existing
        for pane in self.panes:
            if pane.file_path == file_path:
                return
        # Split View Logic
        if len(self.panes) >= 2:
            old_pane = self.panes.pop()
            old_pane.destroy()
        new_pane = EditorPanel(self.paned, file_path, self.refresh_callback,
                               self.close_pane)
        self.paned.add(new_pane, weight=1)
        self.panes.append(new_pane)
        self.lift_window()

    def close_pane(self, pane_obj):
        if pane_obj in self.panes:
            self.panes.remove(pane_obj)
            pane_obj.destroy()

        if not self.panes:
            self.destroy()

    def lift_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()


class ToolTip:
    """For creating a tooltip for a widget"""

    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.tooltip = None
        self.delay = delay
        self._after_id = None
        self.widget.bind("<Enter>", self.schedule_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)
        self.widget.bind("<ButtonPress>", self.hide_tooltip)

    def schedule_tooltip(self, event):
        if self.tooltip:
            return
        if self._after_id:
            self.widget.after_cancel(self._after_id)
        self._after_id = self.widget.after(self.delay, self.show_tooltip)

    def show_tooltip(self):
        if not self._after_id:
            return
        self._after_id = None
        try:
            x, y, _, _ = self.widget.bbox("insert")
            if x is None:
                return
            x += self.widget.winfo_rootx() + 25
            y += self.widget.winfo_rooty() - 20
        except tk.TclError:
            return

        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        label = ttk.Label(self.tooltip, text=self.text, background="#FFFFE0",
                          relief="solid", borderwidth=1)
        label.pack()

    def hide_tooltip(self, event=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None


class ClusterRunnerRendering(tk.Tk):
    def __init__(self, initial_script_folder, cluster_output_folder):
        super().__init__()

        self.screen_width = self.winfo_screenwidth()
        self.screen_height = self.winfo_screenheight()

        try:
            icon = tk.PhotoImage(file="./ClusterRunner_icon.png")
            self.iconphoto(True, icon)
        except tk.TclError:
            pass

        # State Variables
        self.current_script = None
        self.script_inputs = {}
        self.show_all_scripts_var = tk.BooleanVar(value=False)

        self.abs_script_folder = tk.StringVar(
            value=os.path.abspath(initial_script_folder).replace("\\", "/"))

        self.cluster_base_path = tk.StringVar()
        if cluster_output_folder:
            self.cluster_base_path.set(
                os.path.abspath(cluster_output_folder).replace("\\", "/"))

        self.interpreter_path = tk.StringVar(value="")
        self.job_view_mode = tk.StringVar(value="my_jobs")

        self.setup_styles()
        self.setup_window()
        self.create_layout()

    def setup_styles(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use(TTK_THEME)
        except:
            pass

        default_font = tkFont.nametofont("TkDefaultFont")
        default_font.configure(family=FONT_FAMILY, size=FONT_SIZE,
                               weight=FONT_WEIGHT)
        self.option_add("*Font", default_font)

        self.style.configure("TButton", padding=1)
        self.style.configure("TEntry", padding=1)
        self.style.configure("TLabelframe.Label",
                             font=(FONT_FAMILY, FONT_SIZE, "normal"),
                             foreground="#333")
        self.style.configure("Treeview", rowheight=25,
                             font=(FONT_FAMILY, FONT_SIZE))
        self.style.configure("Treeview.Heading",
                             font=(FONT_FAMILY, FONT_SIZE))
        self.style.configure("Path.TLabel", foreground=PATH_COLOR,
                             font=(FONT_FAMILY, FONT_SIZE, "italic"))
        self.style.configure("Small.TButton", padding=3, font=(FONT_FAMILY, 10))
        self.style.configure("Action.TButton",
                             font=(FONT_FAMILY, FONT_SIZE), padding=3)
        self.style.configure("Header.TFrame", background="#e1e1e1",
                             relief="groove")

    def setup_window(self):
        self.title("Cluster Script Runner")
        width = int(self.screen_width * MAIN_WIN_RATIO)
        height = int(self.screen_height * MAIN_WIN_RATIO)
        # Center on primary screen
        x = (self.screen_width - width) // 2
        y = (self.screen_height - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=3)
        self.grid_rowconfigure(2, weight=4)
        self.grid_rowconfigure(3, weight=0)
        self.grid_columnconfigure(0, weight=1)

    def center_child_window(self, window, ratio=0.85):
        """Center child window relative to main window"""
        self.update_idletasks()
        pw = self.winfo_width()
        ph = self.winfo_height()
        px = self.winfo_rootx()
        py = self.winfo_rooty()
        w = int(pw * ratio)
        h = int(ph * ratio)
        x = px + (pw // 2) - (w // 2)
        y = py + (ph // 2) - (h // 2)
        if x < 0:
            x = 0
        if y < 0:
            y = 0
        window.geometry(f"{w}x{h}+{x}+{y}")

    def create_layout(self):
        self.create_selection_bar()

        mid_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        mid_pane.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        # Left side: script list
        left_frame = ttk.LabelFrame(mid_pane, text=" Available scripts",
                                    padding=0)
        mid_pane.add(left_frame, weight=1)

        self.script_list = tk.Listbox(left_frame, selectmode=tk.SINGLE, bd=0,
                                      highlightthickness=1, relief="solid",
                                      selectbackground=LISTBOX_SELECT_BG,
                                      selectforeground=LISTBOX_SELECT_FG,
                                      activestyle="none",
                                      font=(FONT_FAMILY, FONT_SIZE), width=30)
        self.script_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5,
                              pady=5)

        scrollbar = ttk.Scrollbar(left_frame, orient="vertical",
                                  command=self.script_list.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)
        self.script_list.config(yscrollcommand=scrollbar.set)

        # Right side: Controls
        right_frame = ttk.Frame(mid_pane)
        mid_pane.add(right_frame, weight=3)

        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(1, weight=1)
        # 1. Resources
        self.create_resource_frame(right_frame)
        # 2. Arguments
        self.create_args_frame(right_frame)
        self.args_wrapper.grid(row=1, column=0, sticky="nsew", padx=0,
                               pady=(0, 2))
        # Bottom: Monitor & Status
        self.create_job_monitor_panel()

        self.status_bar = ttk.Label(self,
                                    text="Please connect to the cluster.",
                                    relief=tk.SUNKEN, anchor="w",
                                    padding=(3, 3))
        self.status_bar.grid(row=3, column=0, sticky="ew", padx=5, pady=(0, 5))

    def create_selection_bar(self):
        frame = ttk.Frame(self, padding=0, relief="groove", borderwidth=1)
        frame.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 0))
        frame.grid_columnconfigure(1, weight=1)
        # Row 0: Script Folder
        ttk.Label(frame, text="Scripts folder:",
                  font=(FONT_FAMILY, FONT_SIZE)).grid(row=0, column=0,
                                                      padx=5, pady=(0, 5),
                                                      sticky="wens")
        ttk.Label(frame, textvariable=self.abs_script_folder,
                  style="Path.TLabel", anchor="w").grid(row=0, column=1,
                                                        sticky="ewns", padx=5)
        # Check button to list all scripts
        self.chk_show_all = ttk.Checkbutton(frame, text="Show all .py",
                                            variable=self.show_all_scripts_var)
        self.chk_show_all.grid(row=0, column=2, padx=5, pady=5)

        self.btn_browse_scripts = ttk.Button(frame, text="Browse",
                                             style="Small.TButton")
        self.btn_browse_scripts.grid(row=0, column=3, padx=(5, 0), pady=5)

        self.btn_refresh = ttk.Button(frame, text="Refresh list",
                                      style="Small.TButton")
        self.btn_refresh.grid(row=0, column=4, padx=0, pady=5)
        # Row 1: Output Base
        output_msg_folder_lbl = ttk.Label(frame, text="Output message folder:",
                                          font=(FONT_FAMILY, FONT_SIZE))
        output_msg_folder_lbl.grid(row=1, column=0, padx=5, pady=(0, 5),
                                   sticky="ewns")
        ToolTip(output_msg_folder_lbl,
                "Where to save output and error message from the cluster")
        ttk.Label(frame, textvariable=self.cluster_base_path,
                  style="Path.TLabel", anchor="w").grid(row=1, column=1,
                                                        sticky="ewns", padx=5)

        self.btn_browse_out = ttk.Button(frame, text="Browse",
                                         style="Small.TButton")
        self.btn_browse_out.grid(row=1, column=3, padx=(5, 0))

        self.btn_mkdir_out = ttk.Button(frame, text="New folder",
                                        style="Small.TButton")
        self.btn_mkdir_out.grid(row=1, column=4, padx=5)
        # Row 2: Python Env
        env_path_lbl = ttk.Label(frame, text="Python environment path:",
                                 font=(FONT_FAMILY, FONT_SIZE))
        env_path_lbl.grid(row=2, column=0, padx=5, pady=5, sticky="ewns")
        env_path_lbl_tooltip = ("Select python interpreter path: "
                                "1) Manual entry; 2) Select file; "
                                "3) Script Shebang; 4) Same as the current GUI")
        ToolTip(env_path_lbl, env_path_lbl_tooltip)

        ttk.Entry(frame, textvariable=self.interpreter_path,
                  width=80).grid(row=2, column=1, sticky="wns", padx=5, pady=5)

        self.btn_browse_env = ttk.Button(frame, text="Select file",
                                         style="Small.TButton")
        self.btn_browse_env.grid(row=2, column=3, padx=(5, 0))

        self.btn_check_env = ttk.Button(frame, text="Check",
                                        style="Small.TButton")
        self.btn_check_env.grid(row=2, column=4, padx=5)

    def create_resource_frame(self, parent):
        res_frame = ttk.LabelFrame(parent,
                                   text="Computing resources & connection",
                                   padding=5)
        res_frame.grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=0)
        res_frame.columnconfigure(0, weight=1)
        res_frame.columnconfigure(2, weight=1)
        res_frame.columnconfigure(4, weight=2)
        # Vertical Separators
        ttk.Separator(res_frame, orient=tk.VERTICAL).grid(row=0, column=1,
                                                          sticky="ns", padx=5)
        ttk.Separator(res_frame, orient=tk.VERTICAL).grid(row=0, column=3,
                                                          sticky="ns", padx=5)
        # Section 1: resources
        res_sub = ttk.Frame(res_frame, padding=0)
        res_sub.grid(row=0, column=0, sticky="nsew")
        res_sub.columnconfigure(1, weight=1)

        ttk.Label(res_sub, text="Device").grid(row=0, column=0, sticky="w",
                                               padx=5, pady=(0, 5))
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(res_sub, textvariable=self.device_var,
                                         values=["CPU", "GPU"],
                                         state="readonly", width=8)
        self.device_combo.grid(row=0, column=1, sticky="e", padx=5, pady=(0, 5))
        self.device_combo.current(1)

        ttk.Label(res_sub, text="Cores").grid(row=1, column=0, sticky="w",
                                              padx=5, pady=(0, 5))
        self.cpu_var = tk.StringVar()
        self.cpu_combo = ttk.Combobox(res_sub, textvariable=self.cpu_var,
                                      values=["8", "16", "32", "48"],
                                      state="readonly", width=8)
        self.cpu_combo.grid(row=1, column=1, sticky="e", padx=5, pady=(0, 5))
        self.cpu_combo.current(1)

        ttk.Label(res_sub, text="Memory").grid(row=2, column=0, sticky="w",
                                               padx=5, pady=(0, 5))
        self.memory_var = tk.StringVar()
        self.memory_combo = ttk.Combobox(res_sub, textvariable=self.memory_var,
                                         values=["16GB", "32GB", "64GB",
                                                 "128GB"],
                                         state="readonly", width=8)
        self.memory_combo.grid(row=2, column=1, sticky="e", padx=5, pady=(0, 0))
        self.memory_combo.current(1)

        # Section 2: maximum running time
        time_sub = ttk.Frame(res_frame, padding=0)
        time_sub.grid(row=0, column=2, sticky="nsew")
        time_sub.columnconfigure(1, weight=1)

        hours_lbl = ttk.Label(time_sub, text="Hours")
        ToolTip(hours_lbl, "Maximum job runtime. Jobs exceeding this limit "
                           "will be terminated.")
        hours_lbl.grid(row=0, column=0, sticky="w", padx=5, pady=(0, 5))
        self.hours_var = tk.StringVar()
        self.hours_combo = ttk.Combobox(time_sub, textvariable=self.hours_var,
                                        values=[str(i) for i in range(25)],
                                        width=8, state="readonly")
        self.hours_combo.grid(row=0, column=1, sticky="e", padx=5, pady=(0, 5))
        self.hours_combo.current(2)

        minutes_lbl = ttk.Label(time_sub, text="Minutes")
        ToolTip(minutes_lbl, "Maximum job runtime. Jobs exceeding this limit"
                             " will be terminated.")
        minutes_lbl.grid(row=1, column=0, sticky="w", padx=5, pady=(0, 5))
        self.minutes_var = tk.StringVar()
        self.minutes_combo = ttk.Combobox(time_sub,
                                          textvariable=self.minutes_var,
                                          values=[str(i) for i in range(61)],
                                          width=8, state="readonly")
        self.minutes_combo.grid(row=1, column=1, sticky="e", padx=5,
                                pady=(0, 5))
        self.minutes_combo.current(0)
        # Section 3: cluster connection
        conn_sub = ttk.Frame(res_frame, padding=0)
        conn_sub.grid(row=0, column=4, sticky="nsew")
        conn_sub.columnconfigure(1, weight=1)
        ttk.Label(conn_sub, text="Host").grid(row=0, column=0, sticky="w",
                                              padx=5, pady=(0, 5))
        self.host_var = tk.StringVar()
        ttk.Entry(conn_sub, textvariable=self.host_var).grid(row=0, column=1,
                                                             sticky="ew",
                                                             padx=5,
                                                             pady=(0, 5))

        ttk.Label(conn_sub, text="User").grid(row=1, column=0, sticky="w",
                                              padx=5, pady=(0, 5))
        self.username_var = tk.StringVar()
        ttk.Entry(conn_sub, textvariable=self.username_var).grid(row=1,
                                                                 column=1,
                                                                 sticky="ew",
                                                                 padx=5,
                                                                 pady=(0, 5))

        btn_status_sub = ttk.Frame(conn_sub)
        btn_status_sub.grid(row=2, column=0, columnspan=2, sticky="ew",
                            pady=(0, 0))
        btn_status_sub.columnconfigure(1, weight=1)

        self.login_button = ttk.Button(btn_status_sub, text="Connect", width=12)
        self.login_button.grid(row=0, column=0, sticky="wns", padx=5, pady=0)

        self.login_status_label = ttk.Label(btn_status_sub, text="Disconnected",
                                            foreground="red",
                                            font=(FONT_FAMILY, FONT_SIZE,
                                                  "bold"))
        self.login_status_label.grid(row=0, column=1, sticky="e", padx=5,
                                     pady=0)

    def create_args_frame(self, parent):
        self.args_wrapper = ttk.LabelFrame(parent, text="Script arguments",
                                           padding=5)
        self.args_wrapper.grid(row=2, column=0, sticky="nsew", padx=(0, 5),
                               pady=5)
        self.args_wrapper.columnconfigure(0, weight=1)
        self.args_wrapper.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(self.args_wrapper, highlightthickness=0,
                                background=self.style.lookup("TFrame",
                                                             "background"))
        self.scrollbar_args = ttk.Scrollbar(self.args_wrapper,
                                            orient="vertical",
                                            command=self.canvas.yview)
        self.args_frame = ttk.Frame(self.canvas)
        self.args_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))

        self.canvas_window = self.canvas.create_window((0, 0),
                                                       window=self.args_frame,
                                                       anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar_args.set)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=5, pady=1)
        self.scrollbar_args.grid(row=0, column=1, sticky="ns", pady=0)

        self._setup_canvas_scroll(self.canvas)
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self.canvas_window,
                                                          width=e.width))

    def create_job_monitor_panel(self):
        monitor_frame = ttk.LabelFrame(self, text="Job Monitor")
        monitor_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=(0, 5))

        toolbar = ttk.Frame(monitor_frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(5, 0))
        # Configure columns for uniform button widths
        for i in range(6):
            toolbar.columnconfigure(i, weight=1, uniform="monitor_btns")
        # Radio Buttons for Job Status
        self.rb_my_jobs = ttk.Radiobutton(toolbar, text="My jobs status",
                                          variable=self.job_view_mode,
                                          value="my_jobs")
        self.rb_my_jobs.grid(row=0, column=0, padx=(0, 2), sticky="ew")

        self.rb_cluster = ttk.Radiobutton(toolbar, text="Cluster status",
                                          variable=self.job_view_mode,
                                          value="cluster")
        self.rb_cluster.grid(row=0, column=1, padx=2, sticky="ew")

        self.btn_cancel_sel = ttk.Button(toolbar, text="Cancel selected jobs")
        self.btn_cancel_sel.grid(row=0, column=2, padx=2, sticky="ew")

        self.btn_cancel_all = ttk.Button(toolbar, text="Cancel all Jobs")
        self.btn_cancel_all.grid(row=0, column=3, padx=2, sticky="ew")

        self.btn_view_msg = ttk.Button(toolbar, text="View cluster message")
        self.btn_view_msg.grid(row=0, column=4, padx=2, sticky="ew")

        self.btn_view_log = ttk.Button(toolbar, text="View log")
        self.btn_view_log.grid(row=0, column=5, padx=(2, 15), sticky="ew")

        columns = ("index", "job_id", "user", "status", "time", "nodelist")
        self.job_tree = ttk.Treeview(monitor_frame, columns=columns,
                                     show="headings", height=15)
        self.job_tree.heading("index", text="Index")
        self.job_tree.heading("job_id", text="Job ID")
        self.job_tree.heading("user", text="User")
        self.job_tree.heading("status", text="Status")
        self.job_tree.heading("time", text="Time")
        self.job_tree.heading("nodelist", text="Node List")

        self.job_tree.column("index", width=30, anchor="center")
        self.job_tree.column("job_id", width=100, anchor="center")
        self.job_tree.column("user", width=100, anchor="center")
        self.job_tree.column("status", width=100, anchor="center")
        self.job_tree.column("time", width=100, anchor="center")
        self.job_tree.column("nodelist", width=200, anchor="w")

        sb = ttk.Scrollbar(monitor_frame, orient="vertical",
                           command=self.job_tree.yview)
        self.job_tree.configure(yscroll=sb.set)
        self.job_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5,
                           pady=5)
        sb.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

    def _setup_canvas_scroll(self, canvas):
        def _on_mousewheel(event):
            if self.tk.call('tk', 'windowingsystem') == 'win32':
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif self.tk.call('tk', 'windowingsystem') == 'x11':
                if event.num == 4:
                    canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * event.delta), "units")

        def _bind_to_mousewheel(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_mousewheel)
            canvas.bind_all("<Button-5>", _on_mousewheel)

        def _unbind_from_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind('<Enter>', _bind_to_mousewheel)
        canvas.bind('<Leave>', _unbind_from_mousewheel)


class ClusterRunnerInteractions(ClusterRunnerRendering):
    def __init__(self, initial_script_folder, cluster_output_folder):
        super().__init__(initial_script_folder, cluster_output_folder)

        # State Variables
        self.cluster_host = "slurm.server.address"
        self.ssh_client = None
        self.ssh_transport = None
        self.sftp_client = None
        self.on_cluster = False
        self.username = ""
        self.auth_cancelled = False
        self._sock = None

        self.list_jobid = []
        self.cluster_output_msg = []
        self.cluster_error_msg = []
        self.entries = {}
        self.shutdown_flag = False
        self.refresh_loop_active = False
        self.refreshing_status = False

        self.editor_window = None

        self.host_var.set(self.cluster_host)
        self.username_var.set(self.username)

        if not cluster_output_folder:
            self.update_cluster_output_default()

        # Connect UI elements to actions
        self.btn_browse_scripts.config(command=self.browse_script_folder)
        self.btn_refresh.config(command=self.populate_script_list)
        self.chk_show_all.config(command=self.populate_script_list)
        self.btn_browse_out.config(command=self.browse_output_folder)
        self.btn_mkdir_out.config(command=self.create_output_directory)
        self.btn_browse_env.config(command=self.browse_interpreter)
        self.btn_check_env.config(command=self.check_interpreter)
        self.login_button.config(command=self.ssh_login)

        self.rb_my_jobs.config(command=self.get_user_jobs_status)
        self.rb_cluster.config(command=self.get_cluster_status)
        self.btn_cancel_sel.config(command=self.cancel_job)
        self.btn_cancel_all.config(command=self.cancel_all_jobs)
        self.btn_view_msg.config(command=self.show_output_window)
        self.btn_view_log.config(command=self.view_log_file)

        self.script_list.bind("<<ListboxSelect>>", self.on_script_select)
        self.script_list.bind("<Double-Button-1>", self.on_script_double_click)
        self.job_tree.bind("<<TreeviewSelect>>", self.on_job_select)

        self.populate_script_list()

        self.protocol("WM_DELETE_WINDOW", self.on_exit)
        signal.signal(signal.SIGINT, self.on_exit_signal)
        self.check_for_exit_signal()

    def update_cluster_output_default(self):
        """
        Updates the default cluster output folder based on the script folder.
        """
        current_base = self.abs_script_folder.get().strip()
        if not current_base or current_base == ".":
            new_path = "./cluster_msg/"
        else:
            new_path = os.path.join(current_base, "cluster_msg")
        new_path = os.path.normpath(new_path).replace("\\", "/")
        self.cluster_base_path.set(new_path)

    def on_job_select(self, event):
        # Clear script list selection when a job is selected
        self.script_list.selection_clear(0, tk.END)

    def _update_ui_safely(self, func, *args, **kwargs):
        if self.winfo_exists():
            self.after(0, lambda: func(*args, **kwargs))

    def _blocking_dialog_wrapper(self, dialog_func, *args, **kwargs):
        q = queue.Queue()

        def run_dialog():
            if not self.winfo_exists():
                q.put(None)
                return
            try:
                result = dialog_func(*args, parent=self, **kwargs)
                q.put(result)
            except Exception as e:
                q.put(e)

        self.after(0, run_dialog)
        result = q.get()
        if isinstance(result, Exception):
            if self.shutdown_flag or not self.winfo_exists():
                return None
            logging.error("Dialog execution failed: %s", result)
            return None
        return result

    def update_status_bar(self, message=""):
        if self.winfo_exists():
            self.after(0, lambda: self.status_bar.config(text=message))

    def log_to_csv(self, col2, col3, col4="", base_dir_override=None):
        """
        Logs actions to a CSV file.
        Format: [Date Time, Script/Action, JobID/List, Parameters]
        Filename: cluster_runner_log_YYYY-MM-DD.csv
        """
        base_dir = base_dir_override if base_dir_override \
            else self.cluster_base_path.get()
        if not os.path.exists(base_dir):
            return

        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"cluster_runner_log_{date_str}.csv"
        filepath = os.path.join(base_dir, filename)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(filepath, mode='a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, col2, str(col3), str(col4)])
        except Exception as e:
            print(f"Log Error: {e}")

    def view_log_file(self):
        """Opens a toplevel window to view today's log file."""
        base_dir = self.cluster_base_path.get()
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"cluster_runner_log_{date_str}.csv"
        filepath = os.path.join(base_dir, filename)

        if not os.path.exists(filepath):
            messagebox.showinfo("Info",
                                f"No log file found for today ({filename}).")
            return

        top = tk.Toplevel(self)
        top.title(f"Log Viewer: {filename}")
        self.center_child_window(top, ratio=0.85)

        main_pane = ttk.PanedWindow(top, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        table_frame = ttk.Frame(main_pane)
        main_pane.add(table_frame, weight=3)

        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        tree = ttk.Treeview(table_frame,
                            columns=("time", "action", "details", "params"),
                            show="headings")
        tree.heading("time", text="Time")
        tree.heading("action", text="Action")
        tree.heading("details", text="Details (Job IDs)")
        tree.heading("params", text="Parameters")

        tree.column("time", width=150, stretch=tk.NO, anchor="w")
        tree.column("action", width=180, stretch=tk.NO, anchor="w")
        tree.column("details", width=250, stretch=tk.NO, anchor="w")
        tree.column("params", width=1200, stretch=tk.YES, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL,
                            command=tree.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        # Lower frame for detailed view
        detail_frame = ttk.Frame(main_pane)
        main_pane.add(detail_frame, weight=1)

        ttk.Label(detail_frame, text="Selected Entry Details:",
                  font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")
        detail_txt_frame = ttk.Frame(detail_frame)
        detail_txt_frame.pack(fill=tk.BOTH, expand=True)
        detail_txt_frame.grid_columnconfigure(0, weight=1)
        detail_txt_frame.grid_rowconfigure(0, weight=1)

        detail_text = tk.Text(detail_txt_frame, height=6, bd=1, relief="solid",
                              background=BG_COLOR_OUTPUT,
                              font=("Consolas", CONSOLE_FONT), wrap="word")
        detail_text.grid(row=0, column=0, sticky="nsew")
        d_vsb = ttk.Scrollbar(detail_txt_frame, orient=tk.VERTICAL,
                              command=detail_text.yview)
        d_vsb.grid(row=0, column=1, sticky="ns")
        detail_text.configure(yscrollcommand=d_vsb.set)

        def on_tree_select(event):
            selected = tree.selection()
            if not selected:
                return
            item = tree.item(selected[0])
            values = item['values']
            detail_text.delete("1.0", tk.END)
            if values:
                content = (f"Time: {values[0]}\n"
                           f"Action: {values[1]}\n"
                           f"Details: {values[2]}\n"
                           f"Parameters: {values[3]}")
                detail_text.insert(tk.END, content)

        tree.bind("<<TreeviewSelect>>", on_tree_select)
        try:
            with open(filepath, 'r', newline='') as f:
                reader = csv.reader(f)
                for row in reader:
                    while len(row) < 4:
                        row.append("")
                    tree.insert("", tk.END, values=row)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read log: {e}")

    def browse_script_folder(self):
        folder = filedialog.askdirectory(
            initialdir=self.abs_script_folder.get())
        if folder:
            self.abs_script_folder.set(folder)
            self.populate_script_list()
            self.update_cluster_output_default()
            save_config({"last_folder": folder})

    def browse_output_folder(self):
        current = self.cluster_base_path.get()
        initial = current if os.path.exists(
            current) else self.abs_script_folder.get()
        folder = filedialog.askdirectory(initialdir=initial)
        if folder:
            self.cluster_base_path.set(folder)

    def create_output_directory(self):
        """Creates a new folder inside the current output base."""
        current_base = self.cluster_base_path.get()
        if not os.path.exists(current_base):
            if messagebox.askyesno("Create Base?",
                                   f"The current output base does not exist:\n"
                                   f"{current_base}\n\nCreate it now?"):
                try:
                    os.makedirs(current_base, exist_ok=True)
                except Exception as e:
                    messagebox.showerror("Error",
                                         f"Failed to create folder: {e}")
                    return
            else:
                return
        new_folder_name = simpledialog.askstring("New Folder",
                                                 "Enter new folder name:",
                                                 parent=self)
        if new_folder_name:
            new_path = os.path.join(current_base, new_folder_name.strip())
            try:
                os.makedirs(new_path, exist_ok=True)
                self.cluster_base_path.set(new_path)
                messagebox.showinfo("Success",
                                    f"Created and selected:\n{new_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create folder: {e}")

    def browse_interpreter(self):
        filename = filedialog.askopenfilename(title="Select Python Interpreter",
                                              initialdir="/",
                                              filetypes=[("Executables", "*"),
                                                         ("All Files", "*.*")])
        if filename:
            self.interpreter_path.set(filename)

    def resolve_interpreter(self, script_full_path):
        manual_path = self.interpreter_path.get().strip()
        if manual_path:
            if os.path.exists(manual_path) and os.path.isfile(manual_path):
                return manual_path, "Manual Entry"
        if script_full_path is not None:
            try:
                with open(script_full_path, 'r') as f:
                    first_line = f.readline().strip()
                    if first_line.startswith("#!"):
                        potential = first_line[2:].strip()
                        return potential, "Script Shebang (#!)"
            except:
                pass
        return sys.executable, "System Default"

    def check_interpreter(self):
        current_sel = self.script_list.curselection()
        if not current_sel:
            script_path = None
        else:
            script_name = self.script_list.get(current_sel[0])
            script_path = os.path.join(self.abs_script_folder.get(),
                                       script_name)

        interp, source = self.resolve_interpreter(script_path)
        messagebox.showinfo("Interpreter Check",
                            f"Source: {source}\nPath: {interp}")

    def populate_script_list(self):
        self.script_list.delete(0, tk.END)
        folder = self.abs_script_folder.get()
        scripts = find_possible_scripts(folder)
        for script in scripts:
            script_path = os.path.join(folder, script)
            if self.show_all_scripts_var.get():
                self.script_list.insert(tk.END, script)
            else:
                arguments, _ = get_script_arguments(script_path)
                if arguments:
                    self.script_list.insert(tk.END, script)

    def on_script_select(self, event):
        try:
            selected_index = self.script_list.curselection()
            if not selected_index:
                return
            # Clear job monitor selection when a script is selected
            self.job_tree.selection_remove(self.job_tree.selection())
            selected_script = self.script_list.get(selected_index)
            if self.current_script is not None:
                self.save_current_inputs()
            self.display_arguments(selected_script)
            self.current_script = selected_script
            self.update_status_bar(f"Selected script: {self.current_script}")
        except Exception as e:
            print(f"Error selecting script: {e}")

    def on_script_double_click(self, event):
        selection = self.script_list.curselection()
        if not selection:
            return
        script_name = self.script_list.get(selection[0])
        full_path = os.path.join(self.abs_script_folder.get(), script_name)

        if self.editor_window and self.editor_window.winfo_exists():
            self.editor_window.add_file(full_path)
        else:
            self.editor_window = CodeEditorWindow(self,
                                                  self.populate_script_list)
            self.editor_window.add_file(full_path)

    def save_current_inputs(self):
        script = self.current_script
        if not script:
            return
        current_data = {}
        for flag, widgets in self.entries.items():
            current_data[flag] = {
                "value": widgets["entry"].get(),
                "is_list": widgets["is_list"].get()}
        self.script_inputs[script] = current_data

    def display_arguments(self, script):
        for widget in self.args_frame.winfo_children():
            widget.destroy()

        script_path = os.path.join(self.abs_script_folder.get(), script)
        arguments, _ = get_script_arguments(script_path)
        self.entries = {}

        # Configure columns: 0=Flag, 1=Entry, 2=Type, 3=List?, 4=Help
        self.args_frame.columnconfigure(1, weight=0)
        self.args_frame.columnconfigure(4, weight=1)

        row = 0
        ttk.Label(self.args_frame, text=f"{script}",
                  font=(FONT_FAMILY, FONT_SIZE + 1),
                  foreground=PATH_COLOR).grid(row=row, column=0, columnspan=5,
                                              sticky="w", pady=(0, 5))
        row += 1
        if not arguments:
            ttk.Label(self.args_frame,
                      text="No arguments found or not an argparse script.",
                      font=(FONT_FAMILY, 10)).grid(row=row, column=0,
                                                   columnspan=5,
                                                   sticky="w", padx=5)
            row += 1
        for flag, dest, help_text, arg_type, required, default_value \
                in arguments:
            # 1. Flag Label
            ttk.Label(self.args_frame, text=flag, width=15, anchor="w",
                      font=(FONT_FAMILY, FONT_SIZE)).grid(row=row, column=0,
                                                          sticky="nw", pady=5)
            # 2. Entry
            arg_entry = ttk.Entry(self.args_frame, width=15)
            arg_entry.grid(row=row, column=1, sticky="nw", pady=5, padx=5)
            # 3. Type Label
            type_lbl = ttk.Label(self.args_frame, text=f"[{arg_type.__name__}]",
                                 foreground="gray", width=8)
            type_lbl.grid(row=row, column=2, sticky="nw", pady=5)
            # 4. List Checkbox
            is_list_var = tk.BooleanVar(value=False)
            chk = ttk.Checkbutton(self.args_frame, text="List?",
                                  variable=is_list_var)
            ToolTip(chk, "Allow the input flag to accept a list of values for "
                         "submitting multiple jobs.")
            chk.grid(row=row, column=3, sticky="nw", pady=5, padx=5)
            # 5. Help Label
            help_lbl = ttk.Label(self.args_frame, text=help_text,
                                 justify="left",
                                 foreground="#555", wraplength=450)
            help_lbl.grid(row=row, column=4, sticky="nw", pady=5, padx=5)

            # Restore saved values
            saved_data = self.script_inputs.get(script, {}).get(flag)

            if isinstance(saved_data, dict):
                val_to_insert = saved_data.get('value', '')
                is_list_var.set(saved_data.get('is_list', False))
            elif saved_data is not None:
                val_to_insert = str(saved_data)
            elif default_value is not None:
                val_to_insert = str(default_value)
            else:
                val_to_insert = ""

            arg_entry.insert(0, val_to_insert)
            # Save reference to all widgets/vars
            self.entries[flag] = {
                "entry": arg_entry,
                "type": arg_type,
                "is_list": is_list_var}
            row += 1

        btn_frame = ttk.Frame(self.args_frame)
        btn_frame.grid(row=row, column=0, columnspan=5, pady=10, sticky="ew")
        ttk.Button(btn_frame, text="Submit jobs",
                   command=lambda: self.submit_job(script),
                   style="Action.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Label(btn_frame, text="Pause time between jobs").pack(side=tk.LEFT,
                                                                  padx=(15, 2))
        self.pause_time_var = tk.StringVar(value="0.0")
        pause_entry = ttk.Entry(btn_frame, textvariable=self.pause_time_var,
                                width=5)
        pause_entry.pack(side=tk.LEFT, padx=2)
        ttk.Label(btn_frame, text="second").pack(side=tk.LEFT, padx=2)
        ToolTip(pause_entry, "Delay in seconds between individual job "
                             "submissions in a batch. Useful if scripts may "
                             "write to the same location.")

    def _duo_option_dialog(self, message, title="Duo Authentication Required",
                           parent=None):
        if parent is None:
            parent = self
        top = tk.Toplevel(parent)
        top.title(title)
        top.transient(parent)
        top.grab_set()

        frm = ttk.Frame(top, padding=15)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=message, justify="left",
                  wraplength=500).grid(row=0, column=0, columnspan=2,
                                       sticky="w", pady=(0, 10))
        ttk.Label(frm, text="Option / Passcode:").grid(row=1, column=0,
                                                       sticky="e")
        entry_var = tk.StringVar()
        entry = ttk.Entry(frm, textvariable=entry_var, width=25)
        entry.grid(row=1, column=1, sticky="w")
        entry.focus_set()

        result = {"value": None}

        def on_ok(e=None):
            result["value"] = entry_var.get().strip()
            top.destroy()

        def on_cancel(e=None):
            result["value"] = None
            top.destroy()

        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=(15, 0), sticky="e")
        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side="left",
                                                             padx=(0, 5))
        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(
            side="left")

        top.bind("<Return>", on_ok)
        top.bind("<Escape>", on_cancel)

        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 200
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 100
        top.geometry(f"+{x}+{y}")
        parent.wait_window(top)
        return result["value"]

    def _keyboard_interactive_handler(self, title, instructions, prompts):
        responses = []
        title_lower = (title or "").lower()
        instr_lower = (instructions or "").lower()

        for prompt, echo in prompts:
            prompt_lower = (prompt or "").lower()
            if ("duo" in title_lower or "duo" in instr_lower or
                    "select which options" in instr_lower or
                    "passcode" in prompt_lower):
                self._update_ui_safely(self.update_status_bar,
                                       "Duo request received...")
                user_display = self.username_var.get() or self.username
                host_display = self.host_var.get()
                msg = (f"Authentication options for {user_display} on "
                       f"{host_display}:\nServer message:\n"
                       f"{instructions or ''}\nPrompt:\n{prompt or ''}")
                answer = self._blocking_dialog_wrapper(
                    self._duo_option_dialog, msg, title="Duo Authentication")
                if answer is None:
                    self.auth_cancelled = True
                    remaining = len(prompts) - len(responses)
                    responses.extend([""] * remaining)
                    return responses
                responses.append(answer.strip())
                continue

            answer = self._blocking_dialog_wrapper(simpledialog.askstring,
                                                   "Login Prompt",
                                                   prompt or "Auth prompt:",
                                                   show=None if echo else "*")
            if answer is None:
                self.auth_cancelled = True
                remaining = len(prompts) - len(responses)
                responses.extend([""] * remaining)
                return responses
            responses.append(answer)
        return responses

    def ssh_login(self):
        if self.on_cluster:
            self.ssh_disconnect()
            return
        username = self.username_var.get().strip()
        hostname = self.host_var.get().strip()
        if not username:
            messagebox.showerror("Error", "Please enter a username.")
            return
        if not hostname:
            messagebox.showerror("Error", "Please enter a hostname.")
            return

        self.login_button.config(state=tk.DISABLED, text="Connecting...")
        self.login_status_label.config(text="Connecting...", foreground="blue")
        threading.Thread(target=self._ssh_login_threaded,
                         args=(username, hostname), daemon=True).start()

    def _ssh_login_threaded(self, username, hostname):
        self.on_cluster = False
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            self._update_ui_safely(self.update_status_bar,
                                   f"Connecting to {hostname}...")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30.0)
            sock.connect((hostname, 22))
            self._sock = sock
            self.auth_cancelled = False
            self.cluster_host = hostname

            self._update_ui_safely(self.update_status_bar,
                                   "Starting SSH transport...")
            self.ssh_transport = paramiko.Transport(self._sock)
            self.ssh_transport.start_client()

            self._update_ui_safely(self.update_status_bar, "Authenticating...")
            self.ssh_transport.auth_interactive(
                username, self._keyboard_interactive_handler)

            if not self.ssh_transport.is_authenticated():
                raise paramiko.AuthenticationException("Authentication failed.")

            self.ssh_client._transport = self.ssh_transport

            if not self.ssh_transport.is_active():
                raise paramiko.SSHException("Connection closed immediately.")

            channel = self.ssh_client.get_transport().open_session()
            channel.exec_command("whoami")
            remote_user = channel.makefile('r').read().decode().strip()
            channel.close()

            self._update_ui_safely(self.update_status_bar,
                                   f"Connected as {remote_user} on {hostname}")
            self._update_ui_safely(self.login_button.config, state=tk.NORMAL,
                                   text="Disconnect")
            self._update_ui_safely(self.login_status_label.config,
                                   text="Connected", foreground="green")
            self.on_cluster = True
            self.username = username

        except Exception as e:
            if self.auth_cancelled:
                self._update_ui_safely(self.ssh_disconnect)
                return
            self._update_ui_safely(self._handle_login_failure,
                                   "Connection Error", str(e))

    def _handle_login_failure(self, title, msg):
        self.ssh_disconnect()
        if self.winfo_exists():
            self.login_button.config(state=tk.NORMAL, text="Connect SSH")
            self.login_status_label.config(text="Failed", foreground="red")
            messagebox.showerror(title, msg)

    def ssh_disconnect(self):
        # Clear table
        for item in self.job_tree.get_children():
            self.job_tree.delete(item)
        # Reset internal state
        self.list_jobid = []
        self.cluster_output_msg = []
        self.cluster_error_msg = []

        if self.ssh_client:
            self.ssh_client.close()
        if self.ssh_transport:
            self.ssh_transport.close()
        if self._sock:
            self._sock.close()
        self.on_cluster = False
        if self.winfo_exists():
            self.login_button.config(text="Connect SSH", command=self.ssh_login,
                                     state=tk.NORMAL)
            self.login_status_label.config(text="Disconnected",
                                           foreground="red")
            self.update_status_bar("Disconnected.")

    def get_slurm_batch_script(self, output_folder, interpreter_path,
                               full_script_args):
        device = self.device_combo.get()
        num_cpu = self.cpu_combo.get()
        memory = self.memory_combo.get()
        hour = self.hours_combo.get()
        minute = self.minutes_combo.get()
        command_to_run = f"{interpreter_path} -u {full_script_args}"

        header = f"""#!/bin/bash
#SBATCH --job-name=tomo_recon
#SBATCH --ntasks 1
#SBATCH --output={output_folder}/output_%j.out
#SBATCH --cpus-per-task {num_cpu}
#SBATCH --nodes=1
#SBATCH --mem={memory}
#SBATCH --qos=long
#SBATCH --time={hour}:{minute}:00
"""
        if device == "GPU":
            header += "#SBATCH --gres=gpu:1\n"

        script = header + (f"\nsrun -o {output_folder}/output_%j.out "
                           f"-e {output_folder}/error_%j.err "
                           f"{command_to_run}\n")
        return textwrap.dedent(script)

    def __submit_job(self, sbatch_script):
        if not self.on_cluster:
            return ""
        try:
            transport = self.ssh_client._transport
            channel = transport.open_session()
            channel.exec_command('sbatch')
            channel.sendall(sbatch_script.encode('utf-8'))
            channel.shutdown_write()

            stdout_data, stderr_data = b"", b""
            while not channel.exit_status_ready():
                if channel.recv_ready():
                    stdout_data += channel.recv(4096)
                if channel.recv_stderr_ready():
                    stderr_data += channel.recv_stderr(4096)
                time.sleep(0.05)
            while channel.recv_ready():
                stdout_data += channel.recv(4096)
            while channel.recv_stderr_ready():
                stderr_data += channel.recv_stderr(4096)

            channel.close()
            return stdout_data.decode("utf-8").strip()
        except Exception as e:
            self._update_ui_safely(messagebox.showerror, "Error",
                                   f"Submission failed: {e}")
            return ""

    def submit_job(self, script):
        if not self.on_cluster:
            messagebox.showinfo("Connection Required",
                                "Please connect to the cluster first.")
            return

        script_path = os.path.join(self.abs_script_folder.get(), script)
        interpreter, _ = self.resolve_interpreter(script_path)

        scalar_args = {}
        iterable_args = {}
        ordered_flags = list(self.entries.keys())

        for flag in ordered_flags:
            data = self.entries[flag]
            raw_val = data["entry"].get().strip()
            arg_type = data["type"]
            is_list = data["is_list"].get()

            if not raw_val:
                continue

            if is_list:
                parsed_list = get_scan_list(raw_val, target_type=arg_type)
                if parsed_list is None:
                    messagebox.showerror("Error", f"Invalid list format for "
                                                  f"flag -{flag}")
                    return
                iterable_args[flag] = parsed_list
            else:
                try:
                    val = arg_type(raw_val)
                    if arg_type == str:
                        val = shlex.quote(raw_val)
                    else:
                        val = str(val)
                    scalar_args[flag] = val
                except ValueError:
                    messagebox.showerror("Error",
                                         f"Invalid value for -{flag} "
                                         f"(Expected {arg_type.__name__})")
                    return

        num_jobs = 1
        if iterable_args:
            lengths = {f: len(v) for f, v in iterable_args.items()}
            unique_lengths = set(lengths.values())
            if len(unique_lengths) > 1:
                msg = ("List arguments must have equal lengths!\n\n"
                       "Detected lengths:\n")
                for f, l in lengths.items():
                    msg += f" -{f}: {l}\n"
                messagebox.showerror("Error", msg)
                return
            num_jobs = list(unique_lengths)[0]

        if num_jobs == 0:
            messagebox.showerror("Error", "Resulting job list is empty.")
            return

        if num_jobs > 100:
            if not messagebox.askyesno("Confirm",
                                       f"This will submit {num_jobs} jobs. "
                                       f"Continue?"):
                return

        base = self.cluster_base_path.get()
        msg_folder = script.replace(".py", "")
        cluster_output_folder = f"{base}/{msg_folder}".replace("\\", "/")

        try:
            pause_time = float(self.pause_time_var.get())
        except ValueError:
            pause_time = 0.0

        device = self.device_combo.get()
        num_cpu = self.cpu_combo.get()
        memory = self.memory_combo.get()
        hour = self.hours_var.get()
        minute = self.minutes_var.get()
        cluster_base = self.cluster_base_path.get()

        def _worker():
            list_jobid = []
            self.make_folder(cluster_output_folder)

            for i in range(num_jobs):
                if self.shutdown_flag:
                    break

                if i > 0 and pause_time > 0:
                    self.update_status_bar(
                        f"Pausing for {pause_time}s before submitting job "
                        f"{i + 1}/{num_jobs}...")
                    time.sleep(pause_time)
                else:
                    self.update_status_bar(
                        f"Submitting job {i + 1}/{num_jobs}...")

                command_parts = [script_path]
                for flag, val in scalar_args.items():
                    command_parts.append(flag)
                    command_parts.append(str(val))
                for flag, vals in iterable_args.items():
                    val = vals[i]
                    command_parts.append(flag)
                    command_parts.append(str(val))

                if iterable_args:
                    primary_flag = list(iterable_args.keys())[0]
                    primary_val = iterable_args[primary_flag][i]
                    if isinstance(primary_val,
                                  float) and primary_val.is_integer():
                        primary_val = int(primary_val)
                    job_suffix = f"{primary_val}"
                else:
                    job_suffix = f"{i:03}"

                scan_out_dir = f"{cluster_output_folder}/job_{job_suffix}"
                self.make_folder(scan_out_dir)

                full_args = ' '.join(command_parts)
                command_to_run = f"{interpreter} -u {full_args}"
                header = f"""#!/bin/bash
#SBATCH --job-name=tomo_recon
#SBATCH --ntasks 1
#SBATCH --output={scan_out_dir}/output_%j.out
#SBATCH --cpus-per-task {num_cpu}
#SBATCH --nodes=1
#SBATCH --mem={memory}
#SBATCH --qos=long
#SBATCH --time={hour}:{minute}:00
"""
                if device == "GPU":
                    header += "#SBATCH --gres=gpu:1\n"
                sbatch = textwrap.dedent(
                    header + f"\nsrun -o {scan_out_dir}/output_%j.out "
                             f"-e {scan_out_dir}/error_%j.err "
                             f"{command_to_run}\n")

                try:
                    output = self.__submit_job(sbatch)
                    job_id = None
                    for line in output.splitlines():
                        if "Submitted batch job" in line:
                            job_id = line.split()[-1]
                            list_jobid.append(job_id)
                            break
                    if job_id:
                        self.update_status_bar(
                            f"Submitted {i + 1}/{num_jobs}: Job {job_id}")
                    else:
                        print(f"Failed to submit index {i}")
                except Exception as e:
                    print(f"Error submitting index {i}: {e}")

            if list_jobid:
                self._update_ui_safely(messagebox.showinfo, "Success",
                                       f"Submitted {len(list_jobid)} jobs.")
                log_params = scalar_args.copy()
                for flag, vals in iterable_args.items():
                    log_params[f"-{flag} (List)"] = str(vals)

                self.log_to_csv(script, list_jobid, str(log_params),
                                base_dir_override=cluster_base)
                self._update_ui_safely(self.start_refresh_loop)
            else:
                self._update_ui_safely(messagebox.showerror, "Error",
                                       "No jobs submitted.")

        threading.Thread(target=_worker, daemon=True).start()

    def execute_remote_command(self, command):
        if not self.on_cluster:
            raise ConnectionError("Not connected.")
        stdin, stdout, stderr = self.ssh_client.exec_command(command)
        return stdout.read().decode('utf-8').strip(), stderr.read().decode(
            'utf-8').strip()

    def cancel_job(self):
        if not self.on_cluster:
            messagebox.showinfo("Connection Required",
                                "Please connect to the cluster first.")
            return

        if not self.job_tree.get_children():
            messagebox.showinfo("Info", "No jobs running.")
            return

        selected_items = self.job_tree.selection()
        if not selected_items:
            messagebox.showinfo("Info",
                                "Please select one or more jobs to cancel.")
            return

        cancelled_ids = []
        for item in selected_items:
            vals = self.job_tree.item(item, 'values')
            if not vals:
                continue

            job_id = str(vals[1])
            user = str(vals[2])

            if user != self.username:
                print(
                    f"Skipping job {job_id}: belongs to another user ({user})")
                continue

            self.execute_remote_command(f"scancel {job_id}")
            cancelled_ids.append(job_id)

            # Update UI status immediately for this row
            self.job_tree.item(item, values=(
                vals[0], job_id, self.username, "Cancelled", "--", "N/A"))

        if cancelled_ids:
            self.update_status_bar(
                f"Cancelled {len(cancelled_ids)} jobs: "
                f"{', '.join(cancelled_ids[:5])}"
                f"{'...' if len(cancelled_ids) > 5 else ''}")
            self.log_to_csv("Job cancel issued", cancelled_ids)
        else:
            messagebox.showwarning("Warning",
                                   "You can only cancel your own jobs.")

    def cancel_all_jobs(self):
        if not self.on_cluster:
            messagebox.showinfo("Connection Required",
                                "Please connect to the cluster first.")
            return

        if not self.job_tree.get_children():
            messagebox.showinfo("Info", "No jobs running.")
            return

        # Collect Job IDs for logging before they are cancelled
        cancelled_ids = []
        for item in self.job_tree.get_children():
            vals = self.job_tree.item(item, 'values')
            if vals[2] == self.username:
                cancelled_ids.append(vals[1])
                self.job_tree.item(item, values=(
                    vals[0], vals[1], self.username, "Cancelled", "--", "N/A"))

        self.execute_remote_command(f"scancel -u {self.username}")
        messagebox.showinfo("Success", "All jobs cancelled.")

        if cancelled_ids:
            self.log_to_csv("Job Cancel Issued", cancelled_ids)

    def get_cluster_status(self, silent=False):
        if not self.on_cluster:
            if not silent:
                messagebox.showinfo("Connection Required",
                                    "Please connect to the cluster first.")
            return

        if silent and self.refreshing_status:
            return
        self.refreshing_status = True

        def _fetch():
            try:
                if not silent:
                    self.update_status_bar("Fetching cluster status...")
                out, _ = self.execute_remote_command(
                    "squeue --noheader --format='%A %u %T %M %R'")
                self._update_ui_safely(self._populate_table, out)
                if not silent:
                    self.update_status_bar("Status updated.")
            except Exception as e:
                if not silent:
                    self._update_ui_safely(messagebox.showerror, "Error",
                                           f"Fetch failed: {e}")
            finally:
                self.refreshing_status = False

        threading.Thread(target=_fetch, daemon=True).start()

    def get_user_jobs_status(self, silent=False):
        if not self.on_cluster:
            if not silent:
                messagebox.showinfo("Connection Required",
                                    "Please connect to the cluster first.")
            return
        if silent and self.refreshing_status:
            return
        self.refreshing_status = True

        def _fetch():
            try:
                if not silent:
                    self.update_status_bar("Fetching user jobs...")
                out, _ = self.execute_remote_command(
                    f"squeue --noheader -u {self.username} "
                    f"--format='%A %u %T %M %R'")
                self._update_ui_safely(self._populate_table, out)
                if not out.strip():
                    self.update_status_bar("No job running")
                    if not silent:
                        self._update_ui_safely(messagebox.showinfo, "Info",
                                               "No active jobs found.")
                else:
                    if not silent:
                        self.update_status_bar("User jobs updated.")
            except Exception as e:
                if not silent:
                    self._update_ui_safely(messagebox.showerror, "Error",
                                           f"Fetch failed: {e}")
            finally:
                self.refreshing_status = False

        threading.Thread(target=_fetch, daemon=True).start()

    def _populate_table(self, output):
        # Store selected Job IDs before clearing
        selected_ids = []
        for item in self.job_tree.selection():
            values = self.job_tree.item(item, 'values')
            if values:
                selected_ids.append(values[1])
        # Clear table
        for i in self.job_tree.get_children():
            self.job_tree.delete(i)
        if not output:
            return
        # Insert new data and restore selection
        for idx, line in enumerate(output.strip().split('\n'), 1):
            parts = line.strip().split(maxsplit=4)
            if len(parts) == 5:
                job_id = parts[0]
                item_id = self.job_tree.insert("", "end", values=(idx, *parts))
                if job_id in selected_ids:
                    self.job_tree.selection_add(item_id)

    def make_folder(self, path):
        os.makedirs(path, exist_ok=True)

    def get_sub_folders(self, folder):
        if os.path.exists(folder):
            return sorted(
                [os.path.join(folder, d) for d in os.listdir(folder) if
                 os.path.isdir(os.path.join(folder, d))])
        return []

    def get_job_files(self, folder):
        job_ids, out_files, err_files = [], [], []
        if not os.path.exists(folder):
            return [], [], []
        for f in os.listdir(folder):
            if f.startswith("output_") and f.endswith(".out"):
                jid = f.split("_")[1].split(".")[0]
                job_ids.append(jid)
                out_files.append(os.path.join(folder, f))
                err_files.append(
                    os.path.join(folder, f.replace("output_",
                                                   "error_").replace(".out",
                                                                     ".err")))
        zipped = sorted(zip(job_ids, out_files, err_files),
                        key=lambda x: int(x[0]), reverse=True)
        if zipped:
            return zip(*zipped)
        return [], [], []

    def show_output_window(self):
        # Check if a job is selected in the monitor
        selected_job = self.job_tree.selection()
        target_job_id = None
        target_script_name = None

        if selected_job:
            vals = self.job_tree.item(selected_job[0], 'values')
            if vals:
                target_job_id = str(vals[1])
                # We need to find which script this job belongs to.
                base = self.cluster_base_path.get()
                if os.path.exists(base):
                    for script_folder in os.listdir(base):
                        script_path = os.path.join(base, script_folder)
                        if not os.path.isdir(script_path):
                            continue
                        for sub in os.listdir(script_path):
                            sub_path = os.path.join(script_path, sub)
                            if not os.path.isdir(sub_path):
                                continue
                            if any(f"output_{target_job_id}.out" in f for f in
                                   os.listdir(sub_path)):
                                target_script_name = script_folder
                                break
                        if target_script_name:
                            break

        script_to_use = target_script_name if target_script_name else (
            self.current_script.replace(".py",
                                        "") if self.current_script else None)

        if not script_to_use:
            messagebox.showinfo("Info", "Select a script or a job first.")
            return

        base = self.cluster_base_path.get()
        base_dir = f"{base}/{script_to_use}/"

        if not os.path.exists(base_dir):
            messagebox.showinfo("Info",
                                f"No output folder found for {script_to_use}.")
            return
        subfolders = self.get_sub_folders(base_dir)
        if not subfolders:
            messagebox.showinfo("Info", "No scan folders found.")
            return

        top = tk.Toplevel(self)
        top.title(f"Output: {script_to_use}")
        self.center_child_window(top, ratio=0.85)
        paned = ttk.PanedWindow(top, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        # 1. Scan folders panel (Ratio 1)
        folder_frame = ttk.Frame(paned)
        paned.add(folder_frame, weight=1)
        ttk.Label(folder_frame, text="Scan folders",
                  font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(0, 2))
        folder_list = tk.Listbox(folder_frame, bd=1, relief="solid",
                                 selectbackground=LISTBOX_SELECT_BG,
                                 selectforeground=LISTBOX_SELECT_FG,
                                 activestyle="none",
                                 exportselection=False,
                                 font=(FONT_FAMILY, 10))
        folder_list.pack(fill=tk.BOTH, expand=True)
        for f in subfolders:
            folder_list.insert(tk.END, os.path.basename(f))
        # 2. Job IDs panel (Ratio 1)
        job_frame = ttk.Frame(paned)
        paned.add(job_frame, weight=1)
        ttk.Label(job_frame, text="Job IDs",
                  font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(0, 2))
        job_list = tk.Listbox(job_frame, bd=1, relief="solid",
                              selectbackground=LISTBOX_SELECT_BG,
                              selectforeground=LISTBOX_SELECT_FG,
                              activestyle="none",
                              exportselection=False,
                              font=(FONT_FAMILY, 10))
        job_list.pack(fill=tk.BOTH, expand=True)
        # 3. Standard output panel (Ratio 3)
        out_frame = ttk.Frame(paned)
        paned.add(out_frame, weight=3)
        ttk.Label(out_frame, text="Standard output",
                  font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(0, 2))
        out_txt_frame = ttk.Frame(out_frame)
        out_txt_frame.pack(fill=tk.BOTH, expand=True)
        out_txt_frame.grid_columnconfigure(0, weight=1)
        out_txt_frame.grid_rowconfigure(0, weight=1)

        out_txt = tk.Text(out_txt_frame, bd=1, relief="solid",
                          wrap="none",
                          background=BG_COLOR_OUTPUT,
                          font=("Consolas", CONSOLE_FONT))
        out_txt.grid(row=0, column=0, sticky="nsew")

        out_vsb = ttk.Scrollbar(out_txt_frame, orient="vertical",
                                command=out_txt.yview)
        out_vsb.grid(row=0, column=1, sticky="ns")
        out_hsb = ttk.Scrollbar(out_txt_frame, orient="horizontal",
                                command=out_txt.xview)
        out_hsb.grid(row=1, column=0, sticky="ew")

        out_txt.configure(yscrollcommand=out_vsb.set,
                          xscrollcommand=out_hsb.set)
        # 4. Standard error panel (Ratio 3)
        err_frame = ttk.Frame(paned)
        paned.add(err_frame, weight=3)
        ttk.Label(err_frame, text="Standard error",
                  font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(0, 2))

        err_txt_frame = ttk.Frame(err_frame)
        err_txt_frame.pack(fill=tk.BOTH, expand=True)
        err_txt_frame.grid_columnconfigure(0, weight=1)
        err_txt_frame.grid_rowconfigure(0, weight=1)
        err_txt = tk.Text(err_txt_frame, bd=1, relief="solid",
                          wrap="none", fg="red",
                          background=BG_COLOR_OUTPUT,
                          font=("Consolas", CONSOLE_FONT))
        err_txt.grid(row=0, column=0, sticky="nsew")
        err_vsb = ttk.Scrollbar(err_txt_frame, orient="vertical",
                                command=err_txt.yview)
        err_vsb.grid(row=0, column=1, sticky="ns")
        err_hsb = ttk.Scrollbar(err_txt_frame, orient="horizontal",
                                command=err_txt.xview)
        err_hsb.grid(row=1, column=0, sticky="ew")
        err_txt.configure(yscrollcommand=err_vsb.set,
                          xscrollcommand=err_hsb.set)
        self.view_job_ids, self.view_outs, self.view_errs = [], [], []

        def on_folder_sel(e, auto_select_job_id=None):
            sel = folder_list.curselection()
            if not sel:
                return
            folder = subfolders[sel[0]]
            self.view_job_ids, self.view_outs, self.view_errs = \
                self.get_job_files(folder)
            job_list.delete(0, tk.END)
            for j in self.view_job_ids:
                job_list.insert(tk.END, j)

            if auto_select_job_id:
                try:
                    idx = list(self.view_job_ids).index(auto_select_job_id)
                    job_list.select_set(idx)
                    on_job_sel(None)
                except ValueError:
                    pass

        def on_job_sel(e):
            sel = job_list.curselection()
            if not sel:
                return
            idx = sel[0]
            out_txt.delete("1.0", tk.END)
            err_txt.delete("1.0", tk.END)
            try:
                with open(self.view_outs[idx], 'r') as f:
                    out_txt.insert(tk.END, f.read())
            except Exception as e:
                out_txt.insert(tk.END, str(e))
            try:
                with open(self.view_errs[idx], 'r') as f:
                    err_txt.insert(tk.END, f.read())
            except Exception as e:
                err_txt.insert(tk.END, str(e))

        folder_list.bind("<<ListboxSelect>>", on_folder_sel)
        job_list.bind("<<ListboxSelect>>", on_job_sel)

        if target_job_id and target_script_name:
            target_folder_idx = -1
            for idx, folder_path in enumerate(subfolders):
                if any(f"output_{target_job_id}.out" in f for f in
                       os.listdir(folder_path)):
                    target_folder_idx = idx
                    break

            if target_folder_idx != -1:
                folder_list.select_set(target_folder_idx)
                on_folder_sel(None, auto_select_job_id=target_job_id)

    def start_refresh_loop(self):
        if not self.refresh_loop_active:
            self.refresh_loop_active = True
            self.refresh_job_monitor()

    def refresh_job_monitor(self):
        if not self.shutdown_flag and self.on_cluster:
            mode = self.job_view_mode.get()
            if mode == "my_jobs":
                self.get_user_jobs_status(silent=True)
            else:
                self.get_cluster_status(silent=True)

        if not self.shutdown_flag:
            self.after(REFRESH_TIME * 1000, self.refresh_job_monitor)

    def on_exit(self):
        self.shutdown_flag = True
        self.ssh_disconnect()
        self.destroy()

    def on_exit_signal(self, signum, frame):
        self.on_exit()

    def check_for_exit_signal(self):
        if self.shutdown_flag:
            self.on_exit()
        else:
            self.after(100, self.check_for_exit_signal)


display_msg = """
===============================================================================

    GUI software for submitting and managing Python jobs on Slurm Clusters

===============================================================================
"""


def parse_args():
    parser = argparse.ArgumentParser(
        description=display_msg,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-b", "--base", type=str, default=None,
                        help="Specify the base script folder")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Specify the cluster output base folder")
    return parser.parse_args()


def get_base_folders(args_base, args_output):
    """
    Determine the initial script and cluster folders based on:
    1. CLI args
    2. Config file
    3. Defaults/CWD
    """
    config_data = load_config()
    # 1. Script Base Folder
    if args_base:
        script_folder = os.path.abspath(args_base)
    elif config_data and "last_folder" in config_data:
        # Check if saved folder still exists
        if os.path.exists(config_data["last_folder"]):
            script_folder = config_data["last_folder"]
        else:
            script_folder = os.getcwd()
    else:
        script_folder = os.getcwd()
    # 2. Cluster output folder
    if args_output:
        cluster_folder = os.path.abspath(args_output)
    else:
        cluster_folder = None

    return script_folder, cluster_folder


def main():
    args = parse_args()
    script_folder, cluster_folder = get_base_folders(args.base, args.output)

    app = ClusterRunnerInteractions(script_folder, cluster_folder)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app.on_exit()


if __name__ == "__main__":
    main()
