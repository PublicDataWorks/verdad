"""Build prompt variants v1..v4 from the production Stage 1 detection prompt (repo is read only)."""
import re, shutil
from pathlib import Path

SRC = Path("/Users/j/GitHub/verdad/prompts/stage_1/main")
HERE = Path(__file__).resolve().parent
FILES = ["detection_system_instruction.md", "detection_user_prompt.md", "detection_output_schema.json"]

prod_sys = (SRC / FILES[0]).read_text()
prod_up = (SRC / FILES[1]).read_text()


def rep(s, a, b):
    assert s.count(a) == 1, a[:80]
    return s.replace(a, b)


# ---- v1: recall-first system instruction + self-review (H1, H2)
SYS_OLD = ("Your role is to identify specific, demonstrably false claims while carefully distinguishing between "
           "controversial content and actual disinformation. You must provide detailed evidence for any flagged content")
SYS_NEW = ("You are the screening stage of a pipeline: every snippet you flag is fact-checked in depth by a later "
           "verification stage, which discards flags that turn out to be accurate. Your role is to surface every claim "
           "that is plausibly false, unsubstantiated, or misleading in a way that could harm listeners, without flagging "
           "pure opinion or statements of faith that make no factual claim. You must provide clear evidence for any flagged content")

SR_OLD = prod_up[prod_up.index("1. **False Claims Verification**"):prod_up.index("2. **Context Review**")]
SR_NEW = """1. **Coverage Check**
   - Have I gone through the whole transcription, including advertisements, call-ins, interviews and sermons?
   - Have I flagged every claim that is plausibly false, unsubstantiated, or misleading under the heuristics, even when I cannot prove it false from the transcription alone? A later stage fact-checks every flag, so a missed claim costs more than a flag that turns out to be accurate.
   - Health and product claims without evidence (cures, disease prevention, safety for pregnancy or infants), pseudoscience stated as fact, and false or distorted characterizations of parties, groups or policies all count.
   - If the answer to any of these is "no," go back and add the missing snippets.

"""
FV_OLD = """   - [ ] Each flagged snippet contains demonstrably false claims
   - [ ] Timestamps are accurate and properly formatted
   - [ ] Explanations clearly identify specific false claims
   - [ ] I have distinguished between controversial content and actual disinformation
   - [ ] My analysis would be defensible to fact-checkers"""
FV_NEW = """   - [ ] Each flagged snippet contains at least one specific claim that is plausibly false, unsubstantiated, or misleading
   - [ ] Timestamps are accurate and properly formatted
   - [ ] Explanations name the specific claim and why it is likely false or misleading
   - [ ] I have not flagged pure opinion, or statements of faith that make no factual claim
   - [ ] I have not skipped a claim only because it is not demonstrably false"""

v1_sys = rep(prod_sys, SYS_OLD, SYS_NEW)
v1_up = rep(rep(prod_up, SR_OLD, SR_NEW), FV_OLD, FV_NEW)

# ---- v2: v1 + calibration examples and a do-not-flag rule for unfamiliar current events (H3, H6)
CAL = """# Calibration: What Clears the Bar

Flag a claim when a fact-checker would want to check it and it is likely false, unsupported by evidence, or misleading. It does not need to be provably false from the transcription alone. Hypothetical borderline cases that MUST be flagged:

- Health or product claim without evidence: "Este té de moringa limpia la sangre, previene la diabetes y lo pueden tomar las embarazadas y los bebés sin ningún riesgo." Flag: unsubstantiated disease-prevention claim and an unsupported safety claim for pregnancy and infants.
- Pseudoscience or folk belief stated as medical fact: "Si usted se baña con el estómago lleno le da una embolia, eso está comprobado por los médicos." Flag: a myth presented as established medicine.
- False or distorted characterization of a party, group or policy stated as fact: "Los republicanos quieren quitarle el Seguro Social a todos los jubilados." Flag: presents an unsupported claim about a party's position as fact. Apply the same standard whichever side is targeted.

Do NOT flag:

- News about current events, office-holders or conflicts only because you do not recognize them. Treat the recording date as the present; events after your training data may be real. Flag news only when it contradicts the knowledge base, contradicts itself, or matches a disinformation narrative in the heuristics.
- Opinions, prayers, or moral and religious teaching that make no factual claim about health, science, history, law or public affairs.

---

# Self-Review Process"""
v2_up = rep(v1_up, "# Self-Review Process", CAL)

# ---- v3: v2 + in-order pass, one flag per distinct claim (H4)
INS_OLD = """- Please analyze the provided timestamped transcription for potential disinformation. Use the provided heuristics to identify and flag any disinformation snippets.
- Ensure that"""
INS_NEW = """- Please analyze the provided timestamped transcription for potential disinformation. Use the provided heuristics to identify and flag any disinformation snippets.
- Go through the transcription in order, from the first timestamp to the last. Advertisements, call-in segments and sermons often contain several separate claims: flag each distinct claim as its own snippet instead of merging claims that are more than about a minute apart into one long snippet. Keep each snippet to the sentences that carry the claim plus the context needed to understand it (usually 20 to 90 seconds).
- Ensure that"""
v3_up = rep(v2_up, INS_OLD, INS_NEW)

# ---- v4: v2 instructions, condensed heuristics: drop per-category keyword lists and the inline JSON schema (H5)
v4_up = re.sub(r"\*\*Keywords/Phrases\*\*:.*?(?=\*\*Heuristics\*\*:)", "", v2_up, flags=re.S)
v4_up = re.sub(r"# JSON Schema\n.*?```\n\n(?=# Disinformation Detection Heuristics)",
               "# JSON Schema\n\nThe output schema is enforced by the API; return only the `flagged_snippets` object.\n\n",
               v4_up, flags=re.S)
v4_up = rep(v4_up, "including culturally relevant examples in **Spanish** and **Arabic**.",
            "including culturally relevant examples in **Spanish** and **Arabic**. Keywords are not listed; detect the claims by meaning in either language.")

variants = {"v1": (v1_sys, v1_up), "v2": (v1_sys, v2_up), "v3": (v1_sys, v3_up), "v4": (v1_sys, v4_up)}
for name, (sys_txt, up_txt) in variants.items():
    d = HERE / name
    d.mkdir(exist_ok=True)
    (d / FILES[0]).write_text(sys_txt)
    (d / FILES[1]).write_text(up_txt)
    shutil.copy(SRC / FILES[2], d / FILES[2])
    # placeholders must survive .format()
    up_txt.format(kb_context="", metadata="", timestamped_transcription="")
    print(name, len(sys_txt), len(up_txt))
print("prod", len(prod_sys), len(prod_up))
