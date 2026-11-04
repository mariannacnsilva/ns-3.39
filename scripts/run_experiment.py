#!/usr/bin/env python3
"""Executa as etapas reproduzíveis do estudo MANET."""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import gzip
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "experiment.json"
EXPERIMENT_DIR = ROOT / "experiments" / "manet-routing"
NS3 = [sys.executable, str(ROOT / "ns3")]
PROTOCOLS = ("aodv", "olsr", "dsdv")


def load_config(path: Path = CONFIG_PATH) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    experiment = config["experiment"]
    if len(experiment["protocols"]) != len(set(experiment["protocols"])):
        raise ValueError("A lista de protocolos contém duplicatas.")
    minimum = config["experiment"]["minimum_repetitions"]
    for stage in ("stage1", "stage2"):
        profile = resolve_profile(config, stage)
        repetitions = profile["repetitions"]
        if repetitions < minimum:
            raise ValueError(f"{stage}: repetições={repetitions}; mínimo permitido={minimum}.")
        run_range = experiment["run_ranges"][stage]
        if run_range != [1, repetitions]:
            raise ValueError(f"{stage}: run_ranges deve ser [1, {repetitions}].")
        if len(profile["flow_pairs"]) < 1:
            raise ValueError(f"{stage}: configure ao menos um fluxo.")
        if profile["traffic_stop_s"] - profile["traffic_start_s"] != profile["useful_duration_s"]:
            raise ValueError(f"{stage}: useful_duration_s deve ser igual a traffic_stop_s - traffic_start_s.")
    return config


def resolve_profile(config: dict, stage: str) -> dict:
    profile = config["profiles"][stage]
    if "base_profile" in profile:
        base = dict(config["profiles"][profile["base_profile"]])
        base.pop("animation", None)
        base.update({key: value for key, value in profile.items() if key != "base_profile"})
        return base
    return dict(profile)


def matrix(config: dict, stage: str, repetitions: int | None = None,
           animation: bool = False) -> list[tuple[str, float, int, int]]:
    profile = resolve_profile(config, stage)
    protocols = config["experiment"]["protocols"]
    if animation:
        anim = profile["animation"]
        return [(protocol, speed, anim["rate_pps"], run)
                for speed in anim["maximum_speeds_mps"] for protocol in protocols for run in anim["runs"]]
    runs = repetitions if repetitions is not None else profile["repetitions"]
    return [(protocol, speed, rate, run)
            for speed in profile["maximum_speeds_mps"]
            for rate in profile["rate_pps"]
            for run in range(1, runs + 1)
            for protocol in protocols]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def uncompressed_directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        if item.suffix == ".gz":
            with gzip.open(item, "rb") as source:
                total += sum(len(chunk) for chunk in iter(lambda: source.read(1024 * 1024), b""))
        else:
            total += item.stat().st_size
    return total


def compress_flowmonitor_outputs(root: Path) -> int:
    compressed = 0
    for manifest_path in (root / "runs").glob("*.manifest.json"):
        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        flow_xml = root / run_manifest["files"]["flowmonitor"]
        if not flow_xml.exists() or flow_xml.suffix == ".gz":
            continue
        compressed_path = Path(str(flow_xml) + ".gz")
        with flow_xml.open("rb") as source, gzip.open(compressed_path, "wb") as target:
            shutil.copyfileobj(source, target)
        flow_xml.unlink()
        run_manifest["files"]["flowmonitor"] = str(compressed_path.relative_to(root))
        run_manifest["flowmonitor_compression"] = "gzip"
        manifest_path.write_text(json.dumps(run_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        compressed += 1
    return compressed


def pilot_size_projection(root: Path, expected_runs: int) -> dict:
    fixed_bytes = sum(path.stat().st_size for path in root.iterdir()
                      if path.is_file() and path.name != "flows.csv")
    variable_dirs = [root / "raw", root / "mobility", root / "runs"]
    observed_variable = sum(directory_size(path) for path in variable_dirs if path.exists())
    combined_flows = root / "flows.csv"
    if combined_flows.exists():
        observed_variable += combined_flows.stat().st_size
    completed_runs = len(list((root / "runs").glob("*.manifest.json")))
    projected_variable = math.ceil(observed_variable * expected_runs / completed_runs) if completed_runs else 0
    return {"observed_bytes": directory_size(root), "observed_runs": completed_runs,
            "expected_official_runs": expected_runs,
            "projected_uncompressed_official_bytes": fixed_bytes + projected_variable}


def git_metadata(directory: Path) -> dict:
    def read_git(*args: str) -> str:
        result = subprocess.run(["git", "-C", str(directory), *args], text=True,
                                capture_output=True, check=False)
        if result.returncode:
            return ""
        return result.stdout.strip()
    revision = read_git("log", "-1", "--format=%H")
    status = read_git("status", "--short")
    if not revision:
        return {"revision": None,
                "reason": "diretório sem metadados Git acessíveis; o código foi executado a partir dos arquivos locais."}
    return {"revision": revision,
            "working_tree_dirty": bool(status), "status_short": status.splitlines()}


def output_root(stage: str, mode: str, repetitions: int) -> Path:
    if mode == "official":
        return EXPERIMENT_DIR / "data" / "raw" / stage
    if mode == "animation":
        return ROOT / "results" / f"animation-{stage}"
    return ROOT / "results" / f"pilot-{stage}-{repetitions}"


def build_command(config: dict, profile: dict, run: tuple, root: Path,
                  animation: bool) -> list[str]:
    protocol, speed, rate, run_id = run
    tag = f"{protocol}-v{speed:g}-r{rate}-run-{run_id:03d}"
    run_dir = root / "runs" / tag
    mobility_path = root / "mobility" / f"{tag}.csv"
    raw_dir = root / "raw"
    for directory in (run_dir, mobility_path.parent, raw_dir):
        directory.mkdir(parents=True, exist_ok=True)
    args = [*NS3, "run", "--no-build", "scratch/manet-routing-compare", "--",
            f"--stage={run_stage(root)}", f"--protocol={protocol}",
            f"--seed-master={config['experiment']['seed_master']}", f"--run={run_id}",
            f"--speed={speed}", f"--rate={rate}", f"--nodes={profile['nodes']}",
            f"--flow-count={len(profile['flow_pairs'])}",
            f"--flow-pairs={';'.join(f'{a}:{b}' for a, b in profile['flow_pairs'])}",
            f"--wifi-standard={profile['wifi_standard']}", f"--wifi-mode={profile['wifi_mode']}",
            f"--channel-width={profile['channel_width_mhz']}", f"--channel-number={profile['channel_number']}",
            f"--area-width={profile['area_width_m']}", f"--area-height={profile['area_height_m']}",
            f"--pause={profile['pause_s']}", f"--minimum-speed={profile['minimum_speed_mps']}",
            f"--duration={profile['duration_s']}", f"--traffic-start={profile['traffic_start_s']}",
            f"--traffic-stop={profile['traffic_stop_s']}", f"--tx-power={profile['tx_power_dbm']}",
            f"--tx-gain={profile['tx_gain_db']}", f"--rx-gain={profile['rx_gain_db']}",
            f"--rx-sensitivity={profile['rx_sensitivity_dbm']}",
            f"--rts-cts-threshold={profile['rts_cts_threshold_bytes']}",
            f"--reference-loss={profile['reference_loss_db']}",
            f"--reference-distance={profile['reference_distance_m']}",
            f"--path-loss-exponent={profile['log_distance_exponent']}",
            f"--propagation-delay=ns3::{profile['propagation_delay']}",
            f"--application-port={profile['application_port']}",
            f"--ip-network={config['ipv4']['network']}", f"--ip-mask={config['ipv4']['mask']}",
            f"--packet-size={profile['packet_size_bytes']}",
            f"--initial-position-stream={profile['initial_position_stream']}",
            f"--mobility-stream={profile['mobility_stream']}",
            f"--mobility-trace-interval={profile['mobility_trace_interval_s']}",
            f"--flows={run_dir / 'flows.csv'}", f"--mobility-trace={mobility_path}",
            f"--flow-monitor={raw_dir / (tag + '.xml')}"]
    if animation:
        anim = profile["animation"]
        xml_path = root / "animation" / f"{speed:g}" / protocol / f"run-{run_id}.xml"
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        args.extend(["--animation=true", f"--animation-file={xml_path}",
                     f"--anim-start={anim['start_s']}", f"--anim-stop={anim['stop_s']}",
                     f"--max-animation-packets={anim['maximum_packets_per_trace_file']}",
                     f"--mobility-update-interval={anim['mobility_update_interval_s']}",
                     f"--route-update-interval={anim['route_update_interval_s']}"])
    else:
        args.append("--animation=false")
    return args


def run_stage(root: Path) -> str:
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))["stage"]
    return "stage1"


def discard_partial(root: Path, tag: str) -> None:
    """Remove artefatos de uma execução sem manifesto para não deixar pastas incompletas."""
    shutil.rmtree(root / "runs" / tag, ignore_errors=True)
    for leftover in (root / "mobility" / f"{tag}.csv", root / "raw" / f"{tag}.xml",
                     root / "raw" / f"{tag}.xml.gz"):
        leftover.unlink(missing_ok=True)


def count_flow_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def write_run_manifest(root: Path, config: dict, profile: dict, stage: str,
                       run: tuple, flow_csv: Path, mobility: Path, flow_xml: Path,
                       command: list[str], elapsed: float, animation: bool) -> dict:
    protocol, speed, rate, run_id = run
    root_metadata = json.loads((root / "manifest.json").read_text(encoding="utf-8")) if (root / "manifest.json").exists() else {}
    project_git = root_metadata.get("project_git")
    ns3_git = root_metadata.get("ns3_git")
    if project_git is None:
        project_git = git_metadata(ROOT)
    if ns3_git is None:
        ns3_git = git_metadata(ROOT)
    files = {"flows": str(flow_csv.relative_to(root)),
             "mobility": str(mobility.relative_to(root)),
             "flowmonitor": str(flow_xml.relative_to(root))}
    if animation:
        animation_xml = root / "animation" / f"{speed:g}" / protocol / f"run-{run_id}.xml"
        files["animation"] = str(animation_xml.relative_to(root))
        files["routing_table_trace"] = str(Path(str(animation_xml) + ".routes.xml").relative_to(root))
    record = {"kind": "animation" if animation else "metrics", "stage": stage,
              "protocol": protocol, "speed": speed, "rate": rate, "run": run_id,
              "seed": config["experiment"]["seed_master"],
              "configuration_sha256": hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
              "trajectory_sha256": hash_file(mobility), "command": command,
              "elapsed_seconds": elapsed, "ns3_version": config["experiment"]["ns3_version"],
              "project_git": project_git, "ns3_git": ns3_git,
              "profile": profile, "files": files}
    manifest = root / "runs" / f"{protocol}-v{speed:g}-r{rate}-run-{run_id:03d}.manifest.json"
    manifest.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def execute_one(config: dict, profile: dict, stage: str, root: Path, run: tuple,
                animation: bool, baseline_root: Path | None = None,
                compress_xml: bool = False) -> tuple[tuple, bool, str, dict | None]:
    protocol, speed, rate, run_id = run
    tag = f"{protocol}-v{speed:g}-r{rate}-run-{run_id:03d}"
    run_dir = root / "runs" / tag
    flow_csv = run_dir / "flows.csv"
    mobility = root / "mobility" / f"{tag}.csv"
    flow_xml = root / "raw" / f"{tag}.xml"
    flow_xml_gz = Path(str(flow_xml) + ".gz")
    manifest_path = root / "runs" / f"{tag}.manifest.json"
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        flow_xml = root / prior.get("files", {}).get("flowmonitor", str(flow_xml.relative_to(root)))
    baseline_hash = None
    if animation and baseline_root is not None:
        base_manifest = baseline_root / "runs" / f"{tag}.manifest.json"
        if not base_manifest.exists():
            baseline_result = execute_one(config, profile, stage, baseline_root, run, False)
            if not baseline_result[1]:
                return run, False, f"baseline sem animação falhou: {baseline_result[2]}", None
        if base_manifest.exists():
            baseline_hash = json.loads(base_manifest.read_text(encoding="utf-8"))["trajectory_sha256"]
    if flow_csv.exists() and mobility.exists() and (flow_xml.exists() or flow_xml_gz.exists()) and manifest_path.exists():
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        if animation and baseline_hash and saved.get("trajectory_sha256") != baseline_hash:
            return run, False, "hash da trajetória existente não confere com a execução sem animação", None
        return run, True, "retomada: artefatos completos", saved
    flow_xml = root / "raw" / f"{tag}.xml"
    discard_partial(root, tag)
    command = build_command(config, profile, run, root, animation)
    # The stage is supplied by the runner's root manifest and appended to the simulator command.
    command[command.index("--") + 1] = f"--stage={stage}"
    start = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode:
        discard_partial(root, tag)
        return run, False, completed.stderr[-3000:] or completed.stdout[-3000:], None
    if not flow_csv.exists() or not mobility.exists() or not flow_xml.exists():
        discard_partial(root, tag)
        return run, False, "simulador terminou sem gerar todos os CSVs/XMLs esperados", None
    expected_flows = len(profile["flow_pairs"])
    produced_flows = count_flow_rows(flow_csv)
    if produced_flows < expected_flows:
        discard_partial(root, tag)
        return run, False, (f"{tag}: a execução gerou {produced_flows} fluxo(s) em flows.csv; "
                            f"esperado {expected_flows}. Artefatos descartados."), None
    if compress_xml:
        with flow_xml.open("rb") as source, gzip.open(flow_xml_gz, "wb") as target:
            shutil.copyfileobj(source, target)
        flow_xml.unlink()
        flow_xml = flow_xml_gz
    trajectory = hash_file(mobility)
    if animation and baseline_hash and trajectory != baseline_hash:
        discard_partial(root, tag)
        return run, False, f"hash de mobilidade divergente: baseline={baseline_hash}, animação={trajectory}", None
    record = write_run_manifest(root, config, profile, stage, run, flow_csv, mobility,
                                flow_xml, command, time.monotonic() - start, animation)
    if animation:
        xml = root / "animation" / f"{speed:g}" / protocol / f"run-{run_id}.xml"
        segments = [p for p in xml.parent.glob(f"{xml.stem}*.xml") if not p.name.endswith(".routes.xml")]
        route_xml = Path(str(xml) + ".routes.xml")
        size = sum(path.stat().st_size for path in segments)
        route_size = route_xml.stat().st_size if route_xml.exists() else 0
        print(f"[animação] {xml}: {size} bytes, {len(segments)} XML(s); rotas {route_size} bytes; hash={trajectory}", flush=True)
    return run, True, "concluída", record


def collect_stage_csvs(root: Path, stage: str) -> None:
    files = sorted((root / "runs").glob("*/flows.csv"))
    if not files:
        return
    manifest_by_run = {path.stem.removesuffix(".manifest"): json.loads(path.read_text(encoding="utf-8"))
                       for path in (root / "runs").glob("*.manifest.json")}
    destination = root / "flows.csv"
    with destination.open("w", encoding="utf-8", newline="") as output:
        writer = None
        for path in files:
            with path.open(encoding="utf-8", newline="") as source:
                rows = csv.DictReader(source)
                fields = list(rows.fieldnames or []) + ["trajectorySha256"]
                if writer is None:
                    writer = csv.DictWriter(output, fieldnames=fields)
                    writer.writeheader()
                run_tag = path.parent.name
                run_manifest = manifest_by_run.get(run_tag)
                if run_manifest is None:
                    raise ValueError(f"Manifesto da execução ausente para {path}")
                for row in rows:
                    if row["stage"] != stage:
                        raise ValueError(f"CSV de outra etapa em {path}")
                    row["trajectorySha256"] = run_manifest["trajectory_sha256"]
                    writer.writerow(row)


def verify_stage2_reproduction(root: Path, mode: str, repetitions: int) -> None:
    """Require Stage 2's 10 pps runs 1-10 to reproduce Stage 1 exactly."""
    if mode == "official":
        baseline = EXPERIMENT_DIR / "data" / "raw" / "stage1"
    elif mode == "pilot":
        baseline = ROOT / "results" / f"pilot-stage1-{repetitions}"
    else:
        return
    baseline_manifest_path = baseline / "manifest.json"
    if not baseline_manifest_path.exists():
        raise ValueError(f"Não foi encontrada a Etapa 1 correspondente para validar a reprodução: {baseline}")
    baseline_manifest = json.loads(baseline_manifest_path.read_text(encoding="utf-8"))
    if baseline_manifest.get("mode") != mode or baseline_manifest.get("stage") != "stage1":
        raise ValueError("A referência da Etapa 1 não corresponde ao modo/perfil da Etapa 2.")
    if mode == "official" and baseline_manifest.get("completed_runs") != baseline_manifest.get("expected_runs"):
        raise ValueError("A Etapa 1 oficial está incompleta; não é possível validar reprodução da Etapa 2.")

    compared = 0
    for stage2_manifest_path in sorted((root / "runs").glob("*.manifest.json")):
        stage2 = json.loads(stage2_manifest_path.read_text(encoding="utf-8"))
        if stage2.get("rate") != 10 or int(stage2.get("run", 0)) > 10:
            continue
        baseline_tag = (f"{stage2['protocol']}-v{stage2['speed']:g}-r10-"
                        f"run-{int(stage2['run']):03d}")
        baseline_run_manifest_path = baseline / "runs" / f"{baseline_tag}.manifest.json"
        if not baseline_run_manifest_path.exists():
            raise ValueError(f"Manifesto base ausente para comparação exata: {baseline_run_manifest_path}")
        baseline_run = json.loads(baseline_run_manifest_path.read_text(encoding="utf-8"))
        if stage2["trajectory_sha256"] != baseline_run["trajectory_sha256"]:
            raise ValueError(f"Trajetória divergiu entre etapas: {baseline_tag}")
        stage2_csv = root / stage2["files"]["flows"]
        baseline_csv = baseline / baseline_run["files"]["flows"]
        with stage2_csv.open(encoding="utf-8", newline="") as handle:
            stage2_rows = list(csv.DictReader(handle))
        with baseline_csv.open(encoding="utf-8", newline="") as handle:
            baseline_rows = list(csv.DictReader(handle))
        omit = {"stage", "trajectorySha256"}
        comparable_fields = sorted((set(stage2_rows[0]) & set(baseline_rows[0])) - omit) if stage2_rows and baseline_rows else []
        if not comparable_fields or len(stage2_rows) != len(baseline_rows):
            raise ValueError(f"CSV por fluxo ausente/incompatível na comparação: {baseline_tag}")
        for row2, row1 in zip(stage2_rows, baseline_rows):
            if any(row2[field] != row1[field] for field in comparable_fields):
                raise ValueError(f"Métricas da Etapa 2 não reproduzem a Etapa 1: {baseline_tag}")
        compared += 1
    expected_compared = len(PROTOCOLS) * 4 * min(repetitions, 10)
    if compared != expected_compared:
        raise ValueError(f"Comparações de reprodução incompletas: {compared}/{expected_compared}.")


def require_stage1_baseline(mode: str, repetitions: int) -> None:
    if mode == "official":
        baseline = EXPERIMENT_DIR / "data" / "raw" / "stage1"
    elif mode == "pilot":
        baseline = ROOT / "results" / f"pilot-stage1-{repetitions}"
    else:
        return
    manifest_path = baseline / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"Execute primeiro a Etapa 1 correspondente; referência ausente: {baseline}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("mode") != mode or manifest.get("stage") != "stage1":
        raise ValueError("A referência existente não corresponde à Etapa 1 do mesmo modo.")
    if mode == "official" and manifest.get("completed_runs") != manifest.get("expected_runs"):
        raise ValueError("Conclua a Etapa 1 oficial antes de iniciar a Etapa 2.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("stage1", "stage2"), default="stage1")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--pilot", action="store_true", help="piloto curto de uma repetição por célula")
    parser.add_argument("--pilot-runs", type=int, help="número de runs do piloto (mínimo 2 para análise)")
    parser.add_argument("--animation", action="store_true", help="gera as animações do perfil escolhido")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, help="diretório de saída específico")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--protocol", choices=PROTOCOLS)
    parser.add_argument("--speed", type=float)
    parser.add_argument("--rate", type=int)
    parser.add_argument("--run", type=int)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs deve ser pelo menos 1")
    if args.animation and (args.pilot or args.pilot_runs is not None or any(
            value is not None for value in (args.protocol, args.speed, args.rate, args.run))):
        parser.error("Animação é modo independente e não pode ser combinada com piloto ou cenário único.")
    config = load_config(args.config)
    profile = resolve_profile(config, args.stage)
    if args.animation and args.stage != "stage1":
        parser.error("As animações deste estudo usam apenas o cenário-base (stage1).")
    pilot_count = args.pilot_runs if args.pilot_runs is not None else (1 if args.pilot else None)
    if pilot_count is not None and pilot_count < 1:
        parser.error("--pilot-runs deve ser positivo.")
    mode = "animation" if args.animation else ("pilot" if pilot_count is not None else "official")
    runs = matrix(config, args.stage, pilot_count, args.animation)
    selections = (args.protocol, args.speed, args.rate, args.run)
    if any(item is not None for item in selections):
        if any(item is None for item in selections) or args.animation or pilot_count is not None:
            parser.error("Para um cenário isolado informe --protocol, --speed, --rate e --run juntos.")
        runs = [(args.protocol, args.speed, args.rate, args.run)]
        mode = "single"
    root = args.output.resolve() if args.output else output_root(args.stage, mode, pilot_count or 0)
    if args.dry_run:
        print(f"Etapa: {args.stage}; modo: {mode}; execuções: {len(runs)}; saída: {root}")
        for protocol, speed, rate, run_id in runs:
            print(f"{protocol} | {speed:g} m/s | {rate} pps/fluxo | run={run_id} | seed={config['experiment']['seed_master']}")
        return 0
    if args.stage == "stage2" and mode in ("official", "pilot"):
        require_stage1_baseline(mode, pilot_count or profile["repetitions"])
    if root.exists() and any(root.iterdir()):
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            print(f"Erro: saída já existe sem manifesto compatível: {root}. Escolha outro --output.", file=sys.stderr)
            return 2
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        same = previous.get("stage") == args.stage and previous.get("mode") == mode and previous.get("config_sha256") == hashlib.sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if not same:
            print(f"Erro: saída {root} já pertence a outra etapa, modo ou configuração.", file=sys.stderr)
            return 2
    root.mkdir(parents=True, exist_ok=True)
    if next(ROOT.rglob("CMakeCache.txt"), None) is None:
        configure = subprocess.run([*NS3, "configure", "--enable-examples"], cwd=ROOT)
        if configure.returncode:
            return configure.returncode
    build = subprocess.run([*NS3, "build", "scratch/manet-routing-compare"], cwd=ROOT)
    if build.returncode:
        return build.returncode

    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    size_limit_bytes = int(config["experiment"]["data_size_limit_mb"] * 1024 * 1024)
    compress_xml = False
    compression_basis = None
    if mode == "official":
        for candidate_runs in (3, 1):
            pilot_manifest_path = ROOT / "results" / f"pilot-{args.stage}-{candidate_runs}" / "manifest.json"
            if not pilot_manifest_path.exists():
                continue
            pilot_manifest = json.loads(pilot_manifest_path.read_text(encoding="utf-8"))
            estimate = pilot_manifest.get("storage_estimate", {}).get("projected_uncompressed_official_bytes")
            if estimate is not None:
                compression_basis = estimate
                compress_xml = estimate > size_limit_bytes
                break
    metadata = {"stage": args.stage, "mode": mode, "expected_runs": len(runs),
                "expected_repetitions_per_cell": pilot_count or profile["repetitions"],
                "config_sha256": config_hash, "config": config,
                "profile": profile, "ns3_version": config["experiment"]["ns3_version"],
                "project_git": git_metadata(ROOT), "ns3_git": git_metadata(ROOT),
                "flowmonitor_gzip_recommended_by_pilot": compress_xml,
                "compression_projection_bytes": compression_basis}
    (root / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    baseline_root = None
    if args.animation:
        official = EXPERIMENT_DIR / "data" / "raw" / args.stage
        official_manifest = json.loads((official / "manifest.json").read_text(encoding="utf-8")) if (official / "manifest.json").exists() else {}
        if (official_manifest.get("mode") == "official" and
            official_manifest.get("config_sha256") == config_hash and
            official_manifest.get("completed_runs") == official_manifest.get("expected_runs")):
            baseline_root = official
        else:
            baseline_root = root / "baseline"
    failed = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        jobs = [executor.submit(execute_one, config, profile, args.stage, root, run,
                                args.animation, baseline_root, compress_xml) for run in runs]
        for index, future in enumerate(concurrent.futures.as_completed(jobs), start=1):
            run, success, message, _ = future.result()
            print(f"[{index}/{len(runs)}] {run}: {message}", file=sys.stdout if success else sys.stderr, flush=True)
            failed |= not success
    if not args.animation:
        manifests = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((root / "runs").glob("*.manifest.json"))]
        hashes: dict[tuple[float, int], set[str]] = {}
        for item in manifests:
            if item.get("stage") != args.stage or item.get("kind") != "metrics":
                failed = True
                continue
            hashes.setdefault((item["speed"], item["run"]), set()).add(item["trajectory_sha256"])
        mismatch = [key for key, values in hashes.items() if len(values) != 1]
        if mismatch:
            print(f"Erro: as trajetórias diferem para velocidade/run: {mismatch}", file=sys.stderr)
            failed = True
        metadata.update({"completed_runs": len(manifests), "trajectory_hashes_match": not mismatch})
    else:
        animation_manifests = list((root / "runs").glob("*.manifest.json"))
        matches = len(animation_manifests) == len(runs)
        for path in animation_manifests:
            baseline_path = baseline_root / "runs" / path.name
            if not baseline_path.exists() or json.loads(path.read_text(encoding="utf-8")).get("trajectory_sha256") != json.loads(baseline_path.read_text(encoding="utf-8")).get("trajectory_sha256"):
                matches = False
        metadata["completed_runs"] = len(animation_manifests)
        metadata["animation_hashes_match_baseline"] = matches
        failed |= not matches
    collect_stage_csvs(root, args.stage)
    if args.stage == "stage2" and not args.animation:
        try:
            verify_stage2_reproduction(root, mode, pilot_count or profile["repetitions"])
            metadata["stage1_reproduction_verified"] = True
        except (OSError, ValueError, KeyError) as error:
            print(f"Erro na reprodução Etapa 1/2: {error}", file=sys.stderr)
            failed = True
    if mode == "official":
        uncompressed_bytes = uncompressed_directory_size(root)
        if compress_xml or uncompressed_bytes > size_limit_bytes:
            compressed_count = compress_flowmonitor_outputs(root)
            applied = compressed_count > 0 or any((root / "raw").glob("*.xml.gz"))
            metadata["flowmonitor_gzip_applied"] = applied
            metadata["flowmonitor_xmls_compressed"] = compressed_count
            metadata["flowmonitor_xmls_compressed"] = compressed_count
        metadata["storage_estimate"] = {"observed_uncompressed_bytes": uncompressed_bytes,
                                         "stored_bytes_after_compression": directory_size(root),
                                         "size_limit_bytes": size_limit_bytes,
                                         "projected_uncompressed_official_bytes": uncompressed_bytes}
    elif mode == "pilot":
        estimate = pilot_size_projection(root, len(matrix(config, args.stage)))
        metadata["storage_estimate"] = estimate
        metadata["flowmonitor_gzip_recommended_by_pilot"] = estimate["projected_uncompressed_official_bytes"] > size_limit_bytes
        print(f"Dados observados do piloto: {estimate['observed_bytes'] / (1024*1024):.2f} MiB; "
              f"projeção oficial {args.stage}: {estimate['projected_uncompressed_official_bytes'] / (1024*1024):.2f} MiB.")
        if metadata["flowmonitor_gzip_recommended_by_pilot"]:
            print("Aviso: projeção supera 50 MiB; o lote oficial compactará XMLs FlowMonitor em gzip.", file=sys.stderr)
    (root / "manifest.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        raise SystemExit(2)
