# **Task Overview**

### **Inputs**

You will receive **four inputs**:

1. **Transcription**

    - The **full transcription of the entire audio file**.
    - The transcription **may contain multiple languages** mixed together.

2. **Disinformation Snippet** (part of the Transcription)

    - This is a specific segment of the full transcription that has been previously identified as containing disinformation or misinformation.
    - If this snippet is not found in the transcription, that means the inputs are invalid. Refer to the **Guidelines** section below for instructions on how to handle this situation.

3. **Audio Metadata**

    - A JSON object containing metadata about the audio recording.
    - Includes the date and day of the week of the recording in **UTC**.

    **Structure:**

    ```json
    {
        "recorded_at": "Month DD, YYYY HH:MM AM/PM", // Time is in UTC, e.g., "December 3, 2024 11:59 AM"
        "recording_day_of_week": "Day of the Week" // e.g., "Tuesday"
    }
    ```

4. **Analysis JSON**

    - A complex JSON object containing a detailed analysis of the disinformation snippet within the transcription.

    **Structure:**

    ```json
    {
      "translation": "...", // Full translation of the entire transcription, not just the disinformation snippet
      "title": {
        "spanish": "...",
        "english": "..."
      },
      "summary": {
        "spanish": "...",
        "english": "..."
      },
      "explanation": {
        "spanish": "...",
        "english": "..."
      },
      "disinformation_categories": [
        {
          "spanish": "...",
          "english": "..."
        }
      ],
      "keywords_detected": [ "...", "..." ],
      "language": {
        "primary_language": "...",
        "dialect": "...",
        "register": "..."
      },
      "confidence_scores": {
        "overall": 0-100,
        "analysis": {
          "claims": [
            {
              "quote": "...",
              "evidence": "...",
              "score": 0-100
            }
          ],
          "validation_checklist": {
            "specific_claims_quoted": true/false,
            "evidence_provided": true/false,
            "scoring_falsity": true/false,
            "defensible_to_factcheckers": true/false,
            "consistent_explanations": true/false
          },
          "score_adjustments": {
            "initial_score": 0-100,
            "final_score": 0-100,
            "adjustment_reason": "..."
          }
        },
        "categories": [
          {
            "category": "...",
            "score": 0-100
          }
        ]
      },
      "political_leaning": {
        "score": -1.0 to +1.0,
        "evidence": {
          "policy_positions": [ "..." ],
          "arguments": [ "..." ],
          "rhetoric": [ "..." ],
          "sources": [ "..." ],
          "solutions": [ "..." ]
        },
        "explanation": {
          "spanish": "...",
          "english": "...",
          "score_adjustments": {
            "initial_score": -1.0 to +1.0,
            "final_score": -1.0 to +1.0,
            "reasoning": "..."
          }
        }
      }
    }
    ```

### **Your Tasks**

1. **Primary Analysis:**

    - **Review the provided analysis** in the **Analysis JSON**.

2. **Accuracy Determination:**

    - **Determine the accuracy** of each component of the analysis.
    - Identify any discrepancies or inaccuracies.

3. **Verification:**

    - **Utilize the grounded results from internet searches** to verify claims as needed.
    - Cross-reference with up-to-date news and factual data.
    - Ensure external sources are relevant and support the Transcription.

4. **Content Adjustment:**

    - **Modify the content** within the Analysis JSON fields based on your findings.
    - Ensure all updates are justified by and consistent with the Transcription and Metadata.

5. **Output Generation:**

    - **Produce a new JSON object** that **exactly mirrors the structure** of the input Analysis JSON.
    - **Do not add or remove any fields**; only update the content within existing fields.

### **Guidelines**

-   **Transcription and Metadata:**

    -   The **Transcription** is the most important input.
    -   All analysis and updates must be consistent with and directly supported by the Transcription and Audio Metadata.
    -   Give particular focus to the **Disinformation Snippet**, as it is the segment of the Transcription identified as containing disinformation.
      -   Ensure that the **Disinformation Snippet** is included in the Transcription.
          -   Note that the snippet may not perfectly match the transcription; minor discrepancies are acceptable as long as the core content is present.
      -   If the snippet cannot be located in the Transcription:
          -   Set the **confidence_scores.overall** to 0.
          -   Write a clear explanation in the **confidence_scores.analysis.score_adjustments.adjustment_reason** field, indicating that the snippet is missing from the Transcription.
          -   Leave all other fields in the Analysis JSON unchanged.

-   **Comprehensive Review:**

    -   Examine all components of the Analysis JSON.
    -   Evaluate the accuracy and validity of each field.
    -   Note that the claims in the Analysis JSON could be incorrect. Your task is to verify and correct any inaccurate claims.

-   **Evidence-Based Adjustments:**

    -   Update text fields (e.g., `summary`, `explanation`, `evidence`) to accurately reflect the Transcription.
    -   Adjust numerical scores (e.g., `confidence_scores`, `political_leaning.score`):
        -   Provide justifications in the corresponding `explanation` or `reasoning` fields.
        -   Ensure scores are appropriate given the Transcription, Metadata, and the scoring guidelines provided.
    -   Modify array elements as needed:
        -   Add or update `claims` under `confidence_scores.analysis`.

-   **Content Preservation:**

    - If, upon review, a section of the Analysis JSON is deemed accurate and well-written, it should be kept unchanged. There is no need to rephrase or modify content that is already good.
    - Only change the content when you are confident in your assessment. If you are unsure about a change, keep the original content as is.

-   **Objectivity and Neutrality:**

    -   Maintain strict neutrality throughout your analysis.
    -   Focus on verifiable facts from the Transcription, external sources, and Metadata.
    -   Distinguish between controversial content and demonstrably false claims.

-   **Output Requirements:**

    -   **Structure Fidelity:** The output JSON structure must be **identical** to the input Analysis JSON structure.
        -   Do not add, remove, or rearrange any fields.
    -   **Content Updates:** Only update the content within the existing fields.
    -   **Clarity and Precision:** Ensure your revised analysis is clear, concise, and easily understandable.


### **Confidence Scoring and Self-Review Process**

The confidence score represents your degree of certainty that the content contains demonstrably false or misleading claims. This is NOT:
- A measure of confidence in your analysis
- A measure of how controversial or partisan the content is
- A measure of whether you agree with the positions expressed

**Initial Scoring Framework:**

High Confidence Scores (80-100) require:
- Specific factual claims that can be definitively proven false
- Direct contradictions of well-documented facts
- Demonstrably false statements or deliberate misrepresentation
Example: "The COVID vaccine contains microchips for mind control"

Medium Confidence Scores (40-79) require:
- Misleading claims that omit crucial context
- Deceptive presentation of real facts
- Misrepresentation of causation vs correlation
Example: "Immigrants are causing crime rates to spike" (when data shows no correlation)

Low Confidence Scores (1-39) apply to:
- Unsubstantiated claims without clear evidence
- Exaggerated interpretations of real events
- Misleading but not entirely false statements
Example: "The government is hiding the truth about inflation"

Zero Confidence Score (0) applies when:
- Content makes no demonstrably false claims
- Content expresses opinions without misrepresenting facts
- Content may be partisan or controversial but is factually accurate
Example: "We need stricter immigration policies"

### **Required Self-Review Process**

After completing your initial analysis, perform this structured review:

1. **Claim-by-Claim Analysis**
   For each claim identified as disinformation:
   - Quote the specific claim verbatim
   - Identify what makes it false or misleading
   - Cite specific evidence disproving the claim
   - Assign and justify a sub-score

2. **Validation Checklist**
   Answer each question before proceeding:
   - [ ] Have I quoted specific false claims?
   - [ ] Can I prove these claims are false using reliable evidence?
   - [ ] Am I scoring falsity rather than controversy?
   - [ ] Would these scores be defensible to fact-checkers?
   - [ ] Are my explanations consistent with my scores?

3. **Score Adjustment Protocol**
   If any validation fails:
   - Reduce score to 0 if you cannot cite specific false claims
   - Adjust scores to match available evidence
   - Document reasoning for any score changes
   - Ensure final scores reflect only demonstrably false content

4. **Common Error Check**
   Review for these frequent mistakes:
   - Scoring opinions as if they were facts
   - Confusing controversial content with false content
   - Treating bias as equivalent to disinformation
   - Scoring based on disagreement rather than falsity

**Analysis Requirements:**

1. Focus on Observable Elements:
   - Explicit policy positions stated
   - Specific arguments made
   - Language and rhetoric used
   - Sources or authorities cited
   - Solutions proposed

2. Evidence-Based Scoring:
   - Score must be justified by direct references to the content
   - Each claim in the explanation must cite specific elements from the transcription
   - Acknowledge when content contains mixed or ambiguous political signals

### **Additional Instructions**

- **Cultural Sensitivity:** Always consider the cultural context and avoid imposing external biases. Be respectful of cultural nuances in language and expression.
- **Objectivity:** Maintain neutrality throughout your analysis. Do not let personal opinions influence the assessment.
- **Clarity and Precision:** Communicate your findings clearly and precisely to facilitate understanding and decision-making.
- **Zero Confidence Score:** If you assess that the audio transcription does not contain any potential misinformation or disinformation, please give it a zero confidence score.

---

Now proceed to review the following inputs: