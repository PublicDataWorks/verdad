CREATE
OR REPLACE FUNCTION get_welcome_card (p_language TEXT) RETURNS jsonb SECURITY DEFINER AS $$ 
DECLARE 
    current_user_id UUID; 
    card_data JSONB;
    actual_lang VARCHAR(5);
    lang_code VARCHAR(5);
BEGIN 
    -- Check if the user is authenticated 
    current_user_id := auth.uid(); 
    IF current_user_id IS NULL THEN 
        RAISE EXCEPTION 'Only logged-in users can call this function'; 
    END IF; 

  lang_code := CASE LOWER(p_language)
    WHEN 'english' THEN 'en'
    WHEN 'spanish' THEN 'es'
    WHEN 'french' THEN 'fr'
    ELSE NULL
  END;

  -- First try to get the requested language
  SELECT language_code
  INTO actual_lang
  FROM welcome_card
  WHERE language_code = lang_code
  LIMIT 1;
  
  -- If not found, use default language
  IF actual_lang IS NULL THEN
    SELECT language_code
    INTO actual_lang
    FROM welcome_card
    WHERE language_code = 'en'
    LIMIT 1;
  END IF;
  
  SELECT JSONB_BUILD_OBJECT(
    'id', id,
    'language', language_code,
    'title', title,
    'subtitle', subtitle,
    'features', features,
    'footer_text', footer_text,
    'contact_email', contact_email,
    'contact_text', contact_text
  )
  INTO card_data
  FROM welcome_card
  WHERE language_code = actual_lang
  LIMIT 1;
  
  RETURN card_data;
END;
$$ LANGUAGE plpgsql;
