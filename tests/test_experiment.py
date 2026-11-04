import json
import math
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

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
        if not list((run_experiment.ROOT / "build" / "scratch").glob("ns3.39-manet-routing-compare-*")):
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
        self.assertEqual(len(set(hashes.values())), 1, hashes)

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
