# 药材烘干问题完整论文初稿

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
