# 药材烘干问题完整论文初稿

2026 A题四问的完整文章初稿已完成。阅读文件为[完整论文.pdf](完整论文.pdf)，LaTeX入口为[完整论文-LaTeX/cumcm.tex](完整论文-LaTeX/cumcm.tex)，可编辑正文为[manuscript.tex](manuscript.tex)。使用用户指定的 math-modeling-skill 论文工作流和原有 cumcm 模板完成。

本稿共50页：摘要1页，正文及参考文献24页，附录25页。含11幅图、13张表及12份程序附录。实际XeLaTeX/BibTeX编译通过，未豁免任何编译警告；版式与资源检查见[validation.json](validation.json)。AI参与情况另见[AI工具使用详情.pdf](AI工具使用详情.pdf)。

Q3保持原末值延续边界，达标时间57.1726 h。Q4采用规定半径下的材料坐标、均匀径向形变、独立干固体守恒与有效热学物性；推荐末小时均值平台，主结果51.0913 h，末值和名义平台分别为50.8235 h和51.0899 h。边界情景范围不是置信区间。旧Eulerian模型仅为对照。

文章纳入当前材料模型的收敛与参数敏感性、同物性收缩消融、密度定义审计以及二维端面对照。它是条件明确的工程模型初稿，不代表新增工艺实验验证或最终人工评阅已经完成。

本地用户指定入口 `downloads/cumcm-latex-template-main/cumcm.tex` 与本稿保持一致；原始示例模板保存在 `downloads/cumcm-latex-template-original-20260911/`。共享审阅包在仓库工作目录的 `交付包/2026A_完整论文初稿_审阅包.zip`，包含相应数值代码、输入数据、结果、PDF和LaTeX源码。

## 编译和复现

在 `完整论文-LaTeX/` 执行 `latexmk -xelatex -outdir=build cumcm.tex`。本地完整项目及审阅包保留用户模板的字体；Git仓库不另行分发字体文件。由Git检出后，请将原模板中的 `fonts/` 目录放回该LaTeX目录，代码排版还需要Consolas字体。宏包需求为TeX Live中的ctex、gbt7714、needspace等。

数值代码应在上层 `A_model/` 原有布局运行，详见[../README.md](../README.md)和[../Q4_FREEZE.md](../Q4_FREEZE.md)。论文附录的 `code/` 是展示副本，不能单独作为完整数值运行目录。出图脚本 `prepare_paper_assets.py` 从现有权威结果读取数据；本轮写作没有改变已冻结的Q4数值文件。

