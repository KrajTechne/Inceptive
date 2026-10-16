# Inceptive

Protein design with BindCraft2, RFDiffusion, etc. and leverages Optimus for Optional Refinement and Mandatory Cross Validation

A protein binder design pipeline that runs on [Modal](https://modal.com):

```
inputs/configs/<run>.yaml
   │
   ├─ run_design.py      BindCraft2 designs binders on a GPU
   ├─ run_validation.py  picks the top designs, Optimus re-predicts them with other models
   └─ report.py          merges both into results/<run>/final_report.csv
```

`run_pipeline.py` runs all three in order. See `PLAN.md` for the design notes and decisions.

## One-time setup

```bash
git clone --recurse-submodules <this repo>     # the two tools below are git submodules
cd Inceptive
pip install -r requirements.txt                # Python 3.12
modal setup                                    # log in to Modal (once)
```

- `bindcraft2/` (PacesaLab/BindCraft2) and `optimus/` (KrajTechne/Optimus) are **submodules**, pinned to specific commits. If they are empty, run `git submodule update --init`. To move to newer versions: `git submodule update --remote <name>`, then commit.
- **Windows:** set UTF-8 before any `modal` command, otherwise Modal's CLI crashes printing a checkmark (`'charmap' codec can't encode...`). Bash: `export PYTHONUTF8=1`. PowerShell: `$env:PYTHONUTF8 = "1"`. The pipeline scripts set it for the commands they launch.
- **Windows line endings:** Optimus builds a Linux image from files on your disk, and a shell script with Windows (CRLF) endings fails with `$'\r': command not found`. If git converts line endings on your machine, run `git -C optimus config core.autocrlf false` and re-checkout `optimus/LigandMPNN/get_model_params.sh`.

## Run it

```bash
python run_pipeline.py --config inputs/configs/pdl1_denovo_test.yaml --dry-run   # show the plan, run nothing
python run_pipeline.py --config inputs/configs/pdl1_denovo_test.yaml             # run everything
```

Or one step at a time (each takes the same config file and has `--dry-run`):

```bash
python -m modal run run_design.py     --config inputs/configs/pdl1_denovo_test.yaml
python -m modal run run_validation.py --config inputs/configs/pdl1_denovo_test.yaml
python report.py                      --config inputs/configs/pdl1_denovo_test.yaml
```

`run_pipeline.py` also accepts `--skip-design` and `--skip-validation` to reuse finished results.

**Cost and time:** design and validation use paid GPUs (A100 for design, H100 for validation by default). The very first run is slow: it builds the images and downloads about 5.3 GB of AlphaFold weights. Later runs reuse both. Design resumes if you re-run with the same `run_name`.

## The config file

One YAML per run, in `inputs/configs/`. Each step reads its own section; `run_name` is shared and names the folder where everything is stored.

| Section | Used by | What it does |
|---|---|---|
| `run_name` | all steps | Results go to `<run_name>/` on the Volume and `results/<run_name>/` locally. |
| `design` | `run_design.py` | `gpu` (e.g. `A100`, or `A100:4` for 4 GPUs), `timeout_hours`, optional `cpu` / `memory_gb`, and the BindCraft2 settings: `bindcraft_json:` (path to a BindCraft2 settings JSON) and/or `bindcraft:` (inline; wins over the JSON). See "Adding a new target". |
| `selection` | `run_validation.py` | `top_n` best designs to validate, and `binder_chain` (BindCraft2 writes the binder as chain `B`, target as `A`). |
| `validate` | `run_validation.py` | Passed straight to Optimus as its config: `models` (`of3`, `native_af3`, `esmfold2`), `seeds`, `num_samples`, `gpu_type`, etc. |
| `report` | `report.py` | Pass thresholds: `min_iptm`, `min_ipsae`, `min_contact_pass_fraction`. A design passes if every model meets all three. |

To start a new campaign, copy `inputs/configs/pdl1_denovo_test.yaml`, change `run_name` and the settings.

### Adding a new target

1. Put the structure (`.cif` or `.pdb`) in `inputs/structures/`.
2. Put the BindCraft2 settings JSON (a `targets:` list with `name`, `target_path`, `chains`, `hotspots`/`coldspots`, plus campaign settings) in `inputs/configs/`.
3. Copy a run YAML such as `inputs/configs/il4_apo_run.yaml` and point `design.bindcraft_json` at the JSON.

Notes on how the JSON is used:
- **Structures are found by file name** in `inputs/structures/`. The directory written in `target_path` (for example a Colab or Drive path) and any `project_folder` are ignored and replaced automatically.
- Keys under `design.bindcraft:` in the run YAML override the same keys in the JSON. This matters for Colab leftovers: `workers_per_gpu: 1` and `auto_multi_gpu: false` keep BindCraft2 on one worker and one GPU, so override them (for example `auto_multi_gpu: true`, `workers_per_gpu: auto`) when you ask for several GPUs.
- Residue numbers in `hotspots` / `coldspots` follow BindCraft2's numbering of the structure you supplied. Check them if a structure does not start at residue 1.
- `selection.binder_chain` is the chain BindCraft2 gives the binder in its output files (`B` when the target is the single chain `A`); check it on the first run of a target with several chains.

## Where things are stored

Two Modal Volumes (persistent storage; see them with `python -m modal volume list`):

| Volume | Contents |
|---|---|
| `inceptive-runs` | One folder per run: `<run_name>/design/` (BindCraft2 output: `3_Ranked/` has the final designs), `<run_name>/validation/` (Optimus output), `<run_name>/final_report.csv`. |
| `alphafold2-weights` | AlphaFold2 weights for BindCraft2, downloaded once. |

On your computer, `results/<run_name>/` holds the CSV sent to Optimus, the Optimus config used, and `final_report.csv`. It is git-ignored.

`final_report.csv` has one row per design: BindCraft2's metrics (`i_pDAE`, `i_pTM`, ...), each validation model's metrics (`of3_iptm`, `esmfold2_ipsae`, ...), and `passes_validation`.

## Modal cheat-sheet

```bash
python -m modal volume ls  inceptive-runs <run_name>                    # list files
python -m modal volume get inceptive-runs <run_name> ./results/<run_name>/full   # download a folder
python -m modal app list                                                # running and recent apps
python -m modal app logs <app-id>                                       # logs of a run
python -m modal app stop <app-id>                                       # stop a run (stops billing)
```

Run links are also printed when a step starts (`https://modal.com/apps/...`), where you can see logs and GPU use.

## Files

| File | Purpose |
|---|---|
| `modal_app.py` | Shared Modal setup: the app, the two Volumes, and the container images. Change names/paths here. |
| `run_design.py` | Step 1: BindCraft2 on a GPU. |
| `run_validation.py` | Step 2: builds the Optimus input from the top designs, then launches Optimus. |
| `report.py` | Step 3: merges design and validation results. |
| `run_pipeline.py` | Runs the steps in order and waits for validation to finish. |
| `config_loader.py`, `volume_utils.py` | Small helpers (read YAML; copy files to/from the Volume). |
| `inputs/configs/` | One run YAML per run, plus BindCraft2 settings JSONs for each target. |
| `inputs/structures/` | Target structure files (`.cif` / `.pdb`). |

## Adding a step or a tool

1. Add a `<step>:` section to the config with its settings.
2. Copy `run_design.py` (a GPU step) or the `build_designs_csv` function in `run_validation.py` (a small CPU step) to a new `run_<step>.py`. Change the command it runs and which config section it reads.
3. If it needs new software, add an image to `modal_app.py` (copy `bindcraft_image` or `bridge_image`). Remember to end the image with `.add_local_python_source("config_loader", "modal_app")` so the container can import our helpers.
4. Add it to the list in `run_pipeline.py`.

Settings belong in the config, not in the Python files, so a new target or model should only need a YAML edit.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `'charmap' codec can't encode character` | Set `PYTHONUTF8=1` (see setup). |
| `No module named 'config_loader'` in the container | The image is missing `.add_local_python_source("config_loader", "modal_app")` at the end. |
| `$'\r': command not found` while building Optimus's image | Windows line endings; see setup. |
| Optimus results landed in `structure-prediction-outputs` | `OPTIMUS_OUTPUTS_VOLUME` was not set. `run_validation.py` sets it to `inceptive-runs` for you; set it yourself if you call Optimus directly. |
| Design finishes with 0 accepted designs | The filters are strict. Raise `max_trajectories` and re-run with the same `run_name`; it resumes. |
