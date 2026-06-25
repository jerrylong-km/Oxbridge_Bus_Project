import os as _os
# 数据文件统一存放于项目根的 data/ 目录；切到该目录使所有裸文件名读写都落到 data/
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data"))
import json
import pandas as pd
from sklearn.cluster import KMeans

# 1. 读取我们之前生成的虚拟学生数据
input_file = 'virtual_students.json'
with open(input_file, 'r', encoding='utf-8') as f:
    students = json.load(f)

# 将数据转换为 pandas DataFrame 方便处理
df = pd.DataFrame(students)

# 2. 提取经纬度特征用于聚类
# 这里的 X 包含了所有学生的 [纬度, 经度] 坐标
X = df[['lat', 'lng']].values

# 3. 初始化并运行 K-Means 算法
# n_clusters=3 代表我们要划分出 3 条校车路线
# random_state=42 是为了保证每次运行结果一致，方便测试
kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
df['route_id'] = kmeans.fit_predict(X)

# 4. 为不同的路线分配不同的颜色，以便在前端地图上展示
color_map = {
    0: "blue",   # 路线 0 为蓝色
    1: "green",  # 路线 1 为绿色
    2: "orange"  # 路线 2 为橙色
}
df['marker_color'] = df['route_id'].map(color_map)

# 5. 将聚类后的结果保存为新的 JSON 文件
output_file = 'clustered_students.json'
# 将 DataFrame 转回字典列表格式并保存
clustered_data = df.to_dict(orient='records')

with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(clustered_data, f, indent=4)

print(f"算法执行完毕！已成功将学生划分为 3 条路线，结果保存在 {output_file} 中。")