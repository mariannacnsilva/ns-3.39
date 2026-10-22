#!/usr/bin/env python3
"""Run the one-factor-at-a-time MANET comparison matrix for ns-3."""

import argparse
import csv
import hashlib
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOLS = {
    "aodv": "scratch/experimento-aodv-demo",
    "olsr": "scratch/experimento-olsr-demo",
    "dsdv": "scratch/experimento-dsdv-demo",
}
BASE = {"nodes": 40, "width": 1000.0, "height": 1000.0, "speed": 5.0, "pause": 10.0}
SCENARIOS = [("base", {})]
SCENARIOS += [(f"nodes_{n}", {"nodes": n}) for n in (20, 60)]
SCENARIOS += [(f"area_{side}", {"width": float(side), "height": float(side)}) for side in (500, 1500)]
SCENARIOS += [(f"speed_{speed:g}", {"speed": float(speed)}) for speed in (1, 10, 20)]
SCENARIOS += [(f"pause_{pause}", {"pause": float(pause)}) for pause in (0, 30)]
RADIO_RANGE_M = 200.0


def trajectory_signature(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mean_degree_from_trace(path, radio_range):
    samples = {}
    with path.open(newline="") as source:
        for row in csv.DictReader(source):
            time = float(row["time_s"])
            node = int(row["node_id"])
            samples.setdefault(time, {})[node] = (float(row["x_m"]), float(row["y_m"]))

    degrees = []
    for positions in samples.values():
        ids = sorted(positions)
        degree_sum = 0
        for index, first in enumerate(ids):
            x1, y1 = positions[first]
            for second in ids[index + 1 :]:
                x2, y2 = positions[second]
                if math.hypot(x1 - x2, y1 - y2) <= radio_range:
                    degree_sum += 2
        degrees.append(degree_sum / len(ids))
    return sum(degrees) / len(degrees) if degrees else 0.0


def write_rows(rows, destination):
    if not rows:
        return
    with destination.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="1,2,3,4,5,6,7,8,9,10",
                        help="lista separada por vírgulas (padrão: 1 a 10)")
    parser.add_argument("--limit", type=int, default=0,
                        help="limita o número de execuções para testes rápidos")
    parser.add_argument("--output", default="results/condicoes-rede",
                        help="diretório de saída relativo à raiz do ns-3")
    args = parser.parse_args()

    seeds = [int(value) for value in args.seeds.split(",") if value.strip()]
    output_root = ROOT / args.output
    output_root.mkdir(parents=True, exist_ok=True)

    runs = [(scenario, overrides, seed, protocol, target)
            for scenario, overrides in SCENARIOS
            for seed in seeds
            for protocol, target in PROTOCOLS.items()]
    if args.limit:
        runs = runs[: args.limit]

    subprocess.run(["./ns3", "build"], cwd=ROOT, check=True)

    all_rows = []
    manifest = []
    mobility_hashes = {}
    for index, (scenario, overrides, seed, protocol, target) in enumerate(runs, 1):
        config = BASE | overrides
        scenario_dir = output_root / scenario
        scenario_dir.mkdir(parents=True, exist_ok=True)
        tag = f"{scenario}_seed{seed}_{protocol}"
        summary_path = scenario_dir / f"{tag}.csv"
        flow_path = scenario_dir / f"{tag}_flowmonitor.xml"
        trace_path = scenario_dir / f"{scenario}_seed{seed}_mobility.csv"

        command = [
            "./ns3", "run", "--no-build",
            f"{target} --seed={seed} --nodes={config['nodes']} "
            f"--areaWidth={config['width']} --areaHeight={config['height']} "
            f"--speed={config['speed']} --pause={config['pause']} "
            f"--scenario={scenario} --summary={summary_path} "
            f"--mobilityTrace={trace_path} --flowMonitorFile={flow_path} --animation=false",
        ]
        subprocess.run(command, cwd=ROOT, check=True)

        key = (scenario, seed)
        signature = trajectory_signature(trace_path)
        if key in mobility_hashes and mobility_hashes[key] != signature:
            raise RuntimeError(f"Mobilidade diferente entre protocolos em {scenario}, seed {seed}")
        mobility_hashes[key] = signature

        degree = mean_degree_from_trace(trace_path, RADIO_RANGE_M)
        with summary_path.open(newline="") as source:
            for row in csv.DictReader(source):
                row["mean_neighbor_degree"] = f"{degree:.6f}"
                row["simulation_time_s"] = "180"
                row["wifi_standard"] = "802.11b"
                row["data_control_rate"] = "DsssRate1Mbps"
                row["tx_power_dbm"] = "20"
                row["rx_sensitivity_dbm"] = "-101"
                row["propagation_loss"] = "RangePropagationLossModel (200 m), then LogDistancePropagationLossModel (reference loss 40.05 dB at 1 m, exponent 2)"
                row["propagation_delay"] = "ConstantSpeedPropagationDelayModel"
                row["rts_cts"] = "disabled (threshold 65535 bytes)"
                row["mac"] = "AdhocWifiMac"
                row["ns3_version"] = "3.39"
                all_rows.append(row)

        manifest.append({
            "scenario": scenario, "protocol": protocol, "seed": seed,
            "nodes": config["nodes"], "area_width_m": config["width"],
            "area_height_m": config["height"], "max_speed_mps": config["speed"],
            "pause_s": config["pause"],
            "density_nodes_km2": config["nodes"] * 1e6 / (config["width"] * config["height"]),
            "radio_range_nominal_m": f"{RADIO_RANGE_M:.3f}",
            "mean_neighbor_degree": f"{degree:.6f}",
            "simulation_time_s": 180,
            "wifi_standard": "802.11b", "data_control_rate": "DsssRate1Mbps",
            "tx_power_dbm": 20, "rx_sensitivity_dbm": -101,
            "propagation_loss": "RangePropagationLossModel (200 m), then LogDistancePropagationLossModel (reference loss 40.05 dB at 1 m, exponent 2)",
            "propagation_delay": "ConstantSpeedPropagationDelayModel",
            "rts_cts": "disabled (threshold 65535 bytes)", "mac": "AdhocWifiMac",
            "ns3_version": "3.39", "seed_list": ";".join(map(str, seeds)),
            "mobility_trace": str(trace_path.relative_to(ROOT)),
        })
        print(f"[{index}/{len(runs)}] {tag}: grau médio {degree:.3f}")

    write_rows(all_rows, output_root / "resultados.csv")
    write_rows(manifest, output_root / "manifesto.csv")
    print(f"Concluído: {len(runs)} execuções. Resultados: {output_root / 'resultados.csv'}")


if __name__ == "__main__":
    main()
