create extension if not exists "fuzzystrmatch" with schema "extensions";

create extension if not exists "http" with schema "extensions";

create extension if not exists "hypopg" with schema "extensions";

create extension if not exists "index_advisor" with schema "extensions";

create extension if not exists "insert_username" with schema "extensions";

create extension if not exists "pg_hashids" with schema "extensions";

create extension if not exists "pg_jsonschema" with schema "extensions";

create extension if not exists "pgroonga" with schema "extensions";

create extension if not exists "unaccent" with schema "extensions";

create extension if not exists "vector" with schema "extensions";


create extension if not exists "mansueli-supa_queue" with schema "public" version '1.0.4';

create extension if not exists "moddatetime" with schema "public" version '1.0';

create extension if not exists "pg_trgm" with schema "public" version '1.6';

create extension if not exists "supabase-dbdev" with schema "public" version '0.0.5';

create type "public"."processing_status" as enum ('New', 'Processing', 'Processed', 'Error');

create table "public"."audio_files" (
    "id" uuid not null default gen_random_uuid(),
    "created_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "updated_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "radio_station_name" text not null,
    "radio_station_code" text not null,
    "location_state" text,
    "location_city" text,
    "recorded_at" timestamp with time zone not null,
    "recording_day_of_week" text not null,
    "file_path" text not null,
    "file_size" bigint not null,
    "status" processing_status not null default 'New'::processing_status,
    "error_message" text
);


alter table "public"."audio_files" enable row level security;

create table "public"."draft_audio_files" (
    "audio_file_id" uuid not null default gen_random_uuid(),
    "radio_station_name" text not null,
    "radio_station_code" text not null,
    "location_state" text not null,
    "location_city" text not null,
    "broadcast_date" date not null,
    "broadcast_time" time without time zone not null,
    "day_of_week" text not null,
    "local_time_zone" text not null,
    "file_path" text not null,
    "created_at" timestamp with time zone default now()
);


create table "public"."draft_heuristics" (
    "heuristic_id" uuid not null default gen_random_uuid(),
    "version_number" integer not null,
    "content" text not null,
    "llm_model" text not null,
    "created_at" timestamp with time zone default now(),
    "updated_at" timestamp with time zone default now(),
    "change_explanation" text
);


create table "public"."draft_prompt_versions" (
    "prompt_id" uuid not null default gen_random_uuid(),
    "stage" integer not null,
    "version_number" integer not null,
    "llm_model" text not null,
    "prompt_text" text not null,
    "created_at" timestamp with time zone default now(),
    "updated_at" timestamp with time zone default now(),
    "change_explanation" text
);


create table "public"."draft_snippets" (
    "snippet_id" uuid not null default gen_random_uuid(),
    "audio_file_id" uuid not null,
    "start_time" time without time zone not null,
    "end_time" time without time zone not null,
    "audio_clip_path" text not null,
    "transcription" text,
    "translation" text,
    "title" text,
    "summary" text,
    "explanation" text,
    "disinformation_categories" text[],
    "language_primary" text,
    "language_dialect" text,
    "language_register" text,
    "context_before" text,
    "context_after" text,
    "confidence_overall" integer,
    "confidence_categories" jsonb,
    "emotional_tone" jsonb,
    "created_at" timestamp with time zone default now(),
    "updated_at" timestamp with time zone default now()
);


create table "public"."draft_user_feedback" (
    "feedback_id" uuid not null default gen_random_uuid(),
    "snippet_id" uuid not null,
    "user_id" uuid not null,
    "label" text,
    "upvotes" integer default 0,
    "comment" text,
    "created_at" timestamp with time zone default now(),
    "updated_at" timestamp with time zone default now()
);


create table "public"."draft_users" (
    "user_id" uuid not null default gen_random_uuid(),
    "email" text not null,
    "password_hash" text not null,
    "display_name" text,
    "role" text default 'user'::text,
    "created_at" timestamp with time zone default now(),
    "updated_at" timestamp with time zone default now()
);


create table "public"."label_upvotes" (
    "id" uuid not null default gen_random_uuid(),
    "created_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "updated_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "upvoted_by" uuid not null,
    "snippet_label" uuid not null
);


alter table "public"."label_upvotes" enable row level security;

create table "public"."labels" (
    "id" uuid not null default gen_random_uuid(),
    "created_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "updated_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "text" text not null,
    "created_by" uuid,
    "is_ai_suggested" boolean not null default false
);


alter table "public"."labels" enable row level security;

create table "public"."profiles" (
    "id" uuid not null,
    "name" text,
    "email" text,
    "avatar_url" text,
    "updated_at" timestamp with time zone,
    "first_name" text,
    "last_name" text
);


alter table "public"."profiles" enable row level security;

create table "public"."snippet_labels" (
    "id" uuid not null default gen_random_uuid(),
    "created_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "updated_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "snippet" uuid not null,
    "label" uuid not null,
    "applied_by" uuid
);


alter table "public"."snippet_labels" enable row level security;

create table "public"."snippets" (
    "id" uuid not null default gen_random_uuid(),
    "created_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "updated_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "audio_file" uuid,
    "start_time" time without time zone,
    "end_time" time without time zone,
    "file_path" text not null,
    "file_size" bigint not null,
    "transcription" text,
    "translation" text,
    "title" text,
    "summary" text,
    "explanation" text,
    "disinformation_categories" text[],
    "keywords_detected" text[],
    "language" jsonb,
    "confidence_scores" jsonb,
    "emotional_tone" jsonb[],
    "status" processing_status not null default 'New'::processing_status,
    "error_message" text,
    "context" jsonb,
    "stage_1_llm_response" uuid,
    "duration" time without time zone,
    "recorded_at" timestamp with time zone
);


alter table "public"."snippets" enable row level security;

create table "public"."stage_1_llm_responses" (
    "id" uuid not null default gen_random_uuid(),
    "created_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "updated_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "audio_file" uuid not null,
    "status" processing_status not null default 'New'::processing_status,
    "error_message" text,
    "detection_result" jsonb,
    "timestamped_transcription" jsonb,
    "initial_transcription" text,
    "initial_detection_result" jsonb
);


alter table "public"."stage_1_llm_responses" enable row level security;

create table "public"."user_star_snippets" (
    "id" uuid not null default gen_random_uuid(),
    "created_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "updated_at" timestamp with time zone not null default (now() AT TIME ZONE 'utc'::text),
    "user" uuid not null,
    "snippet" uuid not null
);


alter table "public"."user_star_snippets" enable row level security;

CREATE UNIQUE INDEX audio_files_id_key ON public.audio_files USING btree (id);

CREATE UNIQUE INDEX audio_files_pkey ON public.audio_files USING btree (id);

CREATE UNIQUE INDEX draft_audio_files_pkey ON public.draft_audio_files USING btree (audio_file_id);

CREATE UNIQUE INDEX draft_heuristics_pkey ON public.draft_heuristics USING btree (heuristic_id);

CREATE UNIQUE INDEX draft_prompt_versions_pkey ON public.draft_prompt_versions USING btree (prompt_id);

CREATE UNIQUE INDEX draft_snippets_pkey ON public.draft_snippets USING btree (snippet_id);

CREATE UNIQUE INDEX draft_user_feedback_pkey ON public.draft_user_feedback USING btree (feedback_id);

CREATE UNIQUE INDEX draft_users_email_key ON public.draft_users USING btree (email);

CREATE UNIQUE INDEX draft_users_pkey ON public.draft_users USING btree (user_id);

CREATE UNIQUE INDEX label_upvotes_pkey ON public.label_upvotes USING btree (id);

CREATE UNIQUE INDEX labels_content_key ON public.labels USING btree (text);

CREATE UNIQUE INDEX labels_pkey ON public.labels USING btree (id);

CREATE UNIQUE INDEX profiles_pkey ON public.profiles USING btree (id);

CREATE UNIQUE INDEX snippet_labels_pkey ON public.snippet_labels USING btree (id);

CREATE UNIQUE INDEX snippets_pkey ON public.snippets USING btree (id);

CREATE UNIQUE INDEX stage_1_llm_responses_pkey ON public.stage_1_llm_responses USING btree (id);

CREATE UNIQUE INDEX unique_snippet_label ON public.snippet_labels USING btree (snippet, label);

CREATE UNIQUE INDEX unique_stage_version ON public.draft_prompt_versions USING btree (stage, version_number);

CREATE UNIQUE INDEX unique_upvoted_by_snippet_label ON public.label_upvotes USING btree (upvoted_by, snippet_label);

CREATE UNIQUE INDEX unique_user_snippet ON public.user_star_snippets USING btree ("user", snippet);

CREATE UNIQUE INDEX unique_version_number ON public.draft_heuristics USING btree (version_number);

CREATE UNIQUE INDEX user_star_snippets_pkey ON public.user_star_snippets USING btree (id);

alter table "public"."audio_files" add constraint "audio_files_pkey" PRIMARY KEY using index "audio_files_pkey";

alter table "public"."draft_audio_files" add constraint "draft_audio_files_pkey" PRIMARY KEY using index "draft_audio_files_pkey";

alter table "public"."draft_heuristics" add constraint "draft_heuristics_pkey" PRIMARY KEY using index "draft_heuristics_pkey";

alter table "public"."draft_prompt_versions" add constraint "draft_prompt_versions_pkey" PRIMARY KEY using index "draft_prompt_versions_pkey";

alter table "public"."draft_snippets" add constraint "draft_snippets_pkey" PRIMARY KEY using index "draft_snippets_pkey";

alter table "public"."draft_user_feedback" add constraint "draft_user_feedback_pkey" PRIMARY KEY using index "draft_user_feedback_pkey";

alter table "public"."draft_users" add constraint "draft_users_pkey" PRIMARY KEY using index "draft_users_pkey";

alter table "public"."label_upvotes" add constraint "label_upvotes_pkey" PRIMARY KEY using index "label_upvotes_pkey";

alter table "public"."labels" add constraint "labels_pkey" PRIMARY KEY using index "labels_pkey";

alter table "public"."profiles" add constraint "profiles_pkey" PRIMARY KEY using index "profiles_pkey";

alter table "public"."snippet_labels" add constraint "snippet_labels_pkey" PRIMARY KEY using index "snippet_labels_pkey";

alter table "public"."snippets" add constraint "snippets_pkey" PRIMARY KEY using index "snippets_pkey";

alter table "public"."stage_1_llm_responses" add constraint "stage_1_llm_responses_pkey" PRIMARY KEY using index "stage_1_llm_responses_pkey";

alter table "public"."user_star_snippets" add constraint "user_star_snippets_pkey" PRIMARY KEY using index "user_star_snippets_pkey";

alter table "public"."audio_files" add constraint "audio_files_id_key" UNIQUE using index "audio_files_id_key";

alter table "public"."draft_heuristics" add constraint "unique_version_number" UNIQUE using index "unique_version_number";

alter table "public"."draft_prompt_versions" add constraint "draft_prompt_versions_stage_check" CHECK ((stage = ANY (ARRAY[1, 2]))) not valid;

alter table "public"."draft_prompt_versions" validate constraint "draft_prompt_versions_stage_check";

alter table "public"."draft_prompt_versions" add constraint "unique_stage_version" UNIQUE using index "unique_stage_version";

alter table "public"."draft_snippets" add constraint "draft_snippets_audio_file_id_fkey" FOREIGN KEY (audio_file_id) REFERENCES draft_audio_files(audio_file_id) ON DELETE CASCADE not valid;

alter table "public"."draft_snippets" validate constraint "draft_snippets_audio_file_id_fkey";

alter table "public"."draft_user_feedback" add constraint "draft_user_feedback_snippet_id_fkey" FOREIGN KEY (snippet_id) REFERENCES draft_snippets(snippet_id) ON DELETE CASCADE not valid;

alter table "public"."draft_user_feedback" validate constraint "draft_user_feedback_snippet_id_fkey";

alter table "public"."draft_user_feedback" add constraint "draft_user_feedback_user_id_fkey" FOREIGN KEY (user_id) REFERENCES draft_users(user_id) ON DELETE CASCADE not valid;

alter table "public"."draft_user_feedback" validate constraint "draft_user_feedback_user_id_fkey";

alter table "public"."draft_users" add constraint "draft_users_email_key" UNIQUE using index "draft_users_email_key";

alter table "public"."draft_users" add constraint "draft_users_role_check" CHECK ((role = ANY (ARRAY['user'::text, 'moderator'::text, 'admin'::text]))) not valid;

alter table "public"."draft_users" validate constraint "draft_users_role_check";

alter table "public"."label_upvotes" add constraint "label_upvotes_snippet_label_fkey" FOREIGN KEY (snippet_label) REFERENCES snippet_labels(id) ON DELETE CASCADE not valid;

alter table "public"."label_upvotes" validate constraint "label_upvotes_snippet_label_fkey";

alter table "public"."label_upvotes" add constraint "label_upvotes_upvoted_by_fkey" FOREIGN KEY (upvoted_by) REFERENCES auth.users(id) ON DELETE CASCADE not valid;

alter table "public"."label_upvotes" validate constraint "label_upvotes_upvoted_by_fkey";

alter table "public"."label_upvotes" add constraint "unique_upvoted_by_snippet_label" UNIQUE using index "unique_upvoted_by_snippet_label";

alter table "public"."labels" add constraint "labels_content_key" UNIQUE using index "labels_content_key";

alter table "public"."labels" add constraint "labels_created_by_fkey" FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE SET NULL not valid;

alter table "public"."labels" validate constraint "labels_created_by_fkey";

alter table "public"."profiles" add constraint "profiles_id_fkey" FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE not valid;

alter table "public"."profiles" validate constraint "profiles_id_fkey";

alter table "public"."snippet_labels" add constraint "snippet_labels_applied_by_fkey" FOREIGN KEY (applied_by) REFERENCES auth.users(id) ON DELETE SET NULL not valid;

alter table "public"."snippet_labels" validate constraint "snippet_labels_applied_by_fkey";

alter table "public"."snippet_labels" add constraint "snippet_labels_label_fkey" FOREIGN KEY (label) REFERENCES labels(id) ON DELETE CASCADE not valid;

alter table "public"."snippet_labels" validate constraint "snippet_labels_label_fkey";

alter table "public"."snippet_labels" add constraint "snippet_labels_snippet_fkey" FOREIGN KEY (snippet) REFERENCES snippets(id) ON DELETE CASCADE not valid;

alter table "public"."snippet_labels" validate constraint "snippet_labels_snippet_fkey";

alter table "public"."snippet_labels" add constraint "unique_snippet_label" UNIQUE using index "unique_snippet_label";

alter table "public"."snippets" add constraint "snippets_audio_file_fkey" FOREIGN KEY (audio_file) REFERENCES audio_files(id) ON DELETE SET NULL not valid;

alter table "public"."snippets" validate constraint "snippets_audio_file_fkey";

alter table "public"."snippets" add constraint "snippets_stage_1_llm_response_fkey" FOREIGN KEY (stage_1_llm_response) REFERENCES stage_1_llm_responses(id) ON DELETE SET NULL not valid;

alter table "public"."snippets" validate constraint "snippets_stage_1_llm_response_fkey";

alter table "public"."stage_1_llm_responses" add constraint "stage_1_llm_responses_audio_file_fkey" FOREIGN KEY (audio_file) REFERENCES audio_files(id) ON DELETE CASCADE not valid;

alter table "public"."stage_1_llm_responses" validate constraint "stage_1_llm_responses_audio_file_fkey";

alter table "public"."user_star_snippets" add constraint "unique_user_snippet" UNIQUE using index "unique_user_snippet";

alter table "public"."user_star_snippets" add constraint "user_star_snippets_snippet_fkey" FOREIGN KEY (snippet) REFERENCES snippets(id) ON DELETE CASCADE not valid;

alter table "public"."user_star_snippets" validate constraint "user_star_snippets_snippet_fkey";

alter table "public"."user_star_snippets" add constraint "user_star_snippets_user_fkey" FOREIGN KEY ("user") REFERENCES auth.users(id) ON DELETE CASCADE not valid;

alter table "public"."user_star_snippets" validate constraint "user_star_snippets_user_fkey";

set check_function_bodies = off;

CREATE OR REPLACE FUNCTION public.create_apply_and_upvote_label(snippet_id uuid, label_text text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE 
    current_user_id UUID; 
    snippet_label_id UUID; 
    label_id UUID; 
BEGIN 
    -- Check if the user is authenticated 
    current_user_id := auth.uid(); 
    IF current_user_id IS NULL THEN 
        RAISE EXCEPTION 'Only logged-in users can call this function'; 
    END IF;
    
    -- Ensure that the label exists
    SELECT id INTO label_id 
    FROM public.labels 
    WHERE text = label_text 
    LIMIT 1;

    IF label_id IS NULL THEN 
        -- Create the label
        INSERT INTO public.labels (created_by, is_ai_suggested, text) 
        VALUES (current_user_id, FALSE, label_text) 
        RETURNING id INTO label_id;
    END IF; 

    -- Ensure that the label is applied to the snippet
    SELECT id INTO snippet_label_id 
    FROM public.snippet_labels 
    WHERE snippet = snippet_id AND label = label_id; 

    IF snippet_label_id IS NULL THEN 
        -- Apply the label to the snippet
        INSERT INTO public.snippet_labels (snippet, label, applied_by) 
        VALUES (snippet_id, label_id, current_user_id)
        RETURNING id INTO snippet_label_id;
    END IF;

    -- Proceed to upvote the label
    INSERT INTO public.label_upvotes (upvoted_by, snippet_label)
    VALUES (current_user_id, snippet_label_id)
    ON CONFLICT (upvoted_by, snippet_label) DO NOTHING;    

    -- Return the result of the get_snippet_labels function 
    RETURN get_snippet_labels(snippet_id); 
END; 
$function$
;

CREATE OR REPLACE FUNCTION public.draft_update_timestamp()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
   NEW.updated_at = NOW();
   RETURN NEW;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.get_filtering_options()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE 
    current_user_id UUID; 
    result jsonb; 
BEGIN 
    -- Check if the user is authenticated 
    current_user_id := auth.uid(); 
    IF current_user_id IS NULL THEN 
        RAISE EXCEPTION 'Only logged-in users can call this function'; 
    END IF; 

    RETURN jsonb_build_object( 
        'languages', jsonb_build_array(), 
        'states', jsonb_build_array(), 
        'sources', jsonb_build_array(), 
        'labeled', jsonb_build_array( 
            jsonb_build_object('value', 'by_me', 'display', 'by Me'), 
            jsonb_build_object('value', 'by_others', 'display', 'by Others') 
        ), 
        'starred', jsonb_build_array( 
            jsonb_build_object('value', 'by_me', 'display', 'by Me'), 
            jsonb_build_object('value', 'by_others', 'display', 'by Others') 
        ), 
        'labels', jsonb_build_array() 
    ); 
END; 
$function$
;

CREATE OR REPLACE FUNCTION public.get_snippet(snippet_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    current_user_id UUID;
    result jsonb;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Return the specified snippet
    SELECT jsonb_build_object(
        'id', s.id,
        'recorded_at', s.recorded_at,
        'audio_file', jsonb_build_object(
            'id', a.id,
            'radio_station_name', a.radio_station_name,
            'radio_station_code', a.radio_station_code,
            'location_state', a.location_state,
            'location_city', a.location_city
        ),
        'duration', s.duration,
        'start_time', s.start_time,
        'end_time', s.end_time,
        'file_path', s.file_path,
        'file_size', s.file_size,
        'title', s.title,
        'summary', s.summary,
        'explanation', s.explanation,
        'confidence_scores', s.confidence_scores,
        'context', s.context,
        'starred_by_user', CASE
            WHEN us.id IS NOT NULL THEN true
            ELSE false
        END,
        'status', s.status,
        'error_message', s.error_message,
        'labels', get_snippet_labels(s.id) -> 'labels'
    ) INTO result
    FROM snippets s
    LEFT JOIN user_star_snippets us ON s.id = us.snippet AND us."user" = current_user_id
    LEFT JOIN audio_files a ON s.audio_file = a.id
    WHERE s.id = snippet_id;

    RETURN COALESCE(result, '{}'::jsonb);
END;
$function$
;

CREATE OR REPLACE FUNCTION public.get_snippet_labels(snippet_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    result jsonb;
    current_user_id UUID;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    SELECT jsonb_build_object(
        'snippet_id', snippet_id,
        'labels', jsonb_agg(jsonb_build_object(
            'id', l.id,
            'text', l.text,
            'created_by', l.created_by,
            'is_ai_suggested', l.is_ai_suggested,
            'applied_by', sl.applied_by,
            'applied_at', sl.created_at,
            'upvoted_by', COALESCE(upvote_users, '[]'::jsonb)
        ))
    ) INTO result
    FROM public.snippet_labels sl
    JOIN public.labels l ON sl.label = l.id
    LEFT JOIN (
        SELECT lu.snippet_label, jsonb_agg(jsonb_build_object(
            'id', u.id,
            'email', u.email,
            'upvoted_at', lu.created_at
        )) AS upvote_users
        FROM public.label_upvotes lu
        JOIN auth.users u ON lu.upvoted_by = u.id  -- Join to get user email
        WHERE lu.snippet_label IN (
            SELECT id FROM public.snippet_labels WHERE snippet = snippet_id
        )  -- Filter to only include upvotes for the specific snippet
        GROUP BY lu.snippet_label
    ) lu ON sl.id = lu.snippet_label
    WHERE sl.snippet = snippet_id;

    RETURN COALESCE(result, jsonb_build_object('snippet_id', snippet_id, 'labels', '[]'::jsonb));
END;
$function$
;

CREATE OR REPLACE FUNCTION public.get_snippets(page integer DEFAULT 0, page_size integer DEFAULT 10)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    current_user_id UUID;
    result jsonb;
    total_count INTEGER;
    total_pages INTEGER;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Retrieve the total count of snippets whose status is 'Processed'
    SELECT COUNT(*)
    INTO total_count
    FROM snippets s
    WHERE s.status = 'Processed';

    -- Calculate total pages
    total_pages := CEIL(total_count::FLOAT / page_size);

    -- Retrieve all snippets whose status is 'Processed' and paginate them
    SELECT jsonb_agg(snippet_data) INTO result
    FROM (
        SELECT
            s.id,
            s.recorded_at,
            s.duration,
            s.start_time,
            s.end_time,
            s.file_path,
            s.file_size,
            s.title,
            s.summary,
            s.explanation,
            s.confidence_scores,
            s.context,
            (get_snippet_labels(s.id) -> 'labels') AS labels,
            jsonb_build_object(
                'id', a.id,
                'radio_station_name', a.radio_station_name,
                'radio_station_code', a.radio_station_code,
                'location_state', a.location_state,
                'location_city', a.location_city
            ) AS audio_file,
            CASE
                WHEN us.id IS NOT NULL THEN true
                ELSE false
            END AS starred_by_user
        FROM snippets s
        LEFT JOIN audio_files a ON s.audio_file = a.id
        LEFT JOIN user_star_snippets us ON us.snippet = s.id AND us."user" = current_user_id
        WHERE s.status = 'Processed'
        ORDER BY s.recorded_at DESC
        LIMIT page_size OFFSET page * page_size
    ) AS snippet_data;

    -- Return the result along with total pages
    RETURN jsonb_build_object(
        'snippets', COALESCE(result, '[]'::jsonb),
        'total_pages', total_pages
    );
END;
$function$
;

CREATE OR REPLACE FUNCTION public.get_users()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    current_user_id UUID;
    result jsonb;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Return specified fields of all users from the auth schema
    SELECT jsonb_agg(jsonb_build_object(
        'id', u.id,
        'email', u.email,
        'raw_user_meta_data', u.raw_user_meta_data
    ))
    INTO result
    FROM auth.users u;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$function$
;

CREATE OR REPLACE FUNCTION public.get_users_by_emails(emails text[])
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$ 
DECLARE 
    current_user_id UUID;
    result jsonb; 
BEGIN 
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Return specified fields of users from the auth schema based on provided emails 
    SELECT jsonb_agg(jsonb_build_object( 
        'id', u.id, 
        'email', u.email, 
        'raw_user_meta_data', u.raw_user_meta_data 
    )) 
    INTO result 
    FROM auth.users u 
    WHERE u.email = ANY(emails); 

    RETURN COALESCE(result, '[]'::jsonb); 
END; 
$function$
;

CREATE OR REPLACE FUNCTION public.handle_new_user()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
BEGIN
  INSERT INTO public.profiles (id, name, email, avatar_url, updated_at)
  VALUES (
    NEW.id,
    COALESCE(
      NEW.raw_user_meta_data->>'name',
      NEW.raw_user_meta_data->>'full_name',
      NEW.email  -- Use email if no name is found in raw_user_meta_data
    ),
    NEW.email,
    COALESCE(
      NEW.raw_user_meta_data->>'avatar_url',
      NEW.raw_user_meta_data->>'picture',
      ''
    ),
    NEW.created_at
  );
  RETURN NEW;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.setup_profile(first_name text, last_name text, password text, avatar_url text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    current_user_id UUID;
    metadata jsonb;
    result jsonb;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Check minimum password length
    IF LENGTH(password) < 6 THEN
        RAISE EXCEPTION 'Password must be at least 6 characters long';
    END IF;

    -- Create the metadata JSON object
    metadata := jsonb_build_object(
        'first_name', first_name,
        'last_name', last_name,
        'name', CONCAT(first_name, ' ', last_name),
        'full_name', CONCAT(first_name, ' ', last_name),
        'email', (SELECT email FROM auth.users WHERE id = current_user_id),
        'picture', avatar_url,
        'avatar_url', avatar_url
    );

    -- Update the user's profile in the auth.users table
    UPDATE auth.users
    SET
        raw_user_meta_data = metadata,
        encrypted_password = crypt(password, gen_salt('bf')),
        updated_at = now() AT TIME ZONE 'utc'
    WHERE id = current_user_id;

    RETURN jsonb_build_object(
        'status', 'success',
        'message', 'Profile updated successfully'
    );
END;
$function$
;

CREATE OR REPLACE FUNCTION public.toggle_star_snippet(snippet_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    current_user_id UUID;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Check if the user has already starred the snippet
    IF EXISTS (
        SELECT 1
        FROM user_star_snippets
        WHERE "user" = current_user_id AND snippet = snippet_id
    ) THEN
        -- User has already starred the snippet, so remove the star
        DELETE FROM user_star_snippets
        WHERE "user" = current_user_id AND snippet = snippet_id;

        RETURN jsonb_build_object('data', jsonb_build_object('message', 'Snippet unstarred', 'snippet_starred', FALSE));
    ELSE
        -- User has not starred the snippet, so add a star
        INSERT INTO user_star_snippets ("user", snippet)
        VALUES (current_user_id, snippet_id);

        RETURN jsonb_build_object('data', jsonb_build_object('message', 'Snippet starred', 'snippet_starred', TRUE));
    END IF;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.toggle_upvote_label(snippet_id uuid, label_text text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    current_user_id UUID;
    label_id UUID;
    is_ai_suggested BOOLEAN;
    snippet_label_id UUID;
    label_upvote_id UUID;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Get the label ID and is_ai_suggested for the specified label text
    SELECT l.id, l.is_ai_suggested
    INTO label_id, is_ai_suggested
    FROM public.labels l
    WHERE l.text = label_text
    LIMIT 1;

    IF label_id IS NULL THEN
        RETURN jsonb_build_object('data', jsonb_build_object('message', 'The label does not exist'));
    END IF;

    -- Get the snippet_label_id for the specified snippet and label
    snippet_label_id := (SELECT id FROM public.snippet_labels WHERE snippet = snippet_id AND label = label_id LIMIT 1);

    IF snippet_label_id IS NULL THEN
        RETURN jsonb_build_object('data', jsonb_build_object('message', 'The label has not been applied to the snippet'));
    END IF;

    -- Check if the label has been upvoted by the current user
    label_upvote_id := (SELECT id FROM public.label_upvotes WHERE upvoted_by = current_user_id AND snippet_label = snippet_label_id LIMIT 1);

    IF label_upvote_id IS NOT NULL THEN
        -- If upvoted, remove the upvote
        DELETE FROM public.label_upvotes WHERE id = label_upvote_id;

        -- Check if the label should be deleted: the label was not suggested by AI and has zero upvotes
        IF is_ai_suggested = false AND
            (SELECT COUNT(*) FROM public.label_upvotes WHERE snippet_label = snippet_label_id) = 0 THEN
            -- Delete the label
            DELETE FROM public.labels WHERE id = label_id;
        END IF;

        RETURN jsonb_build_object('data', jsonb_build_object('message', 'Label has been un-upvoted successfully'));
    ELSE
        -- If not upvoted, add the upvote
        INSERT INTO public.label_upvotes (upvoted_by, snippet_label) VALUES (current_user_id, snippet_label_id);
        RETURN jsonb_build_object('data', jsonb_build_object('message', 'Label has been upvoted successfully'));
    END IF;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.undo_upvote_label(snippet_id uuid, label_text text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE 
    current_user_id UUID; 
    label_id UUID; 
    is_ai_suggested BOOLEAN; 
    snippet_label_id UUID; 
BEGIN 
    -- Check if the user is authenticated 
    current_user_id := auth.uid(); 
    IF current_user_id IS NULL THEN 
        RAISE EXCEPTION 'Only logged-in users can call this function'; 
    END IF; 

    -- Get the label ID and is_ai_suggested for the specified label text 
    SELECT l.id, l.is_ai_suggested 
    INTO label_id, is_ai_suggested 
    FROM public.labels l 
    WHERE l.text = label_text 
    LIMIT 1; 

    -- Get the snippet_label_id for the specified snippet and label 
    snippet_label_id := (SELECT id FROM public.snippet_labels WHERE snippet = snippet_id AND label = label_id LIMIT 1); 

    -- Delete the upvote record if it exists 
    DELETE FROM public.label_upvotes 
    WHERE upvoted_by = current_user_id 
      AND snippet_label = snippet_label_id; 

    -- Check if the label should be deleted 
    IF label_id IS NOT NULL THEN 
        -- Check if the label was not suggested by AI and has zero upvotes 
        IF is_ai_suggested = false AND 
           (SELECT COUNT(*) FROM public.label_upvotes WHERE snippet_label = snippet_label_id) = 0 THEN 
            -- Delete the label 
            DELETE FROM public.labels WHERE id = label_id; 
        END IF; 
    END IF; 

    -- Return the result of the get_snippet_labels function 
    RETURN get_snippet_labels(snippet_id); 
END; 
$function$
;

CREATE OR REPLACE FUNCTION public.upvote_label(snippet_id uuid, label_text text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE 
    current_user_id UUID; 
    snippet_label_id UUID; 
    label_id UUID; 
BEGIN 
    -- Check if the user is authenticated 
    current_user_id := auth.uid(); 
    IF current_user_id IS NULL THEN 
        RAISE EXCEPTION 'Only logged-in users can call this function'; 
    END IF;

    -- Check if the label exists 
    SELECT id INTO label_id 
    FROM public.labels 
    WHERE text = label_text 
    LIMIT 1; 
    IF label_id IS NULL THEN 
        RAISE EXCEPTION 'The label with text ''%'' does not exist.', label_text; 
    END IF; 

    -- Check if the found label has been applied to the given snippet or not 
    SELECT id INTO snippet_label_id 
    FROM public.snippet_labels 
    WHERE snippet = snippet_id AND label = label_id; 
    IF snippet_label_id IS NULL THEN 
        RAISE EXCEPTION 'The label ''%'' has not been applied to the given snippet yet.', label_text; 
    END IF; 

    -- Proceed to upvote the label
    INSERT INTO public.label_upvotes (upvoted_by, snippet_label)
    VALUES (current_user_id, snippet_label_id)
    ON CONFLICT (upvoted_by, snippet_label) DO NOTHING;

    -- Return the result of the get_snippet_labels function 
    RETURN get_snippet_labels(snippet_id); 
END; 
$function$
;

grant delete on table "public"."audio_files" to "anon";

grant insert on table "public"."audio_files" to "anon";

grant references on table "public"."audio_files" to "anon";

grant select on table "public"."audio_files" to "anon";

grant trigger on table "public"."audio_files" to "anon";

grant truncate on table "public"."audio_files" to "anon";

grant update on table "public"."audio_files" to "anon";

grant delete on table "public"."audio_files" to "authenticated";

grant insert on table "public"."audio_files" to "authenticated";

grant references on table "public"."audio_files" to "authenticated";

grant select on table "public"."audio_files" to "authenticated";

grant trigger on table "public"."audio_files" to "authenticated";

grant truncate on table "public"."audio_files" to "authenticated";

grant update on table "public"."audio_files" to "authenticated";

grant delete on table "public"."audio_files" to "service_role";

grant insert on table "public"."audio_files" to "service_role";

grant references on table "public"."audio_files" to "service_role";

grant select on table "public"."audio_files" to "service_role";

grant trigger on table "public"."audio_files" to "service_role";

grant truncate on table "public"."audio_files" to "service_role";

grant update on table "public"."audio_files" to "service_role";

grant delete on table "public"."current_jobs" to "anon";

grant insert on table "public"."current_jobs" to "anon";

grant references on table "public"."current_jobs" to "anon";

grant select on table "public"."current_jobs" to "anon";

grant trigger on table "public"."current_jobs" to "anon";

grant truncate on table "public"."current_jobs" to "anon";

grant update on table "public"."current_jobs" to "anon";

grant delete on table "public"."current_jobs" to "authenticated";

grant insert on table "public"."current_jobs" to "authenticated";

grant references on table "public"."current_jobs" to "authenticated";

grant select on table "public"."current_jobs" to "authenticated";

grant trigger on table "public"."current_jobs" to "authenticated";

grant truncate on table "public"."current_jobs" to "authenticated";

grant update on table "public"."current_jobs" to "authenticated";

grant delete on table "public"."current_jobs" to "service_role";

grant insert on table "public"."current_jobs" to "service_role";

grant references on table "public"."current_jobs" to "service_role";

grant select on table "public"."current_jobs" to "service_role";

grant trigger on table "public"."current_jobs" to "service_role";

grant truncate on table "public"."current_jobs" to "service_role";

grant update on table "public"."current_jobs" to "service_role";

grant delete on table "public"."draft_audio_files" to "anon";

grant insert on table "public"."draft_audio_files" to "anon";

grant references on table "public"."draft_audio_files" to "anon";

grant select on table "public"."draft_audio_files" to "anon";

grant trigger on table "public"."draft_audio_files" to "anon";

grant truncate on table "public"."draft_audio_files" to "anon";

grant update on table "public"."draft_audio_files" to "anon";

grant delete on table "public"."draft_audio_files" to "authenticated";

grant insert on table "public"."draft_audio_files" to "authenticated";

grant references on table "public"."draft_audio_files" to "authenticated";

grant select on table "public"."draft_audio_files" to "authenticated";

grant trigger on table "public"."draft_audio_files" to "authenticated";

grant truncate on table "public"."draft_audio_files" to "authenticated";

grant update on table "public"."draft_audio_files" to "authenticated";

grant delete on table "public"."draft_audio_files" to "service_role";

grant insert on table "public"."draft_audio_files" to "service_role";

grant references on table "public"."draft_audio_files" to "service_role";

grant select on table "public"."draft_audio_files" to "service_role";

grant trigger on table "public"."draft_audio_files" to "service_role";

grant truncate on table "public"."draft_audio_files" to "service_role";

grant update on table "public"."draft_audio_files" to "service_role";

grant delete on table "public"."draft_heuristics" to "anon";

grant insert on table "public"."draft_heuristics" to "anon";

grant references on table "public"."draft_heuristics" to "anon";

grant select on table "public"."draft_heuristics" to "anon";

grant trigger on table "public"."draft_heuristics" to "anon";

grant truncate on table "public"."draft_heuristics" to "anon";

grant update on table "public"."draft_heuristics" to "anon";

grant delete on table "public"."draft_heuristics" to "authenticated";

grant insert on table "public"."draft_heuristics" to "authenticated";

grant references on table "public"."draft_heuristics" to "authenticated";

grant select on table "public"."draft_heuristics" to "authenticated";

grant trigger on table "public"."draft_heuristics" to "authenticated";

grant truncate on table "public"."draft_heuristics" to "authenticated";

grant update on table "public"."draft_heuristics" to "authenticated";

grant delete on table "public"."draft_heuristics" to "service_role";

grant insert on table "public"."draft_heuristics" to "service_role";

grant references on table "public"."draft_heuristics" to "service_role";

grant select on table "public"."draft_heuristics" to "service_role";

grant trigger on table "public"."draft_heuristics" to "service_role";

grant truncate on table "public"."draft_heuristics" to "service_role";

grant update on table "public"."draft_heuristics" to "service_role";

grant delete on table "public"."draft_prompt_versions" to "anon";

grant insert on table "public"."draft_prompt_versions" to "anon";

grant references on table "public"."draft_prompt_versions" to "anon";

grant select on table "public"."draft_prompt_versions" to "anon";

grant trigger on table "public"."draft_prompt_versions" to "anon";

grant truncate on table "public"."draft_prompt_versions" to "anon";

grant update on table "public"."draft_prompt_versions" to "anon";

grant delete on table "public"."draft_prompt_versions" to "authenticated";

grant insert on table "public"."draft_prompt_versions" to "authenticated";

grant references on table "public"."draft_prompt_versions" to "authenticated";

grant select on table "public"."draft_prompt_versions" to "authenticated";

grant trigger on table "public"."draft_prompt_versions" to "authenticated";

grant truncate on table "public"."draft_prompt_versions" to "authenticated";

grant update on table "public"."draft_prompt_versions" to "authenticated";

grant delete on table "public"."draft_prompt_versions" to "service_role";

grant insert on table "public"."draft_prompt_versions" to "service_role";

grant references on table "public"."draft_prompt_versions" to "service_role";

grant select on table "public"."draft_prompt_versions" to "service_role";

grant trigger on table "public"."draft_prompt_versions" to "service_role";

grant truncate on table "public"."draft_prompt_versions" to "service_role";

grant update on table "public"."draft_prompt_versions" to "service_role";

grant delete on table "public"."draft_snippets" to "anon";

grant insert on table "public"."draft_snippets" to "anon";

grant references on table "public"."draft_snippets" to "anon";

grant select on table "public"."draft_snippets" to "anon";

grant trigger on table "public"."draft_snippets" to "anon";

grant truncate on table "public"."draft_snippets" to "anon";

grant update on table "public"."draft_snippets" to "anon";

grant delete on table "public"."draft_snippets" to "authenticated";

grant insert on table "public"."draft_snippets" to "authenticated";

grant references on table "public"."draft_snippets" to "authenticated";

grant select on table "public"."draft_snippets" to "authenticated";

grant trigger on table "public"."draft_snippets" to "authenticated";

grant truncate on table "public"."draft_snippets" to "authenticated";

grant update on table "public"."draft_snippets" to "authenticated";

grant delete on table "public"."draft_snippets" to "service_role";

grant insert on table "public"."draft_snippets" to "service_role";

grant references on table "public"."draft_snippets" to "service_role";

grant select on table "public"."draft_snippets" to "service_role";

grant trigger on table "public"."draft_snippets" to "service_role";

grant truncate on table "public"."draft_snippets" to "service_role";

grant update on table "public"."draft_snippets" to "service_role";

grant delete on table "public"."draft_user_feedback" to "anon";

grant insert on table "public"."draft_user_feedback" to "anon";

grant references on table "public"."draft_user_feedback" to "anon";

grant select on table "public"."draft_user_feedback" to "anon";

grant trigger on table "public"."draft_user_feedback" to "anon";

grant truncate on table "public"."draft_user_feedback" to "anon";

grant update on table "public"."draft_user_feedback" to "anon";

grant delete on table "public"."draft_user_feedback" to "authenticated";

grant insert on table "public"."draft_user_feedback" to "authenticated";

grant references on table "public"."draft_user_feedback" to "authenticated";

grant select on table "public"."draft_user_feedback" to "authenticated";

grant trigger on table "public"."draft_user_feedback" to "authenticated";

grant truncate on table "public"."draft_user_feedback" to "authenticated";

grant update on table "public"."draft_user_feedback" to "authenticated";

grant delete on table "public"."draft_user_feedback" to "service_role";

grant insert on table "public"."draft_user_feedback" to "service_role";

grant references on table "public"."draft_user_feedback" to "service_role";

grant select on table "public"."draft_user_feedback" to "service_role";

grant trigger on table "public"."draft_user_feedback" to "service_role";

grant truncate on table "public"."draft_user_feedback" to "service_role";

grant update on table "public"."draft_user_feedback" to "service_role";

grant delete on table "public"."draft_users" to "anon";

grant insert on table "public"."draft_users" to "anon";

grant references on table "public"."draft_users" to "anon";

grant select on table "public"."draft_users" to "anon";

grant trigger on table "public"."draft_users" to "anon";

grant truncate on table "public"."draft_users" to "anon";

grant update on table "public"."draft_users" to "anon";

grant delete on table "public"."draft_users" to "authenticated";

grant insert on table "public"."draft_users" to "authenticated";

grant references on table "public"."draft_users" to "authenticated";

grant select on table "public"."draft_users" to "authenticated";

grant trigger on table "public"."draft_users" to "authenticated";

grant truncate on table "public"."draft_users" to "authenticated";

grant update on table "public"."draft_users" to "authenticated";

grant delete on table "public"."draft_users" to "service_role";

grant insert on table "public"."draft_users" to "service_role";

grant references on table "public"."draft_users" to "service_role";

grant select on table "public"."draft_users" to "service_role";

grant trigger on table "public"."draft_users" to "service_role";

grant truncate on table "public"."draft_users" to "service_role";

grant update on table "public"."draft_users" to "service_role";

grant delete on table "public"."job_queue" to "anon";

grant insert on table "public"."job_queue" to "anon";

grant references on table "public"."job_queue" to "anon";

grant select on table "public"."job_queue" to "anon";

grant trigger on table "public"."job_queue" to "anon";

grant truncate on table "public"."job_queue" to "anon";

grant update on table "public"."job_queue" to "anon";

grant delete on table "public"."job_queue" to "authenticated";

grant insert on table "public"."job_queue" to "authenticated";

grant references on table "public"."job_queue" to "authenticated";

grant select on table "public"."job_queue" to "authenticated";

grant trigger on table "public"."job_queue" to "authenticated";

grant truncate on table "public"."job_queue" to "authenticated";

grant update on table "public"."job_queue" to "authenticated";

grant delete on table "public"."job_queue" to "service_role";

grant insert on table "public"."job_queue" to "service_role";

grant references on table "public"."job_queue" to "service_role";

grant select on table "public"."job_queue" to "service_role";

grant trigger on table "public"."job_queue" to "service_role";

grant truncate on table "public"."job_queue" to "service_role";

grant update on table "public"."job_queue" to "service_role";

grant delete on table "public"."label_upvotes" to "anon";

grant insert on table "public"."label_upvotes" to "anon";

grant references on table "public"."label_upvotes" to "anon";

grant select on table "public"."label_upvotes" to "anon";

grant trigger on table "public"."label_upvotes" to "anon";

grant truncate on table "public"."label_upvotes" to "anon";

grant update on table "public"."label_upvotes" to "anon";

grant delete on table "public"."label_upvotes" to "authenticated";

grant insert on table "public"."label_upvotes" to "authenticated";

grant references on table "public"."label_upvotes" to "authenticated";

grant select on table "public"."label_upvotes" to "authenticated";

grant trigger on table "public"."label_upvotes" to "authenticated";

grant truncate on table "public"."label_upvotes" to "authenticated";

grant update on table "public"."label_upvotes" to "authenticated";

grant delete on table "public"."label_upvotes" to "service_role";

grant insert on table "public"."label_upvotes" to "service_role";

grant references on table "public"."label_upvotes" to "service_role";

grant select on table "public"."label_upvotes" to "service_role";

grant trigger on table "public"."label_upvotes" to "service_role";

grant truncate on table "public"."label_upvotes" to "service_role";

grant update on table "public"."label_upvotes" to "service_role";

grant delete on table "public"."labels" to "anon";

grant insert on table "public"."labels" to "anon";

grant references on table "public"."labels" to "anon";

grant select on table "public"."labels" to "anon";

grant trigger on table "public"."labels" to "anon";

grant truncate on table "public"."labels" to "anon";

grant update on table "public"."labels" to "anon";

grant delete on table "public"."labels" to "authenticated";

grant insert on table "public"."labels" to "authenticated";

grant references on table "public"."labels" to "authenticated";

grant select on table "public"."labels" to "authenticated";

grant trigger on table "public"."labels" to "authenticated";

grant truncate on table "public"."labels" to "authenticated";

grant update on table "public"."labels" to "authenticated";

grant delete on table "public"."labels" to "service_role";

grant insert on table "public"."labels" to "service_role";

grant references on table "public"."labels" to "service_role";

grant select on table "public"."labels" to "service_role";

grant trigger on table "public"."labels" to "service_role";

grant truncate on table "public"."labels" to "service_role";

grant update on table "public"."labels" to "service_role";

grant delete on table "public"."profiles" to "anon";

grant insert on table "public"."profiles" to "anon";

grant references on table "public"."profiles" to "anon";

grant select on table "public"."profiles" to "anon";

grant trigger on table "public"."profiles" to "anon";

grant truncate on table "public"."profiles" to "anon";

grant update on table "public"."profiles" to "anon";

grant delete on table "public"."profiles" to "authenticated";

grant insert on table "public"."profiles" to "authenticated";

grant references on table "public"."profiles" to "authenticated";

grant select on table "public"."profiles" to "authenticated";

grant trigger on table "public"."profiles" to "authenticated";

grant truncate on table "public"."profiles" to "authenticated";

grant update on table "public"."profiles" to "authenticated";

grant delete on table "public"."profiles" to "service_role";

grant insert on table "public"."profiles" to "service_role";

grant references on table "public"."profiles" to "service_role";

grant select on table "public"."profiles" to "service_role";

grant trigger on table "public"."profiles" to "service_role";

grant truncate on table "public"."profiles" to "service_role";

grant update on table "public"."profiles" to "service_role";

grant delete on table "public"."snippet_labels" to "anon";

grant insert on table "public"."snippet_labels" to "anon";

grant references on table "public"."snippet_labels" to "anon";

grant select on table "public"."snippet_labels" to "anon";

grant trigger on table "public"."snippet_labels" to "anon";

grant truncate on table "public"."snippet_labels" to "anon";

grant update on table "public"."snippet_labels" to "anon";

grant delete on table "public"."snippet_labels" to "authenticated";

grant insert on table "public"."snippet_labels" to "authenticated";

grant references on table "public"."snippet_labels" to "authenticated";

grant select on table "public"."snippet_labels" to "authenticated";

grant trigger on table "public"."snippet_labels" to "authenticated";

grant truncate on table "public"."snippet_labels" to "authenticated";

grant update on table "public"."snippet_labels" to "authenticated";

grant delete on table "public"."snippet_labels" to "service_role";

grant insert on table "public"."snippet_labels" to "service_role";

grant references on table "public"."snippet_labels" to "service_role";

grant select on table "public"."snippet_labels" to "service_role";

grant trigger on table "public"."snippet_labels" to "service_role";

grant truncate on table "public"."snippet_labels" to "service_role";

grant update on table "public"."snippet_labels" to "service_role";

grant delete on table "public"."snippets" to "anon";

grant insert on table "public"."snippets" to "anon";

grant references on table "public"."snippets" to "anon";

grant select on table "public"."snippets" to "anon";

grant trigger on table "public"."snippets" to "anon";

grant truncate on table "public"."snippets" to "anon";

grant update on table "public"."snippets" to "anon";

grant delete on table "public"."snippets" to "authenticated";

grant insert on table "public"."snippets" to "authenticated";

grant references on table "public"."snippets" to "authenticated";

grant select on table "public"."snippets" to "authenticated";

grant trigger on table "public"."snippets" to "authenticated";

grant truncate on table "public"."snippets" to "authenticated";

grant update on table "public"."snippets" to "authenticated";

grant delete on table "public"."snippets" to "service_role";

grant insert on table "public"."snippets" to "service_role";

grant references on table "public"."snippets" to "service_role";

grant select on table "public"."snippets" to "service_role";

grant trigger on table "public"."snippets" to "service_role";

grant truncate on table "public"."snippets" to "service_role";

grant update on table "public"."snippets" to "service_role";

grant delete on table "public"."stage_1_llm_responses" to "anon";

grant insert on table "public"."stage_1_llm_responses" to "anon";

grant references on table "public"."stage_1_llm_responses" to "anon";

grant select on table "public"."stage_1_llm_responses" to "anon";

grant trigger on table "public"."stage_1_llm_responses" to "anon";

grant truncate on table "public"."stage_1_llm_responses" to "anon";

grant update on table "public"."stage_1_llm_responses" to "anon";

grant delete on table "public"."stage_1_llm_responses" to "authenticated";

grant insert on table "public"."stage_1_llm_responses" to "authenticated";

grant references on table "public"."stage_1_llm_responses" to "authenticated";

grant select on table "public"."stage_1_llm_responses" to "authenticated";

grant trigger on table "public"."stage_1_llm_responses" to "authenticated";

grant truncate on table "public"."stage_1_llm_responses" to "authenticated";

grant update on table "public"."stage_1_llm_responses" to "authenticated";

grant delete on table "public"."stage_1_llm_responses" to "service_role";

grant insert on table "public"."stage_1_llm_responses" to "service_role";

grant references on table "public"."stage_1_llm_responses" to "service_role";

grant select on table "public"."stage_1_llm_responses" to "service_role";

grant trigger on table "public"."stage_1_llm_responses" to "service_role";

grant truncate on table "public"."stage_1_llm_responses" to "service_role";

grant update on table "public"."stage_1_llm_responses" to "service_role";

grant delete on table "public"."user_star_snippets" to "anon";

grant insert on table "public"."user_star_snippets" to "anon";

grant references on table "public"."user_star_snippets" to "anon";

grant select on table "public"."user_star_snippets" to "anon";

grant trigger on table "public"."user_star_snippets" to "anon";

grant truncate on table "public"."user_star_snippets" to "anon";

grant update on table "public"."user_star_snippets" to "anon";

grant delete on table "public"."user_star_snippets" to "authenticated";

grant insert on table "public"."user_star_snippets" to "authenticated";

grant references on table "public"."user_star_snippets" to "authenticated";

grant select on table "public"."user_star_snippets" to "authenticated";

grant trigger on table "public"."user_star_snippets" to "authenticated";

grant truncate on table "public"."user_star_snippets" to "authenticated";

grant update on table "public"."user_star_snippets" to "authenticated";

grant delete on table "public"."user_star_snippets" to "service_role";

grant insert on table "public"."user_star_snippets" to "service_role";

grant references on table "public"."user_star_snippets" to "service_role";

grant select on table "public"."user_star_snippets" to "service_role";

grant trigger on table "public"."user_star_snippets" to "service_role";

grant truncate on table "public"."user_star_snippets" to "service_role";

grant update on table "public"."user_star_snippets" to "service_role";

grant delete on table "public"."workers" to "anon";

grant insert on table "public"."workers" to "anon";

grant references on table "public"."workers" to "anon";

grant select on table "public"."workers" to "anon";

grant trigger on table "public"."workers" to "anon";

grant truncate on table "public"."workers" to "anon";

grant update on table "public"."workers" to "anon";

grant delete on table "public"."workers" to "authenticated";

grant insert on table "public"."workers" to "authenticated";

grant references on table "public"."workers" to "authenticated";

grant select on table "public"."workers" to "authenticated";

grant trigger on table "public"."workers" to "authenticated";

grant truncate on table "public"."workers" to "authenticated";

grant update on table "public"."workers" to "authenticated";

grant delete on table "public"."workers" to "service_role";

grant insert on table "public"."workers" to "service_role";

grant references on table "public"."workers" to "service_role";

grant select on table "public"."workers" to "service_role";

grant trigger on table "public"."workers" to "service_role";

grant truncate on table "public"."workers" to "service_role";

grant update on table "public"."workers" to "service_role";

create policy "Enable read access for authenticated users only"
on "public"."audio_files"
as permissive
for select
to authenticated
using (true);


create policy "Enable read access for authenticated users only"
on "public"."label_upvotes"
as permissive
for select
to authenticated
using (true);


create policy "Enable read access for authenticated users only"
on "public"."labels"
as permissive
for select
to authenticated
using (true);


create policy "Enable read access for authenticated users only"
on "public"."snippet_labels"
as permissive
for select
to authenticated
using (true);


create policy "Enable read access for authenticated users only"
on "public"."snippets"
as permissive
for select
to authenticated
using (true);


CREATE TRIGGER audio_files_handle_updated_at BEFORE UPDATE ON public.audio_files FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');

CREATE TRIGGER draft_heuristics_update_timestamp BEFORE UPDATE ON public.draft_heuristics FOR EACH ROW EXECUTE FUNCTION draft_update_timestamp();

CREATE TRIGGER draft_prompt_versions_update_timestamp BEFORE UPDATE ON public.draft_prompt_versions FOR EACH ROW EXECUTE FUNCTION draft_update_timestamp();

CREATE TRIGGER draft_snippets_update_timestamp BEFORE UPDATE ON public.draft_snippets FOR EACH ROW EXECUTE FUNCTION draft_update_timestamp();

CREATE TRIGGER draft_user_feedback_update_timestamp BEFORE UPDATE ON public.draft_user_feedback FOR EACH ROW EXECUTE FUNCTION draft_update_timestamp();

CREATE TRIGGER draft_users_update_timestamp BEFORE UPDATE ON public.draft_users FOR EACH ROW EXECUTE FUNCTION draft_update_timestamp();

CREATE TRIGGER process_job_trigger AFTER INSERT ON public.job_queue FOR EACH ROW EXECUTE FUNCTION process_job();

CREATE TRIGGER label_upvotes_handle_updated_at BEFORE UPDATE ON public.label_upvotes FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');

CREATE TRIGGER labels_handle_updated_at BEFORE UPDATE ON public.labels FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');

CREATE TRIGGER snippet_labels_handle_updated_at BEFORE UPDATE ON public.snippet_labels FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');

CREATE TRIGGER snippets_handle_updated_at BEFORE UPDATE ON public.snippets FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');

CREATE TRIGGER stage_1_llm_responses_handle_updated_at BEFORE UPDATE ON public.stage_1_llm_responses FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');

CREATE TRIGGER user_star_snippets_handle_updated_at BEFORE UPDATE ON public.user_star_snippets FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');


