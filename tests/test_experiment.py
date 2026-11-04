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

if __name__ == "__main__":
    unittest.main()
