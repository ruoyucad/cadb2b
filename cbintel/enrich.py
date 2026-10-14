"""Find suppliers' websites and public sales contacts (free sources only).

For each supplier:
  1. Candidate sites: DuckDuckGo's HTML results (directories filtered out) plus
     domains guessed from the company name (nitam.ca, nitamsolutions.com, ...).
  2. Verify: a candidate is accepted only if its pages mention the company name
     and, ideally, its postal code or city from the contract data.
  3. Extract: public emails and phone numbers from the home page and its
     contact / about pages.

Only published business contacts are collected, robots.txt is respected and
requests are rate limited. Results go to hist.supplier_contact (data/history.duckdb)
because they cannot be re-downloaded like the open data.
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import duckdb
import requests

from .build import DB_PATH
from .history import attach

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 cbintel/0.1")
TIMEOUT = (10, 20)

# Result domains that are directories / social networks, never the company's own site.
NOT_COMPANY_SITES = re.compile(
    r"(dnb|firmania|chamberofcommerce|linkedin|facebook|instagram|twitter|x\.com|youtube|yelp|"
    r"canada411|yellowpages|pagesjaunes|bbb\.org|opencorporates|bizapedia|zoominfo|wikipedia|"
    r"canadacompanyregistry|buyandsell|canadabuys|canada\.ca|gc\.ca|google|mapquest|indeed|glassdoor|"
    r"crunchbase|bloomberg|rocketreach|signalhire|apollo\.io|cylex|n49|houzz|tiktok|pinterest|"
    r"opengovca|companieslist|canadianbusinessdirectory|411\.ca|bing\.com|duckduckgo|amazon|"
    r"govtribe|ic\.gc|registreentreprises|req\.gouv|infobel|hamster|companylisting|ottawasted|"
    r"showmelocal|yellowpages|manta|hotfrog|brownbook|tuugo|ca\.kompass|cybo|allbiz|bizapedia|"
    r"profilecanada|canpages|goldbook|ourbis|dexknows|foursquare)", re.I)

# Words too common to identify a company on their own.
GENERIC = set("""AND OF THE CANADA CANADIAN SOLUTIONS SOLUTION GROUP SERVICES SERVICE SYSTEMS SYSTEM
INTERNATIONAL TECHNOLOGIES TECHNOLOGY INDUSTRIES ENTERPRISES BUSINESS OFFICE FURNITURE INTERIORS
SUPPLY SUPPLIES PRODUCTS DIVISION OF NORTH NATIONAL GLOBAL HOLDINGS MANAGEMENT DESIGN DESIGNS
INC LTD LIMITED CORP ET DE DES DU LA LE LES""".split())

# Phone area codes by province, as weak evidence a site belongs to a company located there.
AREA_CODES = {
    "ON": "416 647 437 905 289 365 613 343 705 249 519 226 548 807 683 742 753",
    "QC": "514 438 450 579 418 581 819 873 367 354 263 468",
    "BC": "604 778 236 250 672", "AB": "403 587 825 780 368", "MB": "204 431 584",
    "SK": "306 639 474", "NS": "902 782", "PE": "902 782", "NB": "506 428", "NL": "709 879",
}
PROVINCE = {"ONTARIO": "ON", "QUEBEC": "QC", "QUÉBEC": "QC", "BRITISH COLUMBIA": "BC", "ALBERTA": "AB",
            "MANITOBA": "MB", "SASKATCHEWAN": "SK", "NOVA SCOTIA": "NS", "PRINCE EDWARD ISLAND": "PE",
            "NEW BRUNSWICK": "NB", "NEWFOUNDLAND AND LABRADOR": "NL"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})(?!\d)")
CONTACT_LINK = re.compile(r"contact|nous-joindre|joindre|contactez|about|a-propos|propos", re.I)
# Company-wide inboxes. Personal staff addresses are left out on purpose: the product
# sells company contacts, and role addresses are the safest to use under CASL.
ROLE_EMAIL = re.compile(r"^(info|sales|ventes|vente|contact|customer|service|support|orders?|commandes?|"
                        r"admin|office|bureau|reception|hello|bonjour|inquir|enquir|quotes?|soumission|"
                        r"general|marketing|purchasing|achats|bids?|tenders?|gov|government)", re.I)
JUNK_EMAIL = re.compile(r"example\.|sentry|wixpress|\.(png|jpe?g|gif|svg|webp)$|^u00|domain\.com|email\.com", re.I)


class Fetcher:
    """requests.Session with robots.txt checks and a per-host delay."""

    def __init__(self, delay: float = 1.0):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.delay, self.last, self.robots = delay, {}, {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        root = f"{p.scheme}://{p.netloc}"
        if root not in self.robots:
            rp = RobotFileParser()
            try:
                r = self.s.get(root + "/robots.txt", timeout=TIMEOUT)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])
            self.robots[root] = rp
        return self.robots[root].can_fetch(UA, url)

    def get(self, url: str, check_robots: bool = True, **kw) -> requests.Response | None:
        host = urlparse(url).netloc
        wait = self.delay - (time.time() - self.last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        try:
            if check_robots and not self.allowed(url):
                return None
            r = self.s.get(url, timeout=TIMEOUT, **kw)
            return r if r.status_code == 200 and "html" in r.headers.get("Content-Type", "html") else None
        except requests.RequestException:
            return None
        finally:
            self.last[host] = time.time()


def page_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", raw)))


def root_domain(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def search(f: Fetcher, query: str, tries: int = 4) -> list[str]:
    """DuckDuckGo HTML results; it sometimes answers 202 (bot check), so back off."""
    for i in range(tries):
        try:
            r = f.s.post("https://html.duckduckgo.com/html/", data={"q": query}, timeout=TIMEOUT)
        except requests.RequestException:
            r = None
        if r is not None and r.status_code == 200:
            links = [html.unescape(u) for u in re.findall(r'class="result__a" href="([^"]+)"', r.text)]
            return [u for u in links if u.startswith("http") and not NOT_COMPANY_SITES.search(root_domain(u))]
        time.sleep(5 * (i + 1))
    return []


def tokens(key: str) -> list[str]:
    return [t for t in key.split() if t not in GENERIC and len(t) >= 3]


def guess_domains(key: str) -> list[str]:
    words = [w.lower() for w in key.split() if w not in {"AND", "THE", "OF"}]
    distinct = [w.lower() for w in tokens(key)]
    stems = {"".join(words), "".join(words[:2]), *(distinct[:1])}
    return [f"{s}.{tld}" for s in stems if len(s) >= 4 for tld in ("ca", "com")]


def score_site(text: str, domain: str, s: dict) -> tuple[int, list[str]]:
    up = text.upper()
    flat = re.sub(r"[^A-Z0-9]", "", up)
    why, score = [], 0
    toks = tokens(s["supplier_key"])
    if toks and any(t.lower() in domain.replace("-", "") for t in toks if len(t) >= 4):
        score += 2; why.append("domain")
    if s["supplier_key"].replace(" ", "") in flat:
        score += 3; why.append("name")
    elif toks and all(t in up for t in toks):
        score += 2; why.append("name tokens")
    pc = (s.get("postal_code") or "").replace(" ", "").upper()
    if len(pc) == 6 and pc in flat:
        score += 3; why.append("postal code")
    if s.get("city") and s["city"].upper() in up:
        score += 1; why.append("city")
    prov = (s.get("province") or "").upper().strip()
    codes = AREA_CODES.get(PROVINCE.get(prov, prov), "").split()
    if codes and any(a in codes for a, _b, _c in PHONE.findall(text)):
        score += 1; why.append("area code")
    return score, why


def contacts(f: Fetcher, home_url: str, home_html: str) -> tuple[list[str], list[str], str | None]:
    pages = [(home_url, home_html)]
    links = re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', home_html, re.I | re.S)
    seen, contact_page = {home_url}, None
    for href, label in links:
        url = urljoin(home_url, html.unescape(href))
        if root_domain(url) != root_domain(home_url) or url in seen:
            continue
        if CONTACT_LINK.search(href) or CONTACT_LINK.search(page_text(label)):
            seen.add(url)
            r = f.get(url)
            if r is not None:
                pages.append((url, r.text))
                contact_page = contact_page or (url if re.search("contact|joindre", url, re.I) else None)
        if len(pages) >= 4:
            break
    emails, phones = [], []
    dom = root_domain(home_url)
    for _url, raw in pages:
        found = re.findall(r'mailto:([^"?\'>\s]+)', raw, re.I) + EMAIL.findall(page_text(raw))
        for e in found:
            e = html.unescape(e).strip(".").lower()
            if EMAIL.fullmatch(e) and not JUNK_EMAIL.search(e) and e not in emails:
                emails.append(e)
        for a, b, c in PHONE.findall(page_text(raw)):
            p = f"{a}-{b}-{c}"
            if p not in phones:
                phones.append(p)
    emails = [e for e in emails if ROLE_EMAIL.match(e)]
    emails.sort(key=lambda e: (not e.endswith(dom), not re.match(r"(sales|ventes|info|contact)", e)))
    return emails[:3], phones[:3], contact_page


def verified(why: list[str]) -> bool:
    """Directories repeat a company's name and postal code, so the domain itself must
    carry the company's name, plus one more piece of evidence (a one-word name like
    "Asokan" also matches unrelated sites)."""
    return "domain" in why and bool({"name", "postal code", "city", "area code"} & set(why))


def find_contact(f: Fetcher, s: dict) -> dict:
    name = s["operating_name"] or s["display_name"]
    candidates: list[str] = []
    hits = search(f, f'{name} {s.get("city") or ""}'.strip())
    for u in hits[:4]:
        home = f"{urlparse(u).scheme}://{urlparse(u).netloc}/"
        for c in (home, u):          # the site root, then the exact page that was found
            if c not in candidates:
                candidates.append(c)
    for d in guess_domains(s["supplier_key"]):
        for home in (f"https://www.{d}/", f"https://{d}/"):
            if home not in candidates:
                candidates.append(home)

    best = None
    for home in candidates[:10]:
        r = f.get(home) or (f.get("http://" + home[8:]) if home.startswith("https://") else None)
        if r is None:
            continue
        final = r.url if r.url.endswith("/") else r.url.rsplit("/", 1)[0] + "/"
        sc, why = score_site(page_text(r.text), root_domain(final), s)
        if best is None or (verified(why), sc) > (verified(best[1]), best[0]):
            best = (sc, why, final, r.text)
        if verified(why) and sc >= 6:
            break
    out = {"supplier_key": s["supplier_key"], "display_name": s["display_name"], "website": None,
           "emails": None, "phones": None, "contact_page": None, "match_score": 0, "match_reason": None}
    if best and verified(best[1]):
        sc, why, url, raw = best
        emails, phones, cpage = contacts(f, url, raw)
        out.update(website=f"{urlparse(url).scheme}://{urlparse(url).netloc}/", emails=", ".join(emails) or None, phones=", ".join(phones) or None,
                   contact_page=cpage, match_score=sc, match_reason=" + ".join(why))
    else:
        # Nothing verified (site down, or pages don't mention the company). Keep the
        # top search hit whose domain carries the company name, for a manual check.
        toks = [t.lower() for t in tokens(s["supplier_key"]) if len(t) >= 4]
        guess = next((u for u in hits if toks and any(t in root_domain(u).replace("-", "") for t in toks)), None)
        reason = "not verified" + (f" ({' + '.join(best[1])})" if best and best[1] else "")
        out.update(match_score=best[0] if best else 0,
                   match_reason=reason + (f"; candidate: {guess}" if guess else ""))
    return out


def enrich(segments: list[str], top_n: int = 50, refresh: bool = False, db_path=DB_PATH) -> None:
    con = duckdb.connect(str(db_path), read_only=True)
    seg_list = ",".join(f"'{s}'" for s in segments)
    rows = con.execute(f"""
        SELECT DISTINCT d.supplier_key, d.display_name, d.operating_name, d.city, d.province, d.postal_code
        FROM mart_supplier_leaderboard l JOIN dim_supplier d USING (supplier_id)
        WHERE l.segment IN ({seg_list}) AND l.rank_in_segment <= {int(top_n)}""").fetchall()
    con.close()
    cols = ["supplier_key", "display_name", "operating_name", "city", "province", "postal_code"]
    targets = [dict(zip(cols, r)) for r in rows]

    hist = duckdb.connect()
    attach(hist)
    done = {r[0] for r in hist.execute("SELECT supplier_key FROM hist.supplier_contact").fetchall()}
    todo = [t for t in targets if refresh or t["supplier_key"] not in done]
    print(f"[enrich] {len(targets)} suppliers, {len(todo)} to look up")

    f = Fetcher()
    for i, s in enumerate(todo, 1):
        res = find_contact(f, s)
        hist.execute("""INSERT OR REPLACE INTO hist.supplier_contact VALUES
            ($supplier_key, $display_name, $website, $emails, $phones, $contact_page,
             $match_score, $match_reason, 'free-search', $checked_at)""",
                     {**res, "checked_at": datetime.now()})
        print(f"  {i:>3}/{len(todo)} {s['display_name'][:40]:<40} {res['website'] or '-':<35} {res['emails'] or ''}")
    hist.close()
