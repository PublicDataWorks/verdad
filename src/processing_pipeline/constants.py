import json

GEMINI_1_5_PRO = "gemini-1.5-pro-002"
GEMINI_1_5_FLASH = "gemini-1.5-flash"
GEMINI_2_5_FLASH = "gemini-2.5-flash"
GEMINI_2_5_PRO = "gemini-2.5-pro"


def get_transcription_prompt_for_stage_1_preprocess():
    return open("prompts/Stage_1_Preprocess_transcription_prompt.md", "r").read()


def get_detection_prompt_for_stage_1():
    return open("prompts/Stage_1_detection_prompt.md", "r").read()


def get_detection_prompt_for_stage_1_preprocess():
    return open("prompts/Stage_1_Preprocess_detection_prompt.md", "r").read()


def get_system_instruction_for_stage_1():
    return open("prompts/Stage_1_system_instruction.md", "r").read()


def get_system_instruction_for_stage_1_preprocess():
    return open("prompts/Stage_1_Preprocess_system_instruction.md", "r").read()


def get_output_schema_for_stage_1():
    return json.load(open("prompts/Stage_1_output_schema.json", "r"))


def get_output_schema_for_stage_1_preprocess():
    return json.load(open("prompts/Stage_1_Preprocess_output_schema.json", "r"))


def get_user_prompt_for_stage_3():
    return open("prompts/Stage_3_analysis_prompt.md", "r").read()


def get_system_instruction_for_stage_3():
    return open("prompts/Stage_3_system_instruction.md", "r").read()


def get_output_schema_for_stage_3():
    return json.load(open("prompts/Stage_3_output_schema.json", "r"))


def get_timestamped_transcription_generation_prompt():
    return open("prompts/Timestamped_transcription_generation_prompt.md", "r").read()


def get_timestamped_transcription_generation_output_schema():
    return json.load(open("prompts/Timestamped_transcription_generation_output_schema.json", "r"))


def get_system_instruction_for_stage_4():
    return open("prompts/Stage_4_system_instruction.md", "r").read()


def get_user_prompt_for_stage_4():
    return open("prompts/Stage_4_review_prompt.md", "r").read()


def get_output_schema_for_stage_4():
    return json.load(open("prompts/Stage_4_output_schema.json", "r"))


def get_gemini_2_5_pro_transcription_generation_prompt():
    return open("prompts/Gemini_2_5_pro_transcription_generation_prompt.md", "r").read()


if __name__ == "__main__":
    # Print the transcription prompt for stage 1 Preprocess
    # transcription_prompt_for_stage_1_preprocess = get_transcription_prompt_for_stage_1_preprocess()
    # print(transcription_prompt_for_stage_1_preprocess)

    # Print the output schema for stage 1 preprocess
    # output_schema_for_stage_1_preprocess = get_output_schema_for_stage_1_preprocess()
    # print(json.dumps(output_schema_for_stage_1_preprocess, indent=2))

    # Print system instruction for stage 1 preprocess
    # system_instruction_for_stage_1_preprocess = get_system_instruction_for_stage_1_preprocess()
    # print(system_instruction_for_stage_1_preprocess)

    # Print the detection prompt for stage 1 preprocess
    # detection_prompt_for_stage_1_preprocess = get_detection_prompt_for_stage_1_preprocess()
    # print(detection_prompt_for_stage_1_preprocess)

    # Print the output schema for stage 1
    # output_schema_for_stage_1 = get_output_schema_for_stage_1()
    # print(json.dumps(output_schema_for_stage_1, indent=2))

    # Print system instruction for stage 1
    # system_instruction_for_stage_1 = get_system_instruction_for_stage_1()
    # print(system_instruction_for_stage_1)

    # Print detection prompt for stage 1
    # detection_prompt_for_stage_1 = get_detection_prompt_for_stage_1()
    # print(detection_prompt_for_stage_1)

    # Print system instruction for stage 3
    # system_instruction_for_stage_3 = get_system_instruction_for_stage_3()
    # print(system_instruction_for_stage_3)

    # Print user prompt for stage 3
    # user_prompt_for_stage_3 = get_user_prompt_for_stage_3()
    # print(user_prompt_for_stage_3)

    # Print output schema for stage 3
    # output_schema_for_stage_3 = get_output_schema_for_stage_3()
    # print(json.dumps(output_schema_for_stage_3, indent=2))

    # Print timestamped transcription generation prompt
    # timestamped_transcription_generation_prompt = get_timestamped_transcription_generation_prompt()
    # print(timestamped_transcription_generation_prompt)

    # Print timestamped transcription generation output schema
    # timestamped_transcription_generation_output_schema = get_timestamped_transcription_generation_output_schema()
    # print(json.dumps(timestamped_transcription_generation_output_schema, indent=2))

    # Print system instruction for stage 4
    # system_instruction_for_stage_4 = get_system_instruction_for_stage_4()
    # print(system_instruction_for_stage_4)

    # # Print user prompt for stage 4
    # user_prompt_for_stage_4 = get_user_prompt_for_stage_4()
    # print(user_prompt_for_stage_4)

    # Print output schema for stage 4
    # output_schema_for_stage_4 = get_output_schema_for_stage_4()
    # print(json.dumps(output_schema_for_stage_4, indent=2))

    # Print gemini 2.5 pro transcription generation prompt
    gemini_2_5_pro_transcription_generation_prompt = get_gemini_2_5_pro_transcription_generation_prompt()
    print(gemini_2_5_pro_transcription_generation_prompt)
