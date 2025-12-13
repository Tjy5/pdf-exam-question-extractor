import os
from pathlib import Path

total_size = 0
count = 0

for root, dirs, files in os.walk('pdf_images'):
    for f in files:
        if f.endswith(('.png', '.jpg', '.jpeg')):
            file_path = os.path.join(root, f)
            total_size += os.path.getsize(file_path)
            count += 1

print(f'图片文件数: {count}')
print(f'总大小: {total_size / (1024*1024):.2f} MB')
