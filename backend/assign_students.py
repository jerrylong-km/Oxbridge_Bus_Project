import os as _os
# 数据文件统一存放于项目根的 data/ 目录；切到该目录使所有裸文件名读写都落到 data/
# 预览 HTML 则通过 ../frontend/ 写到前端目录
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data"))
import json
import math
import numpy as np

# ============================================================================
#  第 2 步：按校车「运力均衡 + 地理聚合」对 100 名学生分区
# ----------------------------------------------------------------------------
#  输入：virtual_students.json  (仅含 student_id / lat / lng，尚未分区)
#  输出：在每条学生记录中填入 zone 字段 (Zone_1 / Zone_2 / Zone_3)
#
#  算法：带「硬容量上限 + 均衡软惩罚」的 K-Means (Lloyd 迭代)
#    - 每辆校车 = 一个分区 = 一个聚类质心
#    - 硬约束：任何一辆车不得超过座位上限 (BUS_CAPACITY)
#    - 软目标：在地理就近的前提下，把各车人数拉平到 ~100/N 人
#    - 距离按经纬度做了纬度方向的收缩校正，避免佛州中纬度处经度被高估
# ============================================================================

NUM_BUSES = 3        # 校车数量 (= 分区数)
BUS_CAPACITY = 45    # 每辆校车座位上限 (硬约束)

# 均衡力度：越大越强行拉平各车人数 (代价是允许个别学生被分到稍远的车)。
# 1.0 = 温和；2.5 = 较强，人数极差通常能压到 1~3 人。
BALANCE_WEIGHT = 2.5

# 经度收缩系数：在 26.7°N 处，1° 经度 ≈ cos(26.7°) ≈ 0.893° 纬度的地表距离
LAT_REF = 26.7
LNG_SCALE = math.cos(math.radians(LAT_REF))

RANDOM_SEED = 42
MAX_ITER = 100


def load_students(path="virtual_students.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def to_xy(students):
    """把经纬度转成做了纬度收缩的平面坐标 (单位仍近似为度，但各方向等比)。"""
    pts = np.array([[s["lat"], s["lng"] * LNG_SCALE] for s in students], dtype=float)
    return pts


def balanced_capacitated_assign(pts, centroids, capacity, target):
    """在给定质心下，做一次「带容量上限 + 均衡惩罚」的分配。

    返回每个点的分区标签 (np.array)。

    思路：
      - 对每个点计算到各质心的「有效成本」= 几何距离 + 该车当前载客的均衡惩罚
      - 按「最近质心距离」从大到小处理点 (最难安置的点优先选座)，
        减少后处理时无车可上的窘境
      - 某辆车坐满 capacity 后，从候选中剔除，点只能退而求其次
    """
    n = len(pts)
    k = len(centroids)
    # 点到各质心的几何距离矩阵
    d = np.linalg.norm(pts[:, None, :] - centroids[None, :, :], axis=2)  # (n, k)

    labels = np.full(n, -1, dtype=int)
    load = np.zeros(k, dtype=int)

    # 「最难安置」优先：到最近质心都很远的点，先让它挑车
    nearest_dist = d.min(axis=1)
    order = np.argsort(-nearest_dist)

    for i in order:
        # 均衡惩罚：越接近/超过目标人数，惩罚越大，把人往空车赶
        penalty = BALANCE_WEIGHT * (load / target) * nearest_dist[i]
        cost = d[i] + penalty
        # 已坐满的车不可选
        cost[load >= capacity] = np.inf
        choice = int(np.argmin(cost))
        labels[i] = choice
        load[choice] += 1

    return labels


def kmeans_balanced(pts, k, capacity, seed, max_iter):
    n = len(pts)
    target = n / k

    rng = np.random.default_rng(seed)
    # k-means++ 风格的初始质心：先随机选一个，其余尽量选离已选质心远的点
    first = rng.integers(n)
    centroids = [pts[first]]
    for _ in range(1, k):
        dmin = np.min(
            np.linalg.norm(pts[:, None, :] - np.array(centroids)[None, :, :], axis=2),
            axis=1,
        )
        prob = dmin ** 2
        prob = prob / prob.sum()
        nxt = rng.choice(n, p=prob)
        centroids.append(pts[nxt])
    centroids = np.array(centroids)

    labels = None
    for _ in range(max_iter):
        new_labels = balanced_capacitated_assign(pts, centroids, capacity, target)
        # 更新质心为各分区均值
        new_centroids = np.array([
            pts[new_labels == j].mean(axis=0) if np.any(new_labels == j) else centroids[j]
            for j in range(k)
        ])
        if labels is not None and np.array_equal(new_labels, labels):
            centroids = new_centroids
            labels = new_labels
            break
        labels = new_labels
        centroids = new_centroids

    return labels, centroids


def write_zone_preview(students, labels, centroids, counts,
                       filename="../frontend/preview_zones.html"):
    """生成分区结果 SVG 预览图，肉眼核对地理聚合与人数均衡情况。"""
    SCHOOL = {"lat": 26.7153, "lng": -80.1147}
    lats = [s["lat"] for s in students]
    lngs = [s["lng"] for s in students]
    min_lat, max_lat = min(lats) - 0.03, max(lats) + 0.03
    min_lng, max_lng = min(lngs) - 0.03, max(lngs) + 0.03

    W, H = 720, 960
    kx = LNG_SCALE

    def xy(lat, lng):
        sx = (lng - min_lng) * kx / ((max_lng - min_lng) * kx) * W
        sy = H - (lat - min_lat) / (max_lat - min_lat) * H
        return sx, sy

    palette = ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#a855f7"]
    dots = []
    for s, lab in zip(students, labels):
        x, y = xy(s["lat"], s["lng"])
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" '
                    f'fill="{palette[int(lab) % len(palette)]}" opacity="0.85"/>')

    # 质心 (注意 centroids 第二维是 lng*LNG_SCALE，需还原回真实 lng)
    cmarks = []
    for j, c in enumerate(centroids):
        clat, clng = c[0], c[1] / LNG_SCALE
        x, y = xy(clat, clng)
        cmarks.append(
            f'<rect x="{x-7:.1f}" y="{y-7:.1f}" width="14" height="14" '
            f'fill="none" stroke="{palette[j % len(palette)]}" stroke-width="3"/>'
            f'<text x="{x+11:.1f}" y="{y+5:.1f}" fill="{palette[j % len(palette)]}" '
            f'font-size="13" font-weight="bold">Z{j+1}</text>')

    sx, sy = xy(SCHOOL["lat"], SCHOOL["lng"])
    legend = "".join(
        f'<div><span style="display:inline-block;width:12px;height:12px;'
        f'border-radius:50%;background:{palette[j]};margin-right:8px;"></span>'
        f'Zone_{j+1}: {counts[j]} 人 (载客率 {counts[j]/BUS_CAPACITY*100:.0f}%)</div>'
        for j in range(len(counts)))

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>校车运力均衡分区结果</title>
<style>body{{margin:0;background:#1a1a2e;color:#e2e8f0;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}}
.wrap{{display:flex;gap:24px;padding:24px;}}.legend div{{margin:8px 0;font-size:14px;}}
h2{{margin:0 0 8px;}}p{{color:#94a3b8;font-size:13px;}}</style></head><body>
<div class="wrap">
<svg width="{W}" height="{H}" style="background:#242f3e;border-radius:12px;">
{''.join(dots)}{''.join(cmarks)}
<circle cx="{sx:.1f}" cy="{sy:.1f}" r="9" fill="#7c3aed" stroke="#fff" stroke-width="2"/>
<text x="{sx+13:.1f}" y="{sy+4:.1f}" fill="#fff" font-size="13" font-weight="bold">HQ</text>
</svg>
<div class="legend"><h2>运力均衡分区结果</h2>
<p>{NUM_BUSES} 辆校车 · 每辆上限 {BUS_CAPACITY} 座</p>
<p>方块 = 各区质心 · 紫点 = 学校</p><hr style="border-color:#334155;">
{legend}<hr style="border-color:#334155;">
<p>人数极差: {max(counts)-min(counts)} 人</p>
<p>核对要点：同色点应成片聚合<br>不应出现某区零散插花到别区中间。</p>
</div></div></body></html>"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    students = load_students()
    n = len(students)

    if NUM_BUSES * BUS_CAPACITY < n:
        raise SystemExit(
            f"❌ 运力不足：{NUM_BUSES} 辆车 × {BUS_CAPACITY} 座 = "
            f"{NUM_BUSES * BUS_CAPACITY} < {n} 名学生。请增加校车数量或座位上限。"
        )

    pts = to_xy(students)
    labels, centroids = kmeans_balanced(pts, NUM_BUSES, BUS_CAPACITY,
                                        RANDOM_SEED, MAX_ITER)

    # 把分区标签 (0,1,2) 映射成 Zone_1 / Zone_2 / Zone_3 并写回学生记录
    for s, lab in zip(students, labels):
        s["zone"] = f"Zone_{int(lab) + 1}"

    with open("virtual_students.json", "w", encoding="utf-8") as f:
        json.dump(students, f, indent=4, ensure_ascii=False)

    # 统计报告
    print("=" * 52)
    print(f"🚌 运力均衡分区完成 ({NUM_BUSES} 辆校车，每辆上限 {BUS_CAPACITY} 座)")
    print("=" * 52)
    counts = [int(np.sum(labels == j)) for j in range(NUM_BUSES)]
    for j in range(NUM_BUSES):
        bar = "█" * counts[j]
        fill = counts[j] / BUS_CAPACITY * 100
        print(f"  Zone_{j + 1}: {counts[j]:>3} 人 (载客率 {fill:4.0f}%)  {bar}")
    spread = max(counts) - min(counts)
    print("-" * 52)
    print(f"  人数极差 (最多 - 最少): {spread} 人")
    print(f"  合计: {sum(counts)} 人 | 理想均值: {n / NUM_BUSES:.1f} 人/车")
    print("💾 已把 zone 字段写回 virtual_students.json")

    write_zone_preview(students, labels, centroids, counts)
    print("🖼  分区预览图已生成 preview_zones.html")


if __name__ == "__main__":
    main()
