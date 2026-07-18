#!/usr/bin/env python3
"""
today.py

Pulls live GitHub stats for a user (repos, stars, followers, commits, total
lines of code added/removed) and writes them into light_mode.svg and
dark_mode.svg, replacing the {{PLACEHOLDER}} tokens in those files.

Requires an environment variable ACCESS_TOKEN: a GitHub Personal Access
Token with at least `read:user` and `repo` scopes (repo is needed to read
commit stats on private repos too; if you only care about public repos,
`public_repo` is enough).

Usage:
    ACCESS_TOKEN=ghp_xxx USERNAME=Batman1103 python today.py
"""

import os
import sys
import time
import requests

GITHUB_API = "https://api.github.com"
GRAPHQL_API = "https://api.github.com/graphql"

USERNAME = os.environ.get("USERNAME", "Batman1103")
TOKEN = os.environ.get("ACCESS_TOKEN")

if not TOKEN:
    print("ERROR: ACCESS_TOKEN environment variable is not set.", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github+json",
}


def graphql_query(query, variables=None):
    resp = requests.post(
        GRAPHQL_API,
        headers=HEADERS,
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def get_profile_summary():
    """Repo count, stars, followers, and total commit count via GraphQL."""
    query = """
    query($login: String!) {
      user(login: $login) {
        followers { totalCount }
        repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
          totalCount
          nodes {
            name
            stargazerCount
          }
        }
        contributionsCollection {
          totalCommitContributions
          restrictedContributionsCount
        }
      }
    }
    """
    data = graphql_query(query, {"login": USERNAME})
    user = data["user"]

    total_stars = sum(r["stargazerCount"] for r in user["repositories"]["nodes"])
    total_repos = user["repositories"]["totalCount"]
    followers = user["followers"]["totalCount"]
    # totalCommitContributions only covers the last year on some GitHub plans;
    # restrictedContributionsCount adds private contributions the token can see.
    commits = (
        user["contributionsCollection"]["totalCommitContributions"]
        + user["contributionsCollection"]["restrictedContributionsCount"]
    )

    repo_names = [r["name"] for r in user["repositories"]["nodes"]]
    return {
        "repos": total_repos,
        "stars": total_stars,
        "followers": followers,
        "commits": commits,
        "repo_names": repo_names,
    }


def get_loc_for_repo(owner, repo, retries=3):
    """
    Uses the /stats/contributors endpoint, which GitHub computes
    asynchronously (may return 202 the first time — retry after a short wait).
    Returns (additions, deletions) summed across all of this user's weeks.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/stats/contributors"
    for attempt in range(retries):
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 202:
            time.sleep(3)
            continue
        if resp.status_code != 200:
            return 0, 0
        contributors = resp.json()
        for c in contributors:
            author = c.get("author")
            if author and author.get("login", "").lower() == USERNAME.lower():
                additions = sum(w["a"] for w in c["weeks"])
                deletions = sum(w["d"] for w in c["weeks"])
                return additions, deletions
        return 0, 0
    return 0, 0


def get_total_loc(repo_names):
    total_add, total_del = 0, 0
    for name in repo_names:
        a, d = get_loc_for_repo(USERNAME, name)
        total_add += a
        total_del += d
    return total_add, total_del


def format_number(n):
    return f"{n:,}"


def fill_template(template_path, output_path, values):
    """Reads from a template (never modified) and writes the filled result
    to a separate output file, so re-running the script always has fresh
    placeholders to work with."""
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    for key, val in values.items():
        content = content.replace("{{" + key + "}}", str(val))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Wrote {output_path}")


def main():
    print(f"Fetching stats for {USERNAME}...")
    summary = get_profile_summary()

    print(f"Computing total lines of code across {len(summary['repo_names'])} repos "
          f"(this can take a bit)...")
    additions, deletions = get_total_loc(summary["repo_names"])

    values = {
        "REPOS": format_number(summary["repos"]),
        "COMMITS": format_number(summary["commits"]),
        "STARS": format_number(summary["stars"]),
        "FOLLOWERS": format_number(summary["followers"]),
        "LOC_ADDED": format_number(additions),
        "LOC_DELETED": format_number(deletions),
    }

    print("Stats:", values)

    fill_template("templates/light_mode_template.svg", "light_mode.svg", values)
    fill_template("templates/dark_mode_template.svg", "dark_mode.svg", values)


if __name__ == "__main__":
    main()
