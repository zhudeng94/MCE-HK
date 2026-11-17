"""Keep the uncalibrated road activity estimate separate from full 1.A.3."""
import json
from pathlib import Path
import pandas as pd

from cmhk.paths import ROOT, code_hashes


def export_road_proxy(root=ROOT):
    config = json.loads((root/'configs/model.json').read_text())
    data = pd.read_csv(root/'outputs/diagnostics/monthly_scenarios.csv', parse_dates=['date'])
    method = config['transport_proxy']['road_method']
    road = data[data.sector.eq('Road') & data.scenario.eq(method)].copy()
    if road.empty or road.date.duplicated().any():
        raise ValueError('Missing or duplicated road activity estimate')
    dates = pd.date_range(f'{config["start_year"]}-01-01', f'{config["end_year"]}-12-01', freq='MS')
    result = road.set_index('date')[['ktCO2']].reindex(dates)
    result.index.name = 'date'
    result['sector'] = 'Road'
    result['method'] = method
    result.loc[result.index.year < 2013,'method'] = 'annual fuel benchmark + CEIC monthly demand proxy'
    result['role'] = 'road-only activity input; not the published Transport total'
    result.to_csv(root/'outputs/diagnostics/road_monthly_proxy.csv')
    return result
