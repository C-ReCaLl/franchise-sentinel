#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
状态文件同步小工具：
- pull：从 GitHub 私有仓库拉取 pushed_history.json / daily_findings.json 到当前项目
- push：把当前项目里的这两个文件回写到 GitHub 私有仓库

适合在自动化沙箱里使用：每次运行前 pull，运行后 push，跨次保留去重和每日简报状态。

环境变量：
- STATE_REPO：例如 "C-ReCaLl/franchise-sentinel-state"
- GITHUB_TOKEN：具备 repo 作用域的 PAT
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

STATE_FILES = ["pushed_history.json", "daily_findings.json"]
BASE_DIR = Path(__file__).resolve().parent


def github_api(method: str, path: str, token: str, payload=None):
    url = f"https://api.github.com{path}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "franchise-sentinel-state-sync",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def pull(repo: str, token: str) -> int:
    failures = 0
    for name in STATE_FILES:
        try:
            data = github_api("GET", f"/repos/{repo}/contents/{name}", token)
            content = base64.b64decode(data["content"]).decode("utf-8")
            (BASE_DIR / name).write_text(content, encoding="utf-8")
            print(f"[pull] {name} <- {repo} ({len(content)} bytes)")
        except urllib.error.HTTPError as e:
            print(f"[pull] {name} 拉取失败：HTTP {e.code} {e.read().decode('utf-8', 'ignore')}")
            failures += 1
    return failures


def push(repo: str, token: str) -> int:
    failures = 0
    for name in STATE_FILES:
        local = BASE_DIR / name
        if not local.exists():
            print(f"[push] {name} 本地不存在，跳过")
            continue
        local_content = local.read_text(encoding="utf-8")
        # 先取远端 sha；不存在则首次创建
        sha = None
        try:
            current = github_api("GET", f"/repos/{repo}/contents/{name}", token)
            sha = current.get("sha")
            remote_content = base64.b64decode(current["content"]).decode("utf-8")
            if remote_content == local_content:
                print(f"[push] {name} 内容未变，跳过")
                continue
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"[push] {name} 取远端 sha 失败：HTTP {e.code}")
                failures += 1
                continue
        payload = {
            "message": f"sync {name}",
            "content": base64.b64encode(local_content.encode("utf-8")).decode("ascii"),
        }
        if sha:
            payload["sha"] = sha
        try:
            github_api("PUT", f"/repos/{repo}/contents/{name}", token, payload)
            print(f"[push] {name} -> {repo} ({len(local_content)} bytes)")
        except urllib.error.HTTPError as e:
            print(f"[push] {name} 写入失败：HTTP {e.code} {e.read().decode('utf-8', 'ignore')}")
            failures += 1
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["pull", "push"])
    args = parser.parse_args()

    repo = os.getenv("STATE_REPO", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not repo or not token:
        print("跳过状态同步：未配置 STATE_REPO 或 GITHUB_TOKEN 环境变量。")
        return 0

    if args.action == "pull":
        return 1 if pull(repo, token) else 0
    return 1 if push(repo, token) else 0


if __name__ == "__main__":
    sys.exit(main())
