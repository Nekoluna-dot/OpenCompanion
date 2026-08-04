import sys, io, os, importlib.util as il
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "MCP"))

ok = []
fail = []

def check(name, fn):
    try:
        r = fn()
        ok.append(f"{name}: PASS -> {str(r)[:80]}")
    except Exception as e:
        fail.append(f"{name}: FAIL -> {e}")

def load(name, path):
    spec = il.spec_from_file_location(name, os.path.join(ROOT, path))
    m = il.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

uf = load("userfile", "MCP/userfile.py")
el = load("event_logger", "MCP/event_logger.py")
ti = load("topic_interest", "MCP/topic_interest.py")
em = load("emoji", "MCP/emoji.py")
we = load("weather", "MCP/weather.py")
lo = load("get_location", "MCP/get_location.py")
mv = load("movieinfo", "MCP/movieinfo-get-office.py")

# userfile
r = uf.add_record("testuser", "朋友A", "喜欢打篮球", "性格")
check("userfile.add_record", lambda: r)
check("userfile.query_records", lambda: uf.query_records("testuser", keyword="篮球"))
check("userfile.get_record", lambda: uf.get_record("testuser", r["id"]))
check("userfile.update_record", lambda: uf.update_record("testuser", r["id"], category="爱好"))
check("userfile.list_contacts", lambda: uf.list_contacts("testuser"))
check("userfile.list_categories", lambda: uf.list_categories("testuser"))
check("userfile.record_stats", lambda: uf.record_stats("testuser"))
check("userfile.delete_record", lambda: uf.delete_record("testuser", r["id"]))

# event_logger
e = el.add_event("testuser", "2026-08-01 10:00", "签合同")
check("event_logger.add_event", lambda: e)
check("event_logger.query_events", lambda: el.query_events("testuser", action="签合同"))
check("event_logger.get_event", lambda: el.get_event("testuser", e["id"]))
check("event_logger.update_event", lambda: el.update_event("testuser", e["id"], content="重要合同"))
check("event_logger.list_actions", lambda: el.list_actions("testuser"))
check("event_logger.list_users", lambda: el.list_users())
check("event_logger.delete_event", lambda: el.delete_event("testuser", e["id"]))

# topic_interest
t = ti.add_topic_interest("testuser", "动漫", 8, 6, "喜欢热血番")
check("topic.add_topic_interest", lambda: t)
check("topic.query_topic_interests", lambda: ti.query_topic_interests("testuser", min_interest=5))
check("topic.get_topic_interest", lambda: ti.get_topic_interest("testuser", t["id"]))
check("topic.update_topic_interest", lambda: ti.update_topic_interest("testuser", t["id"], favorability=7))
check("topic.list_topics", lambda: ti.list_topics("testuser"))
check("topic.topics_stats", lambda: ti.topics_stats("testuser"))
check("topic.delete_topic_interest", lambda: ti.delete_topic_interest("testuser", t["id"]))
check("topic.query_empty", lambda: ti.query_topic_interests("testuser"))

# emoji
check("emoji.list_emojis", lambda: em.list_emojis())

# weather / location / movie (network)
check("weather.get_weather", lambda: we.get_weather())
check("location.get_user_location", lambda: lo.get_user_location())
check("movie.get_movie_box_office", lambda: mv.get_movie_box_office(5))

print("===== RESULT =====")
for line in ok:
    print("PASS", line)
for line in fail:
    print("FAIL", line)
print(f"passed={len(ok)} failed={len(fail)}")
