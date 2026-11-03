import json
import math
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze
import run_experiment


class ExperimentTests(unittest.TestCase):
    def test_stage_matrix_sizes_and_invalid_arguments(self):
        config = run_experiment.load_config()
        self.assertEqual(len(run_experiment.matrix(config, "stage1")), 120)
        self.assertEqual(len(run_experiment.matrix(config, "stage2")), 240)
        self.assertEqual(len(run_experiment.matrix(config, "stage3")), 720)
        self.assertEqual(len(run_experiment.matrix(config, "stage1", animation=True)), 12)
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
        with self.assertRaises(ValueError):
            analyze.pdr_pct(0, 0)

    def test_weighted_execution_aggregation(self):
        flows = [
            {"txPackets": 100, "rxPackets": 50, "lostPackets": 50, "rxBytes": 25600,
             "delaySumMs": 5000, "jitterSumMs": 490, "p95Ms": 200,
             "controlPackets": 20, "controlBytes": 400, "packetSizeBytes": 512,
             "meanGeometricDegree": 3.0, "maxPackets": 1001},
            {"txPackets": 10, "rxPackets": 2, "lostPackets": 8, "rxBytes": 1024,
             "delaySumMs": 1000, "jitterSumMs": 8, "p95Ms": 900,
             "controlPackets": 20, "controlBytes": 400, "packetSizeBytes": 512,
             "meanGeometricDegree": 3.0, "maxPackets": 1001},
        ]
        result = analyze.aggregate_flows(flows, 100)
        self.assertEqual(result["txPackets"], 110)
        self.assertEqual(result["rxPackets"], 52)
        self.assertAlmostEqual(result["delayMs"], 6000 / 52)
        self.assertAlmostEqual(result["jitterMs"], 498 / 50)
        self.assertAlmostEqual(result["pdrPct"], 100 * 52 / 110)
        self.assertEqual(result["controlBytes"], 400)

    def test_repetition_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            config = json.loads(run_experiment.CONFIG_PATH.read_text(encoding="utf-8"))
            config["profiles"]["stage3"]["repetitions"] = 4
            path = Path(temp) / "experiment.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mínimo"):
                run_experiment.load_config(path)
        with self.assertRaisesRegex(ValueError, "pelo menos 2 runs"):
            analyze.validate_analysis_repetitions(1, "pilot", 5)

    def test_flowmonitor_xml_and_p95(self):
        xml = '''<FlowMonitor><FlowStats><Flow flowId="1" txPackets="3" rxPackets="2" lostPackets="1" txBytes="1536" rxBytes="1024" delaySum="3ms" timesForwarded="1"><delayHistogram nBins="2"><bin index="0" start="0" width="0.001" count="1"/><bin index="1" start="0.001" width="0.001" count="1"/></delayHistogram></Flow></FlowStats><Ipv4FlowClassifier><Flow flowId="1" sourceAddress="10.0.0.1" destinationAddress="10.0.0.2" protocol="17" sourcePort="49152" destinationPort="9000"/></Ipv4FlowClassifier></FlowMonitor>'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "flow.xml"
            path.write_text(xml, encoding="utf-8")
            self.assertEqual(ET.parse(path).getroot().tag, "FlowMonitor")
            self.assertAlmostEqual(analyze.percentile_from_xml(ET.parse(path).find("FlowStats/Flow"), 0.95), 1.5)


if __name__ == "__main__":
    unittest.main()
