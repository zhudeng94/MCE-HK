from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cmhk.sectors.transport_annual import proxy_series, marine_energy
from cmhk.benchmarks.transport import extract_transport


def test_full_transport_weights_include_residual_without_bunkers():
    # A 10% road decline and 20% marine growth yield -4%, with 80:20 weights.
    baseline = {'road': 80., 'marine': 20., 'transport': 105.}
    result = proxy_series(pd.Series({2021: 40., 2022: 36.}),
                          pd.Series({2021: 10., 2022: 12.}), baseline)
    assert np.isclose(result.loc[2021, 'transport_proxy_ktCO2'], 105)
    assert np.isclose(result.loc[2022, 'transport_proxy_ktCO2'], 100.8)
    assert np.isclose(result.loc[2022, 'residual_assumed_proxy_ktCO2'], 4.8)
    assert np.isclose(result.loc[2022, 'yoy_pct'], -4)
    # Rescaling the original road series must not change its activity index.
    scaled = proxy_series(pd.Series({2021: 400., 2022: 360.}),
                          pd.Series({2021: 10., 2022: 12.}), baseline)
    np.testing.assert_allclose(result.transport_proxy_ktCO2, scaled.transport_proxy_ktCO2)


def test_missing_marine_and_gapped_year_do_not_create_totals_or_yoy():
    result = proxy_series(pd.Series({2021: 40., 2022: 36., 2023: 38., 2025: 40.}),
                          pd.Series({2021: 10., 2023: 12., 2025: 13.}),
                          {'road': 80., 'marine': 20., 'transport': 105.})
    assert pd.isna(result.loc[2022, 'transport_proxy_ktCO2'])
    assert not result.loc[2022, 'complete']
    assert pd.isna(result.loc[2023, 'yoy_pct'])
    assert pd.isna(result.loc[2025, 'yoy_pct'])


def test_invalid_inventory_margin_rejected():
    with pytest.raises(ValueError, match='smaller'):
        proxy_series(pd.Series({2021: 1.}), pd.Series({2021: 1.}),
                     {'road': 80., 'marine': 20., 'transport': 90.})


@pytest.mark.integration
def test_explicit_marine_does_not_consume_early_others():
    marine, _ = marine_energy()
    assert marine.index.min() == 2008
    assert 2005 not in marine.index
    # Old 2017 Others would produce 9894 TJ; explicit 2020 Marine = 9680 TJ.
    assert marine.loc[2008, 'marine_TJ'] == 5922 + 3758
    assert marine.loc[2024, 'marine_TJ'] == 2313 + 4561
    assert marine.loc[2021, 'emsd_edition'] == 2026


@pytest.mark.integration
def test_crt_top_level_categories_exclude_child_double_counting():
    book = next((ROOT / 'data/raw/inventory').rglob('*-2021-*.xlsx'))
    components, total = extract_transport(book)
    assert len(components) == 5
    assert np.isclose(total, 6338.25666002)
    assert np.isclose(components.official_ktCO2.sum(), total)
    assert np.isclose(components.set_index('category').loc['1.A.3.e', 'official_ktCO2'], 216.68819466)
