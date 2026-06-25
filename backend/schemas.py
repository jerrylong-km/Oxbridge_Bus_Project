# schemas.py
from pydantic import BaseModel, EmailStr

class SchoolRegister(BaseModel):
    school_name: str
    address: str
    latitude: float
    longitude: float
    username: str
    email: EmailStr
    password: str