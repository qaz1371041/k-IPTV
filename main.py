import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== 配置 ====================
BASE_URL = "https://iptv.cqshushu.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}
TIMEOUT = 5                # 检测超时（秒）
MAX_WORKERS = 20           # 并发检测线程数
OUTPUT_DIR = "output"      # 输出目录
RETRY_TIMES = 3            # 请求重试次数

# 创建全局 Session
session = requests.Session()
session.headers.update(HEADERS)

# ==================== 分类映射 ====================
CCTV_KEYWORDS = ["cctv", "央视", "中央电视", "CCTV-", "CCTV"]

SATELLITE_TV = {
    "湖南卫视": ["湖南卫视", "芒果台"],
    "浙江卫视": ["浙江卫视", "中国蓝"],
    "江苏卫视": ["江苏卫视", "荔枝台"],
    "北京卫视": ["北京卫视", "BTV"],
    "东方卫视": ["东方卫视", "番茄台"],
    "广东卫视": ["广东卫视"],
    "深圳卫视": ["深圳卫视"],
    "天津卫视": ["天津卫视"],
    "山东卫视": ["山东卫视"],
    "安徽卫视": ["安徽卫视"],
    "江西卫视": ["江西卫视"],
    "河南卫视": ["河南卫视"],
    "湖北卫视": ["湖北卫视"],
    "重庆卫视": ["重庆卫视"],
    "四川卫视": ["四川卫视"],
    "云南卫视": ["云南卫视"],
    "贵州卫视": ["贵州卫视"],
    "陕西卫视": ["陕西卫视"],
    "甘肃卫视": ["甘肃卫视"],
    "青海卫视": ["青海卫视"],
    "宁夏卫视": ["宁夏卫视"],
    "新疆卫视": ["新疆卫视"],
    "西藏卫视": ["西藏卫视"],
    "内蒙古卫视": ["内蒙古卫视"],
    "黑龙江卫视": ["黑龙江卫视"],
    "吉林卫视": ["吉林卫视"],
    "辽宁卫视": ["辽宁卫视"],
    "河北卫视": ["河北卫视"],
    "山西卫视": ["山西卫视"],
    "福建卫视": ["福建卫视", "东南卫视"],
    "海南卫视": ["海南卫视", "旅游卫视"],
    "广西卫视": ["广西卫视"],
    "香港卫视": ["香港卫视"],
    "澳门卫视": ["澳门卫视"],
    "台湾卫视": ["台湾卫视"],
}

def classify_channel(name: str) -> str:
    """根据频道名自动归类"""
    name_lower = name.lower()
    for kw in CCTV_KEYWORDS:
        if kw in name_lower:
            return "央视"
    for tv_name, keywords in SATELLITE_TV.items():
        for kw in keywords:
            if kw in name:
                return tv_name
    return "其他"

# ==================== 带重试的请求函数 ====================
def fetch_url(url, params=None, retries=RETRY_TIMES, delay=2):
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as e:
            print(f"  请求失败 (尝试 {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                raise
    return None

# ==================== 抓取首页分页 ====================
def get_page(page=1, t='all', province='all', limit=6):
    params = {'t': t, 'province': province, 'limit': limit, 'page': page}
    return fetch_url(BASE_URL, params=params)

def parse_ip_list(html):
    """解析HTML表格，返回IP信息列表"""
    soup = BeautifulSoup(html, 'html.parser')
    rows = soup.select("table.iptv-table tbody tr")
    ips = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        ip_cell = cells[0]
        a_tag = ip_cell.find("a")
        if not a_tag or "onclick" not in a_tag.attrs:
            continue
        onclick = a_tag["onclick"]
        match = re.search(r"gotoIP\s*\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", onclick)
        if not match:
            continue
        token, iptype = match.groups()
        ips.append({
            "ip": a_tag.get_text(strip=True),
            "token": token,
            "type": iptype,
            "province": cells[2].get_text(strip=True),
            "count": cells[1].get_text(strip=True),
        })
    return ips

# ==================== 获取IP详情频道 ====================
def get_channels(token, iptype):
    url = f"{BASE_URL}iptv_channel.php?token={token}&type={iptype}"
    html = fetch_url(url)
    if not html:
        return []
    soup = BeautifulSoup(html, 'html.parser')
    channels = []
    # 尝试常见选择器
    rows = soup.select(".channels-table tbody tr")
    if not rows:
        rows = soup.select("table tbody tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        name = cells[0].get_text(strip=True)
        a_tag = cells[1].find("a")
        url = a_tag.get("href") if a_tag else cells[1].get_text(strip=True)
        if url and ("http" in url or "m3u8" in url or "ts" in url):
            channels.append({"name": name, "url": url})
    return channels

# ==================== 检测URL可用性 ====================
def check_url(url: str) -> bool:
    try:
        r = requests.head(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200:
            content_type = r.headers.get("Content-Type", "")
            if any(x in content_type for x in ["video", "mpegurl", "audio"]):
                return True
        r = requests.get(url, timeout=TIMEOUT, stream=True)
        if r.status_code == 200:
            chunk = next(r.iter_content(1024), None)
            if chunk:
                return True
    except:
        pass
    return False

# ==================== 处理单个IP ====================
def process_ip(ip_info):
    channels = get_channels(ip_info["token"], ip_info["type"])
    if not channels:
        return None
    valid = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_ch = {executor.submit(check_url, ch["url"]): ch for ch in channels}
        for future in as_completed(future_to_ch):
            ch = future_to_ch[future]
            try:
                if future.result():
                    ch["valid"] = True
                    ch["category"] = classify_channel(ch["name"])
                    valid.append(ch)
            except:
                pass
    if not valid:
        return None
    return {
        "ip": ip_info["ip"],
        "type": ip_info["type"],
        "province": ip_info.get("province", ""),
        "channels": valid
    }

# ==================== 生成播放列表 ====================
def generate_playlists(all_results):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    categories = {}
    for result in all_results:
        for ch in result["channels"]:
            cat = ch["category"]
            categories.setdefault(cat, []).append(ch)

    # 主M3U（带分组）
    m3u_path = os.path.join(OUTPUT_DIR, "iptv_all.m3u")
    with open(m3u_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for cat, channels in categories.items():
            f.write(f'#EXTINF:-1 group-title="{cat}",{cat}\n')
            for ch in channels:
                f.write(f'#EXTINF:-1 tvg-logo="" group-title="{cat}",{ch["name"]}\n')
                f.write(f'{ch["url"]}\n')

    # 各分类独立M3U
    for cat, channels in categories.items():
        cat_path = os.path.join(OUTPUT_DIR, f"{cat}.m3u")
        with open(cat_path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in channels:
                f.write(f'#EXTINF:-1,{ch["name"]}\n')
                f.write(f'{ch["url"]}\n')

    # TXT格式
    txt_path = os.path.join(OUTPUT_DIR, "iptv_all.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for cat, channels in categories.items():
            f.write(f"# {cat}\n")
            for ch in channels:
                f.write(f"{ch['url']}\n")

    total = sum(len(v) for v in categories.values())
    print(f"✅ 生成完成，总计 {total} 个有效频道")
    for cat, channels in categories.items():
        print(f"   - {cat}: {len(channels)} 个")

# ==================== 主函数 ====================
def main():
    print("🚀 开始抓取所有分页IP...")
    all_ips = []
    page = 1
    while True:
        print(f"  抓取第 {page} 页...")
        try:
            html = get_page(page=page)
            ips = parse_ip_list(html)
            if not ips:
                print("  当前页无IP，停止分页。")
                break
            all_ips.extend(ips)
            soup = BeautifulSoup(html, 'html.parser')
            next_link = soup.select_one("a.pagination-btn:contains('下一页')")
            if not next_link:
                break
            page += 1
            time.sleep(random.uniform(1, 3))  # 随机延迟
        except Exception as e:
            print(f"  抓取第 {page} 页失败: {e}")
            break

    print(f"📡 共发现 {len(all_ips)} 个IP")
    if not all_ips:
        print("❌ 未获取到任何IP，退出。")
        return

    all_results = []
    for idx, ip_info in enumerate(all_ips, 1):
        print(f"⏳ 处理 {idx}/{len(all_ips)}: {ip_info['ip']} ({ip_info.get('province', '未知')})")
        try:
            result = process_ip(ip_info)
            if result:
                all_results.append(result)
                print(f"   ✅ 有效频道: {len(result['channels'])} 个")
            else:
                print(f"   ❌ 无有效频道")
        except Exception as e:
            print(f"   ❌ 处理失败: {e}")
        time.sleep(random.uniform(0.5, 1.5))

    generate_playlists(all_results)

if __name__ == "__main__":
    main()
