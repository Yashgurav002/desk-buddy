"""Today's Notion tasks (PRD F6). Stdlib only."""
import datetime
import json
import os

API = "https://api.notion.com/v1/databases/"
DONE_NAMES = ("done", "complete", "completed")


def load_config(home=None):
    token, db = os.environ.get("NOTION_TOKEN"), os.environ.get("NOTION_DB_ID")
    if token and db:
        return {"notion_token": token, "notion_db_id": db}
    home = home or os.environ.get("DESK_BUDDY_HOME") or os.path.join(os.path.expanduser("~"), ".desk-buddy")
    try:
        with open(os.path.join(home, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("notion_token") and cfg.get("notion_db_id"):
            return {"notion_token": cfg["notion_token"], "notion_db_id": cfg["notion_db_id"]}
    except Exception:
        pass
    return {}


def _call(opener, token, url, body=None):
    import urllib.request  # lazy: ~4 MB RSS, only paid when Notion is configured
    req = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "POST",
        headers={"Authorization": "Bearer " + token, "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
    )
    with opener(req, timeout=10) as r:
        return json.loads(r.read())


def _done_filter(props):
    """Filter that excludes done items, or None if the DB has no done property."""
    fallback = None
    for name, p in props.items():
        t = p.get("type")
        if t == "checkbox":
            f = {"property": name, "checkbox": {"equals": False}}
            if name.lower() in DONE_NAMES:
                return f
            fallback = fallback or f
        elif t in ("status", "select"):
            for opt in p.get(t, {}).get("options", []):
                if opt.get("name", "").lower() in DONE_NAMES:
                    return {"property": name, t: {"does_not_equal": opt["name"]}}
    return fallback


def fetch_today(token, db_id, today=None, opener=None):
    try:
        if opener is None:
            import urllib.request
            opener = urllib.request.urlopen
        today = (today or datetime.date.today()).isoformat()
        props = _call(opener, token, API + db_id)["properties"]
        date_prop = next(n for n, p in props.items() if p["type"] == "date")
        title_prop = next(n for n, p in props.items() if p["type"] == "title")
        filters = [{"property": date_prop, "date": {"on_or_before": today}}]
        done = _done_filter(props)
        if done:
            filters.append(done)
        res = _call(opener, token, API + db_id + "/query", {
            "filter": {"and": filters},
            "sorts": [{"property": date_prop, "direction": "ascending"}],
            "page_size": 5,
        })
        out = []
        for page in res.get("results", [])[:5]:
            rich = page["properties"][title_prop].get("title", [])
            out.append({"title": "".join(t.get("plain_text", "") for t in rich) or "Untitled",
                        "url": page.get("url", "")})
        return out
    except Exception:
        return []
