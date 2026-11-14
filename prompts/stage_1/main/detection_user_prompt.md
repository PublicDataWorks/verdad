Please analyze the provided timestamped transcription for potential disinformation. Use the provided heuristics to identify and flag any disinformation snippets. **Determine the `start_time` and `end_time` of each flagged snippet based on the timestamps in the transcription**. Ensure that your output adheres strictly to the provided JSON schema.

# Overview

1. **Transcription Analysis:**

   - Carefully read the entire timestamped transcription.
   - Focus on content that may contain disinformation according to the heuristics provided.

2. **Disinformation Detection:**

   - Apply the detailed heuristics for each disinformation category listed below.
   - Pay special attention to cultural nuances, idioms, colloquialisms, and dialects common among Spanish and Arabic-speaking immigrant communities.

3. **Identify and Flag Snippets:**

   - For each potential disinformation snippet, record the following:
     - `start_time`: The timestamp when the snippet begins, in MM:SS format, based on the provided timestamped transcription.
     - `end_time`: The timestamp when the snippet ends, in MM:SS format, based on the provided timestamped transcription.
     - `transcription`: Transcription of the snippet (without timestamps).
     - `explanation`: Explanation of why this snippet was flagged (in English).
     - `disinformation_categories`: Applicable categories based on heuristics.
     - `keywords_detected`: Specific words or phrases that triggered the flag.

   - **Ensure that `start_time` and `end_time` are accurate and correspond to those provided in the timestamped transcription. Double-check these values to avoid discrepancies.**
     - The `start_time` must always be less than or equal to the `end_time`.
     - Both `start_time` and `end_time` must be within the range of the timestamped transcription.

4. **Assemble Structured Output:**

   - Your output must strictly conform to the provided JSON schema.

# JSON Schema

The output schema is enforced by the API; return only the `flagged_snippets` object.

# Disinformation Detection Heuristics

Below are detailed heuristics for each disinformation category, including culturally relevant examples in **Spanish** and **Arabic**. Keywords are not listed; detect the claims by meaning in either language. Use these heuristics to guide your analysis.

---

### **1. Election Integrity and Voting Processes**

**Description**:
Disinformation that falsely claims election fraud or manipulation in cases where no credible evidence exists. Note: Claims about the 2024 Presidential Election outcome should be evaluated against the official results showing Donald Trump's victory with 312 electoral votes and approximately 77.2 million individual votes (49.9%).

**Heuristics**:
- Claims of widespread voter fraud without evidence
- False claims that Kamala Harris won the 2024 election
- Unfounded allegations about voting systems being manipulated to favor Harris
- Note: Statements accurately reporting Trump's 2024 victory (312 electoral votes and winning the popular vote) should NOT be flagged as disinformation

**Examples**:
- *Spanish*: "Harris ganó el voto popular por millones, pero Trump robó la elección" (FALSE claim to flag)
- *Arabic*: "هاريس فازت بالتصويت الشعبي بالملايين ، لكن ترامب سرق الانتخابات" (FALSE claim to flag)

---

### **2. Immigration Policies**

**Description**:

Disinformation portraying immigrants as threats to security, economy, or culture, often exaggerating negative impacts.

**Heuristics**:

- Depicting immigrants as invaders or criminals.
- Claims that immigrants take jobs from citizens.
- Assertions that immigrants burden social services.

**Examples**:

- *Spanish*: "Los 'extranjeros ilegales' están causando problemas económicos."
- *Arabic*: "الأجانب غير الشرعيين يسببون مشكلات اقتصادية."

---

### **3. COVID-19 and Vaccination**

**Description**:

Disinformation denying the severity of COVID-19, spreading fear about vaccines, or promoting unproven treatments.

**Heuristics**:

- Claims that the pandemic is a hoax or planned event.
- Allegations that vaccines are unsafe or contain tracking devices.
- Promotion of unverified remedies over approved treatments.

**Examples**:

- *Spanish*: "La 'plandemia' es una excusa para controlarnos con 'microchips en vacunas'."
- *Arabic*: "الوباء المخطط هو ذريعة للسيطرة علينا باستخدام 'رقائق في اللقاح'."

---

### **4. Climate Change and Environmental Policies**

**Description**:

Disinformation denying human impact on climate change, often to oppose environmental regulations.

**Heuristics**:

- Denial of scientific consensus on climate change.
- Claims that environmental policies harm the economy without benefit.

**Examples**:

- *Spanish*: "El 'calentamiento global' es un mito para controlar nuestras vidas."
- *Arabic*: "الاحتباس الحراري هو كذبة للسيطرة على حياتنا."

---

### **5. LGBTQ+ Rights and Gender Issues**

**Description**:

Disinformation that misrepresents LGBTQ+ issues, portraying them as threats to traditional values or society.

**Heuristics**:

- Claims that LGBTQ+ rights movements aim to harm traditional family structures.
- Allegations that discussing gender issues confuses or harms children.

**Examples**:

- *Spanish*: "La 'ideología de género' está destruyendo nuestros valores."
- *Arabic*: "أيديولوجية الجندر تدمر قيمنا."

---

### **6. Abortion and Reproductive Rights**

**Description**:

Disinformation that frames abortion in extreme terms, often ignoring legal and ethical complexities.

**Heuristics**:

- Statements that oversimplify abortion debates.
- Use of emotionally charged language to provoke strong reactions.

**Examples**:

- *Spanish*: "El 'aborto' es una 'matanza de bebés' que debe detenerse."
- *Arabic*: "الإجهاض هو 'قتل الأطفال' ويجب إيقافه."

---

### **7. Economic Policies and Inflation**

**Description**:

Disinformation predicting economic collapse due to government policies, often exaggerating or misrepresenting facts.

**Heuristics**:

- Claims of impending economic disaster without credible evidence.
- Assertions that specific policies will ruin the economy.

**Examples**:

- *Spanish*: "Las nuevas políticas nos llevan a una 'hiperinflación inminente'."
- *Arabic*: "السياسات الجديدة تقودنا إلى 'تضخم مفرط وشيك'."

---

### **8. Foreign Policy and International Relations**

**Description**:

Disinformation that promotes distrust of international cooperation, alleging hidden agendas or conspiracies.

**Heuristics**:

- Allegations of international organizations undermining national sovereignty.
- Claims of foreign interference without evidence.

**Examples**:

- *Spanish*: "La 'agenda globalista' quiere dictar nuestras leyes."
- *Arabic*: "الأجندة العالمية تريد فرض قوانينها علينا."

---

### **9. Media and Tech Manipulation**

**Description**:

Disinformation that asserts media and tech companies suppress the truth, fostering distrust in credible sources.

**Heuristics**:

- Claims that mainstream media consistently lies or hides information.
- Allegations of censorship without substantiation.

**Examples**:

- *Spanish*: "No creas lo que dicen; son 'noticias falsas' manipuladas."
- *Arabic*: "لا تصدق ما يقولونه؛ إنها 'أخبار مزيفة' مُتحكَّم بها."

---

### **10. Public Safety and Law Enforcement**

**Description**:

Disinformation that exaggerates crime rates or portrays law enforcement reforms as threats to safety.

**Heuristics**:

- Overstating the prevalence of crime to incite fear.
- Claims that reforming law enforcement endangers communities.

**Examples**:

- *Spanish*: "Con la 'desfinanciación de la policía', la 'ola de crimen' aumentará."
- *Arabic*: "مع 'خفض تمويل الشرطة'، ستزداد 'موجة الجريمة'."

---

### **11. Healthcare Reform**

**Description**:

Disinformation that portrays healthcare reforms as harmful, often spreading fear about decreased quality of care or loss of freedoms.

**Heuristics**:

- Claims that healthcare reforms will lead to poor quality care.
- Allegations that reforms are a means for government control.

**Examples**:

- *Spanish*: "La 'medicina socializada' nos quitará el derecho a elegir."
- *Arabic*: "سيأخذ منا 'الطب الاجتماعي' حقنا في الاختيار."

---

### **12. Culture Wars and Social Issues**

**Description**:

Disinformation that frames social progress as attacks on traditional values, often resisting changes in societal norms.

**Heuristics**:

- Claims that societal changes erode cultural or moral foundations.
- Opposition to movements promoting equality or inclusion.

**Examples**:

- *Spanish*: "La 'corrección política' está destruyendo nuestra sociedad."
- *Arabic*: "تدمر 'الصوابية السياسية' مجتمعنا."

---

### **13. Geopolitical Issues**

#### **13.1 Ukraine-Russia Conflict**

**Description**:

Disinformation that justifies aggression or spreads false narratives about the conflict.

**Heuristics**:

- Blaming external forces for the conflict without evidence.
- Justifying aggressive actions through misleading narratives.

**Examples**:

- *Spanish*: "La 'expansión de la OTAN' obligó a Rusia a actuar."
- *Arabic*: "أجبر 'توسع الناتو' روسيا على التحرك."

#### **13.2 Israel-Palestine Conflict**

**Description**:

Disinformation that oversimplifies the conflict, often taking sides without acknowledging complexities.

**Heuristics**:

- Using emotionally charged language without context.
- Ignoring historical and political nuances.

**Examples**:

- *Spanish*: "El 'apartheid israelí' es la causa de todos los problemas."
- *Arabic*: "سبب كل المشكلات هو 'الفصل العنصري الإسرائيلي'."

#### **13.3 China-US Relations**

**Description**:

Disinformation that exaggerates threats from China, often fostering fear and suspicion.

**Heuristics**:

- Claims that China aims to undermine other nations.
- Allegations of unfair practices without evidence.

**Examples**:

- *Spanish*: "La 'amenaza china' es real y debemos prepararnos."
- *Arabic*: "التهديد الصيني حقيقي وعلينا الاستعداد."

---

### **14. Conspiracy Theories**

**Description**:

Disinformation involving unfounded claims about secret plots or organizations manipulating events.

**Heuristics**:

- Promoting theories without credible evidence.
- Suggesting hidden agendas controlling society.

**Examples**:

- *Spanish*: "El 'estado profundo' está detrás de todo lo que ocurre."
- *Arabic*: "تقف 'الدولة العميقة' وراء كل ما يحدث."

---

### **15. Education and Academic Freedom**

**Description**:

Disinformation alleging that education systems impose biased ideologies, undermining traditional values.

**Heuristics**:

- Claims that schools are indoctrinating children.
- Opposition to curricula promoting diversity or critical thinking.

**Examples**:

- *Spanish*: "Están haciendo 'adoctrinamiento en las escuelas' con ideas peligrosas."
- *Arabic*: "يقومون بـ'تلقين في المدارس' بأفكار خطيرة."

---

### **16. Technology and Privacy**

**Description**:

Disinformation spreading fear about technology infringing on privacy, often exaggerating risks.

**Heuristics**:

- Allegations that new technologies harm health or privacy without evidence.
- Claims of pervasive surveillance infringing on freedoms.

**Examples**:

- *Spanish*: "La tecnología '5G' causa enfermedades y debemos evitarla."
- *Arabic*: "تسبب تقنية '5G' الأمراض ويجب تجنبها."

---

### **17. Gun Rights and Control**

**Description**:

Disinformation that opposes any form of gun regulation, often invoking fears of government overreach.

**Heuristics**:

- Claims that gun regulations infringe on constitutional rights.
- Fear that any regulation leads to total disarmament.

**Examples**:

- *Spanish*: "La 'confiscación de armas' es el primer paso hacia la tiranía."
- *Arabic*: "تعد 'مصادرة الأسلحة' الخطوة الأولى نحو الطغيان."

---

### **18. Political Figures and Movements**

**Description**:

Disinformation involving extreme portrayals of political groups or figures, attributing malicious intent without evidence.

**Heuristics**:

- Labeling political opponents with extreme terms.
- Allegations of conspiracies without substantiation.

**Examples**:

- *Spanish*: "Los 'progresistas radicales' quieren destruir el país."
- *Arabic*: "يريد 'التقدميون المتطرفون' تدمير البلاد."

---

### **19. Labor Rights and Union Activities**

**Description**:

Disinformation that misrepresents labor organizing efforts, union activities, or workers' rights, often aiming to discourage collective action or spread fear about unions.

**Heuristics**:

- Claims that unions only collect dues without providing benefits
- Allegations that organizing efforts will lead to business closures
- False statements about NLRB processes or workers' rights
- Misrepresentation of collective bargaining impacts

**Examples**:

- *Spanish*: "Los 'sindicatos corruptos' solo quieren tu dinero y causarán el cierre de la empresa."
- *Arabic*: "النقابات الفاسدة تريد فقط أموالك وستتسبب في إغلاق الشركة."

---

### **20. Women's Health and Reproductive Care**

**Description**:

Disinformation targeting women's health including reproductive care, hormonal health, cancer prevention/treatment, fertility, pregnancy, and menopause. This includes false claims about contraception, menstruation, gynecological conditions, and women-specific medical treatments. Distinct from Category 6 (Abortion and Reproductive Rights) which focuses on political/ethical framing; this category focuses on medical disinformation — false health claims about treatments, procedures, and conditions regardless of political orientation.

**Heuristics**:

- Claims that natural substances (cúrcuma, jengibre, guanábana, sábila) can cure cancer or serious conditions without medical treatment
- Assertions that doctors, "Big Pharma," or the "cancer industry" hide cures for profit
- False equivalence that natural products are always safe while pharmaceuticals are inherently dangerous
- Claims that contraceptives cause permanent brain damage, infertility, or irreversible hormonal disruption
- Promotion of vaginal detoxes, uterine cleanses, or parasite protocols as cure-alls
- Claims of being "silenced" or "censored" to build credibility before promoting products
- Use of lab coats and medical terminology by unqualified individuals to appear credible
- Promises of miracle cures without side effects
- Migration to closed platforms (Telegram groups) to avoid content moderation
- Commercial incentives (link in bio, discount codes) embedded in health claims

**Examples**:

- *Spanish*: "Con cúrcuma y jengibre mi prima curó el cáncer de mama sin quimioterapia. Los doctores no quieren que sepas esto porque pierden dinero."
- *Arabic*: "استخدمت أختي الحلبة والعسل وشُفيت من تكيس المبايض. الأطباء يخفون هذه العلاجات الطبيعية."

---

### **21. Children's Health and Pediatric Care**

**Description**:

Disinformation targeting children's health including vaccines, fever management, antibiotic use, developmental conditions (autism, ADHD), nutrition, and general pediatric care. This category is particularly dangerous because it can lead parents to make decisions that directly harm their children's health. Distinct from Category 3 (COVID-19 and Vaccination) which focuses specifically on COVID-19; this category encompasses all childhood vaccines and broader pediatric health disinformation.

**Heuristics**:

- Claims that childhood vaccines cause autism, infertility, contain microchips, or alter DNA
- Assertions that natural infection is always preferable to vaccination
- Conspiracy claims that pediatricians are financially motivated to vaccinate/prescribe
- Promotion of dangerous "treatments" for autism including bleach (CDS/MMS), chelation, restrictive diets
- Claims that common medications (acetaminophen, ibuprofen) are poison
- Promotion of essential oils, homeopathy, or herbs as replacements for medical treatment
- Claims that vaccines cause a hidden wave of harm being covered up
- Promotion of homemade infant formula as superior to commercial formula
- Claims that ADHD doesn't exist or is an invention to sell medications
- Use of "censored video" narrative to build credibility for anti-vaccine content

**Examples**:

- *Spanish*: "No le pongas esa vacuna nueva a tu bebé. Nirsevimab es experimental y nadie sabe los efectos a largo plazo. Big Pharma solo quiere ganar dinero con nuestros hijos."
- *Arabic*: "لا تعطي طفلك هذا اللقاح الجديد. إنه تجريبي ولا أحد يعرف آثاره على المدى الطويل."

---

## Additional Instructions

- **Maximize Reliability**: Carefully apply the heuristics to ensure accurate identification of potential disinformation.
- **Cultural Sensitivity**: Be mindful of cultural nuances and avoid stereotypes or generalizations.
- **Efficiency**: Focus on relevant content that may contain disinformation according to the heuristics provided.

---

## Final Notes

By meticulously following these instructions and applying the heuristics across all disinformation categories, you will effectively identify potential disinformation in the provided transcription. Your culturally sensitive approach will ensure that the analysis is relevant and respectful to the Spanish and Arabic-speaking immigrant communities in the USA. Please ensure that the `start_time` and `end_time` fields are accurate and correspond to those in the transcription. This accuracy is crucial for the subsequent processing stages in the pipeline.

---

# Example of Output (Hypothetical)

```json
{{
  "flagged_snippets": [
    {{
      "start_time": "05:30",
      "end_time": "07:15",
      "transcription": "La 'plandemia' es una excusa para controlarnos con 'microchips en vacunas'.",
      "explanation": "The speaker claims that the pandemic is a planned event used to control the population by implanting microchips through vaccines. This promotes unfounded conspiracy theories about COVID-19 and vaccination.",
      "disinformation_categories": ["COVID-19 and Vaccination", "Conspiracy Theories"],
      "keywords_detected": ["plandemia", "microchips en vacunas"]
    }},
    {{
      "start_time": "07:15",
      "end_time": "08:00",
      "transcription": "Los 'extranjeros ilegales' están causando problemas económicos en nuestro país.",
      "explanation": "The speaker asserts that illegal immigrants are causing economic problems in the country, depicting immigrants as a burden without providing evidence. This aligns with disinformation regarding immigration policies.",
      "disinformation_categories": ["Immigration Policies"],
      "keywords_detected": ["extranjeros ilegales", "problemas económicos"]
    }}
  ]
}}
```

This example illustrates how to structure the output for the flagged snippets. Use this as a guide for formatting your outputs while ensuring compliance with all instructions and policies.

---

# Instructions

- Please analyze the provided timestamped transcription for potential disinformation. Use the provided heuristics to identify and flag any disinformation snippets.
- Ensure that the `start_time` and `end_time` fields are accurate and correspond to those in the timestamped transcription. This accuracy is crucial for the subsequent processing stages in the pipeline.
  - The `start_time` must always be less than or equal to the `end_time`.
  - Both `start_time` and `end_time` must be within the range of the timestamped transcription.

---

# Calibration: What Clears the Bar

Flag a claim when a fact-checker would want to check it and it is likely false, unsupported by evidence, or misleading. It does not need to be provably false from the transcription alone. Hypothetical borderline cases that MUST be flagged:

- Health or product claim without evidence: "Este té de moringa limpia la sangre, previene la diabetes y lo pueden tomar las embarazadas y los bebés sin ningún riesgo." Flag: unsubstantiated disease-prevention claim and an unsupported safety claim for pregnancy and infants.
- Pseudoscience or folk belief stated as medical fact: "Si usted se baña con el estómago lleno le da una embolia, eso está comprobado por los médicos." Flag: a myth presented as established medicine.
- False or distorted characterization of a party, group or policy stated as fact: "Los republicanos quieren quitarle el Seguro Social a todos los jubilados." Flag: presents an unsupported claim about a party's position as fact. Apply the same standard whichever side is targeted.
- Faith healing presented as a cure for a diagnosed disease or as a replacement for medical care: "Si el médico te dijo que tienes diabetes, no te preocupes: el Señor ya te sanó, ya no necesitas la insulina." Flag: a health claim inside a religious message that can lead listeners away from treatment.
- A supplement, device or test promoted as treating, preventing or diagnosing disease without evidence, including in ads: "Con este aparato de biorresonancia detectamos cualquier enfermedad en cinco minutos, sin análisis de sangre." Flag: unsupported diagnostic and medical claim.
- Established science denied as fact, including in ads and sermons: "Está comprobado que el ser humano nunca llegó a la Luna." Flag: contradicts established evidence.

Do NOT flag:

- News about current events, office-holders or conflicts only because you do not recognize them. Treat the recording date as the present; events after your training data may be real. Flag news only when it contradicts the knowledge base, contradicts itself, or matches a disinformation narrative in the heuristics.
- Opinions, prayers, or moral and religious teaching that make no factual claim about health, science, history, law or public affairs.
  A religious message that says a disease is cured, or that medical treatment is not needed, does make a health claim and must be flagged.

---

# Self-Review Process

Before finalizing your output, complete this validation checklist:

1. **Coverage Check**
   - Have I gone through the whole transcription, including advertisements, call-ins, interviews and sermons?
   - Have I flagged every claim that is plausibly false, unsubstantiated, or misleading under the heuristics, even when I cannot prove it false from the transcription alone? A later stage fact-checks every flag, so a missed claim costs more than a flag that turns out to be accurate.
   - Health and product claims without evidence (cures, disease prevention, safety for pregnancy or infants), pseudoscience stated as fact, and false or distorted characterizations of parties, groups or policies all count.
   - If the answer to any of these is "no," go back and add the missing snippets.

2. **Context Review**
   - Have I captured sufficient context before and after each snippet?
   - Does the context change the interpretation of the flagged content?
   - Have I accurately determined the snippet boundaries?

3. **Final Verification**
   Answer each with "yes" before proceeding:
   - [ ] Each flagged snippet contains at least one specific claim that is plausibly false, unsubstantiated, or misleading
   - [ ] Timestamps are accurate and properly formatted
   - [ ] Explanations name the specific claim and why it is likely false or misleading
   - [ ] I have not flagged pure opinion, or statements of faith that make no factual claim
   - [ ] I have not skipped a claim only because it is not demonstrably false

If any verification fails, revise your analysis accordingly.

---

# Knowledge Base: Verified Facts

The following are verified facts from our knowledge base. Use them to:
1. Better detect content that contradicts these verified facts (likely disinformation)
2. Avoid flagging content that aligns with these verified facts as disinformation
3. If a claim in the transcription matches a verified fact below, do NOT flag it

Found related knowledge entries:
{kb_context}

---

# Transcription Input

Here is the metadata of the transcription:

{metadata}

Here is the timestamped transcription:

{timestamped_transcription}
