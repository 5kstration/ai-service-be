# app/domain/sync/service.py
import json
import logging
from typing import Optional
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.domain.recommend.entity import CardProduct, InsuranceProduct, PolicyProduct
from app.domain.sync.client import raw_external_client
from app.core.utils.tsid import TSID

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self, db: Session):
        self.db = db

    # =============================================
    # 카드 동기화
    # =============================================

    def sync_card_products(self) -> dict:
        """
        raw-externals에서 CARD 데이터 가져와서 card_product 테이블에 저장.
        rawPayload 구조: TOSS_CARD_LOUNGE 기준
        """
        result = raw_external_client.fetch_raw_externals(category="CARD", size=100)
        items = result.get("data", {}).get("content", [])

        saved, skipped, failed = 0, 0, 0

        for item in items:
            try:
                raw = item.get("rawPayload", {})
                external_id = item.get("externalId", "")

                # 이미 존재하면 스킵 (external_id 기반 중복 체크)
                existing = self.db.query(CardProduct).filter(
                    CardProduct.external_id == external_id
                ).first()
                if existing:
                    skipped += 1
                    continue

                # benefitTexts 배열 → [{label, value}] 형태로 변환
                benefit_texts = raw.get("benefitTexts", [])
                benefits = json.dumps(
                    [{"label": f"혜택 {i+1}", "value": b} for i, b in enumerate(benefit_texts)],
                    ensure_ascii=False
                )

                card = CardProduct(
                    key          = TSID.create(),
                    external_id  = external_id,
                    company      = raw.get("cardCompany") or raw.get("company", ""),
                    card_name    = raw.get("cardName", ""),
                    top_benefit  = raw.get("summary", ""),
                    benefits     = benefits,
                    apply_url    = raw.get("detailUrl", ""),
                    accent_color = "#3182F6",  # 기본값
                )
                self.db.add(card)
                saved += 1

            except Exception as e:
                logger.error(f"[SyncService] 카드 저장 실패 - external_id={item.get('externalId')}, error={e}")
                failed += 1

        try:
            self.db.commit()
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[SyncService] 카드 커밋 실패 - error={e}")
            raise

        logger.info(f"[SyncService] 카드 동기화 완료 - saved={saved}, skipped={skipped}, failed={failed}")
        return {"saved": saved, "skipped": skipped, "failed": failed}

    # =============================================
    # 보험 동기화
    # =============================================

    def sync_insurance_products(self) -> dict:
        """
        raw-externals에서 INSURANCE 데이터 가져와서 insurance_product 테이블에 저장.
        rawPayload 구조: INDEMNITY_INSURANCE 기준
        """
        result = raw_external_client.fetch_raw_externals(category="INSURANCE", size=100)
        items = result.get("data", {}).get("content", [])

        saved, skipped, failed = 0, 0, 0

        for item in items:
            try:
                raw = item.get("rawPayload", {})
                external_id = item.get("externalId", "")

                existing = self.db.query(InsuranceProduct).filter(
                    InsuranceProduct.external_id == external_id
                ).first()
                if existing:
                    skipped += 1
                    continue

                # 보험 혜택 정제
                benefits = json.dumps([
                    {"label": "보험 유형", "value": raw.get("ptrn", "")},
                    {"label": "보장 구분", "value": raw.get("mog", "")},
                    {"label": "기준일", "value": raw.get("basDt", "")},
                ], ensure_ascii=False)

                insurance = InsuranceProduct(
                    key            = TSID.create(),
                    external_id    = external_id,
                    insurer        = raw.get("cmpyNm", ""),
                    insurance_name = raw.get("prdNm", ""),
                    top_benefit    = raw.get("mog", ""),
                    benefits       = benefits,
                    apply_url      = None,
                    accent_color   = "#8B5CF6",
                )
                self.db.add(insurance)
                saved += 1

            except Exception as e:
                logger.error(f"[SyncService] 보험 저장 실패 - external_id={item.get('externalId')}, error={e}")
                failed += 1

        try:
            self.db.commit()
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[SyncService] 보험 커밋 실패 - error={e}")
            raise

        logger.info(f"[SyncService] 보험 동기화 완료 - saved={saved}, skipped={skipped}, failed={failed}")
        return {"saved": saved, "skipped": skipped, "failed": failed}

    # =============================================
    # 청년 정책 동기화
    # =============================================

    def sync_policy_products(self) -> dict:
        """
        raw-externals에서 POLICY 데이터 가져와서 policy_product 테이블에 저장.
        rawPayload 구조: SAFE_INSURANCE 기준
        """
        result = raw_external_client.fetch_raw_externals(category="POLICY", size=100)
        items = result.get("data", {}).get("content", [])

        saved, skipped, failed = 0, 0, 0

        for item in items:
            try:
                raw = item.get("rawPayload", {})
                external_id = item.get("externalId", "")

                existing = self.db.query(PolicyProduct).filter(
                    PolicyProduct.external_id == external_id
                ).first()
                if existing:
                    skipped += 1
                    continue

                # 보장 항목 → tags 및 benefits 정제
                grnt_items = raw.get("lcgvrGrnt", [])
                tags = json.dumps(
                    [g.get("grntItmNm", "") for g in grnt_items[:3]],  # 상위 3개만 태그
                    ensure_ascii=False
                )

                # 마감일 파싱 (grntEnd: "20261231" → "2026.12.31")
                grnt_end = raw.get("grntEnd", "")
                deadline = ""
                if grnt_end and len(grnt_end) == 8:
                    deadline = f"{grnt_end[:4]}.{grnt_end[4:6]}.{grnt_end[6:]}"

                policy = PolicyProduct(
                    key              = TSID.create(),
                    external_id      = external_id,
                    policy_name      = raw.get("insrncGdsNm", ""),
                    org              = raw.get("orgNm") or raw.get("upOrgNm", ""),
                    category         = "안전보험",
                    category_color   = "#3182F6",
                    deadline         = deadline,
                    dday             = None,  # 별도 계산 필요
                    tags             = tags,
                    core_benefit     = raw.get("insrdNm", "")[:255] if raw.get("insrdNm") else "",
                    description      = raw.get("clmMthd", ""),
                    apply_url        = raw.get("hpgeUrl", ""),
                    application_period = f"{raw.get('grntFrom', '')} ~ {raw.get('grntEnd', '')}",
                )
                self.db.add(policy)
                saved += 1

            except Exception as e:
                logger.error(f"[SyncService] 정책 저장 실패 - external_id={item.get('externalId')}, error={e}")
                failed += 1

        try:
            self.db.commit()
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[SyncService] 정책 커밋 실패 - error={e}")
            raise

        logger.info(f"[SyncService] 정책 동기화 완료 - saved={saved}, skipped={skipped}, failed={failed}")
        return {"saved": saved, "skipped": skipped, "failed": failed}