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

export async function getMentionNotificationTemplate() {
    const template = await getEmailTemplate('mention_notification');
    if (!template) {
        return null;
    }

    return template
        .replace('{{subject}}', 'You have been @mentioned in a comment on VERDAD.app')
        .replace('{{commentBody}}', '{{commentBody}}')
        .replace('{{link}}', 'https://verdad.app/snippet/{{roomId}}');
}
