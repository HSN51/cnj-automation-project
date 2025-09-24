#!/usr/bin/env python3
"""
CNJ Certificate Automation (with 2Captcha integration)
Usage:
    python cnj_automation_fixed.py --cpf 11144477735
Or set DEFAULT_CPF in .env and run without args.
"""
import os
import time
import re
import argparse
import logging
import glob
from dotenv import load_dotenv

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# --- Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Load .env
load_dotenv()
TWOCAPTCHA_KEY = os.getenv("TWOCAPTCHA_API_KEY")
DEFAULT_PROFILE = os.getenv("USER_PROFILE_DIR", os.path.join(os.path.expanduser("~"), "cnj_profile"))
DEFAULT_CPF = os.getenv("DEFAULT_CPF", "")
HEADLESS_ENV = os.getenv("HEADLESS", "false").lower() in ("1", "true", "yes")

# --- Helper for 2Captcha
class TwoCaptchaClient:
    IN_URL = "http://2captcha.com/in.php"
    RES_URL = "http://2captcha.com/res.php"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def submit_recaptcha(self, site_key: str, page_url: str, invisible: bool = False) -> str:
        """Submit recaptcha task. Returns captcha_id or raises an Exception."""
        payload = {
            "key": self.api_key,
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1
        }
        if invisible:
            payload["invisible"] = 1
        r = requests.post(self.IN_URL, data=payload, timeout=30).json()
        if r.get("status") != 1:
            raise RuntimeError(f"2Captcha in.php error: {r}")
        return r.get("request")

    def retrieve_result(self, captcha_id: str, max_tries: int = 60, sleep_sec: int = 5) -> str:
        """Poll for result. Returns token string."""
        params = {"key": self.api_key, "action": "get", "id": captcha_id, "json": 1}
        for attempt in range(1, max_tries + 1):
            r = requests.get(self.RES_URL, params=params, timeout=30).json()
            if r.get("status") == 1:
                return r.get("request")
            elif r.get("request") == "CAPCHA_NOT_READY":
                logger.debug(f"2Captcha not ready yet (attempt {attempt})")
                time.sleep(sleep_sec)
                continue
            else:
                raise RuntimeError(f"2Captcha res.php error: {r}")
        raise TimeoutError("2Captcha result timeout")

# --- Main automation class
class CNJAutomation:
    CNJ_URL = "https://www.cnj.jus.br/improbidade_adm/consultar_requerido.php"

    def __init__(self, user_profile_dir: str = DEFAULT_PROFILE, headless: bool = False, twocaptcha_key: str = None):
        self.user_profile_dir = user_profile_dir
        self.headless = headless
        self.twocaptcha_key = twocaptcha_key
        self.driver = None
        self.wait = None
        if twocaptcha_key:
            self.tc = TwoCaptchaClient(twocaptcha_key)
        else:
            self.tc = None

    def setup_driver(self):
        """Initialize Chrome driver with persistent profile"""
        try:
            if not os.path.exists(self.user_profile_dir):
                os.makedirs(self.user_profile_dir, exist_ok=True)
                logger.info(f"Created profile directory: {self.user_profile_dir}")

            options = Options()
            # keep headful by default for debug; headless optional
            if self.headless:
                options.add_argument("--headless=new")
                options.add_argument("--disable-gpu")
            options.add_argument(f"--user-data-dir={self.user_profile_dir}")
            options.add_argument("--start-maximized")
            # try minimize automation flags
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument("--disable-blink-features=AutomationControlled")
            # downloads prefs
            downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
            prefs = {
                "download.default_directory": downloads_path,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "plugins.always_open_pdf_externally": True
            }
            options.add_experimental_option("prefs", prefs)

            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.wait = WebDriverWait(self.driver, 25)

            # remove navigator.webdriver
            try:
                self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                })
            except Exception:
                # fallback
                try:
                    self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                except Exception:
                    pass

            logger.info("Chrome driver initialized")
            return True
        except Exception as e:
            logger.error(f"setup_driver error: {e}")
            return False

    def find_sitekey(self) -> str:
        """Try to find reCAPTCHA sitekey on page (search in page source and frames)."""
        page = self.driver.page_source
        # common patterns: data-sitekey or src iframe k=...
        m = re.search(r"data-sitekey\s*=\s*[\"']([0-9A-Za-z_-]+)[\"']", page)
        if m:
            return m.group(1)
        # search iframes for recaptcha
        frames = self.driver.find_elements(By.TAG_NAME, "iframe")
        for f in frames:
            src = f.get_attribute("src") or ""
            if "recaptcha" in src and "k=" in src:
                km = re.search(r"k=([0-9A-Za-z_-]+)", src)
                if km:
                    return km.group(1)
        return None

    def handle_captcha_2captcha(self, page_url: str = None) -> bool:
        """Use 2Captcha to solve reCAPTCHA v2 and inject token into page."""
        if not self.tc:
            logger.error("No 2Captcha key configured.")
            return False
        if not page_url:
            page_url = self.driver.current_url

        sitekey = self.find_sitekey()
        if not sitekey:
            logger.warning("Sitekey not found on page. Trying to wait for iframes...")
            time.sleep(2)
            sitekey = self.find_sitekey()
        if not sitekey:
            logger.error("Could not find sitekey for reCAPTCHA; manual required.")
            return False

        logger.info(f"Found reCAPTCHA sitekey: {sitekey}")
        try:
            captcha_id = self.tc.submit_recaptcha(sitekey, page_url)
            logger.info(f"Submitted to 2Captcha, id={captcha_id} — waiting for solution...")
            token = self.tc.retrieve_result(captcha_id, max_tries=90, sleep_sec=5)
            logger.info("Token received from 2Captcha")

            # Inject token into g-recaptcha-response textarea
            self.driver.execute_script("""
            var token = arguments[0];
            var el = document.getElementById('g-recaptcha-response');
            if(!el){
                el = document.createElement('textarea');
                el.id = 'g-recaptcha-response';
                el.name = 'g-recaptcha-response';
                el.style.display = 'none';
                document.body.appendChild(el);
            }
            el.value = token;
            """, token)
            # dispatch event in case site listens for change
            try:
                self.driver.execute_script("""
                var el = document.getElementById('g-recaptcha-response');
                var ev = document.createEvent('HTMLEvents');
                ev.initEvent('change', true, true);
                el.dispatchEvent(ev);
                """)
            except Exception:
                pass

            # sometimes require calling grecaptcha callback (if known)
            try:
                self.driver.execute_script("""
                if(window.grecaptcha && grecaptcha.enterprise){
                    // do nothing specific
                } else if(window.grecaptcha && grecaptcha.render){
                    // trigger potential callbacks by executing grecaptcha callback if present
                }
                """)
            except Exception:
                pass

            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"2Captcha solving error: {e}")
            return False

    def fill_cnj_form(self, cpf: str) -> bool:
        """Open CNJ page, select Pessoa Física, fill CPF, solve captcha and click Consultar."""
        try:
            logger.info("Opening CNJ page...")
            self.driver.get(self.CNJ_URL)
            time.sleep(2)

            # dismiss potential cookies/alerts if any
            try:
                # example: close cookie banners by searching common selectors
                banners = self.driver.find_elements(By.XPATH, "//button[contains(., 'Aceitar') or contains(., 'Aceito') or contains(., 'Fechar')]")
                for b in banners:
                    try:
                        if b.is_displayed():
                            b.click()
                            time.sleep(0.5)
                    except Exception:
                        continue
            except Exception:
                pass

            # select Pessoa Física - try several locators
            logger.info("Selecting Pessoa Física...")
            selected = False
            locators = [
                (By.ID, "tipoPessoaFisica"),  # original script assumption
                (By.XPATH, "//input[@type='radio' and contains(@value,'Física') or contains(@id,'fisica')]"),
                (By.XPATH, "//label[contains(., 'Física')]/preceding-sibling::input[1]")
            ]
            for by, sel in locators:
                try:
                    elem = self.wait.until(EC.element_to_be_clickable((by, sel)))
                    try:
                        elem.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", elem)
                    selected = True
                    break
                except Exception:
                    continue
            if not selected:
                logger.warning("Could not auto-select Pessoa Física. Continue and hope default is fine.")

            time.sleep(1)

            # find CPF field
            logger.info(f"Filling CPF: {cpf}")
            cpf_elem = None
            try:
                cpf_elem = self.wait.until(EC.presence_of_element_located((By.ID, "num_cpf_cnpj")))
            except Exception:
                # fallback search
                try:
                    cpf_elem = self.driver.find_element(By.XPATH, "//input[contains(@name,'cpf') or contains(@id,'cpf') or contains(@placeholder,'CPF')]")
                except Exception:
                    cpf_elem = None

            if not cpf_elem:
                logger.error("CPF field not found on page.")
                return False

            cpf_elem.clear()
            for ch in cpf:
                cpf_elem.send_keys(ch)
                time.sleep(0.05)

            time.sleep(0.5)

            # Solve captcha (automatic if twocaptcha key provided, else manual pause)
            page_url = self.driver.current_url
            if self.tc:
                ok = self.handle_captcha_2captcha(page_url)
                if not ok:
                    logger.error("Automatic CAPTCHA solving failed.")
                    return False
            else:
                logger.warning("No 2Captcha configured - waiting for manual CAPTCHA solve. Please interact with browser.")
                input("Please solve the CAPTCHA manually in the opened browser and press Enter here to continue...")

            # Click Consultar button (try various locators)
            logger.info("Clicking 'Consultar' (Pesquisar) button...")
            consult_locators = [
                (By.ID, "btnPesquisarRequerido"),
                (By.XPATH, "//input[@value='Pesquisar' or @value='Consultar' or contains(@value,'Pesquisar')]"),
                (By.XPATH, "//button[contains(., 'Pesquisar') or contains(., 'Consultar')]")
            ]
            clicked = False
            for by, sel in consult_locators:
                try:
                    btn = self.wait.until(EC.element_to_be_clickable((by, sel)))
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                    time.sleep(0.5)
                    try:
                        btn.click()
                    except Exception:
                        ActionChains(self.driver).move_to_element(btn).click().perform()
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked:
                logger.error("Could not click 'Consultar' button.")
                return False

            logger.info("'Consultar' clicked. Waiting for results...")
            time.sleep(3)
            return True
        except Exception as e:
            logger.error(f"fill_cnj_form error: {e}")
            return False

    def wait_for_results_and_issue_certificate(self) -> bool:
        """Wait for results and try to click Gerar Certidão Negativa or download certificate."""
        try:
            # Wait short while for results to load
            time.sleep(2)
            # Search for common certificate controls
            certificate_xpaths = [
                "//input[@value='Gerar Certidão Negativa']",
                "//button[contains(., 'Gerar Certidão Negativa')]",
                "//a[contains(., 'Gerar Certidão Negativa')]",
                "//input[contains(@value,'Certidão')]",
                "//button[contains(., 'Certidão')]",
                "//a[contains(., 'Certidão')]",
            ]

            found = False
            for xpath in certificate_xpaths:
                try:
                    el = self.driver.find_element(By.XPATH, xpath)
                    if el and el.is_displayed() and el.is_enabled():
                        logger.info(f"Found certificate control: {xpath}")
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", el)
                        time.sleep(0.5)
                        try:
                            el.click()
                        except Exception:
                            try:
                                ActionChains(self.driver).move_to_element(el).click().perform()
                            except Exception:
                                self.driver.execute_script("arguments[0].click();", el)
                        found = True
                        logger.info("Clicked certificate control, waiting for download/page...")
                        time.sleep(5)
                        break
                except Exception:
                    continue

            # If not found, maybe results show a table row then a specific link appears - attempt to check for rows
            if not found:
                try:
                    # Check for any anchor with 'certidao' in href
                    anchors = self.driver.find_elements(By.XPATH, "//a[contains(translate(@href,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'certidao') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'certidão')]")
                    for a in anchors:
                        if a.is_displayed():
                            logger.info("Found certificate anchor, clicking it...")
                            self.driver.execute_script("arguments[0].scrollIntoView(true);", a)
                            time.sleep(0.5)
                            try:
                                a.click()
                            except Exception:
                                self.driver.execute_script("arguments[0].click();", a)
                            found = True
                            time.sleep(5)
                            break
                except Exception:
                    pass

            # After clicking, check downloads or new tab
            downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
            time.sleep(3)
            # check new tab
            if len(self.driver.window_handles) > 1:
                logger.info("New tab opened, switching to it...")
                self.driver.switch_to.window(self.driver.window_handles[-1])
                time.sleep(2)

            # look for pdf-like content in URL
            cur = self.driver.current_url.lower()
            if "certidao" in cur or "certificado" in cur or ".pdf" in cur:
                logger.info(f"On certificate page: {self.driver.current_url}")
                # Wait a bit for PDF download
                time.sleep(5)
            # Try to find recently downloaded file
            matches = glob.glob(os.path.join(downloads_path, "*certidao*.pdf")) + glob.glob(os.path.join(downloads_path, "*certificado*.pdf")) + glob.glob(os.path.join(downloads_path, "*certidao*"))
            if matches:
                latest = max(matches, key=os.path.getctime)
                logger.info(f"Certificate seems downloaded: {latest}")
                return True

            logger.warning("Could not automatically confirm certificate download. Please check browser.")
            # save screenshot
            try:
                ss = os.path.join(os.getcwd(), "cnj_debug.png")
                self.driver.save_screenshot(ss)
                logger.info(f"Saved screenshot to {ss}")
            except Exception:
                pass
            return False
        except Exception as e:
            logger.error(f"wait_for_results_and_issue_certificate error: {e}")
            return False

    def run(self, cpf: str) -> bool:
        try:
            if not self.setup_driver():
                return False
            ok = self.fill_cnj_form(cpf)
            if not ok:
                logger.error("Form fill failed.")
                return False
            ok2 = self.wait_for_results_and_issue_certificate()
            if not ok2:
                logger.warning("Certificate step may require manual check.")
            logger.info("Process finished (browser left open for inspection).")
            # leave browser open for user to verify; optionally close on prompt
            input("Press Enter to close browser and exit...")
            return ok2
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass

# --- CLI
def main():
    parser = argparse.ArgumentParser(description="CNJ Certificate Automation with 2Captcha support")
    parser.add_argument("--cpf", type=str, help="Authorized CPF (11 digits).")
    parser.add_argument("--profile", type=str, default=DEFAULT_PROFILE, help="Chrome user-data-dir profile path.")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode (not recommended for captcha debug).")
    args = parser.parse_args()

    cpf = args.cpf or DEFAULT_CPF
    if not cpf or not cpf.isdigit() or len(cpf) not in (11, 14):
        print("Please provide a valid CPF (11 digits). Use --cpf or set DEFAULT_CPF in .env.")
        return

    profile = args.profile
    headless = args.headless or HEADLESS_ENV
    twocaptcha = TWOCAPTCHA_KEY

    autom = CNJAutomation(user_profile_dir=profile, headless=headless, twocaptcha_key=twocaptcha)
    success = autom.run(cpf)
    if success:
        print("✅ Certificate flow appears successful or started.")
    else:
        print("⚠️ Flow did not finish automatically — please inspect the browser and logs.")

if __name__ == "__main__":
    main()
