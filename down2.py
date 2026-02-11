# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests",
#     "selenium",
# ]
# ///


from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.chrome.options import Options
import time
import os
import re
import requests

# Setup download directory
script_dir = os.path.dirname(os.path.abspath(__file__))
download_dir = os.path.join(script_dir, "downloaded_images")
os.makedirs(download_dir, exist_ok=True)


# 1. Setup WebDriver with network logging (新版写法)
caps = DesiredCapabilities.CHROME.copy()
caps['goog:loggingPrefs'] = {'performance': 'ALL'}
options = Options()
for k, v in caps.items():
    options.set_capability(k, v)
driver = webdriver.Chrome(options=options)
driver.get("https://endfield.hypergryph.com/special/over-the-frontier")

collected_image_urls = set()
last_new_image_timestamp = time.time()
inactivity_threshold_seconds = 10
max_clicks = 500
click_count = 0
url_pattern = re.compile(r'https://web\.hycdn\.cn/endfield/special/over-the-frontier/assets/imgs/.*\.(jpg|png|jpeg|webp)', re.IGNORECASE)

def download_image(url):
    """立即下载图片"""
    try:
        filename = url.split("/")[-1].split("?")[0]
        file_path = os.path.join(download_dir, filename)
        
        if os.path.exists(file_path):
            return f"已存在: {filename}"
        
        response = requests.get(url, stream=True, timeout=10)
        response.raise_for_status()
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return f"已下载: {filename}"
    except Exception as e:
        return f"下载失败 {url}: {e}"

try:
    # 2. 查找切换按钮
    toggle_button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, ".xgkw9L"))
    )

    while click_count < max_clicks:
        # 检查是否超时无新图片
        if time.time() - last_new_image_timestamp > inactivity_threshold_seconds and len(collected_image_urls) > 0:
            print("停止: 已一段时间未检测到新图片。")
            break

        toggle_button.click()
        click_count += 1
        print(f"已点击按钮 {click_count} 次。")

        # 给页面一些时间加载新图片
        time.sleep(1)

        # 3. 获取网络日志并提取图片URL
        logs = driver.get_log('performance')
        new_image_found_this_cycle = False
        
        for log in logs:
            try:
                import json
                message = json.loads(log['message'])['message']
                if message['method'] == 'Network.responseReceived':
                    url = message['params']['response']['url']
                    if url_pattern.match(url) and url not in collected_image_urls:
                        collected_image_urls.add(url)
                        new_image_found_this_cycle = True
                        last_new_image_timestamp = time.time()
                        print(f"  发现新图片: {url}")
                        # 立即下载
                        result = download_image(url)
                        print(f"  {result}")
            except:
                pass

        if new_image_found_this_cycle:
            print(f"累计发现图片: {len(collected_image_urls)} 张")
        else:
            print("本轮未发现新图片。")

finally:
    driver.quit()

print(f"\n所有任务完成。共下载图片: {len(collected_image_urls)} 张")