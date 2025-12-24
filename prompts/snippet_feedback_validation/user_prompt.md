# Feedback Validation Task

You are validating user feedback on a snippet that was flagged for potential misinformation.

## Original Snippet Analysis (from Stage 3)

**Snippet ID:** {snippet_id}
**Recording Date:** {recorded_at}
**Radio Station:** {radio_station_name} ({radio_station_code}), {location_state}

### Transcription (Original Language)
{transcription}

### Translation (English)
{translation}

### Original Title
- Spanish: {title_spanish}
- English: {title_english}

### Original Summary
- Spanish: {summary_spanish}
- English: {summary_english}

### Original Explanation (Why it was flagged)
- Spanish: {explanation_spanish}
- English: {explanation_english}

### Original Disinformation Categories
{disinformation_categories}

### Original Confidence Scores
- Overall: {confidence_overall}
- Category Scores: {category_scores}

### Original Claims Analysis
{claims_analysis}

---

## User Feedback

**Total Dislikes:** {dislike_count}

### User-Applied Labels
{user_labels}

### User Comments
{user_comments}

---

## Your Task

1. **Review** the original Stage 3 analysis and its reasoning
2. **Analyze** the user feedback (dislikes, labels, comments)
3. **Verify** the claims using web search, focusing on:
   - Was the original content actually false/misleading?
   - Does the user feedback provide valid reasoning?
4. **Determine** the validation outcome

**Current Date:** {current_date}

Please provide your validation result in the following JSON format:

```json
{{
  "original_claim_summary": "Brief summary of what Stage 3 flagged as misinformation",
  "user_feedback_summary": "Brief summary of user feedback and their apparent reasoning",
  "claim_verifications": [
    {{
      "claim": "The specific claim being verified",
      "original_assessment": "What Stage 3 concluded about this claim",
      "verification_finding": "What web search reveals about this claim",
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
  "thought_summaries": "Detailed reasoning process including searches performed, evidence found, and how the decision was reached"
}}
```

**Status Values:**
- `false_positive`: Stage 3 was WRONG - content is NOT misinformation, user was RIGHT
- `true_positive`: Stage 3 was CORRECT - content IS misinformation, user was WRONG
- `needs_review`: Evidence mixed/ambiguous - requires human review
