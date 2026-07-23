import asyncio
import aiohttp
import time
import logging
import os
from dataclasses import dataclass
from typing import List, Tuple, Optional

# 配置类
class Config:
    CONCURRENT_LIMIT = 30      # 并发限制（提高测速效率）
    TIMEOUT = 8                # 超时时间（秒）
    RETRY_TIMES = 2            # 重试次数
    OUTPUT_DIR = "output"
    LOG_FILE = "output/speed_test.log"

config = Config()

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class SpeedTestResult:
    url: str
    latency: Optional[float] = None      # 延迟（毫秒）
    resolution: Optional[str] = None     # 分辨率
    success: bool = False                # 是否成功
    error: Optional[str] = None          # 错误信息
    test_time: float = 0                 # 测试时间戳

class SpeedTester:
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=config.TIMEOUT, connect=5)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def measure_latency(self, url: str, retry_times: int = 2) -> SpeedTestResult:
        """测量单个URL的延迟"""
        result = SpeedTestResult(url=url, test_time=time.time())
        
        for attempt in range(retry_times):
            try:
                start_time = time.time()
                async with self.session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as response:
                    if response.status == 200:
                        latency = (time.time() - start_time) * 1000  # 转换为毫秒
                        result.latency = latency
                        result.success = True
                        logger.debug(f"URL: {url} 测试成功，延迟: {latency:.2f}ms")
                        break
                    else:
                        result.error = f"HTTP状态码: {response.status}"
            except asyncio.TimeoutError:
                result.error = "超时"
            except Exception as e:
                result.error = str(e)
                logger.warning(f"URL: {url} 尝试 {attempt+1}/{retry_times} 失败: {e}")
            
            await asyncio.sleep(0.5)  # 重试前等待
        
        return result
    
    async def batch_speed_test(self, urls: List[str]) -> List[SpeedTestResult]:
        """批量测速（带并发控制）"""
        if not urls:
            return []
        
        results = []
        semaphore = asyncio.Semaphore(config.CONCURRENT_LIMIT)
        
        async def worker(url):
            async with semaphore:
                result = await self.measure_latency(url, config.RETRY_TIMES)
                results.append(result)
        
        tasks = [worker(url) for url in urls]
        await asyncio.gather(*tasks)
        
        # 按延迟排序（升序），延迟为None的放在最后
        return sorted(results, key=lambda x: x.latency if x.latency is not None else float('inf'))
