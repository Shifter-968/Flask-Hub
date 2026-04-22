class Config:
    SQLALCHEMY_DATABASE_URI = "postgresql://postgres:root@localhost:5432/smart_hub"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "dev_secret"
