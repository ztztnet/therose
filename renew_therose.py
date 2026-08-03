#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TheRose 自动续期 + 自动重启
正确流程：
  登录 → /panel?routeName=servers (My servers)
       → 点 Extend
       → 续期页 #order-submit (Order now)
  续期完成后，自动重启服务器（需设置 SERVER_URL 环境变量）
"""

import os
import re
import sys
import time
import requests
from seleniumbase import SB
from urllib.parse import urlparse

EMAIL = os.environ.get("EMAIL") or ""
PASSWORD = os.environ.get("PASSWORD") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
PROXY = (os.environ.get("PROXY") or "").strip()
PROXY_HOST = (os.environ.get("PROXY_HOST") or "").strip()
PROXY_PORT = (os.environ.get("PROXY_PORT") or "").strip()
PROXY_USER = (os.environ.get("PROXY_USER") or "").strip()
PROXY_PASS = (os.environ.get("PROXY_PASS") or "").strip()
PROXY_SCHEME = (os.environ.get("PROXY_SCHEME") or "socks5").strip().lower()
SERVER_ID = (os.environ.get("SERVER_ID") or "").strip()
SERVER_URL = (os.environ.get("SERVER_URL") or "").strip()

BASE_URL = "https://client.therose.cloud/login"
SERVERS_URL = "https://client.therose.cloud/panel?routeName=servers"
PANEL_URL = "https://client.therose.cloud/panel"

EMAIL_SELECTORS = [
    "#login_form_email",
    'input[name="login_form[email]"]',
    'input[type="email"]',
    'input[name*="email" i]',
    'input[id*="email" i]',
]
PASSWORD_SELECTORS = [
    "#login_form_password",
    'input[name="login_form[password]"]',
    'input[type="password"]',
    'input[name*="password" i]',
    'input[id*="password" i]',
]

if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)


def build_proxy():
    raw = PROXY
    if not raw and PROXY_HOST and PROXY_PORT:
        auth = ""
        if PROXY_USER:
            auth = f"{PROXY_USER}:{PROXY_PASS}@" if PROXY_PASS else f"{PROXY_USER}@"
        raw = f"{PROXY_SCHEME}://{auth}{PROXY_HOST}:{PROXY_PORT}"
    if not raw:
        return None
    if "://" in raw:
        u = urlparse(raw)
        host, port = u.hostname or "", u.port or ""
        if not host or not port:
            print(f"⚠️ 代理地址解析失败: {mask_proxy(raw)}")
            return None
        user, password = u.username or "", u.password or ""
        if user:
            auth = f"{user}:{password}@" if password is not None else f"{user}@"
            core = f"{auth}{host}:{port}"
        else:
            core = f"{host}:{port}"
        if u.scheme.startswith("socks"):
            return f"{u.scheme}://{core}"
        return core
    return raw


def mask_proxy(proxy):
    if not proxy:
        return ""
    return re.sub(r":([^:@/]+)@", r":***@", proxy)


def send_tg(token, chat_id, message, proxies=None):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url, json={"chat_id": chat_id, "text": message}, timeout=15, proxies=proxies
        )
        if resp.status_code == 200:
            print("📨 Telegram 通知已发送")
        else:
            print(f"❌ Telegram 发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")


def page_looks_like_cf(sb):
    try:
        title = (sb.get_title() or "").lower()
        url = (sb.get_current_url() or "").lower()
        body = ""
        try:
            body = (sb.get_text("body") or "").lower()
        except Exception:
            pass
        src = ""
        try:
            src = (sb.get_page_source() or "").lower()[:4000]
        except Exception:
            pass
        blob = f"{title}\n{url}\n{body[:1500]}\n{src}"
        markers = [
            "just a moment",
            "checking your browser",
            "attention required",
            "cf-browser-verification",
            "challenge-platform",
            "sorry, you have been blocked",
            "error 1020",
            "access denied",
        ]
        return any(m in blob for m in markers)
    except Exception:
        return False


def dump_debug(sb, prefix="debug"):
    try:
        print(f"📷 URL: {sb.get_current_url()}")
        print(f"📷 Title: {sb.get_title()}")
    except Exception as e:
        print(f"⚠️ 读 URL 失败: {e}")
    try:
        sb.save_screenshot(f"{prefix}.png")
        print(f"📷 已保存 {prefix}.png")
    except Exception as e:
        print(f"⚠️ 截图失败: {e}")
    try:
        html = sb.get_page_source() or ""
        with open(f"{prefix}.html", "w", encoding="utf-8", errors="ignore") as f:
            f.write(html)
        print(f"📄 已保存 {prefix}.html ({len(html)} bytes)")
    except Exception as e:
        print(f"⚠️ 保存 HTML 失败: {e}")
    try:
        body = sb.get_text("body") or ""
        snippet = " ".join(body.split())[:800]
        if snippet:
            print(f"📝 页面文本: {snippet}")
    except Exception:
        pass


def find_first(sb, selectors, timeout=5):
    for i, sel in enumerate(selectors):
        t = timeout if i == 0 else 1
        try:
            if sb.is_element_present(sel, timeout=t):
                return sel
        except Exception:
            try:
                sb.find_element(sel, timeout=1)
                return sel
            except Exception:
                continue
    return None


def try_pass_cf(sb, rounds=4):
    for i in range(1, rounds + 1):
        print(f"🛡 验证处理 round {i}/{rounds} ...")
        try:
            sb.uc_gui_click_captcha()
        except Exception as e:
            print(f"   ⚠️ captcha: {e}")
        time.sleep(3)
        if find_first(sb, EMAIL_SELECTORS, timeout=2):
            return True
    return bool(find_first(sb, EMAIL_SELECTORS, timeout=2))


def open_login_page(sb):
    print("🌐 打开登录页...")
    try:
        sb.uc_open_with_reconnect(BASE_URL, reconnect_time=5)
    except Exception as e:
        print(f"⚠️ uc_open 失败，回退 open: {e}")
        sb.open(BASE_URL)
    try:
        sb.wait_for_ready_state_complete(timeout=30)
    except Exception:
        pass
    time.sleep(2)
    if page_looks_like_cf(sb) or not find_first(sb, EMAIL_SELECTORS, timeout=3):
        try_pass_cf(sb, rounds=4)
    deadline = time.time() + 45
    while time.time() < deadline:
        sel = find_first(sb, EMAIL_SELECTORS, timeout=2)
        if sel:
            print(f"✅ 登录表单就绪: {sel}")
            return True
        try:
            sb.uc_gui_click_captcha()
        except Exception:
            pass
        time.sleep(2)
    dump_debug(sb, "login_faild")
    return False


def login(sb, email, password):
    if not open_login_page(sb):
        return False, ""
    email_sel = find_first(sb, EMAIL_SELECTORS, timeout=5) or "#login_form_email"
    pass_sel = find_first(sb, PASSWORD_SELECTORS, timeout=5) or "#login_form_password"
    try:
        print("📧 填写邮箱...")
        sb.type(email_sel, email, timeout=15)
        print("🔑 填写密码...")
        sb.type(pass_sel, password, timeout=15)
    except Exception as e:
        print(f"❌ 填表失败: {e}")
        dump_debug(sb, "login_faild")
        return False, sb.get_current_url()

    time.sleep(1)
    print("🛡 处理 Turnstile...")
    try:
        sb.uc_gui_click_captcha()
        time.sleep(5)
    except Exception as e:
        print(f"⚠️ captcha: {e}")

    print("🔑 点击 Sign in...")
    for sel in [
        'button:contains("Sign in")',
        'button[type="submit"]',
        'button:contains("Login")',
    ]:
        try:
            if sb.is_element_present(sel, timeout=2):
                sb.uc_click(sel)
                break
        except Exception:
            try:
                sb.click(sel)
                break
            except Exception:
                continue

    for i in range(40):
        url = sb.get_current_url() or ""
        title = sb.get_title() or ""
        print(f"📄 {url} | {title}")
        low = url.lower()
        if "panel" in low and "login" not in low:
            print("✅ 登录成功")
            return True, url
        if i in (8, 16, 24):
            try:
                sb.uc_gui_click_captcha()
                time.sleep(2)
                sb.uc_click('button:contains("Sign in")')
            except Exception:
                pass
        time.sleep(1)

    dump_debug(sb, "login_faild")
    return False, sb.get_current_url()


def is_login_page(sb):
    """判断当前页面是否为登录页"""
    try:
        url = (sb.get_current_url() or "").lower()
        title = (sb.get_title() or "").lower()
        html = ""
        try:
            html = (sb.get_page_source() or "").lower()[:3000]
        except Exception:
            pass
        combined = f"{url} {title} {html}"
        if "login" in url or "signin" in url or "auth" in url:
            return True
        if "login" in title or "sign in" in title:
            return True
        if "password" in html and ("email" in html or "username" in html or "user" in html):
            return True
        return False
    except Exception:
        return False


def ensure_logged_in_client(sb, max_attempts=3):
    """确保 client.therose.cloud 处于已登录状态。"""
    for attempt in range(max_attempts):
        if not is_login_page(sb):
            return True
        
        print(f"🔐 检测到 client 登录页，尝试登录 (第 {attempt + 1} 次)...")
        sb.save_screenshot(f"client_relogin_attempt_{attempt + 1}.png")
        
        try:
            sb.type('input[type="email"]', EMAIL, timeout=5)
        except Exception:
            try:
                sb.type('#login_form_email', EMAIL, timeout=5)
            except Exception:
                try:
                    sb.type('input[name*="email" i]', EMAIL, timeout=5)
                except Exception as e:
                    print(f"⚠️ 邮箱输入失败: {e}")
                    continue
        
        try:
            sb.type('input[type="password"]', PASSWORD, timeout=5)
        except Exception:
            try:
                sb.type('#login_form_password', PASSWORD, timeout=5)
            except Exception as e:
                print(f"⚠️ 密码输入失败: {e}")
                continue
        
        time.sleep(1)
        
        try:
            sb.uc_gui_click_captcha()
            time.sleep(3)
        except Exception:
            pass
        
        clicked = False
        for sel in [
            'button:contains("Sign in")',
            'button:contains("Login")',
            'button:contains("Log in")',
            'button[type="submit"]',
            'input[type="submit"]',
        ]:
            try:
                if sb.is_element_present(sel, timeout=2):
                    sb.uc_click(sel, timeout=5)
                    clicked = True
                    break
            except Exception:
                continue
        
        if not clicked:
            try:
                sb.driver.execute_script(
                    "var b=document.querySelector('button[type=submit],input[type=submit]');"
                    "if(b)b.click();"
                )
            except Exception:
                pass
        
        time.sleep(8)
        
        if not is_login_page(sb):
            print("✅ 重新登录 client 成功")
            return True
    
    return False


def auto_login_panel(sb, max_attempts=3):
    """
    处理 panel.therose.cloud 的独立登录。
    使用 is_element_visible 替代 find_elements 避免 timeout 参数错误。
    """
    for attempt in range(max_attempts):
        if not is_login_page(sb):
            return True
        
        print(f"🔐 检测到 panel 登录页，尝试登录 (第 {attempt + 1} 次)...")
        sb.save_screenshot(f"panel_relogin_attempt_{attempt + 1}.png")
        
        # 判断是否有密码输入框来确定是否真的是登录页
        try:
            if not sb.is_element_visible('input[type="password"]'):
                print("⚠️ 未检测到密码输入框，可能不是登录页")
                time.sleep(2)
                continue
        except Exception:
            time.sleep(2)
            continue
        
        # 填写用户名/邮箱
        user_filled = False
        user_selectors = [
            'input[name="user"]',
            'input[type="text"]',
            'input[name="email"]',
            'input[type="email"]',
            'input[name*="user" i]',
            'input[name*="email" i]',
            'input[id*="user" i]',
            'input[id*="email" i]',
            'input[placeholder*="user" i]',
            'input[placeholder*="email" i]',
        ]
        
        for sel in user_selectors:
            try:
                if sb.is_element_visible(sel):
                    sb.type(sel, EMAIL)
                    user_filled = True
                    print(f"✅ 已填入用户名/邮箱，选择器: {sel}")
                    break
            except Exception:
                continue
        
        if not user_filled:
            # 使用 JS 找第一个可见的非密码输入框
            try:
                filled = sb.execute_script("""
                    var inputs = document.querySelectorAll('input:not([type="hidden"]):not([type="password"])');
                    for (var i = 0; i < inputs.length; i++) {
                        if (inputs[i].offsetParent !== null) {
                            inputs[i].value = arguments[0];
                            inputs[i].dispatchEvent(new Event('input', { bubbles: true }));
                            return true;
                        }
                    }
                    return false;
                """, EMAIL)
                if filled:
                    user_filled = True
                    print("✅ 已填入第一个可见文本输入框")
            except Exception as e:
                print(f"⚠️ 填入用户名失败: {e}")
                continue
        
        if not user_filled:
            print("⚠️ 无法填入用户名，跳过本次尝试")
            time.sleep(2)
            continue
        
        # 填写密码
        try:
            if sb.is_element_visible('input[type="password"]'):
                sb.type('input[type="password"]', PASSWORD)
                print("✅ 已填入密码")
        except Exception as e:
            print(f"⚠️ 密码输入失败: {e}")
            continue
        
        time.sleep(1)
        
        # 处理可能的验证码
        try:
            sb.uc_gui_click_captcha()
            time.sleep(3)
        except Exception:
            pass
        
        # 点击登录按钮
        clicked = False
        for sel in [
            'button:contains("Sign in")',
            'button:contains("Login")',
            'button:contains("Log in")',
            'button:contains("登录")',
            'button[type="submit"]',
            'input[type="submit"]',
            'button:contains("Authenticate")',
        ]:
            try:
                if sb.is_element_visible(sel):
                    sb.uc_click(sel)
                    clicked = True
                    print(f"✅ 已点击登录按钮: {sel}")
                    break
            except Exception:
                continue
        
        if not clicked:
            try:
                sb.driver.execute_script(
                    "var b=document.querySelector('button[type=submit],input[type=submit]');"
                    "if(b)b.click();"
                )
                print("✅ 已通过 JS 点击提交按钮")
            except Exception:
                pass
        
        time.sleep(8)
        
        if not is_login_page(sb):
            print("✅ panel 登录成功")
            return True
    
    return False


def navigate_with_login_check(sb, target_url, desc="页面", is_panel=False):
    """导航到目标URL，如果遇到登录页则自动登录。"""
    print(f"🌐 导航到{desc}: {target_url}")
    sb.open(target_url)
    sb.wait_for_ready_state_complete()
    time.sleep(5)
    
    if is_panel:
        if not auto_login_panel(sb):
            print(f"❌ 导航到{desc}后登录失败")
            return sb.get_current_url()
    else:
        if not ensure_logged_in_client(sb):
            print(f"❌ 导航到{desc}后登录失败")
            return sb.get_current_url()
    
    if is_login_page(sb):
        print(f"🔄 登录后重新导航到{desc}")
        sb.open(target_url)
        sb.wait_for_ready_state_complete()
        time.sleep(5)
    
    return sb.get_current_url()


def open_servers_page(sb):
    """打开 My servers 列表页。"""
    print(f"🌐 打开 My servers: {SERVERS_URL}")
    navigate_with_login_check(sb, SERVERS_URL, "My servers", is_panel=False)
    
    for _ in range(15):
        url = (sb.get_current_url() or "").lower()
        title = (sb.get_title() or "").lower()
        body = ""
        try:
            body = (sb.get_text("body") or "").lower()
        except Exception:
            pass
        if "routename=servers" in url.replace(" ", "") or "my servers" in title or "valid until" in body:
            print(f"✅ 已在 My servers | {sb.get_current_url()}")
            return True
        try:
            if sb.is_element_present('a:contains("My servers")', timeout=1):
                sb.click('a:contains("My servers")')
                time.sleep(2)
                continue
        except Exception:
            pass
        time.sleep(1)
    
    print("⚠️ 可能未稳定进入 My servers，继续尝试点 Extend")
    return True


def find_extend_info(sb):
    info = {
        "found": False,
        "clickable": False,
        "selector": None,
        "valid_until": None,
        "reason": "",
    }
    try:
        body = sb.get_text("body") or ""
        m = re.search(
            r"Valid until\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2})",
            body,
            re.I,
        )
        if m:
            info["valid_until"] = m.group(1)
            print(f"⏱ Valid until: {info['valid_until']}")
    except Exception:
        pass
    
    try:
        state = sb.execute_script(
            """
            const nodes = Array.from(document.querySelectorAll('a,button,span,div'));
            let best = null;
            for (const el of nodes) {
              const t = (el.innerText || el.textContent || '').trim().toLowerCase();
              if (!t) continue;
              if (t !== 'extend' && t !== 'renew' && !/^\\s*(extend|renew)\\s*$/i.test(t)) {
                if (!(t.includes('extend') && t.length <= 20)) continue;
              }
              const tag = el.tagName.toLowerCase();
              if (!['a','button','span','div'].includes(tag)) continue;
              let target = el;
              if (tag === 'span' || tag === 'div') {
                const p = el.closest('a,button');
                if (p) target = p;
              }
              const style = window.getComputedStyle(target);
              const disabled =
                target.disabled === true ||
                target.getAttribute('disabled') !== null ||
                target.getAttribute('aria-disabled') === 'true' ||
                target.classList.contains('disabled') ||
                style.pointerEvents === 'none' ||
                parseFloat(style.opacity || '1') < 0.5;
              const rect = target.getBoundingClientRect();
              if (rect.width < 5 || rect.height < 5) continue;
              best = {
                text: (target.innerText || '').trim().slice(0, 40),
                tag: target.tagName,
                href: target.getAttribute('href') || '',
                disabled: !!disabled,
                cls: target.className || '',
              };
              if (!disabled) break;
            }
            return best;
            """
        )
        if state:
            info["found"] = True
            print(f"🔎 Extend 节点: {state}")
            if state.get("disabled"):
                info["clickable"] = False
                info["reason"] = (
                    "Extend 按钮存在但不可点（disabled/灰显）。"
                    "常见原因：未到可续时间（部分套餐仅到期前一段时间可续），"
                    f"当前 Valid until={info.get('valid_until') or '未知'}"
                )
            else:
                info["clickable"] = True
                if state.get("href"):
                    info["href"] = state["href"]
            return info
    except Exception as e:
        print(f"⚠️ JS 查找 Extend 异常: {e}")
    
    for sel in [
        'a:contains("Extend")',
        'button:contains("Extend")',
        'a:contains("Renew")',
        'button:contains("Renew")',
    ]:
        try:
            if sb.is_element_present(sel, timeout=2):
                info["found"] = True
                info["selector"] = sel
                el = sb.find_element(sel, timeout=2)
                disabled = False
                try:
                    disabled = (
                        el.get_attribute("disabled") is not None
                        or "disabled" in (el.get_attribute("class") or "")
                    )
                except Exception:
                    pass
                info["clickable"] = not disabled
                if disabled:
                    info["reason"] = "Extend 选择器找到但 disabled"
                return info
        except Exception:
            continue
    
    info["reason"] = "页面上未找到 Extend/Renew 按钮（是否还在 My servers？）"
    return info


def click_extend(sb):
    info = find_extend_info(sb)
    if not info["found"]:
        return False, info
    
    if not info["clickable"]:
        return False, info
    
    href = info.get("href") or ""
    if href and href not in ("#", "javascript:void(0)", "javascript:;"):
        if href.startswith("/"):
            href = "https://client.therose.cloud" + href
        print(f"➡️ 通过 href 打开续期页: {href}")
        try:
            sb.open(href)
            time.sleep(3)
            return True, info
        except Exception as e:
            print(f"⚠️ href 打开失败: {e}")
    
    if SERVER_ID:
        for route in ("cart_renew", "server_renew", "renew"):
            url = f"https://client.therose.cloud/panel?routeName={route}&id={SERVER_ID}"
            print(f"➡️ 尝试直达: {url}")
            sb.open(url)
            time.sleep(2)
            if "renew" in (sb.get_title() or "").lower() or sb.is_element_present(
                "#order-submit", timeout=2
            ):
                return True, info
    
    for sel in [
        'a:contains("Extend")',
        'button:contains("Extend")',
        'a:contains("Renew")',
        'button:contains("Renew")',
    ]:
        try:
            if sb.is_element_present(sel, timeout=2):
                print(f"🖱 点击: {sel}")
                try:
                    sb.uc_click(sel, timeout=5)
                except Exception:
                    el = sb.find_element(sel, timeout=2)
                    sb.driver.execute_script("arguments[0].click();", el)
                time.sleep(3)
                return True, info
        except Exception as e:
            print(f"⚠️ 点击 {sel} 失败: {e}")
    
    try:
        ok = sb.execute_script(
            """
            const nodes = Array.from(document.querySelectorAll('a,button'));
            for (const el of nodes) {
              const t = (el.innerText || '').trim().toLowerCase();
              if (!(t === 'extend' || t.includes('extend'))) continue;
              if (el.disabled || el.getAttribute('disabled') !== null) continue;
              if (el.classList.contains('disabled')) continue;
              el.click();
              return true;
            }
            return false;
            """
        )
        if ok:
            print("✅ JS 点击 Extend 成功")
            time.sleep(3)
            return True, info
    except Exception as e:
        info["reason"] = f"点击失败: {e}"
    return False, info


def wait_renew_page(sb, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        title = (sb.get_title() or "").lower()
        url = (sb.get_current_url() or "").lower()
        has_form = False
        try:
            has_form = sb.is_element_present("#renew-form", timeout=1) or sb.is_element_present(
                "#order-submit", timeout=1
            )
        except Exception:
            pass
        if "renew" in title or "cart_renew" in url or has_form:
            print(f"✅ 已进入续期页 | {sb.get_current_url()} | {sb.get_title()}")
            return True
        time.sleep(1)
    return False


def click_order_now(sb):
    print("⏳ 等待 Order now 可点击...")
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            sb.execute_script(
                """
                const btn = document.querySelector('#order-submit');
                if (!btn) return;
                const sel = document.querySelector('#duration');
                if (sel) sel.dispatchEvent(new Event('change', { bubbles: true }));
                """
            )
            time.sleep(0.5)
            el = sb.find_element("#order-submit", timeout=3)
            disabled = el.get_attribute("disabled")
            if disabled:
                sb.execute_script(
                    """
                    const btn = document.querySelector('#order-submit');
                    if (btn) { btn.disabled = false; btn.removeAttribute('disabled'); }
                    const alert = document.querySelector('[data-alert="not_enough_balance"]');
                    if (alert) alert.classList.add('d-none');
                    """
                )
                time.sleep(0.3)
            print("🛒 点击 Order now (#order-submit)...")
            try:
                sb.uc_click("#order-submit", timeout=5)
            except Exception:
                sb.driver.execute_script(
                    "document.querySelector('#order-submit').click();"
                )
            print("✅ 已点击 Order now")
            time.sleep(4)
            return True, None
        except Exception as e:
            print(f"⏳ 等待按钮: {e}")
            time.sleep(1)
    
    for sel in [
        'button:contains("Order now")',
        'button:contains("Order Now")',
        'button[type="submit"]',
    ]:
        try:
            if sb.is_element_present(sel, timeout=2):
                sb.uc_click(sel)
                time.sleep(4)
                return True, None
        except Exception:
            continue
    return False, "未找到可点的 Order now / #order-submit"


def check_renewal_success(sb):
    time.sleep(3)
    try:
        src = (sb.get_page_source() or "").lower()
        body = ""
        try:
            body = (sb.get_text("body") or "").lower()
        except Exception:
            pass
        blob = src[:8000] + body
        for kw in (
            "successfully purchased",
            "successfully renewed",
            "server renewed",
            "renewal successful",
            "order completed",
            "thank you",
        ):
            if kw in blob:
                return True, f"关键词: {kw}"
        url = (sb.get_current_url() or "").lower()
        if "panel" in url and "renew" not in url and "cart_renew" not in url:
            if sb.is_element_present(".alert-success", timeout=2):
                t = sb.get_text(".alert-success")
                return True, t or "alert-success"
    except Exception as e:
        return False, str(e)
    
    for sel in [".alert-success", ".alert.alert-success", 'div:contains("successfully")']:
        try:
            if sb.is_element_present(sel, timeout=2):
                t = sb.get_text(sel)
                return True, t or sel
        except Exception:
            continue
    return False, "未检测到明确成功提示，请查看截图"


def check_proxy_with_requests(proxy, req_proxies):
    if not req_proxies:
        return True
    print("🔍 测试代理...")
    try:
        r = requests.get(
            "https://api.ipify.org?format=text", proxies=req_proxies, timeout=20
        )
        if r.status_code == 200 and r.text.strip():
            print(f"✅ 代理可用，出口 IP: {r.text.strip()}")
            return True
        print(f"⚠️ 代理 HTTP {r.status_code}")
    except Exception as e:
        print(f"❌ 代理失败: {e}")
    return False


def click_button_by_text(sb, text):
    """
    借鉴作者：通过 JS 精确匹配按钮文字，点击可见且未禁用的按钮。
    """
    return sb.driver.execute_script("""
        const target = arguments[0].toLowerCase().trim();
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            const rect = btn.getBoundingClientRect();
            const visible = rect.width > 0 && rect.height > 0;
            const enabled = !btn.disabled;
            const label = (btn.innerText || btn.textContent || '').trim().toLowerCase();
            if (visible && enabled && label === target) {
                btn.scrollIntoView({block: 'center', inline: 'center'});
                btn.click();
                return true;
            }
        }
        return false;
    """, text)


def click_confirm_modal(sb):
    """
    借鉴作者：点击可能的确认弹窗。
    """
    for kw in ["Confirm", "Yes", "确定", "确认"]:
        try:
            if click_button_by_text(sb, kw):
                print(f"  ✅ 已点击确认弹窗: {kw}")
                time.sleep(1)
                return True
        except Exception:
            pass
    return False


def reboot_server(sb, url):
    """
    借鉴作者的改进：先判断服务器状态，再精确匹配按钮文字，处理确认弹窗，验证重启结果。
    """
    print(f"🔄 准备进入服务器面板: {url}")
    try:
        # 使用 panel 专用的导航函数
        navigate_with_login_check(sb, url, "服务器面板", is_panel=True)
        time.sleep(5)
        
        # 检查是否被重定向到主列表页
        current_url = sb.get_current_url()
        if "/server/" not in current_url:
            print("🔀 检测到停留在主列表页，正在强制进入目标服务器控制台...")
            sb.open(url)
            sb.wait_for_ready_state_complete()
            time.sleep(6)
        
        # 保存控制台页面结构以便调试
        try:
            with open("panel_console.html", "w", encoding="utf-8", errors="ignore") as f:
                f.write(sb.get_page_source())
            print("📄 已保存 panel_console.html")
        except Exception:
            pass
        
        # 读取页面文本判断服务器状态
        try:
            source = sb.get_page_source().lower()
        except Exception:
            source = ""
        
        # 判断是否离线
        is_offline = "offline" in source
        
        btn_clicked = False
        action_name = ""
        
        if is_offline:
            print("🟡 检测到服务器处于 Offline 状态，优先点击 Start 按钮...")
            btn_clicked = click_button_by_text(sb, "Start")
            action_name = "启动"
        else:
            print("🟢 服务器在线，准备点击 Restart 按钮...")
            btn_clicked = click_button_by_text(sb, "Restart")
            action_name = "重启"
        
        # 兜底：JS 找不到就用 SeleniumBase contains
        if not btn_clicked:
            target_text = "Start" if is_offline else "Restart"
            print(f"⚠️ 文字精确匹配未找到，尝试 SeleniumBase contains: '{target_text}'")
            try:
                sb.uc_click(f'button:contains("{target_text}")', timeout=5)
                btn_clicked = True
                action_name = "启动" if is_offline else "重启"
            except Exception as e:
                print(f"❌ SeleniumBase 点击 '{target_text}' 失败: {e}")
        
        # 处理确认弹窗 + 验证结果
        if btn_clicked:
            click_confirm_modal(sb)
            
            print(f"⏳ 等待服务器{action_name}生效（最长等 60 秒）...")
            time.sleep(5)
            
            success = False
            for i in range(55):
                try:
                    sb.open("https://panel.therose.cloud")
                    sb.wait_for_ready_state_complete()
                    time.sleep(1)
                    source = sb.get_page_source().lower()
                except Exception:
                    time.sleep(2)
                    continue
                
                if "online" in source:
                    success = True
                    print(f"  ✅ 总览页检测到 Online 状态 ({i+1}次检查)")
                    break
            
            if success:
                return True, f"✅ 服务器{action_name}成功：检测到状态变为在线"
            else:
                sb.save_screenshot("reboot_unknown.png")
                return False, f"⚠️ 已点击{action_name}按钮，但 60 秒内未检测到服务器状态变化"
        else:
            return False, "❌ 页面上未找到可点击的 Start / Restart 按钮"
    
    except Exception as e:
        return False, f"重启操作发生异常: {e}"


def main():
    proxy = build_proxy()
    if proxy:
        print(f"🌐 使用代理: {mask_proxy(proxy)}")
    else:
        print("ℹ️ 未配置 PROXY")
    
    req_proxies = None
    if proxy:
        if proxy.startswith("socks5://"):
            p = "socks5h://" + proxy[len("socks5://") :]
            req_proxies = {"http": p, "https": p}
        elif "://" in proxy:
            req_proxies = {"http": proxy, "https": proxy}
        else:
            req_proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    
    if proxy and not check_proxy_with_requests(proxy, req_proxies):
        msg = "❌ 代理不可用"
        print(msg)
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
        sys.exit(1)
    
    print("🚀 启动浏览器")
    sb_kwargs = {"uc": True, "headless": False, "locale": "en"}
    if proxy:
        sb_kwargs["proxy"] = proxy
    
    with SB(**sb_kwargs) as sb:
        try:
            ok, _ = login(sb, EMAIL, PASSWORD)
        except Exception as e:
            dump_debug(sb, "login_faild")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, f"❌ 登录异常: {e}", req_proxies)
            sys.exit(1)
        
        if not ok:
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, "❌ 登录失败", req_proxies)
            sys.exit(1)
        
        print("🔍 验证登录状态...")
        sb.open("https://client.therose.cloud/panel?routeName=servers")
        time.sleep(5)
        if is_login_page(sb):
            print("⚠️ 登录状态丢失，尝试重新登录...")
            ok, _ = login(sb, EMAIL, PASSWORD)
            if not ok:
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID, "❌ 重新登录失败", req_proxies)
                sys.exit(1)
        
        open_servers_page(sb)
        dump_debug(sb, "servers_page")
        
        clicked, info = click_extend(sb)
        if not clicked:
            reason = info.get("reason") or "无法点击 Extend"
            if info.get("found") and not info.get("clickable"):
                msg = (
                    f"⏳ Extend 按钮不可点（可能未到可续时间）。"
                    f" Valid until={info.get('valid_until') or '?'}"
                )
                print(msg)
                dump_debug(sb, "extend_disabled")
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, req_proxies)
                sys.exit(0)
            msg = f"❌ 点击 Extend 失败: {reason}"
            print(msg)
            dump_debug(sb, "extend_failed")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, req_proxies)
            sys.exit(1)
        
        if not wait_renew_page(sb, timeout=35):
            msg = "❌ 点击 Extend 后未进入续期页"
            print(msg)
            dump_debug(sb, "renew_page_missing")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, req_proxies)
            sys.exit(1)
        
        dump_debug(sb, "renew_page")
        ok_order, err = click_order_now(sb)
        if not ok_order:
            msg = f"❌ Order now 失败: {err}"
            print(msg)
            dump_debug(sb, "order_failed")
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg, req_proxies)
            sys.exit(1)
        
        success, detail = check_renewal_success(sb)
        if success:
            renewal_msg = f"✅ 续期成功！{detail}"
            print(renewal_msg)
            sb.save_screenshot("renewal_success.png")
        else:
            renewal_msg = f"⚠️ 已提交但未确认成功: {detail}"
            print(renewal_msg)
            dump_debug(sb, "renewal_uncertain")
        
        reboot_msg = ""
        if SERVER_URL:
            print("🔄 开始执行服务器重启...")
            reboot_ok, reboot_detail = reboot_server(sb, SERVER_URL)
            if reboot_ok:
                reboot_msg = f"✅ 重启成功: {reboot_detail}"
                sb.save_screenshot("reboot_success.png")
            else:
                reboot_msg = f"⚠️ 重启失败: {reboot_detail}"
                sb.save_screenshot("reboot_failed.png")
            print(reboot_msg)
        else:
            print("ℹ️ 未设置 SERVER_URL，跳过重启")
            reboot_msg = "ℹ️ 未设置 SERVER_URL，跳过重启"
        
        final_msg = f"{renewal_msg}\n---\n{reboot_msg}"
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, final_msg, req_proxies)
    
    print("🏁 完成")


if __name__ == "__main__":
    main()
