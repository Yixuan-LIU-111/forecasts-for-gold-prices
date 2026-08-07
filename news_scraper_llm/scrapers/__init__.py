"""
站点抓取器集合
"""
from .fed import FedScraper
from .whitehouse import WhiteHouseScraper
from .apnews import APNewsScraper
from .cnn import CNNScraper

__all__ = ["FedScraper", "WhiteHouseScraper", "APNewsScraper", "CNNScraper"]
