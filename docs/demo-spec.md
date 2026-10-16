# Project: FestPass

## Summary
FestPass is a ticketing app with payments for the college fest. Submission is due tomorrow at 10:00. Cadence should keep the four owners in sync through Telegram.

## Deadline
tomorrow 10:00

## Team
| Name | Role (lead/member) | Skills | Telegram @username |
|---|---|---|---|
| Aanya | lead | design, slides, pitching | @aanya |
| Kabir | member | backend, apis | @kabir |
| Meera | member | frontend | @meera |
| Rohan | member | backend, devops | @rohan |

## Tasks
| key | title | owner | status | deadline | depends_on | requires_evidence | milestone | notes |
|---|---|---|---|---|---|---|---|---|
| T1 | Set up backend and database | Rohan | complete | | | yes | M1 | |
| T2 | Set up payment gateway sandbox account | Rohan | pending | today 16:00 | | | M1 | |
| T3 | Connect the payment API | Kabir | pending | today 20:00 | T1 | yes | M1 | |
| T4 | Build checkout UI | Meera | in_progress | today 18:00 | | yes | M1 | |
| T5 | Integrate checkout UI with payment API | Meera | pending | today 23:00 | T3, T4 | yes | M2 | |
| T6 | Prepare pitch slides | Aanya | complete | | | yes | M2 | |
| T7 | Record demo video | Aanya | pending | tomorrow 08:00 | T5, ~T6 | yes | M2 | |
| T8 | Final testing and submission | Aanya | pending | tomorrow 10:00 | T5, T7 | yes | M2 | |

## Deliverables
### F1. Payment API
What: Charge, refund and webhook against the sandbox gateway.
Done means: A sandbox payment succeeds.
Needs: T1
Owner (optional): Kabir

### F2. Checkout
What: Checkout UI wired to the payment API.
Done means: A full purchase works end to end.
Needs: F1
Owner (optional): Meera

## Constraints and notes
T2 is intentionally not listed as a dependency of T3. Kabir's blocker reply should discover that edge at runtime.
