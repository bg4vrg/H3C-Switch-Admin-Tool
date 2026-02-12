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
            'global_delay_factor': 2,
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

    # ================= 核心工具：提取端口ID =================
    def _extract_id(self, name):
        """从 GE1/0/1 或 GigabitEthernet1/0/1 中提取 1/0/1"""
        # 匹配最末尾的数字组合 x/y/z 或 x/y
        match = re.search(r'(\d+/\d+/\d+|\d+/\d+)$', name)
        return match.group(1) if match else name

    # ================= 究极适配版：Brief + Config 混合解析 =================
    def get_interface_list(self):
        conn = self._get_connection()
        
        # 1. 获取所有物理端口的“骨架” (确保端口全，哪怕没配置)
        brief_out = conn.send_command("display interface brief")
        
        # 2. 获取所有接口的“血肉” (Dis Cu 确保描述准确、不截断)
        # 使用 'display current-configuration interface' 只抓接口配置，速度比全局 dis cu 快
        config_out = conn.send_command("display current-configuration interface")
        
        conn.disconnect()

        # --- 解析 Dis Cu 里的描述信息 ---
        desc_map = {} # 格式: {'1/0/1': '财务部'}
        current_if_id = None
        
        for line in config_out.split('\n'):
            line = line.strip()
            if not line: continue
            
            # 识别接口行: interface GigabitEthernet1/0/1
            if line.startswith("interface"):
                parts = line.split()
                if len(parts) > 1:
                    full_name = parts[1]
                    current_if_id = self._extract_id(full_name)
            
            # 识别描述行: description 财务部-王工
            elif line.startswith("description") and current_if_id:
                # 去掉 'description' 前缀，保留后面所有内容
                desc_text = line[len("description"):].strip()
                desc_map[current_if_id] = desc_text
                
            # 遇到 # 号或 quit 结束当前接口上下文 (H3C配置块特性)
            elif line.startswith("#") or line.startswith("quit"):
                current_if_id = None

        # --- 遍历 Brief 生成最终列表 ---
        interfaces = []
        valid_prefixes = ('GE', 'GigabitEthernet', 'XGE', 'Ten-GigabitEthernet', 'FGE', 'Eth', 'M-GE')

        for line in brief_out.split('\n'):
            line = line.strip()
            if not line: continue
            
            # Brief 第一列是接口名
            intf_name = line.split()[0]
            
            # 过滤非法端口
            is_valid = False
            for prefix in valid_prefixes:
                if intf_name.upper().startswith(prefix.upper()):
                    is_valid = True
                    break
            
            if is_valid and "INTERFACE" not in intf_name.upper():
                # 提取ID
                current_id = self._extract_id(intf_name)
                
                # 用ID去 Dis Cu 的字典里查描述
                # 这种匹配方式无视了简写(GE)和全写(GigabitEthernet)的区别，非常稳
                desc = desc_map.get(current_id, "")
                
                # 组装
                display_text = f"{intf_name} ({desc})" if desc else intf_name
                interfaces.append({'value': intf_name, 'text': display_text})
        
        return interfaces

    # ================= ACL 与 端口管理 (保持不变) =================
    def get_acl_rules(self):
        conn = self._get_connection()
        output = conn.send_command("display acl 4000")
        conn.disconnect()
        rules = []
        pattern = re.compile(r'rule\s+(\d+)\s+(permit|deny)(?:.*source-mac\s+([0-9a-f\-]+))?', re.IGNORECASE)
        for line in output.split('\n'):
            match = pattern.search(line)
            if match:
                rules.append({'id': match.group(1), 'action': match.group(2), 'mac': match.group(3) if match.group(3) else "ANY/ALL"})
        return rules

    def add_acl_mac(self, mac, rule_id=None):
        formatted_mac = self.format_mac(mac)
        conn = self._get_connection()
        cmds = ["acl mac 4000"]
        if rule_id:
            cmd = f"rule {rule_id} permit source-mac {formatted_mac} ffff-ffff-ffff"
        else:
            cmd = f"rule permit source-mac {formatted_mac} ffff-ffff-ffff"
        cmds.append(cmd)
        output = conn.send_config_set(cmds)
        conn.save_config()
        conn.disconnect()
        return output

    def delete_acl_rule(self, rule_id):
        conn = self._get_connection()
        config_cmds = ["acl mac 4000", f"undo rule {rule_id}"]
        output = conn.send_config_set(config_cmds)
        conn.save_config()
        time.sleep(2) 
        conn.disconnect()
        return output

    def get_port_info(self, interface):
        conn = self._get_connection()
        cmd = f"display current-configuration interface {interface}"
        output = conn.send_command(cmd)
        conn.disconnect()
        info = {'full_name': interface, 'vlan': '', 'bindings': []}
        name_match = re.search(r'^interface\s+(\S+)', output, re.MULTILINE)
        if name_match: info['full_name'] = name_match.group(1)
        vlan_match = re.search(r'port access vlan (\d+)', output)
        if vlan_match: info['vlan'] = vlan_match.group(1)
        bind_matches = re.findall(r'ip source binding ip-address ([\d\.]+) mac-address ([0-9a-fA-F\-]+)', output)
        for ip, mac in bind_matches: info['bindings'].append({'ip': ip, 'mac': mac})
        return info, output

    def configure_port_binding(self, interface, vlan_id, ip, mac):
        formatted_mac = self.format_mac(mac)
        conn = self._get_connection()
        commands = [
            f"interface {interface}",
            f"port access vlan {vlan_id}",
            "ip verify source ip-address mac-address",
            f"ip source binding ip-address {ip} mac-address {formatted_mac}"
        ]
        output = conn.send_config_set(commands)
        conn.save_config()
        conn.disconnect()
        return output

    def delete_port_binding(self, interface, ip, mac):
        formatted_mac = self.format_mac(mac)
        conn = self._get_connection()
        commands = [
            f"interface {interface}",
            f"undo ip source binding ip-address {ip} mac-address {formatted_mac}"
        ]
        output = conn.send_config_set(commands)
        conn.save_config()
        time.sleep(1)
        conn.disconnect()
        return output

    def save_config_to_device(self):
        conn = self._get_connection()
        output = conn.save_config()
        conn.disconnect()
        return output