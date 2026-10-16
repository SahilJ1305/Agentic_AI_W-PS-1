# Project: ShelfShare

## Summary
ShelfShare is a campus app for listing and swapping textbooks. Submission is due tomorrow at 10:00. This file is a second project spec for testing the importer, not the FestPass demo.

## Deadline
tomorrow 10:00

## Team
| Name | Role (lead/member) | Skills | Telegram @username |
|---|---|---|---|
| Priya | lead | writing, pitching | @priya |
| Dev | member | backend, databases | @dev |
| Leela | member | frontend, design | @leela |
| Omar | member | backend, apis | @omar |
| Noor | member | testing, video | @noor |

## Tasks
| key | title | owner | status | deadline | depends_on | requires_evidence | milestone | notes |
|---|---|---|---|---|---|---|---|---|
| T1 | Set up the listings API | Dev | done | | | yes | M1 | Status word "done" should import as complete. |
| T2 | Design the browse screens | Leela | doing | today 15:00 | | yes | M1 | Status word "doing" should import as in_progress. |
| T3 | Build the listing endpoints | Omar | pending | today 19:00 | T1 | yes | M1 | Hard upstream T1 is already complete, so this is ready. |
| T4 | Connect college login | Dev | blocked | today 17:00 | | yes | M1 | No upstream. Stays ready, and sits in the Blocked column. Left off T3 so a later reply can discover that link. |
| T5 | Build the search page | Leela | not started | today 21:00 | T2 | | M1 | "not started" imports as pending. Waiting because T2 is still in progress. |
| T6 | Wire search to the API | Omar | pending | today 23:00 | T3, T5 | yes | M2 | Waiting on two hard upstreams. Becomes ready only after both T3 and T5 are complete. |
| T7 | Draft the pitch outline | Priya | complete | | | yes | M2 | |
| T8 | Record the demo video | Noor | pending | tomorrow 08:00 | T6, ~T7 | yes | M2 | T6 is hard, so this waits. ~T7 is soft and must not block it. |
| T9 | Final checks and submission | Priya | pending | tomorrow 10:00 | T6, T8 | yes | M2 | End of the hard chain. |
| T10 | Write the test checklist | Noor | pending | | ~T3 | | M2 | Only a soft link, so this is ready even while T3 is open. |
| T11 | Pick up leftover copy edits | | pending | tomorrow 12:00 | | | | Owner left blank on purpose, so this task is unassigned. |

## Deliverables
### F1. Listings API
What: Create, edit and search textbook listings.
Done means: A listing can be created and found by title.
Needs: T1
Owner (optional): Omar

### F2. Browse and search
What: Screens for browsing listings and searching them.
Done means: Search shows live results from the API.
Needs: F1
Owner (optional): Leela

## Constraints and notes
Upload this as a new project. After import the board should look like this:

- Complete: T1, T7
- In progress: T2
- Blocked: T4
- Pending and ready: T3, T10, T11
- Pending and waiting: T5 (on T2), T6 (on T3 and T5), T8 (on T6), T9 (on T6 and T8)

T4 is not a dependency of T3. A blocked reply on T3 can add that edge later, the same way FestPass leaves T2 off T3.
