import { NextFunction, Request, Response } from 'express';

// Express's default handler echoes err.stack unless NODE_ENV=production, which this app never sets.
export const internalErrorHandler = (err: Error, _req: Request, res: Response, _next: NextFunction): void => {
    console.error(err);
    res.status(500).json({ error: 'Internal error' });
};
