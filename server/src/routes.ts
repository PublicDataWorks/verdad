import { Express } from 'express';
import { liveblocksAuth } from './api/liveblocksAuth';
import { handleWebhook } from './api/webhooks';

export const setupRoutes = (app: Express) => {
    app.post('/api/liveblocks-auth', liveblocksAuth);
    app.post('/api/webhooks/liveblocks', handleWebhook);

    app.get('/', (req, res) => {
        res.send('Hello, TypeScript with Express!');
    });
};
