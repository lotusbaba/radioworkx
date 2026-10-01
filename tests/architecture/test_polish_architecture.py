"""Architecture contracts; no application imports, services or credentials needed."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / 'architecture'
SCENARIO = 'Forty listeners with audio and SSE fit synthetic connection budget'


class PolishArchitectureTests(unittest.TestCase):
    def run_polish(self, name, *arguments):
        executable = os.environ.get('POLISH_BIN', 'polish')
        directory = Path(os.environ.get('POLISH_RESULTS_DIR', ROOT / 'runs/polish-ci'))
        directory.mkdir(parents=True, exist_ok=True)
        command = [executable, *map(str, arguments), '--json']
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
        (directory / f'{name}.json').write_text(result.stdout)
        (directory / f'{name}.stderr.txt').write_text(result.stderr)
        (directory / f'{name}.execution.json').write_text(json.dumps({
            'command': command, 'exit_code': result.returncode}, indent=2))
        data = json.loads(result.stdout)
        self.assertEqual(data.get('diagnostics'), [], data)
        return result.returncode, data

    def check_baseline(self, filename, expected_count):
        code, data = self.run_polish(filename, 'simulate', SPEC / filename)
        self.assertEqual(code, 0, data)
        self.assertIs(data['ok'], True)
        self.assertEqual(len(data['results']), expected_count)
        self.assertTrue(all(r['passed'] for r in data['results']), data)

    def test_functional_baseline(self):
        self.check_baseline('radioworkx.polishd', 13)

    def test_streaming_capacity_baseline(self):
        self.check_baseline('radioworkx-streaming-capacity.polishd', 3)

    def test_buffering_introduces_streaming_failure(self):
        baseline = SPEC / 'radioworkx-streaming-capacity.polishd'
        proposal = SPEC / 'radioworkx-buffering-proposal.polishd'
        old = b'load_balancer Proxy { supports_streaming = true response_buffering = false routes_to API }'
        new = old.replace(b'response_buffering = false', b'response_buffering = true')
        original = baseline.read_bytes()
        self.assertEqual(original.count(old), 1)
        # Exact byte comparison protects every expectation and all other declarations.
        self.assertEqual(proposal.read_bytes(), original.replace(old, new, 1))
        code, data = self.run_polish('buffering-plan', 'plan', baseline,
            '--proposed', proposal, '--scenario', SCENARIO)
        self.assertEqual(code, 1, 'Negative architecture plan must return exactly 1')
        self.assertIs(data['ok'], False)
        self.assertEqual(len(data['comparisons']), 1)
        comparison = data['comparisons'][0]
        self.assertEqual(comparison['scenario'], SCENARIO)
        self.assertEqual(comparison['status'], 'introduced')
        self.assertIs(comparison['before']['passed'], True)
        self.assertEqual(comparison['before']['outcome'], 'success')
        self.assertTrue({'Audio', 'Events'} <= set(comparison['before']['reached']))
        self.assertIs(comparison['after']['passed'], False)
        self.assertEqual(comparison['after']['outcome'], 'error')
        self.assertEqual(comparison['after']['error'], 'STREAMING_UNSUPPORTED')
        self.assertTrue(any(f.get('code') == 'STREAMING_UNSUPPORTED'
                            and f.get('status') == 'introduced'
                            and f.get('category') == 'required' for f in data['findings']))
        self.assertEqual([c['component'] for c in data['changes']['components']], ['Proxy'])
        self.assertEqual(data['changes']['added_edges'], [])
        self.assertEqual(data['changes']['removed_edges'], [])


if __name__ == '__main__':
    unittest.main()
