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
}

GRADE_BAND = "junior"


def _upsert_node(
    session: Session,
    *,
    subject: str,
    node: TaxonomyNode,
    parent_id: uuid.UUID | None,
    order: int,
    existing: dict[str, KnowledgePoint],
) -> int:
    created = 0
    point = existing.get(node.code)
    if point is None:
        point = KnowledgePoint(
            subject=subject,
            grade_band=GRADE_BAND,
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
        )
    return created


def sync_knowledge_points(session: Session) -> int:
    """按 (subject, code) 幂等写入知识点树，返回新增节点数。

    已存在的节点只更新名称、别名和排序，不改 `code`，也不删除任何节点：
    历史题目关联和错题本快照都依赖节点稳定存在。
    """
    created = 0
    for subject, roots in TAXONOMY.items():
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
            )
    session.commit()
    return created
