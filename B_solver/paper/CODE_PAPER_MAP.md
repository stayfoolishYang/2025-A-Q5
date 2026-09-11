# 代码—论文映射

路径均相对于 `B_solver/`；代码行号按本轮实际文件核对。基线为 `1cf0b3d`，源文件指纹见 `audit/source_manifest.json`。

| 正文位置 / 公式标签 | 对应文件及行号 | 结论与实现边界 |
|---|---|---|
| Q1误差；`eq:q1-wedge`、`eq:q1-halfplane` | `questions.py:11,17–19`；`geometry.py:5,45–49` | Q1默认1°；共享几何默认1.00500001°；先转弧度，叉积对应两个半平面 |
| 纯测向集 `eq:q1-domain` | `questions.py:20–35` | 默认无圆域，四向LP先区分空/无界/有界；非任意有限大框截断 |
| 多边形裁剪 | `geometry.py:12–29` | 浮点Sutherland–Hodgman，inside阈值1e−9，不宣称全流程精确算术 |
| 圆外包 `eq:q1-outer` | `geometry.py:32–42` | 128边初始圆域、64切线接收圆，均是外包近似 |
| 直径 `eq:q1-diameter` | `geometry.py:56–77` | 旋转卡壳；数学顶点充分性在正文给出凸组合证明 |
| 直径圆 `eq:q1-thales` | `experiments/clearance_geometry_audit.py:39–68` | 独立有理数点积检查；最远点对枚举在该文件26–36行 |
| 主入口直径圆标记 | `questions.py:38` | 实际为数值MEC半径≤D/2+1e−6，不等于上述严格判据调用 |
| 反例 `eq:q1-example`、图1 | `results/q1.json`；`results/geometry_checks.json:5–26`；`experiments.py:93–102` | 已有构造正三角形，D≈40、R≈23.094；非官方实测 |
| MEC `eq:q1-mec` | `geometry.py:80–105` | 固定种子42的增量构圆；返回全顶点最大浮点距离+1e−8 |
| 清除证书 `eq:q1-certificate` | `solver.py:18,41–124,182–183`；`geometry.py:266–278` | 默认MEC，19.999门槛及最终提交点复核；是共用执行层，不是Q1离线入口 |
| Jung `eq:q1-jung`、`eq:q1-thresholds` | `experiments/clearance_geometry_audit.py:72–99` | 独立D²与3r²/4r²分类；未接入主流程，正文给出平面证明 |
| Q2首测域 `eq:q2-prior` | `questions.py:43–44`；`geometry.py:32–49` | 固定(0,0)、30°；未扣除5m近距离盘，仍为保守外包 |
| 接收域 `eq:q2-safe` | `geometry.py:550–552`；`questions.py:47` | 逐候选逐顶点≤1000，safe_only=True；未求圆弧边界 |
| 候选 `eq:q2-grid` | `questions.py:45–47` | 961个旋转网格点→213安全点；不是`candidate_views`的至多15点 |
| 位置/误差情景 `eq:q2-sampled` | `geometry.py:544–559` | 顶点+顶点均值，至多9代表；误差三点，本例15预测示向度 |
| 预测后验 | `geometry.py:557–559` | 仅wedge裁剪，无第二距离圆、near或完整历史误差耦合 |
| 通用无信号边界 | `geometry.py:541–553` | 非安全点从旧直径起算；本Q2安全模式已排除 |
| 评分 `eq:q2-objective` | `geometry.py:560–564` | Dsample+λT，T=移动/5+检测5s，λ单位m/s；同频道无换频 |
| 枚举选择 `eq:q2-choice` | `questions.py:53–58` | 对同一records按四个λ重排；finite sampled minimax |
| Q2权重表、候选图 | `results/q2.json`；`results/q2_candidates.csv`；`make_figures.py:45–52` | 213行逐项算术复核；图颜色上限300m；不是本轮新实验 |
| 设备约束和题意 | `source_text/B题.txt:17–25,70–104`；`source_text/附件2.txt:44–68,102–125,304–313` | 半径、固定同点误差、速度、测量/换频、near、光学与clear |

图1来自 `make_figures.py:27–32` 已生成文件；正文直接复用图片，未运行该综合绘图脚本，以免触及其他问题或重生成结果。

## 正文横向比较与验证过程

| 正文标签 | 数据/代码 | 复核范围 |
|---|---|---|
| `tab:q1-rule-correspondence` | 原B题PDF第1–3页、附件1/2设备及计时规则 | 已从用户原件重新提取，见comparison/evidence |
| `tab:q1-method-comparison` | geometry.py、questions.py、几何证明 | 理论性质比较，不伪装成运行时间实测 |
| `tab:q1-stop-comparison` | results/ablations/point_vs_set.csv；ablations.py:33–47 | 300条、79个点估计超距；81个MEC就绪中0超距；非实际clear日志 |
| `tab:q2-historical`、`fig:q2-historical-tradeoff` | results/ablations/second_view.csv；ablations.py:19–37 | 三方法各100例，两次累计时间；与213安全候选例分开 |
| 逐种子胜负及差值 | comparison/evidence/historical_100_paired_deltas.csv | 200组NBV减基线；无重跑求解 |
| 开发过程界限 | comparison/evidence/git_method_history.txt | 18a53e0已含MEC与时间评分，不虚构单调升级历史 |
