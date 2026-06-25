import os as _os
# 数据文件统一存放于项目根的 data/ 目录；切到该目录使所有裸文件名读写都落到 data/
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data"))
import json
from collections import Counter

# 1. 读取已经分配好路线的学生数据
with open('clustered_students.json', 'r', encoding='utf-8') as f:
    students = json.load(f)

# 2. 仅过滤出西区 (Zone West) 的学生
west_students = [s for s in students if s['approx_zone'] == 'Zone West']

# 3. 统计每个站点 (route_id) 分配到了多少名学生
stop_counts = Counter([s['route_id'] for s in west_students])

print("📊 === 西区 (Zone West) 站点人数审计报告 ===")
for stop_id, count in stop_counts.most_common():
    print(f"站点 {stop_id} : 负责接送 {count} 名学生")
print("=============================================")