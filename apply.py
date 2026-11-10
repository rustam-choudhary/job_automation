"""
Scheduled job-application helper (final version).

Reads links from links.txt, opens each in a browser (Playwright), fills the
form using profile.yaml, uploads your resume, and submits ONLY if every
required field was filled. Anything it can't handle (CAPTCHA, login wall,
unknown required field, no form found) is logged to review.csv.

DRY_RUN is read from the DRY_RUN environment variable (set in apply.yml).
"""
import csv, datetime, os, pathlib, re
import yaml
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = pathlib.Path(__file__).parent
HEADLESS = True
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"
MAX_PER_RUN = 10

profile = yaml.safe_load((BASE / "profile.yaml").read_text())
RESUME = str(BASE / profile["resume_path"])

# label keyword -> profile key. Extend as you meet new forms.
FIELD_MAP = {
    r"first\s*name": "first_name",
    r"last\s*name|surname": "last_name",
    r"full\s*name|^name": "full_name",
    r"e-?mail": "email",
    r"phone|mobile": "phone",
    r"linkedin": "linkedin",
    r"github|portfolio|website": "portfolio",
    r"current.*(company|employer)": "current_company",
    r"current.*(title|role)": "current_title",
    r"total.*experience|years.*experience": "years_experience",
    r"notice": "notice_period",
    r"current.*(ctc|salary|compensation)": "current_ctc",
    r"expected.*(ctc|salary|compensation)": "expected_ctc",
    r"(current|present).*location|city": "city",
}


def log_row(path, row):
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "url", "status", "note"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), *row])


def label_for(ctx, el):
    try:
        return (el.evaluate(
            """e => (e.labels && e.labels[0] && e.labels[0].innerText) ||
                    e.getAttribute('aria-label') || e.placeholder || e.name || ''""") or "").lower()
    except Exception:
        return ""


def fill_form(ctx):
    """ctx is a Page or a Frame. Returns (unfilled_required_labels, filled_count)."""
    unfilled, filled = [], 0
    for el in ctx.query_selector_all(
            "input:not([type=hidden]):not([type=file]):not([type=submit]), textarea"):
        if not el.is_visible() or el.input_value():
            continue
        label = label_for(ctx, el)
        key = next((k for pat, k in FIELD_MAP.items() if re.search(pat, label)), None)
        if key and profile["answers"].get(key):
            el.fill(str(profile["answers"][key]))
            filled += 1
        elif el.get_attribute("required") is not None or "*" in label:
            unfilled.append(label or "unknown field")
    for fi in ctx.query_selector_all("input[type=file]"):
        try:
            fi.set_input_files(RESUME)
            filled += 1
        except Exception:
            pass
    return unfilled, filled


def apply(page, url):
    page.goto(url, timeout=45000)
    page.wait_for_load_state("domcontentloaded")
    body = page.inner_text("body").lower()
    if any(w in body for w in ["captcha", "verify you are human",
                               "sign in to apply", "log in to apply"]):
        return "REVIEW", "captcha or login required"

    # click an Apply button if we landed on a job description page
    for name in ["Apply now", "Apply for this job", "Apply"]:
        btn = page.get_by_role("button", name=re.compile(name, re.I)).first
        link = page.get_by_role("link", name=re.compile(name, re.I)).first
        target = btn if btn.count() else link if link.count() else None
        if target:
            target.click()
            page.wait_for_load_state("domcontentloaded")
            break

    page.wait_for_timeout(4000)
    # many company sites embed a Greenhouse/Lever form in an iframe
    ctx = next((f for f in page.frames
                if f != page.main_frame and ("greenhouse" in f.url or "lever" in f.url)),
               page)

    unfilled, filled = fill_form(ctx)
    if filled == 0:
        return "REVIEW", "no form fields found (embedded form or login)"
    if unfilled:
        return "REVIEW", "required fields not filled: " + ", ".join(unfilled[:6])

    if DRY_RUN:
        shots = BASE / "shots"
        shots.mkdir(exist_ok=True)
        name = re.sub(r"\W+", "_", url)[-60:]
        page.screenshot(path=str(shots / f"{name}.png"), full_page=True)
        return "DRY_RUN", "form filled, not submitted"

    submit = ctx.get_by_role("button", name=re.compile(r"submit|send application", re.I)).first
    if not submit.count():
        return "REVIEW", "no submit button found"
    submit.click()
    page.wait_for_timeout(5000)
    text = ctx.inner_text("body").lower()
    if any(w in text for w in ["thank you", "application has been submitted",
                               "application submitted", "received your application"]):
        return "APPLIED", "confirmed"
    return "REVIEW", "clicked submit but no confirmation seen"


def main():
    links_file, done_file = BASE / "links.txt", BASE / "done.txt"
    done = set(done_file.read_text().split()) if done_file.exists() else set()
    todo = [l.strip() for l in links_file.read_text().splitlines()
            if l.strip() and not l.startswith("#") and l.strip() not in done][:MAX_PER_RUN]
    if not todo:
        print("no new links")
        return
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        for url in todo:
            ctx = browser.new_context()
            page = ctx.new_page()
            try:
                status, note = apply(page, url)
            except PWTimeout:
                status, note = "REVIEW", "timeout"
            except Exception as e:
                status, note = "ERROR", str(e)[:200]
            log_row(BASE / "review.csv", [url, status, note])
            if status in ("APPLIED", "REVIEW", "DRY_RUN"):
                with open(done_file, "a") as f:
                    f.write(url + "\n")
            print(status, url, note)
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
