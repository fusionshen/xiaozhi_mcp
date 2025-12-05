import os
import sys

# 将项目根目录加入 sys.path，确保 `import core.xxx` 不报错
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
