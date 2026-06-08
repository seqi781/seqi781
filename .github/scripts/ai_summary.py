"""
AI Weekly Summary — pulls the last 7 days of public commits from GitHub
events, asks DeepSeek to write a short Chinese narrative, and rewrites the
AI-SUMMARY block inside README.md.

Required env:
  DEEPSEEK_API_KEY  - DeepSeek platform key
  GITHUB_TOKEN      - optional, raises rate limit on the events API
"""

import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

GH_USER = "seqi781"
DAYS = 7
README = pathlib.Path("README.md")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

START = "<!-- AI-SUMMARY-START -->"
END = "<!-- AI-SUMMARY-END -->"


def _gh_get(url: str):
    req = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"{GH_USER}-ai-summary")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_recent_commits(days: int = DAYS):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    commits = []
    for page in range(1, 4):
        try:
            events = _gh_get(
                f"https://api.github.com/users/{GH_USER}/events/public"
                f"?per_page=100&page={page}"
            )
        except urllib.error.HTTPError as e:
            print(f"events api page {page} failed: {e}", file=sys.stderr)
            break
        if not events:
            break
        keep_paging = False
        for ev in events:
            ts = datetime.strptime(
                ev["created_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
            if ts < since:
                continue
            keep_paging = True
            if ev.get("type") != "PushEvent":
                continue
            repo = ev["repo"]["name"].split("/", 1)[-1]
            for c in ev["payload"].get("commits", []):
                msg = c["message"].splitlines()[0].strip()
                if not msg or msg.lower().startswith("merge "):
                    continue
                commits.append({"repo": repo, "msg": msg[:200]})
        if not keep_paging:
            break
    return commits


def call_deepseek(commits):
    if not commits:
        return (
            "本周还没有公开的 commit 活动 —— 也许在憋大招，也许在啃论文，"
            "也许只是周末出去玩了一趟 🤫"
        )
    bullets = "\n".join(f"- [{c['repo']}] {c['msg']}" for c in commits[:80])
    prompt = (
        "下面是我过去 7 天的 GitHub commit 流水。"
        "请帮我写一段 150-250 字的中文「本周在做什么」总结，要求：\n"
        "1. 按主题聚类（如 AI 项目 / 学习笔记 / 工具 / 量化），不要逐条罗列。\n"
        "2. 用第一人称、口语自然，像在跟朋友讲，不要客套话。\n"
        "3. 末尾一句对下周的小展望或感想。\n"
        "4. 不要使用 markdown 标题，纯段落，不超过 2 段。\n\n"
        f"Commits:\n{bullets}\n"
    )
    body = json.dumps(
        {
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 600,
        }
    ).encode("utf-8")
    req = urllib.request.Request(DEEPSEEK_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {os.environ['DEEPSEEK_API_KEY']}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.load(r)
    return resp["choices"][0]["message"]["content"].strip()


def update_readme(summary: str, commit_count: int, repo_count: int):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block = (
        f"{START}\n"
        f"### 🤖 本周在做什么（AI 周报 · DeepSeek 生成）\n\n"
        f"> 更新于 {today}　·　过去 7 天 {commit_count} 个 commit，跨 {repo_count} 个仓库\n\n"
        f"{summary}\n\n"
        f"{END}"
    )
    text = README.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(START) + r".*?" + re.escape(END), re.DOTALL
    )
    if pattern.search(text):
        new_text = pattern.sub(block, text)
    else:
        new_text = text.rstrip() + "\n\n---\n\n" + block + "\n"
    README.write_text(new_text, encoding="utf-8")


def main():
    commits = fetch_recent_commits()
    repos = {c["repo"] for c in commits}
    summary = call_deepseek(commits)
    update_readme(summary, len(commits), len(repos))
    print(f"Wrote summary: {len(commits)} commits across {len(repos)} repos.")


if __name__ == "__main__":
    main()
