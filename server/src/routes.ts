import { Express } from 'express';
import { liveblocksAuth } from './api/liveblocksAuth';
import { getUsersByEmails, searchUsers } from './api/users';

export const setupRoutes = (app: Express) => {
    app.post('/api/liveblocks-auth', liveblocksAuth);
    app.post('/api/users-by-emails', getUsersByEmails);

    app.get('/', (req, res) => {
        res.send('Hello, TypeScript with Express!');
    });

    app.get('/api/search-users', searchUsers);
};
