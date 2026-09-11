import concurrent.futures
import hashlib
import http.client
import json
import math
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from engine import (Engine, Jammer, Scenario, MAX_VIRTUAL_US, bearing_error, generate_scenario,
                    go_round, noise_grid, normalize, quantize_bearing)
from protocol import Rejected, check_media, decode_json, encode, fingerprint, normalize_request
from server import LocalServer, Manager, RobotHandler, Session, create_ui


def scene(*sources, problem=4):
    return Scenario("0123456789abcdef", problem, tuple(sources))


def request(key="one", x=None, y=0, channel=1, robot_id="offline-bot"):
    data = {"arena_id": "default", "robot_id": robot_id, "request_id": key}
    if x is not None:
        data.update(position={"x": x, "y": y}, channel=channel)
    return data


def entered(scenario):
    engine = Engine(scenario)
    engine.apply("/enter", request())
    return engine


class EngineTests(unittest.TestCase):
    def test_documented_timing_sequence(self):
        engine = entered(scene(Jammer(1, -1000, -1000, 1200)))
        actual = [engine.apply(path, request(str(i), *values))["virtual_time_s"] for i, (path, values) in enumerate([
            ("/measure", (300, 400, 1)), ("/measure", (300, 400, 2)),
            ("/clear", (300, 0, 3)), ("/measure", (300, 0, 2))])]
        self.assertEqual(actual, [105, 111, 194, 199])
        self.assertEqual(engine.apply("/exit", request())["virtual_time_s"], 199)

    def test_near_threshold_and_radius_inclusive(self):
        for distance, expected in [(0, "near"), (5, "near"), (5.000001, "direction"),
                                   (1500, "direction"), (1500.000001, "no_signal")]:
            with self.subTest(distance=distance):
                result = entered(scene(Jammer(1, 0, 0, 1500))).apply("/measure", request(x=distance))
                self.assertEqual(result["measure_result"], expected)
                self.assertEqual("svd_deg" in result, expected == "direction")

    def test_directional_boundaries_and_clear_ignores_facing(self):
        source = Jammer(1, 0, 0, 1500, "directional", 0)
        for x, y, expected in [(10, 0, "direction"), (0, 10, "direction"), (0, -10, "direction"),
                               (-10, 0, "no_signal"), (-1, 0, "no_signal"), (0, 0, "near")]:
            with self.subTest(x=x, y=y):
                engine = entered(scene(source))
                self.assertEqual(engine.apply("/measure", request(x=x, y=y))["measure_result"], expected)
        engine = entered(scene(source))
        self.assertEqual(engine.apply("/clear", request(x=-20))["clear_result"], "success")

    def test_clear_boundary_repeat_and_channel(self):
        engine = entered(scene(Jammer(3, 0, 0, 1000)))
        self.assertEqual(engine.apply("/clear", request(x=20.000001, channel=3))["clear_result"], "no_target_in_range")
        self.assertEqual(engine.apply("/clear", request(x=20, channel=3))["clear_result"], "success")
        self.assertEqual(engine.channel, 1)
        self.assertFalse(engine.ended)  # All sources cleared still requires exit or a deadline.
        before = engine.virtual_us
        self.assertEqual(engine.apply("/clear", request(x=20, channel=3))["clear_result"], "no_target_in_range")
        self.assertEqual(engine.virtual_us - before, 3_000_000)
        self.assertEqual(engine.apply("/measure", request(x=20, channel=3))["measure_result"], "no_signal")

    def test_movement_rounds_each_action_to_microseconds(self):
        engine = entered(scene(Jammer(1, 1000, 0, 1000)))
        engine.apply("/measure", request(x=.0000025))
        self.assertEqual(engine.virtual_us, 5_000_001)
        engine.apply("/measure", request(x=0))
        self.assertEqual(engine.virtual_us, 10_000_002)
        for value, expected in [(0.5,1),(-0.5,-1),(1.5,2),(-1.5,-2),(.49999999999999994,0)]:
            self.assertEqual(go_round(value),expected)

    def test_virtual_limit_completes_action(self):
        engine = entered(scene(Jammer(1, 0, 0, 1000)))
        engine.virtual_us = MAX_VIRTUAL_US - 5_000_000
        result = engine.apply("/measure", request(x=0))
        self.assertTrue(result["accepted"])
        self.assertEqual(result["virtual_time_s"], 360000)
        self.assertEqual(engine.end_reason, "virtual_timeout")
        self.assertFalse(engine.apply("/exit", request())["accepted"])
        engine = entered(scene(Jammer(1, 0, 0, 1000)))
        result = engine.apply("/measure", request(x=2_000_000))
        self.assertEqual(result["virtual_time_s"], 400005)

    def test_requires_enter_and_rejects_second_enter(self):
        engine = Engine(scene(Jammer(1, 0, 0, 1000)))
        self.assertFalse(engine.apply("/measure", request(x=0))["accepted"])
        self.assertTrue(engine.apply("/enter", request())["accepted"])
        self.assertFalse(engine.apply("/enter", request())["accepted"])

    def test_noise_is_position_stable_smooth_and_bounded(self):
        seed = int("0123456789abcdef",16)
        fixed = bearing_error(seed, 5, -237.8, 410.12)
        self.assertEqual(fixed, bearing_error(seed,5,-237.8,410.12))
        self.assertLess(abs(fixed-bearing_error(seed,5,-237.800001,410.12)),1e-6)
        self.assertNotEqual(fixed,bearing_error(seed,6,-237.8,410.12))
        for ch in range(1,21):
            for x,y in [(0,0),(-150,-300),(149.999,0),(2e6,-2e6),(230.123,891.77)]:
                self.assertLessEqual(abs(bearing_error(seed,ch,x,y)),1)
        self.assertAlmostEqual(bearing_error(seed,5,-150,-300),noise_grid(seed,5,-1,-2))

    def test_noise_digest_format_endian_and_unsigned_conversion(self):
        seed = 18446744073709551615
        digest = hashlib.blake2b(b"18446744073709551615:20:-1:2",digest_size=8).digest()
        unsigned = int(digest.hex(),16)
        number = float(unsigned) if unsigned < 2**63 else 2*float((unsigned//2)|(unsigned%2))
        self.assertEqual(noise_grid(seed,20,-1,2),number/(2**64)*2-1)

    def test_bearing_wrap_and_rounding(self):
        # 1.00 would exceed base + 1 degree, so the original clamp yields 0.99.
        self.assertEqual(quantize_bearing(359.999,1),.99)
        self.assertEqual(quantize_bearing(0,-1),359)
        self.assertEqual(quantize_bearing(12,.125),12.13)
        self.assertEqual(normalize(-360),0)
        for base in [0,.001,.005,45.1,179.999,359.995]:
            for err in [-1,-.125,0,.125,1]:
                value=quantize_bearing(base,err)
                self.assertTrue(0<=value<360)
                self.assertLessEqual(abs((value-base+180)%360-180),1.0000000001)

    def test_generated_scenes_repeat_and_validate(self):
        for problem in (3,4):
            first=generate_scenario("repeatable",problem)
            self.assertEqual(first,generate_scenario("repeatable",problem))
            self.assertEqual(first,Scenario.from_dict(first.to_dict()))
            self.assertTrue(10<=len(first.jammers)<=16)
            kinds={j.kind for j in first.jammers}
            if problem == 3:
                self.assertEqual(kinds, {"omni"})
            else:
                self.assertIn("directional", kinds)  # Original generator allows all-directional Q4.
            self.assertTrue(all(math.hypot(j.x,j.y)<=1770.000001 for j in first.jammers))

    def test_invalid_custom_scenes(self):
        for field,value in [("channel",True),("channel",21),("x",1801),("receive_radius_m",999),("direction_deg",360),("kind","other")]:
            data=scene(Jammer(1,0,0,1000)).to_dict()
            data["jammers"][0][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                Scenario.from_dict(data)


class ProtocolTests(unittest.TestCase):
    def test_media_types(self):
        for media in ["application/json", "Application/JSON; charset=UTF-8",'application/json; charset="utf-8"']:
            check_media(media,"identity")
        for media,encoding in [("text/plain",""),("application/json; charset=utf-16",""),("application/json; q=1",""),("application/json","gzip")]:
            with self.assertRaises(Rejected) as caught: check_media(media,encoding)
            self.assertEqual(caught.exception.status,415)

    def test_malformed_json_duplicate_keys_and_utf8(self):
        for body in [b'[]',b'{} {}',b'{"x":1,"x":2}',b'{"x":{"y":1,"y":2}}',b'\xef\xbb\xbf{}',
                     b'{"x":NaN}',b'{"x":1e9999}',b'{"x":"\xff"}',b'{"x":"\\ud800"}']:
            with self.subTest(body=body), self.assertRaises(Rejected) as caught: decode_json(body)
            self.assertEqual(caught.exception.status,400)

    def test_body_and_depth_limits(self):
        with self.assertRaises(Rejected) as caught: decode_json(b" "*65537)
        self.assertEqual(caught.exception.status,413)
        decode_json(b'{"x":'+b'['*15+b'0'+b']'*15+b'}')
        with self.assertRaises(Rejected): decode_json(b'{"x":'+b'['*16+b'0'+b']'*16+b'}')

    def test_normalized_numeric_equivalence(self):
        a=normalize_request("/measure",request(x=0,y=-0.0,channel=1))
        b=normalize_request("/measure",request(x=0.0,y=0,channel=1.0))
        self.assertEqual(fingerprint("/measure",a),fingerprint("/measure",b))

    def test_invalid_schema_and_unknown_fields(self):
        for value in [True,1.5,0,21,"1",None]:
            with self.assertRaises(Rejected) as caught: normalize_request("/measure",request(x=0,channel=value))
            self.assertEqual(caught.exception.status,400)
        for x in [True,2_000_001,-2_000_001,float("inf"),"1"]:
            with self.assertRaises(Rejected): normalize_request("/measure",request(x=x))
        for key in ["", "a"*129,"bad\u200bkey","bad\nkey"]:
            with self.assertRaises(Rejected): normalize_request("/enter",request(key))
        data=request();data["extra"]=1
        with self.assertRaises(Rejected) as caught: normalize_request("/enter",data)
        self.assertEqual(caught.exception.status,200)
        data=request(x=0);data["position"]["z"]=0
        with self.assertRaises(Rejected) as caught: normalize_request("/measure",data)
        self.assertEqual(caught.exception.status,200)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.session=Session(scene(Jammer(1,1000,1000,1000)),"offline-bot",Path(self.temp.name),0)
        self.session.opened_now()

    def tearDown(self):
        self.session.abort()
        self.temp.cleanup()

    def execute(self,path,data):
        status,body,owner=self.session.execute(path,normalize_request(path,data))
        if owner:self.session.published()
        return status,json.loads(body),body

    def test_idempotent_full_response_and_conflict(self):
        a=self.execute("/enter",request())
        b=self.execute("/enter",request())
        self.assertEqual(a[2],b[2])
        self.assertEqual(self.session.total_actions,1)
        self.assertEqual(self.execute("/exit",request())[0],409)
        self.execute("/measure",request("m",10))
        old=self.session.engine.virtual_us
        self.assertTrue(self.execute("/measure",request("m",10.0))[1]["accepted"])
        self.assertEqual(self.session.engine.virtual_us,old)

    def test_bad_identity_does_not_consume_id(self):
        rejected=self.execute("/enter",request(robot_id="other"))[1]
        self.assertFalse(rejected["accepted"])
        self.assertEqual(set(rejected),{"accepted","real_timestamp_ms","virtual_time_s"})
        self.assertTrue(self.execute("/enter",request())[1]["accepted"])

    def test_new_concurrent_action_rejected_same_action_waits(self):
        data=normalize_request("/enter",request())
        status,body,owner=self.session.execute("/enter",data)
        self.assertTrue(owner)
        self.assertEqual(self.session.execute("/exit",request("other"))[0],409)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.session.execute,"/enter",data)
            with self.assertRaises(concurrent.futures.TimeoutError):future.result(timeout=.05)
            self.session.published()
            self.assertEqual(future.result(timeout=1)[1],body)
        self.assertEqual(self.session.total_actions,1)

    def test_remaining_time_and_deadlines(self):
        self.assertEqual(self.execute("/enter",request())[1]["remaining_real_duration_s"],1200)
        self.session.check_clock(self.session.entered_at+1200)
        self.assertEqual(self.session.engine.end_reason,"program_timeout")

    def test_late_entry_uses_window_remainder(self):
        self.session.opened=time.monotonic()-1400
        remaining=self.execute("/enter",request())[1]["remaining_real_duration_s"]
        self.assertTrue(98<=remaining<=100)
        self.session.check_clock(self.session.opened+1500)
        self.assertEqual(self.session.engine.end_reason,"window_timeout_running")

    def test_window_timeout_before_enter(self):
        self.session.check_clock(self.session.opened+1500)
        self.assertEqual(self.session.engine.end_reason,"window_timeout_before_enter")
        self.assertFalse(self.execute("/enter",request())[1]["accepted"])

    def test_cache_limit_and_durable_logs(self):
        self.session.cache_limit=1
        self.execute("/enter",request())
        self.assertEqual(self.execute("/measure",request("m",0))[0],429)
        self.assertTrue(self.execute("/enter",request())[1]["accepted"])
        self.session.abort()
        summary=json.loads((self.session.directory/"summary.json").read_text())
        self.assertEqual(summary["accepted_actions"],1)
        events=[json.loads(line) for line in self.session.logfile.read_text().splitlines()]
        self.assertEqual([e["event"] for e in events],["action","session_end"])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.session=Session(scene(Jammer(1,-1000,-1000,1000)),"offline-bot",Path(self.temp.name),0)
        self.session.opened_now()
        self.server=LocalServer(("127.0.0.1",0),RobotHandler)
        self.server.session=self.session
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={"poll_interval":.01},daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.session.abort();self.temp.cleanup()

    def http(self,path,data=None,method="POST",headers=None,raw=None,chunked=False):
        connection=http.client.HTTPConnection("127.0.0.1",self.server.server_address[1],timeout=3)
        body=raw if raw is not None else encode(data or request())
        headers={"Content-Type":"application/json",**(headers or {})}
        if chunked:
            body=iter([body[:7],body[7:]])
        try:
            connection.request(method,path,body,headers,encode_chunked=chunked)
            response=connection.getresponse()
            rawbody=response.read()
            return response.status,json.loads(rawbody),rawbody
        finally:connection.close()

    def test_full_http_lifecycle_and_retries(self):
        self.assertTrue(self.http("/enter")[1]["accepted"])
        first=self.http("/measure",request("m",300,400,1))
        self.assertEqual(first[1]["virtual_time_s"],105)
        self.assertEqual(self.http("/measure",request("m",300.0,400,1.0))[2],first[2])
        self.assertEqual(self.http("/measure",request("m",301,400,1))[0],409)
        self.assertEqual(self.http("/exit",request("out"))[1]["exit_reason"],"user_exit")

    def test_paths_methods_media_and_size(self):
        for path in ["/enter/","/enter?x=1","/ENTER","/missing"]:
            self.assertEqual(self.http(path)[0],404)
        for method in ["GET","PUT","OPTIONS","CUSTOM"]:
            self.assertEqual(self.http("/enter",method=method)[0],405)
        self.assertEqual(self.http("/enter",headers={"Content-Type":"text/plain"})[0],415)
        self.assertEqual(self.http("/enter",raw=b" "*65537)[0],413)

    def test_chunked_utf8_json_and_unknown_fields(self):
        bad=request();bad["debug"]=True
        self.assertFalse(self.http("/enter",bad)[1]["accepted"])
        self.assertTrue(self.http("/enter",chunked=True)[1]["accepted"])


class LifecycleTests(unittest.TestCase):
    @staticmethod
    def wait_for(predicate):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.01)
        raise AssertionError("lifecycle transition timed out")

    def test_listener_only_opens_during_active_run(self):
        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1",0));port=probe.getsockname()[1]
            manager=Manager(Path(directory),port,.15)
            try:
                manager.start({"seed":"lifecycle","robot_id":"offline-bot"})
                with self.assertRaises(OSError):socket.create_connection(("127.0.0.1",port),timeout=.1)
                self.wait_for(lambda:manager.snapshot()["port_open"])
                connection=http.client.HTTPConnection("127.0.0.1",port,timeout=2)
                connection.request("POST","/enter",encode(request()),{"Content-Type":"application/json"})
                self.assertTrue(json.loads(connection.getresponse().read())["accepted"]);connection.close()
                connection=http.client.HTTPConnection("127.0.0.1",port,timeout=2)
                connection.request("POST","/exit",encode(request("exit")),{"Content-Type":"application/json"})
                self.assertEqual(json.loads(connection.getresponse().read())["exit_reason"],"user_exit");connection.close()
                self.wait_for(lambda:manager.robot_server is None and not manager.closing_listener)
                with self.assertRaises(OSError):socket.create_connection(("127.0.0.1",port),timeout=.1)
                manager.start({"seed":"second"})
                self.wait_for(lambda:manager.snapshot()["port_open"])
            finally:manager.close()

    def test_ui_assets_and_local_origin_control(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=Manager(Path(directory),0,0)
            ui=create_ui(manager,0)
            thread=threading.Thread(target=ui.serve_forever,kwargs={"poll_interval":.01},daemon=True);thread.start()
            try:
                for path in ["/","/app.js","/style.css","/api/status"]:
                    connection=http.client.HTTPConnection("127.0.0.1",ui.server_address[1],timeout=2)
                    connection.request("GET",path);response=connection.getresponse()
                    self.assertEqual(response.status,200);self.assertTrue(response.read());connection.close()
                connection=http.client.HTTPConnection("127.0.0.1",ui.server_address[1],timeout=2)
                connection.request("POST","/api/start",b"{}",{"Content-Type":"application/json"})
                response=connection.getresponse();self.assertEqual(response.status,403);response.read();connection.close()
            finally:ui.shutdown();ui.server_close();thread.join();manager.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
