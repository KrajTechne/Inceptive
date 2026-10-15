"""Step 1: run BindCraft2 on a Modal GPU.

Usage:
    python -m modal run run_design.py --config configs/pdl1_denovo_test.yaml
    python -m modal run run_design.py --config configs/pdl1_denovo_test.yaml --dry-run

Results are saved on the `inceptive-runs` Volume under <run_name>/design/.
Re-running with the same run_name resumes where BindCraft2 left off.
"""
import json
import os
import subprocess

from config_loader import load_config, require_keys
from modal_app import (RUNS_DIR, WEIGHTS_DIR, app, bindcraft_image,
                       runs_volume, weights_volume)

COMMIT_EVERY_SECONDS = 300  # save progress to the Volume this often


# This function runs remotely, inside the container on a GPU.
# Its GPU and timeout are filled in later (see main) so they come from the config.
@app.function(
    image=bindcraft_image,
    volumes={RUNS_DIR: runs_volume, WEIGHTS_DIR: weights_volume},
)
def design(run_name: str, bindcraft_settings: dict):
    design_dir = f"{RUNS_DIR}/{run_name}/design"
    os.makedirs(design_dir, exist_ok=True)

    # BindCraft2 reads a JSON settings file, so write the config out as one.
    settings = {**bindcraft_settings, "project_folder": design_dir}
    settings_path = f"{RUNS_DIR}/{run_name}/design_settings.json"
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    # Download the AlphaFold weights the first time (skipped once they are on the Volume).
    subprocess.run(["bindcraft", "fetch-weights"], check=True)
    weights_volume.commit()

    # Run the design campaign. We commit the Volume every few minutes so results
    # are kept even if the run is stopped or times out.
    proc = subprocess.Popen(["bindcraft", "design", settings_path])
    while True:
        try:
            proc.wait(timeout=COMMIT_EVERY_SECONDS)
            break
        except subprocess.TimeoutExpired:
            runs_volume.commit()
    runs_volume.commit()

    if proc.returncode != 0:
        raise RuntimeError(f"bindcraft exited with code {proc.returncode}")
    return design_dir


# This runs on your own computer and launches the remote function.
@app.local_entrypoint()
def main(config: str, dry_run: bool = False):
    cfg = load_config(config)
    require_keys(cfg, ["run_name", "design"], where=config)
    run_name, design_cfg = cfg["run_name"], cfg["design"]
    require_keys(design_cfg, ["gpu", "timeout_hours", "bindcraft"], where="design section")

    print(f"Run name : {run_name}")
    print(f"GPU      : {design_cfg['gpu']}   timeout: {design_cfg['timeout_hours']} h")

    # with_options sets compute from the config instead of the code. cpu and memory_gb are
    # optional; set them for multi-GPU runs (see configs/pdl1_parallel_test.yaml).
    options = {"gpu": design_cfg["gpu"], "timeout": int(design_cfg["timeout_hours"] * 3600)}
    if "cpu" in design_cfg:
        options["cpu"] = design_cfg["cpu"]
    if "memory_gb" in design_cfg:
        options["memory"] = int(design_cfg["memory_gb"] * 1024)  # Modal wants MiB
    print(f"Modal options: {options}")
    print(f"BindCraft2 settings:\n{json.dumps(design_cfg['bindcraft'], indent=2)}")
    if dry_run:
        print("Dry run, nothing launched.")
        return

    remote_design = design.with_options(**options)
    out = remote_design.remote(run_name, design_cfg["bindcraft"])
    print(f"Done. Results on Volume 'inceptive-runs' at {out}")
    print(f"Download with: python -m modal volume get inceptive-runs {run_name} ./results")
