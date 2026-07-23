#!/usr/bin/env python3
"""
IPTV 直播源自动更新脚本
功能：
1. 从 https://iptv.cqshushu.com/ 抓取最新直播源
2. 按频道名自动归类（央视、卫视、地方台等）
3. 并发检测流地址有效性
4. 生成分组的 M3U 播放列表
5. 更新 README 文件
"""

import requests
import re
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# ---------- 配置 ----------
BASE_URL = "https://iptv.cqshushu.com"
OUTPUT_DIR = "output"
MAX_WORKERS = 60          # 检测并发数
REQUEST_TIMEOUT = 10      # 请求超时
DETECT_TIMEOUT = 5        # 流检测超时

# ---------- 工具函数 ----------
def safe_request(url, **kwargs):
    """带重试的请求"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    for i in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=kwargs.get('timeout', REQUEST_TIMEOUT), **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if i == 2:
                raise
            time.sleep(2)

# ---------- 分类规则 ----------
def classify_channel(name):
    """根据频道名返回分组标签"""
    name = name.strip().upper()
    # 央视
    if re.search(r'CCTV|央视|CGTN|CETV|中国教育', name):
        return 'CCTV'
    # 卫视映射
    weishi_map = {
        '湖南': '湖南卫视', '浙江': '浙江卫视', '江苏': '江苏卫视', '北京': '北京卫视',
        '东方': '东方卫视', '深圳': '深圳卫视', '广东': '广东卫视', '山东': '山东卫视',
        '安徽': '安徽卫视', '天津': '天津卫视', '辽宁': '辽宁卫视', '黑龙江': '黑龙江卫视',
        '湖北': '湖北卫视', '江西': '江西卫视', '四川': '四川卫视', '河南': '河南卫视',
        '福建': '福建卫视', '重庆': '重庆卫视', '河北': '河北卫视', '贵州': '贵州卫视',
        '云南': '云南卫视', '陕西': '陕西卫视', '吉林': '吉林卫视', '广西': '广西卫视',
        '山西': '山西卫视', '内蒙古': '内蒙古卫视', '新疆': '新疆卫视', '海南': '海南卫视',
        '宁夏': '宁夏卫视', '青海': '青海卫视', '西藏': '西藏卫视', '甘肃': '甘肃卫视',
        '兵团': '兵团卫视', '卡酷': '卡酷少儿', '金鹰': '金鹰卡通', '嘉佳': '嘉佳卡通'
    }
    for keyword, group in weishi_map.items():
        if keyword in name:
            return group
    # 地方台（以省份归类）
    provinces = ['湖南', '浙江', '江苏', '广东', '山东', '湖北', '四川', '河南', '福建',
                 '安徽', '河北', '辽宁', '黑龙江', '江西', '陕西', '云南', '贵州', '海南',
                 '甘肃', '青海', '宁夏', '新疆', '西藏', '广西', '内蒙古', '吉林', '重庆',
                 '北京', '上海', '天津']
    for prov in provinces:
        if prov in name:
            return f'{prov}地方台'
    return '其他'

# ---------- 从网站获取频道数据 ----------
def get_all_channels():
    """
    获取所有频道列表。
    优先尝试直接下载M3U，失败则解析页面。
    返回 list[dict] : [{'name': 'CCTV1', 'url': 'http://...', 'group': 'CCTV'}]
    """
    # 方法1：尝试已知的M3U接口
    m3u_urls = [
        f"{BASE_URL}/iptv.m3u",
        f"{BASE_URL}/all.m3u",
        f"{BASE_URL}/tv.m3u",
        f"{BASE_URL}/jiekou.php?type=m3u",
    ]
    for url in m3u_urls:
        try:
            resp = safe_request(url)
            if '#EXTM3U' in resp.text:
                print(f"✅ 成功从 {url} 获取M3U文件")
                return parse_m3u(resp.text)
        except:
            continue

    # 方法2：从首页分页抓取IP，再到详情页获取频道
    print("⚠️ 未找到公开M3U接口，尝试从页面解析...")
    return parse_from_pages()

def parse_m3u(content):
    """解析M3U文本为频道列表"""
    channels = []
    lines = content.splitlines()
    current_name = ""
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF'):
            # 提取频道名
            name_match = re.search(r',\s*(.+)$', line)
            if name_match:
                current_name = name_match.group(1).strip()
        elif line and not line.startswith('#'):
            if current_name:
                channels.append({
                    'name': current_name,
                    'url': line,
                    'group': classify_channel(current_name)
                })
            current_name = ""
    return channels

def parse_from_pages():
    """解析首页IP列表并获取每个IP的频道（示例框架）"""
    channels = []
    # 首先获取总页数或循环爬取
    page = 1
    while True:
        url = f"{BASE_URL}/?t=all&province=all&limit=100&page={page}"
        try:
            soup = BeautifulSoup(safe_request(url).text, 'lxml')
        except:
            break
        rows = soup.select('table.iptv-table tbody tr')
        if not rows:
            break
        for row in rows:
            onclick = row.select_one('a.ip-link').get('onclick', '')
            match = re.search(r"gotoIP\('([^']+)', '([^']+)'\)", onclick)
            if not match:
                continue
            enc_id, iptype = match.groups()
            # 构造详情页URL（需根据实际站点调整）
            # 常见的可能是 iptv_channel.php?ip=xxx&type=xxx
            detail_url = f"{BASE_URL}/iptv_channel.php?ip={enc_id}&type={iptype}"
            try:
                detail_resp = safe_request(detail_url)
                ch_list = parse_detail_page(detail_resp.text, iptype)
                channels.extend(ch_list)
                print(f"解析 {iptype} IP {enc_id[:8]}... 得到 {len(ch_list)} 个频道")
            except Exception as e:
                print(f"获取详情失败: {detail_url} - {e}")
            time.sleep(0.5)  # 礼貌延迟
        page += 1
        if page > 50:  # 安全限制
            break
    return channels

def parse_detail_page(html, iptype):
    """从详情页HTML提取频道名和URL（需根据实际页面结构调整）"""
    soup = BeautifulSoup(html, 'lxml')
    channels = []
    # 假设频道以表格行呈现，包含频道名和播放链接
    # 常见结构：<tr><td>频道名</td><td><a href="rtp://...">播放</a></td></tr>
    for row in soup.select('table tbody tr'):
        cols = row.find_all('td')
        if len(cols) >= 2:
            name = cols[0].get_text(strip=True)
            link = cols[1].find('a')
            if link and link.get('href'):
                url = link['href']
                channels.append({
                    'name': name,
                    'url': url,
                    'group': classify_channel(name)
                })
    return channels

# ---------- 流有效性检测 ----------
def check_stream(url, timeout=DETECT_TIMEOUT):
    """检测流地址是否可访问"""
    try:
        resp = requests.get(url, stream=True, timeout=timeout, verify=False,
                            headers={"User-Agent": "VLC/3.0.18 LibVLC/3.0.18"})
        if resp.status_code == 200:
            # 尝试读取一小段数据
            chunk = resp.iter_content(1024).__next__()
            return len(chunk) > 10  # 至少有一些数据
        return False
    except:
        return False

def filter_valid_channels(channels):
    """并发检测，返回有效频道列表"""
    valid = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_ch = {executor.submit(check_stream, ch['url']): ch for ch in channels}
        for future in as_completed(future_to_ch):
            ch = future_to_ch[future]
            try:
                if future.result():
                    valid.append(ch)
            except Exception:
                pass
    return valid

# ---------- 生成M3U文件 ----------
def generate_m3u(group, channels, filename):
    """生成单个分组的M3U文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for ch in channels:
            f.write(f'#EXTINF:-1 group-title="{group}",{ch["name"]}\n')
            f.write(f'{ch["url"]}\n')

def save_all_m3u(groups, output_dir):
    """保存所有分组的M3U到output_dir"""
    os.makedirs(output_dir, exist_ok=True)
    for group, ch_list in groups.items():
        safe_name = re.sub(r'[\\/*?:"<>|]', '_', group)
        filename = os.path.join(output_dir, f"{safe_name}.m3u")
        generate_m3u(group, ch_list, filename)
        print(f"💾 已保存 {group}: {len(ch_list)} 个频道 → {filename}")

# ---------- 更新 README.md ----------
def update_readme(groups, total):
    with open('README.md', 'w', encoding='utf-8') as f:
        f.write(f"# 📺 IPTV 直播源（自动更新）\n\n")
        f.write(f"**更新时间：** {time.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）\n\n")
        f.write(f"**有效频道总数：** {total}\n\n")
        f.write("---\n")
        for group, ch_list in sorted(groups.items()):
            f.write(f"## {group} ({len(ch_list)} 个频道)\n\n")
            for ch in ch_list[:5]:  # 只展示前5个作为示例
                f.write(f"- {ch['name']}\n")
            if len(ch_list) > 5:
                f.write(f"- ... 等共 {len(ch_list)} 个频道\n")
            f.write(f"\n[📥 下载 {group}.m3u](./output/{re.sub(r'[\\/*?:\"<>|]', '_', group)}.m3u)\n\n")
            f.write("---\n\n")

# ---------- 主流程 ----------
def main():
    print("🚀 开始抓取 IPTV 源...")
    raw_channels = get_all_channels()
    if not raw_channels:
        print("❌ 未获取到任何频道，退出。")
        return

    # 去重（按URL）
    unique = {}
    for ch in raw_channels:
        unique[ch['url']] = ch
    channels = list(unique.values())
    print(f"📊 去重后共 {len(channels)} 个候选频道")

    # 有效性检测
    print(f"🔍 开始检测流有效性（最多 {MAX_WORKERS} 线程）...")
    valid = filter_valid_channels(channels)
    print(f"✅ 有效频道: {len(valid)} 个")

    # 分组
    groups = defaultdict(list)
    for ch in valid:
        groups[ch['group']].append(ch)

    # 保存文件
    save_all_m3u(groups, OUTPUT_DIR)

    # 更新README
    update_readme(groups, len(valid))
    print("✅ 所有操作完成！")

if __name__ == '__main__':
    # 禁用 SSL 警告（部分 IPTV 流使用自签名证书）
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
