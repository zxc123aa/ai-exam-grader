# Physics OCR Evaluation Report

## Scan Preprocessing

- 1.jpg current preprocessing output: single_page, captures only left page; right page requires fallback/manual crop.
- 2.jpg current preprocessing output: detected_gutter, splits into left/right pages.

## OCR Result Summary

| Sample | Kind | Engine | Status | Confidence / Usage | Time | Preview |
|---|---|---|---|---|---:|---|
| p1_left_auto | page | paddleocr-gpu-cu130 | succeeded | 0.933 | 0.49s | 运载火箭 2024年 A.动能增 2024-2025年度第二学期 8.用下列 得分： m 满分：100分 考试时间：60分钟 ) 线 B.鲜花香气四溢是一种扩散现象 G 电型 D.水和酒精混合后总体积减少表明分子间有引力 C.铁块很难被压缩表明分子间没有间隙 9. 如图,甲 轮的摩擦 7N A.甲做的 3N 0 3N 10.在水平 0 0 D 两个草莓 SN A B C 时，甲、乙 名 A.甲容器 A. 马路上行驶的汽车有惯性，静止的汽... |
| p1_right_auto | page | paddleocr-gpu-cu130 | succeeded | 0.969 | 0.36s | A.动能增大，势能减小 7 C.动能不变，势能增大 D动能增大，势能增大 ) 0 A 轮的摩擦。下列说法正确的是( B c A.甲做的有用功多 B.乙做的总功多 D 第9题 C.甲做总功的功率大 D.乙所用装置的机械效率小 A.甲容器中草莓受到的浮力更大 C.乙容器中盐水对容器底部的压强更大 B.两容器中盐水的密度相等 二、填空题（本大题有7小题，每空2分，共28分） D.甲容器对桌面的压强更大 甲第10题乙 压强存在的著名实验是 物理... |
| p2_left_auto | page | paddleocr-gpu-cu130 | succeeded | 0.970 | 0.37s | 18. 根据要求规范作图。 （1）在图甲中画出潜水艇静止在水中时受力的示意图。。 (2) 在图乙中画出使用羊角锤拔钉子时动力F的力臂L。 0 甲 乙 图所示的甲、乙、丙探究实验：将三个小球A、B、C先后从同一斜面的不同高度h、h8、hc三个位 置滚下（mx=mg<mc.h=h>hg），推动小木块运动一段距离后静止，请你根据生活经验和所学的物理 探究方法，对以下问题进行判断。 h hc 甲 乙 丙 (1）实验中通过观察木块被小球撞击后在水... |
| p2_right_auto | page | paddleocr-gpu-cu130 | succeeded | 0.953 | 0.24s | 21. 如图所示，小磊骑自行车上学的途中，沿直线匀速经过一段长100m 的平直路面，用时25s。该过程中前后轮与地面的总接触面积为20cm²。 若小磊的质量为50kg，自行车重为150N，骑行时受到的阻力为总重的 0.03倍(ρ=1.0×103kg/m³，g=10N/Kg)，求: (1)小磊所受的重力大小？ (2) 该段骑行过程中，车对水平地面的压强是多少？ (3）求骑行过程中动力做功的功率是多大？ 22. 为减少溺水事故的发生，大学生... |
| p1_header | region | paddleocr-gpu-cu130 | succeeded | 0.994 | 0.06s | 2024-2025年度第二 得分： 满分：100分 考试时间：60分钟 气四溢是一种扩散现象 少表明分子间有引力 |
| p1_q1_q2 | region | paddleocr-gpu-cu130 | succeeded | 0.894 | 0.12s | 1.下列现象用分子动理论的观点解释，其中正确的是( 台型 D.水和酒精混合后总体积减少表明 C.铁块很难被压缩表明分子间没有间隙 9 车 7N 3N 5N A 3N 0 4N 1 0 SN D 医 A B C 8时 |
| p1_q3_q4_diagrams | region | paddleocr-gpu-cu130 | succeeded | 0.804 | 0.11s | 3N 0 0 SN D A B C A. 马路上行驶的汽车有惯性，静止的汽车不具有惯性 C. 超载运行的大货车不容易停下来是因为其质量大惯性大 获得升力的原理相同的是( 证 吹气 |
| p1_q5_q6_figures | region | paddleocr-gpu-cu130 | succeeded | 0.952 | 0.15s | 甲 乙 丙 丁 A. 甲图：往纸片中间吹气，纸片会靠拢 B. 乙图：用吸管吸牛奶，牛奶盒发生形变 C. 丙图：轮船通过三峡船闸 D.丁图：覆杯实验中松手后硬纸片不会掉下 5.以下是公交车上与压强有关的设计，其中为了增大压强的是( 房 密 A.宽大的轮子 B.凹型的座位 C.宽厚的拉环 D. 锥形逃生锤 6. 如图所示的情景中，人对物体做功的是( A.人推一块大石头没推动 B.人捡起地面上的石块 C.人举着哑铃不动 D.人抱着箱子在水平地... |
| p2_q7_q10 | region | paddleocr-gpu-cu130 | succeeded | 0.918 | 0.13s | A.动能增大，势能减小 7 C.动能不变，势能增大 D动能增大，势能增大 A 纶的摩擦。下列说法正确的是( B c A.甲做的有用功多 B.乙做的总功多 D 第9题 C.甲做总功的功率大 D.乙所用装置的机械效率小 甲容器中草莓受到的浮力更大 C.乙容器中盐水对容器底部的压强更大 B.两容器中盐水的密度相等 二、填空题（本大题有7小题，每空2分，共28分） D.甲容器对桌面的压强更大 甲第10题乙 1. 在体育测试中，铅球出手后仍能向前 |
| p2_q11_q16 | region | paddleocr-gpu-cu130 | succeeded | 0.976 | 0.24s | 题有7小题，每空2分，共28分） 甲第10题乙 压强存在的著名实验是 ：物理学史上。证明大气 实验。 速度变大，导致屋顶上表面受到的压强 料时，饮料是在 (选填“增大”或“减小”)的缘故：我们用吸管“吸” 作用下被“吸”入口中的。 其两端靠在墙面的不同地方，在水面处做出标记就找到了 这是利用了 的原理。 高度（选填“相同”或“不同”）， 是有水的透明胶管 第13题 第14题 第15题 4.如图所示，钓鱼竿可以看作一个 (选填“省力“费力... |
| p3_q18 | region | paddleocr-gpu-cu130 | succeeded | 0.959 | 0.09s | 18. 根据要求规范作图。 （1）在图甲中画出潜水艇静止在水中时受力的示意图。。 (2) 在图乙中画出使用羊角锤拔钉子时动力F的力臂L。 0 甲 19. 为了模拟研究汽车超载和超速带来的安全隐患，海口市某初中物理兴趣小组的小俊同学设计了如 乙 |
| p3_q19 | region | paddleocr-gpu-cu130 | succeeded | 0.926 | 0.27s | 兴趣小组的小俊同学设计了如 置滚下（mx=mg<mc.h=h>hg），推动小木块运动一段距离后静止，请你根据生活经验和所学的物理 探究方法，对以下问题进行判断。 4 h hc 甲 乙 丙 (1）实验中通过观察木块被小球撞击后在水平面上运动距离的长短来判断安全隐患大小，该处采用的 研究方法是 (2)让质量相同的小球从斜面的不同高度由静止滚下，可以用来探究小球的动能大小与 1 的关系。 (3) 通过 两次实验可以研究超载对安全隐患的影响（选... |
| p3_q20 | region | paddleocr-gpu-cu130 | succeeded | 0.987 | 0.11s | 甲 乙 丙 （1）实验前，杠杆静止在图甲所示的位置，为了便于测量力臂，应使杠杆在水平位置平衡。为此，应 将平衡螺母向 （选填“左”或“右”）调节； （2）将杠杆调成水平位置平衡后，如图乙所示，在A点挂3个钩码，则应在B点挂 个钩 码，才能使杠杆在水平位置保持平衡：随后两边各取下一个钩码，杠杆 (选填“左”或“右”) 八年级物理第3页（共4页） |
| p4_q21 | region | paddleocr-gpu-cu130 | succeeded | 0.938 | 0.06s | 0.03倍(ρg=1.0×103kg/m³，g=10N/Kg)，求： (1）小磊所受的重力大小？ (2) 该段骑行过程中，车对水平地面的压强是多少？ (3）求骑行过程中动力做功的功率是多大？ |
| p4_q22 | region | paddleocr-gpu-cu130 | succeeded | 0.984 | 0.17s | 22.为减少溺水事故的发生， 戴上该手环下潜到湖面下2m处(未接触湖底)，打开手环开关，手环瞬间弹出一个体积为3.5×10²m²的 气囊，如图乙所示，随后气囊迅速将小铭带出水面。已知小铭的质量为63kg，人体密度约为 1.05×103kg/m3，不计手环的质量和体积。求： (1)手环在湖面下2m深时，受到水的压强是多少？ (2)小铭下潜到湖面下2m深处，人体受到的浮力有多大？ (3)气囊完全打开瞬间小铭受到的合力大小？ (4)测试中发现... |

## Findings

- `materials/physics/1.jpg` exposes a scan preprocessing failure: the current contour detector captures only the left page and misses the right page.
- `materials/physics/2.jpg` is split into two usable pages, but the right page remains low contrast and shadowed.
- PaddleOCR should be treated as the fast baseline for printed text; Kimi should be treated as the slower fallback for layout restoration and difficult physics regions.

## Sample Files

- `p1_left_auto`: `materials/physics/evaluation/pages/p1_left_auto.jpg` (current scan preprocessing output; expected page 1)
- `p1_right_auto`: `materials/physics/evaluation/pages/p1_right_auto.jpg` (current scan preprocessing output; expected page 2)
- `p2_left_auto`: `materials/physics/evaluation/pages/p2_left_auto.jpg` (current scan preprocessing output)
- `p2_right_auto`: `materials/physics/evaluation/pages/p2_right_auto.jpg` (current scan preprocessing output)
- `p1_header`: `materials/physics/evaluation/crops/p1_header.jpg` (title/header)
- `p1_q1_q2`: `materials/physics/evaluation/crops/p1_q1_q2.jpg` (choice questions 1-2)
- `p1_q3_q4_diagrams`: `materials/physics/evaluation/crops/p1_q3_q4_diagrams.jpg` (force diagrams and choice text)
- `p1_q5_q6_figures`: `materials/physics/evaluation/crops/p1_q5_q6_figures.jpg` (photo/cartoon figure options)
- `p2_q7_q10`: `materials/physics/evaluation/crops/p2_q7_q10.jpg` (right-page choice questions with diagrams)
- `p2_q11_q16`: `materials/physics/evaluation/crops/p2_q11_q16.jpg` (fill-in-the-blank questions)
- `p3_q18`: `materials/physics/evaluation/crops/p3_q18.jpg` (drawing question)
- `p3_q19`: `materials/physics/evaluation/crops/p3_q19.jpg` (experiment question with diagrams)
- `p3_q20`: `materials/physics/evaluation/crops/p3_q20.jpg` (lever experiment question)
- `p4_q21`: `materials/physics/evaluation/crops/p4_q21.jpg` (calculation question)
- `p4_q22`: `materials/physics/evaluation/crops/p4_q22.jpg` (application question)
