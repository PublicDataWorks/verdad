import {Request, Response, NextFunction} from 'express';
import { Liveblocks } from '@liveblocks/node';
import {createClient} from "@supabase/supabase-js";

const liveblocks = new Liveblocks({
    secret: process.env.LIVEBLOCKS_SECRET_KEY as string,
});

// The admin check could also be done by calling the `public.get_roles()` RPC, but that function is
// SECURITY DEFINER on `auth.uid()`, so it would need a per-request client built with the anon key and the
// caller's bearer token -- i.e. a new SUPABASE_ANON_KEY secret on this app. We read `user_roles`/`roles`
// with the service-role client instead: no new env var, and the user id is already verified by then.
const supabase = createClient(
    process.env.SUPABASE_URL as string,
    process.env.SUPABASE_SERVICE_ROLE_KEY as string
);

// Liveblocks rooms are snippet comment threads, so a room id is always a `public.snippets.id` uuid.
// Matching strictly also keeps Liveblocks room patterns (`*`, `prefix*`) out of the snippet lookup.
const ROOM_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type RoomGrants =
    | { type: 'grant'; rooms: string[] }
    | { type: 'deny'; status: number; error: string };

export interface ResolveRoomGrantsArgs {
    /** `room` as it arrived in the request body; anything but a string is rejected. */
    room: unknown;
    isAdmin: boolean;
    /** Injected so this stays testable without a database. Only called for a well-formed room id. */
    snippetExists: (roomId: string) => Promise<boolean>;
}

/**
 * Decide which rooms a token may be issued for. Every granted room gets FULL_ACCESS, because
 * Liveblocks Comments needs `comments:write` to post a comment, reply or reaction; there is no
 * narrower permission for "may comment but not edit other people's comments". @liveblocks/react-ui
 * only offers the edit/delete actions on a user's own comments (dist/components/Comment.js:461,
 * `comment.userId === currentUserId`); whether the Liveblocks API enforces that server-side is not
 * verifiable from the installed packages.
 */
export const resolveRoomGrants = async (
    {room, isAdmin, snippetExists}: ResolveRoomGrantsArgs
): Promise<RoomGrants> => {
    // Admins moderate arbitrary threads, so they keep the wildcard they have always had.
    if (isAdmin) {
        return { type: 'grant', rooms: ['*'] };
    }

    // No room in the body: the client is asking for a user-level token (inbox notifications). Issue a
    // token with no room permissions -- `Session.authorize()` allows that, it only logs a warning
    // ("Access tokens without any permission will not be supported soon ...", @liveblocks/node 2.9.0,
    // dist/index.js:164). If notifications ever come back empty, the smallest escalation is
    // `allow('*', READ_ACCESS)`, never FULL_ACCESS.
    if (room === undefined || room === null) {
        return { type: 'grant', rooms: [] };
    }

    if (typeof room !== 'string' || !ROOM_ID_PATTERN.test(room)) {
        return { type: 'deny', status: 403, error: 'Room not found' };
    }

    if (!(await snippetExists(room))) {
        return { type: 'deny', status: 403, error: 'Room not found' };
    }

    return { type: 'grant', rooms: [room] };
};

/** True when the user has the `admin` role in `public.user_roles` -> `public.roles`. */
const isAdminUser = async (userId: string): Promise<boolean> => {
    const { data, error } = await supabase
        .from('user_roles')
        .select('roles!inner(name)')
        .eq('user', userId)
        .eq('roles.name', 'admin')
        .limit(1)
        .maybeSingle();

    // Fail loudly rather than silently downgrading an admin or turning an outage into a 403.
    if (error) {
        throw new Error(`Failed to read user roles: ${error.message}`);
    }
    return data !== null;
};

const snippetExists = async (roomId: string): Promise<boolean> => {
    const { data, error } = await supabase
        .from('snippets')
        .select('id')
        .eq('id', roomId)
        .maybeSingle();

    if (error) {
        throw new Error(`Failed to look up snippet: ${error.message}`);
    }
    return data !== null;
};

export const liveblocksAuth = async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
        const authHeader = req.headers.authorization;
        if (!authHeader) {
            res.status(401).json({ error: 'No authorization header' });
            return;
        }

        const token = authHeader.split(' ')[1];

        // Verify the Supabase token
        const { data: { user }, error } = await supabase.auth.getUser(token);

        if (error || !user) {
            res.status(401).json({ error: 'Invalid token' });
            return;
        }

        const { room } = (req.body ?? {}) as { room?: unknown };
        const grants = await resolveRoomGrants({
            room,
            isAdmin: await isAdminUser(user.id),
            snippetExists,
        });

        if (grants.type === 'deny') {
            res.status(grants.status).json({ error: grants.error });
            return;
        }

        // Start an auth session inside your endpoint
        const session = liveblocks.prepareSession(
            user.email? user.email : user.id,
            { userInfo: {
                    name: user.user_metadata.name? user.user_metadata.name : user.email,
                    avatar: user.user_metadata.avatar_url? user.user_metadata.avatar_url : '',
                }},
        );

        for (const roomId of grants.rooms) {
            session.allow(roomId, session.FULL_ACCESS);
        }

        // Authorize the user and return the result
        const { status, body } = await session.authorize();
        res.status(status).send(body);
    } catch (error) {
        next(error);
    }
};
