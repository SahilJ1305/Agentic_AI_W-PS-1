# Project: DepGuard

## Summary

Project DepGuard is an automated security governance and supply-chain defense system designed to enforce security standards during code reviews. DepGuard evaluates third-party dependencies, generates automated trust and health scores using an internal Dependency Review Bot and OpenSSF Scorecard integrations, and automatically enforces client-side (iframe sandboxing) and server-side (container/chroot process isolation) sandboxing for untrusted inputs or risky third-party packages. The system ensures a defensive security posture across all merged pull requests without delaying release pipelines. Submission is due in 3 days at 18:00 for the Cloud Security & Supply Chain Hackathon.

## Deadline

in 3 days at 18:00 (Asia/Kolkata)

## Team

| Name | Role (lead/member) | Skills | Telegram @username | GitHub username |
|---|---|---|---|---|
| Rohan | lead | security architecture, devsecops, python | @rohan_sec | rohan-sec |
| Aarav | member | frontend, iframe sandboxing, react | @aarav_fe | aarav-ui |
| Vikram | member | backend, containers, go | @vikram_be | vikram-dev |
| Neha | member | automation, bots, github apis | @neha_bot | neha-bot |
| Priya | member | testing, fuzzing, sanitizers | @priya_qa | priya-test |
| Kabir | member | technical writing, docs, compliance | @kabir_docs | kabir-docs |

## Tasks

| key | title | owner | status | deadline | depends_on | requires_evidence | milestone | notes |
|---|---|---|---|---|---|---|---|---|
| T1 | Initialize DepGuard repo, CI pipeline, and security linter | Neha | complete | | | yes | M1 | Done means: main branch enforces static analysis on push. |
| T2 | Design trust scoring & metadata schema for dependencies | Rohan | complete | | T1 | yes | M1 | Done means: DB schema for storing OpenSSF scorecard & CVE data merged. |
| T3 | Build Dependency Review Bot API | Neha | in_progress | today 18:00 | T2 | yes | M1 | Done means: GET /deps/score fetches package metadata and generates a trust score. |
| T4 | Integrate OpenSSF Scorecard & CVE database lookups | Vikram | pending | today 20:00 | T2 | yes | M1 | Done means: automated lookups for known CVEs and repository activity. |
| T5 | Implement client-side iframe sandboxing middleware | Aarav | in_progress | today 17:00 | T1 | yes | M1 | Done means: frontend components restrict untrusted third-party scripts via iframe `sandbox`. |
| T6 | Design server-side container & chroot process isolator | Vikram | complete | | | yes | M1 | Done means: architecture diagram and isolation strategy approved. |
| T7 | Implement server-side isolated runner for untrusted code/uploads | Vikram | in_progress | today 21:00 | T6, ~T3 | yes | M2 | Done means: risky untrusted execution runs inside isolated container/chroot sandbox. |
| T8 | Connect Dependency Bot with PR Code Review checks | Neha | pending | today 23:30 | T3, T4, T7 | yes | M2 | Done means: GitHub Action posts trust score & blocks PRs with unsafe dependencies. |
| T9 | Set up automated fuzzing & sanitizer test suite | Priya | pending | tomorrow 02:00 | T4 | yes | M2 | Done means: fuzzing pipeline catches unhandled buffer overflows and memory sanitization errors. |
| T10 | Deploy DepGuard staging environment on isolated server | Rohan | pending | today 22:00 | T3, T4, T5 | yes | M2 | Done means: staging URL validates sample PRs and outputs dependency risk reports. |
| T11 | Write end-to-end security compliance checklist | Kabir | pending | | ~T8 | yes | M3 | Done means: checklist drafted for supply chain security and sandboxing verification. |
| T12 | Run end-to-end supply chain attacks against staging | Priya | pending | tomorrow 05:00 | T8, T10, T11 | yes | M3 | Done means: all attack vectors neutralized by sandboxing and review bot. |
| T13 | Prepare pitch deck & architecture breakdown | Rohan | in_progress | tomorrow 06:00 | ~T6 | yes | M3 | Done means: deck includes supply chain threat model, live demo, and impact metrics. |
| T14 | Record 2-minute demo video showing bot & sandboxing | Aarav | pending | tomorrow 08:00 | T12, ~T13 | yes | M3 | Done means: video uploaded showing automated PR block on high-risk dependency. |
| T15 | Add presentation link & submit project to hackathon | Rohan | pending | in 3 days 18:00 | T13, T14 | yes | M3 | Done means: submission form sent with repo, video, deck, and fuzzing presentation link. |

## Deliverables

### F1. Dependency Review Bot & Trust Engine
What: Automated bot and API that fetches metadata, evaluates release stability, checks maintenance activity, and generates a trust score using OpenSSF Scorecard & CVE databases.
Done means: A PR adding a low-activity or vulnerable third-party package is flagged and blocked automatically.
Needs: T2, T3
Owner (optional): Neha

### F2. Client & Server Sandboxing Layer
What: Client-side iframe `sandbox` attributes for risky frontend components and server-side process isolation (`chroot`/containers) for untrusted uploads and code execution.
Done means: Untrusted user input or untrusted packages cannot access host system memory or parent DOM context.
Needs: T5, T7
Owner (optional): Vikram

### F3. DepGuard PR Gate & Review Interface
What: Dashboard and GitHub bot integration summarizing dependency health, blast radius evaluation, and sandboxing status.
Done means: Developers view dependency trust scores directly inside GitHub PR comments.
Needs: F1, F2
Owner (optional): Aarav

### F4. Fuzzing Sanitizers & Threat Suite
What: Fuzzing suite integrated with memory sanitizers to test external dependencies against zero-day vulnerabilities.
Done means: Fuzzing runs automatically during security review stages and generates sanitizer reports.
Needs: F1
Owner (optional): Priya

### F5. Pitch, Documentation & Presentation Link
What: Deck, demo video, presentation link on fuzzing sanitizers in meeting agenda/description, and final hackathon submission.
Done means: Submission confirmed by organizers before deadline with presentation link in video description.
Needs: F3 tested end to end on staging
Owner (optional): Rohan

## Milestones (optional)
| Milestone | Due | Includes |
|---|---|---|
| M1 Core Engine & Sandboxing Protocols | today 20:00 | T1, T2, T3, T4, T5, T6 |
| M2 Staging Deployment & Automated PR Checks | today 23:30 | T7, T8, T9, T10 |
| M3 Defense Verification, Pitch & Submission | in 3 days 18:00 | T11, T12, T13, T14, T15 |

## Constraints and notes
- Stack: Python/FastAPI for the review backend, Docker/chroot for server sandboxing, React with restricted iframe attributes for frontend components, deployed on isolated staging servers.
- Judging: defensive security depth, reduction of supply-chain blast radius, live working demo on staging, and code quality.
- Dependency Addition Litmus Test: Adding new third-party dependencies requires passing checks on project maturity, release frequency, and maintenance activity. Small utilities should be reimplemented inline rather than introducing heavy dependencies.
- Every completion requires verifiable proof: a GitHub pull request, staging build URL, OpenSSF scorecard audit report, or video recording link.
- Presentation Link Requirement: As noted in action items, links to the presentation on fuzzing sanitizers must be included in both the meeting agenda and recording description. Rohan and Aarav are responsible for coordinating these links.