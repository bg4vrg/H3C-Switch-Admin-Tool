import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

DB_NAME = 'net_assets.db'

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # 让结果像字典一样访问
    return conn

def init_db():
    """初始化数据库：创建表和默认管理员"""
    # 即使文件存在，也检查一下表是否存在，防止报错
    conn = get_db()
    c = conn.cursor()
    
    # 1. 创建用户表
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL)''')
    
    # 2. 创建交换机资产表
    c.execute('''CREATE TABLE IF NOT EXISTS switches
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  ip TEXT NOT NULL,
                  port INTEGER DEFAULT 22,
                  username TEXT,
                  password TEXT,
                  model TEXT,
                  note TEXT)''')
    
    # 3. 创建默认管理员账号: admin / admin888
    # 注意：这里存的是加密后的哈希值，不是明文，非常安全
    default_user = 'admin'
    default_pass = 'admin888'
    
    c.execute("SELECT * FROM users WHERE username = ?", (default_user,))
    if not c.fetchone():
        print(f"⚙️ 正在初始化默认管理员账号: {default_user}")
        p_hash = generate_password_hash(default_pass)
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", 
                  (default_user, p_hash))
    
    conn.commit()
    conn.close()

# === 用户管理 ===
def get_user_by_id(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    conn.close()
    return user

def verify_user(username, password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    conn.close()
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None

def change_password(username, new_password):
    conn = get_db()
    cur = conn.cursor()
    p_hash = generate_password_hash(new_password)
    cur.execute("UPDATE users SET password_hash = ? WHERE username = ?", (p_hash, username))
    conn.commit()
    conn.close()

# === 资产管理 ===
def get_all_switches():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM switches ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_switch(name, ip, port, username, password, note=""):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO switches (name, ip, port, username, password, note) VALUES (?, ?, ?, ?, ?, ?)",
                (name, ip, port, username, password, note))
    conn.commit()
    conn.close()

def delete_switch(switch_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM switches WHERE id=?", (switch_id,))
    conn.commit()
    conn.close()

# 每次被引用时尝试初始化，确保表存在
init_db()