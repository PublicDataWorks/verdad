import { Request, Response, NextFunction } from 'express';
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
    process.env.SUPABASE_URL as string,
    process.env.SUPABASE_SERVICE_ROLE_KEY as string
);

interface UserData {
    name: string;
    email: string;
    avatar_url: string;
}

export const getUsersByEmails = async (req: Request, res: Response, next: NextFunction): Promise<void> => {
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

        const { userIds } = req.body;

        if (!Array.isArray(userIds) || userIds.length === 0) {
            res.status(400).json({ error: 'Invalid or empty userIds array' });
            return;
        }

        const { data, error: supabaseError } = await supabase
            .from('profiles')
            .select('name, email, avatar_url')
            .in('email', userIds);

        if (supabaseError) {
            throw supabaseError;
        }
        const emptyUser = { name: "", email: "", avatar: "" };

        // Sort the data to match the order of input userIds
        const sortedData = userIds.map(userId => {
            const user = data.find(u => u.email === userId);
            if (user) {
                return { ...user, avatar: user.avatar_url };
            }
            return { ...emptyUser, email: userId };
        });

        res.status(200).json(sortedData);
    } catch (error) {
        next(error);
    }
};

export const searchUsers = async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
        const authHeader = req.headers.authorization;
        if (!authHeader) {
            res.status(401).json({ error: 'No authorization header' });
            return;
        }

        const token = authHeader.split(' ')[1];

        const { data: { user }, error } = await supabase.auth.getUser(token);

        if (error || !user) {
            res.status(401).json({ error: 'Invalid token' });
            return;
        }

        const { text } = req.query;

        let query = supabase
            .from('profiles')
            .select('email');

        if (text && typeof text === 'string') {
            query = query.or(`name.ilike.%${text}%,email.ilike.%${text}%`);
        }

        const { data, error: supabaseError } = await query;

        if (supabaseError) {
            throw supabaseError;
        }

        const emails = data.map(profile => profile.email);

        res.status(200).json(emails);
    } catch (error) {
        next(error);
    }
};
