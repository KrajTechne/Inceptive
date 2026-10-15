"""Read a YAML config file into a plain Python dict.

Every pipeline step starts with this, so the settings live in configs/ and
never in the Python code.
"""
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
