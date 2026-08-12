from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)  # login password (separate from Gmail app password)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    gmail_accounts = db.relationship("GmailAccount", backref="user", lazy=True, cascade="all, delete-orphan")
    apify_tokens = db.relationship("ApifyToken", backref="user", lazy=True, cascade="all, delete-orphan")

class GmailAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    encrypted_app_password = db.Column(db.Text, nullable=False)  # Fernet-encrypted
    is_default = db.Column(db.Boolean, default=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

class ApifyToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    encrypted_token = db.Column(db.Text, nullable=False)  # Fernet-encrypted
    is_default = db.Column(db.Boolean, default=False)
    token_type = db.Column(db.String(50), nullable=True, default="maps")  # "maps" or "contact"
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
