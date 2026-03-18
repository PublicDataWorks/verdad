# Stage 1 Heuristic Format

Stage 1 is for **fast initial flagging**. The LLM scans a transcription and flags potential disinformation snippets. It does NOT do deep analysis or web search verification. The heuristics must be concise and pattern-oriented.

## Main Category Format (for detection_user_prompt.md — NO subcategories)

```markdown
### **{N}. {Category Name}**

**Description**:

{1-3 sentence description of what this disinformation category covers. Include any important context about how it differs from existing categories.}

**Keywords/Phrases**:

- **Spanish**:
  - "{phrase}" / "{variant}" ({English translation})
  - "{phrase}" ({English translation})
  ...
- **Arabic**:
  - "{Arabic phrase}" ({English translation})
  - "{Arabic phrase}" ({English translation})
  ...

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

Same as above for the main category, PLUS subcategories:

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

1. **Concise keywords** — Group related terms with `/` separators: `"cura milagrosa" / "cura natural"`
2. **Pattern-focused heuristics** — Describe WHAT to look for, not WHY it's wrong
3. **Both languages always** — Every keyword list and example needs Spanish AND Arabic
4. **No evidence lines** — Stage 1 doesn't verify claims, it just flags them
5. **No cultural variations or legitimate discussions** — Those are Stage 3 concerns
6. **Subcategories only in heuristics.md** — The detection_user_prompt.md stays flat
