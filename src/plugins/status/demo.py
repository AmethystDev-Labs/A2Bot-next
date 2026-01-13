import sys
import os

# 1. 获取当前 demo.py 所在的目录
current_dir = os.path.dirname(os.path.abspath(__file__))
# 2. 将该目录加入环境变量，这样 Python 就能直接找到 linuxdo.py
sys.path.append(current_dir)

# 3. 【关键修改】去掉前面的点，改为绝对导入
from linuxdo import LinuxDoStatusClient 

c = LinuxDoStatusClient().refreshIfNeeded()

# 后续代码保持不变...
print(c.total, c.operational, c.degraded)
