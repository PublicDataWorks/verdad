import {Request, Response, NextFunction} from 'express';
import { Liveblocks } from '@liveblocks/node';
import {createClient} from "@supabase/supabase-js";

const liveblocks = new Liveblocks({
    secret: process.env.LIVEBLOCKS_SECRET_KEY as string,
});

const supabase = createClient(
    process.env.SUPABASE_URL as string,
    process.env.SUPABASE_SERVICE_ROLE_KEY as string
);

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

        // Start an auth session inside your endpoint
        const session = liveblocks.prepareSession(
            user.email? user.email : user.id,
            { userInfo: {
                    name: user.user_metadata.name? user.user_metadata.name : user.email,
                    avatar: user.user_metadata.avatar_url? user.user_metadata.avatar_url : '',
                }},
        );

        // Use a naming pattern to allow access to rooms with wildcards
        // This is an example, adjust according to your needs
        session.allow(`*`, session.FULL_ACCESS);

        // Authorize the user and return the result
        const { status, body } = await session.authorize();
        res.status(status).send(body);
    } catch (error) {
        next(error);
    }
};