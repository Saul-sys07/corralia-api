from pydantic import BaseModel


class LoginRequest(BaseModel):
    pin: str
    lat: float | None = None
    lng: float | None = None
