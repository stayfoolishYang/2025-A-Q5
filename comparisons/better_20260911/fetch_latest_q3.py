import concurrent.futures,hashlib,json,subprocess,time,urllib.request
from pathlib import Path

SHA='79766ecf0d2577289f814edba310327f55424111'
OUT=Path('J:/2026B_runs/q3_latest_79766ec/source')
OLD=Path(__file__).parent
def main():
    tree=json.loads(subprocess.check_output(['gh','api',f'repos/zhuoshou111/2025-A-Q5/git/trees/{SHA}?recursive=1']))
    assert not tree.get('truncated')
    files=[x for x in tree['tree'] if x['type']=='blob' and x['path'].startswith('q3better/')]
    def fetch(x):
        dest=OUT/x['path'];dest.parent.mkdir(parents=True,exist_ok=True)
        def valid(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==x['sha']
        for p in (dest,OLD/x['path']):
            if p.exists():
                b=p.read_bytes()
                if valid(b):dest.write_bytes(b);return
        for i in range(4):
            try:
                with urllib.request.urlopen(f'https://raw.githubusercontent.com/zhuoshou111/2025-A-Q5/{SHA}/{x["path"]}',timeout=30) as r:b=r.read()
                assert valid(b)
                dest.write_bytes(b);return
            except Exception:
                if i==3:
                    b=subprocess.check_output(['gh','api','-H','Accept: application/vnd.github.raw+json',f'repos/zhuoshou111/2025-A-Q5/git/blobs/{x["sha"]}'])
                    assert valid(b),x['path']
                    dest.write_bytes(b);return
                time.sleep(1+i)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for i,_ in enumerate(pool.map(fetch,files),1):
            if i%50==0:print('Verified',i,'/',len(files),flush=True)
    (OUT/'SOURCE.json').write_text(json.dumps(dict(commit=SHA,files=files),indent=2),encoding='utf-8')
    print('DONE',len(files),flush=True)
if __name__=='__main__':main()
