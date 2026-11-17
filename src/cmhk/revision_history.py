"""Content-addressed snapshots and explicit same-month revision records."""
from datetime import datetime, timezone
import hashlib
import json
import pandas as pd


def record_snapshot(monthly, root):
    folder = root/'outputs/near_realtime/history'
    folder.mkdir(parents=True,exist_ok=True)
    fields = ['date','sector','ktCO2','temporal_status','prediction_model','reference_period']
    current = monthly[fields].sort_values(['date','sector']).copy()
    current['date'] = pd.to_datetime(current.date).dt.strftime('%Y-%m-%d')
    payload = current.to_csv(index=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    latest = folder/'latest.json'
    prior = json.loads(latest.read_text()) if latest.exists() else None
    if prior and prior['sha256']==digest:
        return
    timestamp = datetime.now(timezone.utc).isoformat()
    destination = folder/f'{digest}.csv'
    destination.write_text(payload)
    if prior:
        old = pd.read_csv(folder/prior['file'])
    elif (root/'outputs/hong_kong_sector_monthly.csv').exists():
        old = pd.read_csv(root/'outputs/hong_kong_sector_monthly.csv')
        if 'temporal_status' not in old:
            old['temporal_status'] = 'previous_release_unspecified'
    else:
        old = pd.DataFrame(columns=['date','sector','ktCO2','temporal_status'])
    joined = old[['date','sector','ktCO2','temporal_status']].merge(current,on=['date','sector'],how='outer',suffixes=('_previous','_current'))
    joined['ktCO2_previous'] = pd.to_numeric(joined.ktCO2_previous,errors='coerce')
    joined['ktCO2_current'] = pd.to_numeric(joined.ktCO2_current,errors='coerce')
    different = ~((joined.ktCO2_previous.fillna(-1)-joined.ktCO2_current.fillna(-1)).abs()<1e-8)
    different |= joined.temporal_status_previous.fillna('missing').ne(joined.temporal_status_current.fillna('missing'))
    changed = joined[different].copy()
    changed['revision_ktCO2'] = changed.ktCO2_current-changed.ktCO2_previous
    changed['revision_pct'] = (changed.ktCO2_current/changed.ktCO2_previous-1)*100
    changed['recorded_at'] = timestamp
    changed['version'] = digest
    changed['reason'] = 'input_or_method_update; not necessarily nowcast_error'
    changed.to_csv(folder/f'revisions_{digest}.csv',index=False)
    latest.write_text(json.dumps(dict(file=destination.name,sha256=digest,recorded_at=timestamp,
        as_of=str(monthly.as_of.iloc[0])),indent=2)+'\n')
