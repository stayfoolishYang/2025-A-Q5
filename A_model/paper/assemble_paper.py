"""Assemble the manuscript in a copy of the user's LaTeX template."""
from pathlib import Path
import shutil
import json
import re

PAPER=Path(__file__).resolve().parent
ROOT=PAPER.parent
LATEX=PAPER/'完整论文-LaTeX'
TEMPLATE=ROOT.parent/'downloads/cumcm-latex-template-main'

preamble=(PAPER/'template-preamble.tex').read_text(encoding='utf-8')
abstract=r'''热风烘干中，药材内部升温与水分迁移存在不同时间尺度，含水率变化又会改变物性；半径收缩后，还需区分计算区域的几何积分和以干固体为分母的真实水质量。本文针对圆柱药材的预热、全程干燥及收缩过程，建立与题目四问对应的径向热质耦合模型，并对后期边界延续、运动描述和端面影响分别检验。

对固定圆柱，以散度形式建立导热与含水率扩散方程，使用PCHIP构造附件观测区间内的空气边界。采用圆柱有限体积离散、隐式Picard迭代和非线性界面求积。对收缩圆柱，以规定半径构造随体归一化坐标，在均匀径向形变和独立干固体守恒假设下推导水分方程，将题目密度与比热容的乘积用于有效体积热容；4 h后推荐使用末一小时观测均值平台。

问题一在1800 s时，中心与表面温度分别为33.5764和36.7861 $^\circ$C，表面干基含水率为1.5104 kg/kg。问题二在3 h时中心温度已为49.8494 $^\circ$C，但最大含水率仍为1.7662 kg/kg。问题三在附录3物性、固定半径和末点延续下，达标时间为57.1726 h；问题四在附录4物性、随体收缩和均值平台下，推荐时长为51.0913 h。问题四末点及名义平台分别得到50.8235和51.0899 h，作为边界情景保留。

同物性、同平台的固定半径对照为129.8561 h，说明不能把问题三与四的差值全部归因于收缩。问题四网格由81增至161节点时，达标时间改变6.56 s；步长由1降至0.5 s时改变1.19 s。单参数试验表明扩散系数影响最强。轴对称端面对照未分辨出配对达标时差，但4 h平均含水率降低约3.11\%，故一维近似的适用性应按预测指标区分。本文结论适用于明确的经验物性、材料运动和空气边界假设。
'''
extra=r'''
% Preserve the supplied template's abstract appearance with standard aliases.
\renewenvironment{abstract}{\begin{cumcmabstract}}{\end{cumcmabstract}}
\newcommand{\keywords}[1]{\cumcmkeywords{#1}}
\setCJKfamilyfont{paperhei}[Path=fonts/,BoldFont=SimHei.ttf]{SimHei.ttf}
\renewcommand{\heiti}{\CJKfamily{paperhei}}
\setCJKmonofont[Path=fonts/,BoldFont=SimHei.ttf]{SimSun.ttc}
\setmonofont{Consolas}
\usepackage{needspace}
\renewcommand{\topfraction}{0.9}
\renewcommand{\bottomfraction}{0.8}
\renewcommand{\textfraction}{0.08}
\renewcommand{\floatpagefraction}{0.8}
\setcounter{topnumber}{3}
\setcounter{totalnumber}{4}
\raggedbottom
\title{基于热质耦合与随体收缩模型的药材烘干预测}
\begin{document}
\maketitle
\begin{abstract}
'''
main=preamble+extra+abstract+r'''
\keywords{圆柱药材；热风烘干；有限体积法；材料坐标；干基含水率}
\end{abstract}
\input{manuscript.tex}
\end{document}
'''
(LATEX/'cumcm.tex').write_text(main,encoding='utf-8')
shutil.copy2(PAPER/'manuscript.tex',LATEX/'manuscript.tex')
bib=(PAPER/'research/verified_foundations.bib').read_text(encoding='utf-8').split('% Optional:')[0]
(LATEX/'references.bib').write_text(bib,encoding='utf-8')
for folder in ['figures','tables']:
    shutil.copytree(PAPER/folder,LATEX/folder,dirs_exist_ok=True)

files=['run.py','physics/material.py','physics/boundary.py','solver/fvm_cpu.py',
       'experiments/q4_release.py','experiments/q4_validation.py',
       'validation/q4_contract.py','validation/endface_benchmark.py','tests/test_solver.py',
       'export/prepare_outputs.py','export/workbooks.mjs','paper/prepare_paper_assets.py']
titles=['主计算入口','经验物性与界面扩散系数','观测插值和边界延续','一维有限体积求解器',
        '问题四边界与几何对照','问题四收敛及参数试验','主结果一致性检查','轴对称端面求解与配对比较',
        '独立数值验证','Excel数值准备','Excel模板导出','论文图与结果表生成']
lines=[r'\lstset{basicstyle=\ttfamily\scriptsize,basewidth=0.5em,lineskip=0pt}']
for p,title in zip(files,titles):
    dst=LATEX/'code'/p
    dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/p,dst)
    language='Python' if p.endswith('.py') else 'Java'
    lines += [r'\Needspace{9\baselineskip}',f'\\subsection{{{title}}}',
              f'文件：\\path{{{p}}}。',
              f'\\lstinputlisting[language={language},caption={{{title}}}]{{code/{p}}}']
(LATEX/'code-listings.tex').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(PAPER/'code_sources.json').write_text(json.dumps(files,indent=2),encoding='utf-8')
(PAPER/'latex_README.md').write_text('''# 药材烘干问题完整论文初稿

本目录是2026 A题文章的LaTeX源码项目，已清除原模板的示例文章与AI填写占位文件。入口为 `cumcm.tex`，正文为 `manuscript.tex`；样式和字体沿用用户提供的模板。

使用 XeLaTeX 和 BibTeX 编译：

```text
latexmk -xelatex -outdir=build cumcm.tex
```

本次已实际编译、检查的PDF位于父目录 `完整论文.pdf`，对应的AI参与说明位于父目录 `AI工具使用详情.pdf`。AI说明由父目录 `create_ai_details.py` 生成，没有第二份待填写的LaTeX模板。正式使用前应依据实际人工修改与核验情况更新该说明。

`figures/` 包含正文11幅矢量图及对应PNG，`tables/` 包含题目6张数值表，`code/` 是附录展示的完整源程序副本。数学结果的权威来源是上层 A_model 的现有数值文件，文章采用Q4材料坐标与末小时均值平台的51.0913 h。

`code/` 只供论文附录展示，不是独立数值运行目录。数值复现请在配套的 `A_model/` 根目录执行 `python run.py`，并保留其 `physics/`、`solver/`、`data/`、`results/` 等布局。该目录需包含 `data/boundary.csv`、`data/radius.csv` 和原始Excel结果模板 `data/templates/`。论文出图脚本位于 `A_model/paper/prepare_paper_assets.py`，字体从同层 `完整论文-LaTeX/fonts/` 读取；不要把单个绘图文件移到不含这些数据与字体的目录运行。审阅包附有对应布局的代码、数据和结果。

中文字体与正文字体在 `fonts/`；代码字体使用Windows自带Consolas。其他平台需要安装相应字体或由使用者选择当地可用的等宽字体。本文使用 ctexart、gbt7714、needspace 等标准TeX宏包。

本稿为完整文章初稿。它不是题目附件以外新增的工艺实验验证，也不声称已完成参赛队的最终人工审阅或赛事提交。
''',encoding='utf-8')
shutil.copy2(PAPER/'latex_README.md',LATEX/'README.md')
print('Assembled manuscript, references, figures, six tables, and 12 complete code files.')
