# create_superadmin.py — 创建超级管理员账户
import models
from database import SessionLocal, engine
from auth_utils import get_password_hash

# 确保表存在
models.Base.metadata.create_all(bind=engine)


def create_superadmin():
    db = SessionLocal()

    # 1. 检查是否已存在 admin 账号
    existing = db.query(models.User).filter(models.User.username == "admin").first()
    if existing:
        print("⚠️ 超级管理员 'admin' 已经存在，无需重复创建！")
        db.close()
        return

    # 2. 对密码进行 bcrypt 哈希加密
    hashed_pwd = get_password_hash("admin123")

    # 3. 创建 SuperAdmin 用户（不绑定任何学校）
    admin_user = models.User(
        username="admin",
        email="admin@oxbridge.local",
        password_hash=hashed_pwd,
        role="SuperAdmin",
        school_id=None,
    )
    db.add(admin_user)
    db.commit()
    db.close()

    print("✅ 成功！超级管理员账号创建完毕。")
    print("👉 账号: admin")
    print("👉 密码: admin123")


if __name__ == "__main__":
    create_superadmin()
