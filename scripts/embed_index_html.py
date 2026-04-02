"""Inline public/*.html + styles.css (+ app.js for index) into api/index.py."""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
css = (root / "public" / "styles.css").read_text(encoding="utf-8")


def inline_css(html: str) -> str:
    return html.replace(
        '    <link rel="stylesheet" href="/styles.css" />',
        "    <style>\n" + css + "\n    </style>",
    )


# —— Main studio page ——
js = (root / "public" / "app.js").read_text(encoding="utf-8")
js = js.replace("escapeHtml", "esc").replace("escapeAttr", "escAttr")
index_src = (root / "public" / "index.html").read_text(encoding="utf-8")
index_src = inline_css(index_src)
index_src = index_src.replace(
    '    <script src="/app.js"></script>',
    '    <script type="module">\n' + js + "\n    </script>",
)
index_html = index_src

# —— Economy briefing (inline JS in HTML) ——
briefing_src = (root / "public" / "economy-briefing.html").read_text(encoding="utf-8")
economy_briefing_html = inline_css(briefing_src)

# —— Weather briefing (inline JS in HTML) ——
weather_src = (root / "public" / "weather-briefing.html").read_text(encoding="utf-8")
weather_briefing_html = inline_css(weather_src)

api_path = root / "api" / "index.py"
api = api_path.read_text(encoding="utf-8")

start = api.index("INDEX_HTML = ")
end = api.index('@app.get("/", response_class=HTMLResponse)', start)
block = (
    "INDEX_HTML = "
    + repr(index_html)
    + "\n\nECONOMY_BRIEFING_HTML = "
    + repr(economy_briefing_html)
    + "\n\nWEATHER_BRIEFING_HTML = "
    + repr(weather_briefing_html)
    + "\n\n"
)
api = api[:start] + block + api[end:]

if "def economy_briefing_html" not in api:
    needle = 'def index_html():\n    return INDEX_HTML\n\n\nclass SearchBody'
    insert = (
        'def index_html():\n    return INDEX_HTML\n\n\n'
        '@app.get("/economy-briefing", response_class=HTMLResponse)\n'
        "def economy_briefing_html():\n"
        "    return ECONOMY_BRIEFING_HTML\n\n\n"
        "class SearchBody"
    )
    if needle not in api:
        raise SystemExit("Could not find insertion point for economy_briefing route")
    api = api.replace(needle, insert, 1)

if "def weather_briefing_html" not in api:
    needle = 'def economy_briefing_html_slash():\n    # Some deployments may preserve trailing-slash paths without redirect.\n    return ECONOMY_BRIEFING_HTML\n\n\nclass SearchBody'
    insert = (
        'def economy_briefing_html_slash():\n'
        "    # Some deployments may preserve trailing-slash paths without redirect.\n"
        "    return ECONOMY_BRIEFING_HTML\n\n\n"
        '@app.get("/weather-briefing", response_class=HTMLResponse)\n'
        "def weather_briefing_html():\n"
        "    return WEATHER_BRIEFING_HTML\n\n\n"
        '@app.get("/weather-briefing/", response_class=HTMLResponse)\n'
        "def weather_briefing_html_slash():\n"
        "    return WEATHER_BRIEFING_HTML\n\n\n"
        "class SearchBody"
    )
    if needle not in api:
        raise SystemExit("Could not find insertion point for weather_briefing route")
    api = api.replace(needle, insert, 1)

api_path.write_text(api, encoding="utf-8", newline="\n")
print("OK, INDEX_HTML length:", len(index_html))
print("OK, ECONOMY_BRIEFING_HTML length:", len(economy_briefing_html))
print("OK, WEATHER_BRIEFING_HTML length:", len(weather_briefing_html))
