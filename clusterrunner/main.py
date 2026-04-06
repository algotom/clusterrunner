import os
import argparse
from clusterrunner import __version__
import clusterrunner.lib.utilities as util
from clusterrunner.lib.interactions import ClusterRunnerInteractions


display_msg = """
===============================================================================

    GUI software for submitting and managing Python jobs on Slurm Clusters

===============================================================================
"""


def parse_args():
    parser = argparse.ArgumentParser(
        description=display_msg,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--version", action="version",
                        version=f"ClusterRunner {__version__}")
    parser.add_argument("-b", "--base", type=str, default=None,
                        help="Specify the base script-folder")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Specify the cluster output base-folder")
    return parser.parse_args()


def get_base_folders(args_base, args_output):
    """
    Determine the initial script and cluster folders based on:
    1. CLI args
    2. Config file
    3. Defaults/CWD
    """
    config_data = util.load_config()
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
