// index.ts
import { serve } from "https://deno.land/std@0.140.0/http/server.ts";

serve(async req => {
    const { name } = (await req.json()) || { name: "World" };
    return new Response(JSON.stringify({ message: `Hello, ${name}!` }), {
        headers: { "Content-Type": "application/json" },
    });
});
