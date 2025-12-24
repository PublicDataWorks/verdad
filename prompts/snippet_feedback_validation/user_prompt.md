# Feedback Validation Task

You are validating user feedback on a snippet that was flagged for potential misinformation.

---

## Original Snippet Analysis (from Stage 3)

### Metadata

**Snippet ID:** {snippet_id}
**Recording Date:** {recorded_at}
**Radio Station:** {radio_station_name} ({radio_station_code}), {location_state}

### Full Transcription

#### Transcription (Original Language)
{transcription}

#### Translation (English)
{translation}

*Note: This is the complete transcription of the audio clip. See "Snippet Context" below for the specific flagged portion with surrounding context.*

### Snippet Context

**Before (Original):**
{context_before}

**Before (English):**
{context_before_en}

**Main Snippet (Original):**
{context_main}

**Main Snippet (English):**
{context_main_en}

**After (Original):**
{context_after}

**After (English):**
{context_after_en}

### Stage 3 Assessment

#### Title
- Spanish: {title_spanish}
- English: {title_english}

#### Summary
- Spanish: {summary_spanish}
- English: {summary_english}

#### Explanation (Why it was flagged)
- Spanish: {explanation_spanish}
- English: {explanation_english}

#### Disinformation Categories
{disinformation_categories}

#### Confidence Scores
- Overall: {confidence_overall}
- Category Scores: {category_scores}

#### Claims Analysis
{claims_analysis}

### Keywords That Triggered Flag
{keywords_detected}

### Stage 3 Search Evidence
{grounding_metadata}

### Stage 3 Reasoning Process
{thought_summaries_stage3}

---

## User Feedback

**Total Dislikes:** {dislike_count}

### User-Applied Labels
{user_labels}

### User Comments
{user_comments}

---

## Verification Guidelines

### Verification Protocol

1. **Factual Claims**: Search for BOTH current status AND status at recording date. Require 2+ authoritative sources. If Stage 3 claims something is false, search for evidence BOTH supporting AND refuting the original claim.

2. **Knowledge Cutoff Issues**: Search "[entity/topic] current [year]" AND "[entity/topic] [recording_date_year]". If Stage 3 claims something "doesn't exist" or is "fictional", verify its creation date—recent entities may not have been in Stage 3's training data.

3. **Temporal Confusion**: Verify whether Stage 3 used data from the correct time period. Compare Stage 3's search evidence with your current search results. A claim can be true now but was false at recording time, or vice versa.

4. **Evaluating Stage 3 Search Quality**: Did Stage 3 search for the right terms? Find relevant sources? Use searches specific to the recording date/location? Miss obvious searches that would have changed the conclusion?

---

## Error Pattern Reference

| Error Type | How to Identify |
|------------|-----------------|
| `knowledge_cutoff` | Stage 3 says something doesn't exist that was created after its training cutoff |
| `temporal_confusion` | Stage 3 used data from wrong time period |
| `insufficient_search` | Stage 3's search evidence shows inadequate/no searches for a verifiable claim |
| `misinterpretation` | Stage 3 reasoning shows logical error despite having correct info |
| `correct_detection` | Stage 3 was right, user feedback is wrong |
| `ambiguous` | Mixed evidence, unclear which side is correct |

---

## User Feedback Assessment

**Adversarial Signals (Lower Quality):**
- Generic disagreement without specific reasoning
- Attacks on system rather than specific content
- Labels that don't match content
- No explanation of WHY classification is wrong

**High-Quality Signals:**
- Cites specific claims from the snippet
- Provides evidence, sources, or links
- Explains specifically why classification is wrong
- Identifies factual errors in Stage 3's analysis

---

## Handling Special Cases

**Minimal User Feedback (dislikes only, no comments/labels):**
- Focus verification on Stage 3's weakest claims (lowest scores, vaguest evidence)
- If Stage 3's analysis appears solid with no counter-evidence → lean `true_positive`
- If Stage 3's analysis has gaps → lean `needs_review`

**Empty/Minimal Stage 3 Search Evidence:**
- Strong signal for `insufficient_search` error pattern
- Perform the searches Stage 3 should have done
- If searches reveal Stage 3 was wrong → `false_positive` with `insufficient_search`
- If searches confirm Stage 3 was right → `true_positive`

**Conflicting Claim Verifications:**
- If MOST claims verified as false → `true_positive`
- If MOST claims verified as true → `false_positive`
- If roughly equal or key claims conflict → `needs_review`
- Weight higher-confidence claims more heavily

---

## Your Task

**Current Date:** {current_date}

1. **Review** Stage 3's analysis, search evidence, and reasoning
2. **Analyze** user feedback quality
3. **Verify** claims using web search (follow Verification Protocol above)
4. **Classify** the error pattern if Stage 3 erred
5. **Determine** the validation outcome

**Claim Verification Priority:**
- Verify ALL claims in "Claims Analysis" above
- If none documented, identify main factual assertions from the explanation
- Prioritize claims the user specifically disputes

---

## Output Format

Provide your validation result in the following JSON format:

```json
{{
  "original_claim_summary": "Brief summary of what Stage 3 flagged as misinformation",
  "user_feedback_summary": "Brief summary of user feedback and their apparent reasoning",
  "claim_verifications": [
    {{
      "claim": "The specific claim being verified",
      "original_assessment": "What Stage 3 concluded about this claim",
      "verification_finding": "What your web search reveals about this claim",
      "is_claim_actually_false": true/false,
      "confidence": 0-100
    }}
  ],
  "user_feedback_assessment": {{
    "feedback_quality": "high/medium/low",
    "feedback_reasoning": "Assessment of why user disliked/labeled the snippet",
    "appears_adversarial": true/false
  }},
  "validation_decision": {{
    "status": "false_positive/true_positive/needs_review",
    "confidence": 0-100,
    "primary_reason": "Main reason for this decision"
  }},
  "error_pattern": {{
    "error_type": "knowledge_cutoff/temporal_confusion/insufficient_search/misinterpretation/correct_detection/ambiguous",
    "explanation": "Brief explanation of why this error type was identified"
  }},
  "prompt_improvement_suggestion": "If false_positive, what specific improvement to Stage 3 prompt could prevent this error (null if not applicable)",
  "thought_summaries": "Detailed reasoning process including searches performed, evidence found, comparison with Stage 3's work, and how the decision was reached"
}}
```

---

## Confidence Guidelines

- **90-100**: Clear-cut case with strong evidence; no reasonable doubt
- **70-89**: Strong evidence but minor ambiguities remain
- **50-69**: Evidence leans one way but notable uncertainty exists
- **Below 50**: You MUST use `needs_review` - do not make low-confidence calls

Use `needs_review` when:
- Evidence is genuinely mixed (credible sources disagree)
- Claim is inherently subjective/interpretive
- Required information is unavailable
