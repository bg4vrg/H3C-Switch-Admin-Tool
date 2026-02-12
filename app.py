import os
import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from switch_driver import H3CManager
import database as db
import traceback

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_h3c_admin_tool_2026'

# 备份文件存放目录
BACKUP_ROOT = 'backups'
if not os.path.exists(BACKUP_ROOT):
    os.makedirs(BACKUP_ROOT)

# === 登录管理器配置 ===
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    user_data = db.get_user_by_id(user_id)
    if user_data:
        return User(id=user_data['id'], username=user_data['username'])
    return None

# === 辅助函数 ===
def get_manager(data):
    port = int(data.get('port', 22)) 
    return H3CManager(data['ip'], data['user'], data['pass'], port)

# === 页面路由 ===

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_data = db.verify_user(username, password)
        if user_data:
            user = User(id=user_data['id'], username=user_data['username'])
            login_user(user)
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="❌ 用户名或密码错误")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required 
def index():
    return render_template('index.html', username=current_user.username)

# === 资产管理 API ===

@app.route('/api/switches', methods=['GET'])
@login_required
def list_switches():
    switches = db.get_all_switches()
    return jsonify({'status': 'success', 'data': switches})

@app.route('/api/switches/add', methods=['POST'])
@login_required
def add_switch_api():
    d = request.json
    try:
        db.add_switch(d['name'], d['ip'], int(d.get('port',22)), d['user'], d['pass'], d.get('note',''))
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/api/switches/delete', methods=['POST'])
@login_required
def del_switch_api():
    try:
        db.delete_switch(request.json['id'])
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/api/change_password', methods=['POST'])
@login_required
def change_pass_api():
    try:
        new_pass = request.json.get('new_password')
        if not new_pass: return jsonify({'status': 'error', 'msg': '密码不能为空'})
        db.change_password(current_user.username, new_pass)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# === 🔥 重点新增：批量备份功能 ===
@app.route('/batch_backup', methods=['POST'])
@login_required
def batch_backup():
    # 1. 获取所有设备
    switches = db.get_all_switches()
    if not switches:
        return jsonify({'status': 'error', 'msg': '数据库中没有设备，请先添加！'})

    # 2. 创建当天的备份文件夹
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_dir = os.path.join(BACKUP_ROOT, today)
    if not os.path.exists(today_dir):
        os.makedirs(today_dir)

    log_messages = [f"🚀 开始执行批量备份，共 {len(switches)} 台设备..."]
    success_count = 0
    fail_count = 0

    # 3. 循环备份
    for sw in switches:
        # 为了防止文件名非法，清理一下名称
        safe_name = sw['name'].replace('/', '_').replace('\\', '_').replace(' ', '_')
        target_ip = sw['ip']
        
        log_messages.append(f"🔄 正在连接: {sw['name']} ({target_ip})...")
        
        try:
            # 连接设备
            mgr = H3CManager(target_ip, sw['username'], sw['password'], sw['port'])
            # 抓取配置
            config_text = mgr.get_full_config()
            
            # 保存文件: backups/2026-02-12/核心交换机_192.168.1.1.cfg
            filename = f"{safe_name}_{target_ip}.cfg"
            filepath = os.path.join(today_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(config_text)
                
            success_count += 1
            log_messages.append(f"<span class='status-permit'>✅ 备份成功</span>: 已保存至 {filename}")
            
        except Exception as e:
            fail_count += 1
            error_msg = str(e)
            # 简化报错信息，只显示关键部分
            if "Authentication failed" in error_msg: error_msg = "认证失败(密码错误)"
            elif "timed out" in error_msg: error_msg = "连接超时"
            log_messages.append(f"<span class='status-deny'>❌ 备份失败</span>: {error_msg}")

    # 4. 总结
    final_msg = f"<br>🏁 <b>任务结束</b><br>成功: {success_count} 台<br>失败: {fail_count} 台<br>📁 文件保存在: {today_dir}"
    full_log = "<br>".join(log_messages) + final_msg
    
    return jsonify({'status': 'success', 'log': full_log})

# === 其他业务路由 (保持不变) ===
# 为了篇幅，以下路由逻辑不变，直接粘贴即可

@app.route('/test_connection', methods=['POST'])
@login_required
def test_connection():
    try:
        mgr = get_manager(request.json)
        info = mgr.get_device_info()
        return jsonify({'status': 'success', 'log': info.replace('\n', '<br>')})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/get_interfaces', methods=['POST'])
@login_required
def get_interfaces():
    try:
        mgr = get_manager(request.json)
        interfaces = mgr.get_interface_list()
        return jsonify({'status': 'success', 'data': interfaces})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/get_port_info', methods=['POST'])
@login_required
def get_port_info():
    try:
        mgr = get_manager(request.json)
        info, raw = mgr.get_port_info(request.json['interface'])
        return jsonify({'status': 'success', 'data': info, 'log': f"读取成功。<br>RAW:<br>{raw.replace(chr(10), '<br>')}"})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/bind_port', methods=['POST'])
@login_required
def bind_port():
    try:
        d = request.json
        mgr = get_manager(d)
        log = mgr.configure_port_binding(d['interface'], d['vlan'], d['bind_ip'], d['mac'])
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/del_port_binding', methods=['POST'])
@login_required
def del_port_binding():
    try:
        d = request.json
        mgr = get_manager(d)
        log = mgr.delete_port_binding(d['interface'], d['del_ip'], d['del_mac'])
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/get_acl', methods=['POST'])
@login_required
def get_acl():
    try:
        mgr = get_manager(request.json)
        rules = mgr.get_acl_rules()
        return jsonify({'status': 'success', 'data': rules})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/add_acl', methods=['POST'])
@login_required
def add_acl():
    try:
        d = request.json
        mgr = get_manager(d)
        rid = d.get('rule_id')
        if rid == "": rid = None
        log = mgr.add_acl_mac(d['mac'], rid)
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/del_acl', methods=['POST'])
@login_required
def del_acl():
    try:
        d = request.json
        mgr = get_manager(d)
        log = mgr.delete_acl_rule(d['rule_id'])
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/save_config', methods=['POST'])
@login_required
def save_config():
    try:
        mgr = get_manager(request.json)
        log = mgr.save_config_to_device()
        return jsonify({'status': 'success', 'log': log.replace('\n', '<br>')})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)