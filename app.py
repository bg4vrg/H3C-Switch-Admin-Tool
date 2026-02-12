# ... (保留前面的 import 和 get_manager) ...
from flask import Flask, render_template, request, jsonify
from switch_driver import H3CManager
import traceback

app = Flask(__name__)

def get_manager(data):
    port = int(data.get('port', 22)) 
    return H3CManager(data['ip'], data['user'], data['pass'], port)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/test_connection', methods=['POST'])
def test_connection():
    try:
        data = request.json
        mgr = get_manager(data)
        info = mgr.get_device_info()
        formatted_log = info.replace('\n', '<br>')
        return jsonify({'status': 'success', 'log': formatted_log})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# === 新增：获取接口列表 ===
@app.route('/get_interfaces', methods=['POST'])
def get_interfaces():
    try:
        data = request.json
        mgr = get_manager(data)
        # 调用驱动获取接口列表
        interfaces = mgr.get_interface_list()
        # 同时返回日志，方便调试
        return jsonify({
            'status': 'success', 
            'data': interfaces, 
            'log': f"成功获取 {len(interfaces)} 个物理接口。<br>请在下拉框中选择。"
        })
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# ... (ACL 路由保持不变) ...
@app.route('/get_acl', methods=['POST'])
def get_acl():
    try:
        data = request.json
        mgr = get_manager(data)
        rules = mgr.get_acl_rules()
        return jsonify({'status': 'success', 'data': rules, 'log': 'ACL 读取成功'})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/add_acl', methods=['POST'])
def add_acl():
    try:
        data = request.json
        mgr = get_manager(data)
        rule_id = data.get('rule_id')
        if rule_id == "": rule_id = None
        log = mgr.add_acl_mac(data['mac'], rule_id)
        formatted_log = log.replace('\n', '<br>')
        return jsonify({'status': 'success', 'log': formatted_log})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/del_acl', methods=['POST'])
def del_acl():
    try:
        data = request.json
        mgr = get_manager(data)
        log = mgr.delete_acl_rule(data['rule_id'])
        formatted_log = log.replace('\n', '<br>')
        return jsonify({'status': 'success', 'log': formatted_log})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# ... (端口管理路由保持不变) ...
@app.route('/get_port_info', methods=['POST'])
def get_port_info():
    try:
        data = request.json
        mgr = get_manager(data)
        info, raw_log = mgr.get_port_info(data['interface'])
        formatted_raw_log = raw_log.replace('\n', '<br>')
        return jsonify({'status': 'success', 'data': info, 'log': f"读取端口成功。<br>RAW:<br>{formatted_raw_log}"})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/bind_port', methods=['POST'])
def bind_port():
    try:
        data = request.json
        mgr = get_manager(data)
        log = mgr.configure_port_binding(data['interface'], data['vlan'], data['bind_ip'], data['mac'])
        formatted_log = log.replace('\n', '<br>')
        return jsonify({'status': 'success', 'log': formatted_log})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e) + "\n" + traceback.format_exc()})

@app.route('/del_port_binding', methods=['POST'])
def del_port_binding():
    try:
        data = request.json
        mgr = get_manager(data)
        log = mgr.delete_port_binding(data['interface'], data['del_ip'], data['del_mac'])
        formatted_log = log.replace('\n', '<br>')
        return jsonify({'status': 'success', 'log': formatted_log})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

@app.route('/save_config', methods=['POST'])
def save_config():
    try:
        data = request.json
        mgr = get_manager(data)
        log = mgr.save_config_to_device()
        formatted_log = log.replace('\n', '<br>')
        return jsonify({'status': 'success', 'log': formatted_log})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)