import requests
from bs4 import BeautifulSoup
import re
import time
from concurrent.futures import ThreadPoolExecutor

BASE = "https://iptv.cqshushu.com"

def fetch_latest_m3u():
    """尝试直接从站点提供的统一接口下载"""
    # 常见可能接口
    possible_apis = [
        f"{BASE}/iptv.m3u",
        f"{BASE}/all.m3u",
        f"{BASE}/tv.m3u",
        f"{BASE}/jiekou.php?type=m3u",
    ]
    for url in possible_apis:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200 and '#EXTM3U' in resp.text:
            return resp.text
    return None
