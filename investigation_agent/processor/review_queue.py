"""Generate candidate clusters from heuristic matching (analyst review required)."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from investigation_agent.db.schema import CandidateCluster, CandidateEvidenceLink, Evidence
from investigation_agent.processor.matcher import normalize_reason_labels, pair_score


def generate_candidate_clusters(
    session: Session,
    *,
    evidence_limit: int = 200,
    min_score: float = 0.45,
    max_pairs: int = 2000,
) -> int:
    """
    Scan recent evidence pairs; create pending clusters for pairs above min_score.
    Does not merge duplicates; skips if a link already exists for the pair.
    """
    stmt = select(Evidence).order_by(Evidence.id.desc()).limit(evidence_limit)
    rows = list(session.scalars(stmt).all())
    if len(rows) < 2:
        return 0

    created = 0
    pairs_checked = 0
    # Compare older indices first to prefer newer ids as primary in ordering
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if pairs_checked >= max_pairs:
                break
            pairs_checked += 1
            a, b = rows[j], rows[i]  # higher id = a
            if a.id == b.id:
                continue
            score, reasons = pair_score(a, b)
            if score < min_score:
                continue
            eid_a, eid_b = sorted([a.id, b.id])
            if _pair_already_linked(session, eid_a, eid_b):
                continue
            cluster = CandidateCluster(status="pending", title=None)
            session.add(cluster)
            session.flush()
            for eid, other in ((eid_a, eid_b), (eid_b, eid_a)):
                sig = normalize_reason_labels(reasons)
                rjson = json.dumps(
                    sig + [f"pair_score:{score:.3f}", f"paired_with:{other}"],
                    ensure_ascii=False,
                )
                session.add(
                    CandidateEvidenceLink(
                        cluster_id=cluster.id,
                        evidence_id=eid,
                        reasons_json=rjson,
                        confidence=score,
                    )
                )
            created += 1
        if pairs_checked >= max_pairs:
            break

    session.flush()
    return created


def _pair_already_linked(session: Session, eid_a: int, eid_b: int) -> bool:
    """True if both evidence ids appear together in the same cluster already."""
    q = select(CandidateEvidenceLink.cluster_id).where(CandidateEvidenceLink.evidence_id == eid_a)
    clusters_a = set(session.scalars(q).all())
    if not clusters_a:
        return False
    q2 = select(CandidateEvidenceLink.id).where(
        CandidateEvidenceLink.evidence_id == eid_b,
        CandidateEvidenceLink.cluster_id.in_(clusters_a),
    )
    return session.scalar(q2) is not None
