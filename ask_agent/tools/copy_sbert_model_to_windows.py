#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
copy_sbert_model_to_windows.py

功能：
    将 Linux 上已缓存的 Sentence-Transformer 模型目录拷贝到目标目录，并生成 zip 打包，
    可直接搬到 Windows 使用，无需联网下载。
"""

import os
import shutil
import zipfile

# ---------------- 配置 ----------------
# Linux 上本地缓存模型路径
SRC_MODEL_PATH = "/home/fusionshen/.cache/huggingface/hub/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/snapshots/86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d"
# 拷贝到的目标目录
TARGET_DIR = "./sbert_offline_models"
# zip 文件名
ZIP_FILE_NAME = "paraphrase-multilingual-MiniLM-L12-v2.zip"

# ---------------- 函数 ----------------
def copy_model(src_path: str, target_dir: str) -> str:
    """
    拷贝模型到目标目录
    """
    os.makedirs(target_dir, exist_ok=True)
    model_name = os.path.basename(src_path)
    dest_path = os.path.join(target_dir, model_name)
    
    if os.path.exists(dest_path):
        print(f"⚠️ 目标目录已存在，覆盖: {dest_path}")
        shutil.rmtree(dest_path)
    
    print(f"🔹 拷贝模型 {model_name} 到 {dest_path} ...")
    shutil.copytree(src_path, dest_path)
    print(f"✅ 模型已拷贝完成")
    return dest_path

def zip_model(model_path: str, zip_file: str):
    """
    打包模型目录为 zip
    """
    print(f"🔹 打包 {model_path} 到 {zip_file} ...")
    with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(model_path):
            for file in files:
                abs_file = os.path.join(root, file)
                rel_path = os.path.relpath(abs_file, os.path.dirname(model_path))
                zipf.write(abs_file, rel_path)
    print(f"✅ 打包完成: {zip_file}")

# ---------------- 执行 ----------------
if __name__ == "__main__":
    copied_model_path = copy_model(SRC_MODEL_PATH, TARGET_DIR)
    zip_model(copied_model_path, os.path.join(TARGET_DIR, ZIP_FILE_NAME))
    print(f"✅ 完成！将 {ZIP_FILE_NAME} 复制到 Windows 解压即可使用")

