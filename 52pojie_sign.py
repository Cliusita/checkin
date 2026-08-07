#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
吾爱破解论坛（52pojie.cn）自动签到脚本 v2.0
适配青龙面板

环境变量：
    export POJIE_COOKIE="你的完整cookie"
    多账号用 & 或换行分隔

Cookie获取方法：
    1. 浏览器登录吾爱破解论坛
    2. F12 → Network → 刷新页面
    3. 找到 forum.php 或 home.php 请求
    4. 复制 Request Headers 中的完整 Cookie
    5. 必须包含 9fd7a_auth 和 9fd7a_saltkey 等字段

更新时间：2026-08-07
"""

import os
import re
import sys
import time
import json
import requests
from urllib.parse import unquote

# 青龙面板通知模块
try:
    from notify import send
except ImportError:
    def send(title, content):
        print(f"\n【通知】{title}\n{content}\n")

# ============ 配置 ============
BASE_URL = "https://www.52pojie.cn"
HOME_URL = f"{BASE_URL}/forum.php"
TASK_APPLY_URL = f"{BASE_URL}/home.php?mod=task&do=apply&id=2"
TASK_DRAW_URL = f"{BASE_URL}/home.php?mod=task&do=draw&id=2"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# ============ 工具函数 ============
def log(msg, level="INFO"):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    tag = {"INFO": "[INFO]", "WARN": "[WARN]", "ERROR": "[ERROR]", "DEBUG": "[DEBUG]"}.get(level, "[INFO]")
    print(f"{ts} {tag:8} {msg}")
    return msg


def parse_cookie(cookie_str):
    """解析cookie字符串"""
    cookies = {}
    if not cookie_str:
        return cookies
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


# ============ 核心类 ============
class PojieSigner:
    def __init__(self, cookie_str, index=1):
        self.raw_cookie = cookie_str.strip()
        self.index = index
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.headers["Cookie"] = self.raw_cookie
        requests.packages.urllib3.disable_warnings()
        self.session.verify = False
        self.username = f"账号{index}"

        # 从cookie尝试提取用户名
        ck = parse_cookie(self.raw_cookie)
        if "9fd7a_olympichosts" in ck:
            try:
                decoded = unquote(ck["9fd7a_olympichosts"])
                # 尝试解析用户名
                if "username" in decoded or "user" in decoded:
                    self.username = f"账号{index}"
            except:
                pass

    def _request(self, method, url, **kwargs):
        """统一请求方法，带重试"""
        max_retry = 2
        for i in range(max_retry + 1):
            try:
                resp = self.session.request(method, url, timeout=20, **kwargs)
                return resp
            except requests.exceptions.Timeout:
                log(f"【{self.username}】请求超时 ({i+1}/{max_retry+1}): {url}", "WARN")
                if i < max_retry:
                    time.sleep(2)
            except Exception as e:
                log(f"【{self.username}】请求异常 ({i+1}/{max_retry+1}): {str(e)}", "ERROR")
                if i < max_retry:
                    time.sleep(1)
        return None

    def check_login(self):
        """检查登录状态 - 多种方式"""
        log(f"【{self.username}】正在检查登录状态...")

        # 方式1: 访问首页，检查是否包含"您需要先登录"
        resp = self._request("GET", HOME_URL)
        if resp is None:
            return False, "网络请求失败，无法连接论坛"

        text = resp.text

        # 调试: 保存部分响应内容用于排查
        if "DEBUG_POJIE" in os.environ:
            log(f"【{self.username}】首页响应前500字符: {text[:500]}", "DEBUG")

        # 判断是否包含登录提示
        if "您需要先登录才能继续本操作" in text:
            return False, "Cookie已失效，页面提示需要登录"

        # 方式2: 检查是否有登出链接（登录后才有）
        logout_patterns = [
            r'href=["\']member\.php\?mod=logging&action=logout',
            r'退出',
            r'logout',
        ]
        has_logout = any(re.search(p, text) for p in logout_patterns)

        # 方式3: 检查是否有个人中心/设置等登录后才有的元素
        login_indicators = [
            "个人中心", "我的帖子", "设置", "用户中心", "space.php",
            "home.php?mod=space", "mod=spacecp", "9fd7a_auth"
        ]
        has_login_indicator = any(ind in text for ind in login_indicators)

        # 方式4: 检查cookie中是否包含关键登录字段
        ck = parse_cookie(self.raw_cookie)
        has_auth_cookie = "9fd7a_auth" in ck or "9fd7a_saltkey" in ck

        log(f"【{self.username}】登录检查: has_logout={has_logout}, has_indicator={has_login_indicator}, has_auth={has_auth_cookie}")

        # 综合判断: 有登出链接 或 有登录标识 或 有auth cookie，认为已登录
        if has_logout or has_login_indicator:
            # 尝试提取用户名
            name_match = re.search(r'title=["\']访问我的空间["\'][^>]*>([^<]+)</a>', text)
            if name_match:
                self.username = name_match.group(1).strip()
            return True, f"登录状态正常 (用户名: {self.username})"

        if has_auth_cookie:
            # 有auth cookie但页面没显示登录状态，可能是cookie不完整
            return True, "Cookie包含登录凭证，继续尝试签到"

        # 如果页面既没有登录提示也没有登出链接，可能是网络问题或页面异常
        # 保守处理: 继续尝试，让后续签到流程自己判断
        return True, "无法100%确认登录状态，但将继续尝试签到"

    def get_formhash(self):
        """从首页获取formhash"""
        log(f"【{self.username}】正在获取 formhash...")

        resp = self._request("GET", HOME_URL)
        if not resp:
            return None

        text = resp.text

        # 多种匹配方式
        patterns = [
            r'<input[^>]*name=["\']formhash["\'][^>]*value=["\']([a-f0-9]{8})["\']',
            r'formhash=([a-f0-9]{8})',
            r'<a[^>]*href=["\']member\.php\?mod=logging&action=logout&formhash=([a-f0-9]{8})["\']',
            r'name=["\']formhash["\']\s+value=["\']([a-f0-9]{8})["\']',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                formhash = match.group(1)
                log(f"【{self.username}】获取 formhash 成功: {formhash}")
                return formhash

        log(f"【{self.username}】未能提取到 formhash，将尝试不带formhash签到", "WARN")
        return None

    def sign(self):
        """执行签到"""
        log(f"========== 开始签到【{self.username}】 ==========")

        # 1. 检查登录
        is_login, login_msg = self.check_login()
        if not is_login:
            log(f"【{self.username}】{login_msg}", "ERROR")
            return False, login_msg
        log(f"【{self.username}】{login_msg}")

        # 2. 获取formhash
        formhash = self.get_formhash()

        # 3. 先访问任务页面查看状态
        log(f"【{self.username}】正在访问任务页面...")
        task_resp = self._request("GET", TASK_APPLY_URL)
        if not task_resp:
            return False, "访问任务页面失败"

        task_text = task_resp.text

        # 调试模式保存响应
        if "DEBUG_POJIE" in os.environ:
            log(f"【{self.username}】任务页面关键词: 任务已完成={'任务已完成' in task_text}, 已申请={'已申请过' in task_text}, 登录提示={'您需要先登录' in task_text}", "DEBUG")

        # 判断任务状态
        if "您需要先登录才能继续本操作" in task_text:
            return False, "Cookie失效，任务页面要求登录"

        if "任务已完成" in task_text or "已申请过" in task_text or "本期您已申请过此任务" in task_text:
            return True, "今日已签到"

        if "不是您当前的任务" in task_text:
            return True, "今日已签到（任务已结束）"

        # 4. 提交签到申请
        log(f"【{self.username}】正在提交签到申请...")
        post_data = {
            "formhash": formhash if formhash else "",
            "tasksubmit": "true",
        }

        submit_resp = self._request("POST", TASK_APPLY_URL, data=post_data)
        if not submit_resp:
            return False, "提交签到申请失败"

        submit_text = submit_resp.text

        if "任务已完成" in submit_text or "申请成功" in submit_text:
            return True, "签到成功"
        elif "已申请过" in submit_text or "本期您已申请过此任务" in submit_text:
            return True, "今日已签到"
        elif "您需要先登录" in submit_text:
            return False, "Cookie失效"
        else:
            # 尝试领取奖励
            log(f"【{self.username}】申请结果不明确，尝试领取奖励...")
            draw_resp = self._request("GET", TASK_DRAW_URL)
            if draw_resp:
                draw_text = draw_resp.text
                if "任务已完成" in draw_text or "领取成功" in draw_text:
                    return True, "签到成功（领取奖励）"
                elif "已申请过" in draw_text or "不是您当前的任务" in draw_text:
                    return True, "今日已签到"

            # 如果还是不行，检查是否已签到
            if "不是您当前的任务" in task_text or "不是您当前的任务" in submit_text:
                return True, "今日已签到（任务状态已结束）"

            return False, f"签到状态未知，请开启DEBUG模式排查"

    def run(self):
        """运行签到"""
        try:
            success, msg = self.sign()
            status = "✅ 成功" if success else "❌ 失败"
            log(f"========== 结果【{self.username}】: {status} - {msg} ==========")
            return success, msg
        except Exception as e:
            log(f"【{self.username}】签到异常: {str(e)}", "ERROR")
            import traceback
            log(traceback.format_exc(), "DEBUG")
            return False, f"异常: {str(e)}"


# ============ 主程序 ============
def main():
    log("=" * 60)
    log("吾爱破解论坛自动签到脚本 v2.0 启动")
    log("=" * 60)

    # 读取环境变量
    cookie_env = os.environ.get("POJIE_COOKIE", "")

    if not cookie_env:
        log("错误: 未设置环境变量 POJIE_COOKIE", "ERROR")
        log("请在青龙面板 → 环境变量中添加: 名称=POJIE_COOKIE, 值=你的Cookie", "INFO")
        log("Cookie获取: 浏览器F12 → Network → 找到52pojie.cn请求 → 复制Cookie", "INFO")
        sys.exit(1)

    # 解析多账号
    cookies = []
    if "&" in cookie_env:
        cookies = [c.strip() for c in cookie_env.split("&") if c.strip()]
    else:
        cookies = [c.strip() for c in cookie_env.split("\n") if c.strip()]

    if not cookies:
        log("未解析到有效的Cookie，请检查配置", "ERROR")
        sys.exit(1)

    log(f"共检测到 {len(cookies)} 个账号")

    # 执行签到
    results = []
    for idx, cookie in enumerate(cookies, 1):
        signer = PojieSigner(cookie, idx)
        success, msg = signer.run()
        results.append((idx, signer.username, success, msg))
        if idx < len(cookies):
            time.sleep(3)  # 账号间隔

    # 汇总
    log("=" * 60)
    log("签到汇总")
    log("=" * 60)

    summary_lines = []
    success_count = 0
    for idx, name, success, msg in results:
        icon = "✅" if success else "❌"
        line = f"账号{idx}({name}): {icon} {msg}"
        summary_lines.append(line)
        log(line)
        if success:
            success_count += 1

    summary = "\n".join(summary_lines)
    title = f"吾爱破解签到 {success_count}/{len(cookies)} 成功"

    # 发送通知
    try:
        send(title, summary)
        log("通知发送成功")
    except Exception as e:
        log(f"通知发送失败: {e}", "WARN")

    log("=" * 60)
    log("脚本执行完毕")
    log("=" * 60)


if __name__ == "__main__":
    main()
