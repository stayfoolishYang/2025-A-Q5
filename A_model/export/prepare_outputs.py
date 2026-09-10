from pathlib import Path
import json
import hashlib
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from validation.q4_contract import load_current_q4

def main():
    payload=[]
    load_current_q4()
    for q in range(1,5):
        data=np.load(ROOT/'results'/f'q{q}.npz')['data']
        meta=json.loads((ROOT/'results'/f'q{q}.json').read_text())
        n=meta['n']; data=data[data[:,0]>0]
        radii=np.arange(21)/10
        sheets=[]
        for title,start in ([('温度',2),('水分浓度',2+n)] if q<=2 else [('Sheet1',2+n)]):
            values=[]
            for row in data:
                field=row[start:start+n]; r=row[1]*100
                sampled=np.interp(radii,np.linspace(0,r,n),field)
                entries=[round(float(v),4) if pos<=r+1e-10 else None for pos,v in zip(radii,sampled)]
                if q==4: entries.append(round(float(field[-1]),4))
                values.append([float(row[0])]+entries)
            header=['时间\\到药材中心的距离']+radii.tolist()+(['药材表面'] if q==4 else [])
            sheets.append(dict(name=title,rows=[header]+values))
        item=dict(q=q,sheets=sheets)
        if q==4:
            item['source_sha256']={f'q4.{ext}':hashlib.sha256((ROOT/'results'/f'q4.{ext}').read_bytes()).hexdigest() for ext in ('json','npz')}
        payload.append(item)
        if q==4:
            np.savetxt(ROOT/'results'/'q4_radius_output.csv',np.column_stack((data[:,0],data[:,1]*100)),delimiter=',',header='time_s,radius_cm',comments='')
    (ROOT/'results'/'workbooks.json').write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8')

if __name__=='__main__':main()
