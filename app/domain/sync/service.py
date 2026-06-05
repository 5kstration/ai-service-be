# app/domain/sync/service.py
import json
import logging
import re

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.domain.recommend.entity import CardProduct, InsuranceProduct, PolicyProduct
from app.core.utils.tsid import TSID

logger = logging.getLogger(__name__)


# =============================================
# 유사도 기반 필드 추출 헬퍼
# =============================================

def _get(raw: dict, *candidates, default=""):
    """후보 필드명 순서대로 시도, 첫 번째 비어있지 않은 값 반환."""
    for key in candidates:
        val = raw.get(key)
        if val is not None and str(val).strip():
            return val
    return default

def _parse_date(raw: dict, *candidates) -> str:
    """YYYYMMDD 또는 YYYY-MM-DD 형식 날짜 → YYYY.MM.DD 변환."""
    val = str(_get(raw, *candidates))
    val = re.sub(r"[-/]", "", val)  # 구분자 제거
    if re.fullmatch(r"\d{8}", val):
        return f"{val[:4]}.{val[4:6]}.{val[6:]}"
    return val

def _parse_url(raw: dict, *candidates) -> str:
    """URL 패턴 감지 후 반환."""
    for key in candidates:
        val = raw.get(key, "")
        if val and re.match(r"https?://", str(val)):
            return val
    return ""

def _parse_benefits_json(items: list, label_key: str, value_key: str) -> str:
    """리스트 형태 benefits → JSON 문자열."""
    return json.dumps(
        [{"label": i.get(label_key, ""), "value": i.get(value_key, "")} for i in items],
        ensure_ascii=False,
    )


# =============================================
# sourceCode별 매핑
# =============================================

def _map_card(source_code: str, raw: dict) -> dict:
    if source_code == "TOSS_CARD_LOUNGE":
        benefit_texts = raw.get("benefitTexts", [])
        benefits = json.dumps(
            [{"label": f"혜택 {i+1}", "value": b} for i, b in enumerate(benefit_texts)],
            ensure_ascii=False,
        )
        return dict(
            company     = _get(raw, "cardCompany", "company", "issuer"),
            card_name   = _get(raw, "cardName", "name", "productName"),
            top_benefit = _get(raw, "summary", "topBenefit", "description"),
            benefits    = benefits,
            apply_url   = _parse_url(raw, "detailUrl", "applyUrl", "productUrl", "url"),
            accent_color= "#3182F6",
        )
    # CARD_GORILLA 또는 미지 sourceCode → 유사도 기반 fallback
    benefit_texts = raw.get("benefitTexts") or raw.get("benefits") or []
    if isinstance(benefit_texts, list) and benefit_texts and isinstance(benefit_texts[0], str):
        benefits = json.dumps(
            [{"label": f"혜택 {i+1}", "value": b} for i, b in enumerate(benefit_texts)],
            ensure_ascii=False,
        )
    elif isinstance(benefit_texts, list):
        benefits = json.dumps(benefit_texts, ensure_ascii=False)
    else:
        benefits = "[]"
    return dict(
        company     = _get(raw, "cardCompany", "company", "issuer", "cmpyNm", "brandNm"),
        card_name   = _get(raw, "cardName", "name", "productName", "prdNm", "goodsNm"),
        top_benefit = _get(raw, "summary", "topBenefit", "description", "mog", "brief"),
        benefits    = benefits,
        apply_url   = _parse_url(raw, "detailUrl", "applyUrl", "productUrl", "hpgeUrl", "url"),
        accent_color= "#3182F6",
    )


def _map_insurance(source_code: str, raw: dict) -> dict:
    if source_code == "SAFE_INSURANCE":
        grnt_items = raw.get("lcgvrGrnt", [])
        benefits = json.dumps(
            [{"label": g.get("grntItmNm", ""), "value": g.get("grntCnts", "")} for g in grnt_items[:5]],
            ensure_ascii=False,
        )
        return dict(
            insurer        = _get(raw, "orgNm", "upOrgNm", "ctrtrNm"),
            insurance_name = _get(raw, "insrncGdsNm", "prdNm", "productName"),
            top_benefit    = _get(raw, "insrdNm", "mog", "summary"),
            benefits       = benefits,
            apply_url      = _parse_url(raw, "hpgeUrl", "applyUrl", "url"),
            accent_color   = "#8B5CF6",
        )
    if source_code == "INDEMNITY_INSURANCE":
        benefits = json.dumps([
            {"label": "보험 유형", "value": _get(raw, "ptrn", "insrncType", "category")},
            {"label": "보장 구분", "value": _get(raw, "mog", "coverageType", "coverage")},
            {"label": "기준일",   "value": _get(raw, "basDt", "baseDate", "stdDt")},
        ], ensure_ascii=False)
        return dict(
            insurer        = _get(raw, "cmpyNm", "companyName", "issuer", "orgNm"),
            insurance_name = _get(raw, "prdNm", "productName", "insrncGdsNm", "goodsNm"),
            top_benefit    = _get(raw, "mog", "summary", "topBenefit", "insrdNm"),
            benefits       = benefits,
            apply_url      = _parse_url(raw, "hpgeUrl", "applyUrl", "url"),
            accent_color   = "#8B5CF6",
        )
    # POST_INSURANCE_BEST / POST_INSURANCE_GOODS / 미지 → fallback
    grnt_items = raw.get("lcgvrGrnt") or raw.get("coverages") or raw.get("grntItems") or []
    if grnt_items:
        benefits = json.dumps(
            [{"label": g.get("grntItmNm") or g.get("title", ""), "value": g.get("grntCnts") or g.get("description", "")} for g in grnt_items[:5]],
            ensure_ascii=False,
        )
    else:
        benefits = json.dumps([
            {"label": "보험 유형", "value": _get(raw, "ptrn", "insrncType", "productType", "gdsClsNm")},
            {"label": "보장 구분", "value": _get(raw, "mog", "coverageType", "coverage", "insrncPrd")},
            {"label": "기준일",   "value": _get(raw, "basDt", "baseDate", "stdDt", "aplcStrtDt")},
        ], ensure_ascii=False)
    return dict(
        insurer        = _get(raw, "cmpyNm", "companyName", "orgNm", "upOrgNm", "issuer"),
        insurance_name = _get(raw, "prdNm", "insrncGdsNm", "productName", "goodsNm", "insrncPrdNm"),
        top_benefit    = _get(raw, "mog", "insrdNm", "summary", "topBenefit", "gdsClsNm"),
        benefits       = benefits,
        apply_url      = _parse_url(raw, "hpgeUrl", "applyUrl", "url", "termsUrl"),
        accent_color   = "#8B5CF6",
    )


def _map_policy(source_code: str, raw: dict) -> dict:
    # SAFE_INSURANCE가 category=INSURANCE인데 정책성격도 있음 → 별도 처리
    # YOUTH_CENTER 및 fallback 통합
    grnt_items = raw.get("lcgvrGrnt", [])
    if grnt_items:
        tags = json.dumps([g.get("grntItmNm", "") for g in grnt_items[:3]], ensure_ascii=False)
    else:
        kw_raw = _get(raw, "plcyKywdNm", "keywords", "keyword", "tags")
        if isinstance(kw_raw, list):
            tags = json.dumps(kw_raw[:3], ensure_ascii=False)
        else:
            tags = json.dumps([k.strip() for k in str(kw_raw).split(",")][:3] if kw_raw else [], ensure_ascii=False)

    grnt_end = str(_get(raw, "grntEnd", "endDate", "plcyApplyEndDt", "aplcEndDt", "applyEndDate"))
    deadline = _parse_date(raw, "grntEnd", "endDate", "plcyApplyEndDt", "aplcEndDt") if grnt_end else ""

    grnt_from = _get(raw, "grntFrom", "startDate", "plcyApplyStrtDt", "aplcStrtDt", "applyStartDate")

    category = _get(raw, "bizTycdNm", "polyBizSecd", "category", "policyCategory") or "기타"

    return dict(
        policy_name        = _get(raw, "insrncGdsNm", "plcyNm", "policyName", "polyBizNm", "name"),
        org                = _get(raw, "orgNm", "upOrgNm", "organNm", "jrsdInsttNm", "institution"),
        category           = category,
        category_color     = "#3182F6",
        deadline           = deadline,
        dday               = None,
        tags               = tags,
        core_benefit       = str(_get(raw, "insrdNm", "plcyExplnCn", "coreBenefit", "summary", "polyBizNm") or "")[:255],
        description        = _get(raw, "clmMthd", "plcyExplnCn", "description", "applyMethod", "aplcMthd"),
        apply_url          = _parse_url(raw, "hpgeUrl", "applyUrl", "plcyHomeUrl", "url"),
        application_period = f"{grnt_from} ~ {grnt_end}" if grnt_from or grnt_end else "",
    )


# =============================================
# SyncService
# =============================================

class SyncService:
    def __init__(self, db: Session):
        self.db = db

    def sync_products(self, items: list[dict], category: str) -> dict:
        """
        items: rawExternalDocument 리스트 (api-connector에서 직접 전달)
        category: CARD | INSURANCE | POLICY
        """
        saved, skipped, failed = 0, 0, 0

        for item in items:
            try:
                raw         = item.get("rawPayload", {})
                external_id = item.get("externalId")
                source_code = item.get("sourceCode", "")

                if not external_id:
                    logger.warning(f"[SyncService] externalId 누락 스킵 - sourceCode={source_code}")
                    failed += 1
                    continue

                if category == "CARD":
                    existing = self.db.query(CardProduct).filter(CardProduct.external_id == external_id).first()
                    if existing:
                        skipped += 1
                        continue
                    mapped = _map_card(source_code, raw)
                    with self.db.begin_nested():
                        self.db.add(CardProduct(key=TSID.create(), external_id=external_id, **mapped))

                elif category == "INSURANCE":
                    existing = self.db.query(InsuranceProduct).filter(InsuranceProduct.external_id == external_id).first()
                    if existing:
                        skipped += 1
                        continue
                    mapped = _map_insurance(source_code, raw)
                    with self.db.begin_nested():
                        self.db.add(InsuranceProduct(key=TSID.create(), external_id=external_id, **mapped))

                elif category == "POLICY":
                    existing = self.db.query(PolicyProduct).filter(PolicyProduct.external_id == external_id).first()
                    if existing:
                        skipped += 1
                        continue
                    mapped = _map_policy(source_code, raw)
                    with self.db.begin_nested():
                        self.db.add(PolicyProduct(
                            key=TSID.create(),
                            external_id=external_id,
                            conflict_policy_ids="[]",
                            **mapped,
                        ))

                saved += 1

            except IntegrityError:
                skipped += 1
                logger.warning(f"[SyncService] 중복 스킵 - external_id={item.get('externalId')}")
            except (TypeError, ValueError, AttributeError) as e:
                logger.error(f"[SyncService] payload 매핑 실패 - external_id={item.get('externalId')}, error={e}")
                failed += 1
            except SQLAlchemyError as e:
                logger.error(f"[SyncService] DB 저장 실패 - external_id={item.get('externalId')}, error={e}")
                failed += 1

        self._commit(category)
        logger.info(f"[SyncService] {category} 동기화 완료 - saved={saved}, skipped={skipped}, failed={failed}")
        return {"saved": saved, "skipped": skipped, "failed": failed}

    def _commit(self, label: str) -> None:
        try:
            self.db.commit()
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[SyncService] {label} 커밋 실패 - error={e}")
            raise