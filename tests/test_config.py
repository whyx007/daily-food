from app.config import Settings


def test_defaults_and_radius_list():
    s = Settings(amap_key="k", _env_file=None)
    assert s.default_lat == 39.90923
    assert s.daily_call_limit == 500
    assert s.radius_list == [500, 1000, 2000, 3000]


def test_radius_options_parsing_ignores_spaces():
    s = Settings(radius_options=" 800, 1500 ", _env_file=None)
    assert s.radius_list == [800, 1500]


def test_empty_env_gives_empty_key():
    s = Settings(_env_file=None)
    assert s.amap_key == ""
