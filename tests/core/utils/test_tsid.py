from app.core.utils.tsid import TSID

def test_tsid_create():
    """
    TSID가 정상적으로 문자열을 반환하고 중복되지 않는지 검증합니다.
    """
    tsid1 = TSID.create()
    assert isinstance(tsid1, str)
    assert len(tsid1) > 0
    
    tsid2 = TSID.create()
    assert isinstance(tsid2, str)
    assert tsid1 != tsid2
