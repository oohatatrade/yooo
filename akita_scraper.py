from __future__ import annotations

import html
import re
import ssl
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener


BASE_URL = "https://cals05.pref.akita.lg.jp"
SEARCH_PAGE = f"{BASE_URL}/ecydeen/do/PPI/keiyaku"
SEARCH_ACTION = f"{BASE_URL}/ecydeen/do/PPI/keiyakuSearch"
TURN_ACTION = f"{BASE_URL}/ecydeen/do/PPI/keiyakuTurn"
ORDER_PAGE = f"{BASE_URL}/ecydeen/do/PPI/koukoku"
ORDER_SEARCH_ACTION = f"{BASE_URL}/ecydeen/do/PPI/koukokuSearch"
ORDER_TURN_ACTION = f"{BASE_URL}/ecydeen/do/PPI/koukokuTurn"

CONTRACT_HEADERS = [
    "契約公表番号",
    "入札方式",
    "工事・委託名称",
    "工事・委託場所",
    "工事・委託概要",
    "工事・業務種別",
    "請負者",
    "県内・県外",
    "契約金額",
    "開札日",
    "契約日",
    "公表課所",
    "調達区分",
]

ORDER_HEADERS = [
    "公開日",
    "入札方式",
    "工事・委託名称",
    "工事・委託場所",
    "工事・業務種別",
    "等級",
    "工事・委託概要",
    "予定価格",
    "入札執行課所",
    "調達区分",
]


@dataclass
class SearchParams:
    info_type: str = "contract"
    fiscal_year: str = "2026"
    procurement_category: str = ""
    keywords: list[str] | None = None
    location: str = ""
    contractor: str = ""
    max_pages: int = 0

    @property
    def procurement_category_label(self) -> str:
        return {"": "指定しない", "00": "工事", "01": "委託"}.get(self.procurement_category, self.procurement_category)

    @staticmethod
    def from_payload(payload: dict) -> "SearchParams":
        raw_keywords = payload.get("keywords", "")
        if isinstance(raw_keywords, str):
            keywords = [part.strip() for part in re.split(r"[\n,、]+", raw_keywords) if part.strip()]
        else:
            keywords = [str(part).strip() for part in raw_keywords if str(part).strip()]
        info_type = str(payload.get("infoType") or "contract")
        if info_type not in ("contract", "order"):
            info_type = "contract"
        return SearchParams(
            info_type=info_type,
            fiscal_year=str(payload.get("fiscalYear") or "2026"),
            procurement_category=str(payload.get("procurementCategory") or ""),
            keywords=keywords,
            location=str(payload.get("location") or "").strip(),
            contractor=str(payload.get("contractor") or "").strip(),
            max_pages=int(payload.get("maxPages") or 0),
        )


class ResultParser(HTMLParser):
    def __init__(self, headers: list[str]) -> None:
        super().__init__(convert_charrefs=False)
        self.headers = headers
        self.rows: list[dict] = []
        self._row_stack: list[dict] = []
        self._cell_stack: list[dict] = []
        self.result_count = 0
        self.total_pages = 1
        self._last_input_name = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): v or "" for k, v in attrs}
        if tag == "tr":
            self._row_stack.append({"cells": []})
        elif tag in ("td", "th") and self._row_stack:
            cell = {"text": [], "links": []}
            self._row_stack[-1]["cells"].append(cell)
            self._cell_stack.append(cell)
        elif tag == "a" and self._cell_stack:
            href = attr.get("href", "")
            if href:
                self._cell_stack[-1]["links"].append(urljoin(BASE_URL, href))
        elif tag == "input":
            name = attr.get("name", "")
            value = attr.get("value", "")
            if name == "resultCnt" and value.isdigit():
                self.result_count = int(value)
            elif name == "hiddentotalpages" and value.isdigit():
                self.total_pages = max(1, int(value))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell_stack:
            self._cell_stack.pop()
        elif tag == "tr" and self._row_stack:
            row = self._row_stack.pop()
            cells = []
            links = []
            for cell in row["cells"]:
                text = normalize("".join(cell["text"]))
                cells.append(text)
                links.append(cell["links"])
            if len(cells) >= len(self.headers):
                self.rows.append({"cells": cells, "links": links})

    def handle_data(self, data: str) -> None:
        if self._cell_stack:
            self._cell_stack[-1]["text"].append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.handle_data(html.unescape(f"&#{name};"))


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def decode_body(raw: bytes) -> str:
    for encoding in ("cp932", "shift_jis", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace")


def make_form(
    params: SearchParams,
    keyword: str = "",
    page: int | None = None,
    total_pages: int | None = None,
    result_count: int | None = None,
) -> dict[str, str]:
    form = {
        "nendo": params.fiscal_year,
        "chotatsuKbn": params.procurement_category,
        "kouhyoNo": "",
        "nyusatsu": "",
        "kousyu": "",
        "koujiName": keyword,
        "koujiArea": params.location,
        "koujiGaiyo": "",
        "kennaiCd": "",
        "ukeoiName": params.contractor,
        "keiyakuStartMoney": "",
        "keiyakuEndMoney": "",
        "kaisatsuStartYmd_ecnu_visible_element": "",
        "kaisatsuStartYmd": "",
        "kaisatsuEndYmd_ecnu_visible_element": "",
        "kaisatsuEndYmd": "",
        "keiyakuStartYmd_ecnu_visible_element": "",
        "keiyakuStartYmd": "",
        "keiyakuEndYmd_ecnu_visible_element": "",
        "keiyakuEndYmd": "",
        "sikouKasyo": "",
        "displayNum": "10",
        "resultCnt": str(result_count or 0),
    }
    if page:
        form["curPage"] = str(page)
    if total_pages:
        form["hiddentotalpages"] = str(total_pages)
    return form


def make_order_form(
    params: SearchParams,
    keyword: str = "",
    page: int | None = None,
    total_pages: int | None = None,
    result_count: int | None = None,
) -> dict[str, str]:
    form = {
        "chotatsuKbn": params.procurement_category,
        "nyusatsu": "",
        "kousyu": "",
        "toukyuuCD": "0",
        "koujiName": keyword,
        "koujiArea": params.location,
        "koujiGaiyo": "",
        "yoteikakakuStartMoney": "",
        "yoteikakakuEndMoney": "",
        "syukanka": "",
        "displayNum": "50",
        "resultCnt": str(result_count or 0),
    }
    if page:
        form["curPage"] = str(page)
    if total_pages:
        form["hiddentotalpages"] = str(total_pages)
    return form


class AkitaClient:
    def __init__(self) -> None:
        context = ssl.create_default_context()
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.context = context

    def get(self, url: str) -> str:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 AkitaProcurementExporter/1.0"})
        with self.opener.open(req, timeout=30) as res:
            return decode_body(res.read())

    def post(self, url: str, form: dict[str, str]) -> str:
        body = urlencode(form, encoding="cp932").encode("ascii")
        req = Request(
            url,
            data=body,
            headers={
                "User-Agent": "Mozilla/5.0 AkitaProcurementExporter/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": SEARCH_PAGE,
            },
            method="POST",
        )
        with self.opener.open(req, timeout=45) as res:
            return decode_body(res.read())


def parse_contract_results(markup: str, matched_keyword: str = "") -> tuple[list[dict], int, int]:
    parser = ResultParser(CONTRACT_HEADERS)
    parser.feed(markup)
    parsed: list[dict] = []
    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for row in parser.rows:
        cells = row["cells"]
        if cells[: len(CONTRACT_HEADERS)] == CONTRACT_HEADERS:
            continue
        if len(cells) < len(CONTRACT_HEADERS):
            continue
        candidate = cells[: len(CONTRACT_HEADERS)]
        if not candidate[0] or candidate[0] == "契約公表番号":
            continue
        pdf_url = ""
        if row["links"] and row["links"][0]:
            pdf_url = row["links"][0][0]
        parsed.append(
            {
                "contract_no": candidate[0],
                "bidding_method": candidate[1],
                "project_name": candidate[2],
                "location": candidate[3],
                "summary": candidate[4],
                "work_type": candidate[5],
                "contractor": candidate[6],
                "contractor_area": candidate[7],
                "contract_amount": candidate[8],
                "bid_open_date": candidate[9],
                "contract_date": candidate[10],
                "department": candidate[11],
                "procurement_category": candidate[12],
                "pdf_url": pdf_url,
                "matched_keyword": matched_keyword,
                "scraped_at": scraped_at,
            }
        )
    return parsed, parser.total_pages, parser.result_count


def parse_order_results(markup: str, matched_keyword: str = "") -> tuple[list[dict], int, int]:
    parser = ResultParser(ORDER_HEADERS)
    parser.feed(markup)
    parsed: list[dict] = []
    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for row in parser.rows:
        cells = row["cells"]
        if cells[: len(ORDER_HEADERS)] == ORDER_HEADERS:
            continue
        if len(cells) < len(ORDER_HEADERS):
            continue
        candidate = cells[: len(ORDER_HEADERS)]
        if not candidate[0] or candidate[0] == "公開日":
            continue
        detail_url = ""
        if len(row["links"]) > 2 and row["links"][2]:
            detail_url = row["links"][2][0]
        elif any(row["links"]):
            detail_url = next((links[0] for links in row["links"] if links), "")
        parsed.append(
            {
                "published_date": candidate[0],
                "bidding_method": candidate[1],
                "project_name": candidate[2],
                "location": candidate[3],
                "work_type": candidate[4],
                "grade": candidate[5],
                "summary": candidate[6],
                "estimated_price": candidate[7],
                "department": candidate[8],
                "procurement_category": candidate[9],
                "detail_url": detail_url,
                "matched_keyword": matched_keyword,
                "scraped_at": scraped_at,
            }
        )
    return parsed, parser.total_pages, parser.result_count


def scrape_one_keyword(client: AkitaClient, params: SearchParams, keyword: str) -> list[dict]:
    client.get(SEARCH_PAGE)
    first_html = client.post(SEARCH_ACTION, make_form(params, keyword))
    rows, total_pages, result_count = parse_contract_results(first_html, keyword)
    if result_count == 0 and not rows:
        return rows
    limit = params.max_pages if params.max_pages > 0 else total_pages
    limit = min(limit, total_pages)
    for page in range(2, limit + 1):
        page_html = client.post(TURN_ACTION, make_form(params, keyword, page, total_pages, result_count))
        page_rows, _, _ = parse_contract_results(page_html, keyword)
        rows.extend(page_rows)
    return rows


def scrape_one_order_keyword(client: AkitaClient, params: SearchParams, keyword: str) -> list[dict]:
    client.get(ORDER_PAGE)
    first_html = client.post(ORDER_SEARCH_ACTION, make_order_form(params, keyword))
    rows, total_pages, result_count = parse_order_results(first_html, keyword)
    if result_count == 0 and not rows:
        return rows
    limit = params.max_pages if params.max_pages > 0 else total_pages
    limit = min(limit, total_pages)
    for page in range(2, limit + 1):
        page_html = client.post(ORDER_TURN_ACTION, make_order_form(params, keyword, page, total_pages, result_count))
        page_rows, _, _ = parse_order_results(page_html, keyword)
        rows.extend(page_rows)
    return rows


def scrape_contracts(params: SearchParams) -> list[dict]:
    client = AkitaClient()
    keywords: Iterable[str] = params.keywords or [""]
    merged: dict[str, dict] = {}
    for keyword in keywords:
        source_rows = scrape_one_order_keyword(client, params, keyword) if params.info_type == "order" else scrape_one_keyword(client, params, keyword)
        for row in source_rows:
            key = (
                row.get("contract_no")
                or row.get("pdf_url")
                or row.get("detail_url")
                or f"{row.get('project_name')}:{row.get('contract_date') or row.get('published_date')}"
            )
            if key in merged and keyword:
                existing = merged[key].get("matched_keyword", "")
                parts = [part for part in [existing, keyword] if part]
                merged[key]["matched_keyword"] = " / ".join(dict.fromkeys(parts))
            else:
                merged[key] = row
    return list(merged.values())


if __name__ == "__main__":
    params = SearchParams()
    data = scrape_contracts(params)
    print(f"{len(data)} rows")
    for row in data[:3]:
        print(row)
