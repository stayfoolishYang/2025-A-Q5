"""Local history and formal-practice quotas. No official server state is used."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import uuid
import os


class DirectoryLock:
    """Prevent a second instance from recovering or changing a live run's store."""
    def __init__(self, root):
        self.file = (root / "application.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0, 2)
                if self.file.tell() == 0:
                    self.file.write(b"0"); self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ValueError("此记录目录已被另一个模拟器占用，请关闭已有实例或使用不同 --data-dir") from None

    def close(self):
        self.file.close()


class RunStore:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / "offline-state.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, mode TEXT NOT NULL, problem INTEGER NOT NULL,
              robot_id TEXT NOT NULL, batch_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
              metadata TEXT NOT NULL);
        """)
        defaults = {"robot_id": "offline-bot", "robot_port": 2026, "event_limit": 1000,
                    "practice_seed": "", "batch_id": uuid.uuid4().hex[:12]}
        for key, value in defaults.items():
            self.db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, json.dumps(value)))
        self.db.commit()
        self._recover()

    def settings(self):
        with self.lock:
            return {key: json.loads(value) for key, value in self.db.execute("SELECT key,value FROM settings")}

    def configure(self, values):
        with self.lock, self.db:
            for key, value in values.items():
                self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
        return self.settings()

    def attempts(self, robot_id):
        batch = self.settings()["batch_id"]
        with self.lock:
            result = {}
            for problem in (3, 4):
                used = self.db.execute("SELECT COUNT(*) FROM runs WHERE mode='formal' AND problem=? AND robot_id=? AND batch_id=?",
                                       (problem, robot_id, batch)).fetchone()[0]
                result[str(problem)] = {"used": used, "remaining": max(0, 3-used), "total": 3}
            return result

    def register(self, session):
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                count = self.db.execute("SELECT COUNT(*) FROM runs WHERE mode=? AND problem=? AND robot_id=? AND batch_id=?",
                                        (session.mode, session.engine.scenario.problem, session.robot_id, session.batch_id)).fetchone()[0]
                if session.mode == "formal" and count >= 3:
                    raise ValueError("本轮该问题的 3 次离线正式测试机会已用完")
                session.ordinal = count + 1
                info = session.metadata()
                self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (session.id, session.mode,
                                session.engine.scenario.problem, session.robot_id, session.batch_id,
                                session.ordinal, json.dumps(info, ensure_ascii=False)))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def update(self, info):
        with self.lock, self.db:
            self.db.execute("UPDATE runs SET metadata=? WHERE id=?", (json.dumps(info, ensure_ascii=False), info["run_id"]))

    @staticmethod
    def public(info):
        info = dict(info)
        if info.get("mode") == "formal" or info.get("phase") not in ("ended", "interrupted"):
            for key in ("source_count", "omni_count", "directional_count", "scenario", "seed", "noise_seed_hex"):
                info.pop(key, None)
        return info

    def history(self, robot_id):
        with self.lock:
            rows = self.db.execute("SELECT metadata FROM runs WHERE robot_id=? ORDER BY rowid DESC", (robot_id,)).fetchall()
            return [self.public(json.loads(row[0])) for row in rows]

    def get(self, run_id):
        with self.lock:
            row = self.db.execute("SELECT metadata FROM runs WHERE id=?", (run_id,)).fetchone()
            return self.public(json.loads(row[0])) if row else None

    def _recover(self):
        """Import v1.0 practice history and mark interrupted runs without refunding quotas."""
        with self.lock, self.db:
            known = {row[0] for row in self.db.execute("SELECT id FROM runs")}
            for path in self.root.glob("*/summary.json"):
                try:
                    info = json.loads(path.read_text(encoding="utf-8"))
                    run_id = info["run_id"]
                    if run_id in known or info.get("mode") == "formal":
                        continue
                    problem = info.get("problem")
                    if problem not in (3, 4):
                        problem = json.loads((path.parent / "scenario.json").read_text(encoding="utf-8"))["problem"]
                    info.update(mode="practice", problem=problem, batch_id="legacy", ordinal=0,
                                case_code=info.get("case_code", f"LOCAL-P{problem}-{run_id}"))
                    self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (run_id, "practice", problem,
                                    info.get("robot_id", "offline-bot"), "legacy", 0, json.dumps(info, ensure_ascii=False)))
                except (OSError, ValueError, KeyError, TypeError):
                    continue
            for run_id, raw in self.db.execute("SELECT id,metadata FROM runs").fetchall():
                info = json.loads(raw)
                if info.get("phase") in ("countdown", "ready", "running", "preparing"):
                    info.update(phase="interrupted", end_reason="process_interrupted", io_error="上次运行意外中断；已保留记录，请开始新测试。")
                    self.db.execute("UPDATE runs SET metadata=? WHERE id=?", (json.dumps(info, ensure_ascii=False), run_id))
                    try:
                        (self.root / run_id / "summary.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
                    except OSError:
                        pass

    def close(self):
        with self.lock:
            self.db.close()
