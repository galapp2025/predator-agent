"""Persuadability Scoring — 0.0–1.0 לפני חיוג; מיון CSV DESC; כיול/אימון אופציונלי"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("persuadability")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PersuadabilityInput:
    first_name: str
    last_name: str
    city: str = ""
    street: str = ""
    campaign_type: str = "primaries"
    age_group: str = ""
    gender: str = ""
    support_score: float = 0.5
    registered_branch: str = ""


@dataclass
class ScoredLead:
    lead: Dict
    score: float
    features: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)


@dataclass
class ScoreBreakdown:
    score: float
    backend: str
    features: Dict[str, float]
    contributions: Dict[str, float]
    reasons: List[str]


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

HOT_CITIES = {
    "פתח תקווה",
    "תל אביב",
    "רמת גן",
    "בני ברק",
    "חולון",
    "בת ים",
    "ראשון לציון",
    "ירושלים",
    "חיפה",
    "אשדוד",
}

CAMPAIGN_WEIGHTS = {
    "primaries": 0.72,
    "municipal": 0.65,
    "gotv": 0.88,
    "persuasion": 0.78,
    "awareness": 0.45,
    "fundraising": 0.55,
}

AGE_WEIGHTS = {
    "18-24": 0.55,
    "25-45": 0.70,
    "45-65": 0.75,
    "65+": 0.68,
    "unknown": 0.60,
}

FEATURE_ORDER: Sequence[str] = (
    "name_len",
    "first_hash",
    "last_hash",
    "has_hebrew",
    "city_hot",
    "city_hash",
    "street_hash",
    "has_street",
    "campaign_w",
    "campaign_hash",
    "age_w",
    "gender_w",
    "support_prior",
    "branch_hash",
    "name_commonality",
)


def _stable_hash_unit(text: str) -> float:
    digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _is_hebrew(text: str) -> bool:
    return any("\u0590" <= c <= "\u05FF" for c in (text or ""))


def _name_commonality(first: str, last: str) -> float:
    """שמות נפוצים בישראל → מעט יותר נגישים טלפונית (proxy חלש)."""
    common_first = {
        "משה", "יוסף", "דוד", "אברהם", "יעקב", "ישראל", "דניאל", "יונתן",
        "רחל", "שרה", "מרים", "לאה", "רבקה", "אסתר", "תמר", "נועה", "מיכל",
    }
    common_last = {"כהן", "לוי", "מזרחי", "פרץ", "ביטון", "אברהם", "דוד", "חדד"}
    score = 0.0
    if first in common_first:
        score += 0.55
    if last in common_last:
        score += 0.45
    return min(1.0, score) if score else 0.25


def _name_features(first: str, last: str) -> Dict[str, float]:
    first = (first or "").strip()
    last = (last or "").strip()
    return {
        "name_len": min(1.0, (len(first) + len(last)) / 24.0),
        "first_hash": _stable_hash_unit(first.lower()),
        "last_hash": _stable_hash_unit(last.lower()),
        "has_hebrew": 1.0 if _is_hebrew(first + last) else 0.0,
        "name_commonality": _name_commonality(first, last),
    }


def _geo_features(city: str, street: str, branch: str = "") -> Dict[str, float]:
    city = (city or "").strip()
    street = (street or "").strip()
    branch = (branch or "").strip()
    return {
        "city_hot": 1.0 if city in HOT_CITIES else 0.35,
        "city_hash": _stable_hash_unit(city.lower()),
        "street_hash": _stable_hash_unit(street.lower()),
        "has_street": 1.0 if street else 0.0,
        "branch_hash": _stable_hash_unit(branch.lower()),
    }


def _campaign_features(campaign_type: str) -> Dict[str, float]:
    ct = (campaign_type or "primaries").lower()
    return {
        "campaign_w": CAMPAIGN_WEIGHTS.get(ct, 0.55),
        "campaign_hash": _stable_hash_unit(ct),
    }


def _demo_features(age_group: str, gender: str, support_score: float) -> Dict[str, float]:
    age = (age_group or "unknown").strip()
    gender_l = (gender or "").strip().lower()
    gender_w = 0.55
    if gender_l in ("female", "f", "נקבה", "אישה"):
        gender_w = 0.62
    elif gender_l in ("male", "m", "זכר", "גבר"):
        gender_w = 0.58
    try:
        support = float(support_score)
    except (TypeError, ValueError):
        support = 0.5
    support = max(0.0, min(1.0, support))
    return {
        "age_w": AGE_WEIGHTS.get(age, AGE_WEIGHTS["unknown"]),
        "gender_w": gender_w,
        "support_prior": support,
    }


def featurize(inp: PersuadabilityInput) -> Dict[str, float]:
    feats: Dict[str, float] = {}
    feats.update(_name_features(inp.first_name, inp.last_name))
    feats.update(_geo_features(inp.city, inp.street, inp.registered_branch))
    feats.update(_campaign_features(inp.campaign_type))
    feats.update(_demo_features(inp.age_group, inp.gender, inp.support_score))
    return feats


def feature_vector(feats: Dict[str, float]) -> List[float]:
    return [float(feats.get(k, 0.0)) for k in FEATURE_ORDER]


# ---------------------------------------------------------------------------
# Heuristic model (fallback when no LightGBM/XGBoost artifact)
# ---------------------------------------------------------------------------

HEURISTIC_WEIGHTS: Dict[str, float] = {
    "city_hot": 0.18,
    "campaign_w": 0.14,
    "support_prior": 0.22,
    "age_w": 0.10,
    "has_street": 0.06,
    "has_hebrew": 0.05,
    "name_commonality": 0.08,
    "name_len": 0.05,
    "gender_w": 0.04,
    "city_hash": 0.03,
    "street_hash": 0.025,
    "first_hash": 0.015,
    "branch_hash": 0.01,
}


def _sigmoid(z: float) -> float:
    z = max(-20.0, min(20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def heuristic_score_with_breakdown(feats: Dict[str, float]) -> ScoreBreakdown:
    contributions: Dict[str, float] = {}
    z = -0.35
    for k, w in HEURISTIC_WEIGHTS.items():
        c = w * float(feats.get(k, 0.0))
        contributions[k] = round(c, 4)
        z += c
    score = round(_sigmoid(3.2 * (z - 0.15)), 4)
    reasons: List[str] = []
    if feats.get("city_hot", 0) >= 0.9:
        reasons.append("עיר חמה לקמפיין")
    if feats.get("support_prior", 0) >= 0.7:
        reasons.append("support_score גבוה מראש")
    if feats.get("campaign_w", 0) >= 0.8:
        reasons.append("סוג קמפיין עם המרה גבוהה (GOTV)")
    if feats.get("has_street", 0) < 0.5:
        reasons.append("חסרה כתובת — דיוק נמוך יותר")
    if not reasons:
        reasons.append("ציון בסיסי לפי מאפייני שם/עיר/קמפיין")
    return ScoreBreakdown(
        score=score,
        backend="heuristic",
        features=dict(feats),
        contributions=contributions,
        reasons=reasons,
    )


def _heuristic_score(feats: Dict[str, float]) -> float:
    return heuristic_score_with_breakdown(feats).score


# ---------------------------------------------------------------------------
# Model wrapper
# ---------------------------------------------------------------------------


class PersuadabilityModel:
    """
    Input: first_name, last_name, city, street, campaign_type (+ optional demos)
    Model: LightGBM / XGBoost אם model_path קיים; אחרת heuristic
    Output: 0.0–1.0
    """

    def __init__(self, model_path: Optional[str] = None, backend: str = "auto"):
        self.model_path = Path(model_path) if model_path else (
            Path(os.getenv("PERSUADABILITY_MODEL_PATH", "")) if os.getenv("PERSUADABILITY_MODEL_PATH") else None
        )
        if self.model_path and not str(self.model_path):
            self.model_path = None
        self.backend = backend
        self._booster = None
        self._load_model()

    def _load_model(self) -> None:
        if not self.model_path or not self.model_path.exists():
            self.backend = "heuristic"
            return
        try:
            if self.backend in ("auto", "lightgbm"):
                import lightgbm as lgb  # type: ignore

                self._booster = lgb.Booster(model_file=str(self.model_path))
                self.backend = "lightgbm"
                logger.info("Loaded LightGBM model from %s", self.model_path)
                return
        except Exception as e:
            logger.warning("LightGBM load failed: %s", e)
        try:
            if self.backend in ("auto", "xgboost"):
                import xgboost as xgb  # type: ignore

                self._booster = xgb.Booster()
                self._booster.load_model(str(self.model_path))
                self.backend = "xgboost"
                logger.info("Loaded XGBoost model from %s", self.model_path)
                return
        except Exception as e:
            logger.warning("XGBoost load failed: %s", e)
        self.backend = "heuristic"
        self._booster = None

    def explain(self, inp: PersuadabilityInput) -> ScoreBreakdown:
        feats = featurize(inp)
        if self._booster is None:
            return heuristic_score_with_breakdown(feats)
        row = feature_vector(feats)
        try:
            if self.backend == "lightgbm":
                pred = float(self._booster.predict([row])[0])
            else:
                import xgboost as xgb  # type: ignore

                dmat = xgb.DMatrix([row], feature_names=list(FEATURE_ORDER))
                pred = float(self._booster.predict(dmat)[0])
            score = round(max(0.0, min(1.0, pred)), 4)
            return ScoreBreakdown(
                score=score,
                backend=self.backend,
                features=feats,
                contributions={},
                reasons=[f"תחזית {self.backend}"],
            )
        except Exception as e:
            logger.warning("model predict failed, heuristic fallback: %s", e)
            return heuristic_score_with_breakdown(feats)

    def score(self, inp: PersuadabilityInput) -> float:
        return self.explain(inp).score

    def score_lead(self, lead: Dict, campaign_type: str = "primaries") -> float:
        return self.explain(self.input_from_lead(lead, campaign_type)).score

    def explain_lead(self, lead: Dict, campaign_type: str = "primaries") -> ScoreBreakdown:
        return self.explain(self.input_from_lead(lead, campaign_type))

    @staticmethod
    def input_from_lead(lead: Dict, campaign_type: str = "primaries") -> PersuadabilityInput:
        return PersuadabilityInput(
            first_name=str(lead.get("first_name", "")),
            last_name=str(lead.get("last_name", "")),
            city=str(lead.get("city", "")),
            street=str(lead.get("street", "")),
            campaign_type=str(lead.get("campaign_type") or campaign_type),
            age_group=str(lead.get("age_group", "")),
            gender=str(lead.get("gender", "")),
            support_score=float(lead.get("support_score") or 0.5),
            registered_branch=str(lead.get("registered_branch", "")),
        )


# ---------------------------------------------------------------------------
# Batch scoring / CSV sort
# ---------------------------------------------------------------------------


def score_leads(
    leads: List[Dict],
    model: Optional[PersuadabilityModel] = None,
    campaign_type: str = "primaries",
) -> List[ScoredLead]:
    model = model or PersuadabilityModel()
    scored: List[ScoredLead] = []
    for lead in leads:
        breakdown = model.explain_lead(lead, campaign_type)
        scored.append(
            ScoredLead(
                lead=dict(lead),
                score=breakdown.score,
                features=breakdown.features,
                reasons=breakdown.reasons,
            )
        )
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored


def sort_csv_by_persuadability(
    input_csv: str,
    output_csv: Optional[str] = None,
    campaign_type: str = "primaries",
    model_path: Optional[str] = None,
) -> List[ScoredLead]:
    path = Path(input_csv)
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    model = PersuadabilityModel(model_path=model_path)
    scored = score_leads(rows, model=model, campaign_type=campaign_type)

    out_path = Path(output_csv) if output_csv else path
    fieldnames = list(rows[0].keys()) if rows else []
    for col in ("persuadability", "persuadability_reasons"):
        if col not in fieldnames:
            fieldnames.append(col)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in scored:
            row = dict(item.lead)
            row["persuadability"] = f"{item.score:.4f}"
            row["persuadability_reasons"] = "; ".join(item.reasons)
            writer.writerow(row)

    logger.info(
        "[persuadability] sorted %s leads → %s (backend=%s)",
        len(scored),
        out_path,
        model.backend,
    )
    return scored


def export_feature_matrix(leads: List[Dict], path: str, campaign_type: str = "primaries") -> Path:
    """ייצוא מטריצת פיצ'רים לאימון חיצוני."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for lead in leads:
        inp = PersuadabilityModel.input_from_lead(lead, campaign_type)
        feats = featurize(inp)
        row = {"phone": lead.get("phone", ""), **feats}
        rows.append(row)
    if not rows:
        out.write_text("", encoding="utf-8")
        return out
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return out


def calibrate_scores(scores: Iterable[float], temperature: float = 1.0) -> List[float]:
    """כיול טמפרטורה פשוט לדירוג רך יותר/חד יותר."""
    t = max(0.05, float(temperature))
    out = []
    for s in scores:
        s = max(1e-6, min(1 - 1e-6, float(s)))
        logit = math.log(s / (1 - s)) / t
        out.append(round(_sigmoid(logit), 4))
    return out


def rank_summary(scored: List[ScoredLead], top_n: int = 5) -> dict:
    if not scored:
        return {"count": 0, "mean": 0.0, "top": []}
    mean = sum(s.score for s in scored) / len(scored)
    return {
        "count": len(scored),
        "mean": round(mean, 4),
        "min": scored[-1].score,
        "max": scored[0].score,
        "top": [
            {
                "name": f"{s.lead.get('first_name', '')} {s.lead.get('last_name', '')}".strip(),
                "phone": s.lead.get("phone"),
                "score": s.score,
                "reasons": s.reasons,
            }
            for s in scored[:top_n]
        ],
    }


def save_score_audit(scored: List[ScoredLead], path: str = "data/persuadability_audit.json") -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": rank_summary(scored),
        "items": [
            {
                "lead": {k: v for k, v in s.lead.items() if k != "transcript"},
                "score": s.score,
                "reasons": s.reasons,
                "features": s.features,
            }
            for s in scored
        ],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
