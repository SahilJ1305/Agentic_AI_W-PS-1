import asyncio
import os
from dotenv import load_dotenv
from github_checker import verify_task_on_github, get_commit_code_changes

load_dotenv()

async def simulate_user_update():
    print("==================================================")
    print("   Cadence + GitHub Codebase Verification Demo    ")
    print("==================================================")
    
    # Simulated incoming user update context
    sender_name = "Mayuresh"
    task_key = "README"
    keyword = "project title"
    user_message = "I have updated the project title in the README file."
    
    print(f"\n[Telegram Inbound Message from {sender_name}]:")
    print(f" > \"{user_message}\"")
    print(f"Target Task: {task_key} | Keyword Filter: '{keyword}'")
    
    repo_name = os.getenv('GITHUB_REPO')
    print(f"\n[1/2] Querying GitHub repository '{repo_name}' for matching commits...")
    
    # Step 1: Verify commit existence
    verification = await verify_task_on_github(task_key=task_key, keyword=keyword)
    
    if not verification["verified"]:
        print("\n❌ Verification Failed:")
        print(f"   Reason: {verification.get('reason', verification.get('error'))}")
        print("   -> Action: Fallback triggered. Ask user for a direct link or flag `needs_verification`.")
        return

    print("\n✅ Commit Verified Successfully!")
    print(f"   - Commit Hash : {verification['commit_hash']}")
    print(f"   - Author      : {verification['matched_author']}")
    print(f"   - Message     : {verification['commit_message']}")
    print(f"   - URL         : {verification['commit_url']}")

    # Step 2: Analyze codebase changes (File Diffs)
    print(f"\n[2/2] Analyzing codebase file changes for commit {verification['commit_hash']}...")
    diff_data = await get_commit_code_changes(verification['commit_sha'])
    
    if diff_data["success"]:
        print(f"\n📊 Codebase Analysis Summary:")
        print(f"   - Total Files Changed: {diff_data['total_files_changed']}")
        for f in diff_data["files"]:
            print(f"     • File: {f['filename']} ({f['status']}) -> +{f['additions']} / -{f['deletions']} lines")
        
        print("\n🎉 Policy Engine Decision:")
        print(f"   -> Task '{task_key}' automatically marked as **COMPLETE**.")
        print(f"   -> Attached commit URL as verifiable evidence: {verification['commit_url']}")
    else:
        print(f"\n⚠️ Warning: Could not fetch file diffs ({diff_data.get('error')})")

if __name__ == "__main__":
    asyncio.run(simulate_user_update())