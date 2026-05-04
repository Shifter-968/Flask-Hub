import os
import re
import uuid
import hashlib
import smtplib
import base64
import difflib
import json as std_json
from datetime import datetime, timedelta
from urllib import request as urllib_request, error as urllib_error, parse as urllib_parse
from email.message import EmailMessage
from itsdangerous import URLSafeSerializer, BadSignature
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import (
    Flask, render_template, url_for, request, redirect,
    session, flash, jsonify, json, current_app,
)
from supabase import create_client
from dotenv import load_dotenv

try:
    import httpx as _httpx
    _httpx_available = True
except ImportError:
    _httpx = None
    _httpx_available = False

try:
    from openai import OpenAI as _OpenAIClient
    from openai import APIConnectionError as _OpenAIConnectionError
    from openai import AuthenticationError as _OpenAIAuthenticationError
    from openai import RateLimitError as _OpenAIRateLimitError
    _openai_available = True
except ImportError:
    _openai_available = False
    _OpenAIConnectionError = Exception
    _OpenAIAuthenticationError = Exception
    _OpenAIRateLimitError = Exception

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallbacksecret")

SIGNED_ID_TOKEN_SALT = "signed-id-v1"
SCHOOL_LINK_TOKEN_SALT = "school-link-v1"
MEETING_PASSWORD_TOKEN_SALT = "meeting-password-v1"

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
INSTRUCTOR_AI_PREMIUM_ENABLED = (
    os.getenv("INSTRUCTOR_AI_PREMIUM_ENABLED", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)
try:
    STUDY_AI_MEDIA_DAILY_LIMIT = int((os.getenv("STUDY_AI_MEDIA_DAILY_LIMIT") or "3").strip())
except (TypeError, ValueError):
    STUDY_AI_MEDIA_DAILY_LIMIT = 3
STUDY_AI_MEDIA_DAILY_LIMIT = max(0, STUDY_AI_MEDIA_DAILY_LIMIT)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads", "classroom")
APPLY_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads", "applications")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(APPLY_UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "pdf", "doc", "docx", "ppt",
    "pptx", "xls", "xlsx", "zip", "rar", "mp4", "mp3", "txt",
}
SHOW_SCHOOL_ADMIN_ROLE = os.getenv("SHOW_SCHOOL_ADMIN_ROLE", "false").strip().lower() == "true"

SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
SMTP_PORT = int((os.getenv("SMTP_PORT") or "587").strip() or "587")
SMTP_USERNAME = (os.getenv("SMTP_USERNAME") or "").strip()
SMTP_PASSWORD = (os.getenv("SMTP_PASSWORD") or "").strip()
SMTP_FROM_EMAIL = (os.getenv("SMTP_FROM_EMAIL") or "").strip()
SMTP_USE_TLS = (os.getenv("SMTP_USE_TLS") or "true").strip().lower() == "true"

SMS_PROVIDER = (os.getenv("SMS_PROVIDER") or "none").strip().lower()
SMS_FROM_NUMBER = (os.getenv("SMS_FROM_NUMBER") or "").strip()
TWILIO_ACCOUNT_SID = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
TWILIO_AUTH_TOKEN = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
SMS_WEBHOOK_URL = (os.getenv("SMS_WEBHOOK_URL") or "").strip()
SMS_WEBHOOK_TOKEN = (os.getenv("SMS_WEBHOOK_TOKEN") or "").strip()
GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()

try:
    AUTH_CODE_TTL_MINUTES = int((os.getenv("AUTH_CODE_TTL_MINUTES") or "15").strip())
except (TypeError, ValueError):
    AUTH_CODE_TTL_MINUTES = 15
AUTH_CODE_TTL_MINUTES = max(5, AUTH_CODE_TTL_MINUTES)
