import re
import time
from netmiko import ConnectHandler

class H3CManager:
    def __init__(self, ip, username, password, port=22):
        self.device_info = {
            'device_type': 'hp_comware',
            'ip': ip,
            'username': username,
            'password': password,
            'port': port,
            'global_delay_factor': 2, # 增加延时防止超时
        }

    def _get_connection(self):
        return ConnectHandler(**self.device_info)
    
    def format_mac(self, mac):
        if not mac: return ""
        clean_mac = mac.replace(":", "").replace("-", "").replace(".", "").lower()
        if len(clean_mac) != 12: return mac 
        return f"{clean_mac[0:4]}-{clean_mac[4:8]}-{clean_mac[8:12]}"

    def get_device_info(self):
        conn = self._get_connection()
        prompt = conn.find_prompt()
        hostname = prompt.replace('<', '').replace('>', '').replace('[', '').replace(']', '').strip()
        version_out = conn.send_command("display version")
        conn.disconnect()
        
        model = "Unknown Model"
        for line in version_out.split('\n'):
            if "uptime is" in line:
                model = line.split("uptime is")[0].strip()
                break
        
        if model == "Unknown Model":
            for line in version_out.split('\n'):
                if "H3C" in line and "Software" not in line:
                    model = line.strip()
                    break
                    
        return f"✅ 连接成功！\n设备名称: {hostname}\n设备型号: {model}"

# === 🛠️ 修复版 get_interface_list (支持名称自动缩写匹配) ===
    def get_interface_list(self):
        conn = self._get_connection()
        # 获取 brief 信息 (得到 GE1/0/1 这种短名)
        brief_out = conn.send_command("display interface brief")
        # 获取详细配置信息 (得到 GigabitEthernet1/0/1 这种长名 + description)
        config_out = conn.send_command("display current-configuration interface")
        conn.disconnect()

        # 1. 解析 brief 获取接口名
        interfaces = []
        lines = brief_out.split('\n')
        for line in lines:
            parts = line.split()
            if len(parts) > 0:
                # 兼容 GE, XGE (万兆), MGE (多速率), Bridge-Aggregation (聚合口)
                name = parts[0]
                if name.startswith(('GE', 'XGE', 'Gigabit', 'MGE', 'Bridge')):
                    interfaces.append({'name': name, 'desc': ''})
        
        # 2. 解析 config 获取 description
        current_iface = None
        for line in config_out.split('\n'):
            line = line.strip()
            if line.startswith('interface '):
                # 拿到长名: GigabitEthernet1/0/31
                full_name = line.split(' ')[1]
                
                # 🔄 核心修复：把长名“翻译”成短名，以便和 brief 列表匹配
                current_iface = full_name.replace('GigabitEthernet', 'GE')\
                                         .replace('Ten-GigabitEthernet', 'XGE')\
                                         .replace('M-GigabitEthernet', 'MGE')\
                                         .replace('Bridge-Aggregation', 'BAGG')
                                         
            elif line.startswith('description ') and current_iface:
                # 提取描述内容
                desc_text = line.replace('description ', '').strip()
                
                # 在列表里找这个接口，找到了就更新描述
                for iface in interfaces:
                    # 现在的 current_iface 已经是 GE1/0/31 了，可以匹配上了
                    if iface['name'] == current_iface:
                        iface['desc'] = desc_text
                        break
        
        # 3. 格式化输出 (前端下拉框使用)
        result = []
        for iface in interfaces:
            display_text = iface['name']
            if iface['desc']:
                display_text += f" ({iface['desc']})"  # 效果: GE1/0/31 (link-202.16)
            result.append({'value': iface['name'], 'text': display_text})
            
        return result

# === 🛠️ 修复版 get_port_info ===
    def get_port_info(self, interface_name):
        conn = self._get_connection()
        # 优先使用 display current-configuration，因为它格式最全
        cmds = [
            f"display current-configuration interface {interface_name}",
        ]
        output = ""
        try:
            for cmd in cmds:
                output = conn.send_command(cmd)
                if "interface" in output: break 
        except Exception as e:
            # 如果出错，至少把 output 返回去方便调试
            pass
        finally:
            conn.disconnect()

        # === 开始解析 ===
        vlan = ""
        description = ""
        bindings = []

        for line in output.split('\n'):
            line = line.strip() # 去除首尾空格

            # 1. 解析 VLAN
            # 兼容: "port access vlan 202"
            if line.startswith('port access vlan'):
                parts = line.split()
                # parts 通常是 ['port', 'access', 'vlan', '202']
                if len(parts) >= 4:
                    vlan = parts[3]

            # 2. 解析 Description (描述)
            # 兼容: "description link-202.16"
            if line.startswith('description'):
                # 使用 split(maxsplit=1) 确保只切分第一个空格
                parts = line.split(maxsplit=1)
                if len(parts) > 1:
                    description = parts[1].strip()

            # 3. 解析绑定信息 (核心修复点)
            # 你的设备输出: ip source binding ...
            # 旧版本设备输出: ip-source binding ...
            # 修复：只要行里同时包含 'source binding' 和 'ip-address' 就认为是绑定行
            if 'source binding' in line and 'ip-address' in line:
                # 使用正则提取，兼容中间有多个空格的情况 (\s+)
                ip_match = re.search(r'ip-address\s+([\d\.]+)', line)
                mac_match = re.search(r'mac-address\s+([\w\-\.]+)', line)
                
                if ip_match and mac_match:
                    bindings.append({
                        'ip': ip_match.group(1), 
                        'mac': self.format_mac(mac_match.group(1))
                    })
        
        return {
            'vlan': vlan, 
            'bindings': bindings, 
            'description': description
        }, output

# === 🛠️ 修复版：写入绑定 (去掉 ip-source 中的短横线) ===
    def configure_port_binding(self, interface_name, vlan_id, bind_ip, bind_mac):
        cmds = [
            f"interface {interface_name}",
            "stp edged-port",
            f"port access vlan {vlan_id}",
            "ip verify source ip-address mac-address",
            # 修改点：ip-source -> ip source
            f"ip source binding ip-address {bind_ip} mac-address {self.format_mac(bind_mac)}"
        ]
        
        conn = self._get_connection()
        output = conn.send_config_set(cmds)
        conn.save_config()
        conn.disconnect()
        return output

    # === 🛠️ 修复版：解除绑定 (去掉 ip-source 中的短横线) ===
    def delete_port_binding(self, interface_name, del_ip, del_mac):
        cmds = [
            f"interface {interface_name}",
            # 修改点：undo ip-source -> undo ip source
            f"undo ip source binding ip-address {del_ip} mac-address {self.format_mac(del_mac)}"
        ]
        conn = self._get_connection()
        output = conn.send_config_set(cmds)
        conn.save_config()
        conn.disconnect()
        return output

    def get_acl_rules(self, acl_number=4000):
        conn = self._get_connection()
        output = conn.send_command(f"display acl {acl_number}")
        conn.disconnect()
        
        rules = []
        # 解析规则: rule 0 permit source aaaa-bbbb-cccc ffff-ffff-ffff
        for line in output.split('\n'):
            if line.strip().startswith('rule'):
                parts = line.split()
                try:
                    rule_id = parts[1]
                    action = parts[2]
                    mac = parts[4] # 简单假设 mac 在第5个位置
                    rules.append({'id': rule_id, 'action': action, 'mac': self.format_mac(mac)})
                except:
                    pass
        return rules

    def add_acl_mac(self, mac, rule_id=None, acl_number=4000):
        cmd = f"rule {rule_id} permit" if rule_id else "rule permit"
        cmd += f" source {self.format_mac(mac)} ffff-ffff-ffff"
        
        config_cmds = [
            f"acl mac {acl_number}",
            cmd
        ]
        conn = self._get_connection()
        output = conn.send_config_set(config_cmds)
        conn.save_config()
        conn.disconnect()
        return output

    def delete_acl_rule(self, rule_id, acl_number=4000):
        config_cmds = [
            f"acl mac {acl_number}",
            f"undo rule {rule_id}"
        ]
        conn = self._get_connection()
        output = conn.send_config_set(config_cmds)
        conn.save_config()
        conn.disconnect()
        return output

    def save_config_to_device(self):
        conn = self._get_connection()
        output = conn.save_config()
        conn.disconnect()
        return output

    def get_full_config(self):
        conn = self._get_connection()
        try:
            # netmiko 会自动处理分屏 (--More--)
            config = conn.send_command("display current-configuration")
            return config
        except Exception as e:
            raise e
        finally:
            conn.disconnect()