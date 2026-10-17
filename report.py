"""Step 3: merge BindCraft2 (design) and Optimus (validation) results into one table.

Usage:
    python report.py --config inputs/configs/pdl1_denovo_test.yaml

Downloads the two result tables from the Volume, joins them on design name, and
writes results/<run_name>/final_report.csv (also uploaded to <run_name>/final_report.csv
on the Volume). Runs on your computer, no GPU needed.
"""
import argparse
import os

import pandas as pd

from config_loader import (final_report_volume_path, load_config, local_results_dir,
                           require_keys, validation_volume_dir)
from volume_utils import volume_get, volume_put

# Columns kept from BindCraft2's !_Ranked.csv
DESIGN_COLUMNS = ["rank", "design", "length", "i_pDAE", "i_pTM", "i_pAE", "pLDDT", "Binder_Sequence"]

# Columns kept from Optimus's validation_summary.csv, renamed to short names.
# Each becomes one column per model, e.g. of3_iptm, esmfold2_iptm.
VALIDATION_COLUMNS = {
    "iptm_mean": "iptm",
    "ipsae_min_mean": "ipsae",
    "binder_plddt_mean": "binder_plddt",
    "contact_pass_fraction": "contact_pass",
    "epitope_recall_mean": "epitope_recall",
}


def merge_results(designs, validation, thresholds):
    """Join design and validation tables. One row per design."""
    # Pass/fail for each design x model row, using the thresholds from the config.
    validation = validation.copy()
    validation["passes"] = (
        (validation["iptm_mean"] >= thresholds["min_iptm"])
        & (validation["ipsae_min_mean"] >= thresholds["min_ipsae"])
        & (validation["contact_pass_fraction"] >= thresholds["min_contact_pass_fraction"])
    )

    # Reshape from one row per design x model to one row per design.
    wide = validation.pivot(index="design_name", columns="model",
                            values=list(VALIDATION_COLUMNS) + ["passes"])
    wide.columns = [f"{model}_{VALIDATION_COLUMNS.get(metric, metric)}" for metric, model in wide.columns]
    pass_columns = [c for c in wide.columns if c.endswith("_passes")]
    wide["passes_validation"] = wide[pass_columns].all(axis=1)
    wide = wide.drop(columns=pass_columns).reset_index()

    merged = designs[DESIGN_COLUMNS].merge(wide, left_on="design", right_on="design_name", how="left")
    merged = merged.drop(columns="design_name")
    # Designs that passed validation first, then BindCraft2's own rank.
    return merged.sort_values(["passes_validation", "rank"], ascending=[False, True])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    require_keys(cfg, ["run_name", "report"], where=args.config)
    require_keys(cfg["report"], ["min_iptm", "min_ipsae", "min_contact_pass_fraction"], where="report section")
    run_name = cfg["run_name"]

    results_dir = local_results_dir(cfg)
    ranked_path = os.path.join(results_dir, "!_Ranked.csv")
    summary_path = os.path.join(results_dir, "validation_summary.csv")
    if not volume_get(f"{run_name}/design/3_Ranked/!_Ranked.csv", ranked_path):
        raise SystemExit("Could not download the design results. Has run_design.py finished?")
    if not volume_get(f"{validation_volume_dir(cfg)}/validation_summary.csv", summary_path):
        raise SystemExit("Could not download the validation results. Has run_validation.py finished?")

    report = merge_results(pd.read_csv(ranked_path), pd.read_csv(summary_path), cfg["report"])

    out_path = os.path.join(results_dir, "final_report.csv")
    report.to_csv(out_path, index=False)
    volume_put(out_path, final_report_volume_path(cfg))

    show = ["rank", "design", "length", "i_pDAE", "passes_validation"] + [
        c for c in report.columns if c.endswith(("_iptm", "_ipsae"))]
    print(report[show].to_string(index=False))
    print(f"\n{int(report['passes_validation'].sum())} of {len(report)} designs passed validation.")
    print(f"Saved {out_path} (and to the Volume at {final_report_volume_path(cfg)})")


if __name__ == "__main__":
    main()
