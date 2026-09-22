import { NextFunction, Request, Response } from 'express';
import { Mock, beforeEach, describe, expect, it, vi } from 'vitest';

// Both SDKs are constructed at module load from process.env, so they are replaced before the module
// under test is imported. Nothing here reaches the network or needs real credentials.
const mocks = vi.hoisted(() => ({
    getUser: vi.fn(),
    from: vi.fn(),
    prepareSession: vi.fn(),
}));

vi.mock('@liveblocks/node', () => ({
    Liveblocks: class {
        prepareSession = mocks.prepareSession;
    },
}));

vi.mock('@supabase/supabase-js', () => ({
    createClient: () => ({
        auth: { getUser: mocks.getUser },
        from: mocks.from,
    }),
}));

import { liveblocksAuth, resolveRoomGrants } from '../liveblocksAuth';

const FULL_ACCESS = ['room:write', 'comments:write'];
const SNIPPET_ROOM = '11111111-2222-4333-8444-555555555555';
const USER = { id: 'user-uuid', email: 'reporter@example.com', user_metadata: {} };

type QueryResult = { data: unknown; error: { message: string } | null };

/** Minimal stand-in for the PostgREST builder: every filter returns itself, `maybeSingle` resolves. */
const queryChain = (table: string, result: QueryResult): Record<string, unknown> => {
    const chain: Record<string, unknown> = {};
    for (const method of ['select', 'limit']) {
        chain[method] = () => chain;
    }
    chain.eq = (column: string, value: unknown) => {
        eqCalls.push([table, column, value]);
        return chain;
    };
    chain.maybeSingle = () => Promise.resolve(result);
    return chain;
};

/** Every `.eq(column, value)` filter applied, as [table, column, value]. */
let eqCalls: [string, string, unknown][];

let adminRow: QueryResult;
let snippetRow: QueryResult;

const makeSession = () => ({
    FULL_ACCESS,
    allow: vi.fn(),
    authorize: vi.fn().mockResolvedValue({ status: 200, body: '{"token":"fake-token"}' }),
});

type MockRes = Response & { status: Mock; json: Mock; send: Mock };

const makeRes = (): MockRes => {
    const res: Record<string, Mock> = {};
    res.status = vi.fn(() => res);
    res.json = vi.fn(() => res);
    res.send = vi.fn(() => res);
    return res as unknown as MockRes;
};

// `authorization: null` means "send no Authorization header at all".
const makeReq = (body: unknown, authorization: string | null = 'Bearer supabase-token') =>
    ({ headers: authorization === null ? {} : { authorization }, body }) as unknown as Request;

const callHandler = async (req: Request): Promise<{ res: MockRes; next: Mock }> => {
    const res = makeRes();
    const next: Mock = vi.fn();
    await liveblocksAuth(req, res, next as unknown as NextFunction);
    return { res, next };
};

beforeEach(() => {
    vi.clearAllMocks();
    adminRow = { data: null, error: null };
    snippetRow = { data: { id: SNIPPET_ROOM }, error: null };
    mocks.getUser.mockResolvedValue({ data: { user: USER }, error: null });
    eqCalls = [];
    mocks.from.mockImplementation((table: string) =>
        queryChain(table, table === 'user_roles' ? adminRow : snippetRow)
    );
    mocks.prepareSession.mockImplementation(() => makeSession());
});

describe('resolveRoomGrants', () => {
    it('gives admins the wildcard without looking up a snippet', async () => {
        const snippetVisible = vi.fn();

        await expect(
            resolveRoomGrants({ room: SNIPPET_ROOM, isAdmin: true, snippetVisible })
        ).resolves.toEqual({ type: 'grant', rooms: ['*'] });
        expect(snippetVisible).not.toHaveBeenCalled();
    });

    it('grants no rooms when the body has no room (inbox token)', async () => {
        const snippetVisible = vi.fn();

        await expect(
            resolveRoomGrants({ room: undefined, isAdmin: false, snippetVisible })
        ).resolves.toEqual({ type: 'grant', rooms: [] });
        expect(snippetVisible).not.toHaveBeenCalled();
    });

    it('grants exactly the requested room when the snippet exists', async () => {
        const snippetVisible = vi.fn().mockResolvedValue(true);

        await expect(
            resolveRoomGrants({ room: SNIPPET_ROOM, isAdmin: false, snippetVisible })
        ).resolves.toEqual({ type: 'grant', rooms: [SNIPPET_ROOM] });
        expect(snippetVisible).toHaveBeenCalledWith(SNIPPET_ROOM);
    });

    it.each([
        ['a wildcard', '*'],
        ['a prefix pattern', `${SNIPPET_ROOM}*`],
        ['a non-uuid string', 'lobby'],
        ['a uuid with trailing content', `${SNIPPET_ROOM} `],
        ['an uppercase uuid (Liveblocks room ids are case-sensitive)', 'ABCDEF01-2222-4333-8444-555555555555'],
        ['a non-string', 42],
    ])('denies %s without hitting the database', async (_label, room) => {
        const snippetVisible = vi.fn();

        await expect(resolveRoomGrants({ room, isAdmin: false, snippetVisible })).resolves.toEqual({
            type: 'deny',
            status: 403,
            error: 'Room not found',
        });
        expect(snippetVisible).not.toHaveBeenCalled();
    });

    it('denies a well-formed uuid that is not a snippet', async () => {
        const snippetVisible = vi.fn().mockResolvedValue(false);

        await expect(
            resolveRoomGrants({ room: SNIPPET_ROOM, isAdmin: false, snippetVisible })
        ).resolves.toEqual({ type: 'deny', status: 403, error: 'Room not found' });
    });
});

describe('liveblocksAuth', () => {
    it('allows only the requested room for a non-admin', async () => {
        const session = makeSession();
        mocks.prepareSession.mockReturnValue(session);

        const { res, next } = await callHandler(makeReq({ room: SNIPPET_ROOM }));

        expect(mocks.getUser).toHaveBeenCalledWith('supabase-token');
        expect(session.allow).toHaveBeenCalledTimes(1);
        expect(session.allow).toHaveBeenCalledWith(SNIPPET_ROOM, FULL_ACCESS);
        expect(session.authorize).toHaveBeenCalledTimes(1);
        expect(res.status).toHaveBeenCalledWith(200);
        expect(res.send).toHaveBeenCalledWith('{"token":"fake-token"}');
        expect(next).not.toHaveBeenCalled();
    });

    it('issues a token with no room permissions when the body has no room', async () => {
        const session = makeSession();
        mocks.prepareSession.mockReturnValue(session);

        const { res } = await callHandler(makeReq({}));

        expect(session.allow).not.toHaveBeenCalled();
        expect(session.authorize).toHaveBeenCalledTimes(1);
        expect(res.status).toHaveBeenCalledWith(200);
    });

    it('rejects a room that is not a uuid', async () => {
        const { res } = await callHandler(makeReq({ room: '*' }));

        expect(mocks.prepareSession).not.toHaveBeenCalled();
        expect(res.status).toHaveBeenCalledWith(403);
        expect(res.json).toHaveBeenCalledWith({ error: 'Room not found' });
    });

    it('only grants a room for a Processed snippet', async () => {
        await callHandler(makeReq({ room: SNIPPET_ROOM }));

        expect(eqCalls).toContainEqual(['snippets', 'id', SNIPPET_ROOM]);
        expect(eqCalls).toContainEqual(['snippets', 'status', 'Processed']);
    });

    it.each([
        ['an embedded hide row', { snippet: SNIPPET_ROOM }],
        ['a list of hide rows', [{ snippet: SNIPPET_ROOM }]],
    ])('rejects a hidden snippet returned with %s', async (_label, hideRows) => {
        snippetRow = { data: { id: SNIPPET_ROOM, user_hide_snippets: hideRows }, error: null };

        const { res } = await callHandler(makeReq({ room: SNIPPET_ROOM }));

        expect(mocks.prepareSession).not.toHaveBeenCalled();
        expect(res.status).toHaveBeenCalledWith(403);
        expect(res.json).toHaveBeenCalledWith({ error: 'Room not found' });
    });

    it('grants a snippet whose hide embed is an empty list', async () => {
        snippetRow = { data: { id: SNIPPET_ROOM, user_hide_snippets: [] }, error: null };
        const session = makeSession();
        mocks.prepareSession.mockReturnValue(session);

        const { res } = await callHandler(makeReq({ room: SNIPPET_ROOM }));

        expect(session.allow).toHaveBeenCalledWith(SNIPPET_ROOM, FULL_ACCESS);
        expect(res.status).toHaveBeenCalledWith(200);
    });

    it('rejects a uuid that is not a snippet', async () => {
        snippetRow = { data: null, error: null };

        const { res } = await callHandler(makeReq({ room: SNIPPET_ROOM }));

        expect(mocks.prepareSession).not.toHaveBeenCalled();
        expect(res.status).toHaveBeenCalledWith(403);
        expect(res.json).toHaveBeenCalledWith({ error: 'Room not found' });
    });

    it('gives an admin the wildcard', async () => {
        adminRow = { data: { roles: { name: 'admin' } }, error: null };
        const session = makeSession();
        mocks.prepareSession.mockReturnValue(session);

        const { res } = await callHandler(makeReq({ room: SNIPPET_ROOM }));

        expect(session.allow).toHaveBeenCalledTimes(1);
        expect(session.allow).toHaveBeenCalledWith('*', FULL_ACCESS);
        expect(res.status).toHaveBeenCalledWith(200);
    });

    it('returns 401 when the Authorization header is missing', async () => {
        const { res } = await callHandler(makeReq({ room: SNIPPET_ROOM }, null));

        expect(mocks.getUser).not.toHaveBeenCalled();
        expect(res.status).toHaveBeenCalledWith(401);
        expect(res.json).toHaveBeenCalledWith({ error: 'No authorization header' });
    });

    it('returns 401 when Supabase rejects the token', async () => {
        mocks.getUser.mockResolvedValue({ data: { user: null }, error: { message: 'bad jwt' } });

        const { res } = await callHandler(makeReq({ room: SNIPPET_ROOM }));

        expect(mocks.prepareSession).not.toHaveBeenCalled();
        expect(res.status).toHaveBeenCalledWith(401);
        expect(res.json).toHaveBeenCalledWith({ error: 'Invalid token' });
    });

    it('forwards a database failure to the error handler instead of issuing a token', async () => {
        snippetRow = { data: null, error: { message: 'connection refused' } };

        const { res, next } = await callHandler(makeReq({ room: SNIPPET_ROOM }));

        expect(mocks.prepareSession).not.toHaveBeenCalled();
        expect(res.status).not.toHaveBeenCalled();
        expect(next).toHaveBeenCalledTimes(1);
    });
});
