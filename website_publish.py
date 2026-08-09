from __future__ import annotations

from pathlib import Path
import os
import re
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
CASE_STUDY_TITLE = "Demographic Weighting Exercise"
CASE_STUDY_SLUG = "demographic-weighting-exercise"
CASE_STUDY_DATE = "2026"
CASE_STUDY_LEDE = "A simulated survey study comparing post-stratification and raking to correct demographic imbalance while measuring bias and precision trade-offs."
WEBSITE_REPOSITORY = "ag-prudenzano/ag-prudenzano.github.io"
WEBSITE_REMOTE = f"https://github.com/{WEBSITE_REPOSITORY}.git"
WEBSITE_BRANCH = "main"
TEMPLATE_PAGE, SCRIPT_FILE, INDEX_FILE = "survey-response-quality-audit.html", "script.js", "index.html"
PUBLISH_TOKEN_ENV = "PORTFOLIO_PUBLISH_TOKEN"
TEMPLATE_TITLE = "Survey Response Quality Audit"
TEMPLATE_SLUG = "survey-response-quality-audit"
TEMPLATE_LEDE = "A simulated audit of 1,250 UK online survey responses using eight respondent-level quality checks to identify records for review or exclusion."


def run(args, *, cwd, check=True, env=None):
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True, env=env)


def source_repository_is_clean():
    return not run(["git", "status", "--porcelain", "--", "report.md", "data", "outputs", "figures"], cwd=ROOT).stdout.strip()


def authenticated_environment(temp_root):
    token = os.environ.get(PUBLISH_TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(f"Automatic website publishing needs a one-time secret named {PUBLISH_TOKEN_ENV}. The token must be able to write repository contents in {WEBSITE_REPOSITORY}.")
    askpass = temp_root / "git-askpass.sh"
    askpass.write_text('#!/bin/sh\ncase "$1" in\n  *Username*) printf "%s\\n" "x-access-token" ;;\n  *) printf "%s\\n" "$PORTFOLIO_PUBLISH_TOKEN" ;;\nesac\n', encoding="utf-8")
    askpass.chmod(askpass.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy(); env["GIT_ASKPASS"] = str(askpass); env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def update_publication_map(text):
    entry = f'  "{CASE_STUDY_TITLE}": {{\n    href: "{CASE_STUDY_SLUG}.html",\n    date: "{CASE_STUDY_DATE}",\n  }},'
    pattern = re.compile(rf'  "{re.escape(CASE_STUDY_TITLE)}": \{{\n    href: "[^"]+",\n    date: "[^"]+",\n  \}},')
    if pattern.search(text): return pattern.sub(entry, text, count=1)
    marker = "const publishedPortfolioStudies = {\n"
    if marker not in text: raise RuntimeError("Could not find the website publication map in script.js.")
    return text.replace(marker, marker + entry + "\n", 1)


def publish_website():
    if not (ROOT / "report.md").exists():
        print("Website publishing skipped: report.md does not exist yet."); return
    if not source_repository_is_clean():
        print("Website publishing skipped because generated case-study files have uncommitted changes."); return
    commit = run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="portfolio-website-") as temp:
        temp_root = Path(temp); website = temp_root / "website"; env = authenticated_environment(temp_root)
        clone = run(["git", "clone", "--depth", "1", "--branch", WEBSITE_BRANCH, WEBSITE_REMOTE, str(website)], cwd=temp_root, check=False, env=env)
        if clone.returncode: raise RuntimeError(f"Could not clone website repository: {(clone.stderr or clone.stdout).strip()}")
        name = run(["git", "config", "user.name"], cwd=ROOT, check=False).stdout.strip() or "AG Prudenzano"
        email = run(["git", "config", "user.email"], cwd=ROOT, check=False).stdout.strip() or "309410350+ag-prudenzano@users.noreply.github.com"
        run(["git", "config", "user.name", name], cwd=website); run(["git", "config", "user.email", email], cwd=website)
        script = website / SCRIPT_FILE; script.write_text(update_publication_map(script.read_text(encoding="utf-8")), encoding="utf-8")
        template = (website / TEMPLATE_PAGE).read_text(encoding="utf-8")
        page = template.replace(TEMPLATE_TITLE, CASE_STUDY_TITLE).replace(TEMPLATE_SLUG, CASE_STUDY_SLUG).replace(TEMPLATE_LEDE, CASE_STUDY_LEDE)
        (website / f"{CASE_STUDY_SLUG}.html").write_text(page, encoding="utf-8")
        index = website / INDEX_FILE; index.write_text(re.sub(r'script\.js\?v=[^"]+', f"script.js?v=published-{CASE_STUDY_SLUG}-{commit}", index.read_text(encoding="utf-8"), count=1), encoding="utf-8")
        if not run(["git", "status", "--porcelain"], cwd=website).stdout.strip():
            print("Website is already up to date."); return
        run(["git", "add", "--", SCRIPT_FILE, INDEX_FILE, f"{CASE_STUDY_SLUG}.html"], cwd=website)
        run(["git", "commit", "-m", f"Publish {CASE_STUDY_TITLE}"], cwd=website)
        push = run(["git", "push", "origin", WEBSITE_BRANCH], cwd=website, check=False, env=env)
        if push.returncode: raise RuntimeError(f"Could not push the website update: {(push.stderr or push.stdout).strip()}")
        print(f"Website updated and pushed to {WEBSITE_REPOSITORY}.")
