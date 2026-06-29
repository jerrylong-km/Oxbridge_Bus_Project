import os
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
from dotenv import load_dotenv

# 从与本文件同目录（backend/）的 .env 加载环境变量，不依赖启动时的工作目录
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# SECRET_KEY 必须通过环境变量提供，绝不硬编码进源码（防止密钥随代码泄露）
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "环境变量 SECRET_KEY 未设置。请在项目根目录的 .env 文件中配置 "
        "SECRET_KEY（可参考 .env.example）。"
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# 同时支持 bcrypt（新账号默认）与 sha256_crypt（兼容历史账号，如早期注册接口生成的哈希）。
# deprecated="auto" 会把非首选算法标记为过时，verify_password 仍能正确校验两种格式。
pwd_context = CryptContext(schemes=["bcrypt", "sha256_crypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)