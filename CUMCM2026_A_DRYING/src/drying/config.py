"""Finite, serializable run contract for A26-04-v2 (SI units)."""
from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class RunConfig:
    route: str = "B"
    question: int = 23
    nr: int = 20
    nz: int = 1
    geometry: str = "fixed"
    end_condition: str = "C0"
    scenario: str = "S0"
    radius_method: str = "linear"
    radius_tail: str = "NONE"
    window_start_h: float = 3.0
    tmax: float = 259200.0
    wall_seconds: float = 3600.0
    max_steps: int = 500000
    rtol: float = 1e-6
    atol_t: float = 1e-6
    atol_c: float = 1e-9
    h0: float = 0.1
    hmax: float = 60.0
    newton_tol: float = 1e-3
    linear_tol: float = 1e-8
    checkpoint_steps: int = 500
    max_output_rows: int = 1048575
    memory_mb: int = 2048
    execution_backend: str = "LOCAL_DEV"
    execution_purpose: str = "FRAMEWORK_INTEGRATION"
    production_eligible: bool = False
    seed: int = 20260910
    test_case: str | None = None
    case_end_time: float | None = None
    model_version: str = "A26-04-v2"
    input_version: str = "A26-INPUT-v1"

    def __post_init__(self):
        allowed = {"route": {"B", "C"}, "question": {1, 23, 4},
                   "geometry": {"fixed", "moving"}, "end_condition": {"C0", "C1"},
                   "scenario": {"S0", "S1"}, "radius_method": {"linear", "pchip"},
                   "radius_tail": {"NONE", "HOLD"}}
        for name, choices in allowed.items():
            if getattr(self, name) not in choices:
                raise ValueError(f"CONFIG_INVALID: {name} must be one of {sorted(choices)}")
        for name in ("nr", "nz", "max_steps", "checkpoint_steps", "max_output_rows", "memory_mb"):
            v = getattr(self, name)
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise ValueError(f"CONFIG_INVALID: {name} must be a positive integer")
        if self.nr < 2:
            raise ValueError("CONFIG_INVALID: nr >= 2 required for axis reconstruction")
        if self.route == "B" and (self.nz != 1 or self.end_condition != "C0"):
            raise ValueError("CONFIG_INVALID: B requires nz=1 and end_condition=C0")
        if self.route == "C" and self.nz < 2:
            raise ValueError("CONFIG_INVALID: C requires nz >= 2")
        for name in ("tmax", "wall_seconds", "rtol", "atol_t", "atol_c", "h0", "hmax", "newton_tol", "linear_tol"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v <= 0:
                raise ValueError(f"CONFIG_INVALID: {name} must be positive and finite")
        if self.h0 > self.hmax or self.h0 > 0.1 or self.hmax > 60:
            raise ValueError("CONFIG_INVALID: require h0 <= 0.1 and h0 <= hmax <= 60 seconds")
        if self.window_start_h not in (2.5, 3.0, 3.5):
            raise ValueError("CONFIG_INVALID: approved S0 windows begin at 2.5, 3, or 3.5 hours")
        if self.scenario == "S1" and self.window_start_h != 3.0:
            raise ValueError("CONFIG_INVALID: window sensitivity applies to S0 only")
        if self.geometry == "moving" and self.question != 4 and self.test_case is None:
            raise ValueError("CONFIG_INVALID: formal moving geometry uses question=4")
        if self.geometry == "moving" and self.radius_tail == "NONE" and self.tmax > 259200:
            raise ValueError("CONFIG_INVALID: moving input ends at 259200 s; explicit HOLD required beyond it")
        if self.radius_tail == "HOLD" and (self.geometry != "moving" or self.tmax <= 259200):
            raise ValueError("CONFIG_INVALID: HOLD requires moving geometry and finite tmax > 259200")
        if self.case_end_time is not None and (not math.isfinite(self.case_end_time) or not 0 < self.case_end_time <= self.tmax):
            raise ValueError("CONFIG_INVALID: case_end_time must be within (0,tmax]")
        if self.test_case is not None and (not isinstance(self.test_case, str) or not self.test_case):
            raise ValueError("CONFIG_INVALID: test_case must be a nonempty name")
        if self.execution_backend not in {"LOCAL_DEV", "REMOTE_SERVER"}:
            raise ValueError("CONFIG_INVALID: unknown execution backend")
        if self.execution_purpose not in {"FRAMEWORK_INTEGRATION", "PRODUCTION", "TEST_ONLY", "SMOKE"}:
            raise ValueError("CONFIG_INVALID: unknown execution purpose")
        if not isinstance(self.production_eligible, bool):
            raise ValueError("CONFIG_INVALID: production_eligible must be boolean")
        if self.production_eligible and (self.execution_backend != "REMOTE_SERVER" or self.execution_purpose != "PRODUCTION" or self.test_case is not None):
            raise ValueError("CONFIG_INVALID: production eligibility requires remote production and no TEST_CASE")
        if self.test_case is not None and self.execution_purpose != "TEST_ONLY":
            raise ValueError("CONFIG_INVALID: synthetic test_case requires TEST_ONLY purpose")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ValueError("CONFIG_INVALID: seed must be a nonnegative integer")
        if self.max_output_rows > 1048575:
            raise ValueError("CONFIG_INVALID: output exceeds Excel capacity after header")
        if self.model_version != "A26-04-v2" or self.input_version != "A26-INPUT-v1":
            raise ValueError("CONFIG_INVALID: unsupported authority version")

    def as_dict(self):
        return asdict(self)

    @property
    def fingerprint(self):
        return sha256(json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    @classmethod
    def from_dict(cls, values):
        values = dict(values)
        unknown = set(values) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"CONFIG_INVALID: unknown fields {sorted(unknown)}")
        if values.get("radius_tail") == "R_EXT_HOLD":
            values["radius_tail"] = "HOLD"
        return cls(**values)

    @classmethod
    def from_json(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    def to_json(self, path):
        Path(path).write_text(json.dumps(self.as_dict(), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
