import os
import ast
import platform
import json

# ==============================================================================
#                          Configuration & Constants
# ==============================================================================

FONT_FAMILY = "Segoe UI" if os.name == "nt" else "Helvetica"
FONT_SIZE = 11
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
