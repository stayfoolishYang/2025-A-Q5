"""Adapt recovered native scenes and explicit seed inputs to the offline engine."""
from __future__ import annotations

import hashlib
import re
import secrets

from recovered_generator import (GENERATION_RULES, SIMULATION_RULES,
                                 generate_practice, parse_seed, to_offline)


def seed_hex_from_inputs(*, seed=None, seed_hex=None):
    if seed is not None and seed_hex is not None:
        raise ValueError("seed 与 seed_hex 只能提供一个")
    if seed_hex is not None:
        return parse_seed(seed_hex).hex()
    if seed is None or seed == "":
        return secrets.token_hex(32)
    if not isinstance(seed, str) or len(seed) > 256:
        raise ValueError("文本 seed 必须是不超过 256 字符的字符串")
    # Text seeds are a convenience of this service, not an official case-code mapping.
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def generate_document(*, problem=3, seed=None, seed_hex=None, format="offline"):
    if type(problem) is not int or problem not in (3, 4):
        raise ValueError("problem 必须是整数 3 或 4")
    native = generate_practice(seed_hex_from_inputs(seed=seed, seed_hex=seed_hex), problem)
    if format == "native":
        return native
    if format != "offline":
        raise ValueError("format 必须为 native 或 offline")
    return to_offline(native)


def native_to_offline(data):
    """Validate a decoded scenario-v1 JSON document; encrypted packages aren't accepted."""
    required = {"schema_version", "ruleset_version", "problem_no", "source", "dataset_version",
                "generator_version", "generator_seed_hex", "noise_seed_hex", "generation_rules",
                "simulation_rules", "jammers"}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("scenario-v1 场景字段缺失或包含未知字段；不支持加密场景包")
    if data["schema_version"] != "scenario-v1" or data["ruleset_version"] != "rules-v1":
        raise ValueError("不支持的原版场景或规则版本")
    if type(data["problem_no"]) is not int or data["problem_no"] not in (3, 4):
        raise ValueError("problem_no 必须是整数 3 或 4")
    if not strict_equal(data["simulation_rules"], SIMULATION_RULES):
        raise ValueError("simulation_rules 与已恢复的默认仿真规则不一致")
    noise = data["noise_seed_hex"]
    if not isinstance(noise, str) or not re.fullmatch(r"[0-9a-f]{16}", noise):
        raise ValueError("noise_seed_hex 必须为 16 个小写十六进制字符")
    if data["source"] == "practice_generated":
        if data["dataset_version"] is not None or data["generator_version"] != "practice-gen-v1":
            raise ValueError("演练生成器元数据不合法")
        raw_seed = data["generator_seed_hex"]
        if not isinstance(raw_seed, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_seed):
            raise ValueError("generator_seed_hex 必须为 64 个小写十六进制字符")
        if not strict_equal(data["generation_rules"], GENERATION_RULES):
            raise ValueError("generation_rules 与默认演练生成规则不一致")
        label = "practice-gen-v1:" + raw_seed
    elif data["source"] == "formal_dataset":
        dataset = data["dataset_version"]
        if not isinstance(dataset, str) or not re.fullmatch(r"[a-z0-9._-]{1,32}", dataset):
            raise ValueError("正式来源需要合法的 dataset_version")
        if any(data[k] is not None for k in ("generator_version", "generator_seed_hex", "generation_rules")):
            raise ValueError("正式来源的生成器元数据必须为空")
        label = "imported-dataset:" + dataset
    else:
        raise ValueError("未知的场景 source")
    jammers = data["jammers"]
    if not isinstance(jammers, list) or not 10 <= len(jammers) <= 16:
        raise ValueError("原版场景需要 10 至 16 个干扰源")
    last_channel = directions = 0
    converted = []
    for j in jammers:
        if not isinstance(j, dict) or set(j) != {"channel", "x_um", "y_um", "max_receive_um", "kind", "direction_udeg"}:
            raise ValueError("原版干扰源字段不完整或存在未知字段")
        if any(type(j[k]) is not int for k in ("channel", "x_um", "y_um", "max_receive_um")):
            raise ValueError("原版频道、微米坐标与接收半径必须是整数")
        if not last_channel < j["channel"] <= 20:
            raise ValueError("原版频道必须在 1 至 20 内严格递增")
        last_channel = j["channel"]
        if j["x_um"] ** 2 + j["y_um"] ** 2 > 1_770_000_000 ** 2:
            raise ValueError("原版源位置超出 1770 米圆盘")
        if not 1_000_000_000 <= j["max_receive_um"] <= 1_500_000_000:
            raise ValueError("原版接收半径超出 1000 至 1500 米")
        angle = j["direction_udeg"]
        if j["kind"] == "omni":
            if angle is not None:
                raise ValueError("全向源的 direction_udeg 必须为空")
        elif j["kind"] == "directional":
            if type(angle) is not int or not 0 <= angle < 360_000_000:
                raise ValueError("direction_udeg 必须是 [0,360000000) 内的整数")
            directions += 1
        else:
            raise ValueError("未知的干扰源类型")
        converted.append({"channel": j["channel"], "x": j["x_um"] / 1_000_000,
                          "y": j["y_um"] / 1_000_000,
                          "receive_radius_m": j["max_receive_um"] / 1_000_000,
                          "kind": j["kind"], "direction_deg": (angle or 0) / 1_000_000})
    if (data["problem_no"] == 3 and directions) or (data["problem_no"] == 4 and not directions):
        raise ValueError("定向源数量不符合问题编号")
    return {"format": "jammers-offline-v1", "problem": data["problem_no"],
            "noise_seed_hex": noise, "generator_seed": label, "jammers": converted}


def strict_equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(b, dict):
        return set(a) == set(b) and all(strict_equal(a[k], b[k]) for k in b)
    return a == b


def load_scenario(data):
    from engine import Scenario
    if isinstance(data, dict) and data.get("schema_version") == "scenario-v1":
        data = native_to_offline(data)
    return Scenario.from_dict(data)
