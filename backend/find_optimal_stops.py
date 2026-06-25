import os as _os
# 数据文件统一存放于项目根的 data/ 目录；切到该目录使所有裸文件名读写都落到 data/
# 预览 HTML 则通过 ../frontend/ 写到前端目录
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data"))
import json
import math
import numpy as np

# ============================================================================
#  第 4 步：每个区内「自动决定最优站点数」并定位站点坐标
# ----------------------------------------------------------------------------
#  输入：virtual_students.json  (已含 zone = Zone_1 / Zone_2 / Zone_3)
#  输出：
#    - all_bus_stops.json      每个站点的坐标 + 所属区 + 服务人数
#    - clustered_students.json 每个学生分配到的具体站点 (供前端散点渲染)
#
#  算法：对每个区独立运行
#    1. 在 k = 2..K_MAX 范围内用纯 numpy K-Means 聚类
#    2. 用「轮廓系数 (silhouette score)」自动挑出最优站点数 k
#    3. (可选) 商业合并：裁撤服务人数 < MIN_STOP_SIZE 的微型站，
#       其学生就近并入最近的达标站，避免站点过于碎碎
#  距离统一用纬度收缩校正后的平面近似，口径与 assign_students.py 一致。
# ============================================================================

K_MAX = 6              # 每区最多尝试的站点数上限
MIN_STOP_SIZE = 4      # 商业合并阈值：服务人数低于此值的站会被裁撤合并
MAX_STOP_SIZE = 11     # 单站人数上限：轮廓系数选出的某站超此值则自动增加站数拆分
ENABLE_MERGE = True    # 是否启用商业合并 (False 则纯按轮廓系数结果)

LAT_REF = 26.7
LNG_SCALE = math.cos(math.radians(LAT_REF))
RANDOM_SEED = 42


def load_students(path="virtual_students.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def to_xy(lat, lng):
    return np.array([lat, lng * LNG_SCALE], dtype=float)


def kmeans(pts, k, seed, max_iter=100):
    """纯 numpy K-Means (k-means++ 初始化)。返回 (labels, centroids)。"""
    n = len(pts)
    rng = np.random.default_rng(seed)
    first = rng.integers(n)
    centroids = [pts[first]]
    for _ in range(1, k):
        dmin = np.min(
            np.linalg.norm(pts[:, None, :] - np.array(centroids)[None, :, :], axis=2),
            axis=1,
        )
        prob = dmin ** 2
        s = prob.sum()
        if s == 0:
            centroids.append(pts[rng.integers(n)])
            continue
        centroids.append(pts[rng.choice(n, p=prob / s)])
    centroids = np.array(centroids)

    labels = np.zeros(n, dtype=int)
    for _ in range(max_iter):
        d = np.linalg.norm(pts[:, None, :] - centroids[None, :, :], axis=2)
        new_labels = d.argmin(axis=1)
        new_centroids = np.array([
            pts[new_labels == j].mean(axis=0) if np.any(new_labels == j) else centroids[j]
            for j in range(k)
        ])
        if np.array_equal(new_labels, labels):
            labels = new_labels
            centroids = new_centroids
            break
        labels, centroids = new_labels, new_centroids
    return labels, centroids


def silhouette_score(pts, labels):
    """纯 numpy 轮廓系数 (平均值)。labels 至少含 2 个簇且每簇 ≥1 点。"""
    n = len(pts)
    unique = np.unique(labels)
    if len(unique) < 2:
        return -1.0
    # 两两距离矩阵
    D = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=2)
    sil = np.zeros(n)
    for i in range(n):
        same = labels == labels[i]
        same[i] = False
        if same.sum() == 0:
            sil[i] = 0.0  # 孤点簇
            continue
        a = D[i, same].mean()
        b = np.inf
        for c in unique:
            if c == labels[i]:
                continue
            mask = labels == c
            b = min(b, D[i, mask].mean())
        sil[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return sil.mean()


def choose_best_k(pts, k_max, seed, max_stop_size=None):
    """在 k=2..k_max 用轮廓系数挑最优站数。点太少时退化。

    若给定 max_stop_size，则在轮廓最优解的基础上继续增加站数，
    直到没有任何单站服务人数超过该上限 (解决「某站挤太多人」的问题)。
    """
    n = len(pts)
    if n <= 2:
        return 1
    best_k, best_score = 2, -1.0
    upper = min(k_max, n - 1)
    for k in range(2, upper + 1):
        labels, _ = kmeans(pts, k, seed)
        if len(np.unique(labels)) < 2:
            continue
        score = silhouette_score(pts, labels)
        if score > best_score:
            best_score, best_k = score, k

    # 单站人数上限约束：若最优解里仍有超载站，逐步加站直到达标
    if max_stop_size is not None:
        k = best_k
        while k < upper:
            labels, _ = kmeans(pts, k, seed)
            counts = np.bincount(labels, minlength=k)
            if counts.max() <= max_stop_size:
                break
            k += 1
        best_k = k

    return best_k


def merge_small_stops(pts, labels, centroids, min_size):
    """商业合并：把服务人数 < min_size 的微型站裁撤，学生就近并入达标大站。"""
    counts = np.bincount(labels, minlength=len(centroids))
    large = [j for j in range(len(centroids)) if counts[j] >= min_size]
    if not large:  # 全不达标 → 保留最大的一个
        large = [int(counts.argmax())]
    large_centroids = centroids[large]

    new_labels = labels.copy()
    for i in range(len(pts)):
        if labels[i] not in large:
            d = np.linalg.norm(large_centroids - pts[i], axis=1)
            new_labels[i] = large[int(d.argmin())]

    # 重新编号为连续 0..m-1，并重算质心
    remap = {old: new for new, old in enumerate(sorted(set(new_labels)))}
    final_labels = np.array([remap[l] for l in new_labels])
    m = len(remap)
    final_centroids = np.array([pts[final_labels == j].mean(axis=0) for j in range(m)])
    return final_labels, final_centroids


def write_stops_preview(students_assigned, stops, filename="../frontend/preview_stops.html"):
    """生成站点结果 SVG 预览：学生按所属站点上色，站点用大圈+序号标出。"""
    SCHOOL = {"lat": 26.7153, "lng": -80.1147}
    lats = [s["lat"] for s in students_assigned] + [b["lat"] for b in stops]
    lngs = [s["lng"] for s in students_assigned] + [b["lng"] for b in stops]
    min_lat, max_lat = min(lats) - 0.03, max(lats) + 0.03
    min_lng, max_lng = min(lngs) - 0.03, max(lngs) + 0.03

    W, H = 720, 960
    kx = LNG_SCALE

    def xy(lat, lng):
        sx = (lng - min_lng) * kx / ((max_lng - min_lng) * kx) * W
        sy = H - (lat - min_lat) / (max_lat - min_lat) * H
        return sx, sy

    zone_base = {"Zone_1": "#10b981", "Zone_2": "#3b82f6", "Zone_3": "#f59e0b"}
    palette = ["#34d399", "#60a5fa", "#fbbf24", "#f87171", "#c084fc",
               "#fb923c", "#f472b6", "#38bdf8", "#a3e635", "#e879f9"]
    stop_color = {b["stop_id"]: palette[i % len(palette)] for i, b in enumerate(stops)}

    dots = []
    for s in students_assigned:
        x, y = xy(s["lat"], s["lng"])
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" '
                    f'fill="{stop_color[s["route_id"]]}" opacity="0.7"/>')

    smarks = []
    for b in stops:
        x, y = xy(b["lat"], b["lng"])
        c = stop_color[b["stop_id"]]
        smarks.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{c}" '
            f'stroke="#fff" stroke-width="2"/>'
            f'<text x="{x+12:.1f}" y="{y+4:.1f}" fill="{c}" font-size="11" '
            f'font-weight="bold">{b["student_count"]}人</text>')

    sx, sy = xy(SCHOOL["lat"], SCHOOL["lng"])
    zones = sorted({b["zone"] for b in stops})
    legend = ""
    for z in zones:
        zstops = [b for b in stops if b["zone"] == z]
        legend += (f'<div style="margin-top:10px;font-weight:bold;'
                   f'color:{zone_base.get(z,"#fff")};">{z}: {len(zstops)} 站 '
                   f'/ {sum(b["student_count"] for b in zstops)} 人</div>')
        for b in zstops:
            legend += (f'<div style="font-size:13px;margin-left:8px;">'
                       f'<span style="display:inline-block;width:10px;height:10px;'
                       f'border-radius:50%;background:{stop_color[b["stop_id"]]};'
                       f'margin-right:6px;"></span>{b["stop_id"]}: {b["student_count"]} 人</div>')

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>各区最优站点预览</title>
<style>body{{margin:0;background:#1a1a2e;color:#e2e8f0;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}}
.wrap{{display:flex;gap:24px;padding:24px;}}h2{{margin:0 0 8px;}}
p{{color:#94a3b8;font-size:13px;}}</style></head><body>
<div class="wrap">
<svg width="{W}" height="{H}" style="background:#242f3e;border-radius:12px;">
{''.join(dots)}{''.join(smarks)}
<circle cx="{sx:.1f}" cy="{sy:.1f}" r="9" fill="#7c3aed" stroke="#fff" stroke-width="2"/>
<text x="{sx+13:.1f}" y="{sy+4:.1f}" fill="#fff" font-size="13" font-weight="bold">HQ</text>
</svg>
<div class="legend" style="max-height:920px;overflow-y:auto;">
<h2>各区最优站点</h2><p>大圈=站点 · 同色散点=该站服务的学生 · 紫点=学校</p>
<p>共 {len(stops)} 个站点</p><hr style="border-color:#334155;">{legend}
<hr style="border-color:#334155;">
<p>核对要点：每个站到其学生的距离是否合理，<br>有无某站服务人数过多/步行过远。</p>
</div></div></body></html>"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    students = load_students()
    zones = sorted({s["zone"] for s in students})

    all_bus_stops = []
    clustered_students = []

    print("=" * 56)
    print("🚏 第 4 步：每区自动决定最优站点数 (轮廓系数)")
    print("=" * 56)

    for zone in zones:
        zone_students = [s for s in students if s["zone"] == zone]
        pts = np.array([to_xy(s["lat"], s["lng"]) for s in zone_students])
        n = len(zone_students)

        best_k = choose_best_k(pts, K_MAX, RANDOM_SEED, MAX_STOP_SIZE)
        labels, centroids = kmeans(pts, best_k, RANDOM_SEED)

        merged_note = ""
        if ENABLE_MERGE and best_k > 1:
            before = len(np.unique(labels))
            labels, centroids = merge_small_stops(pts, labels, centroids, MIN_STOP_SIZE)
            after = len(centroids)
            if after < before:
                merged_note = f" (轮廓建议 {before} 站 → 商业合并后 {after} 站)"

        num_stops = len(centroids)
        counts = np.bincount(labels, minlength=num_stops)

        print(f"\n📍 {zone} (共 {n} 名学生) → 最优 {num_stops} 个站点{merged_note}")

        for j in range(num_stops):
            clat = float(centroids[j][0])
            clng = float(centroids[j][1] / LNG_SCALE)  # 还原真实经度
            stop_id = f"{zone}_Stop_{j + 1}"
            all_bus_stops.append({
                "stop_id": stop_id,
                "zone": zone,
                "lat": round(clat, 6),
                "lng": round(clng, 6),
                "student_count": int(counts[j]),
            })
            print(f"     • {stop_id}: 服务 {counts[j]} 名学生  "
                  f"({clat:.5f}, {clng:.5f})")

        # 学生 → 站点分配 (初步按区内最近)
        for s, lab in zip(zone_students, labels):
            stop_id = f"{zone}_Stop_{int(lab) + 1}"
            stop = next(b for b in all_bus_stops if b["stop_id"] == stop_id)
            rec = dict(s)
            rec["route_id"] = stop_id
            rec["stop_lat"] = stop["lat"]
            rec["stop_lng"] = stop["lng"]
            clustered_students.append(rec)

    # ══════════════════════════════════════════════════════════════════════
    #  后处理：全局最近站重分配 (跨区修正边界学生的不合理分配)
    # ──────────────────────────────────────────────────────────────────────
    #  K-Means 只在本区内看最近站，但区域边界附近的学生可能离隔壁区的站更近。
    #  这一步让每个学生忽略区域限制，直接分配给绝对最近的站点，
    #  然后 zone 跟随新站点所在区。最后检查各车不超载 (BUS_CAPACITY)。
    # ══════════════════════════════════════════════════════════════════════
    BUS_CAPACITY = 45
    print("\n🔄 全局最近站重分配 (跨区修正边界学生)...")
    reassigned_count = 0

    # 构建所有站点的 xy 坐标数组
    stop_pts = np.array([to_xy(b["lat"], b["lng"]) for b in all_bus_stops])

    for rec in clustered_students:
        pt = to_xy(rec["lat"], rec["lng"])
        dists = np.linalg.norm(stop_pts - pt, axis=1)
        nearest_idx = int(dists.argmin())
        nearest_stop = all_bus_stops[nearest_idx]

        if nearest_stop["stop_id"] != rec["route_id"]:
            # 检查目标站所在区是否会超载
            target_zone = nearest_stop["zone"]
            zone_load = sum(1 for r in clustered_students
                           if r.get("route_id", "").startswith(target_zone))
            if zone_load < BUS_CAPACITY:
                rec["route_id"] = nearest_stop["stop_id"]
                rec["stop_lat"] = nearest_stop["lat"]
                rec["stop_lng"] = nearest_stop["lng"]
                rec["zone"] = target_zone
                reassigned_count += 1

    # 重算每个站的服务人数
    for b in all_bus_stops:
        b["student_count"] = sum(1 for r in clustered_students
                                 if r["route_id"] == b["stop_id"])

    # 同步更新 virtual_students.json 里的 zone (保持一致)
    student_zone_map = {r["student_id"]: r["zone"] for r in clustered_students}
    students_updated = load_students()
    for s in students_updated:
        if s["student_id"] in student_zone_map:
            s["zone"] = student_zone_map[s["student_id"]]
    with open("virtual_students.json", "w", encoding="utf-8") as f:
        json.dump(students_updated, f, indent=4, ensure_ascii=False)

    print(f"   ↪ 跨区重分配了 {reassigned_count} 名边界学生")
    # 打印重分配后各区人数
    for zone in sorted({b["zone"] for b in all_bus_stops}):
        zone_count = sum(b["student_count"] for b in all_bus_stops if b["zone"] == zone)
        zone_stops = [b for b in all_bus_stops if b["zone"] == zone]
        detail = "/".join(str(b["student_count"]) for b in zone_stops)
        print(f"   {zone}: {zone_count} 人 ({detail})")

    with open("all_bus_stops.json", "w", encoding="utf-8") as f:
        json.dump(all_bus_stops, f, indent=4, ensure_ascii=False)
    with open("clustered_students.json", "w", encoding="utf-8") as f:
        json.dump(clustered_students, f, indent=4, ensure_ascii=False)

    print("\n" + "-" * 56)
    print(f"✅ 全部 {len(zones)} 个区共设置 {len(all_bus_stops)} 个站点")
    print("💾 已写入 all_bus_stops.json 与 clustered_students.json")

    write_stops_preview(clustered_students, all_bus_stops)
    print("🖼  站点预览图已生成 preview_stops.html")


if __name__ == "__main__":
    main()
