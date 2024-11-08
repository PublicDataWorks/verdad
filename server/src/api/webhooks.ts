import { Request, Response, NextFunction } from 'express';
import { Liveblocks, WebhookHandler } from '@liveblocks/node';
import { sendEmail } from '../services/emailService';
import {
    handleCommentCreated,
    handleCommentEdited,
    handleCommentDeleted,
    handleReactionAdded,
    handleReactionRemoved
} from '../services/commentService';
import { getEmailTemplate } from '../services/templateService';

const WEBHOOK_SECRET = process.env.LIVEBLOCKS_WEBHOOK_SECRET;
if (!WEBHOOK_SECRET) {
    throw new Error("LIVEBLOCKS_WEBHOOK_SECRET environment variable is required");
}

const webhookHandler = new WebhookHandler(WEBHOOK_SECRET);

const liveblocks = new Liveblocks({
    secret: process.env.LIVEBLOCKS_SECRET_KEY as string,
});


export const handleWebhook = async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
        const rawBody = JSON.stringify(req.body);

        let event;
        try {
            event = webhookHandler.verifyRequest({
                headers: req.headers as Record<string, string>,
                rawBody: rawBody,
            });
        } catch (err) {
            console.error('Webhook verification failed:', err);
            res.status(400).json({ error: 'Could not verify webhook call' });
            return;
        }

        switch (event.type) {
            case "commentCreated":
                await handleCommentCreated(event.data);
                break;
            case "commentEdited":
                await handleCommentEdited(event.data);
                break;
            case "commentDeleted":
                await handleCommentDeleted(event.data);
                break;
            case "commentReactionAdded":
                await handleReactionAdded(event.data);
                break;
            case "commentReactionRemoved":
                await handleReactionRemoved(event.data);
                break;
            case "notification":
                const { inboxNotificationId, userId, roomId } = event.data;

                if (!userId || !roomId || !inboxNotificationId) {
                    console.error('Missing required data in webhook event');
                    res.status(400).json({ error: 'Missing required data' });
                    return;
                }

                const inboxNotification = await liveblocks.getInboxNotification({
                    inboxNotificationId,
                    userId,
                });

                let notificationMessage = 'You have a new notification';
                let templateName = 'default_notification';

                if ('kind' in inboxNotification) {
                    switch (inboxNotification.kind) {
                        case 'thread': {
                            notificationMessage = `A new thread was created in room ${roomId}`;
                            templateName = 'thread_notification';
                            break;
                        }
                        case 'textMention': {
                            notificationMessage = `You were mentioned in room ${roomId}`;
                            templateName = 'mention_notification';
                            break;
                        }
                        default: {
                            if (inboxNotification.kind.startsWith('$')) {
                                const customType = inboxNotification.kind.slice(1);
                                notificationMessage = `New ${customType} notification in room ${roomId}`;
                                templateName = `${customType}_notification`;
                            }
                            break;
                        }
                    }
                }

                const template = await getEmailTemplate(templateName);
                const emailContent = template
                    ? template
                        .replace('{{notificationMessage}}', notificationMessage)
                        .replace('{{roomId}}', roomId)
                        .replace('{{additionalContent}}', '')
                    : `
                        <h1>New Notification from Verdad</h1>
                        <p>${notificationMessage}</p>
                        <a href="https://verdad.app/snippet/${roomId}" style="display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">View in Verdad</a>
                    `;

                await sendEmail(
                    userId,
                    notificationMessage,
                    emailContent
                );
                break;
        }

        res.status(200).json({ message: 'Webhook processed successfully' });
    } catch (error) {
        console.error('Webhook processing error:', error);
        next(error);
    }
};
