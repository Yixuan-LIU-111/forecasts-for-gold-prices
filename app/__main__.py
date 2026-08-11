"""
允许通过 `python -m app` 启动后端服务（兼容开发习惯）。
实际打包入口为根目录 run.py。
"""
from run import main

if __name__ == "__main__":
    main()
