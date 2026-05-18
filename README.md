项目简介（中文）
股票多维度实时监控与 AI 分析系统是一款基于 Python Flask 的本地化金融数据监控工具，专为个人投资者和小型研究团队设计。

它能够：

实时监控行情：通过东方财富、腾讯财经等公开 API，获取 A 股实时价格、涨跌幅、成交量等核心量价数据。

自动计算技术指标：集成 RSI、MACD、布林带、KDJ 等常用技术指标，无需手动查表。

展示基本面数据：市盈率、市净率、总市值、ROE 等关键财务指标一目了然。

抓取新闻舆情：自动从东方财富等财经媒体获取最新相关新闻，并附带情感分析（正面/负面/中性）。

AI 智能总结：接入 DeepSeek、OpenAI、Grok、Gemini 等大模型，基于实时数据和新闻自动生成行情概述、新闻要点和综合判断。

定时自动监控：可设置任意间隔（如每 60 秒）自动刷新数据，实时告警价格异动、成交量突增、负面舆情等异常情况。

完全本地运行：所有数据处理均在本地完成，无需将隐私信息上传至任何第三方服务器。

适用场景：

个人投资者盘前/盘中快速掌握自选股动态

小型投研团队构建轻量级数据看板

AI 辅助决策的实验与学习平台

Project Introduction (English)
Multi-Dimensional Stock Real-Time Monitoring & AI Analysis System is a localized financial data monitoring tool built with Python Flask, designed for individual investors and small research teams.

Key features:

Real-time market data: Fetches live prices, percentage changes, volume, and other core metrics via public APIs from Eastmoney, Tencent Finance, etc.

Automatic technical indicators: Computes RSI, MACD, Bollinger Bands, KDJ, and more without manual lookups.

Fundamental data display: P/E ratio, P/B ratio, market cap, ROE, and other key financial indicators at a glance.

Financial news scraping: Automatically gathers the latest relevant news from Eastmoney with integrated sentiment analysis (positive/negative/neutral).

AI-powered summary: Leverages large language models (DeepSeek, OpenAI, Grok, Gemini) to generate market overviews, news highlights, and comprehensive judgment based on real-time data and news.

Scheduled monitoring: Customizable refresh intervals (e.g., every 60 seconds) with automatic alerts for price swings, volume spikes, and negative sentiment.

Fully local processing: All data processing happens on your local machine, ensuring no sensitive information is uploaded to third-party servers.

Use Cases:

Individual investors quickly grasping stock dynamics before or during trading hours

Small investment teams building lightweight data dashboards

AI-assisted decision-making experimentation and learning platform

技术栈
层级	技术
后端框架	Flask
前端	原生 HTML/CSS/JavaScript
数据源	东方财富 API、腾讯财经 API、新浪财经 API
AI 模型	DeepSeek、OpenAI、Grok、Gemini
技术指标计算	NumPy、Pandas
定时调度	Flask-APScheduler
加密存储	cryptography (Fernet)
