import os as _os
# 数据文件统一存放于项目根的 data/ 目录；切到该目录使所有裸文件名读写都落到 data/
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data"))
import random
import json
import math

# ============================================================================
#  Oxbridge Academy 校车「真实覆盖范围」虚拟学生坐标生成器  (第 2 轮优化测试)
# ----------------------------------------------------------------------------
#  数据来源：根据学校现有 3 条校车线路 (North-1~7 / West-1~3 / South-1~4)
#  共 14 个真实站点手绘出的红色覆盖范围图。
#
#  ⚠️ 精度说明：下面的 COVERAGE_POLYGON 顶点是依据红线图中可识别的真实地标
#     (Tequesta、大西洋海岸线、Wellington、Westlake、The Acreage、
#      Grassy Waters Preserve、Boynton Beach 南端) 人工标定的「近似多边形」，
#     并非像素级精确还原。如发现落点与红线有偏差，直接调整这里的顶点即可，
#     运行后用 preview_students.html 肉眼核对。
# ============================================================================

# 学校总部真实坐标 (图中红色大头针)
SCHOOL = {"name": "Oxbridge Academy", "lat": 26.7153, "lng": -80.1147}

# 学校 1 公里范围内不生成学生 (太近，无需乘坐校车)
EXCLUDE_RADIUS_KM = 1.0

TOTAL_STUDENTS = 100

# ----------------------------------------------------------------------------
#  覆盖范围多边形顶点 (顺时针，单位: 经纬度 [lat, lng])
#  形状特征:
#    - 北段(North): 沿 I-95 / Florida Tpke 走廊的竖条, 顶到 Tequesta, 东抵海岸
#    - 西段(West):  向西突出到 Wellington / Westlake / The Acreage
#    - North 与 West 之间有一个深凹口 (排除 Grassy Waters Preserve / Jupiter Farms 西部)
#    - 东边界: 大致沿大西洋海岸线 (lng ≈ -80.035)
#    - 南段(South): 下探到 Boynton Beach (1500 SW 8th St, South-1) 一带
# ----------------------------------------------------------------------------
COVERAGE_POLYGON = [
    # —— 北顶 (Tequesta 一带) ——
    (26.975, -80.105),   # 北顶 · 西角
    (26.975, -80.070),   # 北顶 · 东角 (Intracoastal 以西，确保在陆地)
    # —— 东边界: 沿 Intracoastal Waterway 西侧南下 (不越过海岸线) ——
    (26.840, -80.062),   # Jupiter / Palm Beach Gardens
    (26.700, -80.050),   # North Palm Beach / Riviera Beach
    (26.560, -80.053),   # Lake Worth 一带
    (26.490, -80.055),   # 东南角 (Boynton Beach 西侧)
    # —— 南边界: 向西 ——
    (26.487, -80.095),
    (26.490, -80.150),   # 南 · 西南角 (Boynton 西)
    # —— 西边界(South 段): 北上 ——
    (26.590, -80.168),
    (26.620, -80.170),
    # —— West 段: 向西突出 ——
    (26.622, -80.258),   # West · 西南 (Wellington 南)
    (26.705, -80.262),   # West · 西北 (Lion Country / Westlake)
    (26.718, -80.205),   # West · 北东
    # —— North / West 之间的深凹口 (排除 Grassy Waters) ——
    (26.700, -80.130),   # 凹口 · 东南底
    (26.745, -80.128),
    # —— 西边界(North 段): 北上 (排除 Jupiter Farms 西部) ——
    (26.790, -80.150),
    (26.865, -80.150),
    (26.878, -80.112),
    (26.915, -80.112),
    (26.975, -80.105),   # 闭合回北顶西角
]


def haversine_km(lat1, lng1, lat2, lng2):
    """两点间地表大圆距离 (公里)，用于排除学校 1km 范围。"""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def point_in_polygon(lat, lng, polygon):
    """射线法判断点 (lat,lng) 是否落在多边形内部。"""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i]      # (lat, lng)
        yj, xj = polygon[j]
        intersect = ((yi > lat) != (yj > lat)) and \
                    (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside


def bounding_box(polygon):
    lats = [p[0] for p in polygon]
    lngs = [p[1] for p in polygon]
    return min(lats), max(lats), min(lngs), max(lngs)


def generate_students():
    min_lat, max_lat, min_lng, max_lng = bounding_box(COVERAGE_POLYGON)
    students = []
    attempts = 0
    rng = random.Random(42)  # 固定随机种子，保证结果可复现

    while len(students) < TOTAL_STUDENTS:
        attempts += 1
        if attempts > TOTAL_STUDENTS * 1000:
            raise RuntimeError("拒绝采样次数过多，请检查多边形顶点是否正确。")

        lat = rng.uniform(min_lat, max_lat)
        lng = rng.uniform(min_lng, max_lng)

        # 条件 1: 必须落在红色覆盖多边形内部
        if not point_in_polygon(lat, lng, COVERAGE_POLYGON):
            continue
        # 条件 2: 必须在学校 1 公里之外
        if haversine_km(lat, lng, SCHOOL["lat"], SCHOOL["lng"]) < EXCLUDE_RADIUS_KM:
            continue

        idx = len(students) + 1
        students.append({
            "student_id": f"STU_{idx:03d}",
            "lat": round(lat, 6),
            "lng": round(lng, 6),
        })

    return students, attempts


def write_preview_html(students, filename="../frontend/preview_students.html"):
    """生成一个不依赖 Google API 的 SVG 预览图，直接用浏览器打开即可肉眼核对。"""
    min_lat, max_lat, min_lng, max_lng = bounding_box(COVERAGE_POLYGON)
    pad = 0.02
    min_lat -= pad; max_lat += pad; min_lng -= pad; max_lng += pad

    W, H = 760, 1000
    lat0 = math.radians((min_lat + max_lat) / 2)
    kx = math.cos(lat0)  # 经度按纬度收缩，避免形状变形

    def to_xy(lat, lng):
        x = (lng - min_lng) * kx
        y = (lat - min_lat)
        sx = x / ((max_lng - min_lng) * kx) * W
        sy = H - (y / (max_lat - min_lat) * H)  # 纬度大在上
        return sx, sy

    poly_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in
                        (to_xy(la, ln) for la, ln in COVERAGE_POLYGON))

    # 此阶段学生尚未分区，统一用单色显示
    STUDENT_COLOR = "#38bdf8"
    dots = []
    for s in students:
        x, y = to_xy(s["lat"], s["lng"])
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" '
                    f'fill="{STUDENT_COLOR}" opacity="0.85"/>')

    sx, sy = to_xy(SCHOOL["lat"], SCHOOL["lng"])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>虚拟学生分布预览 · 核对用</title>
<style>
  body {{ margin:0; background:#1a1a2e; color:#e2e8f0;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  .wrap {{ display:flex; gap:24px; padding:24px; }}
  .legend div {{ margin:6px 0; font-size:14px; }}
  .sw {{ display:inline-block; width:12px; height:12px; border-radius:50%;
        margin-right:8px; vertical-align:middle; }}
  h2 {{ margin:0 0 4px; }} p {{ color:#94a3b8; font-size:13px; margin:4px 0; }}
</style></head><body>
<div class="wrap">
  <svg width="{W}" height="{H}" style="background:#242f3e;border-radius:12px;">
    <polygon points="{poly_pts}" fill="rgba(239,68,68,0.06)"
             stroke="#ef4444" stroke-width="3"/>
    {''.join(dots)}
    <circle cx="{sx:.1f}" cy="{sy:.1f}" r="9" fill="#7c3aed"
            stroke="#fff" stroke-width="2"/>
    <text x="{sx+14:.1f}" y="{sy+4:.1f}" fill="#fff" font-size="13"
          font-weight="bold">Oxbridge HQ</text>
  </svg>
  <div class="legend">
    <h2>虚拟学生分布预览</h2>
    <p>红色边框 = 你手绘的校车覆盖范围</p>
    <p>紫点 = 学校 (周边 1km 已排除)</p>
    <p>蓝点 = 虚拟学生 (尚未分区)</p>
    <p>共 {len(students)} 名学生</p>
    <hr style="border-color:#334155;">
    <p>核对要点：所有蓝点应落在红框内，<br>且学校紫点周围应有一圈空白。</p>
    <p style="color:#64748b;">分区将在下一步按校车运力均衡算法决定。</p>
  </div>
</div></body></html>"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    students, attempts = generate_students()

    with open("virtual_students.json", "w", encoding="utf-8") as f:
        json.dump(students, f, indent=4, ensure_ascii=False)

    write_preview_html(students)

    acc = len(students) / attempts * 100

    print(f"✅ 已在覆盖多边形内生成 {len(students)} 个虚拟学生 (采样命中率 {acc:.1f}%)")
    print(f"   已排除学校 {EXCLUDE_RADIUS_KM}km 范围内的位置")
    print("   学生尚未分区 (分区将在下一步按校车运力均衡算法决定)")
    print("💾 已写入 virtual_students.json")
    print("🖼  预览图已生成 preview_students.html (浏览器打开即可肉眼核对落点)")
