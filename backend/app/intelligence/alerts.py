"""
Alerting & Temporal Tracking — Change detection, monitoring, intelligence updates.

Capabilities:
  - Track influence score changes over time
  - Detect significant profile changes (new sanctions, news surge, etc.)
  - Generate actionable alerts for field operatives
  - Maintain historical snapshots for trend analysis
"""

import json
import hashlib
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertType(str, Enum):
    SANCTIONS_NEW = "sanctions_new"
    NEWS_SURGE = "news_surge"
    SCORE_CHANGE = "score_change"
    NETWORK_EXPANSION = "network_expansion"
    NEGATIVE_PRESS = "negative_press"
    PROFILE_EMERGED = "profile_emerged"
    DATA_EXPIRY = "data_expiry"


@dataclass
class Alert:
    alert_id: str
    entity_name: str
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    description: str
    timestamp: str
    previous_value: Optional[float] = None
    current_value: Optional[float] = None
    delta: Optional[float] = None
    recommended_action: str = ""
    acknowledged: bool = False


@dataclass
class EntitySnapshot:
    entity_name: str
    timestamp: str
    composite_score: float
    tier: str
    political_capital: float
    community_influence: float
    voter_reliability: float
    financial_leverage: float
    alert_count: int = 0
    raw_data_hash: str = ""


class AlertManager:
    """Manages alerts and temporal tracking for monitored entities."""

    def __init__(self, max_history_per_entity: int = 20):
        self.alerts: list[Alert] = []
        self.snapshots: dict[str, list[EntitySnapshot]] = {}
        self.max_history = max_history_per_entity
        self._alert_counter = 0

    def take_snapshot(self, name: str, profile) -> EntitySnapshot:
        raw_hash = hashlib.md5(
            json.dumps(profile.evidence, sort_keys=True, default=str).encode()
        ).hexdigest()
        snapshot = EntitySnapshot(
            entity_name=name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            composite_score=profile.composite_score,
            tier=profile.tier.value,
            political_capital=profile.political_capital,
            community_influence=profile.community_influence,
            voter_reliability=profile.voter_reliability,
            financial_leverage=profile.financial_leverage,
            raw_data_hash=raw_hash,
        )
        if name not in self.snapshots:
            self.snapshots[name] = []
        self.snapshots[name].append(snapshot)
        if len(self.snapshots[name]) > self.max_history:
            self.snapshots[name] = self.snapshots[name][-self.max_history:]
        return snapshot

    def detect_changes(self, name: str, current_profile) -> list[Alert]:
        history = self.snapshots.get(name, [])
        if len(history) < 2:
            return []
        previous = history[-2]
        new_alerts = []
        score_delta = current_profile.composite_score - previous.composite_score
        if abs(score_delta) >= 15:
            direction = "surged" if score_delta > 0 else "dropped"
            sev = AlertSeverity.HIGH if abs(score_delta) >= 25 else AlertSeverity.MEDIUM
            new_alerts.append(self._create_alert(
                name, AlertType.SCORE_CHANGE, sev,
                title=f"Influence {direction} by {abs(score_delta):.0f} pts",
                description=f"{name}: {previous.composite_score:.0f} -> {current_profile.composite_score:.0f}",
                previous_value=previous.composite_score,
                current_value=current_profile.composite_score,
                delta=score_delta,
                recommended_action=(
                    "Full re-assessment needed." if abs(score_delta) >= 25
                    else "Monitor trend."
                ),
            ))
        if previous.tier != current_profile.tier.value:
            new_alerts.append(self._create_alert(
                name, AlertType.SCORE_CHANGE, AlertSeverity.HIGH,
                title=f"Tier: {previous.tier} -> {current_profile.tier.value}",
                description=f"{name} changed influence tier.",
                recommended_action="Update engagement strategy.",
            ))
        return new_alerts

    def check_sanctions_alert(self, name: str, data: dict) -> Optional[Alert]:
        if data.get("sanctions_count", 0) > 0:
            return self._create_alert(
                name, AlertType.SANCTIONS_NEW, AlertSeverity.CRITICAL,
                title=f"SANCTIONS: {name} on {data['sanctions_count']} list(s)",
                description=f"Lists: {', '.join(data.get('sanctions_lists', []))}",
                recommended_action="IMMEDIATE compliance review. Escalate to legal.",
            )
        if data.get("pep_status") == "confirmed":
            return self._create_alert(
                name, AlertType.SANCTIONS_NEW, AlertSeverity.HIGH,
                title=f"PEP CONFIRMED: {name}",
                description=f"Countries: {', '.join(data.get('pep_countries', ['unknown']))}",
                recommended_action="Enhanced due diligence. Senior operative only.",
            )
        return None

    def check_news_surge(self, name: str, data: dict, prev: int = 0) -> Optional[Alert]:
        current = data.get("mention_count", 0)
        if current >= 10 and current >= prev * 3:
            sev = AlertSeverity.CRITICAL if current >= 25 else AlertSeverity.HIGH
            return self._create_alert(
                name, AlertType.NEWS_SURGE, sev,
                title=f"NEWS SURGE: {name} — {current} mentions",
                description=f"Sentiment: {data.get('sentiment', {}).get('label', 'unknown')}",
                recommended_action="Review coverage. Adjust timing.",
            )
        return None

    def check_data_age(self, name: str, snap: EntitySnapshot) -> Optional[Alert]:
        try:
            st = datetime.fromisoformat(snap.timestamp)
            age = datetime.now(timezone.utc) - st.replace(tzinfo=timezone.utc)
            if age > timedelta(days=14):
                return self._create_alert(
                    name, AlertType.DATA_EXPIRY, AlertSeverity.LOW,
                    title=f"Data aging: {age.days}d",
                    description=f"Profile {age.days}d old. Schedule refresh.",
                    recommended_action="Schedule refresh cycle.",
                )
        except (ValueError, TypeError):
            pass
        return None

    def _create_alert(self, entity_name: str, alert_type: AlertType,
                       severity: AlertSeverity, title: str, description: str,
                       previous_value: Optional[float] = None,
                       current_value: Optional[float] = None,
                       delta: Optional[float] = None,
                       recommended_action: str = "") -> Alert:
        self._alert_counter += 1
        alert = Alert(
            alert_id=f"ALT-{self._alert_counter:06d}",
            entity_name=entity_name,
            alert_type=alert_type,
            severity=severity,
            title=title,
            description=description,
            timestamp=datetime.now(timezone.utc).isoformat(),
            previous_value=previous_value,
            current_value=current_value,
            delta=delta,
            recommended_action=recommended_action,
        )
        self.alerts.append(alert)
        return alert

    def get_active_alerts(self, severity: Optional[AlertSeverity] = None,
                           acknowledged: Optional[bool] = False) -> list[Alert]:
        alerts = [a for a in self.alerts if a.acknowledged == acknowledged]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)

    def acknowledge(self, alert_id: str):
        for a in self.alerts:
            if a.alert_id == alert_id:
                a.acknowledged = True
                return

    def get_timeline(self, name: str) -> list[dict]:
        return [
            {
                "timestamp": s.timestamp, "composite": s.composite_score,
                "tier": s.tier, "political": s.political_capital,
                "community": s.community_influence, "voter": s.voter_reliability,
                "financial": s.financial_leverage,
            }
            for s in self.snapshots.get(name, [])
        ]

    def summary(self) -> dict:
        active = self.get_active_alerts()
        critical = [a for a in active if a.severity == AlertSeverity.CRITICAL]
        return {
            "total_alerts": len(self.alerts),
            "active_alerts": len(active),
            "critical_alerts": len(critical),
            "tracked_entities": len(self.snapshots),
            "latest_alert": active[0].timestamp if active else None,
        }
