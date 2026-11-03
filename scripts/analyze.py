#!/usr/bin/env python3
"""Valida e analisa uma etapa isolada do estudo MANET."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

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
                "pdrPct", "delayMs", "jitterMs", "p95Ms", "delaySumMs", "jitterSumMs",
                "controlPackets", "controlBytes", "maxPackets", "flowIndex", "packetSizeBytes",
                "sourceNode", "destinationNode", "meanGeometricDegree", "trajectorySha256"]


def pdr_pct(received: int, transmitted: int) -> float:
    if transmitted <= 0:
        raise ValueError("PDR indefinido: txPackets deve ser maior que zero")
    return 100.0 * received / transmitted


def throughput_mbps(received_bytes: int, useful_duration_s: float,
                    bytes_per_megabit: float = 1e6) -> float:
    if useful_duration_s <= 0:
        raise ValueError("A duração útil deve ser positiva")
    return received_bytes * 8.0 / useful_duration_s / bytes_per_megabit


def delay_ms(delay_sum_ms: float, received: int) -> float:
    return delay_sum_ms / received if received > 0 else math.nan


def jitter_ms(jitter_sum_ms: float, received: int) -> float:
    return jitter_sum_ms / (received - 1) if received > 1 else math.nan


def percentile_from_xml(flow: ET.Element, quantile: float) -> float:
    histogram = flow.find("delayHistogram")
    if histogram is None or not 0 < quantile < 1:
        return math.nan
    bins = sorted(histogram.findall("bin"), key=lambda item: int(item.get("index", "0")))
    total = sum(int(item.get("count", "0")) for item in bins)
    if total == 0:
        return math.nan
    target = math.ceil(total * quantile)
    cumulative = 0
    for item in bins:
        cumulative += int(item.get("count", "0"))
        if cumulative >= target:
            return (float(item.get("start", "0")) + float(item.get("width", "0")) / 2) * 1000
    return math.nan


def validate_analysis_repetitions(repetitions: int, mode: str,
                                  official_minimum: int) -> None:
    if repetitions < 2:
        raise ValueError("A análise exige pelo menos 2 runs por célula; este piloto tem apenas 1.")
    if mode == "official" and repetitions < official_minimum:
        raise ValueError(f"Execução oficial abaixo do mínimo de repetições ({official_minimum}).")


def aggregate_flows(flows: list[dict], useful_duration_s: float,
                    bytes_per_megabit: float = 1e6) -> dict:
    tx = sum(int(flow["txPackets"]) for flow in flows)
    rx = sum(int(flow["rxPackets"]) for flow in flows)
    lost = sum(int(flow["lostPackets"]) for flow in flows)
    rx_bytes = sum(int(flow["rxBytes"]) for flow in flows)
    delay_sum = sum(float(flow.get("delaySumMs", 0) or 0) for flow in flows)
    jitter_sum = sum(float(flow.get("jitterSumMs", 0) or 0) for flow in flows)
    jitter_pairs = sum(max(int(flow["rxPackets"]) - 1, 0) for flow in flows)
    p95_values = [(float(flow["p95Ms"]), int(flow["rxPackets"])) for flow in flows
                  if _number(flow.get("p95Ms")) and int(flow["rxPackets"]) > 0]
    p95 = (sum(value * count for value, count in p95_values) / sum(count for _, count in p95_values)
           if p95_values else math.nan)
    payload_size = int(float(flows[0]["packetSizeBytes"])) if flows else 0
    control_bytes = int(float(flows[0].get("controlBytes", 0) or 0)) if flows else 0
    return {"txPackets": tx, "rxPackets": rx, "lostPackets": lost, "rxBytes": rx_bytes,
            "throughputMbps": throughput_mbps(rx_bytes, useful_duration_s, bytes_per_megabit),
            "pdrPct": pdr_pct(rx, tx), "delayMs": delay_ms(delay_sum, rx),
            "jitterMs": jitter_sum / jitter_pairs if jitter_pairs else math.nan,
            "p95Ms": p95,
            "controlPackets": int(float(flows[0].get("controlPackets", 0) or 0)) if flows else 0,
            "controlBytes": control_bytes,
            "controlBytesPerPayloadByte": control_bytes / (rx * payload_size) if rx else math.nan,
            "meanGeometricDegree": float(flows[0].get("meanGeometricDegree", math.nan)) if flows else math.nan,
            "maxPackets": int(float(flows[0].get("maxPackets", 0) or 0)) if flows else 0}


def _number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _read_flow_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        missing = set(FLOW_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Colunas ausentes em {path}: {', '.join(sorted(missing))}")
        return list(reader)


def parse_flowmonitor(path: Path) -> ET.Element:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as source:
            return ET.parse(source).getroot()
    return ET.parse(path).getroot()


def validate_dataset(root: Path, config: dict, stage: str) -> tuple[pd.DataFrame, dict, list[str]]:
    manifest_path, config_path = root / "manifest.json", root / "config.json"
    if not manifest_path.exists() or not config_path.exists():
        raise ValueError(f"Manifesto/config.json ausente em {root}; diretório de piloto ou etapa incompleta?")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("stage") != stage:
        raise ValueError(f"Mistura de etapas: solicitado {stage}, manifesto contém {manifest.get('stage')}.")
    if manifest.get("mode") in ("animation", "single"):
        raise ValueError("Animações e cenários isolados não são entradas do analisador estatístico.")
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    config_hash = hashlib.sha256(json.dumps(saved_config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if manifest.get("config_sha256") != config_hash:
        raise ValueError("O hash da configuração no manifesto não confere com config.json.")
    if saved_config != config:
        raise ValueError("A configuração da saída difere da configuração atual; não misture estudos.")
    profile = manifest.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("Perfil de execução ausente no manifesto.")
    if not math.isclose(profile["traffic_stop_s"] - profile["traffic_start_s"],
                        profile["useful_duration_s"], rel_tol=0, abs_tol=1e-9):
        raise ValueError("Duração útil inconsistente com os limites de início/fim do tráfego.")
    if profile != _resolve_profile(config, stage):
        raise ValueError("Perfil congelado no manifesto diverge do perfil da configuração.")
    flow_file = root / "flows.csv"
    if not flow_file.exists():
        raise ValueError(f"flows.csv não encontrado em {root}; execute/conclua o runner primeiro.")
    rows = _read_flow_csv(flow_file)
    if not rows:
        raise ValueError("flows.csv não contém fluxos para analisar.")
    frame = pd.DataFrame(rows)
    frame["run"] = pd.to_numeric(frame["run"], errors="coerce")
    frame["seed"] = pd.to_numeric(frame["seed"], errors="coerce")
    frame["speed"] = pd.to_numeric(frame["speed"], errors="coerce")
    frame["rate"] = pd.to_numeric(frame["rate"], errors="coerce")
    for column in ("flowId", "txPackets", "rxPackets", "lostPackets", "rxBytes", "flowIndex",
                   "sourceNode", "destinationNode", "packetSizeBytes", "maxPackets"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if set(frame["stage"].dropna()) != {stage}:
        raise ValueError("flows.csv contém etapas diferentes ou dados sem etapa identificada.")
    if set(frame["protocol"].dropna()) != set(config["experiment"]["protocols"]):
        raise ValueError("flows.csv contém protocolos faltantes ou inesperados.")
    for column in ("txPackets", "rxPackets", "lostPackets", "rxBytes"):
        if (frame[column] < 0).any():
            raise ValueError(f"Dados impossíveis: {column} negativo.")
    if frame["run"].isna().any() or frame["seed"].isna().any() or frame["speed"].isna().any() or frame["rate"].isna().any():
        raise ValueError("Há campos de run/seed/velocidade/taxa inválidos.")
    if (frame["rxPackets"] > frame["txPackets"]).any():
        raise ValueError("Dados impossíveis: rxPackets maior que txPackets.")
    if (frame["lostPackets"] > frame["txPackets"]).any():
        raise ValueError("Dados impossíveis: lostPackets maior que txPackets.")
    if (frame["txPackets"] <= 0).any():
        raise ValueError("Divisão por zero: há fluxo sem pacotes transmitidos.")
    stored_pdr = pd.to_numeric(frame["pdrPct"], errors="coerce")
    recomputed_pdr = 100.0 * frame["rxPackets"] / frame["txPackets"]
    if ((recomputed_pdr < 0) | (recomputed_pdr > 100)).any():
        raise ValueError("Dados impossíveis: PDR fora do intervalo 0–100%.")
    if not np.allclose(stored_pdr, recomputed_pdr, rtol=1e-8, atol=1e-10):
        raise ValueError("pdrPct registrado diverge de rxPackets / txPackets × 100.")
    frame["pdrPct"] = recomputed_pdr
    stored_throughput = pd.to_numeric(frame["throughputMbps"], errors="coerce")
    frame["throughputMbps"] = frame["rxBytes"] * 8.0 / profile["useful_duration_s"] / config["metrics"]["bytes_per_megabit"]
    if not np.allclose(stored_throughput, frame["throughputMbps"], rtol=1e-8, atol=1e-12):
        raise ValueError("throughputMbps registrado diverge de rxBytes × 8 / duração útil / 10^6.")
    frame["delayMs"] = pd.to_numeric(frame["delayMs"], errors="coerce")
    frame["jitterMs"] = pd.to_numeric(frame["jitterMs"], errors="coerce")
    frame["p95Ms"] = pd.to_numeric(frame["p95Ms"], errors="coerce")
    frame["delaySumMs"] = pd.to_numeric(frame["delaySumMs"], errors="coerce")
    frame["jitterSumMs"] = pd.to_numeric(frame["jitterSumMs"], errors="coerce")
    if frame[["delaySumMs", "jitterSumMs"]].isna().any().any() or (frame[["delaySumMs", "jitterSumMs"]] < 0).any().any():
        raise ValueError("delaySumMs/jitterSumMs ausente ou negativo.")
    stored_delay, stored_jitter = frame["delayMs"].copy(), frame["jitterMs"].copy()
    frame["delayMs"] = np.where(frame["rxPackets"] > 0,
                                 frame["delaySumMs"] / frame["rxPackets"], np.nan)
    frame["jitterMs"] = np.where(frame["rxPackets"] > 1,
                                  frame["jitterSumMs"] / (frame["rxPackets"] - 1), np.nan)
    if not np.allclose(stored_delay.fillna(0), frame["delayMs"].fillna(0), rtol=1e-6, atol=1e-8):
        raise ValueError("delayMs registrado diverge de delaySum / rxPackets.")
    if not np.allclose(stored_jitter.fillna(0), frame["jitterMs"].fillna(0), rtol=1e-6, atol=1e-8):
        raise ValueError("jitterMs registrado diverge de jitterSum / (rxPackets - 1).")
    frame.loc[frame["rxPackets"] == 0, ["delayMs", "p95Ms"]] = np.nan
    frame.loc[frame["rxPackets"] <= 1, "jitterMs"] = np.nan
    if (frame["delayMs"].dropna() < 0).any() or (frame["jitterMs"].dropna() < 0).any():
        raise ValueError("Dados impossíveis: atraso ou jitter negativo.")
    if (frame["p95Ms"].dropna() < 0).any():
        raise ValueError("Dados impossíveis: p95 de atraso negativo.")
    if (frame["seed"].astype(int) != int(config["experiment"]["seed_master"])).any():
        raise ValueError("Seed mestre de uma linha diverge da configuração.")
    expected_max_packets = np.ceil(frame["rate"] * profile["useful_duration_s"]) + 1
    if (frame["maxPackets"] != expected_max_packets).any():
        raise ValueError("MaxPackets não cobre a taxa configurada durante a janela útil.")
    if (frame["packetSizeBytes"] != profile["packet_size_bytes"]).any():
        raise ValueError("Tamanho do payload no CSV diverge do perfil.")

    expected_reps = int(manifest["expected_repetitions_per_cell"])
    validate_analysis_repetitions(expected_reps, manifest.get("mode", ""),
                                  config["experiment"]["minimum_repetitions"])
    if manifest.get("mode") == "official" and expected_reps < config["experiment"]["minimum_repetitions"]:
        raise ValueError("Execução oficial abaixo do mínimo de repetições configurado.")
    expected_cells = {(protocol, float(speed), int(rate))
                      for protocol in config["experiment"]["protocols"]
                      for speed in profile["maximum_speeds_mps"] for rate in profile["rate_pps"]}
    actual_cells = set(zip(frame["protocol"], frame["speed"], frame["rate"]))
    if actual_cells != expected_cells:
        raise ValueError(f"Células da matriz divergentes: faltantes={expected_cells - actual_cells}, extras={actual_cells - expected_cells}.")
    run_key = ["stage", "protocol", "speed", "rate", "run", "flowIndex"]
    if frame.duplicated(run_key).any():
        raise ValueError("flows.csv contém uma linha duplicada para run/fluxo.")
    warnings = []
    expected_flow_count = len(profile["flow_pairs"])
    run_manifests = sorted((root / "runs").glob("*.manifest.json"))
    expected_manifest_count = len(expected_cells) * expected_reps
    if len(run_manifests) != expected_manifest_count:
        raise ValueError(f"Manifestos incompletos: esperado {expected_manifest_count}, encontrado {len(run_manifests)}.")
    trajectory_hashes: dict[tuple[float, int], set[str]] = {}
    manifest_keys = set()
    xml_ids: dict[tuple[str, float, int, int], set[int]] = {}
    for run_manifest_path in run_manifests:
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        if run_manifest.get("stage") != stage or run_manifest.get("kind") != "metrics":
            raise ValueError(f"Manifesto de outra etapa/modo: {run_manifest_path}")
        if run_manifest.get("configuration_sha256") != config_hash:
            raise ValueError(f"Configuração diferente no manifesto {run_manifest_path}")
        key = (run_manifest["protocol"], float(run_manifest["speed"]),
               int(run_manifest["rate"]), int(run_manifest["run"]))
        if key in manifest_keys:
            raise ValueError(f"Manifesto duplicado: {key}")
        manifest_keys.add(key)
        mobility = root / run_manifest["files"]["mobility"]
        flow_xml = root / run_manifest["files"]["flowmonitor"]
        if not mobility.exists() or hashlib.sha256(mobility.read_bytes()).hexdigest() != run_manifest["trajectory_sha256"]:
            raise ValueError(f"Trace de mobilidade ausente ou hash divergente: {mobility}")
        if not flow_xml.exists():
            raise ValueError(f"XML FlowMonitor ausente: {flow_xml}")
        xml_root = parse_flowmonitor(flow_xml)
        if xml_root.tag != "FlowMonitor":
            raise ValueError(f"XML FlowMonitor inválido: {flow_xml}")
        flow_ids = {int(item.get("flowId")) for item in xml_root.findall("FlowStats/Flow")}
        flow_rows = frame[(frame["protocol"] == key[0]) & (frame["speed"] == key[1]) &
                          (frame["rate"] == key[2]) & (frame["run"] == key[3])]
        csv_ids = set(flow_rows["flowId"].astype(int))
        if not csv_ids.issubset(flow_ids):
            raise ValueError(f"FlowMonitor XML não contém todos os flowId do CSV: {flow_xml}")
        xml_ids[key] = flow_ids
        if flow_rows["trajectorySha256"].nunique() != 1 or flow_rows["trajectorySha256"].iloc[0] != run_manifest["trajectory_sha256"]:
            raise ValueError(f"Hash da trajetória diverge no CSV/manifesto: {key}")
        trajectory_hashes.setdefault((key[1], key[3]), set()).add(run_manifest["trajectory_sha256"])
    if any(len(values) != 1 for values in trajectory_hashes.values()):
        raise ValueError("Trajetórias diferentes para a mesma velocidade/run entre protocolos ou cargas.")
    for cell, group in frame.groupby(["protocol", "speed", "rate"]):
        runs = sorted(group["run"].astype(int).unique())
        if len(runs) != expected_reps or runs != list(range(1, expected_reps + 1)):
            raise ValueError(f"Número de runs incorreto para célula {cell}: esperados {expected_reps}, encontrados {runs}.")
        for run_id, run_rows in group.groupby("run"):
            if len(run_rows) != expected_flow_count:
                raise ValueError(f"Run {run_id} da célula {cell} tem {len(run_rows)} fluxos; esperado {expected_flow_count}.")
            if set(run_rows["flowIndex"].astype(int)) != set(range(expected_flow_count)):
                raise ValueError(f"IDs/índices de fluxo incompletos no run {run_id} da célula {cell}.")
            observed_pairs = {(int(row.flowIndex), int(row.sourceNode), int(row.destinationNode))
                              for row in run_rows.itertuples()}
            expected_pairs = {(index, int(pair[0]), int(pair[1]))
                              for index, pair in enumerate(profile["flow_pairs"])}
            if observed_pairs != expected_pairs:
                raise ValueError(f"Pares origem-destino divergentes no run {run_id} da célula {cell}.")
    no_receive = int((frame["rxPackets"] == 0).sum())
    if no_receive:
        warnings.append(f"{no_receive} fluxo(s) sem recepção: PDR=0 quando transmitidos; atraso/jitter ficam ausentes.")
    if frame["jitterMs"].isna().any():
        warnings.append(f"{int(frame['jitterMs'].isna().sum())} fluxo(s) com jitter ausente (menos de 2 pacotes recebidos).")
    return frame, manifest, warnings


def _resolve_profile(config: dict, stage: str) -> dict:
    profile = dict(config["profiles"][stage])
    if "base_profile" in profile:
        base = dict(config["profiles"][profile.pop("base_profile")])
        base.pop("animation", None)
        base.update(profile)
        return base
    return profile


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


def holm_adjust(p_values: list[float]) -> list[float]:
    order = np.argsort(p_values)
    adjusted = [1.0] * len(p_values)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(p_values) - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


def build_run_results(frame: pd.DataFrame, profile: dict, config: dict) -> pd.DataFrame:
    results = []
    for key, group in frame.groupby(["stage", "protocol", "speed", "rate", "run", "seed"], sort=True):
        records = group.to_dict("records")
        aggregate = aggregate_flows(records, profile["useful_duration_s"],
                        config["metrics"]["bytes_per_megabit"])
        aggregate["stage"], aggregate["protocol"], aggregate["speed"], aggregate["rate"], aggregate["run"], aggregate["seed"] = key
        aggregate["flowCount"] = len(group)
        aggregate["trajectoryHash"] = str(group["trajectorySha256"].iloc[0])
        aggregate["controlPacketsPerDeliveredPacket"] = aggregate["controlPackets"] / aggregate["rxPackets"] if aggregate["rxPackets"] else math.nan
        results.append(aggregate)
    return pd.DataFrame(results)


def summarize(results: pd.DataFrame, confidence: float) -> pd.DataFrame:
    metrics = ["txPackets", "rxPackets", "lostPackets", "rxBytes", "throughputMbps",
               "pdrPct", "delayMs", "jitterMs", "p95Ms", "controlPackets", "controlBytes",
               "controlBytesPerPayloadByte", "meanGeometricDegree"]
    rows = []
    for (stage, protocol, speed, rate), group in results.groupby(["stage", "protocol", "speed", "rate"]):
        for metric in metrics:
            n, mean, std, lower, upper = mean_ci(group[metric], confidence)
            rows.append({"stage": stage, "protocol": protocol, "speed": speed, "rate": rate,
                         "metric": metric, "n_runs": len(group), "n_valid": n,
                         "mean": mean, "std": std, "ci95_low": lower, "ci95_high": upper})
    return pd.DataFrame(rows)


def paired_comparisons(results: pd.DataFrame, config: dict, threshold: int) -> pd.DataFrame:
    rows = []
    metric_names = ["pdrPct", "throughputMbps", "delayMs", "jitterMs", "p95Ms",
                    "controlPackets", "controlBytes", "controlBytesPerPayloadByte"]
    protocols = config["experiment"]["protocols"]
    for (stage, speed, rate), group in results.groupby(["stage", "speed", "rate"]):
        for metric in metric_names:
            for i, left in enumerate(protocols):
                for right in protocols[i + 1:]:
                    paired = group[group["protocol"].isin((left, right))].pivot(
                        index="run", columns="protocol", values=metric).dropna(subset=[left, right])
                    n = len(paired)
                    pvalue = math.nan
                    if n >= threshold:
                        differences = paired[left].to_numpy() - paired[right].to_numpy()
                        if np.allclose(differences, 0):
                            pvalue = 1.0
                        else:
                            pvalue = float(stats.ttest_rel(paired[left], paired[right]).pvalue)
                    rows.append({"stage": stage, "speed": speed, "rate": rate, "metric": metric,
                                 "protocolA": left, "protocolB": right, "n_paired": n,
                                 "test": "paired-t" if n >= threshold else "IC-only-small-n",
                                 "p_value": pvalue, "p_holm": math.nan})
    frame = pd.DataFrame(rows)
    for _, indices in frame[frame["p_value"].notna()].groupby(["stage", "speed", "rate", "metric"]).groups.items():
        frame.loc[indices, "p_holm"] = holm_adjust(frame.loc[indices, "p_value"].tolist())
    frame["p_holm_hypothesis"] = math.nan
    hypothesis_families = {
        "H2": ["pdrPct", "throughputMbps", "delayMs"],
        "H3": ["controlPackets", "controlBytes", "controlBytesPerPayloadByte"],
    }
    for metric_names in hypothesis_families.values():
        selected = frame["metric"].isin(metric_names) & frame["p_value"].notna()
        if selected.any():
            frame.loc[selected, "p_holm_hypothesis"] = holm_adjust(frame.loc[selected, "p_value"].tolist())
    return frame


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, na_rep="")


def plot_metric(summary: pd.DataFrame, metric: str, ylabel: str, stage: str,
                figure_root: Path, confidence: float, rates: list[int],
                minimum_pdr_pct: float) -> list[Path]:
    outputs = []
    rate_groups = rates if len(rates) > 1 else [None]
    for rate in rate_groups:
        fig, ax = plt.subplots(figsize=(8, 5))
        selected = summary[(summary["stage"] == stage) & (summary["metric"] == metric)]
        if rate is not None:
            selected = selected[selected["rate"] == rate]
        for protocol, values in selected.groupby("protocol"):
            values = values.sort_values("speed")
            n = values["n_valid"].to_numpy(dtype=int)
            errors = np.array([(row["ci95_high"] - row["mean"] if pd.notna(row["ci95_high"]) else np.nan)
                               for _, row in values.iterrows()])
            ax.errorbar(values["speed"], values["mean"], yerr=errors, marker="o", capsize=4,
                        linewidth=1.8, label=protocol.upper())
        if metric == "pdrPct":
            ax.axhline(minimum_pdr_pct, color="gray", linestyle="--",
                       label=f"limiar prévio {minimum_pdr_pct:g}%")
        xlabel = "Velocidade máxima (m/s)"
        title = f"{metric} × velocidade — {stage}"
        filename = f"{metric}-speed.png"
        if rate is not None:
            title += f" — {rate} pacotes/s por fluxo"
            filename = f"{metric}-rate-{rate}pps.png"
        ax.set(xlabel=xlabel, ylabel=ylabel, title=title)
        ax.grid(True, alpha=0.25)
        ax.legend(title="Protocolo")
        fig.tight_layout()
        path = figure_root / stage / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=160)
        plt.close(fig)
        outputs.append(path)
    return outputs


def plot_overhead_pdr(results: pd.DataFrame, stage: str, figure_root: Path,
                     rates: list[int]) -> list[Path]:
    outputs = []
    plotted_rates = rates if len(rates) > 1 else [None]
    for rate in plotted_rates:
        selected = results[results["stage"] == stage]
        if rate is not None:
            selected = selected[selected["rate"] == rate]
        fig, ax = plt.subplots(figsize=(8, 5))
        for protocol, values in selected.groupby("protocol"):
            ax.scatter(values["pdrPct"], values["controlBytesPerPayloadByte"],
                       label=protocol.upper(), alpha=0.75)
        filename = "overhead-pdr.png" if rate is None else f"overhead-pdr-rate-{rate}pps.png"
        title = f"Overhead de controle × PDR — {stage}"
        if rate is not None:
            title += f" — {rate} pacotes/s por fluxo"
        ax.set(xlabel="PDR (%)", ylabel="Bytes de controle / byte de payload", title=title)
        ax.grid(True, alpha=0.25)
        ax.legend(title="Protocolo")
        fig.tight_layout()
        path = figure_root / stage / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=160)
        plt.close(fig)
        outputs.append(path)
    return outputs


def print_synthesis(summary: pd.DataFrame, stage: str, protocols: list[str], rates: list[int]) -> None:
    print(f"\nSíntese descritiva — {stage} (limitada às condições simuladas):")
    labels = {"pdrPct": "PDR (%)", "throughputMbps": "Throughput (Mbps)",
              "delayMs": "Atraso (ms)", "jitterMs": "Jitter (ms)"}
    for rate in rates:
        print(f"Carga: {rate} pacotes/s por fluxo")
        for metric, label in labels.items():
            selected = summary[(summary["stage"] == stage) & (summary["rate"] == rate) &
                               (summary["metric"] == metric)]
            descriptions = []
            for protocol in protocols:
                values = selected[selected["protocol"] == protocol].sort_values("speed")
                if values.empty:
                    continue
                means = values["mean"].to_numpy(dtype=float)
                valid = np.isfinite(means)
                trend = "sem valores válidos"
                if valid.sum() >= 2:
                    slope = float(np.polyfit(values.loc[valid, "speed"], means[valid], 1)[0])
                    trend = "tendência crescente" if slope > 0 else ("tendência decrescente" if slope < 0 else "sem tendência linear")
                degradation_index = int(np.nanargmax(means) if metric in ("delayMs", "jitterMs") else np.nanargmin(means)) if valid.any() else -1
                degradation = f"maior degradação observada em {values.iloc[degradation_index]['speed']:g} m/s" if degradation_index >= 0 else "ponto de degradação não identificável"
                valid_ns = values.loc[valid, "n_valid"].astype(int).tolist()
                n_text = f"n válido={min(valid_ns)}–{max(valid_ns)}" if valid_ns else "n válido=0"
                descriptions.append(f"{protocol.upper()}: {trend}; {degradation}; {n_text}")
            overlaps = []
            for i, left in enumerate(protocols):
                for right in protocols[i + 1:]:
                    a = selected[selected["protocol"] == left].set_index("speed")
                    b = selected[selected["protocol"] == right].set_index("speed")
                    shared = sorted(set(a.index) & set(b.index))
                    overlap_speeds = [speed for speed in shared
                        if pd.notna(a.loc[speed, "ci95_low"]) and pd.notna(b.loc[speed, "ci95_low"])
                        and a.loc[speed, "ci95_low"] <= b.loc[speed, "ci95_high"]
                        and b.loc[speed, "ci95_low"] <= a.loc[speed, "ci95_high"]]
                    overlaps.append(f"{left.upper()}/{right.upper()}: ICs sobrepostos em {len(overlap_speeds)}/{len(shared)} velocidades")
            print(f"- {label}: " + "; ".join(descriptions) + ". " + "; ".join(overlaps) + ".")
    print("Síntese descritiva não substitui inferência: diferenças são inconclusivas quando ICs se sobrepõem ou n válido é pequeno.")


def print_hypothesis_summary(results: pd.DataFrame, paired: pd.DataFrame, config: dict) -> None:
    alpha = config["experiment"]["significance_level"]
    threshold = config["experiment"]["large_n_threshold"]
    protocols = config["experiment"]["protocols"]
    h1_rows = []
    for (stage, protocol, rate), group in results.groupby(["stage", "protocol", "rate"]):
        speeds = sorted(group["speed"].unique())
        if len(speeds) < 2:
            continue
        low = group[group["speed"] == speeds[0]].set_index("run")
        high = group[group["speed"] == speeds[-1]].set_index("run")
        joined = low.join(high, lsuffix="_low", rsuffix="_high", how="inner")
        for metric in ("delayMs", "pdrPct"):
            delta_series = (joined[f"{metric}_high"] - joined[f"{metric}_low"]).dropna()
            delta = delta_series.to_numpy(dtype=float)
            n = len(delta_series)
            if n < 2:
                continue
            mean = float(np.mean(delta))
            half = float(stats.t.ppf((1 + config["experiment"]["confidence_level"]) / 2,
                                     n - 1) * stats.sem(delta))
            pvalue = (float(stats.ttest_rel(joined.loc[delta_series.index, f"{metric}_high"],
                                           joined.loc[delta_series.index, f"{metric}_low"]).pvalue)
                      if n >= threshold else math.nan)
            h1_rows.append({"stage": stage, "protocol": protocol, "rate": rate, "metric": metric,
                            "mean_delta": mean, "ci_low": mean - half, "ci_high": mean + half,
                            "n": n, "p": pvalue})
    for metric in ("delayMs", "pdrPct"):
        selected = [item for item in h1_rows if item["metric"] == metric and math.isfinite(item["p"])]
        adjusted = holm_adjust([item["p"] for item in selected])
        for item, value in zip(selected, adjusted):
            item["p_holm"] = value
    h1_supported = [item for item in h1_rows if item.get("p_holm", 1) < alpha and
                    ((item["metric"] == "delayMs" and item["ci_low"] > 0) or
                     (item["metric"] == "pdrPct" and item["ci_high"] < 0))]
    print("\nHipóteses (síntese neutra):")
    print("- H1, mobilidade: " + (f"IC/teste pareado indica aumento de atraso e/ou queda de PDR em {len(h1_supported)} comparação(ões), com t pareado e Holm quando n ≥ {threshold}."
                                  if h1_supported else "inconclusiva: os ICs/testes de velocidade não sustentam uma direção após o critério configurado."))
    h2 = paired[paired["metric"].isin(["pdrPct", "throughputMbps", "delayMs"])]
    h2 = h2[h2["p_holm_hypothesis"].notna() & (h2["p_holm_hypothesis"] < alpha)]
    print("- H2, protocolos: " + (f"diferenças detectadas em {len(h2)} comparação(ões) pareadas de atraso, throughput ou PDR."
                                  if len(h2) else "inconclusiva: nenhuma diferença pareada atingiu o nível ajustado."))
    h3 = paired[paired["metric"].isin(["controlPackets", "controlBytes", "controlBytesPerPayloadByte"])]
    h3 = h3[h3["p_holm_hypothesis"].notna() & (h3["p_holm_hypothesis"] < alpha)]
    print("- H3, overhead: " + (f"diferenças detectadas em {len(h3)} comparação(ões) pareadas de controle."
                                 if len(h3) else "inconclusiva: nenhuma diferença pareada de overhead atingiu o nível ajustado."))
    print("Conclusões limitadas às condições simuladas; nenhum protocolo é declarado globalmente superior.")


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
    flows_out = flows.copy()
    flows_out["throughputMbps"] = flows_out["rxBytes"] * 8.0 / profile["useful_duration_s"] / config["metrics"]["bytes_per_megabit"]
    for column in ("pdrPct", "throughputMbps", "delayMs", "jitterMs", "p95Ms"):
        flows_out[column] = pd.to_numeric(flows_out[column], errors="coerce")
    save_csv(flows_out, output_root / "flows.csv")
    results = build_run_results(flows_out, profile, config)
    save_csv(results, output_root / "results.csv")
    summary = summarize(results, config["experiment"]["confidence_level"])
    save_csv(summary, output_root / "summary.csv")
    paired = paired_comparisons(results, config, config["experiment"]["large_n_threshold"])
    save_csv(paired, output_root / "paired-tests.csv")
    mandatory = [
        ("pdrPct", "PDR (%)"), ("throughputMbps", "Throughput (Mbps)"),
        ("delayMs", "Atraso (ms)"), ("jitterMs", "Jitter (ms)")]
    figures = []
    rates = sorted(int(rate) for rate in profile["rate_pps"])
    for metric, label in mandatory:
        figures.extend(plot_metric(summary, metric, label, stage, figure_root,
                                   config["experiment"]["confidence_level"], rates,
                                   config["experiment"]["minimum_reliable_pdr_pct"]))
    figures.extend(plot_overhead_pdr(results, stage, figure_root, rates))
    print(f"Análise {stage}: {len(results)} execuções; {len(flows_out)} fluxos; saídas {output_root}")
    for warning in warnings:
        print(f"Aviso: {warning}", file=sys.stderr)
    for path in figures:
        print(f"Figura: {path}")
    print_synthesis(summary, stage, config["experiment"]["protocols"], rates)
    print_hypothesis_summary(results, paired, config)
    return output_root, figure_root, results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("stage1", "stage2", "stage3"), default="stage1")
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
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ET.ParseError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        raise SystemExit(2)
