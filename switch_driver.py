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

    def get_interface_list(self):
        conn = self._get_connection()
        # 获取 brief 信息
        brief_out = conn.send_command("display interface brief")
        # 获取详细配置信息（为了拿 description）
        config_out = conn.send_command("display current-configuration interface")
        conn.disconnect()

        # 1. 解析 brief 获取接口名
        interfaces = []
        lines = brief_out.split('\n')
        for line in lines:
            parts = line.split()
            if len(parts) > 0:
                if parts[0].startswith('GE') or parts[0].startswith('XGE') or parts[0].startswith('Gigabit'):
                    interfaces.append({'name': parts[0], 'desc': ''})
        
        # 2. 解析 config 获取 description
        current_iface = None
        for line in config_out.split('\n'):
            line = line.strip()
            if line.startswith('interface '):
                current_iface = line.split(' ')[1]
            elif line.startswith('description ') and current_iface:
                desc_text = line.replace('description ', '')
                # 找到对应的接口并更新描述
                for iface in interfaces:
                    if iface['name'] == current_iface:
                        iface['desc'] = desc_text
                        break
        
        # 3. 格式化输出
        result = []
        for iface in interfaces:
            display_text = iface['name']
            if iface['desc']:
                display_text += f" ({iface['desc']})"
            result.append({'value': iface['name'], 'text': display_text})
            
        return result

    def get_port_info(self, interface_name):
        conn = self._get_connection()
        cmds = [
            f"display current-configuration interface {interface_name}",
            f"display this interface {interface_name}" # 备用
        ]
        output = ""
        for cmd in cmds:
            output = conn.send_command(cmd)
            if "interface" in output: break 
        conn.disconnect()

        vlan = ""
        vlan_match = re.search(r'port access vlan (\d+)', output)
        if vlan_match:
            vlan = vlan_match.group(1)

        bindings = []
        for line in output.split('\n'):
            if 'ip-source binding' in line:
                # 格式通常是: ip-source binding ip-address 192.168.1.1 mac-address 0000-1111-2222
                ip_match = re.search(r'ip-address ([\d\.]+)', line)
                mac_match = re.search(r'mac-address ([\w\-]+)', line)
                if ip_match and mac_match:
                    bindings.append({'ip': ip_match.group(1), 'mac': self.format_mac(mac_match.group(1))})
        
        return {'vlan': vlan, 'bindings': bindings}, output

    def configure_port_binding(self, interface_name, vlan_id, bind_ip, bind_mac):
        cmds = [
            f"interface {interface_name}",
            "stp edged-port",
            f"port access vlan {vlan_id}",
            "ip verify source ip-address mac-address",
            f"ip-source binding ip-address {bind_ip} mac-address {self.format_mac(bind_mac)}"
        ]
        
        conn = self._get_connection()
        output = conn.send_config_set(cmds)
        conn.save_config()
        conn.disconnect()
        return output

    def delete_port_binding(self, interface_name, del_ip, del_mac):
        cmds = [
            f"interface {interface_name}",
            f"undo ip-source binding ip-address {del_ip} mac-address {self.format_mac(del_mac)}"
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

    # === 新增：获取完整配置 ===
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