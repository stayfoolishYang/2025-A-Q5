# B题 Q1/Q2 LaTeX 章节交付

本目录仅整理问题一、问题二。正文依据现有代码、题目与附件、已有 JSON/CSV 和审计记录编写，没有修改求解算法，没有重新运行算例或模拟器。

- `q1_model.tex`：问题一正文，可独立 `\input`。
- `q2_model.tex`：问题二正文，可独立 `\input`。
- `main.tex`：两节合并审阅入口。
- `q1_q2_model_v2.pdf`：当前12页正文版，已融入题意对照、横向比较和验证过程。旧 `q1_q2_model.pdf` 为9页历史审阅稿。
- `references.bib`：题目及四篇已核验文献。
- `CODE_PAPER_MAP.md`：公式、结论、实现及结果的对应关系。
- `AUDIT_NOTES.md`：数学、代码、题意、语言四重审计及历史冲突。
- `audit/`：三个独立只读审计笔记、文献核验元数据、源文件指纹及编译记录。
- `figures/`：两幅既有结果图的原样副本，不是本轮新实验。

## 使用提供的竞赛模板

模板来源：`../../downloads/cumcm-latex-template-original-20260911/`。
`cumcm2026.sty` 原样复制，许可证保留为 `TEMPLATE_LICENSE`，原模板目录未修改。主文件保留原模板的字体文件设定，仅将字体路径指向原目录；补充黑体粗体映射、中文等宽字体及段落孤行控制，以消除字体警告和单字跨页。没有复制约28MB字体文件。

`main.tex` 是供本轮审阅的章节包装，不是完整竞赛提交稿，不包含摘要、Q3/Q4、整篇论文的附录或完整AI使用声明。它复用用户给定的版式，不对模板文件中所述竞赛规则重新作官方核验。

合入已有论文时，将 `q1_model.tex`、`q2_model.tex` 和 `figures/` 放到该论文主文件同目录；在模型建立与求解的适当位置加入：

```tex
\input{q1_model}
\input{q2_model}
```

两节内部已含 `\section`，不需要再包一层同名标题。标签使用 `q1`/`q2` 前缀，编号由宿主主文件自动续接。将本目录 `references.bib` 的五条记录合入宿主文献库，保留引用键；主文件只保留一次参考文献输出。图路径为 `figures/...`，需要随同复制。使用原 `cumcm.tex` 时保留其前导设置和其余章节，不要用本审阅包装替换完整论文。

## 本机编译

在 `B_solver/paper` 目录执行（已安装 TeX Live 2023）：

```powershell
New-Item -ItemType Directory -Force build | Out-Null
& 'D:\texlive\2023\bin\windows\xelatex.exe' -interaction=nonstopmode -halt-on-error -output-directory=build main.tex
& 'D:\texlive\2023\bin\windows\bibtex.exe' build/main
& 'D:\texlive\2023\bin\windows\xelatex.exe' -interaction=nonstopmode -halt-on-error -output-directory=build main.tex
& 'D:\texlive\2023\bin\windows\xelatex.exe' -interaction=nonstopmode -halt-on-error -output-directory=build main.tex
Copy-Item -LiteralPath build/main.pdf -Destination q1_q2_model_v2.pdf
```

编译依赖原模板字体目录。若移到其他设备，请同时携带获授权使用的原字体目录，或按当地环境调整 `main.tex` 中的字体设定。中间文件与渲染预览放在被忽略的 `build/`，最终日志保留在 `audit/`。

## 本轮范围与版本

审计基线：分支 `q4-diagnostic-recovery`，HEAD `1cf0b3d`。本轮交付新增于 `B_solver/paper/`，未修改算法和历史结果，未把其他 A题/Q4 工作纳入本目录。收尾时仓库已有并行Q4提交 `9bee5c4`，当前HEAD为该提交；它没有修改本次核对的Q1/Q2源文件。当前工作区为 dirty；本轮论文未另行提交或推送，历史提交不作改写。

正式测试启动次数 = 0。官方接口调用次数 = 0。

本轮只做论文整理、代码核对和本地 LaTeX 编译；已有 CSV 的算术复核不属于新求解或新模拟实验。

## 正文比较版更新

Q1新增约束对应表、方法比较及点估计/集合证书的历史验证；Q2新增100同种子单源策略比较与时间权衡。CSV汇总及配对差值在 `comparison/evidence/`，绘图和纯数据复核脚本在 `comparison/analyze_existing.py`。只重算保存记录的统计值，没有运行求解器。

当前仓库HEAD快照为 `dcb62ac`，仍是同一分支；以上旧审计基线属于其记录时间点。正文比较版PDF单独命名，避免覆盖正在打开的旧PDF。
