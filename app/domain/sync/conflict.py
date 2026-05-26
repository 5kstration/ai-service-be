# app/domain/sync/conflict.py
import json
import logging
from app.domain.recommend.entity import PolicyProduct

logger = logging.getLogger(__name__)

CONFLICT_KEYWORDS = [
    "중복 불가", "타 지원 제외", "단독 지원",
    "중복 수혜 불가", "중복 지원 불가", "중복 신청 불가"
]


def detect_conflict(p1: PolicyProduct, p2: PolicyProduct) -> bool:
    """두 정책 간 중복 불가 여부 판단."""

    # 1. 동일 주관기관 + 동일 카테고리
    if p1.org and p2.org and p1.org == p2.org:
        if p1.category and p2.category and p1.category == p2.category:
            return True

    # 2. 나이 범위 겹침 + 동일 카테고리
    if (
        p1.age_min is not None and p1.age_max is not None and
        p2.age_min is not None and p2.age_max is not None
    ):
        age_overlap = (p1.age_min <= p2.age_max and p2.age_min <= p1.age_max)
        if (
            age_overlap and
            p1.category is not None and
            p2.category is not None and
            p1.category == p2.category
        ):
            return True

    # 3. 명시적 중복 불가 키워드
    desc1 = (p1.description or "") + (p1.core_benefit or "")
    desc2 = (p2.description or "") + (p2.core_benefit or "")
    for kw in CONFLICT_KEYWORDS:
        if kw in desc1 or kw in desc2:
            return True

    return False


def build_conflict_map(policies: list[PolicyProduct]) -> dict:
    """전체 정책 목록에서 conflict_policy_ids 자동 생성."""
    conflict_map = {}

    for i, p1 in enumerate(policies):
        conflicts = []
        for j, p2 in enumerate(policies):
            if i == j:
                continue
            if detect_conflict(p1, p2):
                conflicts.append(p2.key)
        conflict_map[p1.key] = conflicts
        if conflicts:
            logger.info(f"[Conflict] {p1.policy_name} ↔ conflict {len(conflicts)}건")

    return conflict_map


def update_conflict_ids(db, policies: list[PolicyProduct]) -> None:
    """정책 테이블에 conflict_policy_ids 업데이트."""
    conflict_map = build_conflict_map(policies)
    for policy in policies:
        policy.conflict_policy_ids = json.dumps(
            conflict_map.get(policy.key, []),
            ensure_ascii=False,
        )
    try:
        db.commit()
        logger.info(f"[Conflict] conflict 자동 계산 완료 - 총 {len(policies)}개 정책")
    except Exception:
        db.rollback()
        logger.exception("[Conflict] conflict_policy_ids 업데이트 중 DB 커밋 실패")
        raise
