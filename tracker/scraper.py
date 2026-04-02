"""
UNX Character Tracker - 실제 스크래퍼
Playwright 기반으로 Zeta AI, Rofan AI, Crack AI 실시간 데이터 수집
"""
from __future__ import annotations
import logging
import time
import os
import hashlib
import requests
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

@dataclass
class Character:
    id: str
    name: str
    source: str  # "zeta" | "rofan" | "crack" | "sample"
    description: str = ""
    tags: list = field(default_factory=list)
    interaction_count: int = 0
    chat_count_str: str = ""
    creator: str = ""
    url: str = ""
    image_url: str = ""
    image_local: str = ""  # 로컬 저장 경로 (public/images/...)
    raw: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "description": self.description,
            "tags": self.tags,
            "interaction_count": self.interaction_count,
            "chat_count_str": self.chat_count_str,
            "creator": self.creator,
            "url": self.url,
            "image_url": self.image_url,
            "image_local": self.image_local,
        }


def download_image(image_url: str, save_dir: Path, filename: str = None) -> str:
    """이미지를 다운로드하고 로컬 경로 반환"""
    if not image_url:
        return ""
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
        if not filename:
            ext = image_url.split("?")[0].split(".")[-1] or "jpg"
            if ext not in ["jpg", "jpeg", "png", "webp", "gif"]:
                ext = "jpg"
            h = hashlib.md5(image_url.encode()).hexdigest()[:12]
            filename = f"{h}.{ext}"
        save_path = save_dir / filename
        if save_path.exists():
            return f"/images/{filename}"
        resp = requests.get(image_url, headers=HEADERS, timeout=10, stream=True)
        resp.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        logger.info(f"[Image] 저장: {filename}")
        return f"/images/{filename}"
    except Exception as e:
        logger.warning(f"[Image] 다운로드 실패 {image_url[:60]}: {e}")
        return ""


def parse_count(s: str) -> int:
    """'4.2만' → 42000 변환"""
    if not s:
        return 0
    s = s.strip().replace(",", "").replace(" ", "")
    try:
        if "만" in s:
            return int(float(s.replace("만", "")) * 10000)
        if "천" in s:
            return int(float(s.replace("천", "")) * 1000)
        if "k" in s.lower():
            return int(float(s.lower().replace("k", "")) * 1000)
        if "M" in s:
            return int(float(s.replace("M", "")) * 1000000)
        return int(float(s))
    except:
        return 0


class ZetaScraper:
    """Zeta AI (zeta-ai.io) 랭킹 스크래퍼 - Playwright 사용"""
    BASE = "https://zeta-ai.io"
    RANKING_URL = "https://zeta-ai.io/ko?tab=ranking"
    IMAGE_BASE = "https://image.zeta-ai.io/plot-cover-image"

    def fetch(self, cfg, image_dir: Path) -> list[Character]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[Zeta] playwright 미설치 → 스킵")
            return []

        results = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent=HEADERS["User-Agent"],
                    extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"}
                )
                page.goto(self.RANKING_URL, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)

                # 이미지가 있는 링크 추출
                cards = page.query_selector_all("a[href*='/ko/plots/']")
                seen_ids = set()
                rank = 0
                for card in cards[:30]:
                    href = card.get_attribute("href") or ""
                    if "/profile" not in href:
                        continue
                    plot_id = href.split("/plots/")[1].split("/")[0] if "/plots/" in href else ""
                    if not plot_id or plot_id in seen_ids:
                        continue
                    seen_ids.add(plot_id)
                    rank += 1

                    img_el = card.query_selector("img")
                    img_url = img_el.get_attribute("src") if img_el else ""
                    img_alt = img_el.get_attribute("alt") if img_el else ""

                    # OG 이미지 가져오기 (프로필 페이지에서)
                    if not img_url or img_url.startswith("data:"):
                        try:
                            profile_page = browser.new_page()
                            profile_page.goto(f"{self.BASE}{href}", wait_until="domcontentloaded", timeout=15000)
                            og = profile_page.query_selector('meta[property="og:image"]')
                            img_url = og.get_attribute("content") if og else ""
                            profile_page.close()
                        except:
                            pass

                    # 텍스트 데이터
                    card_text = card.inner_text()
                    lines = [l.strip() for l in card_text.split("\n") if l.strip()]
                    name = img_alt.split("의 ")[-1] if "의 " in img_alt else lines[0] if lines else ""
                    desc = lines[1] if len(lines) > 1 else ""
                    chat_count = ""
                    for l in lines:
                        if "만" in l or "천" in l:
                            chat_count = l
                            break

                    local_path = download_image(img_url, image_dir, f"zeta_{plot_id[:8]}.png") if img_url else ""

                    results.append(Character(
                        id=f"zeta_{plot_id}",
                        name=name,
                        source="zeta",
                        description=desc,
                        tags=[],
                        interaction_count=parse_count(chat_count),
                        chat_count_str=chat_count,
                        url=f"{self.BASE}{href}",
                        image_url=img_url,
                        image_local=local_path,
                    ))
                    if rank >= cfg.top_n * 2:
                        break

                browser.close()
        except Exception as e:
            logger.error(f"[Zeta] 스크래핑 실패: {e}")
        logger.info(f"[Scraper] Zeta: {len(results)}개 수집")
        return results


class RofanScraper:
    """Rofan AI (rofan.ai) 랭킹 스크래퍼"""
    RANKING_URL = "https://rofan.ai/?tab=ranking&period=real_time&gender=all"

    def fetch(self, cfg, image_dir: Path) -> list[Character]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[Rofan] playwright 미설치 → 스킵")
            return []

        results = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent=HEADERS["User-Agent"],
                    extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"}
                )
                page.goto(self.RANKING_URL, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)

                imgs = page.query_selector_all("img[src*='rofan.ai/bot-assets']")
                rank = 0
                for img in imgs[:cfg.top_n * 2]:
                    img_url = img.get_attribute("src") or ""
                    name = img.get_attribute("alt") or ""
                    if not img_url or not name:
                        continue
                    rank += 1

                    card_text = ""
                    char_url = ""
                    try:
                        card_el = img.evaluate("el => el.closest('a')")
                        if card_el:
                            char_url = page.evaluate("el => el.href", card_el) or ""
                    except:
                        pass

                    # 인접 텍스트
                    try:
                        parent = page.evaluate("""img => {
                            const p = img.closest('a') || img.parentElement?.parentElement;
                            return p ? p.innerText : '';
                        }""", img)
                        card_text = parent or ""
                    except:
                        pass

                    lines = [l.strip() for l in card_text.split("\n") if l.strip()]
                    desc = next((l for l in lines if l != name and len(l) > 5 and not l.startswith("#")), "")
                    tags_str = next((l for l in lines if l.startswith("#")), "")
                    tags = [t.strip() for t in tags_str.split("#") if t.strip()]
                    chat_count = next((l for l in lines if "만" in l or "천" in l), "")

                    char_id = img_url.split("bot-assets/")[1].split("/")[0] if "bot-assets/" in img_url else f"rofan_{rank}"
                    local_path = download_image(img_url, image_dir, f"rofan_{char_id[:8]}.webp")

                    results.append(Character(
                        id=f"rofan_{char_id}",
                        name=name,
                        source="rofan",
                        description=desc,
                        tags=tags,
                        interaction_count=parse_count(chat_count),
                        chat_count_str=chat_count,
                        url=char_url,
                        image_url=img_url,
                        image_local=local_path,
                    ))

                browser.close()
        except Exception as e:
            logger.error(f"[Rofan] 스크래핑 실패: {e}")
        logger.info(f"[Scraper] Rofan: {len(results)}개 수집")
        return results


class CrackScraper:
    """Crack AI (crack.wrtn.ai) 인기 캐릭터 스크래퍼"""
    BASE_URL = "https://crack.wrtn.ai/characters"

    def fetch(self, cfg, image_dir: Path) -> list[Character]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[Crack] playwright 미설치 → 스킵")
            return []

        results = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent=HEADERS["User-Agent"],
                    extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"}
                )
                page.goto(self.BASE_URL, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)

                # 남성 인기 탭 클릭
                try:
                    page.click("text=남성 인기", timeout=5000)
                    page.wait_for_timeout(2000)
                except:
                    pass

                imgs = page.query_selector_all("img[src*='cloudfront']")
                rank = 0
                seen = set()
                for img in imgs:
                    img_url = img.get_attribute("src") or ""
                    if not img_url or "badge" in img_url or img_url in seen:
                        continue
                    seen.add(img_url)
                    name = img.get_attribute("alt") or ""
                    if "badge" in name:
                        continue
                    rank += 1

                    card_text = ""
                    char_url = ""
                    try:
                        parent_data = page.evaluate("""img => {
                            const p = img.closest('li') || img.closest('article') || img.parentElement?.parentElement?.parentElement;
                            const link = p?.querySelector('a') || p?.closest('a');
                            return { text: p ? p.innerText : '', url: link ? link.href : '' };
                        }""", img)
                        card_text = parent_data.get("text", "")
                        char_url = parent_data.get("url", "")
                    except:
                        pass

                    lines = [l.strip() for l in card_text.split("\n") if l.strip() and len(l.strip()) > 1]
                    if not name:
                        name = lines[0] if lines else f"캐릭터{rank}"
                    desc = next((l for l in lines if l != name and len(l) > 5 and not l.startswith("#") and not any(c.isdigit() for c in l[:3])), "")
                    tags_str = next((l for l in lines if "#" in l), "")
                    tags = [f"#{t.strip()}" for t in tags_str.replace("#", " #").split(" #") if t.strip()]
                    chat_count = next((l for l in lines if any(x in l for x in ["M", "만", "천", "k"])), "")

                    img_id = img_url.split("/")[-1].split("_")[0][:8]
                    local_path = download_image(img_url, image_dir, f"crack_{img_id}.webp")

                    results.append(Character(
                        id=f"crack_{img_id}",
                        name=name,
                        source="crack",
                        description=desc,
                        tags=tags,
                        interaction_count=parse_count(chat_count),
                        chat_count_str=chat_count,
                        url=char_url or self.BASE_URL,
                        image_url=img_url,
                        image_local=local_path,
                    ))
                    if rank >= cfg.top_n * 2:
                        break

                browser.close()
        except Exception as e:
            logger.error(f"[Crack] 스크래핑 실패: {e}")
        logger.info(f"[Scraper] Crack: {len(results)}개 수집")
        return results


SAMPLE_CHARACTERS = [
    Character(id="sample_1", name="전지적 독자 시점 - 김독자", source="sample",
              description="소설 속 세계에 들어온 유일한 독자. 서사와 메타 구조를 독보적인 캐릭터.",
              tags=["#판타지", "#메타픽션", "#아포칼립스"],
              interaction_count=7600000, chat_count_str="760만",
              image_url="https://img.rofan.ai/bot-assets/5878dc89-f6ec-4d86-8d37-4c5dabe02d0e/8e5848ae4b8eaaf6eab6f0dd684a8198.webp"),
    Character(id="sample_2", name="나 혼자만 레벨업 - 성진우", source="sample",
              description="죽음의 문턱에서 단독 플레이어가 된 헌터. 한국 판타지 웹소설 역대급 인기 캐릭터.",
              tags=["#판타지", "#헌터", "#성장"],
              interaction_count=9800000, chat_count_str="980만",
              image_url="https://img.rofan.ai/bot-assets/29b9de91-0ca9-4581-ae22-fa2805749a7c/4c995b0024b254d86e6af851e93a54ce.webp"),
    Character(id="sample_3", name="재혼 황후 - 나비에", source="sample",
              description="황후 자리를 스스로 버리고 적국 황제에게 청혼한 여성. 로맨스 판타지 정점.",
              tags=["#로맨스판타지", "#황후", "#역하렘"],
              interaction_count=8400000, chat_count_str="840만",
              image_url="https://img.rofan.ai/bot-assets/255c60ff-45c8-41a2-86a0-e2491e216c1c/8995090ac01a8776eb5aa88b145be8e9.webp"),
]


# 기존 코드 호환성을 위한 별칭
def scrape_all(cfg) -> list[Character]:
    """기존 호환성 래퍼"""
    scraper = Scraper(cfg)
    return scraper.fetch_all()


class Scraper:
    """메인 스크래퍼: 설정에 따라 소스별 수집"""

    def __init__(self, cfg):
        self.cfg = cfg
        # images 저장 경로: public/images/
        script_dir = Path(__file__).parent.parent
        self.image_dir = script_dir / "public" / "images"
        self.image_dir.mkdir(parents=True, exist_ok=True)

    def fetch_all(self) -> list[Character]:
        sources = getattr(self.cfg, "enabled_sources", ["zeta", "rofan", "crack", "sample"])
        all_chars = []

        if "rofan" in sources:
            logger.info("[Scraper] Rofan AI 스크래핑 시작...")
            try:
                chars = RofanScraper().fetch(self.cfg, self.image_dir)
                all_chars.extend(chars)
                logger.info(f"[Scraper] Rofan: {len(chars)}개 수집")
            except Exception as e:
                logger.error(f"[Scraper] Rofan 실패: {e}")

        if "crack" in sources:
            logger.info("[Scraper] Crack AI 스크래핑 시작...")
            try:
                chars = CrackScraper().fetch(self.cfg, self.image_dir)
                all_chars.extend(chars)
                logger.info(f"[Scraper] Crack: {len(chars)}개 수집")
            except Exception as e:
                logger.error(f"[Scraper] Crack 실패: {e}")

        if "zeta" in sources:
            logger.info("[Scraper] Zeta AI 스크래핑 시작...")
            try:
                chars = ZetaScraper().fetch(self.cfg, self.image_dir)
                all_chars.extend(chars)
                logger.info(f"[Scraper] Zeta: {len(chars)}개 수집")
            except Exception as e:
                logger.error(f"[Scraper] Zeta 실패: {e}")

        if not all_chars or "sample" in sources:
            if not all_chars:
                logger.warning("[Scraper] 실제 수집 데이터 없음 → 샘플 폴백")
            all_chars.extend(SAMPLE_CHARACTERS)
            logger.info(f"[Scraper] 샘플 {len(SAMPLE_CHARACTERS)}개 추가")

        logger.info(f"[Scraper] 총 {len(all_chars)}개 캐릭터 수집 완료")
        return all_chars
