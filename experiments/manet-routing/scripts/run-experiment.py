#!/usr/bin/env python3
"""Compile e execute cenários MANET comparando AODV, DSDV e OLSR.

O script não cria um repositório Git e não modifica os arquivos-fonte do ns-3.
Ele apenas coleta a configuração do experimento e registra os resultados em
`experiments/manet-routing/results`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_clean_destination(destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)


def build_ns3(root: Path) -> None:
    build_script = root / "ns3"
    if not build_script.exists():
        raise FileNotFoundError(f"Executável ns3 não encontrado em {build_script}")

    subprocess.run(
        [str(build_script), "configure", "--enable-examples"],
        cwd=root,
        check=True,
    )


def run_protocol(root: Path, protocol: str, config: dict, dry_run: bool) -> Path:
    source = root / "scratch" / f"experimento-{protocol}-demo.cc"
    if not source.exists():
        raise FileNotFoundError(f"Cenário não encontrado: {source}")

    output_dir = root / "experiments" / "manet-routing" / "results" / "raw" / protocol
    ensure_clean_destination(output_dir)

    output_xml = output_dir / f"resultado-flowmonitor-{protocol}.xml"
    animation_xml = output_dir / f"experimento-{protocol}-demo.xml"

    if dry_run:
        print(f"[dry-run] {protocol}: {source}")
        print(f"[dry-run] saída: {output_xml}")
        return output_dir

    build_ns3(root)
    command = [str(root / "ns3"), "run", f"scratch/{source.name}"]
    subprocess.run(command, cwd=root, check=True)

    source_xml = root / output_xml.name
    source_animation = root / animation_xml.name
    if source_xml.exists():
        source_xml.replace(output_xml)
    else:
        raise FileNotFoundError(f"Resultado XML não foi gerado em {source_xml}")
    if source_animation.exists():
        source_animation.replace(animation_xml)
    else:
        print(f"[aviso] Animação não encontrada: {source_animation}", file=sys.stderr)

    manifest = {
        "protocol": protocol,
        "seed": config["experiment"]["seed"],
        "ns3_version": config["experiment"]["ns3_version"],
        "command": command,
        "scenario": config["scenario"],
        "output": {
            "xml": str(output_xml.relative_to(root)),
            "animation": str(animation_xml.relative_to(root)),
        },
    }
    manifest_path = output_dir / "run-metadata.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Executado: {protocol}")
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "experiment.json",
    )
    parser.add_argument(
        "--protocol",
        choices=["aodv", "dsdv", "olsr", "all"],
        default="all",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    root = Path(__file__).resolve().parents[3]

    if args.protocol == "all":
        protocols = config["experiment"]["protocols"]
    else:
        protocols = [args.protocol]

    for protocol in protocols:
        run_protocol(root, protocol, config, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
