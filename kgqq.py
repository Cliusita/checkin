#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全民K歌独立签到脚本 v2（青龙面板）
修复：参考吾爱破解 Java 源码，改用 GET 请求 + URL 参数传递 cmd
功能：每日自动签到领鲜花（约120朵/天）

【环境变量配置】
1. KGQQ_COOKIE: 必填，全民K歌Cookie字符串，多账号用 & 或换行分隔
   需包含字段：uid（作为 t_uid）, qrsig（用于计算 g_tk）
2. KGQQ_NOTIFY: 可选，是否开启通知，true/false，默认false

【Cookie获取方式】
1. 电脑浏览器打开 https://kg.qq.com/ 并登录
2. F12打开开发者工具 -> Network（网络）
3. 刷新页面，点击任意请求，在Headers中复制Cookie
4. 确保包含 uid 字段
"""

import os
import sys
import json
import re
import time
import base64
import requests
from urllib.parse import quote

# ==================== 配置区域 ====================

ENV_COOKIE = "KGQQ_COOKIE"
ENV_NOTIFY = "KGQQ_NOTIFY"

BASE_URL = "https://node.kg.qq.com/webapp/proxy"

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

# ==================== 工具函数 ====================

def get_gtk(skey):
    """计算g_tk（腾讯系通用算法）"""
    if not skey:
        return "5381"
    hash_val = 5381
    for char in skey:
        hash_val += (hash_val << 5) + ord(char)
    return str(hash_val & 0x7fffffff)

def build_map_ext(cmd_name, appid=1000626, modid=503937, cmd=589824, file_name="taskJce"):
    """构建 mapExt 参数（参考吾爱破解 Java 源码）"""
    data = {
        "file": file_name,
        "cmdName": cmd_name,
        "wnsConfig": {"appid": appid},
        "l5api": {"modid": modid, "cmd": cmd}
    }
    # 步骤1: JSON -> URL encode -> base64 -> URL encode
    json_str = json.dumps(data, separators=(',', ':'))
    url_encoded = quote(json_str, safe='')
    b64_encoded = base64.b64encode(url_encoded.encode('utf-8')).decode('utf-8')
    final = quote(b64_encoded, safe='')
    return final

# ==================== 签到核心 ====================

def kg_request(cookie_raw, params, desc="请求"):
    """发起全民K歌 GET 请求"""
    headers = {
        "Host": "node.kg.qq.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://kg.qq.com/",
        "Origin": "https://kg.qq.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": cookie_raw,
    }

    try:
        resp = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
        log(f"{desc} HTTP状态码: {resp.status_code}")
        try:
            return resp.json()
        except Exception:
            log(f"{desc} 响应解析失败: {resp.text[:500]}", "ERROR")
            return None
    except Exception as e:
        log(f"{desc} 请求异常: {e}", "ERROR")
        return None

def sign(cookie_info, index=1):
    """执行签到"""
    raw_cookie = cookie_info["raw"]
    fields = cookie_info["fields"]
    uid = fields.get("uid", "")

    if not uid:
        log(f"账号[{index}] 未找到 uid，无法签到", "ERROR")
        return False, "缺少 uid"

    log(f"========== 开始签到 账号[{index}] ==========")

    # 计算 g_tk
    qrsig = fields.get("qrsig", "")
    gtk = get_gtk(qrsig)

    results = []

    # 1. 先获取用户信息（验证Cookie有效性）
    profile_params = {
        "ns": "proto_profile",
        "cmd": "profile.getProfile",
        "mapExt": build_map_ext("ProfileGet", appid=1000626, modid=294017, cmd=262144),
        "t_uUid": uid,
    }
    if gtk and gtk != "5381":
        profile_params["g_tk_openkey"] = gtk

    profile_resp = kg_request(raw_cookie, profile_params, "获取用户信息")
    if profile_resp and "data" in profile_resp:
        try:
            nick = profile_resp["data"]["profile.getProfile"]["stPersonInfo"]["sKgNick"]
            flower = profile_resp["data"]["profile.getProfile"]["uFlowerNum"]
            log(f"账号[{index}] 昵称: {nick}, 当前鲜花: {flower}")
        except Exception:
            pass

    # 2. 执行签到（多个 t_iShowEntry）
    # 参考 Java 源码: t_iShowEntry = [1, 2, 4, 16, 128, 512]
    show_entries = [1, 2, 4, 16, 128, 512]
    total_award = 0

    for entry in show_entries:
        sign_params = {
            "ns": "KG_TASK",
            "cmd": "task.signinGetAward",
            "mapExt": build_map_ext("GetSignInAwardReq", appid=1000626, modid=503937, cmd=589824),
            "t_uid": uid,
            "t_iShowEntry": entry,
        }
        if gtk and gtk != "5381":
            sign_params["g_tk"] = gtk
            sign_params["g_tk_openkey"] = gtk

        resp = kg_request(raw_cookie, sign_params, f"签到(entry={entry})")

        if resp is None:
            continue

        log(f"签到(entry={entry}) 返回: {json.dumps(resp, ensure_ascii=False, indent=2)}")

        # 解析返回
        if "data" in resp and "task.signinGetAward" in resp["data"]:
            award_data = resp["data"]["task.signinGetAward"]
            ret = award_data.get("ret", 0)

            if ret == 0:
                awards = award_data.get("awards", [])
                num = awards[0].get("num", 0) if awards else 0
                total_award += num
                log(f"✅ 签到成功(entry={entry})，获得鲜花 {num} 朵")
            elif ret == -11532 or "已经签到" in str(award_data) or "重复" in str(award_data):
                log(f"⚠️ 今日已签到(entry={entry})")
            else:
                log(f"⚠️ 签到返回码: {ret}")
        elif "code" in resp:
            code = resp.get("code", -1)
            msg = resp.get("msg", resp.get("message", "未知"))
            if code == 0 or "成功" in msg:
                log(f"✅ 签到成功(entry={entry}): {msg}")
            elif "已经" in msg or "重复" in msg:
                log(f"⚠️ 今日已签到(entry={entry}): {msg}")
            else:
                log(f"❌ 签到失败(entry={entry}): {msg} (code={code})")

        time.sleep(0.5)  # 请求间隔

    # 3. 抽奖（task.getLottery）
    # 参考 Java 源码: t_type = [1, 2]
    lottery_types = [1, 2]
    for l_type in lottery_types:
        lottery_params = {
            "ns": "KG_TASK",
            "cmd": "task.getLottery",
            "mapExt": build_map_ext("LotteryReq", appid=1000557, modid=503937, cmd=589824),
            "t_uid": uid,
            "t_type": l_type,
        }
        if gtk and gtk != "5381":
            lottery_params["g_tk"] = gtk
            lottery_params["g_tk_openkey"] = gtk

        resp = kg_request(raw_cookie, lottery_params, f"抽奖(type={l_type})")
        if resp and "data" in resp:
            log(f"抽奖(type={l_type}) 返回: {json.dumps(resp, ensure_ascii=False)[:200]}")
        time.sleep(0.5)

    if total_award > 0:
        msg = f"签到成功，共获得鲜花 {total_award} 朵"
        log(msg)
        return True, msg
    else:
        msg = "签到完成（可能今日已签到或无新增鲜花）"
        log(msg)
        return True, msg

# ==================== 主函数 ====================

def main():
    log("=" * 50)
    log("全民K歌自动签到脚本 v2 启动")
    log("参考：吾爱破解 Java 源码 + DailyCheckIn")
    log("=" * 50)

    cookie_env = os.environ.get(ENV_COOKIE, "")
    if not cookie_env:
        log(f"未找到环境变量 {ENV_COOKIE}，请先在青龙面板配置Cookie", "ERROR")
        sys.exit(1)

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

        success, msg = sign(cookie_info, idx)
        results.append((f"账号{idx}", success, msg))

        if idx < len(cookies):
            time.sleep(2)

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
