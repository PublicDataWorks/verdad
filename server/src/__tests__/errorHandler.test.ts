import { NextFunction, Request, Response } from 'express';
import { describe, expect, it, vi } from 'vitest';

import { internalErrorHandler } from '../errorHandler';

describe('internalErrorHandler', () => {
    it('answers 500 with a fixed body, never the error message or stack', () => {
        const res = { status: vi.fn(), json: vi.fn() };
        res.status.mockReturnValue(res);
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
        const err = new Error('Failed to look up snippet: connection refused');

        internalErrorHandler(err, {} as Request, res as unknown as Response, vi.fn() as unknown as NextFunction);

        expect(res.status).toHaveBeenCalledWith(500);
        expect(res.json).toHaveBeenCalledWith({ error: 'Internal error' });
        expect(JSON.stringify(res.json.mock.calls)).not.toContain('connection refused');
        expect(consoleError).toHaveBeenCalledWith(err);
        consoleError.mockRestore();
    });
});
