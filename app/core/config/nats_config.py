import asyncio
import nats
import os
from dotenv import load_dotenv

load_dotenv()

NATS_URL = os.getenv("NATS_URL", "nats://10.0.2.65:4222")

nc = None
js = None

async def connect_nats():
    global nc, js
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    print(f"NATS 연결 성공: {NATS_URL}")
    return nc, js

async def close_nats():
    global nc
    if nc:
        await nc.close()
        print("NATS 연결 종료")

def get_jetstream():
    return js

if __name__ == "__main__":
    async def test():
        await connect_nats()
        print("NATS JetStream 연결 성공!")
        await close_nats()

    asyncio.run(test())
