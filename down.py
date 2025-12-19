# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests",
#     "selenium",
#     "webdriver-manager",
# ]
# ///
import os
import time
import requests
import re
from urllib.parse import urlparse, unquote
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# --- 配置区域 ---
#TARGET_URL = "https://jcomic.net/page/[Pixiv]%20NekoBlow%20(30960989)"

TARGET_URL = "https://hentaiera.com/gallery/1288085/"

# 模式选择
# 0: 极速流式模式 (针对短效链接，如 Cloudflare R2)。边滚边下，高并发，支持截图兜底。
# 1: 稳健批量模式 (针对普通长效链接)。先滚动到底部收集所有链接，最后统一批量下载。
MODE = 1
# ----------------

def sanitize_filename(name):
    """清理文件名中的非法字符"""
    return re.sub(r'[\\/*?:"<>|]', "", name)

def init_driver():
    """
    初始化 Chrome 浏览器驱动。
    """
    print("初始化 Chrome 驱动")
    chrome_options = Options()
    
    # 基础设置
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    # 如果你想不显示浏览器界面（后台运行），取消下面这行的注释：
    # chrome_options.add_argument('--headless') 
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36')
    chrome_options.add_argument('--ignore-certificate-errors')
    
    # **关键**: 设置页面加载策略为 'eager'
    # 'normal': (默认) 等待所有资源(图片/CSS)加载完成 -> 导致一直转圈不执行代码
    # 'eager': DOMContentLoaded 事件触发即返回 -> DOM 结构有了就开始跑代码，不用等图片转圈
    chrome_options.page_load_strategy = 'eager'

    try:
        # 优先尝试直接启动 (利用 Selenium 4.6+ 内置的 Selenium Manager，通常不需要梯子)
        driver = webdriver.Chrome(options=chrome_options)
    except Exception:
        # 如果失败，再尝试使用 webdriver_manager (可能会因为网络问题报错)
        print("内置驱动启动失败，尝试下载驱动...")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
    return driver

import concurrent.futures

def process_mode_0(driver, folder_name):
    """
    模式 0: 极速流式模式
    一边滚动页面，一边查找并下载图片。
    """
    print("[模式 0] 开始滚动页面并同步下载资源...")
    
    processed_urls = set()
    last_height = driver.execute_script("return document.body.scrollHeight")
    
    # 创建线程池
    # 增加并发数到 25，以应对大量短效链接
    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        while True:
            # 查找当前页面上的所有媒体元素
            images = driver.find_elements(By.TAG_NAME, 'img')
            videos = driver.find_elements(By.TAG_NAME, 'video')
            
            current_elements = []
            # 收集 img
            for img in images:
                src = img.get_attribute('src')
                if src: current_elements.append((src, img))
                else:
                    data_src = img.get_attribute('data-src')
                    if data_src: current_elements.append((data_src, img))
            
            # 收集 video
            for vid in videos:
                src = vid.get_attribute('src')
                if src: current_elements.append((src, vid))

            # 收集本轮新任务
            new_tasks = []
            for url, element in current_elements:
                if url not in processed_urls:
                    processed_urls.add(url)
                    print(f"发现新资源: {os.path.basename(urlparse(url).path)[:20]}...")
                    new_tasks.append((url, element))
            
            if new_tasks:
                print(f"    -> 本轮新增 {len(new_tasks)} 个任务，并发下载中...")
                # 提交 requests 下载任务
                future_to_element = {
                    executor.submit(download_file_requests_only, url, folder_name, TARGET_URL): (url, element)
                    for url, element in new_tasks
                }
                
                for future in concurrent.futures.as_completed(future_to_element):
                    url, element = future_to_element[future]
                    try:
                        success = future.result()
                        if not success:
                            # requests 失败，主线程立即截图
                            print(f"    [!] requests 失败，转为主线程截图: {os.path.basename(urlparse(url).path)[:15]}...")
                            
                            # 计算文件名以便保存
                            parsed = urlparse(url)
                            filename = os.path.basename(parsed.path)
                            if not filename or len(filename) > 100: filename = f"file_{hash(url)}.jpg"
                            filename = unquote(sanitize_filename(filename))
                            
                            # 自动重命名避免覆盖
                            base, ext = os.path.splitext(filename)
                            counter = 1
                            save_path = os.path.join(folder_name, filename)
                            while os.path.exists(save_path):
                                save_path = os.path.join(folder_name, f"{base}_{counter}{ext}")
                                counter += 1
                            
                            save_image_from_browser(driver, element, save_path)
                    except Exception as exc:
                        print(f"    [!] 任务异常: {exc}")

            # 向下滚动
            # 减小滚动步长，增加检查频率，让下载更及时
            driver.execute_script("window.scrollBy(0, 400);")
            time.sleep(0.2) # 减少等待时间
            
            # 检查是否到底
            new_height = driver.execute_script("return window.pageYOffset + window.innerHeight")
            total_height = driver.execute_script("return document.body.scrollHeight")
            
            if new_height >= total_height:
                # 再次确认
                time.sleep(2)
                new_total_height = driver.execute_script("return document.body.scrollHeight")
                if new_total_height == total_height:
                    break
                else:
                    total_height = new_total_height
                    last_height = new_total_height

def process_mode_1(driver, folder_name):
    """
    模式 1: 稳健批量模式
    先滚动到底部收集所有链接，最后统一批量下载。
    """
    print("[模式 1] 开始滚动页面以收集所有资源链接...")

    # 尝试点击 "Show all" 按钮 (针对部分折叠的画廊)
    try:
        # 查找包含 "Show all" 文本的元素
        show_all_btns = driver.find_elements(By.XPATH, "//*[contains(text(), 'Show all') or contains(text(), 'Show All') or contains(text(), 'Load full')]")
        for btn in show_all_btns:
            # 确保元素可见且可点击
            if btn.is_displayed():
                print("    -> 发现 'Show all' 按钮，尝试点击...")
                # 使用 JS 点击以规避遮挡
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(3) # 等待内容展开
                break
    except Exception as e:
        print(f"    [!] 尝试点击 Show all 失败: {e}")
    
    collected_urls = set()
    last_height = driver.execute_script("return document.body.scrollHeight")
    
    while True:
        # 查找当前页面上的所有媒体元素
        images = driver.find_elements(By.TAG_NAME, 'img')
        videos = driver.find_elements(By.TAG_NAME, 'video')
        
        # 收集 img
        for img in images:
            candidate_url = None
            
            # 1. 优先检查父级 <a> 标签 (针对需要点击才能看原图的网站)
            try:
                # 获取父元素
                parent = driver.execute_script("return arguments[0].parentNode;", img)
                if parent and parent.tag_name.lower() == 'a':
                    href = parent.get_attribute('href')
                    # 如果有链接，优先使用链接 (可能是原图，也可能是详情页)
                    if href:
                        candidate_url = href
            except Exception:
                pass

            # 2. 其次检查常见的高清图属性
            if not candidate_url:
                for attr in ['data-original', 'data-full', 'data-large', 'data-src']:
                    val = img.get_attribute(attr)
                    if val:
                        candidate_url = val
                        break
            
            # 3. 最后使用 src (兜底)
            if not candidate_url:
                candidate_url = img.get_attribute('src')

            if candidate_url:
                collected_urls.add(candidate_url)
        
        # 收集 video
        for vid in videos:
            src = vid.get_attribute('src')
            if src: collected_urls.add(src)
            
        print(f"    -> 当前已收集 {len(collected_urls)} 个资源...", end="\r")

        # 向下滚动
        # 减慢滚动速度以等待加载 (步长减小，等待增加)
        driver.execute_script("window.scrollBy(0, 300);")
        time.sleep(1.5) 
        
        # 检查是否到底
        new_height = driver.execute_script("return window.pageYOffset + window.innerHeight")
        total_height = driver.execute_script("return document.body.scrollHeight")
        
        if new_height >= total_height:
            time.sleep(2)
            new_total_height = driver.execute_script("return document.body.scrollHeight")
            if new_total_height == total_height:
                break
            else:
                total_height = new_total_height
                last_height = new_total_height

    print(f"\n[模式 1] 收集完成，共 {len(collected_urls)} 个资源。开始批量下载...")
    
    # 开始批量下载
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for url in collected_urls:
            futures.append(executor.submit(download_file_requests_only, url, folder_name, TARGET_URL))
        
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            print(f"进度: [{completed}/{len(collected_urls)}]", end="\r")
            try:
                future.result()
            except Exception:
                pass
    print("\n[模式 1] 下载任务全部完成。")

def download_file_requests_only(url, folder_path, referer):
    """
    仅尝试使用 requests 下载。
    支持自动解析 HTML 页面中的 og:image (针对详情页链接)。
    返回 True 表示成功，False 表示失败。
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        }

        # 1. 预检: 如果 URL 看起来不像图片，先尝试作为网页解析
        is_image_url = any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.webm'])
        
        if not is_image_url:
            try:
                # 获取页面内容
                with requests.get(url, headers=headers, timeout=10, stream=True) as r:
                    content_type = r.headers.get('Content-Type', '').lower()
                    if 'text/html' in content_type:
                        # 读取页面 HTML
                        html = r.text
                        # 尝试提取 og:image
                        og_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html, re.IGNORECASE)
                        if not og_match:
                            og_match = re.search(r'<meta\s+content="([^"]+)"\s+property="og:image"', html, re.IGNORECASE)
                        
                        if og_match:
                            real_image_url = og_match.group(1)
                            print(f"    -> 解析详情页成功，发现图片: {os.path.basename(urlparse(real_image_url).path)}")
                            # 递归调用下载真实图片
                            return download_file_requests_only(real_image_url, folder_path, referer)
            except Exception:
                pass # 解析失败，继续尝试直接下载 (万一它是没有后缀的图片链接)

        # 2. 常规下载流程
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        if not filename or len(filename) > 100:
            filename = f"file_{hash(url)}.jpg"
        
        filename = unquote(filename)
        filename = sanitize_filename(filename)
        
        # 如果此时还没有扩展名，尝试从 Content-Type 猜测，或者默认 jpg
        if '.' not in filename:
             filename += ".jpg"

        save_path = os.path.join(folder_path, filename)
        
        # 自动重命名避免覆盖
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(save_path):
            save_path = os.path.join(folder_path, f"{base}_{counter}{ext}")
            counter += 1
        
        with requests.get(url, headers=headers, stream=True, timeout=10) as r:
            if r.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"[+] 下载成功: {filename}")
                return True
            else:
                return False
    except Exception:
        return False

import base64

def save_image_from_browser(driver, element, save_path):
    """
    尝试从浏览器中直接保存图片。
    策略 1: Canvas 导出 (获取原图数据，如果未跨域)
    策略 2: 截图 (Screenshot, 兜底方案)
    """
    print(f"    -> 尝试从浏览器保存图片...")
    
    # 策略 1: 尝试使用 Canvas 提取 Base64
    try:
        js_canvas = """
            var img = arguments[0];
            try {
                var canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth;
                canvas.height = img.naturalHeight;
                var ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                return canvas.toDataURL('image/jpeg', 0.95);
            } catch(e) {
                return "ERROR: " + e.message;
            }
        """
        result = driver.execute_script(js_canvas, element)
        
        if result and isinstance(result, str) and not result.startswith("ERROR"):
            # 保存 Base64
            header, encoded = result.split(",", 1)
            data = base64.b64decode(encoded)
            with open(save_path, 'wb') as f:
                f.write(data)
            print(f"    [+] Canvas 导出成功 (原图)")
            return True
        else:
            if result and result.startswith("ERROR"):
                print(f"    [-] Canvas 导出失败 (可能是跨域): {result[7:]}")
    except Exception as e:
        print(f"    [-] Canvas 尝试出错: {e}")

    # 策略 2: 截图 (兜底)
    try:
        # 强制修改扩展名为 png，因为截图默认是 png
        # 并添加 _screenshot 标记以便区分
        base, ext = os.path.splitext(save_path)
        save_path = f"{base}_screenshot.png"
            
        if element.screenshot(save_path):
            print(f"    [+] 截图保存成功 (可见区域): {os.path.basename(save_path)}")
            return True
    except Exception as e:
        print(f"    [!] 截图失败: {e}")
    
    return False

def download_file(url, folder_path, referer, driver=None, element=None):
    """使用 requests 下载文件，失败则尝试从浏览器保存"""
    try:
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        if not filename or len(filename) > 100:
            filename = f"file_{hash(url)}.jpg"
        
        filename = unquote(filename)
        filename = sanitize_filename(filename)
        
        if not any(filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.webm']):
            return

        save_path = os.path.join(folder_path, filename)
        if os.path.exists(save_path):
            print(f"[-] 跳过已存在: {filename}")
            return

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "Referer": referer
        }

        # 移除 Referer 头，因为某些 CDN (如 Cloudflare R2) 会检查 Referer 并拒绝跨域请求
        # 或者如果必须保留，可以尝试设置为空，或者设置为图片所在的域名
        headers.pop("Referer", None) 
        
        success = False
        try:
            with requests.get(url, headers=headers, stream=True, timeout=20) as r:
                if r.status_code == 200:
                    with open(save_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    print(f"[+] 下载成功: {filename}")
                    success = True
                else:
                    print(f"[!] requests 状态码错误 {r.status_code}: {url}")
        except Exception as req_err:
            print(f"[!] requests 下载出错: {req_err}")

        # 如果 requests 失败且提供了 driver 和 element，尝试从浏览器保存
        if not success and driver and element:
            save_image_from_browser(driver, element, save_path)

    except Exception as e:
        print(f"    [!] 下载流程出错: {e}")

def main():
    driver = init_driver()
    
    try:
        driver.get(TARGET_URL)
        time.sleep(3)
        
        # 获取网页标题作为文件夹名
        page_title = driver.title
        folder_name = sanitize_filename(page_title.strip())
        if not folder_name: folder_name = "jcomic_download"
        if not os.path.exists(folder_name):
            os.makedirs(folder_name)
        
        if MODE == 0:
            process_mode_0(driver, folder_name)
        else:
            process_mode_1(driver, folder_name)
        
        print("\n所有任务完成，关闭浏览器。")
        driver.quit()
            
    except Exception as e:
        print(f"发生错误: {e}")
        if 'driver' in locals():
            driver.quit()

if __name__ == "__main__":
    main()