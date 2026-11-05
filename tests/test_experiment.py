import csv
import gzip
import json
import math
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze
import run_experiment


class ExperimentTests(unittest.TestCase):
    def test_stage_matrix_sizes_and_invalid_arguments(self):
        config = run_experiment.load_config()
        self.assertEqual(len(run_experiment.matrix(config, "stage1")), 120)
        self.assertEqual(len(run_experiment.matrix(config, "stage2")), 720)
        self.assertEqual(len(run_experiment.matrix(config, "stage1", animation=True)), 12)
        self.assertEqual(len(run_experiment.matrix(config, "stage1", 1)), 12)
        self.assertEqual(len(run_experiment.matrix(config, "stage2", 1)), 24)
        self.assertEqual(len(run_experiment.matrix(config, "stage1", 3)), 36)
        self.assertEqual(len(run_experiment.matrix(config, "stage2", 3)), 72)
        with patch.object(sys, "argv", ["run_experiment.py", "--jobs", "0", "--dry-run"]):
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                run_experiment.main()

    def test_formula_units_and_jitter_missing(self):
        self.assertAlmostEqual(analyze.pdr_pct(8, 10), 80.0)
        self.assertAlmostEqual(analyze.throughput_mbps(1_000_000, 10), 0.8)
        self.assertAlmostEqual(analyze.delay_ms(120, 3), 40.0)
        self.assertAlmostEqual(analyze.jitter_ms(12, 4), 4.0)
        self.assertTrue(math.isnan(analyze.jitter_ms(0, 1)))
        self.assertTrue(math.isnan(analyze.jitter_ms(0, 0)))
        self.assertTrue(math.isnan(analyze.pdr_pct(0, 0)))

    def test_weighted_execution_aggregation(self):
        flows = [
            {"txPackets": 100, "rxPackets": 50, "lostPackets": 50, "rxBytes": 25600,
             "delaySumMs": 5000, "jitterSumMs": 490},
            {"txPackets": 10, "rxPackets": 2, "lostPackets": 8, "rxBytes": 1024,
             "delaySumMs": 1000, "jitterSumMs": 8},
        ]
        result = analyze.aggregate_flows(flows, 100)
        self.assertEqual(result["txPackets"], 110)
        self.assertEqual(result["rxPackets"], 52)
        self.assertAlmostEqual(result["delayMs"], 6000 / 52)
        self.assertAlmostEqual(result["jitterMs"], 498 / 50)
        self.assertAlmostEqual(result["pdrPct"], 100 * 52 / 110)
        self.assertAlmostEqual(result["throughputMbps"], 26624 * 8 / 100 / 1e6)
        repeated = [{**flow, "controlPackets": 7, "controlBytes": 70} for flow in flows]
        control = analyze.aggregate_flows(repeated, 100)
        self.assertEqual((control["controlPackets"], control["controlBytes"]), (7, 70))

    def test_repetition_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            config = json.loads(run_experiment.CONFIG_PATH.read_text(encoding="utf-8"))
            config["profiles"]["stage2"]["repetitions"] = 4
            config["experiment"]["run_ranges"]["stage2"] = [1, 4]
            path = Path(temp) / "experiment.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mínimo"):
                run_experiment.load_config(path)
        with self.assertRaisesRegex(ValueError, "pelo menos 2 runs"):
            analyze.validate_analysis_repetitions(1)

    def test_h1_endpoint_ci_outcomes(self):
        rows = []
        for protocol, values in (("aodv", (10.0, 20.0)),
                                 ("dsdv", (10.0, 5.0)),
                                 ("olsr", (10.0, 10.5))):
            for speed, mean in zip((1.0, 20.0), values):
                rows.append({"stage": "stage1", "protocol": protocol, "speed": speed,
                             "rate": 10, "metric": "delayMs", "n_valid": 10,
                             "mean": mean, "ci95_low": mean - 1, "ci95_high": mean + 1})
        result = analyze.classify_h1(__import__("pandas").DataFrame(rows), "stage1")
        outcomes = dict(zip(result["protocol"], result["outcome"]))
        self.assertEqual(outcomes, {"aodv": "sustentada", "dsdv": "melhora", "olsr": "inconclusiva"})

    def test_trajectory_hash_equal_across_protocols(self):
        if not list((run_experiment.ROOT / "build" / "scratch").glob("ns3.39-manet-routing-compare*")):
            self.skipTest("simulador n\u00e3o compilado")
        hashes = {}
        with tempfile.TemporaryDirectory() as tmp:
            for protocol in run_experiment.PROTOCOLS:
                trace = Path(tmp) / f"{protocol}.csv"
                completed = run_experiment.subprocess.run(
                    [*run_experiment.NS3, "run", "--no-build", "scratch/manet-routing-compare", "--",
                     f"--protocol={protocol}", "--run=1", "--speed=20", "--duration=40",
                     "--traffic-start=10", "--traffic-stop=30", f"--mobility-trace={trace}",
                     f"--flows={Path(tmp) / (protocol + '-flows.csv')}",
                     f"--flow-monitor={Path(tmp) / (protocol + '.xml')}"],
                    cwd=run_experiment.ROOT, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                hashes[protocol] = run_experiment.hash_file(trace)
                with (Path(tmp) / f"{protocol}-flows.csv").open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(len(rows), 4)
                self.assertGreater(int(rows[0]["controlPackets"]), 0)
                self.assertEqual(len({(row["controlPackets"], row["controlBytes"]) for row in rows}), 1)
                for row in rows:
                    self.assertEqual(row["routingProtocol"], analyze.ROUTING_TYPES[protocol])
                    self.assertEqual(int(row["txPackets"]), 200)
                    self.assertEqual(int(row["undeliveredPackets"]),
                                     int(row["txPackets"]) - int(row["rxPackets"]))
            traces = [run_experiment.read_trace(Path(tmp) / f"{protocol}.csv") for protocol in run_experiment.PROTOCOLS]
            for trace in traces[1:]:
                self.assertLessEqual(run_experiment.trajectory_deviation(traces[0], trace),
                                     run_experiment.TRAJECTORY_TOLERANCE_M)

    def test_hash_ignores_compression_and_gzip_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "a.csv", Path(tmp) / "b.csv"
            first.write_bytes(b"time_s,node_id,x_m,y_m\n")
            second.write_bytes(first.read_bytes())
            plain_hash = run_experiment.hash_file(first)
            run_experiment.compress_deterministic(first, Path(tmp) / "a.csv.gz")
            run_experiment.compress_deterministic(second, Path(tmp) / "b.csv.gz")
            self.assertEqual(run_experiment.hash_file(Path(tmp) / "a.csv.gz"), plain_hash)
            self.assertEqual((Path(tmp) / "a.csv.gz").read_bytes(), (Path(tmp) / "b.csv.gz").read_bytes())
            self.assertEqual(gzip.decompress((Path(tmp) / "a.csv.gz").read_bytes()), b"time_s,node_id,x_m,y_m\n")

    def test_trajectory_comparison_tolerates_only_numeric_noise(self):
        base = [(0.0, 0, 10.0, 20.0), (1.0, 0, 11.0, 20.0)]
        noise = [(0.0, 0, 10.000001, 20.0), (1.0, 0, 11.0, 20.0)]
        moved = [(0.0, 0, 10.5, 20.0), (1.0, 0, 11.0, 20.0)]
        tolerance = run_experiment.TRAJECTORY_TOLERANCE_M
        self.assertLessEqual(run_experiment.trajectory_deviation(base, noise), tolerance)
        self.assertGreater(run_experiment.trajectory_deviation(base, moved), tolerance)
        self.assertEqual(run_experiment.trajectory_deviation(base, base[:1]), math.inf)
        self.assertEqual(run_experiment.trajectory_deviation(base, [(0.0, 1, 10.0, 20.0), (1.0, 0, 11.0, 20.0)]), math.inf)

    def test_official_batch_refuses_uncommitted_code(self):
        for state in ({"revision": "abc", "working_tree_dirty": True, "status_short": [" M x"]},
                      {"revision": None, "reason": "sem git"}):
            with patch.object(run_experiment, "git_metadata", return_value=state), \
                 patch.object(sys, "argv", ["run_experiment.py", "--stage", "stage1"]), \
                 patch.object(run_experiment.subprocess, "run") as simulator, redirect_stderr(StringIO()):
                self.assertEqual(run_experiment.main(), 2)
                simulator.assert_not_called()

    def test_effective_range_matches_link_budget(self):
        profile = run_experiment.resolve_profile(run_experiment.load_config(), "stage1")
        self.assertAlmostEqual(analyze.effective_range_m(profile), 169.4, delta=0.5)
        self.assertAlmostEqual(analyze.effective_range_m({**profile, "log_distance_exponent": 3.0}), 85.4, delta=0.5)

    def test_trace_connectivity_uses_multihop_paths(self):
        rows = []
        for time_s in (10.0, 11.0):
            for node, x in enumerate((0.0, 100.0, 200.0, 900.0)):
                rows.append({"time_s": time_s, "node_id": node, "x_m": x, "y_m": 0.0})
        result = analyze.trace_connectivity(pd.DataFrame(rows), [(0, 2), (0, 3)], 150.0, 10.0, 11.0)
        self.assertAlmostEqual(result["reachPct"], 50.0)
        self.assertAlmostEqual(result["meanDegree"], 1.0)
        self.assertAlmostEqual(result["largestComponentPct"], 75.0)
        self.assertAlmostEqual(result["meanHops"], 2.0)

    def test_flowmonitor_xml_is_checked_against_csv(self):
        xml = (b'<FlowMonitor><FlowStats><Flow flowId="1" rxPackets="5" rxBytes="2700" lostPackets="1" '
               b'delaySum="+2.5e+07ns" /></FlowStats></FlowMonitor>')
        row = {"flowId": 1, "rxPackets": 5, "rxBytes": 2700, "lostPackets": 1, "delaySumMs": 25.0}
        analyze.check_flowmonitor(xml, [row], "ok")
        analyze.check_flowmonitor(xml, [{**row, "flowId": 0, "rxPackets": 0}], "ausente")
        with self.assertRaisesRegex(ValueError, "rxPackets"):
            analyze.check_flowmonitor(xml, [{**row, "rxPackets": 6}], "x")
        with self.assertRaisesRegex(ValueError, "delaySum"):
            analyze.check_flowmonitor(xml, [{**row, "delaySumMs": 30.0}], "x")
        with self.assertRaisesRegex(ValueError, "não existe"):
            analyze.check_flowmonitor(xml, [{**row, "flowId": 9}], "x")

    def test_trend_and_load_comparison(self):
        rows = []
        for rate, values in ((10, (90.0, 88.0, 80.0, 78.0)), (100, (50.0, 49.0, 48.0, 20.0))):
            for speed, mean in zip((1.0, 5.0, 10.0, 20.0), values):
                rows.append({"stage": "stage2", "protocol": "aodv", "speed": speed, "rate": rate,
                             "metric": "pdrPct", "n_valid": 30, "mean": mean,
                             "ci95_low": mean - 1, "ci95_high": mean + 1})
        h1 = analyze.classify_h1(pd.DataFrame(rows), "stage2")
        by_rate = {row.rate: row for row in h1.itertuples()}
        self.assertEqual(by_rate[10].trend, "piora")
        self.assertEqual(by_rate[10].worstInterval, "5 a 10 m/s")
        self.assertEqual(by_rate[100].worstInterval, "10 a 20 m/s")
        trend = analyze.load_trend(h1).iloc[0]
        self.assertAlmostEqual(trend["delta20vs1LowRate"], -12.0)
        self.assertAlmostEqual(trend["delta20vs1HighRate"], -30.0)
        self.assertTrue(trend["sameOutcome"])

    def test_run_with_too_few_flows_leaves_no_partial_directory(self):
        config = run_experiment.load_config()
        profile = run_experiment.resolve_profile(config, "stage1")
        run = ("olsr", 5.0, 10, 1)
        tag = "olsr-v5-r10-run-001"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_simulator(command, **kwargs):
                flows = next(Path(a.split("=", 1)[1]) for a in command if a.startswith("--flows="))
                mobility = next(Path(a.split("=", 1)[1]) for a in command if a.startswith("--mobility-trace="))
                xml = next(Path(a.split("=", 1)[1]) for a in command if a.startswith("--flow-monitor="))
                flows.write_text("flowIndex\n0\n", encoding="utf-8")
                mobility.write_text("time_s\n", encoding="utf-8")
                xml.write_text("<x/>", encoding="utf-8")
                return run_experiment.subprocess.CompletedProcess(command, 0, "", "")

            with patch.object(run_experiment.subprocess, "run", fake_simulator):
                _, success, message, _ = run_experiment.execute_one(config, profile, "stage1", root, run, False)
            self.assertFalse(success)
            self.assertIn("1 fluxo(s)", message)
            self.assertFalse((root / "runs" / tag).exists())
            self.assertFalse((root / "mobility" / f"{tag}.csv").exists())


if __name__ == "__main__":
    unittest.main()
