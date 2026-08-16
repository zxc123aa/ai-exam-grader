"""初中物理与数学知识点树。

第一版按课标章节骨架建，只求覆盖常考章节并保持编码稳定，不追求学术完备。
新增节点只能追加，不要改动已发布的 `code`：错题本快照按名称留存，题目关联按
`code` 匹配，改编码会让历史标注失去对应关系。
"""

import uuid
from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.models import KnowledgePoint, KnowledgePointSource


@dataclass(frozen=True)
class TaxonomyNode:
    code: str
    name: str
    aliases: tuple[str, ...] = ()
    children: tuple["TaxonomyNode", ...] = field(default_factory=tuple)


PHYSICS_JUNIOR: tuple[TaxonomyNode, ...] = (
    TaxonomyNode(
        code="ph.mechanics",
        name="力学",
        children=(
            TaxonomyNode(
                code="ph.mechanics.motion",
                name="机械运动",
                aliases=("速度", "平均速度"),
            ),
            TaxonomyNode(
                code="ph.mechanics.force",
                name="力与相互作用",
                aliases=("重力", "弹力", "摩擦力"),
            ),
            TaxonomyNode(
                code="ph.mechanics.newton",
                name="牛顿定律与平衡",
                aliases=("二力平衡", "惯性"),
            ),
            TaxonomyNode(
                code="ph.mechanics.pressure",
                name="压强",
                aliases=("液体压强", "大气压强"),
            ),
            TaxonomyNode(
                code="ph.mechanics.buoyancy",
                name="浮力",
                aliases=("阿基米德原理", "浮沉条件"),
            ),
            TaxonomyNode(
                code="ph.mechanics.simple_machine",
                name="简单机械",
                aliases=("杠杆", "滑轮", "滑轮组"),
            ),
            TaxonomyNode(
                code="ph.mechanics.work_power",
                name="功和功率",
                aliases=("机械效率", "功的计算"),
            ),
            TaxonomyNode(
                code="ph.mechanics.energy",
                name="机械能",
                aliases=("动能", "重力势能", "弹性势能"),
            ),
        ),
    ),
    TaxonomyNode(
        code="ph.thermal",
        name="热学",
        children=(
            TaxonomyNode(
                code="ph.thermal.temperature",
                name="温度与物态变化",
                aliases=("熔化", "凝固", "汽化", "液化"),
            ),
            TaxonomyNode(
                code="ph.thermal.internal_energy",
                name="内能与热传递",
                aliases=("热量", "比热容"),
            ),
            TaxonomyNode(
                code="ph.thermal.engine",
                name="内能的利用",
                aliases=("热机", "热值", "热机效率"),
            ),
        ),
    ),
    TaxonomyNode(
        code="ph.electricity",
        name="电学",
        children=(
            TaxonomyNode(
                code="ph.electricity.charge",
                name="电流和电路",
                aliases=("串联", "并联", "电路图"),
            ),
            TaxonomyNode(
                code="ph.electricity.voltage_resistance",
                name="电压和电阻",
                aliases=("滑动变阻器",),
            ),
            TaxonomyNode(
                code="ph.electricity.ohm",
                name="欧姆定律",
                aliases=("伏安法", "电阻测量"),
            ),
            TaxonomyNode(
                code="ph.electricity.power",
                name="电功和电功率",
                aliases=("焦耳定律", "电能表"),
            ),
            TaxonomyNode(
                code="ph.electricity.magnetism",
                name="电与磁",
                aliases=("电磁铁", "电动机", "发电机"),
            ),
            TaxonomyNode(
                code="ph.electricity.safety",
                name="生活用电",
                aliases=("家庭电路", "安全用电"),
            ),
        ),
    ),
    TaxonomyNode(
        code="ph.optics",
        name="光学",
        children=(
            TaxonomyNode(
                code="ph.optics.propagation",
                name="光的直线传播",
                aliases=("影子", "小孔成像"),
            ),
            TaxonomyNode(
                code="ph.optics.reflection",
                name="光的反射与平面镜",
                aliases=("反射定律", "平面镜成像"),
            ),
            TaxonomyNode(
                code="ph.optics.refraction",
                name="光的折射与色散",
                aliases=("折射定律",),
            ),
            TaxonomyNode(
                code="ph.optics.lens",
                name="透镜及其应用",
                aliases=("凸透镜成像", "焦距"),
            ),
        ),
    ),
    TaxonomyNode(
        code="ph.sound",
        name="声学",
        children=(
            TaxonomyNode(
                code="ph.sound.production",
                name="声的产生与传播",
                aliases=("声速", "回声"),
            ),
            TaxonomyNode(
                code="ph.sound.character",
                name="声音的特性与噪声",
                aliases=("音调", "响度", "音色"),
            ),
        ),
    ),
    TaxonomyNode(
        code="ph.matter",
        name="物质与测量",
        children=(
            TaxonomyNode(
                code="ph.matter.density", name="质量与密度", aliases=("密度测量",)
            ),
            TaxonomyNode(
                code="ph.matter.measurement",
                name="测量与仪器读数",
                aliases=("刻度尺", "天平", "量筒"),
            ),
        ),
    ),
)


PHYSICS_SENIOR: tuple[TaxonomyNode, ...] = (
    TaxonomyNode(
        code="phs.mechanics",
        name="力学",
        children=(
            TaxonomyNode(
                code="phs.mechanics.linear_motion",
                name="直线运动",
                children=(
                    TaxonomyNode(
                        code="phs.mechanics.linear_motion.kinematics",
                        name="匀变速直线运动规律",
                        aliases=("运动学公式", "v-t图像", "x-t图像"),
                    ),
                    TaxonomyNode(
                        code="phs.mechanics.linear_motion.pursuit",
                        name="追及与相遇问题",
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.mechanics.interaction",
                name="相互作用",
                children=(
                    TaxonomyNode(
                        code="phs.mechanics.interaction.equilibrium",
                        name="受力分析与物体平衡",
                        aliases=("力的合成与分解", "共点力平衡", "受力分析"),
                    ),
                    TaxonomyNode(
                        code="phs.mechanics.interaction.friction",
                        name="摩擦力分析与计算",
                        aliases=("滑动摩擦力", "静摩擦力"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.mechanics.newton",
                name="牛顿运动定律",
                children=(
                    TaxonomyNode(
                        code="phs.mechanics.newton.second_law",
                        name="牛顿第二定律应用",
                        aliases=("瞬时加速度", "连接体", "动力学两类问题"),
                    ),
                    TaxonomyNode(
                        code="phs.mechanics.newton.weight",
                        name="超重与失重",
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.mechanics.curve",
                name="曲线运动",
                children=(
                    TaxonomyNode(
                        code="phs.mechanics.curve.projectile",
                        name="抛体运动",
                        aliases=("平抛运动", "斜抛运动"),
                    ),
                    TaxonomyNode(
                        code="phs.mechanics.curve.circular",
                        name="圆周运动",
                        aliases=("向心力", "向心加速度", "匀速圆周运动"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.mechanics.gravitation",
                name="万有引力与航天",
                children=(
                    TaxonomyNode(
                        code="phs.mechanics.gravitation.celestial",
                        name="万有引力定律与天体运动",
                        aliases=("卫星变轨", "宇宙速度", "同步卫星"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.mechanics.energy",
                name="机械能",
                children=(
                    TaxonomyNode(
                        code="phs.mechanics.energy.work_power",
                        name="功与功率计算",
                        aliases=("恒力做功", "变力做功", "瞬时功率"),
                    ),
                    TaxonomyNode(
                        code="phs.mechanics.energy.kinetic_theorem",
                        name="动能定理",
                        aliases=("动能定理应用",),
                    ),
                    TaxonomyNode(
                        code="phs.mechanics.energy.conservation",
                        name="机械能守恒定律",
                        aliases=("机械能守恒", "功能关系"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.mechanics.momentum",
                name="动量",
                children=(
                    TaxonomyNode(
                        code="phs.mechanics.momentum.theorem",
                        name="动量定理",
                        aliases=("冲量",),
                    ),
                    TaxonomyNode(
                        code="phs.mechanics.momentum.conservation",
                        name="动量守恒定律",
                        aliases=("碰撞", "反冲", "爆炸"),
                    ),
                ),
            ),
        ),
    ),
    TaxonomyNode(
        code="phs.electromagnetism",
        name="电磁学",
        children=(
            TaxonomyNode(
                code="phs.electromagnetism.field",
                name="静电场",
                children=(
                    TaxonomyNode(
                        code="phs.electromagnetism.field.coulomb",
                        name="库仑定律",
                        aliases=("点电荷", "库仑力"),
                    ),
                    TaxonomyNode(
                        code="phs.electromagnetism.field.intensity",
                        name="电场强度与电场线",
                        aliases=("电场强度", "电场线", "场强叠加"),
                    ),
                    TaxonomyNode(
                        code="phs.electromagnetism.field.potential",
                        name="电势能与电势",
                        aliases=("电势差", "等势面", "电场力做功"),
                    ),
                    TaxonomyNode(
                        code="phs.electromagnetism.field.capacitor",
                        name="电容器与电容",
                        aliases=("平行板电容器",),
                    ),
                    TaxonomyNode(
                        code="phs.electromagnetism.field.motion",
                        name="带电粒子在电场中的运动",
                        aliases=("加速电场", "偏转电场"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.electromagnetism.circuit",
                name="恒定电流",
                children=(
                    TaxonomyNode(
                        code="phs.electromagnetism.circuit.ohm",
                        name="欧姆定律与电阻定律",
                        aliases=("电阻定律", "伏安特性曲线"),
                    ),
                    TaxonomyNode(
                        code="phs.electromagnetism.circuit.closed",
                        name="闭合电路欧姆定律",
                        aliases=("路端电压", "电源电动势", "动态电路分析"),
                    ),
                    TaxonomyNode(
                        code="phs.electromagnetism.circuit.experiment",
                        name="电学实验",
                        aliases=("伏安法测电阻", "测电源电动势和内阻", "电表改装"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.electromagnetism.magnetic",
                name="磁场",
                children=(
                    TaxonomyNode(
                        code="phs.electromagnetism.magnetic.ampere",
                        name="磁感应强度与安培力",
                        aliases=("安培力", "左手定则"),
                    ),
                    TaxonomyNode(
                        code="phs.electromagnetism.magnetic.lorentz",
                        name="洛伦兹力与带电粒子圆周运动",
                        aliases=("洛伦兹力", "回旋加速器", "质谱仪"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.electromagnetism.induction",
                name="电磁感应",
                children=(
                    TaxonomyNode(
                        code="phs.electromagnetism.induction.lenz",
                        name="楞次定律",
                        aliases=("感应电流方向", "右手定则"),
                    ),
                    TaxonomyNode(
                        code="phs.electromagnetism.induction.faraday",
                        name="法拉第电磁感应定律",
                        aliases=("感应电动势", "动生电动势", "感生电动势"),
                    ),
                    TaxonomyNode(
                        code="phs.electromagnetism.induction.application",
                        name="电磁感应综合问题",
                        aliases=("电磁感应图像", "导轨模型", "自感"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.electromagnetism.ac",
                name="交变电流",
                children=(
                    TaxonomyNode(
                        code="phs.electromagnetism.ac.description",
                        name="正弦交流电的产生与描述",
                        aliases=("有效值", "最大值", "交流电图像"),
                    ),
                    TaxonomyNode(
                        code="phs.electromagnetism.ac.transformer",
                        name="变压器与电能输送",
                        aliases=("理想变压器", "远距离输电"),
                    ),
                ),
            ),
        ),
    ),
    TaxonomyNode(
        code="phs.thermal",
        name="热学",
        children=(
            TaxonomyNode(
                code="phs.thermal.molecular",
                name="分子动理论",
                children=(
                    TaxonomyNode(
                        code="phs.thermal.molecular.theory",
                        name="分子动理论基本观点",
                        aliases=("扩散", "布朗运动", "分子间作用力", "阿伏伽德罗常数"),
                    ),
                    TaxonomyNode(
                        code="phs.thermal.molecular.internal_energy",
                        name="温度与内能",
                        aliases=("分子平均动能", "分子势能", "内能变化"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.thermal.gas",
                name="气体",
                children=(
                    TaxonomyNode(
                        code="phs.thermal.gas.laws",
                        name="气体实验定律",
                        aliases=(
                            "玻意耳定律",
                            "查理定律",
                            "盖-吕萨克定律",
                            "等温变化",
                            "等压变化",
                            "等容变化",
                        ),
                    ),
                    TaxonomyNode(
                        code="phs.thermal.gas.state_equation",
                        name="理想气体状态方程",
                        aliases=("理想气体", "状态方程"),
                    ),
                    TaxonomyNode(
                        code="phs.thermal.gas.microscopic",
                        name="气体压强的微观解释",
                        aliases=("分子热运动", "统计规律"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.thermal.solid_liquid",
                name="固体与液体",
                children=(
                    TaxonomyNode(
                        code="phs.thermal.solid_liquid.properties",
                        name="固体与液体性质",
                        aliases=("晶体", "非晶体", "表面张力", "浸润"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.thermal.thermodynamics",
                name="热力学定律",
                children=(
                    TaxonomyNode(
                        code="phs.thermal.thermodynamics.first_law",
                        name="热力学第一定律",
                        aliases=("做功与热传递", "能量守恒"),
                    ),
                    TaxonomyNode(
                        code="phs.thermal.thermodynamics.second_law",
                        name="热力学第二定律",
                        aliases=("热机效率", "熵"),
                    ),
                ),
            ),
        ),
    ),
    TaxonomyNode(
        code="phs.oscillation",
        name="振动与波",
        children=(
            TaxonomyNode(
                code="phs.oscillation.vibration",
                name="机械振动",
                children=(
                    TaxonomyNode(
                        code="phs.oscillation.vibration.shm",
                        name="简谐运动",
                        aliases=("弹簧振子", "单摆", "回复力"),
                    ),
                    TaxonomyNode(
                        code="phs.oscillation.vibration.resonance",
                        name="受迫振动与共振",
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.oscillation.wave",
                name="机械波",
                children=(
                    TaxonomyNode(
                        code="phs.oscillation.wave.propagation",
                        name="波的传播与图像",
                        aliases=("波长", "波速", "波动图像"),
                    ),
                    TaxonomyNode(
                        code="phs.oscillation.wave.phenomena",
                        name="波的干涉衍射与多普勒效应",
                        aliases=("干涉", "衍射", "多普勒效应"),
                    ),
                ),
            ),
        ),
    ),
    TaxonomyNode(
        code="phs.optics",
        name="光学",
        children=(
            TaxonomyNode(
                code="phs.optics.geometric",
                name="几何光学",
                children=(
                    TaxonomyNode(
                        code="phs.optics.geometric.refraction",
                        name="光的折射与全反射",
                        aliases=("折射率", "全反射", "光导纤维"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.optics.physical",
                name="物理光学",
                children=(
                    TaxonomyNode(
                        code="phs.optics.physical.interference",
                        name="光的干涉衍射与偏振",
                        aliases=("双缝干涉", "薄膜干涉", "衍射"),
                    ),
                    TaxonomyNode(
                        code="phs.optics.physical.photoelectric",
                        name="光电效应",
                        aliases=("光子说", "逸出功", "遏止电压"),
                    ),
                ),
            ),
        ),
    ),
    TaxonomyNode(
        code="phs.atomic",
        name="原子与原子核",
        children=(
            TaxonomyNode(
                code="phs.atomic.structure",
                name="原子结构",
                children=(
                    TaxonomyNode(
                        code="phs.atomic.structure.bohr",
                        name="玻尔模型与能级跃迁",
                        aliases=("氢原子光谱", "能级"),
                    ),
                ),
            ),
            TaxonomyNode(
                code="phs.atomic.nucleus",
                name="原子核",
                children=(
                    TaxonomyNode(
                        code="phs.atomic.nucleus.reaction",
                        name="核反应方程与衰变",
                        aliases=("α衰变", "β衰变", "半衰期"),
                    ),
                    TaxonomyNode(
                        code="phs.atomic.nucleus.energy",
                        name="核能与质能方程",
                        aliases=("质能方程", "核裂变", "核聚变"),
                    ),
                ),
            ),
        ),
    ),
)


MATH_JUNIOR: tuple[TaxonomyNode, ...] = (
    TaxonomyNode(
        code="ma.number_algebra",
        name="数与代数",
        children=(
            TaxonomyNode(
                code="ma.number_algebra.rational",
                name="有理数与实数",
                aliases=("绝对值", "数轴", "二次根式"),
            ),
            TaxonomyNode(
                code="ma.number_algebra.expression",
                name="整式与分式",
                aliases=("因式分解", "乘法公式"),
            ),
            TaxonomyNode(
                code="ma.number_algebra.linear_equation",
                name="一元一次方程与二元一次方程组",
                aliases=("方程组",),
            ),
            TaxonomyNode(
                code="ma.number_algebra.quadratic_equation",
                name="一元二次方程",
                aliases=("配方法", "求根公式", "判别式"),
            ),
            TaxonomyNode(
                code="ma.number_algebra.inequality",
                name="不等式与不等式组",
                aliases=("解集",),
            ),
            TaxonomyNode(
                code="ma.number_algebra.linear_function",
                name="一次函数与反比例函数",
                aliases=("正比例函数", "图象与性质"),
            ),
            TaxonomyNode(
                code="ma.number_algebra.quadratic_function",
                name="二次函数",
                aliases=("抛物线", "顶点式", "最值"),
            ),
        ),
    ),
    TaxonomyNode(
        code="ma.geometry",
        name="图形与几何",
        children=(
            TaxonomyNode(
                code="ma.geometry.line_angle",
                name="相交线与平行线",
                aliases=("同位角", "内错角"),
            ),
            TaxonomyNode(
                code="ma.geometry.triangle",
                name="三角形",
                aliases=("全等三角形", "等腰三角形", "内角和"),
            ),
            TaxonomyNode(
                code="ma.geometry.right_triangle",
                name="直角三角形与勾股定理",
                aliases=("锐角三角函数", "解直角三角形"),
            ),
            TaxonomyNode(
                code="ma.geometry.quadrilateral",
                name="四边形",
                aliases=("平行四边形", "矩形", "菱形", "正方形", "梯形"),
            ),
            TaxonomyNode(
                code="ma.geometry.similarity",
                name="相似与位似",
                aliases=("相似三角形", "比例线段"),
            ),
            TaxonomyNode(
                code="ma.geometry.circle",
                name="圆",
                aliases=("圆周角", "切线", "弧长", "扇形面积"),
            ),
            TaxonomyNode(
                code="ma.geometry.transformation",
                name="图形变换",
                aliases=("平移", "旋转", "轴对称", "中心对称"),
            ),
            TaxonomyNode(
                code="ma.geometry.solid",
                name="视图与投影",
                aliases=("三视图", "展开图"),
            ),
        ),
    ),
    TaxonomyNode(
        code="ma.statistics",
        name="统计与概率",
        children=(
            TaxonomyNode(
                code="ma.statistics.data",
                name="数据的收集与描述",
                aliases=("扇形统计图", "频数分布"),
            ),
            TaxonomyNode(
                code="ma.statistics.analysis",
                name="数据的分析",
                aliases=("平均数", "中位数", "众数", "方差"),
            ),
            TaxonomyNode(
                code="ma.statistics.probability",
                name="概率初步",
                aliases=("树状图", "列表法"),
            ),
        ),
    ),
    TaxonomyNode(
        code="ma.coordinate",
        name="平面直角坐标系",
        children=(
            TaxonomyNode(
                code="ma.coordinate.basic",
                name="坐标与图形位置",
                aliases=("象限", "对称点"),
            ),
        ),
    ),
)


TAXONOMY: dict[str, tuple[TaxonomyNode, ...]] = {
    "物理": PHYSICS_JUNIOR,
    "数学": MATH_JUNIOR,
    "高中物理": PHYSICS_SENIOR,
}

GRADE_BAND = "junior"

SUBJECT_GRADE_BANDS: dict[str, str] = {
    "物理": "junior",
    "数学": "junior",
    "高中物理": "senior",
}


def _upsert_node(
    session: Session,
    *,
    subject: str,
    node: TaxonomyNode,
    parent_id: uuid.UUID | None,
    order: int,
    existing: dict[str, KnowledgePoint],
    grade_band: str = GRADE_BAND,
) -> int:
    created = 0
    point = existing.get(node.code)
    if point is None:
        point = KnowledgePoint(
            subject=subject,
            grade_band=grade_band,
            code=node.code,
            name=node.name,
            parent_id=parent_id,
            aliases=list(node.aliases),
            source=KnowledgePointSource.CURRICULUM,
            sort_order=order,
        )
        created += 1
    else:
        point.name = node.name
        point.parent_id = parent_id
        point.aliases = list(node.aliases)
        point.sort_order = order
    session.add(point)
    session.flush()
    existing[node.code] = point
    for child_order, child in enumerate(node.children):
        created += _upsert_node(
            session,
            subject=subject,
            node=child,
            parent_id=point.id,
            order=child_order,
            existing=existing,
            grade_band=grade_band,
        )
    return created


def sync_knowledge_points(session: Session) -> int:
    """按 (subject, code) 幂等写入知识点树，返回新增节点数。

    已存在的节点只更新名称、别名和排序，不改 `code`，也不删除任何节点：
    历史题目关联和错题本快照都依赖节点稳定存在。
    """
    created = 0
    for subject, roots in TAXONOMY.items():
        grade_band = SUBJECT_GRADE_BANDS.get(subject, GRADE_BAND)
        existing = {
            point.code: point
            for point in session.exec(
                select(KnowledgePoint).where(KnowledgePoint.subject == subject)
            ).all()
        }
        for root_order, root in enumerate(roots):
            created += _upsert_node(
                session,
                subject=subject,
                node=root,
                parent_id=None,
                order=root_order,
                existing=existing,
                grade_band=grade_band,
            )
    session.commit()
    return created
