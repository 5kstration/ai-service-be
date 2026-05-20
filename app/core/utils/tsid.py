import time
import random
import threading

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


#java쪽 tsid 구성 동일을 위해 직접 구현
class TSID:
    NODE_BITS = 10
    COUNTER_BITS = 12
    _lock = threading.Lock()
    node = random.randint(0, (1 << NODE_BITS) - 1)
    counter = 0
    last_time = 0

    @classmethod
    def create(cls) -> str:
        # race
        with cls._lock:
            ts = int(time.time() * 1000)
            if ts == cls.last_time:
                cls.counter += 1
                if cls.counter >= (1 << cls.COUNTER_BITS):  # 4096 초과 방지
                    while ts <= cls.last_time:
                        time.sleep(0.0001)
                        ts = int(time.time() * 1000)
                    cls.counter = 0
                    cls.last_time = ts
            else:
                cls.counter = 0
                cls.last_time = ts
            value = (
                (ts << (cls.NODE_BITS + cls.COUNTER_BITS))
                | (cls.node << cls.COUNTER_BITS)
                | cls.counter
            )
            return cls._to_base32(value)

    @staticmethod
    def _to_base32(value: int) -> str:
        if value == 0:
            return ALPHABET[0]
        chars = []
        while value > 0:
            value, rem = divmod(value, 32)
            chars.append(ALPHABET[rem])
        return ''.join(reversed(chars))