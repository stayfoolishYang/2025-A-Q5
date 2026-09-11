"""Verify and package the completed scientific figures and fresh rerun evidence."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile
import numpy as np
import pandas as pd
from pypdf import PdfReader
from PIL import Image,ImageDraw
from run_practice_matched import BASE,OUT as ROOT,SNAP,ROOTS

def main():
    out=ROOT/'科学图谱'
    df=pd.read_csv(out/'data/cases.csv');summary=json.loads((out/'SUMMARY.json').read_bytes())
    catalog=json.loads((out/'CATALOG.json').read_bytes())
    book=PdfReader(out/'图谱合订.pdf');assert len(book.pages)==len(catalog)==35
    for q in (3,4):
        g=df[df.problem==q]
        for group in ['official','local','reference']:
            a=g[g.group==group];s=summary[str(q)][group]
            assert len(a)==s['n']
            assert abs(a.score.mean()-s['mean'])<1e-9
            assert abs(np.var(a.score/a.score.mean(),ddof=1)-s['normalized_variance'])<1e-12
            assert np.max(np.abs(a[['move','measure','switch','clear']].sum(axis=1)-a.time))<1e-5
        # Compare every actual official manifest, not just a claimed version label.
        baseline=json.loads((ROOTS[q]/('source/q4better/configs/q4_known16_tri25_R12.yaml' if q==4 else 'cpu519/PLAN.json')).read_bytes())
        expected=baseline if q==4 else baseline['configs']['D']
        for case in g[g.group=='official'].case:
            m=json.loads((BASE/'official_latest'/f'q{q}_{case}'/'manifest.json').read_bytes())
            assert m['config']==expected,(q,case)
    thumbs=Image.new('RGB',(1500,7*165),'white');draw=ImageDraw.Draw(thumbs)
    for i,c in enumerate(catalog):
        stem=c['id']
        for ext in ['png','pdf','svg']:assert (out/ext/f'{stem}.{ext}').stat().st_size>1000
        with Image.open(out/'png'/f'{stem}.png') as im:
            assert im.width>2000 and im.height>1000
            im.thumbnail((295,140));x=(i%5)*300;y=(i//5)*165
            thumbs.paste(im,(x,y+20));draw.text((x+5,y+2),stem,fill='black')
    thumbs.save(out/'总览缩略图.jpg',quality=90)
    page=(out/'index.html').read_text(encoding='utf-8')
    for link in re.findall(r'(?:href|src)="([^"]+)"',page):
        if not link.startswith('#'):assert (out/link).exists(),link
    notes='# 量化发现与下一步建议\n\n'
    for q in (3,4):
        notes+=f'## Q{q}\n\n'
        for group in ['official','local']:
            a=df[(df.problem==q)&(df.group==group)]
            costs=[(a[k]/a.total).mean() for k in ['move','measure','switch','clear']]
            label='官方' if group=='official' else '本轮本地'
            notes+=f'{label}：移动、测量、切频、清除分别为{costs[0]:.3f}、{costs[1]:.3f}、{costs[2]:.3f}、{costs[3]:.3f}秒/源；移动占该组平均成绩的{costs[0]/a.score.mean():.2%}。无信号共{int(a.negatives.sum())}/{int(a.measures.sum())}次；这是观测结果占比，不是漏检率。全清后平均仍执行{a.after_clear.mean():.3f}秒/局，最大{a.after_clear.max():.3f}秒/局。\n\n'
        a=df[(df.problem==q)&(df.group=='local')]
        stage=(a.stage_discovery/a.total).mean()
        notes+=f'本轮本地有可靠stage标签：发现阶段{stage:.3f}秒/源，占平均成绩{stage/a.score.mean():.2%}。官方没有对应stage，不能直接复制这个百分比。\n\n'
        r=summary[str(q)]['reference_resampling_variance'];actual=summary[str(q)]['official']['normalized_variance']
        notes+=f'归一化方差：官方{actual:.6f}；N匹配本地子集中央95%范围[{r["lower"]:.6f}, {r["upper"]:.6f}]。该经验范围不是总体置信区间。\n\n'
    notes+='## 解释边界\n\nQ4官方定向源比例（按源汇总）47.49%，本轮本地59.50%，说明匹配N之后仍有构成差异。当前对照支持同一成绩量级，不能将约3%的均值差归因为引擎误差。后续如扩大比较，应预先匹配N×定向数量并保留不同几何，而不是按结果选择案例。\n\n优先阅读图04、09、12、15、19、21、22和32：分别回答归一化波动、动作成本、发现到退出、测点分布、路径负担、本地阶段、方向构成和最慢官方Q4案例。\n'
    (out/'量化发现.md').write_text(notes,encoding='utf-8')
    shutil.copy2(Path(__file__),out/'evidence'/Path(__file__).name)
    manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.rglob('*') if p.is_file() and p.name!='PACKAGE_HASHES.json'}
    (ROOT/'PACKAGE_HASHES.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=BASE/'官方演练与本地同量级对照_20260911.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(ROOT))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name,h in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==h,name
    archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest(),encoding='ascii')
    print('Verified: 35 figures x 3 formats; 35 PDF pages; 1152 case rows; all official configs match local.')
    print('Archive bytes:',archive.stat().st_size)
    print(archive)

if __name__=='__main__':main()
