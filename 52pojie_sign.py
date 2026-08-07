#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
吾爱破解论坛（52pojie.cn）自动签到脚本
适配青龙面板

环境变量配置：
    export POJIE_COOKIE="你的cookie"
    多账号用换行分隔，或 export POJIE_COOKIE="账号1cookie&账号2cookie"

Cookie获取方法：
    1. 浏览器登录吾爱破解论坛
    2. F12打开开发者工具 → Network → 刷新页面
    3. 找到任意 52pojie.cn 请求，复制 Request Headers 中的 Cookie
    4. 只需要包含登录状态的cookie即可（如 9fd7a_auth, 9fd7a_saltkey 等）

更新时间：2026-08-07
"""

import os
import re
import sys
import time
import json
import requests
from urllib.parse import urlencode

# 尝试导入青龙面板的 notify 模块
try:
    from notify import send
except ImportError:
    def send(title, content):
        print(f"【{title}】\n{content}")

# ============ 配置区域 ============
# 签到URL
BASE_URL = "https://www.52pojie.cn"
HOME_URL = f"{BASE_URL}/forum.php"
TASK_URL = f"{BASE_URL}/home.php?mod=task&do=apply&id=2"

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# ============ 日志输出 ============
def log(msg, level="INFO"):
    """统一日志输出"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    level_tag = f"[{level}]"
    print(f"{timestamp} {level_tag:8} {msg}")
    return msg


# ============ Cookie处理 ============
def parse_cookies(cookie_str):
    """解析cookie字符串为字典"""
    cookies = {}
    if not cookie_str:
        return cookies

    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def get_cookie_str(cookies_dict):
    """将cookie字典转为字符串"""
    return "; ".join([f"{k}={v}" for k, v in cookies_dict.items()])


# ============ 核心签到逻辑 ============
class PojieSign:
    def __init__(self, cookie_str, index=1):
        self.cookie_str = cookie_str.strip()
        self.index = index
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.headers["Cookie"] = self.cookie_str
        # 禁用SSL警告
        requests.packages.urllib3.disable_warnings()
        self.session.verify = False

        # 解析cookie获取用户名（如果有）
        self.username = f"账号{index}"
        cookies = parse_cookies(self.cookie_str)
        # 尝试从cookie中获取用户名信息
        if "9fd7a_olympichosts" in cookies:
            try:
                import urllib.parse
                decoded = urllib.parse.unquote(cookies.get("9fd7a_olympichosts", ""))
                # 简单提取
                self.username = f"账号{index}"
            except:
                pass

    def get_formhash(self):
        """从首页获取formhash"""
        try:
            log(f"【{self.username}】正在获取 formhash...")
            resp = self.session.get(HOME_URL, timeout=15)

            if resp.status_code != 200:
                log(f"【{self.username}】获取首页失败，状态码: {resp.status_code}", "ERROR")
                return None

            # 检查是否登录
            if "登录" in resp.text and "注册" in resp.text and "您需要先登录" not in resp.text:
                # 可能未登录，但继续尝试获取formhash
                pass

            # 提取formhash - 多种匹配方式
            patterns = [
                r'<input[^>]*name=["\']formhash["\'][^>]*value=["\']([^"\']+)["\']',
                r'name=["\']formhash["\']\s+value=["\']([^"\']+)["\']',
                r'formhash=([a-z0-9]{8})',
                r'<a[^>]*href=["\']member\.php\?mod=logging&action=logout&formhash=([^"\']+)["\']',
            ]

            for pattern in patterns:
                match = re.search(pattern, resp.text)
                if match:
                    formhash = match.group(1)
                    log(f"【{self.username}】获取 formhash 成功: {formhash}")
                    return formhash

            log(f"【{self.username}】未能从页面提取到 formhash", "WARN")
            return None

        except Exception as e:
            log(f"【{self.username}】获取 formhash 异常: {str(e)}", "ERROR")
            return None

    def check_login_status(self):
        """检查登录状态"""
        try:
            resp = self.session.get(HOME_URL, timeout=15)
            # 如果页面包含"登录"和"注册"按钮，且没有用户中心相关链接，可能未登录
            if "您需要先登录才能继续本操作" in resp.text:
                return False, "Cookie已失效，需要重新登录"
            if "个人中心" in resp.text or "我的" in resp.text or "设置" in resp.text:
                return True, "登录状态正常"
            # 尝试通过其他方式判断
            if "9fd7a_auth" in self.cookie_str or "9fd7a_saltkey" in self.cookie_str:
                return True, "Cookie格式看起来正常"
            return False, "无法确认登录状态"
        except Exception as e:
            return False, f"检查登录状态异常: {str(e)}"

    def do_sign(self):
        """执行签到"""
        results = []

        # 1. 检查登录状态
        is_login, login_msg = self.check_login_status()
        if not is_login:
            log(f"【{self.username}】{login_msg}", "ERROR")
            return False, login_msg

        log(f"【{self.username}】{login_msg}")

        # 2. 获取formhash
        formhash = self.get_formhash()
        if not formhash:
            # 尝试不带formhash直接签到
            log(f"【{self.username}】未获取到formhash，尝试直接签到...", "WARN")

        # 3. 执行签到请求
        try:
            # 吾爱破解的签到是通过任务系统实现的
            # 先访问任务页面
            log(f"【{self.username}】正在访问任务页面...")
            task_resp = self.session.get(TASK_URL, timeout=15)

            task_text = task_resp.text

            # 判断任务状态
            if "任务已完成" in task_text or "已申请过" in task_text or "本期您已申请过此任务" in task_text:
                msg = "今日已签到"
                log(f"【{self.username}】{msg}")
                return True, msg

            if "您需要先登录才能继续本操作" in task_text:
                msg = "Cookie已失效，请重新获取"
                log(f"【{self.username}】{msg}", "ERROR")
                return False, msg

            # 如果页面显示可以申请任务，则提交申请
            if "申请任务" in task_text or "立即申请" in task_text:
                # 构造POST数据
                post_data = {
                    "formhash": formhash if formhash else "",
                    "tasksubmit": "true",
                }

                # 提交任务申请
                log(f"【{self.username}】正在提交签到申请...")
                submit_url = f"{BASE_URL}/home.php?mod=task&do=apply&id=2"
                submit_resp = self.session.post(submit_url, data=post_data, timeout=15)

                submit_text = submit_resp.text

                if "任务已完成" in submit_text or "申请成功" in submit_text:
                    msg = "签到成功"
                    log(f"【{self.username}】{msg}")
                    return True, msg
                elif "已申请过" in submit_text or "本期您已申请过此任务" in submit_text:
                    msg = "今日已签到（重复申请）"
                    log(f"【{self.username}】{msg}")
                    return True, msg
                elif "您需要先登录" in submit_text:
                    msg = "Cookie失效"
                    log(f"【{self.username}】{msg}", "ERROR")
                    return False, msg
                else:
                    msg = f"签到状态未知，响应包含: {submit_text[:200]}"
                    log(f"【{self.username}】{msg}", "WARN")
                    return False, msg
            else:
                # 尝试另一种签到方式 - 直接GET带参数
                sign_url = f"{BASE_URL}/home.php?mod=task&do=draw&id=2"
                log(f"【{self.username}】尝试领取任务奖励...")
                draw_resp = self.session.get(sign_url, timeout=15)

                if "任务已完成" in draw_resp.text or "领取成功" in draw_resp.text:
                    msg = "签到成功（领取奖励）"
                    log(f"【{self.username}】{msg}")
                    return True, msg
                elif "已申请过" in draw_resp.text:
                    msg = "今日已签到"
                    log(f"【{self.username}】{msg}")
                    return True, msg
                else:
                    msg = "无法确定签到状态，可能今日已签到或页面结构变更"
                    log(f"【{self.username}】{msg}", "WARN")
                    # 保守返回成功，避免重复通知
                    return True, msg

        except requests.exceptions.Timeout:
            msg = "请求超时"
            log(f"【{self.username}】{msg}", "ERROR")
            return False, msg
        except Exception as e:
            msg = f"签到异常: {str(e)}"
            log(f"【{self.username}】{msg}", "ERROR")
            return False, msg

    def run(self):
        """运行签到流程"""
        log(f"========== 开始签到【账号{self.index}】 ==========")
        success, msg = self.do_sign()
        status = "✅ 成功" if success else "❌ 失败"
        log(f"========== 签到结果【账号{self.index}】: {status} - {msg} ==========")
        return success, msg


# ============ 主入口 ============
def main():
    log("=" * 50)
    log("吾爱破解论坛（52pojie.cn）自动签到脚本启动")
    log("=" * 50)

    # 从环境变量读取cookie
    cookie_env = os.environ.get("POJIE_COOKIE", "")

    if not cookie_env:
        log("未配置环境变量 POJIE_COOKIE，请先在青龙面板配置", "ERROR")
        log("配置方法：青龙面板 → 环境变量 → 新建 → 名称: POJIE_COOKIE，值: 你的cookie", "INFO")
        sys.exit(1)

    # 解析多账号（支持 & 或换行分隔）
    cookies = []
    if "&" in cookie_env:
        cookies = [c.strip() for c in cookie_env.split("&") if c.strip()]
    else:
        cookies = [c.strip() for c in cookie_env.split("\n") if c.strip()]

    if not cookies:
        log("未解析到有效的cookie，请检查环境变量配置", "ERROR")
        sys.exit(1)

    log(f"共检测到 {len(cookies)} 个账号")

    # 执行签到
    all_results = []
    for idx, cookie in enumerate(cookies, start=1):
        signer = PojieSign(cookie, idx)
        success, msg = signer.run()
        all_results.append((idx, success, msg))
        time.sleep(2)  # 账号间间隔，避免请求过快

    # 汇总结果
    log("=" * 50)
    log("签到汇总")
    log("=" * 50)

    summary_lines = []
    success_count = 0
    for idx, success, msg in all_results:
        status = "✅" if success else "❌"
        line = f"账号{idx}: {status} {msg}"
        summary_lines.append(line)
        log(line)
        if success:
            success_count += 1

    summary = "\n".join(summary_lines)
    title = f"吾爱破解签到 - {success_count}/{len(cookies)} 成功"

    # 发送通知
    try:
        send(title, summary)
        log("通知发送成功")
    except Exception as e:
        log(f"通知发送失败: {str(e)}", "WARN")

    log("=" * 50)
    log("脚本执行完毕")
    log("=" * 50)


if __name__ == "__main__":
    main()
