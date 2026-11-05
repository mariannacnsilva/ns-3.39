#!/usr/bin/env python3
"""Valida e analisa a H1, as quatro métricas e, de forma descritiva, o efeito da carga."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from scipy.sparse.csgraph import connected_components, shortest_path

from run_experiment import (TRAJECTORY_TOLERANCE_M, hash_file, read_trace, resolve_profile,
                            trajectory_deviation)

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "manet-routing"
FLOW_COLUMNS = ["stage", "protocol", "speed", "rate", "run", "seed", "flowId",
                "txPackets", "rxPackets", "lostPackets", "rxBytes", "throughputMbps",
                "pdrPct", "delayMs", "jitterMs", "delaySumMs", "jitterSumMs",
                "maxPackets", "flowIndex", "sourceNode", "destinationNode",
                "packetSizeBytes", "undeliveredPackets", "routingProtocol",
                "controlPackets", "controlBytes", "trajectorySha256"]
ROUTING_TYPES = {"aodv": "ns3::aodv::RoutingProtocol", "olsr": "ns3::olsr::RoutingProtocol",
                 "dsdv": "ns3::dsdv::RoutingProtocol"}
# Cor por protocolo, fixa em todas as figuras; validada para daltonismo.
PROTOCOL_COLORS = {"aodv": "#0072B2", "dsdv": "#D55E00", "olsr": "#009E73"}
PROTOCOL_MARKERS = {"aodv": "o", "dsdv": "s", "olsr": "^"}
METRICS = {
    "throughputMbps": ("Vazão (Mbps)", "higher"),
    "pdrPct": ("PDR (%)", "higher"),
    "delayMs": ("Atraso médio (ms)", "lower"),
    "jitterMs": ("Jitter médio (ms)", "lower"),
}


# Tráfego de controle: valor da rede inteira em cada execução, comparado por protocolo. Fora da decisão da H1.
METRIC_LABELS = {**{metric: details[0] for metric, details in METRICS.items()},
                 "controlPackets": "Pacotes de controle", "controlBytes": "Bytes de controle"}


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
        "undeliveredPackets": tx - rx,
        "controlPackets": int(flows[0].get("controlPackets", 0)),
        "controlBytes": int(flows[0].get("controlBytes", 0)),
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


def _read_bytes(path: Path) -> bytes:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as source:
            return source.read()
    return path.read_bytes()


def _time_ms(value: str) -> float:
    return float(value.removesuffix("ns")) / 1e6


def check_flowmonitor(xml_bytes: bytes, rows: list[dict], label: str) -> None:
    """Confere os contadores do CSV com o XML bruto do FlowMonitor."""
    stats_by_id = {element.get("flowId"): element
                   for element in ET.fromstring(xml_bytes).findall("FlowStats/Flow")}
    for row in rows:
        flow_id = str(int(row["flowId"]))
        if flow_id == "0":
            if int(row["rxPackets"]) != 0:
                raise ValueError(f"{label}: fluxo ausente no FlowMonitor com pacotes recebidos.")
            continue
        element = stats_by_id.get(flow_id)
        if element is None:
            raise ValueError(f"{label}: flowId {flow_id} não existe no XML.")
        for attribute in ("rxPackets", "rxBytes", "lostPackets"):
            if int(element.get(attribute)) != int(row[attribute]):
                raise ValueError(f"{label}: {attribute} do fluxo {flow_id} diverge entre CSV e XML.")
        if not math.isclose(_time_ms(element.get("delaySum")), float(row["delaySumMs"]),
                            rel_tol=1e-4, abs_tol=1e-3):
            raise ValueError(f"{label}: delaySum do fluxo {flow_id} diverge entre CSV e XML.")


def validate_dataset(root: Path, config: dict, stage: str) -> tuple[pd.DataFrame, dict, list[str]]:
    manifest_path, config_path, flow_path = root / "manifest.json", root / "config.json", root / "flows.csv"
    if not manifest_path.exists() or not config_path.exists() or not flow_path.exists():
        raise ValueError(f"Manifesto, config.json ou flows.csv ausente em {root}.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("stage") != stage:
        raise ValueError(f"Etapa divergente: solicitada {stage}, manifesto contém {manifest.get('stage')}.")
    if manifest.get("mode") == "animation":
        raise ValueError("Animações não podem ser analisadas como lote.")
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
               "rxBytes", "maxPackets", "flowIndex", "sourceNode", "destinationNode", "packetSizeBytes",
               "undeliveredPackets", "controlPackets", "controlBytes"]
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
    if (frame["undeliveredPackets"] != frame["txPackets"] - frame["rxPackets"]).any():
        raise ValueError("undeliveredPackets difere de tx - rx.")
    if (frame["protocol"].map(ROUTING_TYPES) != frame["routingProtocol"]).any():
        raise ValueError("O protocolo instalado na simulação difere do protocolo solicitado.")
    control_by_run = frame.groupby(["protocol", "speed", "rate", "run"])[["controlPackets", "controlBytes"]]
    if (control_by_run.nunique() != 1).any().any() or (frame["controlPackets"] <= 0).any():
        raise ValueError("Tráfego de controle ausente ou diferente entre fluxos da mesma execução.")
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

    # Texto "nan" do CSV vira ausente de verdade; as fórmulas acima já foram conferidas.
    for column in METRICS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

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
    trace_references: dict[tuple[float, int], list] = {}
    max_deviation = 0.0
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
        if not mobility.exists() or hash_file(mobility) != item["trajectory_sha256"]:
            raise ValueError(f"Trace de mobilidade ausente ou hash divergente: {mobility}.")
        if not flow_xml.exists():
            raise ValueError(f"XML FlowMonitor ausente: {flow_xml}.")
        selection = frame[(frame["protocol"] == key[0]) & (frame["speed"] == key[1]) &
                          (frame["rate"] == key[2]) & (frame["run"] == key[3])]
        if len(selection) != expected_flow_count or selection["trajectorySha256"].nunique() != 1:
            raise ValueError(f"Fluxos/hashes incompletos no manifesto {key}.")
        if selection["trajectorySha256"].iloc[0] != item["trajectory_sha256"]:
            raise ValueError(f"Hash da trajetória diverge entre CSV e manifesto: {key}.")
        check_flowmonitor(_read_bytes(flow_xml), selection.to_dict("records"), str(key))
        trace = read_trace(mobility)
        deviation = trajectory_deviation(trace_references.setdefault((key[1], key[3]), trace), trace)
        max_deviation = max(max_deviation, deviation)
        if deviation > TRAJECTORY_TOLERANCE_M:
            raise ValueError(f"Trajetória diferente entre protocolos ou cargas: {key}, desvio de {deviation} m.")
    print(f"Trajetórias pareadas: desvio máximo de {max_deviation:.2e} m (tolerância {TRAJECTORY_TOLERANCE_M:g} m).")

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
        for metric in METRIC_LABELS:
            n, mean, std, low, high = mean_ci(group[metric], confidence)
            rows.append({"stage": stage, "protocol": protocol, "speed": speed, "rate": rate,
                         "metric": metric, "n_runs": len(group), "n_valid": n,
                         "mean": mean, "std": std, "ci95_low": low, "ci95_high": high})
    return pd.DataFrame(rows)


def _is_worse(direction: str, before: float, after: float) -> bool:
    return after < before if direction == "higher" else after > before


def _intervals_overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool | None:
    if not all(math.isfinite(value) for value in (a_low, a_high, b_low, b_high)):
        return None
    return not (a_high < b_low or b_high < a_low)


def _trend(group: pd.DataFrame, direction: str) -> tuple[str, str]:
    """Tendência entre as pontas e o intervalo de velocidade com a maior piora."""
    points = [(float(row.speed), float(row.mean)) for row in group.sort_values("speed").itertuples()
              if math.isfinite(row.mean)]
    if len(points) < 2:
        return "indisponível", "indisponível"
    first, last = points[0][1], points[-1][1]
    trend = "estável" if first == last else ("piora" if _is_worse(direction, first, last) else "melhora")
    worst, worst_size = "sem piora", 0.0
    for (speed_a, value_a), (speed_b, value_b) in zip(points, points[1:]):
        if _is_worse(direction, value_a, value_b) and abs(value_b - value_a) > worst_size:
            worst, worst_size = f"{speed_a:g} a {speed_b:g} m/s", abs(value_b - value_a)
    return trend, worst


def classify_h1(summary: pd.DataFrame, stage: str) -> pd.DataFrame:
    rows = []
    selected = summary[(summary["stage"] == stage) & summary["metric"].isin(METRICS)]
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
        trend, worst = _trend(group, direction)
        rows.append({"stage": stage, "protocol": protocol, "rate": rate, "metric": metric,
                     "n_1mps": low_speed.n_valid, "mean_1mps": low_speed.mean,
                     "ci95_low_1mps": low_speed.ci95_low, "ci95_high_1mps": low_speed.ci95_high,
                     "n_20mps": high_speed.n_valid, "mean_20mps": high_speed.mean,
                     "ci95_low_20mps": high_speed.ci95_low, "ci95_high_20mps": high_speed.ci95_high,
                     "outcome": outcome, "trend": trend, "worstInterval": worst,
                     "cisOverlap": _intervals_overlap(low_speed.ci95_low, low_speed.ci95_high,
                                                      high_speed.ci95_low, high_speed.ci95_high)})
    return pd.DataFrame(rows)


def effective_range_m(profile: dict) -> float:
    """Alcance em que o sinal recebido iguala o RSSI mínimo de detecção do preâmbulo."""
    budget = profile["tx_power_dbm"] - profile["reference_loss_db"] - profile["preamble_minimum_rssi_dbm"]
    return profile["reference_distance_m"] * 10 ** (budget / (10 * profile["log_distance_exponent"]))


def trace_connectivity(trace: pd.DataFrame, pairs: list, range_m: float,
                       start_s: float, stop_s: float) -> dict:
    """Conectividade geométrica na janela de tráfego: limite do que qualquer protocolo poderia entregar."""
    window = trace[(trace["time_s"] >= start_s) & (trace["time_s"] <= stop_s)]
    degrees, reachable, largest, hops = [], [], [], []
    for _, sample in window.groupby("time_s"):
        positions = sample.sort_values("node_id")[["x_m", "y_m"]].to_numpy(dtype=float)
        distances = np.linalg.norm(positions[:, None] - positions[None], axis=2)
        adjacency = distances <= range_m
        np.fill_diagonal(adjacency, False)
        _, labels = connected_components(adjacency, directed=False)
        degrees.append(adjacency.sum() / len(positions))
        reachable.append(np.mean([labels[a] == labels[b] for a, b in pairs]))
        paths = shortest_path(adjacency, directed=False, unweighted=True)
        hops.extend(paths[a, b] for a, b in pairs if labels[a] == labels[b])
        largest.append(np.bincount(labels).max() / len(positions))
    return {"meanDegree": float(np.mean(degrees)), "reachPct": 100.0 * float(np.mean(reachable)),
            "largestComponentPct": 100.0 * float(np.mean(largest)),
            "meanHops": float(np.mean(hops)) if hops else math.nan}


def connectivity_table(root: Path, profile: dict) -> pd.DataFrame:
    range_m = effective_range_m(profile)
    seen, rows = set(), []
    for path in sorted((root / "runs").glob("*.manifest.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        key = (float(item["speed"]), int(item["run"]))
        if key in seen:
            continue
        seen.add(key)
        trace = pd.read_csv(root / item["files"]["mobility"])
        row = trace_connectivity(trace, profile["flow_pairs"], range_m,
                                 profile["traffic_start_s"], profile["traffic_stop_s"])
        rows.append({"speed": key[0], "run": key[1], "rangeM": range_m, **row})
    return pd.DataFrame(rows).sort_values(["speed", "run"])


def load_trend(h1: pd.DataFrame) -> pd.DataFrame:
    """Compara, entre as cargas, o efeito da velocidade. Descritivo: não há hipótese sobre a carga."""
    rates = sorted(h1["rate"].unique())
    if len(rates) != 2:
        return pd.DataFrame()
    rows = []
    for (protocol, metric), group in h1.groupby(["protocol", "metric"]):
        by_rate = {row.rate: row for row in group.itertuples()}
        if set(by_rate) != set(rates):
            continue
        low, high = by_rate[rates[0]], by_rate[rates[1]]
        rows.append({"protocol": protocol, "metric": metric, "lowRate": rates[0], "highRate": rates[1],
                     "outcomeLowRate": low.outcome, "outcomeHighRate": high.outcome,
                     "sameOutcome": low.outcome == high.outcome,
                     "delta20vs1LowRate": high_minus(low), "delta20vs1HighRate": high_minus(high)})
    return pd.DataFrame(rows)


def high_minus(row) -> float:
    return float(row.mean_20mps) - float(row.mean_1mps)


def write_load_report(trend: pd.DataFrame, path: Path) -> None:
    lines = ["# Efeito da carga sobre a tendência com a velocidade", "",
             "Resultado descritivo: a hipótese do estudo é somente a H1. A tabela mostra se o desfecho da H1 "
             "muda entre as cargas e a diferença de médias entre 20 e 1 m/s em cada carga.", "",
             "| Protocolo | Métrica | H1, carga menor | H1, carga maior | Mesmo desfecho | "
             "Δ 20−1 m/s, carga menor | Δ 20−1 m/s, carga maior |", "|---|---|---|---|---|---:|---:|"]
    for row in trend.itertuples(index=False):
        lines.append(f"| {row.protocol.upper()} | {METRICS[row.metric][0]} | {row.outcomeLowRate} | "
                     f"{row.outcomeHighRate} | {'sim' if row.sameOutcome else 'não'} | "
                     f"{row.delta20vs1LowRate:.4g} | {row.delta20vs1HighRate:.4g} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, na_rep="")


def write_h1_report(h1: pd.DataFrame, path: Path) -> None:
    lines = ["# Síntese da hipótese H1", "",
             "Critério: comparação dos ICs t de 95% entre 1 e 20 m/s. "
             "Não sobreposição na direção de piora = sustentada; na direção oposta = melhora; "
             "sobreposição ou IC indisponível = inconclusiva. A tendência compara as médias nas pontas; "
             "a maior piora é o intervalo de velocidades com a maior degradação da média.", "",
             "| Protocolo | Carga (pps/fluxo) | Métrica | Desfecho | Tendência | Maior piora | ICs sobrepostos |",
             "|---|---:|---|---|---|---|---|"]
    labels = {True: "sim", False: "não"}
    for row in h1.itertuples(index=False):
        label = METRICS[row.metric][0]
        lines.append(f"| {row.protocol.upper()} | {row.rate} | {label} | {row.outcome} | {row.trend} | "
                     f"{row.worstInterval} | {labels.get(row.cisOverlap, 'indisponível')} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _draw_metric(ax, summary: pd.DataFrame, stage: str, metric: str, marker_size: float = 6) -> None:
    label = METRIC_LABELS[metric]
    selected = summary[(summary["stage"] == stage) & (summary["metric"] == metric)]
    many_rates = selected["rate"].nunique() > 1
    lowest_rate = selected["rate"].min()
    groups = list(selected.groupby(["protocol", "rate"]))
    for index, ((protocol, rate), series) in enumerate(groups):
        series = series.sort_values("speed")
        series = series.loc[np.isfinite(series["mean"].to_numpy(dtype=float))]
        if series.empty:
            continue
        lower = np.maximum(0, series["mean"].to_numpy() - series["ci95_low"].to_numpy())
        upper = np.maximum(0, series["ci95_high"].to_numpy() - series["mean"].to_numpy())
        errors = np.vstack([np.nan_to_num(lower), np.nan_to_num(upper)])
        suffix = f", {int(rate)} pps" if many_rates else ""
        high_load = many_rates and rate != lowest_rate
        # Pequeno deslocamento horizontal para as barras de erro não se cobrirem.
        offset = (index - (len(groups) - 1) / 2) * 0.16
        ax.errorbar(series["speed"] + offset, series["mean"], yerr=errors, capsize=3, linewidth=1.6,
                    color=PROTOCOL_COLORS[protocol], marker=PROTOCOL_MARKERS[protocol], markersize=marker_size,
                    markerfacecolor="white" if high_load else PROTOCOL_COLORS[protocol],
                    linestyle="--" if high_load else "-", label=f"{protocol.upper()}{suffix}")
    ax.set(xlabel="Velocidade máxima (m/s)", ylabel=label)
    ax.set_xticks(sorted(selected["speed"].unique()))
    # O IC t pode ultrapassar o intervalo possível; o eixo mostra só valores possíveis.
    ax.set_ylim(bottom=0)
    if metric == "pdrPct":
        ax.set_ylim(top=100)
    ax.grid(True, alpha=0.25)


def plot_metrics(summary: pd.DataFrame, stage: str, figure_root: Path) -> list[Path]:
    output = []
    for metric, label in METRIC_LABELS.items():
        fig, ax = plt.subplots(figsize=(8, 5))
        _draw_metric(ax, summary, stage, metric)
        ax.set_title(f"{label} × velocidade — {stage}")
        ax.legend(title="Protocolo / carga")
        fig.tight_layout()
        path = figure_root / stage / f"{metric}-speed.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=160)
        plt.close(fig)
        output.append(path)
    return output


def plot_panel(summary: pd.DataFrame, stage: str, figure_root: Path) -> list[Path]:
    """Painel 2 × 2 para o artigo, em PDF vetorial e PNG."""
    with plt.rc_context({"font.size": 8, "axes.labelsize": 8, "legend.fontsize": 7.5}):
        fig, axes = plt.subplots(2, 2, figsize=(6.3, 4.6))
        for ax, metric in zip(axes.flat, METRICS):
            _draw_metric(ax, summary, stage, metric, marker_size=4)
        handles, labels = axes.flat[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False)
        fig.tight_layout(rect=(0, 0.11, 1, 1))
        directory = figure_root / stage
        directory.mkdir(parents=True, exist_ok=True)
        paths = [directory / "panel.pdf", directory / "panel.png"]
        fig.savefig(paths[0])
        fig.savefig(paths[1], dpi=200)
        plt.close(fig)
    return paths


def analyze(input_root: Path, stage: str, config: dict) -> tuple[Path, Path, pd.DataFrame]:
    flows, manifest, warnings = validate_dataset(input_root, config, stage)
    profile = manifest["profile"]
    official = manifest.get("mode") == "official"
    output_root = EXPERIMENT_DIR / "data" / "processed" / stage if official else input_root / "processed"
    figure_root = EXPERIMENT_DIR / "figures" if official else input_root / "figures"
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
    save_csv(results_frame, output_root / "results.csv")
    save_csv(summary, output_root / "summary.csv")
    save_csv(h1, output_root / "h1-results.csv")
    write_h1_report(h1, output_root / "h1-summary.md")
    figures = plot_metrics(summary, stage, figure_root) + plot_panel(summary, stage, figure_root)
    connectivity = connectivity_table(input_root, profile)
    save_csv(connectivity, output_root / "connectivity.csv")
    print(f"Alcance efetivo calculado: {effective_range_m(profile):.1f} m; "
          f"pares com caminho na janela de tráfego: {connectivity['reachPct'].mean():.1f}%; "
          f"grau médio: {connectivity['meanDegree'].mean():.2f}; "
          f"saltos médios: {connectivity['meanHops'].mean():.2f}.")
    if stage == "stage2":
        trend = load_trend(h1)
        save_csv(trend, output_root / "load-trend.csv")
        write_load_report(trend, output_root / "load-effect.md")
    print(f"Análise {stage}: {len(results_frame)} execuções; {len(flows)} fluxos; saídas {output_root}")
    for warning in warnings:
        print(f"Aviso: {warning}", file=sys.stderr)
    for path in figures:
        print(f"Figura: {path}")
    print(f"Síntese H1: {output_root / 'h1-summary.md'}")
    return output_root, figure_root, results_frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("stage1", "stage2"), default="stage1")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "experiment.json")
    parser.add_argument("--input", type=Path, help="Diretório raw da etapa ou do piloto")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    input_root = args.input or (EXPERIMENT_DIR / "data" / "raw" / args.stage)
    analyze(input_root.resolve(), args.stage, config)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        raise SystemExit(2)
