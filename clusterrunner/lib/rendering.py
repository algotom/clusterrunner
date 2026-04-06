import os
import tkinter as tk
from pathlib import Path
import importlib.resources
import tkinter.font as tkFont
from tkinter import ttk, messagebox
import clusterrunner.lib.utilities as util

try:
    from idlelib.colorizer import ColorDelegator
    from idlelib.percolator import Percolator
except ImportError:
    ColorDelegator = None
    Percolator = None


def get_icon_path():
    with importlib.resources.path("clusterrunner.assets",
                                  "ClusterRunner_icon.png") as icon:
        return str(icon)


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
                  font=(util.FONT_FAMILY, 8)).pack(side=tk.LEFT, padx=2)
        self.entry_new_name = ttk.Entry(toolbar,
                                        width=12, font=(util.FONT_FAMILY, 9))
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
                                  font=(util.FONT_FAMILY, 9, "bold"))
        self.lbl_info.pack(side=tk.RIGHT, padx=5)
        # Main Content
        content_frame = ttk.Frame(self)
        content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.vsb = ttk.Scrollbar(content_frame, orient="vertical")
        self.hsb = ttk.Scrollbar(content_frame, orient="horizontal")
        # Line Numbers
        self.line_numbers = tk.Text(content_frame, width=4, padx=4, takefocus=0,
                                    border=0, background=util.LINE_NUM_BG,
                                    foreground=util.LINE_NUM_FG,
                                    state='disabled',
                                    font=("Consolas", util.CODE_FONT_SIZE))
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)
        # Text Area
        self.text_area = tk.Text(content_frame, wrap="none",
                                 font=("Consolas", util.CODE_FONT_SIZE),
                                 undo=True, yscrollcommand=self.vsb.set,
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
        width = int(self.screen_width * util.TEXT_WIN_RATIO)
        height = int(self.screen_height * util.TEXT_WIN_RATIO)
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
            icon_path = get_icon_path()
            if icon_path and Path(icon_path).exists():
                icon = tk.PhotoImage(file=icon_path)
                self.iconphoto(True, icon)
        except (tk.TclError, TypeError):
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
            self.style.theme_use(util.TTK_THEME)
        except:
            pass

        default_font = tkFont.nametofont("TkDefaultFont")
        default_font.configure(family=util.FONT_FAMILY, size=util.FONT_SIZE,
                               weight=util.FONT_WEIGHT)
        self.option_add("*Font", default_font)

        self.style.configure("TButton", padding=1)
        self.style.configure("TEntry", padding=1)
        self.style.configure("TLabelframe.Label",
                             font=(util.FONT_FAMILY, util.FONT_SIZE, "normal"),
                             foreground="#333")
        self.style.configure("Treeview", rowheight=25,
                             font=(util.FONT_FAMILY, util.FONT_SIZE))
        self.style.configure("Treeview.Heading",
                             font=(util.FONT_FAMILY, util.FONT_SIZE))
        self.style.configure("Path.TLabel", foreground=util.PATH_COLOR,
                             font=(util.FONT_FAMILY, util.FONT_SIZE, "italic"))
        self.style.configure("Small.TButton", padding=3,
                             font=(util.FONT_FAMILY, 10))
        self.style.configure("Action.TButton",
                             font=(util.FONT_FAMILY, util.FONT_SIZE), padding=3)
        self.style.configure("Header.TFrame", background="#e1e1e1",
                             relief="groove")

    def setup_window(self):
        self.title("Cluster Script Runner")
        width = int(self.screen_width * util.MAIN_WIN_RATIO)
        height = int(self.screen_height * util.MAIN_WIN_RATIO)
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
                                      selectbackground=util.LISTBOX_SELECT_BG,
                                      selectforeground=util.LISTBOX_SELECT_FG,
                                      activestyle="none",
                                      font=(util.FONT_FAMILY, util.FONT_SIZE),
                                      width=30)
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
                  font=(util.FONT_FAMILY, util.FONT_SIZE)).grid(row=0, column=0,
                                                                padx=5,
                                                                pady=(0, 5),
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
                                          font=(util.FONT_FAMILY,
                                                util.FONT_SIZE))
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
                                 font=(util.FONT_FAMILY, util.FONT_SIZE))
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
                                            font=(util.FONT_FAMILY,
                                                  util.FONT_SIZE, "bold"))
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
