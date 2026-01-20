# Iterative Refinement and Prompt Versioning

VERDAD employs a multi-pass, feedback-driven approach to continuously improve disinformation detection and analysis. This process leverages both LLMs and human reviewers to refine heuristics, prompts, and system instructions.

## Iterative Refinement Process

1. **User Feedback Collection**
   - Users (analysts, journalists) apply labels, upvote/downvote, and add comments to flagged snippets.
   - All feedback is stored in the database and associated with the relevant snippet and prompt version.

2. **Periodic LLM Review**
   - An advanced LLM periodically reviews accumulated user feedback and snippet discussions.
   - The LLM proposes adjustments to the dynamic heuristics and prompts used in detection and analysis stages.

3. **Final LLM and Human Review**
   - Another LLM (or a human reviewer) evaluates the proposed changes to heuristics and system instructions.
   - If approved, a plan for revising the system message is written and, upon human approval, executed.

4. **Prompt Versioning and Rollback**
   - Each prompt version is stored in the database with a unique version ID, associated LLM model, and an explanation of changes.
   - A chronological record of all prompt versions is maintained, allowing for easy comparison and rollback if needed.
   - Deprecated/archived prompts are retained for auditability.

## Database Interactions
- **Stage 1:** Insert basic snippet metadata when a snippet is first identified.
- **Stage 2:** Update with detailed analysis, transcriptions, and translations.
- **Prompt Management:** Store current and historical versions of prompts, with version IDs, explanations, and associated LLM models.
- **LLM Review Results:** Store proposed heuristic adjustments, evaluation plans, and track which proposals were implemented or rejected.

## Benefits
- Ensures the system adapts to new disinformation tactics.
- Maintains transparency and auditability of prompt changes.
- Enables rapid rollback in case of issues with new heuristics or prompts.
