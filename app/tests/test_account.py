import main


def test_extract_wedge_count():
    assert main.extract_wedge_count({"wedges": 249}) == 249
    assert main.extract_wedge_count({"wedges": "249"}) == 249
    assert main.extract_wedge_count({}) is None
    assert main.extract_wedge_count({"wedges": -1}) is None


def test_extract_bonus_points_from_seedbonus():
    assert main.extract_bonus_points({"seedbonus": 123456}) == 123456
    assert main.extract_bonus_points({"seedbonus": "123456.7"}) == 123456


def test_extract_bonus_points_fallback_keys():
    assert main.extract_bonus_points({"bonus": 5}) == 5
    assert main.extract_bonus_points({"points": 7}) == 7


def test_extract_bonus_points_missing_returns_none():
    assert main.extract_bonus_points({"wedges": 10}) is None


def test_extract_bonus_points_negative_returns_none():
    assert main.extract_bonus_points({"seedbonus": -3}) is None
