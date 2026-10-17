import os
import httpx
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO") # format: owner/repo

async def verify_task_on_github(task_key: str, github_username: str = None, keyword: str = None) -> dict:
    """
    Checks GitHub commits for a given task key or keyword.
    Returns verification status, commit hash, message, URL, and author.
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/commits"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params={"per_page": 20})
        
        if response.status_code != 200:
            return {"verified": False, "error": f"GitHub API error: {response.status_code} - {response.text}"}
        
        commits = response.json()
        
        for commit in commits:
            message = commit["commit"]["message"]
            author_login = commit.get("author")
            author_name = commit["commit"]["author"]["name"]
            commit_url = commit["html_url"]
            commit_sha = commit["sha"]
            
            # Check if task key or keyword matches
            key_match = task_key.lower() in message.lower()
            keyword_match = keyword and keyword.lower() in message.lower()
            
            # Optional author check if username is provided
            author_match = True
            if github_username and author_login:
                author_match = author_login.get("login", "").lower() == github_username.lower()
            
            if (key_match or keyword_match) and author_match:
                return {
                    "verified": True,
                    "commit_sha": commit_sha,
                    "commit_hash": commit_sha[:7],
                    "commit_message": message.split("\n")[0],
                    "commit_url": commit_url,
                    "matched_author": author_name
                }
                
        return {"verified": False, "reason": "No matching commit found with task key or keyword."}

async def get_commit_code_changes(commit_sha: str) -> dict:
    """
    Fetches the specific file changes, additions, deletions, and patches for a commit.
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{commit_sha}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            return {"success": False, "error": f"Failed to fetch diffs: {response.status_code}"}
            
        data = response.json()
        files_changed = []
        
        for file in data.get("files", []):
            files_changed.append({
                "filename": file["filename"],
                "status": file["status"], # added, modified, removed
                "additions": file["additions"],
                "deletions": file["deletions"]
            })
            
        return {
            "success": True,
            "total_files_changed": len(files_changed),
            "files": files_changed
        }