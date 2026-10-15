"""Shared Modal setup: the app, the storage Volumes, and the BindCraft2 image.

Every step file (run_design.py, ...) imports `app` and the Volumes from here,
so there is exactly one place to change names or paths.
"""
import modal

# An App groups all our Modal functions together (shows up in the Modal dashboard).
app = modal.App("inceptive")

# A Volume is persistent storage that survives after a function finishes.
# create_if_missing=True makes it the first time it is used.
RUNS_VOLUME_NAME = "inceptive-runs"
runs_volume = modal.Volume.from_name(RUNS_VOLUME_NAME, create_if_missing=True)
weights_volume = modal.Volume.from_name("alphafold2-weights", create_if_missing=True)

# Where each Volume appears inside the running container.
RUNS_DIR = "/runs"        # one subfolder per run: /runs/<run_name>/...
WEIGHTS_DIR = "/weights"  # model weights, downloaded once and reused

# --- BindCraft2 image -------------------------------------------------------
# An Image is the container recipe. This follows bindcraft2/containers/Dockerfile.
# The bindcraft2/ folder is a git submodule (pinned to a specific commit).
BINDCRAFT_PATH = "/opt/bindcraft"

bindcraft_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "build-essential")
    # Copy the submodule into the image. copy=True is needed so the next step can
    # use the files while building. .git is skipped because it is not needed.
    .add_local_dir("bindcraft2", BINDCRAFT_PATH, copy=True, ignore=["**/.git", "docs"])
    # Editable install, because BindCraft2 finds its settings/ folder next to its source.
    .run_commands(f"pip install -e '{BINDCRAFT_PATH}[cuda13]'")
    # From BindCraft2's Dockerfile: tell the system where the pip-installed CUDA
    # libraries are, otherwise JAX silently falls back to the (very slow) CPU.
    .run_commands(
        "python -c \"import nvidia, pathlib; print('\\n'.join(sorted(str(p) for r in nvidia.__path__ "
        "for p in pathlib.Path(r).glob('*/lib'))))\" > /etc/ld.so.conf.d/bindcraft-cuda.conf && ldconfig"
    )
    # Make BindCraft2 keep its AlphaFold weights (5.3 GB) on the weights Volume.
    .env({"BINDCRAFT_WEIGHTS": f"{WEIGHTS_DIR}/bindcraft"})
    # run_design.py imports these at the top, so the container needs them too
    # (Modal only copies the entrypoint file by itself). Keep this line last.
    .pip_install("pyyaml")
    .add_local_python_source("config_loader", "modal_app")
)

# --- Bridge image (CPU only) ------------------------------------------------
# Used by run_validation.py to turn BindCraft2's .cif files into the CSV that
# Optimus expects. It reuses Optimus's own designs_from_structures.py (from the
# optimus/ submodule), so the logic is not copied into this repo.
bridge_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("biotite", "gemmi", "pandas", "numpy", "pyyaml")
    .add_local_file("optimus/designs_from_structures.py", "/root/designs_from_structures.py")
    .add_local_file("optimus/StrucTools.py", "/root/StrucTools.py")
    .add_local_python_source("config_loader", "modal_app")
)
