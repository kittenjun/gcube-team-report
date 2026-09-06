# GCUBE team work explorer

`generate_report.py` collects Azure DevOps work items and builds `index.html`.
The existing scheduled workflow continues to run it. `report_view.py` owns
classification and period metrics; `report_template.html` owns the interface.

## Scope

- Current assignee must exactly match one of `AZDO_MEMBERS` (not creator).
- Removed items are excluded. All other open items are collected even when stale.
- Done items changed within the rolling window are collected, but completion
  counts require a ClosedDate within the displayed 30 calendar dates.
- The UI separates recent activity, all open work, stale open work, and newly
  created work. Created mode still uses the current assignee cohort.
- Topics use exact, case-insensitive Azure tags: gcube (GCUBE 플랫폼),
  pcbang (PC방 솔루션), edu (강의 솔루션), test (테스트 TOOLS).
  Multiple matching tags appear in each topic; totals count unique tickets.
  Missing/unrecognized tags appear under 기타; titles never substitute tags.
- Each topic groups tickets into 새로열림 (New/Ready), 진행
  (In Progress/Active/Blocked), 리뷰 (In Review), 완료 (Done/Closed).
  Original states remain visible in detail and Blocked keeps its warning.
  Seven-day activity counts are calculated within the selected scope.
- Summaries are labeled source excerpts, not inferred delivery claims.
- Comments, PRs and deployment evidence are not collected in this version.
- Full descriptions are preserved in generated HTML. Review the intended
  publication audience before publishing; the current repository is public.

## Validation

`python -m unittest test_report` runs offline regression tests.
`python preview_report.py` creates a labeled preview from the committed old
snapshot without credentials. Its descriptions are still truncated and its
stale work coverage is incomplete. Do not publish it as a fresh collection.

Production: set AZDO_PAT with Work Items read access and run
`python generate_report.py`. Do not commit credentials or raw API responses.
