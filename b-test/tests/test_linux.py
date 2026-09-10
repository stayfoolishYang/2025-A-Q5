import base64
import copy
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from access import validate_bind
from client import APIError, ControlClient, RobotClient
from scenario_io import generate_document, load_scenario, seed_hex_from_inputs
from server import Manager, create_ui

FIXTURE = Path(__file__).parent / "fixtures/original_practice_q4.json"
SEED = bytes(range(32)).hex()
TOKEN = "linux-test-token-" + "a" * 32


class GeneratorAdapterTests(unittest.TestCase):
    def test_native_output_matches_prior_original_instruction_result(self):
        expected = json.loads(FIXTURE.read_text())
        self.assertEqual(generate_document(problem=4, seed_hex=SEED, format="native"), expected)

    def test_text_seeds_are_explicitly_hashed_and_not_confused_with_hex(self):
        self.assertEqual(seed_hex_from_inputs(seed="hello"), hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(seed_hex_from_inputs(seed_hex=SEED.upper()), SEED)
        self.assertNotEqual(seed_hex_from_inputs(seed=SEED), SEED)
        with self.assertRaises(ValueError): seed_hex_from_inputs(seed="hello", seed_hex=SEED)

    def test_all_directional_scene_remains_possible(self):
        seed = "b31d2f6ecf0c7b9f340ec3f739320e8f6e36a50ec3be20b6c5e6f20ca441f1f3"
        scene = load_scenario(generate_document(seed_hex=seed, problem=4, format="native"))
        self.assertTrue(all(j.kind == "directional" for j in scene.jammers))

    def test_native_import_matches_offline_output(self):
        native = generate_document(problem=4, seed_hex=SEED, format="native")
        self.assertEqual(load_scenario(native).to_dict(), generate_document(problem=4, seed_hex=SEED))

    def test_native_import_rejects_rules_and_boundary_changes(self):
        original = generate_document(problem=4, seed_hex=SEED, format="native")
        changes = [lambda d: d["jammers"][0].update(x_um=1_770_000_001, y_um=0),
                   lambda d: d.update(generator_seed_hex="bad"),
                   lambda d: d.update(problem_no=4.0),
                   lambda d: d["simulation_rules"].update(target_area_radius_um=True),
                   lambda d: d["jammers"][0].update(channel=True),
                   lambda d: d.update(unrecognized=True)]
        for change in changes:
            data = copy.deepcopy(original); change(data)
            with self.assertRaises(ValueError): load_scenario(data)

    def test_decoded_dataset_requires_empty_generator_metadata(self):
        data = generate_document(problem=4, seed_hex=SEED, format="native")
        data.update(source="formal_dataset", dataset_version="synthetic-test-v1")
        with self.assertRaises(ValueError): load_scenario(data)
        data.update(generator_version=None, generator_seed_hex=None, generation_rules=None)
        scene = load_scenario(data)
        self.assertEqual(scene.generator_seed, "imported-dataset:synthetic-test-v1")

    def test_remote_binding_requires_token(self):
        with self.assertRaises(ValueError): validate_bind("0.0.0.0", None)
        self.assertEqual(validate_bind("0.0.0.0", TOKEN), "0.0.0.0")


class AuthenticatedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = Manager(Path(self.temp.name), 0, 0, access_token=TOKEN)
        self.ui = create_ui(self.manager, 0)
        self.worker = threading.Thread(target=self.ui.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.ui.server_address[1]}"
        self.control = ControlClient(self.url, TOKEN)
        self.robot = RobotClient(f"http://127.0.0.1:{self.manager.robot_port}", token=TOKEN)

    def tearDown(self):
        self.ui.shutdown(); self.ui.server_close(); self.worker.join()
        self.manager.close(); self.temp.cleanup()

    def test_control_and_robot_authentication_and_retries(self):
        for token in (None, "wrong-token"):
            with self.assertRaises(APIError) as error: ControlClient(self.url, token).status()
            self.assertEqual(error.exception.status, 401)
        self.assertTrue(self.control.call("/healthz")["ok"])
        self.control.start(problem=4, seed_hex=SEED, wait=3)
        with self.assertRaises(APIError) as error:
            RobotClient(self.robot.url).enter(request_id="enter")
        self.assertEqual(error.exception.status, 401)
        first = self.robot.enter(request_id="enter")
        self.assertEqual(first, self.robot.enter(request_id="enter"))
        self.robot.measure(100, 200, 1, request_id="measure")
        self.robot.exit()

    def test_service_generator_exact_native_fields_and_import(self):
        data = self.control.call("/api/generate", {"problem": 4, "seed_hex": SEED, "format": "native"})
        self.assertEqual(data, json.loads(FIXTURE.read_text()))
        run = self.control.start(problem=4, scenario=data, wait=3)
        self.robot.enter(); self.robot.exit()
        scene = self.control.call(f'/api/runs/{run["run_id"]}/scenario')
        self.assertEqual(scene, load_scenario(data).to_dict())

    def test_basic_browser_login_and_same_origin_policy(self):
        header = "Basic " + base64.b64encode(("jammers:" + TOKEN).encode()).decode()
        conn = http.client.HTTPConnection("127.0.0.1", self.ui.server_address[1], timeout=3)
        conn.request("GET", "/", headers={"Authorization": header, "Host": "server.test:2027"})
        response = conn.getresponse(); self.assertEqual(response.status, 200); self.assertIn(b"<html", response.read()); conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", self.ui.server_address[1], timeout=3)
        conn.request("POST", "/api/start", b'{}', headers={"Authorization": header, "Host": "server.test:2027",
                     "Origin": "http://other.test", "X-Jammers-Local": "1", "Content-Type": "application/json"})
        response = conn.getresponse(); self.assertEqual(response.status, 403); response.read(); conn.close()
        self.assertIsNone(self.manager.session)

    def test_control_rejects_bad_payload_and_seed_conflict(self):
        for payload in ([], {"seed": "x", "seed_hex": SEED}, {"problem": True}, {"format": "bad"}):
            with self.assertRaises(APIError) as error: self.control.call("/api/generate", payload)
            self.assertEqual(error.exception.status, 400)
        with self.assertRaises(APIError):
            self.control.start(mode="formal", problem=4, seed_hex=SEED, confirmed=True)
        self.assertEqual(self.control.status()["attempts"]["4"]["remaining"], 3)
