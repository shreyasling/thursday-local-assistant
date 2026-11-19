from __future__ import annotations

import base64
import ipaddress
import os
import socket
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from assistant.agent.context import ExecutionContext
from assistant.config.loader import ToolConfig
from assistant.tools.base import BaseTool, ToolMetadata


# A single persistent Chromium profile keeps website cookies and sign-ins across
# tool calls and container restarts. The profile lives on the /data volume.
_PROFILE_DIR = Path(os.getenv("THURSDAY_BROWSER_PROFILE", "/data/browser-profile"))
_SCREENSHOT_DIR = Path(os.getenv("THURSDAY_BROWSER_SCREENSHOTS", "/data/browser-screenshots"))
_LOCK = threading.RLock()
_PLAYWRIGHT: Any | None = None
_CONTEXT: BrowserContext | None = None
_CURRENT_PAGE: Page | None = None
_MANUAL_CONTROL = False


def _require_agent_control() -> None:
    if _MANUAL_CONTROL:
        raise RuntimeError("Browser is in manual takeover mode. Wait until the user hands control back.")


def _validate_public_url(raw_url: str) -> str:
    value = raw_url.strip()
    if not value:
        raise ValueError("A URL is required.")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http:// and https:// websites are supported.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local and internal network addresses are blocked.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            }
        except OSError as exc:
            raise ValueError(f"Could not resolve website host: {host}") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Private, local, and non-public network destinations are blocked.")
    return value


def _guard_request(route: Any) -> None:
    """Block navigations and subresources that target local/private networks."""
    try:
        _validate_public_url(route.request.url)
    except ValueError:
        route.abort()
        return
    route.continue_()


def _browser() -> tuple[BrowserContext, Page]:
    global _PLAYWRIGHT, _CONTEXT, _CURRENT_PAGE
    if _CONTEXT is None:
        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        _PLAYWRIGHT = sync_playwright().start()
        _CONTEXT = _PLAYWRIGHT.chromium.launch_persistent_context(
            user_data_dir=str(_PROFILE_DIR),
            headless=True,
            viewport={"width": 1440, "height": 1000},
            accept_downloads=False,
            args=["--disable-dev-shm-usage"],
        )
        _CONTEXT.route("**/*", _guard_request)
        _CONTEXT.set_default_timeout(12000)
        pages = _CONTEXT.pages
        _CURRENT_PAGE = pages[0] if pages else _CONTEXT.new_page()
    if _CURRENT_PAGE is None or _CURRENT_PAGE.is_closed():
        _CURRENT_PAGE = _CONTEXT.new_page()
    return _CONTEXT, _CURRENT_PAGE


def _page_result(page: Page) -> dict[str, Any]:
    try:
        title = page.title()
    except Exception:
        title = ""
    return {
        "success": True,
        "url": page.url,
        "title": title,
    }


class BrowserOpenTool(BaseTool):
    metadata = ToolMetadata(
        name="browser_open",
        description="Open a public website in Thursday's persistent headless Chromium browser. Website sign-ins and cookies are retained between requests and container restarts. Only public HTTP(S) sites are allowed.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Public website URL, for example https://www.youtube.com"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        effect="mutation",
        parallel_safe=False,
        resource="browser",
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        _require_agent_control()
        url = _validate_public_url(str(arguments.get("url", "")))
        with _LOCK:
            _, page = _browser()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except PlaywrightTimeoutError:
                pass
            return _page_result(page)


class BrowserSearchTool(BaseTool):
    metadata = ToolMetadata(
        name="browser_search",
        description="Search Google or YouTube in Thursday's persistent Chromium browser and display the results page. Use engine google or youtube.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "engine": {"type": "string", "enum": ["google", "youtube"]},
            },
            "required": ["query", "engine"],
            "additionalProperties": False,
        },
        effect="mutation",
        parallel_safe=False,
        resource="browser",
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        _require_agent_control()
        query = str(arguments.get("query", "")).strip()
        engine = str(arguments.get("engine", "google")).lower()
        if not query:
            raise ValueError("A search query is required.")
        if engine not in {"google", "youtube"}:
            raise ValueError("Search engine must be google or youtube.")
        base = "https://www.youtube.com/results?search_query=" if engine == "youtube" else "https://www.google.com/search?q="
        url = _validate_public_url(base + quote_plus(query))
        with _LOCK:
            _, page = _browser()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except PlaywrightTimeoutError:
                pass
            return _page_result(page)


class BrowserClickTool(BaseTool):
    metadata = ToolMetadata(
        name="browser_click",
        description="Click an element in the current browser tab using a visible text label or a CSS selector. Prefer the text argument for ordinary buttons and links.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Visible text of the button or link to click."},
                "selector": {"type": "string", "description": "Optional CSS selector; use instead of text."},
            },
            "additionalProperties": False,
        },
        effect="mutation",
        parallel_safe=False,
        resource="browser",
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        _require_agent_control()
        text = str(arguments.get("text", "")).strip()
        _require_agent_control()
        selector = str(arguments.get("selector", "")).strip()
        if bool(text) == bool(selector):
            raise ValueError("Provide exactly one of text or selector.")
        with _LOCK:
            _, page = _browser()
            locator = page.locator(selector).first if selector else page.get_by_text(text, exact=False).first
            locator.click()
            return _page_result(page)


class BrowserTypeTool(BaseTool):
    metadata = ToolMetadata(
        name="browser_type",
        description="Fill a text field in the current browser tab. Use a CSS selector such as input[name=q] or textarea, and provide the text to enter. This only fills the field; submit separately with browser_click or a key press is not supported yet.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["selector", "text"],
            "additionalProperties": False,
        },
        effect="mutation",
        parallel_safe=False,
        resource="browser",
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        selector = str(arguments.get("selector", "")).strip()
        if not selector:
            raise ValueError("A CSS selector is required.")
        with _LOCK:
            _, page = _browser()
            page.locator(selector).first.fill(str(arguments.get("text", "")))
            return {"success": True, "url": page.url, "filled": selector}


class BrowserReadPageTool(BaseTool):
    metadata = ToolMetadata(
        name="browser_read_page",
        description="Read the current browser page's title, URL, visible text, and links. Use after opening or navigating a page to understand what is displayed.",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        effect="read",
        parallel_safe=False,
        resource="browser",
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        with _LOCK:
            _, page = _browser()
            body_text = page.locator("body").inner_text(timeout=10000)
            links = page.locator("a").evaluate_all(
                "(nodes) => nodes.slice(0, 40).map(a => ({text: (a.innerText || a.getAttribute('aria-label') || '').trim(), href: a.href})).filter(a => a.text && a.href)"
            )
            return {
                **_page_result(page),
                "text": body_text[:14000],
                "links": links,
            }


class BrowserScreenshotTool(BaseTool):
    metadata = ToolMetadata(
        name="browser_screenshot",
        description="Capture a screenshot of the current browser page and save it to persistent storage. Returns the screenshot path and current page details.",
        parameters={
            "type": "object",
            "properties": {"full_page": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
        effect="read",
        parallel_safe=False,
        resource="browser",
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        with _LOCK:
            _, page = _browser()
            _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = _SCREENSHOT_DIR / "latest.png"
            page.screenshot(path=str(path), full_page=bool(arguments.get("full_page", False)))
            return {**_page_result(page), "screenshot": str(path)}


class BrowserTabsTool(BaseTool):
    metadata = ToolMetadata(
        name="browser_tabs",
        description="List the tabs currently open in Thursday's persistent Chromium browser.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        effect="read",
        parallel_safe=False,
        resource="browser",
    )

    def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        with _LOCK:
            browser_context, _ = _browser()
            tabs = []
            for index, page in enumerate(browser_context.pages):
                try:
                    tabs.append({"index": index, "url": page.url, "title": page.title()})
                except Exception:
                    tabs.append({"index": index, "url": page.url, "title": ""})
            return {"success": True, "tabs": tabs}


def get_tools(config: ToolConfig) -> list[BaseTool]:
    return [
        BrowserOpenTool(),
        BrowserSearchTool(),
        BrowserClickTool(),
        BrowserTypeTool(),
        BrowserReadPageTool(),
        BrowserScreenshotTool(),
        BrowserTabsTool(),
    ]


def browser_ui_frame() -> dict[str, Any]:
    """Return a fresh frame and browser metadata for the authenticated live UI."""
    with _LOCK:
        if _CONTEXT is None or _CURRENT_PAGE is None or _CURRENT_PAGE.is_closed():
            return {"running": False, "tabs": []}
        page = _CURRENT_PAGE
        png = page.screenshot(type="png", animations="disabled")
        tabs = []
        for index, tab in enumerate(_CONTEXT.pages):
            try:
                tabs.append({"index": index, "title": tab.title(), "url": tab.url})
            except Exception:
                tabs.append({"index": index, "title": "", "url": ""})
        return {"running": True, "image": base64.b64encode(png).decode("ascii"), "url": page.url,
                "title": page.title(), "width": (page.viewport_size or {}).get("width", 1440),
                "height": (page.viewport_size or {}).get("height", 1000), "tabs": tabs}


def browser_ui_action(data: dict[str, Any]) -> dict[str, Any]:
    """Apply one bounded user takeover action to the persistent browser."""
    global _MANUAL_CONTROL
    action = str(data.get("action", ""))
    if action == "takeover":
        _MANUAL_CONTROL = bool(data.get("enabled"))
        return {"success": True, "manual_control": _MANUAL_CONTROL}
    with _LOCK:
        _, page = _browser()
        if action == "navigate":
            url = _validate_public_url(str(data.get("url", "")))
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except PlaywrightTimeoutError:
                pass
        elif action == "click":
            x, y = float(data.get("x", -1)), float(data.get("y", -1))
            width = (page.viewport_size or {}).get("width", 1440)
            height = (page.viewport_size or {}).get("height", 1000)
            if not (0 <= x <= width and 0 <= y <= height):
                raise ValueError("Click position is outside the browser viewport.")
            page.mouse.click(x, y)
        elif action == "scroll":
            dx, dy = float(data.get("dx", 0)), float(data.get("dy", 0))
            if abs(dx) > 2000 or abs(dy) > 2000:
                raise ValueError("Scroll amount is too large.")
            page.mouse.wheel(dx, dy)
        elif action == "key":
            key = str(data.get("key", ""))
            allowed = {"Enter", "Tab", "Escape", "Backspace", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown", " "}
            if key not in allowed and not (len(key) == 1 and key.isprintable()):
                raise ValueError("Unsupported keyboard key.")
            if len(key) == 1 and key.isprintable() and key != " ":
                page.keyboard.insert_text(key)
            else:
                page.keyboard.press("Space" if key == " " else key)
        elif action == "type":
            value = str(data.get("text", ""))
            if len(value) > 4000:
                raise ValueError("Text input is too long.")
            page.keyboard.insert_text(value)
        elif action == "back":
            page.go_back(wait_until="domcontentloaded", timeout=15000)
        elif action == "forward":
            page.go_forward(wait_until="domcontentloaded", timeout=15000)
        elif action == "reload":
            page.reload(wait_until="domcontentloaded", timeout=30000)
        else:
            raise ValueError("Unsupported browser control action.")
        return _page_result(page)
