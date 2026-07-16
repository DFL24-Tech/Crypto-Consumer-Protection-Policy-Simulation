"""Extract the headline numbers from results/ into the server's reference bundle.

Run from anywhere after regenerating results/:

    python server/scripts/build_reference_data.py

Rewrites server/dfl24sim_server/reference_data.json (committed package data),
which get_reference_results serves. Curation — headlines, white-paper section
provenance, the simulation-not-field caveat — lives in dfl24sim_server/reference.py;
this script only copies numbers, so the bundle can never drift from results/ by
transcription error.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
OUT = ROOT / "server" / "dfl24sim_server" / "reference_data.json"


def _read_json(rel: str):
    return json.loads((RESULTS / rel).read_text(encoding="utf-8"))


def _read_csv(rel: str) -> list[dict]:
    with open(RESULTS / rel, newline="") as f:
        return list(csv.DictReader(f))


def _coverage_by_role(rel: str) -> dict:
    return {
        row["role"]: {
            "detected": int(row["detected"]),
            "total": int(row["total"]),
            "rate": float(row["rate"]),
            "ci95": [float(row["lo"]), float(row["hi"])],
        }
        for row in _read_csv(rel)
    }


def build() -> dict:
    calibration = _read_json("calibration.json")
    validation = _read_json("gsa/validation.json")
    convergence = validation["convergence"]
    return {
        "calibration": calibration,
        "sensitivity": {
            "morris": _read_json("gsa/morris.json"),
            "sobol": _read_json("gsa/sobol.json"),
            "sweeps": _read_json("sensitivity/sweeps.json"),
        },
        "coverage": {
            "static": _coverage_by_role("coverage.csv"),
            "adaptive": _coverage_by_role("coverage_adaptive.csv"),
        },
        "fade": {
            "per_step": [
                {
                    "step": int(row["step"]),
                    "control": float(row["control"]),
                    "friction": float(row["friction"]),
                    "reduction": float(row["reduction"]),
                }
                for row in _read_csv("fade.csv")
            ],
            "first_reduction": {
                "target": calibration["targets"]["first_reduction"],
                "achieved": calibration["achieved_moments"]["first_reduction"],
            },
            "fade_ratio": {
                "target": calibration["targets"]["fade_ratio"],
                "achieved": calibration["achieved_moments"]["fade_ratio"],
            },
        },
        "battery": {
            "battery": [
                {
                    "policy": row["policy"],
                    "attack": row["attack"],
                    "coverage": float(row["coverage"]),
                    "retail_burn": float(row["retail_burn"]),
                    "final_trust": float(row["final_trust"]),
                    "precision": float(row["precision"]),
                }
                for row in _read_csv("scenarios/battery.csv")
            ],
        },
        "validation": {
            "stylized_calm": validation["stylized_calm"],
            "stylized_mania": validation["stylized_mania"],
            "convergence": {
                "n_seeds": len(convergence["seeds"]),
                "first_reduction": {
                    "mean": convergence["first_final"],
                    "se": convergence["first_se_final"],
                },
                "coverage": {
                    "mean": convergence["cov_final"],
                    "se": convergence["cov_se_final"],
                },
            },
            "adversary_floor": validation["adversary_floor"],
        },
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
