import { sendEmail } from './emailService';

const SLACK_NOTIFICATION_EMAIL = process.env.SLACK_NOTIFICATION_EMAIL;

type SlackNotificationParams = {
    type: 'mention' | 'comment' | 'edit' | 'delete';
    actor: string;
    roomId: string;
    mentionedUsers?: string[];
    commentId?: string;
    content?: string;
    editedContent?: string;
};

export async function sendSlackNotification(params: SlackNotificationParams) {
    if (!SLACK_NOTIFICATION_EMAIL) {
        console.warn('SLACK_NOTIFICATION_EMAIL not configured');
        return;
    }

    let subject = '';
    let content = '';

    switch (params.type) {
        case 'mention':
            subject = `🔔 Mention in Room ${params.roomId}`;
            content = `
                <p><strong>${params.actor}</strong> mentioned ${params.mentionedUsers?.join(', ')} in room ${params.roomId}</p>
            `;
            break;
        case 'comment':
            subject = `💬 New Comment in Room ${params.roomId}`;
            content = `
                <p><strong>${params.actor}</strong> added a new comment in room ${params.roomId}</p>
                <div style="margin: 10px 0; padding: 10px; background: #f5f5f5; border-radius: 4px;">
                    <p>${params.content}</p>
                </div>
            `;
            break;
        case 'edit':
            subject = `✏️ Comment Edited in Room ${params.roomId}`;
            content = `
                <p><strong>${params.actor}</strong> edited a comment in room ${params.roomId}</p>
                <div style="margin: 10px 0; padding: 10px; background: #f5f5f5; border-radius: 4px;">
                    <p><strong>Original:</strong></p>
                    <p style="color: #666;">${params.content}</p>
                    <p><strong>Edited to:</strong></p>
                    <p style="color: #000;">${params.editedContent}</p>
                </div>
            `;
            break;
        case 'delete':
            subject = `🗑️ Comment Deleted in Room ${params.roomId}`;
            content = `
                <p><strong>${params.actor}</strong> deleted a comment in room ${params.roomId}</p>
            `;
            break;
    }

    const html = `
        ${content}
        <p><a href="https://verdad.app/snippet/${params.roomId}">View in Verdad</a></p>
    `;

    try {
        await sendEmail(
            SLACK_NOTIFICATION_EMAIL,
            subject,
            html
        );
    } catch (error) {
        console.error('Error sending Slack notification:', error);
    }
}
