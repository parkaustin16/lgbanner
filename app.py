import os
import time
import zipfile
import io
import sys
import asyncio
from datetime import datetime
import streamlit as st
import cloudinary
import cloudinary.uploader
from pyairtable import Api
import subprocess
import os


# Check if chromium is installed, if not, install it
# Check if chromium and fonts are installed, if not, install them
@st.cache_resource
def install_playwright_browsers():
    try:
        # We no longer run apt-get here because packages.txt handles it
        # Just install the Playwright chromium binary
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Error installing playwright: {e}")


# Call the function
install_playwright_browsers()
# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv not installed, will use system env variables

# Windows-specific fix for Python 3.13 + Playwright subprocess error
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.sync_api import sync_playwright, ViewportSize

# --- CONFIGURATION ---
UPLOAD_FOLDER = 'static/captures'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# Helper function to get config from Streamlit secrets or environment variables
def get_config(key, default=None):
    """Get configuration from Streamlit secrets first, then environment variables."""
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except:
        return os.getenv(key, default)


# Cloudinary Configuration
CLOUDINARY_CLOUD_NAME = st.secrets["CLOUDINARY_HIDDEN_CLOUD_NAME"]
CLOUDINARY_API_KEY = st.secrets['CLOUDINARY_HIDDEN_API_KEY']
CLOUDINARY_API_SECRET = st.secrets['CLOUDINARY_HIDDEN_API_SECRET']

# Airtable Configuration
AIRTABLE_API_KEY = st.secrets["AIRTABLE_HIDDEN_API_KEY"]
AIRTABLE_BASE_ID = st.secrets["AIRTABLE_HIDDEN_BASE_ID"]
AIRTABLE_TABLE_NAME = "capture"

# Configure Cloudinary only if credentials are available
if all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True
    )

# Fix SSL certificate verification issues
import ssl
import certifi
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context

st.set_page_config(page_title="Banner Capture", layout="wide")


# --- CLOUDINARY UPLOAD ---

def upload_to_cloudinary(file_path, country_code, mode, slide_num):
    """Upload image to Cloudinary and return the URL."""
    if not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
        st.warning("⚠️ Cloudinary credentials not configured. Please set them in .env file or Streamlit secrets.")
        return None, None

    try:
        import hashlib
        import base64

        # Generate timestamp
        timestamp = int(time.time())

        # Prepare upload parameters
        folder_name = f"lg_banners/{country_code}/{mode}"
        public_id = f"{country_code}_{mode}_hero_{slide_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Method 1: Try using cloudinary SDK with proper config
        try:
            response = cloudinary.uploader.upload(
                file_path,
                folder=folder_name,
                public_id=public_id,
                resource_type="image",
                overwrite=True,
                use_filename=False
            )
            return response.get('secure_url'), response.get('public_id')
        except Exception as sdk_error:
            # Method 2: Fallback to direct API call with proper signature
            import requests

            # Create signature for authentication
            params_to_sign = f"folder={folder_name}&public_id={public_id}&timestamp={timestamp}{CLOUDINARY_API_SECRET}"
            signature = hashlib.sha1(params_to_sign.encode('utf-8')).hexdigest()

            url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload"

            with open(file_path, 'rb') as f:
                files = {'file': f}
                data = {
                    'api_key': CLOUDINARY_API_KEY,
                    'timestamp': timestamp,
                    'signature': signature,
                    'folder': folder_name,
                    'public_id': public_id
                }

                response = requests.post(url, files=files, data=data, verify=False)
                response.raise_for_status()
                result = response.json()

                return result.get('secure_url'), result.get('public_id')

    except Exception as e:
        st.error(f"❌ Cloudinary upload failed: {str(e)}")
        return None, None


# --- AIRTABLE INTEGRATION ---

def save_to_airtable(country_code, mode, urls, full_country_name):
    """Save all capture URLs to a single Airtable record."""
    if not all([AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME]):
        st.warning("⚠️ Airtable credentials not configured. Please set them in .env file or Streamlit secrets.")
        return None

    try:
        # Determine banner type and record name
        banner_type_label = "hero-banner-pc" if mode.lower() == "desktop" else "hero-banner-mo"
        mode_suffix = "pc" if mode.lower() == "desktop" else "mobile"
        record_name = f"{country_code.lower()}-hero-banner-{mode_suffix}-gp1"
        capture_date = datetime.now().strftime('%m/%d/%Y')
        
        # Format the URLs as a single string (newline separated)
        url_text = ", ".join(urls)

        # Method 1: Try using pyairtable with SSL fix
        try:
            api = Api(AIRTABLE_API_KEY)
            table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

            record = {
                "domain": country_code,
                "country": full_country_name,
                "period": capture_date,
                "banner-type": banner_type_label,
                "URLs": url_text
            }

            created_record = table.create(record)
            return created_record['id']

        except Exception as pyairtable_error:
            # Method 2: Fallback to direct requests API call
            import requests

            url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"

            headers = {
                "Authorization": f"Bearer {AIRTABLE_API_KEY}",
                "Content-Type": "application/json"
            }

            data = {
                "fields": {
                    "domain": country_code,
                    "country": full_country_name,
                    "period": capture_date,
                    "banner-type": banner_type_label,
                    "URLs": url_text
                }
            }

            response = requests.post(url, json=data, headers=headers, verify=False)
            response.raise_for_status()
            result = response.json()

            return result.get('id')

    except Exception as e:
        st.error(f"❌ Airtable save failed: {str(e)}")
        return None


# --- CORE CAPTURE LOGIC (Enhanced with Hero Detection) ---

def apply_clean_styles(page_obj):
    """Comprehensive CSS cleanup with Sharpening and Speed fixes."""
    page_obj.evaluate("""
        document.querySelectorAll('.c-notification-banner').forEach(el => el.remove());
        const style = document.createElement('style');
        style.innerHTML = `
            [class*="chat"], [id*="chat"], [class*="proactive"], 
        .alk-container, #genesys-chat, .genesys-messenger,
        .floating-button-portal, #WAButton, .embeddedServiceHelpButton,
        .c-pop-toast__container, .onetrust-pc-dark-filter, #onetrust-consent-sdk,
        .c-membership-popup, 
        [class*="cloud-shoplive"], [class*="csl-"], [class*="svelte-"], 
        .l-cookie-teaser, .c-cookie-settings, .LiveMiniPreview,
        .c-notification-banner, .c-notification-banner *, .c-notification-banner__wrap,
        .open-button, .js-video-pause, .js-video-play, [aria-label*="Pausar"], [aria-label*="video"]
            { display: none !important; visibility: hidden !important; opacity: 0 !important; pointer-events: none !important; }

            /* SPEED: Disable transitions for instant navigation */
            *, *::before, *::after {
                transition-duration: 0s !important;
                animation-duration: 0s !important;
                transition-delay: 0s !important;
                animation-delay: 0s !important;
            }

            /* Sharpness Fixes: Disable smoothing that causes blur during screenshots */
            .cmp-carousel__item, .c-hero-banner, img {
                image-rendering: -webkit-optimize-contrast !important;
                image-rendering: crisp-edges !important;
                transform: translateZ(0) !important;
                backface-visibility: hidden !important;
                perspective: 1000 !important;
            }
        `;
        document.head.appendChild(style);

        const hideSelectors = ['.c-header', '.navigation', '.iw_viewport-wrapper > header', '.al-quick-btn__quickbtn', '.al-quick-btn__topbtn'];
        hideSelectors.forEach(s => {
            document.querySelectorAll(s).forEach(el => el.style.setProperty('display', 'none', 'important'));
        });

        const opacitySelectors = ['.cmp-carousel__indicators', '.cmp-carousel__actions', '.c-carousel-controls'];
        opacitySelectors.forEach(s => {
            document.querySelectorAll(s).forEach(el => el.style.setProperty('opacity', '0', 'important'));
        });

        // Pause videos immediately to prevent motion blur
        document.querySelectorAll('video').forEach(v => v.pause());
    """)


def find_hero_carousel(page, log_callback=None):
    """
    Intelligently identify the FIRST/MAIN hero banner carousel on LG.com pages.
    Filters out notification banners and other non-hero carousels.
    """

    def log(message):
        if log_callback:
            log_callback(message)

    log("🔍 Detecting hero carousel...")

    excluded_wrappers = ".c-notification-banner, .l-cookie-teaser, .c-membership-popup"

    hero_selectors = [
        "main .cmp-carousel",
        ".main-content .cmp-carousel",
        ".hero-section .cmp-carousel",
        ".c-hero-section .cmp-carousel",
        "[class*='hero'] .cmp-carousel",
        ".content .cmp-carousel",
        "section .cmp-carousel",
    ]

    hero_carousel = None
    for selector in hero_selectors:
        try:
            elements = page.query_selector_all(selector)
            for element in elements:
                is_in_excluded = element.evaluate(f"el => !!el.closest('{excluded_wrappers}')")
                if is_in_excluded:
                    continue

                indicators = element.query_selector_all(".cmp-carousel__indicator")
                if len(indicators) > 0:
                    bbox = element.bounding_box()
                    if bbox and bbox['height'] >= 300:
                        log(f"✅ Found hero carousel using: {selector}")
                        hero_carousel = element
                        break
            if hero_carousel:
                break
        except Exception:
            continue

    if not hero_carousel:
        log("⚠️ Could not find hero carousel with specific selectors, using advanced scoring...")
        try:
            all_carousels = page.query_selector_all(".cmp-carousel")
            candidates = []
            viewport_size = page.viewport_size
            viewport_width = viewport_size['width'] if viewport_size else 1280

            for idx, carousel in enumerate(all_carousels):
                is_in_excluded = carousel.evaluate(f"el => !!el.closest('{excluded_wrappers}')")
                if is_in_excluded:
                    log(f"   Carousel {idx}: SKIPPED (inside {excluded_wrappers})")
                    continue

                indicators = carousel.query_selector_all(".cmp-carousel__indicator")
                if len(indicators) == 0:
                    continue

                bbox = carousel.bounding_box()
                if not bbox:
                    continue

                if bbox['height'] < 200:
                    log(f"   Carousel {idx}: SKIPPED (too short: {bbox['height']:.0f}px)")
                    continue

                if bbox['width'] < viewport_width * 0.5:
                    log(f"   Carousel {idx}: SKIPPED (too narrow: {bbox['width']:.0f}px)")
                    continue

                has_hero_banner = carousel.query_selector(".c-hero-banner") is not None
                has_hero_image = carousel.query_selector(".c-image__item, .cmp-image") is not None

                try:
                    carousel_text = carousel.inner_text().lower()
                    notification_keywords = [
                        'cookie', 'クッキー', 'プライバシー', 'privacy', 'notice',
                        'お知らせ', '利用規約', '特定商取引', 'オンラインショップ',
                        'terms', 'conditions', '規約', '改正'
                    ]
                    if any(keyword in carousel_text for keyword in notification_keywords):
                        log(f"   Carousel {idx}: SKIPPED (notification/legal content detected)")
                        continue
                except:
                    pass

                score = 0
                if has_hero_banner:
                    score += 100
                if has_hero_image:
                    score += 50

                area = bbox['width'] * bbox['height']
                if area > 500000:
                    score += 30

                if bbox['height'] > 400:
                    score += 50
                elif bbox['height'] > 300:
                    score += 30
                elif bbox['height'] > 200:
                    score += 10

                if 100 < bbox['y'] < 600:
                    score += 25
                elif 50 < bbox['y'] < 100:
                    score -= 20
                elif bbox['y'] < 50:
                    score -= 100

                if bbox['width'] > viewport_width * 0.9:
                    score += 20
                elif bbox['width'] > viewport_width * 0.8:
                    score += 15

                candidates.append({
                    'carousel': carousel,
                    'score': score,
                    'position': bbox['y'],
                    'height': bbox['height'],
                    'size': area,
                    'has_hero': has_hero_banner,
                    'index': idx
                })

                log(f"   Carousel {idx}: score={score}, pos={bbox['y']:.0f}px, height={bbox['height']:.0f}px, size={area:.0f}, hero={has_hero_banner}")

            if candidates:
                candidates.sort(key=lambda x: x['score'], reverse=True)
                best = candidates[0]

                if best['score'] > 0:
                    hero_carousel = best['carousel']
                    log(f"✅ Selected carousel {best['index']} (score: {best['score']})")
                else:
                    log(f"❌ No suitable carousel found (best score: {best['score']})")

        except Exception as e:
            log(f"❌ Error in advanced detection: {str(e)}")

    return hero_carousel


def capture_hero_banners(url, country_code, mode='desktop', log_callback=None, upload_to_cloud=False):
    def log(message):
        if log_callback:
            log_callback(message)

    size = {'width': 1920, 'height': 720} if mode == 'desktop' else {'width': 360, 'height': 640}
    session_folder_name = f"{country_code}_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    session_path = os.path.join(UPLOAD_FOLDER, session_folder_name)
    os.makedirs(session_path, exist_ok=True)

    with sync_playwright() as p:
        log("🚀 Launching browser (Stealth configuration)...")
        
        # EXTENSIVE EVASION ARGUMENTS
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-popup-blocking",
            "--start-maximized",
            "--disable-web-security"
        ]
        
        browser = p.chromium.launch(headless=True, args=args)
        
        # Real-world User Agent
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        
        context = browser.new_context(
            viewport=size,
            device_scale_factor=2,
            user_agent=user_agent,
            locale="en-US",
            timezone_id="America/New_York",
            # Add extra headers to look legitimate
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "max-age=0",
                "Sec-Ch-Ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
                "Sec-Ch-Ua-Mobile": "?0" if mode == 'desktop' else "?1",
                "Sec-Ch-Ua-Platform": '"Windows"' if mode == 'desktop' else '"Android"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1"
            }
        )
        
        # INJECT JAVASCRIPT TO MASK WEBDRIVER PROPERTY
        # This is the single most important line for bypassing detection
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = context.new_page()

        try:
            log(f"🌐 Navigating to {url}...")
            # Wait for commit instead of full load to check status earlier
            response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Check Status Code
            if response and response.status in [403, 429]:
                log(f"⛔ Server responded with {response.status} (Access Denied)")
                page.screenshot(path=os.path.join(session_path, "debug_403.jpg"))
                return

            # Check Page Title for Soft Blocks
            if "Access Denied" in page.title() or "Human" in page.title():
                log("⛔ Still BLOCKED by firewall.")
                page.screenshot(path=os.path.join(session_path, "debug_softblock.jpg"))
                return

            # --- CAROUSEL DETECTION (Same robust logic as before) ---
            log("🔍 Access granted! Looking for .c-hero-banner...")
            
            try:
                # Wait for banner to appear
                page.wait_for_selector(".c-hero-banner", timeout=15000)
                banner = page.locator(".c-hero-banner").first
                hero_carousel = banner.locator("xpath=ancestor::div[contains(@class, 'cmp-carousel')][1]")
                
                if hero_carousel.count() == 0:
                    hero_carousel = page.locator(".cmp-carousel").first
                    
                log("✅ Found Hero Carousel")
                hero_carousel.scroll_into_view_if_needed()
                time.sleep(1)
                
            except Exception as e:
                log(f"❌ Failed to find carousel content: {e}")
                page.screenshot(path=os.path.join(session_path, "debug_no_content.jpg"))
                return

            indicators = hero_carousel.locator(".cmp-carousel__indicator").all()
            num_slides = len(indicators)
            log(f"📸 Found {num_slides} slides")

            captured_sigs = []

            for i in range(num_slides):
                slide_num = i + 1
                success = False
                
                for attempt in range(3):
                    # Navigation
                    try:
                        page.evaluate("""(i) => {
                            const banner = document.querySelector('.c-hero-banner');
                            const car = banner ? banner.closest('.cmp-carousel') : document.querySelector('.cmp-carousel');
                            if (car && car.swiper) {
                                car.swiper.autoplay.stop();
                                car.swiper.slideToLoop(i, 0);
                            } else {
                                car.querySelectorAll('.cmp-carousel__indicator')[i].click();
                            }
                        }""", i)
                    except: pass

                    time.sleep(2.0)
                    apply_clean_styles(page)
                    
                    filename = f"{country_code}_{mode}_hero_{slide_num}.jpg"
                    filepath = os.path.join(session_path, filename)
                    
                    try:
                        hero_carousel.screenshot(path=filepath, scale="device", quality=95)
                        log(f"✅ Captured: {filename}")
                        
                        c_url = None
                        if upload_to_cloud:
                             c_url, _ = upload_to_cloudinary(filepath, country_code, mode, slide_num)
                        yield filepath, slide_num, c_url
                        success = True
                        break
                    except Exception as e:
                        time.sleep(1)

                if not success:
                    log(f"❌ Failed slide {slide_num}")

        except Exception as e:
            log(f"❌ Error: {str(e)}")
        finally:
            browser.close()

# --- STREAMLIT UI ---

def main():
    st.title("LG Hero Banner Capture")

    with st.expander("⚙️ Configuration Status", expanded=False):
        cloudinary_configured = all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET])
        airtable_configured = all([AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME])
        st.write("**Cloudinary:**", "✅ Configured" if cloudinary_configured else "❌ Not configured")
        st.write("**Airtable:**", "✅ Configured" if airtable_configured else "❌ Not configured")

    if 'log_messages' not in st.session_state:
        st.session_state.log_messages = []
        
    if 'stop_requested' not in st.session_state:
        st.session_state.stop_requested = False

    with st.sidebar:
        st.header("Settings")
        if st.button("🔍 Test Airtable Connection"):
            try:
                import requests
                # 1. READ TEST
                read_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
                headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
                read_response = requests.get(read_url, headers=headers, verify=False)

                if read_response.status_code == 200:
                    st.success("✅ READ access works!")

                    # 2. WRITE TEST (Functional check without the info text)
                    write_data = {
                        "fields": {
                            "country": "Australia",
                            "period": datetime.now().strftime('%m/%d/%Y'),
                            "banner-type": "hero-banner-pc",
                        }
                    }
                    write_response = requests.post(read_url, json=write_data, headers=headers, verify=False)

                    if write_response.status_code == 200:
                        st.success("✅ WRITE access works!")
                        # Cleanup test record
                        record_id = write_response.json().get('id')
                        requests.delete(f"{read_url}/{record_id}", headers=headers, verify=False)
                    else:
                        st.error(f"❌ WRITE failed: {write_response.text}")
                else:
                    st.error(f"❌ READ failed: {read_response.text}")
            except Exception as e:
                st.error(f"❌ Test failed: {str(e)}")

        st.divider()

        # Regional Groups Definition
        regions = {
            "Asia": [
                ("au", "Australia (AU)"), ("jp", "Japan (JP)"), ("hk", "Hong Kong (HK)"), ("tw", "Taiwan (TW)"),
                ("in", "India (IN)"), ("sg", "Singapore (SG)"), ("my", "Malaysia (MY)"),
                ("th", "Thailand (TH)"), ("vn", "Vietnam (VN)"), ("ph", "Philippines (PH)"),
                ("id", "Indonesia (ID)")
            ],
            "Europe": [
                ("uk", "United Kingdom (UK)"), ("ch_fr", "Switzerland (CH_FR)"), ("ch_de", "Switzerland (CH_DE)"),
                ("fr", "France (FR)"), ("de", "Germany (DE)"), ("it", "Italy (IT)"),
                ("es", "Spain (ES)"), ("nl", "Netherlands (NL)"), ("cz", "Czech Republic (CZ)"),
                ("se", "Sweden (SE)"), ("pt", "Portugal (PT)"), ("hu", "Hungary (HU)"),
                ("pl", "Poland (PL)"), ("at", "Austria (AT)")
            ],
            "LATAM": [
                ("mx", "Mexico (MX)"), ("br", "Brazil (BR)"), ("ar", "Argentina (AR)"), ("cl", "Chile (CL)"),
                ("co", "Colombia (CO)"), ("pe", "Peru (PE)"), ("pa", "Panama (PA)")
            ],
            "MEA": [
                ("kz", "Kazakhstan (KZ)"), ("tr", "Turkiye (TR)"), ("eg_en", "Egypt (EG_EN)"), ("eg_ar", "Egypt (EG_AR)"),
                ("ma", "Morocco (MA)"), ("sa_en", "Saudi Arabia (SA_EN)"), ("sa", "Saudi Arabia (SA)"), 
                ("za", "South Africa (ZA)")
            ],
            "Canada": [
                ("ca_en", "Canada (CA_EN)"), ("ca_fr", "Canada (CA_FR)")
            ]
        }
        
        all_subs = []
        for r_list in regions.values():
            all_subs.extend(r_list)

        # Build Dropdown Options
        # Options will be: Region Name, All Subsidiaries, or Individual Country Name
        country_labels = ["All Subsidiaries", "Asia", "Europe", "LATAM", "MEA", "Canada"]
        
        # Add individual countries (sorted)
        individual_sorted = sorted(all_subs, key=lambda x: x[1])
        country_labels.extend([label for _, label in individual_sorted])

        selected_option = st.selectbox("Subsidiary/Region", options=country_labels, index=0) # Default to All Subsidiaries
        mode = st.selectbox("View Mode", options=["desktop", "mobile"])

        st.divider()
        st.subheader("☁️ Airtable Upload")
        upload_enabled = st.checkbox("Upload to Cloudinary & Airtable", value=False, disabled=not (
                all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]) and all(
            [AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME])))

        st.divider()
        run_btn = st.button("Start Capture", type="primary", use_container_width=True)
        
        # Stop Capture Button replaces "Run All Subsidiaries"
        if st.button("Stop Capture", use_container_width=True):
            st.session_state.stop_requested = True
            st.warning("Stop requested. Will exit after current country finishes.")
            
        st.divider()
        st.subheader("Activity Log")
        log_placeholder = st.empty()

    def add_log(message):
        msg = f"`{datetime.now().strftime('%H:%M:%S')}` {message}"
        st.session_state.log_messages.append(msg)
        
        # Keep only the last 50 logs to prevent memory/app reset issues
        if len(st.session_state.log_messages) > 50:
            st.session_state.log_messages = st.session_state.log_messages[-50:]
            
        log_placeholder.markdown("\n\n".join(st.session_state.log_messages[::-1]))

    # Logic for Capture
    if run_btn:
        st.session_state.log_messages = []
        st.session_state.stop_requested = False
        
        # Determine the queue based on selection
        capture_queue = []
        if selected_option == "All Subsidiaries":
            capture_queue = all_subs
        elif selected_option in regions:
            capture_queue = regions[selected_option]
        else:
            # It's an individual country
            selected_code = next(code for code, label in all_subs if label == selected_option)
            capture_queue = [(selected_code, selected_option)]

        add_log(f"🏁 Starting capture for **{selected_option}** ({len(capture_queue)} sites) in **{mode}** mode...")
        
        progress_bar = st.progress(0)
        
        # Single view for results if only 1 country, otherwise just show logs
        if len(capture_queue) == 1:
            site, label = capture_queue[0]
            country_full_name = label.split(" (")[0]
            url = f"https://www.lg.com/{site}/"
            captured_files = []
            cloudinary_urls = []
            
            st.subheader(f"Results: {site.upper()} ({mode})")
            cols = st.columns(3)
            
            for idx, result in enumerate(capture_hero_banners(url, site, mode, log_callback=add_log, upload_to_cloud=upload_enabled)):
                img_path, slide_num, cloudinary_url = result
                captured_files.append(img_path)
                if cloudinary_url:
                    cloudinary_urls.append(cloudinary_url)
                    
                with cols[idx % 3]:
                    st.image(img_path, caption=f"Slide {slide_num}")
                    if cloudinary_url: st.caption(f"☁️ [View on Cloudinary]({cloudinary_url})")

            if upload_enabled and cloudinary_urls:
                add_log("💾 Saving record to Airtable...")
                save_to_airtable(site, mode, cloudinary_urls, country_full_name)
            
            if captured_files:
                st.divider()
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zf:
                    for fpath in captured_files: zf.write(fpath, os.path.basename(fpath))
                st.download_button(label="📥 Download Banners (ZIP)", data=zip_buffer.getvalue(),
                                   file_name=f"banners_{site}_{mode}_{datetime.now().strftime('%Y%m%d')}.zip",
                                   mime="application/zip", use_container_width=True)
                st.success(f"✅ Capture complete! {len(captured_files)} images saved.")
        else:
            # Batch process
            for i, (c_code, c_label) in enumerate(capture_queue):
                if st.session_state.stop_requested:
                    add_log("🛑 Capture process stopped by user.")
                    break
                    
                c_full_name = c_label.split(" (")[0]
                url = f"https://www.lg.com/{c_code}/"
                
                add_log(f"🌍 Processing **{c_label}** ({i+1}/{len(capture_queue)})...")
                cloudinary_urls = []
                
                for result in capture_hero_banners(url, c_code, mode, log_callback=add_log, upload_to_cloud=upload_enabled):
                    _, _, cloudinary_url = result
                    if cloudinary_url:
                        cloudinary_urls.append(cloudinary_url)
                
                if upload_enabled and cloudinary_urls:
                    save_to_airtable(c_code, mode, cloudinary_urls, c_full_name)
                
                # Manual memory cleanup after each country
                import gc
                gc.collect()
                
                progress_bar.progress((i + 1) / len(capture_queue))
            
            if not st.session_state.stop_requested:
                add_log("✨ Batch processing complete!")
                st.success("✅ Selected region/group processed successfully.")


if __name__ == "__main__":
    main()
