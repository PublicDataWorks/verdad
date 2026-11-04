# Stage 1 Heuristic Format

Stage 1 is for **fast initial flagging**. The LLM scans a transcription and flags potential disinformation snippets. It does NOT do deep analysis or web search verification. The heuristics must be concise and pattern-oriented.

## Main Category Format (for detection_user_prompt.md — NO subcategories, NO keyword list)

```markdown
### **{N}. {Category Name}**

**Description**:

{1-3 sentence description of what this disinformation category covers. Include any important context about how it differs from existing categories.}

**Heuristics**:

- {Detection pattern as a bullet point — focus on WHAT to look for}
- {Another detection pattern}
- {Behavioral signals like commercial incentives, censorship claims, platform migration}
...

**Examples**:

- *Spanish*: "{Realistic example sentence that a speaker might say}"
- *Arabic*: "{Arabic equivalent example}"
```

## Main Category + Subcategories Format (for heuristics.md standalone file)

Same as above for the main category, PLUS the `**Keywords/Phrases**` list (bilingual, same layout as in `templates/stage3_format.md`) and subcategories:

```markdown
#### **{N}.{M} {Subcategory Name}**

**Description**:

{Brief description of this specific subcategory.}

**Common Narratives**:

- "{Narrative in Spanish}" ({English translation})
- "{Another narrative}" ({English translation})

**Examples**:

- *Spanish*: "{Example sentence}"
- *Arabic*: "{Arabic equivalent}"
```

## Key Principles for Stage 1

1. **No keyword lists in the prompt** — Since `stage_1/disinformation_detection` 3.0.0 the Stage 1 prompt detects claims by meaning (keyword lists diluted the instruction on Gemini 3.x / Gemma 4). Put the keywords in the standalone `heuristics.md` only
2. **Pattern-focused heuristics** — Describe WHAT to look for, not WHY it's wrong
3. **Both languages always** — Every example needs Spanish AND Arabic
4. **No evidence lines** — Stage 1 doesn't verify claims, it just flags them
5. **No cultural variations or legitimate discussions** — Those are Stage 3 concerns
6. **Subcategories only in heuristics.md** — The detection_user_prompt.md stays flat
