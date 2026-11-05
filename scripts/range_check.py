#!/usr/bin/env python3
"""Confirma no simulador o alcance previsto para o canal de config/experiment.json."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analyze import effective_range_m, resolve_profile  # noqa: E402

OUTPUT = ROOT / "results" / "range-check" / "range-check.csv"


def main() -> int:
    config = json.loads((ROOT / "config" / "experiment.json").read_text(encoding="utf-8"))
    profile = resolve_profile(config, "stage1")
    predicted = effective_range_m(profile)
    distances = [50, 100, 150, 160, 165, 168, 169, 170, 171, 175, 180, 200, 250]
    rows = []
    for distance in distances:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "ns3"), "run", "--no-build", "scratch/range-check", "--",
             f"--distance={distance}", f"--tx-power={profile['tx_power_dbm']}",
             f"--rx-sensitivity={profile['rx_sensitivity_dbm']}",
             f"--preamble-min-rssi={profile['preamble_minimum_rssi_dbm']}",
             f"--reference-loss={profile['reference_loss_db']}",
             f"--reference-distance={profile['reference_distance_m']}",
             f"--path-loss-exponent={profile['log_distance_exponent']}",
             f"--packet-size={profile['packet_size_bytes']}"],
            cwd=ROOT, text=True, capture_output=True, check=True)
        measured, sent, received = completed.stdout.strip().splitlines()[-1].split(",")
        rows.append({"distanceM": measured, "sent": sent, "received": received,
                     "deliveryPct": 100.0 * int(received) / int(sent), "predictedRangeM": round(predicted, 1)})
        print(f"{measured:>5} m: {received}/{sent}", flush=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Alcance previsto: {predicted:.1f} m. Tabela: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
