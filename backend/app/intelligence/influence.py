"""Influence network mapping (Feature 2) — distinct from opposition network.py."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import db

router = APIRouter(tags=["influence"])


def _pseudo_age(voter: dict[str, Any]) -> int:
    raw = f"{voter.get('id')}{voter.get('last_name')}".encode()
    return 28 + (int(hashlib.md5(raw).hexdigest()[:4], 16) % 45)


def _influence_score(voter: dict[str, Any], cluster_size: int, same_name: int, nb_total: int) -> float:
    age = _pseudo_age(voter)
    cluster_size_score = min(cluster_size / 100.0, 1.0)
    density = same_name / max(same_name, nb_total, 1)
    density_score = min(density * 3, 1.0)
    age_score = min((age - 25) / 50.0, 1.0) if age > 50 else 0.0
    return round((cluster_size_score * 40 + density_score * 30 + age_score * 30), 1)


def _build_graph(rows: list[dict[str, Any]]) -> tuple[list[dict], list[dict], list[dict], int]:
    by_nb_ln: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_nb: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        nb = str(r.get("neighborhood") or r.get("city") or "כללי")
        ln = str(r.get("last_name") or "").strip()
        by_nb_ln[(nb, ln)].append(r)
        by_nb[nb].append(r)

    hubs: list[dict[str, Any]] = []
    hub_ids: set[str] = set()
    for (nb, ln), group in by_nb_ln.items():
        if len(group) < 5 or not ln:
            continue
        group.sort(key=lambda x: _pseudo_age(x), reverse=True)
        hub = group[0]
        hub_id = str(hub.get("id"))
        hub_ids.add(hub_id)
        score = _influence_score(hub, len(group), len(group), len(by_nb[nb]))
        cluster_key = f"{nb}_{ln}".replace(" ", "_")[:32]
        top_gotv = max((str(m.get("gotv_category") or "swing") for m in group), key=lambda x: x)
        hubs.append(
            {
                "hub_id": hub_id,
                "full_name": f"{hub.get('first_name')} {hub.get('last_name')}".strip(),
                "neighborhood": nb,
                "age": _pseudo_age(hub),
                "influence_score": min(100.0, score),
                "cluster": cluster_key,
                "reach": len(group),
                "cluster_voters": len(group),
                "top_gotv_in_cluster": top_gotv.upper(),
                "recommended_approach": "פניה אישית מהמועמד — ראש משפחה/קהילה מקומית",
            }
        )

    # Neighborhood density bonus hubs
    for nb, group in by_nb.items():
        if len(group) >= 500:
            continue
        elders = [g for g in group if _pseudo_age(g) >= 50]
        if len(elders) >= 3:
            hub = max(elders, key=lambda x: float(x.get("support_score") or 0))
            hid = str(hub.get("id"))
            if hid not in hub_ids:
                hub_ids.add(hid)
                hubs.append(
                    {
                        "hub_id": hid,
                        "full_name": f"{hub.get('first_name')} {hub.get('last_name')}".strip(),
                        "neighborhood": nb,
                        "age": _pseudo_age(hub),
                        "influence_score": min(100.0, _influence_score(hub, len(elders), 3, len(group))),
                        "cluster": f"{nb}_elders",
                        "reach": len(elders),
                        "cluster_voters": len(elders),
                        "top_gotv_in_cluster": str(hub.get("gotv_category") or "SWING").upper(),
                        "recommended_approach": "פגישת שכונה קצרה עם מוביל/ת דעה",
                    }
                )

    hubs.sort(key=lambda x: x["influence_score"], reverse=True)

    nodes = []
    edges = []
    for r in rows[:5000]:
        vid = str(r.get("id"))
        nodes.append(
            {
                "id": vid,
                "label": f"{r.get('first_name')} {r.get('last_name')}".strip(),
                "influence_score": _influence_score(r, 1, 1, len(by_nb[str(r.get('neighborhood') or r.get('city') or 'כללי')])),
                "cluster": str(r.get("neighborhood") or "כללי"),
                "gotv": str(r.get("gotv_category") or "swing").upper(),
            }
        )

    for (nb, ln), group in by_nb_ln.items():
        if len(group) < 2:
            continue
        hub = max(group, key=lambda x: _pseudo_age(x))
        hub_id = str(hub.get("id"))
        for m in group[1:6]:
            edges.append(
                {
                    "from": hub_id,
                    "to": str(m.get("id")),
                    "weight": 3,
                    "connection_type": "same_last_name",
                }
            )

    clusters = len({h["cluster"] for h in hubs})
    return hubs, nodes, edges, clusters


class InfluenceScanRequest(BaseModel):
    max_hubs: int = Field(default=100, ge=1, le=500)
    neighborhoods: list[str] = Field(default_factory=lambda: ["all"])


@router.post("/intel/influence/scan")
async def influence_scan(body: InfluenceScanRequest) -> dict[str, Any]:
    t0 = time.perf_counter()
    rows = await db.all_voters()
    if body.neighborhoods and "all" not in [n.lower() for n in body.neighborhoods]:
        allowed = set(body.neighborhoods)
        rows = [r for r in rows if str(r.get("neighborhood") or r.get("city") or "") in allowed]
    hubs, _, _, clusters = _build_graph(rows)
    hubs = hubs[: body.max_hubs]
    ms = int((time.perf_counter() - t0) * 1000)
    return {
        "hubs_found": len(hubs),
        "hubs": hubs,
        "clusters_found": clusters,
        "scan_duration_ms": ms,
    }


@router.get("/influence/map")
async def influence_map(
    neighborhood: str = Query("all"),
    depth: int = Query(2, ge=1, le=4),
) -> dict[str, Any]:
    rows = await db.all_voters()
    if neighborhood.lower() != "all":
        rows = [
            r
            for r in rows
            if neighborhood in str(r.get("neighborhood") or "") or neighborhood in str(r.get("city") or "")
        ]
    hubs, nodes, edges, clusters = _build_graph(rows)
    if depth < 2:
        edges = edges[: max(1, len(edges) // 2)]
    return {
        "nodes": nodes[:2000],
        "edges": edges[:8000],
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "hubs": len(hubs),
            "clusters": clusters,
        },
    }


class InfluenceScoreRequest(BaseModel):
    voter_id: str


@router.post("/intel/influence/influence-score")
async def influence_score(body: InfluenceScoreRequest) -> dict[str, Any]:
    voter = await db.resolve_voter(body.voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail="בוחר לא נמצא")
    rows = await db.all_voters()
    nb = str(voter.get("neighborhood") or voter.get("city") or "כללי")
    ln = str(voter.get("last_name") or "")
    cluster = [r for r in rows if str(r.get("neighborhood") or r.get("city") or "כללי") == nb and str(r.get("last_name") or "") == ln]
    score = _influence_score(voter, len(cluster), len(cluster), len([r for r in rows if str(r.get("neighborhood") or r.get("city") or "כללי") == nb]))
    all_scores = sorted(
        [_influence_score(r, 1, 1, 1) for r in rows[:500]],
    )
    percentile = 50
    if all_scores:
        below = sum(1 for s in all_scores if s <= score)
        percentile = int(100 * below / len(all_scores))
    return {
        "voter_id": voter.get("id"),
        "influence_score": score,
        "reach": max(1, len(cluster)),
        "cluster": f"{nb}_{ln}".replace(" ", "_")[:32] if ln else f"{nb}_general",
        "is_hub": score >= 55 and _pseudo_age(voter) >= 50,
        "percentile": percentile,
    }


class TargetHubsRequest(BaseModel):
    top_n: int = Field(default=10, ge=1, le=100)
    gotv_filter: str = "SWING"


@router.post("/intel/influence/target-hubs")
async def target_hubs(body: TargetHubsRequest) -> dict[str, Any]:
    rows = await db.all_voters()
    hubs, _, _, _ = _build_graph(rows)
    filt = body.gotv_filter.lower()
    filtered = [h for h in hubs if filt in str(h.get("top_gotv_in_cluster", "")).lower()]
    if not filtered:
        filtered = hubs
    filtered.sort(key=lambda x: x["influence_score"], reverse=True)
    return {"hubs": filtered[: body.top_n], "count": min(body.top_n, len(filtered))}
