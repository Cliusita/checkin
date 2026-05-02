#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全民K歌独立签到脚本（青龙面板）
参考：DailyCheckIn KGQQ 模块 + Chavyleung 脚本逻辑
功能：每日自动签到领鲜花（约120朵/天）

【环境变量配置】
1. KGQQ_COOKIE: 必填，全民K歌Cookie字符串，多账号用 & 或换行分隔
   需包含字段：muid, uid, userlevel, openid, openkey, opentype, qrsig, pgv_pvid
2. KGQQ_BODY: 可选，自定义签到请求体JSON字符串（抓包获取）
   若未设置，脚本会自动构建默认请求体
3. KGQQ_NOTIFY: 可选，是否开启通知，true/false，默认false

【Cookie获取方式】
1. 电脑浏览器打开 https://kg.qq.com/ 并登录
2. F12打开开发者工具 -> Network（网络）
3. 刷新页面，点击任意请求，在Headers中复制Cookie
4. 确保包含 openid, openkey, uid 等关键字段
"""

import os
import sys
import json
import re
import time
import requests
from urllib.parse import urlencode

# ==================== 配置区域 ====================

ENV_COOKIE = "KGQQ_COOKIE"
ENV_BODY = "KGQQ_BODY"
ENV_NOTIFY = "KGQQ_NOTIFY"

SIGN_URL = "https://node.kg.qq.com/webapp/proxy"

# ==================== 日志工具 ====================

def log(msg, level="INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")
    sys.stdout.flush()

# ==================== Cookie 解析 ====================

def parse_cookie(cookie_str):
    """从cookie字符串中提取关键字段"""
    cookie = cookie_str.strip()
    if not cookie:
        return None

    fields = {}
    for key in ["muid", "uid", "userlevel", "openid", "openkey", "opentype", "qrsig", "pgv_pvid"]:
        pattern = rf"{key}=([^;\s]+)"
        match = re.search(pattern, cookie)
        if match:
            fields[key] = match.group(1)

    # 兼容openid可能在cookie中的不同命名
    if "openid" not in fields:
        # 尝试从 wxopenid, qqopenid 等获取
        for alt in ["wxopenid", "qqopenid", "openid"]:
            pattern = rf"{alt}=([^;\s]+)"
            match = re.search(pattern, cookie)
            if match:
                fields["openid"] = match.group(1)
                break

    return {
        "raw": cookie,
        "fields": fields
    }

# ==================== 通知函数 ====================

def send_notify(title, content):
    """调用青龙通知"""
    notify = os.environ.get(ENV_NOTIFY, "false").lower() == "true"
    if not notify:
        return
    try:
        notify_file = "/ql/data/scripts/sendNotify.py"
        if not os.path.exists(notify_file):
            notify_file = "/ql/scripts/sendNotify.py"
        if os.path.exists(notify_file):
            import importlib.util
            spec = importlib.util.spec_from_file_location("sendNotify", notify_file)
            notify_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(notify_module)
            notify_module.send(title, content)
        else:
            log(f"【通知】{title}: {content}")
    except Exception as e:
        log(f"通知发送失败: {e}", "ERROR")

# ==================== 签到核心 ====================

def build_sign_body(cookie_fields, custom_body=None):
    """构建签到请求体"""
    if custom_body:
        try:
            body = json.loads(custom_body)
            # 替换模板变量
            body_str = json.dumps(body)
            for key, val in cookie_fields.items():
                body_str = body_str.replace(f"{{{{{key}}}}}", str(val))
            return json.loads(body_str)
        except Exception as e:
            log(f"自定义body解析失败: {e}，使用默认body", "WARN")

    # 默认请求体（参考 Chavyleung 抓包逻辑）
    body = {
        "cmd": "task.revisionSignInGetAward",
        "data": {
            "platform": 4,
            "version": "8.1.38",
            "uin": cookie_fields.get("uid", ""),
            "openid": cookie_fields.get("openid", ""),
            "openkey": cookie_fields.get("openkey", ""),
            "opentype": cookie_fields.get("opentype", ""),
        },
        "appid": "wx5ed5823d0d0aa4b5",
        "openid": cookie_fields.get("openid", ""),
        "openkey": cookie_fields.get("openkey", ""),
    }
    return body

def get_gtk(skey):
    """计算g_tk（腾讯系通用算法）"""
    if not skey:
        return ""
    hash_val = 5381
    for char in skey:
        hash_val += (hash_val << 5) + ord(char)
    return str(hash_val & 0x7fffffff)

def sign(cookie_info, custom_body=None, index=1):
    """执行签到"""
    raw_cookie = cookie_info["raw"]
    fields = cookie_info["fields"]

    log(f"========== 开始签到 账号[{index}] ==========")

    # 构建请求头
    headers = {
        "Host": "node.kg.qq.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://kg.qq.com",
        "Referer": "https://kg.qq.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": raw_cookie,
    }

    # 构建请求体
    body = build_sign_body(fields, custom_body)

    # 计算g_tk（如果有qrsig）
    gtk = ""
    if "qrsig" in fields:
        gtk = get_gtk(fields["qrsig"])

    url = SIGN_URL
    if gtk:
        url = f"{SIGN_URL}?g_tk={gtk}&g_tk_openkey={gtk}"

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=30,
            allow_redirects=False
        )

        log(f"HTTP状态码: {resp.status_code}")

        try:
            result = resp.json()
        except Exception:
            log(f"响应解析失败，原始内容: {resp.text[:500]}", "ERROR")
            return False, "响应解析失败"

        log(f"接口返回: {json.dumps(result, ensure_ascii=False, indent=2)}")

        # 解析返回结果（参考 Chavyleung 脚本逻辑）
        if "data" in result and "task.revisionSignInGetAward" in result["data"]:
            award_data = result["data"]["task.revisionSignInGetAward"]
            ret = award_data.get("ret", 0)
            total = award_data.get("total", 0)

            if ret == -11532:
                msg = f"今日已签到，已连续签到 {total} 天"
                log(msg)
                return True, msg
            elif total != 0 or ret == 0:
                awards = award_data.get("awards", [])
                num = awards[0].get("num", 0) if awards else 0
                msg = f"签到成功，获得鲜花 {num} 朵，已连续签到 {total} 天"
                log(msg)
                return True, msg
            else:
                msg = f"签到异常，返回码: {ret}"
                log(msg, "WARN")
                return False, msg
        elif "code" in result:
            code = result.get("code", -1)
            msg = result.get("msg", result.get("message", "未知错误"))
            if code == 0 or "成功" in msg or "已经签到" in msg or "重复" in msg:
                log(f"签到结果: {msg}")
                return True, msg
            else:
                log(f"签到失败: {msg} (code={code})", "ERROR")
                return False, msg
        else:
            msg = f"未知响应格式: {json.dumps(result, ensure_ascii=False)[:200]}"
            log(msg, "WARN")
            return False, msg

    except requests.exceptions.Timeout:
        msg = "请求超时"
        log(msg, "ERROR")
        return False, msg
    except Exception as e:
        msg = f"请求异常: {str(e)}"
        log(msg, "ERROR")
        return False, msg

# ==================== 主函数 ====================

def main():
    log("=" * 50)
    log("全民K歌自动签到脚本启动")
    log("参考：DailyCheckIn KGQQ + Chavyleung qmkg")
    log("=" * 50)

    # 读取环境变量
    cookie_env = os.environ.get(ENV_COOKIE, "")
    if not cookie_env:
        log(f"未找到环境变量 {ENV_COOKIE}，请先在青龙面板配置Cookie", "ERROR")
        log("配置示例：export KGQQ_COOKIE='muid=xxx; uid=xxx; openid=xxx; openkey=xxx; ...'")
        sys.exit(1)

    custom_body = os.environ.get(ENV_BODY, "")
    if custom_body:
        log("检测到自定义请求体 KGQQ_BODY，将使用自定义body进行签到")

    # 支持多账号（换行或 & 分隔）
    cookies = []
    if "\n" in cookie_env:
        cookies = [c.strip() for c in cookie_env.split("\n") if c.strip()]
    elif "&" in cookie_env:
        cookies = [c.strip() for c in cookie_env.split("&") if c.strip()]
    else:
        cookies = [cookie_env.strip()]

    log(f"共读取到 {len(cookies)} 个账号")

    results = []
    for idx, cookie_str in enumerate(cookies, 1):
        cookie_info = parse_cookie(cookie_str)
        if not cookie_info:
            log(f"账号[{idx}] Cookie为空，跳过", "WARN")
            results.append((f"账号{idx}", False, "Cookie为空"))
            continue

        # 检查关键字段
        missing = []
        for key in ["openid", "uid"]:
            if key not in cookie_info["fields"]:
                missing.append(key)
        if missing:
            log(f"账号[{idx}] Cookie缺少关键字段: {missing}", "WARN")

        success, msg = sign(cookie_info, custom_body, idx)
        results.append((f"账号{idx}", success, msg))

        # 账号间延迟
        if idx < len(cookies):
            time.sleep(2)

    # 汇总
    summary_lines = ["全民K歌签到结果："]
    for name, success, msg in results:
        status = "✅" if success else "❌"
        summary_lines.append(f"{status} {name}: {msg}")

    summary = "\n".join(summary_lines)
    log("\n========== 签到汇总 ==========")
    log(summary)

    send_notify("全民K歌签到结果", summary)

    if any(not s for _, s, _ in results):
        sys.exit(1)

if __name__ == "__main__":
    main()
