import os
import pymysql
import json
import time
import base64
import hashlib
import hmac
import sqlite3
import threading
import re
import zipfile
import urllib.request
import statistics
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

app = FastAPI(title="Zhiku Device Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASS', ''),
    'database': os.getenv('DB_NAME', 'zhiku_db'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

SOURCE_DB_CONFIG = {
    'host': os.getenv('SOURCE_DB_HOST', ''),
    'port': int(os.getenv('SOURCE_DB_PORT', '3306')),
    'user': os.getenv('SOURCE_DB_USER', ''),
    'password': os.getenv('SOURCE_DB_PASS', ''),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'connect_timeout': 8,
    'read_timeout': 30,
    'write_timeout': 30,
}

ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', 'change_me_admin_token')
MAX_DEVICE_LOGS = int(os.getenv('MAX_DEVICE_LOGS', '5000'))
INLINE_LOG_LIMIT = int(os.getenv('INLINE_LOG_LIMIT', '1000'))
CACHE_TTL_SECONDS = int(os.getenv('CACHE_TTL_SECONDS', '300'))
DEVICE_LOOKUP_CACHE_TTL_SECONDS = int(os.getenv('DEVICE_LOOKUP_CACHE_TTL_SECONDS', '600'))
VERSION_STATS_CACHE_TTL_SECONDS = int(os.getenv('VERSION_STATS_CACHE_TTL_SECONDS', '600'))
RECIPE_SEARCH_CACHE_TTL_SECONDS = int(os.getenv('RECIPE_SEARCH_CACHE_TTL_SECONDS', '21600'))
MAX_RECIPE_SEARCH_DAYS = int(os.getenv('MAX_RECIPE_SEARCH_DAYS', '180'))
MAX_RECIPE_SEARCH_LIMIT = int(os.getenv('MAX_RECIPE_SEARCH_LIMIT', '300'))
CACHE_DIR = Path(os.getenv('CACHE_DIR', '/app/cache'))
OIL_THERMAL_DATA_DIR = Path(os.getenv('OIL_THERMAL_DATA_DIR', '/app/data'))
FAULT_CODE_DATA_PATH = OIL_THERMAL_DATA_DIR / 'fault_codes_latest.json'
MAX_LOG_ANALYSIS_DOWNLOAD_MB = int(os.getenv('MAX_LOG_ANALYSIS_DOWNLOAD_MB', '80'))
AUTH_SECRET = os.getenv('AUTH_SECRET', ADMIN_TOKEN)
SESSION_TTL_SECONDS = int(os.getenv('SESSION_TTL_SECONDS', str(7 * 24 * 3600)))
REPORT_CACHE = {}
DEVICE_LOOKUP_CACHE = {}
VERSION_STATS_CACHE = {}
LOG_ANALYSIS_VERSION = 2
CACHE_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_DB_PATH = CACHE_DIR / 'zhiku_audit.sqlite3'
AUDIT_LOCK = threading.Lock()

LOG_KIND_DEFS = {
    'oildrum_board': {
        'label': '猪油桶板日志',
        'purpose': '油温、油管温度、投料电机、油桶加热 PWM、加热目标和功率限制。',
        'key_patterns': ['dev status', 'pump hall start', 'pump hall finish', 'read power', 'oil heat enable', 'pipe heat enable', 'read sw v'],
    },
    'temperature': {
        'label': '温度采样日志',
        'purpose': '主控温度采样，用于辅助看整机温度变化。',
        'key_patterns': ['temperature triplet'],
    },
    'main_board': {
        'label': '主控板日志',
        'purpose': '主控动作、加油/加水/翻锅/温控等过程日志。',
        'key_patterns': ['add oil', 'add water', 'lean', 'tempctr', 'fail'],
    },
    'mcu_debug': {
        'label': 'MCU 调试日志',
        'purpose': 'MCU 通讯、温控、错误码查询、超时等底层调试信息。',
        'key_patterns': ['send to mcu', 'heaterGetErrCode', 'timeout', 'error'],
    },
    'android_app': {
        'label': '安卓应用日志',
        'purpose': 'App 指令、资源动作、网络、数据采集和业务流程。',
        'key_patterns': ['sendMsg', 'readResult', 'SAUCE_STARCH', 'SAUCE_NEW', 'DataCollectManager'],
    },
    'other': {
        'label': '其他文件',
        'purpose': '暂未建立专用解析器的日志或附件。',
        'key_patterns': [],
    },
}

OILDRUM_FIELD_SPECS = [
    {
        'category': '状态数据',
        'pattern': 'dev status',
        'fields': [
            '时间',
            '油温度 * 10',
            '油管温度 * 10',
            '预留',
            '电机速度 RPM',
            '油桶加热 PWM 占空比',
        ],
        'example': '[26.05.10 17:36:22] dev status 506 607 0 468 2.80',
        'meaning': '示例表示油温 50.6℃、油管温度 60.7℃、投料电机 468RPM、PWM 占空比 2.8%。',
    },
    {
        'category': '电机控制开始',
        'pattern': 'pump hall start',
        'fields': ['时间', '霍尔数量，负数投油，正数反抽', '控制电机占空比'],
        'example': '[26.05.10 17:39:51] pump hall start -2476 100',
        'meaning': '示例表示开始投油，目标霍尔数 2476，电机占空比 100%。',
    },
    {
        'category': '电机控制完成',
        'pattern': 'pump hall finish',
        'fields': ['时间', '实际霍尔数量', '本次电机控制实际时间 ms', '霍尔缺相检测，1 异常，0 正常'],
        'example': '[26.05.10 17:40:05] pump hall finish 2477,time 14738,state 1',
        'meaning': '示例表示电机工作 14.738 秒，霍尔缺相检测异常。',
    },
    {
        'category': '功率限制',
        'pattern': 'read power',
        'fields': ['时间', '功率限制状态，1 有限制，0 无限制', '预留', '预留'],
        'example': '[26.05.10 17:40:36] read power 1 0 0',
        'meaning': '示例表示当前存在加热功率限制。',
    },
    {
        'category': '油桶加热目标',
        'pattern': 'oil heat enable',
        'fields': ['时间', '加热状态，1 使能，0 不使能', '目标温度'],
        'example': '[26.04.08 18:19:35] oil heat enable 1 70',
        'meaning': '示例表示使能猪油桶加热，目标温度 70℃。',
    },
    {
        'category': '油管加热目标',
        'pattern': 'pipe heat enable',
        'fields': ['时间', '加热状态，1 使能，0 不使能', '目标温度'],
        'example': '[26.04.08 18:19:37] pipe heat enable 1 70',
        'meaning': '示例表示使能油管加热，目标温度 70℃。',
    },
    {
        'category': '软件版本',
        'pattern': 'read sw v',
        'fields': ['时间', '版本号高位', '版本号中位', '版本号低位'],
        'example': '[26.04.08 18:26:57] read sw v 1 0 11',
        'meaning': '示例表示猪油桶板软件版本 1.0.11。',
    },
]

def get_conn():
    return pymysql.connect(**DB_CONFIG)

def get_source_conn(database=None):
    if not SOURCE_DB_CONFIG['host']:
        raise HTTPException(status_code=500, detail="Source database is not configured")
    config = dict(SOURCE_DB_CONFIG)
    if database:
        config['database'] = database
    return pymysql.connect(**config)

class DeviceReport(BaseModel):
    info: dict
    stats: dict
    logs: list
    intervals: list
    recipes: list
    faults: list
    maintenance: list

class LoginRequest(BaseModel):
    username: str
    password: str

class ProfileUpdate(BaseModel):
    display_name: str = ''

class RecipeTopJobRequest(BaseModel):
    start_date: str = ''
    end_date: str = ''
    top_n: int = 500
    sort_by: str = 'cooking_count'
    recipe_keyword: str = ''
    customer_keyword: str = ''
    sn: str = ''
    region: str = ''
    category: str = ''
    resource_type: str = ''
    stat_object: str = 'all'
    refresh: bool = False

def parse_users():
    raw = os.getenv('ZHIKU_USERS', f"admin:{ADMIN_TOKEN}")
    users = {}
    for item in raw.split(','):
        if ':' not in item:
            continue
        parts = item.split(':')
        username = parts[0].strip()
        password = parts[1].strip() if len(parts) > 1 else ''
        role = parts[2].strip() if len(parts) > 2 else ('admin' if username == 'admin' else 'user')
        username = username.strip()
        if username:
            users[username] = {'password': password, 'role': role}
    return users

ZHIKU_USERS = parse_users()

def audit_conn():
    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_audit_db():
    with AUDIT_LOCK, audit_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                username TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'user',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                sn TEXT,
                detail TEXT,
                ip TEXT,
                user_agent TEXT,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_events(username, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action_time ON audit_events(action, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_sn_time ON audit_events(sn, created_at)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analytics_query_jobs (
                job_id TEXT PRIMARY KEY,
                query_type TEXT NOT NULL,
                params_json TEXT NOT NULL,
                params_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT '',
                progress INTEGER NOT NULL DEFAULT 0,
                created_by TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                started_at INTEGER,
                finished_at INTEGER,
                cache_expires_at INTEGER,
                result_path TEXT,
                xlsx_path TEXT,
                error_message TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_hash ON analytics_query_jobs(query_type, params_hash, status, cache_expires_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_created ON analytics_query_jobs(created_at)")
        now = int(time.time())
        for username, meta in ZHIKU_USERS.items():
            conn.execute(
                "INSERT OR IGNORE INTO user_profiles(username, role, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (username, meta.get('role', 'user'), now, now),
            )
            conn.execute(
                "UPDATE user_profiles SET role = ?, updated_at = CASE WHEN role != ? THEN ? ELSE updated_at END WHERE username = ?",
                (meta.get('role', 'user'), meta.get('role', 'user'), now, username),
            )
        conn.commit()

init_audit_db()

def sign_token(username, expires_at):
    payload = f"{username}:{int(expires_at)}"
    signature = hmac.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()

def verify_token(token):
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        username, expires_at, signature = decoded.rsplit(':', 2)
        payload = f"{username}:{expires_at}"
        expected = hmac.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(expires_at) < int(time.time()):
            return None
        if username not in ZHIKU_USERS:
            return None
        return username
    except Exception:
        return None

def require_auth(authorization: str = None, token: str = None):
    raw = token
    if authorization and authorization.lower().startswith('bearer '):
        raw = authorization.split(' ', 1)[1].strip()
    username = verify_token(raw or '')
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return username

def is_admin(username):
    return ZHIKU_USERS.get(username, {}).get('role') == 'admin'

def require_admin(authorization: str = None, token: str = None):
    username = require_auth(authorization=authorization, token=token)
    if not is_admin(username):
        raise HTTPException(status_code=403, detail="Admin only")
    return username

def row_to_dict(row):
    return dict(row) if row else None

def get_profile(username):
    with AUDIT_LOCK, audit_conn() as conn:
        row = conn.execute(
            "SELECT username, display_name, role, created_at, updated_at FROM user_profiles WHERE username = ?",
            (username,),
        ).fetchone()
    profile = row_to_dict(row) or {
        'username': username,
        'display_name': '',
        'role': ZHIKU_USERS.get(username, {}).get('role', 'user'),
        'created_at': int(time.time()),
        'updated_at': int(time.time()),
    }
    profile['profile_required'] = not bool(profile.get('display_name'))
    return profile

def update_profile(username, display_name):
    clean_name = (display_name or '').strip()[:40]
    now = int(time.time())
    with AUDIT_LOCK, audit_conn() as conn:
        conn.execute(
            "INSERT INTO user_profiles(username, display_name, role, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(username) DO UPDATE SET display_name = excluded.display_name, updated_at = excluded.updated_at",
            (username, clean_name, ZHIKU_USERS.get(username, {}).get('role', 'user'), now, now),
        )
        conn.commit()
    return get_profile(username)

def request_ip(request: Request = None):
    if not request or not request.client:
        return ''
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.client.host or ''

def log_event(username, action, request: Request = None, sn=None, detail=None):
    payload = json.dumps(detail or {}, ensure_ascii=False, default=str)
    user_agent = request.headers.get('user-agent', '')[:240] if request else ''
    now = int(time.time())
    with AUDIT_LOCK, audit_conn() as conn:
        conn.execute(
            "INSERT INTO audit_events(username, action, sn, detail, ip, user_agent, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (username, action, sn, payload, request_ip(request), user_agent, now),
        )
        conn.commit()

def audit_summary():
    now = int(time.time())
    day_ago = now - 86400
    week_ago = now - 7 * 86400
    with AUDIT_LOCK, audit_conn() as conn:
        users = [dict(row) for row in conn.execute("""
            SELECT p.username, p.display_name, p.role,
                   COALESCE(SUM(CASE WHEN e.action = 'login' THEN 1 ELSE 0 END), 0) AS login_count,
                   COALESCE(SUM(CASE WHEN e.action IN ('search', 'search_refresh') THEN 1 ELSE 0 END), 0) AS search_count,
                   COALESCE(SUM(CASE WHEN e.action IN ('recipe_search', 'recipe_search_refresh') THEN 1 ELSE 0 END), 0) AS recipe_search_count,
                   COALESCE(SUM(CASE WHEN e.action = 'export' THEN 1 ELSE 0 END), 0) AS export_count,
                   COALESCE(SUM(CASE WHEN e.action = 'recipe_search_export' THEN 1 ELSE 0 END), 0) AS recipe_export_count,
                   COALESCE(SUM(CASE WHEN e.action = 'log_download' THEN 1 ELSE 0 END), 0) AS log_download_count,
                   COALESCE(SUM(CASE WHEN e.action IN ('log_analysis_view', 'admin_log_analysis_view') THEN 1 ELSE 0 END), 0) AS log_analysis_count,
                   COALESCE(SUM(CASE WHEN e.created_at >= ? THEN 1 ELSE 0 END), 0) AS events_24h,
                   MAX(e.created_at) AS last_seen
            FROM user_profiles p
            LEFT JOIN audit_events e ON e.username = p.username
            GROUP BY p.username, p.display_name, p.role
            ORDER BY events_24h DESC, last_seen DESC
        """, (day_ago,))]
        recent_events = [dict(row) for row in conn.execute("""
            SELECT id, username, action, sn, detail, ip, user_agent, created_at
            FROM audit_events
            ORDER BY created_at DESC
            LIMIT 120
        """)]
        top_devices = [dict(row) for row in conn.execute("""
            SELECT sn, COUNT(*) AS hits, COUNT(DISTINCT username) AS user_count, MAX(created_at) AS last_seen
            FROM audit_events
            WHERE sn IS NOT NULL AND sn != ''
            GROUP BY sn
            ORDER BY hits DESC
            LIMIT 30
        """)]
        ip_summary = [dict(row) for row in conn.execute("""
            SELECT username, COUNT(DISTINCT ip) AS ip_count
            FROM audit_events
            WHERE created_at >= ? AND ip IS NOT NULL AND ip != ''
            GROUP BY username
            HAVING ip_count >= 4
            ORDER BY ip_count DESC
        """, (week_ago,))]
        recipe_keyword_events = [dict(row) for row in conn.execute("""
            SELECT detail, COUNT(*) AS hits, MAX(created_at) AS last_seen
            FROM audit_events
            WHERE action IN ('recipe_search', 'recipe_search_refresh', 'recipe_search_export')
            GROUP BY detail
            ORDER BY hits DESC
            LIMIT 80
        """)]

    alerts = []
    for user in users:
        if user['log_download_count'] >= 20:
            alerts.append({'level': 'high', 'username': user['username'], 'message': '日志下载次数较高，请确认是否为排障需要'})
        if user['events_24h'] >= 80:
            alerts.append({'level': 'medium', 'username': user['username'], 'message': '24 小时内操作频次较高'})
        if not user.get('display_name') and user['role'] != 'admin' and (user['login_count'] or user['search_count']):
            alerts.append({'level': 'low', 'username': user['username'], 'message': '已使用但尚未填写真实姓名'})
    for row in ip_summary:
        alerts.append({'level': 'medium', 'username': row['username'], 'message': f"近 7 天出现 {row['ip_count']} 个不同 IP"})

    for event in recent_events:
        try:
            event['detail'] = json.loads(event.get('detail') or '{}')
        except json.JSONDecodeError:
            event['detail'] = {}
    recipe_keywords = []
    for row in recipe_keyword_events:
        try:
            detail = json.loads(row.get('detail') or '{}')
        except json.JSONDecodeError:
            detail = {}
        label_parts = [detail.get('scope') or 'recipe']
        if detail.get('keyword'):
            label_parts.append(detail.get('keyword'))
        if detail.get('recipe_keyword'):
            label_parts.append(detail.get('recipe_keyword'))
        recipe_keywords.append({
            'label': ' / '.join(label_parts),
            'scope': detail.get('scope'),
            'keyword': detail.get('keyword'),
            'recipe_keyword': detail.get('recipe_keyword'),
            'hits': row.get('hits'),
            'last_seen': row.get('last_seen'),
            'cache_hit': detail.get('cache_hit'),
            'total_logs': detail.get('total_logs'),
        })

    return {
        'users': users,
        'recent_events': recent_events,
        'top_devices': top_devices,
        'recipe_keywords': recipe_keywords[:30],
        'alerts': alerts[:50],
        'totals': {
            'user_count': len(users),
            'events_24h': sum(int(u.get('events_24h') or 0) for u in users),
            'search_count': sum(int(u.get('search_count') or 0) for u in users),
            'recipe_search_count': sum(int(u.get('recipe_search_count') or 0) for u in users),
            'export_count': sum(int(u.get('export_count') or 0) for u in users),
            'recipe_export_count': sum(int(u.get('recipe_export_count') or 0) for u in users),
            'log_download_count': sum(int(u.get('log_download_count') or 0) for u in users),
            'log_analysis_count': sum(int(u.get('log_analysis_count') or 0) for u in users),
        },
    }

def seconds_label(seconds):
    total = int(seconds or 0)
    hours = total // 3600
    minutes = (total % 3600) // 60
    if hours:
        return f"{hours}小时{minutes}分"
    return f"{minutes}分"

def emergency_device_summary(sns):
    result = []
    for input_sn in sns:
        real_sn, info = resolve_sn(input_sn)
        customer = get_company_info(info.get('company_id'))
        daily_rows = fetch_all(
            "SELECT DATE(create_time) AS day, COUNT(*) AS production_count, "
            "COUNT(DISTINCT recipe_id) AS recipe_count, MIN(create_time) AS first_time, "
            "MAX(create_time) AS last_time, "
            "TIMESTAMPDIFF(SECOND, MIN(create_time), MAX(create_time)) AS span_seconds, "
            "SUM(CAST(time AS SIGNED)) AS cook_seconds "
            "FROM sop_machinelog WHERE sn = %s "
            "GROUP BY day ORDER BY day",
            (real_sn,),
            source=True,
            database='btyc',
        )
        total_span_seconds = 0
        max_span_seconds = 0
        for row in daily_rows:
            row['span_seconds'] = int(row.get('span_seconds') or 0)
            row['cook_seconds'] = int(row.get('cook_seconds') or 0)
            row['span_label'] = seconds_label(row['span_seconds'])
            row['cook_label'] = seconds_label(row['cook_seconds'])
            total_span_seconds += row['span_seconds']
            max_span_seconds = max(max_span_seconds, row['span_seconds'])
        result.append({
            'sn': real_sn,
            'input_sn': input_sn,
            'customer': customer,
            'info': {
                'company_id': info.get('company_id'),
                'robot_type': info.get('robot_type'),
                'hardware_version': info.get('hardware_version'),
                'latest_update_package': info.get('latest_update_package'),
                'last_online_time': info.get('last_online_time'),
            },
            'usage_days': len(daily_rows),
            'total_span_seconds': total_span_seconds,
            'total_span_label': seconds_label(total_span_seconds),
            'max_daily_span_seconds': max_span_seconds,
            'max_daily_span_label': seconds_label(max_span_seconds),
            'total_production_count': sum(int(row.get('production_count') or 0) for row in daily_rows),
            'daily': daily_rows,
        })
    return result

@app.post("/api/login")
def login(payload: LoginRequest, request: Request):
    user_meta = ZHIKU_USERS.get(payload.username)
    expected = user_meta.get('password') if user_meta else None
    if expected is None or not hmac.compare_digest(expected, payload.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    log_event(payload.username, 'login', request)
    return {
        "token": sign_token(payload.username, expires_at),
        "username": payload.username,
        "expires_at": expires_at,
        "role": user_meta.get('role', 'user'),
        "profile": get_profile(payload.username),
    }

def fetch_all(query, args=None, source=False, database=None):
    conn = get_source_conn(database) if source else get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(query, args)
            return cur.fetchall()
    finally:
        conn.close()

def fetch_one(query, args=None, source=False, database=None):
    rows = fetch_all(query, args, source=source, database=database)
    return rows[0] if rows else None

def candidate_sns(sn):
    raw = sn.strip()
    candidates = [raw]
    if raw and not raw.startswith('0'):
        candidates.append(f'0{raw}')
    return list(dict.fromkeys(candidates))

def resolve_sn(sn):
    candidates = candidate_sns(sn)
    placeholders = ','.join(['%s'] * len(candidates))
    robot = fetch_one(
        f"SELECT * FROM sop_robot WHERE machinecode IN ({placeholders}) LIMIT 1",
        tuple(candidates),
        source=True,
        database='btyc',
    )
    if robot:
        return robot['machinecode'], robot

    robot = fetch_one(
        "SELECT * FROM sop_robot WHERE machinecode LIKE %s LIMIT 1",
        (f'%{sn.strip()}',),
        source=True,
        database='btyc',
    )
    if robot:
        return robot['machinecode'], robot

    raise HTTPException(status_code=404, detail="Device not found")

def format_gap(delta):
    total_seconds = int(delta.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    if days:
        return f"{days}天 {hours}小时 {minutes}分"
    if hours:
        return f"{hours}小时 {minutes}分"
    return f"{minutes}分"

def classify_production_behavior(log, duration_stats):
    duration = int(log.get('duration_seconds') or 0)
    recipe_id = log.get('recipe_id')
    stats = duration_stats.get(recipe_id) or {}
    expected = stats.get('avg_duration_seconds')
    expected_duration = float(expected) if expected is not None else None
    duration_ratio = round(duration / expected_duration, 2) if expected_duration else None

    whether = log.get('whether')
    manual = log.get('manual')
    whether_label = {0: '取消', 1: '失败', 2: '成功'}.get(whether, '未知')
    manual_label = {0: '手动', 1: '自动'}.get(manual, '未知')
    tags = []

    if whether == 0:
        tags.append('取消')
    elif whether == 1:
        tags.append('失败')
    if manual == 0:
        tags.append('手动控制')

    if expected_duration and expected_duration >= 60 and duration > 0:
        if duration <= max(expected_duration * 0.5, 60) and expected_duration >= 120:
            tags.append('执行过短')
        elif duration >= expected_duration * 1.8:
            tags.append('执行过长')
    elif duration and duration <= 60:
        tags.append('短时执行')

    if not tags:
        tags.append('正常执行')

    return {
        'whether_label': whether_label,
        'manual_label': manual_label,
        'expected_duration_seconds': round(expected_duration, 1) if expected_duration else None,
        'duration_ratio': duration_ratio,
        'behavior_tags': tags,
        'is_behavior_exception': any(tag in tags for tag in ['取消', '失败', '手动控制', '执行过短', '执行过长', '短时执行']),
    }

def parse_json_array(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []

def parse_json_value(value):
    if value in (None, ''):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value

def command_text(step):
    return str(step.get('commands') or step.get('command') or '').strip()

def recipe_resource_summary(recipe, detail, usage):
    cook_steps = parse_json_array(detail.get('cook_steps') if detail else None)
    wash_steps = parse_json_array(detail.get('wash_steps') if detail else None)
    moisten_steps = parse_json_array(detail.get('moisten_steps') if detail else None)
    cooking_ingredients = parse_json_array(detail.get('cooking_ingredient') if detail else None)

    resource_flags = {
        'heating': False,
        'stirring': False,
        'pot_position': False,
        'auto_feeding': False,
        'manual_feeding': False,
        'oil': False,
        'lard': False,
        'starch_slurry': False,
        'water': False,
        'seasoning': False,
        'moisten_pot': bool(moisten_steps),
        'wash': bool(wash_steps),
        'move_pot': False,
    }
    resources = set()
    steps = []

    for step in cook_steps:
        text = command_text(step)
        step_type = str(step.get('type', ''))
        automatic = str(step.get('automatic', ''))
        power = str(step.get('power') or '')
        speed = str(step.get('speed') or step.get('stirSpeed') or '')
        position = str(step.get('position') or '')

        if step_type == '3' or (power and power not in {'0', '0.0'}):
            resource_flags['heating'] = True
            resources.add('加热/功率')
        if speed and speed not in {'0', '0.0'}:
            resource_flags['stirring'] = True
            resources.add('搅拌')
        if position:
            resource_flags['pot_position'] = True
            resources.add('锅位')
        if str(step.get('movepot', '0')) not in {'', '0', '0.0'}:
            resource_flags['move_pot'] = True
            resources.add('翻锅/移锅')
        if step_type == '2' or automatic == '1' or '自动投入' in text:
            resource_flags['auto_feeding'] = True
            resources.add('自动投料')
        if step_type == '1' and automatic != '1':
            resource_flags['manual_feeding'] = True
            resources.add('人工/预制投料')
        if any(k in text for k in ['水淀粉', '水溶き片栗粉', '片栗粉', '生粉']):
            resource_flags['starch_slurry'] = True
            resource_flags['water'] = True
            resources.add('水淀粉')
        if any(k in text for k in ['猪油', 'lard', 'Lard']):
            resource_flags['lard'] = True
            resource_flags['oil'] = True
            resources.add('油桶注油')
            resources.add('猪油桶/猪油')
        elif any(k in text for k in ['油', 'オイル', 'oil', 'Oil']):
            resource_flags['oil'] = True
            resources.add('油桶注油')
        if any(k in text for k in ['水', '高汤', 'スープ']):
            resource_flags['water'] = True
            resources.add('水/汤汁')
        if any(k in text for k in ['盐', '精盐', '鸡精', '味精', '生抽', '老抽', '蚝油', '豆瓣', '酱', '粉']):
            resource_flags['seasoning'] = True
            resources.add('调料')

        steps.append({
            'time': step.get('time'),
            'type': step.get('type'),
            'automatic': step.get('automatic'),
            'power': step.get('power'),
            'speed': step.get('speed') or step.get('stirSpeed'),
            'position': step.get('position'),
            'movepot': step.get('movepot'),
            'commands': text,
        })

    if moisten_steps:
        resources.add('润锅')
    if wash_steps:
        resources.add('洗锅')

    category = str(recipe.get('group_name') or recipe.get('type') or '未分类')

    return {
        'id': recipe.get('id'),
        'name': recipe.get('name'),
        'category': category,
        'group_name': recipe.get('group_name'),
        'recipe_type': recipe.get('type'),
        'execution_count': usage.get(recipe.get('id'), {}).get('cnt', 0),
        'total_duration_seconds': usage.get(recipe.get('id'), {}).get('total_duration_seconds', 0),
        'first_time': usage.get(recipe.get('id'), {}).get('first_time'),
        'last_time': usage.get(recipe.get('id'), {}).get('last_time'),
        'cook_time': detail.get('cook_time') if detail else None,
        'resource_flags': resource_flags,
        'resources': sorted(resources),
        'steps': steps[:80],
        'wash_steps_count': len(wash_steps),
        'moisten_steps_count': len(moisten_steps),
        'ingredient_count': len(cooking_ingredients),
        'has_lard': resource_flags['lard'],
    }

def build_recipe_category_summary(recipe_archive):
    categories = {}
    for recipe in recipe_archive:
        category = recipe.get('category') or '未分类'
        if category not in categories:
            categories[category] = {
                'category': category,
                'recipe_count': 0,
                'execution_count': 0,
                'lard_recipe_count': 0,
                'resources': set(),
            }
        item = categories[category]
        item['recipe_count'] += 1
        item['execution_count'] += int(recipe.get('execution_count') or 0)
        if recipe.get('has_lard'):
            item['lard_recipe_count'] += 1
        item['resources'].update(recipe.get('resources') or [])

    summary = []
    for item in categories.values():
        summary.append({
            **item,
            'resources': sorted(item['resources']),
        })
    return sorted(summary, key=lambda row: row['execution_count'], reverse=True)

def get_company_info(company_id):
    if not company_id:
        return {}
    company = fetch_one(
        "SELECT id, company_name, common_name, addr, company_addr, area_code, "
        "geo_pname, geo_cityname, geo_adname, geo_name, geo_address, contact_name, contact_phone "
        "FROM ums_company WHERE id = %s LIMIT 1",
        (company_id,),
        source=True,
        database='btyc',
    )
    return company or {}

def get_device_software_info(sn):
    version_record = fetch_one(
        "SELECT apk_version, rom_version, version, create_time, update_time "
        "FROM robot_version_record WHERE sn = %s ORDER BY update_time DESC LIMIT 1",
        (sn,),
        source=True,
        database='btyc',
    ) or {}
    config_info = fetch_one(
        "SELECT app_version, create_time FROM robot_config_info WHERE sn = %s ORDER BY create_time DESC LIMIT 1",
        (sn,),
        source=True,
        database='btyc',
    ) or {}
    return {
        'upper_computer_version': version_record.get('apk_version') or config_info.get('app_version'),
        'apk_version': version_record.get('apk_version'),
        'rom_version': version_record.get('rom_version'),
        'version_record_time': version_record.get('update_time') or version_record.get('create_time'),
        'reported_app_version': config_info.get('app_version'),
        'reported_app_time': config_info.get('create_time'),
    }

def compact_keyword(value):
    return re.sub(r'[\s\(\)（）【】\[\]{}<>《》,，.。·_\-—/\\\\]+', '', value or '').strip()

def device_lookup_cache_key(keyword, limit):
    return hashlib.sha256(json.dumps({
        'keyword': keyword.strip(),
        'limit': limit,
    }, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()

def search_devices_by_keyword(keyword, limit=50, force_refresh=False):
    clean = (keyword or '').strip()
    if len(clean) < 2:
        raise HTTPException(status_code=400, detail="请输入至少 2 个字符")
    safe_limit = max(1, min(int(limit or 50), 100))
    cache_key = device_lookup_cache_key(clean, safe_limit)
    now = time.time()
    cached = DEVICE_LOOKUP_CACHE.get(cache_key)
    if cached and not force_refresh and cached['expires_at'] > now:
        result = dict(cached['result'])
        result['cache'] = {'hit': True, 'ttl_seconds': int(cached['expires_at'] - now), 'created_at': cached['created_at']}
        return result

    like = f"%{clean}%"
    compact = compact_keyword(clean)
    compact_like = f"%{compact}%" if compact else like
    compact_sql = """
        REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
            CONCAT_WS('', r.machinecode, r.name, r.spec, r.robot_type, r.latest_update_package,
                c.company_name, c.common_name, c.addr, c.company_addr, c.geo_pname,
                c.geo_cityname, c.geo_adname, c.geo_name, c.geo_address, c.contact_name),
            ' ', ''), '（', ''), '）', ''), '(', ''), ')', ''), '-', ''), '_', ''), '·', ''), '，', '')
    """
    rows = fetch_all(
        f"""
        SELECT
            r.machinecode AS sn,
            r.name AS device_name,
            r.spec,
            r.robot_type,
            r.hardware_version,
            r.latest_update_package AS version,
            r.last_online_time,
            r.status,
            r.company_id,
            COALESCE(c.common_name, c.company_name, '') AS customer_name,
            c.company_name,
            c.common_name,
            COALESCE(c.geo_cityname, c.geo_pname, c.area_code, '') AS region,
            c.geo_pname,
            c.geo_cityname,
            c.geo_adname,
            c.area_code,
            c.addr,
            c.company_addr
        FROM btyc.sop_robot r
        LEFT JOIN btyc.ums_company c ON r.company_id = c.id
        WHERE r.machinecode IS NOT NULL AND r.machinecode != ''
          AND (
            r.machinecode LIKE %s OR r.name LIKE %s OR r.spec LIKE %s OR
            r.robot_type LIKE %s OR r.latest_update_package LIKE %s OR
            c.company_name LIKE %s OR c.common_name LIKE %s OR c.addr LIKE %s OR
            c.company_addr LIKE %s OR c.geo_pname LIKE %s OR c.geo_cityname LIKE %s OR
            c.geo_adname LIKE %s OR c.geo_name LIKE %s OR c.geo_address LIKE %s OR
            c.contact_name LIKE %s OR {compact_sql} LIKE %s
          )
        ORDER BY
            CASE
                WHEN r.machinecode = %s THEN 0
                WHEN c.common_name LIKE %s OR c.company_name LIKE %s THEN 1
                WHEN c.geo_cityname LIKE %s OR c.geo_pname LIKE %s OR c.geo_adname LIKE %s THEN 2
                WHEN r.name LIKE %s OR r.spec LIKE %s THEN 3
                ELSE 4
            END,
            r.last_online_time DESC,
            r.machinecode
        LIMIT %s
        """,
        tuple([like] * 15 + [compact_like, clean, like, like, like, like, like, like, like, safe_limit]),
        source=True,
        database='btyc',
    )
    result = {
        'keyword': clean,
        'compact_keyword': compact,
        'total': len(rows),
        'devices': rows,
        'cache': {'hit': False, 'ttl_seconds': DEVICE_LOOKUP_CACHE_TTL_SECONDS, 'created_at': int(now)},
    }
    DEVICE_LOOKUP_CACHE[cache_key] = {
        'result': result,
        'created_at': int(now),
        'expires_at': now + DEVICE_LOOKUP_CACHE_TTL_SECONDS,
    }
    return result

def version_stats_cache_key(version, keyword, limit):
    return hashlib.sha256(json.dumps({
        'version': (version or '').strip(),
        'keyword': (keyword or '').strip(),
        'limit': int(limit or 500),
    }, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()

def build_device_version_stats(version='', keyword='', limit=500, force_refresh=False):
    clean_version = (version or '').strip()
    clean_keyword = (keyword or '').strip()
    safe_limit = max(1, min(int(limit or 500), 5000))
    cache_key = version_stats_cache_key(clean_version, clean_keyword, safe_limit)
    now = time.time()
    cached = VERSION_STATS_CACHE.get(cache_key)
    if cached and not force_refresh and cached['expires_at'] > now:
        result = dict(cached['result'])
        result['cache'] = {'hit': True, 'ttl_seconds': int(cached['expires_at'] - now), 'created_at': cached['created_at']}
        return result

    version_expr = "COALESCE(NULLIF(rv.apk_version, ''), NULLIF(rci.app_version, ''), '未知上位机版本')"
    version_time_expr = "COALESCE(rv.update_time, rv.create_time, rci.create_time)"
    version_from_sql = """
        FROM btyc.sop_robot r
        LEFT JOIN btyc.ums_company c ON r.company_id = c.id
        LEFT JOIN (
            SELECT sn, apk_version, rom_version, version, create_time, update_time
            FROM (
                SELECT sn, apk_version, rom_version, version, create_time, update_time,
                       ROW_NUMBER() OVER(PARTITION BY sn ORDER BY update_time DESC, id DESC) AS rn
                FROM btyc.robot_version_record
            ) t WHERE rn = 1
        ) rv ON r.machinecode = rv.sn
        LEFT JOIN (
            SELECT sn, app_version, create_time
            FROM (
                SELECT sn, app_version, create_time,
                       ROW_NUMBER() OVER(PARTITION BY sn ORDER BY create_time DESC, id DESC) AS rn
                FROM btyc.robot_config_info
            ) t WHERE rn = 1
        ) rci ON r.machinecode = rci.sn
    """
    conditions = ["r.machinecode IS NOT NULL", "r.machinecode != ''"]
    args = []
    if clean_version:
        if clean_version == '未知上位机版本':
            conditions.append("(rv.apk_version IS NULL OR rv.apk_version = '') AND (rci.app_version IS NULL OR rci.app_version = '')")
        else:
            conditions.append(f"{version_expr} = %s")
            args.append(clean_version)
    if clean_keyword:
        like = f"%{clean_keyword}%"
        conditions.append(
            "(r.machinecode LIKE %s OR r.name LIKE %s OR r.spec LIKE %s OR r.robot_type LIKE %s OR "
            "r.latest_update_package LIKE %s OR r.hardware_version LIKE %s OR "
            "rv.apk_version LIKE %s OR rv.rom_version LIKE %s OR rci.app_version LIKE %s OR "
            "c.company_name LIKE %s OR c.common_name LIKE %s OR c.geo_pname LIKE %s OR "
            "c.geo_cityname LIKE %s OR c.geo_adname LIKE %s OR c.area_code LIKE %s)"
        )
        args.extend([like] * 15)
    where_sql = " AND ".join(conditions)

    summary_rows = fetch_all(
        f"""
        SELECT
            {version_expr} AS version,
            COUNT(*) AS device_count,
            COUNT(DISTINCT r.company_id) AS customer_count,
            MIN({version_time_expr}) AS first_upgrade_time,
            MAX({version_time_expr}) AS last_upgrade_time,
            MAX(r.last_online_time) AS latest_online_time
        {version_from_sql}
        WHERE {where_sql}
        GROUP BY {version_expr}
        ORDER BY device_count DESC, last_upgrade_time DESC
        LIMIT 200
        """,
        tuple(args),
        source=True,
        database='btyc',
    )
    device_rows = fetch_all(
        f"""
        SELECT
            r.machinecode AS sn,
            r.name AS device_name,
            r.spec,
            r.robot_type,
            r.hardware_version,
            {version_expr} AS version,
            rv.apk_version,
            rv.rom_version,
            rci.app_version AS reported_app_version,
            r.latest_update_package AS update_package,
            {version_time_expr} AS version_update_time,
            r.update_time AS package_update_time,
            r.last_online_time,
            r.status,
            r.network_status,
            r.company_id,
            COALESCE(c.common_name, c.company_name, '') AS customer_name,
            COALESCE(c.geo_cityname, c.geo_pname, c.area_code, '') AS region
        {version_from_sql}
        WHERE {where_sql}
        ORDER BY {version_time_expr} DESC, r.last_online_time DESC, r.machinecode
        LIMIT %s
        """,
        tuple(args + [safe_limit]),
        source=True,
        database='btyc',
    )
    total_row = fetch_one(
        f"""
        SELECT COUNT(*) AS total_devices, COUNT(DISTINCT r.company_id) AS total_customers
        {version_from_sql}
        WHERE {where_sql}
        """,
        tuple(args),
        source=True,
        database='btyc',
    )
    result = {
        'params': {'version': clean_version, 'keyword': clean_keyword, 'limit': safe_limit},
        'summary': {
            'total_devices': int(total_row.get('total_devices') or 0),
            'total_customers': int(total_row.get('total_customers') or 0),
            'version_count': len(summary_rows),
            'returned_devices': len(device_rows),
            'truncated': int(total_row.get('total_devices') or 0) > len(device_rows),
            'upgrade_time_field': 'robot_version_record.update_time / robot_config_info.create_time',
            'version_field': 'robot_version_record.apk_version',
        },
        'versions': summary_rows,
        'devices': device_rows,
        'cache': {'hit': False, 'ttl_seconds': VERSION_STATS_CACHE_TTL_SECONDS, 'created_at': int(now)},
    }
    VERSION_STATS_CACHE[cache_key] = {
        'result': result,
        'created_at': int(now),
        'expires_at': now + VERSION_STATS_CACHE_TTL_SECONDS,
    }
    return result

def get_device_log_files(sn):
    return fetch_all(
        "SELECT id, sn, file_length, file_name, pic AS url, type, create_time, update_time, cos_deleted "
        "FROM machine_ftp WHERE sn = %s ORDER BY create_time DESC LIMIT 300",
        (sn,),
        source=True,
        database='btyc',
    )

def parse_log_ts(line):
    patterns = [
        (re.compile(r'\[(\d{4})-(\d{2})-(\d{2})[ _](\d{2}:\d{2}:\d{2})\]'), '%Y-%m-%d %H:%M:%S'),
        (re.compile(r'\[(\d{2})\.(\d{2})\.(\d{2}) (\d{2}:\d{2}:\d{2})\]'), None),
        (re.compile(r'\[(\d{2})-(\d{2}) (\d{2}:\d{2}:\d{2})\]'), None),
    ]
    for idx, (pattern, fmt) in enumerate(patterns):
        match = pattern.search(line)
        if not match:
            continue
        try:
            if idx == 0:
                return datetime.strptime(f"{match.group(1)}-{match.group(2)}-{match.group(3)} {match.group(4)}", fmt)
            if idx == 1:
                return datetime.strptime(f"20{match.group(1)}-{match.group(2)}-{match.group(3)} {match.group(4)}", "%Y-%m-%d %H:%M:%S")
            return datetime.strptime(f"2026-{match.group(1)}-{match.group(2)} {match.group(3)}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None

def log_analysis_cache_path(file_id):
    return CACHE_DIR / 'log_analysis' / f'{int(file_id)}.json'

def read_cached_log_analysis(file_id):
    path = log_analysis_cache_path(file_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        if payload.get('analysis_version') != LOG_ANALYSIS_VERSION:
            return None
        return payload
    except Exception:
        path.unlink(missing_ok=True)
        return None

def save_cached_log_analysis(file_id, payload):
    path = log_analysis_cache_path(file_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str))

def download_log_zip(url):
    limit = MAX_LOG_ANALYSIS_DOWNLOAD_MB * 1024 * 1024
    req = urllib.request.Request(url, headers={'User-Agent': 'ZhikuDashboard/1.0'})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = bytearray()
        while True:
            chunk = resp.read(1024 * 512)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > limit:
                raise HTTPException(status_code=413, detail=f"Log file exceeds {MAX_LOG_ANALYSIS_DOWNLOAD_MB}MB analysis limit")
    return bytes(data)

def text_from_zip_member(zf, info, max_bytes=8 * 1024 * 1024):
    if info.file_size > max_bytes:
        data = zf.open(info).read(max_bytes)
    else:
        data = zf.read(info)
    return data.decode('utf-8', errors='ignore')

def classify_log_file(name):
    base = Path(name).name
    if base.startswith('android_'):
        return 'android_app'
    if base.startswith('debug'):
        return 'mcu_debug'
    if base == 'main_board.log':
        return 'main_board'
    if base == 'oildrum_board.log':
        return 'oildrum_board'
    if base == 'temperature.log':
        return 'temperature'
    return 'other'

def log_kind_label(kind):
    return LOG_KIND_DEFS.get(kind, LOG_KIND_DEFS['other'])['label']

def log_specs_payload():
    return {
        'file_kinds': [
            {'kind': kind, **meta}
            for kind, meta in LOG_KIND_DEFS.items()
        ],
        'oildrum_fields': OILDRUM_FIELD_SPECS,
        'fault_code_source': {
            'file': FAULT_CODE_DATA_PATH.name,
            'sheet': '故障码清单V5.0-屏蔽',
            'code_rule': '日志形如“故障码：1_1_86_F”时，按第 1 段 + 第 2 段补两位 + 第 4 段补两位转换，例如 1_1_86_F => 1010F。',
        },
    }

def load_fault_code_records():
    if not FAULT_CODE_DATA_PATH.exists():
        return []
    try:
        payload = json.loads(FAULT_CODE_DATA_PATH.read_text())
        return payload.get('records', [])
    except Exception:
        return []

FAULT_CODE_RECORDS = load_fault_code_records()
FAULT_CODE_BY_ERROR = {str(row.get('error_code', '')).upper(): row for row in FAULT_CODE_RECORDS if row.get('error_code')}
FAULT_CODE_BY_ERR = {str(row.get('err_code', '')).upper(): row for row in FAULT_CODE_RECORDS if row.get('err_code')}

def normalize_fault_code(value):
    return str(value or '').strip().upper().replace(' ', '')

def fault_code_from_tuple(parts):
    if len(parts) < 4:
        return ''
    first = normalize_fault_code(parts[0])
    second = normalize_fault_code(parts[1]).zfill(2)
    fourth = normalize_fault_code(parts[3]).zfill(2)
    return f"{first}{second}{fourth}"

def extract_fault_matches(text, file_name, kind, limit=80):
    counter = Counter()
    examples = {}
    for line in text.splitlines()[:120000]:
        line_upper = line.upper()
        has_fault_context = bool(re.search(r'故障|报警|异常|FAULT|ERR|ERROR|MALFUNCTION|HEATERGETERRCODE|ERRCODE|ERROR\\s*CODE', line_upper))
        for match in re.finditer(r'(?:故障码|FAULT|ERR(?:OR)?\\s*CODE)[:：=\\s]+([0-9A-F]+)_([0-9A-F]+)_([0-9A-F]+)_([0-9A-F]+)', line_upper):
            code = fault_code_from_tuple(match.groups())
            if code in FAULT_CODE_BY_ERROR:
                counter[code] += 1
                examples.setdefault(code, line.strip()[:180])
        if not has_fault_context:
            continue
        for match in re.finditer(r'(?<![A-Z0-9])([1-9][0-9A-F]{4,5})(?![A-Z0-9])', line_upper):
            code = normalize_fault_code(match.group(1))
            if code in FAULT_CODE_BY_ERROR:
                counter[code] += 1
                examples.setdefault(code, line.strip()[:180])
        for match in re.finditer(r'(?<![A-Z0-9])([A-Z]{2,4}\\d{2})(?![A-Z0-9])', line_upper):
            meta = FAULT_CODE_BY_ERR.get(normalize_fault_code(match.group(1)))
            if meta:
                code = meta.get('error_code')
                counter[code] += 1
                examples.setdefault(code, line.strip()[:180])

    rows = []
    for code, count in counter.most_common(limit):
        meta = FAULT_CODE_BY_ERROR.get(code, {})
        rows.append({
            'file_name': file_name,
            'kind': kind,
            'kind_label': log_kind_label(kind),
            'error_code': code,
            'err_code': meta.get('err_code'),
            'module': meta.get('module'),
            'meaning': meta.get('meaning'),
            'err_message': meta.get('err_message'),
            'priority': meta.get('priority'),
            'remark': meta.get('remark'),
            'count': count,
            'example': examples.get(code, ''),
        })
    return rows

def build_log_category_summary(file_summary):
    grouped = {}
    for row in file_summary:
        kind = row.get('kind') or 'other'
        meta = LOG_KIND_DEFS.get(kind, LOG_KIND_DEFS['other'])
        item = grouped.setdefault(kind, {
            'kind': kind,
            'label': meta['label'],
            'purpose': meta['purpose'],
            'key_patterns': meta.get('key_patterns', []),
            'file_count': 0,
            'total_lines': 0,
            'total_size_mb': 0,
            'first_time': None,
            'last_time': None,
        })
        item['file_count'] += 1
        item['total_lines'] += int(row.get('lines') or 0)
        item['total_size_mb'] += float(row.get('size_mb') or 0)
        if row.get('first_time'):
            item['first_time'] = row['first_time'] if not item['first_time'] else min(item['first_time'], row['first_time'])
        if row.get('last_time'):
            item['last_time'] = row['last_time'] if not item['last_time'] else max(item['last_time'], row['last_time'])
    result = []
    order = ['oildrum_board', 'temperature', 'main_board', 'mcu_debug', 'android_app', 'other']
    for kind in order:
        if kind in grouped:
            grouped[kind]['total_size_mb'] = round(grouped[kind]['total_size_mb'], 2)
            result.append(grouped[kind])
    return result

def analyze_oildrum_text(text):
    status_re = re.compile(r'^\[(\d{2})\.(\d{2})\.(\d{2}) (\d{2}:\d{2}:\d{2})\]\s+dev status\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)(?:\s+([\d.\-]+))?')
    pump_start_re = re.compile(r'pump hall start\s+(-?\d+)\s+(-?[\d.]+)', re.I)
    pump_finish_re = re.compile(r'pump hall finish\s+(-?\d+),\s*time\s+(\d+),\s*state\s+(\d+)', re.I)
    read_power_re = re.compile(r'read power\s+(\d+)\s+(-?\d+)\s+(-?\d+)', re.I)
    heat_re = re.compile(r'(oil|pipe) heat enable\s+(\d+)\s+(-?[\d.]+)', re.I)
    sw_re = re.compile(r'read sw v\s+(\d+)\s+(\d+)\s+(\d+)', re.I)
    samples = []
    events = []
    event_counts = Counter()
    motor_events = []
    heat_events = []
    power_events = []
    sw_versions = []
    for line in text.splitlines():
        clean = line.strip()
        ts = parse_log_ts(clean)
        match = status_re.search(clean)
        if match:
            if not ts:
                continue
            bucket = int(match.group(5)) / 10
            pipe = int(match.group(6)) / 10
            reserved = int(match.group(7))
            motor_rpm = int(match.group(8))
            heater_pwm = float(match.group(9)) if match.group(9) else None
            samples.append({
                't': ts,
                'bucket_temp': bucket,
                'pipe_temp': pipe,
                'oil_temp': bucket,
                'reserved': reserved,
                'motor_rpm': motor_rpm,
                'heater_pwm': heater_pwm,
                'current': heater_pwm,
            })
            continue
        if not ts:
            continue
        event_text = re.sub(r'^\[[^\]]+\]\s*', '', clean)[:180]
        start = pump_start_re.search(clean)
        if start:
            hall_count = int(start.group(1))
            direction = '投油' if hall_count < 0 else '反抽'
            event_counts[f'电机开始-{direction}'] += 1
            item = {
                'time': ts.isoformat(sep=' '),
                'type': 'pump_start',
                'label': f'电机开始{direction}',
                'hall_count': hall_count,
                'motor_pwm': float(start.group(2)),
                'direction': direction,
                'text': event_text,
            }
            motor_events.append(item)
            events.append(item)
            continue
        finish = pump_finish_re.search(clean)
        if finish:
            state = int(finish.group(3))
            event_counts['电机完成-霍尔异常' if state == 1 else '电机完成-正常'] += 1
            item = {
                'time': ts.isoformat(sep=' '),
                'type': 'pump_finish',
                'label': '电机完成',
                'hall_count': int(finish.group(1)),
                'duration_ms': int(finish.group(2)),
                'hall_phase_state': state,
                'hall_phase_label': '异常' if state == 1 else '正常',
                'text': event_text,
            }
            motor_events.append(item)
            events.append(item)
            continue
        power = read_power_re.search(clean)
        if power:
            limited = int(power.group(1)) == 1
            event_counts['功率限制-有' if limited else '功率限制-无'] += 1
            item = {
                'time': ts.isoformat(sep=' '),
                'type': 'read_power',
                'label': '读取功率限制',
                'power_limited': limited,
                'text': event_text,
            }
            power_events.append(item)
            events.append(item)
            continue
        heat = heat_re.search(clean)
        if heat:
            target = '油桶' if heat.group(1).lower() == 'oil' else '油管'
            enabled = int(heat.group(2)) == 1
            target_temp = float(heat.group(3))
            event_counts[f'{target}加热-{"使能" if enabled else "关闭"}'] += 1
            item = {
                'time': ts.isoformat(sep=' '),
                'type': f'{heat.group(1).lower()}_heat_enable',
                'label': f'{target}加热目标',
                'target': target,
                'enabled': enabled,
                'target_temp': target_temp,
                'text': event_text,
            }
            heat_events.append(item)
            events.append(item)
            continue
        sw = sw_re.search(clean)
        if sw:
            version = f"{sw.group(1)}.{sw.group(2)}.{sw.group(3)}"
            event_counts['软件版本读取'] += 1
            item = {
                'time': ts.isoformat(sep=' '),
                'type': 'read_sw_version',
                'label': '软件版本',
                'version': version,
                'text': event_text,
            }
            sw_versions.append(item)
            events.append(item)
    samples.sort(key=lambda row: row['t'])
    if not samples:
        return {
            'sample_count': 0,
            'series': [],
            'daily': [],
            'events': events[:120],
            'event_counts': [{'category': k, 'count': v} for k, v in event_counts.most_common()],
            'motor_events': motor_events[:120],
            'heat_events': heat_events[:120],
            'power_events': power_events[:120],
            'sw_versions': sw_versions[:20],
            'field_specs': OILDRUM_FIELD_SPECS,
        }

    by_10 = defaultdict(lambda: {'bucket': [], 'pipe': [], 'motor_rpm': [], 'heater_pwm': []})
    by_day = defaultdict(lambda: {'bucket': [], 'pipe': [], 'motor_rpm': [], 'heater_pwm': [], 'first': None, 'last': None, 'samples': 0})
    over_100 = 0
    negative_pipe = 0
    for row in samples:
        if row['bucket_temp'] > 100:
            over_100 += 1
        if row['pipe_temp'] < 0:
            negative_pipe += 1
        minute = row['t'].replace(minute=(row['t'].minute // 10) * 10, second=0)
        if 0 <= row['bucket_temp'] <= 160:
            by_10[minute]['bucket'].append(row['bucket_temp'])
        if 0 <= row['pipe_temp'] <= 120:
            by_10[minute]['pipe'].append(row['pipe_temp'])
        if row['motor_rpm'] is not None:
            by_10[minute]['motor_rpm'].append(row['motor_rpm'])
        if row['heater_pwm'] is not None:
            by_10[minute]['heater_pwm'].append(row['heater_pwm'])
        day = row['t'].strftime('%Y-%m-%d')
        item = by_day[day]
        if 0 <= row['bucket_temp'] <= 160:
            item['bucket'].append(row['bucket_temp'])
        if 0 <= row['pipe_temp'] <= 120:
            item['pipe'].append(row['pipe_temp'])
        if row['motor_rpm'] is not None:
            item['motor_rpm'].append(row['motor_rpm'])
        if row['heater_pwm'] is not None:
            item['heater_pwm'].append(row['heater_pwm'])
        item['first'] = row['t'] if item['first'] is None else min(item['first'], row['t'])
        item['last'] = row['t'] if item['last'] is None else max(item['last'], row['t'])
        item['samples'] += 1

    series = []
    for ts, agg in sorted(by_10.items()):
        series.append({
            'time': ts.isoformat(sep=' '),
            'bucket_temp': round(statistics.mean(agg['bucket']), 2) if agg['bucket'] else None,
            'pipe_temp': round(statistics.mean(agg['pipe']), 2) if agg['pipe'] else None,
            'motor_rpm': round(statistics.mean(agg['motor_rpm']), 2) if agg['motor_rpm'] else None,
            'heater_pwm': round(statistics.mean(agg['heater_pwm']), 2) if agg['heater_pwm'] else None,
        })
    daily = []
    for day, agg in sorted(by_day.items()):
        daily.append({
            'day': day,
            'first_time': agg['first'].isoformat(sep=' ') if agg['first'] else None,
            'last_time': agg['last'].isoformat(sep=' ') if agg['last'] else None,
            'bucket_min': round(min(agg['bucket']), 1) if agg['bucket'] else None,
            'bucket_avg': round(statistics.mean(agg['bucket']), 1) if agg['bucket'] else None,
            'bucket_max': round(max(agg['bucket']), 1) if agg['bucket'] else None,
            'pipe_min': round(min(agg['pipe']), 1) if agg['pipe'] else None,
            'pipe_avg': round(statistics.mean(agg['pipe']), 1) if agg['pipe'] else None,
            'pipe_max': round(max(agg['pipe']), 1) if agg['pipe'] else None,
            'motor_rpm_avg': round(statistics.mean(agg['motor_rpm']), 1) if agg['motor_rpm'] else None,
            'heater_pwm_avg': round(statistics.mean(agg['heater_pwm']), 2) if agg['heater_pwm'] else None,
            'samples': agg['samples'],
        })

    values_bucket = [r['bucket_temp'] for r in samples if 0 <= r['bucket_temp'] <= 160]
    values_pipe = [r['pipe_temp'] for r in samples if 0 <= r['pipe_temp'] <= 120]
    values_rpm = [r['motor_rpm'] for r in samples if r.get('motor_rpm') is not None]
    values_pwm = [r['heater_pwm'] for r in samples if r.get('heater_pwm') is not None]
    finish_events = [row for row in motor_events if row.get('type') == 'pump_finish']
    return {
        'sample_count': len(samples),
        'first_time': samples[0]['t'].isoformat(sep=' '),
        'last_time': samples[-1]['t'].isoformat(sep=' '),
        'bucket_min': round(min(values_bucket), 1) if values_bucket else None,
        'bucket_avg': round(statistics.mean(values_bucket), 1) if values_bucket else None,
        'bucket_max': round(max(values_bucket), 1) if values_bucket else None,
        'pipe_min': round(min(values_pipe), 1) if values_pipe else None,
        'pipe_avg': round(statistics.mean(values_pipe), 1) if values_pipe else None,
        'pipe_max': round(max(values_pipe), 1) if values_pipe else None,
        'bucket_over_100_count': over_100,
        'pipe_negative_count': negative_pipe,
        'motor_rpm_max': max(values_rpm) if values_rpm else None,
        'heater_pwm_max': round(max(values_pwm), 2) if values_pwm else None,
        'motor_start_count': len([row for row in motor_events if row.get('type') == 'pump_start']),
        'motor_finish_count': len(finish_events),
        'hall_abnormal_count': len([row for row in finish_events if row.get('hall_phase_state') == 1]),
        'max_motor_duration_ms': max([row.get('duration_ms', 0) for row in finish_events], default=None),
        'series': series[-900:],
        'daily': daily,
        'events': events[:160],
        'event_counts': [{'category': k, 'count': v} for k, v in event_counts.most_common()],
        'motor_events': motor_events[:160],
        'heat_events': heat_events[:160],
        'power_events': power_events[:160],
        'sw_versions': sw_versions[:20],
        'field_specs': OILDRUM_FIELD_SPECS,
    }

def analyze_temperature_text(text):
    temp_re = re.compile(r'^\[(\d{4}-\d{2}-\d{2})_(\d{2}:\d{2}:\d{2})\]\s+(-?\d+)_(-?\d+)_(-?\d+)')
    values = []
    first = None
    last = None
    count = 0
    for line in text.splitlines():
        match = temp_re.search(line.strip())
        if not match:
            continue
        ts = parse_log_ts(line)
        if ts:
            first = first or ts
            last = ts
        triplet = [int(match.group(i)) for i in (3, 4, 5)]
        values.extend(triplet)
        count += 1
    return {
        'sample_count': count,
        'first_time': first.isoformat(sep=' ') if first else None,
        'last_time': last.isoformat(sep=' ') if last else None,
        'min': min(values) if values else None,
        'avg': round(statistics.mean(values), 1) if values else None,
        'max': max(values) if values else None,
    }

def parse_temperature_series(text, max_points=600000):
    temp_re = re.compile(r'^\[(\d{4}-\d{2}-\d{2})_(\d{2}:\d{2}:\d{2})\]\s+(-?\d+)_(-?\d+)_(-?\d+)')
    series = []
    for line in text.splitlines():
        match = temp_re.search(line.strip())
        if not match:
            continue
        ts = parse_log_ts(line)
        if not ts:
            continue
        raw = [int(match.group(i)) for i in (3, 4, 5)]
        series.append({
            'ts': ts,
            'time': ts.isoformat(sep=' '),
            'temp_1': round(raw[0] / 10, 1),
            'temp_2': round(raw[1] / 10, 1),
            'temp_3': round(raw[2] / 10, 1),
            'raw': '_'.join(str(x) for x in raw),
        })
        if len(series) >= max_points:
            break
    return series

def parse_android_pot_temperature_series(text, max_points=300000):
    temp_re = re.compile(r'温度:_?(-?\d+)_(-?\d+)_(-?\d+)')
    series = []
    for line in text.splitlines():
        match = temp_re.search(line)
        if not match:
            continue
        ts = parse_log_ts(line)
        if not ts:
            continue
        aux_1, aux_2, pot = [int(match.group(i)) for i in (1, 2, 3)]
        series.append({
            'ts': ts,
            'time': ts.isoformat(sep=' '),
            'pot_temp': pot,
            'aux_temp_1': aux_1,
            'aux_temp_2': aux_2,
            'raw': f"{aux_1}_{aux_2}_{pot}",
            'source': 'android_app 温度字段，第3位按锅体温度展示',
        })
        if len(series) >= max_points:
            break
    return series

def temperature_series_cache_path(file_id):
    path = CACHE_DIR / 'temperature_series'
    path.mkdir(parents=True, exist_ok=True)
    return path / f'{int(file_id)}.json'

def cached_temperature_series_from_file(file_row):
    file_id = file_row.get('id')
    if not file_id or not file_row.get('url'):
        return None
    path = temperature_series_cache_path(file_id)
    if path.exists():
        try:
            payload = json.loads(path.read_text())
            if payload.get('version') == 1:
                series = payload.get('series') or []
                for row in series:
                    row['ts'] = datetime.strptime(row['time'], "%Y-%m-%d %H:%M:%S")
                return {
                    'file': payload.get('file') or {},
                    'coverage': payload.get('coverage') or {},
                    'series': series,
                }
        except Exception:
            path.unlink(missing_ok=True)

    if file_row.get('cos_deleted'):
        return None
    try:
        zip_bytes = download_log_zip(file_row['url'])
        zf = zipfile.ZipFile(BytesIO(zip_bytes))
    except Exception:
        return None

    temperature_series = []
    fallback_temperature_series = []
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            base = Path(info.filename).name
            if base.startswith('android_'):
                temperature_series.extend(parse_android_pot_temperature_series(text_from_zip_member(zf, info, max_bytes=16 * 1024 * 1024)))
            elif base == 'temperature.log':
                fallback_temperature_series = parse_temperature_series(text_from_zip_member(zf, info, max_bytes=16 * 1024 * 1024))
    temperature_series.sort(key=lambda row: row['ts'])
    if not temperature_series and fallback_temperature_series:
        temperature_series = fallback_temperature_series
    if not temperature_series:
        return None

    payload = {
        'version': 1,
        'file': {
            'id': file_row.get('id'),
            'file_name': file_row.get('file_name'),
            'create_time': file_row.get('create_time'),
            'file_length': file_row.get('file_length'),
        },
        'coverage': {
            'start': temperature_series[0]['ts'].isoformat(sep=' '),
            'end': temperature_series[-1]['ts'].isoformat(sep=' '),
            'sample_count': len(temperature_series),
            'temperature_unit': 'android_app 温度字段第3位，单位 ℃；无安卓温度时回退 temperature.log 原始值 / 10 ℃',
        },
        'series': [{k: v for k, v in row.items() if k != 'ts'} for row in temperature_series],
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        pass
    return {'file': payload['file'], 'coverage': payload['coverage'], 'series': temperature_series}

def find_temperature_series_for_window(sn, window_start, window_end, max_files=12):
    rows = fetch_all(
        """
        SELECT id, sn, file_name, file_length, pic AS url, type, create_time, update_time, cos_deleted
        FROM machine_ftp
        WHERE sn = %s AND cos_deleted = 0
          AND create_time >= %s AND create_time <= %s
        ORDER BY create_time DESC
        LIMIT %s
        """,
        (sn, window_start - timedelta(days=2), window_end + timedelta(days=10), max_files),
        source=True,
        database='btyc',
    )
    if not rows:
        rows = fetch_all(
            """
            SELECT id, sn, file_name, file_length, pic AS url, type, create_time, update_time, cos_deleted
            FROM machine_ftp
            WHERE sn = %s AND cos_deleted = 0
            ORDER BY create_time DESC
            LIMIT %s
            """,
            (sn, max_files),
            source=True,
            database='btyc',
        )
    for row in rows:
        payload = cached_temperature_series_from_file(row)
        if not payload or not payload.get('series'):
            continue
        coverage_start = payload['series'][0]['ts']
        coverage_end = payload['series'][-1]['ts']
        if coverage_start <= window_end and coverage_end >= window_start:
            return payload
    return None

def cooking_temperature_summary_from_series(series, cook_start, cook_end):
    if not series or not cook_start or not cook_end:
        return {'covered': False, 'status': '无温度样本'}
    window_start = cook_start - timedelta(seconds=20)
    window_end = cook_end + timedelta(seconds=20)
    cook_series = [row for row in series if window_start <= row['ts'] <= window_end]
    values = [row.get('pot_temp') for row in cook_series if row.get('pot_temp') is not None]
    if not values:
        values = [
            value
            for row in cook_series
            for value in (row.get('temp_1'), row.get('temp_2'), row.get('temp_3'))
            if value is not None
        ]
    if not values:
        return {'covered': False, 'status': '作业窗口无温度样本', 'sample_count': len(cook_series)}
    return {
        'covered': True,
        'status': '已匹配',
        'sample_count': len(cook_series),
        'min_temp': round(min(values), 1),
        'max_temp': round(max(values), 1),
        'avg_temp': round(statistics.mean(values), 1),
        'start_temp': round(values[0], 1),
        'end_temp': round(values[-1], 1),
    }

def parse_main_board_actions(text, start_time, end_time):
    action_patterns = [
        ('add_oil', '加油/投油', re.compile(r'add oil|stop add oil', re.I)),
        ('add_water', '加水', re.compile(r'add water|stop add water', re.I)),
        ('roll_move', '翻锅/转锅', re.compile(r'roll mov|roll start|roll stop', re.I)),
        ('heat_info', '加热读取', re.compile(r'read heat info', re.I)),
        ('stir', '搅拌/电机', re.compile(r'stir|motor|pwm', re.I)),
        ('pump', '泵/投料', re.compile(r'pump|hall', re.I)),
        ('error', '异常/失败', re.compile(r'fail|error|err|timeout', re.I)),
    ]
    actions = []
    for line in text.splitlines():
        ts = parse_log_ts(line)
        if not ts or ts < start_time or ts > end_time:
            continue
        label = None
        kind = None
        for key, name, pattern in action_patterns:
            if pattern.search(line):
                kind = key
                label = name
                break
        if not label:
            continue
        actions.append({
            'time': ts.isoformat(sep=' '),
            'offset_seconds': int((ts - start_time).total_seconds()),
            'kind': kind,
            'label': label,
            'raw': line.strip()[:320],
        })
        if len(actions) >= 400:
            break
    return actions

def nearest_temperature_sample(series, target_time, max_delta_seconds=8):
    if not series:
        return None
    best = None
    best_delta = None
    for sample in series:
        delta = abs((sample['ts'] - target_time).total_seconds())
        if best_delta is None or delta < best_delta:
            best = sample
            best_delta = delta
            if delta == 0:
                break
    if best is None or best_delta is None or best_delta > max_delta_seconds:
        return None
    payload = {k: v for k, v in best.items() if k != 'ts'}
    payload['delta_seconds'] = round(best_delta, 1)
    return payload

def recipe_step_action_label(step):
    type_map = {1: '人工投料', 2: '自动投料', 3: '机器控制', 4: '等待/时间', 5: '洗锅', 6: '润锅'}
    try:
        type_value = int(step.get('type') or 0)
    except Exception:
        type_value = 0
    commands = str(step.get('commands') or '').strip()
    return commands or type_map.get(type_value, f"步骤{type_value}")

def build_cook_temperature_analysis(sn, file_id=None):
    real_sn, _ = resolve_sn(sn)
    if file_id:
        file_row = fetch_one(
            "SELECT id, sn, file_name, file_length, pic AS url, type, create_time, update_time, cos_deleted "
            "FROM machine_ftp WHERE id = %s AND sn = %s LIMIT 1",
            (file_id, real_sn),
            source=True,
            database='btyc',
        )
    else:
        file_row = fetch_one(
            "SELECT id, sn, file_name, file_length, pic AS url, type, create_time, update_time, cos_deleted "
            "FROM machine_ftp WHERE sn = %s AND cos_deleted = 0 ORDER BY create_time DESC LIMIT 1",
            (real_sn,),
            source=True,
            database='btyc',
        )
    if not file_row or not file_row.get('url'):
        raise HTTPException(status_code=404, detail="Log file not found")
    if file_row.get('cos_deleted'):
        raise HTTPException(status_code=410, detail="Log file has been deleted from COS")

    zip_bytes = download_log_zip(file_row['url'])
    try:
        zf = zipfile.ZipFile(BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Downloaded log file is not a valid zip")

    temperature_series = []
    fallback_temperature_series = []
    main_board_text = ''
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            base = Path(info.filename).name
            if base.startswith('android_'):
                temperature_series.extend(parse_android_pot_temperature_series(text_from_zip_member(zf, info, max_bytes=16 * 1024 * 1024)))
            elif base == 'temperature.log':
                fallback_temperature_series = parse_temperature_series(text_from_zip_member(zf, info, max_bytes=16 * 1024 * 1024))
            elif base == 'main_board.log':
                main_board_text = text_from_zip_member(zf, info, max_bytes=16 * 1024 * 1024)
    temperature_series.sort(key=lambda row: row['ts'])
    if not temperature_series and fallback_temperature_series:
        temperature_series = fallback_temperature_series
    if not temperature_series:
        raise HTTPException(status_code=404, detail="No usable temperature samples found")

    coverage_start = temperature_series[0]['ts']
    coverage_end = temperature_series[-1]['ts']
    latest_overall = fetch_one(
        "SELECT id, recipe_id, recipe_name, time AS duration_seconds, create_time, end_time, whether, manual "
        "FROM sop_machinelog WHERE sn = %s ORDER BY create_time DESC LIMIT 1",
        (real_sn,),
        source=True,
        database='btyc',
    )
    cook_log = fetch_one(
        "SELECT id, recipe_id, recipe_name, time AS duration_seconds, create_time, end_time, whether, manual "
        "FROM sop_machinelog WHERE sn = %s AND recipe_id IS NOT NULL AND recipe_id != 0 "
        "AND whether = 2 AND create_time BETWEEN %s AND %s ORDER BY create_time DESC LIMIT 1",
        (real_sn, coverage_start, coverage_end),
        source=True,
        database='btyc',
    )
    if not cook_log:
        cook_log = fetch_one(
            "SELECT id, recipe_id, recipe_name, time AS duration_seconds, create_time, end_time, whether, manual "
            "FROM sop_machinelog WHERE sn = %s AND create_time BETWEEN %s AND %s ORDER BY create_time DESC LIMIT 1",
            (real_sn, coverage_start, coverage_end),
            source=True,
            database='btyc',
        )
    if not cook_log:
        raise HTTPException(status_code=404, detail="No production record found in selected log coverage")

    duration = int(cook_log.get('duration_seconds') or 0)
    cook_end = cook_log.get('create_time')
    cook_start = cook_end - timedelta(seconds=duration) if cook_end and duration else cook_log.get('end_time') or cook_end
    window_start = cook_start - timedelta(seconds=20)
    window_end = cook_end + timedelta(seconds=20)
    cook_series = [row for row in temperature_series if window_start <= row['ts'] <= window_end]
    values = [row['pot_temp'] for row in cook_series if row.get('pot_temp') is not None]
    if not values:
        values = [value for row in cook_series for value in (row.get('temp_1'), row.get('temp_2'), row.get('temp_3')) if value is not None]

    steps = []
    if cook_log.get('recipe_id'):
        detail = fetch_one(
            "SELECT recipe_id, cook_time, cook_steps FROM recipe_detail WHERE recipe_id = %s LIMIT 1",
            (cook_log.get('recipe_id'),),
            source=True,
            database='manage_backend',
        )
        for index, step in enumerate(parse_json_array(detail.get('cook_steps') if detail else None), start=1):
            offset = int(float(step.get('time') or 0))
            target = cook_start + timedelta(seconds=offset)
            steps.append({
                'step_index': index,
                'offset_seconds': offset,
                'target_time': target.isoformat(sep=' '),
                'type': step.get('type'),
                'automatic': step.get('automatic'),
                'power': step.get('power'),
                'speed': step.get('speed'),
                'position': step.get('position'),
                'commands': recipe_step_action_label(step),
                'temperature': nearest_temperature_sample(temperature_series, target),
            })

    main_actions = parse_main_board_actions(main_board_text, cook_start, cook_end) if main_board_text else []
    for action in main_actions[:120]:
        ts = datetime.strptime(action['time'], "%Y-%m-%d %H:%M:%S")
        action['temperature'] = nearest_temperature_sample(temperature_series, ts)

    newer_uncovered = bool(latest_overall and latest_overall.get('create_time') and latest_overall.get('create_time') > coverage_end)
    stride = max(1, len(cook_series) // 240) if cook_series else 1
    return {
        'sn': real_sn,
        'file': {
            'id': file_row.get('id'),
            'file_name': file_row.get('file_name'),
            'create_time': file_row.get('create_time'),
            'file_length': file_row.get('file_length'),
        },
        'coverage': {
            'start': coverage_start.isoformat(sep=' '),
            'end': coverage_end.isoformat(sep=' '),
            'sample_count': len(temperature_series),
            'temperature_unit': 'android_app 温度字段第3位，单位 ℃；无安卓温度时回退 temperature.log 原始值 / 10 ℃',
            'newer_production_not_covered': newer_uncovered,
            'latest_production_time': latest_overall.get('create_time') if latest_overall else None,
        },
        'cook': {
            **cook_log,
            'start_time': cook_start.isoformat(sep=' ') if cook_start else None,
            'end_time_calc': cook_end.isoformat(sep=' ') if cook_end else None,
        },
        'summary': {
            'sample_count': len(cook_series),
            'min_temp': round(min(values), 1) if values else None,
            'max_temp': round(max(values), 1) if values else None,
            'avg_temp': round(statistics.mean(values), 1) if values else None,
        },
        'steps': steps,
        'main_board_actions': main_actions[:120],
        'series': [{k: v for k, v in row.items() if k != 'ts'} for row in cook_series[::stride]],
    }

def count_log_keywords(text, kind):
    definitions = {
        'mcu_debug': {
            '加热状态查询': 'getHeaterCurStatus',
            '通讯发包/MCU': 'send to mcu',
            '错误字样error': 'error',
            '超时timeout': 'timeout',
            '温控': 'tempctr',
            '加热错误码查询': 'heaterGetErrCode',
        },
        'main_board': {
            '主控加热': 'sta start',
            '加水': 'add water',
            '加油': 'add oil',
            '加蚝油': 'add oyster',
            '翻锅/倾锅': 'lean',
            '转锅速度': 'roll speed',
            '温控': 'tempctr',
            '无FrameID': 'no FrameID',
            '失败fail': 'fail',
        },
        'android_app': {
            '水淀粉/SAUCE_STARCH': 'SAUCE_STARCH',
            '液料/SAUCE_NEW': 'SAUCE_NEW',
            '网络请求': 'network request',
            '发送指令sendMsg': 'sendMsg',
            '读取结果readResult': 'readResult',
            '错误字样error': 'error',
            '数据采集DataCollect': 'DataCollectManager',
        },
    }
    counts = {}
    lower = text.lower()
    for label, needle in definitions.get(kind, {}).items():
        counts[label] = lower.count(needle.lower())
    return {k: v for k, v in counts.items() if v}

def top_log_patterns(text, limit=10):
    counter = Counter()
    for line in text.splitlines()[:80000]:
        msg = re.sub(r'^\[[^\]]+\]\s*', '', line.strip())
        msg = re.sub(r'0x[0-9a-fA-F]+', '0x#', msg)
        msg = re.sub(r'\d+', '#', msg)[:100]
        if msg:
            counter[msg] += 1
    return [{'pattern': pattern, 'count': count} for pattern, count in counter.most_common(limit)]

def build_log_analysis(file_row, zip_bytes):
    try:
        zf = zipfile.ZipFile(BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Downloaded log file is not a valid zip")

    file_summary = []
    keyword_counts = []
    top_patterns = []
    fault_matches = []
    oil = None
    temperature = None
    suggestions = []
    with zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        for info in infos:
            base = Path(info.filename).name
            kind = classify_log_file(base)
            text = text_from_zip_member(zf, info)
            first = None
            last = None
            line_count = 0
            for line in text.splitlines():
                line_count += 1
                ts = parse_log_ts(line)
                if ts:
                    first = first or ts
                    last = ts
            file_summary.append({
                'file_name': base,
                'kind': kind,
                'kind_label': log_kind_label(kind),
                'size_mb': round(info.file_size / 1024 / 1024, 2),
                'lines': line_count,
                'first_time': first.isoformat(sep=' ') if first else None,
                'last_time': last.isoformat(sep=' ') if last else None,
            })
            fault_matches.extend(extract_fault_matches(text, base, kind))
            if kind == 'other':
                continue
            if kind == 'oildrum_board':
                oil = analyze_oildrum_text(text)
            elif kind == 'temperature':
                temperature = analyze_temperature_text(text)
            counts = count_log_keywords(text, kind)
            for label, count in counts.items():
                keyword_counts.append({'file_name': base, 'kind': kind, 'category': label, 'count': count})
            top_patterns.extend({'file_name': base, 'kind': kind, **row} for row in top_log_patterns(text, limit=6))

    if oil and oil.get('bucket_over_100_count', 0):
        suggestions.append('油桶板日志存在桶温超过 100℃ 的采样，建议重点核对桶温字段定义、加热目标值和是否存在局部过冲。')
    if oil and oil.get('pipe_max') and oil['pipe_max'] >= 60:
        suggestions.append('油路/管路推定温度达到 60℃ 左右，建议与管材长期耐温、泵附近抖动和加热丝接触位置一起评估。')
    if any(row['category'] == '水淀粉/SAUCE_STARCH' for row in keyword_counts):
        suggestions.append('日志中可识别水淀粉资源动作，后续可以把它纳入设备资源筛查，而不只看猪油/油桶。')
    if oil and oil.get('hall_abnormal_count'):
        suggestions.append('猪油桶日志存在霍尔缺相检测异常记录，后续可以结合投油动作、持续时间和电机占空比进一步定位。')
    if fault_matches:
        suggestions.append('日志文本中命中了故障码清单，可先按优先级、模块和命中次数查看是否与现场问题一致。')
    if not suggestions:
        suggestions.append('该日志包已完成结构化解析，建议先从文件摘要、动作计数和温度统计确认哪些字段对排障最有价值。')

    return {
        'file': {
            'id': file_row.get('id'),
            'sn': file_row.get('sn'),
            'file_name': file_row.get('file_name'),
            'file_length': file_row.get('file_length'),
            'create_time': file_row.get('create_time'),
            'update_time': file_row.get('update_time'),
        },
        'analysis_version': LOG_ANALYSIS_VERSION,
        'generated_at': int(time.time()),
        'zip_size_mb': round(len(zip_bytes) / 1024 / 1024, 2),
        'file_summary': sorted(file_summary, key=lambda row: row['file_name']),
        'category_summary': build_log_category_summary(file_summary),
        'keyword_counts': sorted(keyword_counts, key=lambda row: row['count'], reverse=True)[:120],
        'top_patterns': top_patterns[:160],
        'fault_matches': sorted(fault_matches, key=lambda row: (row.get('priority') or '', -row.get('count', 0)))[:160],
        'oil_thermal': oil,
        'temperature': temperature,
        'suggestions': suggestions,
        'log_specs': log_specs_payload(),
        'field_assumptions': {
            'oildrum_bucket_temp': 'oildrum_board.log dev status 第 1 个数 / 10，按《猪油桶相关日志说明》确认为油温度',
            'oildrum_pipe_temp': 'oildrum_board.log dev status 第 2 个数 / 10，按《猪油桶相关日志说明》确认为油管温度',
            'oildrum_motor_rpm': 'oildrum_board.log dev status 第 4 个数为投料电机速度 RPM',
            'oildrum_heater_pwm': 'oildrum_board.log dev status 第 5 个数为油桶加热 PWM 占空比',
        },
    }

def build_device_report(sn: str):
    real_sn, info = resolve_sn(sn)
    customer = get_company_info(info.get('company_id'))
    software_info = get_device_software_info(real_sn)

    log_summary = fetch_one(
        "SELECT COUNT(*) AS total_logs, MIN(create_time) AS first_time, MAX(create_time) AS last_time "
        "FROM sop_machinelog WHERE sn = %s",
        (real_sn,),
        source=True,
        database='btyc',
    )
    total_logs = int(log_summary['total_logs'] or 0)
    monthly_summary = fetch_all(
        "SELECT DATE_FORMAT(create_time, '%%Y-%%m') AS month, COUNT(*) AS total_logs, "
        "COUNT(DISTINCT recipe_id) AS recipe_count, MIN(create_time) AS first_time, "
        "MAX(create_time) AS last_time, SUM(CAST(time AS SIGNED)) AS total_duration_seconds, "
        "ROUND(AVG(CAST(time AS SIGNED)), 1) AS avg_duration_seconds "
        "FROM sop_machinelog WHERE sn = %s GROUP BY month ORDER BY month",
        (real_sn,),
        source=True,
        database='btyc',
    )
    if total_logs > MAX_DEVICE_LOGS:
        logs = fetch_all(
            "SELECT id, recipe_id, recipe_name, time AS duration_seconds, create_time, end_time, "
            "username, data_time, comment, whether, manual, component, uuid "
            "FROM sop_machinelog WHERE sn = %s ORDER BY create_time DESC LIMIT %s",
            (real_sn, MAX_DEVICE_LOGS),
            source=True,
            database='btyc',
        )
        logs = list(reversed(logs))
    else:
        logs = fetch_all(
            "SELECT id, recipe_id, recipe_name, time AS duration_seconds, create_time, end_time, "
            "username, data_time, comment, whether, manual, component, uuid "
            "FROM sop_machinelog WHERE sn = %s ORDER BY create_time ASC",
            (real_sn,),
            source=True,
            database='btyc',
        )

    duration_stat_rows = fetch_all(
        "SELECT recipe_id, COUNT(*) AS sample_count, "
        "ROUND(AVG(CAST(time AS SIGNED)), 1) AS avg_duration_seconds, "
        "MIN(CAST(time AS SIGNED)) AS min_duration_seconds, "
        "MAX(CAST(time AS SIGNED)) AS max_duration_seconds "
        "FROM sop_machinelog WHERE sn = %s AND recipe_id IS NOT NULL AND recipe_id != 0 "
        "AND time IS NOT NULL GROUP BY recipe_id",
        (real_sn,),
        source=True,
        database='btyc',
    )
    duration_stats = {row['recipe_id']: row for row in duration_stat_rows}
    for log in logs:
        log.update(classify_production_behavior(log, duration_stats))

    intervals = []
    last_time = None
    for log in logs:
        curr = log['create_time']
        gap = None
        if last_time:
            delta = curr - last_time
            gap_hours = delta.total_seconds() / 3600
            gap = {
                'hours': round(gap_hours, 2),
                'days': delta.days,
                'label': format_gap(delta),
                'flag': 'LONG_DELAY' if gap_hours > 24 else 'NORMAL'
            }
        intervals.append({
            'id': log['id'],
            'create_time': curr,
            'recipe_name': log.get('recipe_name'),
            'gap': gap
        })
        last_time = curr

    recipe_usage_rows = fetch_all(
        "SELECT recipe_id, MAX(recipe_name) AS recipe_name, COUNT(*) AS cnt, "
        "SUM(CAST(time AS SIGNED)) AS total_duration_seconds, MIN(create_time) AS first_time, "
        "MAX(create_time) AS last_time FROM sop_machinelog "
        "WHERE sn = %s AND recipe_id IS NOT NULL AND recipe_id != 0 "
        "GROUP BY recipe_id ORDER BY cnt DESC",
        (real_sn,),
        source=True,
        database='btyc',
    )
    recipe_usage = {row['recipe_id']: row for row in recipe_usage_rows}
    recipe_ids = sorted(recipe_usage.keys())
    recipes = []
    recipe_archive = []
    has_lard = False
    if recipe_ids:
        placeholders = ','.join(['%s'] * len(recipe_ids))
        raw_recipes = fetch_all(
            f"SELECT id, name, group_name, type, steps_describe, ingredients_total_dosage FROM main_recipe WHERE id IN ({placeholders})",
            tuple(recipe_ids),
            source=True,
            database='manage_backend',
        )
        raw_details = fetch_all(
            f"SELECT recipe_id, cook_time, cook_steps, wash_steps, moisten_steps, cooking_ingredient "
            f"FROM recipe_detail WHERE recipe_id IN ({placeholders})",
            tuple(recipe_ids),
            source=True,
            database='manage_backend',
        )
        detail_by_recipe_id = {row['recipe_id']: row for row in raw_details}
        for r in raw_recipes:
            archive_item = recipe_resource_summary(r, detail_by_recipe_id.get(r['id']), recipe_usage)
            is_lard = archive_item['has_lard'] or '猪油' in str(r.get('name', '')) or '猪油' in str(r.get('steps_describe', ''))
            if is_lard: has_lard = True
            recipes.append({**r, 'has_lard': is_lard, 'execution_count': recipe_usage.get(r['id'], {}).get('cnt', 0)})
            recipe_archive.append(archive_item)

        found_ids = {r['id'] for r in raw_recipes}
        for missing_id in sorted(set(recipe_ids) - found_ids):
            usage = recipe_usage.get(missing_id, {})
            recipe_archive.append({
                'id': missing_id,
                'name': usage.get('recipe_name') or f'菜谱 {missing_id}',
                'category': '菜谱详情缺失',
                'execution_count': usage.get('cnt', 0),
                'total_duration_seconds': usage.get('total_duration_seconds', 0),
                'first_time': usage.get('first_time'),
                'last_time': usage.get('last_time'),
                'resources': [],
                'resource_flags': {},
                'steps': [],
                'has_lard': False,
            })

    faults = fetch_all(
        "SELECT id, create_time, module, second_level_error_details as details, deal_state "
        "FROM bytc_robot_malfunctions_log WHERE sn = %s ORDER BY create_time DESC LIMIT 200",
        (real_sn,),
        source=True,
        database='btyc',
    )

    maint = fetch_all(
        "SELECT id, create_time, status, mode, duration FROM robot_conservation_pot_log "
        "WHERE machine_code = %s ORDER BY create_time DESC LIMIT 200",
        (real_sn,),
        source=True,
        database='btyc',
    )
    device_logs = get_device_log_files(real_sn)

    recipe_archive = sorted(recipe_archive, key=lambda item: item.get('execution_count', 0), reverse=True)

    return {
        "info": info,
        "software": software_info,
        "customer": customer,
        "stats": {
            "sn": real_sn,
            "total_logs": total_logs,
            "returned_logs": len(logs),
            "first_time": log_summary['first_time'],
            "last_time": log_summary['last_time'],
            "truncated": total_logs > MAX_DEVICE_LOGS,
            "has_lard": has_lard,
        },
        "monthly_summary": monthly_summary,
        "logs": logs if len(logs) <= INLINE_LOG_LIMIT else logs[-INLINE_LOG_LIMIT:],
        "intervals": intervals if len(intervals) <= INLINE_LOG_LIMIT else intervals[-INLINE_LOG_LIMIT:],
        "recipes": recipes,
        "recipe_archive": recipe_archive,
        "recipe_category_summary": build_recipe_category_summary(recipe_archive),
        "faults": faults,
        "maintenance": maint,
        "device_logs": device_logs,
    }

def get_cached_report(sn: str, force_refresh: bool = False):
    normalized = sn.strip()
    cached = REPORT_CACHE.get(normalized)
    now = time.time()
    if not force_refresh and cached and now - cached['created_at'] < CACHE_TTL_SECONDS:
        report = cached['report']
        report['cache'] = {'hit': True, 'created_at': cached['created_at'], 'ttl_seconds': CACHE_TTL_SECONDS}
        return report

    if not force_refresh:
        disk_report = load_disk_report(normalized, now)
        if disk_report:
            real_sn = disk_report['stats']['sn']
            for key in set(candidate_sns(normalized) + [real_sn]):
                REPORT_CACHE[key] = {'created_at': disk_report['cache']['created_at'], 'report': disk_report}
            return disk_report

    report = build_device_report(normalized)
    real_sn = report['stats']['sn']
    for key in set(candidate_sns(normalized) + [real_sn]):
        REPORT_CACHE[key] = {'created_at': now, 'report': report}
    report['cache'] = {'hit': False, 'created_at': now, 'ttl_seconds': CACHE_TTL_SECONDS}
    save_disk_report(real_sn, report, now)
    return report

def cache_path(sn):
    digest = hashlib.sha256(sn.encode()).hexdigest()
    return CACHE_DIR / f"{digest}.json"

def load_disk_report(sn, now):
    for candidate in candidate_sns(sn):
        path = cache_path(candidate)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
            created_at = float(payload.get('created_at', 0))
            if now - created_at >= CACHE_TTL_SECONDS:
                continue
            report = payload.get('report')
            if not report:
                continue
            report['cache'] = {'hit': True, 'disk': True, 'created_at': created_at, 'ttl_seconds': CACHE_TTL_SECONDS}
            return report
        except Exception:
            path.unlink(missing_ok=True)
    return None

def save_disk_report(sn, report, created_at):
    serializable = dict(report)
    serializable.pop('cache', None)
    payload = {'created_at': created_at, 'report': serializable}
    path = cache_path(sn)
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str))

def get_device_month_detail(sn: str, month: str):
    if not re.match(r'^\d{4}-\d{2}$', month or ''):
        raise HTTPException(status_code=400, detail="Invalid month")
    real_sn, _ = resolve_sn(sn)
    start = datetime.strptime(f"{month}-01", "%Y-%m-%d")
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)

    summary = fetch_one(
        "SELECT COUNT(*) AS total_logs, COUNT(DISTINCT recipe_id) AS recipe_count, "
        "MIN(create_time) AS first_time, MAX(create_time) AS last_time, "
        "SUM(CAST(time AS SIGNED)) AS total_duration_seconds, ROUND(AVG(CAST(time AS SIGNED)), 1) AS avg_duration_seconds "
        "FROM sop_machinelog WHERE sn = %s AND create_time >= %s AND create_time < %s",
        (real_sn, start, end),
        source=True,
        database='btyc',
    ) or {}
    recipes = fetch_all(
        "SELECT recipe_id, MAX(recipe_name) AS recipe_name, COUNT(*) AS execution_count, "
        "SUM(CAST(time AS SIGNED)) AS total_duration_seconds, ROUND(AVG(CAST(time AS SIGNED)), 1) AS avg_duration_seconds, "
        "MIN(create_time) AS first_time, MAX(create_time) AS last_time "
        "FROM sop_machinelog WHERE sn = %s AND create_time >= %s AND create_time < %s "
        "GROUP BY recipe_id ORDER BY execution_count DESC, last_time DESC LIMIT 300",
        (real_sn, start, end),
        source=True,
        database='btyc',
    )
    logs = fetch_all(
        "SELECT id, recipe_id, recipe_name, time AS duration_seconds, create_time, end_time, username, data_time, comment "
        "FROM sop_machinelog WHERE sn = %s AND create_time >= %s AND create_time < %s "
        "ORDER BY create_time DESC LIMIT %s",
        (real_sn, start, end, MAX_DEVICE_LOGS),
        source=True,
        database='btyc',
    )
    logs = list(reversed(logs))
    total_logs = int(summary.get('total_logs') or 0)
    return {
        "sn": real_sn,
        "month": month,
        "summary": {
            "total_logs": total_logs,
            "returned_logs": len(logs),
            "truncated": total_logs > len(logs),
            "recipe_count": int(summary.get('recipe_count') or 0),
            "first_time": summary.get('first_time'),
            "last_time": summary.get('last_time'),
            "total_duration_seconds": int(summary.get('total_duration_seconds') or 0),
            "avg_duration_seconds": summary.get('avg_duration_seconds'),
        },
        "recipes": recipes,
        "logs": logs,
    }

RECIPE_SEARCH_SCOPES = {
    'customer': '客户维度',
    'device': '设备号维度',
    'active_machine': '当日/区间使用机器',
}
RECIPE_SEARCH_CACHE_VERSION = 1
RECIPE_ANALYSIS_CACHE_VERSION = 4

def parse_recipe_search_date(value, default_date, end=False):
    raw = (value or '').strip()
    if not raw:
        day = default_date
    else:
        try:
            day = datetime.strptime(raw[:10], '%Y-%m-%d').date()
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式需要是 YYYY-MM-DD")
    if end:
        return datetime.combine(day, datetime.max.time().replace(microsecond=0))
    return datetime.combine(day, datetime.min.time())

def normalize_recipe_search_params(scope, keyword, recipe_keyword, start_date, end_date, limit):
    clean_scope = (scope or 'customer').strip()
    if clean_scope not in RECIPE_SEARCH_SCOPES:
        raise HTTPException(status_code=400, detail="不支持的检索维度")

    today = datetime.now().date()
    start_dt = parse_recipe_search_date(start_date, today - timedelta(days=7), end=False)
    end_dt = parse_recipe_search_date(end_date, today, end=True)
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")

    span_days = (end_dt.date() - start_dt.date()).days + 1
    if span_days > MAX_RECIPE_SEARCH_DAYS:
        raise HTTPException(status_code=400, detail=f"单次检索最多支持 {MAX_RECIPE_SEARCH_DAYS} 天，请缩小时间范围")

    clean_keyword = (keyword or '').strip()
    clean_recipe_keyword = (recipe_keyword or '').strip()
    if clean_scope in {'customer', 'device'} and not clean_keyword:
        raise HTTPException(status_code=400, detail="客户/设备号维度需要填写模糊关键词")
    if clean_scope == 'active_machine' and not clean_keyword and not clean_recipe_keyword and span_days > 7:
        raise HTTPException(status_code=400, detail="空关键词查询使用机器最多支持 7 天，请缩小时间范围或补充关键词")

    capped_limit = max(20, min(int(limit or 200), MAX_RECIPE_SEARCH_LIMIT))
    return {
        'version': RECIPE_SEARCH_CACHE_VERSION,
        'scope': clean_scope,
        'scope_label': RECIPE_SEARCH_SCOPES[clean_scope],
        'keyword': clean_keyword,
        'recipe_keyword': clean_recipe_keyword,
        'start_date': start_dt.date().isoformat(),
        'end_date': end_dt.date().isoformat(),
        'start_time': start_dt,
        'end_time': end_dt,
        'span_days': span_days,
        'limit': capped_limit,
    }

def recipe_search_cache_key(params):
    payload = {
        'version': RECIPE_SEARCH_CACHE_VERSION,
        'scope': params['scope'],
        'keyword': params['keyword'],
        'recipe_keyword': params['recipe_keyword'],
        'start_date': params['start_date'],
        'end_date': params['end_date'],
        'limit': params['limit'],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def recipe_search_cache_path(key):
    cache_dir = CACHE_DIR / 'recipe_search'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f'{key}.json'

def load_cached_recipe_search(params, now):
    key = recipe_search_cache_key(params)
    path = recipe_search_cache_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        created_at = float(payload.get('created_at', 0))
        if now - created_at >= RECIPE_SEARCH_CACHE_TTL_SECONDS:
            return None
        result = payload.get('result')
        if not result:
            return None
        result['cache'] = {
            'hit': True,
            'disk': True,
            'created_at': created_at,
            'ttl_seconds': RECIPE_SEARCH_CACHE_TTL_SECONDS,
            'cache_key': key,
        }
        return result
    except Exception:
        path.unlink(missing_ok=True)
        return None

def save_cached_recipe_search(params, result, created_at):
    key = recipe_search_cache_key(params)
    serializable = dict(result)
    serializable.pop('cache', None)
    recipe_search_cache_path(key).write_text(json.dumps({
        'created_at': created_at,
        'params': {
            'scope': params['scope'],
            'keyword': params['keyword'],
            'recipe_keyword': params['recipe_keyword'],
            'start_date': params['start_date'],
            'end_date': params['end_date'],
            'limit': params['limit'],
        },
        'result': serializable,
    }, ensure_ascii=False, default=str))
    return key

def recipe_analysis_cache_key(params, recipe_id=None, recipe_name=''):
    payload = {
        'version': RECIPE_ANALYSIS_CACHE_VERSION,
        'type': 'recipe_analysis',
        'scope': params['scope'],
        'keyword': params['keyword'],
        'recipe_keyword': params['recipe_keyword'],
        'start_date': params['start_date'],
        'end_date': params['end_date'],
        'limit': params['limit'],
        'recipe_id': recipe_id,
        'recipe_name': recipe_name,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def recipe_analysis_cache_path(key):
    cache_dir = CACHE_DIR / 'recipe_analysis'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f'{key}.json'

def get_cached_recipe_analysis(params, recipe_id=None, recipe_name='', force_refresh=False):
    key = recipe_analysis_cache_key(params, recipe_id=recipe_id, recipe_name=recipe_name)
    path = recipe_analysis_cache_path(key)
    now = time.time()
    if not force_refresh and path.exists():
        try:
            payload = json.loads(path.read_text())
            created_at = float(payload.get('created_at') or 0)
            if now - created_at < RECIPE_SEARCH_CACHE_TTL_SECONDS and payload.get('result'):
                result = payload['result']
                result['cache'] = {
                    'hit': True,
                    'disk': True,
                    'created_at': created_at,
                    'ttl_seconds': RECIPE_SEARCH_CACHE_TTL_SECONDS,
                    'cache_key': key,
                }
                return result
        except Exception:
            path.unlink(missing_ok=True)
    result = build_recipe_analysis_result(params, recipe_id=recipe_id, recipe_name=recipe_name)
    serializable = dict(result)
    serializable.pop('cache', None)
    path.write_text(json.dumps({'created_at': now, 'result': serializable}, ensure_ascii=False, default=str))
    result['cache'] = {
        'hit': False,
        'created_at': now,
        'ttl_seconds': RECIPE_SEARCH_CACHE_TTL_SECONDS,
        'cache_key': key,
    }
    return result

ANALYTICS_QUERY_TTL_SECONDS = int(os.getenv('ANALYTICS_QUERY_TTL_SECONDS', str(7 * 24 * 3600)))
ANALYTICS_OWNER_BATCH_SIZE = int(os.getenv('ANALYTICS_OWNER_BATCH_SIZE', '100'))
ANALYTICS_MAX_OWNERS = int(os.getenv('ANALYTICS_MAX_OWNERS', '50000'))
ANALYTICS_CACHE_DIR = CACHE_DIR / 'analytics'
ANALYTICS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
ANALYTICS_JOB_THREADS = {}

def parse_analytics_date(value, default_date, end=False):
    raw = (value or '').strip()
    day = default_date if not raw else datetime.strptime(raw[:10], '%Y-%m-%d').date()
    if end:
        return datetime.combine(day, datetime.max.time().replace(microsecond=0))
    return datetime.combine(day, datetime.min.time())

def normalize_recipe_top_params(payload: RecipeTopJobRequest):
    today = datetime.now().date()
    start_dt = parse_analytics_date(payload.start_date, today - timedelta(days=180), end=False)
    end_dt = parse_analytics_date(payload.end_date, today, end=True)
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    span_days = (end_dt.date() - start_dt.date()).days + 1
    if span_days > 366:
        raise HTTPException(status_code=400, detail="Top 榜单次最多支持 366 天")
    top_n = max(50, min(int(payload.top_n or 500), 1000))
    sort_by = payload.sort_by if payload.sort_by in {'cooking_count', 'device_count', 'customer_count', 'total_duration_seconds'} else 'cooking_count'
    return {
        'query_type': 'recipe_top',
        'start_date': start_dt.date().isoformat(),
        'end_date': end_dt.date().isoformat(),
        'start_time': start_dt,
        'end_time': end_dt,
        'span_days': span_days,
        'top_n': top_n,
        'sort_by': sort_by,
        'recipe_keyword': (payload.recipe_keyword or '').strip(),
        'customer_keyword': (payload.customer_keyword or '').strip(),
        'sn': (payload.sn or '').strip(),
        'region': (payload.region or '').strip(),
        'category': (payload.category or '').strip(),
        'resource_type': (payload.resource_type or '').strip(),
        'stat_object': (payload.stat_object or 'all').strip(),
    }

def analytics_params_hash(params):
    stable = {k: v for k, v in params.items() if k not in {'start_time', 'end_time'}}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

def analytics_result_path(job_id):
    return ANALYTICS_CACHE_DIR / f'{job_id}.json'

def analytics_xlsx_path(job_id):
    return ANALYTICS_CACHE_DIR / f'{job_id}.xlsx'

def rowdict(row):
    return dict(row) if row else None

def get_analytics_job(job_id):
    with AUDIT_LOCK, audit_conn() as conn:
        row = conn.execute("SELECT * FROM analytics_query_jobs WHERE job_id = ?", (job_id,)).fetchone()
    job = rowdict(row)
    if job and job.get('params_json'):
        job['params'] = json.loads(job['params_json'])
    return job

def find_reusable_analytics_job(query_type, params_hash, now):
    with AUDIT_LOCK, audit_conn() as conn:
        row = conn.execute(
            "SELECT * FROM analytics_query_jobs WHERE query_type = ? AND params_hash = ? "
            "AND status IN ('PENDING','RUNNING','COMPLETED') "
            "AND (cache_expires_at IS NULL OR cache_expires_at > ?) "
            "ORDER BY created_at DESC LIMIT 1",
            (query_type, params_hash, now),
        ).fetchone()
    return rowdict(row)

def insert_analytics_job(query_type, params_hash, params, username):
    job_id = f"{query_type}_{uuid.uuid4().hex[:16]}"
    now = int(time.time())
    with AUDIT_LOCK, audit_conn() as conn:
        conn.execute(
            "INSERT INTO analytics_query_jobs(job_id, query_type, params_json, params_hash, status, stage, progress, created_by, created_at, cache_expires_at) "
            "VALUES (?, ?, ?, ?, 'PENDING', '排队中', 0, ?, ?, ?)",
            (job_id, query_type, json.dumps(params, ensure_ascii=False, default=str), params_hash, username, now, now + ANALYTICS_QUERY_TTL_SECONDS),
        )
        conn.commit()
    return job_id

def update_analytics_job(job_id, **fields):
    if not fields:
        return
    assignments = ', '.join([f"{key} = ?" for key in fields])
    values = list(fields.values()) + [job_id]
    with AUDIT_LOCK, audit_conn() as conn:
        conn.execute(f"UPDATE analytics_query_jobs SET {assignments} WHERE job_id = ?", values)
        conn.commit()

def start_analytics_thread(job_id, params, username):
    if job_id in ANALYTICS_JOB_THREADS and ANALYTICS_JOB_THREADS[job_id].is_alive():
        return
    thread = threading.Thread(target=run_recipe_top_job, args=(job_id, params, username), daemon=True)
    ANALYTICS_JOB_THREADS[job_id] = thread
    thread.start()

def resolve_recipe_top_owners(params):
    from_sql = "FROM btyc.sop_robot r LEFT JOIN btyc.ums_company c ON r.company_id = c.id"
    conditions = ["r.company_id IS NOT NULL", "r.company_id <> 0"]
    args = []
    if params.get('customer_keyword'):
        like = f"%{params['customer_keyword']}%"
        conditions.append("(c.common_name LIKE %s OR c.company_name LIKE %s OR c.geo_cityname LIKE %s OR c.geo_pname LIKE %s)")
        args.extend([like] * 4)
    if params.get('sn'):
        conditions.append("r.machinecode LIKE %s")
        args.append(f"%{params['sn']}%")
    if params.get('region'):
        like = f"%{params['region']}%"
        conditions.append("(c.geo_cityname LIKE %s OR c.geo_pname LIKE %s OR c.area_code LIKE %s)")
        args.extend([like] * 3)
    rows = fetch_all(
        f"SELECT DISTINCT r.company_id AS owner {from_sql} WHERE {' AND '.join(conditions)} LIMIT %s",
        tuple(args + [ANALYTICS_MAX_OWNERS]),
        source=True,
        database='btyc',
    )
    return [int(row['owner']) for row in rows if row.get('owner')]

def owner_chunks(owners):
    for idx in range(0, len(owners), ANALYTICS_OWNER_BATCH_SIZE):
        yield owners[idx:idx + ANALYTICS_OWNER_BATCH_SIZE]

def recipe_top_owner_sql(params, owners):
    placeholders = ','.join(['%s'] * len(owners))
    conditions = [f"l.owner IN ({placeholders})", "l.mac_time >= %s", "l.mac_time <= %s", "l.recipe_id IS NOT NULL", "l.recipe_id <> 0"]
    args = [*owners, params['start_date'], params['end_date']]
    if params.get('recipe_keyword'):
        like = f"%{params['recipe_keyword']}%"
        conditions.append("(l.recipe_name LIKE %s OR mr.name LIKE %s OR mr.group_name LIKE %s OR CAST(l.recipe_id AS CHAR) LIKE %s)")
        args.extend([like] * 4)
    if params.get('sn'):
        conditions.append("l.sn LIKE %s")
        args.append(f"%{params['sn']}%")
    if params.get('category'):
        conditions.append("mr.group_name LIKE %s")
        args.append(f"%{params['category']}%")
    sql = f"""
        SELECT l.recipe_id,
               COALESCE(MAX(mr.name), MAX(l.recipe_name), CONCAT('菜谱', l.recipe_id)) AS recipe_name,
               COALESCE(MAX(mr.group_name), '未分类') AS category,
               MAX(mr.type) AS recipe_type,
               COUNT(*) AS cooking_count,
               COUNT(DISTINCT l.sn) AS device_count,
               COUNT(DISTINCT l.owner) AS customer_count,
               MIN(l.create_time) AS first_time,
               MAX(l.create_time) AS last_time,
               SUM(CAST(l.time AS SIGNED)) AS total_duration_seconds,
               ROUND(AVG(CAST(l.time AS SIGNED)), 1) AS avg_duration_seconds
        FROM btyc.sop_machinelog l FORCE INDEX(idx_owner_mac_time)
        LEFT JOIN manage_backend.main_recipe mr ON l.recipe_id = mr.id
        WHERE {' AND '.join(conditions)}
        GROUP BY l.recipe_id
    """
    return sql, tuple(args)

def merge_recipe_top_partials(partial_rows, params, limit):
    merged = {}
    for row in partial_rows:
        rid = int(row['recipe_id'])
        item = merged.setdefault(rid, {
            'recipe_id': rid,
            'recipe_name': row.get('recipe_name'),
            'category': row.get('category') or '未分类',
            'recipe_type': row.get('recipe_type'),
            'cooking_count': 0,
            'device_count': 0,
            'customer_count': 0,
            'first_time': row.get('first_time'),
            'last_time': row.get('last_time'),
            'total_duration_seconds': 0,
        })
        item['recipe_name'] = item.get('recipe_name') or row.get('recipe_name')
        item['category'] = item.get('category') or row.get('category') or '未分类'
        item['cooking_count'] += int(row.get('cooking_count') or 0)
        item['device_count'] += int(row.get('device_count') or 0)
        item['customer_count'] += int(row.get('customer_count') or 0)
        if row.get('first_time') and (not item.get('first_time') or row['first_time'] < item['first_time']):
            item['first_time'] = row['first_time']
        if row.get('last_time') and (not item.get('last_time') or row['last_time'] > item['last_time']):
            item['last_time'] = row['last_time']
        item['total_duration_seconds'] += int(row.get('total_duration_seconds') or 0)
    rows = []
    for item in merged.values():
        count = max(1, int(item.get('cooking_count') or 0))
        item['avg_duration_seconds'] = round(item.get('total_duration_seconds', 0) / count, 1)
        rows.append(item)
    sort_key = params.get('sort_by') or 'cooking_count'
    return sorted(rows, key=lambda row: (row.get(sort_key) or 0, row.get('last_time') or ''), reverse=True)[:limit]

def ingredient_classes(row):
    text = ' '.join(str(row.get(k) or '') for k in ['ingredient_name', 'category_1', 'category_2', 'raw_json'])
    water = any(k in text for k in ['水', '清水', '饮用水', '开水', '冷水', '热水', '高汤', '汤汁', '汤底', '水淀粉'])
    oil = any(k in text for k in ['油', '猪油', '菜籽油', '色拉油', '橄榄油', 'lard', 'oil'])
    liquid = str(row.get('ingredient_type')) == '3' or oil or water or any(k in text for k in ['汁', '酱', '醋', '料酒', '生抽', '老抽', '蚝油', '汤', '液', '乳', '奶'])
    seasoning = any(k in text for k in ['盐', '精盐', '鸡精', '味精', '生抽', '老抽', '蚝油', '醋', '料酒', '酱', '粉'])
    return {'liquid': liquid, 'water': water, 'oil': oil, 'seasoning': seasoning}

def summarize_recipe_top_rows(top_rows, process_rows):
    ingredients = process_rows.get('ingredients', [])
    steps = process_rows.get('cook_steps', [])
    raw_rows = process_rows.get('raw_process', [])
    by_recipe = {int(row['recipe_id']): row for row in top_rows if row.get('recipe_id')}
    summary = {rid: {
        'ingredient_count': 0,
        'cook_step_count': 0,
        'has_detail': False,
        'liquid_feed_count': 0,
        'liquid_amount': 0,
        'water_feed_count': 0,
        'water_amount': 0,
        'oil_feed_count': 0,
        'oil_amount': 0,
        'seasoning_feed_count': 0,
        'seasoning_amount': 0,
    } for rid in by_recipe}
    for row in raw_rows:
        rid = int(row.get('recipe_id') or 0)
        if rid in summary:
            summary[rid]['ingredient_count'] = int(row.get('ingredient_count') or 0)
            summary[rid]['cook_step_count'] = int(row.get('cook_steps_count') or 0)
            summary[rid]['has_detail'] = not bool(row.get('detail_missing'))
    for row in steps:
        rid = int(row.get('recipe_id') or 0)
        if rid in summary:
            summary[rid]['cook_step_count'] = max(summary[rid]['cook_step_count'], int(row.get('step_index') or 0))
    for row in ingredients:
        rid = int(row.get('recipe_id') or 0)
        if rid not in summary:
            continue
        classes = ingredient_classes(row)
        amount = normalized_amount(row.get('dosage'), row.get('unit'))
        if classes['liquid']:
            summary[rid]['liquid_feed_count'] += 1
            if amount is not None:
                summary[rid]['liquid_amount'] += amount
        if classes['water']:
            summary[rid]['water_feed_count'] += 1
            if amount is not None:
                summary[rid]['water_amount'] += amount
        if classes['oil']:
            summary[rid]['oil_feed_count'] += 1
            if amount is not None:
                summary[rid]['oil_amount'] += amount
        if classes['seasoning']:
            summary[rid]['seasoning_feed_count'] += 1
            if amount is not None:
                summary[rid]['seasoning_amount'] += amount
        row.update({
            'is_liquid': classes['liquid'],
            'is_water': classes['water'],
            'is_oil': classes['oil'],
            'is_seasoning': classes['seasoning'],
            'normalized_amount': amount,
        })
    result = []
    for index, row in enumerate(top_rows, start=1):
        rid = int(row.get('recipe_id') or 0)
        stats = summary.get(rid, {})
        result.append({
            'rank': index,
            **row,
            **stats,
            'liquid_amount': round(stats.get('liquid_amount', 0), 2),
            'water_amount': round(stats.get('water_amount', 0), 2),
            'oil_amount': round(stats.get('oil_amount', 0), 2),
            'seasoning_amount': round(stats.get('seasoning_amount', 0), 2),
        })
    return result

def fetch_recipe_top_coverage(params, recipe_ids, owners):
    if not recipe_ids:
        return [], []
    placeholders = ','.join(['%s'] * len(recipe_ids))
    devices = []
    customers = []
    for chunk in owner_chunks(owners):
        owner_placeholders = ','.join(['%s'] * len(chunk))
        base_conditions = f"l.owner IN ({owner_placeholders}) AND l.mac_time >= %s AND l.mac_time <= %s AND l.recipe_id IN ({placeholders})"
        args = [*chunk, params['start_date'], params['end_date'], *recipe_ids]
        devices.extend(fetch_all(
            f"""
            SELECT l.recipe_id, l.sn, MAX(r.name) AS device_name, MAX(r.robot_type) AS robot_type,
                   MAX(r.latest_update_package) AS version,
                   COALESCE(MAX(c.common_name), MAX(c.company_name), '未知客户') AS customer_name,
                   COALESCE(MAX(c.geo_cityname), MAX(c.geo_pname), MAX(c.area_code), '') AS region,
                   COUNT(*) AS cooking_count, MIN(l.create_time) AS first_time, MAX(l.create_time) AS last_time
            FROM btyc.sop_machinelog l FORCE INDEX(idx_owner_mac_time)
            LEFT JOIN btyc.sop_robot r ON l.sn = r.machinecode
            LEFT JOIN btyc.ums_company c ON l.owner = c.id
            WHERE {base_conditions}
            GROUP BY l.recipe_id, l.sn
            """,
            tuple(args),
            source=True,
            database='btyc',
        ))
        customers.extend(fetch_all(
            f"""
            SELECT l.recipe_id, l.owner AS company_id,
                   COALESCE(MAX(c.common_name), MAX(c.company_name), '未知客户') AS customer_name,
                   COALESCE(MAX(c.geo_cityname), MAX(c.geo_pname), MAX(c.area_code), '') AS region,
                   COUNT(*) AS cooking_count, COUNT(DISTINCT l.sn) AS device_count,
                   MIN(l.create_time) AS first_time, MAX(l.create_time) AS last_time
            FROM btyc.sop_machinelog l FORCE INDEX(idx_owner_mac_time)
            LEFT JOIN btyc.ums_company c ON l.owner = c.id
            WHERE {base_conditions}
            GROUP BY l.recipe_id, l.owner
            """,
            tuple(args),
            source=True,
            database='btyc',
        ))
    return devices, customers

def build_recipe_top_result(params, job_id=None):
    owners = resolve_recipe_top_owners(params)
    if job_id:
        update_analytics_job(job_id, stage=f'查询生产日志（{len(owners)} 个 owner）', progress=18)
    partial_rows = []
    chunks = list(owner_chunks(owners))
    for index, chunk in enumerate(chunks, start=1):
        sql, args = recipe_top_owner_sql(params, chunk)
        partial_rows.extend(fetch_all(sql, args, source=True, database='btyc'))
        if job_id and (index == len(chunks) or index % 10 == 0):
            progress = 18 + int(32 * index / max(1, len(chunks)))
            update_analytics_job(job_id, stage=f'查询生产日志 {index}/{len(chunks)}', progress=progress)
    if job_id:
        update_analytics_job(job_id, stage='合并 TopN', progress=55)
    fetch_limit = min(max(params['top_n'] * 3, params['top_n']), 3000) if params.get('resource_type') else params['top_n']
    top_rows = merge_recipe_top_partials(partial_rows, params, fetch_limit)
    for row in top_rows:
        row['execution_count'] = row.get('cooking_count')
    if job_id:
        update_analytics_job(job_id, stage='读取菜谱详情', progress=62)
    top_rows = hydrate_recipe_search_resources(top_rows)
    if params.get('resource_type'):
        top_rows = [row for row in top_rows if params['resource_type'] in (row.get('resources') or [])][:params['top_n']]
    else:
        top_rows = top_rows[:params['top_n']]
    process_rows = fetch_recipe_process_export_rows(top_rows)
    if job_id:
        update_analytics_job(job_id, stage='统计投料与步骤', progress=72)
    summary = summarize_recipe_top_rows(top_rows, process_rows)
    recipe_ids = [int(row['recipe_id']) for row in summary if row.get('recipe_id')]
    if job_id:
        update_analytics_job(job_id, stage='读取设备/客户覆盖', progress=78)
    devices, customers = fetch_recipe_top_coverage(params, recipe_ids, owners)
    liquid_rows = [
        row for row in process_rows.get('ingredients', [])
        if row.get('is_liquid') or row.get('is_water') or row.get('is_oil')
    ]
    return {
        'params': {k: v for k, v in params.items() if k not in {'start_time', 'end_time'}},
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'summary': {
            'recipe_count': len(summary),
            'owner_count': len(owners),
            'device_coverage_rows': len(devices),
            'customer_coverage_rows': len(customers),
        },
        'top_recipes': summary,
        'liquid_water_ingredients': liquid_rows,
        'all_ingredients': process_rows.get('ingredients', []),
        'cook_steps': process_rows.get('cook_steps', []),
        'raw_process': process_rows.get('raw_process', []),
        'device_coverage': devices,
        'customer_coverage': customers,
        'rule_notes': [
            '液料优先按 btyc.base_ingredients.ingredinent_type = 3 判断，并用油/汁/酱/醋/料酒/生抽/老抽/蚝油/高汤/汤/液/乳/奶等关键词兜底。',
            '水按食材名、分类或原始字段中包含水、清水、饮用水、开水、冷水、热水、高汤、汤汁、汤底、水淀粉等关键词判断。',
            'g/克直接计入，kg/千克/公斤乘1000，L/升乘1000，ml/毫升保留原数值并保留原单位；不确定单位保留原值和原始JSON。',
        ],
    }

def build_recipe_top_workbook(result, job):
    wb = Workbook()
    wb.remove(wb.active)
    params = result.get('params', {})
    write_sheet(wb, '口径说明', [
        {'field': '查询类型', 'value': '菜谱 Top 榜与投料统计'},
        {'field': '开始日期', 'value': params.get('start_date')},
        {'field': '结束日期', 'value': params.get('end_date')},
        {'field': 'Top N', 'value': params.get('top_n')},
        {'field': '排序指标', 'value': params.get('sort_by')},
        {'field': '生成时间', 'value': result.get('generated_at')},
        {'field': '任务ID', 'value': job.get('job_id')},
        {'field': '缓存过期', 'value': datetime.fromtimestamp(job.get('cache_expires_at')).strftime('%Y-%m-%d %H:%M:%S') if job.get('cache_expires_at') else ''},
        {'field': '液料/水判断规则', 'value': '；'.join(result.get('rule_notes', []))},
    ], [('field', '字段'), ('value', '值')])
    write_sheet(wb, 'Top菜谱汇总', result.get('top_recipes', []), [
        ('rank', '排名'), ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '标准菜名/分类'),
        ('cooking_count', '烹饪次数'), ('device_count', '覆盖设备数'), ('customer_count', '覆盖客户数'),
        ('first_time', '首次烹饪时间'), ('last_time', '末次烹饪时间'),
        ('total_duration_seconds', '累计烹饪时长秒'), ('avg_duration_seconds', '平均烹饪时长秒'),
        ('liquid_feed_count', '液料投料次数'), ('liquid_amount', '液料克数/毫升数'),
        ('water_feed_count', '水投料次数'), ('water_amount', '水克数/毫升数'),
        ('oil_feed_count', '油投料次数'), ('oil_amount', '油克数/毫升数'),
        ('seasoning_feed_count', '调料投料次数'), ('seasoning_amount', '调料克数/毫升数'),
        ('ingredient_count', '配料项数量'), ('cook_step_count', '烹饪步骤数量'), ('has_detail', '是否有原始详情'), ('resources', '资源覆盖')
    ])
    ingredient_cols = [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('ingredient_index', '配料序号'),
        ('cooking_step_id', '关联烹饪步骤ID'), ('ingredient_id', '食材ID'), ('ingredient_name', '食材名称'),
        ('dosage', '原始用量'), ('unit', '原始单位'), ('normalized_amount', '折算克/毫升数'),
        ('is_liquid', '是否液料'), ('is_water', '是否水'), ('is_oil', '是否油'), ('is_seasoning', '是否调料'),
        ('preprocess', '备菜处理方式'), ('feeding_mode', '投料模式'), ('ingredient_type', '食材类型'), ('category_1', '一级分类'), ('category_2', '二级分类'), ('raw_json', '原始JSON')
    ]
    write_sheet(wb, '液料水投料明细', result.get('liquid_water_ingredients', []), ingredient_cols)
    write_sheet(wb, '全部配料明细', result.get('all_ingredients', []), ingredient_cols)
    write_sheet(wb, '全部烹饪步骤', result.get('cook_steps', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('step_index', '步骤序号'),
        ('time', '时间'), ('type_label', '步骤类型'), ('automatic_label', '自动/手动'), ('power', '功率'),
        ('speed', '搅拌速度'), ('position', '锅位'), ('movepot', '翻锅/移锅'), ('commands', '原始指令内容'), ('execution_content', '机器执行内容'), ('raw_json', '原始步骤JSON')
    ])
    write_sheet(wb, '菜谱原始JSON', result.get('raw_process', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('cook_time', '烹饪时长'),
        ('cook_steps_count', '烹饪步骤数'), ('ingredient_count', '配料数'), ('description', '备菜/预制说明'),
        ('cook_steps_json', '烹饪步骤JSON'), ('cooking_ingredient_json', '配料JSON'), ('ingredient_note_json', '备菜须知JSON'), ('serve_note_json', '出菜须知JSON')
    ])
    write_sheet(wb, '设备覆盖明细', result.get('device_coverage', []), [
        ('recipe_id', '菜谱ID'), ('sn', '设备SN'), ('device_name', '设备名'), ('customer_name', '客户'), ('region', '地区'),
        ('robot_type', '设备类型'), ('version', '版本'), ('cooking_count', '烹饪次数'), ('first_time', '首次'), ('last_time', '末次')
    ])
    write_sheet(wb, '客户覆盖明细', result.get('customer_coverage', []), [
        ('recipe_id', '菜谱ID'), ('company_id', '客户ID'), ('customer_name', '客户'), ('region', '地区'),
        ('cooking_count', '烹饪次数'), ('device_count', '设备数'), ('first_time', '首次'), ('last_time', '末次')
    ])
    return wb

def run_recipe_top_job(job_id, params, username):
    started = int(time.time())
    try:
        update_analytics_job(job_id, status='RUNNING', stage='查询生产日志', progress=12, started_at=started)
        result = build_recipe_top_result(params, job_id=job_id)
        update_analytics_job(job_id, stage='生成 Excel', progress=82)
        result_path = analytics_result_path(job_id)
        result_path.write_text(json.dumps(result, ensure_ascii=False, default=str))
        job = get_analytics_job(job_id) or {'job_id': job_id}
        xlsx_path = analytics_xlsx_path(job_id)
        wb = build_recipe_top_workbook(result, job)
        wb.save(xlsx_path)
        update_analytics_job(
            job_id,
            status='COMPLETED',
            stage='完成',
            progress=100,
            finished_at=int(time.time()),
            cache_expires_at=int(time.time()) + ANALYTICS_QUERY_TTL_SECONDS,
            result_path=str(result_path),
            xlsx_path=str(xlsx_path),
            error_message='',
        )
    except Exception as exc:
        update_analytics_job(job_id, status='FAILED', stage='失败', progress=100, finished_at=int(time.time()), error_message=str(exc)[:1000])

def resolve_recipe_search_sns(params):
    keyword = params['keyword']
    like = f"%{keyword}%" if keyword else None
    if params['scope'] in {'customer', 'device'}:
        if params['scope'] == 'customer':
            where_sql = (
                "(c.company_name LIKE %s OR c.common_name LIKE %s OR c.addr LIKE %s OR "
                "c.company_addr LIKE %s OR c.geo_pname LIKE %s OR c.geo_cityname LIKE %s OR "
                "c.geo_adname LIKE %s OR c.geo_name LIKE %s OR c.geo_address LIKE %s OR "
                "c.contact_name LIKE %s OR r.name LIKE %s OR r.spec LIKE %s)"
            )
            args = [like] * 12
        else:
            where_sql = (
                "(r.machinecode LIKE %s OR r.name LIKE %s OR r.spec LIKE %s OR "
                "r.robot_type LIKE %s OR r.latest_update_package LIKE %s)"
            )
            args = [like] * 5
        rows = fetch_all(
            f"""
            SELECT DISTINCT r.machinecode AS sn
            FROM btyc.sop_robot r
            LEFT JOIN btyc.ums_company c ON r.company_id = c.id
            WHERE r.machinecode IS NOT NULL AND r.machinecode != '' AND {where_sql}
            ORDER BY r.machinecode
            LIMIT 2000
            """,
            tuple(args),
            source=True,
            database='btyc',
        )
        return [row['sn'] for row in rows if row.get('sn')]

    conditions = ["d.`烹饪日期` >= %s", "d.`烹饪日期` <= %s"]
    args = [params['start_time'], params['end_time']]
    if like:
        conditions.append(
            "(d.`设备编号` LIKE %s OR d.`门店名称` LIKE %s OR d.`企业名称` LIKE %s OR "
            "r.name LIKE %s OR r.spec LIKE %s OR c.company_name LIKE %s OR c.common_name LIKE %s)"
        )
        args.extend([like] * 7)
    rows = fetch_all(
        f"""
        SELECT DISTINCT d.`设备编号` AS sn
        FROM btyc_statics.robot_cook_day d
        LEFT JOIN btyc.sop_robot r ON d.`设备编号` = r.machinecode
        LEFT JOIN btyc.ums_company c ON r.company_id = c.id
        WHERE d.`设备编号` IS NOT NULL AND d.`设备编号` != '' AND {' AND '.join(conditions)}
        ORDER BY d.`设备编号`
        LIMIT 2000
        """,
        tuple(args),
        source=True,
        database='btyc_statics',
    )
    return [row['sn'] for row in rows if row.get('sn')]

def recipe_search_sql_parts(params):
    detail_join = "LEFT JOIN manage_backend.recipe_detail rd ON l.recipe_id = rd.recipe_id" if params['recipe_keyword'] else ""
    from_sql = f"""
        FROM btyc.sop_machinelog l
        LEFT JOIN btyc.sop_robot r ON l.sn = r.machinecode
        LEFT JOIN btyc.ums_company c ON r.company_id = c.id
        LEFT JOIN manage_backend.main_recipe mr ON l.recipe_id = mr.id
        {detail_join}
    """
    conditions = ["l.create_time >= %s", "l.create_time <= %s"]
    args = [params['start_time'], params['end_time']]

    sn_filter = params.get('sn_filter') or []
    if sn_filter:
        placeholders = ','.join(['%s'] * len(sn_filter))
        conditions.append(f"l.sn IN ({placeholders})")
        args.extend(sn_filter)

    recipe_keyword = params['recipe_keyword']
    if recipe_keyword:
        like = f"%{recipe_keyword}%"
        conditions.append(
            "(l.recipe_name LIKE %s OR mr.name LIKE %s OR mr.group_name LIKE %s OR "
            "CAST(l.recipe_id AS CHAR) LIKE %s OR rd.cook_steps LIKE %s OR "
            "rd.cooking_ingredient LIKE %s OR rd.wash_steps LIKE %s OR rd.moisten_steps LIKE %s)"
        )
        args.extend([like] * 8)

    return from_sql, " AND ".join(conditions), args

def hydrate_recipe_search_resources(recipe_rows):
    recipe_ids = [int(row['recipe_id']) for row in recipe_rows if row.get('recipe_id')]
    if not recipe_ids:
        for row in recipe_rows:
            row['resources'] = []
            row['has_lard'] = False
            row['resource_flags'] = {}
        return recipe_rows

    placeholders = ','.join(['%s'] * len(recipe_ids))
    raw_recipes = fetch_all(
        f"SELECT id, name, group_name, type, steps_describe, ingredients_total_dosage "
        f"FROM main_recipe WHERE id IN ({placeholders})",
        tuple(recipe_ids),
        source=True,
        database='manage_backend',
    )
    raw_details = fetch_all(
        f"SELECT recipe_id, cook_time, cook_steps, wash_steps, moisten_steps, cooking_ingredient "
        f"FROM recipe_detail WHERE recipe_id IN ({placeholders})",
        tuple(recipe_ids),
        source=True,
        database='manage_backend',
    )
    recipe_by_id = {int(row['id']): row for row in raw_recipes}
    detail_by_recipe_id = {int(row['recipe_id']): row for row in raw_details}

    for row in recipe_rows:
        recipe_id = int(row['recipe_id']) if row.get('recipe_id') else None
        recipe = recipe_by_id.get(recipe_id)
        if recipe:
            usage = {
                'cnt': row.get('execution_count'),
                'total_duration_seconds': row.get('total_duration_seconds'),
                'first_time': row.get('first_time'),
                'last_time': row.get('last_time'),
            }
            archive = recipe_resource_summary(recipe, detail_by_recipe_id.get(recipe_id), {recipe_id: usage})
            row['resources'] = archive.get('resources', [])
            row['has_lard'] = bool(archive.get('has_lard'))
            row['resource_flags'] = archive.get('resource_flags', {})
            row['category'] = row.get('category') or archive.get('category') or '未分类'
            row['recipe_name'] = row.get('recipe_name') or archive.get('name')
        else:
            row['resources'] = []
            row['has_lard'] = False
            row['resource_flags'] = {}
            row['category'] = row.get('category') or '菜谱详情缺失'
    return recipe_rows

def json_cell(value):
    if value is None:
        return ''
    return json.dumps(value, ensure_ascii=False, default=str)

def fetch_ingredient_name_map(ingredient_ids):
    ids = sorted({str(item).strip() for item in ingredient_ids if str(item or '').strip()})
    if not ids:
        return {}
    placeholders = ','.join(['%s'] * len(ids))
    rows = fetch_all(
        f"SELECT ingredinent_id, ingredients_name, ingredinent_type, categories_1, categories_2, automatic, lang "
        f"FROM base_ingredients WHERE ingredinent_id IN ({placeholders}) "
        f"ORDER BY CASE WHEN lang = 'cn' THEN 0 WHEN lang = 'zh' THEN 1 WHEN lang = '' THEN 2 ELSE 3 END, lang",
        tuple(ids),
        source=True,
        database='btyc',
    )
    result = {}
    for row in rows:
        key = str(row['ingredinent_id'])
        if key not in result:
            result[key] = row
    return result

def first_present(data, *keys):
    for key in keys:
        value = data.get(key)
        if value not in (None, ''):
            return value
    return None

def number_value(value):
    if value in (None, ''):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None

def normalized_amount(value, unit):
    raw = number_value(value)
    if raw is None:
        return None
    clean_unit = str(unit or '').strip().lower()
    if clean_unit in {'kg', '千克', '公斤'}:
        return raw * 1000
    if clean_unit in {'l', '升'}:
        return raw * 1000
    if clean_unit in {'g', '克', 'ml', '毫升'}:
        return raw
    return None

def step_type_label(value):
    labels = {
        '1': '投料',
        '2': '等待/执行',
        '3': '机器控制',
        '4': '出菜/提示',
    }
    return labels.get(str(value), str(value) if value not in (None, '') else '')

def auto_label(value):
    if str(value) == '1':
        return '自动'
    if str(value) == '0':
        return '手动'
    return value

def build_machine_execution_text(step):
    parts = []
    text = command_text(step)
    if text:
        parts.append(text)
    power = first_present(step, 'power')
    speed = first_present(step, 'speed', 'stirSpeed')
    position = first_present(step, 'position')
    if power not in (None, '', '0', '0.0'):
        parts.append(f"功率:{power}W")
    if speed not in (None, '', '0', '0.0'):
        parts.append(f"搅拌:{speed}")
    if position not in (None, '', '0', '0.0'):
        parts.append(f"锅位:{position}")
    if str(first_present(step, 'movepot') or '0') not in {'', '0', '0.0'}:
        parts.append(f"翻锅/移锅:{first_present(step, 'movepot')}")
    direction = first_present(step, 'direction')
    if direction not in (None, '', '0', '0.0'):
        parts.append(f"方向:{direction}")
    duration = first_present(step, 'time')
    if duration not in (None, '', '0', '0.0'):
        parts.append(f"时间:{duration}s")
    return '；'.join(parts)

def note_rows(recipe_id, section, value, recipe=None, usage=None, base_builder=None):
    parsed = parse_json_value(value)
    if parsed in (None, ''):
        return []
    items = parsed if isinstance(parsed, list) else [parsed]
    rows = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            content = first_present(item, 'content', 'note', 'desc', 'description', 'commands', 'name', 'text')
            raw = item
        else:
            content = str(item)
            raw = {'value': item}
        row = base_builder(recipe_id, recipe, usage) if base_builder else {'recipe_id': recipe_id}
        row.update({
            'section': section,
            'note_index': index,
            'content': content,
            'raw_json': json_cell(raw),
        })
        rows.append(row)
    return rows

def fetch_recipe_process_export_rows(recipe_rows):
    recipe_ids = sorted({
        int(row['recipe_id'])
        for row in recipe_rows
        if row.get('recipe_id')
    })
    if not recipe_ids:
        return {
            'cook_steps': [],
            'wash_steps': [],
            'moisten_steps': [],
            'ingredients': [],
            'prep_notes': [],
            'serve_notes': [],
            'temperature_curve': [],
            'raw_process': [],
        }

    placeholders = ','.join(['%s'] * len(recipe_ids))
    raw_recipes = fetch_all(
        f"SELECT id, name, group_name, type, description, steps_describe, ingredients_total_dosage, "
        f"weight, portion_size, cooking_time, pot_type, power_type, max_power, apply_moisten_pot "
        f"FROM main_recipe WHERE id IN ({placeholders})",
        tuple(recipe_ids),
        source=True,
        database='manage_backend',
    )
    raw_details = fetch_all(
        f"SELECT recipe_id, cook_time, cook_steps, wash_steps, moisten_steps, cooking_ingredient, "
        f"ingredient_note, serve_note, temperature_curve, initial_temperature, initial_temperature_array "
        f"FROM recipe_detail WHERE recipe_id IN ({placeholders})",
        tuple(recipe_ids),
        source=True,
        database='manage_backend',
    )
    recipe_by_id = {int(row['id']): row for row in raw_recipes}
    detail_by_recipe_id = {int(row['recipe_id']): row for row in raw_details}
    usage_by_recipe_id = {
        int(row['recipe_id']): row
        for row in recipe_rows
        if row.get('recipe_id')
    }
    ingredient_ids = []
    for detail in raw_details:
        for item in parse_json_array(detail.get('cooking_ingredient')):
            if isinstance(item, dict):
                ingredient_ids.append(first_present(item, 'ingredientsId', 'Ingredients_id', 'ingredientId', 'id'))
    ingredient_name_map = fetch_ingredient_name_map(ingredient_ids)

    def base(recipe_id, recipe=None, usage=None):
        recipe = recipe or {}
        usage = usage or {}
        return {
            'recipe_id': recipe_id,
            'recipe_name': recipe.get('name') or usage.get('recipe_name'),
            'category': recipe.get('group_name') or usage.get('category') or '未分类',
            'recipe_type': recipe.get('type') or usage.get('recipe_type'),
            'recipe_description': recipe.get('description'),
            'recipe_weight': recipe.get('weight'),
            'portion_size': recipe.get('portion_size'),
            'recipe_cooking_time': recipe.get('cooking_time'),
            'pot_type': recipe.get('pot_type'),
            'power_type': recipe.get('power_type'),
            'max_power': recipe.get('max_power'),
            'execution_count': usage.get('execution_count'),
            'device_count': usage.get('device_count'),
            'customer_count': usage.get('customer_count'),
        }

    def step_row(recipe_id, section, index, step, recipe=None, usage=None):
        if not isinstance(step, dict):
            step = {'commands': str(step)}
        row = base(recipe_id, recipe, usage)
        row.update({
            'section': section,
            'step_index': index,
            'time': step.get('time'),
            'cook_time': step.get('cook_time'),
            'type': step.get('type'),
            'type_label': step_type_label(step.get('type')),
            'automatic': step.get('automatic'),
            'automatic_label': auto_label(step.get('automatic')),
            'power': step.get('power'),
            'speed': step.get('speed') or step.get('stirSpeed'),
            'stir': step.get('stir'),
            'stir_mode': step.get('stirMode'),
            'mode': step.get('mode'),
            'position': step.get('position'),
            'movepot': step.get('movepot'),
            'direction': step.get('direction'),
            'type_operation': step.get('typeOperation'),
            'thedof_time': step.get('thedofTime'),
            'ingredients_time': step.get('ingredientsTime'),
            'initial_temperature': step.get('initialTemperature'),
            'initial_temperature_array': step.get('initialTemperatureArray'),
            'commands': command_text(step),
            'execution_content': build_machine_execution_text(step),
            'raw_json': json_cell(step),
        })
        return row

    cook_rows = []
    wash_rows = []
    moisten_rows = []
    ingredient_rows = []
    prep_note_rows = []
    serve_note_rows = []
    temperature_rows = []
    raw_rows = []

    for recipe_id in recipe_ids:
        recipe = recipe_by_id.get(recipe_id, {})
        detail = detail_by_recipe_id.get(recipe_id, {})
        usage = usage_by_recipe_id.get(recipe_id, {})
        cook_steps = parse_json_array(detail.get('cook_steps'))
        wash_steps = parse_json_array(detail.get('wash_steps'))
        moisten_steps = parse_json_array(detail.get('moisten_steps'))
        ingredients = parse_json_array(detail.get('cooking_ingredient'))
        temperature_curve = parse_json_value(detail.get('temperature_curve'))

        for index, step in enumerate(cook_steps, start=1):
            cook_rows.append(step_row(recipe_id, '烹饪', index, step, recipe, usage))
        for index, step in enumerate(wash_steps, start=1):
            wash_rows.append(step_row(recipe_id, '洗锅', index, step, recipe, usage))
        for index, step in enumerate(moisten_steps, start=1):
            moisten_rows.append(step_row(recipe_id, '润锅', index, step, recipe, usage))
        for index, item in enumerate(ingredients, start=1):
            if not isinstance(item, dict):
                item = {'name': str(item)}
            ingredient_id = first_present(item, 'ingredientsId', 'Ingredients_id', 'ingredientId', 'id')
            ingredient_meta = ingredient_name_map.get(str(ingredient_id)) or {}
            row = base(recipe_id, recipe, usage)
            row.update({
                'ingredient_index': index,
                'cooking_step_id': first_present(item, 'cookingId', 'cooking_id'),
                'ingredient_id': ingredient_id,
                'ingredient_name': first_present(item, 'name', 'materialName', 'food_name', 'ingredient_name') or ingredient_meta.get('ingredients_name'),
                'dosage': first_present(item, 'ingredientsDosage', 'Ingredients_dosage', 'dosage', 'weight', 'num', 'amount'),
                'unit': first_present(item, 'ingredientsUnit', 'Ingredients_unit', 'unit', 'dosageUnit', 'unit_name'),
                'preprocess': first_present(item, 'ingredientsTodyw', 'Ingredients_todyw', 'preprocess'),
                'feeding_mode': first_present(item, 'feedingMode', 'feeding_mode'),
                'insideand': first_present(item, 'insideand', 'Insideand'),
                'position': item.get('position'),
                'error_dosage': first_present(item, 'errorDosage', 'error_dosage'),
                'automatic': first_present(item, 'automatic') if first_present(item, 'automatic') is not None else ingredient_meta.get('automatic'),
                'ingredient_type': ingredient_meta.get('ingredinent_type'),
                'category_1': ingredient_meta.get('categories_1'),
                'category_2': ingredient_meta.get('categories_2'),
                'raw_json': json_cell(item),
            })
            ingredient_rows.append(row)

        prep_note_rows.extend(note_rows(recipe_id, '备菜须知', detail.get('ingredient_note'), recipe, usage, base))
        serve_note_rows.extend(note_rows(recipe_id, '出菜须知', detail.get('serve_note'), recipe, usage, base))
        if isinstance(temperature_curve, list):
            for index, item in enumerate(temperature_curve, start=1):
                data = item if isinstance(item, dict) else {'value': item}
                row = base(recipe_id, recipe, usage)
                row.update({
                    'point_index': index,
                    'time': first_present(data, 'time', 'x', 'second', 'seconds'),
                    'temperature': first_present(data, 'temperature', 'temp', 'y'),
                    'raw_json': json_cell(data),
                })
                temperature_rows.append(row)

        raw = base(recipe_id, recipe, usage)
        raw.update({
            'cook_time': detail.get('cook_time'),
            'cook_steps_count': len(cook_steps),
            'wash_steps_count': len(wash_steps),
            'moisten_steps_count': len(moisten_steps),
            'ingredient_count': len(ingredients),
            'description': recipe.get('description'),
            'steps_describe': recipe.get('steps_describe'),
            'ingredients_total_dosage': recipe.get('ingredients_total_dosage'),
            'ingredient_note_json': detail.get('ingredient_note'),
            'serve_note_json': detail.get('serve_note'),
            'temperature_curve_json': detail.get('temperature_curve'),
            'initial_temperature': detail.get('initial_temperature'),
            'initial_temperature_array': detail.get('initial_temperature_array'),
            'cook_steps_json': detail.get('cook_steps'),
            'wash_steps_json': detail.get('wash_steps'),
            'moisten_steps_json': detail.get('moisten_steps'),
            'cooking_ingredient_json': detail.get('cooking_ingredient'),
            'detail_missing': not bool(detail),
        })
        raw_rows.append(raw)

    return {
        'cook_steps': cook_rows,
        'wash_steps': wash_rows,
        'moisten_steps': moisten_rows,
        'ingredients': ingredient_rows,
        'prep_notes': prep_note_rows,
        'serve_notes': serve_note_rows,
        'temperature_curve': temperature_rows,
        'raw_process': raw_rows,
    }

def empty_recipe_search_result(params, reason='未匹配到设备'):
    return {
        'params': {
            'scope': params['scope'],
            'scope_label': params['scope_label'],
            'keyword': params['keyword'],
            'recipe_keyword': params['recipe_keyword'],
            'start_date': params['start_date'],
            'end_date': params['end_date'],
            'span_days': params['span_days'],
            'limit': params['limit'],
            'matched_device_count': int(params.get('matched_device_count') or 0),
        },
        'summary': {
            'total_logs': 0,
            'device_count': 0,
            'recipe_count': 0,
            'customer_count': 0,
            'first_time': None,
            'last_time': None,
            'total_duration_seconds': 0,
            'total_duration_label': seconds_label(0),
            'empty_reason': reason,
        },
        'recipes': [],
        'customers': [],
        'devices': [],
        'recent_logs': [],
    }

def build_recipe_search_result(params):
    sn_filter = resolve_recipe_search_sns(params)
    params['sn_filter'] = sn_filter
    params['matched_device_count'] = len(sn_filter)
    if not sn_filter:
        return empty_recipe_search_result(params)

    from_sql, where_sql, args = recipe_search_sql_parts(params)
    limit = params['limit']

    summary = fetch_one(
        f"""
        SELECT COUNT(*) AS total_logs,
               COUNT(DISTINCT l.sn) AS device_count,
               COUNT(DISTINCT CASE WHEN l.recipe_id IS NULL OR l.recipe_id = 0 THEN l.recipe_name ELSE l.recipe_id END) AS recipe_count,
               COUNT(DISTINCT r.company_id) AS customer_count,
               MIN(l.create_time) AS first_time,
               MAX(l.create_time) AS last_time,
               SUM(CAST(l.time AS SIGNED)) AS total_duration_seconds
        {from_sql}
        WHERE {where_sql}
        """,
        tuple(args),
        source=True,
        database='btyc',
    ) or {}

    recipe_rows = fetch_all(
        f"""
        SELECT COALESCE(NULLIF(CAST(l.recipe_id AS CHAR), '0'), CONCAT('name:', COALESCE(l.recipe_name, ''))) AS recipe_key,
               MAX(NULLIF(l.recipe_id, 0)) AS recipe_id,
               COALESCE(MAX(mr.name), MAX(l.recipe_name), '未知菜谱') AS recipe_name,
               COALESCE(MAX(mr.group_name), '未分类') AS category,
               MAX(mr.type) AS recipe_type,
               COUNT(*) AS execution_count,
               COUNT(DISTINCT l.sn) AS device_count,
               COUNT(DISTINCT r.company_id) AS customer_count,
               MIN(l.create_time) AS first_time,
               MAX(l.create_time) AS last_time,
               SUM(CAST(l.time AS SIGNED)) AS total_duration_seconds,
               ROUND(AVG(CAST(l.time AS SIGNED)), 1) AS avg_duration_seconds
        {from_sql}
        WHERE {where_sql}
        GROUP BY recipe_key
        ORDER BY execution_count DESC, last_time DESC
        LIMIT %s
        """,
        tuple(args + [limit]),
        source=True,
        database='btyc',
    )
    recipe_rows = hydrate_recipe_search_resources(recipe_rows)

    customer_rows = fetch_all(
        f"""
        SELECT COALESCE(r.company_id, 0) AS company_id,
               COALESCE(MAX(c.common_name), MAX(c.company_name), '未知客户') AS customer_name,
               COALESCE(MAX(c.geo_cityname), MAX(c.geo_pname), MAX(c.area_code), '') AS region,
               COUNT(*) AS production_count,
               COUNT(DISTINCT l.sn) AS device_count,
               COUNT(DISTINCT CASE WHEN l.recipe_id IS NULL OR l.recipe_id = 0 THEN l.recipe_name ELSE l.recipe_id END) AS recipe_count,
               MIN(l.create_time) AS first_time,
               MAX(l.create_time) AS last_time
        {from_sql}
        WHERE {where_sql}
        GROUP BY COALESCE(r.company_id, 0)
        ORDER BY production_count DESC, last_time DESC
        LIMIT 80
        """,
        tuple(args),
        source=True,
        database='btyc',
    )

    device_rows = fetch_all(
        f"""
        SELECT l.sn,
               MAX(r.name) AS device_name,
               MAX(r.robot_type) AS robot_type,
               MAX(r.latest_update_package) AS version,
               COALESCE(MAX(c.common_name), MAX(c.company_name), '未知客户') AS customer_name,
               COALESCE(MAX(c.geo_cityname), MAX(c.geo_pname), MAX(c.area_code), '') AS region,
               COUNT(*) AS production_count,
               COUNT(DISTINCT CASE WHEN l.recipe_id IS NULL OR l.recipe_id = 0 THEN l.recipe_name ELSE l.recipe_id END) AS recipe_count,
               MIN(l.create_time) AS first_time,
               MAX(l.create_time) AS last_time
        {from_sql}
        WHERE {where_sql}
        GROUP BY l.sn
        ORDER BY production_count DESC, last_time DESC
        LIMIT 120
        """,
        tuple(args),
        source=True,
        database='btyc',
    )

    recent_logs = fetch_all(
        f"""
        SELECT l.id, l.sn, l.recipe_id, l.recipe_name, l.time AS duration_seconds,
               l.create_time, l.end_time,
               MAX(r.name) AS device_name,
               COALESCE(MAX(c.common_name), MAX(c.company_name), '未知客户') AS customer_name,
               COALESCE(MAX(c.geo_cityname), MAX(c.geo_pname), MAX(c.area_code), '') AS region
        {from_sql}
        WHERE {where_sql}
        GROUP BY l.id, l.sn, l.recipe_id, l.recipe_name, l.time, l.create_time, l.end_time
        ORDER BY l.create_time DESC
        LIMIT %s
        """,
        tuple(args + [min(limit, 200)]),
        source=True,
        database='btyc',
    )

    total_duration = int(summary.get('total_duration_seconds') or 0)
    return {
        'params': {
            'scope': params['scope'],
            'scope_label': params['scope_label'],
            'keyword': params['keyword'],
            'recipe_keyword': params['recipe_keyword'],
            'start_date': params['start_date'],
            'end_date': params['end_date'],
            'span_days': params['span_days'],
            'limit': limit,
            'matched_device_count': len(sn_filter),
        },
        'summary': {
            'total_logs': int(summary.get('total_logs') or 0),
            'device_count': int(summary.get('device_count') or 0),
            'recipe_count': int(summary.get('recipe_count') or 0),
            'customer_count': int(summary.get('customer_count') or 0),
            'first_time': summary.get('first_time'),
            'last_time': summary.get('last_time'),
            'total_duration_seconds': total_duration,
            'total_duration_label': seconds_label(total_duration),
        },
        'recipes': recipe_rows,
        'customers': customer_rows,
        'devices': device_rows,
        'recent_logs': recent_logs,
    }

def get_cached_recipe_search(params, force_refresh=False):
    now = time.time()
    if not force_refresh:
        cached = load_cached_recipe_search(params, now)
        if cached:
            return cached
    result = build_recipe_search_result(params)
    key = save_cached_recipe_search(params, result, now)
    result['cache'] = {
        'hit': False,
        'created_at': now,
        'ttl_seconds': RECIPE_SEARCH_CACHE_TTL_SECONDS,
        'cache_key': key,
    }
    return result

def recipe_analysis_step_group(row):
    section = row.get('section') or ''
    text = ' '.join(str(row.get(k) or '') for k in ['commands', 'execution_content', 'raw_json'])
    step_type = str(row.get('type') or '')
    automatic = str(row.get('automatic') or '')
    power = number_value(row.get('power')) or 0
    speed = number_value(row.get('speed')) or 0
    position = str(row.get('position') or '').strip()
    groups = []
    if section == '洗锅':
        groups.append('洗锅')
    if section == '润锅':
        groups.append('润锅')
    if step_type == '3' or power:
        groups.append('加热/功率')
    if speed:
        groups.append('搅拌')
    if position and position not in {'0', '0.0'}:
        groups.append('锅位')
    if step_type == '2' or automatic == '1' or '自动' in str(row.get('automatic_label') or ''):
        groups.append('自动投料')
    if step_type == '1' and automatic != '1':
        groups.append('人工/预制投料')
    if any(k in text for k in ['猪油', '菜籽油', '色拉油', '橄榄油', '油桶', '注油', 'add oil', 'oil']):
        groups.append('油/注油')
    if any(k in text for k in ['水淀粉', '清水', '饮用水', '开水', '冷水', '热水', '高汤', '汤汁', '汤底', '加水', 'add water']):
        groups.append('水/水淀粉')
    if any(k in text for k in ['盐', '鸡精', '味精', '生抽', '老抽', '蚝油', '醋', '料酒', '酱', '粉']):
        groups.append('调料')
    return groups or ['其他动作']

def build_recipe_analysis_classification(process_rows):
    all_steps = (
        process_rows.get('cook_steps', []) +
        process_rows.get('moisten_steps', []) +
        process_rows.get('wash_steps', [])
    )
    group_counter = Counter()
    classified_steps = []
    power_counter = Counter()
    position_counter = Counter()
    for row in all_steps:
        groups = recipe_analysis_step_group(row)
        for group in groups:
            group_counter[group] += 1
        power = row.get('power')
        speed = row.get('speed')
        position = row.get('position')
        if power not in (None, '', '0', '0.0'):
            power_counter[f"{power}W / 速度{speed or '-'} / 锅位{position or '-'}"] += 1
        if position not in (None, '', '0', '0.0'):
            position_counter[str(position)] += 1
        item = dict(row)
        item['resource_groups'] = groups
        item['resource_group_label'] = ' / '.join(groups)
        classified_steps.append(item)

    ingredient_rows = []
    feed_summary = {
        'total_count': 0,
        'liquid_count': 0,
        'liquid_amount': 0,
        'water_count': 0,
        'water_amount': 0,
        'oil_count': 0,
        'oil_amount': 0,
        'seasoning_count': 0,
        'seasoning_amount': 0,
    }
    for row in process_rows.get('ingredients', []):
        classes = ingredient_classes(row)
        amount = normalized_amount(row.get('dosage'), row.get('unit'))
        labels = []
        if classes['liquid']:
            labels.append('液料')
            feed_summary['liquid_count'] += 1
            feed_summary['liquid_amount'] += amount or 0
        if classes['water']:
            labels.append('水/汤汁')
            feed_summary['water_count'] += 1
            feed_summary['water_amount'] += amount or 0
        if classes['oil']:
            labels.append('油')
            feed_summary['oil_count'] += 1
            feed_summary['oil_amount'] += amount or 0
        if classes['seasoning']:
            labels.append('调料')
            feed_summary['seasoning_count'] += 1
            feed_summary['seasoning_amount'] += amount or 0
        if not labels:
            labels.append('食材')
        feed_summary['total_count'] += 1
        item = dict(row)
        item.update({
            'class_label': ' / '.join(labels),
            'normalized_amount': amount,
        })
        ingredient_rows.append(item)

    return {
        'step_groups': [{'group': group, 'count': count} for group, count in group_counter.most_common()],
        'power_profile': [{'profile': profile, 'count': count} for profile, count in power_counter.most_common()],
        'position_profile': [{'position': position, 'count': count} for position, count in position_counter.most_common()],
        'feed_summary': feed_summary,
        'classified_steps': classified_steps,
        'classified_ingredients': ingredient_rows,
    }

def enrich_recipe_logs_with_temperature(log_rows, span_days):
    if not log_rows:
        return {'logs': log_rows, 'summary': {'enabled': False, 'reason': '无生产记录'}}
    if span_days > 2:
        return {'logs': log_rows, 'summary': {'enabled': False, 'reason': '温度匹配仅在指定日期/两日内查询启用，避免批量下载日志拖慢页面'}}

    series_cache = {}
    matched = 0
    missing = 0
    for row in log_rows:
        sn = row.get('sn')
        cook_end = row.get('create_time')
        duration = int(row.get('duration_seconds') or 0)
        if not sn or not cook_end or not duration:
            row['temperature'] = {'covered': False, 'status': '缺少作业时间'}
            missing += 1
            continue
        cook_start = cook_end - timedelta(seconds=duration)
        day_key = (sn, cook_start.date().isoformat())
        if day_key not in series_cache or series_cache.get(day_key) is None:
            series_cache[day_key] = find_temperature_series_for_window(sn, cook_start - timedelta(minutes=5), cook_end + timedelta(minutes=5))
        payload = series_cache.get(day_key)
        if not payload:
            row['temperature'] = {'covered': False, 'status': '未找到覆盖该日期的日志温度'}
            missing += 1
            continue
        temp = cooking_temperature_summary_from_series(payload.get('series') or [], cook_start, cook_end)
        temp['file_id'] = payload.get('file', {}).get('id')
        temp['file_name'] = payload.get('file', {}).get('file_name')
        temp['coverage_start'] = payload.get('coverage', {}).get('start')
        temp['coverage_end'] = payload.get('coverage', {}).get('end')
        row['temperature'] = temp
        if temp.get('covered'):
            matched += 1
        else:
            missing += 1
    return {
        'logs': log_rows,
        'summary': {
            'enabled': True,
            'matched_count': matched,
            'missing_count': missing,
            'unit': '锅体温度 ℃，优先取 android 日志 温度:_x_y_z 第3位',
        },
    }

def build_recipe_analysis_result(params, recipe_id=None, recipe_name=''):
    sn_filter = resolve_recipe_search_sns(params)
    params['sn_filter'] = sn_filter
    params['matched_device_count'] = len(sn_filter)
    if not sn_filter:
        return {
            **empty_recipe_search_result(params),
            'summary': {'empty_reason': '未匹配到当前客户/设备范围'},
            'devices': [],
            'recent_logs': [],
            'daily_stats': [],
            'temperature_summary': {'enabled': False, 'reason': '无生产记录'},
            'process': {},
            'classification': {},
        }

    from_sql, where_sql, args = recipe_search_sql_parts(params)
    extra_conditions = []
    extra_args = []
    clean_recipe_name = (recipe_name or '').strip()
    if recipe_id:
        extra_conditions.append("l.recipe_id = %s")
        extra_args.append(int(recipe_id))
    elif clean_recipe_name:
        extra_conditions.append("(l.recipe_name = %s OR mr.name = %s)")
        extra_args.extend([clean_recipe_name, clean_recipe_name])
    else:
        raise HTTPException(status_code=400, detail="需要选择一个菜谱后再分析")
    if extra_conditions:
        where_sql = f"{where_sql} AND {' AND '.join(extra_conditions)}"
        args = args + extra_args

    summary = fetch_one(
        f"""
        SELECT MAX(NULLIF(l.recipe_id, 0)) AS recipe_id,
               COALESCE(MAX(mr.name), MAX(l.recipe_name), %s) AS recipe_name,
               COALESCE(MAX(mr.group_name), '未分类') AS category,
               COUNT(*) AS execution_count,
               COUNT(DISTINCT l.sn) AS device_count,
               COUNT(DISTINCT r.company_id) AS customer_count,
               MIN(l.create_time) AS first_time,
               MAX(l.create_time) AS last_time,
               SUM(CAST(l.time AS SIGNED)) AS total_duration_seconds,
               ROUND(AVG(CAST(l.time AS SIGNED)), 1) AS avg_duration_seconds
        {from_sql}
        WHERE {where_sql}
        """,
        tuple([clean_recipe_name] + args),
        source=True,
        database='btyc',
    ) or {}
    if not int(summary.get('execution_count') or 0):
        return {
            'params': {
                'scope': params['scope'],
                'scope_label': params['scope_label'],
                'keyword': params['keyword'],
                'recipe_keyword': params['recipe_keyword'],
                'start_date': params['start_date'],
                'end_date': params['end_date'],
                'matched_device_count': len(sn_filter),
            },
            'summary': {'empty_reason': '当前范围内没有这道菜的生产记录'},
            'devices': [],
            'recent_logs': [],
            'daily_stats': [],
            'temperature_summary': {'enabled': False, 'reason': '无生产记录'},
            'process': {},
            'classification': {},
        }

    devices = fetch_all(
        f"""
        SELECT l.sn,
               MAX(r.name) AS device_name,
               MAX(r.robot_type) AS robot_type,
               MAX(r.latest_update_package) AS version,
               COALESCE(MAX(c.common_name), MAX(c.company_name), '未知客户') AS customer_name,
               COALESCE(MAX(c.geo_cityname), MAX(c.geo_pname), MAX(c.area_code), '') AS region,
               COUNT(*) AS execution_count,
               MIN(l.create_time) AS first_time,
               MAX(l.create_time) AS last_time,
               ROUND(AVG(CAST(l.time AS SIGNED)), 1) AS avg_duration_seconds
        {from_sql}
        WHERE {where_sql}
        GROUP BY l.sn
        ORDER BY execution_count DESC, last_time DESC
        LIMIT 120
        """,
        tuple(args),
        source=True,
        database='btyc',
    )
    recent_logs = fetch_all(
        f"""
        SELECT l.id, l.sn, l.recipe_id, l.recipe_name, l.time AS duration_seconds,
               l.create_time, l.end_time, l.whether, l.manual,
               COALESCE(MAX(c.common_name), MAX(c.company_name), '未知客户') AS customer_name,
               COALESCE(MAX(c.geo_cityname), MAX(c.geo_pname), MAX(c.area_code), '') AS region
        {from_sql}
        WHERE {where_sql}
        GROUP BY l.id, l.sn, l.recipe_id, l.recipe_name, l.time, l.create_time, l.end_time, l.whether, l.manual
        ORDER BY l.create_time DESC
        LIMIT 100
        """,
        tuple(args),
        source=True,
        database='btyc',
    )
    daily_stats = fetch_all(
        f"""
        SELECT DATE(l.create_time) AS day,
               COUNT(*) AS execution_count,
               COUNT(DISTINCT l.sn) AS device_count,
               MIN(l.create_time) AS first_time,
               MAX(l.create_time) AS last_time,
               ROUND(AVG(CAST(l.time AS SIGNED)), 1) AS avg_duration_seconds
        {from_sql}
        WHERE {where_sql}
        GROUP BY DATE(l.create_time)
        ORDER BY day DESC
        LIMIT 180
        """,
        tuple(args),
        source=True,
        database='btyc',
    )

    total_duration = int(summary.get('total_duration_seconds') or 0)
    recipe_row = {
        'recipe_id': summary.get('recipe_id') or recipe_id,
        'recipe_name': summary.get('recipe_name') or clean_recipe_name,
        'category': summary.get('category') or '未分类',
        'execution_count': int(summary.get('execution_count') or 0),
        'device_count': int(summary.get('device_count') or 0),
        'customer_count': int(summary.get('customer_count') or 0),
        'first_time': summary.get('first_time'),
        'last_time': summary.get('last_time'),
        'total_duration_seconds': total_duration,
        'avg_duration_seconds': summary.get('avg_duration_seconds'),
    }
    process_rows = fetch_recipe_process_export_rows([recipe_row])
    classification = build_recipe_analysis_classification(process_rows)
    temperature_payload = enrich_recipe_logs_with_temperature(recent_logs, params.get('span_days') or 0)
    recent_logs = temperature_payload['logs']
    return {
        'params': {
            'scope': params['scope'],
            'scope_label': params['scope_label'],
            'keyword': params['keyword'],
            'recipe_keyword': params['recipe_keyword'],
            'start_date': params['start_date'],
            'end_date': params['end_date'],
            'matched_device_count': len(sn_filter),
        },
        'summary': {
            **recipe_row,
            'total_duration_label': seconds_label(total_duration),
        },
        'devices': devices,
        'recent_logs': recent_logs,
        'daily_stats': daily_stats,
        'temperature_summary': temperature_payload['summary'],
        'process': process_rows,
        'classification': classification,
    }

@app.get("/api/me")
def me(authorization: str = Header(None)):
    username = require_auth(authorization=authorization)
    return {"username": username, "role": ZHIKU_USERS[username].get('role', 'user'), "profile": get_profile(username)}

@app.patch("/api/profile")
def profile_update(payload: ProfileUpdate, request: Request, authorization: str = Header(None)):
    username = require_auth(authorization=authorization)
    profile = update_profile(username, payload.display_name)
    log_event(username, 'profile_update', request, detail={'display_name': profile.get('display_name')})
    return {"profile": profile}

@app.get("/api/devices/search")
def device_lookup(
    request: Request,
    keyword: str = Query(''),
    limit: int = Query(50),
    refresh: int = Query(0),
    authorization: str = Header(None),
):
    username = require_auth(authorization=authorization)
    result = search_devices_by_keyword(keyword, limit=limit, force_refresh=bool(refresh))
    log_event(
        username,
        'device_lookup_refresh' if refresh else 'device_lookup',
        request,
        detail={
            'keyword': keyword,
            'result_count': result.get('total'),
            'cache_hit': bool(result.get('cache', {}).get('hit')),
        },
    )
    return result

@app.get("/api/device-versions")
def device_versions(
    request: Request,
    version: str = Query(''),
    keyword: str = Query(''),
    limit: int = Query(500),
    refresh: int = Query(0),
    authorization: str = Header(None),
):
    username = require_auth(authorization=authorization)
    result = build_device_version_stats(version=version, keyword=keyword, limit=limit, force_refresh=bool(refresh))
    log_event(
        username,
        'device_versions_refresh' if refresh else 'device_versions',
        request,
        detail={
            'version': version,
            'keyword': keyword,
            'limit': limit,
            'cache_hit': bool(result.get('cache', {}).get('hit')),
            'total_devices': result.get('summary', {}).get('total_devices'),
            'version_count': result.get('summary', {}).get('version_count'),
        },
    )
    return result

@app.get("/api/search/{sn}")
def search_device(sn: str, request: Request, refresh: int = 0, authorization: str = Header(None)):
    username = require_auth(authorization=authorization)
    report = get_cached_report(sn, force_refresh=bool(refresh))
    log_event(
        username,
        'search_refresh' if refresh else 'search',
        request,
        sn=report['stats']['sn'],
        detail={
            'input_sn': sn,
            'cache_hit': bool(report.get('cache', {}).get('hit')),
            'total_logs': report.get('stats', {}).get('total_logs'),
            'recipe_count': len(report.get('recipe_archive', [])),
        },
    )
    return report

@app.get("/api/search/{sn}/month/{month}")
def search_device_month(sn: str, month: str, request: Request, authorization: str = Header(None)):
    username = require_auth(authorization=authorization)
    detail = get_device_month_detail(sn, month)
    log_event(
        username,
        'search_month',
        request,
        sn=detail['sn'],
        detail={
            'input_sn': sn,
            'month': month,
            'total_logs': detail.get('summary', {}).get('total_logs'),
            'recipe_count': detail.get('summary', {}).get('recipe_count'),
        },
    )
    return detail

@app.get("/api/cook-temperature/{sn}")
def cook_temperature(sn: str, request: Request, file_id: int = Query(None), authorization: str = Header(None)):
    username = require_auth(authorization=authorization)
    result = build_cook_temperature_analysis(sn, file_id=file_id)
    log_event(
        username,
        'cook_temperature',
        request,
        sn=result.get('sn'),
        detail={
            'file_id': result.get('file', {}).get('id'),
            'cook_id': result.get('cook', {}).get('id'),
            'recipe_id': result.get('cook', {}).get('recipe_id'),
            'step_count': len(result.get('steps', [])),
        },
    )
    return result

@app.get("/api/recipe-search")
def recipe_search(
    request: Request,
    scope: str = Query('customer'),
    keyword: str = Query(''),
    recipe_keyword: str = Query(''),
    start_date: str = Query(None),
    end_date: str = Query(None),
    limit: int = Query(200),
    refresh: int = Query(0),
    authorization: str = Header(None),
):
    username = require_auth(authorization=authorization)
    params = normalize_recipe_search_params(scope, keyword, recipe_keyword, start_date, end_date, limit)
    result = get_cached_recipe_search(params, force_refresh=bool(refresh))
    log_event(
        username,
        'recipe_search_refresh' if refresh else 'recipe_search',
        request,
        detail={
            'scope': params['scope'],
            'keyword': params['keyword'],
            'recipe_keyword': params['recipe_keyword'],
            'start_date': params['start_date'],
            'end_date': params['end_date'],
            'cache_hit': bool(result.get('cache', {}).get('hit')),
            'total_logs': result.get('summary', {}).get('total_logs'),
            'recipe_count': result.get('summary', {}).get('recipe_count'),
        },
    )
    return result

@app.get("/api/recipe-analysis")
def recipe_analysis(
    request: Request,
    scope: str = Query('customer'),
    keyword: str = Query(''),
    recipe_keyword: str = Query(''),
    start_date: str = Query(None),
    end_date: str = Query(None),
    limit: int = Query(200),
    recipe_id: int = Query(None),
    recipe_name: str = Query(''),
    refresh: int = Query(0),
    authorization: str = Header(None),
):
    username = require_auth(authorization=authorization)
    params = normalize_recipe_search_params(scope, keyword, recipe_keyword, start_date, end_date, limit)
    result = get_cached_recipe_analysis(params, recipe_id=recipe_id, recipe_name=recipe_name, force_refresh=bool(refresh))
    log_event(
        username,
        'recipe_analysis',
        request,
        detail={
            'scope': params['scope'],
            'keyword': params['keyword'],
            'recipe_id': recipe_id,
            'recipe_name': recipe_name,
            'start_date': params['start_date'],
            'end_date': params['end_date'],
            'cache_hit': bool(result.get('cache', {}).get('hit')),
            'execution_count': result.get('summary', {}).get('execution_count'),
        },
    )
    return result

@app.post("/api/analytics/recipe-top/jobs")
def create_recipe_top_job(payload: RecipeTopJobRequest, request: Request, authorization: str = Header(None)):
    username = require_auth(authorization=authorization)
    params = normalize_recipe_top_params(payload)
    params_hash = analytics_params_hash(params)
    now = int(time.time())
    existing = None if payload.refresh and is_admin(username) else find_reusable_analytics_job('recipe_top', params_hash, now)
    if existing:
        job = get_analytics_job(existing['job_id'])
        log_event(username, 'recipe_top_query', request, detail={'job_id': job['job_id'], 'cache_hit': True, 'params': job.get('params')})
        return {**job, 'cache_hit': True}
    if payload.refresh and not is_admin(username):
        raise HTTPException(status_code=403, detail="只有 admin 可以强制刷新缓存")
    job_id = insert_analytics_job('recipe_top', params_hash, params, username)
    start_analytics_thread(job_id, params, username)
    job = get_analytics_job(job_id)
    log_event(username, 'recipe_top_query', request, detail={'job_id': job_id, 'cache_hit': False, 'params': {k: v for k, v in params.items() if k not in {'start_time', 'end_time'}}})
    return {**job, 'cache_hit': False}

@app.get("/api/analytics/jobs/{job_id}")
def analytics_job_status(job_id: str, authorization: str = Header(None)):
    require_auth(authorization=authorization)
    job = get_analytics_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.get("/api/analytics/recipe-top/jobs/{job_id}/result")
def recipe_top_job_result(job_id: str, request: Request, authorization: str = Header(None)):
    username = require_auth(authorization=authorization)
    job = get_analytics_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job['status'] != 'COMPLETED':
        return {'job': job, 'result': None}
    path = Path(job.get('result_path') or '')
    if not path.exists():
        raise HTTPException(status_code=404, detail="Result file not found")
    result = json.loads(path.read_text())
    log_event(username, 'recipe_top_result', request, detail={'job_id': job_id, 'recipe_count': result.get('summary', {}).get('recipe_count')})
    return {'job': job, 'result': result}

@app.get("/api/analytics/recipe-top/jobs/{job_id}/export")
def recipe_top_job_export(job_id: str, request: Request, token: str = Query(None), authorization: str = Header(None)):
    username = require_auth(authorization=authorization, token=token)
    job = get_analytics_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job['status'] != 'COMPLETED':
        raise HTTPException(status_code=409, detail="Job not completed")
    path = Path(job.get('xlsx_path') or '')
    if not path.exists():
        result_path = Path(job.get('result_path') or '')
        if not result_path.exists():
            raise HTTPException(status_code=404, detail="Export file not found")
        result = json.loads(result_path.read_text())
        wb = build_recipe_top_workbook(result, job)
        path = analytics_xlsx_path(job_id)
        wb.save(path)
        update_analytics_job(job_id, xlsx_path=str(path))
    log_event(username, 'recipe_top_export', request, detail={'job_id': job_id, 'file_name': path.name})
    data = BytesIO(path.read_bytes())
    filename = f"zhiku_recipe_top_{job_id}.xlsx"
    return StreamingResponse(
        data,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )

@app.get("/api/recipe-search/export")
def export_recipe_search(
    request: Request,
    scope: str = Query('customer'),
    keyword: str = Query(''),
    recipe_keyword: str = Query(''),
    start_date: str = Query(None),
    end_date: str = Query(None),
    limit: int = Query(200),
    token: str = Query(None),
    authorization: str = Header(None),
):
    username = require_auth(authorization=authorization, token=token)
    params = normalize_recipe_search_params(scope, keyword, recipe_keyword, start_date, end_date, limit)
    result = get_cached_recipe_search(params)
    process_rows = fetch_recipe_process_export_rows(result.get('recipes', []))
    log_event(
        username,
        'recipe_search_export',
        request,
        detail={
            'scope': params['scope'],
            'keyword': params['keyword'],
            'recipe_keyword': params['recipe_keyword'],
            'start_date': params['start_date'],
            'end_date': params['end_date'],
            'total_logs': result.get('summary', {}).get('total_logs'),
        },
    )

    wb = Workbook()
    wb.remove(wb.active)
    write_sheet(wb, '检索条件', [
        {'field': '检索维度', 'value': result['params'].get('scope_label')},
        {'field': '范围关键词', 'value': result['params'].get('keyword')},
        {'field': '菜谱关键词', 'value': result['params'].get('recipe_keyword')},
        {'field': '开始日期', 'value': result['params'].get('start_date')},
        {'field': '结束日期', 'value': result['params'].get('end_date')},
        {'field': '生产次数', 'value': result['summary'].get('total_logs')},
        {'field': '设备数', 'value': result['summary'].get('device_count')},
        {'field': '客户数', 'value': result['summary'].get('customer_count')},
        {'field': '菜谱数', 'value': result['summary'].get('recipe_count')},
    ], [('field', '字段'), ('value', '值')])
    write_sheet(wb, '菜谱汇总', result.get('recipes', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'),
        ('execution_count', '生产次数'), ('device_count', '设备数'), ('customer_count', '客户数'),
        ('first_time', '首次生产'), ('last_time', '末次生产'),
        ('total_duration_seconds', '累计耗时秒'), ('avg_duration_seconds', '平均耗时秒'),
        ('resources', '资源覆盖'), ('has_lard', '是否含猪油')
    ])
    write_sheet(wb, '客户汇总', result.get('customers', []), [
        ('company_id', '客户ID'), ('customer_name', '客户'), ('region', '地区'),
        ('production_count', '生产次数'), ('device_count', '设备数'), ('recipe_count', '菜谱数'),
        ('first_time', '首次生产'), ('last_time', '末次生产')
    ])
    write_sheet(wb, '设备汇总', result.get('devices', []), [
        ('sn', '设备SN'), ('device_name', '设备名'), ('customer_name', '客户'), ('region', '地区'),
        ('robot_type', '设备类型'), ('version', '版本'),
        ('production_count', '生产次数'), ('recipe_count', '菜谱数'),
        ('first_time', '首次生产'), ('last_time', '末次生产')
    ])
    write_sheet(wb, '明细样本', result.get('recent_logs', []), [
        ('id', '日志ID'), ('sn', '设备SN'), ('customer_name', '客户'), ('region', '地区'),
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'),
        ('duration_seconds', '耗时秒'), ('create_time', '生产时间'), ('end_time', '结束时间')
    ])
    write_sheet(wb, '菜谱烹饪步骤', process_rows.get('cook_steps', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('recipe_type', '类型'),
        ('recipe_description', '备菜/预制说明'), ('recipe_weight', '菜谱总重量g'), ('portion_size', '份量'),
        ('recipe_cooking_time', '菜谱总时长秒'), ('pot_type', '锅类型'), ('power_type', '功率类型'), ('max_power', '最大功率'),
        ('execution_count', '生产次数'), ('device_count', '设备数'), ('customer_count', '客户数'),
        ('step_index', '步骤序号'), ('time', '时间'), ('cook_time', '烹饪时长'),
        ('type', '步骤类型编码'), ('type_label', '步骤类型'), ('automatic', '自动编码'), ('automatic_label', '自动/手动'),
        ('power', '功率'), ('speed', '搅拌速度'), ('stir', '搅拌'), ('stir_mode', '搅拌模式'), ('mode', '模式'),
        ('position', '锅位'), ('movepot', '翻锅/移锅'), ('direction', '方向'), ('type_operation', '操作类型'),
        ('thedof_time', '录菜总时长'), ('ingredients_time', '投料时间'), ('initial_temperature', '初始温度'),
        ('initial_temperature_array', '初始温度曲线'), ('commands', '原始指令内容'),
        ('execution_content', '机器执行内容'), ('raw_json', '原始步骤JSON')
    ])
    write_sheet(wb, '菜谱洗锅步骤', process_rows.get('wash_steps', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('recipe_type', '类型'),
        ('step_index', '步骤序号'), ('time', '时间'), ('type', '步骤类型编码'), ('type_label', '步骤类型'),
        ('automatic', '自动编码'), ('automatic_label', '自动/手动'), ('power', '功率'), ('speed', '搅拌速度'),
        ('position', '锅位'), ('commands', '洗锅内容'), ('execution_content', '机器执行内容'), ('raw_json', '原始步骤JSON')
    ])
    write_sheet(wb, '菜谱润锅步骤', process_rows.get('moisten_steps', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('recipe_type', '类型'),
        ('step_index', '步骤序号'), ('time', '时间'), ('type', '步骤类型编码'), ('type_label', '步骤类型'),
        ('automatic', '自动编码'), ('automatic_label', '自动/手动'), ('power', '功率'), ('speed', '搅拌速度'),
        ('position', '锅位'), ('commands', '润锅内容'), ('execution_content', '机器执行内容'), ('raw_json', '原始步骤JSON')
    ])
    write_sheet(wb, '菜谱配料明细', process_rows.get('ingredients', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('recipe_type', '类型'),
        ('recipe_description', '备菜/预制说明'), ('ingredient_index', '配料序号'), ('cooking_step_id', '关联烹饪步骤ID'),
        ('ingredient_id', '食材ID'), ('ingredient_name', '食材名称'), ('dosage', '用量'), ('unit', '单位'),
        ('preprocess', '备菜处理方式'), ('feeding_mode', '投料模式'), ('insideand', '详情展示'),
        ('position', '位置'), ('error_dosage', '误差用量'), ('automatic', '是否自动'),
        ('ingredient_type', '食材类型'), ('category_1', '一级分类'), ('category_2', '二级分类'), ('raw_json', '原始配料JSON')
    ])
    write_sheet(wb, '备菜须知', process_rows.get('prep_notes', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('recipe_type', '类型'),
        ('recipe_description', '备菜/预制说明'), ('note_index', '序号'), ('content', '备菜内容'), ('raw_json', '原始JSON')
    ])
    write_sheet(wb, '出菜须知', process_rows.get('serve_notes', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('recipe_type', '类型'),
        ('note_index', '序号'), ('content', '出菜内容'), ('raw_json', '原始JSON')
    ])
    write_sheet(wb, '温度曲线', process_rows.get('temperature_curve', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('recipe_type', '类型'),
        ('point_index', '点位序号'), ('time', '时间'), ('temperature', '温度'), ('raw_json', '原始JSON')
    ])
    write_sheet(wb, '菜谱原始过程', process_rows.get('raw_process', []), [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('category', '分类'), ('recipe_type', '类型'),
        ('execution_count', '生产次数'), ('device_count', '设备数'), ('customer_count', '客户数'),
        ('cook_time', '菜谱烹饪时长'), ('cook_steps_count', '烹饪步骤数'),
        ('wash_steps_count', '洗锅步骤数'), ('moisten_steps_count', '润锅步骤数'), ('ingredient_count', '配料数'),
        ('description', '备菜/预制说明'), ('steps_describe', '步骤描述'), ('ingredients_total_dosage', '配料总量'),
        ('ingredient_note_json', '备菜须知JSON'), ('serve_note_json', '出菜须知JSON'),
        ('temperature_curve_json', '温度曲线JSON'), ('initial_temperature', '初始温度'),
        ('initial_temperature_array', '初始温度曲线'),
        ('cook_steps_json', '烹饪步骤JSON'), ('wash_steps_json', '洗锅步骤JSON'),
        ('moisten_steps_json', '润锅步骤JSON'), ('cooking_ingredient_json', '配料JSON'),
        ('detail_missing', '详情是否缺失')
    ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"zhiku_recipe_search_{params['scope']}_{params['start_date']}_{params['end_date']}.xlsx"
    return StreamingResponse(
        output,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )

def write_sheet(wb, title, rows, columns):
    ws = wb.create_sheet(title=title[:31])
    ws.append([label for _, label in columns])
    header_fill = PatternFill('solid', fgColor='E9EEF7')
    for cell in ws[1]:
        cell.font = Font(name='Arial', bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
    for row in rows:
        ws.append([normalize_cell(row.get(key)) for key, _ in columns])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name='Arial')
            cell.alignment = Alignment(vertical='top', wrap_text=True)
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        max_len = 8
        for cell in col:
            max_len = max(max_len, min(len(str(cell.value or '')), 40))
        ws.column_dimensions[col[0].column_letter].width = max_len + 2

def normalize_cell(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value

@app.get("/api/export/{sn}")
def export_device_report(sn: str, request: Request, token: str = Query(None), authorization: str = Header(None)):
    username = require_auth(authorization=authorization, token=token)
    report = get_cached_report(sn)
    log_event(
        username,
        'export',
        request,
        sn=report['stats']['sn'],
        detail={'recipe_count': len(report.get('recipe_archive', [])), 'log_count': len(report.get('logs', []))},
    )
    wb = Workbook()
    wb.remove(wb.active)

    write_sheet(wb, '设备档案', [{'field': k, 'value': v} for k, v in report['info'].items()], [('field', '字段'), ('value', '值')])
    write_sheet(wb, '客户信息', [{'field': k, 'value': v} for k, v in report.get('customer', {}).items()], [('field', '字段'), ('value', '值')])
    write_sheet(wb, '月度生产', report.get('monthly_summary', []), [
        ('month', '月份'), ('total_logs', '生产次数'), ('recipe_count', '菜谱数'),
        ('first_time', '首次生产'), ('last_time', '末次生产'),
        ('total_duration_seconds', '累计耗时秒'), ('avg_duration_seconds', '平均耗时秒')
    ])
    write_sheet(wb, '菜谱分类汇总', report.get('recipe_category_summary', []), [
        ('category', '分类'), ('recipe_count', '菜谱数'), ('execution_count', '执行次数'),
        ('lard_recipe_count', '含猪油菜谱数'), ('resources', '资源覆盖')
    ])
    write_sheet(wb, '菜谱归档', report.get('recipe_archive', []), [
        ('id', '菜谱ID'), ('name', '菜谱名称'), ('category', '分类'), ('execution_count', '执行次数'),
        ('total_duration_seconds', '累计耗时秒'), ('first_time', '首次执行'), ('last_time', '末次执行'),
        ('resources', '资源覆盖'), ('has_lard', '是否含猪油'), ('wash_steps_count', '洗锅步骤数'),
        ('moisten_steps_count', '润锅步骤数'), ('ingredient_count', '配料项数')
    ])

    step_rows = []
    for recipe in report.get('recipe_archive', []):
        for step in recipe.get('steps', []):
            step_rows.append({'recipe_id': recipe.get('id'), 'recipe_name': recipe.get('name'), **step})
    write_sheet(wb, '菜谱步骤', step_rows, [
        ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'), ('time', '时间点秒'),
        ('type', '步骤类型'), ('automatic', '自动'), ('power', '功率'), ('speed', '速度'),
        ('position', '锅位'), ('movepot', '移锅'), ('commands', '动作/投料')
    ])

    write_sheet(wb, '生产日志', report.get('logs', []), [
        ('id', '日志ID'), ('recipe_id', '菜谱ID'), ('recipe_name', '菜谱名称'),
        ('duration_seconds', '耗时秒'), ('create_time', '执行时间'), ('end_time', '结束时间'),
        ('expected_duration_seconds', '同菜谱平均耗时秒'), ('duration_ratio', '耗时倍率'),
        ('whether_label', '执行状态'), ('manual_label', '控制方式'), ('behavior_tags', '行为标签'),
        ('username', '账号/门店'), ('data_time', '数据时间'), ('comment', '备注')
    ])
    write_sheet(wb, '间隔分析', report.get('intervals', []), [
        ('id', '日志ID'), ('create_time', '执行时间'), ('recipe_name', '菜谱名称'), ('gap', '距上次间隔')
    ])
    write_sheet(wb, '故障日志', report.get('faults', []), [
        ('id', '故障ID'), ('create_time', '时间'), ('module', '模块'), ('details', '详情'), ('deal_state', '处理状态')
    ])
    write_sheet(wb, '维护记录', report.get('maintenance', []), [
        ('id', '记录ID'), ('create_time', '时间'), ('status', '状态'), ('mode', '模式'), ('duration', '时长')
    ])
    write_sheet(wb, '设备日志文件', report.get('device_logs', []), [
        ('id', '文件ID'), ('sn', '设备SN'), ('file_length', '文件大小'), ('file_name', '文件名'),
        ('create_time', '创建时间'), ('update_time', '修改时间'), ('type', '类型'),
        ('cos_deleted', '是否删除'), ('url', '下载URL')
    ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"zhiku_device_{report['stats']['sn']}.xlsx"
    return StreamingResponse(
        output,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )

@app.get("/api/device-log-download/{file_id}")
def download_device_log(file_id: int, request: Request, token: str = Query(None), authorization: str = Header(None)):
    username = require_auth(authorization=authorization, token=token)
    row = fetch_one(
        "SELECT sn, file_name, file_length, pic AS url FROM machine_ftp WHERE id = %s LIMIT 1",
        (file_id,),
        source=True,
        database='btyc',
    )
    if not row or not row.get('url'):
        raise HTTPException(status_code=404, detail="Log file not found")
    log_event(
        username,
        'log_download',
        request,
        sn=row.get('sn'),
        detail={'file_id': file_id, 'file_name': row.get('file_name'), 'file_length': row.get('file_length')},
    )
    return RedirectResponse(row['url'])

def get_log_analysis_payload(file_id, request, username, refresh=False, allow_refresh=False, action='log_analysis_view'):
    row = fetch_one(
        "SELECT id, sn, file_name, file_length, pic AS url, type, create_time, update_time, cos_deleted "
        "FROM machine_ftp WHERE id = %s LIMIT 1",
        (file_id,),
        source=True,
        database='btyc',
    )
    if not row or not row.get('url'):
        raise HTTPException(status_code=404, detail="Log file not found")
    if row.get('cos_deleted'):
        raise HTTPException(status_code=410, detail="Log file has been deleted from COS")
    if refresh and not allow_refresh:
        raise HTTPException(status_code=403, detail="Only admin can refresh log analysis")

    if not refresh:
        cached = read_cached_log_analysis(file_id)
        if cached:
            cached['cache'] = {'hit': True}
            log_event(
                username,
                action,
                request,
                sn=row.get('sn'),
                detail={'file_id': file_id, 'cache_hit': True},
            )
            return cached

    zip_bytes = download_log_zip(row['url'])
    payload = build_log_analysis(row, zip_bytes)
    payload['cache'] = {'hit': False}
    save_cached_log_analysis(file_id, payload)
    log_event(
        username,
        action,
        request,
        sn=row.get('sn'),
        detail={
            'file_id': file_id,
            'cache_hit': False,
            'zip_size_mb': payload.get('zip_size_mb'),
            'file_name': row.get('file_name'),
        },
    )
    return payload

@app.get("/api/log-analysis/{file_id}")
def log_analysis(file_id: int, request: Request, refresh: int = Query(0), authorization: str = Header(None)):
    username = require_auth(authorization=authorization)
    return get_log_analysis_payload(
        file_id,
        request,
        username,
        refresh=bool(refresh),
        allow_refresh=is_admin(username),
        action='log_analysis_view',
    )

@app.get("/api/admin/log-analysis/{file_id}")
def admin_log_analysis(file_id: int, request: Request, refresh: int = Query(0), authorization: str = Header(None)):
    username = require_admin(authorization=authorization)
    return get_log_analysis_payload(
        file_id,
        request,
        username,
        refresh=bool(refresh),
        allow_refresh=True,
        action='admin_log_analysis_view',
    )

@app.get("/api/admin/status")
def admin_status(authorization: str = Header(None)):
    username = require_admin(authorization=authorization)
    return {"status": "ok", "user": username, "cache_entries": len(REPORT_CACHE), **audit_summary()}

@app.get("/api/admin/emergency-devices")
def admin_emergency_devices(request: Request, authorization: str = Header(None)):
    username = require_admin(authorization=authorization)
    sns = ['0105222512180008', '0105222512180015']
    data = emergency_device_summary(sns)
    log_event(username, 'admin_emergency_view', request, detail={'sns': sns})
    return {'devices': data, 'sns': sns, 'generated_at': int(time.time())}

@app.get("/api/admin/oil-thermal/{sn}")
def admin_oil_thermal(sn: str, request: Request, authorization: str = Header(None)):
    username = require_admin(authorization=authorization)
    safe_sn = ''.join(ch for ch in sn if ch.isdigit())
    path = OIL_THERMAL_DATA_DIR / f'oil_thermal_{safe_sn}.json'
    if not path.exists():
        raise HTTPException(status_code=404, detail="Oil thermal log data not found")
    payload = json.loads(path.read_text())
    log_event(username, 'admin_oil_thermal_view', request, sn=safe_sn, detail={'source': str(path)})
    return payload

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
