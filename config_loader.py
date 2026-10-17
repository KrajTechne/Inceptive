"""Read a YAML config file into a plain Python dict.

Every pipeline step starts with this, so the settings live in configs/ and
never in the Python code.
"""
import os
from pathlib import Path

import yaml


def load_config(path):
    """Load a YAML file and return its contents as a dict."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def require_keys(config, keys, where="config"):
    """Stop early with a clear message if a required key is missing."""
    missing = [k for k in keys if k not in config]
    if missing:
        raise KeyError(f"{where} is missing required keys: {missing}")


# --- Where validation results live -------------------------------------------
# validate.output_name (default "validation") lets you run validation again on the same
# designs without touching the earlier results: set it to e.g. "validation_retest".
DEFAULT_VALIDATION_NAME = "validation"


def validation_name(cfg):
    return cfg.get("validate", {}).get("output_name", DEFAULT_VALIDATION_NAME)


def validation_volume_dir(cfg):
    """Folder on the Volume for validation results, e.g. 'my_run/validation'."""
    return f"{cfg['run_name']}/{validation_name(cfg)}"


def local_results_dir(cfg):
    """Folder on your computer for this run's files. A non-default output_name gets its own subfolder."""
    base = os.path.join("results", cfg["run_name"])
    name = validation_name(cfg)
    return base if name == DEFAULT_VALIDATION_NAME else os.path.join(base, name)


def final_report_volume_path(cfg):
    """Where report.py uploads the merged table on the Volume."""
    name = validation_name(cfg)
    suffix = "" if name == DEFAULT_VALIDATION_NAME else f"_{name}"
    return f"{cfg['run_name']}/final_report{suffix}.csv"
