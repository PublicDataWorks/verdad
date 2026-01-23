#!/usr/bin/env python3
"""
Load prompt files from the prompts/ directory into the PostgreSQL database.
This script reads markdown and JSON files and inserts them into the prompt_versions table.
"""

import json
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.processing_pipeline.postgres_client import PostgresClient


def read_file(filepath):
    """Read file content."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


def read_json(filepath):
    """Read JSON file content."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_prompts():
    """Load all prompts into the database."""
    db = PostgresClient()
    prompts_dir = project_root / 'prompts'
    
    print("🚀 Loading prompts into database...")
    
    # Define prompt configurations
    prompt_configs = [
        {
            'stage': 'gemini_timestamped_transcription',
            'version_number': 1,
            'llm_model': 'gemini-2.5-flash',
            'prompt_file': 'Gemini_timestamped_transcription_generation_prompt.md',
            'system_instruction_file': None,
            'output_schema_file': 'Timestamped_transcription_generation_output_schema.json',
            'change_explanation': 'Initial prompt version for Gemini timestamped transcription'
        },
        {
            'stage': 'stage_1',
            'version_number': 1,
            'llm_model': 'gemini-2.5-flash',
            'prompt_file': 'Stage_1_detection_prompt.md',
            'system_instruction_file': 'Stage_1_system_instruction.md',
            'output_schema_file': 'Stage_1_output_schema.json',
            'change_explanation': 'Initial prompt version for Stage 1 detection'
        },
        {
            'stage': 'stage_3',
            'version_number': 1,
            'llm_model': 'gemini-2.5-flash',
            'prompt_file': 'Stage_3_analysis_prompt.md',
            'system_instruction_file': 'Stage_3_system_instruction.md',
            'output_schema_file': 'Stage_3_output_schema.json',
            'change_explanation': 'Initial prompt version for Stage 3 analysis'
        },
        {
            'stage': 'stage_4',
            'version_number': 1,
            'llm_model': 'gemini-2.5-flash',
            'prompt_file': 'Stage_4_review_prompt.md',
            'system_instruction_file': 'Stage_4_system_instruction.md',
            'output_schema_file': 'Stage_4_output_schema.json',
            'change_explanation': 'Initial prompt version for Stage 4 review'
        }
    ]
    
    # Load each prompt configuration
    for config in prompt_configs:
        stage = config['stage']
        
        # Check if prompt already exists
        existing = db._execute(
            "SELECT id FROM prompt_versions WHERE stage = %s AND is_active = TRUE",
            (stage,),
            fetch_one=True
        )
        
        if existing:
            print(f"⏭️  Skipping {stage} - already exists")
            continue
        
        # Read prompt text
        prompt_text = read_file(prompts_dir / config['prompt_file'])
        
        # Read system instruction if exists
        system_instruction = None
        if config['system_instruction_file']:
            system_instruction = read_file(prompts_dir / config['system_instruction_file'])
        
        # Read output schema if exists
        output_schema = None
        if config['output_schema_file']:
            output_schema = read_json(prompts_dir / config['output_schema_file'])
        
        # Insert into database
        db._execute(
            """
            INSERT INTO prompt_versions (
                stage,
                version_number,
                llm_model,
                prompt_text,
                system_instruction,
                output_schema,
                is_active,
                change_explanation
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                stage,
                config['version_number'],
                config['llm_model'],
                prompt_text,
                system_instruction,
                json.dumps(output_schema) if output_schema else None,
                True,
                config['change_explanation']
            ),
            fetch_one=False
        )
        
        print(f"✅ Loaded {stage} prompt (v{config['version_number']})")
    
    # Load heuristics
    heuristics_configs = [
        {
            'stage': 'stage_1',
            'version_number': 1,
            'content_file': 'Stage_1_heuristics.md',
            'change_explanation': 'Initial heuristics for Stage 1'
        },
        {
            'stage': 'stage_3',
            'version_number': 1,
            'content_file': 'Stage_3_heuristics.md',
            'change_explanation': 'Initial heuristics for Stage 3'
        }
    ]
    
    for config in heuristics_configs:
        stage = config['stage']
        
        # Check if heuristics already exist
        existing = db._execute(
            "SELECT id FROM heuristics WHERE stage = %s AND is_active = TRUE",
            (stage,),
            fetch_one=True
        )
        
        if existing:
            print(f"⏭️  Skipping {stage} heuristics - already exists")
            continue
        
        # Read heuristics content
        content = read_file(prompts_dir / config['content_file'])
        
        # Insert into database
        db._execute(
            """
            INSERT INTO heuristics (
                stage,
                version_number,
                content,
                is_active,
                change_explanation
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                stage,
                config['version_number'],
                content,
                True,
                config['change_explanation']
            ),
            fetch_one=False
        )
        
        print(f"✅ Loaded {stage} heuristics (v{config['version_number']})")
    
    db.close()
    print("\n🎉 All prompts and heuristics loaded successfully!")


if __name__ == '__main__':
    load_prompts()
