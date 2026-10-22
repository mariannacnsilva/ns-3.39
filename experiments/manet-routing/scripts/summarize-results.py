#!/usr/bin/env python3
"""Extrai métricas básicas dos resultados XML do FlowMonitor."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from xml.etree import ElementTree


def parse_time_ns(value: str) -> float:
    if not value or value == "0ns":
        return 0.0
    if value.endswith("ns"):
        return float(value[:-2])
    raise ValueError(f"Unidade de tempo não suportada: {value!r}")


def metrics_for_flow(flow: ElementTree.Element) -> dict:
    flow_id = flow.get("flowId")
    tx_packets = float(flow.get("txPackets", "0"))
    rx_packets = float(flow.get("rxPackets", "0"))
    tx_bytes = float(flow.get("txBytes", "0"))
    rx_bytes = float(flow.get("rxBytes", "0"))
    lost_packets = float(flow.get("lostPackets", "0"))
    times_forwarded = float(flow.get("timesForwarded", "0"))

    tx_start = parse_time_ns(flow.get("timeFirstTxPacket", "0ns"))
    tx_end = parse_time_ns(flow.get("timeLastTxPacket", "0ns"))
    rx_start = parse_time_ns(flow.get("timeFirstRxPacket", "0ns"))
    rx_end = parse_time_ns(flow.get("timeLastRxPacket", "0ns"))

    duration_tx = max((tx_end - tx_start) * 1e-9, 0.0)
    duration_rx = max((rx_end - rx_start) * 1e-9, 0.0)

    tx_bitrate = tx_bytes * 8.0 / duration_tx if duration_tx > 0 else None
    rx_bitrate = rx_bytes * 8.0 / duration_rx if duration_rx > 0 else None

    delay_sum = parse_time_ns(flow.get("delaySum", "0ns"))
    delay_mean = (delay_sum / rx_packets) * 1e-9 if rx_packets > 0 else None

    packet_loss_ratio = None
    if tx_packets > 0:
        packet_loss_ratio = lost_packets / tx_packets

    hops = None
    if rx_packets > 0:
        hops = (times_forwarded / rx_packets) + 1.0

    return {
        "flow_id": int(flow_id),
        "tx_packets": int(tx_packets),
        "rx_packets": int(rx_packets),
        "lost_packets": int(lost_packets),
        "tx_bytes": int(tx_bytes),
        "rx_bytes": int(rx_bytes),
        "tx_bitrate_kbps": tx_bitrate / 1000.0 if tx_bitrate is not None else None,
        "rx_bitrate_kbps": rx_bitrate / 1000.0 if rx_bitrate is not None else None,
        "delay_mean_ms": delay_mean * 1000.0 if delay_mean is not None else None,
        "packet_loss_ratio": packet_loss_ratio,
        "estimated_hops": hops,
    }


def identify_flow(flow: ElementTree.Element, classifier: ElementTree.Element) -> dict:
    flow_id = int(flow.get("flowId"))
    classifier_flow = None

    for candidate in classifier.findall("Flow"):
        if int(candidate.get("flowId")) == flow_id:
            classifier_flow = candidate
            break

    if classifier_flow is None:
        return {}

    return {
        "source": candidate.get("sourceAddress"),
        "destination": candidate.get("destinationAddress"),
        "protocol": int(candidate.get("protocol")),
        "source_port": int(candidate.get("sourcePort")),
        "destination_port": int(candidate.get("destinationPort")),
    }


def extract_rows(xml_path: Path) -> list[dict]:
    tree = ElementTree.parse(xml_path)
    root = tree.getroot()
    classifier = root.find("Ipv4FlowClassifier")

    if classifier is None:
        raise ValueError(f"Ipv4FlowClassifier não encontrado em {xml_path}")

    rows: list[dict] = []
    for flow in root.findall("FlowStats/Flow"):
        metrics = metrics_for_flow(flow)
        identity = identify_flow(flow, classifier)
        rows.append(
            {
                "xml_file": xml_path.name,
                **metrics,
                **identity,
            }
        )

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "results" / "raw",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "results" / "processed" / "summary.csv",
    )
    args = parser.parse_args()

    xml_files = sorted(args.input.glob("**/*.xml"))
    if not xml_files:
        raise FileNotFoundError(f"Nenhum XML encontrado em {args.input}")

    rows: list[dict] = []
    for xml_path in xml_files:
        rows.extend(extract_rows(xml_path))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "xml_file",
        "flow_id",
        "source",
        "destination",
        "protocol",
        "source_port",
        "destination_port",
        "tx_packets",
        "rx_packets",
        "lost_packets",
        "tx_bytes",
        "rx_bytes",
        "tx_bitrate_kbps",
        "rx_bitrate_kbps",
        "delay_mean_ms",
        "packet_loss_ratio",
        "estimated_hops",
    ]

    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV gerado: {args.output}")
    print(f"Linhas: {len(rows)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - apresenta mensagem útil para o usuário
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1)
