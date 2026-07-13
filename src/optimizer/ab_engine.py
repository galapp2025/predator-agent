"""A/B Engine — Bayesian bandit על (neighborhood × age × gender) → persona/tactic/speed"""

from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("ab-engine")

ArmKey = Tuple[str, str, float]  # (persona, tactic, speed)


@dataclass
class BetaArm:
    persona: str
    tactic: str
    speed: float
    alpha: float = 1.0  # successes + 1
    beta: float = 1.0  # failures + 1

    @property
    def key(self) -> ArmKey:
        return (self.persona, self.tactic, round(self.speed, 2))

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    def sample(self) -> float:
        # Thompson sampling — Beta(α, β)
        return random.betavariate(self.alpha, self.beta)

    def update(self, reward: float) -> None:
        """reward בטווח 0–1 (commitment≈1, hangup≈0)."""
        reward = max(0.0, min(1.0, float(reward)))
        self.alpha += reward
        self.beta += 1.0 - reward


@dataclass
class SegmentStats:
    segment_key: str
    arms: Dict[ArmKey, BetaArm] = field(default_factory=dict)
    pulls: int = 0

    def get_or_create(self, persona: str, tactic: str, speed: float) -> BetaArm:
        key = (persona, tactic, round(speed, 2))
        if key not in self.arms:
            self.arms[key] = BetaArm(persona=persona, tactic=tactic, speed=round(speed, 2))
        return self.arms[key]


DEFAULT_PERSONAS = ["D", "I", "S", "C"]
DEFAULT_TACTICS = [
    "micro_yes_ladder",
    "loss_aversion",
    "social_proof",
    "limited_choice",
    "emotional_time_travel",
    "debt_creation",
    "three_cards",
]
DEFAULT_SPEEDS = [0.88, 0.95, 1.00, 1.08, 1.15]


def segment_key(neighborhood: str, age_group: str, gender: str) -> str:
    n = (neighborhood or "unknown").strip().lower()
    a = (age_group or "unknown").strip().lower()
    g = (gender or "unknown").strip().lower()
    return f"{n}|{a}|{g}"


class ABEngine:
    """
    Bayesian bandit (Thompson Sampling) למזעור regret.
    מיפוי: (neighborhood × age_group × gender) → best_persona → best_tactic → best_speed
    """

    def __init__(
        self,
        store_path: str = "data/ab_bandit_state.json",
        personas: Optional[List[str]] = None,
        tactics: Optional[List[str]] = None,
        speeds: Optional[List[float]] = None,
    ):
        self.store_path = Path(store_path)
        self.personas = personas or list(DEFAULT_PERSONAS)
        self.tactics = tactics or list(DEFAULT_TACTICS)
        self.speeds = speeds or list(DEFAULT_SPEEDS)
        self.segments: Dict[str, SegmentStats] = {}
        self.load()

    def _ensure_segment(self, key: str) -> SegmentStats:
        if key not in self.segments:
            self.segments[key] = SegmentStats(segment_key=key)
        return self.segments[key]

    def _candidate_arms(self, seg: SegmentStats) -> List[BetaArm]:
        arms: List[BetaArm] = []
        for p in self.personas:
            for t in self.tactics:
                for s in self.speeds:
                    arms.append(seg.get_or_create(p, t, s))
        return arms

    def select(
        self,
        neighborhood: str,
        age_group: str,
        gender: str,
    ) -> dict:
        """בוחר זרוע לפי Thompson Sampling — ממזער regret צפוי."""
        key = segment_key(neighborhood, age_group, gender)
        seg = self._ensure_segment(key)
        arms = self._candidate_arms(seg)
        best = max(arms, key=lambda a: a.sample())
        seg.pulls += 1
        return {
            "segment": key,
            "best_persona": best.persona,
            "best_tactic": best.tactic,
            "best_speed": best.speed,
            "expected_mean": round(best.mean, 4),
            "pulls": seg.pulls,
        }

    def observe(
        self,
        neighborhood: str,
        age_group: str,
        gender: str,
        persona: str,
        tactic: str,
        speed: float,
        reward: float,
    ) -> dict:
        key = segment_key(neighborhood, age_group, gender)
        seg = self._ensure_segment(key)
        arm = seg.get_or_create(persona, tactic, speed)
        before = arm.mean
        arm.update(reward)
        self.save()
        return {
            "segment": key,
            "arm": {"persona": persona, "tactic": tactic, "speed": speed},
            "reward": reward,
            "mean_before": round(before, 4),
            "mean_after": round(arm.mean, 4),
        }

    def best_known(
        self,
        neighborhood: str,
        age_group: str,
        gender: str,
    ) -> Optional[dict]:
        """הזרוע עם mean גבוה ביותר (ניצול) — בלי exploration."""
        key = segment_key(neighborhood, age_group, gender)
        seg = self.segments.get(key)
        if not seg or not seg.arms:
            return None
        best = max(seg.arms.values(), key=lambda a: a.mean)
        return {
            "segment": key,
            "best_persona": best.persona,
            "best_tactic": best.tactic,
            "best_speed": best.speed,
            "mean": round(best.mean, 4),
            "alpha": best.alpha,
            "beta": best.beta,
        }

    def estimated_regret(self, segment: str) -> float:
        """קירוב regret: פער בין הזרוע הטובה לממוצע הזרועות שנמשכו."""
        seg = self.segments.get(segment)
        if not seg or not seg.arms:
            return 0.0
        means = [a.mean for a in seg.arms.values()]
        return round(max(means) - (sum(means) / len(means)), 4)

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for key, seg in self.segments.items():
            data[key] = {
                "pulls": seg.pulls,
                "arms": [
                    {
                        "persona": a.persona,
                        "tactic": a.tactic,
                        "speed": a.speed,
                        "alpha": a.alpha,
                        "beta": a.beta,
                    }
                    for a in seg.arms.values()
                ],
            }
        self.store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> None:
        if not self.store_path.exists():
            return
        try:
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            for key, blob in raw.items():
                seg = SegmentStats(segment_key=key, pulls=int(blob.get("pulls", 0)))
                for arm in blob.get("arms", []):
                    a = BetaArm(
                        persona=arm["persona"],
                        tactic=arm["tactic"],
                        speed=float(arm["speed"]),
                        alpha=float(arm.get("alpha", 1.0)),
                        beta=float(arm.get("beta", 1.0)),
                    )
                    seg.arms[a.key] = a
                self.segments[key] = seg
            logger.info("[ab] loaded %s segments from %s", len(self.segments), self.store_path)
        except Exception as e:
            logger.warning("[ab] failed to load state: %s", e)


def reward_from_outcome(outcome: str, commitment: bool = False) -> float:
    """מיפוי תוצאת שיחה ל-reward 0–1."""
    if commitment or outcome in ("committed", "gotv_confirmed"):
        return 1.0
    mapping = {
        "answered": 0.4,
        "interested": 0.7,
        "callback": 0.55,
        "objection": 0.3,
        "no_answer": 0.05,
        "declined": 0.1,
        "do_not_call": 0.0,
        "hangup": 0.15,
    }
    return mapping.get((outcome or "").lower(), 0.25)
