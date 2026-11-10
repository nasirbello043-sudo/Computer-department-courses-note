"""One-time move of old-layout courses (courses/<course>/course.json + lesson files)
into the new layout (courses/html/<course>/course.json + pictures.json + info.json).
Safe to run again: courses already moved are skipped."""
import json, os, re, shutil

OLD_PART = re.compile(r"^(lesson|draft)-(\d+)\.json$")
SHARED = {"images", "html", "pdf", "summaries", "updates"}

def _read(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return default

def _write(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)

def _pictures(course):
    pics = []
    for i, les in enumerate(course.get("lessons", []), 1):
        for g in (les.get("data") or {}).get("diagrams", []):
            if g.get("type") == "image":
                pics.append({"lesson": i, "file": g.get("file"), "caption": g.get("caption"), "status": g.get("status", "ready")})
    return pics

def migrate_one(root, cid):
    old = os.path.join(root, cid)
    course = _read(os.path.join(old, "course.json"))
    if not course:
        return False
    for i, les in enumerate(course.get("lessons", [])):
        fname = les.get("file") or ""
        if fname:
            data = _read(os.path.join(old, fname))
            if data is not None:
                les["data"] = data
        dname = f"draft-{i + 1:02d}.json"
        draft = _read(os.path.join(old, dname))
        if draft is not None and not les.get("data"):
            les["draft"] = draft
    new = os.path.join(root, "html", cid)
    _write(os.path.join(new, "course.json"), course)
    _write(os.path.join(new, "pictures.json"), _pictures(course))
    lessons = course.get("lessons", [])
    _write(os.path.join(new, "info.json"), {"id": cid, "title": course.get("title"), "theme": course.get("theme"),
                                           "total": len(lessons), "ready": sum(1 for l in lessons if l.get("data"))})
    shutil.rmtree(old)  # the old folder is now fully inside the new one
    return True

def migrate(root="courses"):
    moved = []
    if not os.path.isdir(root):
        return moved
    for name in sorted(os.listdir(root)):
        if name in SHARED or not os.path.isdir(os.path.join(root, name)):
            continue
        if migrate_one(root, name):
            moved.append(name)
    return moved

if __name__ == "__main__":
    print("moved:", migrate())
