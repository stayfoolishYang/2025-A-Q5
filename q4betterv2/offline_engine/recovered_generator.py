"""Executable reconstruction of Jammers practice-gen-v1 from the supplied PE.

This module needs the raw 32-byte generation seed (64 hex digits), not a case
identifier. It does not contact the official service or generate formal cases.
Only Python's standard library is required. See RECOVERY_REPORT.md for evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import re
import secrets
from pathlib import Path

MASK64 = (1 << 64) - 1
DOMAIN = b"practice-case-v1\x00"
UM_PER_M = 1_000_000
JAMMER_RADIUS_UM = 1_770_000_000
TAU = float.fromhex("0x1.921fb54442d18p+2")

GENERATION_RULES = {
    "generator_rules_version": "practice-gen-rules-v1",
    "target_area_radius_um": 1_800_000_000,
    "jammer_max_radius_um": JAMMER_RADIUS_UM,
    "outer_empty_ring_um": 30_000_000,
    "jammer_count_min": 10, "jammer_count_max": 16,
    "channel_min": 1, "channel_max": 20,
    "max_receive_min_um": 1_000_000_000,
    "max_receive_max_um": 1_500_000_000,
    "position_distribution": "uniform_disk_area",
    "max_receive_distribution": "uniform_integer_um",
    "problem4_directional_count_mode": "uniform_integer_one_to_count",
}
SIMULATION_RULES = {
    "simulation_rules_version": "simulation-rules-v1",
    "target_area_radius_um": 1_800_000_000,
    "near_distance_um": 5_000_000,
    "clear_distance_um": 20_000_000,
    "move_speed_um_per_s": 5_000_000,
    "channel_switch_duration_us": 1_000_000,
    "measure_duration_us": 5_000_000,
    "clear_success_duration_us": 5_000_000,
    "clear_failure_duration_us": 3_000_000,
    "max_virtual_duration_us": 360_000_000_000,
    "directional_beam_width_udeg": 180_000_000,
    "bearing_noise_model": "spatial-bearing-v1",
    "bearing_noise_grid_um": 150_000_000,
    "bearing_error_max_udeg": 1_000_000,
}


class CounterSource:
    """Separate deterministic HMAC-SHA256 counter for each exact label."""

    def __init__(self, seed: bytes, trace: list | None = None):
        if not isinstance(seed, bytes) or len(seed) != 32:
            raise ValueError("种子必须是 32 字节")
        self.seed = seed
        self.counters: dict[str, int] = {}
        self.trace = trace

    def next(self, label: str) -> int:
        counter = self.counters.get(label, 0)
        if counter == MASK64:
            raise OverflowError("counter exhausted")
        message = DOMAIN + label.encode("utf-8") + b"\x00" + counter.to_bytes(8, "big")
        digest = hmac.digest(self.seed, message, "sha256")
        value = int.from_bytes(digest[:8], "big")
        self.counters[label] = counter + 1
        if self.trace is not None:
            self.trace.append({"label": label, "counter": counter,
                               "message_hex": message.hex(), "hmac_sha256": digest.hex(),
                               "uint64": value})
        return value

    def uint_n(self, label: str, n: int) -> int:
        # The Go instruction negates a uint64 before taking the remainder.
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= (1 << 63):
            raise ValueError("n 必须位于 [1, 2^63]")
        threshold = ((-n) & MASK64) % n
        while True:
            value = self.next(label)
            if value >= threshold:
                return value % n

    def shuffle(self, label: str, values: list[int]) -> None:
        for i in range(len(values) - 1, 0, -1):
            j = self.uint_n(label, i + 1)
            values[i], values[j] = values[j], values[i]

    def unit_float(self, label: str) -> float:
        return float(self.next(label) >> 11) * (2.0 ** -53)


def go_round(value: float) -> int:
    """Nearest integer, halfway away from zero; no extra rounding via x + .5."""
    fraction, integral = math.modf(value)
    return int(integral) + (1 if fraction >= 0.5 else -1 if fraction <= -0.5 else 0)


# Exact binary64 coefficients read from this executable's math.Sincos tables.
_SIN = tuple(float.fromhex(x) for x in (
    "0x1.5d8fd1fd19ccdp-33", "-0x1.ae5e5a9291f5dp-26",
    "0x1.71de3567d48a1p-19", "-0x1.a01a019bfdf03p-13",
    "0x1.111111110f7d0p-7", "-0x1.5555555555548p-3"))
_COS = tuple(float.fromhex(x) for x in (
    "-0x1.8fa49a0861a9bp-37", "0x1.1ee9d7b4e3f05p-29",
    "-0x1.27e4f7eac4bc6p-22", "0x1.a01a019c844f5p-16",
    "-0x1.6c16c16c14f91p-10", "0x1.555555555554bp-5"))


def recovered_sincos(theta: float) -> tuple[float, float]:
    """Recovered small-argument branch, exactly the domain used by the generator.

    Evaluation order follows scalar SSE instructions; do not replace by an FMA
    or NumPy polynomial evaluation. This is not a general-purpose trig library.
    """
    if not math.isfinite(theta) or not 0 <= theta <= TAU:
        raise ValueError("本函数仅还原生成器使用的 [0, 2π] 分支")
    if theta == 0:
        return theta, 1.0
    octant = int(float.fromhex("0x1.45f306dc9c883p+0") * theta)
    multiple = float(octant)
    if octant & 1:
        octant += 1
        multiple += 1.0
    z = theta - float.fromhex("0x1.921fb40000000p-1") * multiple
    z = z - float.fromhex("0x1.4442d00000000p-25") * multiple
    z = z - float.fromhex("0x1.8469898cc5170p-49") * multiple
    octant &= 7
    sin_negative = octant > 3
    quadrant = octant - 4 if sin_negative else octant
    cos_negative = octant > 3
    if quadrant > 1:
        cos_negative = octant <= 3
    zz = z * z
    c = 1.0 - 0.5 * zz
    cp = _COS[0] * zz
    for coeff in _COS[1:-1]:
        cp = (cp + coeff) * zz
    cp = cp + _COS[-1]
    cp = cp * (zz * zz)
    sp = _SIN[0] * zz
    for coeff in _SIN[1:-1]:
        sp = (sp + coeff) * zz
    sp = sp + _SIN[-1]
    sp = sp * (z * zz)
    c = c + cp
    s = sp + z
    # The assembly exchanges temporaries again at return. Its net effect is
    # to exchange the sine/cosine polynomials for quadrants 1 and 2.
    if quadrant in (1, 2):
        s, c = c, s
    if cos_negative:
        c = -c
    if sin_negative:
        s = -s
    return s, c


def parse_seed(seed_hex: str) -> bytes:
    if not isinstance(seed_hex, str) or re.fullmatch(r"[0-9a-fA-F]{64}", seed_hex) is None:
        raise ValueError("需要 64 位十六进制原始种子；测试编号不能替代原始种子")
    return bytes.fromhex(seed_hex)


def generate_practice(seed_hex: str, problem: int = 3, *, trace: list | None = None) -> dict:
    if isinstance(problem, bool) or problem not in (3, 4):
        raise ValueError("问题编号必须是 3 或 4")
    seed = parse_seed(seed_hex)
    source = CounterSource(seed, trace)
    count = 10 + source.uint_n("count", 7)
    channels = list(range(1, 21))
    source.shuffle("channels", channels)
    channels = sorted(channels[:count])
    directional: set[int] = set()
    if problem == 4:
        directional_count = 1 + source.uint_n("directional-count", count)
        order = channels.copy()
        source.shuffle("directional-channels", order)
        directional = set(order[:directional_count])
    jammers = []
    for channel in channels:
        while True:
            r = math.sqrt(source.unit_float(f"jammer/{channel}/radius")) * float(JAMMER_RADIUS_UM)
            theta = source.unit_float(f"jammer/{channel}/theta") * TAU
            sine, cosine = recovered_sincos(theta)
            x_um, y_um = go_round(cosine * r), go_round(r * sine)
            if x_um * x_um + y_um * y_um <= JAMMER_RADIUS_UM ** 2:
                break
        receive_um = 1_000_000_000 + source.uint_n(f"jammer/{channel}/receive", 500_000_001)
        is_directional = channel in directional
        direction = source.uint_n(f"jammer/{channel}/direction", 360_000_000) if is_directional else None
        jammers.append({"channel": channel, "x_um": x_um, "y_um": y_um,
                        "max_receive_um": receive_um,
                        "kind": "directional" if is_directional else "omni",
                        "direction_udeg": direction})
    noise = source.next("noise-seed")
    # Field names/order and nullable fields are recovered from Go type metadata.
    # JSON byte-for-byte serialization equality has not been established.
    return {
        "schema_version": "scenario-v1", "ruleset_version": "rules-v1",
        "problem_no": problem, "source": "practice_generated", "dataset_version": None,
        "generator_version": "practice-gen-v1", "generator_seed_hex": seed.hex(),
        "noise_seed_hex": f"{noise:016x}", "generation_rules": GENERATION_RULES.copy(),
        "simulation_rules": SIMULATION_RULES.copy(), "jammers": jammers,
    }


def to_offline(scenario: dict) -> dict:
    """Convert our recovered generator output to the delivered offline v1 format."""
    return {
        "format": "jammers-offline-v1", "noise_seed_hex": scenario["noise_seed_hex"],
        "problem": scenario["problem_no"],
        "generator_seed": "practice-gen-v1:" + scenario["generator_seed_hex"],
        "jammers": [{"channel": j["channel"], "x": j["x_um"] / UM_PER_M,
                     "y": j["y_um"] / UM_PER_M,
                     "receive_radius_m": j["max_receive_um"] / UM_PER_M,
                     "kind": j["kind"], "direction_deg": (j["direction_udeg"] or 0) / UM_PER_M}
                    for j in scenario["jammers"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="已还原的原版演练场景生成器")
    seeds = parser.add_mutually_exclusive_group(required=True)
    seeds.add_argument("--seed-hex", help="32 字节原始种子，以 64 位十六进制表示")
    seeds.add_argument("--random-seed", action="store_true", help="本地随机生成 32 字节种子，并在场景中保留")
    parser.add_argument("--problem", type=int, choices=(3, 4), default=3)
    parser.add_argument("--format", choices=("native", "offline"), default="offline")
    parser.add_argument("--output", type=Path, help="不指定时输出至标准输出")
    parser.add_argument("--trace", type=Path, help="可选：记录每个标签的随机流")
    args = parser.parse_args()
    trace = [] if args.trace else None
    try:
        seed_hex = secrets.token_bytes(32).hex() if args.random_seed else args.seed_hex
        result = generate_practice(seed_hex, args.problem, trace=trace)
    except ValueError as exc:
        parser.error(str(exc))
    if args.format == "offline":
        result = to_offline(result)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    if args.trace:
        args.trace.parent.mkdir(parents=True, exist_ok=True)
        args.trace.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
