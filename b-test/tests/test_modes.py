import hashlib
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import zipfile

from engine import generate_scenario
from protocol import encode
from server import Manager, create_ui


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = Manager(self.root, 0, 10)

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def formal(self, problem=3):
        return self.manager.start({"mode": "formal", "problem": problem, "confirmed": True})

    def test_formal_requires_confirmation_and_rejects_custom_input(self):
        for body in [{"mode":"formal","problem":3},
                     {"mode":"formal","problem":3,"confirmed":True,"seed":"chosen"},
                     {"mode":"formal","problem":3,"confirmed":True,"scenario":None}]:
            with self.assertRaises(ValueError): self.manager.start(body)
        self.assertEqual(self.manager.snapshot()["attempts"]["3"]["remaining"],3)
        self.assertEqual(self.manager.store.history("offline-bot"),[])

    def test_three_opportunities_separate_per_problem(self):
        for index in range(1,4):
            run=self.formal(3)
            self.assertEqual(run["ordinal"],index)
            self.manager.abort()  # Includes aborting during countdown, before enter.
        with self.assertRaises(ValueError): self.formal(3)
        attempts=self.manager.snapshot()["attempts"]
        self.assertEqual(attempts["3"],{"used":3,"remaining":0,"total":3})
        self.assertEqual(attempts["4"]["remaining"],3)
        self.formal(4)
        self.assertEqual(self.manager.snapshot()["attempts"]["4"]["remaining"],2)

    def test_practice_unlimited_and_does_not_charge_formal(self):
        for _ in range(5):
            run=self.manager.start({"mode":"practice","problem":3,"seed":"same"})
            self.assertNotIn("source_count",run)
            self.assertFalse(run["counts_available"])
            self.manager.abort()
        self.assertEqual(self.manager.snapshot()["attempts"]["3"]["remaining"],3)
        self.assertEqual(len(self.manager.store.history("offline-bot")),5)

    def test_practice_reveals_counts_and_formal_never_reveals(self):
        self.manager.start({"mode":"practice","problem":4})
        self.manager.abort()
        practice=self.manager.snapshot()["session"]
        self.assertTrue(practice["counts_available"])
        self.assertEqual(practice["source_count"],practice["omni_count"]+practice["directional_count"])
        self.assertIn("scenario",practice)
        self.formal(4)
        self.manager.abort()
        formal=self.manager.snapshot()["session"]
        forbidden={"source_count","omni_count","directional_count","scenario","seed","noise_seed_hex"}
        for surface in [formal,self.manager.session.metadata(),self.manager.store.history("offline-bot")[0]]:
            self.assertFalse(forbidden & set(surface))
        self.assertFalse(formal["counts_available"])

    def test_formal_package_excludes_truth_and_has_valid_hashes(self):
        self.formal()
        self.manager.abort()
        session=self.manager.session
        with zipfile.ZipFile(session.directory/session.package_name) as archive:
            self.assertEqual(set(archive.namelist()),{"summary.json","events.jsonl","SHA256.json"})
            hashes=json.loads(archive.read("SHA256.json"))
            for name,digest in hashes.items():self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),digest)
            info=json.loads(archive.read("summary.json"))
            self.assertFalse(info["official_submission"])
            self.assertNotIn("source_count",info)
            self.assertNotIn("noise_seed_hex",archive.read("events.jsonl").decode())

    def test_restart_keeps_quota_and_history(self):
        run=self.formal(3);self.manager.abort()
        self.manager.close();self.manager=Manager(self.root,0,10)
        self.assertEqual(self.manager.snapshot()["attempts"]["3"]["remaining"],2)
        self.assertIsNone(self.manager.session)
        self.assertEqual(self.manager.store.history("offline-bot")[0]["case_code"],run["case_code"])

    def test_interrupted_run_stays_charged(self):
        self.formal(4)
        # Model a process loss before normal abort/cleanup, while still in countdown.
        self.manager.stop_event.set();self.manager.monitor.join(timeout=1)
        self.manager.reserved.server_close();self.manager.store.close();self.manager.directory_lock.close()
        self.manager=Manager(self.root,0,10)
        row=self.manager.store.history("offline-bot")[0]
        self.assertEqual(row["phase"],"interrupted")
        self.assertEqual(row["end_reason"],"process_interrupted")
        self.assertEqual(self.manager.snapshot()["attempts"]["4"]["remaining"],2)

    def test_new_local_round_retains_previous_history(self):
        run=self.formal();self.manager.abort()
        self.manager.new_batch()
        self.assertEqual(self.manager.snapshot()["attempts"]["3"]["remaining"],3)
        self.assertNotEqual(run["batch_id"],self.manager.snapshot()["settings"]["batch_id"])
        self.assertEqual(len(self.manager.store.history("offline-bot")),1)

    def test_busy_settings_and_invalid_settings_rejected(self):
        for values in [{"event_limit":99},{"event_limit":5001},{"robot_id":""},{"robot_port":True}]:
            with self.assertRaises(ValueError):self.manager.configure(values)
        self.manager.configure({"event_limit":150,"robot_id":"team-test","practice_seed":"fixed"})
        self.assertEqual(self.manager.snapshot()["settings"]["event_limit"],150)
        self.formal()
        with self.assertRaises(ValueError):self.manager.configure({"event_limit":200})
        with self.assertRaises(ValueError):self.manager.new_batch()

    def test_case_identity_and_module_match(self):
        with self.assertRaises(ValueError):
            self.manager.start({"problem":3,"scenario":generate_scenario("x",4).to_dict()})
        run=self.formal(3)
        self.assertTrue(run["case_code"].startswith("LOCAL-F3-"))
        with self.assertRaises(ValueError):self.formal(4)
        self.assertEqual(self.manager.snapshot()["attempts"]["4"]["remaining"],3)

    def test_port_unavailable_does_not_charge(self):
        self.manager.reserved.server_close();self.manager.reserved=None
        with socket.socket() as holder:
            holder.bind(("127.0.0.1",self.manager.robot_port));holder.listen(1)
            with self.assertRaises(ValueError):self.formal()
        self.assertEqual(self.manager.snapshot()["attempts"]["3"]["remaining"],3)

    def test_idle_reservation_and_clear_finished(self):
        with self.assertRaises(OSError):socket.create_connection(("127.0.0.1",self.manager.robot_port),timeout=.1)
        self.formal();self.manager.abort();self.manager.clear_finished()
        self.assertIsNone(self.manager.snapshot()["session"])
        self.assertEqual(len(self.manager.store.history("offline-bot")),1)

    def test_legacy_practice_history_is_preserved(self):
        self.manager.close()
        directory=self.root/"20260101-000000-legacy";directory.mkdir()
        (directory/"scenario.json").write_text(json.dumps(generate_scenario("legacy",4).to_dict()))
        (directory/"summary.json").write_text(json.dumps({"run_id":directory.name,"robot_id":"offline-bot","phase":"ended","source_count":12,"accepted_actions":3}))
        self.manager=Manager(self.root,0,10)
        row=self.manager.store.history("offline-bot")[0]
        self.assertEqual(row["mode"],"practice");self.assertEqual(row["problem"],4)
        self.assertEqual(row["source_count"],12)

    def test_second_instance_cannot_modify_live_run(self):
        self.formal()
        with self.assertRaises(ValueError): Manager(self.root,0,10)
        self.assertEqual(self.manager.store.history("offline-bot")[0]["phase"],"countdown")


class ModeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.manager=Manager(Path(self.temp.name),0,10)
        self.ui=create_ui(self.manager,0)
        self.thread=threading.Thread(target=self.ui.serve_forever,kwargs={"poll_interval":.01},daemon=True);self.thread.start()

    def tearDown(self):
        self.ui.shutdown();self.ui.server_close();self.thread.join();self.manager.close();self.temp.cleanup()

    def call(self,path,data=None):
        connection=http.client.HTTPConnection("127.0.0.1",self.ui.server_address[1],timeout=3)
        try:
            connection.request("GET" if data is None else "POST",path,None if data is None else encode(data),
                               {"Content-Type":"application/json","X-Jammers-Local":"1"})
            response=connection.getresponse();body=response.read()
            return response.status,body
        finally:connection.close()

    def test_formal_routes_truth_policy_and_history(self):
        status,body=self.call("/api/start",{"mode":"formal","problem":3,"confirmed":True})
        self.assertEqual(status,200);run=json.loads(body)
        self.assertEqual(self.call("/api/abort",{})[0],400)
        self.assertEqual(self.call("/api/abort",{"confirmed":True})[0],200)
        self.assertEqual(self.call("/api/export/scenario")[0],403)
        self.assertEqual(self.call(f'/api/runs/{run["run_id"]}/scenario')[0],403)
        self.assertEqual(self.call(f'/api/runs/{run["run_id"]}/package')[0],200)
        summary=json.loads(self.call(f'/api/runs/{run["run_id"]}/summary')[1])
        self.assertNotIn("source_count",summary)
        rows=json.loads(self.call("/api/history")[1])["runs"]
        self.assertEqual(rows[0]["mode"],"formal");self.assertNotIn("scenario",rows[0])

    def test_native_resources_and_control_confirmation(self):
        for path in ["/native.css","/logo.png","/ui-flow.js"]:
            status,body=self.call(path);self.assertEqual(status,200);self.assertTrue(body)
        self.assertEqual(self.call("/api/new-batch",{})[0],400)
        self.assertEqual(self.call("/api/new-batch",{"confirmed":True})[0],200)
        self.assertEqual(self.call("/api/configure",{"robot_port":self.ui.server_address[1]})[0],400)


if __name__=="__main__":unittest.main(verbosity=2)
