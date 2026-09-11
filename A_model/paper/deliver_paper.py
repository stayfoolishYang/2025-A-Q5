"""Copy the reviewed paper to the user's template path and make a review archive."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

PAPER = Path(__file__).resolve().parent
MODEL = PAPER.parent
ROOT = MODEL.parent
PROJECT = PAPER / '完整论文-LaTeX'
TARGET = ROOT / 'downloads/cumcm-latex-template-main'
OUTPUT = ROOT / '交付包/2026A_完整论文初稿_审阅包.zip'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sync_target():
    # The original directory has already been moved to a checked backup path.
    if TARGET.exists():
        raise FileExistsError(f'Refusing to overwrite existing delivery: {TARGET}')
    shutil.copytree(PROJECT, TARGET, ignore=shutil.ignore_patterns('build', 'latex-project.json'))
    shutil.copy2(PAPER / '完整论文.pdf', TARGET / 'cumcm.pdf')
    shutil.copy2(PAPER / 'AI工具使用详情.pdf', TARGET / 'AI工具使用详情.pdf')
    text = (PAPER / 'latex_README.md').read_text(encoding='utf-8')
    text = text.replace('父目录 `完整论文.pdf`', '本目录 `cumcm.pdf`')
    text = text.replace('父目录 `AI工具使用详情.pdf`', '本目录 `AI工具使用详情.pdf`')
    text = text.replace('父目录 `create_ai_details.py`', '仓库 `A_model/paper/create_ai_details.py`')
    text = text.replace('上层 A_model', '仓库 A_model')
    (TARGET / 'README.md').write_text(text, encoding='utf-8')
    checked = []
    for path in PROJECT.rglob('*'):
        rel = path.relative_to(PROJECT)
        if not path.is_file() or 'build' in rel.parts or rel.as_posix() in {'README.md', 'latex-project.json'}:
            continue
        assert sha(path) == sha(TARGET / rel), rel
        checked.append(rel.as_posix())
    assert sha(PAPER / '完整论文.pdf') == sha(TARGET / 'cumcm.pdf')
    return checked


def package_review():
    files = {}

    def add(path):
        if not path.is_file():
            raise FileNotFoundError(path)
        files[path.relative_to(ROOT).as_posix()] = path

    code = json.loads((PAPER / 'code_sources.json').read_text(encoding='utf-8'))
    for rel in code:
        add(MODEL / rel)
    for rel in ['requirements.txt', 'README.md', 'STATUS.md', 'Q4_FREEZE.md',
                'validation/verify_exports.py']:
        path = MODEL / rel
        if path.exists():
            add(path)
    for path in (MODEL / 'data').rglob('*'):
        if path.is_file() and path.suffix in {'.csv', '.xlsx', '.pdf', '.json'}:
            add(path)
    results = MODEL / 'results'
    names = [f'q{q}.{ext}' for q in range(1, 5) for ext in ['json', 'npz']]
    names += [f'result{q}.xlsx' for q in range(1, 5)]
    names += [f'table{q}.csv' for q in range(1, 7)]
    names += ['q4_ablation.csv', 'q4_convergence.csv', 'q4_sensitivity.csv',
              'q4_release_experiments.json', 'q4_validation.json',
              'q4_validation_provenance.json', 'q4_freeze_manifest.json',
              'tests.json', 'quadrature_validation.json', 'export_validation.json',
              '求解报告.md']
    names += [p.name for p in results.glob('endface*') if p.suffix in {'.json', '.csv', '.npz'}]
    for name in names:
        add(results / name)
    for sub in ['q4_scenarios', 'q4_validation_states']:
        for path in (results / sub).glob('*'):
            if path.is_file() and path.suffix in {'.json', '.npz'}:
                add(path)
    excluded = {'build', 'checkpoints', 'rendered', 'template_artifacts', 'package_check', '__pycache__'}
    for path in PAPER.rglob('*'):
        rel = path.relative_to(PAPER)
        if path.is_file() and not set(rel.parts) & excluded and not path.name.endswith(('.raw.txt', '.stderr.txt')):
            if path.name not in {'delivery_manifest.json'}:
                add(path)
    instructions = '''# 2026 A题完整论文初稿审阅包

先阅读 A_model/paper/完整论文.pdf（50页，其中摘要1页、正文及参考文献24页、附录25页）。
AI工具使用详情.pdf为当前可核实的AI参与记录。本文只讨论药材烘干A题。

Q4主模型：材料坐标、规定半径、均匀径向形变、干固体守恒、有效热学物性、末小时均值平台。
Q4主结果51.0912847222 h，Q3保留末值平台57.1725868056 h。边界情景不是置信区间。
本包用于审阅完整初稿；没有宣称实验验证、8卡UQ或参赛队最终人工验收已完成。

源码入口：A_model/paper/完整论文-LaTeX/cumcm.tex。
在该目录执行 latexmk -xelatex -outdir=build cumcm.tex；需要XeLaTeX、BibTeX、标准TeX宏包和Consolas。
已随包保留用户模板fonts。图为矢量PDF，正文数值表来自现有CSV，附录代码与实际源程序逐文件一致。

数值复现请保持A_model原布局：安装requirements.txt中的Python库，然后执行python A_model/run.py。
情景/消融：python A_model/experiments/q4_release.py；当前收敛/敏感性：python A_model/experiments/q4_validation.py。
二维端面对照使用 validation/endface_benchmark.py，其参数说明见源文件及Q4_FREEZE.md。
出图：python A_model/paper/prepare_paper_assets.py。所有引用的已有结果均已随包保存，可直接核查。
Excel已有成品；重新导出需先运行export/prepare_outputs.py，再运行export/workbooks.mjs，后者依赖Node及@oai/artifact-tool。

评阅建议：重点核对材料坐标与热学有效参数的物理解释、Ceq经验映射、4h后边界依据、二维端面结论的适用范围；不要把条件模型的数值收敛误当成真实工艺验证。
SHA256SUMS.json列出每份随包文件的哈希值。validation.json对应已实际编译的PDF。
'''
    OUTPUT.parent.mkdir(exist_ok=True)
    hashes = {name: sha(path) for name, path in sorted(files.items())}
    with zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr('先读我.md', instructions)
        z.writestr('SHA256SUMS.json', json.dumps(hashes, ensure_ascii=False, indent=2))
        for name, path in sorted(files.items()):
            z.write(path, name)
    with zipfile.ZipFile(OUTPUT) as z:
        assert z.testzip() is None
        for name, expected in hashes.items():
            assert hashlib.sha256(z.read(name)).hexdigest() == expected, name
        q4 = json.loads(z.read('A_model/results/q4.json'))
        assert q4['ale'] is False and abs(q4['event_h'] - 51.0912847222) < 1e-7
    return {'path': str(OUTPUT), 'sha256': sha(OUTPUT), 'bytes': OUTPUT.stat().st_size,
            'file_count': len(files) + 2, 'all_file_hashes_verified': True}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--package-only', action='store_true')
    args = parser.parse_args()
    synced = [] if args.package_only else sync_target()
    result = {'target': str(TARGET), 'synced_source_assets': len(synced),
              'pdf_sha256': sha(PAPER / '完整论文.pdf'), 'archive': package_review()}
    (PAPER / 'delivery_manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
