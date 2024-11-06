import { Request, Response, NextFunction } from 'express';
import { Liveblocks, WebhookHandler, stringifyCommentBody } from '@liveblocks/node';
import { createClient } from "@supabase/supabase-js";
import { sendEmail } from '../services/emailService';

const WEBHOOK_SECRET = process.env.LIVEBLOCKS_WEBHOOK_SECRET;
if (!WEBHOOK_SECRET) {
    throw new Error("LIVEBLOCKS_WEBHOOK_SECRET environment variable is required");
}

const webhookHandler = new WebhookHandler(WEBHOOK_SECRET);

const liveblocks = new Liveblocks({
    secret: process.env.LIVEBLOCKS_SECRET_KEY as string,
});

const supabase = createClient(
    process.env.SUPABASE_URL as string,
    process.env.SUPABASE_SERVICE_ROLE_KEY as string
);

async function checkRoomAccess(userId: string, roomId: string): Promise<boolean> {
    try {
        const { data, error } = await supabase
            .from('room_access')  // You'll need to create this table
            .select('*')
            .eq('user_id', userId)
            .eq('room_id', roomId)
            .single();

        if (error || !data) {
            return false;
        }
        return true;
    } catch {
        return false;
    }
}

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

        if (event.type === "notification") {
            const { inboxNotificationId, userId, roomId } = event.data;

            if (!userId || !roomId || !inboxNotificationId) {
                console.error('Missing required data in webhook event');
                res.status(400).json({ error: 'Missing required data' });
                return;
            }

            // Check if user has access to the room
            const hasAccess = await checkRoomAccess(userId, roomId);
            if (!hasAccess) {
                console.log(`User ${userId} doesn't have access to room ${roomId}`);
                res.status(200).json({ message: 'User does not have access to room' });
                return;
            }

            const inboxNotification = await liveblocks.getInboxNotification({
                inboxNotificationId,
                userId,
            });

            const { data: userData, error: userError } = await supabase
                .from('profiles')
                .select('email, name')
                .eq('email', userId)
                .single();

            if (userError || !userData) {
                console.error('Error fetching user:', userError);
                res.status(404).json({ error: 'User not found' });
                return;
            }

            let notificationMessage = 'You have a new notification';
            let additionalContent = '';

            if ('kind' in inboxNotification) {
                switch (inboxNotification.kind) {
                    case 'thread': {
                        notificationMessage = `A new thread was created in room ${roomId}`;
                        break;
                    }
                    case 'textMention': {
                        notificationMessage = `You were mentioned in room ${roomId}`;
                        break;
                    }
                    default: {
                        // Handle custom notification types
                        if (inboxNotification.kind.startsWith('$')) {
                            const customType = inboxNotification.kind.slice(1); // Remove the $ prefix
                            notificationMessage = `New ${customType} notification in room ${roomId}`;
                        }
                        break;
                    }
                }
            }

            const emailContent = `
                <h1>New Notification from Verdad</h1>
                <p>${notificationMessage}</p>
                ${additionalContent}
                <a href="https://verdad.app/room/${roomId}" style="display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">View in Verdad</a>
            `;

            await sendEmail(
                userData.email,
                notificationMessage,
                emailContent
            );
        }

        res.status(200).json({ message: 'Webhook processed successfully' });
    } catch (error) {
        console.error('Webhook processing error:', error);
        next(error);
    }
};
