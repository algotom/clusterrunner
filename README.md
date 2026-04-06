# ClusterRunner
![Logo](https://github.com/algotom/clusterrunner/raw/main/ClusterRunner_icon.png)

---
*GUI software for submitting and managing Python jobs on Slurm Clusters*
---

Motivation
==========

In facilities with a SLURM cluster high-performance computing (HPC) system, to run a Python 
script users have to log in (ssh) to a submission node and write a *sbatch* script to 
request resources and submit the Python scripts, then use SLURM commands to 
manage jobs. This is inconvenient and inefficient, particularly for those who 
are not experienced with running jobs on a cluster. This GUI is designed to 
make submitting and managing jobs on a cluster easy for anyone who has access 
to the cluster and wants to make the most of it.

This GUI was originally built to support running tomography data processing workflows on 
clusters, driven by very high data generation rates of synchrotron-based 
tomography beamlines (20–100 GB/minute).

Features
========

- Simple cluster connection: connect to a Slurm cluster over SSH (supports 
  interactive login such as Duo) without using the terminal. Users do not need to 
  log in to a submission node manually; everything is done through the GUI.

  ![Fig_1](https://github.com/algotom/clusterrunner/raw/main/figs/fig1.png)

- Automatic input form generation: load an argparse-based Python script and the 
  GUI automatically builds input fields from its arguments. This is especially 
  useful for command-line data processing workflows, which is the main purpose 
  of this GUI. For non-argparse scripts (tick "Show all .py"), users simply submit them to the cluster.

  ![Fig_2](https://github.com/algotom/clusterrunner/raw/main/figs/fig2.png)

- Easy job submission: choose CPU/GPU, memory, and runtime, then submit jobs with a single click.

  ![Fig_3](https://github.com/algotom/clusterrunner/raw/main/figs/fig3.png)

- Batch jobs made simple: run multiple jobs at once by providing lists of input values.

  ![Fig_4](https://github.com/algotom/clusterrunner/raw/main/figs/fig4.png)
  
- Built-in job monitor: view job status, cancel jobs, and check output/error logs directly within the GUI.

  ![Fig_5](https://github.com/algotom/clusterrunner/raw/main/figs/fig5.png)

- Built-in script editor: edit Python scripts directly inside the application, no need for external editors 
  like VS Code or Vim. Compare two scripts side-by-side to track modifications or validate parameter changes.

  ![Fig_6](https://github.com/algotom/clusterrunner/raw/main/figs/fig6.png)

Installation
============

Install [Miniconda, Anaconda or Miniforge](https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html), then 
open a Linux terminal or the Miniconda/Anaconda PowerShell prompt and use the following commands
for installation.

Using pip:
```commandline
pip install clusterrunner
```
Using conda:
```commandline
conda install -c algotom clusterrunner
```
Once installed, launching Cluster-Runner with
```commandline
clusterrunner
```
Using -h for option usage
```commandline
clusterrunner -h
```
---
Installing from source:
- If using a single file:
    + Copy the file *clusterrunner.py*. Install python, paramiko.
    + Run:
        ```commandline
        python clusterrunner.py
        ```
- If using setup.py
    + Create conda environment
      ```commandline
      conda create -n clusterrunner python=3.11
      conda activate clusterrunner
      ``` 
    + Clone the source (git needs to be installed)
      ```commandline
      git clone https://github.com/algotom/clusterrunner.git
      ```
    + Navigate to the cloned directory (having setup.py file)
      ```commandline
      pip install .
      ```
      
Usage
=====

- For users not familiar with using a cluster: the GUI must be run on a system that 
  can SSH to a Slurm cluster (Linux OS). Because Python scripts run in the cluster 
  environment, make sure outputs are written to files (e.g., interactive plots will 
  not work). If the script reads from or writes to files, ensure the cluster can 
  access those folders.

- Select a base folder containing Python scripts and a folder for cluster output messages.
  Select the path to the Python environment. By default, the interpreter is chosen in the 
  following priority: Manual entry, “Select file”, Script shebang, Same as the current GUI.

- Clicking a script will show the arguments of that script in the right panel.

- Double-clicking a script will open the Editor panel window.

- Clicking "Submit jobs" will submit the current script to the cluster.

- Tick "List" option to accept a list of values for submitting multiple-jobs.

- By default, ClusterRunner picks and displays ArgParse-based scripts. However, users 
  can choose to display all Python scripts by ticking the box "Show all .py".
