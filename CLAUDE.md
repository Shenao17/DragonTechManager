
# DragonTech Manager — Project Instructions

## 1. PROJECT OBJECTIVE

Develop DragonTech Manager, a professional local desktop management application for DragonTech Care.

Technology:
- Python
- PySide6
- SQLite
- SQL migrations
- Git

The primary objective is a stable, secure and maintainable version 1.0.

Financial integrity, data protection and operational reliability take priority over development speed and additional features.

## 2. COMMUNICATION RULES

- Be concise and direct.
- Minimize unnecessary token consumption.
- Do not provide lengthy explanations unless requested.
- Do not repeat information already documented.
- Do not generate unnecessary reports.
- Do not narrate every action.
- Report only relevant findings, completed changes, blockers and required decisions.
- Do not explain basic concepts unless requested.
- Avoid unnecessary questions.

## 3. DOCUMENTATION AND CONTEXT

Before starting:
1. Read `docs/ai-context/README.md` if it exists.
2. Read only the documents relevant to the current task.
3. Inspect the actual implementation before modifying it.
4. Check whether the requested work is already implemented.

Documentation is the project's persistent technical memory.

Distinguish between:
- Implemented and verified.
- Implemented but not verified.
- Approved and pending implementation.
- Proposed and awaiting approval.
- Pending decisions.

Never present planned functionality as implemented.

Do not repeat completed analyses unless new evidence demonstrates a concrete problem.

Preserve original approved design documents.

## 4. TOKEN EFFICIENCY

- Use Sonnet by default.
- Use Opus only for genuinely complex architectural or financial problems.
- Prefer targeted file inspection.
- Avoid reading entire modules when specific sections are sufficient.
- Never repeat searches without a concrete reason.
- Avoid duplicated analysis and unnecessary agents.
- Do not regenerate existing documentation.
- Do not produce extensive implementation summaries.
- Do not investigate unrelated modules.
- Avoid unnecessary test execution.
- Do not spend tokens explaining routine operations.

Plan once, implement once, verify appropriately and document the result.

## 5. DEVELOPMENT WORKFLOW

For each authorized delivery:

1. Identify the requested scope.
2. Inspect relevant code and dependencies.
3. Check Git status and current branch.
4. Identify risks and affected modules.
5. Create a concise implementation plan.
6. Implement the complete authorized scope.
7. Perform necessary targeted verification.
8. Update relevant documentation.
9. Report completion and remaining blockers.

Do not stop at planning when implementation has been authorized.

Do not expand the scope without permission.

## 6. TESTING POLICY

The user will handle routine test execution and manual UI validation whenever practical.

Therefore:

- Do not automatically execute the entire test suite after every modification.
- Do not repeatedly inspect test output without a concrete reason.
- Do not spend unnecessary tokens generating test reports.
- Write or update tests when required by the implementation.
- Provide concise commands for the user to execute tests.
- Do not remove, weaken or bypass existing tests.
- Never claim tests passed if they were not executed.
- Clearly distinguish unverified changes from verified changes.

Testing must not be neglected in critical areas.

For the following operations, targeted verification is mandatory when necessary:
- Financial transactions.
- Payments and payment reversals.
- Refunds and customer credits.
- Inventory movements.
- Database migrations.
- Backup and restoration.
- Data integrity and transaction atomicity.

The user may execute the tests and provide results for investigation.

## 7. CODE QUALITY

- Follow the existing architecture and conventions.
- Preserve separation between UI, services, repositories and database.
- Avoid duplicated business logic.
- Keep functions and modules maintainable.
- Use explicit validations.
- Handle exceptions appropriately.
- Avoid silent failures.
- Use clear names and meaningful error messages.
- Document non-obvious business rules.
- Do not introduce unnecessary dependencies.
- Do not perform unrelated refactoring.

Do not sacrifice code quality to reduce token consumption.

## 8. FINANCIAL AND DATA INTEGRITY

This is a critical requirement.

- Never delete historical financial records to correct an operation.
- Preserve payment traceability.
- Prevent duplicate financial operations.
- Preserve transaction atomicity.
- Prevent negative or inconsistent balances.
- Validate inventory movements.
- Preserve historical relationships.
- Use idempotency where required.
- Never weaken financial constraints to make an operation succeed.
- Never modify production financial data during testing.

Approved financial rules must be respected exactly.

Do not reinterpret or simplify approved formulas, invariants or decisions.

Consult `BUSINESS_RULES.md` and the original approved design documents when working on financial modules.

If a concrete contradiction exists, document it and stop the affected operation until resolved.

## 9. DATABASE AND MIGRATIONS

- Preserve existing data.
- Never modify historical migrations already applied.
- Create new sequential migrations.
- Maintain referential integrity.
- Use transactions where appropriate.
- Validate migration compatibility.
- Avoid destructive schema changes.
- Preserve backup and restoration mechanisms.
- Use temporary databases for testing.

Never assume the production database is disposable.

## 10. SECURITY AND PRIVACY

- Protect customer information.
- Avoid exposing sensitive information in logs.
- Never hardcode credentials or secrets.
- Validate user input.
- Handle local files securely.
- Apply appropriate access restrictions.
- Do not assume local storage alone guarantees security.
- Avoid unnecessary transmission of customer data.

Security improvements must not break existing functionality.

## 11. USER INTERFACE

- Preserve the established visual identity.
- Maintain a professional dark interface.
- Use consistent spacing, typography and components.
- Avoid unnecessary visual redesigns.
- Prevent overflowing content and inaccessible controls.
- Provide clear loading, empty, success and error states.
- Preserve usability at common desktop resolutions.

The user will perform routine visual validation.

## 12. GIT RULES

Before modifying files:
- Inspect the current branch.
- Inspect the working tree.
- Identify unrelated user changes.
- Never overwrite work that does not belong to the current task.

Without explicit authorization, never:
- Commit.
- Push.
- Create tags.
- Reset branches.
- Discard changes.
- Rewrite Git history.

## 13. PROJECT DOCUMENTATION

After completing an authorized delivery:

- Update `PROJECT_STATE.md`.
- Update `IMPLEMENTATION_ROADMAP.md` when necessary.
- Update `KNOWN_ISSUES.md` when necessary.
- Update `CHANGELOG_AI.md`.
- Update technical or business rules only when the implementation changes an approved decision.

Do not rewrite every document after every small modification.

Keep documentation concise, accurate and synchronized with the actual code.

## 14. DECISION MANAGEMENT

- Respect previously approved decisions.
- Do not reopen settled topics without concrete technical evidence.
- Do not introduce new architectural approaches without justification.
- Ask the user only when a decision blocks safe implementation.
- Never silently make important financial or business-policy decisions.

## 15. VERSION 1.0 PRIORITIES

Priority order:

1. Financial integrity.
2. Database and data integrity.
3. Security and privacy.
4. Backup and recovery.
5. Core business functionality.
6. Operational stability.
7. User interface reliability.
8. Documentation and deployment.
9. Performance optimization.
10. Additional features.

Version 1.0 must be stable before commercial expansion.

Do not introduce cloud infrastructure, subscriptions, multi-company functionality or major architectural changes unless explicitly authorized.

## 16. FINAL WORKING PRINCIPLE

Build the requested functionality correctly.

Avoid unnecessary analysis, repeated inspections, excessive reports and wasted tokens.

Do not confuse token efficiency with skipping essential engineering work.

The objective is not to produce more code.

The objective is to deliver a reliable DragonTech Manager 1.0.

## Session and Context Management

- Monitor context usage throughout each Claude Code session.
- Periodically inform the user how much context has been used and how much remains, when this information is available.
- Recommend `/compact` before context becomes critically low, ideally around 65–70% usage.
- Never compact without warning the user first.
- Before compacting, preserve:
  - Current task and implementation progress.
  - Pending work and next concrete steps.
  - Known bugs and unresolved issues.
  - Approved business rules and technical decisions.
  - Important constraints and previously rejected alternatives.
- After compacting, verify that the essential project context is still available.
- Avoid repeatedly asking the user for information already documented.
- At the beginning of a new session, briefly state the current task and relevant project status.
- Keep session summaries concise and actionable.

### Git Efficiency
- Do not repeat Git status checks at the beginning of every task or delivery.
- Treat the last confirmed commit as the baseline for the next delivery.
- Inspect Git only when necessary to detect unexpected changes, conflicts, or potential data loss.
- Never repeat checks already completed in the current session without a concrete reason.
- Keep Git operations minimal and avoid unnecessary token consumption.