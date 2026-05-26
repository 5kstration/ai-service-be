# app/domain/recommend_ai/reranker.py
import logging
from sentence_transformers import CrossEncoder
import numpy as np

logger = logging.getLogger(__name__)

class RerankerClient:
    def __init__(self):
        self._model = None
        try:
            model = CrossEncoder("bongsoo/klue-cross-encoder-v1")
            model.predict([["warmup", "warmup"]], show_progress_bar=False)
            self._model = model
            logger.info("[Reranker] 모델 로드 완료")
        except Exception as e:
            logger.warning(f"[Reranker] 모델 초기화 실패 - fallback only. error={e}")


    def rerank(self, query, documents, top_n=7):
        if not documents:
            return []
        if len(documents) <= top_n:
            return list(range(len(documents)))
        if self._model is None:
            return list(range(min(top_n, len(documents))))

        try:
            pairs  = [[query, doc] for doc in documents]
            scores = self._model.predict(pairs, show_progress_bar=False)

            # 1. numpy 변환
            scores_np   = np.array(scores).flatten()
            # 2. 리스트 생성
            scores_list = [(float(scores_np[idx]), idx) for idx in range(len(scores_np))]
            # 3. 정렬
            scores_list.sort(key=lambda x: x[0], reverse=True)
            # 4. 인덱스 추출
            indices = [idx for _, idx in scores_list[:top_n]]

            logger.info(f"[Reranker] 완료 - {len(documents)}→{top_n}개, top score={scores_list[0][0]:.4f}")
            return indices

        except Exception as e:
            logger.warning(f"[Reranker] 실패 - fallback. error={e}")
            return list(range(min(top_n, len(documents))))

reranker_client = RerankerClient()