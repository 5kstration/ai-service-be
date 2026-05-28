import sys
import os
import random
import uuid
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
load_dotenv()

from app.core.client.neo4j_client import neo4j_client
from app.core.config.settings import settings

CATEGORIES = ["식비", "교통", "쇼핑", "카페", "주거", "문화", "통신"]

def generate_graph_users():
    print("🚀 그래프 풍부화: 더미 유저 및 구독(Subscription) 관계 생성 중...")
    with neo4j_client._driver.session(database=settings.NEO4J_DATABASE) as session:
        # 기존 User 삭제 (초기화)
        session.run("MATCH (u:User) DETACH DELETE u")
        
        # 상품 키 가져오기
        policies = [r["key"] for r in session.run("MATCH (p:Policy) RETURN p.key AS key")]
        cards = [r["key"] for r in session.run("MATCH (c:Card) RETURN c.key AS key")]
        insurances = [r["key"] for r in session.run("MATCH (i:Insurance) RETURN i.key AS key")]
        
        print(f"  상품 로드 완료: Policy {len(policies)}개, Card {len(cards)}개, Insurance {len(insurances)}개")
        
        if not policies or not cards or not insurances:
            print("❌ 상품이 Neo4j에 없습니다. 먼저 graph_sync.py를 실행하세요.")
            return

        batch_size = 100
        for b in range(10): # 1000 users total
            for i in range(batch_size):
                user_id = f"01HXGRAPH{str(b*batch_size + i).zfill(4)}{uuid.uuid4().hex[:10].upper()}"
                fav_cat = random.choice(CATEGORIES)
                
                sub_policies = random.sample(policies, random.randint(1, 3))
                sub_cards = random.sample(cards, random.randint(1, 3))
                sub_insurances = random.sample(insurances, random.randint(1, 3))
                
                # Cypher query for this user
                q = f"CREATE (u:User {{user_id: '{user_id}', favorite_category: '{fav_cat}'}})\n"
                for p_key in sub_policies:
                    q += f"WITH u MATCH (p:Policy {{key: '{p_key}'}}) MERGE (u)-[:SUBSCRIBED_TO]->(p)\n"
                for c_key in sub_cards:
                    q += f"WITH u MATCH (c:Card {{key: '{c_key}'}}) MERGE (u)-[:SUBSCRIBED_TO]->(c)\n"
                for i_key in sub_insurances:
                    q += f"WITH u MATCH (ins:Insurance {{key: '{i_key}'}}) MERGE (u)-[:SUBSCRIBED_TO]->(ins)\n"
                
                session.run(q)
                
            print(f"  ✅ {(b+1)*batch_size}명 생성 완료...")
        
        print("✅ 그래프 더미 데이터 생성 및 관계 연결 완료!")

if __name__ == "__main__":
    generate_graph_users()
