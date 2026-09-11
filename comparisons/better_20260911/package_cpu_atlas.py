"""Package the completed atlas with an offline reading index."""
import hashlib, html, json, re, shutil, zipfile
from pathlib import Path
import pandas as pd
from PIL import Image

root=Path('J:/2026B_runs/CPU_519_科学图谱')
catalog=json.loads((root/'CATALOG.json').read_text(encoding='utf-8'))
assert len(catalog)==23
assert len(re.findall(rb'/Type\s*/Page\b',(root/'CPU519_完整科学图谱.pdf').read_bytes()))==23
for fmt in ('png','pdf','svg'):
    assert len(list((root/fmt).glob('*.'+fmt)))==23
for p in (root/'png').glob('*.png'):
    with Image.open(p) as im: im.verify()
df=pd.read_csv(root/'data/case_features.csv')
assert len(df)==2595 and not df.duplicated(['problem','variant','seed']).any()
summary=df.groupby(['problem','variant']).agg(cases=('seed','size'),mean_s_per_source=('score','mean'),median_s_per_source=('score','median'),maximum_s_per_source=('score','max'),mean_distance_m=('distance','mean'),mean_measurements=('measures','mean'))
summary.to_csv(root/'data/group_summary.csv',encoding='utf-8-sig')
intro='''# CPU 519种子图谱阅读指南

这套图谱包含23张复合图，依据2595次已完成的本地CPU运行和完整动作日志生成。每个方案519个种子；不混入CUDA、实机演练或官方成绩。本次仅提取、绘图和核对结果，没有启动求解器或官方测试。

## 建议阅读顺序

1. 图01—03：先判断平均收益、逐例胜负与尾部风险。Q3 B平均减少12.916秒/源，但最大值升到2813.654秒/源；Q4 C相对A平均减少124.584秒/源，519例均快，相对B仍有19例退步。
2. 图04—10：解释成本、源数、定向源比例、最后首次发现和全清后动作。成本只按移动、测量、切频道、清除四项分解。原日志阶段字段不足以可靠区分discovery/active/diagnostic，不能把四项动作成本冒称阶段耗时。
3. 图11—14：看圆域内外测量驻点、无信号比例、路径长度密度与真实源发现延迟。统一坐标、100m网格和同图色标便于横向比较；半径1800m虚线是真实目标圆域，不是机器人可达边界。
4. 图15—17：看归一化清除进度、种子族差异与最大退步清单。分位带是案例差异，不是置信区间。
5. 图18—23：Q3、Q4各选最大退步、最大节省和配对差中位附近案例；路径与发现/清除阶梯图成对呈现。它们按明示规则挑选，不是随机代表样本。

## 如何读空间图

- 测量热力：每格测量次数除以519，亮点表示高频驻点，不能解释成源出现概率。
- 无信号比例：无信号次数/测量次数，少于50次的格子留空；低访问量不能被误读为低风险。
- 路径热力：每段路径以不超过50m的中点采样分配长度，按519场归一化；总长度与日志相等，但栅格分配是近似，不是精确线段裁切。
- 发现延迟：按真实源位置聚合其首次被发现时刻，至少5个源事件才着色；这是离线解释，真实坐标不作为在线策略输入。
- 案例路径颜色：各方案自身的t/T；比较绝对速度应看下排统一秒轴。橙色空心点表示测量驻点，面积随重复次数增加；黑圆点为全向源，黑三角与箭头为定向源及朝向。

## 使用和审计

index.html为离线图文索引；CPU519_完整科学图谱.pdf适合连续审阅；png供预览，pdf/svg供论文排版和编辑。图表详解.md逐图列出研究意义、读法、结论边界和证据来源。

data保存2595行案例特征、空间网格、进程统计、六个案例的选取规则。原始日志仍在J:/2026B_runs/better_full519_20260911；包内不重复装入全部原日志。MANIFEST.json记录产物哈希及源PLAN哈希。两份脚本保存生成和打包步骤。

已验证每组519行、总计2595行且无重复；动作成本合计等于虚拟时间；测量、无信号、首次发现计数和路径长度在热力网格聚合前后守恒。23份PNG可解码、23页合订PDF及各23份矢量输出齐全。

固定种子集合包括结构化种子与fixture，不能当成独立同分布的官方抽样。因此不添加缺乏采样依据的显著性星号，不将样本逐例胜出写成普遍保证。
'''
(root/'阅读指南.md').write_text(intro,encoding='utf-8')
esc=html.escape
links=' '.join(f'<a href="#f{c["id"]}">{c["id"]}</a>' for c in catalog)
cards=[]
for c in catalog:
    cards.append(f'<section id="f{c["id"]}"><h2>图{c["id"]} {esc(c["title"])}</h2><a href="png/{c["id"]}.png"><img loading="lazy" src="png/{c["id"]}.png"></a>'+''.join(f'<p><b>{label}：</b>{esc(c[k])}</p>' for k,label in [('meaning','研究意义'),('readout','阅读与解释'),('limit','结论边界'),('source','数据来源')])+f'<p><a href="pdf/{c["id"]}.pdf">单图PDF</a> · <a href="svg/{c["id"]}.svg">矢量SVG</a> · <a href="#top">回到目录</a></p></section>')
(root/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>CPU 519种子科学图谱</title><style>body{font:16px/1.7 "Microsoft YaHei",sans-serif;max-width:1400px;margin:32px auto;padding:0 24px;color:#222;background:#f5f6f8}section{background:white;padding:24px;margin:24px 0;border:1px solid #ddd}img{width:100%;height:auto}a{color:#0072bd}nav a{display:inline-block;padding:5px 12px}h1,h2{line-height:1.4}</style><body id="top"><h1>CPU 519种子科学图谱</h1><p>23张复合图 · 2595场已完成本地运行 · MATLAB式科学绘图 · 六个案例的圆域路径与事件时间线</p><p>Q3 B平均节省12.916秒/源但长尾恶化；Q4 C相对A平均节省124.584秒/源，相对B仍有19例退步。所有结论仅针对固定回归集。</p><p><a href="CPU519_完整科学图谱.pdf">完整PDF</a> · <a href="阅读指南.md">阅读指南与审计说明</a> · <a href="图表详解.md">逐图详解</a></p><nav>'+links+'</nav>'+''.join(cards)+'</body></html>',encoding='utf-8')
for name in ('build_cpu_atlas.py','package_cpu_atlas.py'):
    shutil.copy2(Path(__file__).parent/name,root/name)
manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.name!='MANIFEST.json'}
manifest['SOURCE_PLAN_SHA256']=hashlib.sha256(Path('J:/2026B_runs/better_full519_20260911/PLAN.json').read_bytes()).hexdigest()
(root/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
dest=root.with_suffix('.zip')
with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for p in root.rglob('*'):
        if p.is_file():z.write(p,p.relative_to(root.parent))
print('Validated 23 figures, 2595 rows. Archive bytes:',dest.stat().st_size)
