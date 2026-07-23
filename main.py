import os
import re
import asyncio
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ============ 配置 ============
BASE_URL = "https://iptv.cqshushu.com/"
TIMEOUT = 5           # 检测超时（秒）
MAX_WORKERS = 20      # 并发检测线程数
OUTPUT_DIR = "output"

# ============ 分类映射 ============
# 央视关键词
CCTV_KEYWORDS = ["cctv", "央视", "中央电视", "CCTV-", "CCTV"]

# 卫视关键词（可自行扩展）
卫视映射 = {
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
    "湖南卫视": ["湖南卫视"],
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
    # 1. 央视
    for kw in CCTV_KEYWORDS:
        if kw in name_lower:
            return "央视"
    # 2. 卫视
    for卫视名, keywords in卫视映射.items():
        for kw in keywords:
            if kw in name:
                return卫视名
    # 3. 其他
    return "其他"


# ============ 第一步：抓取所有IP列表（使用Playwright） ============
async def fetch_all_ips():
    """使用Playwright渲染页面，获取所有IP的token和元信息"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(BASE_URL, wait_until="networkidle")
        
        # 等待表格加载
        await page.wait_for_selector("table.iptv-table tbody tr", timeout=30000)
        
        # 获取所有分页的IP
        all_ips = []
        page_num = 1
        
        while True:
            # 等待当前页表格加载
            await page.wait_for_selector("table.iptv-table tbody tr", timeout=10000)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            # 解析当前页的IP
            rows = soup.select("table.iptv-table tbody tr")
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
                all_ips.append({
                    "ip": a_tag.get_text(strip=True),
                    "token": token,
                    "type": iptype,
                    "province": cells[2].get_text(strip=True) if len(cells) > 2 else "",
                    "count": cells[1].get_text(strip=True) if len(cells) > 1 else "0",
                })
            
            # 检查是否有下一页
            next_link = soup.select_one("a.pagination-btn:contains('下一页')")
            if not next_link:
                break
            
            # 点击下一页
            await page.click("a.pagination-btn:contains('下一页')")
            await page.wait_for_timeout(2000)  # 等待加载
            page_num += 1
        
        await browser.close()
        return all_ips


# ============ 第二步：获取单个IP的频道列表 ============
async def fetch_channels(token: str, iptype: str):
    """通过token获取该IP下的所有频道"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        url = f"{BASE_URL}iptv_channel.php?token={token}&type={iptype}"
        await page.goto(url, wait_until="networkidle")
        
        # 等待频道列表加载
        await page.wait_for_selector(".channels-table tbody tr", timeout=15000)
        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        channels = []
        rows = soup.select(".channels-table tbody tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
                name = cells[0].get_text(strip=True)
                # 播放地址可能在 <a> 标签中
                a_tag = cells[1].find("a")
                url = a_tag.get("href") if a_tag else cells[1].get_text(strip=True)
                if url and (".m3u8" in url or ".ts" in url or "http" in url):
                    channels.append({"name": name, "url": url})
        
        await browser.close()
        return channels


# ============ 第三步：检测URL可用性 ============
def check_url(url: str) -> bool:
    """检测单个URL是否可播放"""
    try:
        # 先用HEAD快速检测
        r = requests.head(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200:
            content_type = r.headers.get("Content-Type", "")
            if any(x in content_type for x in ["video", "mpegurl", "audio"]):
                return True
        # HEAD不行则尝试GET少量数据
        r = requests.get(url, timeout=TIMEOUT, stream=True)
        if r.status_code == 200:
            chunk = next(r.iter_content(1024), None)
            if chunk:
                return True
    except:
        pass
    return False


# ============ 第四步：处理单个IP（获取频道 + 检测 + 分类） ============
async def process_ip(ip_info):
    """处理单个IP，返回有效的频道列表（已分类）"""
    channels = await fetch_channels(ip_info["token"], ip_info["type"])
    if not channels:
        return None
    
    # 并发检测
    valid_channels = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_ch = {executor.submit(check_url, ch["url"]): ch for ch in channels}
        for future in as_completed(future_to_ch):
            ch = future_to_ch[future]
            try:
                if future.result():
                    ch["valid"] = True
                    ch["category"] = classify_channel(ch["name"])
                    valid_channels.append(ch)
            except:
                pass
    
    if not valid_channels:
        return None
    
    return {
        "ip": ip_info["ip"],
        "type": ip_info["type"],
        "province": ip_info.get("province", ""),
        "channels": valid_channels
    }


# ============ 第五步：生成播放列表 ============
def generate_playlists(all_results):
    """生成M3U和TXT播放列表，按分类分组"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 按分类汇总
    categories = {}
    for result in all_results:
        for ch in result["channels"]:
            cat = ch["category"]
            categories.setdefault(cat, []).append(ch)
    
    # 生成主M3U（所有分类）
    m3u_path = os.path.join(OUTPUT_DIR, "iptv_all.m3u")
    with open(m3u_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for cat, channels in categories.items():
            f.write(f'#EXTINF:-1 group-title="{cat}",{cat}\n')
            for ch in channels:
                f.write(f'#EXTINF:-1 tvg-logo="" group-title="{cat}",{ch["name"]}\n')
                f.write(f'{ch["url"]}\n')
    
    # 生成每个分类的单独M3U
    for cat, channels in categories.items():
        cat_path = os.path.join(OUTPUT_DIR, f"{cat}.m3u")
        with open(cat_path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for ch in channels:
                f.write(f'#EXTINF:-1,{ch["name"]}\n')
                f.write(f'{ch["url"]}\n')
    
    # 生成TXT格式（每行一个URL）
    txt_path = os.path.join(OUTPUT_DIR, "iptv_all.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for cat, channels in categories.items():
            f.write(f"# {cat}\n")
            for ch in channels:
                f.write(f"{ch['url']}\n")
    
    print(f"✅ 播放列表已生成：{OUTPUT_DIR}/")
    print(f"   - 总计 {sum(len(v) for v in categories.values())} 个有效频道")
    for cat, channels in categories.items():
        print(f"   - {cat}: {len(channels)} 个")


# ============ 主函数 ============
async def main():
    print("🚀 开始抓取所有IP列表...")
    all_ips = await fetch_all_ips()
    print(f"📡 共发现 {len(all_ips)} 个IP")
    
    all_results = []
    for idx, ip_info in enumerate(all_ips, 1):
        print(f"⏳ 处理 {idx}/{len(all_ips)}: {ip_info['ip']} ({ip_info.get('province', '未知')})")
        result = await process_ip(ip_info)
        if result:
            all_results.append(result)
            print(f"   ✅ 有效频道: {len(result['channels'])} 个")
    
    print(f"📊 有效IP数量: {len(all_results)}")
    generate_playlists(all_results)


if __name__ == "__main__":
    asyncio.run(main())
