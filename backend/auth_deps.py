# auth_deps.py — JWT 鉴权依赖项（供路由保护使用）
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

import models
from auth_utils import SECRET_KEY, ALGORITHM
from database import get_db

# OAuth2 方案声明：前端从 /api/login 获取 token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """
    解析 JWT，返回当前登录用户对象。
    任何需要登录才能访问的接口都可以用 Depends(get_current_user)。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已过期或无效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(
        models.User.user_id == int(user_id)
    ).first()

    if user is None:
        raise credentials_exception

    return user


def require_role(required_role: str):
    """
    角色校验工厂 — 生成一个依赖项，要求用户必须具备指定角色。
    用法：Depends(require_role("SuperAdmin"))
    """
    def role_checker(current_user: models.User = Depends(get_current_user)):
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足：需要 {required_role} 角色",
            )
        return current_user
    return role_checker
