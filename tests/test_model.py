import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cmhk.kernels import allocate, constrained_months, split_generation, forward_holdout
from cmhk.sources.prepare import complete_oil_quarters

def test_quarter_preserves_benchmark_and_calendar():
    weights = pd.Series([10.,20.,30.], index=pd.date_range('2020-01-01',periods=3,freq='MS'))
    answer = constrained_months(120, weights, '2020Q1', 'Q')
    np.testing.assert_allclose(answer,[20,40,60])
    with pytest.raises(ValueError):
        constrained_months(120,weights.iloc[:2],'2020Q1','Q')

@pytest.mark.parametrize('values', [[0,0],[-1,2],[1,np.nan],[1,np.inf]])
def test_invalid_weights_rejected(values):
    with pytest.raises(ValueError):
        allocate(10, values)

def test_partial_year_cannot_absorb_annual_fuel():
    w = pd.Series(1.,index=pd.date_range('2026-01-01',periods=8,freq='MS'))
    with pytest.raises(ValueError):
        constrained_months(1200,w,'2026','Y')

def test_dispatch_preserves_both_margins_and_responds_to_demand():
    g = pd.Series([100,110,140,160,200,250,280,260,230,180,130,100],
                  index=pd.date_range('2024-01-01',periods=12,freq='MS'))
    gas, coal = split_generation(g,1200,2)
    np.testing.assert_allclose(gas+coal,g)
    assert np.isclose(gas.sum(),1200)
    assert (gas>=0).all() and (coal>=0).all()
    assert gas.iloc[6]/g.iloc[6] > gas.iloc[0]/g.iloc[0]
    constant,_ = split_generation(g,1200,0)
    np.testing.assert_allclose(constant/g,1200/g.sum())

def test_holdout_does_not_use_target_or_future():
    b = pd.Series([10.,20.,900.,40.],index=[2019,2020,2021,2022])
    a = pd.Series([1.,2.,3.,4.],index=b.index)
    v = forward_holdout(b,a)
    assert v.iloc[0].predicted == 30
    b.loc[2021:] = 100000
    assert forward_holdout(b,a).iloc[0].predicted == 30
    assert v.iloc[0].training_through == '2020'

def test_q4_is_annual_residual_not_repeated_annual():
    d = pd.DataFrame({'period':['2020','202003','202006','202009'],
                      'freq':['Y','Q','Q','Q'],'figure':[100.,10.,20.,30.],
                      'SALES_TYPEDesc':['Aircraft stores']*4,'PROD_TYPE':['E_1']*4})
    result = complete_oil_quarters(d)
    assert result[result.period=='202012'].figure.item() == 40
    assert result[result.freq=='Q'].figure.sum() == 100
    assert len(complete_oil_quarters(result)) == len(result)

def test_unit_conversion_and_direct_gas():
    from cmhk.context import EstimationContext
    context = EstimationContext()
    volume_tj, factor, CFG = context.volume_tj, context.factor, context.config
    # 1,000 kL jet fuel * 0.8 t/kL * 44.1 GJ/t = 35.28 TJ.
    assert np.isclose(volume_tj(1000,'jet_kerosene','Kilolitres'),35.28)
    assert np.isclose(35.28*factor('jet_kerosene'),2.52252)
    # One TJ = 1,000,000 MJ; kg -> kt cancels that million.
    assert np.isclose(CFG['town_gas_kg_co2_per_48_mj']/48,0.05310416666666667)

@pytest.mark.integration
def test_delivered_results_do_not_hide_missing_values():
    root=Path(__file__).resolve().parents[1]
    if not (root/'outputs/diagnostics/monthly_2019_2026.csv').exists():
        pytest.skip('Run pipeline before integration check')
    d=pd.read_csv(root/'outputs/hong_kong_sector_monthly.csv',parse_dates=['date'])
    assert len(d)==22*12*8
    assert not d.duplicated(['date','sector']).any()
    industry=d[(d.sector=='Industry')&(d.date<='2026-06-01')]
    assert industry.ktCO2.notna().all()
    import json
    cutoff=pd.Timestamp(json.loads((root/'configs/model.json').read_text())['as_of'])
    assert d[d.date+pd.offsets.MonthEnd()>cutoff].ktCO2.isna().all()
    b=pd.read_csv(root/'outputs/diagnostics/monthly_components.csv')
    assert np.isfinite(b.ktCO2).all() and b.ktCO2.ge(0).all()
    assert not b.duplicated(['date','sector','fuel','scenario']).any()
    checks=pd.read_csv(root/'outputs/diagnostics/consistency_checks.csv')
    assert checks.passed.all()
