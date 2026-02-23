# /// script
# dependencies = [
#   "requests",
# ]
# ///

import os
import time
import random
import requests
import hashlib
from datetime import datetime

# API 配置
APIS = {
    "pc": "https://api.fuukei.org/random-img/default/pc.php",
    #"pc": "https://acg.sx/images",
    "mobile": "https://api.fuukei.org/random-img/default/mobile.php",
}

SAVE_DIR = "downloaded_images"
HASH_INDEX = "hashes.txt"
# 用于存储已下载图片的 MD5 哈希值
downloaded_hashes = set()


def get_content_hash(content):
    """计算二进制内容的 MD5 值"""
    return hashlib.md5(content).hexdigest()


def get_file_hash(file_path):
    """计算文件的 MD5 值，避免一次性读入大文件"""
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def load_existing_hashes():
    """加载已保存的哈希索引，并补齐目录中现有文件的哈希"""
    os.makedirs(SAVE_DIR, exist_ok=True)

    index_path = os.path.join(SAVE_DIR, HASH_INDEX)
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    downloaded_hashes.add(line)

    for name in os.listdir(SAVE_DIR):
        file_path = os.path.join(SAVE_DIR, name)
        if not os.path.isfile(file_path):
            continue
        if name == HASH_INDEX:
            continue

        try:
            file_hash = get_file_hash(file_path)
        except OSError:
            continue

        downloaded_hashes.add(file_hash)

    with open(index_path, "w", encoding="utf-8") as f:
        for h in sorted(downloaded_hashes):
            f.write(f"{h}\n")


def download_image():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)

    mode = random.choice(["pc", "mobile"])
    url = APIS[mode]

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        # 计算当前获取到的图片哈希
        img_hash = get_content_hash(response.content)

        # 检测重复
        if img_hash in downloaded_hashes:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 检测到重复图片 ({mode})，已跳过。"
            )
            return

        # 如果不重复，记录哈希并保存
        downloaded_hashes.add(img_hash)

        index_path = os.path.join(SAVE_DIR, HASH_INDEX)
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(f"{img_hash}\n")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 将哈希值的前 8 位加入文件名，确保文件名唯一且易读
        filename = f"{mode}_{timestamp}_{img_hash[:8]}.jpg"
        filepath = os.path.join(SAVE_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(response.content)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 成功下载新图片: {filename}")

    except Exception as e:
        print(f"❌ 下载失败: {e}")


def main():
    print("🚀 启动自动去重下载任务...")
    print(f"保存目录: {os.path.abspath(SAVE_DIR)}")
    print("速率限制: 2秒/次 | 模式: MD5去重\n")

    load_existing_hashes()

    try:
        while True:
            download_image()
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n👋 程序已由用户停止。")


if __name__ == "__main__":
    main()
