"""允许通过 `python -m news_scraper_llm` 运行（需从父目录 forecasts for gold prices 执行）。"""
import asyncio

from news_scraper_llm.main import main

if __name__ == "__main__":
    asyncio.run(main())
