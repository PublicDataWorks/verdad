import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
    process.env.SUPABASE_URL as string,
    process.env.SUPABASE_SERVICE_ROLE_KEY as string
);

export async function handleCommentCreated(data: {
    projectId: string;
    roomId: string;
    threadId: string;
    commentId: string;
    createdBy: string;
}) {
    const { error } = await supabase
        .from('comments')
        .insert({
            comment_id: data.commentId,
            thread_id: data.threadId,
            room_id: data.roomId,
            project_id: data.projectId,
            created_by: data.createdBy
        });

    if (error) throw error;
}

export async function handleCommentEdited(data: {
    commentId: string;
    editedAt: string;
}) {
    const { error } = await supabase
        .from('comments')
        .update({ edited_at: data.editedAt })
        .eq('comment_id', data.commentId);

    if (error) throw error;
}

export async function handleCommentDeleted(data: {
    commentId: string;
    deletedAt: string;
}) {
    const { error } = await supabase
        .from('comments')
        .update({ deleted_at: data.deletedAt })
        .eq('comment_id', data.commentId);

    if (error) throw error;
}

export async function handleReactionAdded(data: {
    commentId: string;
    emoji: string;
    addedBy: string;
}) {
    const { error } = await supabase
        .from('comment_reactions')
        .insert({
            comment_id: data.commentId,
            emoji: data.emoji,
            user_id: data.addedBy
        });

    if (error) throw error;
}

export async function handleReactionRemoved(data: {
    commentId: string;
    emoji: string;
    removedBy: string;
}) {
    const { error } = await supabase
        .from('comment_reactions')
        .delete()
        .match({
            comment_id: data.commentId,
            emoji: data.emoji,
            user_id: data.removedBy
        });

    if (error) throw error;
}
