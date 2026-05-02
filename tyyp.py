# -*- coding: utf-8 -*-
# 天翼云盘自动签到脚本 青龙面板专用
# 修复版：适配 20260501签名验证，支持个人签到+抽奖+家庭签到
# 修复版 v2：修正 getAccessTokenBySsKey 签名参数和 AppKey
# 修复版 v3：增加家庭签到开关，默认关闭（避免 IP 绑定问题）
import os
import json
import time
import hashlib
import requests
from datetime import datetime

# ========== 配置区 ==========
cookie_list = os.getenv("TYYP_COOKIE", "").split("&")
if not cookie_list or cookie_list == [""]:
    print("❌ 未配置 TYYP_COOKIE 环境变量，请先配置！")
    exit(1)

# 家庭签到开关：1=开启，0=关闭（默认关闭，避免 IP 绑定错误）
# 如需开启，必须在服务器上重新抓取 Cookie，否则报 InvalidSessionKey
ENABLE_FAMILY = os.getenv("TYYP_FAMILY_SIGN", "0") == "1"

APP_CONFIG = {
    "clientId": "538135150693412",
    "model": "KB2000",
    "version": "9.0.6",
}

BASE_HEADERS = {
    "User-Agent": f"Mozilla/5.0 (Linux; U; Android 11; {APP_CONFIG['model']} Build/RP1A.201005.001) "
                  f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/74.0.3729.136 Mobile Safari/537.36 "
                  f"Ecloud/{APP_CONFIG['version']} Android/30 clientId/{APP_CONFIG['clientId']} "
                  f"clientModel/{APP_CONFIG['model']} clientChannelId/qq proVersion/1.0.6",
    "Referer": "https://m.cloud.189.cn/zhuanti/2016/sign/index.jsp?albumBackupOpened=1",
    "Accept-Encoding": "gzip, deflate",
}


# ========== 推送函数 ==========
def push_msg(title, content):
    push_key = os.getenv("PUSH_KEY", "")
    if not push_key:
        return
    url = f"https://sctapi.ftqq.com/{push_key}.send"
    try:
        requests.post(url, data={"title": title, "desp": content}, timeout=10)
    except Exception as e:
        print(f"⚠️ 推送失败: {e}")


# ========== 签名工具 ==========
def get_signature(data: dict) -> str:
    params = [f"{k}={v}" for k, v in data.items()]
    params.sort()
    return hashlib.md5("&".join(params).encode("utf-8")).hexdigest()


# ========== 个人签到（移动端接口，无需签名，不校验 IP） ==========
def personal_checkin(cookie):
    headers = {**BASE_HEADERS, "Cookie": cookie}
    rand = str(int(time.time() * 1000))
    sign_url = (
        f"https://cloud.189.cn/mkt/userSign.action?"
        f"rand={rand}&clientType=TELEANDROID&version={APP_CONFIG['version']}&model={APP_CONFIG['model']}"
    )
    try:
        r = requests.get(sign_url, headers=headers, timeout=10)
        data = r.json()
        bonus = data.get("netdiskBonus", "0")
        if data.get("isSign") == "false" or data.get("isSign") == False:
            msg = f"✅ 个人签到成功，获得 {bonus}M 空间"
        else:
            msg = f"⏭️ 今日已签到，获得 {bonus}M 空间"
    except Exception as e:
        msg = f"❌ 个人签到异常: {str(e)}"

    prizes = []
    tasks = [
        ("TASK_SIGNIN", "ACT_SIGNIN", "签到抽奖"),
        ("TASK_SIGNIN_PHOTOS", "ACT_SIGNIN", "照片抽奖"),
        ("TASK_2022_FLDFS_KJ", "ACT_SIGNIN", "福利抽奖"),
    ]
    for task_id, act_id, name in tasks:
        try:
            url = f"https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId={task_id}&activityId={act_id}"
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()
            if data.get("errorCode") == "User_Not_Chance":
                prizes.append(f"{name}: 次数不足")
            elif "prizeName" in data:
                prizes.append(f"{name}: {data['prizeName']}")
            else:
                prizes.append(f"{name}: 未中奖")
        except Exception as e:
            prizes.append(f"{name}: 异常")
        time.sleep(1)
    return msg, prizes


# ========== 家庭签到（需要 accessToken，严格 IP 绑定） ==========
def family_checkin(cookie):
    headers = {**BASE_HEADERS, "Cookie": cookie, "Accept": "application/json;charset=UTF-8"}
    results = []
    try:
        # 1. 获取 sessionKey
        r = requests.get(
            "https://cloud.189.cn/api/portal/v2/getUserBriefInfo.action",
            headers=headers, timeout=10
        )
        brief_data = r.json()
        session_key = brief_data.get("sessionKey", "")
        if not session_key:
            return ["❌ 获取 sessionKey 失败"]

        # 2. 获取 accessToken（AppKey=601102120，参数包含 sessionKey）
        ts = str(int(time.time() * 1000))
        sig = get_signature({
            "AppKey": "601102120",
            "Timestamp": ts,
            "sessionKey": session_key
        })
        token_headers = {
            "Sign-Type": "1",
            "Signature": sig,
            "Timestamp": ts,
            "AppKey": "601102120",
            "Cookie": cookie,
        }
        r = requests.get(
            f"https://cloud.189.cn/api/open/oauth2/getAccessTokenBySsKey.action?sessionKey={session_key}",
            headers=token_headers, timeout=10
        )
        token_data = r.json()
        access_token = token_data.get("accessToken", "")
        if not access_token:
            err = token_data.get("errorMsg", "未知错误")
            return [f"❌ 获取 accessToken 失败: {err}"]

        # 3. 获取家庭列表
        ts = str(int(time.time() * 1000))
        sig = get_signature({"AccessToken": access_token, "Timestamp": ts})
        family_headers = {
            "Sign-Type": "1",
            "Signature": sig,
            "Timestamp": ts,
            "Accesstoken": access_token,
            "Accept": "application/json;charset=UTF-8",
            "Cookie": cookie,
        }
        r = requests.get(
            "https://api.cloud.189.cn/open/family/manage/getFamilyList.action",
            headers=family_headers, timeout=10
        )
        families = r.json().get("familyInfoResp", [])

        # 4. 逐个家庭签到
        for fam in families:
            fid = fam.get("familyId")
            fname = fam.get("familyName", "未知家庭")
            ts = str(int(time.time() * 1000))
            sig = get_signature({"familyId": fid, "AccessToken": access_token, "Timestamp": ts})
            sign_headers = {
                "Sign-Type": "1",
                "Signature": sig,
                "Timestamp": ts,
                "Accesstoken": access_token,
                "Accept": "application/json;charset=UTF-8",
                "Cookie": cookie,
            }
            r = requests.get(
                f"https://api.cloud.189.cn/open/family/manage/exeFamilyUserSign.action?familyId={fid}",
                headers=sign_headers, timeout=10
            )
            data = r.json()
            bonus = data.get("bonusSpace", "0")
            if data.get("signStatus"):
                results.append(f"⏭️ 家庭「{fname}」已签到，空间 {bonus}M")
            else:
                results.append(f"✅ 家庭「{fname}」签到成功，获得 {bonus}M")
            time.sleep(1)
    except Exception as e:
        results.append(f"❌ 家庭签到异常: {str(e)}")
    return results


# ========== 查询容量 ==========
def get_size_info(cookie):
    headers = {**BASE_HEADERS, "Cookie": cookie, "Accept": "application/json;charset=UTF-8"}
    try:
        r = requests.get(
            "https://cloud.189.cn/api/portal/getUserSizeInfo.action",
            headers=headers, timeout=10
        )
        d = r.json()
        cloud = d.get("cloudCapacityInfo", {})
        family = d.get("familyCapacityInfo", {})
        c_total = cloud.get("totalSize", 0) / 1024 ** 3
        c_used = cloud.get("usedSize", 0) / 1024 ** 3
        f_total = family.get("totalSize", 0) / 1024 ** 3
        f_used = family.get("usedSize", 0) / 1024 ** 3
        return [
            f"💾 个人: {c_used:.2f}G / {c_total:.2f}G",
            f"🏠 家庭: {f_used:.2f}G / {f_total:.2f}G",
        ]
    except Exception as e:
        return [f"❌ 查询容量异常: {str(e)}"]


# ========== 主程序 ==========
if __name__ == "__main__":
    print(f"🚀 天翼云盘自动签到任务开始 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📌 家庭签到开关: {'开启' if ENABLE_FAMILY else '关闭'}")
    if not ENABLE_FAMILY:
        print("   💡 如需开启家庭签到，请在服务器上重新抓取 Cookie，并设置环境变量 TYYP_FAMILY_SIGN=1")
    all_msgs = []
    for i, cookie in enumerate(cookie_list):
        if not cookie:
            continue
        ck = cookie.strip()
        print(f"\n———— 账号 {i + 1} ————")
        all_msgs.append(f"【账号 {i + 1}】")

        # 个人签到（始终执行）
        p_msg, prizes = personal_checkin(ck)
        print(p_msg)
        all_msgs.append(p_msg)
        for p in prizes:
            print(f"   🎁 {p}")
            all_msgs.append(f"   🎁 {p}")

        # 家庭签到（可选）
        if ENABLE_FAMILY:
            f_msgs = family_checkin(ck)
            for m in f_msgs:
                print(m)
                all_msgs.append(m)
        else:
            skip_msg = "⏭️ 家庭签到已跳过（未开启）"
            print(skip_msg)
            all_msgs.append(skip_msg)

        # 容量信息
        size_msgs = get_size_info(ck)
        for m in size_msgs:
            print(m)
            all_msgs.append(m)

        all_msgs.append("")
        time.sleep(3)

    push_content = "\n".join(all_msgs)
    print("\n" + "=" * 30)
    print(push_content)
    push_msg("天翼云盘签到通知", push_content)
    print("\n✅ 所有账号任务执行完成！")
