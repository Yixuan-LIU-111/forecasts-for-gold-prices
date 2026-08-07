"""
页面爬虫 -> 数据落库 流水线包。

模块职责（职责分离，对齐后端-dev 流程）：
- models.py   : ORM 表定义（数据层）
- scraper.py  : 页面抓取 + HTML 解析 + 清洗（采集层）
- store.py    : 清洗校验 + upsert 落库（服务层）
- run.py      : 端到端编排入口
- tests/test_pipeline.py : 落库结果的 一致性 / 完整性 / 字段正确性 自动化测试
"""
