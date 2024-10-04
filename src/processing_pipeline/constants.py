import json


def get_user_prompt_for_stage_1():
    return open("prompts/Stage_1_detection-prompt.md", "r").read()


def get_system_instruction_for_stage_1():
    return open("prompts/Stage_1-system-instruction.md", "r").read()


def get_output_schema_for_stage_1():
    return json.load(open("prompts/Stage_1-output_schema.json", "r"))["components"]["schemas"][
        "DisinformationDetectionOutput"
    ]


def get_user_prompt_for_stage_2():
    return open("prompts/Stage_2_analysis-prompt.md", "r").read()


def get_system_instruction_for_stage_2():
    return open("prompts/Stage_2_system-instruction.md", "r").read()


def get_output_schema_for_stage_2():
    return json.load(open("prompts/Stage_2-output_schema.json", "r"))["components"]["schemas"][
        "DisinformationAnalysisOutput"
    ]


if __name__ == "__main__":
    # Print the output schema for stage 1
    # output_schema_for_stage_1 = get_output_schema_for_stage_1()
    # print(json.dumps(output_schema_for_stage_1, indent=2))

    # Print system instruction for stage 1
    # system_instruction_for_stage_1 = get_system_instruction_for_stage_1()
    # print(system_instruction_for_stage_1)

    # Print user prompt for stage 1
    # user_prompt_for_stage_1 = get_user_prompt_for_stage_1()
    # print(user_prompt_for_stage_1)

    # Print system instruction for stage 2
    # system_instruction_for_stage_2 = get_system_instruction_for_stage_2()
    # print(system_instruction_for_stage_2)

    # Print user prompt for stage 2
    # user_prompt_for_stage_2 = get_user_prompt_for_stage_2()
    # print(user_prompt_for_stage_2)

    # Print output schema for stage 2
    output_schema_for_stage_2 = get_output_schema_for_stage_2()
    print(json.dumps(output_schema_for_stage_2, indent=2))

    pass
