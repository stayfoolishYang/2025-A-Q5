"""Write a factual AI-use record for the manuscript draft."""
from pathlib import Path
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

P=Path(__file__).resolve().parent
pdfmetrics.registerFont(TTFont('CJK',str(P/'完整论文-LaTeX/fonts/SimHei.ttf')))
styles=getSampleStyleSheet()
styles.add(ParagraphStyle('TitleCN',fontName='CJK',fontSize=19,leading=27,alignment=TA_CENTER,spaceAfter=20))
styles.add(ParagraphStyle('H',fontName='CJK',fontSize=13,leading=19,spaceBefore=14,spaceAfter=7))
styles.add(ParagraphStyle('CN',fontName='CJK',fontSize=10.5,leading=17,spaceAfter=7,wordWrap='CJK'))
story=[Paragraph('AI工具使用详情',styles['TitleCN'])]
sections=[
('1. 文件范围与工具信息',[
 '本说明对应《基于热质耦合与随体收缩模型的药材烘干预测》初稿，记录截至2026年9月11日的已知AI参与情况。它不代表论文已由参赛队逐项完成最终人工核验，也不代表已提交。',
 '本次写作使用OpenAI Codex（当前运行基于GPT-6），并采用用户指定的 math-modeling-skill 工作流程。前序模型讨论、代码修改及材料审查也由Codex辅助；用户另提供过一份GPT审阅意见，其具体产品版本和型号未在可见材料中完整记录，故不作推测。数值计算由Python程序实际执行，AI没有替代计算程序生成数值。']),
('2. 具体用途与环节',[
 '模型与公式：讨论固定圆柱热质传递方程、含水率的干基定义、移动边界的材料速度与网格速度、独立干固体密度及有效热物性的区别；整理Robin边界与4小时后的平台延续假设。',
 '数值与代码：协助编写和调试圆柱有限体积、隐式Picard迭代、Thomas求解、非线性界面求积、事件定位、Excel输出、参数扫描及轴对称端面对照程序。',
 '结果与资料：协助读取题目附件，核对表格与全精度数值轨迹，执行已有测试和补充比较，查找并核验方法文献的题名、作者、年份和DOI。',
 '论文：基于现有完整计算结果生成中文初稿、公式、结果解释和局限说明；从数据重新生成图表，填充用户给定LaTeX模板并编译、检查版面。']),
('3. 主要提示方式与迭代过程',[
 '用户首先要求严格基于题目与附件完成药材烘干建模和数值求解，强调物理正确性与实际计算。随后要求核对4小时后的温湿边界、审查ALE变量及干基含水率守恒、解释固定半径与移动域时长差异，并进行同物性的严格消融。',
 '在审阅反馈后，用户明确要求将Q4主模型由Eulerian结果切换为材料坐标版本，采用末一小时均值平台，同时保留其他边界情景，并统一重新生成结果表、主图和消融表。本次要求是在指定的cumcm.tex模板中形成完整文章。',
 '因此，稿件采用材料坐标与均值平台下约51.09小时作为Q4主值；末点平台约50.82小时作为情景；旧Eulerian主值未用于主结论。文中说明这些数值对应的物性、边界和运动假设。']),
('4. 采纳与核验的已知情况',[
 '采纳的主要内容包括独立干固体密度、材料坐标推导、末小时均值平台和同物性消融方案。模型修订已落实到计算程序、数值文件及正文，敏感性和收敛比较使用当前Q4材料模型。',
 '现有自动化证据包括原始附件读取、六张题目表与NPZ逐数核对、线性求解器对照、Robin解析模态、非线性界面求积、材料水分预算、网格和时间步比较、二维端面对照，以及实际LaTeX编译和PDF渲染检查。这些是计算或工具验证，不应写成已经完成的人工逐项审查。',
 '用户提供的外部审阅文本自述进行了独立测试与收敛实验。该意见已用于发现物理定义与主结果不一致的风险；本说明不据此推断审阅者身份，也不把其自述等同于参赛队已经完成全部人工复核。',
 '可见上下文没有完整记录参赛队成员对本次全文逐段改写、对所有模型假设逐项确认的过程。因此人工修改与最终核验目前不能声称全部完成。后续若实际发生人工修改和核验，应依据事实更新本说明，保持论文声明与最终材料一致。']),
('5. 关键保留意见',[
 '51.09小时是规定半径、均匀随体径向形变、独立干固体守恒、经验有效热物性和末小时均值边界下的条件结果；4小时后的工艺边界、空气到材料的平衡含水映射和潜热等资料仍不足。',
 '本文没有完成药材真实工艺的外部实验验证，也没有执行8卡随机不确定性计算；不能把数值预算达到机器精度解释为物理预测精度。上述限制与正文保持一致。'])]
for title,paras in sections:
    story.append(Paragraph(title,styles['H']))
    story += [Paragraph(t,styles['CN']) for t in paras]
def footer(c,d):
    c.setFont('CJK',9);c.drawCentredString(A4[0]/2,35,str(d.page))
pdf=P/'AI工具使用详情.pdf'
doc=SimpleDocTemplate(str(pdf),pagesize=A4,leftMargin=71,rightMargin=71,topMargin=63,bottomMargin=58,title='AI工具使用详情',author='')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(pdf)
