import re
import requests
import logging
from collections import OrderedDict
from datetime import datetime
import config
import os
import difflib
import asyncio
from utils.speed_test import SpeedTester, SpeedTestResult

# 确保 output 文件夹存在
output_folder = "output"
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

# 日志记录
log_file_path = os.path.join(output_folder, "function.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, "w", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def parse_template(template_file):
    """解析模板文件，提取频道分类和频道名称"""
    template_channels = OrderedDict()
    current_category = None
    with open(template_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if "#genre#" in line:
                    current_category = line.split(",")[0].strip()
                    template_channels[current_category] = []
                elif current_category:
                    channel_name = line.split(",")[0].strip()
                    template_channels[current_category].append(channel_name)
    return template_channels

def clean_channel_name(channel_name):
    """数据清洗函数"""
    cleaned_name = re.sub(r'[$「」-]', '', channel_name)
    cleaned_name = re.sub(r'\s+', '', cleaned_name)
    cleaned_name = re.sub(r'(\D*)(\d+)', lambda m: m.group(1) + str(int(m.group(2))), cleaned_name)
    return cleaned_name.upper()

def fetch_channels(url):
    """从指定URL抓取频道列表"""
    channels = OrderedDict()
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
        lines = response.text.split("\n")
        current_category = None
        is_m3u = any(line.startswith("#EXTINF") for line in lines[:15])
        source_type = "m3u" if is_m3u else "txt"
        logging.info(f"url: {url} 成功，判断为{source_type}格式")
        if is_m3u:
            channels.update(parse_m3u_lines(lines))
        else:
            channels.update(parse_txt_lines(lines))
        if channels:
            categories = ", ".join(channels.keys())
            logging.info(f"url: {url} 成功，包含频道分类: {categories}")
    except requests.RequestException as e:
        logging.error(f"url: {url} 失败❌, Error: {e}")
    return channels

def parse_m3u_lines(lines):
    """解析M3U格式的频道列表行"""
    channels = OrderedDict()
    current_category = None
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF"):
            match = re.search(r'group-title="(.*?)",(.*)', line)
            if match:
                current_category = match.group(1).strip()
                channel_name = match.group(2).strip()
                if channel_name and channel_name.startswith("CCTV"):
                    channel_name = clean_channel_name(channel_name)
                if current_category not in channels:
                    channels[current_category] = []
        elif line and not line.startswith("#"):
            channel_url = line.strip()
            if current_category and channel_name:
                channels[current_category].append((channel_name, channel_url))
    return channels

def parse_txt_lines(lines):
    """解析TXT格式的频道列表行"""
    channels = OrderedDict()
    current_category = None
    for line in lines:
        line = line.strip()
        if "#genre#" in line:
            current_category = line.split(",")[0].strip()
            channels[current_category] = []
        elif current_category:
            match = re.match(r"^(.*?),(.*?)$", line)
            if match:
                channel_name = match.group(1).strip()
                if channel_name and channel_name.startswith("CCTV"):
                    channel_name = clean_channel_name(channel_name)
                channel_urls = match.group(2).strip().split('#')
                for channel_url in channel_urls:
                    channel_url = channel_url.strip()
                    channels[current_category].append((channel_name, channel_url))
            elif line:
                channels[current_category].append((line, ''))
    return channels

def find_similar_name(target_name, name_list):
    """查找最相似的名称"""
    matches = difflib.get_close_matches(target_name, name_list, n=1, cutoff=0.6)
    return matches[0] if matches else None

def match_channels(template_channels, all_channels):
    """匹配模板中的频道与抓取到的频道"""
    matched_channels = OrderedDict()
    all_online_channel_names = []
    for online_category, online_channel_list in all_channels.items():
        for online_channel_name, _ in online_channel_list:
            all_online_channel_names.append(online_channel_name)
    for category, channel_list in template_channels.items():
        matched_channels[category] = OrderedDict()
        for channel_name in channel_list:
            similar_name = find_similar_name(channel_name, all_online_channel_names)
            if similar_name:
                for online_category, online_channel_list in all_channels.items():
                    for online_channel_name, online_channel_url in online_channel_list:
                        if online_channel_name == similar_name:
                            matched_channels[category].setdefault(channel_name, []).append(online_channel_url)
    return matched_channels

def merge_channels(target, source):
    """合并两个频道字典"""
    for category, channel_list in source.items():
        if category in target:
            target[category].extend(channel_list)
        else:
            target[category] = channel_list

def is_ipv6(url):
    """判断URL是否为IPv6地址"""
    return re.match(r'^http:\/\/\[[0-9a-fA-F:]+\]', url) is not None

def is_video_source(url):
    """判断是否为视频源（非直播源），视频源不过滤分辨率"""
    video_extensions = ('.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.m4v')
    return url.lower().endswith(video_extensions)

def get_resolution_from_url(url):
    """
    从URL中尝试提取分辨率信息
    返回: (width, height) 或 None
    """
    # 尝试从URL中匹配分辨率模式，如 1920x1080, 1280x720, 720p, 1080p 等
    patterns = [
        r'(\d{3,4})[xX](\d{3,4})',          # 1920x1080
        r'(\d{3,4})[pP]',                   # 720p, 1080p
        r'[_-](\d{3,4})[_-]',               # _720_
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            if 'x' in pattern or 'X' in pattern:
                w = int(match.group(1))
                h = int(match.group(2))
                if w >= 1280 and h >= 720:
                    return (w, h)
            else:
                val = int(match.group(1))
                if val >= 720:
                    return (val, None)
    return None

def is_resolution_below_720p(url):
    """
    判断视频源分辨率是否低于720P
    返回: True 表示低于720P，需要过滤
    """
    # 视频源不过滤
    if is_video_source(url):
        return False
    
    resolution = get_resolution_from_url(url)
    if resolution is None:
        # 无法判断分辨率，默认保留（不过滤）
        return False
    
    if len(resolution) == 2:
        w, h = resolution
        return w < 1280 or h < 720
    else:
        val = resolution[0]
        return val < 720

async def speed_test_urls(urls, channel_name):
    """对一组URL进行测速，返回排序后的结果"""
    if not urls:
        return []
    
    logging.info(f"开始测速: {channel_name}，共 {len(urls)} 个源")
    async with SpeedTester() as tester:
        results = await tester.batch_speed_test(urls)
    
    # 按延迟排序（延迟低的优先）
    sorted_results = sorted(results, key=lambda x: x.latency if x.latency is not None else float('inf'))
    
    # 返回排序后的URL列表，失效的用 # 标记
    sorted_urls = []
    for result in sorted_results:
        if result.success:
            sorted_urls.append(result.url)
        else:
            # 失效源用 # 标记（注释掉）
            sorted_urls.append(f"#{result.url}")
    
    return sorted_urls

def filter_source_urls(template_file):
    """过滤源URL，获取匹配后的频道信息，并进行测速排序"""
    template_channels = parse_template(template_file)
    source_urls = config.source_urls
    all_channels = OrderedDict()
    
    for url in source_urls:
        fetched_channels = fetch_channels(url)
        merge_channels(all_channels, fetched_channels)
    
    matched_channels = match_channels(template_channels, all_channels)
    
    # 对每个频道的URL进行测速、排序、过滤低分辨率
    for category, channel_dict in matched_channels.items():
        for channel_name, urls in channel_dict.items():
            # 1. 过滤掉低于720P的源（视频源除外）
            filtered_urls = [url for url in urls if not is_resolution_below_720p(url)]
            if len(filtered_urls) < len(urls):
                logging.info(f"{channel_name}: 过滤掉 {len(urls) - len(filtered_urls)} 个低于720P的源")
            
            # 2. 测速并排序
            sorted_urls = asyncio.run(speed_test_urls(filtered_urls, channel_name))
            
            # 3. 更新结果
            matched_channels[category][channel_name] = sorted_urls
    
    return matched_channels, template_channels

def updateChannelUrlsM3U(channels, template_channels):
    """更新频道URL到M3U和TXT文件中"""
    written_urls_ipv4 = set()
    written_urls_ipv6 = set()
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    for group in config.announcements:
        for announcement in group['entries']:
            if announcement['name'] is None:
                announcement['name'] = current_date
    
    ipv4_m3u_path = os.path.join(output_folder, "live_ipv4.m3u")
    ipv4_txt_path = os.path.join(output_folder, "live_ipv4.txt")
    ipv6_m3u_path = os.path.join(output_folder, "live_ipv6.m3u")
    ipv6_txt_path = os.path.join(output_folder, "live_ipv6.txt")
    
    with open(ipv4_m3u_path, "w", encoding="utf-8") as f_m3u_ipv4, \
         open(ipv4_txt_path, "w", encoding="utf-8") as f_txt_ipv4, \
         open(ipv6_m3u_path, "w", encoding="utf-8") as f_m3u_ipv6, \
         open(ipv6_txt_path, "w", encoding="utf-8") as f_txt_ipv6:
        
        f_m3u_ipv4.write(f"""#EXTM3U x-tvg-url={",".join(f'"{epg_url}"' for epg_url in config.epg_urls)}\n""")
        f_m3u_ipv6.write(f"""#EXTM3U x-tvg-url={",".join(f'"{epg_url}"' for epg_url in config.epg_urls)}\n""")
        
        for group in config.announcements:
            f_txt_ipv4.write(f"{group['channel']},#genre#\n")
            f_txt_ipv6.write(f"{group['channel']},#genre#\n")
            for announcement in group['entries']:
                url = announcement['url']
                if is_ipv6(url):
                    if url not in written_urls_ipv6:
                        written_urls_ipv6.add(url)
                        f_m3u_ipv6.write(f"""#EXTINF:-1 tvg-id="1" tvg-name="{announcement['name']}" tvg-logo="{announcement['logo']}" group-title="{group['channel']}",{announcement['name']}\n""")
                        f_m3u_ipv6.write(f"{url}\n")
                        f_txt_ipv6.write(f"{announcement['name']},{url}\n")
                else:
                    if url not in written_urls_ipv4:
                        written_urls_ipv4.add(url)
                        f_m3u_ipv4.write(f"""#EXTINF:-1 tvg-id="1" tvg-name="{announcement['name']}" tvg-logo="{announcement['logo']}" group-title="{group['channel']}",{announcement['name']}\n""")
                        f_m3u_ipv4.write(f"{url}\n")
                        f_txt_ipv4.write(f"{announcement['name']},{url}\n")
        
        for category, channel_list in template_channels.items():
            f_txt_ipv4.write(f"{category},#genre#\n")
            f_txt_ipv6.write(f"{category},#genre#\n")
            if category in channels:
                for channel_name in channel_list:
                    if channel_name in channels[category]:
                        sorted_urls_ipv4 = []
                        sorted_urls_ipv6 = []
                        for url in channels[category][channel_name]:
                            # 跳过被注释的失效源（以#开头）
                            if url.startswith('#'):
                                continue
                            if is_ipv6(url):
                                if url not in written_urls_ipv6:
                                    sorted_urls_ipv6.append(url)
                                    written_urls_ipv6.add(url)
                            else:
                                if url not in written_urls_ipv4:
                                    sorted_urls_ipv4.append(url)
                                    written_urls_ipv4.add(url)
                        
                        total_urls_ipv4 = len(sorted_urls_ipv4)
                        total_urls_ipv6 = len(sorted_urls_ipv6)
                        
                        for index, url in enumerate(sorted_urls_ipv4, start=1):
                            new_url = add_url_suffix(url, index, total_urls_ipv4, "IPV4")
                            write_to_files(f_m3u_ipv4, f_txt_ipv4, category, channel_name, index, new_url)
                        
                        for index, url in enumerate(sorted_urls_ipv6, start=1):
                            new_url = add_url_suffix(url, index, total_urls_ipv6, "IPV6")
                            write_to_files(f_m3u_ipv6, f_txt_ipv6, category, channel_name, index, new_url)
            
            f_txt_ipv4.write("\n")
            f_txt_ipv6.write("\n")

def add_url_suffix(url, index, total_urls, ip_version):
    """添加URL后缀"""
    suffix = f"${ip_version}" if total_urls == 1 else f"${ip_version}•线路{index}"
    base_url = url.split('$', 1)[0] if '$' in url else url
    return f"{base_url}{suffix}"

def write_to_files(f_m3u, f_txt, category, channel_name, index, new_url):
    """写入M3U和TXT文件"""
    logo_url = f"./pic/logos{channel_name}.png"
    f_m3u.write(f"#EXTINF:-1 tvg-id=\"{index}\" tvg-name=\"{channel_name}\" tvg-logo=\"{logo_url}\" group-title=\"{category}\",{channel_name}\n")
    f_m3u.write(new_url + "\n")
    f_txt.write(f"{channel_name},{new_url}\n")

if __name__ == "__main__":
    template_file = "demo.txt"
    channels, template_channels = filter_source_urls(template_file)
    updateChannelUrlsM3U(channels, template_channels)
