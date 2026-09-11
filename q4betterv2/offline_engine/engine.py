"""Independent local implementation of the documented Jammers simulation rules.

No original executable, authorization data, or service connection is used.
All positions are metres; accumulated virtual time is integer microseconds.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass

MAX_VIRTUAL_US = 360_000_000_000
MAX_REAL_S = 1200
WINDOW_S = 1500
COORD_LIMIT = 2_000_000


def go_round(value: float) -> int:
    """Round finite values to nearest integer, with ties away from zero."""
    # Splitting the integral and fractional parts avoids rounding x + 0.5 twice.
    fraction, integral = math.modf(value)
    return int(integral) + (1 if fraction >= .5 else -1 if fraction <= -.5 else 0)


def normalize(value: float) -> float:
    value = math.fmod(value, 360.0)
    if value < 0:
        value += 360.0
    return value if value != 0 else 0.0


def noise_grid(seed: int, channel: int, x: int, y: int) -> float:
    key = f"{seed}:{channel}:{x}:{y}".encode("ascii")
    number = int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")
    # Match the recovered Go uint64 -> float64 conversion, including its rounding.
    converted = float(number) if number < (1 << 63) else float((number >> 1) | (number & 1)) * 2
    return converted / 18446744073709551616.0 * 2 - 1


def bearing_error(seed: int, channel: int, x: float, y: float) -> float:
    gx, gy = x / 150.0, y / 150.0
    ix, iy = math.floor(gx), math.floor(gy)
    fx, fy = max(0., min(1., gx - ix)), max(0., min(1., gy - iy))
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = noise_grid(seed, channel, ix, iy)
    b = noise_grid(seed, channel, ix + 1, iy)
    c = noise_grid(seed, channel, ix, iy + 1)
    d = noise_grid(seed, channel, ix + 1, iy + 1)
    low, high = a + (b - a) * sx, c + (d - c) * sx
    return low + (high - low) * sy


def quantize_bearing(base: float, error: float) -> float:
    base = normalize(base)
    value = go_round((base + error) * 100)
    value = max(math.ceil((base - 1) * 100), min(math.floor((base + 1) * 100), value))
    return (value % 36000) / 100


def finite_number(value, label: str, limit: float = COORD_LIMIT) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label} 必须是数字")
    try:
        value = float(value)
    except OverflowError:
        raise ValueError(f"{label} 超出范围") from None
    if not math.isfinite(value) or abs(value) > limit:
        raise ValueError(f"{label} 超出范围")
    return value if value else 0.0


@dataclass(frozen=True)
class Jammer:
    channel: int
    x: float
    y: float
    receive_radius_m: float
    kind: str = "omni"
    direction_deg: float = 0.0


@dataclass(frozen=True)
class Scenario:
    noise_seed_hex: str
    problem: int
    jammers: tuple[Jammer, ...]
    generator_seed: str = "custom"

    def to_dict(self) -> dict:
        return {"format": "jammers-offline-v1", "noise_seed_hex": self.noise_seed_hex,
                "problem": self.problem, "generator_seed": self.generator_seed,
                "jammers": [asdict(item) for item in self.jammers]}

    @classmethod
    def from_dict(cls, data: dict) -> Scenario:
        if not isinstance(data, dict) or data.get("format") != "jammers-offline-v1":
            raise ValueError("场景格式必须是 jammers-offline-v1")
        allowed = {"format", "noise_seed_hex", "problem", "generator_seed", "jammers"}
        if set(data) - allowed:
            raise ValueError("场景包含未知字段")
        seed, problem = data.get("noise_seed_hex"), data.get("problem")
        if not isinstance(seed, str) or not re.fullmatch(r"[0-9a-fA-F]{16}", seed):
            raise ValueError("noise_seed_hex 必须是 16 位十六进制字符串")
        if isinstance(problem, bool) or problem not in (3, 4):
            raise ValueError("problem 必须是 3 或 4")
        items = data.get("jammers")
        if not isinstance(items, list) or not 1 <= len(items) <= 20:
            raise ValueError("自定义场景需要 1 至 20 个干扰源；标准演练生成 10 至 16 个")
        parsed, channels = [], set()
        for item in items:
            if not isinstance(item, dict) or set(item) - set(Jammer.__dataclass_fields__):
                raise ValueError("干扰源包含未知字段")
            channel = item.get("channel")
            if isinstance(channel, bool) or not isinstance(channel, int) or not 1 <= channel <= 20 or channel in channels:
                raise ValueError("干扰源频道必须为不重复的 1 至 20 整数")
            x, y = finite_number(item.get("x"), "x"), finite_number(item.get("y"), "y")
            if math.hypot(x, y) > 1800.000001:
                raise ValueError("干扰源必须位于半径 1800 米的区域内")
            radius = finite_number(item.get("receive_radius_m"), "接收半径")
            if not 1000 <= radius <= 1500:
                raise ValueError("接收半径必须为 1000 至 1500 米")
            kind = item.get("kind", "omni")
            if kind not in ("omni", "directional") or (problem == 3 and kind != "omni"):
                raise ValueError("kind 必须是 omni 或 directional；问题 3 只允许 omni")
            direction = finite_number(item.get("direction_deg", 0), "朝向", 360)
            if not 0 <= direction < 360:
                raise ValueError("朝向必须位于 [0, 360)")
            channels.add(channel)
            parsed.append(Jammer(channel, x, y, radius, kind, direction))
        label = data.get("generator_seed", "custom")
        if not isinstance(label, str) or len(label) > 256:
            raise ValueError("generator_seed 必须为不超过 256 字符的字符串")
        return cls(seed.lower(), int(problem), tuple(parsed), label)


def generate_scenario(seed: str, problem: int = 3) -> Scenario:
    """Text-seed convenience API backed by the recovered practice generator."""
    from scenario_io import generate_document
    return Scenario.from_dict(generate_document(seed=seed, problem=problem))


class Engine:
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.sources = {source.channel: source for source in scenario.jammers}
        self.noise_seed = int(scenario.noise_seed_hex, 16)
        self.x = self.y = 0.0
        self.channel = 1
        self.virtual_us = 0
        self.entered = False
        self.ended = False
        self.end_reason = None
        self.cleared: set[int] = set()

    def end(self, reason: str):
        if not self.ended:
            self.ended, self.end_reason = True, reason

    def apply(self, path: str, request: dict) -> dict:
        if self.ended:
            return {"accepted": False, "virtual_time_s": 0}
        if path == "/enter":
            if self.entered:
                return {"accepted": False, "virtual_time_s": 0}
            self.entered = True
            return {"accepted": True, "virtual_time_s": 0}
        if not self.entered:
            return {"accepted": False, "virtual_time_s": 0}
        if path == "/exit":
            self.end("user_exit")
            return {"accepted": True, "virtual_time_s": self.virtual_us / 1_000_000, "exit_reason": "user_exit"}
        if path not in ("/measure", "/clear"):
            raise ValueError("Unknown action")
        # API validation occurs before apply. This engine also defends direct callers.
        x = finite_number(request["position"]["x"], "x")
        y = finite_number(request["position"]["y"], "y")
        channel = request["channel"]
        if isinstance(channel, bool) or not isinstance(channel, int) or not 1 <= channel <= 20:
            raise ValueError("Invalid channel")
        movement = go_round((1e12 * math.hypot(x - self.x, y - self.y)) / 5_000_000)
        self.virtual_us += movement
        self.x, self.y = x, y
        source = self.sources.get(channel)
        distance = math.hypot(source.x - x, source.y - y) if source else math.inf
        available = source is not None and channel not in self.cleared
        if path == "/clear":
            success = available and distance <= 20
            self.virtual_us += 5_000_000 if success else 3_000_000
            if success:
                self.cleared.add(channel)
            result = {"clear_result": "success" if success else "no_target_in_range"}
        else:
            if channel != self.channel:
                self.virtual_us += 1_000_000
                self.channel = channel
            self.virtual_us += 5_000_000
            covered = available and distance <= source.receive_radius_m
            if covered and source.kind == "directional" and distance != 0:
                source_to_dog = normalize(math.atan2(y - source.y, x - source.x) * 180 / math.pi)
                angular_distance = abs((source_to_dog - source.direction_deg + 180) % 360 - 180)
                covered = angular_distance <= 90.000000001
            if not covered:
                result = {"measure_result": "no_signal"}
            elif distance <= 5:
                result = {"measure_result": "near"}
            else:
                base = normalize(math.atan2(source.y - y, source.x - x) * 180 / math.pi)
                result = {"measure_result": "direction", "svd_deg": quantize_bearing(
                    base, bearing_error(self.noise_seed, channel, x, y))}
        if self.virtual_us >= MAX_VIRTUAL_US:
            self.end("virtual_timeout")
        return {"accepted": True, "virtual_time_s": self.virtual_us / 1_000_000, **result}
