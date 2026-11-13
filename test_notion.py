import datetime
import io
import json
import os
import tempfile
import urllib.error

import notion

SCHEMA = {"properties": {
    "Name": {"type": "title", "title": {}},
    "Due": {"type": "date", "date": {}},
    "Status": {"type": "status", "status": {"options": [{"name": "Todo"}, {"name": "Done"}]}},
}}
PAGES = {"results": [
    {"url": f"https://notion.so/p{i}",
     "properties": {"Name": {"title": [{"plain_text": f"Task {i}"}]}}} for i in range(7)]}


class Fake:
    def __init__(self, schema=SCHEMA, error=None):
        self.schema, self.error, self.reqs = schema, error, []

    def __call__(self, req, timeout=None):
        self.reqs.append(req)
        if self.error:
            raise self.error
        body = PAGES if req.full_url.endswith("/query") else self.schema
        return io.BytesIO(json.dumps(body).encode())


# happy path
f = Fake()
items = notion.fetch_today("tok", "db1", today=datetime.date(2026, 11, 13), opener=f)
assert len(items) == 5, items
assert items[0] == {"title": "Task 0", "url": "https://notion.so/p0"}
assert f.reqs[0].get_header("Notion-version") == "2022-06-28"
assert f.reqs[0].get_header("Authorization") == "Bearer tok"
q = json.loads(f.reqs[1].data)
assert {"property": "Due", "date": {"on_or_before": "2026-11-13"}} in q["filter"]["and"]
assert {"property": "Status", "status": {"does_not_equal": "Done"}} in q["filter"]["and"]

# checkbox done property
cb = {"properties": {"Name": {"type": "title"}, "When": {"type": "date"}, "Done": {"type": "checkbox"}}}
f = Fake(cb)
notion.fetch_today("tok", "db1", opener=f)
assert {"property": "Done", "checkbox": {"equals": False}} in json.loads(f.reqs[1].data)["filter"]["and"]

# missing date property
f = Fake({"properties": {"Name": {"type": "title"}}})
assert notion.fetch_today("tok", "db1", opener=f) == []
assert len(f.reqs) == 1  # never queried

# HTTP error and network error
err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"{}"))
assert notion.fetch_today("bad", "db1", opener=Fake(error=err)) == []
assert notion.fetch_today("t", "db1", opener=Fake(error=urllib.error.URLError("down"))) == []

# config: env wins, then file, else {}
saved = {k: os.environ.pop(k, None) for k in ("NOTION_TOKEN", "NOTION_DB_ID")}
try:
    with tempfile.TemporaryDirectory() as home:
        assert notion.load_config(home) == {}
        with open(os.path.join(home, "config.json"), "w") as fh:
            json.dump({"notion_token": "ft", "notion_db_id": "fd"}, fh)
        assert notion.load_config(home) == {"notion_token": "ft", "notion_db_id": "fd"}
        os.environ["NOTION_TOKEN"], os.environ["NOTION_DB_ID"] = "et", "ed"
        assert notion.load_config(home) == {"notion_token": "et", "notion_db_id": "ed"}
        with open(os.path.join(home, "config.json"), "w") as fh:
            fh.write("not json")
        del os.environ["NOTION_TOKEN"], os.environ["NOTION_DB_ID"]
        assert notion.load_config(home) == {}
finally:
    for k, v in saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v

print("test_notion: OK")
