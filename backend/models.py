from sqlalchemy import Column, Integer, String, Float, ForeignKey, Text, DateTime
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class School(Base):
    __tablename__ = "schools"
    
    school_id = Column(Integer, primary_key=True, index=True) 
    school_name = Column(String, index=True) # 学校名称
    address = Column(String) # 学校地址
    
    # 【新增】学校的经纬度坐标，用于作为校车路线的起点/终点
    latitude = Column(Float, nullable=True)  
    longitude = Column(Float, nullable=True) 
    
    approval_status = Column(String, default="待审核") # 状态：待审核、已通过、已拒绝
    
    # 建立与用户、学生、路线的关联 (一对多关系)
    users = relationship("User", back_populates="school")
    students = relationship("Student", back_populates="school") # 【新增】关联学生表
    routes = relationship("Route", back_populates="school")

class User(Base):
    __tablename__ = "users"
    
    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String) # 密码哈希值
    role = Column(String) # 角色：SuperAdmin 或 SchoolAdmin
    avatar = Column(Text, nullable=True)  # 头像（base64 data URL）
    
    # 外键关联
    school_id = Column(Integer, ForeignKey("schools.school_id"), nullable=True) 
    
    school = relationship("School", back_populates="users")

# 【全新建表】学生信息表
class Student(Base):
    __tablename__ = "students"

    student_id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True) # 学生姓名
    grade = Column(String) # 年级
    address = Column(String) # 家庭地址

    # 学生的家庭经纬度坐标（导入时为空，Geocoding 后填入）
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # 优化分区标签，如 "Zone_1"
    zone = Column(String, nullable=True)
    # 分配到的优化站点 ID
    assigned_stop_id = Column(Integer, ForeignKey("optimized_stops.id"), nullable=True)

    # 【核心安全机制】强绑定 school_id，实现多租户数据隔离
    school_id = Column(Integer, ForeignKey("schools.school_id"), nullable=False)

    school = relationship("School", back_populates="students")
    assigned_stop = relationship("OptimizedStop", back_populates="students")

class Route(Base):
    __tablename__ = "routes"

    route_id = Column(Integer, primary_key=True, index=True)
    route_data = Column(Text) # 存储计算后的 JSON 路线数据

    school_id = Column(Integer, ForeignKey("schools.school_id"), nullable=False)

    school = relationship("School", back_populates="routes")

# 【现有校车线路】SchoolAdmin 手工录入的线路与站点（与算法生成的 Route 表分开）
class BusLine(Base):
    __tablename__ = "bus_lines"

    line_id = Column(Integer, primary_key=True, index=True)
    line_name = Column(String, nullable=False)  # 线路名称

    # 到校/发车时间（用于耗时计算）
    arrival_school_morning = Column(String, nullable=True)     # 早上到校时间，如 "08:10"
    departure_school_afternoon = Column(String, nullable=True) # 下午从学校发车时间，如 "15:20"

    # 多租户隔离：每条线路强绑定所属学校
    school_id = Column(Integer, ForeignKey("schools.school_id"), nullable=False)

    school = relationship("School")
    # 删除线路时级联删除其下站点
    stops = relationship(
        "BusStop",
        back_populates="line",
        cascade="all, delete-orphan",
        order_by="BusStop.sequence",
    )

class BusStop(Base):
    __tablename__ = "bus_stops"

    stop_id = Column(Integer, primary_key=True, index=True)
    line_id = Column(Integer, ForeignKey("bus_lines.line_id"), nullable=False)

    stop_name = Column(String, nullable=False)        # 站点名称
    address = Column(String)                          # 站点地址
    latitude = Column(Float, nullable=True)           # 地址补全自动抓取
    longitude = Column(Float, nullable=True)
    arrival_morning = Column(String, nullable=True)   # 早上到站时间，如 "07:30"
    arrival_afternoon = Column(String, nullable=True) # 下午到站时间，如 "16:30"
    sequence = Column(Integer, default=0)             # 线路内站点顺序

    line = relationship("BusLine", back_populates="stops")


# 【优化校车线路】算法生成的站点
class OptimizedStop(Base):
    __tablename__ = "optimized_stops"

    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("schools.school_id"), nullable=False)
    zone = Column(String, nullable=False)          # 所属分区，如 "Zone_1"
    stop_name = Column(String, nullable=True)      # 站点名称（可由管理员命名）
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    student_count = Column(Integer, default=0)
    sequence = Column(Integer, default=0)          # 路线内站点顺序

    school = relationship("School")
    students = relationship("Student", back_populates="assigned_stop")


# 【优化校车线路】最终生成的路线结果
class OptimizedRoute(Base):
    __tablename__ = "optimized_routes"

    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("schools.school_id"), nullable=False)
    route_data = Column(Text)       # 路线详情 JSON（各区有序站点 + polyline）
    metrics_data = Column(Text)     # 里程/耗时指标 JSON
    created_at = Column(DateTime, default=datetime.utcnow)

    school = relationship("School")