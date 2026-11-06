from app.geo import haversine_m, quantize_grid


def test_quantize_grid_rounds_to_500m_cells():
    assert quantize_grid(39.90923, 116.397428) == "39.910,116.395"


def test_quantize_grid_same_cell_for_nearby_points():
    assert quantize_grid(39.9110, 116.3960) == quantize_grid(39.9080, 116.3940)


def test_haversine_m_about_850m_for_0_01_lng_at_39_9():
    d = haversine_m(39.90923, 116.397428, 39.90923, 116.407428)
    assert 800 <= d <= 900


def test_haversine_zero_distance():
    assert haversine_m(39.9, 116.4, 39.9, 116.4) == 0
