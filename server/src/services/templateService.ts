import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
    process.env.SUPABASE_URL as string,
    process.env.SUPABASE_SERVICE_ROLE_KEY as string
);

export async function getEmailTemplate(templateName: string) {
    const { data, error } = await supabase
        .from('email_template')
        .select('template_content')
        .eq('template_name', templateName)
        .single();

    if (error) {
        console.error('Error fetching email template:', error);
        return null;
    }

    return data?.template_content;
}
