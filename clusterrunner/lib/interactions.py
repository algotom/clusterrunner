import os
import sys
import shlex
import time
import socket
import signal
import textwrap
import threading
import queue
import paramiko
import logging
import csv
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import clusterrunner.lib.utilities as util
from clusterrunner.lib.rendering import ClusterRunnerRendering, \
    CodeEditorWindow, ToolTip


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
                  font=(util.FONT_FAMILY, 10, "bold")).pack(anchor="w")
        detail_txt_frame = ttk.Frame(detail_frame)
        detail_txt_frame.pack(fill=tk.BOTH, expand=True)
        detail_txt_frame.grid_columnconfigure(0, weight=1)
        detail_txt_frame.grid_rowconfigure(0, weight=1)

        detail_text = tk.Text(detail_txt_frame, height=6, bd=1, relief="solid",
                              background=util.BG_COLOR_OUTPUT,
                              font=("Consolas", util.CONSOLE_FONT), wrap="word")
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
            util.save_config({"last_folder": folder})

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
        scripts = util.find_possible_scripts(folder)
        for script in scripts:
            script_path = os.path.join(folder, script)
            if self.show_all_scripts_var.get():
                self.script_list.insert(tk.END, script)
            else:
                arguments, _ = util.get_script_arguments(script_path)
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
        arguments, _ = util.get_script_arguments(script_path)
        self.entries = {}

        # Configure columns: 0=Flag, 1=Entry, 2=Type, 3=List?, 4=Help
        self.args_frame.columnconfigure(1, weight=0)
        self.args_frame.columnconfigure(4, weight=1)

        row = 0
        ttk.Label(self.args_frame, text=f"{script}",
                  font=(util.FONT_FAMILY, util.FONT_SIZE + 1),
                  foreground=util.PATH_COLOR).grid(row=row, column=0,
                                                   columnspan=5, sticky="w",
                                                   pady=(0, 5))
        row += 1
        if not arguments:
            ttk.Label(self.args_frame,
                      text="No arguments found or not an argparse script.",
                      font=(util.FONT_FAMILY, 10)).grid(row=row, column=0,
                                                        columnspan=5,
                                                        sticky="w", padx=5)
            row += 1
        for flag, dest, help_text, arg_type, required, default_value \
                in arguments:
            # 1. Flag Label
            ttk.Label(self.args_frame, text=flag, width=15, anchor="w",
                      font=(util.FONT_FAMILY, util.FONT_SIZE)).grid(row=row,
                                                                    column=0,
                                                                    sticky="nw",
                                                                    pady=5)
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
                parsed_list = util.get_scan_list(raw_val, target_type=arg_type)
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
                  font=(util.FONT_FAMILY, 10, "bold")).pack(anchor="w",
                                                            pady=(0, 2))
        folder_list = tk.Listbox(folder_frame, bd=1, relief="solid",
                                 selectbackground=util.LISTBOX_SELECT_BG,
                                 selectforeground=util.LISTBOX_SELECT_FG,
                                 activestyle="none",
                                 exportselection=False,
                                 font=(util.FONT_FAMILY, 10))
        folder_list.pack(fill=tk.BOTH, expand=True)
        for f in subfolders:
            folder_list.insert(tk.END, os.path.basename(f))
        # 2. Job IDs panel (Ratio 1)
        job_frame = ttk.Frame(paned)
        paned.add(job_frame, weight=1)
        ttk.Label(job_frame, text="Job IDs",
                  font=(util.FONT_FAMILY, 10, "bold")).pack(anchor="w",
                                                            pady=(0, 2))
        job_list = tk.Listbox(job_frame, bd=1, relief="solid",
                              selectbackground=util.LISTBOX_SELECT_BG,
                              selectforeground=util.LISTBOX_SELECT_FG,
                              activestyle="none",
                              exportselection=False,
                              font=(util.FONT_FAMILY, 10))
        job_list.pack(fill=tk.BOTH, expand=True)
        # 3. Standard output panel (Ratio 3)
        out_frame = ttk.Frame(paned)
        paned.add(out_frame, weight=3)
        ttk.Label(out_frame, text="Standard output",
                  font=(util.FONT_FAMILY, 10, "bold")).pack(anchor="w",
                                                            pady=(0, 2))
        out_txt_frame = ttk.Frame(out_frame)
        out_txt_frame.pack(fill=tk.BOTH, expand=True)
        out_txt_frame.grid_columnconfigure(0, weight=1)
        out_txt_frame.grid_rowconfigure(0, weight=1)

        out_txt = tk.Text(out_txt_frame, bd=1, relief="solid",
                          wrap="none",
                          background=util.BG_COLOR_OUTPUT,
                          font=("Consolas", util.CONSOLE_FONT))
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
                  font=(util.FONT_FAMILY, 10, "bold")).pack(anchor="w",
                                                            pady=(0, 2))

        err_txt_frame = ttk.Frame(err_frame)
        err_txt_frame.pack(fill=tk.BOTH, expand=True)
        err_txt_frame.grid_columnconfigure(0, weight=1)
        err_txt_frame.grid_rowconfigure(0, weight=1)
        err_txt = tk.Text(err_txt_frame, bd=1, relief="solid",
                          wrap="none", fg="red",
                          background=util.BG_COLOR_OUTPUT,
                          font=("Consolas", util.CONSOLE_FONT))
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
            self.after(util.REFRESH_TIME * 1000, self.refresh_job_monitor)

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
