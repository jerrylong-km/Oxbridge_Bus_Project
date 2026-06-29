# optimization.py — 校车线路优化算法模块
# 从 assign_students.py / find_optimal_stops.py / calculate_routes.py 提取核心算法
# 供 FastAPI 端点调用，不依赖文件系统 I/O

import math
import itertools
import numpy as np
import requests

# ============================================================================
#  常量
# ============================================================================
LAT_REF = 26.7
LNG_SCALE = math.cos(math.radians(LAT_REF))  # 经度收缩系数 (~0.893)
RANDOM_SEED = 42
MAX_ITER = 100

# --- 站点驾车时间约束（用于 find_optimal_stops 裂变逻辑） ---
MAX_DRIVE_MINUTES = 15      # 学生到站点的最大驾车时间（分钟）
DRIVE_SPEED_KMH = 30        # 上午7点住宅区保守平均车速（km/h）
DRIVE_DETOUR_FACTOR = 1.3   # 道路绕行系数（直线→实际路程）
# 换算：最大直线距离(km) = MAX_DRIVE_MINUTES/60 * DRIVE_SPEED_KMH / DRIVE_DETOUR_FACTOR
_MAX_RADIUS_KM = MAX_DRIVE_MINUTES / 60.0 * DRIVE_SPEED_KMH / DRIVE_DETOUR_FACTOR  # ≈5.77 km
# 转为纬度收缩后的坐标系距离（1° ≈ 111 km）
MAX_RADIUS_DEG = _MAX_RADIUS_KM / 111.0  # ≈0.0347°

# ============================================================================
#  工具函数
# ============================================================================

def to_xy(lat, lng):
    """经纬度 → 做了纬度收缩的平面坐标"""
    return np.array([lat, lng * LNG_SCALE], dtype=float)


def coords_to_xy(coords):
    """批量转换 [(lat, lng), ...] → numpy array (n, 2)"""
    return np.array([[lat, lng * LNG_SCALE] for lat, lng in coords], dtype=float)


# ============================================================================
#  1. 运力均衡 K-Means 分区 (from assign_students.py)
# ============================================================================

def balanced_capacitated_assign(pts, centroids, capacity, target, balance_weight=2.5):
    """带容量上限 + 均衡惩罚的分配"""
    n = len(pts)
    k = len(centroids)
    d = np.linalg.norm(pts[:, None, :] - centroids[None, :, :], axis=2)

    labels = np.full(n, -1, dtype=int)
    load = np.zeros(k, dtype=int)

    nearest_dist = d.min(axis=1)
    order = np.argsort(-nearest_dist)

    for i in order:
        penalty = balance_weight * (load / max(target, 1)) * nearest_dist[i]
        cost = d[i] + penalty
        cost[load >= capacity] = np.inf
        choice = int(np.argmin(cost))
        labels[i] = choice
        load[choice] += 1

    return labels


def balanced_kmeans(coords, num_buses, bus_capacity, balance_weight=2.5):
    """运力均衡 K-Means 聚类分区

    Args:
        coords: [(lat, lng), ...] 学生坐标列表
        num_buses: 校车数量（= 分区数）
        bus_capacity: 每辆车座位上限
        balance_weight: 均衡力度（越大越均匀）

    Returns:
        labels: numpy array, 每个学生的分区标签 (0-based)
        centroids: numpy array (k, 2), 各区质心坐标（已收缩）
    """
    pts = coords_to_xy(coords)
    n = len(pts)
    k = num_buses
    target = n / k

    rng = np.random.default_rng(RANDOM_SEED)

    # K-Means++ 初始化
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
        else:
            centroids.append(pts[rng.choice(n, p=prob / s)])
    centroids = np.array(centroids)

    labels = None
    for _ in range(MAX_ITER):
        new_labels = balanced_capacitated_assign(pts, centroids, bus_capacity, target, balance_weight)
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


def split_cluster(pts, labels, cluster_id):
    """将指定簇拆分为两个子簇

    Args:
        pts: 全部学生坐标 (n, 2) numpy array（已做纬度收缩）
        labels: 全部学生的当前簇标签 (n,)
        cluster_id: 要拆分的簇编号

    Returns:
        new_labels: 更新后的标签数组（原 cluster_id 拆为 cluster_id 和 new_id）
        new_id: 新簇的编号
    """
    mask = labels == cluster_id
    sub_pts = pts[mask]

    # 对该簇内学生做 k=2 聚类
    sub_labels, _ = kmeans_cluster(sub_pts, 2)

    # 分配新簇编号
    new_id = int(labels.max()) + 1
    new_labels = labels.copy()
    indices = np.where(mask)[0]
    for i, idx in enumerate(indices):
        if sub_labels[i] == 1:
            new_labels[idx] = new_id

    return new_labels, new_id


# ============================================================================
#  2. 最优站点数选择 + 定位 (from find_optimal_stops.py)
# ============================================================================

def kmeans_cluster(pts, k, seed=RANDOM_SEED, max_iter=100):
    """纯 numpy K-Means (k-means++ 初始化)"""
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
    """纯 numpy 轮廓系数"""
    n = len(pts)
    unique = np.unique(labels)
    if len(unique) < 2:
        return -1.0
    D = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=2)
    sil = np.zeros(n)
    for i in range(n):
        same = labels == labels[i]
        same[i] = False
        if same.sum() == 0:
            sil[i] = 0.0
            continue
        a = D[i, same].mean()
        b = np.inf
        for c in unique:
            if c == labels[i]:
                continue
            mask = labels == c
            b = min(b, D[i, mask].mean())
        sil[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(sil.mean())


def find_optimal_stops(zone_coords, max_stops):
    """计算一个区内的最优站点位置

    算法：
      1. 用轮廓系数选出初始最优 k
      2. 检查每个簇内最远学生到质心的距离是否超过 MAX_RADIUS_DEG
      3. 对超标簇进行裂变（拆成2个），直到所有学生满足约束或达到 max_stops 上限

    Args:
        zone_coords: [(lat, lng), ...] 该区学生坐标
        max_stops: 最大站点数上限

    Returns:
        stops: [{"lat": float, "lng": float, "student_count": int}, ...]
        assignments: [stop_index, ...] 每个学生分配的站点索引
    """
    pts = coords_to_xy(zone_coords)
    n = len(pts)

    if n <= 2:
        # 学生太少，整区一个站
        centroid = pts.mean(axis=0)
        lat = float(centroid[0])
        lng = float(centroid[1] / LNG_SCALE)
        return [{"lat": lat, "lng": lng, "student_count": n}], [0] * n

    # --- 阶段1：用轮廓系数选最优 k (2 ~ max_stops) ---
    upper = min(max_stops, n - 1)
    best_k, best_score = 1, -1.0

    for k in range(2, upper + 1):
        labels, _ = kmeans_cluster(pts, k)
        if len(np.unique(labels)) < 2:
            continue
        score = silhouette_score(pts, labels)
        if score > best_score:
            best_score, best_k = score, k

    # 用最优 k 做初始聚类
    labels, centroids = kmeans_cluster(pts, best_k)

    # --- 阶段2：超时裂变，确保每个学生驾车≤10分钟 ---
    current_k = best_k
    while current_k < max_stops:
        # 计算每个簇内最远学生到质心的距离
        worst_cluster = -1
        worst_dist = 0.0

        for j in range(int(labels.max()) + 1):
            mask = labels == j
            if not np.any(mask):
                continue
            cluster_pts = pts[mask]
            centroid = cluster_pts.mean(axis=0)
            dists = np.linalg.norm(cluster_pts - centroid, axis=1)
            max_dist = float(dists.max())
            if max_dist > MAX_RADIUS_DEG and max_dist > worst_dist:
                worst_dist = max_dist
                worst_cluster = j

        if worst_cluster == -1:
            # 所有簇都满足约束，停止裂变
            break

        # 裂变最差的簇
        labels, _ = split_cluster(pts, labels, worst_cluster)
        current_k += 1

    # --- 阶段3：重新计算质心，构建返回结果 ---
    unique_labels = np.unique(labels)
    # 重新编号为连续 0, 1, 2, ...
    label_map = {old: new for new, old in enumerate(unique_labels)}
    labels = np.array([label_map[l] for l in labels])
    final_k = len(unique_labels)

    centroids = np.array([
        pts[labels == j].mean(axis=0) for j in range(final_k)
    ])
    counts = np.bincount(labels, minlength=final_k)

    stops = []
    for j in range(final_k):
        lat = float(centroids[j][0])
        lng = float(centroids[j][1] / LNG_SCALE)
        stops.append({"lat": lat, "lng": lng, "student_count": int(counts[j])})

    return stops, labels.tolist()


# ============================================================================
#  3. 路线求解 (from calculate_routes.py)
# ============================================================================

def build_simulated_matrices(points):
    """基于经纬度生成模拟行车时间(秒)+距离(米)矩阵"""
    n = len(points)
    cos_lat = math.cos(math.radians(LAT_REF))
    time_matrix = [[0] * n for _ in range(n)]
    dist_matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            dlat = points[i]["lat"] - points[j]["lat"]
            dlng = (points[i]["lng"] - points[j]["lng"]) * cos_lat
            dist_km = math.sqrt(dlat**2 + dlng**2) * 111.0
            road_km = dist_km * 1.3
            drive_seconds = int(road_km / 35.0 * 3600)
            time_matrix[i][j] = drive_seconds
            dist_matrix[i][j] = int(road_km * 1000)
    return time_matrix, dist_matrix


def fetch_distance_matrix(points, api_key, departure_time=None):
    """调用 Google Distance Matrix API 获取真实行车矩阵

    Args:
        points: [{"lat": float, "lng": float}, ...]
        api_key: Google Maps API Key
        departure_time: Unix 时间戳（整数），传入时启用路况感知路由

    Returns:
        (time_matrix[秒], dist_matrix[米])
    """
    if not api_key or not api_key.startswith("AIza"):
        return build_simulated_matrices(points)

    coords_str = "|".join([f"{p['lat']},{p['lng']}" for p in points])
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": coords_str,
        "destinations": coords_str,
        "mode": "driving",
        "key": api_key,
    }
    if departure_time:
        params["departure_time"] = departure_time
        params["traffic_model"] = "best_guess"

    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()

        if data.get("status") != "OK":
            return build_simulated_matrices(points)

        n = len(points)
        time_matrix = [[0] * n for _ in range(n)]
        dist_matrix = [[0] * n for _ in range(n)]

        for i in range(n):
            elements = data["rows"][i]["elements"]
            for j in range(n):
                if elements[j].get("status") == "OK":
                    el = elements[j]
                    # 有 departure_time 时使用含路况的时长，否则用基础时长
                    time_val = el.get("duration_in_traffic", el["duration"])["value"]
                    time_matrix[i][j] = time_val
                    dist_matrix[i][j] = el["distance"]["value"]
                else:
                    time_matrix[i][j] = 999999
                    dist_matrix[i][j] = 999999

        return time_matrix, dist_matrix
    except Exception:
        return build_simulated_matrices(points)


def solve_open_route(time_matrix):
    """固定终点为学校(索引0)的最短开放路径

    返回 (有序站点索引列表, 总秒数)
    """
    num_points = len(time_matrix)
    if num_points <= 1:
        return [], 0

    stop_indices = list(range(1, num_points))

    # 发车点 = 离学校最远的站
    start = max(stop_indices, key=lambda i: time_matrix[0][i])
    middle = [i for i in stop_indices if i != start]

    best_perm = None
    min_time = float("inf")

    for perm in itertools.permutations(middle):
        seq = [start, *perm]
        t = 0
        for i in range(len(seq) - 1):
            t += time_matrix[seq[i]][seq[i + 1]]
        t += time_matrix[seq[-1]][0]

        if t < min_time:
            min_time = t
            best_perm = seq

    return best_perm, min_time


# ============================================================================
#  4. Google Geocoding
# ============================================================================

def geocode_address(address, api_key):
    """调用 Google Geocoding API 获取地址坐标

    Args:
        address: 英文地址字符串
        api_key: Google Maps API Key

    Returns:
        {"lat": float, "lng": float} 或 None（失败时）
    """
    if not api_key or not api_key.startswith("AIza"):
        return None

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": api_key}

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return {"lat": loc["lat"], "lng": loc["lng"]}
    except Exception:
        pass
    return None
