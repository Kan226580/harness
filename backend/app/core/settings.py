from pathlib import Path
from typing import Literal

from pydantic import BaseModel, SecretStr, Field, computed_field, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根路径
BASE_DIR = Path(__file__).resolve().parents[3]

# 环境名称
EnvName = Literal["dev", "test", "prod"]


class DbSettings(BaseModel):
    """PostgreSQL settings"""
    model_config = ConfigDict(extra="forbid")

    host: str = Field(..., min_length=1, description="数据库主机")
    port: int = Field(default=5432, ge=1, le=65535, description="数据库端口")
    username: str = Field(..., min_length=1, description="数据库用户")
    hashed_password: SecretStr = Field(..., min_length=1, description="数据库密码")
    name: str = Field(..., min_length=1, description="数据库名")
    driver: str = Field(default="postgresql+asyncpg", description="数据库驱动")

    @computed_field
    @property
    def url(self) -> str:
        pwd = self.hashed_password.get_secret_value()
        return (f"{self.driver}://"
                f"{self.username}:{pwd}"
                f"@{self.host}:{self.port}/{self.name}")


class RedisSettings(BaseModel):
    """Redis settings"""
    model_config = ConfigDict(extra="forbid")

    host: str = Field(..., min_length=1, description="redis主机")
    port: int = Field(default=6379, ge=1, le=65535, description="redis端口")
    db: int = Field(default=0, ge=0, description="redis数据库")
    hashed_password: SecretStr = Field(..., description="redis密码")

    @computed_field
    @property
    def url(self) -> str:
        pwd = self.hashed_password.get_secret_value()
        return f"redis://:{pwd}@{self.host}:{self.port}/{self.db}"


class Settings(BaseSettings):
    """应用配置根模型"""
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",  # REDIS__PORT -> redis.port
        extra="forbid",
        case_sensitive=False,
    )

    env: EnvName = "prod"
    db: DbSettings = Field(default_factory=DbSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)


settings = Settings()

if __name__ == '__main__':
    print(BASE_DIR)
