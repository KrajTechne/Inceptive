# Inceptive: BindCraft2 → Optimus Design/Validation Pipeline on Modal

Status: DRAFT for discussion. Items marked **[DECIDE]** need your input before we build.

## 0. Decisions so far

- Repos are brought in as **git submodules** (`bindcraft2/`, `optimus/`), pinned to commits.
- First end-to-end test: **PD-L1 miniprotein** (BC2 `examples/pdl1.json`).
- Default validation models: **OpenFold3 + ESMFold2** (no AF3 weights needed for now).
- We will **create a new Modal Volume** (proposed name `inceptive-runs`).
- Optimus is called by **shelling out to its CLI** initially (no Optimus changes). Revisit after milestone 1: either `modal deploy` + `Function.from_name`, or a small Python entrypoint in Optimus.

## 0b. Engineering principles (from you)

Code should be clean, scalable, and easy to extend by someone still learning Modal, without a coding assistant. Concretely:
- **One concept per file, short files, plain functions.** No clever abstractions or class hierarchies.
- **Every Modal-specific line is commented** with what it does and why (image, Volume, GPU, timeout).
- **All tunable values live in `configs/`**, never in Python. Adding a target or changing models means editing YAML only.
- **Copy-paste friendly**: adding a new pipeline step = copy an existing `run_*.py`, change the command and the config.
- A `README.md` with a "how to run", "where do results go", and "how to add a step" section, and a Modal cheat-sheet (`modal run`, `modal volume ls/get`, `modal app logs`).
- `--dry-run` prints what would run and the resolved config before spending GPU time.

## 0c. Recon findings (milestone 1)

**BindCraft2** (submodule `bindcraft2/` @ `c0ee638`, v1.0.3)
- `pyproject.toml`: Python >= 3.12, JAX 0.11 (`cuda13` extra, which is the reference stack), `pip install -e ".[cuda13]"`. It is installed **editable** because `settings/` and `scaffolds/` sit at the repo root and are found relative to the source tree. The Modal image must therefore copy the whole submodule and install it editable.
- `containers/Dockerfile` is a working recipe: plain Ubuntu 24.04 + pip + an `ldconfig` step for the CUDA libs + a build-time self-check (`bindcraft --help`, `selfcheck`). We port this to a Modal image rather than inventing our own.
- **AlphaFold params (5.3 GB)** are not in the package. Either bake them into the image (`bindcraft fetch-weights` at build) or cache on a Volume via `BINDCRAFT_WEIGHTS` / `BINDCRAFT_AF2_PARAMS`. Plan: a **weights Volume**, so the image stays small and weights download once.
- Built-in target `hPDL1` (settings/target + bundled structure), so no target PDB is needed for the first test. `examples/pdl1_denovo.json` is the miniprotein example (binder_lengths 60-100, `max_trajectories` 40, `number_of_final_designs` 10).
- No CPU mode, so the design step always needs a GPU. It fans out one worker per visible GPU; a multi-GPU Modal request (`gpu="H100:4"`) should therefore scale it with no code changes.
- Output layout confirmed in code: `1_Trajectories`, `2_Refolded`, `3_Ranked` with `!_Ranked.csv`; accepted designs are written as `.cif`. Binder chain is **B** in BC2 output (per user); pass `--binder_chain B` to `designs_from_structures.py` (default is A). Verify once on the first real output.

**Optimus** (submodule `optimus/` @ `cd79d09`)
- Findings are in the previous discussion: the local CSV input, the fire-and-forget CLI, hardcoded app and Volume names, and unpinned deps.
- Validation CSV from structures: `designs_from_structures.py --input_dir --out_csv --binder_chain` (default `A`).

**Resulting design choices**
- Two Volumes: `inceptive-runs` (inputs/outputs of each run) and `inceptive-weights` (AF2 params cache).
- Our `run_design.py` runs BC2 in an image built from the submodule, writing to `/runs/<run_name>/design` on the Volume.
- The bridge (`select_designs.py`) runs on Modal against the Volume, importing Optimus's `designs_from_structures` logic, and writes `designs.csv` to the Volume. It never touches local disk.
- Optimus validation is launched by `run_validation.py`. The one change needed in Optimus is letting `run_validation` read its CSV from the Volume (milestone 3).

- Submodules are committed as pointers only. After cloning use `git clone --recurse-submodules`. Repo lives in OneDrive, which can corrupt `.git`; move it out if git errors appear.

## 1. Goal

One command takes a target and a design config, runs **BindCraft2 (BC2)** on a Modal GPU to produce ranked binders, then automatically feeds the survivors into **Optimus** for independent multi-model, multi-seed structure validation on Modal. All persistent state lives on a Modal Volume.

```
configs/design.yaml ──► [BC2 design]  ──► Volume: runs/<run>/design/3_Ranked/*.cif + !_Ranked.csv
                                              │
                                   [bridge: select + convert]
                                              │
                                              ▼
configs/validate.yaml ─► [Optimus validation] ─► Volume: runs/<run>/validation/validation_summary.csv
                                              │
                                   [merge: design metrics + validation metrics]
                                              ▼
                                   runs/<run>/final_report.csv
```

## 2. What the two repos give us (from their READMEs)

**BindCraft2** (`PacesaLab/BindCraft2`)
- CLI: `bindcraft design <campaign.json> [--modality ..] [--set key=value]`, plus `bindcraft rank|filter <folder>`. Resumes by default when pointed at the same `project_folder`.
- Install: Linux only, `bash install.sh` creating `.venv` (pyproject-based). GPU is needed (AF2 + ProteinMPNN). Weights/checkpoint setup is not described in the README, so we must check `install.sh`/docs.
- Inputs: target PDB/mmCIF/FASTA, `chains`, `hotspots`, `coldspots`, `binder_lengths`, `number_of_final_designs`, `project_folder`, `modality` (miniprotein, VHH, cyclic peptide, ...).
- Outputs: `1_Trajectories/`, `2_Refolded/`, `3_Ranked/` (`.cif` complexes + `!_Ranked.csv`, sorted by `i_pDAE`), `campaign_metadata.json`.

**Optimus** (`KrajTechne/Optimus`)
- Already Modal-native: `modal_run_validation.py`, `modal_common.py`, `validation_core.py`, per-model runners (AF3, OpenFold3, Boltz2, ESMFold2, OpenDDE).
- Validation input: CSV with `design_name, seq_binder, seq_target` (optional `ligands`, reference interface columns).
- `designs_from_structures.py` builds that CSV from a folder of `.pdb`/`.cif` complexes (binder chain given; other protein chains = target). **This is our natural bridge.**
- Outputs: `validation_results.csv` (per design/model/seed), `validation_summary.csv` (ipTM, ipSAE, pLDDT, contact pass fraction, consistency), `failures.csv`.
- Caveat from its README: the reference interface is usually another model's prediction, and best-of-N biases scores upward. We should keep BC2's own AF2 prediction as the "reference" and be careful about how we read the numbers.

**Integration point:** BC2 `3_Ranked/*.cif` → `designs_from_structures.py` → `designs.csv` → `modal_run_validation.py`.

## 3. Proposed flat repo layout

```
Inceptive/
├── PLAN.md
├── README.md
├── configs/
│   ├── design/
│   │   ├── pdl1_miniprotein.yaml     # one file per campaign
│   │   └── ...
│   ├── validate/
│   │   ├── default.yaml              # models, seeds, thresholds, GPU
│   │   └── ...
│   └── pipeline/
│       └── pdl1_full.yaml            # ties a design cfg + validate cfg + selection rules
├── targets/                          # input PDB/CIF files for targets
├── modal_app.py                      # Modal App, images, Volume, secrets (shared setup)
├── run_design.py                     # Modal function: BC2 design from a design config
├── select_designs.py                 # pick top-N from BC2 output, build Optimus CSV
├── run_validation.py                 # Modal function: calls into Optimus validation
├── run_pipeline.py                   # local entrypoint: design → select → validate → report
├── report.py                         # merge BC2 + Optimus metrics → final_report.csv
├── config_loader.py                  # load/validate YAML, apply CLI overrides
├── tests/
├── vendor/ or submodules             # see decision below
└── pyproject.toml
```

Kept flat: scripts at the top level, `configs/` as the only structured folder (plus `targets/`, `tests/`).

**[DECIDE] How to bring in the two repos.** Options:
1. **Git submodules** (`bindcraft2/`, `optimus/`) pinned to commits, mounted/installed into Modal images. Easy to update, reproducible. *My recommendation.*
2. `pip install git+https://...@<sha>` inside the Modal image, with no copies in our repo. Cleanest tree, but Optimus is script-style (not clearly a package), so imports may be awkward.
3. Copy code into our repo. Simple but drifts from upstream.

## 4. Config design

The configs are the contract. Each step reads one file, and CLI `--set key=value` overrides work like BC2's.

`configs/pipeline/<name>.yaml`
```yaml
run_name: pdl1_v1
design_config: configs/design/pdl1_miniprotein.yaml
validate_config: configs/validate/default.yaml
selection:
  source_metric: i_pDAE        # BC2 ranked column
  top_n: 50
  binder_chain: B              # chain BC2 writes the binder on (verify)
```

`configs/design/*.yaml` is a thin wrapper that we translate to BC2's JSON campaign file (target path, chains, hotspots, binder_lengths, modality, number_of_final_designs, plus a `gpu` and `timeout` block for Modal). Anything BC2-native passes through under a `bindcraft:` key so we don't re-model its whole schema.

`configs/validate/*.yaml` maps to Optimus's CLI flags: `models`, `seeds`, `gpu`, thresholds (`iptm`/`ipsae_min`), and output options.

**[DECIDE]** YAML vs JSON. BC2 uses JSON; Optimus accepts YAML/JSON. I suggest YAML for ours (comments are useful), converted to JSON for BC2 at runtime.

## 5. Modal architecture

- **Two images**: `bc2_image` (BC2 + its venv, AF2 deps) and Optimus's own images (reuse what `modal_common.py` already defines; ESMFold2 and OpenDDE conflict, so Optimus already isolates them).
- **One Volume** (e.g. `inceptive-runs`) holding `targets/`, `runs/<run_name>/{design,validation}/`, plus model weights caches.
- **Secrets** for any weight download tokens (Hugging Face etc.). AF3 weights have licensing terms, so we must confirm that your account/org has the right to use them.
- **Functions**: `design` (GPU, long timeout, retries on preemption; BC2 resumes so retrying is safe), `validate` (delegates to Optimus), `report` (CPU).
- **Scaling**: BC2 is trajectory-parallel. Phase 1 uses one GPU container per campaign. Phase 3 can fan out N containers on the same `project_folder`, if BC2's resume/locking allows it (to check).
- **Cost/safety**: `--dry-run` that prints the resolved configs and planned GPU hours without launching.

## 6. Milestones

1. **Recon (small)**: read BC2 `install.sh`, `pyproject.toml`, `docs/`, `containers/` (may contain a Dockerfile we can reuse), and `examples/pdl1.json`. Read Optimus's `modal_common.py` and `modal_run_validation.py` to see how to call them programmatically instead of through their CLIs. Decide the submodule question.
2. **BC2 on Modal**: image builds, `bindcraft design --list-targets` works, then run the PD-L1 example on a small `number_of_final_designs`. Output is persisted to the Volume.
3. **Optimus standalone from our repo**: run validation on a hand-made CSV via our wrapper, so we know that side works before connecting.
4. **Bridge**: `select_designs.py` reads `!_Ranked.csv`, picks top-N, runs `designs_from_structures.py`, and checks chain assignment and that sequences round-trip correctly (cyclic peptides and VHH may need special handling).
5. **End-to-end**: `run_pipeline.py` with the PD-L1 example, producing `final_report.csv` that joins BC2 (`i_pDAE`, etc.) with Optimus (ipTM, ipSAE, consistency).
6. **Hardening**: resume/retry, dry-run, logging, tests for config loading and selection logic, README.
7. **Later (optional)**: parallel fan-out, multiple targets per run, sweep configs, a web viewer for results.

## 7. Risks and open questions

- **GPU/dependency mismatch**: BC2's install is Linux venv-based and may pin CUDA/JAX versions. Containers dir may help. We'll test on the GPU type we plan to use.
- **Weights**: BC2 weight sourcing isn't in the README, and AF3 weights require Google's terms. OpenFold3 (Apache-2.0) is the simpler default for validation.
- **Chain/ID conventions**: BC2 `.cif` chain labels vs. Optimus's `binder_chain` argument need to be verified on real output.
- **Modality coverage**: do we need all BC2 modalities in validation, or only miniproteins/VHH first? **[DECIDE]**
- **Statistical caution**: validation by a model related to the design model is not independent evidence. We should report it as a filter, not proof of binding.
- **Cost**: H100 for validation is the Optimus default. We may want a cheaper default for exploratory runs.

## 8. Questions for you

1. Submodules vs. pip-from-git for the two repos (section 3)?
2. Which modality and target do you want as the first end-to-end test (PD-L1 miniprotein from BC2's examples is my default)?
3. Which validation models must be in the default (OpenFold3 + Boltz2 + ESMFold2, or AF3 too)?
4. Do you already have a Modal workspace, Volume names, and secrets set up, or should we create them?
5. Anything in Optimus you want changed to make it easier to call from here (e.g. a Python entrypoint rather than only a CLI)?
