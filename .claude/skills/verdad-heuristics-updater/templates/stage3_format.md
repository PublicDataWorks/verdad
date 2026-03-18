# Stage 3 Heuristic Format

Stage 3 is for **deep in-depth analysis** with web search verification. The LLM evaluates flagged snippets, verifies claims against current evidence, and assigns confidence scores. Heuristics must be detailed with evidence grounding, cultural context, and nuanced guidance.

## Main Category Format (used in BOTH analysis_prompt.md and heuristics.md — WITH subcategories)

```markdown
### **{N}. {Category Name}**

**Description**:

{Detailed description paragraph covering what this disinformation category encompasses. Be specific about scope.}

**Important Context**: {How this category relates to or differs from existing categories. E.g., "This category is distinct from Category 6 (Abortion) which focuses on political/ethical framing. Category N focuses on medical disinformation."}

**Common Narratives**:

- **"{Named Pattern}"**: {Description of this narrative pattern}
- **"{Named Pattern}"**: {Description}
...

**Disinformation Tactics (Detection Signals)**:
- "{Spanish phrase pattern}" - {What this tactic signals}
- "{Spanish phrase pattern}" - {What this tactic signals}
...

**Cultural/Regional Variations**:

- **Spanish-Speaking Communities**:
  - {Specific cultural factor affecting how this disinformation spreads}
  - {Information channel patterns — e.g., WhatsApp, family networks}
  ...
- **Arabic-Speaking Communities**:
  - {Specific cultural factor}
  - {Traditional/religious context}
  ...

**Potential Legitimate Discussions**:

- {Topic that could look like disinformation but isn't}
- {Another legitimate topic to NOT flag}
...

**Keywords/Phrases for Detection**:

**Spanish**:
- "{phrase1}", "{phrase2}", "{phrase3}"
...

**Arabic**:
- "{Arabic phrase}" ({English translation}), "{Arabic phrase}" ({translation})
...

**Examples**:

- *Spanish*: "{Realistic multi-sentence example showing a real disinformation pattern}"
- *Arabic*: "{Arabic equivalent}"
- *Spanish*: "{Another example showing a different pattern}"
- *Arabic*: "{Arabic equivalent}"

**Red Flags for High-Confidence Disinformation**:

Immediate high-confidence signals:
- {Pattern that is almost always disinformation}
...

Requires careful analysis:
- {Pattern that MIGHT be disinformation but could be legitimate}
...
```

## Subcategory Format

```markdown
#### **{N}.{M} {Subcategory Name}**

**Description**:

{1-2 sentence description focused on what specific disinformation this covers.}

**Narratives**:
- "{Narrative in Spanish}" ({English translation})
- "{Another narrative}" ({English translation})
...

**Evidence**: {1-2 sentence summary of medical/scientific consensus that explains WHY these claims are disinformation. This grounds the LLM's analysis.}

**Examples**:

- *Spanish*: "{Example sentence}"
- *Arabic*: "{Arabic equivalent}"
```

## Cross-Category Considerations (at end, after ALL new categories)

```markdown
**Cross-Category Considerations**:

These categories may overlap with:
- Category N ({Name}): {How they overlap}
...
```

## Key Principles for Stage 3

1. **Named narrative patterns** — Use bold named patterns like **"Miracle Cures"**, **"Industry Conspiracy"** for easy reference
2. **Evidence in subcategories** — Every subcategory gets a brief `**Evidence**:` line grounding the medical/scientific consensus
3. **Cultural nuance** — Detailed cultural variations for both communities, including traditional medicine practices, information channels, and trust factors
4. **Legitimate discussions** — Explicitly list things NOT to flag to reduce false positives
5. **Disinformation tactics** — Meta-patterns (commercial incentives, censorship claims, platform migration) that signal disinformation regardless of specific topic
6. **Red flags** — Split into "immediate high-confidence" vs "requires careful analysis" to help calibrate confidence scores
7. **Rich examples** — Multi-sentence examples that show realistic disinformation patterns, not just keywords
8. **Both languages always** — Every keyword, phrase, example, and narrative needs Spanish AND Arabic
