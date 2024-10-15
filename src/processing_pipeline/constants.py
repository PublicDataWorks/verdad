import json


def get_user_prompt_for_stage_1():
    return open("prompts/Stage_1_detection-prompt.md", "r").read()


def get_system_instruction_for_stage_1():
    return open("prompts/Stage_1-system-instruction.md", "r").read()


def get_output_schema_for_stage_1():
    return json.load(open("prompts/Stage_1-output_schema.json", "r"))


def get_user_prompt_for_stage_3():
    return open("prompts/Stage_3_analysis-prompt.md", "r").read()


def get_system_instruction_for_stage_3():
    return open("prompts/Stage_3_system-instruction.md", "r").read()


def get_output_schema_for_stage_3():
    return json.load(open("prompts/Stage_3-output_schema.json", "r"))


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

    # Print system instruction for stage 3
    # system_instruction_for_stage_3 = get_system_instruction_for_stage_3()
    # print(system_instruction_for_stage_3)

    # Print user prompt for stage 3
    user_prompt_for_stage_3 = get_user_prompt_for_stage_3()
    print(user_prompt_for_stage_3)

    # Print output schema for stage 3
    # output_schema_for_stage_3 = get_output_schema_for_stage_3()
    # print(json.dumps(output_schema_for_stage_3, indent=2))
