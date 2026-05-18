import os, sys, json, datetime, re, time, threading, concurrent.futures, webbrowser
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
from cryptography.fernet import Fernet
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np

# ==================== 可选依赖检测 ====================
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

try:
    from flask_apscheduler import APScheduler
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False
    print("[WARN] flask-apscheduler 未安装，定时监控不可用。安装: pip install flask-apscheduler")

app = Flask(__name__)

# ==================== 配置 ====================
PROVIDERS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "default_model": "deepseek-chat"},
    "openai": {"base_url": "https://api.openai.com/v1", "default_model": "gpt-4o"},
    "grok": {"base_url": "https://api.x.ai/v1", "default_model": "grok-2-latest"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "default_model": "gemini-2.0-flash"},
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(BASE_DIR, "secret.key")
CONFIG_FILE = os.path.join(BASE_DIR, "config.enc")
CACHE_FILE = os.path.join(BASE_DIR, "monitor_cache.json")

# ==================== 加密存储 ====================
def generate_key():
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f: f.write(key)

def load_fernet():
    if not os.path.exists(KEY_FILE): generate_key()
    return Fernet(open(KEY_FILE, "rb").read())

def load_api_keys():
    if not os.path.exists(CONFIG_FILE): return {}
    fernet = load_fernet()
    with open(CONFIG_FILE, "rb") as f: encrypted = f.read()
    try:
        return json.loads(fernet.decrypt(encrypted).decode())
    except:
        return {}

def save_api_keys(keys_dict):
    fernet = load_fernet()
    encrypted = fernet.encrypt(json.dumps(keys_dict).encode())
    with open(CONFIG_FILE, "wb") as f: f.write(encrypted)

def get_api_key(provider): return load_api_keys().get(provider, "")
def set_api_key(provider, key):
    keys = load_api_keys()
    keys[provider] = key
    save_api_keys(keys)

# ==================== AI 客户端 ====================
def create_client(provider, api_key=""):
    config = PROVIDERS.get(provider)
    if not config: raise ValueError(f"不支持的提供商: {provider}")
    key = api_key or get_api_key(provider)
    if not key: raise RuntimeError(f"请提供 {provider} 的 API 密钥")
    return OpenAI(api_key=key, base_url=config["base_url"])

# ==================== 监控缓存 ====================
monitor_cache = {}
monitor_configs = []

def load_cache():
    global monitor_cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f: monitor_cache = json.load(f)
        except: pass

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(monitor_cache, f, ensure_ascii=False, indent=2)

# ==================== 1. 量价数据（东方财富实时API） ====================
def fetch_realtime_quote(symbol: str) -> dict:
    result = {"symbol": symbol, "name": "", "price": 0, "change_pct": 0, "volume": 0,
              "high": 0, "low": 0, "open": 0, "pre_close": 0, "turnover_rate": 0, "source": "东方财富API"}

    if symbol.startswith(('0', '3')): secid = f"0.{symbol}"
    elif symbol.startswith(('6', '9')): secid = f"1.{symbol}"
    else: secid = f"0.{symbol}"

    url = "http://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170,f171",
        "invt": "2", "fltt": "1",
        "cb": "jQuery_" + str(int(time.time() * 1000))
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": "http://quote.eastmoney.com/", "Accept": "*/*"}

    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=5)
            text = resp.text
            json_str = text[text.index("(") + 1 : text.rindex(")")] if text.startswith("jQuery_") else text
            data = json.loads(json_str).get("data")
            if data:
                result.update({
                    "name": data.get("f58", ""),
                    "price": data.get("f43", 0) / 100 if data.get("f43") else 0,
                    "change_pct": data.get("f170", 0) / 100 if data.get("f170") else 0,
                    "volume": data.get("f47", 0),
                    "high": data.get("f44", 0) / 100 if data.get("f44") else 0,
                    "low": data.get("f45", 0) / 100 if data.get("f45") else 0,
                    "open": data.get("f46", 0) / 100 if data.get("f46") else 0,
                    "pre_close": data.get("f60", 0) / 100 if data.get("f60") else 0,
                    "turnover_rate": data.get("f168", 0) / 100 if data.get("f168") else 0,
                })
                return result
        except Exception as e:
            print(f"[行情API] 第{attempt+1}次失败: {e}")
            time.sleep(1.5 * (attempt + 1))
    return result

# ==================== 2. 技术指标（腾讯财经 + 新浪备用） ====================
def calc_technical_indicators(symbol: str) -> dict:
    result = {"symbol": symbol, "rsi": None, "macd": None, "macd_signal": None,
              "macd_hist": None, "boll_upper": None, "boll_mid": None, "boll_lower": None,
              "kdj_k": None, "kdj_d": None, "kdj_j": None, "status": "unavailable"}

    if symbol.startswith(('0', '3')): tencent_code = f"sz{symbol}"
    elif symbol.startswith(('6', '9')): tencent_code = f"sh{symbol}"
    else: tencent_code = f"sz{symbol}"

    closes, highs, lows = [], [], []

    # 数据源1：腾讯财经
    try:
        url = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        params = {"param": f"{tencent_code},day,,,120,qfq"}
        headers = {"User-Agent": "Mozilla/5.0 ...", "Referer": "http://gu.qq.com/"}
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        data = resp.json()
        klines = data.get("data", {}).get(tencent_code, {}).get("qfqday", []) or \
                 data.get("data", {}).get(tencent_code, {}).get("day", [])
        if klines:
            for row in klines[-120:]:
                closes.append(float(row[2]))
                highs.append(float(row[3]))
                lows.append(float(row[4]))
    except Exception as e:
        print(f"[技术指标-腾讯] 失败: {e}")

    # 数据源2：新浪财经
    if not closes:
        try:
            sina_code = f"sz{symbol}" if symbol.startswith(('0', '3')) else f"sh{symbol}"
            url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_MarketService.getDailyKLine?symbol={sina_code}&scale=240&ma=no&datalen=120"
            headers = {"User-Agent": "Mozilla/5.0 ...", "Referer": "https://finance.sina.com.cn/"}
            resp = requests.get(url, headers=headers, timeout=8)
            text = resp.text
            json_str = text[text.index("(") + 1 : text.rindex(")")]
            data = json.loads(json_str).get("data", [])
            for row in data[-120:]:
                closes.append(float(row[2]))
                highs.append(float(row[3]))
                lows.append(float(row[4]))
        except Exception as e:
            print(f"[技术指标-新浪] 失败: {e}")

    if len(closes) < 26: return result

    try:
        close_arr = np.array(closes); high_arr = np.array(highs); low_arr = np.array(lows)
        # RSI
        delta = np.diff(close_arr, prepend=close_arr[0])
        gain = np.where(delta > 0, delta, 0); loss = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gain).rolling(14).mean().iloc[-1]
        avg_loss = pd.Series(loss).rolling(14).mean().iloc[-1]
        result["rsi"] = round(100 - (100 / (1 + (avg_gain / avg_loss))), 2) if avg_loss != 0 else 100.0
        # MACD
        ema12 = pd.Series(close_arr).ewm(span=12, adjust=False).mean()
        ema26 = pd.Series(close_arr).ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist = macd_line - signal_line
        result["macd"] = round(macd_line.iloc[-1], 4)
        result["macd_signal"] = round(signal_line.iloc[-1], 4)
        result["macd_hist"] = round(hist.iloc[-1], 4)
        # 布林带
        sma20 = pd.Series(close_arr).rolling(20).mean()
        std20 = pd.Series(close_arr).rolling(20).std()
        result["boll_upper"] = round(sma20.iloc[-1] + 2 * std20.iloc[-1], 2)
        result["boll_mid"] = round(sma20.iloc[-1], 2)
        result["boll_lower"] = round(sma20.iloc[-1] - 2 * std20.iloc[-1], 2)
        # KDJ
        low9 = pd.Series(low_arr).rolling(9).min()
        high9 = pd.Series(high_arr).rolling(9).max()
        rsv = ((close_arr - low9) / (high9 - low9 + 1e-9)) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d
        result["kdj_k"] = round(k.iloc[-1], 2)
        result["kdj_d"] = round(d.iloc[-1], 2)
        result["kdj_j"] = round(j.iloc[-1], 2)
        result["status"] = "ok"
    except Exception as e:
        print(f"[技术指标计算] 失败: {e}")
    return result

# ==================== 3. 基本面（腾讯财经接口） ====================
def fetch_fundamentals(symbol: str) -> dict:
    result = {"symbol": symbol, "pe": None, "pb": None, "market_cap": None,
              "total_shares": None, "eps": None, "roe": None, "status": "unavailable"}

    if symbol.startswith(('0', '3')): tencent_code = f"sz{symbol}"
    elif symbol.startswith(('6', '9')): tencent_code = f"sh{symbol}"
    else: tencent_code = f"sz{symbol}"

    try:
        url = f"http://qt.gtimg.cn/q={tencent_code}"
        headers = {"User-Agent": "Mozilla/5.0 ...", "Referer": "http://gu.qq.com/"}
        resp = requests.get(url, headers=headers, timeout=5)
        text = resp.text
        data_str = text.split('"')[1] if '"' in text else text
        fields = data_str.split("~")
        if len(fields) > 40:
            result.update({
                "pe": fields[39] if fields[39] else None,
                "market_cap": fields[45] if fields[45] else None,
                "total_shares": fields[44] if fields[44] else None,
                "pb": fields[48] if fields[48] else None,
                "eps": fields[43] if fields[43] else None,
                "roe": fields[46] if fields[46] else None,
                "status": "ok"
            })
    except Exception as e:
        print(f"[基本面] 失败: {e}")
    return result

# ==================== 4. 资金流向（akshare备用） ====================
def fetch_money_flow(symbol: str) -> dict:
    result = {"symbol": symbol, "main_net_inflow": None, "status": "unavailable"}
    if AKSHARE_AVAILABLE:
        try:
            market = "sh" if symbol.startswith("6") else "sz"
            df = ak.stock_individual_fund_flow(stock=symbol, market=market)
            if df is not None and not df.empty:
                r = df.iloc[-1]
                result["main_net_inflow"] = float(r.get("主力净流入", 0)) if pd.notna(r.get("主力净流入")) else 0
                result["status"] = "ok"
        except Exception as e:
            print(f"[资金流向] 失败: {e}")
    return result

# ==================== 5. 宏观指标（akshare备用） ====================
def fetch_macro_indicators() -> dict:
    result = {"status": "unavailable", "indicators": {}}
    if AKSHARE_AVAILABLE:
        try:
            cpi = ak.macro_china_cpi_monthly()
            if cpi is not None and not cpi.empty:
                r = cpi.iloc[-1]
                result["indicators"]["cpi"] = {"value": float(r.get("cpi", 0)), "date": str(r.get("日期", ""))}
            pmi = ak.macro_china_pmi()
            if pmi is not None and not pmi.empty:
                r = pmi.iloc[-1]
                result["indicators"]["pmi"] = {"value": float(r.get("制造业", 0)), "date": str(r.get("日期", ""))}
            result["status"] = "partial"
        except: pass
    return result

def fetch_alternative_data(symbol: str) -> dict:
    return {"symbol": symbol, "status": "not_implemented"}
def fetch_credit_risk(symbol: str) -> dict:
    return {"symbol": symbol, "status": "unavailable"}

# ==================== 6. 新闻舆情 ====================
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def crawl_finance_news(keyword: str, max_results: int = 5) -> list:
    results = []
    try:
        url = f"https://search.eastmoney.com/search?q={keyword}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select(".news-item")[:max_results]:
            title_el = item.select_one("a")
            snippet_el = item.select_one(".snippet")
            time_el = item.select_one(".time")
            title = title_el.get_text(strip=True) if title_el else ""
            results.append({
                "title": title,
                "url": title_el["href"] if title_el and title_el.has_attr("href") else "",
                "source": "东方财富",
                "snippet": snippet_el.get_text(strip=True)[:200] if snippet_el else "",
                "time": time_el.get_text(strip=True) if time_el else "",
                "sentiment": analyze_sentiment(title)
            })
    except Exception as e:
        print(f"[新闻爬取] 失败: {e}")
    return results

def analyze_sentiment(text: str) -> str:
    pos = sum(1 for w in ["涨","利好","买入","突破","看好","涨停","增持","超预期","大涨"] if w in text)
    neg = sum(1 for w in ["跌","利空","卖出","崩盘","看空","跌停","减持","低于预期","暴跌"] if w in text)
    return "positive" if pos > neg else ("negative" if neg > pos else "neutral")

# ==================== 核心快照（轻量级 + 异步新闻） ====================
def build_snapshot_quick(symbol: str) -> dict:
    """快速返回行情/指标/基本面，新闻从缓存读取（1-3秒）"""
    snapshot = {
        "symbol": symbol,
        "timestamp": datetime.datetime.now().isoformat(),
        "quote": fetch_realtime_quote(symbol),
        "technicals": calc_technical_indicators(symbol),
        "fundamentals": fetch_fundamentals(symbol),
        "money_flow": fetch_money_flow(symbol),
        "alternative": fetch_alternative_data(symbol),
        "credit_risk": fetch_credit_risk(symbol),
        "news": monitor_cache.get(symbol, {}).get("news", []),
        "alerts": []
    }
    snapshot["alerts"] = check_triggers(snapshot)
    return snapshot

def update_news_async(symbol: str, keywords: list = None):
    """后台线程更新新闻缓存"""
    try:
        kw_list = keywords or [symbol]
        all_news = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(crawl_finance_news, kw, 5): kw for kw in kw_list}
            for f in concurrent.futures.as_completed(futures):
                all_news.extend(f.result())
        seen = set()
        unique = []
        for n in all_news:
            url = n.get("url", "")
            if url and url not in seen:
                seen.add(url)
                unique.append(n)
        if symbol not in monitor_cache:
            monitor_cache[symbol] = {}
        monitor_cache[symbol]["news"] = unique
        save_cache()
    except Exception as e:
        print(f"[新闻异步] 失败: {e}")

def check_triggers(snapshot: dict) -> list:
    alerts = []
    sym = snapshot["symbol"]
    q = snapshot["quote"]
    t = snapshot["technicals"]
    chg = q.get("change_pct", 0)
    if abs(chg) > 5: alerts.append({"type":"price","level":"warning","msg":f"{sym} 涨跌幅 {chg:.2f}%"})
    elif abs(chg) > 3: alerts.append({"type":"price","level":"info","msg":f"{sym} 涨跌幅 {chg:.2f}%"})
    if t.get("rsi") and t["rsi"] > 80: alerts.append({"type":"rsi","level":"warning","msg":f"{sym} RSI超买 {t['rsi']}"})
    elif t.get("rsi") and t["rsi"] < 20: alerts.append({"type":"rsi","level":"warning","msg":f"{sym} RSI超卖 {t['rsi']}"})
    vol = q.get("volume", 0)
    prev_vol = monitor_cache.get(f"prev_vol_{sym}", 0)
    if prev_vol and vol > prev_vol * 3: alerts.append({"type":"volume","level":"warning","msg":f"{sym} 成交量放大 {vol/prev_vol:.1f}倍"})
    monitor_cache[f"prev_vol_{sym}"] = vol
    neg_news = [n for n in snapshot.get("news", []) if n.get("sentiment") == "negative"]
    if len(neg_news) >= 3: alerts.append({"type":"sentiment","level":"warning","msg":f"{sym} 出现{len(neg_news)}条负面新闻"})
    return alerts

# ==================== Flask 路由 ====================
@app.route("/")
def index():
    return render_template("index.html", providers=list(PROVIDERS.keys()))

@app.route("/snapshot", methods=["POST"])
def snapshot_route():
    data = request.get_json()
    symbols = data.get("symbols", [])
    keywords = data.get("keywords", [])
    if not symbols:
        return jsonify({"error": "股票代码列表不能为空"}), 400
    results = {}
    for sym in symbols:
        snap = build_snapshot_quick(sym)
        results[sym] = snap
        # 异步更新新闻
        threading.Thread(target=update_news_async, args=(sym, keywords)).start()
    save_cache()
    return jsonify(results)

@app.route("/alerts")
def alerts_route():
    all_alerts = []
    for sym, snap in monitor_cache.items():
        if isinstance(snap, dict) and "alerts" in snap:
            for a in snap["alerts"]:
                a["symbol"] = sym
                all_alerts.append(a)
    return jsonify(all_alerts)

@app.route("/ai_summary", methods=["POST"])
def ai_summary_route():
    data = request.get_json()
    sym = data.get("symbol", "").strip()
    provider = data.get("provider", "deepseek")
    api_key = data.get("api_key", "")
    keywords = data.get("keywords", [])
    if not sym: return jsonify({"error": "股票代码为空"}), 400
    try:
        quote = fetch_realtime_quote(sym)
        all_news = []
        for kw in (keywords or [sym]):
            all_news.extend(crawl_finance_news(kw, 5))
        client = create_client(provider, api_key)
        news_text = "\n".join([f"- {n['title']} ({n['source']})" for n in all_news[:10]])
        prompt = f"""股票 {sym}（{quote.get('name','')}）
行情：价格 {quote.get('price')}，涨跌 {quote.get('change_pct')}%
新闻：{news_text or '无'}
输出：1.行情概述 2.新闻要点 3.偏多/偏空/中性及理由"""
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return jsonify({"summary": resp.choices[0].message.content.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/save_key", methods=["POST"])
def save_key_route():
    d = request.get_json()
    set_api_key(d["provider"], d["api_key"])
    return jsonify({"success": True})

@app.route("/get_key/<provider>")
def get_key_route(provider):
    return jsonify({"key": get_api_key(provider)})

# ==================== 定时调度 ====================
if APSCHEDULER_AVAILABLE:
    class SchedulerConfig:
        SCHEDULER_API_ENABLED = False
    app.config.from_object(SchedulerConfig())
    scheduler = APScheduler()
    scheduler.init_app(app)

    def scheduled_monitor():
        with app.app_context():
            for cfg in monitor_configs:
                for sym in cfg["symbols"]:
                    snap = build_snapshot_quick(sym)
                    monitor_cache[sym] = snap
                    # 异步新闻
                    threading.Thread(target=update_news_async, args=(sym, cfg.get("keywords", []))).start()
            save_cache()

    @app.route("/monitor/start", methods=["POST"])
    def start_monitor():
        d = request.get_json()
        config = {
            "id": str(len(monitor_configs) + 1),
            "symbols": d["symbols"],
            "keywords": d.get("keywords", []),
            "interval": d.get("interval", 60),
            "active": True
        }
        monitor_configs.append(config)
        try:
            scheduler.add_job(
                id=f"m_{config['id']}",
                func=scheduled_monitor,
                trigger="interval",
                seconds=config["interval"],
                replace_existing=True
            )
            if not scheduler.running:
                scheduler.start()
            return jsonify({"success": True, "task_id": config["id"]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/monitor/stop", methods=["POST"])
    def stop_monitor():
        tid = request.get_json().get("task_id")
        for cfg in monitor_configs:
            if cfg["id"] == tid:
                cfg["active"] = False
                try: scheduler.remove_job(f"m_{tid}")
                except: pass
                return jsonify({"success": True})
        return jsonify({"error": "任务不存在"}), 404

    @app.route("/monitor/list")
    def list_monitors():
        return jsonify(monitor_configs)

# ==================== 启动 ====================
if __name__ == "__main__":
    if not os.path.exists(KEY_FILE):
        generate_key()
    load_cache()
    if APSCHEDULER_AVAILABLE:
        try:
            if not scheduler.running:
                scheduler.start()
        except: pass
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        webbrowser.open("http://127.0.0.1:5000")
    app.run(debug=False, host="127.0.0.1", port=5000)