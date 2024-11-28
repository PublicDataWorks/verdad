import { Request, Response, NextFunction } from 'express';
import { Liveblocks, WebhookHandler, stringifyCommentBody } from '@liveblocks/node';
import { sendEmail } from '../services/emailService';
import {
    handleCommentCreated,
    handleCommentEdited,
    handleCommentDeleted,
    handleReactionAdded,
    handleReactionRemoved,
    getCommentContent
} from '../services/commentService';
import { getEmailTemplate } from '../services/templateService';
import { sendSlackNotification } from '../services/slackService';

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
                console.log('📝 Processing comment creation:', event.data);

                const commentContent = await handleCommentCreated(event.data);
                await sendSlackNotification({
                    type: 'comment',
                    actor: event.data.createdBy,
                    roomId: event.data.roomId,
                    content: commentContent
                });
                break;
            case "commentEdited":
                console.log('✏️ Processing comment edit:', event.data);

                const oldComment = await getCommentContent(event.data.commentId);
                
                const comment = await liveblocks.getComment({
                    roomId: event.data.roomId,
                    threadId: event.data.threadId,
                    commentId: event.data.commentId
                });
                
                if (!comment.body) {
                    console.error('Comment body is undefined');
                    break;
                }
                
                const editedContent = await stringifyCommentBody(comment.body);
                
                await handleCommentEdited({
                    roomId: event.data.roomId,
                    threadId: event.data.threadId,
                    commentId: event.data.commentId,
                    editedAt: event.data.editedAt
                });
                
                await sendSlackNotification({
                    type: 'edit',
                    actor: comment.userId || 'A user',
                    roomId: event.data.roomId,
                    content: oldComment?.body || '',
                    editedContent: editedContent
                });
                break;
            case "commentDeleted":
                console.log('🗑️ Processing comment deletion:', event.data);

                await handleCommentDeleted(event.data);
                await sendSlackNotification({
                    type: 'delete',
                    actor: 'A user',
                    roomId: event.data.roomId,
                    commentId: event.data.commentId
                });
                break;
            case "commentReactionAdded":
                console.log('👍 Processing reaction addition:', event.data);
                await handleReactionAdded(event.data);
                break;

            case "commentReactionRemoved":
                console.log('👎 Processing reaction removal:', event.data);
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
                            notificationMessage = "You have been @mentioned in a comment on VERDAD.app";
                            templateName = 'mention_notification';
                            await sendSlackNotification({
                                type: 'mention',
                                actor: inboxNotification.createdBy || 'A user',
                                roomId,
                                mentionedUsers: [userId]
                            });
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
                        .replace('{{commentBody}}', 'body' in inboxNotification ? inboxNotification.body : '')
                        .replace('{{link}}', `https://verdad.app/snippet/${roomId}`)
                    : `<!DOCTYPE html><html><body><p>${notificationMessage}</p></body></html>`;

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
