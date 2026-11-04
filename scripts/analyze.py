#!/usr/bin/env python3
"""Valida e analisa somente H1 e as quatro métricas do estudo MANET."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "manet-routing"
FLOW_COLUMNS = ["stage", "protocol", "speed", "rate", "run", "seed", "flowId",
                "txPackets", "rxPackets", "lostPackets", "rxBytes", "throughputMbps",
                "pdrPct", "delayMs", "jitterMs", "delaySumMs", "jitterSumMs",
                "maxPackets", "flowIndex", "sourceNode", "destinationNode",
                "packetSizeBytes", "trajectorySha256"]
METRICS = {
    "throughputMbps": ("Vazão (Mbps)", "higher"),
    "pdrPct": ("PDR (%)", "higher"),
    "delayMs": ("Atraso médio (ms)", "lower"),
    "jitterMs": ("Jitter médio (ms)", "lower"),
}


def pdr_pct(received: int, transmitted: int) -> float:
    return 100.0 * received / transmitted if transmitted > 0 else math.nan


def throughput_mbps(received_bytes: int, useful_duration_s: float,
                    bytes_per_megabit: float = 1e6) -> float:
    if useful_duration_s <= 0 or bytes_per_megabit <= 0:
        raise ValueError("A duração útil e os bytes por megabit devem ser positivos.")
    return received_bytes * 8.0 / useful_duration_s / bytes_per_megabit


def delay_ms(delay_sum_ms: float, received: int) -> float:
    return delay_sum_ms / received if received > 0 else math.nan


def jitter_ms(jitter_sum_ms: float, received: int) -> float:
    return jitter_sum_ms / (received - 1) if received > 1 else math.nan


def aggregate_flows(flows: list[dict], useful_duration_s: float,
                    bytes_per_megabit: float = 1e6) -> dict:
    tx = sum(int(flow["txPackets"]) for flow in flows)
    rx = sum(int(flow["rxPackets"]) for flow in flows)
    lost = sum(int(flow["lostPackets"]) for flow in flows)
    rx_bytes = sum(int(flow["rxBytes"]) for flow in flows)
    delay_sum = sum(float(flow["delaySumMs"] or 0) for flow in flows)
    jitter_sum = sum(float(flow["jitterSumMs"] or 0) for flow in flows)
    jitter_samples = sum(max(int(flow["rxPackets"]) - 1, 0) for flow in flows)
    return {
        "txPackets": tx,
        "rxPackets": rx,
        "lostPackets": lost,
        "rxBytes": rx_bytes,
        "throughputMbps": throughput_mbps(rx_bytes, useful_duration_s, bytes_per_megabit),
        "pdrPct": pdr_pct(rx, tx),
        "delayMs": delay_ms(delay_sum, rx),
        "jitterMs": jitter_sum / jitter_samples if jitter_samples else math.nan,
    }


def mean_ci(series: pd.Series, confidence: float) -> tuple[int, float, float, float, float]:
    values = series.dropna().to_numpy(dtype=float)
    n = len(values)
    if n == 0:
        return 0, math.nan, math.nan, math.nan, math.nan
    mean = float(np.mean(values))
    if n < 2:
        return n, mean, math.nan, math.nan, math.nan
    std = float(np.std(values, ddof=1))
    half = float(stats.t.ppf((1 + confidence) / 2, n - 1) * stats.sem(values))
    return n, mean, std, mean - half, mean + half


def validate_analysis_repetitions(repetitions: int) -> None:
    if repetitions < 2:
        raise ValueError("A análise exige pelo menos 2 runs por célula.")


def resolve_profile(config: dict, stage: str) -> dict:
    profile = dict(config["profiles"][stage])
    if "base_profile" in profile:
        base = dict(config["profiles"][profile.pop("base_profile")])
        base.pop("animation", None)
        base.update(profile)
        return base
    return profile


def _read_flows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(FLOW_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Colunas ausentes em {path}: {', '.join(sorted(missing))}")
        return list(reader)


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _close_or_missing(stored: object, calculated: float, label: str) -> None:
    observed = _as_float(stored)
    if math.isnan(calculated):
        if not math.isnan(observed):
            raise ValueError(f"{label}: deveria estar ausente, mas contém {stored}.")
    elif not math.isfinite(observed) or not math.isclose(observed, calculated, rel_tol=1e-7, abs_tol=1e-9):
        raise ValueError(f"{label}: valor registrado diverge do cálculo ({stored} != {calculated}).")


def validate_dataset(root: Path, config: dict, stage: str) -> tuple[pd.DataFrame, dict, list[str]]:
    manifest_path, config_path, flow_path = root / "manifest.json", root / "config.json", root / "flows.csv"
    if not manifest_path.exists() or not config_path.exists() or not flow_path.exists():
        raise ValueError(f"Manifesto, config.json ou flows.csv ausente em {root}.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("stage") != stage:
        raise ValueError(f"Etapa divergente: solicitada {stage}, manifesto contém {manifest.get('stage')}.")
    if manifest.get("mode") in ("animation", "single"):
        raise ValueError("Animações e execuções isoladas não podem ser analisadas como lote.")
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    config_hash = hashlib.sha256(json.dumps(saved_config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if manifest.get("config_sha256") != config_hash or saved_config != config:
        raise ValueError("Configuração da saída difere da configuração atual ou do manifesto.")
    profile = manifest.get("profile")
    if not isinstance(profile, dict) or profile != resolve_profile(config, stage):
        raise ValueError("Perfil congelado no manifesto diverge da configuração.")
    if not math.isclose(profile["traffic_stop_s"] - profile["traffic_start_s"],
                        profile["useful_duration_s"], rel_tol=0, abs_tol=1e-9):
        raise ValueError("Duração útil inconsistente com a janela de tráfego.")

    records = _read_flows(flow_path)
    if not records:
        raise ValueError("flows.csv está vazio.")
    frame = pd.DataFrame(records)
    numeric = ["speed", "rate", "run", "seed", "flowId", "txPackets", "rxPackets", "lostPackets",
               "rxBytes", "maxPackets", "flowIndex", "sourceNode", "destinationNode", "packetSizeBytes"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any():
            raise ValueError(f"Campo numérico inválido ou ausente: {column}.")
    for column in ("delaySumMs", "jitterSumMs"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any() or (frame[column] < 0).any():
            raise ValueError(f"{column} ausente ou negativo.")
    if set(frame["stage"]) != {stage}:
        raise ValueError("flows.csv mistura etapas ou contém etapa ausente.")
    if set(frame["protocol"]) != set(config["experiment"]["protocols"]):
        raise ValueError("flows.csv contém protocolos faltantes ou inesperados.")
    if (frame[["txPackets", "rxPackets", "lostPackets", "rxBytes"]] < 0).any().any():
        raise ValueError("Contagem de pacotes/bytes negativa.")
    if (frame["rxPackets"] > frame["txPackets"]).any() or (frame["lostPackets"] > frame["txPackets"]).any():
        raise ValueError("Contagens impossíveis: rx ou lost maior que tx.")
    if (frame["seed"].astype(int) != int(config["experiment"]["seed_master"])).any():
        raise ValueError("Seed mestre de uma linha diverge da configuração.")
    if (frame["packetSizeBytes"] != int(profile["packet_size_bytes"])).any():
        raise ValueError("Tamanho do payload diverge do perfil.")
    expected_max = np.ceil(frame["rate"] * profile["useful_duration_s"]) + 1
    if (frame["maxPackets"] != expected_max).any():
        raise ValueError("MaxPackets não cobre a taxa durante a janela útil.")

    for raw, row in zip(records, frame.itertuples(index=False)):
        expected = {
            "throughputMbps": throughput_mbps(int(row.rxBytes), profile["useful_duration_s"],
                                               config["metrics"]["bytes_per_megabit"]),
            "pdrPct": pdr_pct(int(row.rxPackets), int(row.txPackets)),
            "delayMs": delay_ms(float(row.delaySumMs), int(row.rxPackets)),
            "jitterMs": jitter_ms(float(row.jitterSumMs), int(row.rxPackets)),
        }
        for metric, value in expected.items():
            _close_or_missing(raw[metric], value, f"{metric}, {row.protocol}/{row.speed}/{row.rate}/run{row.run}")

    expected_reps = int(manifest["expected_repetitions_per_cell"])
    validate_analysis_repetitions(expected_reps)
    if manifest.get("mode") == "official" and expected_reps < int(config["experiment"]["minimum_repetitions"]):
        raise ValueError("Execução oficial abaixo do mínimo de repetições.")
    expected_cells = {(protocol, float(speed), int(rate))
                      for protocol in config["experiment"]["protocols"]
                      for speed in profile["maximum_speeds_mps"] for rate in profile["rate_pps"]}
    actual_cells = set(zip(frame["protocol"], frame["speed"], frame["rate"].astype(int)))
    if actual_cells != expected_cells:
        raise ValueError("Células da matriz ausentes ou inesperadas.")
    key_columns = ["stage", "protocol", "speed", "rate", "run", "flowIndex"]
    if frame.duplicated(key_columns).any():
        raise ValueError("flows.csv contém linhas duplicadas para run/fluxo.")

    expected_flow_count = len(profile["flow_pairs"])
    manifests = sorted((root / "runs").glob("*.manifest.json"))
    if len(manifests) != len(expected_cells) * expected_reps:
        raise ValueError(f"Manifestos incompletos: esperado {len(expected_cells) * expected_reps}, encontrado {len(manifests)}.")
    trajectory_hashes: dict[tuple[float, int], set[str]] = {}
    manifest_keys = set()
    warnings = []
    for path in manifests:
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("stage") != stage or item.get("kind") != "metrics":
            raise ValueError(f"Manifesto de outra etapa/modo: {path}.")
        if item.get("configuration_sha256") != config_hash:
            raise ValueError(f"Hash da configuração divergente em {path}.")
        key = (item["protocol"], float(item["speed"]), int(item["rate"]), int(item["run"]))
        if key in manifest_keys:
            raise ValueError(f"Manifesto duplicado: {key}.")
        manifest_keys.add(key)
        mobility = root / item["files"]["mobility"]
        flow_xml = root / item["files"]["flowmonitor"]
        if not mobility.exists() or hashlib.sha256(mobility.read_bytes()).hexdigest() != item["trajectory_sha256"]:
            raise ValueError(f"Trace de mobilidade ausente ou hash divergente: {mobility}.")
        if not flow_xml.exists():
            raise ValueError(f"XML FlowMonitor ausente: {flow_xml}.")
        selection = frame[(frame["protocol"] == key[0]) & (frame["speed"] == key[1]) &
                          (frame["rate"] == key[2]) & (frame["run"] == key[3])]
        if len(selection) != expected_flow_count or selection["trajectorySha256"].nunique() != 1:
            raise ValueError(f"Fluxos/hashes incompletos no manifesto {key}.")
        if selection["trajectorySha256"].iloc[0] != item["trajectory_sha256"]:
            raise ValueError(f"Hash da trajetória diverge entre CSV e manifesto: {key}.")
        trajectory_hashes.setdefault((key[1], key[3]), set()).add(item["trajectory_sha256"])
    if any(len(values) != 1 for values in trajectory_hashes.values()):
        raise ValueError("Trajetórias diferentes entre protocolos ou cargas para mesma velocidade/run.")

    for cell, group in frame.groupby(["protocol", "speed", "rate"]):
        runs = sorted(group["run"].astype(int).unique())
        if runs != list(range(1, expected_reps + 1)):
            raise ValueError(f"Célula {cell} tem runs faltantes ou inesperados: {runs}.")
        for run, run_rows in group.groupby("run"):
            if len(run_rows) != expected_flow_count:
                raise ValueError(f"Célula {cell}, run {run}: esperado {expected_flow_count} fluxos.")
            observed_pairs = {(int(row.flowIndex), int(row.sourceNode), int(row.destinationNode))
                              for row in run_rows.itertuples()}
            wanted_pairs = {(i, int(pair[0]), int(pair[1])) for i, pair in enumerate(profile["flow_pairs"])}
            if observed_pairs != wanted_pairs:
                raise ValueError(f"Pares origem/destino inesperados na célula {cell}, run {run}.")
    no_receive = int((frame["rxPackets"] == 0).sum())
    if no_receive:
        warnings.append(f"{no_receive} fluxo(s) sem recepção: PDR=0; atraso/jitter ausentes.")
    if frame["jitterMs"].isna().any():
        warnings.append(f"{int(frame['jitterMs'].isna().sum())} fluxo(s) com jitter ausente (menos de 2 recepções).")
    return frame, manifest, warnings


def summarize(results: pd.DataFrame, confidence: float) -> pd.DataFrame:
    rows = []
    for (stage, protocol, speed, rate), group in results.groupby(["stage", "protocol", "speed", "rate"]):
        for metric in METRICS:
            n, mean, std, low, high = mean_ci(group[metric], confidence)
            rows.append({"stage": stage, "protocol": protocol, "speed": speed, "rate": rate,
                         "metric": metric, "n_runs": len(group), "n_valid": n,
                         "mean": mean, "std": std, "ci95_low": low, "ci95_high": high})
    return pd.DataFrame(rows)


def classify_h1(summary: pd.DataFrame, stage: str) -> pd.DataFrame:
    rows = []
    selected = summary[summary["stage"] == stage]
    for (protocol, rate, metric), group in selected.groupby(["protocol", "rate", "metric"]):
        endpoints = {float(row.speed): row for row in group.itertuples()}
        if 1.0 not in endpoints or 20.0 not in endpoints:
            continue
        low_speed, high_speed = endpoints[1.0], endpoints[20.0]
        outcome = "inconclusiva"
        direction = METRICS[metric][1]
        if all(math.isfinite(value) for value in (low_speed.ci95_low, low_speed.ci95_high,
                                                   high_speed.ci95_low, high_speed.ci95_high)):
            if direction == "higher":
                if high_speed.ci95_high < low_speed.ci95_low:
                    outcome = "sustentada"
                elif low_speed.ci95_high < high_speed.ci95_low:
                    outcome = "melhora"
            else:
                if high_speed.ci95_low > low_speed.ci95_high:
                    outcome = "sustentada"
                elif high_speed.ci95_high < low_speed.ci95_low:
                    outcome = "melhora"
        rows.append({"stage": stage, "protocol": protocol, "rate": rate, "metric": metric,
                     "n_1mps": low_speed.n_valid, "mean_1mps": low_speed.mean,
                     "ci95_low_1mps": low_speed.ci95_low, "ci95_high_1mps": low_speed.ci95_high,
                     "n_20mps": high_speed.n_valid, "mean_20mps": high_speed.mean,
                     "ci95_low_20mps": high_speed.ci95_low, "ci95_high_20mps": high_speed.ci95_high,
                     "outcome": outcome})
    return pd.DataFrame(rows)


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, na_rep="")


def write_h1_report(h1: pd.DataFrame, path: Path) -> None:
    lines = ["# Síntese da hipótese H1", "",
             "Critério: comparação dos ICs t de 95% entre 1 e 20 m/s. "
             "Não sobreposição na direção de piora = sustentada; na direção oposta = melhora; "
             "sobreposição ou IC indisponível = inconclusiva.", "",
             "| Protocolo | Carga (pps/fluxo) | Métrica | Desfecho |", "|---|---:|---|---|"]
    for row in h1.itertuples(index=False):
        label = METRICS[row.metric][0]
        lines.append(f"| {row.protocol.upper()} | {row.rate} | {label} | {row.outcome} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_metrics(summary: pd.DataFrame, stage: str, figure_root: Path) -> list[Path]:
    output = []
    for metric, (label, _) in METRICS.items():
        fig, ax = plt.subplots(figsize=(8, 5))
        selected = summary[(summary["stage"] == stage) & (summary["metric"] == metric)]
        for (protocol, rate), series in selected.groupby(["protocol", "rate"]):
            series = series.sort_values("speed")
            valid = np.isfinite(series["mean"].to_numpy(dtype=float))
            series = series.loc[valid]
            if series.empty:
                continue
            lower = np.maximum(0, series["mean"].to_numpy() - series["ci95_low"].to_numpy())
            upper = np.maximum(0, series["ci95_high"].to_numpy() - series["mean"].to_numpy())
            errors = np.vstack([np.nan_to_num(lower), np.nan_to_num(upper)])
            suffix = f", {int(rate)} pps" if selected["rate"].nunique() > 1 else ""
            ax.errorbar(series["speed"], series["mean"], yerr=errors, marker="o", capsize=4,
                        linewidth=1.6, label=f"{protocol.upper()}{suffix}")
        ax.set(xlabel="Velocidade máxima (m/s)", ylabel=label,
               title=f"{label} × velocidade — {stage}")
        ax.grid(True, alpha=0.25)
        ax.legend(title="Protocolo / carga")
        fig.tight_layout()
        path = figure_root / stage / f"{metric}-speed.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=160)
        plt.close(fig)
        output.append(path)
    return output


def write_saturation_check(results: pd.DataFrame, profile: dict, stage: str, mode: str,
                           path: Path) -> None:
    if stage != "stage2" or 100 not in set(results["rate"]):
        return
    flow_count = len(profile["flow_pairs"])
    payload_mbps = flow_count * 100 * int(profile["packet_size_bytes"]) * 8 / 1e6
    ip_udp_mbps = flow_count * 100 * (int(profile["packet_size_bytes"]) + 28) * 8 / 1e6
    lines = ["# Checagem de carga a 100 pacotes/s por fluxo", "",
             f"Carga oferecida: **{payload_mbps:.4f} Mbps de payload**; considerando cabeçalhos IPv4/UDP, "
             f"aproximadamente **{ip_udp_mbps:.4f} Mbps**. O modo PHY configurado é 6 Mbps.",
             "A razão entre carga IP/UDP e taxa PHY é apenas uma referência: não mede airtime e não inclui "
             "preambulos, contenção, retransmissões nem tráfego de roteamento. Saturação não pode ser confirmada "
             "somente por essa razão.", "",
             "Comparação descritiva das médias agregadas entre runs:",
             "", "| Protocolo | PDR médio a 10 pps | PDR médio a 100 pps | Atraso médio a 10 pps (ms) | "
             "Atraso médio a 100 pps (ms) | Velocidades com PDR menor e atraso maior a 100 pps |",
             "|---|---:|---:|---:|---:|---:|"]
    for protocol in sorted(results["protocol"].unique()):
        subset = results[results["protocol"] == protocol]
        at10, at100 = subset[subset["rate"] == 10], subset[subset["rate"] == 100]
        pdr10, pdr100 = at10["pdrPct"].mean(), at100["pdrPct"].mean()
        delay10, delay100 = at10["delayMs"].mean(), at100["delayMs"].mean()
        comparisons = at10.groupby("speed")["pdrPct"].mean().to_frame("pdr10").join(
            at100.groupby("speed")["pdrPct"].mean().rename("pdr100")).join(
            at10.groupby("speed")["delayMs"].mean().rename("delay10")).join(
            at100.groupby("speed")["delayMs"].mean().rename("delay100"))
        signs = int(((comparisons["pdr100"] < comparisons["pdr10"]) &
                     (comparisons["delay100"] > comparisons["delay10"])).sum())
        def fmt(value: float) -> str:
            return f"{value:.3f}" if math.isfinite(value) else "ausente"
        lines.append(f"| {protocol.upper()} | {fmt(pdr10)}% | {fmt(pdr100)}% | {fmt(delay10)} | "
                     f"{fmt(delay100)} | {signs}/{len(comparisons)} |")
    lines += ["", "Interpretação: a contagem final indica em quantas velocidades os dois sinais de degradação "
              "(PDR menor e atraso maior) aparecem juntos. É uma checagem empírica de indícios de contenção, "
              f"não uma medição direta de saturação. Modo da amostra: **{mode}**; resultados de piloto são preliminares."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze(input_root: Path, stage: str, config: dict, output_root: Path | None = None,
            figure_root: Path | None = None) -> tuple[Path, Path, pd.DataFrame]:
    flows, manifest, warnings = validate_dataset(input_root, config, stage)
    profile = manifest["profile"]
    if output_root is None:
        output_root = (EXPERIMENT_DIR / "data" / "processed" / stage
                       if manifest.get("mode") == "official" else input_root / "processed")
    if figure_root is None:
        figure_root = (EXPERIMENT_DIR / "figures" if manifest.get("mode") == "official"
                       else input_root / "figures")
    output_root.mkdir(parents=True, exist_ok=True)
    results = []
    for key, group in flows.groupby(["stage", "protocol", "speed", "rate", "run", "seed"], sort=True):
        row = aggregate_flows(group.to_dict("records"), profile["useful_duration_s"],
                              config["metrics"]["bytes_per_megabit"])
        row.update(dict(zip(["stage", "protocol", "speed", "rate", "run", "seed"], key)))
        row["flowCount"] = len(group)
        row["trajectoryHash"] = group["trajectorySha256"].iloc[0]
        results.append(row)
    results_frame = pd.DataFrame(results)
    summary = summarize(results_frame, config["experiment"]["confidence_level"])
    h1 = classify_h1(summary, stage)
    save_csv(flows, output_root / "flows.csv")
    save_csv(results_frame, output_root / "results.csv")
    save_csv(summary, output_root / "summary.csv")
    save_csv(h1, output_root / "h1-results.csv")
    write_h1_report(h1, output_root / "h1-summary.md")
    figures = plot_metrics(summary, stage, figure_root)
    write_saturation_check(results_frame, profile, stage, manifest.get("mode", "unknown"),
                           output_root / "saturation-check.md")
    print(f"Análise {stage}: {len(results_frame)} execuções; {len(flows)} fluxos; saídas {output_root}")
    for warning in warnings:
        print(f"Aviso: {warning}", file=sys.stderr)
    for path in figures:
        print(f"Figura: {path}")
    print(f"Síntese H1: {output_root / 'h1-summary.md'}")
    if stage == "stage2":
        print(f"Checagem de carga/saturação: {output_root / 'saturation-check.md'}")
    return output_root, figure_root, results_frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("stage1", "stage2"), default="stage1")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "experiment.json")
    parser.add_argument("--input", type=Path, help="Diretório raw da etapa ou do piloto")
    parser.add_argument("--output", type=Path, help="Destino CSV processado")
    parser.add_argument("--figures", type=Path, help="Destino dos PNGs")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    input_root = args.input or (EXPERIMENT_DIR / "data" / "raw" / args.stage)
    analyze(input_root.resolve(), args.stage, config,
            args.output.resolve() if args.output else None,
            args.figures.resolve() if args.figures else None)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        raise SystemExit(2)
