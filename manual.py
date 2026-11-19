"""Adds the courses you upload yourself to the site.
manual-upload.txt has one course per line with a format tag and a department tag:
    Introduction to Accounting [dept=business] [pdf]
    Motion [dept=physics] [html]
PDF courses: put courses/manual/pdf/<course-name>.pdf in the repo under manual/pdf/.
HTML courses: put the .html file in manual/html/<course-name>.html.
Runs after generate.py in the combine job. Writer-built courses are never changed by this step."""
import json, os, re, shutil

def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default

def save(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

def main():
    if not os.path.exists("manual-upload.txt"):
        print("manual: no manual-upload.txt, nothing to add")
        return
    index = load("courses/index.json", [])
    departments = load("courses/departments.json", [])
    # manual courses are rebuilt from the list each run; writer courses are kept exactly as they are
    writer_entries = [e for e in index if not e.get("manual")]
    writer_ids = {e["id"] for e in writer_entries}
    names = {d["id"]: d["name"] for d in departments}
    manual_entries = []
    for line in open("manual-upload.txt", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        flags = {f.strip().lower() for f in re.findall(r"\[([^\]]+)\]", line)}
        title = re.sub(r"\[[^\]]+\]", "", line).strip()
        fmt = "pdf" if "pdf" in flags else "html" if "html" in flags else None
        if fmt is None:
            print("manual: add [pdf] or [html] to the line:", title)
            continue
        depts = [d for f in flags if f.startswith("dept=") for d in f[5:].split("+") if d] or ["general"]
        cid = slug(title)
        if cid in writer_ids:
            print("manual: the id", cid, "is already used by a writer course, rename this course:", title)
            continue
        if fmt == "pdf":
            src = os.path.join("manual", "pdf", cid + ".pdf")
            dst = os.path.join("courses", "pdf", cid + ".pdf")
            url = None
        else:
            src = os.path.join("manual", "html", cid + ".html")
            dst = os.path.join("courses", "manual", cid + ".html")
            url = dst
        if not os.path.exists(src):
            print("manual: file not found:", src)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)
        for d in depts:
            if d not in names:
                names[d] = d.replace("-", " ").title()
                departments.append({"id": d, "name": names[d]})
        entry = {"id": cid, "title": title, "total": 1, "ready": 1,
                 "theme": {"hue": sum(map(ord, title)) % 360, "code": re.sub(r"[^A-Z0-9]", "", title.upper())[:4]},
                 "depts": depts, "kind": fmt, "manual": True}
        if url:
            entry["url"] = url
        manual_entries.append(entry)
        print("manual: added", title, "(" + fmt + ")", "under", ", ".join(names[d] for d in depts))
    save("courses/index.json", writer_entries + manual_entries)
    save("courses/departments.json", departments)
    print("manual: done,", len(manual_entries), "manual course(s) on the site")

if __name__ == "__main__":
    main()
