"""Deterministic case similarity for AI Decision Intelligence (EA-0020 E3)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from aqelyn.conventions.errors import DecisionConfigInvalid
from aqelyn.decision.models import SimilarityHit
from aqelyn.decision.store import validate_limit

CaseFeatures = Mapping[str, Sequence[str]]
CaseCorpus = Mapping[str, CaseFeatures]


def similar_cases(
    case_id: str,
    corpus: CaseCorpus,
    *,
    limit: int = 5,
) -> list[SimilarityHit]:
    """Return deterministic Jaccard similarity hits with explicit shared features."""

    _validate_case_id(case_id)
    validate_limit(limit)
    target = corpus.get(case_id)
    if target is None:
        return []
    target_flat = _flatten(target)
    hits: list[SimilarityHit] = []
    for candidate_id, candidate in corpus.items():
        if candidate_id == case_id:
            continue
        candidate_flat = _flatten(candidate)
        union = target_flat | candidate_flat
        shared_flat = target_flat & candidate_flat
        score = 0.0 if not union else len(shared_flat) / len(union)
        hits.append(
            SimilarityHit(
                case_id=candidate_id,
                score=score,
                shared=_shared_by_kind(target, candidate),
                reason=(
                    f"{candidate_id} shares {len(shared_flat)} of {len(union)} "
                    f"explicit features with {case_id}."
                ),
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.case_id))
    return hits[:limit]


def _flatten(features: CaseFeatures) -> set[str]:
    flattened: set[str] = set()
    for kind, values in features.items():
        _validate_case_id(kind, field="feature kind")
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise DecisionConfigInvalid("case features must be non-empty strings")
            flattened.add(f"{kind}:{value}")
    return flattened


def _shared_by_kind(left: CaseFeatures, right: CaseFeatures) -> dict[str, list[str]]:
    shared: dict[str, list[str]] = {}
    for kind in sorted(set(left) | set(right)):
        selected = sorted(set(left.get(kind, ())) & set(right.get(kind, ())))
        if selected:
            shared[kind] = selected
    return shared or {"features": []}


def _validate_case_id(value: str, *, field: str = "case_id") -> str:
    if not value.strip():
        raise DecisionConfigInvalid(f"{field} must not be empty")
    return value
