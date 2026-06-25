import math
import itertools
import json
import os
import datetime
import requests

# 数据文件统一存放于项目根的 data/ 目录；切到该目录使所有裸文件名读写都落到 data/
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
# ============================================================================
#  第 5 步：每辆校车的最优行驶路线 (固定终点为学校的最短开放路径)
# ----------------------------------------------------------------------------
#  输入：all_bus_stops.json (含 zone = Zone_1/Zone_2/Zone_3)
#  输出：bus_routes.json    (每个区: 最远站点→有序途中站点→学校)
#
#  ⚠️ 与实际运行手册一致：校车早上不是从学校出发再绕回学校，而是
#     「从离学校最远的站点发车 → 依次经过沿途各站点接学生 → 最终到校」。
#     因此这是一条固定起点(最远站)、固定终点(学校)的开放路径，而非闭环。
#
#  算法：
#    1. 对每个区，把「学校 + 该区所有站点」打包
#    2. 调 Google Distance Matrix API 获取真实行车时间矩阵
#       (若 API 不可用则自动降级为模拟路网矩阵)
#    3. 选出离学校行车时间最长的站点作为固定发车点
#    4. 暴力枚举其余途中站点的所有排列 (计算量极小)，找出
#       「最远站 → … → 学校」总行车时间最短的顺序
#    5. 输出有序路线 JSON，供前端渲染
# ============================================================================

# ==================== 1. 配置 ====================
def load_dotenv(path=".env"):
    """极简 .env 读取器 (无需第三方库)。把 KEY=VALUE 写入 os.environ。

    .env 已被 .gitignore 屏蔽，密钥不会进入 git 历史。
    已存在的环境变量优先，不被 .env 覆盖 (方便临时 export 调试)。
    """
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_dotenv()

# Google Maps API Key (留空或填 placeholder 时自动降级为模拟矩阵)
# 来源优先级：环境变量 > .env 文件。两处都没有则用模拟矩阵。
GOOGLE_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")


def is_real_key(key):
    """判断是否是一个真实可用的 Google key (而非空/占位符)。

    真实 Google Maps key 以 'AIza' 开头、约 39 位 ASCII 字符。
    .env 里的中文占位符、'YOUR_...' 之类都会被判为非真实 → 自动降级模拟矩阵。
    """
    if not key:
        return False
    if key.startswith("YOUR"):
        return False
    if not key.isascii():       # 中文占位符 (如「在这里粘贴你的key」)
        return False
    return key.startswith("AIza") and len(key) >= 30

# 学校总部坐标
SCHOOL = {"name": "Oxbridge Academy", "lat": 26.7153, "lng": -80.1147}

# 是否启用早高峰路况 (True 时向 Google 请求含拥堵的 duration_in_traffic)
# 校车早上运行，开启后用时更贴近实际运营手册。仅在使用真实 API Key 时生效。
USE_RUSH_HOUR_TRAFFIC = True

# 早高峰出发时刻 (本地时间)，用于 duration_in_traffic 估算。
# Google 要求 departure_time 必须是「未来」的时刻，下面会自动取下一个工作日的该时刻。
RUSH_HOUR = (7, 30)  # 07:30


def next_weekday_departure(hour, minute):
    """返回下一个工作日 hour:minute 的 Unix 时间戳 (秒)，供 Google departure_time 用。

    Google Distance Matrix 要求 departure_time 为未来时刻；周末顺延到周一。
    """
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    # 跳过周六(5)、周日(6)
    while target.weekday() >= 5:
        target += datetime.timedelta(days=1)
    return int(target.timestamp())


# ==================== 2. Google Distance Matrix 请求 ====================
def fetch_matrices(points):
    """向 Google 请求真实驾车行车时间+距离矩阵。

    返回 (time_matrix[秒], dist_matrix[米])。
    若开启 USE_RUSH_HOUR_TRAFFIC 则用 duration_in_traffic (含路况)。
    API 不可用时自动降级为模拟矩阵。
    """
    if not is_real_key(GOOGLE_API_KEY):
        return build_simulated_matrices(points, is_demo=True)

    coords_str = "|".join([f"{p['lat']},{p['lng']}" for p in points])
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": coords_str,
        "destinations": coords_str,
        "mode": "driving",
        "key": GOOGLE_API_KEY,
    }

    # 早高峰路况
    if USE_RUSH_HOUR_TRAFFIC:
        params["departure_time"] = next_weekday_departure(*RUSH_HOUR)
        params["traffic_model"] = "best_guess"

    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()

        if data.get("status") != "OK":
            print(f"   ⚠️ Google API 状态异常: {data.get('status')}，降级为模拟数据")
            return build_simulated_matrices(points)

        n = len(points)
        time_matrix = [[0] * n for _ in range(n)]
        dist_matrix = [[0] * n for _ in range(n)]

        for i in range(n):
            elements = data["rows"][i]["elements"]
            for j in range(n):
                if elements[j].get("status") == "OK":
                    # 优先取含路况的 duration_in_traffic，没有则取 duration
                    if "duration_in_traffic" in elements[j]:
                        time_matrix[i][j] = elements[j]["duration_in_traffic"]["value"]
                    else:
                        time_matrix[i][j] = elements[j]["duration"]["value"]
                    dist_matrix[i][j] = elements[j]["distance"]["value"]
                else:
                    time_matrix[i][j] = 999999
                    dist_matrix[i][j] = 999999

        traffic_note = "含早高峰路况" if USE_RUSH_HOUR_TRAFFIC else "自由流"
        print(f"   ✅ Google Distance Matrix 请求成功 ({traffic_note})")
        return time_matrix, dist_matrix

    except Exception as e:
        print(f"   ❌ 网络请求失败 ({e})，降级为模拟数据")
        return build_simulated_matrices(points)


def build_simulated_matrices(points, is_demo=False):
    """基于经纬度几何距离 × 路网系数，生成模拟行车时间(秒)+距离(米)矩阵。"""
    if is_demo:
        print("   💡 当前使用模拟行车时间/距离矩阵 (如需真实路网请设置 GOOGLE_MAPS_API_KEY 环境变量)")
    n = len(points)
    cos_lat = math.cos(math.radians(26.7))
    time_matrix = [[0] * n for _ in range(n)]
    dist_matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            dlat = points[i]["lat"] - points[j]["lat"]
            dlng = (points[i]["lng"] - points[j]["lng"]) * cos_lat
            # 直线度数距离 → 近似公里 (1°≈111km)
            dist_km = math.sqrt(dlat**2 + dlng**2) * 111.0
            # 市区路网弯曲系数 ≈ 1.3 (实际路比直线长约 30%)
            road_km = dist_km * 1.3
            # 模拟市区驾车速度 ~35km/h
            drive_seconds = int(road_km / 35.0 * 3600)
            time_matrix[i][j] = drive_seconds
            dist_matrix[i][j] = int(road_km * 1000)  # 米
    return time_matrix, dist_matrix


# ==================== 3. 开放路径求解 (暴力枚举，适用于 ≤8 站) ====================
def solve_open_route(time_matrix):
    """固定终点为学校(索引0)的最短开放路径 (按时间最优)。

    校车从离学校最远的站点发车，依次经过其余途中站点，最终到校。
    返回 (有序站点索引列表, 总秒数)：列表首项=最远发车站，末项之后即学校。
    """
    num_points = len(time_matrix)
    if num_points <= 1:
        return [], 0

    stop_indices = list(range(1, num_points))

    # 发车点 = 离学校行车时间最长的站点 (固定为路径起点)
    start = max(stop_indices, key=lambda i: time_matrix[0][i])
    middle = [i for i in stop_indices if i != start]

    best_perm = None
    min_time = float("inf")

    # 枚举途中站点顺序：start → 中间各站 → 学校(0)
    for perm in itertools.permutations(middle):
        seq = [start, *perm]
        t = 0
        for i in range(len(seq) - 1):
            t += time_matrix[seq[i]][seq[i + 1]]
        t += time_matrix[seq[-1]][0]  # 最后一站 → 学校

        if t < min_time:
            min_time = t
            best_perm = seq

    return best_perm, min_time


# ==================== 4. 主程序 ====================
def main():
    if not os.path.exists("all_bus_stops.json"):
        print("❌ 找不到 all_bus_stops.json，请先运行 find_optimal_stops.py")
        return

    with open("all_bus_stops.json", "r", encoding="utf-8") as f:
        stops_list = json.load(f)

    # 按区分组
    zones = sorted({s["zone"] for s in stops_list})
    routes_output = {}
    metrics_output = {}

    traffic_label = "含早高峰路况" if (USE_RUSH_HOUR_TRAFFIC and is_real_key(GOOGLE_API_KEY)) \
        else "自由流/模拟"

    print("=" * 56)
    print("🚀 第 5 步：计算每辆校车最优行驶路线 (最远站发车 → 到校)")
    print(f"   时间口径: {traffic_label}")
    print("=" * 56)

    grand_seconds = 0
    grand_meters = 0
    rename_map = {}  # 老 stop_id → 新 stop_id (按运行顺序: 最远=1号, 最近号最大)

    for zone in zones:
        zone_stops = [s for s in stops_list if s["zone"] == zone]
        num_stops = len(zone_stops)

        if num_stops == 0:
            routes_output[zone] = [SCHOOL]
            metrics_output[zone] = {"total_minutes": 0, "total_km": 0, "segments": []}
            continue

        # 学校在索引 0，其余为站点
        all_points = [SCHOOL] + zone_stops

        # 获取行车时间(秒)+距离(米)矩阵
        time_matrix, dist_matrix = fetch_matrices(all_points)

        # 求解开放路径 (最远站 → … → 学校)，按时间最优
        best_perm, min_seconds = solve_open_route(time_matrix)

        # 完整索引序列: 最远站 → 途中站 → ... → 学校(索引0)
        idx_seq = list(best_perm) + [0]

        # 按运行顺序登记重编号映射：发车站(最远)=1号，沿途递增，最近站号最大。
        # best_perm 已是「最远 → … → 最近」的站点顺序 (不含学校)。
        for new_no, idx in enumerate(best_perm, start=1):
            old_sid = all_points[idx]["stop_id"]
            rename_map[old_sid] = f"{zone}_Stop_{new_no}"

        # 组装有序路线点 (供前端渲染)
        ordered_route = [all_points[idx] for idx in idx_seq]
        routes_output[zone] = ordered_route

        # 逐段明细 + 累计距离
        segments = []
        total_meters = 0
        for a, b in zip(idx_seq[:-1], idx_seq[1:]):
            seg_sec = time_matrix[a][b]
            seg_m = dist_matrix[a][b]
            total_meters += seg_m
            segments.append({
                "from": all_points[a].get("stop_id", all_points[a].get("name", "?")),
                "to": all_points[b].get("stop_id", all_points[b].get("name", "?")),
                "minutes": round(seg_sec / 60, 1),
                "km": round(seg_m / 1000, 2),
            })

        total_minutes = round(min_seconds / 60, 1)
        total_km = round(total_meters / 1000, 2)
        grand_seconds += min_seconds
        grand_meters += total_meters

        metrics_output[zone] = {
            "start_stop": ordered_route[0].get("stop_id", "?"),
            "total_minutes": total_minutes,
            "total_km": total_km,
            "num_stops": num_stops,
            "segments": segments,
        }

        stop_order = " → ".join(
            [s.get("stop_id", s.get("name", "?")) for s in ordered_route]
        )
        print(f"\n🚌 {zone} ({num_stops} 站) · 总用时 {total_minutes} 分钟 · 总里程 {total_km} km")
        print(f"   发车站: {ordered_route[0].get('stop_id', '?')} (离学校最远)")
        print(f"   路线: {stop_order}")
        print(f"   逐段明细:")
        for seg in segments:
            print(f"     • {seg['from']:>16} → {seg['to']:<16} "
                  f"{seg['minutes']:>5} 分 / {seg['km']:>6} km")

    with open("bus_routes.json", "w", encoding="utf-8") as f:
        json.dump(routes_output, f, indent=4, ensure_ascii=False)
    with open("route_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics_output, f, indent=4, ensure_ascii=False)

    # ══════════════════════════════════════════════════════════════════════════
    #  按运行路线顺序重编号站点 (最远=1号, 最近=最大号)
    # ──────────────────────────────────────────────────────────────────────────
    #  统一重写 all_bus_stops.json / clustered_students.json / bus_routes.json
    #  / route_metrics.json 里的 stop_id / route_id，保持所有文件一致。
    # ══════════════════════════════════════════════════════════════════════════
    if rename_map:
        # 如果新旧编号完全一致就跳过
        needs_rename = any(old != new for old, new in rename_map.items())
        if needs_rename:
            print("\n🔢 按运行顺序重编号站点...")
            for old, new in sorted(rename_map.items()):
                if old != new:
                    print(f"   {old} → {new}")

            # 1. all_bus_stops.json
            with open("all_bus_stops.json", "r", encoding="utf-8") as f:
                stops = json.load(f)
            for s in stops:
                if s["stop_id"] in rename_map:
                    s["stop_id"] = rename_map[s["stop_id"]]
            with open("all_bus_stops.json", "w", encoding="utf-8") as f:
                json.dump(stops, f, indent=4, ensure_ascii=False)

            # 2. clustered_students.json
            if os.path.exists("clustered_students.json"):
                with open("clustered_students.json", "r", encoding="utf-8") as f:
                    students = json.load(f)
                for s in students:
                    if s.get("route_id") in rename_map:
                        s["route_id"] = rename_map[s["route_id"]]
                with open("clustered_students.json", "w", encoding="utf-8") as f:
                    json.dump(students, f, indent=4, ensure_ascii=False)

            # 3. bus_routes.json (已在内存里，用新编号重写)
            for zone in routes_output:
                for pt in routes_output[zone]:
                    if pt.get("stop_id") in rename_map:
                        pt["stop_id"] = rename_map[pt["stop_id"]]
            with open("bus_routes.json", "w", encoding="utf-8") as f:
                json.dump(routes_output, f, indent=4, ensure_ascii=False)

            # 4. route_metrics.json
            for zone in metrics_output:
                m = metrics_output[zone]
                if m.get("start_stop") in rename_map:
                    m["start_stop"] = rename_map[m["start_stop"]]
                for seg in m.get("segments", []):
                    if seg.get("from") in rename_map:
                        seg["from"] = rename_map[seg["from"]]
                    if seg.get("to") in rename_map:
                        seg["to"] = rename_map[seg["to"]]
            with open("route_metrics.json", "w", encoding="utf-8") as f:
                json.dump(metrics_output, f, indent=4, ensure_ascii=False)

            print("   ✅ 所有文件已同步重编号")
        else:
            print("\n🔢 站点编号已与运行顺序一致，无需重命名。")

    print("\n" + "-" * 56)
    print(f"📊 三车合计: {round(grand_seconds / 60, 1)} 分钟 / {round(grand_meters / 1000, 2)} km")
    print("✅ 全部路线已优化完成")
    print("💾 已写入 bus_routes.json (前端渲染) 与 route_metrics.json (用时/距离对比明细)")


if __name__ == "__main__":
    main()
