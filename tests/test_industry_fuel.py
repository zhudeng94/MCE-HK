from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cmhk.sectors.industry import monthly_fuel


def test_annual_fuel_survives_different_monthly_shapes_and_partial_year_is_not_normalized():
    annual=pd.DataFrame({'gas_lpg_TJ':[120.],'oil_coal_TJ':[240.],
                         'electricity_excluded_TJ':[999999.]},index=[2021])
    dates=pd.date_range('2021-01-01','2022-03-01',freq='MS')
    activity=pd.DataFrame({'GASC_LOCAL':10.,'ELEC_LOCAL':np.r_[np.arange(1,13),[2.,4.,6.]]},index=dates)
    result=monthly_fuel(annual,activity,2021,'2022-03-15')
    observed=result[result.date.dt.year.eq(2021)].groupby('component').fuel_TJ.sum()
    assert np.isclose(observed.gaseous_fuels,120.)
    assert np.isclose(observed.liquid_and_solid_fuels,240.)
    tail=result[result.date.dt.year.eq(2022)]
    assert set(tail.date.dt.month)=={1,2}
    assert np.isclose(tail[tail.component.eq('gaseous_fuels')].fuel_TJ.sum(),20.)
    assert np.isclose(tail[tail.component.eq('liquid_and_solid_fuels')].fuel_TJ.sum(),240*6/78)
    reshaped=activity.copy();reshaped.loc['2021','ELEC_LOCAL']=1.
    other=monthly_fuel(annual,reshaped,2021,'2022-03-15')
    assert np.isclose(other[other.date.dt.year.eq(2021)].fuel_TJ.sum(),360.)


def test_missing_month_does_not_redistribute_annual_fuel_over_surviving_months():
    annual=pd.DataFrame({'gas_lpg_TJ':[120.],'oil_coal_TJ':[240.]},index=[2021])
    activity=pd.DataFrame({'GASC_LOCAL':1.,'ELEC_LOCAL':1.},index=pd.date_range('2021-01-01',periods=12,freq='MS'))
    activity.loc['2021-02-01','ELEC_LOCAL']=np.nan
    result=monthly_fuel(annual,activity,2021,'2022-01-01')
    assert set(result.component)=={'gaseous_fuels'}
