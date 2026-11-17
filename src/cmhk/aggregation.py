"""Published totals: Road includes residual transport; road + navigation preserves full 1.A.3."""
import pandas as pd

import json
from cmhk.paths import ROOT

_MAPPING = json.loads((ROOT / 'configs/sector_mapping.json').read_text())
SCOPES = _MAPPING['scopes']
LOCAL = SCOPES['covered_local_sectors']


def sum_complete(frame):
    return frame.sum(axis=1,min_count=frame.shape[1])


def with_transport_sum(frame):
    """Compatibility aggregate for broad external transport comparisons only."""
    result=frame.copy()
    result['Transport']=result[['Road Transport','Domestic Navigation']].sum(axis=1,min_count=2)
    return result
