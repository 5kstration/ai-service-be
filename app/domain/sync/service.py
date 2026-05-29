# app/domain/sync/service.py
import json
import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.domain.recommend.entity import CardProduct, InsuranceProduct, PolicyProduct
from app.domain.sync.client import raw_external_client
from app.core.utils.tsid import TSID
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from app.domain.sync.conflict import update_conflict_ids

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self, db: Session):
        self.db = db

    # =============================================
    # 카드 동기화
    # =============================================

    def sync_card_products(self) -> dict:
        saved, skipped, failed = 0, 0, 0
        page = 0

        while True:
            result = raw_external_client.fetch_raw_externals(category="CARD", page=page, size=100)
            data  = result.get("data", {})
            items = data.get("content", [])

            if not items:
                break

            for item in items:
                try:
                    raw         = item.get("rawPayload", {})
                    external_id = item.get("externalId")
                    if not external_id:
                        logger.warning("[SyncService] externalId 누락으로 항목 스킵")
                        failed += 1
                        continue

                    existing = self.db.query(CardProduct).filter(
                        CardProduct.external_id == external_id
                    ).first()
                    if existing:
                        skipped += 1
                        continue

                    benefit_texts = raw.get("benefitTexts", [])
                    benefits = json.dumps(
                        [{"label": f"혜택 {i+1}", "value": b} for i, b in enumerate(benefit_texts)],
                        ensure_ascii=False,
                    )
                    
                    with self.db.begin_nested():
                        self.db.add(CardProduct(
                            key          = TSID.create(),
                            external_id  = external_id,
                            company      = raw.get("cardCompany") or raw.get("company", ""),
                            card_name    = raw.get("cardName", ""),
                            top_benefit  = raw.get("summary", ""),
                            benefits     = benefits,
                            apply_url    = raw.get("detailUrl", ""),
                            accent_color = "#3182F6",
                        ))
                    saved += 1

                except IntegrityError:
                    skipped += 1
                    logger.warning(f"[SyncService] 중복 external_id 스킵 - external_id={external_id}")
                except (TypeError, ValueError, AttributeError) as e:
                    logger.error(
                        f"[SyncService] 카드 payload 매핑 실패 - external_id={item.get('externalId')}, error={e}")
                    failed += 1
                except SQLAlchemyError as e:
                    logger.error(
                        f"[SyncService] 카드 저장 실패 - external_id={item.get('externalId')}, error={e}")
                    failed += 1

            if data.get("last", True):
                break
            page += 1

        self._commit("카드")
        logger.info(f"[SyncService] 카드 동기화 완료 - saved={saved}, skipped={skipped}, failed={failed}")
        return {"saved": saved, "skipped": skipped, "failed": failed}

    # =============================================
    # 보험 동기화
    # =============================================

    def sync_insurance_products(self) -> dict:
        saved, skipped, failed = 0, 0, 0
        page = 0

        while True:
            result = raw_external_client.fetch_raw_externals(category="INSURANCE", page=page, size=100)
            data  = result.get("data", {})
            items = data.get("content", [])

            if not items:
                break

            for item in items:
                try:
                    raw         = item.get("rawPayload", {})
                    external_id = item.get("externalId")
                    if not external_id:
                        logger.warning("[SyncService] externalId 누락으로 항목 스킵")
                        failed += 1
                        continue
                    existing = self.db.query(InsuranceProduct).filter(
                        InsuranceProduct.external_id == external_id
                    ).first()
                    if existing:
                        skipped += 1
                        continue

                    benefits = json.dumps([
                        {"label": "보험 유형",  "value": raw.get("ptrn", "")},
                        {"label": "보장 구분",  "value": raw.get("mog", "")},
                        {"label": "기준일",     "value": raw.get("basDt", "")},
                    ], ensure_ascii=False)
                    with self.db.begin_nested():
                        self.db.add(InsuranceProduct(
                            key            = TSID.create(),
                            external_id    = external_id,
                            insurer        = raw.get("cmpyNm", ""),
                            insurance_name = raw.get("prdNm", ""),
                            top_benefit    = raw.get("mog", ""),
                            benefits       = benefits,
                            apply_url      = None,
                            accent_color   = "#8B5CF6",
                        ))
                    saved += 1
                except IntegrityError:
                    skipped += 1
                    logger.warning(f"[SyncService] 중복 external_id 스킵 - external_id={external_id}")
                except (TypeError, ValueError, AttributeError) as e:
                    logger.error(
                        f"[SyncService] 보험 payload 매핑 실패 - external_id={item.get('externalId')}, error={e}")
                    failed += 1
                except SQLAlchemyError as e:
                    logger.error(
                        f"[SyncService] 보험 저장 실패 - external_id={item.get('externalId')}, error={e}")
                    failed += 1

            if data.get("last", True):
                break
            page += 1

        self._commit("보험")
        logger.info(f"[SyncService] 보험 동기화 완료 - saved={saved}, skipped={skipped}, failed={failed}")
        return {"saved": saved, "skipped": skipped, "failed": failed}

    # =============================================
    # 청년 정책 동기화
    # =============================================

    def sync_policy_products(self) -> dict:
        saved, skipped, failed = 0, 0, 0
        page = 0

        while True:
            result = raw_external_client.fetch_raw_externals(category="POLICY", page=page, size=100)
            data  = result.get("data", {})
            items = data.get("content", [])

            if not items:
                break

            for item in items:
                try:
                    raw         = item.get("rawPayload", {})
                    external_id = item.get("externalId")
                    if not external_id:
                        logger.warning("[SyncService] externalId 누락으로 항목 스킵")
                        failed += 1
                        continue
                    existing = self.db.query(PolicyProduct).filter(
                        PolicyProduct.external_id == external_id
                    ).first()
                    if existing:
                        skipped += 1
                        continue

                    grnt_items = raw.get("lcgvrGrnt", [])
                    tags = json.dumps(
                        [g.get("grntItmNm", "") for g in grnt_items[:3]],
                        ensure_ascii=False,
                    )

                    grnt_end = raw.get("grntEnd", "")
                    deadline = ""
                    if grnt_end and len(grnt_end) == 8:
                        deadline = f"{grnt_end[:4]}.{grnt_end[4:6]}.{grnt_end[6:]}"
                    with self.db.begin_nested():
                        self.db.add(PolicyProduct(
                            key                = TSID.create(),
                            external_id        = external_id,
                            policy_name        = raw.get("insrncGdsNm", ""),
                            org                = raw.get("orgNm") or raw.get("upOrgNm", ""),
                            category           = "안전보험",
                            category_color     = "#3182F6",
                            deadline           = deadline,
                            dday               = None,
                            tags               = tags,
                            core_benefit       = (raw.get("insrdNm", "") or "")[:255],
                            description        = raw.get("clmMthd", ""),
                            apply_url          = raw.get("hpgeUrl", ""),
                            application_period = f"{raw.get('grntFrom', '')} ~ {raw.get('grntEnd', '')}",
                        ))
                    saved += 1
                    all_policies = self.db.query(PolicyProduct).all()
                    update_conflict_ids(self.db, all_policies)

                except IntegrityError:
                    skipped += 1
                    logger.warning(f"[SyncService] 중복 external_id 스킵 - external_id={external_id}")
                except (TypeError, ValueError, AttributeError) as e:
                    logger.error(
                        f"[SyncService] 정책 payload 매핑 실패 - external_id={item.get('externalId')}, error={e}")
                    failed += 1
                except SQLAlchemyError as e:
                    logger.error(
                        f"[SyncService] 정책 저장 실패 - external_id={item.get('externalId')}, error={e}")
                    failed += 1

            if data.get("last", True):
                break
            page += 1

        if saved > 0:
            all_policies = self.db.query(PolicyProduct).all()
            update_conflict_ids(self.db, all_policies)

        self._commit("정책")

        logger.info(f"[SyncService] 정책 동기화 완료 - saved={saved}, skipped={skipped}, failed={failed}")
        return {"saved": saved, "skipped": skipped, "failed": failed}

    # =============================================
    # 공통 커밋
    # =============================================

    def _commit(self, label: str) -> None:
        try:
            self.db.commit()
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"[SyncService] {label} 커밋 실패 - error={e}")
            raise