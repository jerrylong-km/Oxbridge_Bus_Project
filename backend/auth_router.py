# auth_router.py — 登录认证路由
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

import models
from auth_utils import verify_password, create_access_token
from database import get_db

router = APIRouter(prefix="/api", tags=["认证"])


# 登录响应模型
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    school_id: Optional[int] = None
    username: str


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    登录接口 — 校验流程：
    1. 用户名是否存在
    2. 密码是否正确
    3. 如果是 SchoolAdmin，其学校是否已通过审核
    """
    # 1. 查找用户
    user = db.query(models.User).filter(
        models.User.username == form_data.username
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. 验证密码
    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. SchoolAdmin 需要学校已通过审核
    if user.role == "SchoolAdmin":
        school = db.query(models.School).filter(
            models.School.school_id == user.school_id
        ).first()
        if not school or school.approval_status != "已通过":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您的学校尚未通过审核，请等待超级管理员批准后再登录",
            )

    # 4. 签发 JWT Token
    token_data = {
        "sub": str(user.user_id),
        "username": user.username,
        "role": user.role,
        "school_id": user.school_id,
    }
    access_token = create_access_token(token_data)

    return TokenResponse(
        access_token=access_token,
        role=user.role,
        school_id=user.school_id,
        username=user.username,
    )
