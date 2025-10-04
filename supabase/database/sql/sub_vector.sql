CREATE OR REPLACE FUNCTION sub_vector(v extensions.vector, dimensions INT)
RETURNS extensions.vector
LANGUAGE plpgsql
IMMUTABLE
SET search_path = ''
AS $$
BEGIN
  IF dimensions > extensions.vector_dims(v) THEN
    RAISE EXCEPTION 'Dimensions must be less than or equal to the vector size';
  END IF;

  RETURN (
    WITH unnormed(elem) AS (
      SELECT x FROM unnest(v::float4[]) WITH ORDINALITY v(x, ix)
      WHERE ix <= dimensions
    ),
    norm(factor) AS (
      SELECT
        sqrt(sum(pow(elem, 2)))
      FROM
        unnormed
    )
    SELECT
      array_agg(u.elem / r.factor)::extensions.vector
    FROM
      norm r, unnormed u
  );
END;
$$;
